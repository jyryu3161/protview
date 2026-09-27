# M10 atom measurement and rigid comparison — implementation review

Reviewer: GPT-6 Astra. Implementation and offscreen harness: GPT-6 Sol. Date: 2026-09-27. Accepted predecessor: `479d961`. Final actual renderer build: `cjYPdV6dj3ZdSKSJLhpz2` (eleventh).

## Verdict

Verdict: APPROVED

No blocking finding remains for the selected M10 contract. This approves the reviewed implementation and evidence for recording. The parent must still execute the eight exact acceptance commands, record the hash-bound review and pass `--verify`. This report does not predeclare those command results, phase completion, commit or merge. M11–M13 remain subsequent authorized work outside this approval.

## Scientific and source-identity review

Distance uses two complete immutable same-run AtomRefs and original coordinates in ångströms, including distinct coincident sites. Native atom selection is restricted to a single atomic locus; bond, ambiguous and cross-source selections are not guessed. Model number, author and label identifiers, insertion code, alternate location and immutable traversal site remain explicit. Exact served-byte SHA and complete native row mapping guard original PDB/mmCIF, prepared and minimized display sources. Original selected serialization is verified against the pinned Gemmi traversal/emission provenance; unchanged coordinate sources use validated raw-row identity. Identical ambiguous original sites fail closed. The shared bidirectional residue adapter reconstructs all seven authoritative residue fields and all matching sites, rather than weakening label equality when native PDB `A` differs from authoritative `Axp`.

Rigid fitting uses the normal guarded Run.call lane, explicit 3–1000 protein CA correspondences, unweighted float64 Kabsch with a proper rotation, finite-value checks and stated rank/degeneracy tolerances. There is no inferred correspondence, reflection-as-rotation, mutation of stored coordinates, affinity, stability or model-quality claim. NumPy 2.4.6 and Gemmi 0.7.5 are explicitly declared. Reviewed backend fixtures cover planar/nonplanar fits, reflected data, shuffled pairs, collinear/coincident/near-degenerate inputs, strict references, wrong-kind/cross-run/nonprotein inputs and nonfinite derived values.

Immutable reports cite exact result fields, units, source bytes and provenance. Reads validate saved geometry and transforms without fitting again. Review found and resolved the forged-singular-spectrum loophole: scaled Gram trace, squared-trace and determinant invariants now constrain the saved spectrum, alongside source coordinates, proper-rotation checks, residual/RMSD coherence and optimality. The forged diag(3,2,1)/15-degree result is a labeled regression fixture, not a scientific observation. Strict nested references, exact integer models and nonnegative residual/scalar checks prevent malformed stored evidence. Events-only tests patch SVD and tools to fail during reads, separately from the browser's no-new-call observations.

## Native integration and resolved lifecycle findings

Actual Mol* reference and moving representations are separate source-bound layers. The saved rotation/translation modifies the moving display tree; native world-coordinate readback, layer visibility, aligned/unaligned controls and real layer picks were checked against immutable coordinates. Same-layer measurements remain source-coordinate distances. Pair focus selects and frames both exact sites. Comparison and active atom visuals prevent incompatible single-source scene/PNG saves; leaving Measure, clearing it, restoring a scene and returning to one source clear the current visuals while retaining immutable history.

The final native queue captures binding, operation token and manual revision at admission; awaited mutation stages recheck ownership. Identical nonnull six-field binding acknowledgments preserve ownership, while real changes, explicit null and cancellation revoke it. Representation reconciliation has its own desired-source/representation intent, avoiding self-cancellation by a session acknowledgment. Actual state-cell readiness prevents a deleted representation selector from falsely claiming a usable viewer; partial active failures expose retry rather than stale rollback. Ordinary focus retains the last confirmed selection until guarded success; catalog reconciliation never emits a manual-selection callback. Late catalogs are validated against the actual ready instance, and selection-dependent actions remain unavailable until validation succeeds.

Page reads are bound to current source/catalog attempts; rejected catalogs cannot be readmitted during retry. Comparison actions use logical desired-view intent rather than physical source-load completion. The eleventh held-request case deliberately admits B while the prior source is still loading, keeps B held until that source becomes natively ready, then releases B and finally stale A. This directly exercises the previously failing cancellation boundary. Explicit newer actions and run/source changes retain their guards. Earlier genuine failures and harness mistakes are preserved, including ordinary PDB identity, zero-height pair-table layout, focus self-cancellation, false manual restore cancellation, malformed-catalog retry, enabled B cancellation and the counter-only first eleventh failure.

## Independently inspected evidence

Archive root: `docs/qa/m10-comparison-20260927`. Every one of the 2,280 manifest entries was independently checked for SHA-256 and byte length: 278,854,386 bytes, no mismatch. All 224 JSON files, 49 JSONL flows and 30 gzip event streams parsed/decompressed. The manifest and retention policy preserve all raw rows, page captures, downloads, failed paints and selected successful paints; redundant successful paints and ephemeral browser/storage directories are explicitly excluded. Integrity validation of the whole archive is not a claim of visual review of every screenshot.

