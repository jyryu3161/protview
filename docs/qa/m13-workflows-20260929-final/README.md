# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-09-29T10:58:42.789344+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "NUugf8EWW7h480ZPwlhqc", "gitHead": "e83071b7e74b42e34a64595f41f66fcabbfa68b5", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "dirtyFiles": [], "recordedAt": "2026-09-29T10:19:08.381298+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

## Git에 넣지 않은 큰 증거 파일 (사용자 결정, 2026-09-29)

256 KiB를 넘는 텍스트 증거 50개(합계 331,007,991 bytes)는 저장소 크기 때문에 사용자 결정(2026-09-29)으로 Git에 넣지 않고 Git 제외 폴더 `<repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929c/export-full/`로 옮겼다(폴더 기준 상대 경로 유지, 삭제하지 않음). ledger(`case-ledger*.json`, `ledger-row.json`)는 크기와 관계없이 남겼다.
옮긴 파일의 SHA-256은 `ARCHIVED-EVIDENCE.sha256`에 있고 `SHA256SUMS`에도 원래 줄이 그대로 남아 있다. 확인: `cd <repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929c/export-full && shasum -a 256 -c <repo>/docs/qa/m13-workflows-20260929-final/ARCHIVED-EVIDENCE.sha256`.

| 파일 | bytes | SHA-256 |
|---|---|---|
| `evidence/chemical-create/downloads/1790677370182-30684-5-protview-report-6f04ff4e31e9.json` | 294,309 | `5b87cd24413188b9473d88a09e525e4dfd0044e18dae161d610a0c1104e9a160` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,493,245 | `534fbd7cc9eebff3e5790e720494bd189fb913f6a9440b72223491c109e0eda2` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,612 | `1f38870eb824a5a7c75974222921898a2955db693a8851dccf87d58cd2d566f9` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,327,166 | `659038a7d40aa0bb3568ecc2b1397170d9a2c4959d41cfc4c2882efb21c86eb7` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,629 | `5460148207edd3b4e5b9f0ee9fe9c0ef4ff4acbc38832e6463b7fd0cb2472e77` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,968,316 | `3d3a68d0dbbb0844c7e13e704a94be74fb831de84d49cda8212883b03f3e0768` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,600 | `bef956cfe30fb0c00c484d72895e437754c308a9693aad6bbee9e4571538e033` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,015 | `1be0b8c4d34fc2a543dc07b17b1622d984d40705792b1aa7ef668fd8fd79ef52` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,989,459 | `7ccd445881e493f28e086b861c8b54ba0ae2662eb4f8420c0f8260d8fd55837a` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,301 | `0ff84e425a7d74f5ffcc284912bf735625f292f9b25ed8270df32b80148ad0b1` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,672 | `59f32765b80865861f5ccd8bc33ae677be78d4b0edb320d39906ff8ec246a548` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790678446001-41758-4-protview-report-9af70bdf65c0.json` | 1,191,725 | `98aef02c6126cdd6cf4e537af1df3d46177aacff036a2c3a44261fd9f3701ae7` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,461,729 | `c639e19af95f6041645878da0d72c1f14cc5d40d7bb0118cd5c1e64953d598c3` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790678475624-41934-2-protview-report-68b5e657a824.json` | 491,458 | `e7937544ae33ff6c2059dde93743542f98272feaaa127a1b62ef28a62e70a014` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 1,941,397 | `ded95f8d733a930753119cbcd53eee30592cdad2bb7e9d1363fb65e0551839bf` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,307 | `b846a9d190db6e9d8a339931a772b0cf0289e4a9778c2045f83bd69178bfaf2e` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,246 | `b7436b4223eb6a57393131e9988a7cbcf067a91a82b9fde6ed845e080b62e641` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,600 | `50eecbf6ca6f43f29956ff59cd34576b2b46c55d85d7761962e93c5d1ec1ece6` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,253,339 | `f93517c704c3ca02bec0f08825648b82e2bf54b805e008d4735d6cefc5537955` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,631 | `76c2e9e9a5039bf53302a036fd001cea24e5e542f04588a9bb9a2b381fe6483b` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,005,080 | `2fbbac97f9c61762974afa12ae3353017cea9dd0684b7825359adbb869db8964` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,618 | `d5d4a4294d1d2142ab7c3f3799ebbea487e988f81773606233efa0f73c88d687` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,237 | `7ab0ded93bb5d0840d3131751771e2484804cf37a5cc71e792b3b64070ec118b` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,614 | `474b0b37e822efe4978ca7bca43757e24171de06c0a147298c51c9d837d5c05e` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,309 | `6407b5bf84a9783d5c84445089dd05b51a7d7dbdc2005d3114ef3cfe7aa78a35` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 803,114 | `909002980fd544b627acf8302d51c00d0cab6aec26f0d715657da968bc7c9769` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 757,389 | `f9766325eafc4e0c848a8c0dfc0b533fbfcc18921f2de815fad38e5bd99110d5` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 293,375 | `4c6b77f9cd657dfb58dc46d02fd439252dc7d3770416db1c868c280edb7d25e0` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,969,640 | `f3480730ecea10f2ac9b11df10aca36ebb17a5717522e97ca0a4d7f9c27d21e9` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,610 | `f77c9cce94029d916daab3289bc03d45564442390712b4169da477e98f09a351` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,719 | `9ce56daa7552ceff6d4e8e69857b2ab9b4cb51b358fa3c6df94174bcc68bf799` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,574,179 | `dd667ea0f1e367e8625a46445a0febe986115a334d6aaefb8eda008c05ceea5e` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,156,565 | `57d2a93d3e5ce431fdcb49643cb864ad44f7dc3bcb0669ffbab2b6f701c2e845` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,894,902 | `43dbc2553471d300acc9e473f2ab1f42321424cdfbb227b3e0e7d6c2933e07d3` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790679254839-48620-4-protview-report-87dc26898e0c.json` | 1,191,725 | `a533a0685e397ba7872d6dba8ae3416640fe9f7b7eb8e0c2f81027b832f028f0` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,052,105 | `21c3c3310f51664586a2a62508811968604d226e09e458836135e61b4ac88f14` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790679282714-48704-2-protview-report-0f639e04aa6d.json` | 491,458 | `d39f26651d4e1c734a4efbffabb4bd7d69da33ea735246eb6bed7725b07ceed1` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,415 | `b36c084a91ba306e491ec21869ba8eccc87554abe6f383b8056137d47424a165` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,313 | `ab295107e363d86e25edf4c38e87841a00adbdead640dddc933cb1ea51266bff` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 523,739 | `303ea4945a9807c5be2a5321a77715207d8c0f8bbc17f36792cf3bdeb39ad16b` |
| `evidence/main/downloads/1790677165111-28981-4-protview-report-4227972c6744.json` | 1,191,724 | `4b3c5eb16d466f955b1a114096cea62698849ebdac0cf2f1eb05aa69d4915248` |
| `evidence/main/downloads/1790677176397-28981-7-protview-report-37bd5763b19e.json` | 406,808 | `69e1b47c3004480076f166be248af73a90b1107d616439521ba556f95d920e8a` |
| `evidence/main/downloads/1790677177279-28981-9-protview-report-a33564d0f111.json` | 1,191,725 | `bb7b004bdf5d8a9e0547500ea3d2b5ee880a8d6ecabcc5d5f04b7bdbd76f57e0` |
| `evidence/minimize/downloads/1790677250742-30451-2-protview-report-a7aceb2795d5.json` | 493,024 | `ac3da78105cc562c871bfd2456838af32b1d35cb42a83bacdcd4c2d408ae6b7a` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,071,219 | `a7e8ef6300980b1da544da800cb865de77e52e3aa6b310cf593ffe495dd9902a` |
| `evidence/regression-m8-normal/downloads/1790677514070-31859-4-protview-report-a8ea3d0530f9.json` | 1,191,726 | `30a722eb7ac2676337a22ad8456c59b5b104ba525f12254212d832787da7989b` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,916,369 | `d0344119f003c1ed98e46599de45e813229406de2b8cf47097840bcf60e0a10e` |
| `evidence/regression-m9-openmm/downloads/1790677539635-31940-2-protview-report-27a720f03a34.json` | 491,458 | `75877a015be04289b8bc783448644af603ed99c5041e97c51a59a6b7f587eec0` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,069,579 | `b374a1b02280dee456e4f4e53ba6b34e6cf3b4543a31e1294bb50d66d5d39f4c` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,565,497 | `51cd7b0dde0765a6f93562a44dbbc5c7378cf824ec266f94f42850d3c1b22486` |
