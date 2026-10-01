# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-01T11:17:18.384960+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "sqA-QDPAIvtGu2INokvMg", "gitHead": "e6ab4f9b82808aaddb67c1e2d53ef80628dc097a", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "98f37b608faf8278aa4807d8e8e6fd57fe23deb43577444e5f6b087519cdc7d6", "dirtyFiles": ["?? docs/qa/m17-ligand-20261001/acceptance/", "?? docs/qa/m17-ligand-20261001/gate.txt", "?? docs/qa/m17-ligand-20261001/m14-regression/", "?? docs/qa/m17-ligand-20261001/m15-regression/", "?? docs/qa/m17-ligand-20261001/m16-regression/"], "recordedAt": "2026-10-01T10:42:48.694352+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(331,948,097 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m13-acceptance/m17-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m13-acceptance/m17-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m17-ligand-20261001/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,947 | `aae8d04ab284c2657802c71ca8fd54ec1665c31dd780dab85940bd9ee15dea31` |
| `evidence/chemical-create/downloads/1790851561731-83774-5-protview-report-d72a3f26db04.json` | 294,309 | `c38fdaed6e6f2e96743d3787fa0827ed50df25dd33440a66db155406b87aa9b5` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,870 | `1592aaf8c367bfd7c45456ec14f02a14322ed95e49e6d415dc41183733b80ccb` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,626 | `045f3ccb7c6243af0e609978886d92ea57ed2654296428cf27b6116a1d6fc68d` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,502 | `574d5aec8c6aa80b8812bbb8c6c99495215c1a5dc4ba771408a53d764e01804b` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,639 | `3b4f5a55e53764940b02319a805a8a85caf5da142d3c18124f355861d7164217` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,981,465 | `d0fd89b04f0f5ac2971c6b41b5378756f1ae7536d48c4a482351fb8a0ca8005f` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,610 | `0963d08e2b340c51bd2cd61b98766d050f9c592d021179b1861fadafc9f3124f` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,600 | `3308a9e2daec5252a5a92df66d9ecc6a9f3340fd6d1fbd8d34099c14af3428eb` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,312 | `d01224e4bb3de79e038cf16a101ad9a9f8404c243539c039230254840681e978` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,054 | `d0751cd0a653b1c2208d6ab36c7f520beb60e1124230d5191764bc5a607a953b` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,078,242 | `86cc2ddfe27fed69a45d33a5bf66b7a0fda58f4c1340643ae5317d45f7896ae7` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790852530687-88494-4-protview-report-e0a082d506a3.json` | 1,191,725 | `ea5a9c5053b7f8004d23feaf28a5e2006d91558dcf8995f058d318206eff50c5` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,924,954 | `14934134591076b02639506a28259a7f9ecffebab5e190f303b2405ce697ab97` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790852557106-88570-2-protview-report-dcf4ec68c5b5.json` | 491,458 | `e00c09af7e41ef31e3c4ef14afd70c8ad7423ff698cb7ed58ffa3fe4294e1f2c` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,072,865 | `2a19f464444710177935845b34ee38851e49d9ef49f32f04d3b08086be82b4b5` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,617 | `6b1c2ac20d0d77307e50a93cc7d4a751fed9bba6873da1925a09d96a8fc6a38f` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,205,711 | `5908f59ef16cfc65cfe58d3e989e5312933cdbdb92192e996aa388f24dc90130` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,610 | `7cf43f0dfcc6a6e8903f24137d27b4c5ad7e5f79cf62a7fed83903a5f63c5845` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,254,522 | `bff71631aedbf8834e1a3f3ca49868929beb06f2de0aae3de20cb0227c78327d` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,641 | `ccd57a3e8712281cd0a018ae9c4040eafb28a3c9aed50a491c2c5372d0aebca2` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,484 | `8958e5cdd8fb7ddd591d87981d923b9dcf8ae228a65f7212c2f79f189fc97281` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,632 | `e944939381c6d07caa59e81da9102c09b107d38ed54077159f44bf6f4ea9c59c` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,206,384 | `164cad809d55ab24806ec3712dc0deb6f61cec44fce4ea992b75467f17efa7e2` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,624 | `6622b2ddaaee2067e9ccd296f44c0bb108e05c9bacb7fcbdd61263922f623daf` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,419 | `e348c167226c1315eb493103c29238d05bce200785c49731e869b7b2b1acfb9b` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,141 | `c3829f63ed2a4714c72a643352af82b9861f1fdb3b4bbaaf13ce93db11d9ef5f` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 764,632 | `ada9ee9d9a9d9614aa391d57d680ecc0f06570707ba78618b8b1b52707aed0b3` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,691 | `f7cc406005eeb054ae1cfd5f4766de6afa159ad859262d1d397bbe6ba7a770ac` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,973,541 | `d82fd5562eb96b3562cd4de56810d5f1bac8e13eb48273ac1993c14bbef2a3f5` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,618 | `2da8cc6f8ea756b84a7e3144306d3f0139f390bd32acd2e0e750dbce09f275cb` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,104,994 | `769ee1568fb337a0f9fc16044fa4d50ccd86a622bbd678468426e1be8809f5a3` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,633 | `e7d42d7fb03ffa629565df0ad572e7b1d715b323027bac3d861ec1648fbfdf0f` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,157,885 | `6c942ddb39175726a00825d82c6cb4e3673460e59a8803a61bb4f7cca18aef6a` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,895,193 | `8d7151f58d81306eecb14bedd6eb04f0f326db3f9bca4c330ddf1f93f3d01972` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790853206989-91781-4-protview-report-c45e5c1c4208.json` | 1,191,725 | `46dd9268531a1580153fbdbdfd328685127bf7b67ecd669920a9c7c458ed9eb0` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,990,558 | `0e232b16717abbe91f8e71e8399f1f95274af799b07e2fe3ae5db23331e89952` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790853227626-91849-2-protview-report-6acb19890536.json` | 491,458 | `7e01719de7d878d423b3f61fb3b4ace78f2a248a587795058cbaa367b9834ab5` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,008,466 | `5bbafbee9ad4f92d7927b745f01ffb479be6428f37b2e9b1ceb20ffb4672415c` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,620 | `8f6d785cdd42fda9055d765b1c42c34492f773505f7f0e3e8ceed3914b9228c9` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 556,322 | `b7d95713c430f1f8f2a1c801afb34c2abb08a348a3d62046b25c852df038ac21` |
| `evidence/main/downloads/1790851383469-83207-4-protview-report-a7a5b983a0d5.json` | 1,191,725 | `a97903895e6df93a74f8e9b94e74679e0e12cb21ade0de73e1a3ffe52eeac52b` |
| `evidence/main/downloads/1790851394095-83207-7-protview-report-ded0e64c6dce.json` | 406,808 | `998c6b3d86df70ad7295f2f5402a02ba44bcd0e58b1dac54d24ba2798eed5de3` |
| `evidence/main/downloads/1790851394860-83207-9-protview-report-0526ae8f32f5.json` | 1,191,726 | `2a5eca382ab232de1275c504fe17eb38f42fb3da0dddd98347b2ff4ba30d9c7d` |
| `evidence/minimize/downloads/1790851460603-83611-2-protview-report-b2c3d8efa40d.json` | 493,024 | `e9827639e0cd00fb5b2a4439f000b90ccaa5318d55fee1af4f80b906793bb029` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,805 | `75bb157d5de2b67769a566a2255628fa558cb709484f723d0093316551c09704` |
| `evidence/regression-m8-normal/downloads/1790851692149-84870-4-protview-report-dec2b2696384.json` | 1,191,725 | `ea62837a88eac3bb4d8670e68c380703e93611af4c3b9206ad711e6d5fae355a` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,986,095 | `8f169c364929db189b5fbd52bac9d82d2cdebe9fce8ed6ffe2753e432e590e44` |
| `evidence/regression-m9-openmm/downloads/1790851719618-84938-2-protview-report-0a1dfc15fe0c.json` | 491,458 | `795d0eb6d88718e70f64e4cc156046cb464e01995538cbb132b44827689ac2ef` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,006,633 | `1528d5dc09db1321128d95781467519b924c27c203f0c520391456532b99965a` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,567,799 | `20411202cd74def008c0b447aff16155174cf68f835c2d4f3693f44027ed2388` |
