# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-05T13:01:46.796180+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "8UVqy3iRzm6o2VSKemMX3", "gitHead": "7871e83ffafbee001eb0f849595b0a59c5615fef", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "5ec64afd84f4d3f5cef77e5b850c085d975822a5e22526ced364661d1302f292", "dirtyFiles": ["?? docs/qa/m23-sequence-ga-20261005/acceptance/", "?? docs/qa/m23-sequence-ga-20261005/m14-regression/", "?? docs/qa/m23-sequence-ga-20261005/m15-regression/", "?? docs/qa/m23-sequence-ga-20261005/m16-regression/", "?? docs/qa/m23-sequence-ga-20261005/m17-regression/", "?? docs/qa/m23-sequence-ga-20261005/m18-regression/", "?? docs/qa/m23-sequence-ga-20261005/m19-regression/", "?? docs/qa/m23-sequence-ga-20261005/m20-regression/", "?? docs/qa/m23-sequence-ga-20261005/m21-regression/", "?? docs/qa/m23-sequence-ga-20261005/m22-regression/"], "recordedAt": "2026-10-05T12:24:47.413579+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(332,086,790 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m23-acceptance/attempt1/regressions/m13/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m23-acceptance/attempt1/regressions/m13/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m23-sequence-ga-20261005/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,919 | `9cd95004eef0fa2dc07b13e2dedd65b01d76580de8d19e7b9cd763b402153424` |
| `evidence/chemical-create/downloads/1791203284143-70807-5-protview-report-d24ea0fa0fa1.json` | 294,300 | `7dd59186452aa8798cd445dad4298f7d621ebabce645f3ef8e037f2eb5f776a4` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,308 | `dc4d57151a352dc594deba265a6eec5cedad17780d3831db0083a9ffbb2b2b17` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,644 | `fb1374309733b8736169289e1411bcbd452ec0eee60335ad6cef974526d4e20d` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,615 | `3d9e95cda650df738e70d0edffea002ff241c42d532842888d2951e743c6a54c` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,661 | `b4b346c0503a4a434a5c8f6607ef740838fe2f912d94a4111be71540f98c9f1d` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,984,351 | `ddd90ee6a98170fbb866a596888088c69a3e2899d2da8c0e03e62147e295d565` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,626 | `750ae4a23d4233ad9030cced246501c6c751da638f4f2b0e21518f64e4b8e6f8` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,666 | `66886f487f69d8dc2c46851c6eefaa4ac5f1da1f5d57e7132a3c2c93be4ae787` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,425 | `eea852ff06d84dd57870fd5ddc9464b92da2de4fbbec6d0ce4727acd0d0f9edd` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,209 | `37581652df024359e94277e3f7714ca3b5cfcfa20e89c9976601b200cad97429` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,703 | `c26b1524e5c3e5d79ec985dc4e02ec34e407e13d7c94d4c689193974e463fecb` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1791204273949-75455-4-protview-report-afb1421404ef.json` | 1,191,725 | `7c7eb155604a3e041b44e1ea2aa475f15d887af2197883c573cd0b357f7bc146` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,991,223 | `9b861091d5be11dea644c7257a3bc71e07f0dca9e37759f7da90aab1604983a5` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1791204299096-75527-2-protview-report-d4fde9d32292.json` | 491,459 | `faa8b799bca0696e8b8889c831ba647c7edd862693bbd1e98c582bc1e5cb1b7c` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,073,607 | `41e0d7d69b99eec630b30a5803e4e821eed31b7659c7901b3f7e390af174f9e5` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,204 | `ad9aa3854c04daabd12dc8944f10557340df4daa4305b36ddd913f89df6f70ac` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,205,753 | `e2ddd150170f89a1872724490294492c0e1a05f913ad779207ad4b56edb67514` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,626 | `2a0dcbb671d9401c24f32868d86299989820e2b0f377f869c5a42bd4c0ea5a33` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,254,920 | `73481be3d4c0cc0bff5c4d155ee6f03ecf75ca8e8370eba67e7f4d5a8d7f58b5` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,659 | `f055b5a3ce643a94582027c0cbc7fcf5830c9055cde205229586b6c7ae70be48` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,632 | `3fa8685b4b2d9509e6230bd776e58daddccda57736dbcd14b7c499d596c64027` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,650 | `29439e4c5dea1f09e24585a067212b29e59c80a424c0423b5611fafeaefc0ee7` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,206,426 | `6e2e766bbee1f6a15e9024a0b638553be637d8a6299edf17ce5c0df2b36008e0` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,640 | `8458fc1da6258a12992f550f45c9c6fda72d4ff55f76930f75d75002e48f5530` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,614 | `78aaafc65bf9f974ae24b0f8317de00f39627210c5e20d71a8fb5d9b90802684` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,448 | `7f4ec2b097cd74b8494e801044917626620272866cbbf8c13c33831051e13ccb` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 765,527 | `afc11e085783339d109dc6b776cea8f5908cf77f688faba79d6364fdf68fcd63` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,907 | `fb17c6f190740975c78eb8eaf9a816fc34268cab4627a6645c96ee3537efed97` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,974,807 | `942d6892cb35bee88db0cfa6a0498941c7026a565e29df81171a89a3bf404dad` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,640 | `1c122c58e709522f8d83dddbe15e6c204c1ce7e888e9821cf9749fe933a3eee4` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,689 | `7e914900500a4b891dda51aedfa4ae024ebf87dffe01fabb91abe4c977054508` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,577,454 | `21729243de69263587d5321634874616ecf5b62b247f4c17442fceb22d6a796d` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,159,429 | `c356c8948c35ec5c34862b4cecda8f6b4b8b7d0173fcf2515457b94f6ae83874` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,895,296 | `0c5113816fb02be1c72e973d8e00f5dc028645c82c4122a408a688141490c533` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1791205048390-79081-4-protview-report-a23f2ef4f638.json` | 1,191,725 | `503dfcd1c77558173cc29b006458c02e823ee521924e50d0ff8df2eb18c849cd` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,926,926 | `042045c5ede2a4bf5631725e90ba5bf358c7964b810e3bea22c179260cf50093` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1791205069362-79137-2-protview-report-2008ef799f84.json` | 491,458 | `e744010ab0e036fdc27eb8a484de3538f2a12decde913fe72fbcea098abf9ac2` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,009,232 | `79c424f8b571b826ef9c5b55bb63a38ffc0f6ee1ec5c34851a3ad5cfc1d3347a` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,205 | `d09d0c3f4980e063a0d91aca5b69548ad9aa30606e2116f041f1105156fc2406` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 567,089 | `28b8f6f11c517fcbb530e9fd0e89422165d5f6ec0a34ce02fdf8d31d18a474f4` |
| `evidence/main/downloads/1791203104319-70267-4-protview-report-7c0ff685bc01.json` | 1,191,725 | `2b7e394aa34250669285c591ca92798ec96799c489c911b6ce1e73fc49481f04` |
| `evidence/main/downloads/1791203114793-70267-7-protview-report-e5872d585e5c.json` | 406,808 | `42122bd0b14d85d4af5da40f7528246d97916ef2719bea384fb035bb9fe54ad2` |
| `evidence/main/downloads/1791203115538-70267-9-protview-report-8363e33b0d53.json` | 1,191,727 | `0ab21b990a1b4a57d8baeb815e6e3f4fd22b968a135b746645c37da75cf8deec` |
| `evidence/minimize/downloads/1791203182638-70653-2-protview-report-0fcfeaa3eae9.json` | 493,025 | `811cdce2f096eca08225e8b542abca4086a555078505839cd12ebae0083847aa` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,224 | `7dee5de57fb0e5fbe01e4d790c7b08b388bc4b778723380101526041de952e3a` |
| `evidence/regression-m8-normal/downloads/1791203405415-71698-4-protview-report-4f1391be7a79.json` | 1,191,725 | `f567d14388f9148d76dd7d4687b3b9331ec201c2d53824eb5fe3ae9fd306d28e` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 5,053,531 | `d48641994c020a7fabf1e9c5fc9a3881b1531d41dc83c96fc1c16b30e726a8c1` |
| `evidence/regression-m9-openmm/downloads/1791203427393-71816-2-protview-report-e7006d31bc4b.json` | 491,458 | `3993f183237b40fd6f9b224af52ef6d30c6ed7bedc72577c30b1dd1e74a34cc4` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,778 | `5215b3e58e5650c73605bc9de9a6cda896c94f010ac8422ed00fd5cda07d01d7` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,392 | `99e8dc1b915a93b5564e64db3cfe0394076db02e099f7037545321db7d603fa3` |
