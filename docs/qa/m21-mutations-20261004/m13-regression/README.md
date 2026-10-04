# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-04T04:56:52.604923+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "AP8FpT2CpFyqfPjUEREAR", "gitHead": "4a3dabe51af0ef8b6328bf7f09fa7f719e4ef7e1", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "fba7de238d6c9ebc2e83e698a7aa787058598fad7fb2054d50df562910c85591", "dirtyFiles": ["?? docs/qa/m21-mutations-20261004/acceptance/", "?? docs/qa/m21-mutations-20261004/gate.txt", "?? docs/qa/m21-mutations-20261004/m14-regression/", "?? docs/qa/m21-mutations-20261004/m15-regression/", "?? docs/qa/m21-mutations-20261004/m16-regression/", "?? docs/qa/m21-mutations-20261004/m17-regression/", "?? docs/qa/m21-mutations-20261004/m18-regression/", "?? docs/qa/m21-mutations-20261004/m19-regression/", "?? docs/qa/m21-mutations-20261004/m20-regression/"], "recordedAt": "2026-10-04T04:22:06.129900+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(331,886,193 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m21-acceptance/attempt1/regressions/m13/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m21-acceptance/attempt1/regressions/m13/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m21-mutations-20261004/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,916 | `0d726e1f5e7c89c7ebc1bc6e7140e94ab4762601cd728031dd9650f7adb1a78b` |
| `evidence/chemical-create/downloads/1791087923633-8512-5-protview-report-53ae814dfe11.json` | 294,302 | `7280c9dc0c0c8e440901ff568a0f7c6b4a8fd6bc02a588c9a9e2dba03417b614` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,489,200 | `3f890ca122bffc17351597dec9d1e726a98aef7fa3bb328916ce1f6e62af02da` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,644 | `e5b0a80920a36dba7b7baa9ff53526976c2400ea1a4c952741d74b08c4ee22ea` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,329,872 | `d2cdf3f311774f1081629ae880887de70cbb0a57323a3aefbe8de32c011484ee` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,653 | `c09bfaa958675e82ca0194ce43186e1f0a15d1b7c8a3313ad9c7bf895887d273` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,970,371 | `c87801f63f069b4761a0230c184961279bc84031559de435cdd5dc7c991fc2b2` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,626 | `fd902c2d41e1a64b10532b8b1c12ed201ee49d0e37987ebc51c8c7c15dd5b18f` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,826 | `6e2af1b30c07463224e6399b417e2268e280c07439ecb8869153ae9a8b1e9863` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,371 | `5293aed9f6f2c6f9092818c55b0ecabf9743298165e83974a8af6004b2656039` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,064 | `5456bcd28c972444c51ebc9fc0418d8b17c3f07031f9698a2b9febbd24e4f049` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,714 | `a656c07fa16226983d68402dbad3e1255f6949a0615b7a642992e5bab14fd779` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1791088884252-13242-4-protview-report-ca015177b4f3.json` | 1,191,725 | `931733115b505b9cbcd606bd942909c14afb6b3fbfd1fdec979201ddd96c6da5` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,121,209 | `6941c0f564aed13f1b76c2b571f7ed3fefaf85eb41983ac9ce6e8557238a30f4` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1791088910995-13316-2-protview-report-95f424891f1b.json` | 491,458 | `8bf9a1de7bda3df564301903a9089339a716f5f4b30e6cd83b1e9e31a48e9c29` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,073,625 | `f8a3c9c993e79d6636124c242269a05e07c6ad00a58dd538765627e9d28303bc` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,202 | `ff86be462c65b8cb91c12ed25792644ff9a7ebdeadded65c1d0f104b842f9188` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,692 | `ebe97d026c3e1e9e85bb1e8a4ccd503e55ceceb1489d515fdd634b4949609469` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,626 | `fca81a74b2b243fb3ab1e83182e8341c3a23d37a00cec33138100ebd4a463652` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,266,392 | `f6618f4040f3dba32748252f0d4c6a2f2df7ded8b469ff5f53037dc1c83a3720` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,659 | `bdff8e608b6a96c1010f597b06dfe7adce9848a9c1b5928bb24ed18b23c51cdb` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,538 | `4d8da5429dcc67664de0b0c67a5a184c6630c87fe3be51cfdc8134a9fbc702ae` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,650 | `76984f373ba6649c5078a56b28a27a64745e4bb98997ba16a3eff79a6969be69` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,365 | `ec36051411c4a8235d27e4b5db02ad9098b35ba311a67099257e653b5c47a938` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,640 | `0575d0901b160c502044449f29b81630f96a13c71c85460db2db7913dfc56e6a` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,449 | `175ce506af5d90e379949f0f90544ef8de0a7fb5118352663c22a57fde657998` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,382 | `a85d81ba39af38b249f73d8b53c1c504858fc989381672ae1eb417b1bf9c468f` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 764,139 | `e51855462671faf132e541578aa459cb468ce1afa03d15f7bdfcdff7731af96c` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,799 | `93b215ff71b514b1bcfe16f1b302746b0db135a9976aabc87f8a549dfcba26ea` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,975,070 | `d0d8e05922a49d24cf39fe4aec1cb404686ff28a09804d8a8c2052b1bf1418c8` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,640 | `9afd0a36c5bae6e20d6b27b23d3a21ebdd8805df5768921383e02027bc6ff189` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,719 | `8a48e1467f6637e3aadc1488bbfec05e133c63ede2dc7995634bb9084403ad23` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,574,668 | `b318063c11e464006250e76946cf392e583f169d9eed86a00630df87fc410d31` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,153,931 | `8f4b8e04f87d4dc1bd5f82177468d5115de110ca60276b7284e164432ed97263` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,895,175 | `828bd172e9924b63184d564f00eb6f733b6ec166788c30fa4e8ef3d56009185f` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1791089568013-16530-4-protview-report-765138c77578.json` | 1,191,725 | `8b332b0af2f4d8ef3e62e62731f47ec9a9775220547bb52c77696dcb64622ca5` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,926,913 | `dc33b479eda70c3d62ceafbcf84cc6c2011edc8c2a094fbe44e385678e78bc8e` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1791089589529-16658-2-protview-report-a6ffe7e50b12.json` | 491,459 | `08f28602c9e178f03a3b52dc2f04d97efe6294e530bd57e3d0fd0455d7793894` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,009,240 | `208d4f222b148b0fd7619d66a3c397ad6baa5508e6c9cc38b20d950e0ae3b7a0` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,205 | `142b216eeb7129061c07df0b403c67335acbdbd6484655159c4335ead41be088` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 557,964 | `d312447e683cdef0ed5639f74fd140a9a098646fbda18720d7eea6e2b4c21b2c` |
| `evidence/main/downloads/1791087742016-7945-4-protview-report-7a9edd538199.json` | 1,191,725 | `baf3e28536ad05a097064b32af38c0cfeeb4acac5461cd1abcacf42029d927d1` |
| `evidence/main/downloads/1791087752495-7945-7-protview-report-935ce94cdb64.json` | 406,809 | `d88a471c3b691a19c008c0a034d1628b5cc3a5b0f4ae071f755bf31d12be7f36` |
| `evidence/main/downloads/1791087753273-7945-9-protview-report-ceb826f08131.json` | 1,191,727 | `5bb37ebb8b9050d1799397744cf977b5314e8699f5eab2d9c281ca98f9ccb1f2` |
| `evidence/minimize/downloads/1791087821554-8278-2-protview-report-dbcbd3a1d7cd.json` | 493,025 | `af40b54afd06604b63fe242445345fe73a060bfbede2db687f45b9e4575daa8e` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,095,925 | `705075195ba3e72576aa33ee445594482314cda544f1d20ca72c02b2dfc65281` |
| `evidence/regression-m8-normal/downloads/1791088045172-9637-4-protview-report-857d1f80adc5.json` | 1,191,726 | `c7d7bbed18a796ab1cbbf948634e3dd6a72fcdcc53c8c75f4cc8ad1916c57f7f` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,856,649 | `ec89dde9f51ca33c27a68d903c87e417b95323ca18b292c722459ce13e2a0bab` |
| `evidence/regression-m9-openmm/downloads/1791088066411-9692-2-protview-report-62446b1aa881.json` | 491,458 | `15a6a1242ff1181d6d75ff133fa30c646e388abffaeddfbd996f2bebc18bf0a6` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 1,942,963 | `29e82a1fb370afe6e627455dca4bb817815ac7e40307e865e3a5da6ab5fd7611` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,368 | `a4991b99cf120c3812f22c8d35658fcf7f8fb783385fd83155cbc9a5d2477703` |
