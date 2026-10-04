# M22 리간드 GA 설계 완료 기록

- 판정: **완료** (2026-10-05). main에는 아직 병합하지 않았다(사용자 통합 승인 대기, push 없음).
- 브랜치: `dryforge/m22-ga-design` (`phase/m22-ga-design` = main `849acb7`에서 분기). M21은 시작 전에 main에 병합되어 있었다(`61d5c03`, 기록 `849acb7`).
- 고정 소스: `a71b2e6`(`a71b2e6ac4f82311f1c008f9cc3646a0d0e063be`, 독립 코드 검토 수정 커밋). 증거 커밋 `9e63b41`. 고정 뒤 소스 변경은 없다. 고정 뒤 커밋은 증거·기록 문서뿐이다.
- 수락 증거: `docs/qa/m22-ga-20261004/preflight.txt`(착수 확인), `docs/qa/m22-ga-20261005/`(`gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M22 수락, `m21-regression/`, `m20-regression/`, `m19-regression/`, `m18-regression/`, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 51개 331,512,196 B, m14-regression 1개 1,191,726 B, m15-regression 1개 590,108 B, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`). 커밋한 폴더는 약 9.9 MB다.
- 외부 요청 0건, OpenRouter 호출 0회(흐름 행 두 개와 재현 검사 두 run).

