# M25 JEV 설계 루프 완료 기록

- 판정: **완료** (2026-10-07 UTC / 2026-10-08 KST).
- 브랜치: `dryforge/m25-jev-loop` (`phase/m25-jev-loop` = main `b8866a8`에서 분기). M24는 시작 전에 main에 병합되어 있었다(`2e0f2b9`, 기록 `b8866a8`).
- 고정 소스: `4360598`(T11 마지막 검토 수정). 고정 뒤 제품 소스(`backend/mw`·`frontend/src`·`frontend/app`·`design`·`config`) 변경은 없다. 고정 뒤 커밋은 M24 오프스크린 하네스 한 파일(`frontend/tests/offscreen/jev-flow.cjs`, `9a9a625`), 증거(`c782419`·`c092591`·`27ea348`), 이 기록 문서뿐이다. 변경 규모는 `git diff main...HEAD`에서 증거 폴더를 뺀 68개 파일(T12 시점)이고 수정 금지 파일은 0개다(`gate-invariants.txt` (3)).
- 수락 증거: `docs/qa/m25-jev-loop-20261007/`(`preflight.txt` 착수 확인, `gate-backend.txt`·`gate-frontend.txt`·`gate-invariants.txt` 게이트, `acceptance-fixture/` 수락(fixture 단계), `acceptance-calibrate/` 첫 실호출, `acceptance-live/` 나머지 실호출, `m24-regression/`…`m13-regression/` 회귀, `regression-harness-changes.txt` M24 하네스 수정과 회귀 사슬). 256 KiB를 넘는 텍스트 증거 53개(`m13-regression` 51개 331,655,797 B, `m14-regression` 1개 1,191,725 B, `m15-regression` 1개 590,108 B)는 결정 0020에 따라 Git 제외 `frontend/tests/offscreen/artifacts/m25-acceptance/regress-20261008a/export-full/<폴더>/`로 옮겼다(해시는 각 폴더의 `ARCHIVED-EVIDENCE.sha256`, `shasum -c` 모두 OK).
- 외부 요청: 브라우저 비-loopback 0건. **OpenRouter 호출은 실호출 8회뿐**(사용자 할당 합계 8회, 결정 0012·0033. fixture 단계와 회귀는 0회, 가짜 transport). 키·헤더·원시 오류는 어떤 증거에도 없다(키 문자열 검색 0건).

