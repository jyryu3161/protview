# M23 서열 GA 설계 오프스크린 수락 QA 증거

- 생성: 2026-10-11T17:43:24.618114+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "rBBec44wIyXoIAtlHTe43", "gitHead": "5a5ba3f2e9e2f4b572eb9e7dc27111598a52dbe3", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e515176ada09faba74882b98ed8fbcf588eb59a652a1066842f188e61f1e0b41", "dirtyFiles": ["?? docs/qa/m28-final-20261011/regression/"], "recordedAt": "2026-10-11T17:32:35.649796+00:00", "codeRoot": "<repo>", "harnessSha256": {"sequence-ga-flow.cjs": "54e3e15c9a64f19b65113b098adaee69bbec12b5094e3d1f97d0182893a3e7d2", "docking-flow.cjs": "93ab8a165cdd0c0e82d53a5897085ba9ca8a1bfb5ebbda9d9a7af61085218473", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "runnerSha256": "e5bb4fbcebfad06623bde434e3e21d2f89a9189500e3f5a1e7ef69543c0ca559"}
- 환경: docking venv-locked 있음 · qvina2 있음 · 프로젝트 .venv 있음 · sequence_ga_design 사용 가능 · 환경 없는 layout backend `worker_missing` · 버전 {"model": {"openmm": "8.6.0", "openmm_engine_build": "8.6.0.dev-c6173db", "pdbfixer": "1.12.0"}, "docking": {"MDAnalysis": "2.10.0", "gemmi": "0.7.5", "meeko": "0.8.0", "rdkit": "2026.03.6"}}
- 입력: 공개 1UBQ(`backend/tests/fixtures/public_1ubq.cif`, M7을 통과하는 유일한 로컬 공개 구조), M20 화면으로 만든 tiny 집합(I3 보호, K6·I44·G76, 허용 A·W: 후보 6개, 조합 26개 = T1 fixture)과 I44W 집합, 합성 표시 SDF 셋(페놀, 평면(ligand_not_3d), 암시 수소(기준 행 도킹 실패)).
- run A 실제 비싼 계산 단위(백엔드 /budget): 사용 58 / 한도 58 (GA마다 시작 전 reserved_units 한 번 예약·환불 없음, 같은 인자 재제출 0. 한도 증액은 모두 화면 버튼 클릭)
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