## 결과물
- 작업 전용 도구 `qvina_ga_design`, 프로토콜 `qvina_ga_dock_v1`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`·작업 승인 허용 목록·guardian(도킹 인터프리터, 감시 대상, 종료 기록 한도 64 KiB)·큐 dispatch, `SUPPORTED_TOOLS` 아님) → 개체마다 단독 M18 `docking_result@1`(새 도킹만 게시) + 요약 `ligand_ga_result@1`. 작업 하나 = GA 한 번, 시작 때 `reserved_units` 예약(환불 없음), 시도 1회, 작업 한도 15000초. `config/tools.yaml`(L3, `durable_job`), `tools/energetic.py`(등록·작업 전용 표시), `core/events.py`(이벤트 두 종류).
- 서버 모듈: `ligand_ga_constants.py`(닫힌 집합·파라미터 범위·기본값·상한·예산 상수·고정 문장 G1–G3, 의존성 없음, 작업 모듈도 파일 경로로 읽음), `ligand_ga_inputs.py`(입장 1–5, `ga` 정규화·교차 규칙, 필터 적격, 풀·선택 기록, 개체 M18 인자·선택 재구성, 재사용 색인, 예약 단위·필요량·부족분·증액량·시작 전 확인 수치), `ligand_ga_bundle.py`(작업 모듈 세대 기록 + 서버 관찰로 요약 만들기, `check_summary`, GA 호출 키), `ligand_ga_jobs.py`(capability, 입장 4–5, 재사용 계획, 스테이징, `finish` 게시, GA 증액 `limit_approval`, 진행, 검증 읽기), `ligand_ga_reads.py`(시작 전 확인·목록·상세·개체), `ligand_ga_reports.py`(보고서 `ligand_ga`). 작업 모듈 `jobs/ligand_ga_worker.py`(RDKit은 Morgan 지문에만, 도킹은 `docking_worker.py` 파일 경로 함수로). 큐(`jobs/queue.py`: 15000초 상한, `SUMMARY_PROTOCOLS`로 M19와 같은 1회 시도·정리 뒤 게시·복구)·guardian·`api/app.py` 연결.
- M18·M19 덧붙임(명세 7절이 허용한 두 곳): `docking_bundle.producer()`에 GA 개체 증거(`_ga_individual_producer`, 가장 먼저 게시한 쪽 규칙 그대로), `docking_batch_inputs.published_m18_results`에 GA 개체 게시 handle(`setdefault`). `docking_worker.py`·`docking_constants.py`·M17·M19 상수·이유 집합은 바꾸지 않았다.
- API: `POST /runs/{id}/ligand/ga/preflight`, `GET /runs/{id}/ligand/ga/results`, `/results/{handle}`, `/results/{handle}/individual?candidate_id=`(handle은 경로), `POST /runs/{id}/ligand/ga/limit_approval`(사람 증액), `/capabilities`의 `methods.ligand_ga_design`(`GET /tools`에는 나오지 않음, M18·M19 작업 도구와 같음), 작업 `artifacts.ligand_ga_result`와 진행 필드 `ga`, 방법 보고서 `analysis_type: "ligand_ga"`.
- 화면: `frontend/src/components/LigandGaPanel.tsx`(새, 리간드 탭 M19 일괄 영역 다음), 순수 로직 `src/lib/ligand-ga.ts`(새), `app/page.tsx`(마운트, 개체 행 → M18 상세는 `dockingOpenRequest`), `lib/api.ts`·`contracts.ts`, `lib/report-library.ts`("리간드 GA 설계 보고서"), `design/components.css`(+ `npm run tokens`). M17 `FilterForm`·M18 `RefusalList`·`lib/docking.ts` 순수 로직은 가져다 쓰고 바꾸지 않았다.
- Fixture: `backend/tests/fixtures/ligand_ga/`(표시된 합성 block·규칙, 실제 M17 작업으로 만든 작은 풀 10개 후보 집합 `m17-candidate-set-small-pool.json`, 2,000개 측정 풀 입력, 표준 라이브러리만 쓰는 독립 oracle `independent_ga_oracle.py --check`, 기대 경로·산식 `expected.json`, `SYNTHETIC-PROVENANCE.md`, `build_ligand_ga_fixtures.py --check`), 도우미 `backend/tests/ligand_ga_fixture.py`.
- 테스트: 백엔드 `test_ligand_ga_inputs.py`, `_bundle.py`, `_worker.py`, `_jobs.py`, `_budget.py`, `_api.py`, `_reports.py`. 프런트 `tests/ligand-ga.test.cjs`. 스크립트 `test_m22_offscreen_acceptance.py`(39개).
- QA 도구: `frontend/tests/offscreen/ligand-ga-flow.cjs`(`test:offscreen:ligand-ga`, 모드 `main`·`unavailable`, M18 흐름 모듈을 불러 씀), `scripts/m22_offscreen_acceptance.py`(단계 `ga-main`·`ga-unavailable`, 재현 검사, `--regressions`).

## 사용자 결정 (2026-10-05)
근거는 결정 0030. 사용자는 명세 확정 때 모든 질문에서 추천안을 골랐다.
- 개체 = 부위 하나 × building block(후보 풀 = 게시된 M17 후보 집합, 새 후보 생성 없음). 적합도 = qvina 점수 단일 + M17 필터 통과(다목적 제외). 작업 하나 = GA 한 번(세대마다 승인 없음).
- 상한 개체 24·세대 8·새 도킹 100(기본 12·5·60). 다음 세대 = 이어받음 + 토너먼트 부모의 Morgan Tanimoto 유사 후보 + 무작위 비율(기본 0.2), 교차 없음. 자유 도킹만, 세대별 점수 표만(순위·최고·개선 금지). M13 연동 없음.
- 예산 = 시작 전 `reserved_units` 예약·환불 없음, 재사용은 무과금·상한에 세지 않음. 시간 기본 7200초·최대 14400초. 조기 중단 = 점수 최솟값이 N세대 연속 작아지지 않음(기본 3). seed 둘(GA·도킹). 재현성 = 같은 저장 결과가 있을 때만 같은 결과(개체마다 재사용 기록).
- 실행 중 조율 세션이 승인한 세부와 결과: 새 도킹은 `reserved_units`까지(T2 수정, 명세 3·6절 수정), 가벼운 스테이징과 서버의 개체 선택 재구성, `prepared.json` 전에 멈추면 요약 없음(작업 실패), 중단된 개체는 목록에 없음, `producer()`·`published_m18_results` 덧붙임 두 곳, 작업 모듈만 RDKit Morgan 지문 import, GA 전용 사람 증액 라우트와 새 이벤트 이름 둘, 다른 프로토콜의 7800 < `timeout_s` ≤ 15000 요청의 422 본문 변경.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인과 fixture | `268333b` |
| T2 서버 순수 모듈(상수·입장·요약 검증), 새 도킹 `reserved_units` 상한·조기 중단 규칙 수정 | `effe659`, `613a707` |
| T3 격리 GA 작업 모듈(실제 엔진 테스트, oracle 일치) | `5fe516e` |
| T4 작업 경로(큐·guardian·게시·GA 증액) | `134f247` |
| T5 읽기 API와 `ligand_ga` 보고서 | `ec98069` |
| T6 프런트 API·순수 로직 | `c2c3892`, `083ff47` |
| T7 리간드 탭 GA 설계 영역, 보고서 목록 이름 | `e946b3f`, `f77f5ae` |
| T8 오프스크린 흐름과 M22 수락 실행기(흐름이 찾은 유사도 표시 수정 포함) | `448e912` |
| T9 독립 코드 검토 수정 | `a71b2e6`(= 고정 소스) |
| T10 게이트·수락·회귀 증거 | `9e63b41` |
| T11 독립 증거 검토 | 커밋 없음(APPROVE) |
| T12 완료 기록·결정 0030·프로젝트 문서 | 이 기록과 같은 커밋 |

## 착수 확인 (`docs/qa/m22-ga-20261004/preflight.txt`, 기준 `849acb7`)
- (a) 도킹 환경(`docking_worker.py`를 파일 경로로 먼저 불러 socket을 막은 같은 프로세스)에서 RDKit Morgan(반지름 2, 2048비트, `rdFingerprintGenerator`)·Tanimoto가 동작했고, 온비트 정확 분수 |A∩B|/|A∪B|와 별도 RDKit 설치(ProLIF 환경)의 값과 전부 같았다. Tanimoto 동점이 흔해 풀 순서 동점 규칙이 실제로 쓰인다.
- (a2) 실제 M17 후보 집합 2,000개: 후보마다 `docking_bundle.submission`이면 ≈ 99초, 수용체·부모를 한 번만 검증하면 0.68초(표본 40개 바이트 동일), 행 선택을 모두 실은 스테이징 5,178,143 B(후보 4필드 + `input_sha256`만이면 1,958,143 B). `producer()`·`published_m18_results` 덧붙임은 새 이벤트에만 걸려 기존 반환값이 같다(코드 읽기).
- (b) 후보 집합 검증 읽기 0.031초, 적격 평가 2,000행 0.012–0.015초, 호출 키 2,000개 0.019초, 재사용 색인 0.005초.
- (c) 기본 값 자유 도킹 한 건 35.0–82.9초(6건 평균 71.4초). 새 도킹 100건 ≈ 7,140초, 기본 설정(예약 52) ≈ 3,710초. 같은 seed는 프로세스를 바꿔도 결과 바이트 동일하고 실제 `qvina_dock_v1` 작업 바이트와 같다.
- (d) 최악 요약(8세대 × 24) 74,646 B(1 MiB의 7.1%), 개체 게시 이벤트 ≈ 376 B, 새 도킹 100건이면 작업 출력 ≈ 21–40 MB.
- (e) 15000초는 API `JobSubmit.timeout_s`(`le=7800`)와 `JobQueue.submit` 프로토콜별 상한 두 곳에서 거절되었다. guardian `MAX_GO_WAIT_S` 3600은 GO 대기만이다. M19 선례대로 이 프로토콜만 넓혔다.
- (f) 독립 oracle(표준 라이브러리, `mw` 미import)로 기대 경로 10개와 산식 표를 `expected.json`에 기록했다(`--check` 종료 0). 명세가 비워 둔 해석 A1–A7은 T2·T3에서 확정했다(A4·A5는 명세 3절 수정으로).
- 정할 점 C1–C5(스테이징 내용, 작업 기록 크기, 422 본문, 기본 설정의 "끝까지 못 갈 수 있음" 문구, 100건 상한과 기본 7200초)는 결정 0030의 조율 세션 항목과 화면 안내(`gaTimeAdvice`, `PARTIAL_RISK_NOTE`)로 처리했다.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토(T9, 고정 전): **막는 지적 없음**. 권고를 반영했다(`a71b2e6`): `finish`가 읽을 수 있는 세대 기록의 새 도킹 개체를 먼저 모두 게시하고 읽을 수 없거나 틈이 있는 기록·종료 기록 불일치는 예외가 아니라 `worker_failed`(M19와 같음), 작업 모듈이 `dock_row`가 돌아오자마자 신호를 막은 뒤 개인 폴더를 지우고 남은 `qvina_work`를 먼저 지움, 시작 때 재사용 계획으로 128 MiB 크기 검사를 다시 함(`ga_reuse_too_large`, 예약 전), 진행에 `individuals_result_files` 추가와 화면의 "새 도킹" 이름표, 점수 없는 개체를 모든 정렬에서 끝에, 요약 읽기 한 번에 후보 집합 검증 한 번(`_one_pool_check`).
- 독립 증거 검토(T11, 코드 검토자와 다른 새 인스턴스, 고정 뒤): **APPROVE**. 참고 지적 셋은 아래 "증거 검토 참고"에 적었다.

## 게이트 (고정 `a71b2e6`, `gate.txt`, 2026-10-04 16:49:04–17:30:16 UTC)
시작 때 작업 트리 깨끗함, 다른 세션의 Stop 훅 pytest(16:38:19Z 시작)와 그 작업 모듈이 모두 끝난 뒤 시작(겹침 없음), 모든 명령을 한 줄로 차례로 실행, 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 백엔드 pytest는 Stop 훅의 다섯 그룹(`.codex/hooks/stop.py` `CHECKS[1:]`)을 제한 없이 따로 돌렸다. 끝난 뒤 작업 트리 깨끗함, HEAD 그대로.

| 명령 | 결과 |
|---|---|
| 백엔드 pytest 다섯 그룹(화학 24, M11 작업 API 25, M18 도킹 198, M19 일괄 209, 나머지 2,063 = 백엔드 1,753 + 실행기 310) | exit 0 ×5, 백엔드 합계 2209 passed(수집 2209), 0 skipped. 나머지 그룹 1324초 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 17개 파일(M21 게이트 16개 + `test_m22_offscreen_acceptance.py`) | exit 0, 423 passed, 0 skipped(M22 실행기 39개) |
| `node --check` 흐름 11개(M21의 10개 + `ligand-ga-flow`) | exit 0 ×11 |
| `npm --prefix frontend run test:events` | exit 0, 345 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `a71b2e6`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m22_offscreen_acceptance.py --root runs/m22-acceptance-20261005-attempt1 --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/attempt1 --out docs/qa/m22-ga-20261005/acceptance --regressions --kbase <home>/Projects/kbase_kinase` (2026-10-04 17:30:36Z 시작, 18:24:24Z 종료 0, 회귀 포함 약 54분, M22 부분 17:30:40–17:36:39Z). 실패한 시도·재시도 없음. 시작 전 8000·3000 포트 비어 있음.
- 빌드 `CHa6nmR7ciWcO8tOTTcKV`(gitHead `a71b2e6`, 소스 도장 일치, `dirtyFiles` 없음, `--build auto`가 typecheck 뒤 build). `verdict: pass`, `acceptance: true`, `failedSteps` 없음, 판정 사례 25개 모두 통과(`ga-main` 21 + `ga-unavailable` 2 + `GA-reproducible` + `S-no-egress`). 환경(`ligand_ga_design` 사용 가능: qvina-2.1.0-h4a521e9_8, Meeko 0.8.0, RDKit 2026.03.6, MDAnalysis 2.10.0, gemmi 0.7.5, `ga_worker_sha256` `0c001cae…`, `ga_constants_sha256` `bdbbe8c9…`; 단독 도킹·M17 후보 사용 가능; `.deps` 없는 layout 백엔드는 `worker_missing`)·남은 프로세스 행 통과. 비-loopback 요청 0건, 제공자 호출 0회.
- 입력: 공개 수용체 `fixtures/chemical/prolif-vina-rec.pdb`, 공개 파생 부모 `fixtures/docking/public-derived-parent-record0.sdf`, 합성 표시 블록 `fixtures/ligand_ga/synthetic-ga-small-blocks.smi`(실제 M17 점검·생성으로 후보 10개, 부위 원자 22).
- 관찰 요약(실제 Electron 오프스크린, 실제 qvina): 후보 집합 전 이유만 → 수용체 가져오기 + 실제 M17 작은 풀 → 파라미터 가드(GA seed 비움, 개체 25, 무작위 비율 0.6, 개체 − 이어받음 < 2, 새 도킹 < 개체: 칸마다 이유, 시작 전 확인·시작 막힘, 요청 없음)·"기본값으로"(GA seed 유지) → `ga_pool_too_small` 거절(기본값 10 < 12, M17 필터 3 < 4) → GA 1 시작 전 확인(`reserved_units` 6 = 명세 산식, 필요 6단위·1200초, 부족 0, "끝까지 못 갈 수 있음", G1) → 실제 GA 1 완료(두 번째 승인 없음, `timeout_s` = `total_s` + 600, 정확히 예약 단위만 과금, 요약은 목록에만) → 진행 줄 = 작업 기록 → 결과(세대 탭, 개체 행 = 저장 요약, 점수 = 각 M18 결과 첫 모드, 이어받음 = 직전 세대 저장 점수 낮은 순, 자리 수 산식, 유사도 = fixture 지문 Tanimoto, 최솟값·최댓값은 값만, 종료 이유) → 정렬(자리·후보·점수, 점수 없는 행은 끝, `aria-sort`, 순위 열 없음) → 개체 행 → 기존 M18 상세 → GA 2(다른 GA seed, 같은 도킹 seed): 부족분 → 화면 버튼으로 증액(부족분만, `by: human`, GA 맥락) → GA 1 인자 다시(기존 작업, 새 작업·단위 없음) → GA 2가 GA 1 저장 결과 재사용(G1 + G3) → GA 3 `pool_exhausted`(`complete`) → GA 4(새 도킹 상한 4) `partial`/`docking_limit`(G1 + G2, 멈춘 세대 표시, 계산하지 않은 개체 숫자 없음) → GA 5 도킹 중 화면 취소(`cancelled` 작업, `partial`/`cancelled` 요약, G2, 남은 프로세스 없음, 환불 없음) → 보고서·지식 탭 목록 "리간드 GA 설계 보고서"·Markdown/JSON 내려받기 = 백엔드 바이트 → 전역 예산 = 백엔드 → 프로세스 → 문구. `ga-unavailable`: run 없음·`worker_missing`은 이유만(숫자·컨트롤·GA 요청 없음).
- 예산(백엔드 `/budget`에서 셈): run A 사용 32 / 한도 32 = M17 2 + GA마다 시작 전 `reserved_units` 한 번(환불 없음), 같은 인자 재제출 0. 모든 한도 증액은 화면 버튼 클릭이다.
- 재현 검사(`GA-reproducible`): 흐름의 GA 1(GA seed 11, 도킹 seed 1, cpu 1, 개체 4, 세대 2, 이어받음 2, 새 도킹 상한 6, `total_s` 600)을 **같은 서버 프로세스**의 새 run 두 개에서 API로 다시 돌렸다(콜드 재시작이 아님). 둘 다 작업 `done`, `complete`/`generations_complete`, run별 obj:// handle과 그 위에서 계산된 해시(`input_sha256`·`selection_sha256`·`call_key`)만 자리표시로 바꾼 요약 SHA-256 `479ddc70…9d63a`가 흐름과 같았고, 개체 8개의 결과 내용과 포즈 SDF 바이트도 같았다. 다른 버전 간 비트 동일은 주장하지 않는다.

