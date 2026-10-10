# M21 변이 구조 모델링 오프스크린 수락 QA 증거

- 생성: 2026-10-10T13:51:36.298397+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "wbonjE7nah2kMcCTup7fP", "gitHead": "e595ca404b2ffa210eb6d372d8983c86fc7538b4", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "151e9f6f2346add9c4d499b08749474564601c2fc6dcaab1ceb580ea07a505fd", "dirtyFiles": ["?? docs/qa/m27-precedents-20261010/regression/"], "recordedAt": "2026-10-10T13:49:50.568617+00:00", "codeRoot": "<repo>", "harnessSha256": {"mutation-model-flow.cjs": "3e3c4b7fff5d0e134b17ddceecc54a96e36bc6841d58c3bbd8c3a6dd75ac0112", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "8b4fe080cd28d4edbea1f3cd61a08fe68b543bd79ced8c41769caea2dda09268"}
- 환경: mutation_model 사용 가능 (OpenMM 8.6.0, PDBFixer 1.12.0) · mutation_candidates 사용 가능 · ligand_docking 사용 가능
- 입력: 공개 1UBQ(`backend/tests/fixtures/public_1ubq.cif`, M7 사전 검사를 통과하는 유일한 로컬 공개 구조, 리간드 없음)와 합성 표시 페놀 SDF(`backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf`, 같은 조건 도킹 흐름의 기계적 검증용). 후보는 M20 직접 선택 I44W.
- run A 실제 비싼 계산 단위: 5 / 한도 8 (모델 {'before': 0, 'after': 1}, 같은 조건 도킹 {'before': 1, 'after': 3, 'actions': []}, 한쪽 취소 짝 {'before': 3, 'after': 4, 'actions': [{'cancel': 'mutant', 'at': 1791640239034}]}; 같은 요청 재제출 0, 실행 중 취소한 모델 작업 1)
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

