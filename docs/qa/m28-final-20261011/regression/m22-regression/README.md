# M22 리간드 GA 설계(qvina) 오프스크린 수락 QA 증거

- 생성: 2026-10-11T17:49:18.198040+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "rBBec44wIyXoIAtlHTe43", "gitHead": "5a5ba3f2e9e2f4b572eb9e7dc27111598a52dbe3", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e515176ada09faba74882b98ed8fbcf588eb59a652a1066842f188e61f1e0b41", "dirtyFiles": ["?? docs/qa/m28-final-20261011/regression/"], "recordedAt": "2026-10-11T17:43:25.039024+00:00", "codeRoot": "<repo>", "harnessSha256": {"ligand-ga-flow.cjs": "9fa1ef37ddc4d31e26aef34a2da08d89b44f3b528bae25972d604793b3e73bbb", "docking-flow.cjs": "93ab8a165cdd0c0e82d53a5897085ba9ca8a1bfb5ebbda9d9a7af61085218473", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "runnerSha256": "c09b0a89e3b0e97fe19c6d2d1f72a32d6498eb19903089b1db7d2c8ab5bd067a"}
- 작업 환경: docking venv-locked 있음 · qvina2 있음 · M17 venv-locked 있음 · 주 backend GA capability 사용 가능 · 환경 없는 layout backend `worker_missing`
- 입력: 공개 수용체 `backend/tests/fixtures/chemical/prolif-vina-rec.pdb`, 공개 파생 부모 `backend/tests/fixtures/docking/public-derived-parent-record0.sdf`, 합성 표시 블록 `backend/tests/fixtures/ligand_ga/synthetic-ga-small-blocks.smi`(실제 M17 작업으로 후보 10개).
- run A 실제 비싼 계산 단위(백엔드 /budget): 사용 32 / 한도 32 (M17 2, GA마다 시작 전 reserved_units 한 번 예약·환불 없음, 같은 인자 재제출 0. 한도 증액은 모두 화면 버튼 클릭)
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