## 결과물
- 루프 기록 `jev_loop@1`(저장하지 않음, 이벤트·저장 객체·작업 기록에서 읽을 때마다 도출·검증)과 이벤트 넷 `jev_loop_created`·`jev_loop_compute_approved`·`jev_loop_docking_abandoned`·`jev_loop_ended`. 리간드(M17 후보 집합, 단독 M18 자유 도킹)·단백질(M20 후보 집합, M21 모델링 → 변이 구조 M18 도킹) 두 갈래, 풀 2–20, 목표 `explore`·`exploit`, 반복 상한 1–8, 바퀴마다 전송 승인 + 계산 시작 승인.
- 값싼 도구 `build_jev_loop_projection`(사전 검사 훅이 루프 기록 입력을 `bound`로 고정) → 불변 투영 `jev_loop_projection@1`(전송마다 `sha256_order_v1`로 섞은 순서·별칭, 목표 질문 넷, 계산된 후보 표시 `computed`, 와이어 `jev_loop_ligand_candidates@1`·`jev_loop_mutation_candidates@1`). M24 미리보기·전송 라우트가 루프 투영을 받고(승인 이벤트 앞의 루프 검사 `loop_send_invalid`), 응답은 제안 객체 `jev_loop_choice@1`, 끝내기 때 요약 `jev_loop_result@1`, 보고서 `jev_loop`("JEV 루프 보고서").
- 서버 모듈: `jev_loop_constants.py`(닫힌 집합·상한·질문 지시문·고정 문장 LJ1–LJ8·UL1–UL3, 표준 라이브러리만), `jev_loop_projection.py`(섞기·와이어·본문·`parse_loop_choice`·제안 만들기와 `validated_loop_choice`, 순수), `jev_loops.py`(순수 도출 `derive_loop`·입장 판정·`job_owners`·`proposal_matches_send`), `jev_loop_store.py`(한 번 읽기 보기, 만들기·계산 판정·승인 이벤트·도킹 포기·끝내기, capability), `jev_loop_result.py`(요약 만들기·검증), `jev_loop_reports.py`(보고서), `tools/jev_loop.py`(도구와 사전 검사). M24 모듈의 최소 분기: `jev_sends.py`(루프 투영 받기·미리보기 `loop`·`loop_blocks`·승인 콜백 안 루프 검사·제안 저장·전송 기록 `loop` 키·`load_loop_choice`), `egress/science.py`(스키마로 검증·본문·응답 해석 세 호출만 가름). `mutation_model_reads.py`(짝 행 `loop` 키), `api/app.py`(루프 라우트 여섯, `SUPPORTED_TOOLS`, `methods.jev_loop`, 보고서 등록), `core/events.py`(이벤트 종류 넷).
- API: `POST /runs/{id}/jev_loops`, `GET …/jev_loops`, `GET …/jev_loops/{loop_id}`, `POST …/jev_loops/{loop_id}/compute`, `…/abandon_docking`, `…/end`, `/capabilities`의 `methods.jev_loop`(갈래별), 방법 보고서 `analysis_type: "jev_loop"`.
- 화면: `frontend/src/components/JevLoopPanel.tsx`(새, 리간드 설계·탐색 탭의 M22 GA 영역 다음과 단백질 공학 탭의 M23 서열 GA 영역 다음, `data-testid`는 모두 `jev-loop-`), 순수 로직 `src/lib/jev-loop.ts`(새), `app/page.tsx`(마운트 둘), `JevPanel.tsx`(전송 기록의 루프 행 표시 prop `sendHistoryMark`, M24 동작 불변), `MutationModelPanel.tsx`·`lib/mutation-model.ts`(짝 표 "루프 도킹(야생형 없음) · 바퀴 n"), `lib/jev.ts`(`usdText` export), `lib/api.ts`·`contracts.ts`·`report-library.ts`, `design/components.css`(+ `npm run tokens`). M17 `FilterForm`·M21 `PairInputs`·M18 `lib/docking.ts` 입력 로직을 그대로 가져다 썼다.
- QA 도구: `frontend/tests/offscreen/jev-loop-flow.cjs`(모드 `fixture`·`calibrate`·`live`), `backend/tests/offscreen_jev_loop_fixture/server.py`(가짜 transport 서버, 스크립트 일곱 가지)·`qa_setup.py`(loopback API로 QA run 둘), `scripts/m25_offscreen_acceptance.py`(단계 `fixture`·`calibrate`·`live`·`--finalize`·`--rehearse`·`--regressions`, 저장소 대장 `runs/m25-live-ledger.json`), `frontend/package.json` `test:offscreen:jev-loop`.
- 테스트: 백엔드 `test_jev_loop_*.py`·`test_jev_loops_*.py` 11개 파일 689개(`constants`·`projection`·`derive`·`api`·`read`·`tool`·`choice`·`sends`·`compute`·`result`·`reports`), 프런트 `tests/jev-loop.test.cjs`·`tests/jev-loop-panel.test.cjs`, 스크립트 `test_m25_offscreen_acceptance.py` 99개. Fixture: `backend/tests/fixtures/jev_loop/`(독립 섞기 oracle `independent_order.py`와 `expected.json`, 착수 확인 일회용 `prototype_*.py`, `SYNTHETIC-PROVENANCE.md`), M24 과학 전송 골든 `backend/tests/fixtures/jev/golden_science_m24.json`(209,001 B)과 기록기 `golden_science_m24.py`(T1이 M24 코드를 바꾸기 전에 기록).

## 사용자 결정 (2026-10-07)
근거는 결정 0033. 사용자는 모든 질문에서 추천안을 골랐다: 진행(바퀴마다 전송 승인 + 계산 시작 승인), 입력(고정 목표 문장 + 계산 표시, 탐색형은 점수 없음), 순서 편향(전송마다 seed로 섞고 목록 위치를 값으로), 멈춤(상한·예산·소진·사람), 목표 둘, 범위(리간드·단백질), 단백질 계산(M21 → 변이 구조 M18을 사람이 차례로), 증액 경로 없음, 실호출 8회, 사람 지정, 반복 상한 5/8, 외부 예산 공유, 루프 전용 기록, 화면(두 탭에 각각), 범위 밖(기준선 비교·진행 요약·최종 후보 표시). 독립 점검 뒤 추가: 시작 전 취소 후보 `unavailable`, `dock` 시작 전 취소 `not_run`, 후보 상태 우선순위, 의도 감사 열네 항목.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인, fixture, M24 과학 전송 골든 | `6a32ba4` |
| T2 상수·순수 투영·순수 도출 | `bd1aa13`, `46ced42`, `c907f94` |
| T3 루프 이벤트·만들기·읽기·`methods.jev_loop` | `cd32f45`, `5c4c497` |
| T4 투영 도구와 M24 미리보기 확장 | `8d2c947` |
| T5 전송 연결과 제안 객체 | `ab7c19b`, `f5d02e0`, `853a43c`, Stop 훅 그룹(`b0d0f96`) |
| T6 계산 시작·도킹 포기·끝내기·요약 | `da37288`, `0561cb4`, `8079024`, `02fd5c6` |
| T7 보고서·짝 표 `loop` 키 | `5b17cb2` |
| T8 프런트 순수 로직·API 클라이언트 | `90fed31` |
| T9 화면 `JevLoopPanel` | `8867c90` |
| T10 오프스크린 흐름·fixture 서버·수락 실행기 | `4308283`, `43ba917` |
| T11 독립 코드 검토 수정 | `490cfc7`, `2b925c8`, `0045340`, `43a3e5d`, `4360598`(= 고정 소스) |
| T12 M24 하네스 수정과 증거 | `9a9a625`, `c782419`, `c092591`, `27ea348` |
| T14 기술 문서·기록 | 이 기록의 커밋 |

