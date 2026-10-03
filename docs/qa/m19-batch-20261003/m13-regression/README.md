# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-03T03:23:26.313451+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "HZVIvlS1pgVkSE0gAkqD6", "gitHead": "858bd45217e5bae3e87c4451261c1bc369a079c3", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "778f30c3b9e326589c49d0fa213eb6ff3e41737c23376bfdd0210c4f970196dd", "dirtyFiles": ["?? docs/qa/m19-batch-20261003/acceptance/", "?? docs/qa/m19-batch-20261003/gate.txt", "?? docs/qa/m19-batch-20261003/m14-regression/", "?? docs/qa/m19-batch-20261003/m15-regression/", "?? docs/qa/m19-batch-20261003/m16-regression/", "?? docs/qa/m19-batch-20261003/m17-regression/", "?? docs/qa/m19-batch-20261003/m18-regression/"], "recordedAt": "2026-10-03T02:48:30.097616+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| W-inspect-raw | inspect_ligand from the raw structure (prepare step in the plan) | pass | main:pass |
| W-inspect-prepared | inspect_ligand from a prepared structure | pass | main:pass |
| W-cavities-main | find_cavities, main screen, prepared source with explicit chains | pass | main:pass |
| W-measure | measure_atoms from two real atom picks | pass | m10:pass |
| W-compare | compare_structures from explicit CA pairs | pass | m10:pass |
| W-minimize | minimize_protein (1UBQ) | pass | minimize:pass |
| W-chem-create | chemical_interactions create_new | pass | chemical-create:pass |
| W-cavities-chemical | find_cavities on a chemical_structure (chemical screen) | pass | chemical-create:pass |
| W-chem-attach | chemical_interactions attach_existing | pass | chemical-attach:pass |
| S-unavailable | method engine absent → 사용할 수 없음 with the reason | pass | unavailable:pass |
| S-nl-unavailable | natural-language planning shown unavailable (disabled, reason) | pass | main:pass, unavailable:pass |
| S-prereq-ligand | prerequisite unmet: no ligand | pass | main:pass |
| S-prereq-chains | prerequisite unmet: no explicit chains | pass | main:pass |
| S-prereq-ca | prerequisite unmet: no CA pairs | pass | m10:pass |
| S-prereq-chem | prerequisite unmet: no chemistry request | pass | chemical-create:pass |
| S-error | step error shown (typed native failure; job failure) | pass | chemical-error:pass, minimize:pass |
| S-retry | one explicit retry after a labeled worker fault | pass | minimize:pass |
| S-stop-plan-approval | Stop while waiting for plan approval | pass | main:pass |
| S-stop-scientific-approval | Stop while the job waits for scientific approval | pass | main:pass |
| S-stop-running | Stop while the owned job runs | pass | minimize:pass |
| S-shared | shared-job explanation (observed_shared) | pass | minimize:pass |
| S-scientific-already | 이 run에서 이미 계산 승인됨 shown instead of a second approval | pass | minimize:pass, chemical-create:pass |
| S-race-clicks | two quick clicks start one step | pass | main:pass |
| S-race-window | second window: concurrent Advance | pass | race:pass |
| S-race-run-switch | held Advance response across a run switch | pass | race:pass |
| S-dry-run | dry-run run: plan_only + notice | pass | dry-run:pass |
| S-chem-placement | chemical goal/results placed in the chemical screen | pass | chemical-create:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| main | pass |  |
| m10 | pass |  |
| race | pass |  |
| minimize | pass |  |
| chemical-create | pass |  |
| attach-setup | pass |  |
| chemical-attach | pass |  |
| chemical-error | pass |  |
| dry-run | pass |  |
| unavailable | pass |  |
| regression-m8-normal | pass |  |
| regression-m9-openmm | pass |  |
| regression-m9-scenes-core | pass |  |
| regression-m10-measure | pass |  |
| regression-m10-alignment | pass |  |
| m11-acceptance | pass |  |
| m12-acceptance | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
npm --prefix frontend run typecheck   # build와 동시에 돌리지 않음
npm --prefix frontend run build
.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/<label> \
    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-<YYYYMMDD>
