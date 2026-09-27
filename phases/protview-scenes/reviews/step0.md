# M9 saved scenes and local figure export — implementation review

Reviewer: GPT-6 Astra. Implementation and harness: GPT-6 Sol. Date: 2026-09-27. Accepted predecessor: `6894ab4`. Reviewed production build: `ok0MiGdUCB_XqVsI8MjXC`.

## Verdict

Verdict: APPROVED

No blocking implementation or evidence finding remains for the selected M9 contract. This approves the reviewed source and evidence for phase recording. Parent must still record the SHA-bound review, execute all eight acceptance commands and pass `--verify`; this report does not predeclare their output, phase completion, commit or merge.

## Implementation and resolved findings

Named immutable scenes retain exact source kind/schema/model, authoritative seven-field residue identity or null, representation, all eleven native Mol* camera fields and theme. Explicit restoration loads saved source bytes into a fresh session/generation, including original, historical prepared and validated OpenMM-minimized sources. Native restoration and image capture serialize with viewer work and reject stale bindings, manual changes, lost WebGL and timed-out continuations. Camera transition settling and full native readback precede successful acknowledgment. Manual clear and rescope release saved selection; catalogs at most 256 retain their full target list, while larger restored selections display their actual exact scope.

PNG and JSON are one immutable captured pair. Actual Mol* ImagePass rendering is followed by state/binding checks and bounded PNG validation. Download links use the same figure handle and safe generated filenames. The sidecar explicitly identifies client-rendered local viewing provenance, not a scientific measurement. The backend revalidates source/model/selection, strict manifests, image structure/dimensions/hash and same-run links. Durable admissions reserve UUID/capacity before object writes under the run transition lock. Interrupted admissions remain recoverable and count toward limits; rejected byte-budget requests do not consume a fresh figure slot. Identical content is deduplicated. Events-only restoration requires no input paths, renderer, scientific rerun or model request.

Review and actual renderer failures drove specific repairs: binding value comparison instead of object identity; durable admission crash gaps and PNG reservations; exact residue projection; ImagePass temporal-mode blank output; delayed list clobbering; selected-session synchronization; camera-transition settling; manual precedence across held detail/session reads; newer restore ownership; and visible catalog scope. Original failures remain archived. A final harness defect was also resolved: V13 now waits for the actual 503 and scoped error alert, then requires visible completion, a fresh session/generation and complete native-state readback on retry. No scientific values were substituted to make these cases pass.

## Independent evidence inspection

The archive inventory is `docs/qa/m9-scenes-20260927/manifest.json`. I independently verified every one of its 499 listed files against SHA-256 and byte length: 78,981,679 bytes total, no mismatch. All 84 JSON, 34 JSONL and 4 gzip event logs parsed. This is integrity coverage of the complete retained archive, not a claim to have visually inspected every screenshot. The manifest discloses omitted browser profiles, duplicate paint counterparts and earlier successful screenshots.

All ten current runtime files match `commands/seventh-built-source-hashes.json`. Final seventh-build scene records contain core 40/40, faults 7/7, identity 4/4, corrected projection 4/4, readiness 4/4, POST races 3/3, encoding 5/5, large scope 6/6 and overlapping restore 2/2. Browser replay contributes 17/17 and selected-source 3/3. I independently checked all 95 final scene/replay records for pass status, actual offscreen/nonvisible/GPU flags, positive paint count and no blocked non-loopback requests. Loaded observations contain real native viewer state; the empty host baseline with canvasCount0 is not rendering proof. Electron 44.4.5/Chromium 152.0.7977.130 are recorded.

The seven focus/manual timing cases were executed on build six and remain attributed to that build; they are not relabeled as build-seven runs. The final shared-page regressions are separate normal 37/37 and OpenMM 17/17 seventh-build executions. Historical M8's 86-case ledger is not claimed to have been wholly rerun. Archived backend output records 271 passing tests; the final eight-command phase gate remains the parent's responsibility. Unit PNG fixtures are intentionally synthetic and cannot establish molecular visual content.

I inspected raw strict V13 failure/retry, overlapping A/B restoration, core report/budget/job invariance, native camera/selection and download records. The final PNG download is 1200×800, 155502 bytes, SHA-256 `33cbf31fb6149858d998b110862ec52af41b7b07fbc06b42802c0f9d4959dae6`; its archived JSON sidecar independently matches that hash and the minimized source/scene. Its decoded record has 207 sampled colors and 4489 occupied samples.

Events-only setup records two fresh run roots containing only events.jsonl. I independently decompressed and compared before/after event streams: each before stream is an exact prefix; additions are only 15 session + 14 state events for the OpenMM run and 3 session + 2 state events for the selected-source run. All 53 embedded object content hashes match their handles, and all 53 raw-file hashes match the recorded pre-replay baseline. Parent's separate API verification records 16 exact figure/report download streams plus equal scene/figure/report/budget/job state before and after browser replay. I inspected those records; I did not independently repeat the entire service recovery. No scientific event was added by replay.

## Direct visual inspection

Within the archive I directly viewed these five images:

