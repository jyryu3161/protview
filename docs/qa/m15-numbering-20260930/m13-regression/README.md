# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-09-30T05:15:33.001372+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "mc98KdfOBAIUwmBLTIM0q", "gitHead": "c1d824d8bb6400f98790b1196c04cf84c6950264", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "dc7f03a106c4f81373f7b2071b191950e95a621bd93107a2d52702bf1392bc47", "dirtyFiles": ["?? docs/qa/m15-numbering-20260930/"], "recordedAt": "2026-09-30T04:38:56.830866+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 52개(331,922,391 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m15-acceptance/m13-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m15-acceptance/m13-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m15-numbering-20260930/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,931 | `a73e79939799702efb8c3555110a64248b4b64087af02d3e4ff732c54d1eefde` |
| `evidence/chemical-create/downloads/1790743342790-26589-5-protview-report-10e4610d7f63.json` | 294,307 | `fd43148e7aabb97a69197ffdbeeac4de86a6e5a75cbf024ff5f7cfbf78928c3f` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,211 | `1d5d96b240149ab11a9efe46664da2b351a33733adb5d838018f521adab32e3b` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,624 | `ce07e9550b6eb2426138f3fda9e7c037a49f01789e92a8f5477852daf841757a` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,329,689 | `4f5d18b8efc5d68a8f469d10edec4ae01a439c5db7f4639f93d0d28f80935bda` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,637 | `2ca2d961bcaa36fdc3859fbd90e7621d20deeec7c684ac909c358cf5bc1712a3` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,967,926 | `5b4e905cbef07df88c10d762ca3bfff0123c266348a7b2f89339279cd8844c0d` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,612 | `665f6fdfc80db7a13da68d154e2b809b0236d99a7ea259e28241452b6444f941` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,555 | `06844a4c1a7d21cf1274c04bed2a57d3e825d82cf4a1dbfc05d6d2dd8f26732d` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,989,578 | `52dc5f4b1e3e296376217422e8e5902fdf2c6a12b2b767fc608b2a6b672e89b4` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,202 | `89e7a37a7d647193f6b4b735bb305a2e75617e9ebb693307ab9b00500879e79c` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,075,363 | `7d1672db918a7cfae8aa8d178c928a3ffa86016d27253b1414297a99a4eec7dc` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790744363246-31457-4-protview-report-8da9fcfbe30c.json` | 1,191,726 | `1a646eb19be44e2edfdbd183989e3f4ef1449c06f87fb57e6c622bcc566d559f` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,789,748 | `2f34a2fb3b1745a32d9d2c349eec67de82fdf6c952ab938b1c0f72fed6d9ddaf` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790744386971-31545-2-protview-report-f2d165d4ca4d.json` | 491,459 | `5877c29c28ad1811e88e56548d98182c5853772fb5943eeff04f45da041f5e3b` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,380 | `600745659e2a68dc42704cdb64ea8a61127f2106792b86acbff678a096105dcc` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,568,381 | `fb9067efc7f9d6237eb9b1d963b3fb33f6b2dd1a9c4bea188b7398ec9647e68c` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,741 | `1f2d6973ab0982939d3b9938087f8ead41c0d1af2cfe103fc15aba76b3cdc785` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,612 | `c401db38d0e0413dd639b2c2079ad185e8a3518938044d56523d37b7b8d60671` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,264,873 | `dc112115409658c6de3d61c35c745397c0b7e62d9fb7e59f89a7f1d3c8afc9e0` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,639 | `e4ff8936e85c29e1c2167f4dd5354e1a03f381ccabeb656f229e07966196647b` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,130 | `f381d3b3822a9447cc82515fbf03d0f495106ae5962c6a6bf87adc89a165196a` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,630 | `7e700a859cad5060754b795ddb133070151d4117e9b663cafe422743d755d5d5` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,258 | `acfe59a4fe75eb6d02d19d09024740b0f82f505db465b781e793dc7572d4b0b2` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,626 | `e235b116ec7b98c8d3b6cfb213a70cfcf7fde2c16dc695de0ef9c300381c45da` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,442 | `565ebbf97d7d14799851e86648339b4e3a159313bf028649e3438e0025cadd4d` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 800,030 | `995f3266003905061850715f3a79aa88a78f077e77521a548b10d9473e29e7e9` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 754,502 | `7e497f1638fbd286abd526a0a2e9b576c7d80fcc2e107dff31384b1a99685409` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 293,375 | `f1f8bedf2fc63f3aac569a0b0d3764027c462d6ff14aecabe74722f0ca35e06b` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,969,289 | `db4cb095d158aaf9cee252ddead88cb57e4d9c3987636b0c02503f1bdc9d0eb6` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,618 | `83c7964e0216e8d6cbb352fbca48671a4f9875986898783b52419f8412b3ce19` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,215,275 | `3ffc8a9908de82c0c65e73d07cabfbf47675e7e47128eaecedb548e54474d261` |
| `evidence/m12-acceptance/evidence/regression-m10-measure/comparison-measure.jsonl` | 324,062 | `f01786f364fc3dbd95fcd3856bfed930939b5231705d238a75dbe22a7add3f81` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,350 | `f71c572544995dd3637ef4c7ad2f62ee0ea9374eb697fb1b02b0bd9c0c2b85ec` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,157,318 | `2c4eb58ef188600bac6a1a152db5949a69c52de5b34b963b9fd48ca8fbaf31f5` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,894,924 | `20428d16a4330dde3dd609e6ab9ab6a574363dcdc76ced3f17d593da65db0aae` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790745091464-34967-4-protview-report-6e01315c9579.json` | 1,191,725 | `5fb45bf20f1a0710dbea7a88b2d05acc73a7a46c71c154fbc8d40d07c6b576f0` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,986,586 | `78852fe933411d8dc6215799f3d786880c8243ad821a285727a88e5b65259b8f` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790745113221-35030-2-protview-report-3b6ec9bbf1ca.json` | 491,458 | `29aee5ffa7d0b872cc38004edf88aa257a8eff3b0cea15085b1fac2b951fbdb3` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 1,942,568 | `b8e3a28ea520fc6520ea5269f024d52d421d9b49cf357403caed08a039debc0b` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,568,384 | `e27da596beb036fea188fa2f73c6f29c1a30b0f5a2d813ed45b8e24a2be5238c` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 539,905 | `ba62a3e440173b6619f570d637acde5b2be1c7e60a9d277960b72ec4daaa5cd5` |
| `evidence/main/downloads/1790743151853-25957-4-protview-report-5eb1111fc7ac.json` | 1,191,725 | `e295fd5be8031976d96a0e9e598e3e3fcf37464490cef129aaff9e3d45d86d3f` |
| `evidence/main/downloads/1790743162792-25957-7-protview-report-5d0b8c567969.json` | 406,808 | `cc1c74831d30b9f8ecee940d0ebdcdd2c1585a23513efd59b26147fb25962aef` |
| `evidence/main/downloads/1790743163584-25957-9-protview-report-4f0579fb6dcc.json` | 1,191,726 | `d28ebce96894ac04315395ebb54b79d75d3c5316d57cfeb561fda9733cd59369` |
| `evidence/minimize/downloads/1790743232959-26358-2-protview-report-88c1d3594dca.json` | 493,024 | `3aa6ebe33341a5bff0664f3d9d30f2b982b818bd1730f7f598ddd9c06f3d48a2` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,071,908 | `3bd4b1b3c9f467ab8c41945cb1c5e22d758e4e434573ee0a6278589fff68d2dd` |
| `evidence/regression-m8-normal/downloads/1790743483211-27563-4-protview-report-b5d9c77e645b.json` | 1,191,726 | `549d2545c6802b729709d44435af568be3fa206a3df47ecabc0cd74b23b3cf8a` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,916,471 | `5b15fbbc1393e7d7eddb097692a4f61e8181a13fc9d4e9a9e0e6c8d889649358` |
| `evidence/regression-m9-openmm/downloads/1790743510896-27714-2-protview-report-84976c31bd6b.json` | 491,457 | `7076c6e4bc2e0467d91c5222656b2017d01a98e198280931c49807a10153f335` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 1,876,329 | `5918f5c56ca265f1cfce8a8b9a31cc69212ff5275433366d7f3719309dec239f` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,564,568 | `a3aba255c918767538917725c72cdd3563b1e21e17069d60c41ad1b681c0a39e` |
