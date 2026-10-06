# M24 JEV 과학 데이터 전송 통로 완료 기록

- 판정: **완료** (2026-10-06). main 병합: 사용자 결정 대기.
- 브랜치: `dryforge/m24-jev-egress` (`phase/m24-jev-egress` = main `71ba769`에서 분기). M23은 시작 전에 main에 병합되어 있었다(`5d8481f`, 기록 `1451f24`, Stop 훅 그룹 열넷 `71ba769`).
- 고정 소스: `5218130`(첫 실호출 보정 뒤 예약식·실행기 수정 커밋). 고정 뒤 소스 변경은 없다. 고정 뒤 커밋은 증거(`4f96697`·`17e183b`·`81fa175`·`36961cc`)와 기록 문서뿐이다.
- 수락 증거: `docs/qa/m24-jev-20261006/`(`preflight.txt` 착수 확인, `gate-backend.txt` 백엔드 게이트, `acceptance-fixture/` 수락(fixture 단계), `acceptance-calibrate/` 첫 실호출, `acceptance-live/` 나머지 실호출, `m23-regression/`…`m13-regression/` 회귀, 개발 중 증거 `t8-*`·`t9-*`). 256 KiB를 넘는 텍스트 증거 53개(333,391,605 bytes)는 결정 0020에 따라 Git 제외 artifacts(`frontend/tests/offscreen/artifacts/m24-acceptance/final-20261006/export-full/`)로 옮겼다(`m13-regression` 51개, `m14-regression` 1개, `m15-regression` 1개, 해시는 각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 외부 요청: 브라우저 비-loopback 0건. **OpenRouter 호출은 실호출 6회뿐**(사용자 할당 합계 6회, 결정 0012. 수락 fixture 단계와 회귀는 0회, 가짜 transport). 키·헤더·원시 오류는 어떤 증거에도 없다(키 문자열 검색 0건).

## 결과물
- 값싼 도구 `build_jev_projection`(`SUPPORTED_TOOLS`, 작업·승인·예산 단위 없음, dry-run에서도 실행) → 불변 객체 `jev_projection@1`: 게시된 M17 `ligand_candidate_set@1`·M20 `mutation_candidate_set@1`에서 사용자가 고른 후보 1–20개(리간드는 선택적 M17 필터 통과 강제)를 허용 목록 필드만으로 와이어(`jev_ligand_candidates@1`·`jev_mutation_candidates@1`)로 만들고 본문(64 KiB 이하)의 해시를 저장한다. 변이 와이어는 저장 좌표에서 계산한 이웃 잔기(5.0 Å)·서열 구간(앞뒤 5)을 담고 번호 대응·KLIFS·보호 사유 이름·좌표·전체 서열·후보 id 해시·block 이름·SMARTS는 담지 않는다.
- 서버 모듈: `jev_constants.py`(닫힌 집합·상한·질문 지시문·고정 문장 J1–J7·U1–U3·예약식, 표준 라이브러리만), `jev_projection.py`(와이어 빌더·허용 규칙·본문 인코딩·`parse_choice`·`validated_projection`), `tools/jev.py`(도구와 사전 검사), `egress/science.py`(`request_science`: 단계 순서·감사·예약·정산·단일 HTTP), `jev_sends.py`(동의·진행 중 집합·`run_send`·`jev_send@1` 도출·제안 객체 `jev_choice@1`·`validated_choice`·상태·미리보기), `jev_reports.py`(보고서 `jev_choice`).
- 동의·승인: run 수준 과학 전송 동의 이벤트(`jev_science_consent_changed`, 기본 꺼짐, 뷰어 동의·`egress_config["mode"]`와 무관)와 전송마다 승인(`jev_send_approved`, 본문 SHA-256 일치). 감사 `prepared`에 승인된 정확한 본문 객체, 이벤트 `jev_science_dispatch_started`(run당 10회 상한)·`jev_send_outcome`. `request_science`의 호출자는 `jev_sends.run_send` 하나, 그 호출자는 라우트 `POST /runs/{id}/jev/sends` 하나(AST 테스트). 게이트는 승인 콜백(`admit`)이 없으면 어떤 이벤트도 쓰기 전에 거절하고 콜백 뒤 로그에서 승인을 다시 대조한다. JEV POST는 `application/json`만 받는다(415).
- 예산: 비싼 계산 단위를 쓰지 않는다. 외부 토큰 `min(50000, 4096 + ceil(body_bytes × 2 / 3))`·USD 0.10 예약, 응답 사용량으로 정산, 뷰어와 외부 예산·`usage_unknown` 중지 상태를 공유.
- API: `GET /runs/{id}/jev/status`, `POST …/jev/consent`, `POST …/jev/preview`, `POST …/jev/sends`, `GET …/jev/sends`, `GET …/jev/sends/{send_id}`, `/capabilities`의 `methods.jev_choice`, 방법 보고서 `analysis_type: "jev_choice"`(증거 종류 `computed`·`model_response`, 후보별 확률 제외).
- 화면: `frontend/src/components/JevPanel.tsx`(새, 지식·보고서 탭 `NumberingPanel` 아래), 순수 로직 `src/lib/jev.ts`(새), `app/page.tsx`·`WorkspaceTabs.tsx`(마운트와 전역 줄의 "과학 전송 허용" 표시, `.mw-app-run` 바깥), `lib/api.ts`·`contracts.ts`·`report-library.ts`("JEV 판정 보고서"), `design/components.css`(+ `npm run tokens`). M17 `FilterForm`은 그대로 가져다 썼다.
- QA 도구: `frontend/tests/offscreen/jev-flow.cjs`(모드 `fixture`·`live`), `backend/tests/offscreen_jev_fixture/server.py`(가짜 transport 서버, 스크립트 일곱 가지), `scripts/m24_offscreen_acceptance.py`(단계 `fixture`·`calibrate`·`live`·`--finalize`·`--regressions`, 저장소 단위 실호출 대장 `runs/m24-live-ledger.json`).
- 테스트: 백엔드 `test_jev_*.py` 8개 파일 476개(`constants`·`projection`·`tool`·`science_gate`·`sends`·`api`·`reports`·`ast`), 프런트 `tests/jev.test.cjs`, 스크립트 `test_m24_offscreen_acceptance.py` 77개. Fixture: `backend/tests/fixtures/jev/`(독립 oracle `independent_neighbors.py`·`expected.json`, 기존 게이트 감사 열 골든 `golden_egress_events.json`, 일회용 `prototype_*.py`, `SYNTHETIC-PROVENANCE.md`).

## 사용자 결정 (2026-10-06)
근거는 결정 0032. 사용자는 모든 질문에서 추천안을 골랐다: 범위(선택지형 후보 고르기 하나), 보낼 내용(부위 주변 정보까지), 승인·상한(전송마다 승인, 10회·64 KiB), 실호출 6회, 화면(지식·보고서 탭 한 곳), 후보(직접 고른 ≤ 20), 응답(제안 객체 + 보고서), 예산(비싼 계산 단위 미사용), 질문 기준(고정 질문만). 독립 점검 뒤 추가: 별도 run 수준 동의 스위치, 번호 대응 참조값 미전송, 결과 넘기기 단추 없음, 후보 순서 고정 + 안내 문장, 같은 목록 재전송 허용(합치기 없음), 뷰어와 외부 예산 공유, 리간드에 수용체 정보 없음, 늦은 응답 저장·표시.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인과 fixture | `2dd36fd` |
| T2 상수·순수 모듈 | `fc01fba` |
| T3 값싼 도구 `build_jev_projection`과 T2 규칙 보정 둘 | `8e13219` |
| T4 게이트 `request_science`·동의·전송·제안 객체 | `f384315`, 수정(승인 필수화·순서 테스트) `59a1d33` |
| T5 라우트·읽기·보고서·AST 테스트 | `cad0ee5` |
| T6 프런트 순수 로직·API 클라이언트 | `bb57406` |
| T7 `JevPanel`·전역 표시 | `a79c43a` |
| T8 오프스크린 흐름·fixture 서버·수락 실행기 | `7a24650`, `9c0ce31`, `c24466b`(증거) |
| T9 독립 코드 검토 수정(백엔드 JSON 전용·고정 500, 프런트·하네스·대장) | `81feeca`, `a27979e`, `30f3795`(증거) |
| T10 실호출 보정(예약식·calibrate 마무리 모드·`record` 충돌)과 증거 | `5218130`(= 고정 소스), `4f96697`, `17e183b`, `81fa175`, `36961cc` |
| T12 기술 문서·기록 | `47d7b45`와 이 기록의 커밋 |

## 착수 확인 (`docs/qa/m24-jev-20261006/preflight.txt`, 기준 `71ba769`)
- 와이어 허용 목록의 모든 항목이 M17·M20 저장 객체에 있다. 이름이 다른 곳은 파생한다: `generation_kinds`는 `origins[].rule_id`(`fixed`→`fixed_replace`, 그 밖→`user_rule`)에서, `sources`는 객체 목록의 `kind`를 이름으로 합쳐서, `protection_checks`는 `.status`만, `pockets`는 handle 제외. 부모 SMILES·속성은 후보 집합의 필수 필드. `generation_order`는 저장 필드가 아니라 배열 위치.
- 20개 후보 본문은 변이 최대 29,828 B·리간드 풀(2,000개)에서 9,876 B로 64 KiB 안(가장 넓은 모양을 가정해도 리간드 51,935 B). 이웃 5.0 Å 경계 최소 여유 0.00126 Å.
- `budget_reserved`에 비싼 계산 축 없이 `external_tokens`·`usd`만 있어도 예약·정산·재생·환불이 기존 코드로 동작하고, 새 이벤트 종류가 재생을 깨지 않는다. 응답 없는 전송은 재시작 때 `usage_unknown`, 과다 사용은 `budget_exhausted`.
- 전송이 HTTP 동안 run 실행 잠금을 잡는다(같은 run의 다른 변경 요청 503 busy, 읽기는 잠금 없음). 전송 중 메모리 `run.cancelled`는 갱신되지 않아 늦음은 이벤트 순서로만 판정한다. 취소·동의 끄기 뒤에도 감사 이벤트와 제안 객체 저장이 된다.
- 이벤트 로그 50 MB에서 상태·미리보기 읽기 0.09초(실제 최대 로그 48.5 MB는 0.147초), 이벤트 추가가 매번 로그 전체를 다시 읽어 전송 한 번에 약 1.5초. 기존 `request_jev` 9경우·`request_viewer` 5경우·뷰어 라우트 1경우의 감사 이벤트 열을 골든(`golden_egress_events.json`)으로 저장했고 이후 모든 단계에서 `--check`가 통과한다.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 점검(고정 전, 의도 감사): 1차에서 여덟 항목(과학 전송 동의 스위치, 번호 대응 참조값 전송, 선택 결과 넘기기, 후보 순서, 같은 목록 재전송, 예산 공유, 리간드 수용체 맥락, 늦은 응답)을 사용자에게 물어 모두 추천안으로 확정했고, 2차 점검의 새 지적 셋(보호 정보 상태 구분, 늦음의 경계, 서열 구간으로 정체 추정)을 명세에 반영했다.
- 독립 실행 가능성 검토(고정 전, 문서 셋): 막는 지적 6건(빈 삽입 코드 규칙, 리간드 후보 순서 기준, 진행 중 전송 구분, 응답·기록 모양, 오프스크린 fixture 서버, 보고서 근거 객체)을 문서에 반영했다.
- 독립 명세 검토: T2 `pass`(advisory: 경로 모양 검사 과다 거절 → T4에서 보정), T4 `needs-fix` 둘(게이트가 승인 이벤트 없이 전송할 수 있음, 단계 순서 테스트가 일부만 덮음 → `59a1d33`에서 `admit` 필수화·사후 승인 대조·인접 조합 테스트).
- 독립 코드 검토(T9, 고정 전, 영역을 둘로 나눈 새 인스턴스): 백엔드 **approved**(변이 13개 중 11개를 테스트가 잡음, 살아남은 둘은 동작이 같은 변이), 프런트·하네스 **issues 1건**(실서버 흐름이 "실서버로" 사례 일부를 다루지 않음 → calibrate 흐름의 첫 클릭 전 사전 확인과 접힌 확률 단언 추가). 반영한 advisory: JEV POST JSON 전용·승인 뒤 예외 고정 500·실호출 대장·금지어 판정 공통화·서버 영어 메시지 미표시·전역 표시 응답 순서 가드·동의 안내 문구·`reasonOnly` 숫자 단언.
- 독립 증거 검토(T11, 고정 뒤): 아래 "증거 검토".

## 게이트 (고정 `5218130`, 2026-10-06 UTC)
| 명령 | 결과 |
|---|---|
| 백엔드 pytest 열네 그룹(Stop 훅 그룹과 같은 인자, 동시에 제한 없이, `gate-backend.txt`) | exit 0 ×14, 합계 3,712 passed, 343초(수집 대비 skip 0) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 19개 파일(M13–M24 실행기, 가져오기, 측정, 훅, 실행기, 설치 스크립트) | 마지막 그룹에 포함, exit 0(M24 실행기 77개) |
| `node --check` 하네스 전부(`frontend/tests/offscreen/*.cjs` 28개) | exit 0 |
| `npm --prefix frontend run test:events` | exit 0, 417 pass, 0 fail |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (`acceptance-fixture/`·`acceptance-calibrate/`·`acceptance-live/`)
- **fixture 단계**(`--live-calls 0`, 고정 소스, 2026-10-06): `verdict: pass`, `acceptance: true`, 사례 26개 모두 통과(화면 22 + 실행기 4), 실제 Electron 오프스크린(`isOffscreen()===true`, GPU·WebGL 켜짐, paint 확인). 관찰한 것: 탭 진입(다른 탭 내용 불변), 동의 끈 상태의 `consent_off`와 승인 단추 비활성, 동의 켜고 끄기와 전역 "과학 전송 허용" 표시, 자동 선택 없음, 21번째 체크 거절과 이유, 리간드 필터 통과만, 미리보기 `<pre>` 본문 = 서버 미리보기 문자열 = 하네스 계산 SHA-256·바이트 = 저장 투영 = 감사 `prepared` 본문 = transport 수신 바이트, 확인 체크 없이 전송 불가, 정상 전송 결과 카드(후보별 값은 접혀 있고 후보 순서 그대로), 같은 본문 재전송, 보고서 "JEV 판정 보고서", 실패·거절(`response_invalid`·`model_mismatch`·`provider_http_error`는 이유만), `no_usage` 뒤 `egress_stopped`, `slow` 중 동의 끄기 → 늦은 응답 표시와 J7, 열 번째 전송 뒤 `send_cap_exhausted`, 실호출 계획 리허설(`--control`) 여섯 전송 모두 completed. dispatch 이벤트 18 = fixture transport 호출 18. 브라우저 비-loopback 요청 0, 남은 프로세스·리스너 없음, 증거 키 문자열 0건.
- **실호출 6회**(`acceptance-calibrate/`·`acceptance-live/`, 사용자 할당 전부): 응답 모델 `typesafe/jev-1.13-20260917`, 전부 `completed`, 외부 요청 중지·예약 초과 없음, 응답에 `confidence`와 후보별 `probabilities` 포함.

| # | 소스 | 후보 | 본문 B | 입력 | 출력 | 비용 USD | 예약 토큰 | 고른 후보 | 확신도 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 리간드(공개 파생 부모 + 합성 표시 block) | 5 | 3,539 | 2,087 | 65 | 0.0000877 | 5,866(첫 식) | c01 | 0.78 |
| 2 | 변이(1UBQ) | 5 | 7,030 | 3,921 | 65 | 0.0001647 | 8,783 | m01 | 0.87 |
| 3 | 리간드 | 10 | 5,607 | 3,433 | 110 | 0.0001442 | 7,834 | c01 | 0.84 |
| 4 | 변이(1MQ4) | 20 | 29,151 | 17,011 | 200 | 0.0007145 | 23,530 | m01 | 0.89 |
| 5 | 같은 본문 재전송 | 20 | 29,151 | 17,011 | 200 | 0.0007145 | 23,530 | m01 | 0.88 |
| 6 | 변이(1UBQ) | 20 | 25,428 | 14,619 | 200 | 0.0006140 | 21,048 | m01 | 0.86 |

  첫 호출(1번)은 고정 전 빌드(`30f3795`, 첫 식)에서, 나머지 다섯 호출은 고정 소스와 같은 소스의 빌드(`4f96697`, 조정한 식)에서 나갔다. 합계 토큰 58,922, 비용 약 $0.0024. 본문 바이트/입력 토큰은 1.63–1.79(첫 식이 가정한 2.0보다 낮아 첫 호출 뒤 예약식을 `min(50000, 4096 + ceil(body_bytes × 2 / 3))`로 조정). **6회 모두 목록의 첫 후보를 골랐다**(같은 본문 재전송 포함, 확신도는 호출마다 조금 달랐다). 기준·목표 문구가 없는 질문의 선택이 목록 순서의 영향을 받을 수 있다는 J4의 근거이며 6건으로 일반화하지 않는다. 입력은 공개 1UBQ·1MQ4와 합성 표시 입력뿐이라 사용자 데이터가 나가지 않았다.
- calibrate 단계는 실호출 직후 실행기의 `record` 인자 충돌로 마무리 보고 없이 죽었다(호출 결과는 `live-state.json`에 저장). `--finalize`(새 호출 없음)로 증거를 다시 만들었다. 실호출 대장(`runs/m24-live-ledger.json`)은 합계 6/6.

### 관찰하지 못한 사례 (위조하지 않음)
- run 취소 뒤 도착한 응답(HTTP 취소 경로 없음), `external_timeout`·`transport_error`, 키 없음, 재시작 뒤 `delivery_unknown`·`outcome_not_recorded` 도출, 다른 전송 진행 중, dry-run, 화면의 "다시 읽기 필요" 표시(한 창에서는 재현 안 됨): 백엔드 테스트(`test_jev_sends.py`·`test_jev_science_gate.py`)와 프런트 단위 테스트가 덮는다.

### 회귀 (고정 `5218130`, `--regressions`가 차례로, 모두 종료 0·`acceptance: true`)
- M23 35/35, M22 25/25, M21 23/23, M20 24/24, M19 26/26, M18 24/24, M17 21/21, M16 19/19, M15 14/14, M14 15/15, M13 28사례(17단계, M8–M12 하위 실행기 포함). 각자 새 root·artifacts, 외부 요청 0건, 남은 프로세스 없음. M23 이후 모든 회귀가 새 빌드에서 그대로 통과했고 기존 수락 실행기·흐름 스크립트는 하나도 고치지 않았다.

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님).
- `backend/tests/test_api.py`: `/tools` 이름 집합에 `build_jev_projection`. `test_reference_site_annotation.py`·`test_residue_numbering.py`: 사전 검사가 있는 도구 집합에 새 도구. `test_ligand_api.py`: `/capabilities` 방법 집합 둘에 `jev_choice`. 새 도구 하나·capability 하나가 늘었다는 이유 주석이 있다.
- 증액 호출자 AST 테스트 셋은 고치지 않았다(호출자 셋 그대로, 새 모듈에 `raise_limits`·`limit_approval` 문자열 없음).
- `frontend/tests/report-library.test.cjs`: `jev_choice` 종류 이름 단언 한 줄.
- M17·M18·M19·M20·M21·M22·M23 코드·상수·결과는 바꾸지 않았다(골든 호출 키·감사 열 골든 `--check` 통과).