### 관찰하지 못한 사례 (위조하지 않음)
- `GA-null-result`(점수 없는 개체 화면): 작은 풀 후보 10개 모두 qvina가 모드를 낸다(착수 확인). `frontend/tests/ligand-ga.test.cjs`(점수 없는 행은 숫자 없이 늘 끝)와 `backend/tests/test_ligand_ga_worker.py`가 덮는다. 작업 모듈 테스트의 점수 없는 개체는 실제 qvina가 아니라 표시된 합성 대역 도킹(`stand_in`, "selection-logic stand-in, not engine output")으로 만든 것이다(아래 증거 검토 참고).
- `GA-no-change`(조기 중단): 엔진 점수에 달려 있어 그것을 강제하는 입력을 고르지 않았다. `test_ligand_ga_worker.py`(`test_pool_exhausted_no_change_and_filter_excluded_on_stored_real_results`)와 `test_ligand_ga_bundle.py`(조기 중단 검증)가 덮는다.
- `GA-time-and-worker-limits`(`time_exhausted`, `candidate_timeout`, `worker_failed`, `resource_exceeded`): 몇 시간·작업 모듈 강제 종료·큰 출력이 필요하다. `test_ligand_ga_worker.py`(시간·출력 총량·SIGTERM, 테스트에서만 줄인 상수)와 `test_ligand_ga_jobs.py`(`test_run_budget_deadline_is_time_exhausted_with_a_partial_summary`, `test_hard_kill_of_the_worker_is_worker_failed_and_has_no_retry`, `test_server_death_recovery_publishes_staged_individuals_and_a_worker_failed_summary`)가 덮는다.