## 착수 확인 (`docs/qa/m25-jev-loop-20261007/preflight.txt`, 기준 `b8866a8`, 제품 코드 변경 없음)
- 큐: `submit`은 같은 호출 키의 기존 작업을 상태와 무관하게 돌려주고(다른 `timeout_s` 재제출도 같은 `job_id`, 첫 `timeout_s` 유지), 시작 전 취소는 무과금 `cancelled`, `retry`는 `failed`·`interrupted`만 받는다. 프로세스가 뜨기 전/후의 경계는 `budget_reserved{attempt_id, root_call_id = job_id, tool, expensive_calls: 1}`이다. M18·M21 호출 키에 `timeout_s`는 없다.
- 호출 키: 루프 요청의 정규화 바이트·호출 키가 단독 M18 = M19 `row_arguments` = M22 `row_arguments`·`individual_selection`, 단백질 M21 = 작업 호출 키(cutoff 4·4.0·생략 동일), 변이 쪽 M18 = M23 `individual_arguments`와 같다. `published_m18_results`가 루프 키로 단독·M19 행 결과를 찾는다. M21에는 키 → 모델 색인이 없어 루프 쪽에서 만든다.
- M24 확장: 분기 지점 9곳을 저장 종류·스키마·질문 id로 가르면 M24 바이트 불변으로 확장 가능. `golden_egress_events.json`·새 `golden_science_m24.json` `--check` 0.
- 본문: 후보 20개 루프 본문 최대 31,525 B(1MQ4 변이 활용형, 계산 18개), 닿을 수 없는 상한 32,089 B, 1UBQ 27,448 B, 리간드 11,362 B(64 KiB의 48%). 1MQ4 최대 본문의 예약은 25,113 토큰이라 run당 약 6전송.
- 읽기: 한 번 읽기 보기 하나로 작업 접기·재사용 색인·저장 결과 검증까지, 50 MB 로그에서 도출 0.122초. 실행 잠금 안 `submit` 가능·`start`는 busy, 전이 잠금 안 `submit`은 교착.
- 엔진: 리간드 M18 32.5·40.4초, M21 1UBQ I44W 20.0초, 변이 구조 도킹 2.8초(기본 한도 대비 3.6배 이상 여유). 1MQ4는 M7 사전 검사에서 422 `openmm_preflight_failed`(모델링 불가).
- 새 이벤트 넷은 예산·egress 멈춤·작업 상태·재사용 색인·전송 기록·GET 25개 상태 코드에 영향 없음. 짝 표는 루프 도킹 짝을 `other_side_missing`으로 읽고 `mutation_model_reads.py`는 어떤 해시 집합에도 없다. 키는 해석기로 찾아지고 `.env`는 0600(값은 보지 않음). 불일치 0.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 점검(고정 전): 실행 가능성 점검(문서 셋)이 코드·계약과 부딪힌 열다섯 항목을 지적해 하나(시작 전 취소 → `unavailable`)는 사용자 결정, 나머지는 문서에서 고쳤다(게이트 분기, M24 과학 전송 골든, 도구 경로 422/412, 단계 결과 정의, 검사 순서, `iterations[]`·`current`·목록 행, `budget_exhausted` 조건, `jev_sends` import 금지, 짝 표 `loop` 키, LJ8, `setup_reason` 등). 범위 한정 두 번째 점검의 상태 기계 빈칸(`dock` 시작 전 취소, 후보 상태 우선순위)은 사용자 확인으로 닫았다. 의도 감사 열네 항목은 사용자가 모두 추천안으로 확정했다.
- 독립 코드 검토(T11, 고정 전, 백엔드·프런트/하네스 두 영역): 막는 지적을 고정 전에 반영했다. 백엔드: 작업 ↔ 승인 귀속을 규칙 하나(`job_owners`)로(`490cfc7`), 재검토에서 M24 전송 이벤트도 귀속을 끊고 단위 0 채택은 작업을 소유하지 않게(`43a3e5d`), 계산 요청 모양 거절·승인 직전 취소 재확인. 프런트: 진행 중 읽기가 있을 때 요청한 기록 읽기를 건너뛰어 낡은 기록으로 카드를 판정하던 문제(`2b925c8`), 연 루프만 다시 읽기·끝난 전송 기록만 기다리기(`4360598`). 하네스·실행기: 두 번째 `criteria` 키(`good_second`)·문구 검사 범위·표 정렬 기대·fixture 서버 pid 확인·대장 잠금·반쯤 쓴 줄·그룹 정리·내보낸 뒤 검사 실패의 acceptance false(`0045340`).
- **독립 증거 검토(T13, 고정 뒤): APPROVE_WITH_NOTES, 막는 지적 0.** 검토 항목: 고정 뒤 소스 무변경, 실호출 8 = 대장 8, 키·헤더 0건, 사례 수·`acceptance: true`, 바뀐 기존 검사 목록, 위치 관찰 서술의 정직성. 참고(기록):
  - 수락 QA README의 입력 설명에는 "run P = 공개 1UBQ(22곳)·1MQ4(3곳)"가 함께 적혀 있지만 단백질 루프의 풀은 모두 1UBQ 집합(22곳)에서 골랐다(fixture 3개, 실호출 5개). 1MQ4 집합으로 루프를 만들면 422 `setup_invalid`/`openmm_preflight_failed`로 거절되며(fixture 사례 `P-create-refused`) 이는 M7 사전 검사의 한계다.
  - 실호출 8회는 제품 게이트로 나갔고 미리보기 해시 = 감사 `prepared` 본문 해시(`preparedBodyEqual: true`)는 증거로 확인했지만, 실제 transport 바이트 해시는 fixture 게이트에서만 기록할 수 있어 transport 바이트 동일성은 fixture 단계(transport 7 = dispatch 7)에 근거한다.
  - M24 바이트 불변은 `golden_science_m24.py --check`·`prototype_golden_egress.py --check` 종료 코드 0(`gate-invariants.txt`, 고정 `4360598` 시점)에 근거하며, 고정 뒤 변경은 하네스 한 파일(`jev-flow.cjs`)과 증거 문서뿐이다.

