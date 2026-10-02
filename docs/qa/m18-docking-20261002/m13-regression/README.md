# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-02T04:01:41.313856+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "TQn8wObN5_83HO7HbKqrf", "gitHead": "23e2c03d87038092edd1e1ec4c10d5ff398adb11", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "cf0fbe1200386d7727bdfa795118a385521c0fa23cb298147c211d43b3c99a73", "dirtyFiles": ["?? docs/qa/m18-docking-20261002/acceptance/", "?? docs/qa/m18-docking-20261002/gate.txt", "?? docs/qa/m18-docking-20261002/m14-regression/", "?? docs/qa/m18-docking-20261002/m15-regression/", "?? docs/qa/m18-docking-20261002/m16-regression/", "?? docs/qa/m18-docking-20261002/m17-regression/"], "recordedAt": "2026-10-02T03:27:01.225767+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 52개(332,715,022 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m13-acceptance/m18-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m13-acceptance/m18-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m18-docking-20261002/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,949 | `af8f11d4cc585c1a0cbe0c0c731f49d7c4e2ef15d3c4e7973c33ada5543da675` |
| `evidence/chemical-create/downloads/1790911817615-87911-5-protview-report-315f29951ecc.json` | 294,310 | `83d9ad200d1b293794e836c9977ccf4df98b81c79ac74ebeefc911246db85bc7` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,770 | `76f89b2df9e0b4e1c19f10f4731f47283f928f1aa8aa4c62ef5f307504973821` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,622 | `db2ef3ce75469c9bb2da19a0aef525f36c6e401302afc17ed701dfa447fc147a` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,660 | `94ac9e4020c20baea225d1141437fb57cb7279d49df8b193dc1c0a6cae8e2482` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,637 | `13dc4d35d803116460914cade0d402403c91dc4686fde3f6b02afe54b75c51e4` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,981,884 | `204f9fe3a46bb01ed1e181722f738cf3a4ae958e8c59411ea46a11faf8d92d59` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,608 | `5eb7df452bb6dd6c4938a41b75c90804120b0fdfcd87557b00b08159eedc462d` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,257 | `1bb559e166f70ccdd846bf9f237e85c4bb3fb95f40f68a6fc5b39c4cae537e01` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,592 | `5d006a14faecf808c64576ca328969e5de12879b94432ccf9522055c71f2f3ba` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,153,424 | `ce571096f7dbda25b1e8bfb030783f4ffbe7469d2b62764c846919c8e830b7ef` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,078,260 | `9ba069f8af5d3d7584ff7a291974f1e86849fd69c481a7b6de68e107d5431ce3` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790912787367-92265-4-protview-report-94e39d9d8288.json` | 1,191,725 | `c47f2848a9a9611f3d1e89ba30e2c3b7bebf9a61fd7149e92b04011442d72b36` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,184,900 | `5633220549aec03dbbd9dfef5824f2b698e376132f6a9f9a4940d537c41647af` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790912813548-92342-2-protview-report-47cd2b02f7f3.json` | 491,458 | `afb01ed0fc9fea88fde9f5c46baf9a06cf906a2dae19673d311f59738606cdf9` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,072,864 | `d5ff4d8fa865b0440fb9b897f6a0e655100cc4e9550b97097c2cbc4baa77a831` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,617 | `146f618d3b81cf2bcdd91f29b068bf0abb86592229ebdefac07e1e5b738cfdd3` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,205,600 | `e58c6928034e0e1041e982b688e8870d420701bcef9c34222227fdde3681e4c1` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,608 | `f666ed231ca94b705d5d78b63b36760ce6108b0000c5675504aa4bfc376d9cb3` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,254,995 | `99570973f8d1c40a281c7142e301e2eac4baee053fcdb3f8b6e01d9ab2b14b81` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,639 | `4de29e5eb93918b3f315141a19542aa04c6123fd20508c0fead61e0f322fe4f5` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,479 | `65e1f943a6c2119d66e8f81513736eb91012aec369aacdebe3dcf9ca2c6befd2` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,628 | `d6d1ced24eb5b073d90092811ffe13e0704f595b8e8c98f448658e40878b7f2a` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,206,591 | `1ffdc239bb8ec40a1fa069d2d9103d7370fa54fae0c23ee8d5529d1d9cb0fab0` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,622 | `07d1af54d6f948587a0ff8699b6c43bedaac8de4c2236d987ce7ce43a59caa60` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,421 | `b76a63aeb19590fc551aad7490bbe0fe4374aefe2cbc59e7411056d50fa0feee` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,343 | `a13d56fddad2af942393746c947d34e40f70a7401a389ef86c0f091a9ebc6b53` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 763,038 | `6496ccf32d9bcc12a7093d54283bef11cf9a6c8a8aa270a4d0f49c729a406551` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,907 | `0647de823df7e5db8cecfe3ba4026d5216c04a7345de1c021edd7403e745427a` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,970,174 | `3c34c00d5918907c435d8ff755e2fe5b4c3bee60f1695a7e074fbad350d22f7a` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,618 | `351165f150cc28c527a82eb8cb957a91188024e05922234f7064dc790087a9ad` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,218,330 | `0a71016ac9ce0e0994916c8c110872c8a4852253596ec70040b1a34f9e22333c` |
| `evidence/m12-acceptance/evidence/regression-m10-measure/comparison-measure.jsonl` | 326,801 | `75532636d1b72194c589d1673650c9320e2fb8e8a561638a31270388cd5c6145` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,544 | `3b1d1764a020919f474cf70ac4c5c4bcb4c1457e38cd809cf522db852f440068` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,157,858 | `7a37a40760af91108d653682a47faa2f5cb79c2f5882fd71de60dc62f6eb4cc2` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,895,264 | `5287d08e11c3bcbc55efcd1d4af8c1bff51a6cf928dfc160098a3c765ed6dfa1` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790913469352-95391-4-protview-report-e1a192a1105a.json` | 1,191,725 | `6926193ad165cf5aa39a5e8c322530d72e3827fb47d9028607a507cd1dc65ad2` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,121,743 | `4a1c05277b8af6b8e00e0d7c9f41780e44db434f61574165c6344fb1454d1f4e` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790913490038-95526-2-protview-report-df125013ac77.json` | 491,458 | `795e2746419d3dc67261fdbfe96b10409968f576e28c0360e874ea9e74e8e24e` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 1,944,126 | `6da3d146c6b0c233725de7f7e66f1d7ee5e99e8b5102c92414aa1caebbb6f67b` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,617 | `227f606616da5d352fd9cbc7159e08c2840acf7439337eb63a8892a2eb983479` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 562,816 | `6a2486389036897ac27fa75c2dc8ab04541f3b4bbc475407a0fc93638e3adfcd` |
| `evidence/main/downloads/1790911636765-87291-4-protview-report-4368926a908a.json` | 1,191,725 | `0197ee4cdc9735ab7ce0e246a6b9fac0940aca1c43c225331cf3cac9aea73d23` |
| `evidence/main/downloads/1790911647384-87291-7-protview-report-607da21fba1c.json` | 406,808 | `dfe7db0f824b8979d836cd7defb37725316c4b9a5f190e49403546efc72572dc` |
| `evidence/main/downloads/1790911648123-87291-9-protview-report-c60d6b298bff.json` | 1,191,726 | `500bf0a90f4f972f5ff749451556fb3d557189e22cb38e060978780b27376672` |
| `evidence/minimize/downloads/1790911715259-87694-2-protview-report-50b82c5e7e51.json` | 493,024 | `60e0e7b1f2649684c7e894c4b1175ddb618dd5e73439fe7536a5d0704a85fdbb` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,784 | `9088269a463da8f64221fb88d7fdce05a7d05ea7121c9a9b0d2a7732cb364c4f` |
| `evidence/regression-m8-normal/downloads/1790911944150-88770-4-protview-report-fd1aa0e6e2c5.json` | 1,191,726 | `6e2e159d06e01edf4ae4b620cab3151a3b244882b98c377008244972338b4911` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,920,468 | `975fb1834fa4e15c0f1035d695e22af23089fb9047112601a4934805da19d582` |
| `evidence/regression-m9-openmm/downloads/1790911968359-88828-2-protview-report-60dea5728382.json` | 491,459 | `78ac572031d180bc08d26696bdb74a897ad6b1d901bbc2fb86aca278a9710ec8` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,019 | `7052f166ec76009de6515ef858f2deefb76e3818c21782579fdc7dde89d68f90` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,567,801 | `24f8c5afef32f049f2e1c31842c4a9dfccafa81b3bb996e3f61a151c3f97716a` |
