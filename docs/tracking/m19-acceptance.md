# M19 후보 일괄 도킹(qvina) 완료 기록

- 판정: **완료** (2026-10-03). main 병합: `20e652c`(push 없음).
- 브랜치: `dryforge/m19-batch-docking` (`phase/m19-batch-docking` = main `2c04db4`에서 분기). M18은 시작 전에 main에 병합되어 있었다(`e0b84ea`, 기록 `2c04db4`).
- 고정 소스: `858bd45`(`858bd45217e5bae3e87c4451261c1bc369a079c3`, 독립 코드 검토 수정의 마지막 커밋). 증거 커밋 `c11bfb4`(`c11bfb46ff318e9dcd3970a410e515cb91f4ce7a`). 고정 뒤 제품 동작을 바꾸는 소스 변경은 없다. 고정 뒤 변경은 증거·기록 문서와 `8a327c8`(`backend/mw/api/app.py`의 주석 한 줄, Stop 훅 `.codex/hooks/stop.py`의 스레드 수를 그룹 수로 맞춤)이며, `8a327c8`은 고정 소스의 게이트(`858bd45`)에 포함되지 않는다.
- 수락 증거: `docs/qa/m19-batch-20261003/`(`preflight.txt` 착수 확인, `gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M19 수락, `m18-regression/`, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 51개 331,871,173 B, m14-regression 1개 1,191,725 B, m15-regression 1개 590,108 B, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 외부 요청 0건, OpenRouter 호출 0회(모든 흐름 행과 재현 검사).

## 결과물
- 작업 프로토콜 `qvina_batch_dock_v1`(도구 `qvina_dock_batch`, 엔진 `qvina`, 기존 `JobQueue` 비싼 작업 경로, 작업 시간 상한 7800초, 시도 1회) → 후보별 `docking_result@1`(단독 M18과 같은 객체) + 요약 `docking_batch_result@1`. 작업 모듈 `backend/mw/jobs/docking_batch_worker.py`(M18 작업 환경 그대로, `docking_worker.py`를 파일 경로로 불러 행 계산). `jobs/queue.py`(프로토콜 상한, N단위 예약, 재사용 계획, 종료 상태마다 행·요약 게시, N = 0, 시도 1회, 복구), `jobs/guardian.py`(고정 진입점, 종료 기록 한도 64 KiB, 감시 대상), `runtime/orchestrator.py`(`reserve_attempt(units=…)`, `raise_limits`), `core/events.py`(`docking_batch_row_published`, `docking_batch_published`), `tools/energetic.py`·`config/tools.yaml` 등록, `docking_bundle.py`(`store_result` 분리, 일괄 행 게시 증거를 받는 `producer()`), `docking_worker.py`(동작 변경 없는 `receptor_inputs`·`receptor_prepared`·`dock_row` 추출).
- 서버 모듈(RDKit·Meeko·MDAnalysis import 없음, qvina 실행 없음): `docking_batch_constants.py`(상한·상태·이유·고정 문장 B1–B3, 의존성 없음), `docking_batch_inputs.py`(입장, 행별 M18 인자, `batch_input_sha256`, 재사용 색인, 필요량·부족분·증액량), `docking_batch_bundle.py`(요약 행 규칙·검증), `docking_batch_jobs.py`(capability, 재사용 계획, 스테이징, `finish`, `limit_approval`, 진행, 검증 읽기), `docking_batch_reads.py`(읽기 API), `docking_batch_reports.py`(보고서).
- API: 시작 전 확인 `POST /docking/batches/preflight`(읽기), `GET /docking/batches`, `GET /docking/batches/detail`, 사람 증액 `POST /docking/batches/limit_approval`, `/capabilities`의 `methods.ligand_docking_batch`, 작업 기록의 `batch` 진행 필드와 `artifacts.docking_batch_result`, 방법 보고서 `analysis_type: "ligand_docking_batch"`, 작업 승인 허용 목록에 `qvina_dock_batch`, `JobSubmit.timeout_s` 상한 7800(이 프로토콜만 큐가 허용). 가져오기 종류는 새로 만들지 않았다.
- 화면: 리간드 설계·탐색 탭에 도킹 영역 다음으로 붙인 `frontend/src/components/DockingBatchPanel.tsx`(순수 로직 `src/lib/docking-batch.ts`), `app/page.tsx`(마운트, 보고서 목록 `reloadToken`, 행 상세 → `DockingPanel.openRequest`), `DockingPanel.tsx`(`openRequest`, `RefusalList` export), `LigandPanel.tsx`(`FilterForm` export와 `idPrefix`), `lib/api.ts`·`contracts.ts`·`report-library.ts`("리간드 도킹 일괄 보고서"), 스타일 `design/components.css`와 생성물(정렬 버튼 2줄).
- Fixture: `backend/tests/fixtures/docking/m19-batch-input.json`(기존 파일만으로 만든 일괄 입력, 명세 산술 손 oracle, 착수 확인 관찰값)과 `SYNTHETIC-PROVENANCE.md` 절, 테스트 도우미 `backend/tests/docking_batch_fixture.py`. 새 구조·SDF·후보 파일은 없다.
- 테스트: 백엔드 `test_docking_batch_inputs.py`, `test_docking_batch_bundle.py`, `test_docking_batch_worker.py`, `test_docking_batch_jobs.py`, `test_docking_batch_budget.py`, `test_docking_batch_api.py`, `test_docking_batch_reports.py`. 프런트 `tests/docking-batch.test.cjs`. 스크립트 `test_m19_offscreen_acceptance.py`. Stop 훅에 일괄 테스트 그룹(`.codex/hooks/stop.py`, `scripts/test_codex_hooks.py`).
- QA 도구: `frontend/tests/offscreen/docking-batch-flow.cjs`(`test:offscreen:docking-batch`, 모드 `main`·`unavailable`), `scripts/m19_offscreen_acceptance.py`(단계 `batch-main`, 재현 검사, `batch-unavailable`, `--regressions`).

## 사용자 결정 (2026-10-03, 명세 확정 때)
근거는 결정 0027. 사용자는 모든 질문에서 추천안을 골랐다.
- 일괄은 작업 하나, 새로 계산하는 행마다 1단위. 방식은 일괄마다 하나. 부모 기준 행은 선택 사항(기본 끔)·자유 방식에서만(코어 고정에서는 비활성, 새 방법 없음).
- 후보는 M17 후보 집합의 필터 결과 + 체크박스. 결과는 후보별 `docking_result@1` + 일괄 요약.
- 상한 50(+1)·행당 300초·전체 2시간(꽉 찬 일괄은 부분 완료일 수 있음을 시작 전에 안내). 부분 완료는 끝낸 행을 보관.
- 표는 후보별 점수 + 열 정렬만(부모 대비 차이·접촉 잔기 비교·순위 없음), 행에서 기존 M18 상세로.
- 일괄 시작 때 사람의 명시적 한도 증액 승인(부족분만, run 끝까지 유지, 이벤트 기록, 사람만). 저장된 결과 자동 재사용(과금 없음). 활동 시간은 실제 경과만. 일괄 보고서 하나 + 후보별 M18 보고서는 그대로.
- 조율 세션이 정하고 사용자가 최종 확인에서 바꿀 수 있는 것(고정 문장 B1–B3 문구, 점수 열 = 첫 행, 작업 시간 한도 7800초, 출력 총량 128 MiB, N단위 예약·환불 없음, 시도 1회, 서버가 만드는 요약, 추가 이유, 착수 확인이 바꾼 행별 스테이징 + 종료 때 게시 설계, 증액 규칙과 60초 여유, 재사용 키 = M18 호출 키 전체, N = 0도 첫 계산 승인)은 결정 0027에 적었다.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인: 측정, 일괄 fixture | `ebb811c` |
| (준비) M11 handshake 캐시 테스트가 화학 작업 모듈만 세게 함 | `b2c6436` |
| T2 상수, 입장, 시작 전 확인, 요약 검증 | `f672407` |
| T3 일괄 작업 모듈(수용체 한 번 준비) | `9627eb5` |
| (준비) Stop 훅 일괄 테스트 그룹 | `b8fafd5` |
| T4 `reserve_attempt` 단위 수 | `8e81443` |
| T4 작업 경로: 등록, N단위 예약, 스테이징, 행 게시, 요약, 복구 | `1e4bfb8` |
| T4 작업 테스트, N = 0 fixture 값, Stop 훅 그룹 | `665807a` |
| T5 사람 증액 승인 | `5ab616f` |
| T6 읽기 API | `49d42c7` |
| T7 `ligand_docking_batch` 보고서 | `5a71ffe` |
| T8 프런트 API·타입·순수 로직 | `e364a77` |
| T9 일괄 화면 | `ca47e78` |
| T10 수정: 시작 전 확인 거절의 수용체 거부 목록 표시 | `e7727ad` |
| T10 오프스크린 흐름 | `1baeb3e` |
| T10 M19 수락 실행기와 단위 테스트 | `a4a79c0` |
| T10 재실행 작업 상태와 요약 상태 분리 | `6d28e2d` |
| T11 독립 코드 검토 수정 | `f3cc8c6`, `4aa9fc2`, `b505830`, `858bd45`(= 고정 소스) |
| T12 게이트·수락·회귀 증거 | `c11bfb4` |
| 완료 기록·결정 0027·프로젝트 문서 | 이 기록과 같은 커밋들 |

## 착수 확인 (`preflight.txt`, 기준 `2c04db4`)
- 수용체 PDBQT를 한 번만 준비해 7행(부모 자유 1, 후보 자유 3, 후보 코어 고정 3)에 써도 모든 행이 단독 M18 작업과 출력 바이트·`docking_result@1` 내용·handle·`input_sha256`·점수·포즈가 같았다. 수용체 준비 0.93초.
- 행당 시간(exhaustiveness 8, 이 fixture 크기): 자유 32.41–41.17초, 코어 고정 5.54–6.15초. 꽉 찬 자유 일괄 51행은 약 2,100초로 7200초 안이지만 exhaustiveness·비틀림·상자에 비례해 늘어난다.
- 작업 실행 중 행 게시는 큐의 게시 순서상 불가능했다. 행별 스테이징 + 종료 때 서버 게시로 바꾸었고 조율 세션이 사용자에게 알렸다(결정 0027).
- 숨은 900초 상한 두 곳(`JobQueue.submit`, API `JobSubmit.timeout_s`), 결과 하나 239,389–312,672 B·이벤트 줄 320,327–418,189 B(51행 ≈ 16 MB·≈ 21 MB), `reserve_attempt`만 고치면 재생은 N을 그대로 더함, `budget_limit_updated`에 맥락 필드를 더해도 재생 불변, M18 `producer()`·보고서 확장 필요, 재사용 키의 작업 모듈 해시, 증액 직후 런타임 오버헤드, N = 0 승인, 2시간 동안 잠금·전역 슬롯 점유 — 8개 정할 점은 T2–T5에서 정했다(결정 0027, `docs/engineering-notes.md`).

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토(고정 전): 막는 지적 없음, 권고 여럿. 고친 것: 요약을 만들 수 없어도 검증된 행 결과는 자기 행 게시 증거로 읽히고 재사용됨(`f3cc8c6`), 증액 승인의 판단·응답·계획을 실제 증액이 쓰는 스냅숏(과금된 사용량)으로 통일하고 취소된 run을 거절(`4aa9fc2`), 일괄 capability가 일괄 작업 모듈 자체 handshake를 요구(`b505830`), 작업 마감으로 멈춘 일괄이 작업 `failed`만이 아니라 요약 상태·멈춘 이유를 보임(`858bd45`). 고치지 않은 권고(증액 상한·여유의 해석은 결정 0027로 정함, 상자 계산이 작업 모듈과 `dock_row`에 중복, 늦은 신호가 끝난 행을 잃게 할 수 있음·남은 `qvina_work` 폴더의 `OSError`, 활동 시간 예산을 제출 때만 확인, 멈춘 뒤에도 재사용 행은 `scored`, 51행 읽기 비용, 2시간 작업의 stdout 상한, `pocket_reports._budget_snapshot_valid` 비공개 import)는 아래 "알려진 한계"와 `docs/tracking/findings.md`에 적었다.
- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 고정 뒤): **approve**. 권고(증액 승인 이벤트가 커밋한 증거에 해시로 묶여 있지 않음, 명세 13절 2의 시간 한도·크래시 사례는 오프스크린이 아니라 백엔드 테스트로만 덮음, 일부 사례의 대장에 일괄 상태가 빠짐)는 이 기록과 `findings.md`로 처리했다.

## 게이트 (고정 `858bd45`, `gate.txt`, 2026-10-03 02:11:48–02:37:17 UTC)
시작 때 작업 트리 깨끗함, 다른 세션의 Stop 훅 pytest가 끝난 뒤 시작(겹침 없음), 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 끝난 뒤 작업 트리 깨끗함, HEAD 그대로, 남은 프로세스 없음.

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 1613 passed, 0 skipped(1515초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 14개 파일(M18 게이트 13개 + `test_m19_offscreen_acceptance.py`) | exit 0, 310 passed, 0 skipped |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow`·`ligand-flow`·`docking-flow`·`docking-batch-flow` | exit 0 ×8 |
| `npm --prefix frontend run test:events` | exit 0, 277 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `858bd45`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m19_offscreen_acceptance.py --root runs/m19-acceptance-20261003-attempt1 --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/attempt1 --out docs/qa/m19-batch-20261003/acceptance --regressions --kbase <home>/Projects/kbase_kinase` (02:38:10–03:23:28 UTC, 회귀 포함 2718초).
- 그 전에 같은 명령을 `--root runs/m19-acceptance-20261003`로 한 번 띄웠다가 도구의 2시간 백그라운드 상한 때문에 빌드 직후(약 17초, 흐름 시작 전) 멈추고 분리 실행으로 다시 띄웠다. run·작업·흐름이 만들어지기 전이라 수락 시도로 세지 않으며 그 로그는 Git 제외 `…/m19-acceptance/final/`에 있다. 그 빌드가 아래 빌드다.
- 빌드 `HZVIvlS1pgVkSE0gAkqD6`(gitHead `858bd45`, 소스 도장 일치). `verdict: pass`, `acceptance: true`, 판정 사례 26개(`batch-main` 22 + `batch-unavailable`의 `B-no-run`·`B-unavailable` + `B-reproducible` + `S-no-egress`), 단계 `batch-main`·`batch-unavailable` 통과. 환경·capability(`ligand_docking_batch` 사용 가능, `batch_constants_sha256 81cdcdf2…d53d`)·layout `worker_missing`·남은 프로세스·증거 내보내기(누출 없음) 행 통과. 비-loopback 요청 0건, 제공자 호출 0회, 남은 일괄·도킹·M17 작업 프로세스·guardian·`qvina2`·8000/3000 리스너 없음.
- 관찰 요약: run A — 구조 분석 탭 run 그대로(run 선택 없음), capability 줄, 빈 목록, 시작 막힘 → 도킹 영역에서 수용체 가져오기, 실제 M17 점검(승인)·생성(부위 22) → 후보 id가 fixture와 같은 집합 순서 → 후보 집합·부모 SDF, M17 필터(중원자 ≤ 45, 통과만) 행 = 서버 필터 페이지, 체크박스, "선택 n / 50", id는 클릭 순서가 아니라 집합 순서 → 물·아연 수용체 시작 전 확인이 `receptor_unsupported_residue`로 거절, 거부 목록(7필드 null 그대로, 원자 이름) = fixture oracle, 작업·이벤트 없음 → 부모 행 포함 자유 일괄: N 4, 필요 4단위·1500초(명세 산술), 잔여 = 예산, 부족분 0, 환불 없음·대기 안내, B1 → 증액 버튼 없음 → 두 번째 승인 없이 실제 일괄 `done`, 정확히 4단위 → 표(상태, B1·B3, 행마다 상태·첫 행 점수 `ROUND_HALF_UP`·점수 대상·이유·재사용·상세) = 저장 요약·행 결과 → 행 번호·후보 id·점수 정렬 양방향, 점수 없는 행 끝, `aria-sort`, 순위 열 없음 → 상세 열기 = 그 행 결과의 M18 상세, 포즈 SDF = 저장 `pose_sdf` → 같은 일괄: N 0, 기존 작업, 새 작업·단위 없음 → 부분 집합 일괄: N 0·필요 60초, 단위 없는 새 작업, 모든 행 "저장된 결과 재사용" → 코어 고정에서 부모 행 해제·비활성(`batch_parent_not_allowed`) → 코어 고정 N 3·잔여 2단위 → 부족 1, 증액 버튼, 시작 막힘(`batch_limit_raise_required`), 증액 = 부족분만(`by: human`, 일괄 맥락, 작업·객체 없음), 다시 확인, 올라간 한도 유지(전역 예산 = 백엔드) → 코어 고정 일괄 "샘플 1(점수 오름차순 나열)" 점수 = 저장값 → 보고서 → 지식 탭 "리간드 도킹 일괄 보고서", Markdown·JSON 다운로드 = 백엔드. run B — 평면 부모 fixture: 부모 행 `ligand_not_3d`(점수 없음, 상세 비활성), 후보 행 점수, 일괄 `complete`, 4단위. run C — 표시된 생성 사슬 후보 집합(59): 첫 행이 끝난 뒤 느린 일괄 취소 → `partial`/`cancelled`, 끝난 행 점수 보관, 진행 중 행 `cancelled`, 나머지 `not_run`(숫자 없음), 남은 작업 프로세스·`qvina2` 없음, 환불 없음 → 50개 체크 뒤 51번째 체크 불가, 시작 전 확인 N = 50 − 재사용 1, 7800초, 부족분, 꽉 찬 일괄 안내, 증액 버튼 제시(누르지 않음), 시작 막힘. run D — 표시된 dry-run run 기록: dry-run 안내, 증액 버튼 없음, 계산 없음. 일괄 영역에 고정 문장·점수 이름 밖의 순위·best·최적·개선·결합 강도·친화도 낱말 없음. `batch-unavailable`: run 없음은 이유만, 환경 없는 백엔드는 `worker_missing` 이유만(숫자·컨트롤·일괄 요청 없음).
- 재현 검사(`B-reproducible`): 흐름의 자유 일괄(부모 + `c_1afb7cd3e603456c`, `c_2c7a25e0cc0ad3f2`, `c_21d6c6f0d07e3759`, seed 42, exhaustiveness 1, num_modes 3, energy_range 3, `ligand_range` 여백 8)을 새 run 두 개에서 API로 다시 돌려 둘 다 `done`/`complete`, run별 handle·입력 해시를 자리표시로 바꾼 요약 SHA-256 `c3cc21a1…b475`가 흐름과 같았고 행 결과·포즈 SDF도 같았다. 저장된 첫 행 qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님): 부모 −12.9, `c_1afb7cd3e603456c` −9.6, `c_2c7a25e0cc0ad3f2` −11.8, `c_21d6c6f0d07e3759` −11.6. 부모 점수는 같은 입력·값의 M18 자유 도킹 첫 모드 점수(−12.9)와 같다. handle은 run마다 다르므로(내용에 그 run의 가져오기·후보 집합 handle이 들어감) run 사이 handle 동일은 주장하지 않는다. 같은 run 안의 같은 입력은 `B-dedupe`가 덮는다.

### 관찰하지 못한 사례
- `B-dry-run-shortfall`: dry-run run은 후보 집합을 가질 수 없어(M17 작업이 계획만 만듦) 부족분이 있는 통과 시작 전 확인에 닿을 수 없다. dry-run 안내와 증액 버튼 없음은 관찰했다. `frontend/tests/docking-batch.test.cjs`, `backend/tests/test_docking_batch_budget.py`가 덮는다.
- `B-null-result`: 이번 유효 입력에서 qvina가 모드 0개를 낸 적이 없다. 위조하지 않았다. 백엔드 일괄 테스트와 프런트 단위 테스트가 덮는다.
- `B-time-limits`: `candidate_timeout`, `time_exhausted`, `worker_failed`, 출력 총량 128 MiB는 몇 시간이 걸리거나 작업 프로세스를 죽여야 한다. `backend/tests/test_docking_batch_worker.py`와 `test_docking_batch_jobs.py`가 테스트 전용으로 줄인 상수로 덮는다(작업 마감·강제 종료·서버 재시작 복구·요약 실패는 작업 경로로, 작업 모듈 자체 전체 시계·출력 총량은 작업 모듈 테스트로만).

### 회귀 (고정 `858bd45`, 같은 빌드 `HZVIvlS1pgVkSE0gAkqD6`, M19 실행기 `--regressions`가 차례로)
- 각자 새 `--root runs/m19-acceptance-20261003-attempt1-m1X-regression`·`--artifacts frontend/tests/offscreen/artifacts/m19-acceptance/attempt1/regressions/m1X`, `--code-root <repo>`, 실행 전후 포트 비어 있음.
- M18 `m18-regression/` → `acceptance: true`, 24/24(`D-zero-modes`는 관찰하지 않음, M18과 같음). M17 `m17-regression/` → 21/21. M16 `m16-regression/`(kbase) → 19/19. M15 `m15-regression/`(kbase) → 14/14. M14 `m14-regression/` → 15/15. M8–M13 `m13-regression/`(`--phases workflows,unavailable,regressions,m11,m12,ledger`) → 사례 28개·필수 단계 17개, M11·M12 하위 실행기 통과.
- 모두 외부 요청 0건, 남은 프로세스 없음. 제공자 호출 필드가 있는 흐름 행은 모두 0회(M13 하위 실행기·회귀 행은 이 필드를 기록하지 않음, M18과 같음).

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다.
- `backend/tests/test_ligand_api.py` 2줄: `/capabilities` 방법 집합 기대에 `ligand_docking_batch`를 더했다.
- `backend/tests/test_m11_job_api.py`: handshake 캐시 테스트가 화학 작업 모듈 argv만 센다(`/capabilities`가 M17·M18·M19 작업 모듈 handshake도 실행해 그룹 단독 실행에서 수가 틀렸음, `b2c6436`).
- `frontend/tests/report-library.test.cjs` 1사례: 새 보고서 종류 이름 "리간드 도킹 일괄 보고서".
- `scripts/test_codex_hooks.py`: Stop 훅 그룹 수(검사 6개)와 일괄 그룹·나머지 그룹 목록 기대.
- 수락 실행기(M13–M18)와 그 흐름 스크립트의 기대는 바뀌지 않았다. M18 도킹·M17 리간드·M14 탭 흐름은 일괄 영역이 붙은 채 그대로 통과했다. 과거 검토 파일·해시는 건드리지 않았다.

## 알려진 한계
- 끝난 행은 작업이 끝나기 전에는 객체로 보이지 않는다(작업 프로세스 그룹 정리 확인 뒤 게시). 진행은 상태 파일 수로만 보인다.
- 재사용 키에 작업 모듈 해시가 들어가므로 M19 전에 만든 M18 결과는 재사용되지 않는다. `docking_worker.py`를 다시 고치면 그 전 결과의 재사용도 끊긴다.
- 일괄이 도는 동안(최대 약 2시간) 그 run의 실행 잠금과 전역 작업 슬롯을 쥔다. 같은 run의 다른 계산·보고서 생성·증액 승인(503 `transient`)과 다른 run의 비싼 작업이 기다린다.
- 활동 시간 예산은 제출 때만 확인한다. 시작까지 시간이 지나 잔여가 줄면 실제 마감(min(잔여, 7800초))이 필요량보다 짧아 일괄이 `time_exhausted`로 끝날 수 있다.
- 멈춘 일괄에서도 재사용 행은 `scored`로 남는다(작업이 계산하지 않았으므로). 그래서 `partial` 요약에도 멈춘 뒤 순서의 재사용 행 점수가 있다.
- 사용량이 한도를 60초 넘게 넘은 run은 한 번의 증액으로 부족분이 0이 되지 않는다(다시 승인).
- 일괄 읽기(목록·상세·작업 진행)는 행마다 다시 검증해 51행 일괄이 여러 개면 느리다.
- 서버 재시작 복구 때 게시하지 못한 행 결과는 잃는다(다시 하면 새로 계산).
- 시작 전 확인의 M18 문장 11(미지정 입체)은 요청만으로 정할 수 없어 결과 요약이 정한다.
- 플랫폼은 macOS arm64·CPython 3.11뿐이다(M18과 같음).

## 대체한 과거 검증 범위
- M19는 공유 소스를 바꿨다: 백엔드 `api/app.py`(작업 제출 상한, 작업 진행 필드·artifacts, capability, 작업 승인 허용 목록, 보고서 분기·목록, 일괄 라우트), `jobs/queue.py`, `jobs/guardian.py`, `runtime/orchestrator.py`, `core/events.py`, `tools/energetic.py`, `config/tools.yaml`, M18 `docking_bundle.py`·`jobs/docking_worker.py`. 프런트 `app/page.tsx`, `DockingPanel.tsx`, `LigandPanel.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, 스타일. Stop 훅 `.codex/hooks/stop.py`.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(1613개, skip 0, M18 도킹 테스트 전부 포함)와 M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `858bd45`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합(방법은 사용자에게 묻는다)과 위 병합 해시 기록. push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): 코드 검토 권고 중 고치지 않은 것(상자 계산 중복, 늦은 신호·남은 작업 폴더, 제출 때만 하는 활동 시간 확인, 멈춘 뒤 재사용 행, 51행 읽기 비용, 2시간 stdout 상한, 비공개 함수 import), 증거 검토 권고, 작업 경로로 끝까지 확인하지 않은 경우(작업 모듈 자체 7200초 시계, 수용체 준비 실패, 출력 총량 정지), 관찰하지 못한 사례, Stop 훅 다섯 그룹과 스레드 넷.