All 80 current runtime files matched the eleventh frozen source manifest. The final 2,413-path review inventory was also independently rehashed without mismatch after the final documentation correction. Source review covered the production/test/document paths below and the relevant unchanged runtime, source serialization, event replay, Run.call, egress and viewer contracts. Semantic evidence review examined selected raw assertions, network ledgers, numerical results, manifests, download bytes and event logs, rather than relying only on pass labels.

Completed eleventh evidence reviewed includes normal 37/37; M9 core 32/32, held-session/manual 2/2 and held-detail/manual 3/3; Measure 17/17; alignment 32/32; adapter 8/8; late catalog 3/3; source matrix 8/8; faults 15/15; and pending-atom scene restore 5/5. M9 core omits the historical other-run cases and is not called a 40-case rerun. Ninth identity 6/6 remains attributed to that actual build with unchanged native mapping/backend evidence; it is not relabeled as eleventh execution. Earlier model-2 insertion/altloc-B native picking and catalog-only duplicate-site observations retain that distinction.

The real 3–4–5 picks produced 5 Å in both directions; current eleventh same-site retry ledgers were empty. The reverse report binds the reverse result, not the first result. Four-pair alignment has determinant approximately 1.000000000000002, independent RMSD approximately 3.15e-15 Å and original RMSD 11.269427669584646 Å; native layers contain 17 atoms each. Download bytes and all seven distance / 52 alignment claim source bindings were inspected, and downloaded hashes were independently recomputed. Report previews and older immutable reports remain correctly attributed.

Manual camera races preserved all eleven camera fields exactly after held real session POST201 and scene GET200 responses. The new scene-midpick case has a genuine ALA N site0 first endpoint, visible pending state, fresh-session saved-scene restoration, complete selection/camera, Measure off and zero scientific command POSTs. Existing result and scene rereads remain unchanged.

Representative images directly inspected during final review include:

- `normal-eleventh-build/V05-click.page.png`: real contact-row ARG A/8 selection and camera change.
- `faults-eleventh-counter-fixed/C13-malformed-catalog-retry.page.png`: actual recovered blue/orange native overlay after a fresh matching-SHA GET200.
- `measure-eleventh-build/C11-distance-report.page.png`: real endpoint highlights, distance annotation and selected reverse-result report.
- `alignment-eleventh-build/C08-full-unaligned-overview.page.png` and `C08-pair-row-focus.page.png`: separated full source layers and actual aligned pair focus.
- `adapter-eleventh-build/C15-pdb-selected-scene-reopen.page.png` and `replay-distance-scene-eleventh/C14-selected-pdb-scene-after-reopen.page.png`: authoritative Axp/null-label selection after fresh-session restore.

Earlier reviewed native identity, source-matrix, blank-PNG failure and corrected M9 PNG images remain historical evidence with their original build attribution. Source-matrix limitations are explicit: eleventh original mmCIF aimed site2 but hit validated site5; minimized aimed site0 but hit validated site11; prepared aimed/hit site2. These establish correct observed native-site identity, not exact intended-site targeting for all sources. Ordinary real 1HSG residue selection includes a retained empty hit. Coincident zero-distance sites, reflection/degeneracy and malformed scientific inputs use labeled API/backend fixtures where the UI cannot express them. Focus-then-orbit browser retention does not prove deliberately overlapping pending-focus timing; controlled production-helper tests cover that boundary. Late-catalog browser release after native readiness is not proof of the narrower pre-instance interval covered by controlled lifecycle tests.

## Events-only replay and prior-work preservation

The pre-service inventory records six copied event logs only, no object/upload/index files or symlinks, and the original isolated QA root renamed. Its directory/file assertion correction occurred before service startup and changed no event/object bytes. Prebrowser reconstruction checks 88 objects and 150 exact API responses with zero appended events. Actual browser replay passed alignment 6/6, distance plus selected PDB scene 7/7, selected original/prepared M9 scenes 3/3 and saved scenes/figures 18/18. Four M10 replay report downloads were independently hashed and match the original eleventh bytes.

I independently compared both live retained files and the archived gzip originals/replays: each original event log is an exact byte prefix, current hashes match the probe, and the only appended types total 23 viewer_session_created and 18 viewer_scene_updated. Postbrowser verification checks all 88 original objects and 150 API responses without mismatch, including budget/jobs/scientific state and report/figure bytes. Accepted M9's separate immutable subset retains all 53 objects and 16 downloads. No scientific recomputation, report creation, model call or new figure/scene object is evidenced or needed for replay. This does not promise future renderer pixel determinism; stored artifacts replay as exact bytes.

## Explicit current shared-source coverage extension

This review supersedes stale current-source coverage from M0–M9 and the integration review for changed `backend/mw/api/app.py`, `backend/mw/workspace.py`, `backend/pyproject.toml`, `config/tools.yaml`, `backend/tests/test_api.py`, `frontend/app/page.tsx`, `frontend/app/globals.css`, `frontend/src/components/MolstarViewer.tsx`, `frontend/src/components/ViewerAgentPanel.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/saved-scene.ts`, shared saved-scene/viewer-scene tests, `frontend/tests/offscreen/normal-flow.cjs` and `README.md`, using the hashes below and fresh regression evidence. It adds the new M10 tools, report validation, native mapping/helper tests, harness, contract and documentation. Unchanged M0–M9 scientific/runtime code is included in the full runtime/phase binding and appropriate backend/regression checks; this is not a claim that every historic UI inventory was rerun. Existing phase reviews, indices, archived failures and immutable scientific reports remain historical records and are not rewritten.

