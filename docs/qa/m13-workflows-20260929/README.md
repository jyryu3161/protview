# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-09-29T08:59:19.065563+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "WCnxUsptjGLeenXzwlYhV", "gitHead": "af1500b60f93a4fa24865f0e059ad2abe70b8126", "gitStatusPorcelainSha256": "da3cc300ceb34bbc311c729f22ddf41b8d8ace620115c334228bcd6cc6c51ab2", "dirtyFiles": ["?? docs/qa/m13-workflows-20260929-run1/"], "recordedAt": "2026-09-29T08:20:54.453118+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "231eb9dd0ce628b0e882671e0da8638078b531ff4e83dc7756ab416f0744f05c"}
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

256 KiB를 넘는 텍스트 증거 50개(합계 331,398,166 bytes)는 저장소 크기 때문에 사용자 결정(2026-09-29)으로 Git에 넣지 않고 Git 제외 폴더 `<repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929b/export-full/`로 옮겼다(폴더 기준 상대 경로 유지, 삭제하지 않음). ledger(`case-ledger*.json`, `ledger-row.json`)는 크기와 관계없이 남겼다.
옮긴 파일의 SHA-256은 `ARCHIVED-EVIDENCE.sha256`에 있고 `SHA256SUMS`에도 원래 줄이 그대로 남아 있다. 확인: `cd <repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929b/export-full && shasum -a 256 -c <repo>/docs/qa/m13-workflows-20260929/ARCHIVED-EVIDENCE.sha256`.

