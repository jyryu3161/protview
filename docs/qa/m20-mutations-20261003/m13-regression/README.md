# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-03T15:17:03.976319+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "vPeuYWb5CrtGZ__mURwva", "gitHead": "ea2913c7346bf2660853e6415a4dbb5b27e2d298", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "197dac68834a5f2e2690fe971e582a52ff0e96fdf7aaa825804166caa31e604a", "dirtyFiles": ["?? docs/qa/m20-mutations-20261003/acceptance/", "?? docs/qa/m20-mutations-20261003/gate.txt", "?? docs/qa/m20-mutations-20261003/m14-regression/", "?? docs/qa/m20-mutations-20261003/m15-regression/", "?? docs/qa/m20-mutations-20261003/m16-regression/", "?? docs/qa/m20-mutations-20261003/m17-regression/", "?? docs/qa/m20-mutations-20261003/m18-regression/", "?? docs/qa/m20-mutations-20261003/m19-regression/"], "recordedAt": "2026-10-03T14:41:17.941661+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 텍스트 증거 51개(331,879,749 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m20-acceptance/attempt1/regressions/m13/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m20-acceptance/attempt1/regressions/m13/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m20-mutations-20261003/m13-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `binary-artifacts.json` | 362,954 | `4881542dd0c575699350e764dbfe333846af1c48adde89e594660974045f2adf` |
| `evidence/chemical-create/downloads/1791038676098-69184-5-protview-report-ae8464379a72.json` | 294,306 | `13ae337e0310a8b04a5d6675625927b156d63711fbf936c330a2d2f7e14ff388` |
| `evidence/m11-acceptance/evidence/attach-map/chemical-evidence.json` | 1,488,623 | `a4574fe7f23ac3b9d6a3687ff517e9ec3970fc3c65b28b9ec80801fc81ad30c2` |
| `evidence/m11-acceptance/evidence/attach-map/report-download-proof.json` | 591,646 | `825f08ac3dcb7cb7acda8b7ba285e57abda64a4ad113623a0875cdaa34a25201` |
| `evidence/m11-acceptance/evidence/attach-replace/chemical-evidence.json` | 1,326,281 | `23cd61b187ce12f97be00cabf5fe070568838acecb779bdeca2e9b0657d32ed9` |
| `evidence/m11-acceptance/evidence/attach-replace/report-download-proof.json` | 457,657 | `2d8e831c5dfbc82fa4ed5a758abec8e53977807b5a67e676dd18dcc741d16863` |
| `evidence/m11-acceptance/evidence/create/chemical-evidence.json` | 5,969,680 | `62244825f98127908641e711efa3c0c62607d03f2a41992906f82f6320f5ca82` |
| `evidence/m11-acceptance/evidence/create/report-download-proof.json` | 302,630 | `62183b8d7530d7b8895380aba4ea5222bc2dd1657008f27de16a2df58f4d150b` |
| `evidence/m11-acceptance/evidence/empty/chemical-evidence.json` | 3,571,097 | `d4878bc429d2f4e3fbe7abdf3b24f5a8601aaaf0669e2581c8cc30ffd4ca87b5` |
| `evidence/m11-acceptance/evidence/faults/chemical-evidence.json` | 61,990,758 | `8ad72f0b1435d1a348b09256512650270e4db0ccc530f601eaa49a1d7dedf94c` |
| `evidence/m11-acceptance/evidence/prepare-only/chemical-evidence.json` | 3,154,209 | `69e1c803ab763e06e37458553c509760231bf9159b470d020e764bf2b3fb8406` |
| `evidence/m11-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,709 | `b2bd32674963098edda61fdd0973f0bebf98a542c879aa7064c12124deae34cf` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/downloads/1791039658203-73749-4-protview-report-01b1b3cb1f25.json` | 1,191,726 | `2f2a15d64511b08f355062c1bf9b6df5da9eb4addefa72df8e5e981d3d95f036` |
| `evidence/m11-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,729,999 | `3a59032d99b1ed3b253619cb46ec0490c9dc706efa6bd53b949a20b3a1131dbc` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/downloads/1791039685350-73955-2-protview-report-22e0160a1d35.json` | 491,459 | `31f00f379a20571b75fe3b6309e2fb3f343caf159c9afedca7ffe0fd042fb633` |
| `evidence/m11-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,073,630 | `d9aa24a28f123ce84075611111a0db5bb4333dfff307a81c99e216c32f0fc27c` |
| `evidence/m11-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,207 | `27e5212aa09d51e9c8d5f1036e1aecf79cb9ade4bb29e5423c002ee221a70da0` |
| `evidence/m11-acceptance/evidence/reopen/chemical-evidence.json` | 31,201,768 | `b9a922a61b3a6e29ded948663ca63206c62dafbb33c9f09d00d469bcd45ebee6` |
| `evidence/m11-acceptance/evidence/reopen/report-download-proof.json` | 302,630 | `a721f27a70680c3a9677b23485360b66f7f78f089d9df221f2b2dca2756d4c2d` |
| `evidence/m11-acceptance/evidence/reopen-complete/chemical-evidence.json` | 3,255,162 | `6084fc11b7a0b13dcc2a2bacf4d6bb6623f59e7d25e98df8aed22dd88a768b0f` |
| `evidence/m11-acceptance/evidence/reopen-complete/report-download-proof.json` | 457,659 | `9d444238d48b84698cfc09110e0f0208fa07d63389dc06970a09f59fb3da1776` |
| `evidence/m11-acceptance/evidence/replay-attach/chemical-evidence.json` | 62,001,646 | `c57d17af6a3dbad1465c191742e8df98210a9cacef5a5911c50ee0e067fb19dd` |
| `evidence/m11-acceptance/evidence/replay-attach/report-download-proof.json` | 591,652 | `c409630e772c24582802d77e0d86180b403a4cca0ec12d7dc5b40276dfcc9f48` |
| `evidence/m11-acceptance/evidence/replay-create/chemical-evidence.json` | 31,202,600 | `ea0ab7196449533a12f6b2f0fa2022bf148747e414f208d8bf0210d3cc028533` |
| `evidence/m11-acceptance/evidence/replay-create/report-download-proof.json` | 302,644 | `ee19e81577a3e187302e1fa2ace314f5801b40b9adf7818c0543d15ce5399527` |
| `evidence/m11-acceptance/evidence/replay-empty/chemical-evidence.json` | 30,496,614 | `138c82cc16db15c0e0ce5fe68ca05c36d1821bbfeaf44ae4eccf57dfe769f033` |
| `evidence/m11-acceptance/evidence/restrictions/chemical-evidence.json` | 801,508 | `bf5ef5bb734d663b44e28bd111e28d329625fa34f8d1e668467bdd16714c5358` |
| `evidence/m11-acceptance/evidence/services/backend-main.log` | 764,707 | `ba3197edaa18752fa2d093f036d9858d13b79e69b61f1cdee40b9dd7d9f4ae5e` |
| `evidence/m11-acceptance/evidence/services/backend-replay-worker-missing.log` | 289,799 | `4c84f963ef67ee761bcd50b0214d13a7350c054d704ac4d507d80be905d90e54` |
| `evidence/m12-acceptance/evidence/m11-create/chemical-evidence.json` | 5,983,470 | `3c0a48b416a796d7da4f98e89cf83c0ae900dff1cf1d682ad205db708a608178` |
| `evidence/m12-acceptance/evidence/m11-create/report-download-proof.json` | 302,638 | `dc9916edd639890b546c1bf5ad304db87a47fb6915ba8ef649b8dfc589f991cf` |
| `evidence/m12-acceptance/evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,079,727 | `398372b5f5548d70df75afe5e796f54fa7fa01c30b7c5f6a90d8320112285331` |
| `evidence/m12-acceptance/evidence/regression-m11-empty/chemical-evidence.json` | 3,577,162 | `46cf86433ce7e331cda8428b009fae0380f8df6ca4305760aa60a375388b1f85` |
| `evidence/m12-acceptance/evidence/regression-m11-prepare-only/chemical-evidence.json` | 3,159,429 | `230655e66e5d03c5cb7810b05c49bfbae8c639c9ac06df027763f266e5f279ba` |
| `evidence/m12-acceptance/evidence/regression-m11-reopen/chemical-evidence.json` | 30,899,292 | `599c53dcb22baf60c12af738795f07564a93a5151dcd885463c383452fad082e` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/downloads/1791040362902-77082-4-protview-report-e9442cd8413c.json` | 1,191,726 | `4438eeda25cb88f6a0af964d44781b28f6c7b0bf21016f62699d44e92e5a56f9` |
| `evidence/m12-acceptance/evidence/regression-m8-normal/normal-flow.jsonl` | 4,992,436 | `87e24a3131d422b579edbaccaa9fec562171c0ef1377c6b0e03fcd53cf1b0e11` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/downloads/1791040387537-77156-2-protview-report-ce7d5013ae7b.json` | 491,459 | `07d17c7783e4ded3da5a02af46851c82d2dabb197bb1760701e8c917a069673b` |
| `evidence/m12-acceptance/evidence/regression-m9-openmm/openmm-full.jsonl` | 2,073,644 | `159ff080d7990f60706f93752596edb0db3e8f8479bd8346b5ce5ec91102f286` |
| `evidence/m12-acceptance/evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,573,208 | `62d42715e669bac0d6ef76b9d6615a2af939c407dbde7ba6c2ecd867b34738cc` |
| `evidence/m12-acceptance/evidence/services/backend-main.log` | 565,838 | `3146d287ac2094535658146f0857ba6b66202a7715d64570e9a94fd373d9f361` |
| `evidence/main/downloads/1791038494098-68434-4-protview-report-f409c3cbf67b.json` | 1,191,725 | `1ce7b1378fd5b3aa4b4ebb484649d4866478bbf1a52a3271637b9db293afb0f9` |
| `evidence/main/downloads/1791038505622-68434-7-protview-report-783f391c70b6.json` | 406,808 | `e5a21bc8f7499fa63fd3b280cd8748f8273b41eb54bac4c632266421be6600c0` |
| `evidence/main/downloads/1791038506390-68434-9-protview-report-17557d2ceeba.json` | 1,191,726 | `fe2a2b2a4eed3c56067a5f442d8983c4a0d36c09652a4e570d3fbe8c372ddf36` |
| `evidence/minimize/downloads/1791038573245-68955-2-protview-report-d2fd1af65b67.json` | 493,025 | `27639d399519ed9cde9a8b75ba87d2e00f0e840f4552df3853b1a00d8ccd3ce7` |
| `evidence/regression-m10-alignment/comparison-alignment.jsonl` | 1,076,255 | `dfe951ce1877d3a2c5b2c65d54efced927159010ed99e17b3660e648ce3f46e7` |
| `evidence/regression-m8-normal/downloads/1791038798944-70153-4-protview-report-c5f02aea9baf.json` | 1,191,725 | `46d1e9353c6c2583a370c99a87a238cbeca0fd06c100bc253f556b95927291f3` |
| `evidence/regression-m8-normal/normal-flow.jsonl` | 4,987,868 | `f47485a4a18b43ff558d4e70b3f3ec1212128b17921aa43f26a2875dddc7f798` |
| `evidence/regression-m9-openmm/downloads/1791038820733-70214-2-protview-report-4a9eaa7abdaa.json` | 491,459 | `3d00e88e4857cb4aa77d139a9a381386752e3dfb05e3f6ea6d097757ea4c5e24` |
| `evidence/regression-m9-openmm/openmm-full.jsonl` | 2,071,773 | `627c2c859120c961a9da8c31bfb90f2ce0301ebe97baed73a89daff1a2326ced` |
| `evidence/regression-m9-scenes-core/scenes-core.jsonl` | 4,569,396 | `af5449b72474df755f7e7376fb627cc7980dc5094f53a61e0cbc8a561538ee3d` |
