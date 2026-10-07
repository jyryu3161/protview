# M24 JEV 과학 전송 오프스크린 수락 QA 증거 (fixture 단계)

- 생성: 2026-10-07T15:55:38.696604+00:00 · verdict **pass** · acceptance **true** (범위: fixture, --live-calls 0)
- 빌드: {"buildId": "W4Fsnhol08JIGulRiMyz7", "gitHead": "436059863ccc88a46a9c2c66a6b70dbc2c90bd34", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "4e6d3002035cc3f7c3b864da5bc413a4e47b6ab952fdef663eb886a79727c3e4", "dirtyFiles": [" M frontend/tests/offscreen/jev-flow.cjs", "?? docs/qa/m25-jev-loop-20261007/acceptance-fixture/", "?? docs/qa/m25-jev-loop-20261007/gate-backend.txt", "?? docs/qa/m25-jev-loop-20261007/gate-frontend.txt", "?? docs/qa/m25-jev-loop-20261007/gate-invariants.txt", "?? docs/qa/m25-jev-loop-20261007/m23-regression/"], "recordedAt": "2026-10-07T15:54:46.446143+00:00", "codeRoot": "<repo>", "harnessSha256": {"jev-flow.cjs": "b372e73f5d68c6e2b26ead6e42d9782aa2a9f42b60606dad2d8ed392a5638982", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "fixtureServerSha256": "03b316c610c567af6c1c13b8069577b4c264bd2c007c426d625fdc21b3a96455", "runnerSha256": "9e839455a10619d2d770ead97501445b193c7aa8864c23f94d50ad33a31e0a38"}
- 환경: M17 venv-locked 있음 · ligand_candidates True · mutation_candidates True · jev_choice True · fixture 서버 True · 키 존재(불리언, 증거 검색용 해석기) True
- 입력: 공개 1UBQ·1MQ4(`backend/tests/fixtures/public_*.cif`, 이웃 수가 많은 Ala 아닌 잔기 22·24곳, A로만 치환한 실제 M20 후보 집합), 공개 파생 부모 + 합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 교체).
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0

- 실호출: 0회. fixture 서버(SCIENCE_GATE = 스크립트된 httpx.MockTransport)만 썼고, dispatch 이벤트 18개 = fixture transport 호출 18개, response_received 감사 18개 = 응답한 호출 18개.

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. 키·헤더·원시 오류는 기록하지 않는다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| J-tab-entry | 지식·보고서 탭 진입: GET 읽기만, 동의 꺼짐, 자동 선택·작성·전송 없음, 고정 안내와 U2·U3, run당 10회 중 0회 사용, 구조 분석 패널은 숨김·inert로 유지, 전역 표시 없음 | pass | jev-fixture:pass |
| J-source-choice | 후보 집합 종류와 집합을 사람이 직접 고름(두 변이 집합이 보이고 아무것도 미리 고르지 않음) | pass | jev-fixture:pass |
| J-consent-off-block | 동의 꺼짐: 미리보기 차단 이유 consent_off, 확인 체크를 해도 전송 단추가 닫힘 | pass | jev-fixture:pass |
| J-consent-toggle | 동의 켬: 차단 이유 없음, 전역 줄 run id 바로 뒤에 "과학 전송 허용"; 끔: 표시가 사라지고 consent_off가 돌아옴 | pass | jev-fixture:pass |
| J-candidate-limit | 20개까지 체크, 21번째 클릭은 체크되지 않고 이유가 보임(20개 유지) | pass | jev-fixture:pass |
| J-preview-match | 보낼 내용 만들기: <pre> 본문 = 서버 미리보기 문자열, 여기서 계산한 SHA-256·바이트 = 표시 = 저장 투영, 별칭 표 = 저장 선택 | pass | jev-fixture:pass |
| J-confirm-required | 확인 체크 없이는 전송 단추가 닫히고 이유가 보임; 체크하면 열림 | pass | jev-fixture:pass |
| J-send-good | fixture good: completed, 결과 카드 = 저장된 제안(별칭·로컬 표기·확신도·모델·사용량·접힌 후보별 값은 보낸 순서 그대로·J1–J4와 J6), 정렬·막대·색 비교 요소 없음 | pass | jev-fixture:pass |
| J-bytes-equal | transport가 받은 바이트의 SHA-256 = 미리보기 = 감사 prepared 본문(같은 내용)과 payload_sha256 | pass | jev-fixture:pass |
| J-resend | 같은 본문 다시 보내기(good_no_extras): 미리보기의 이전 전송 1회, 별도의 두 번째 제안, 기록에 시간순 두 줄과 U1, 합친 줄 없음, 받지 않은 값은 "보고 없음" | pass | jev-fixture:pass |
| J-report | 보고서 만들기: 보고서 목록에 "JEV 판정 보고서", 클릭하면 저장된 Markdown(고정 문장 포함, 후보별 값 없음) | pass | jev-fixture:pass |
| J-ligand-filter | 리간드 집합: 필터를 통과하지 못한 후보는 체크할 수 없고 "필터 통과만 보기"는 통과 행만, 필터가 요청과 투영에 실림 | pass | jev-fixture:pass |
| J-failed-alias | fixture alias_outside: failed response_invalid, 이유만(카드·숫자 없음) | pass | jev-fixture:pass |
| J-failed-model | fixture model_mismatch: failed model_mismatch, 이유만 | pass | jev-fixture:pass |
| J-late | fixture slow 중 동의 끄기: completed + 늦은 응답(동의 끈 뒤 도착)과 J7, 기록 줄 표시, 전역 표시 사라짐 | pass | jev-fixture:pass |
| J-send-cap | 1MQ4 20개 후보로 열 번째 전송까지: 사용 10회·남은 0회, 미리보기 send_cap_exhausted, 전송 단추 닫힘 | pass | jev-fixture:pass |
| J-other-tabs | 단백질 공학·리간드 설계·탐색 탭의 영역과 숫자를 가린 글자가 JEV 동작 전후로 같고 JEV 요소·POST 없음, 구조 분석 뷰어는 같은 세션·소스 | pass | jev-fixture:pass |
| J-no-usage-stop | run B fixture no_usage: completed, 사용량 네 칸 모두 "알 수 없음", 외부 전송 멈춤(usage_unknown), 미리보기 egress_stopped, 전송 단추 닫힘 | pass | jev-fixture:pass |
| J-failed-http | run C fixture HTTP 500: failed provider_http_error, 이유만 | pass | jev-fixture:pass |
| J-wording | 금지 표현 검사(고정 문장 J1–J7·U1–U3 제외): 화면 여러 시점, 보고서 Markdown, fixture 응답 | pass | jev-fixture:pass |
| J-no-egress-browser | 브라우저의 비-loopback 요청 0건 | pass | jev-fixture:pass |
| J-live-rehearsal | 실호출 계획(여섯 전송, run당 셋 이하)을 같은 화면 경로로 fixture 서버에 대고 calibrate·live 두 번으로 나눠 미리 돌림: calibrate 리허설은 첫 전송 전에 전송 없이 사전 확인(L1의 1UBQ 집합: 동의 끔 → 미리보기 consent_off·확인 체크해도 전송 단추 닫힘 → 다시 켬, 20개 체크 뒤 21번째 거절 → 5개로 줄임, 확인 체크 전 전송 단추 닫힘, 전송 요청·dispatch 0) 뒤 한 전송, live 리허설은 새 화면에서 나머지 다섯 전송; 모두 completed, 결과 카드의 후보별 값은 처음에 접힘, 전송 전 계수 확인, 보고서 하나, 다른 탭 불변 | pass | jev-rehearsal-calibrate:pass, jev-rehearsal-live:pass |
| S-browser-egress-zero | 모든 흐름 행의 브라우저 비-loopback 요청 0건 | pass | runner:pass |
| S-key-absent | 증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건 | pass | runner:pass |
| S-wording-evidence | 증거 텍스트에 금지 표현 0건(고정 문장 제외) | pass | runner:pass |
| S-real-calls-zero | fixture 단계 실호출 0회: 서버 기록이 MockTransport 게이트이고 dispatch·response_received 감사 수가 fixture transport 호출 기록과 같으며 모든 호출의 인증 값이 placeholder였음(불리언) | pass | runner:pass |