## 게이트 (고정 `4360598`, 2026-10-07 UTC)
| 명령 | 결과 |
|---|---|
| 백엔드 pytest 열여섯 그룹(Stop 훅 `PYTEST_GROUPS` 열다섯 + 나머지 그룹, 같은 인자로 동시에 제한 없이, `gate-backend.txt`) | exit 0 ×16, 합계 4,500개 통과(스크립트 pytest 포함), skip·xfail·error 0, 가장 긴 그룹 398초(나머지 그룹), 480초 넘은 그룹 0. M25 무거운 두 그룹 175초·224초 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 20개 파일(M13–M25 실행기, 가져오기, 측정, 훅, 실행기, 설치 스크립트) | 나머지 그룹에 포함, exit 0(M25 실행기 99개) |
| `node --check` 하네스 29개 + 단위 테스트 28개(57개) | exit 0 |
| `npm --prefix frontend run test:events` | exit 0, 455 pass, 0 fail |
| `typecheck` → `build` | exit 0 → exit 0 |
| 골든 `--check`: `golden_science_m24.py`(M24 과학 전송)·`prototype_golden_egress.py`(M3·M8 게이트) | exit 0, exit 0 |
| 호출자·위치 AST 테스트(`test_jev_ast.py`, 증액 호출자 셋) | 58 passed: `request_science` ← `run_send` ← 라우트 하나, `httpx`는 `egress/` 안, `Run.raise_limits` 호출자 셋 그대로, 루프 모듈에 `raise_limits`·`limit_approval` 문자열·`jev_sends` import 없음 |
| 새 팁 `9a9a625` 재확인(제품 소스 같음) | `node --check` 57개 exit 0, `test:events` 455 pass, ruff exit 0, `test_m24`·`test_m25` 실행기·`test_codex_hooks.py` 201 passed |

