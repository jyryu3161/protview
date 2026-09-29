# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-09-29T08:16:56.579365+00:00 · verdict **fail** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "WCnxUsptjGLeenXzwlYhV", "gitHead": "d1eaf48243e26301528c7593780c6ad2b630583b", "gitStatusPorcelainSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "dirtyFiles": [], "recordedAt": "2026-09-29T07:38:06.617408+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "195c0cc2509700b5a090840b0fb1abda6b1bf7360af5d731050b02f8f05855f0"}
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
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | fail |  |

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
| m11-acceptance | fail | status fail; externalRequestCount None |
| m12-acceptance | fail | status fail; externalRequestCount None |

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

256 KiB를 넘는 텍스트 증거 50개(합계 330,975,167 bytes)는 저장소 크기 때문에 사용자 결정(2026-09-29)으로 Git에 넣지 않고 Git 제외 폴더 `<repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929/export-full/`로 옮겼다(폴더 기준 상대 경로 유지, 삭제하지 않음). ledger(`case-ledger*.json`, `ledger-row.json`)는 크기와 관계없이 남겼다.
옮긴 파일의 SHA-256은 `ARCHIVED-EVIDENCE.sha256`에 있고 `SHA256SUMS`에도 원래 줄이 그대로 남아 있다. 확인: `cd <repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929/export-full && shasum -a 256 -c <repo>/docs/qa/m13-workflows-20260929-run1/ARCHIVED-EVIDENCE.sha256`.

