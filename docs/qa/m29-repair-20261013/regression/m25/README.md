# M25 JEV 루프 오프스크린 수락 QA 증거 (fixture 단계)

- 생성: 2026-10-13T16:08:01.779438+00:00 · verdict **fail** · acceptance **false** (범위: fixture, --live-calls 0)
- 빌드: {"buildId": "zHxijM08Zpd_R8U7RDu8X", "gitHead": "5fe7f208c0e544e92382fc0f87f93c0795c9245c", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "b9355b8ac813f75d14bf5ab2e03af96da626d3610e6bca03386154cbd5193c70", "dirtyFiles": ["?? docs/qa/m29-repair-20261013/regression/"], "recordedAt": "2026-10-13T16:06:10.888224+00:00", "codeRoot": "<repo>", "harnessSha256": {"jev-loop-flow.cjs": "6a4eef9223abb1c6bfc40be99c560379a1d37616780f06881511ac308022cea2", "jev-flow.cjs": "3fa77454cba84914570de78dad662187f9b52ca7fa0ca727ceeff5e89e7a0521", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "fixtureServerSha256": "199b5b1fac6ef509c3760a161f8258ab7ed43e3c0989be8dd8312c4c07126cb9", "qaSetupSha256": "f973aee568be6882b1c514eb08312be0739709c01e69b7407127da8ab6a80c29", "runnerSha256": "e0787b7f2953774cbc1ef0fd8b18422024741d9a842a7a8820f4f2860bea2865"}
- 환경: M17 True · 도킹 True · qvina True · jev_loop ligand True / protein True · fixture 서버 True · 키 존재(불리언) None · .env 비공개 None
- 입력: run L = 공개 준비 수용체 예제·공개 파생 부모·합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 교체), run P = 공개 1UBQ(22곳)·1MQ4(3곳) A 치환 실제 M20 후보 집합과 합성 표시 페놀 SDF.
- 남은 프로세스/포트: 없음
- 내보낸 증거 검사(키·placeholder·문구) 실패: {"ok": false, "keyScanOk": true, "keyHits": [], "sentinelHits": [], "wording": {"evidence/case-ledger.json": ["최솟값"], "evidence/jev-loop-fixture/jev-loop-fixture.jsonl": ["최솟값"], "evidence/runner-summary.jsonl": ["최솟값"]}, "checkedAt": "2026-10-13T16:08:01.954065+00:00"} — acceptance false
- 브라우저 비-loopback 요청 합계: 0

- 실호출: 0회. fixture 서버(SCIENCE_GATE = 스크립트된 httpx.MockTransport)만 썼고, 이 단계의 dispatch 이벤트 2개 = fixture transport 호출 2개, response_received 감사 2개 = 응답한 호출 2개, 자격 증명 해석 {"productResolverReads": 0, "sentinelReads": 2, "updatedAt": "2026-10-13T16:07:53.998659+00:00"}.