### 단위 테스트로만 확인한 것
- 코드 검토 수정 중 읽을 수 없는 세대 기록·종료 기록 불일치(`test_an_unreadable_generation_record_or_an_end_mismatch_publishes_then_is_worker_failed`), 늦은 SIGTERM·남은 개인 폴더(`test_a_finished_docking_survives_a_late_sigterm_and_a_stale_private_directory`), 시작 때 재사용 크기 재검사(`test_admission_refusals_record_and_charge_nothing`, 예약 전 거절)는 백엔드 테스트로만 확인했다. 흐름은 정상 종료·취소·상한 경로만 지난다.
- 서버 재시작 복구(`interrupted` + `worker_failed` 요약)와 events-only 복구는 백엔드 테스트(`test_ligand_ga_jobs.py`)로만 확인했다.

### 증거 검토 참고 (T11, 막는 지적 아님)
- `summary.txt`의 폴더 색인은 회귀 폴더마다 `binary-artifacts.json`이 있다고 적지만, `m13-regression/`의 `binary-artifacts.json`은 256 KiB를 넘어 Git 제외 `export-full/`로 옮겨졌다(그 폴더의 `ARCHIVED-EVIDENCE.sha256` 첫 줄). 증거 자체는 해시로 대조된다. 해시로 묶인 증거 폴더라 고치지 않고 여기 적는다.
- `GA-null-result`를 덮는 백엔드 테스트는 실제 qvina가 아니라 표시된 합성 대역 도킹이 낸 점수 없는 개체를 쓴다(선택 규칙·표시 순서 검증용). 실제 qvina가 모드 0개를 내는 경우는 M18·M19와 같이 관찰하지 못했다. 프런트 표시는 `ligand-ga.test.cjs`가 덮는다.
- `GA-partial`(K01)·`GA-cancel`(C01) 사례의 G2 단언(`facts2.statements` = `["G1", "G2"]`)은 대장 행 문장이 아니라 흐름 스크립트 `frontend/tests/offscreen/ligand-ga-flow.cjs` 1378행·1428행 근처의 `assert`에 있다(통과해야 그 단계가 pass).

