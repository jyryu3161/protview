# M19 후보 일괄 도킹(qvina) 오프스크린 수락 QA 증거

- 생성: 2026-10-09T10:27:35.702232+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "Dikedmz3G0FMeEOWwIdzo", "gitHead": "dac2755a00e0139b0ce25085a82a1ed08caf3e71", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "4c7db47848caae952fc83dc3b03001d06f0c2563e9cfc4137656949eaebf54de", "dirtyFiles": ["?? docs/qa/m26-reaction-20261008/acceptance/", "?? docs/qa/m26-reaction-20261008/regression/"], "recordedAt": "2026-10-09T10:24:22.411613+00:00", "codeRoot": "<repo>", "harnessSha256": {"docking-batch-flow.cjs": "9598f058d5d6aa084416eba6c5a9c947eb39c80cca6ddee78c90b832f597497f", "docking-flow.cjs": "93ab8a165cdd0c0e82d53a5897085ba9ca8a1bfb5ebbda9d9a7af61085218473", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "3c82786f51bbb090e64d773ac60b93b3c4c4c8ccbe83e18f9927cdb7c53d9452"}
- 작업 환경: docking venv-locked 있음 · qvina2 있음 · M17 venv-locked 있음 · 주 backend 일괄 capability 사용 가능 · 환경 없는 layout backend `worker_missing`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

재현 검사: handle은 run마다 다르다(내용에 그 run의 가져오기·후보 집합 handle이 들어감). 그래서 새 run 두 개에서 같은 일괄을 다시 돌려 요약과 행별 결과의 내용(obj:// handle과 그 handle로 계산한 입력 해시만 자리표시로 바꿈)과 포즈 SDF 바이트를 흐름의 것과 비교한다. 같은 run 안의 같은 입력은 같은 요약을 돌려준다(사례 B-dedupe).

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| B-run-panel | ligand tab batch area uses the global run (no run choice), capability line, no summaries, start blocked | pass | batch-main:pass |
| B-m17-set | receptors imported in the docking area; real M17 inspection (approval) + enumeration at site 22 → the fixture candidate ids in set order | pass | batch-main:pass |
| B-select | candidate set + parent SDF; M17 filter (heavy atoms ≤ 45, passes only) rows = the server's filtered page and the stored properties; checkboxes; 선택 n / 50; ids recorded in set order, not click order | pass | batch-main:pass |
| B-refusal | water/zinc receptor → preflight refused receptor_unsupported_residue; the refusal list (seven residue fields, nulls kept, atom names) equals the fixture oracle; no job, no event | pass | batch-main:pass |
| B-preflight | N 4 (parent + 3), needed 4 units / 1500 s = spec 6.3 arithmetic, remaining = budget, shortfall 0, no-refund note, wait note, rows new/reused, B1 verbatim; the view shows the server numbers | pass | batch-main:pass |
| B-no-approval | no limit approval control while the shortfall is 0 | pass | batch-main:pass |
| B-run | real qvina_batch_dock_v1 to done without a second approval, exactly N units, summary listed not opened | pass | batch-main:pass |
| B-table | status, B1/B3, every row (state, score = stored first row with ROUND_HALF_UP, score target, reason, reuse mark, detail) equals the stored summary and per-row results (no client recompute) | pass | batch-main:pass |
| B-sort | row/candidate/score headers both ways follow the stored values; rows without a score always last; aria-sort; no rank column | pass | batch-main:pass |
| B-detail | 상세 열기 → the existing M18 detail of that row's stored result; pose SDF download = stored pose_sdf | pass | batch-main:pass |
| B-dedupe | identical batch: preflight N 0 and the existing job; 일괄 시작 shows that job again (no new job, no unit) | pass | batch-main:pass |
| B-reuse | subset batch: preflight N 0 / needed 60 s; a new job with no unit; every row marked 저장된 결과 재사용 with the stored handles | pass | batch-main:pass |
| B-core-parent-disabled | 코어 고정 clears and disables the parent row with batch_parent_not_allowed (no number) | pass | batch-main:pass |
| B-limit-approval | core-fixed N 3 with 2 units left → shortfall 1, approval control shown, start blocked (batch_limit_raise_required); explicit approval raises the limit by the shortfall only (by human, batch context, no job/object), preflight re-read; the raised limit stays (global budget = backend) | pass | batch-main:pass |
| B-core-fixed | core-fixed batch rows show 샘플 1(점수 오름차순 나열) scores equal to the stored results | pass | batch-main:pass |
| B-report | 보고서 만들기 → 리간드 도킹 일괄 보고서 in the knowledge-tab list (B1, B3, score name); Markdown/JSON downloads equal the backend | pass | batch-main:pass |
| B-fail-row | planar parent fixture → the parent row fails ligand_not_3d (no score, detail disabled), the candidate rows are scored, the batch is complete, 4 units | pass | batch-main:pass |
| B-cancel | slow batch cancelled after a finished row → partial / cancelled; finished row kept with its score, running row cancelled, the rest not_run with the reason and no number; no worker/qvina2 left; no refund | pass | batch-main:pass |
| B-cap | labeled generated chain set (59): 50 selected, the 51st cannot be ticked; preflight N = 50 − reused finished rows, 7800 s, shortfall, may-be-partial note, approval offered (not used), start blocked | pass | batch-main:pass |
| B-dry-run | labeled dry-run run record: dry-run note, no limit approval control, nothing computed | pass | batch-main:pass |
| B-processes | no batch worker, docking worker, M17 worker, guardian or qvina2 process under the runs folder | pass | batch-main:pass |
| B-wording | no rank/best/optimum/improvement/binding-strength/affinity word in the batch area outside the fixed sentences and the score names | pass | batch-main:pass |
| B-no-run | no run: the batch area shows only the no-run reason (no numbers, no controls) | pass | batch-unavailable:pass |
| B-unavailable | backend without the locked environments: 사용할 수 없음 with the capability reason (worker_missing), no numbers, no controls, no batch requests | pass | batch-unavailable:pass |
| B-reproducible | the flow's free batch run again in two fresh runs: the summary and every row result (contents with the run-scoped obj:// handles and input hashes replaced) and the poses SDF bytes equal the flow's (cpu 1, seed fixed) | pass | runner:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- B-dry-run-shortfall: a dry-run run cannot hold a candidate set (M17 jobs only plan there), so an admitted preflight with a shortfall cannot be reached in one; covered by frontend/tests/docking-batch.test.cjs and backend/tests/test_docking_batch_budget.py.
- B-null-result: qvina returns modes for every valid input here; no zero-mode row is forged. Covered by the backend batch tests and frontend/tests/docking-batch.test.cjs.
- B-time-limits: candidate_timeout, time_exhausted, worker_failed and the output cap need hours or a killed worker; covered by backend/tests/test_docking_batch_worker.py and test_docking_batch_jobs.py with test-only reduced constants.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| batch-main | pass |  |
| batch-unavailable | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m19_offscreen_acceptance.py --root runs/m19-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/<label> \
    --out docs/qa/m19-batch-<YYYYMMDD>/acceptance
```