스크린숏·paint 프레임 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. 키·헤더·원시 오류는 기록하지 않는다. 고른 목록 위치는 관찰값으로만 기록했다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| L-tab-entry | 리간드 탭 진입: GET 읽기만, 동의 꺼짐, UL1·UL3, 루프 없음, 집합·목표 자동 선택 없음, seed 비어 있음, 반복 상한 5 | fail | jev-loop-fixture:fail |
| L-create-fields | 만들기 칸별 이유: 풀 1개(pool_invalid)·목표 없음(goal_invalid)·seed 비어 있음(seed_invalid)·반복 상한 9(iteration_cap_invalid)·계산 조건, 만들기 단추 닫힘 | fail | jev-loop-fixture:fail |
| L-create | 루프 만들기: jev_loop_created 하나, 바퀴 1 선택 대기, 요청 = 화면 입력 | fail | jev-loop-fixture:fail |
| L-loop-active | 같은 갈래의 끝나지 않은 루프가 있으면 만들기가 loop_active 이유와 함께 닫힘 | fail | jev-loop-fixture:fail |
| L-consent-off-block | 동의 꺼짐: 미리보기 consent_off, 확인 체크를 해도 전송 단추 닫힘 | fail | jev-loop-fixture:None |
| L-preview-match | 미리보기 <pre> = 서버 문자열, 여기서 계산한 SHA-256·바이트 = 표시 = 저장 투영 | fail | jev-loop-fixture:None |
| L-order-oracle | 후보 순서·별칭·criteria·computed 행 = 독립 sha256_order_v1 계산, 질문 = 명세 4.5 문장 | fail | jev-loop-fixture:None |
| L-consent-toggle | 동의 켬: 차단 이유 없음, 전역 줄 run id 바로 뒤 "과학 전송 허용" | fail | jev-loop-fixture:None |
| L-confirm-required | 확인 체크 없이는 전송 단추가 닫히고 이유가 보임; 체크하면 열림 | fail | jev-loop-fixture:None |
| L-failed-model | fixture model_mismatch: failed model_mismatch, 이유만 | fail | jev-loop-fixture:None |
| L-ordinal-refused | dispatch 뒤 같은 투영은 ordinal_mismatch로 막히고 다시 만들면 새 순서 | fail | jev-loop-fixture:None |
| L-bytes-equal | 전송마다 transport 수신 바이트 SHA-256 = 미리보기 = 감사 prepared(본문 같음) | fail | jev-loop-fixture:None |
| L-send-good | fixture good_second(두 번째 criteria 키): completed, 기록이 전송을 알기 전에는 확인 중 줄만, 이 바퀴의 선택, 목록 위치 2/5, 계산이 그 후보로 시작 | fail | jev-loop-fixture:None |
| L-choice-card | JEV 판정(모델 선택) 카드 = 저장 제안: 목록 위치 n/m, 확신도, 모델, 사용량, 접힌 후보별 값은 보낸 순서 그대로, 정렬·막대·색 비교 요소 없음 | fail | jev-loop-fixture:None |
| L-compute-jev | 이 선택으로 계산 시작: decided_by jev 승인 하나, 단독 M18 작업 | fail | jev-loop-fixture:None |
| L-real-engine | 실제 qvina 도킹, 점수 = 저장 결과 첫 모드(소수 첫째 자리 표시) | fail | jev-loop-fixture:None |
| L-failed-computed-alias | fixture computed_alias: 게이트에서 response_invalid, 이유만 | fail | jev-loop-fixture:None |
| L-late | fixture slow 중 동의 끄기: completed + 늦은 응답, 이 바퀴의 선택이 아님, J7 | fail | jev-loop-fixture:None |
| L-designate | 직접 지정(늦은 응답이 고른 후보): decided_by human, 실제 도킹 | fail | jev-loop-fixture:None |
| L-designate-no-send | 전송 없는 바퀴의 직접 지정, 유효 반복 상한 도달(iteration_cap) | fail | jev-loop-fixture:None |
| L-candidate-table | 후보 표(루프 A: pending, 루프 B: 재사용 행·계산 행·pending): 네 열 모두 오름·내림에서 여기서 쓴 순서 규칙과 같음(점수 없는 행은 끝·풀 순서, 재사용 행은 바퀴 열에서 번호 있는 행 뒤), aria-sort, 순번 열·강조 없음 | fail | jev-loop-fixture:None |
| L-end-summary | 루프 끝내기: iteration_cap, 요약 jev_loop_result@1 = 기록, LJ8 | fail | jev-loop-fixture:None |
| L-report | 보고서 만들기: 목록의 "JEV 루프 보고서"와 저장된 Markdown(고정 문장, 확률 없음) | fail | jev-loop-fixture:None |
| L-reuse | 저장된 같은 조건 결과는 계산됨(저장된 결과 재사용, 단위 0) | fail | jev-loop-fixture:None |
| L-no-usage-stop | fixture no_usage: completed, 사용량 "알 수 없음", 외부 전송 멈춤(usage_unknown), 다음 루프 미리보기 egress_stopped | fail | jev-loop-fixture:None |
| L-send-cap-display | run 전송 상한 줄 = dispatch 수(10회 중 5회) | fail | jev-loop-fixture:None |
| L-knowledge-rows | 지식·보고서 전송 기록: 루프 전송은 읽기 전용 "JEV 루프" 행, 열기·보고서 만들기 단추 없음 | fail | jev-loop-fixture:None |
| L-other-tabs | 다른 영역의 숫자를 가린 글자가 같음(M18 도킹 영역은 루프의 단독 결과를 목록에 보임), 진입 POST 없음, 구조 분석 숨김 | fail | jev-loop-fixture:None |
| P-tab-entry | 단백질 탭 진입: GET 읽기만, UL1·UL3·U3, 두 집합 모두 고르지 않음 | pass | jev-loop-fixture:pass |
| P-pool-limit | 20개 체크 뒤 21번째 거절(이유 표시), 1개로 줄이면 최소 2(pool_invalid) | pass | jev-loop-fixture:pass |
| P-create-fields | 단백질 칸별 이유: 목표·seed·반복 상한 0·확인 두 항목(confirmation_missing)·cutoff 7(argument_invalid) | pass | jev-loop-fixture:pass |
| P-create-refused | 1MQ4 풀: 서버 422 setup_invalid(openmm_preflight_failed)가 계산 조건 칸에, 이벤트 없음 | pass | jev-loop-fixture:pass |
| P-create | 1UBQ 풀 3개로 루프 만들기, loop_active | pass | jev-loop-fixture:pass |
| P-send-good | fixture good_second: 변이 본문(좌표·서열·handle 없음) 전송, 카드의 잔기 표기와 목록 위치 2/3, 모델링·도킹이 그 후보로 시작 | pass | jev-loop-fixture:pass |
| P-bytes-equal | 단백질 전송 바이트 = 미리보기 = 감사 prepared = transport | pass | jev-loop-fixture:pass |
| P-order-oracle | 단백질 순서·별칭·criteria = 독립 계산 | pass | jev-loop-fixture:pass |
| P-first-approval | 첫 비싼 계산 승인 안내 → 비싼 계산 승인(POST /jobs/approve) → 작업 시작(새 승인 이벤트 없음) | pass | jev-loop-fixture:pass |
| P-end-refused-job | 작업 대기 중 루프 끝내기 닫힘(job_running) | pass | jev-loop-fixture:pass |
| P-end-refused-docking | 도킹 대기 중 루프 끝내기 닫힘(docking_pending) | pass | jev-loop-fixture:pass |
| P-dock | 변이 구조에 도킹: 점수 = 저장 결과 첫 모드, 수용체 = 그 모델의 변이형 | pass | jev-loop-fixture:pass |
| P-real-engine | 실제 PDBFixer·OpenMM 모델링과 qvina 도킹 | pass | jev-loop-fixture:pass |
| P-abandon | 도킹 포기: not_run(docking_not_run), 유효 반복 상한 도달 | pass | jev-loop-fixture:pass |
| P-end-summary | 루프 끝내기: iteration_cap, 요약, LJ8 | pass | jev-loop-fixture:pass |
| P-report | 단백질 루프 보고서 저장과 목록 | pass | jev-loop-fixture:pass |
| P-candidate-table | 후보 표(점수 행·not_run·pending): 네 열 모두 오름·내림에서 여기서 쓴 순서 규칙과 같음(not_run·pending은 끝·풀 순서), 후보 열은 번호 순, aria-sort | pass | jev-loop-fixture:pass |
| P-reuse | 모델·변이형 도킹이 저장된 후보는 재사용(단위 0), 활용형 computed 행은 저장 점수 그대로 | pass | jev-loop-fixture:pass |
| P-failed-http | fixture HTTP 500: failed provider_http_error, 이유만, 외부 전송 멈춤 | pass | jev-loop-fixture:pass |
| P-pair-loop | M21 같은 조건 짝 표: "루프 도킹(야생형 없음) · 바퀴 1"(loop 키), 야생형 쪽 점수 없음 | pass | jev-loop-fixture:pass |
| P-knowledge-rows | 지식·보고서: run P의 루프 전송 두 줄이 읽기 전용 행 | pass | jev-loop-fixture:pass |
| P-other-tabs | run P의 다른 영역 불변(M21 영역·M18 도킹 영역은 루프 결과 목록), 구조 분석 숨김 | pass | jev-loop-fixture:pass |
| X-fixture-proof | 흐름 안 확인: fixture transport 호출 = dispatch 이벤트 = 바이트 대조 행, placeholder만, 제품 키 해석기 0회 | pass | jev-loop-fixture:pass |
| X-wording | 화면 문구 검사(고정 문장·지시문·본문 줄 제외) 모든 시점 통과 | pass | jev-loop-fixture:pass |
| X-no-egress-browser | 브라우저의 비-loopback 요청 0건 | pass | jev-loop-fixture:pass |
| S-browser-egress-zero | 모든 흐름 행의 브라우저 비-loopback 요청 0건 | pass | runner:pass |
| S-key-absent | 증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건 | pass | runner:pass |
| S-wording-evidence | 증거 텍스트에 금지 표현 0건(고정 문장·지시문·보낸 본문 줄 제외) | fail | runner:fail |
| S-real-calls-zero | 실호출 0회: 서버 기록이 MockTransport 게이트이고 이 단계의 dispatch·response_received 감사 수가 fixture transport 호출 기록과 같으며 모든 호출의 인증 값이 placeholder였고 제품 키 해석기 호출 0회 | pass | runner:pass |

