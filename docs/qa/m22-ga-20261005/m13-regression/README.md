# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-04T18:24:22.972177+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "CHa6nmR7ciWcO8tOTTcKV", "gitHead": "a71b2e6ac4f82311f1c008f9cc3646a0d0e063be", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "783ab98eb2b0a68a254945f55395ec053c0d2ecf0ceaf49bdbaf3a01b00bbd59", "dirtyFiles": ["?? docs/qa/m22-ga-20261005/"], "recordedAt": "2026-10-04T17:49:18.913230+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(331,512,196 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m22-acceptance/attempt1/regressions/m13/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m22-acceptance/attempt1/regressions/m13/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m22-ga-20261005/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,932 | `38e5b745f41218c82599f636ea401383ad26cfe06d81a48ad314451f5963dd40` |
| `evidence/chemical-create/downloads/1791136357571-70864-5-protview-report-692f2e86f09f.json` | 294,309 | `229e69f07d5b1edec8ae3ba8415073a8f23ba804682f0eb0b1e28c8b2f55466b` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,355 | `2fadd37b432644536e6ccc1742f8197fcf990b602d25addbd286b9cb47862396` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,644 | `fc2b2579e83b1a9208976add9745ad1b18a7dad3809f8f7b9f5882621a01ab32` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,673 | `56c4e97be0096c5c13f64320a0426b5f9c608295e9d70c5b9575fda2489e0700` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,659 | `1700c2326f51e8845286069af4d7fda9b258942d2e612ff79078bbe9cc5f8298` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,970,647 | `5d2d443c60640610556dd38af22798121550f65c96d0055e795415d5c24ecbb4` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,630 | `fcefab447dc956a8e23b37714793a3a55f7aac8c0f3dfa2e46809a21a24bc001` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,917 | `e5ce76d649b2d578066ddac5cec5dfc8e338b9b894bf63dc7095080aead7e9d5` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,435 | `405d9a881b90194e533885fa62652c0ff6cf9639edd465bc2c48b0f4bf34245c` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,209 | `999b71fd7283594a325af07264a6ca6055f6d3b9da7beb4f09c3f8258ff2ced7` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,715 | `d7b3f582b0397961d18ccd79ee27b00e6b4a2257221e944d4f4f5965e5c390ea` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1791137343745-75362-4-protview-report-380b60c8af47.json` | 1,191,725 | `d17fa6912e90a5193be244fe53e1f23a56c69fb0cbc6e980e38e8a47d7934539` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,664,432 | `dd1d1e9d5851f8648aa5cb53e38f82444311346f9a8a67611007719c99d9b56a` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1791137369846-75514-2-protview-report-11758fe57135.json` | 491,458 | `0eaef4c6baa398cc13365a88bd3a789459b1583ef9ac6e672b515a96426d1b03` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,073,617 | `41e8757e09b6637f481fc2f6dd035977a2e99c2d304b387e5072539546ee96eb` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,209 | `e4a91fa6a730fcd59b6c1a4248ca866910c5b9464f41bffe209957c62e37e790` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,828 | `1d8f1c02c2bb51c9b4b16216c7b1a7c5c07b1c5eeba15844cda6f16280794cc6` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,630 | `24807ebc86d650a72154a340ffee42173fca6374199e32470f1004cc39020401` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,254,925 | `5f885213099d6a5faa3c0cd54df1bacaeb2713acd6866e7debcc33343abc6c39` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,661 | `b95e47040b5d2b194c87df12f97f0b81911892f1c7d664d10603161341d44287` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,544 | `63ad9fc2c31527b1fb5f63124242ae449a866e362c2d600fb53a20fc26622975` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,650 | `f47afa4bfb1a04529a9bd145d5080e3f282e320216e2d9f5d0396add6b883c56` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,660 | `ed1bac1f15d67e01212243de72264dcf0246da2e90c2c8cfa15d0dc103330896` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,644 | `a21eed26ef558ae060e625b623a1903fd85eadc4d63232c33686d57cd94d7acb` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,449 | `5b0a622afd0511008e13bfe602daf55fa4bd498cd3f3def50411f296ddf6006f` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,181 | `0a29320079f88f6327c0439f599b151db1b2b7d462c52f032dea8e572e147187` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 763,593 | `57305bc3e2cf45e40e4472fe36b703eb86d8b9980b6c5f05ef3de9a16689e86e` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,799 | `68165fe5113dd0cc9614d3c7c28d8a3e345e2268040e5f3ddcfbd805ca80ac68` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,987,288 | `3bb7e8c3bac436c8b0c5282fcd9f3e19b03d764ca335611f0c2790511998c6f6` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,636 | `bf9f17f2ca311323f1d2a9dcacc503314658f00c394ad30d09f9be5e4a8fc3e3` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,106,454 | `636dae362473ac26c0fe25d14c73352f66f5ef2151db21b6496352574a842244` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,959 | `d9f98efae90bd11386733de55f566ce0628012c672c8980ea69e0247260018d2` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,158,228 | `ed1bf16521e1b0c51963c2d82af3bc9d5b46668b1e35be1561e68914b9bd3927` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,899,298 | `3ae5470d543c2122d346c3f4d3a302171b104858907f8a3d859cea1fb104be76` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1791138030332-78751-4-protview-report-bb260dfa4baf.json` | 1,191,726 | `666cc04d20c121a70bad3db84e7c050035f1306bfe14168f191c758621e1f22d` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,926,889 | `b913d2d2d1e04bcc5f2451945a1ea9348a82b8cec51d39e320e3f3967a1b43bf` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1791138051183-78855-2-protview-report-4dee3d5541f5.json` | 491,458 | `d687d96e44faca3c8db95c5271e80a0d29c4376a46ba9ba17cd8e200e7ad9511` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,009,223 | `5da7b64b6f30ce5842ea868b35bbd0ce221fbab927f0681a466f60fc9f8c2356` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,212 | `45eb28dd725f04f22ee02939f9caa2aeb9f9d2148373c37dc27ecbbc1e1a3e63` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 563,382 | `d5533d3255111f1f7854ba7fd767a9a61d4befce872bede9ae67062404634cab` |
| `evidence/main/downloads/1791136175321-70228-4-protview-report-136a84776762.json` | 1,191,725 | `2d51111e2b12c35a7f66b517ab38d91ec0d5c9e8cb25334104954ab5c1996ec6` |
| `evidence/main/downloads/1791136185960-70228-7-protview-report-80a4458768a1.json` | 406,808 | `f000ab0cb12584d35ed474aaa3e818a4b7c99bc9522749cee38980eab068ee0a` |
| `evidence/main/downloads/1791136186705-70228-9-protview-report-e8b98fe4beba.json` | 1,191,725 | `e5c644cc4ead00d7e5227bb9db02b8e1c213280ac7e16d4280cc61e23b4378d4` |
| `evidence/minimize/downloads/1791136255451-70566-2-protview-report-eedbdfad89ea.json` | 493,024 | `e07d78618f4111e6d8369ff2014634154b805ccfac0bea4874a08b1030b48ed7` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,239 | `34b1d8d3a33038ca311ae40173ce172abd73b93d43b78aa12249cd5d2c8fa971` |
| `evidence/regression-m8-normal/downloads/1791136489281-71766-4-protview-report-db4b2f1a05bb.json` | 1,191,724 | `78456c6c1c6be5c294c3a27cadaeddf50acf0d6672c8217986ce1564b374f3e8` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,856,835 | `79281279d69296484617664418f7c9fb99d8dec37e5871a4a6e06149cbbeef4d` |
| `evidence/regression-m9-openmm/downloads/1791136516437-71923-2-protview-report-d9eed2f24c0e.json` | 491,458 | `b31e662cdf6aea23e342a9bd8f7bd7633f5e08f92ecefa162e4946021b0b333c` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,007,388 | `05884ada8e34019ef0450d31e5f2e28b89533ea9ef7aa66f837befbc58fc9d60` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,387 | `1182173cf943df0a0e74b313e3b9588cca3c00a4e6a168162143b08de4e04846` |