## 수락 QA (`acceptance-fixture/`·`acceptance-calibrate/`·`acceptance-live/`)
- **fixture 단계**(`--live-calls 0`, `9a9a625`, 2026-10-07): `verdict: pass`, `acceptance: true`, 사례 57개 모두 통과(화면 53 + 실행기 4), 실제 Electron 오프스크린(`isOffscreen()===true`, GPU·WebGL, paint 확인). run L(리간드, 실제 M17 후보 10개)·run P(공개 1UBQ·1MQ4의 실제 M20 집합과 합성 표시 페놀 SDF). 관찰한 것: 탭 진입(GET 읽기만, 자동 선택 없음), 만들기 칸별 이유와 `loop_active`, 동의 끈 상태의 `consent_off`, 미리보기 `<pre>` = 서버 문자열 = 하네스 계산 SHA-256·바이트 = 저장 투영 = 감사 `prepared` = transport 수신 바이트, 순서·별칭·`criteria`·`computed` = 독립 `sha256_order_v1` 계산, 확인 체크 없이 전송 불가, `model_mismatch` 뒤 `ordinal_mismatch`, `good_second`로 목록 위치 2/m 카드와 그 후보의 계산, 계산된 별칭 선택 `response_invalid`, 동의 끈 뒤 늦은 응답(선택 아님, J7)과 같은 후보의 사람 지정, 전송 없는 직접 지정, 후보 표 네 열 정렬(점수 없는 행 끝), 끝내기·요약·LJ8·보고서, 저장 결과 재사용(단위 0), `no_usage` 뒤 외부 전송 멈춤, 전송 상한 표시, 지식 탭 루프 행(읽기 전용, 단추 없음), 21번째 체크 거절, 1MQ4 풀의 `setup_invalid`(`openmm_preflight_failed`), 첫 비싼 계산 승인 → 작업 시작, `job_running`·`docking_pending`으로 끝내기 닫힘, 실제 PDBFixer·OpenMM·qvina, 도킹 포기 `not_run`, HTTP 500, M21 짝 표 "루프 도킹(야생형 없음) · 바퀴 1", 다른 탭 불변. dispatch 이벤트 7 = fixture transport 호출 7 = 응답 감사 7, 제품 키 해석기 호출 0(sentinel 7), 브라우저 비-loopback 요청 0, 증거·QA 루트·내보낸 증거 430개 파일에서 키·sentinel 문자열 0건, 남은 프로세스·리스너 없음.
- **실호출 8회**(`acceptance-calibrate/`·`acceptance-live/`, 사용자 할당 전부, 제품 백엔드·실제 `SCIENCE_GATE`, 같은 root): 응답 모델 `typesafe/jev-1.13-20260917`, 8회 모두 `completed`(응답 해석 성공, 제안 저장), 늦은 응답·외부 전송 멈춤·예약 초과 없음. 첫 호출 응답은 `answers`·`confidence`·후보별 확률 5개를 담았다. 저장소 대장 `runs/m25-live-ledger.json`(Git 제외) 합계 1 → 8 = dispatch 이벤트 8(run L 5, run P 3). 키 존재 불리언 True·`.env` 0600(내용은 열지 않음), 키 검색 0건, 브라우저 비-loopback 0.