재현 검사: handle은 run마다 다르다(obj://<run>/…). 그래서 같은 서버 프로세스의 새 run 두 개에서 흐름의 불러오기·전처리·후보·모델 요청을 API로 보내고(승인·시작), 모델 요청을 한 번 더 보내 같은 작업·같은 handle인지, 저장된 모델(obj:// handle만 자리표시로 바꿈)이 흐름의 모델과 같은지 본다. 흐름 안에서는 같은 요청을 다시 보내 같은 handle·새 단위 없음을 본다(사례 MM-same-handle).

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| MM-no-run | fresh root, no run: the model area shows 사용할 수 없음 + the no-run reason only (no numbers, no controls, no model reads) | pass | model-main:pass |
| MM-load-prepare | public_1ubq.cif loaded and prepared through the structure screen | pass | model-main:pass |
| MM-candidate-set | M20 direct-residue candidate set (ILE A:44, allowed W) through the candidate screen: one candidate I → W | pass | model-main:pass |
| MM-handoff | 변이 구조 모델링 on the M20 candidate row fills the request area with that set and index; seed empty, confirmations unchecked, defaults 4.0 Å / 120 s; nothing chosen or sent automatically | pass | model-main:pass |
| MM-validation | submit blocked without seed and confirmations, with seed only, with one confirmation, with cutoff 7.0 (argument_invalid); enabled only when complete; no job request while blocked | pass | model-main:pass |
| MM-job | 모델링 작업 제출 → 비싼 계산 승인 → 작업 시작 → real openmm_mutation_model_v1 done; the six request arguments + timeout_s; one expensive unit; the model listed, not opened automatically | pass | model-main:pass |
| MM-side-by-side | side-by-side table = API detail = stored event-log payload for both structures (OpenMM potential before/after, mutated-residue SASA, contact and residue counts, PDBFixer atoms, disulfides, atoms, hydrogens) with the harness ROUND_HALF_UP; no difference field stored | pass | model-main:pass |
| MM-limitations | the limitation sentences shown = stored = spec §4 verbatim in order (L5/L6 only under their stored conditions) | pass | model-main:pass |
| MM-negative | no difference/change/rank/best/recommendation/stability wording or arrow in the model panel (every check of the run); both structure cells of every side-by-side and pair row have the same style; no extra column | pass | model-main:pass |
| MM-contacts | contact table pages (야생형 기준 1, 변이형 1 → 다음 → 이전) = API pages = stored rows (7 partner fields, atom names, distance ROUND_HALF_UP); more than one page with cutoff 6.0 Å | pass | model-main:pass |
| MM-downloads | both mmCIF downloads: bytes SHA-256 = stored structure_sha256 = backend bytes | pass | model-main:pass |
| MM-report | 보고서 만들기 → saved and listed for the model (no new model); Markdown/JSON downloads = backend bytes; the Markdown carries the fixed sentences and no docking value | pass | model-main:pass |
| MM-same-handle | the same model submission again returns the existing done job and the same model handle; no new job, no new model, no new unit | pass | model-main:pass |
| MM-late-contacts | a held 변이형 contact page released after switching back to 야생형 기준 is not applied | pass | model-main:pass |
| MM-tab-state | ligand SDF imported in the 리간드 설계·탐색 tab; back on 단백질 공학 the area remounts, re-reads its lists (GET only) and opens nothing by itself | pass | model-main:pass |
| MM-pair-submit | same-condition docking: 2-unit notice, blocked until the 2-unit box is ticked; one click sends two qvina_dock_v1 jobs that differ only in receptor_source.side (no imported-receptor key); both real qvina jobs done through the screen's buttons; two expensive units | pass | model-main:pass |
| MM-pair-scores | pair row: both scores side by side = docking_pairs = each M18 result's first mode score (receptor source recorded), header with the server's score name, four columns, no difference | pass | model-main:pass |
| MM-pair-partial | second condition (seed 7) with the 변이형 job cancelled while queued: per-side job status, both cells '없음(server reason)' without a number; one unit for the started job; the first pair keeps its scores | pass | model-main:pass |
| MM-cancel | a running modeling job (seed 7) cancelled from the screen: cancelled, no model, no worker/guardian process left, the area shows 실패 with the cancel sentence, one reserved unit kept | pass | model-main:pass |
| MM-late-run | a held run A model-list response released after switching to run B is not applied | pass | model-main:pass |
| MM-reproducible | the flow's load, prepare, candidate and model requests made in each of two fresh runs over the API: the same job and model handle twice per run and the stored model (obj:// handles replaced) equal to the flow's model | pass | runner:pass |
| MM-budget | real expensive units of run A counted from the backend budget: model job 1, same submission 0, same-condition docking 2, partial pair 1 (the queued side cancelled before it started), cancelled modeling job 1; total within the run limit | pass | model-main:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- MM-unavailable: methods.mutation_model depends on the project .venv (OpenMM 8.6.0, PDBFixer 1.12.0) and the process-identity adapter, not on .deps; the M18/M13 layout-without-.deps precedent cannot make it unavailable without forging an interpreter. Covered by backend/tests/test_mutation_model_jobs.py::test_unavailable_engine_pdbfixer_or_identity_is_412_without_reservation and frontend/tests/mutation-model.test.cjs ('five area states: unavailable, failed, loading, empty, ready', 'submit is blocked without capability…').
- MM-pair-approval: the expensive_first_call approval is per run and the model job (needed before any pair) already took it, so the docking pair's own approval button cannot be reached honestly. Covered by frontend/tests/mutation-model.test.cjs (pairApprovalRequired) and the M18 acceptance (D-free-job).
- MM-failed-job: no valid 1UBQ input makes the worker fail with a closed reason (all T1 combinations model). Covered by backend/tests/test_mutation_model_worker.py (test_energy_contact_and_output_limits_are_closed_failures, test_pdbfixer_errors_are_mutation_modeling_failed) and test_mutation_model_jobs.py (test_tampered_output_typed_errors_size_limit_and_late_cancel_publish_nothing).
- MM-zero-contacts: the I44W model has contacts on both structures; a zero contact page ('0개, 계산한 결과') is covered by frontend/tests/mutation-model.test.cjs ('contact pages: query, cells, and a zero count…').
- MM-conditional-limitations: L5/L6 need a histidine/cysteine state difference or a new disulfide; 1UBQ I44W has neither (the flow asserts the stored conditions). Covered by backend/tests/test_mutation_model_worker.py (test_removed_disulfide_records_the_partner_difference_and_l5, test_new_disulfide_is_recorded_with_l5_and_l6) on the derived synthetic fixtures.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| model-main | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m21_offscreen_acceptance.py --root runs/m21-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/<label> \
    --out docs/qa/m21-mutations-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]
```