| 파일 | bytes | SHA-256 |
|---|---|---|
| `evidence/chemical-create/downloads/1790667700605-82935-5-protview-report-3a045155d3d9.json` | 294,301 | `75fa8644ae7f15ec51c9abde43eb5919eeb768a4a3f5020c8f4603519289caba` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,058 | `6548ac2d3ddd4036d97bd3f0ecda4c74fa8d87ace4a7d938e5b604613fd6acbb` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,610 | `baba8e59c8a4f69150c920099b691a190f22713b6cd0d02ea7703a2131b2716f` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,330,667 | `517935b5c7c97db9e85c3168a4623f95457fe68dd633444bcdd749129405ea8c` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,627 | `995b935a5edbd3413e25660c7f3f4c53afc7f4f198d12f0195fd973c9a5a7612` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,980,413 | `2db0ee2fa51b2b445edbc731d9b36912561c5d7e386f8f9181121976b5f8e09a` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,598 | `2adc414e5afe35d9089aff007ea6882a7fc1d5b8f982a634ece74ddae4636d44` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,570,840 | `599bc0eacc247bc71e510d855938ae55ee4b8487645d8d276652753d7ec0cdce` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,989,187 | `f4bed73022d6342d6c9144a15a35137b6b94ac05f0fa35c648fa7d386d9b6bc7` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,153,377 | `e087cb66dbd1670777495c11f31d69bf8275d00272d6d6c3d090042d5b16303e` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,530 | `31c70184cd5a490a3adc5ad7ca0b1e1cc637ad5ebe82bbe555dbd4741ea95c17` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790668774863-99596-4-protview-report-38f78f3de393.json` | 1,191,725 | `c4d508c595f6e15c43d95ce474a25953b55581105d9414251f5e61e6d3462150` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,723,716 | `17c1729ae534104cf26b8683d269b30172e4172b97621f7c5468e3bd2fff29de` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790668804218-99774-2-protview-report-e862ed3f7620.json` | 491,458 | `3ee663e8161ad805977b600203e09c31aca6a31d2be0c7465e8cc866f2edc644` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,005,766 | `e0b7f606c77cbc7377eb7a7103985e3aa2c96963b8344be1bb9e4ad644d3fdb0` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,143 | `7449f0d955044a59bb02e6db5a7165c809e376e7fdaf12a288ab6032ee4d6750` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,205,184 | `565e5a09eace3270a3c6bbc3775be3d3a8290c1f0bdabff1be29a08338397682` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,598 | `957c1cd0c88b03b3528c10f7d846d6d6c1b60b0c89efcf07e4ede8d80833dce3` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,265,095 | `f7af244fcc941f2343fe8d452c5aeebfe68ced0457075393b797b8b1260543d3` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,629 | `64bea96df07f599ee31919f86fbce8eca3d27cc43933956562bbee68ac3c4dce` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,001 | `f7cba3d66be393d477b864be60d479f2f6fa665070fc68f70a8277b9449931d7` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,614 | `7754aee73f5c331ca00a30c79bc7cf526ee27fc96237a74e63c2dd2a8a1f29f6` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,206,173 | `bee553de51d3892df9303114fdb2bf82ba6075895e1d68f9441f9aae0d3bd8c2` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,610 | `2d0e73bb13bd8185daa5e0d93fa2c606ee3bd83abd19efc3c6bfc927b0ea9ef7` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,308 | `28827764de64037eee18a71782ac93afb136a14ad53b0c8cf3968606c66e10a2` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 799,902 | `311a37f2a832d7e16edf9552f9bf86ac42a5c5ad928aa65af120d5a0d29b1102` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 752,777 | `04d9d08d19df19f82dca9f3cb5f670e69fee73544513570c3c3f18ecf4c66c1e` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,659 | `d4004b8b082c70bd3647394b65598ed3967a9c667369e5240ffc9c8205e79e8d` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,972,879 | `da26dae633cb22f348b3dea5a47cc575836d6edb2c4b539042259ff4586453b5` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,608 | `749a10335fae22ce8682610ed89cc0f7337bf8bf86f19c9c05f9cea4a999d1af` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,516 | `a87d433d5d609f765145249c2f02d9ebc829fe7513fb19aa39d9ed39130218d8` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,893 | `679351c2da01a1d39cde178c3143c51490d06c0167f47ce511e703a65cf7052d` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,157,708 | `fba34a196bfc7c22bb2b4f59f0c3dde43e366c3636d5ee0e676b25f1a71e70bb` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,894,634 | `320e4b7dc385e664c7cff3c224765eaf27eafc7ea1e313fb2812abb9bf958a67` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790669558600-14289-4-protview-report-3d117471519d.json` | 1,191,725 | `ea790fc0f8025c8f67b339d343b0b1b62a90123691ebe7397560f9dac530e8a1` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,855,217 | `8ff8f0aee85babc30da9fd9306da2b3c68624818e5c2e19c7d0c8982eb4ec13b` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790669580860-15385-2-protview-report-907e678b7144.json` | 491,459 | `1fe8afe56a836c556b7e61e5a49f862a866c461c3a055056f9de62aab7fa4f4a` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,006,914 | `70023d4796591759f0c56ed233b7b2984995ab8bc017ef4ff37ae529ba0db43d` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,151 | `4f9fddea724d93c849301fc6bc7896248e7b385c3de9fbe7471ba1f37eb905f5` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 539,495 | `97ef90e5d13ac9f258e0b3b82decd14cf0524105ff6b85d444214cf2a408168f` |
| `evidence/main/downloads/1790667504140-79330-4-protview-report-726adfc03808.json` | 1,191,725 | `933540581d27debe63cd2e199bd102a74568d301a9dbec406032bc93d103dc21` |
| `evidence/main/downloads/1790667515440-79330-7-protview-report-c76cc672d64d.json` | 406,808 | `cac99d909d04c2aff46178224ea00aae574f4895dc26db576e9971a118e012af` |
| `evidence/main/downloads/1790667516243-79330-9-protview-report-13cd594781a7.json` | 1,191,726 | `a425addb76d6244d56d7b8ff2e0e7075b101b5b2fbafd42e006514ac2014384e` |
| `evidence/minimize/downloads/1790667587279-81345-2-protview-report-005b63b54541.json` | 493,025 | `42199529dc3a7ba5acf24b73a2289dcad007ccdffdf8df16d415bd506b3d8ccf` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,071,077 | `f2c1d786c2e787151175204f212ad3decab9e8d9fc27ec32f761c70ac2f17346` |
| `evidence/regression-m8-normal/downloads/1790667839453-86063-4-protview-report-e87a4b9e298c.json` | 1,191,725 | `4947459b8a46e8a80d0f6d5c7456cb1157bca7415fbba7b6152a4991e2ba7abf` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,785,036 | `7ae27fd95d2a0cfe60eafe68bdcca1c75102fc37ea4e5f2e9b3b373fb19140dc` |
| `evidence/regression-m9-openmm/downloads/1790667865998-86135-2-protview-report-12e088148b69.json` | 491,458 | `c4127149c91c31a10cf106b6e7d4ed21a59bcea058cb72fa341129d726410adb` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,069,495 | `de4662cf65a22ea0f319dbc58fea653bb46a5e808ae7b5a14dfded951823424a` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,565,327 | `e2c33bff44978de2ce73a2b30bc97e814f0245129ce61bcc6cd4b1ae3810d338` |