## 관찰하지 않은 사례

- JL-calibrate-send: 관찰하지 않음 — 실호출은 T12의 calibrate·live 단계에서만 한다. 이 실행은 가짜 transport fixture 서버만 썼다(실호출 0회).
- JL-live-sends: 관찰하지 않음 — 실호출은 T12의 calibrate·live 단계에서만 한다. 이 실행은 가짜 transport fixture 서버만 썼다(실호출 0회).
- L-late-run-cancelled: run 취소 뒤 도착한 루프 응답: 화면에 run 취소 경로가 없다. backend/tests/test_jev_loop_sends.py::test_a_late_reply_is_kept_but_never_the_selection 이 덮는다.
- L-unavailable-before-start: 시작 전 취소된 후보(unavailable): backend/tests/test_jev_loops_compute.py::test_two_presses_make_one_step_and_a_job_cancelled_before_start_is_unavailable 이 덮는다.
- L-budget-blocked: 계산 예산 부족(budget_blocked)과 budget_exhausted 끝내기: 화면 run은 한도를 늘리거나 줄이지 않는다. test_jev_loops_compute.py::test_budget_blocked_names_each_short_axis_and_charges_nothing, test_a_loop_short_of_compute_budget_ends_budget_exhausted_with_its_unfinished_iteration 이 덮는다.
- L-end-server-refusal: 끝내기 서버 거절(job_running·docking_pending): 화면은 단추를 닫아 요청을 보내지 않는다. test_jev_loops_compute.py::test_end_refusals_follow_the_spec_order_and_write_nothing 이 덮는다.
- L-send-cap-ten: run당 10회 전송 소진: 한 run의 fixture 계획이 5회에서 외부 전송 멈춤으로 끝난다. test_jev_loop_sends.py::test_the_ten_send_cap_and_the_budget_are_shared_with_m24_sends 가 덮는다.
- L-dry-run: 연습용 run: test_jev_loop_sends.py::test_a_loop_projection_in_a_dry_run_run_names_no_loop_and_never_reads_the_key 가 덮는다.
- L-sort-null-failed: null_result·failed 후보 행의 표 정렬 위치: 화면 run의 실제 도킹이 포즈 없음이나 실패를 만들지 않아 실제 루프 상태로 보이지 못했다(fixture가 결과를 꾸며 넣지 않는다). frontend/tests/jev-loop.test.cjs의 "candidate order: display only; rows without a score are last in every column and direction, ties in pool order" 가 덮고, 화면은 pending·not_run·재사용 행으로 같은 규칙을 확인했다.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| jev-loop-fixture | fail | status fail |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<label> \
    --out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-fixture   # --phase fixture (실호출 0)
# 연습(실호출 0): --phase calibrate --rehearse --live-calls 8, 같은 --root로 --phase live --rehearse
# 실호출(사용자 할당 8회 안에서만): 새 --root로 --phase calibrate --live-calls 8, 이어서 같은 --root로
# --phase live --live-calls 8 (저장소 대장 합계 + 계획이 8을 넘으면 거절)
# calibrate 실호출 뒤 증거를 쓰기 전에 멈췄으면: 같은 --root·--artifacts로 --phase calibrate --finalize
```