재현 검사: handle은 run마다 다르다(내용에 그 run의 가져오기·후보 집합 handle이 들어가고 GA 호출 키·스테이징 선택 해시·M18 입력 해시가 그 handle로 계산됨). 그래서 새 run 두 개에서 흐름의 GA 1을 다시 돌려 요약과 평가한 개체마다의 결과 내용(obj:// handle과 그 해시만 자리표시로 바꿈)과 포즈 SDF 바이트를 흐름의 것과 비교한다. 같은 run 안의 같은 인자는 같은 작업을 돌려준다(사례 GA-dedupe).

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| GA-run-panel | ligand tab GA area uses the global run (no run choice), capability line, no summaries, start blocked | pass | ga-main:pass |
| GA-no-candidate-set | before any M17 set the pool area shows 사용할 수 없음 with the reason only (no number, no candidate set option, no GA request) | pass | ga-main:pass |
| GA-m17-set | receptor imported in the docking area; real M17 inspection (approval) + enumeration of the synthetic small pool at site 22 → the fixture's ten candidate ids in set order | pass | ga-main:pass |
| GA-param-guards | GA seed empty, population 25, random fraction 0.6, population − elite < 2, max new < population: each disables 시작 전 확인 and GA 시작 with the field's reason (invalid_job_arguments); no GA request is sent | pass | ga-main:pass |
| GA-defaults | 기본값으로 restores every spec 2 default and keeps the GA seed; range/default text per field; effective summary with the job time limit; 끝까지 못 갈 수 있음 advice | pass | ga-main:pass |
| GA-pool-too-small | preflight refused ga_pool_too_small with the defaults (10 eligible < 12) and with the M17 filter (3 eligible < 4); start blocked; no job, no event | pass | ga-main:pass |
| GA-preflight | GA 1 preflight: pool, reusable 0, reserved_units 6 = expected, need 6 units / 1200 s, remaining = budget, shortfall 0, 끝까지 못 갈 수 있음 (reserved × 300 s > total_s), G1; the view shows the server numbers; no approval control without a shortfall | pass | ga-main:pass |
| GA-run | real qvina_ga_dock_v1 to done without a second approval, timeout total_s + 600, exactly reserved_units units, summary listed not opened | pass | ga-main:pass |
| GA-progress | while running, the progress line equals the stored job record's staged counts | pass | ga-main:pass |
| GA-results | status, stop reason, G sentences, summary lines, generation tabs and every individual row equal the stored summary; scores = each stored M18 result's first mode (ROUND_HALF_UP); carried = previous generation's lowest stored scores; slot counts; similarity = fixture Morgan Tanimoto; min/max as values only | pass | ga-main:pass |
| GA-sort | slot/candidate/score headers both ways follow the stored values; rows without a score always last; aria-sort; no rank column | pass | ga-main:pass |
| GA-detail | 상세 열기 → the existing M18 detail of that individual's stored result; the individual read names it | pass | ga-main:pass |
| GA-limit-approval | shortfall → approval control shown, start blocked (ga_limit_raise_required); the screen's button raises the limit by the shortfall only (by human, GA context, no job/object), preflight re-read with no shortfall (GA 2, 3, 4, 5) | pass | ga-main:pass |
| GA-dedupe | GA 1 arguments again: preflight names the existing job; GA 시작 shows that job (no new job, no unit) | pass | ga-main:pass |
| GA-reuse | GA 2 (other GA seed, same docking seed): reused individuals cite GA 1's stored results (저장된 결과 재사용), new docking objects = new_dockings_used, reserved_units charged once, G1 + G3 | pass | ga-main:pass |
| GA-pool-exhausted | GA 3 takes every eligible candidate, then complete / pool_exhausted | pass | ga-main:pass |
| GA-partial | GA 4 (max new 4, nothing reusable): partial / docking_limit after generation 1; G1 + G2; stopped generation marked; no number for uncomputed individuals | pass | ga-main:pass |
| GA-cancel | GA 5 cancelled from the screen while an individual is docking: cancelled job, partial / cancelled summary with the finished individuals, G2, no worker/qvina2 left, no refund | pass | ga-main:pass |
| GA-report | 보고서 만들기 → 리간드 GA 설계 보고서 in the knowledge-tab list (G1, G3, score name); Markdown/JSON downloads equal the backend; the global budget equals the backend | pass | ga-main:pass |
| GA-processes | no GA worker, docking worker, M17 worker, guardian or qvina2 process under the runs folder | pass | ga-main:pass |
| GA-wording | no rank/best/improvement/affinity/winner/recommendation word in the GA area outside the fixed sentences and the score names | pass | ga-main:pass |
| GA-no-run | no run: the GA area shows only the no-run reason (no numbers, no controls) | pass | ga-unavailable:pass |
| GA-unavailable | backend without the locked environments: 사용할 수 없음 with the capability reason (worker_missing), no numbers, no controls, no GA requests | pass | ga-unavailable:pass |
| GA-reproducible | the flow's GA 1 run again in two fresh runs: the summary and every evaluated individual's result (contents with the run-scoped obj:// handles and the hashes over them replaced) and the poses SDF bytes equal the flow's (cpu 1, GA and docking seeds fixed) | pass | runner:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- GA-null-result: qvina returns modes for every small-pool candidate (T1: all ten scored), so no individual without a score is shown; nothing is forged. Covered by frontend/tests/ligand-ga.test.cjs and backend/tests/test_ligand_ga_worker.py.
- GA-no-change: no_change depends on the engine's scores; no input is chosen to force it. Covered by backend/tests/test_ligand_ga_worker.py.
- GA-time-and-worker-limits: time_exhausted, candidate_timeout, worker_failed and resource_exceeded need hours, a killed worker or oversized output; covered by backend/tests/test_ligand_ga_worker.py and test_ligand_ga_jobs.py with test-only reduced constants.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| ga-main | pass |  |
| ga-unavailable | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m22_offscreen_acceptance.py --root runs/m22-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/<label> \
    --out docs/qa/m22-ga-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]
```
