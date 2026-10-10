# M13 분석 흐름 오프스크린 수락 QA 증거

- 생성: 2026-10-10T14:39:28.278164+00:00 · verdict **pass** · phases workflows, unavailable, regressions, m11, m12, ledger
- 빌드: {"buildId": "wbonjE7nah2kMcCTup7fP", "gitHead": "e595ca404b2ffa210eb6d372d8983c86fc7538b4", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "151e9f6f2346add9c4d499b08749474564601c2fc6dcaab1ceb580ea07a505fd", "dirtyFiles": ["?? docs/qa/m27-precedents-20261010/regression/"], "recordedAt": "2026-10-10T14:03:03.287508+00:00", "codeRoot": "<repo>", "harnessSha256": {"workflows-flow.cjs": "8bd886baabc3d06b00f05d2dfaa196d8e458f2e6d57f081303168ad5240aaa70", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "comparison-flow.cjs": "5a9fe1bcdeadaddc5b7ffd051c65b672c75dd10adf8c181829d2c6d21dd30099", "openmm-flow.cjs": "1827d7501c836633bc83e0401bd2dc77ca2f74dc5cd3efce4976ea5ad340e420", "scenes-flow.cjs": "043813eda1309726cfaa107dc333d3e8732817d6f42428257656f7598dbd0ad2", "chemical-flow.cjs": "c834569aed7e4f2a899293168a7587448e70f0625b13835b151bc322b051d967", "pocket-flow.cjs": "f8e0949a9fcc65a9a2071a5de657c20763f59b1fcd7ebbf706a3b29abd7586da"}, "runnerSha256": "b16ccb9f6e4f6c49bf29ecbe203e474c758cc5811e204e3167c0e007098a54f5"}
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

256 KiB를 넘는 증거 52개(합계 332,085,710 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m27-final/export-full/m27-precedents-20261010__regression__m13-regression/`로 옮겼다(이 폴더 기준 상대 경로 유지, 삭제하지 않음). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m27-final/export-full/m27-precedents-20261010__regression__m13-regression && shasum -a 256 -c ../../../../../../../docs/qa/m27-precedents-20261010/regression/m13-regression/ARCHIVED-EVIDENCE.sha256`

참고: 이 폴더의 `SHA256SUMS`에서 `README.md` 줄만 일치하지 않는다. 해시를 만든 뒤 이 절을 덧붙였기 때문이며, 옮긴 파일은 위 확인 명령으로, 나머지 파일은 `SHA256SUMS`로 확인한다.