| # | 단계 | 루프(목표, loop_seed) | run | 바퀴 | 별칭 | 선택 가능 | 본문 B | 입력 | 출력 | 비용 USD | 예약 토큰 | 목록 위치(관찰값) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | calibrate | 리간드 탐색형, 101 | L | 1 | 5 | 5 | 3,855 | 2,154 | 65 | 0.0000905 | 6,666 | 1/5 |
| 2 | live | 리간드 활용형 | L | 1 | 5 | 5 | 4,194 | 2,271 | 65 | 0.0000954 | 6,892 | 1/5 |
| 3 | live | 리간드 활용형 | L | 2 | 5 | 4 | 4,225 | 2,286 | 56 | 0.0000960 | 6,913 | 2/4 |
| 4 | live | 리간드 활용형 | L | 3 | 5 | 3 | 4,257 | 2,302 | 47 | 0.0000967 | 6,934 | 2/3 |
| 5 | live | 단백질 활용형(1UBQ) | P | 1 | 5 | 5 | 7,900 | 4,146 | 65 | 0.0001741 | 9,363 | 1/5 |
| 6 | live | 단백질 활용형(1UBQ) | P | 2 | 5 | 4 | 7,931 | 4,159 | 56 | 0.0001747 | 9,384 | 2/4 |
| 7 | live | 단백질 활용형(1UBQ) | P | 3 | 5 | 3 | 7,963 | 4,175 | 47 | 0.0001754 | 9,405 | 3/3 |
| 8 | live | 리간드 탐색형(섞기 확인), 404 | L | 1 | 5 | 5 | 3,855 | 2,154 | 65 | 0.0000905 | 6,666 | 1/5 |

  첫 호출 보정: 본문 3,855 B·별칭 5개에 사용 2,219 토큰(입력 2,154·출력 65)·$0.0000905 대 예약 6,666 토큰·$0.10, 본문 바이트/입력 토큰 1.79, 예약식 `min(50000, 4096 + ceil(body_bytes × 2 / 3))` 조정 불필요(예약식은 사용자 결정이며 실행기는 바꾸지 않음). 합계 토큰 run L 11,465 / run P 12,648(한도 120,000), 비용 합 약 $0.00099(< $0.0010). 리간드·단백질은 비싼 계산 단위 때문에 다른 run에서 했다. 입력은 공개·공개 파생·합성 표시 입력뿐이라 사용자 데이터가 나가지 않았다.
  **위치 관찰**: 같은 풀·같은 목표(리간드 탐색형)에서 loop_seed 101(#1)과 404(#8)는 서로 다른 보낸 순서를 만들었고 두 번 모두 JEV가 고른 목록 위치는 1이었다. 이것은 관찰값 두 개일 뿐 섞기의 효과·무효과·편향의 증거가 아니다. 표의 목록 위치 열도 값을 기록한 것이며 어떤 경향의 근거로 쓰지 않는다(LJ3).
- calibrate·live 증거의 빌드 도장은 `c782419`(calibrate)·`c092591`(live)이며 제품 소스는 고정 `4360598`과 같다(그 사이 커밋은 증거뿐).

### 관찰하지 못한 사례 (위조하지 않음)
- run 취소 뒤 도착한 루프 응답(화면에 run 취소 경로 없음, `test_jev_loop_sends.py::test_a_late_reply_is_kept_but_never_the_selection`), 시작 전 취소된 후보 `unavailable`(`test_jev_loops_compute.py::test_two_presses_make_one_step_and_a_job_cancelled_before_start_is_unavailable`), 계산 예산 부족 `budget_blocked`와 `budget_exhausted` 끝내기(화면 run은 한도를 바꾸지 않음, `test_budget_blocked_names_each_short_axis_and_charges_nothing`·`test_a_loop_short_of_compute_budget_ends_budget_exhausted_with_its_unfinished_iteration`), 끝내기 서버 거절(화면은 단추를 닫아 요청을 보내지 않음, `test_end_refusals_follow_the_spec_order_and_write_nothing`), run당 10회 전송 소진(fixture 계획이 5회에서 외부 전송 멈춤으로 끝남, `test_the_ten_send_cap_and_the_budget_are_shared_with_m24_sends`), 연습용 run(`test_a_loop_projection_in_a_dry_run_run_names_no_loop_and_never_reads_the_key`), `null_result`·`failed` 후보 행의 표 정렬 위치(실제 도킹이 만들지 않음, fixture가 결과를 꾸며 넣지 않음, `jev-loop.test.cjs`가 덮고 화면은 `pending`·`not_run`·재사용 행으로 같은 규칙 확인). fixture 단계의 실호출 사례 둘(`JL-calibrate-send`·`JL-live-sends`)은 calibrate·live 단계에서 관찰했다.

### 회귀 (하나씩 순서대로, 각자 새 root·artifacts, 실호출 0, 모두 종료 0·`acceptance: true`)
- M24(fixture 단계) 26/26, M23 35/35, M22 25/25, M21 23/23, M20 24/24, M19 26/26, M18 24/24, M17 21/21, M16 19/19, M15 14/14, M14 15/15, M13 28사례(workflows·unavailable·regressions(M8–M10)·m11·m12·ledger). M23은 첫 사슬(`4360598`)에서 통과했고 그 하네스는 바뀌지 않아 다시 돌리지 않았다. M24와 나머지는 하네스 수정 뒤(`9a9a625`)에 돌렸다. 각 실행기 끝에 남은 프로세스·8000·3000 리스너 0, 간헐 실패 없음.
- 첫 M24 회귀 시도는 M24 하네스가 "리간드·단백질 탭에 `jev-` 요소 0"을 기대해 실패했다(단백질 공학 탭 41개·리간드 탭 35개, 제품 동작 변화가 아니라 M25 루프 영역의 `jev-loop-*` 요소). 사실과 수정 내용은 `regression-harness-changes.txt`에 있고 실패 증거는 커밋하지 않았다(Git 제외 artifacts에 보관).

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님).
- `backend/tests/test_api.py`: `/tools` 이름 집합에 `build_jev_loop_projection`. `test_reference_site_annotation.py`·`test_residue_numbering.py`: 사전 검사가 있는 도구 집합에 새 도구(호출 키에 루프 기록 입력 해시가 들어간다는 주석). `test_ligand_api.py`: `/capabilities` 방법 집합 둘에 `jev_loop`. 새 도구 하나·capability 하나가 늘었다는 이유 주석이 있다.
- `frontend/tests/report-library.test.cjs`: `jev_loop` 종류 이름 단언 한 줄.
- `scripts/test_codex_hooks.py`: Stop 훅 `CHECKS` 기대 15 → 17(무거운 루프 테스트 그룹 `b0d0f96`, 계산 테스트 그룹 `da37288`).
- `frontend/tests/offscreen/jev-flow.cjs`(M24 하네스, `9a9a625`): `tabSignature`가 `[data-testid="jev-loop-panel"]` 영역 글자를 서명에서 빼고 M24 요소 수를 `[data-testid^="jev-"]:not([data-testid^="jev-loop-"])`로 센다. 다른 단언·M24 실행기는 그대로다.
- 증액 호출자 AST 테스트 셋과 `test_jev_ast.py`는 고치지 않았다(호출자·임포터 집합 그대로). M17·M18·M19·M20·M21·M22·M23 코드·상수·결과와 해시 파일은 바꾸지 않았다.