### 회귀 (고정 `a71b2e6`, 같은 빌드 `CHa6nmR7ciWcO8tOTTcKV`, M22 실행기 `--regressions`가 차례로)
- 각자 새 `--root runs/m22-acceptance-20261005-attempt1-m2X|m1X-regression`·`--artifacts frontend/tests/offscreen/artifacts/m22-acceptance/attempt1/regressions/m2X|m1X`, `--code-root <repo>`(M20·M16·M15는 `--kbase`). 대장마다 같은 buildId·gitHead, `buildCurrentWithSource: true`, `dirtyFiles`는 이 QA의 Git 미추적 증거 폴더뿐(소스 파일 없음).
- M21 `m21-regression/` → `acceptance: true`, 23/23(`MM-unavailable`·`MM-pair-approval`·`MM-failed-job`·`MM-zero-contacts`·`MM-conditional-limitations` 관찰하지 않음, M21과 같음). M20 → 24/24(`M-map-conflict`·`M-too-many-positions`·`M-nonstandard-disulfide`). M19 → 26/26(`B-dry-run-shortfall`·`B-null-result`·`B-time-limits`). M18 → 24/24(`D-zero-modes`). M17 → 21/21. M16 → 19/19. M15 → 14/14. M14 → 15/15. M8–M13 `m13-regression/`(`--phases workflows,unavailable,regressions,m11,m12,ledger`) → 28/28, 17행 통과, M11·M12 하위 실행기 통과.
- 모두 종료 0, 외부 요청 0건, 남은 프로세스 없음. 제공자 호출 필드가 있는 흐름 행은 모두 0회(M13 하위 실행기·회귀 행 7개는 이 필드를 기록하지 않음, M18–M21과 같음).

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님). 기존 수락 실행기와 흐름 스크립트는 하나도 고치지 않았다(회귀 대장의 "Changed existing expectations: none").
- `backend/tests/test_docking_batch_budget.py`(증액 호출자 테스트): 소스 검사 집합에 `ligand_ga_jobs.py`를 더하고, `api/app.py`의 `limit_approval` 호출자 AST 검사를 `docking_batch_jobs.limit_approval` 호출로 좁혔으며(GA 라우트는 GA 함수를 부름), `limit_approval` 라우트 목록에서 `/ligand/ga/` 경로를 뺐다. M19 증액 함수·라우트가 각각 하나라는 단언은 그대로다. GA 쪽 규칙(호출자 둘, 서로 부르지 않음)은 새 `test_ligand_ga_budget.py`가 확인한다.
- `backend/tests/test_ligand_api.py` 2곳: `/capabilities` 방법 집합에 `ligand_ga_design`.
- `frontend/tests/report-library.test.cjs`: `ligand_ga` 종류 이름 "리간드 GA 설계 보고서" 단언 추가.
- 422 본문 변경(테스트 수정 없음): API `JobSubmit.timeout_s` 상한을 15000으로 올려 다른 프로토콜의 7800 < `timeout_s` ≤ 15000 요청은 422 상태 그대로 본문이 요청 모델 오류에서 큐의 "invalid job timeout" 도구 실패로 바뀐다. 이 본문을 고정한 기존 테스트는 없었고(`test_docking_batch_jobs.py`는 상태 코드만 봄), 새 `test_ligand_ga_jobs.py::test_registration_capability_and_protocol_timeout_bound`가 바뀐 본문을 단언한다.
- 모든 회귀가 새 루트라 이전 결과 재사용의 영향이 없다. M22는 M18 호출 키가 묶는 파일을 바꾸지 않았으므로 M21 뒤에 만든 M18·M19 결과는 GA·M18·M19가 계속 재사용한다.

