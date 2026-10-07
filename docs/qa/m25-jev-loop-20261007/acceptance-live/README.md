# M25 JEV 루프 오프스크린 수락 QA 증거 (live 단계)

- 생성: 2026-10-07T17:04:44.461878+00:00 · verdict **pass** · acceptance **true** (범위: live, --live-calls 8)
- 빌드: {"buildId": "W4Fsnhol08JIGulRiMyz7", "gitHead": "c092591e4f6fcd5ce2932c80a6c6df885687c756", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "dirtyFiles": [], "recordedAt": "2026-10-07T17:01:39.903458+00:00", "codeRoot": "<repo>", "harnessSha256": {"jev-loop-flow.cjs": "6a4eef9223abb1c6bfc40be99c560379a1d37616780f06881511ac308022cea2", "jev-flow.cjs": "b372e73f5d68c6e2b26ead6e42d9782aa2a9f42b60606dad2d8ed392a5638982", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "fixtureServerSha256": "199b5b1fac6ef509c3760a161f8258ab7ed43e3c0989be8dd8312c4c07126cb9", "qaSetupSha256": "f973aee568be6882b1c514eb08312be0739709c01e69b7407127da8ab6a80c29", "runnerSha256": "e0787b7f2953774cbc1ef0fd8b18422024741d9a842a7a8820f4f2860bea2865"}
- 환경: M17 True · 도킹 True · qvina True · jev_loop ligand True / protein True · fixture 서버 None · 키 존재(불리언) True · .env 비공개 True
- 입력: run L = 공개 준비 수용체 예제·공개 파생 부모·합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 교체), run P = 공개 1UBQ(22곳)·1MQ4(3곳) A 치환 실제 M20 후보 집합과 합성 표시 페놀 SDF.
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0

- 실호출 계수(모든 QA run): {"run_3c47e688f11048a485180e132da985b8": {"dispatch": 3, "responseReceived": 3, "scienceResponses": 3}, "run_a6f1fdc86c674f33b5cf975a085dc3a4": {"dispatch": 5, "responseReceived": 5, "scienceResponses": 5}} · 한도 8 · 판정 True
- 저장소 대장 Git 제외 runs/m25-live-ledger.json: 단계 전 1회 + 이번 계획 7회, 단계 뒤 합계 8회 / 8 · 판정 True
- 계획 예산: {"ok": true, "plan": {"ok": true, "needs": {"L": {"expensive_units": 5, "wall_clock_s": 1140, "external_tokens": 61440, "usd": 0.5, "sends": 5}, "P": {"expensive_units": 6, "wall_clock_s": 1260, "external_tokens": 77826, "usd": 0.3, "sends": 3}}, "limits": {"expensive_units": 8, "wall_clock_s": 1800, "external_tokens": 120000, "usd": 2.0, "sends": 10}, "short": {"L": [], "P": []}}, "phaseNeeds": {"L": {"expensive_units": 5, "wall_clock_s": 1140, "external_tokens": 49152, "usd": 0.4, "sends": 4}, "P": {"expensive_units": 6, "wall_clock_s": 1260, "external_tokens": 77826, "usd": 0.3, "sends": 3}}, "remainingShort": {"L": [], "P": []}}
- 첫 전송 보정: {"ok": true, "flowPassed": true, "entry": "L-explore-calibrate", "status": "completed", "reasonCode": null, "servedModel": "typesafe/jev-1.13-20260917", "bodyBytes": 3855, "aliases": 5, "usage": {"cost": 9.0468e-05, "external_tokens": 2219, "input_tokens": 2154, "output_tokens": 65}, "reservation": {"external_tokens": 6666, "usd": 0.1}, "egressStop": null, "responseShape": {"answersParsed": true, "confidence": true, "probabilities": true, "probabilityCount": 5}, "reservationFormula": "min(50000, 4096 + ceil(body_bytes × 2 / 3)) external tokens and USD 0.10 per send", "withinReservation": true, "adjustmentSuggested": false, "adjustmentNote": "예약식 조정은 사용자 결정이며 실행기는 자동으로 바꾸지 않는다", "bodyBytesPerInputToken": 1.7896935933147633, "reservedTokensOverUsed": 3.0040558810274898}
- 섞기 확인(관찰값만 기록): {"planned": true, "ok": true}

스크린숏·paint 프레임 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. 키·헤더·원시 오류는 기록하지 않는다. 고른 목록 위치는 관찰값으로만 기록했다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| JL-live-sends | 나머지 계획: 리간드 활용형 3바퀴(바퀴마다 전송 1회와 실제 qvina), 단백질 활용형 3바퀴(다른 run, 실제 모델링·도킹), 섞기 확인 1회(같은 풀·목표, 다른 루프 seed): 결과 카드·계산·요약·보고서, 다른 탭 불변 | pass | jev-loop-live:pass |
| S-browser-egress-zero | 모든 흐름 행의 브라우저 비-loopback 요청 0건 | pass | runner:pass |
| S-key-absent | 증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건 | pass | runner:pass |
| S-wording-evidence | 증거 텍스트에 금지 표현 0건(고정 문장·지시문·보낸 본문 줄 제외) | pass | runner:pass |
| JL-count | 실호출 계수: 모든 QA run의 dispatch 이벤트와 response_received 감사가 --live-calls 이하, run마다 계획 상한 이하 | pass | runner:pass |
| JL-ledger | 실호출 대장(Git 제외 runs/m25-live-ledger.json, 모든 root의 dispatch 이벤트로 확정, 실패한 전송 포함): 단계 뒤 합계 8회 이하. 시작 전 대장 합계 + 이번 계획이 8을 넘거나 --live-calls가 남은 양을 넘거나 대장을 읽을 수 없으면 거절 | pass | runner:pass |
| JL-budget | 계획의 run별 필요량(비싼 계산 단위·활동 시간·외부 토큰·USD·전송 수)이 run 기본 한도와 남은 예산 안 | pass | runner:pass |
| JL-calibration | 첫 실호출: completed, 사용량(입력·출력 토큰·비용)을 알고 예약값 이하, 외부 전송 멈춤 없음, calibrate 흐름 통과 | pass | runner:pass |
| JL-shuffle-observed | 섞기 확인: 같은 풀·목표·다른 루프 seed의 두 첫 전송의 순서와 고른 목록 위치를 관찰값으로만 기록 | pass | runner:pass |

## 관찰하지 않은 사례

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
| jev-loop-live | pass |  |

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