## 해석 메모 (명세가 모호한 곳에서 조율 세션이 정한 해석)
- N1 단백질 루프 만들기는 M7 사전 검사 거절(`openmm_preflight_failed`)도 `setup_invalid`/`setup_reason`으로 거절한다(1MQ4는 모델링 불가라 단백질 QA·실호출은 1UBQ만).
- N2 `steps[].reason_code`는 작업 실패에 닫힌 이유 코드가 없으면(시간 초과 `{error: resource_exceeded, message: "job timeout"}`·취소·중단) null이다.
- N3 프로세스 시작 판정은 `budget_reserved.root_call_id == job_id`다(`job_terminal.attempt_id`가 아님). 과금 뒤·dispatch 전 취소는 '뒤'로 보아 `failed`·바퀴 시작·단위 셈에 들어간다.
- G1 `counts.reused_count` = 풀에서 `evaluation: reused`인 후보 수. G2 `jev_decided`/`human_decided`는 시작한 바퀴만(첫 단계 승인 기준). G3 선택 대기 중 늦은 제안이 계산 시작으로 오면 `proposal_late`. G4 도킹 승인의 `decided_by`는 늘 `human`, `proposal_handle` null.
- 끝난 루프 기록은 `jev_loop_ended` 이벤트로 동결한다(상태·끝 이유·결과 handle은 그 시점 도출에서, 쓰기 라우트 거절은 지금 로그에서, `current.remaining`만 지금 값). 끝난 루프의 `current`는 바퀴·phase·단계가 null이다.
- 작업 큐 기존 동작을 그대로 쓴 선택: 시작 전 취소는 `cancelled`·무과금, `retry`는 `failed`/`interrupted`만, `submit`은 같은 호출 키의 기존 작업을 상태와 무관하게 돌려준다. 그래서 루프가 승인했다가 시작 전에 취소된 후보는 그 run에서 `unavailable`이다.
- 작업 → 승인 귀속: 같은 호출 키의 가장 가까운 앞 승인에 속하되 사이에 `jev_loop_*` 이벤트나 M24 과학 전송 이벤트(승인·dispatch·결과)가 있으면 끊긴다. 단위 0 승인(재사용 채택)은 작업을 소유하지 않는다.
- 취소된 run에서도 루프 만들기는 거절하지 않는다(명세 3.1 거절 집합에 `cancelled`가 없다). 만든 루프는 곧바로 `run_cancelled`로 읽히고 이후 쓰기 라우트는 `cancelled`로 거절한다. 거절 집합에 이유를 더하는 것은 사용자 결정이라 더하지 않았다.
- 루프 쪽 전송 상태 `in_progress`와 M24 전송 기록의 `failed`는, 결과를 못 받고 사라진 이전 전송이 있는 run에서 새 전송의 `begin_send`부터 승인 이벤트까지의 짧은 구간에 서로 다르게 보일 수 있다(표시만의 차이, 쓰기 거절 판정은 같다).
- 새 `jev_loop_*` 이름·이유는 모두 명세 문자 그대로이고 새 이름을 만들지 않았다(`setup_reason`·`capability_unavailable`의 pin 불일치는 기존 이름 `missing_configuration`).