```

`regressions`는 이 실행기의 서비스로 M8 normal-flow, M9 openmm-flow full → scenes-flow core, M10 comparison-flow measure/alignment를 돌린다. `m11`/`m12`는 `scripts/m11_offscreen_acceptance.py`·`scripts/m12_offscreen_acceptance.py`를 기본(전체) phase로 `<root>/m11-acceptance`·`<root>/m12-acceptance` 루트에서 실행하며 각자 서비스를 띄우고 끈다. 이 README는 실제로 실행한 phase만 기록한다.

코드 루트: `<repo>`

## 옮긴 큰 텍스트 증거 (결정 0020)

256 KiB를 넘는 텍스트 증거 51개(331,871,173 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m19-acceptance/attempt1/regressions/m13/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m19-acceptance/attempt1/regressions/m13/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m19-batch-20261003/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,553 | `0bacc4fd49a9e7eda69cd65503197bc00f87fbc475c3196cd1b08f5286700b8b` |
| `evidence/chemical-create/downloads/1790995909898-79190-5-protview-report-7be1d8aa3472.json` | 294,302 | `53d73c01e23f517c7c3d391841b6d2cc6ff1173e43b0c13c0cac6e7a2807ed48` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,487,780 | `f86b6583b547a151e0f890eb81f207bc7db67e5c4fa36d26e82894adebb8ada7` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,644 | `78018b21107e89bd53dc44dbd54c96cfc8052c797617615e5a828dbc96e927a0` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,329,466 | `ad755155f8d343d383cbf4c0c9c12249aeaaaf54fc53886f083ff403b1c35560` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,655 | `080c42884f0b2019a7d24d9685133660788198f6240eb3835dba34a5a61bcff1` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,970,298 | `a7db2e7bcb78c1f4fcecbf5e1e3a81a453c42c20e2a2b48b34ec0885d4a942d1` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,630 | `b8d19d698e34a502f04533b2e892fb597a52696bb211986bed3916b61eade828` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,589 | `0c830dfb908fe93c12fe20d6c18948138160ab29d5b8861cdec0a6bfbc272a21` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,704 | `de1dbb2e1b2e55f7b0900f232c591610e4350f043e01d7cdcced591c9dbade91` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,531 | `dec7030e2a43f466501e70ff8755478bcf2251fc337c341ff2a4c5e9343ca26b` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,700 | `6a7e86204dc00f31a56abea464364e6c25b0adfecfc6b9979ddab9e946a164c7` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790996870684-83882-4-protview-report-b5a20b77bcea.json` | 1,191,726 | `a336d16d2c128d4e0120971326255b5f138a963cdbc3c3c116ee4575e4ae5819` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,795,731 | `74abfa72472400a7b6dc0254860391648f7994803059fb7e72754896d2067627` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790996894336-84071-2-protview-report-6d1c329b5967.json` | 491,458 | `80089ebd9857304ebe239591619677645312b46a374f0df7955d1d8c661258b1` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,009,267 | `75ffab227f1e8be3c6963434b244d421be83bda66db2fe83700ecc9558616997` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,205 | `5d10433aa31bcc57c2e9c61aa94195f9e85ea556fbecd27bd5e965a52718ed57` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,925 | `f287504ea4e92daeabf6f8642b955fc5ac97a3558be52d0247885a451cf5dbc6` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,630 | `c6f7bc953679e623ca5d3fc3236e90d5547a727b8974bb0903951692bfc27168` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,266,391 | `e6d56ec9d281632624a5b2a68737038a83bb0a458ba095b9ef9fa63c60a44a40` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,659 | `806a5bc1f643bb8acda74a85b2ee983a210026d7e98fcab1b33274b249b14182` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,548 | `ae5b1a95defa1512b6822678b5f1053c20f9d1e628186fc6c4041ea591f99466` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,650 | `f3d6f2ab6cf3cef67ba239b6c3aa8238fb7ed7bf8a451c837239eaa75aa229fa` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,757 | `6d51aa49b6e3beedb5cb8d5de4a235bb1e12b81900b45ec38ad9585282e2b7ce` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,644 | `167eeca9a70fa410aafd24ce668198dd8208d5238c430a1225d9ada7fc0875ce` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,606 | `f409dd472fb63cfa9ed40d4f546f432b9e46bf78aa8abbe88d7cc4002757f8fa` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,382 | `a4e924dc4fa65a64467c380f553a4b9fdea57b6dc05edf34cb80c60250a494ad` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 786,601 | `7301447f8ac7964d2e599d111d9e49c32bdf9bf92f29230f1b6a8d56ff39f6d1` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 294,193 | `ad0b353c2254afbae20e521488b1254baff17b6c62b3bb9ac6730612936db9e2` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,987,183 | `aa6522f039d63de593a094f5898e3399cc362d3af7fe2bcb42c80e0c2fba99a9` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,636 | `44f106c090ce2904b356792820b5f7156d14a57608afcc72949233655a539cb1` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,721 | `0524eb7d9d3ffad8bbd6cd9fbdaa261e98e2b8a5bfa4f3fbe61331a09e0e1cad` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,576,806 | `fa047da57f7b0841c8b356ae41b8d780387547e3c382976f16f16c191a2e67cc` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,159,100 | `c2f587581b52a5e8e88db3ab720ded6c357bdcdfb06dc58d7594b07826b3fd37` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,899,240 | `94317e0b58551602d23c349bf3b4ef3f5932e04972799d4143fcb0744581dfd2` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790997554694-87144-4-protview-report-35ed34eb9c38.json` | 1,191,726 | `b414d16bd044b3a18c70ae70a391a27824c9166863a1aa9a553448ba8e00d5ad` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,057,999 | `3784df5c037501db871f6ae15da3143db99dee2448f4a4716ebf22714740c794` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790997576012-87198-2-protview-report-a9c82e34c41e.json` | 491,458 | `d4b23a2f0b34676464a33e6167aec15a0c21bf47d6a52306ca88ed268b656c8a` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,009,244 | `17029d70bc07576029e747369691ae73ef2d9c61c4119498cc8061721673073a` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,209 | `fc82f4b40efaf5f0cc5e127e72b5f49938e5a02ba1a3aafe18d2745e4eb2e29d` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 575,223 | `e432abfbcbfd722e61f5fabd89c404efb31377acd7308ba2d670384f6e443a71` |
| `evidence/main/downloads/1790995726038-78561-4-protview-report-b053f8e8e7a3.json` | 1,191,725 | `3062d6c5f6429b62763a5dd34b80cf8d8c332e76ffb4c9352f09bee4464c8cac` |
| `evidence/main/downloads/1790995737389-78561-7-protview-report-198aabbfb350.json` | 406,808 | `eb1aef6e3f80810e0d297b70e175647937c6bbad23be27e1267c400eb70a75d6` |
| `evidence/main/downloads/1790995738153-78561-9-protview-report-bc99d0893064.json` | 1,191,727 | `5bdc6b95d5ca26743efeb176f9b4d09560ff9b333bd285203df1440fc3a4cbc5` |
| `evidence/minimize/downloads/1790995807028-78992-2-protview-report-6fa6d6839ee4.json` | 493,024 | `598dcb0d4d508784340a8880124c752f98566f3cb1c593c0101d5ea02861497c` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,244 | `a29d4e8efd496f95a1d9d9f0300fc88d6b6a8c101eba293f5087dac9890486cf` |
| `evidence/regression-m8-normal/downloads/1790996032831-80050-4-protview-report-05ad44534bba.json` | 1,191,726 | `bbb2cb0512a92c17af86b4747a9ba609e7217d99e8ef0a4eeb058eb63b77e580` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,987,912 | `f352f8aaa0d922740b27403d2569b88c2d5f3bcff3d2b53ef90e91cd864ead63` |
| `evidence/regression-m9-openmm/downloads/1790996055066-80189-2-protview-report-26c8a1fa3fed.json` | 491,458 | `9852d37040fc48f683cd3cb61f0c2009f09e54a23e17e51b7e8fef4d42f76608` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,007,387 | `6e7f1bf4db90186326df484bffabf3b90fbcf891f6a8e558c19c60c3a29c3a8a` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,392 | `9b706c66a9aa5a998ac2d74a50101303bf51a52ed9edd66eb39293db5b17b39f` |