- `scenes-core-seventh/downloads/1790466242234-51966-1-protview-figure-5ed29518fb81.png`: nonblank molecular cartoon, light background and rolled axes.
- `scenes-core-seventh/V08-restore-selected.page.png`: highlighted MK1, full identity/selection legend and restored saved view.
- `scenes-scope-large-seventh/V09-large-restore-scope.page.png`: original 326-residue source with selected MK1 and explicit exact scope.
- `scenes-identity-seventh/V08-identity-reopen.page.png`: labeled synthetic model 2, auth A/42A, restored selection; observed chain_label Axp and seq_label null are retained honestly.
- `scenes-core-third/downloads/1790464504786-38941-1-protview-figure-b6b200733a56.png`: the preserved blank original failure, not accepted current output.

## Coverage extension and limits

This review explicitly supersedes prior current-source review coverage for changed shared files `backend/mw/api/app.py`, `backend/mw/core/events.py`, `frontend/app/page.tsx`, `frontend/src/components/MolstarViewer.tsx`, `frontend/src/components/ViewerAgentPanel.tsx`, `frontend/src/lib/api.ts`, `frontend/package.json`, `frontend/tests/openmm-action.test.cjs` and `README.md`, using the hashes below and current regression evidence. It adds coverage for the new M9 implementation, tests, fixture, harness, contracts, user documentation and QA archive. The unchanged lockfile is also bound. Historical M0–M8 and integration reviews, indices and scientific report bytes remain historical evidence; they are not rewritten or asserted to bind changed source.

No new provider call or scientific inference is approved by scene capture. Native coordinates and reported units retain their earlier scientific limits; screenshots are illustrations. Cross-platform future rerenders are not guaranteed pixel-identical, whereas stored PNG/JSON bytes replay exactly. Model 2 and orthographic fixtures remain labeled synthetic/API setup, and injected faults remain fixtures. M10–M13 contracts and dependency probes are outside this M9 approval and remain subsequent authorized work.

## Reviewed current-file hashes

The table is the explicit current source/document inventory. The manifest hash binds the 499 archived artifacts and their exact paths/hashes; the parent phase record must bind that full inventory as well. Mutable phase-index recording and Git metadata are excluded from this table.

| File | SHA-256 |
| --- | --- |
| `README.md` | `b5d832d7718a1b0bff28067d1bd83b6d0fdaf1b412eab2f41ff537fd665bd71c` |
| `backend/mw/saved_scenes.py` | `dbde8a9ec031d661e61813300a9ec0e7cdfe14a9a7a5bb6b4566df5e4fe9144b` |
| `backend/mw/api/app.py` | `3d74dcbd3a3a1c74b0bc1b02d7e0b09d123978a2a08eb23829e94550ae63567c` |
| `backend/mw/core/events.py` | `0a843089b15441c5950c3a3d2e15a6b35e6a1b64c0d52de4a26888a756d9afc5` |
| `backend/tests/test_saved_scenes.py` | `974eb6e36498dce04135daf00e934509025335097873ba69cb197d498124c522` |
| `frontend/app/page.tsx` | `84fb75a96c33eb18813f3a3f276d0b8144de9a5e82aef0cdb9cfcf2c59e06381` |
| `frontend/src/components/MolstarViewer.tsx` | `903b764703fd82edc5414b17a00ddc201b8d28e9af50e180ef265dcc60647966` |
| `frontend/src/components/ViewerAgentPanel.tsx` | `e7b5f79569f0df3620d4f5888d6e022404965f9bf4c85287970804815f40391f` |
| `frontend/src/lib/saved-scene.ts` | `d02f9ba62f2ef6233ffdfa6d67e1c21016c11af3babd9af7142d20a35b8d702c` |
| `frontend/src/lib/api.ts` | `da2e2887930be5b2d5f229af642ccb007840e8428d36d0daa10ce71b8a635a47` |
| `frontend/package.json` | `7b09cc034a4aff61d1195668afe4050e9697f591c5e7d8346bc5eb789352ab8f` |
| `frontend/package-lock.json` | `3125f791bf8f7763c64b494502acea3f66283f9db4ef45392665a7552ea74f54` |
| `frontend/tests/saved-scene.test.cjs` | `e59861129388d6ad28bb717abda338a08adacc30fb950842e2d33f10921aa5f0` |
| `frontend/tests/openmm-action.test.cjs` | `80d3d82fab3460e168f614767639d40ab8d9aaff360ce9bb80c22821e26ada7a` |
| `frontend/tests/offscreen/scenes-flow.cjs` | `043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2` |
| `frontend/tests/offscreen/fixtures/m9-identities.pdb` | `6745048ca8d0326da3e730b14124379c400b53663c08aee66559a557b8be0bcc` |
| `docs/M9_SCENES_EXPORT_CONTRACT.md` | `835c638f97fb16935ac4f4b17b9e1508dc55eabbe83710fa27c4d7fc229c445d` |
| `docs/M9_SCENES_EXPORT.md` | `7c842b26ca8b84b787d0c15eca0be42631fb6c07bcee2092359b173861ad2af0` |
| `docs/M9_OFFSCREEN_QA_PLAN.md` | `a0933fed0167cd610791db81c2d3939422e7b1c7eb003c53b5d1c6bea3fde05c` |
| `docs/M9_SCENES_QA_REPORT.md` | `9d384b4ff6182738c529c9a24177f37cc19a570584c5395f0407d6d8d3b263c8` |
| `phases/protview-scenes/step0.md` | `a77f8bbfdce5fa6689c673321123c21db9255fe4aecb1602c2b98ea708f405df` |
| `docs/qa/m9-scenes-20260927/manifest.json` | `cba82b5fd0cafc66e8299d4e3fbea73e36dc950ef54da27a7d1846453f6717a2` |