## 알려진 한계
- JEV 판정은 계산 대기열에 먼저 둘 후보 하나일 뿐이며 그 선택이 좋다는 주장도, 루프가 더 나은 후보를 찾는다는 주장도 하지 않는다. 고른 이유는 알 수 없다. 실호출 8회는 공개·합성 입력의 작은 풀(5개)뿐이었다.
- 단백질 루프는 M7 사전 검사를 통과하는 구조에서만 만들 수 있다(로컬 공개 구조 중 1UBQ뿐). 단백질 점수는 후보마다 다른 변이 구조에 도킹한 값이다(LJ7).
- 시작 전에 취소한 후보는 그 run에서 다시 계산할 수 없다(`unavailable`). 루프는 남은 작업을 재시도하지 않는다.
- 계산 시작 응답은 작업이 끝날 때까지 기다리고(기존 시작 라우트와 같음) 그동안 같은 run의 다른 변경 요청은 503 `busy`다. 외부 토큰을 늘릴 수 없어 후보 20개 단백질 루프는 run당 약 6번 전송이 한계다.
- 실호출의 transport 바이트 해시는 제품 게이트에서 기록하지 않으므로 transport 바이트 동일성은 fixture 단계 증거에 근거한다(미리보기 = `prepared`는 실호출에서도 확인).
- 화면에서 만들 수 없는 경로(run 취소 뒤 늦은 응답, 예산 부족, 10회 소진, dry-run, `null_result`·`failed` 정렬)는 백엔드·프런트 단위 테스트로만 확인했다.
- Stop 훅을 동시에 돌릴 때 환경·우연으로 간헐 실패하는 기존 테스트 셋이 있다(`docs/tracking/findings.md`).
- 명세·계획이 말한 M24 미리보기·승인 구성 요소의 공용화는 하지 않았다. `JevLoopPanel.tsx`가 마크업을 따로 두고 판단 로직만 `lib/jev.ts` 함수를 공유한다(`jev.ts`는 `usdText` export만 바뀜, `JevPanel`은 전송 기록 행 표시 prop `sendHistoryMark` 하나가 늘었고 그 값이 null이면 M24 DOM과 같다). M24 화면 불변이라는 더 강한 조건을 지키려는 선택이다.
- 독립 최종 검토(고정 뒤)의 막지 않는 관찰 다섯은 고정 소스를 바꾸지 않으려고 고치지 않고 `docs/tracking/findings.md`에 기록했다(수락 실행기가 멈춘 실호출 계획의 건너뛴 항목을 판정에 넣지 않음, 짝 표 행 `loop` 키가 프런트 타입에 없음, `qa_setup.py` 설명, 시작 경합 오류 코드의 화면 문구, 끝난 루프 요약의 `unfinished[]` 미표시).

## 대체한 과거 검증 범위
- M25는 공유 소스를 바꿨다: 백엔드 `api/app.py`(루프 라우트·capability·보고서 등록·`SUPPORTED_TOOLS`), `core/events.py`(이벤트 종류 넷), `jev_sends.py`·`egress/science.py`(루프 분기), `mutation_model_reads.py`(짝 행 `loop` 키), `workspace.py`·`config/tools.yaml`(새 도구), 프런트 `app/page.tsx`(마운트 둘)·`JevPanel.tsx`(루프 행 표시)·`MutationModelPanel.tsx`·`lib/mutation-model.ts`·`lib/jev.ts`·`lib/api.ts`·`contracts.ts`·`report-library.ts`, `design/components.css`.
- 그 밖의 연결 변경: `frontend/package.json`(`test:offscreen:jev-loop`), `.codex/hooks/stop.py`(`SCRIPT_TESTS`에 M25 실행기 테스트, `PYTEST_GROUPS` 두 그룹), `docs/standards.md`(게이트 목록), `scripts/AGENTS.md`.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(4,500개, 스크립트 포함, skip 0)와 M24(fixture 단계)·M23·M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함), 두 골든 `--check`로 대체한다. M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- 새 미해결 문제(`docs/tracking/findings.md`): Stop 훅 동시 실행 중 간헐 실패 셋, M24 하네스와 `jev-` 선택자 결합, 1MQ4 모델링 불가로 단백질 루프는 1UBQ로만 검증, 위치 관찰은 효과 근거가 아님, M25 수락 QA에서 만들 수 없는 사례.
