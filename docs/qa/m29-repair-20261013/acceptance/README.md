# M29 구조 보완 수락 증거 (fixture)

- 생성: 2026-10-13T15:42:52.193650+00:00 · acceptance **true** · 통과 True · 사례 {"pass": 12, "fail": 0, "not_observed": 0}
- 단계: r1, r3, r4a, table, r8, r7, r6, r4b, pytest, r9 (일부만 돌리면 acceptance는 늘 false) · 구조 13개
- 소스: 1802a32f8711728155a8accef67c5e6c304eba06 · 작업 트리 변경 0개
- 관문: {"buildStamped": true, "browserNonLoopback0": true, "providerCalls0": true, "dispatchEvents0": true, "noForbiddenRequest": true, "noServerError": true, "noBackendTraceback": true, "nothingLeft": true, "defaultFoldersAbsent": true, "fixedSentencesExported": true, "exportClean": true}
- 외부 요청: {"browserNonLoopbackRequests": 0, "providerCalls": 0, "productResolverReads": 0, "dispatchEvents": 0, "harnessDispatchGuard": false, "apiRequests": 508, "apiForbiddenSent": 0, "harnessServerErrors": 0, "proxyTimeouts": [{"job": "job_3b64933a485349b886631904c1f6e36d", "method": "POST", "path": "/api/runs/<run>/jobs/<job>/start", "status": 500, "frontendLogLine": true, "frontendLog": "Failed to proxy http://127.0.0.1:8000/runs/<run>/jobs/<job>/start [socket hang up]", "finalJobStatus": "done"}], "reopenProviderCalls": 0, "reopenResolverReads": 0, "apiServerErrors": [], "backendLogFailures": {"backend-main.log": 0, "backend-reopen.log": 0}}

## 사례

| 사례 | 내용 | 상태 | 이유 | 허용된 관찰 공백 |
|---|---|---|---|---|
| R1 | 8VF6 종단(UI): 불러오기·전처리·사전 검사·승인·작업·결과·내려받기·보완 보고서 | pass |  |  |
| R2 | M7 통과: 보완 8VF6이 두 물 정책에서 게시되고 M21 입장이 openmm_preflight_failed 없이 열림 | pass |  |  |
| R3 | M20 인계(UI): 원본 기준 번호 대응·주석·포켓, KLIFS 일곱 자리, 모델링 잔기 표시, SO1–SO3, @3 | pass |  |  |
| R4a | completes 구조(1HSG, UI): M21 작업 완료(240초)·M21 보고서 @2·같은 조건 도킹·M18 보고서 구조 출처 | pass |  |  |
| R4b | 시간 상한 관측(8VF6 M21, 240초): 작업 실패·결과 없음·모델 0·1단위 환불 없음·프로세스 정리 | pass |  | docking:no_model_time_limit |
| R5 | 분류 표(13구조 × 물 정책 둘) = 독립 분류, in_scope 사슬(보완 → M20 → M21 입장), out_of_scope 거절 | pass |  |  |
| R6 | 기본 거절: §5.2 소비자 전부 repaired_structure_not_accepted, 인벤토리 시험, 뷰어 경로 없음 | pass |  |  |
| R7 | 입장 거절: nothing_to_repair·already_repaired·gap_too_long·합성 표시 다섯, 예산·작업 0 | pass |  |  |
| R8 | MSE: 1RNH의 MSE 세 개 → MET, 대응표·RP5·치환 잔기 표시 | pass |  |  |
| R9 | 재열기: 이벤트만으로 보완 기록·구조·보고서, 저장된 M20 @1·@2·M21 @1 같은 바이트, 비보완 응답 바이트 | pass |  |  |
| R10 | JEV 경고(UI): 미리보기·승인 화면 JW1, 전송 0, M23 화면 표시, M23 보고서 바이트 불변 | pass |  |  |
| R11 | 금지어: 새 화면·보고서·고정 문장에 금지어 0, 비폭로 | pass |  |  |

not_observed와 fail은 통과로 세지 않는다. 합성 표시 자료: `backend/tests/fixtures/structure_repair/synthetic-*.cif`(R7), `backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf`(R4a 도킹, 기계적 경로 확인). 큰 증거·스크린숏·내려받기·화면 글자는 Git 제외 artifacts에 있고 여기에는 경로·크기·SHA-256만 있다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다.

