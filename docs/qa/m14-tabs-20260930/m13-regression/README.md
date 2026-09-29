# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-09-29T15:49:24.793081+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "jaO5G-sFo9B5sB5owJLyf", "gitHead": "4501aa1ed9eee1e958f047826c2be1ed968ce3df", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "0531ab42674d36afb7034eccbbb07fb3a3ec19fa3338c961e8cad9fccfe99689", "dirtyFiles": ["?? docs/qa/m14-tabs-20260930/"], "recordedAt": "2026-09-29T15:13:03.889060+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 50개(331,447,219 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m14-acceptance/20260930-m13-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m14-acceptance/20260930-m13-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m14-tabs-20260930/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/chemical-create/downloads/1790694994929-96072-5-protview-report-7afd07938b4b.json` | 294,305 | `444f42ddb9dd1207ae2e5749feb8106eaf5432205943ec1a0911268223f6344c` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,608 | `c4e7686b8a0e28c2025d59d1c691a1adef166dc17822aedd31bdc7f9cadc5458` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,644 | `59756a61716672f11870e2ca75e85b66e9986e17c3a60c0521867edac359c021` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,325,876 | `f467941796a85053782590ce5d68511aa22b7f43df160ad24fe62cdb117033be` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,657 | `31376ea92f2d1f7df1c72af81ffe7e60d5f027676c4753f7d3113e71fb3adb7d` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,967,302 | `6b6aecdb1258a9e52b86deb7c23dc548b43041204c65db0528d76ed3d54a7b44` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,626 | `6ef5cf0f55842d4c76e22e15e561a943c80ebed84ec69d32aa0c31f6bd604372` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,609 | `c3c54da9e505e1dc1c4764336eb0f69060e7be91736c584773c7453e91dab3a9` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,989,686 | `1c3d8c51df014394a7bbd3263852f729a5eecef2bda4989317b98fc6f6378cca` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,052 | `bc7d2c6f33638246f5a65d7789ec81d7197779d91d3856a6904ea4babd0ee2e3` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,671 | `541b58cebc89e522363182637395f32e31fa9c7823604518ca49d0fce5c882d4` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1790695990873-1445-4-protview-report-9a0fc981c742.json` | 1,191,724 | `bab8a0d3d19099f6b699b5af95cc9565853ee5af1cf325e0799a24267f6f7bea` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,922,486 | `21c9e152cd8d7518bf4f1bb17fc91b23b8eaff5d8efab65cae0b63e5da869b26` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1790696015467-1527-2-protview-report-de0225c71495.json` | 491,458 | `c03397ac9c2255d4003add4c9863e43e435a5a5c5f0dfc420e352e1b79d2c3e7` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,072,010 | `997af3f9f15ed33de9822ee00c93784d61bfe180b04368b48313eedfd03badc9` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,781 | `77cb2d33c30ee2c19b9bc01825ee00ef61cd8aa34f014f6241024e6354a0deaa` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,253,326 | `e2d51834972e27013846f5ecb2e87a22a8fcef94cbe625bd8a96d6c66f8102a9` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,661 | `86ab082e539259adfd70de467d78828879c7a1f91a59fd5e6bfc4697a8ad2f17` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,357 | `1366ec5df722776ea2e37d8dd61168a78937a23db528f9e03591cfe508e184ba` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,624 | `076abd2cad1a3e3de932b6dca537486c9eeb8026d32caa31dd88fc5e43281624` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,197 | `5a3a435be5cc31a2143bbc361cf47fa366ac40388025e61c257b483ab8dda1d4` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,648 | `44bf214d8a4d7465c7dcc117b375da3f20618ece45673f1a49dc2c9ec8d3a857` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,189 | `cbffc410d9c626f8bafb0ab445e9fab15633735dabf55408953e620535c35e44` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,638 | `8db147d9e0c75f6906234aa84c793a638625a09b76f3183792c9162b5365cfc7` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,485 | `3129277c47388dbe6789632fa495c9dfe334476306b6239ff0743fda397df5e5` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 800,065 | `701f44c0a9b572dc19ea2af14da35adcd77177da68d7701eb3eb62d9f9daafe4` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 754,313 | `942d9231d82e2f085a8d2e84be10f8632328b2ada99e3d22aec8f33173f98f44` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 293,373 | `c2472dda1c6feb31cf5ef3059d79ce16198186e720718e4b638ade5bcc2b8953` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,969,907 | `f70bce16923da66cbdc5c8e8053ea5decc7a600cd6953f47bf7f4991085fdc25` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,636 | `d2ceb6055fd2df3fe84a8e7922506db54aca92fb24997f3d1e24fae290a22f72` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,664 | `1f5b9805d9ddf36c1e8b33febfc80f75e1bf8de1b5d544a13fcd894bb844baa5` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,575,553 | `a04850343515302646cb29c810a86221bec6b71db0df15ab7f748441a9770393` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,158,553 | `481f13aeaf9a4f805076a1969b0ff9cfcc38bf635aacb2e0599692e3eed39537` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,894,963 | `733a8c7bab38ac5520717f450113342b144bf04c1b618cd25e06bda4b9f0d5a4` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1790696720663-4657-4-protview-report-a2a396d4591e.json` | 1,191,725 | `54dc96faa3212e81a16f93271ec454f07fbdbe7990d4baddb1daa8b497bdfec1` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,988,229 | `c77abec7a6754ac6540319e0b18376f3798ee3cc513a71d4004a0dc80e350598` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1790696742622-4709-2-protview-report-34b875f1a415.json` | 491,458 | `42a9b8f2412e9d24bc4e0aeb4fad2dd14fc48ba64b22596f073f622efd33ff6a` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,007,653 | `6136d1682f3b090b2666264391ced500cac2a1f78202fe6e9b710aec736d3e86` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,789 | `ae262e62dfc8f461b7df509ed281cba876b60b609127b7658bd46a9b3c69c857` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 546,441 | `f002c4ee68c40607d05d388df6b6fe6a0164dc4fbc7e543a7fc06cff1f4961b9` |
| `evidence/main/downloads/1790694799234-95250-4-protview-report-2c01555492e3.json` | 1,191,726 | `e355d6720ed50982a37d96e44ba14b0bf02c460102142b767fc7d59d111c3d01` |
| `evidence/main/downloads/1790694811339-95250-7-protview-report-7c7737d95a04.json` | 406,808 | `549073ffb6b6eeea65203e1310b895a4d1a0ec952aa01d39a90087fb94abb874` |
| `evidence/main/downloads/1790694812139-95250-9-protview-report-9dc84d07cc40.json` | 1,191,726 | `dd379419ae3ff210830921b5ce60ab8655ca62eb64a1dbd8073a3756d0ec5517` |
| `evidence/minimize/downloads/1790694883467-95822-2-protview-report-040d889ed001.json` | 493,025 | `4c75d82debd5825441c522147f5a1f0900b76edb0c3ce2e70848c0dbaaa2690c` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,092,758 | `a224c94057b9da135addd16057086b2ccaf91337d117b4b51268863cb626c95e` |
| `evidence/regression-m8-normal/downloads/1790695130179-97468-4-protview-report-ab85ebce1dc5.json` | 1,191,726 | `e08e062d88ae5c0fdb0da29de6c62c66ddeef8b8ba9f5b9a6d7f6650bafbb252` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,918,212 | `2a8874c4ab936c396f93d08fa872de22bd0434c918800808365d77f017c7f7a1` |
| `evidence/regression-m9-openmm/downloads/1790695153225-97627-2-protview-report-6898ef14578d.json` | 491,459 | `08fdfff10f91171de02d94a946079ce2d5eb9e8add4de86af2a03513d2786cd3` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,005,838 | `978707b75eebc2d0af24f1b1864a79f49ffe0ea2dc7647efdbfe72a4b34a5521` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,565,999 | `67a138d671b992779cb9778d9e070ebd3e3e94a15f7b70435033c925678407d3` |