## 관찰하지 않은 사례

- JL-calibrate-send: 관찰하지 않음 — 실호출 할당은 T10. 이 실행은 가짜 transport fixture 서버만 썼다(OpenRouter 실호출 0회). 실호출은 --phase calibrate --live-calls N, 이어서 같은 --root로 --phase live --live-calls N.
- JL-live-sends: 관찰하지 않음 — 실호출 할당은 T10. 이 실행은 가짜 transport fixture 서버만 썼다(OpenRouter 실호출 0회). 실호출은 --phase calibrate --live-calls N, 이어서 같은 --root로 --phase live --live-calls N.
- J-late-run-cancelled: run 취소 뒤 도착한 응답: HTTP 취소 경로가 없어 화면에서 만들 수 없다. backend/tests/test_jev_sends.py::test_a_valid_reply_after_cancel_or_consent_off_is_kept_and_marked_late 가 덮는다.
- J-timeout-transport: external_timeout·transport_error: backend/tests/test_jev_science_gate.py::test_transport_timeout_is_external_timeout_and_usage_unknown, test_other_transport_errors_are_transport_error 가 덮는다.
- J-missing-credential: 키 없음(missing_credential): backend/tests/test_jev_science_gate.py::test_missing_or_unusable_key_is_missing_credential_after_one_read 가 덮는다.
- J-restart-derivation: 재시작 뒤 delivery_unknown·outcome_not_recorded 도출: backend/tests/test_jev_sends.py::test_restart_without_an_outcome_derives_delivery_unknown_or_outcome_not_recorded 가 덮는다.
- J-send-in-progress: 다른 전송 진행 중(send_in_progress): 화면이 한 번에 한 전송만 열어 두 번째 전송을 만들 수 없다. backend/tests/test_jev_sends.py::test_a_send_in_flight_blocks_other_sends_and_reads_as_in_progress 가 덮는다.
- J-dry-run: dry-run run: backend/tests/test_jev_sends.py::test_dry_run_cannot_enable_consent_and_rejects_sends 가 덮는다.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| jev-fixture | pass |  |
| jev-rehearsal-calibrate | pass |  |
| jev-rehearsal-live | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m24_offscreen_acceptance.py --root runs/m24-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<label> \
    --out docs/qa/m24-jev-<YYYYMMDD>/acceptance-fixture   # --phase fixture (실호출 0)
# 실호출(사용자 할당 안에서만): 새 --root로 --phase calibrate --live-calls N, 이어서 같은 --root로
# --phase live --live-calls N (N <= 6, run당 3회 이하; 저장소 대장 합계 + 계획이 6을 넘으면 거절)
# calibrate 실호출 뒤 증거를 쓰기 전에 멈췄으면: 같은 --root·--artifacts로 --phase calibrate --finalize
# (새 호출 없음, --live-calls 0, 비어 있는 --out)
```
