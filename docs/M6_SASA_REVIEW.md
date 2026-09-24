# M6 independent scientific and integration review

Reviewer: GPT-6 Astra. Implementation: GPT-6 Sol. Date: 2026-09-24. Final correction session99489 was terminal before this review. Branch: `phase/m6-interface-sasa`.

Verdict: APPROVED

The selected M6 contract is satisfied: a real, local FreeSASA protein–ligand area calculation, exact immutable input/identity mapping, actionable current/historical viewer flow, and separate evidence-bound method reports. This approval covers implementation and reviewed evidence. Parent must still bind this report to the listed source hashes through the actual step0 acceptance/review recorder. M7 OpenMM implementation and acceptance remain pending.

## Scientific method and independent measurement

The adapter uses FreeSASA2.2.1 `calcCoord`, Lee–Richards100 slices, probe1.4Å and one thread, with actual Gemmi0.7.5 element radii. It selects canonical20 protein polymer heavy atoms and exactly one full ResidueRef nonpolymer ligand. Model number, author/label chain and residue IDs, insertion code and residue name remain linked to the immutable prepared/source/preparation objects. Excluded components and hydrogen policy are explicit. The three actual calculations retain isolated/combined per-atom areas, all protein-residue rows and partner/total SASA loss in Å². No hidden half-factor, energy/affinity inference, mock area, or native-output correction was found.

Native input checks reject empty/oversize arrays, invalid or unsupported radii, nonfinite/out-of-range coordinates, ambiguous identities, unresolved altlocs and coincident centers before native execution. All three inputs use the same recorded translation. Semantic cache keys include actual scientific dependencies and fixed settings. Moderate synchronous work uses existing active wall accounting; it does not claim a hard process timeout or cancellation guarantee.

Astra independently executed the unchanged `/tmp/protview-qa/m6-astra-scientific-probe.py` after the correction. Before/after source hashes were identical. Actual public1HSG source SHA256 is `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`. Product input comprises1514 protein and45 MK1 ligand heavy atoms. All198 complete residue identities matched the separate direct-engine reference. Maximum absolute differences were4.547473508864641e-11Å² across eight summary fields and1.2313705610722536e-11Å² across every residue area field.

Measured protein burial is546.4015616674023Å², ligand burial782.7580589969108Å², and total SASA loss1329.1596206643135Å². Agreement verifies settings, selection, mapping and arithmetic; it is not a biological or affinity benchmark. The parent direct reference is `/tmp/protview-qa/m6-independent-lr-reference.json`.

The pre-implementation Shrake–Rupley1000 configuration failed independent isolated/separated-sphere checks and was rejected before approval. The approved Lee–Richards analytic checks satisfy isolated/separated absolute1e-6Å² and overlap/rotation0.5% plus1e-6Å² criteria. The old failing reference is historical evidence, not an accepted product result. No output patch or isolated-atom special case was introduced.

## Finding M6-1 resolved: saved result type validation

Initial `saved_method_report` accepted same-shaped `job_result/job_fixture@1` and `interface_sasa/interface_sasa@999` evidence when fixture report/event links were paired consistently. Creation already rejected these types, but saved reads omitted the check. These were deliberately constructed malformed typed-object fixtures, not observed corruption in normal user data. Initial reviewed method_reports SHA was `b7be99f57ffcf2b1ab7d31950c7aca684cec152023012bea003f4c9f1b3503d3`.

The correction requires result metadata `interface_sasa/interface_sasa@1` and payload schema `interface_sasa@1` before source/claim use. The original independent probe now rejects both metadata fixtures with `EvidenceError:wrong_result_kind`. Added paired regressions also reject payload-schema mismatch, while forbidding native calls and current-dependency lookup in saved reads. Corrected method_reports SHA is `ea2b709b56ce0bcafbf03cf070617fe4122e534575afdd0a86cb066ed19dbb13`. No unresolved blocking finding remains.

Creation validates exact source kinds/schemas, geometry and full selection, unique atom/row identities, integer counts, finite areas and aggregate identities. Claims bind result handle/schema/hash, named field/row fingerprint/full subject, quantity, unit and exact/rendered values. Wrong units, subjects, fields, row identity and rendered values fail closed. Saved reads retain exact bytes without remeasuring or requiring current engine initialization. Independent deletion of source, object directory and index restored the exact method artifact with FreeSASA forbidden and zero appended events.

## Tests and actual browser evidence

Parent final host evidence `/tmp/protview-qa/m6-final-host-evidence.json` records251 passed,0 skipped in21.01s across backend and harness tests, plus full Ruff PASS, on terminal corrected sources. The correction's targeted acceptance tests were58 passed. Astra independently ran corrected `test_sasa.py`:11 passed in1.52s. Parent independently ran11 frontend tests; unchanged frontend typecheck and production build passed in the implementation gate. Sandbox process-enumeration skips in earlier Sol runs are not counted as host acceptance.

Parent's completed actual-browser evidence `/tmp/protview-qa/m6-final-browser-evidence.json` covers real1HSG native calculation, full1559-atom/198-residue JSON, all-row Markdown, preview/download equality and actual ASP authA25/labelA25/model1 focus. Reload preserves the exact report with53 events before and after, no new calculation, and the old M5 geometry artifact remains identical. Corrected backend restart also preserves both saved formats. Astra inspected the evidence and `m6-browser-sasa-report.png`, showing the molecular scene, matching highlighted ASP identity and saved method report.

Explicit synthetic history fixtures retain separate A115.48055260029452Å² and B0Å² reports and their exact input structures. A held B200 response released after selecting A does not replace A. Injected503 shows a report error without a preview, retains the measured A result, and retry restores the exact artifact. These are lifecycle/UI fixtures, not additional experimental validation. No nonloopback request or page error was observed. No OpenRouter request was made for M6.

## Explicit extension supersession and remaining scope

M0–M5 were accepted and verified on the honest baseline commit `d22fe15` on master; those historical records are preserved. There were no per-phase Git branches for that earlier work. M6 is a real subsequent branch. This review explicitly supersedes the changed shared-source coverage for the M6 branch through the exact file list below, direct diff review, full host regressions and actual old/new browser/report continuity. It does not claim that historical `protview-mvp --verify` hashes remain fresh on this branch, and does not rewrite old MVP records.

Baseline continuity was checked: core object/event/residue implementation, job supervision, old reports/workflows, external-model gate, harness and hook configuration have no diff from `d22fe15`. The orchestrator change adds scientific dependencies only to the SASA key. Changed API/workspace/registry/frontend paths are reviewed for existing command, cache observation, source lineage, saved-report discriminator and error/retry behavior. Full host tests cover the existing runtime/job/harness boundaries, and actual browser reads preserve old report bytes. Harness security/pins were not changed. No original reference/archive or credential file was edited by the reviewer.

SASA remains probe/radius/resolution-dependent selected-partner geometry. Rosetta protocols remain separately unavailable. OpenMM protein-only minimization is selected for M7 but is not implemented or approved by this review. Parent owns actual phase recording and commits; the phase index is authoritative for recorded completion. Only the named current extension phase group may be claimed as freshly verified after its actual gate runs.

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