## Reviewed file hashes

The following table names the production, test and documentation files directly relevant to this extension. The archive manifest binds its full retained inventory. Parent recording must additionally bind the complete 2,413-path final review inventory (including all 80 runtime files and archive entries); mutable phase recording and this report's own hash are recorded separately. Mandatory final command evidence is produced by the parent after this review.

| File | SHA-256 |
| --- | --- |
| `README.md` | `fba022e453f0e1574e5bc94f07a8091c24dd2677413c79da3f53d7f36bce0fbe` |
| `backend/mw/tools/comparison.py` | `1926d149af33bcd210109f217bf0724d9a87b99cc9b6060366a6911bdba6f38e` |
| `backend/mw/comparison_reports.py` | `d03540ea34bf5941f9169c085723c54d355808835bdfbd2d1f1f175bac5dc0fc` |
| `backend/mw/api/app.py` | `b2cafd1f314298c68bf2dc5128b289b48dae2e3d120f29fd59bc1b3e027b295a` |
| `backend/mw/workspace.py` | `dcd260688329e8b8ce9bd414a5adb4fb52c3a1bac443b004b54155d117a07404` |
| `backend/pyproject.toml` | `90bd8f9be6e55e56d63e9a5a1f3059b95f580a3e4562c3b3b7a3155a229eb956` |
| `config/tools.yaml` | `a4d5b19b60c6a15617976938ba2ea153226bab124a4e40b45b75a0085cf8f680` |
| `backend/tests/test_comparison.py` | `109d30885675e6ed6513883f71ca3a1fede45566d379a0b6ab63418d676b9c2d` |
| `backend/tests/test_api.py` | `e591e9ccf6e319ee80decd2589cec6f1be46a64550f28257cb70b918c1f432b2` |
| `frontend/app/page.tsx` | `ba2c9a40e4cb4d836235c2a6b358171d4c2ed28873272eeff8462115bf3286c8` |
| `frontend/app/globals.css` | `0da268e32640fc7fca3e53cd8f642c41c02c245aca6701ec93817536e484f13d` |
| `frontend/src/components/MolstarViewer.tsx` | `6cb4671eb4348fad833dc1e498bb2b0b46de54cc0d1bf90d10a69fd9417f68d4` |
| `frontend/src/components/ViewerAgentPanel.tsx` | `37087a3e8bf358a90bcd40fc308336fa51123b5c3c97b7dbe8dae1141884ecd7` |
| `frontend/src/lib/api.ts` | `16a7c021375a5be63da1290dca5faad0d4aedec34a395b54deb0bbf2731401cd` |
| `frontend/src/lib/comparison.ts` | `f9f818e9cdb3a784c690fe41eee1eef2d4771987829afdbfbda04f2ddf23e523` |
| `frontend/src/lib/saved-scene.ts` | `40600bb14993912525f83c02f1a17f0150d379461c65ee39f6f0c5fce73cc732` |
| `frontend/tests/comparison.test.cjs` | `02aed577085f1d7c087804da63e150d4bc167021d8bbd0afd26e54f2be0990c2` |
| `frontend/tests/comparison-native-parser.test.cjs` | `3e477f690c4e592806cfadea333627e697b337e8e36acdb56e440ffc668bb9a9` |
| `frontend/tests/saved-scene.test.cjs` | `1fa7e88069bf218b11afbcc5add70e78111f5cb559db66e92b1679b786a830d9` |
| `frontend/tests/viewer-scene.test.cjs` | `77e067ef7e6c7bb1cb00d137852100fce81f16d71900375c9d464fe2b011f656` |
| `frontend/tests/offscreen/comparison-flow.cjs` | `5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099` |
| `frontend/tests/offscreen/normal-flow.cjs` | `fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d` |
| `docs/M10_MEASUREMENT_ALIGNMENT_CONTRACT.md` | `8bbdd8e07a3c3db644a9f3102c12b183b95b3571368f9546230cdb633388e86a` |
| `docs/M10_MEASUREMENT_ALIGNMENT.md` | `20741aec7738b74938ffb078aa67f4f37e1c171ee54d32c9a61294d0f50d008b` |
| `docs/M10_OFFSCREEN_QA_PLAN.md` | `6af7c2d5355f5efbf5fb9f7346eeb0746af83cbd68455091014d17760f4fa35a` |
| `phases/protview-comparison/step0.md` | `29dcaba57770db6813a81798d558ae4376570e26dbc3041d4d816f9bd8da8125` |
| `docs/qa/m10-comparison-20260927/manifest.json` | `b811f55df580d4019fdbaa7543c74a78229973213e609a1268f1af3a59b80a9d` |