## 알려진 한계
- 응답은 JEV가 후보 목록에서 고른 하나일 뿐 계산 결과·점수·순위·추천·예측이 아니다. 선택 이유는 알 수 없다. 6회 응답이 모두 첫 후보였고 질문에 기준이 없어 M25에서 목표를 담는 질문과 순서 효과 점검이 필요하다.
- 변이 와이어의 서열 구간·이웃 잔기 이름으로 단백질이 알려질 수 있다(U3). 번호 대응·accession은 보내지 않는다.
- 단백질 잔기 정의가 M20과 같아 HETATM 변형 잔기(MSE 등)는 구간·이웃에서 빠진다. 계산하지 않은 `neighbors`는 `null`이다.
- 승인했으나 보내지 못한 경우(`prepared` 저장 실패·사후 승인 대조 실패)가 `delivery_unknown`으로 도출된다(닫힌 이유 집합에 "보내지 않음"이 없음). 늦은 응답은 실패 기록에도 `late`로 표시된다.
- 전송은 HTTP 동안 run 실행 잠금을 잡고 이벤트 추가가 로그 전체를 다시 읽어(50 MB에서 약 1.5초) 이벤트 루프를 막는다(뷰어 전송과 같은 성질). 상태·미리보기는 캐시된 예산을 잠금 없이 읽어 화면 표시가 잠깐 어긋날 수 있다.
- 실호출 6회는 모두 공개·합성 입력이었다. 사용량 단위·비용(약 $0.0024)은 6회 표본이며 더 큰 본문(64 KiB 근처)의 실사용량은 측정하지 않았다.
- 화학·도킹·GA POST 라우트(M11–M23)는 JSON Content-Type을 검사하지 않는다(JEV POST만 415).
- 가짜 transport QA root의 감사 이벤트도 `destination`에 실제 OpenRouter URL을 적는다. 실호출과 구분하려면 이벤트가 아니라 fixture `calls.jsonl`과 실호출 대장을 본다.

