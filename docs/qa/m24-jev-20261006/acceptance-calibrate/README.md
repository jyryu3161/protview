# M24 JEV 과학 전송 오프스크린 수락 QA 증거 (calibrate 단계)

- 생성: 2026-10-06T14:24:42.839804+00:00 · verdict **pass** · acceptance **true** (범위: calibrate, --live-calls 6)
- 빌드: {"buildId": "L1WcPjrTR60b9VYSegZtb", "gitHead": "30f37959beca6db34116d6f5b906fa907ac76415", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "dirtyFiles": [], "recordedAt": "2026-10-06T14:04:09.773347+00:00", "codeRoot": "<repo>", "harnessSha256": {"jev-flow.cjs": "9e68cfe2292b2f4d3ec7802d24c001c704d84e44eee77e8a96d85088ebbfeed1", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a"}, "fixtureServerSha256": "03b316c610c567af6c1c13b8069577b4c264bd2c007c426d625fdc21b3a96455", "runnerSha256": "350ad5229d30cc06188b61b93c5d858c0c0f4f0bbe7b4f0130bdbf6f58600bc8"}
- 환경: M17 venv-locked 있음 · ligand_candidates True · mutation_candidates True · jev_choice True · fixture 서버 None · 키 존재(불리언, 증거 검색용 해석기) True
- 입력: 공개 1UBQ·1MQ4(`backend/tests/fixtures/public_*.cif`, 이웃 수가 많은 Ala 아닌 잔기 22·24곳, A로만 치환한 실제 M20 후보 집합), 공개 파생 부모 + 합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 교체).
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0

- 실호출 계수(모든 QA run): {"run_1b47383f84ce4286a686c21d1080a99d": {"dispatch": 1, "responseReceived": 1, "scienceResponses": 1}, "run_34c0b3fd12444b6fa261f34d241fa3a4": {"dispatch": 0, "responseReceived": 0, "scienceResponses": 0}} · 한도 1 · 판정 True
- 실호출 대장(저장소 단위, Git 제외 runs/m24-live-ledger.json, 모든 root의 dispatch 이벤트): 단계 전 0회 + 이번 계획 1회, 단계 뒤 합계 1회 / 6 · 판정 True
- 첫 실호출 보정: {"ok": true, "flowPassed": true, "entry": "L1-ligand-5", "status": "completed", "reasonCode": null, "servedModel": "typesafe/jev-1.13-20260917", "bodyBytes": 3539, "usage": {"cost": 8.7654e-05, "external_tokens": 2152, "input_tokens": 2087, "output_tokens": 65}, "reservation": {"external_tokens": 5866, "usd": 0.1}, "egressStop": null, "responseShape": {"confidence": true, "probabilities": true, "probabilityCount": 5}, "bodyBytesPerInputToken": 1.6957355055103018, "reservedTokensOverUsed": 2.725836431226766}
- 마무리 모드(--finalize, 2026-10-06T14:24:42.453136+00:00): 실호출을 마친 root의 저장 파일(live-state.json·jev-calibrate 행·runner-state.json·root의 이벤트·대장)만 읽어 이 증거를 다시 만들었다. 새 호출·빌드·서버·Electron·POST 없음, 대장·root·runner-state.json은 읽기만(대장 SHA-256 82e76fec91abb09d81bd954844245df3296695c058b90955738b0fbf798b28e1, 실행기 SHA-256 9e839455a10619d2d770ead97501445b193c7aa8864c23f94d50ad33a31e0a38, git 52181308dc7f7bc31b55173a9b6a283eb8f257ce).

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. 키·헤더·원시 오류는 기록하지 않는다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| JL-calibrate-send | 첫 실호출 클릭 전에 같은 화면에서 전송 없이(L1의 1UBQ 집합): 동의 끔 → 미리보기 consent_off·확인 체크해도 전송 단추 닫힘 → 다시 켬, 20개 체크 뒤 21번째 거절(체크되지 않고 이유 표시) → 5개로 줄임, 확인 체크 전 전송 단추 닫힘, 전송 요청·dispatch 이벤트 0; 이어서 첫 실호출 한 번(리간드 5개): 실제 JEV 결과 카드(후보별 값은 처음에 접힘)·고정 문장·보고서, 다른 탭 불변 | pass | jev-calibrate:pass |
| S-browser-egress-zero | 모든 흐름 행의 브라우저 비-loopback 요청 0건 | pass | runner:pass |
| S-key-absent | 증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건 | pass | runner:pass |
| S-wording-evidence | 증거 텍스트에 금지 표현 0건(고정 문장 제외) | pass | runner:pass |
| JL-count | 실호출 계수: 모든 QA run의 dispatch 이벤트와 response_received 감사가 --live-calls 이하, run당 3회 이하 | pass | runner:pass |
| JL-calibration | 첫 실호출: completed, 사용량(입력·출력 토큰·비용)을 알고 예약값 이하, 외부 전송 멈춤 없음, calibrate 흐름 전체(사전 확인·결과 카드·보고서·다른 탭) 통과 | pass | runner:pass |
| JL-ledger | 저장소 단위 실호출 대장(Git 제외 runs/m24-live-ledger.json, 모든 QA root의 dispatch 이벤트로 확정, 실패한 전송 포함): 단계 뒤 합계 6회 이하. 단계 시작 전에 대장 합계 + 이번 계획이 6을 넘거나 대장을 읽을 수 없으면 아무것도 시작하지 않고 거절 | pass | runner:pass |

## 관찰하지 않은 사례

- J-late-run-cancelled: run 취소 뒤 도착한 응답: HTTP 취소 경로가 없어 화면에서 만들 수 없다. backend/tests/test_jev_sends.py::test_a_valid_reply_after_cancel_or_consent_off_is_kept_and_marked_late 가 덮는다.
- J-timeout-transport: external_timeout·transport_error: backend/tests/test_jev_science_gate.py::test_transport_timeout_is_external_timeout_and_usage_unknown, test_other_transport_errors_are_transport_error 가 덮는다.
- J-missing-credential: 키 없음(missing_credential): backend/tests/test_jev_science_gate.py::test_missing_or_unusable_key_is_missing_credential_after_one_read 가 덮는다.
- J-restart-derivation: 재시작 뒤 delivery_unknown·outcome_not_recorded 도출: backend/tests/test_jev_sends.py::test_restart_without_an_outcome_derives_delivery_unknown_or_outcome_not_recorded 가 덮는다.
- J-send-in-progress: 다른 전송 진행 중(send_in_progress): 화면이 한 번에 한 전송만 열어 두 번째 전송을 만들 수 없다. backend/tests/test_jev_sends.py::test_a_send_in_flight_blocks_other_sends_and_reads_as_in_progress 가 덮는다.
- J-dry-run: dry-run run: backend/tests/test_jev_sends.py::test_dry_run_cannot_enable_consent_and_rejects_sends 가 덮는다.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| jev-calibrate | pass |  |

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