| 파일 | bytes | SHA-256 |
|---|---|---|
| `evidence/chemical-create/downloads/1790670267466-31915-5-protview-report-26cb0bbb9353.json` | 294,303 | `442c5b7290779a9fa67f7f3b3a61aaa575c37c6a94d59aca8b5304e30fd1b26d` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,493,114 | `5fb9297bfcc80bd66646aff265e2fd3e034309de3088b8853857728bca93be94` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,612 | `c6da4d3398571ff3ed1cb384e5d1a9402af17f685613e420b09e7e9362db73fc` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,327,568 | `ad81d6c9496bae9c88191594a6ea352ff69171f58b8c018b8c1d06c1f05f4ebc` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,629 | `a0bd87ea5e47f49e88582f8b089ec20cb544bb05c853766bfc88aa20ada3f954` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,968,226 | `670732cad88900ccfd6f17ca8b0cfd348eb8c02273df8dd54ca7f31c243cd548` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,602 | `b7bcc22f1acf3204109d3b9b6fdf5dc9772845fc69a937a05b4a7c93cca379eb` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,980 | `4bd706636b8bccbfe4421200c3a1a15e44c3ef6fb739e99d74ede06a1f52b76b` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,989,406 | `0e56287d09390ff0b71653cb68f8ea5b3010ed36bfd176153bd3cc930e5e4073` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,153,378 | `d96ae0113a6e6b3c8c3d43970e2baadfc05038262c7414a1fb20464d85385450` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,709 | `b7321e81c0fcf4febcf4e02d885e017a488c2bbb90900a7ab9d695e4c93879c2` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790671369980-39936-4-protview-report-866c0fae90fd.json` | 1,191,726 | `9c3ac6a5c6b56b2db407874da607355025f3cf80a81905a85d399e1dc763ecba` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,920,638 | `d45f363cd343857e63aaa630c9a2106c2792d48a7eacbd7f991265d7952c4623` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790671394959-40116-2-protview-report-49fdb0fd03f0.json` | 491,459 | `ae6bba9551f7793b083258e46ddf2403ba1bf2dc9431ae4a05fc7034008edf6f` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,425 | `03c521c770f0ae0eac3a890224a320d0d6f26ca3ea1f2ce7748bbe1a70f39513` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,303 | `80662f7196baa355ccabd00160bc8f30bd45de584a1cb25c8e138e5cab0f87b9` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,274 | `9eae58557e25c688b8ea0749a496f039e76eb486f31b07fd622da8f001d05359` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,602 | `6d8d971f4168ce0a52a564a0b1539eeb7d2581fb0931a82311941fd481dc2697` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,252,298 | `85898d3e9d565b95db383703584e76ee5aaa286681554d5c3a47b9f4e84d7377` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,629 | `d553083c88dff30a604414dd2feccfb6b7c08f957899a8b5288fb401125a294e` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,005,044 | `8298fdfd1ab596ae0784c9f18429d1fbb91eb9ea44a21d4b96c56f9e902828d0` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,618 | `d32a260c3f72904a204328fa48caa9a1e58d957f9fd2e4c327dcfcb8fb0a54c9` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,265 | `5f7d1441d59fd6c076fc6f1edb7e5a1ea0f2a997f3af2755a700a26ac1899d86` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,616 | `9733ef77bfdfe83b9935c45c4cf18e9e62b2c2278e306220a24cec9116971565` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,311 | `fc232c52b98633dfb4f77f7de8f21a247997dc4e093dec43719ba722dc5aeee0` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 803,081 | `29e75337b04400358ee9b1630fab0c0b967dbc354613af225ea9e6b9916ed603` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 775,637 | `d66a6e8403577fcfb2e7119c7eaa812a112c41fbde0381093b257fd3c93e195b` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 293,479 | `ac7a9cffbd2e9b828d3b9e7c801aef15bb019d52c64e7966f71fdfcd614cd8e3` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,985,392 | `e5305eb6a2fbc176da99945cb00c4251e0149924819731287ae5995cfa02f3e8` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,606 | `739c1daca45a25426b6ccd2f01df903bb7a01512e5d6a0d1b037d84cf3fb2cd6` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,701 | `bc9b2e43715e901371ce5303adfcee964872477c21fa0165743502414035c166` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,244 | `b5ff6206f9b83f216e42b3c1444c0a1bc39a9adb2d99f699f3d7fb72d90c3fcc` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,157,386 | `1198de896b300ab2a168c13742d986253168da9398eaabcef25b8e107e11635e` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,898,848 | `da7649bd6c52fa75fe02ab922a0a8cab127a74d4f775b4299c0739ead775e981` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790672116595-45381-4-protview-report-2eb70d240e1a.json` | 1,191,726 | `b2429522eae43c6299568a7620a876cf860b7a680f972b378f65eeccb352d989` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,920,928 | `0b48698ae79796cf219bb72368fbd8e82e78c6183a82dc653d80d86d00450c8c` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790672137962-45446-2-protview-report-17e48deac64e.json` | 491,459 | `ca3c04496bcd93e8356d8048abacf53027ad58bd5d6631df09724da4c030f051` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,006,985 | `e138e55499dbeb22347267e277716dde5d53b90880a74f4333b5dcb2bef24cbb` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,302 | `27f7ba766dfc3d5f4722e3676bdb6a58cfd4ad6f8559a3d11b9db20e53354349` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 547,039 | `5cb96002c6fd88d0b57db9fa3d857c9ec75ab4570c5dd54a9e39ddfee7c60949` |
| `evidence/main/downloads/1790670069722-30768-4-protview-report-2955a6574052.json` | 1,191,724 | `c6c9449d375825fd544cf7f845cd14b0b825f07900b6123320365187f563ab19` |
| `evidence/main/downloads/1790670081854-30768-7-protview-report-8cf11ce5bdeb.json` | 406,808 | `33fdf46148cbd8060964c94909694fd532ae10c49f353a599e2dd402e9b1ee85` |
| `evidence/main/downloads/1790670082661-30768-9-protview-report-7b8627c69ac5.json` | 1,191,726 | `5659b75ed4c9dea0692fa591a6b0b015879600a60da160d7454a53a2890b3764` |
| `evidence/minimize/downloads/1790670152911-31648-2-protview-report-0a08cb4c36a8.json` | 493,024 | `d67ef4577d546281ad0584c04dc2c1cb0323638c5b931164863c6283d475c0dc` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,071,231 | `75316f4fda4bdcfe44d497903cb1fa0b6f06feb0ccff0d082cdc8feb69bcde33` |
| `evidence/regression-m8-normal/downloads/1790670400710-33161-4-protview-report-b4e5322ab42f.json` | 1,191,725 | `bc9b1b9c175660490d6a6a7b05e3f1a655ba0ce5b9c6dbeaa957a7e6a18b47d1` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,916,254 | `da11de80d48501e742ce07b0d5f54437e7611b9989218a73c7366e55f6a83c01` |
| `evidence/regression-m9-openmm/downloads/1790670424105-33311-2-protview-report-c53dd797a7ed.json` | 491,458 | `5c5159751f2705e78c3623b8beb9606fc151e92f2f35a3f34d8afecf89f4f595` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,005,177 | `9146bec599f495cbd4f23426d8db8ae0c541f2bf2ba8155cf04adb0fd9de3bb5` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,565,491 | `b48906761333149c1c7129fada91a0d808c61d5ad701ba0b7d793076bf952226` |