## 대체한 과거 검증 범위
- M24는 공유 소스를 바꿨다: 백엔드 `api/app.py`(JEV 라우트·`SCIENCE_GATE`·capability·보고서 등록), `core/events.py`(이벤트 종류 넷), `egress/gate.py`(위임 메서드 하나), `workspace.py`·`config/tools.yaml`·`SUPPORTED_TOOLS`(새 도구), 프런트 `app/page.tsx`(마운트·run 변경 때 `GET /jev/status`)·`WorkspaceTabs.tsx`(전역 표시), `lib/api.ts`·`contracts.ts`·`report-library.ts`, `design/components.css`.
- 그 밖의 연결 변경: `frontend/package.json`(`test:offscreen:jev` 스크립트), `.codex/hooks/stop.py`(`SCRIPT_TESTS`에 M24 실행기 테스트), `docs/standards.md`(게이트 목록).
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(3,712개 포함 스크립트, skip 0)와 M23·M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `5218130`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 증거·문서 검토 (T11, 코드 검토자와 다른 새 인스턴스 둘, 고정 뒤, HEAD `bc98ebc`)
- **증거 검토: APPROVE**(막는 지적 없음). 검토자가 확인한 것: 고정 뒤 변경은 문서뿐이고 증거 커밋 넷은 추가만 했으며 기존 증거 불변, 256 KiB 초과 파일 0개와 옮긴 53개 파일의 해시 일치, `runs/` 아래 `events.jsonl` 1,157개를 모두 훑어 실호출 dispatch가 `runs/m24-live-20261006`의 6건뿐(모두 `completed`·HTTP 200·예약 초과 없음)이고 가짜 transport root 8곳은 dispatch가 fixture 호출 기록과 같음, 저장소 대장 합계 6, 6회 표의 모든 칸이 이벤트·객체 값과 같음, 실제 키 원문·base64 변형·`Bearer` 0건(파일 28,087개 약 4.3 GB), 게이트 3,712개·사례 수·`acceptance: true`·빌드 도장, 기존 파일 수정이 도구·capability 이름 집합 네 파일과 단언 한 줄뿐임, 골든 `--check`·AST 테스트·`node --check` 28개·`test:events` 417 재실행 통과. 참고(반영): 첫 호출의 빌드가 고정 전이었음(위 6회 표에 적음), m13·m14·m15 README의 `SHA256SUMS` 줄은 "옮긴 큰 텍스트 증거" 절을 덧붙이기 전 해시라 README만 일치하지 않음(각 README에 적음), 백엔드 게이트 파일에 gitHead가 없음(헤더 추가), 프런트 게이트 기록 파일이 없었음(`gate-frontend.txt` 추가), "대체한 과거 검증 범위"의 연결 변경 누락, 가짜 transport 이벤트의 `destination`(위 한계에 적음).
- **문서 검토: issues 5건 → 모두 반영**. 가리키는 절이 없던 "JSON 전용 POST" 함정(→ `docs/engineering-notes.md`에 절 추가), 예약 수치(현재 식 6,456 대 첫 식 5,866), 입장 사유 개수 표기(결정 0032: 9개 + `projection_invalid`), 6회 관찰을 현재형 법칙으로 쓴 findings 제목(→ 관찰로), `transport_failed` 뒤 정산이 없다는 이벤트 순서. 반영한 advisory: 결정 0032의 덧붙인 기존 코드·테스트 서술, 실행 잠금 예외 문장(`backend/AGENTS.md`), `missing_configuration` pin 범위, `budget` 표기, `audit_id` 거절 설명, 상태 문서의 API·테스트 수 표기, `docs/operations.md`의 낡은 그룹 합집합 수치, 결정의 "하지 않은 것"이 영구 금지로 읽히지 않게 M24 범위 밖 표기.

## 남은 일
- main 병합은 사용자 결정 대기(`--no-ff`, push 안 함).
- 새 미해결 문제(`docs/tracking/findings.md`): 기준 없는 질문의 첫 후보 선택, 보내지 않음의 `delivery_unknown` 도출, `_finish`의 전이 잠금만 쓰는 예외와 읽기 경합, 서열 구간으로 단백질 정체 추정, HETATM 변형 잔기 제외, 화학 POST의 JSON 검사 없음, 수락 QA에서 만들 수 없는 사례, 실호출 대장의 root 의존, M24 밖의 낡은 문서 문장.