재현 검사: 같은 서버 프로세스의 새 run 두 개에서 흐름의 GA 1을 화면 입력으로 다시 돌린다(콜드 재시작이 아니다. 서열 GA는 어떤 설정이든 10단위 이상이 필요해 기본 run 예산 8단위를 넘고, 한도 증액은 사람이 화면 버튼으로만 하므로 API 재실행이 아니라 화면 재실행이다). handle은 run마다 다르고 GA 호출 키·조건 해시·스테이징 선택 해시·M18 입력 해시가 그 handle로 계산되므로, 요약과 평가한 행마다의 모델·M18 결과 내용(obj:// handle과 그 해시만 자리표시로 바꿈)과 포즈 SDF 바이트를 흐름의 것과 비교한다.

독립 oracle: 흐름의 GA 1·GA 2 저장 경로를 T1 독립 oracle(`backend/tests/fixtures/sequence_ga/independent_sequence_ga_oracle.py`, 표준 라이브러리만)에 T1 실제 엔진 첫 모드 점수표를 넣은 결과와 비교한다(GA 2는 GA 1의 저장 행을 재사용 색인으로).

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| SG-load-prepare | public_1ubq.cif loaded and prepared through the structure screen | pass | seqga-main:pass |
| SG-no-candidate-set | before any M20 set the sequence GA area shows 사용할 수 없음 with the reason only (no number, no input, only the list re-read button, no POST) | pass | seqga-main:pass |
| SG-candidate-sets | M20 screen: the tiny set (I3 protected, K6, I44, G76; allowed A W) whose candidates and positions equal the T1 fixture and the oracle space, and an I44W-only set | pass | seqga-main:pass |
| SG-ligand-imports | phenol, planar and implicit-H SDFs imported through the docking area; back on 단백질 공학 the area remounts and reads its lists with GET only | pass | seqga-main:pass |
| SG-initial-state | nothing chosen, submitted or approved automatically: no set, SDF or box, confirmations and acknowledgements unchecked, GA seed empty, defaults prefilled, both buttons blocked with the reasons, 빈 결과, capability line | pass | seqga-main:pass |
| SG-param-guards | each of the 11 GA keys out of range (and the GA seed empty) blocks 시작 전 확인 and 서열 GA 시작 with the field's reason (invalid_job_arguments); no request | pass | seqga-main:pass |
| SG-cross-rules | population − elite < 2 and max new < population: blocked at the named field; no request | pass | seqga-main:pass |
| SG-defaults | 기본값으로 restores every spec 2 default and keeps the GA seed; range/default text per field; the effective summary with the job time limit total_s + 600 | pass | seqga-main:pass |
| SG-confirmations | a missing rebuild_pH7 confirmation or acknowledgement blocks the preflight with "… (confirmation_missing)" / "… (acknowledgement_missing)"; no request | pass | seqga-main:pass |
| SG-refusals | preflight refusals ga_space_too_small (6 < 8 at max_mutations 1; the I44W set 1 < 4) and ligand_not_3d (planar SDF) shown as "한국어 (code)" with the server detail; no job, no event, no charge | pass | seqga-main:pass |
| SG-preflight | GA 1 preflight: space 3/6/26 (cap 3) in ②, 602 heavy atoms and no 4,890 warning line (server flag), reserved 13 evaluations / 28 units, need, remaining, shortfall and may-be-partial = spec 7 arithmetic; S1 S4 S5 S6 verbatim; the view shows the server numbers | pass | seqga-main:pass |
| SG-limit-approval | shortfall → approval control, start blocked (ga_limit_raise_required); the screen's button raises by the shortfall only (by human, sequence GA context, no job/object/charge), the preflight is read again with no shortfall, nothing starts by itself (GA 1, GA 1 again, GA 4) | pass | seqga-main:pass |
| SG-run | real sequence_ga_dock_v1 GA 1: the run's first expensive call approval, 작업 시작, done; timeout total_s + 600; exactly reserved_units units; summary listed, not opened | pass | seqga-main:pass |
| SG-progress | while running, the progress line and data attributes equal the stored job record (reference row recorded, generations, new evaluations) | pass | seqga-main:pass |
| SG-results | status, stop reason (no_change = 점수 최솟값 변화 없음), S sentences, summary lines, the reference row apart from the table, generation tabs and every row (mutations from the set with 7 fields, origin, parents, evaluation, state, score = stored M18 first mode ROUND_HALF_UP) = stored; carried rule; min/max as values | pass | seqga-main:pass |
| SG-oracle-path | GA 1's stored path = the T1 independent oracle vector s4_tiny_observed (keys, origins, parents, edit ops, evaluations, indices, states, scores, stop) | pass | seqga-main:pass |
| SG-sort | slot/key/score headers both ways follow the stored values; rows without a score last; aria-sort; no rank column | pass | seqga-main:pass |
| SG-detail | individual and reference detail = the stored mutation_set_model@1 values only (mutations, potentials with S5, HIS/CYS states and differences, disulfides, PDBFixer atoms, model limitations) and the stored M18 result detail | pass | seqga-main:pass |
| SG-download | individual and reference mmCIF downloads: bytes SHA-256 = stored structure_sha256 = backend bytes | pass | seqga-main:pass |
| SG-dedupe | GA 1 arguments again: preflight names the existing job; 서열 GA 시작 shows that job (no new job, object or unit) | pass | seqga-main:pass |
| SG-reuse | GA 2 (other GA seed, same evaluation seed): reused individuals and the reference row cite GA 1's stored model and result (재사용), new objects = new evaluations, reserved_units charged once, S3 | pass | seqga-main:pass |
| SG-partial | GA 2 stops at evaluation_limit (new = reserved evaluations), stopped generation marked, partial, S2 | pass | seqga-main:pass |
| SG-cancel | GA 3 cancelled from the screen while running: cancelled job, partial / cancelled summary with the finished individuals, S2, no worker/modeling child/qvina2 left, no refund | pass | seqga-main:pass |
| SG-reference-failed | GA 4 (implicit-H SDF, admitted by the server): the reference row fails in docking (reason "한국어 (code)", score —, never 0), no generation, partial / reference_failed, S2, stored reference model shown without an M18 result; reserved units charged | pass | seqga-main:pass |
| SG-late-response | a held summary-detail response released after switching to another summary is not applied | pass | seqga-main:pass |
| SG-report | 보고서 만들기 → saved and listed for the summary (no new GA object, no unit); Markdown/JSON downloads = backend bytes; 지식·보고서 lists 서열 GA 보고서 and reopens the saved Markdown; global budget = backend | pass | seqga-main:pass |
| SG-tabs | back on 단백질 공학 the area remounts (GET only, nothing opened); M20, M21, sequence GA areas in order; the 구조 분석 panel stays mounted, hidden and inert; the four tabs unchanged | pass | seqga-main:pass |
| SG-processes | no GA worker, modeling child, docking worker, guardian or qvina2 process under the runs folder | pass | seqga-main:pass |
| SG-wording | no rank/best/improvement/winner/recommendation/comparison/difference/average/effect/affinity/stability word in the sequence GA area outside the fixed and stored sentences and the score names | pass | seqga-main:pass |
| SG-no-run | no run: the sequence GA area shows only the no-run reason (no numbers, no controls, no request) | pass | seqga-main:pass, seqga-unavailable:pass |
| SG-unavailable | backend without the locked docking environment: 사용할 수 없음 with the capability reason (worker_missing), no numbers, no controls, no sequence GA request | pass | seqga-unavailable:pass |
| SG-repro-runs | two fresh runs replay GA 1 through the screen (load, prepare, M20 tiny set, phenol import, the same inputs and values, the screen's limit approval, run to done) | pass | seqga-repro:pass |
| SG-reproducible | the flow's GA 1 replayed in two fresh runs of the same backend process: the summary and every evaluated row's model and M18 result (contents with the run-scoped obj:// handles and the hashes over them replaced) and the poses SDF bytes equal the flow's (cpu 1, GA and evaluation seeds fixed) | pass | runner:pass |
| SG-oracle-paths | the flow's GA 1 and GA 2 stored paths equal the independent T1 oracle on the T1 real-engine first-mode table (GA 2 with GA 1's stored rows as the reuse index) | pass | runner:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- SG-individual-without-score: every individual of the 1UBQ + phenol GAs is scored (T1: all 26 keys and the reference row scored); nothing is forged. The reference row without a score is observed (SG-reference-failed). Covered by frontend/tests/sequence-ga.test.cjs and backend/tests/test_sequence_ga_api.py::test_rows_without_a_score_are_null_never_zero.
- SG-heavy-atom-warning: 1UBQ projects 602 heavy atoms (< 4,890): the flag is false and the line absent on every preflight; no local public structure passing M7 exceeds it. Covered by backend/tests/test_sequence_ga_inputs.py and frontend/tests/sequence-ga.test.cjs.
- SG-other-stop-reasons: generations_complete, space_exhausted, time_exhausted, worker_failed, resource_exceeded and repeated_failure need other scores, hours, a killed worker, oversized output or five failing models; covered by backend/tests/test_sequence_ga_worker.py and test_sequence_ga_jobs.py.
- SG-model-conditional-sentences: SL5/L6 need a HIS/CYS state difference outside the mutated residues or a new disulfide; the observed 1UBQ tiny-set models have none (the flow asserts the stored conditions). Covered by backend/tests/test_sequence_model_bundle.py and test_sequence_model_worker.py.
- SG-dry-run: a dry-run run plans only; covered by backend/tests/test_sequence_ga_jobs.py::test_dry_run_plans_only and frontend/tests/sequence-ga.test.cjs.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| seqga-main | pass |  |
| seqga-repro | pass |  |
| seqga-unavailable | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m23_offscreen_acceptance.py --root runs/m23-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/<label> \
    --out docs/qa/m23-sequence-ga-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]
```
