# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-01T01:29:52.961902+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "q6eypdtQJ4Qgom9x2qBFB", "gitHead": "b23cb10f624d1942666d0f0080e49e449055b53e", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "b58aae9c02f2ac1375d2804bb1929b23fa571c348149618deed46d440a3bc58f", "dirtyFiles": ["?? docs/qa/m16-annotations-20261001/acceptance/", "?? docs/qa/m16-annotations-20261001/gate.txt", "?? docs/qa/m16-annotations-20261001/m14-regression/", "?? docs/qa/m16-annotations-20261001/m15-regression/"], "recordedAt": "2026-10-01T00:53:42.347811+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(332,090,577 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m13-acceptance/m16-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m13-acceptance/m16-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m16-annotations-20261001/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,938 | `81c5f17607c0e9ab6d2ef5e780740970823a6dd245f8eeb141223c8818779f0f` |
| `evidence/chemical-create/downloads/1790816231344-21054-5-protview-report-a04d37d0f2b9.json` | 294,306 | `924060b039b4097fbf2d7151773bf252d192f56bdc408236912619990cfc5d87` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,489,105 | `244f17ac999ee560489066e4cc6ce639b89489b047016c217436a58cd92dfde0` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,624 | `e928bf036f5c3b127ad94712cf2d87ee22a3dee85f52c7ff8aca303ec94f7c17` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,631 | `80b8943ac76d97d87b724f7cd5cc390f9f9df7f87d3f8bc71319c576ed367d15` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,639 | `295ae089fa10ce2919d8b50c7f9a008b7368816f20437cf4d78e5ad7093a02d4` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,969,386 | `cf2bb2f80a0efba3617978f85532c39fe7405daaf462268198bbf48db87478f8` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,612 | `040808d100a86ea3e6a423e8dd88ff065655cd7166b61a3a4401e9e5d589f628` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,244 | `12d9abdeb0307e8c15338baea6938697bf4b29b5c05e8b99d2048c7516431275` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,664 | `3cf940442d8e7511cc27350623ecef14fcd9036a2e74c03a3f6c9950f70d5eb1` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,373 | `b00f7a8e33c2b940b729afba16c214e1d21016393a11921b1a627040640ea5de` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,078,257 | `fea9b2d9acd1c3df164234d03d06772b0eb583096ea7161577485c4bb28b2040` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790817217061-26779-4-protview-report-8ac84ecd3e4f.json` | 1,191,726 | `4eb1970bf980f04a60abb49a4a2792c18d050ac8e7419e09e8eb195ef4e49f7e` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 5,119,337 | `0dff978366a11be605d10c10bb8875e6786dc7f5630aa59fc9ef6a652e841f4b` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790817240170-26864-2-protview-report-0d8822e6af1c.json` | 491,459 | `92b2ecd3c4bfafd3e14d76e315d68f564043f471ab6ebfaeb0475c37d380906a` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,072,883 | `0e4c607a2e33c8e83690d213cb25c858f511763bb74c61884b45ef95314f24aa` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,616 | `553caf01305b92a4ca41d34b809ae477bb2d9fb7369940196dd9038883cf207e` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,768 | `a337c1d9751d5ff60505032a053f5cc5e63c77a613bc21b48058785364a1721b` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,612 | `9c266aa7399b39a812ac3c588d4191af53513d1f7093bf4224ed4f90105e9d8b` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,254,744 | `315903e868bf327b98a7a300e3c601de2b60e4e7283f21d3a240f38b34cf0c95` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,643 | `d8d172f97cb2f613d385d29c73fb2e95667424924a61b66a4e1c1c825b892fd8` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,490 | `4825cb32896681d9914ba967a7c8d7b12d552fc97445fa244aeae241a1d82257` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,630 | `56ae54e431ad0d5509c992527c28527ab8f4161f09a64fab3c6e98340ba69e2c` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,600 | `b2b16fc9345401f7feffa231057329b00d4a19d2f65213d75ad7b9b8570a1b5c` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,626 | `653e702531b9322768b13f4bbdc4e079cafc133e7dc643e86f683b6f25bd2aa9` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,421 | `59c8587b88798d35da6e109f7c129fb89980db80a20931209ac5bacb51a62fca` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,141 | `762b2fa3fda692293e1a448e725fa12741c31100358840e72490b01ef5d043b4` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 766,394 | `d4444f616b3aae88b1861eee4c7425eb27ae177b8bff535e16976de7f490a1aa` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 293,866 | `1b21a10580fa8769511555372b81945d6bbaf5eda540c1479c5a0030805fa2c1` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,984,827 | `a5c3f28fda9c4f77b78d811bddbadbb597b0c0092424a5371b3f4a97aa342522` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,614 | `393b5ad18ec3a40ff975bf7e3136e92e5e1667efcb75b5a3c5cbb1fa6c228b2d` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,078,263 | `27adbbdb94cfc9d93d3004a2b4c4c292f8cfdc286fecee8e45e51e78beb62739` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,572,616 | `c7885b8df051cd4a15e4edaa90dce64f9b4254b21698ffa649455ab447bae207` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,154,543 | `1b2c8781431d6108bc7380b45c614d1bcb67b2a9bf486418aa8e5138bbc3ae4d` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,899,194 | `c26256047498f9cacfd096b1591e6db83c37897bec6c12dd067f28e2e833cb62` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790817919764-30454-4-protview-report-315292b02e4b.json` | 1,191,725 | `6a68e4826664775486b44774520b03f9b5808615ad0faa8975d949f673452799` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,922,798 | `3238c534e57b3eb5b6e1700baa3553a4db20ca18c46dab31815d54d70a6794b9` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790817945439-30537-2-protview-report-0caf5a2b4fc3.json` | 491,458 | `8b45786588cbfb23b9545d368aa78d52beb7bf5ef9c5e0cabbfb2c9fdfc963fd` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,008,384 | `389ab38739fce148eccd416da46150127ef3ae51d78dca6149b57273e5739cde` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,571,617 | `69e7b67ba7d6d2ab857e10c4fb0cf4ecc34c4988093973ae161b030d79bcacea` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 537,560 | `308dd842215e1c9263b66de99f332f7b548057944d5359041fc4a4561cf85923` |
| `evidence/main/downloads/1790816037078-20071-4-protview-report-f103a30a3934.json` | 1,191,725 | `a2f76704b2e23884eb98e7d643a6332a1f2c89626b03866653d17d5efcecb2f1` |
| `evidence/main/downloads/1790816048650-20071-7-protview-report-24eeb934e9fa.json` | 406,808 | `4079b6b9a821df42893d702db50fb91e52875079b63e9853456cee1ccba30c2d` |
| `evidence/main/downloads/1790816049449-20071-9-protview-report-3f4945e4f6ec.json` | 1,191,726 | `fecc49752dde1e2e4938ab367d407b86d2b0068ade7e66a127e75f66cec08acd` |
| `evidence/minimize/downloads/1790816117894-20896-2-protview-report-bee2ed4b592f.json` | 493,025 | `9dca761764a6e0f1ad52ea52e5d9562f81fc1316f8868a3cef0b8acaf3b697c5` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,074,803 | `a02b83180d016c9218c290419cb21eeab5587e5f13d54038b16323f07673a30e` |
| `evidence/regression-m8-normal/downloads/1790816362343-22390-4-protview-report-7ff51e7beaa2.json` | 1,191,726 | `416810bf110282e89ebcf9ed61ee4aff9ed31fcedf80d48d877d87f3e0876489` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 5,051,538 | `78f9a84c071a043c7c7619702f5e8dbb72477a0ba50ff4777b63d35ecd2f2b0f` |
| `evidence/regression-m9-openmm/downloads/1790816384639-22474-2-protview-report-1343a58e6658.json` | 491,458 | `dd96b4658d2cf60321faf8578e5f67201644b6449204cd165140c0f82d4a43b0` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,006,633 | `676d9f37c2e23cdf18b09a54c89749cd572b00cd9b4f515430f636f1902c568d` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,567,801 | `1c954c7915f5b4ddb06b61c6548fd813b550d0d86e8a39ae87eec590c184e104` |