## 알려진 한계
- GA 입력 풀은 공개 ProLIF/Vina 수용체 fixture 위의 합성 표시 block 작은 풀이다. 실제 qvina 점수로 GA 동작을 검증했을 뿐 생물학적 설계가 아니다.
- 시간은 기본 값 6건(35–83초)과 작은 풀(exhaustiveness 1)에서만 쟀다. 새 도킹 100건 연속과 4시간 실행의 잠금·폴링 거동은 실제로 돌리지 않았다(가늠). exhaustiveness·회전결합·상자가 크면 14400초에서도 100건이 다 안 될 수 있다.
- `parent_candidate_id`·`similarity`는 작업 모듈 기록이며 서버가 다시 계산하지 않는다(서버 모듈 RDKit 금지, G1). 모양만 검사한다.
- 같은 seed라도 저장 결과 집합이 다르면 다른 경로가 나온다(G3). 시간·상한·취소로 멈춘 실행은 재현을 약속하지 않는다(G2).
- GA가 도는 동안(최대 15000초) run 실행 잠금과 전역 작업 슬롯을 쥔다.
- 요약 읽기는 단일 게시·선택 기록·모든 개체 결과를 매번 다시 검증한다(이벤트 로그 재파싱). 개체 ≤ 101개 결과를 다시 읽으므로 GA 요약이 많은 run에서는 목록·폴링이 느려질 수 있다.
- Stop 훅 나머지 그룹은 단독 1324초로 480초 제한을 넘고, M20·M21·M22 실행기 단위 테스트가 훅 목록에 없다(`docs/tracking/findings.md`).

## 대체한 과거 검증 범위
- M22는 공유 소스를 바꿨다: 백엔드 `api/app.py`(`JobSubmit.timeout_s` 상한, GA 거절 코드, capability, 작업 승인 허용 목록, 작업 artifacts·진행, 보고서 분기·목록, 읽기·증액 라우트), `jobs/queue.py`, `jobs/guardian.py`, `core/events.py`, `tools/energetic.py`, `config/tools.yaml`, `docking_bundle.py`(`producer()`), `docking_batch_inputs.py`(`published_m18_results`). 프런트 `app/page.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, `design/components.css`(+ 생성물), `package.json`.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(2209개, skip 0)와 M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `a71b2e6`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합(사용자 승인 대기). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): Stop 훅 나머지 그룹 시간 초과와 M22 실행기 단위 테스트 누락, 관찰하지 못한 사례, 100건·4시간 실행 미측정, GA 요약 읽기 재검증 비용.
