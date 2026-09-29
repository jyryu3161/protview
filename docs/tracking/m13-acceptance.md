# M13 결정적 로컬 분석 흐름 완료 기록

- 판정: **완료** (2026-09-29)
- 브랜치: `dryforge/m13-workflows` (`phase/m13-analysis-workflows` = main `1e91848`에서 분기). main 병합 `50ca0b4`(2026-09-29).
- 최종 고정 소스: `e83071b`(최종 검토 수정 `86bbff3`). 공유 작업 경로가 바뀌어 전체 게이트와 수락 QA 전체를 이 고정에서 다시 돌렸다(3차 실행). 이전 고정: 제품 `d1eaf48`, 실행기 대장 판정 수정 `af1500b`(증거 커밋 `f630e20`).
- 수락 증거: `docs/qa/m13-workflows-20260929-final/`(최종, 3차 실행). 이력: `docs/qa/m13-workflows-20260929/`(2차 실행, `af1500b`, pass), `docs/qa/m13-workflows-20260929-run1/`(1차 실행, fail 보존, `RUN1-NOTE.md`).
- 옛 단계 폴더 `phases/protview-workflows/`는 index를 만들지 않고 `step0.md`도 그대로 둔다(결정 0018).

## 결과물
- 템플릿·계획 `backend/mw/analysis_plans.py`: 목표 6개(`inspect_ligand`, `measure_atoms`, `compare_structures`, `chemical_interactions`, `find_cavities`, `minimize_protein`), 불변 계획 `analysis_plan@1`(`planner=local_rules@1`, `source=local_rules`, 1–8단계, lane `run_call`·`durable_job`·`report`), 계약 이름 ↔ 실제 도구·프로토콜·보고서 대응 표 한 곳(`OPERATIONS`, `REPORT_TYPES`), 선행 조건 미충족 목록, 호환성 지문. 계획 생성은 과학 호출을 하지 않는다. 계획 JSON 1 MiB, run당 100개(결정 0019).
- 실행 driver `backend/mw/analysis_executions.py`: 실행 기록 `analysis_execution@1`(상태 10개, 단계 상태 8개), 계획 승인·철회, 한 번에 한 단계(다음 단계 실행), 명시적 재시도 1회, 범위 한정 중지, 충돌 구간 1–4 복구, 완료 요약 `workflow_summary@1`과 JSON 다운로드, `analysis_*` 이벤트 16종.
- 내부 실행 연결: `Run.call`(`runtime/orchestrator.py`의 `ExecutionLink`, `execution_call_admitted`·`execution_call_stopped`), `JobQueue`(제출·시도·취소·재시도에 연결 필드, `job_observed`, 소유 작업의 수동 시작·재시도 거절 412 `job_owned_by_analysis_execution`), 보고서 게시(`reports.py`의 `resume_linked_report`, 연산 멱등). 연결 필드가 없는 호출·작업·보고서의 이벤트는 바뀌지 않는다.
- API: `/runs/{id}/analysis/...` 14개 경로, `/capabilities`의 `methods.analysis_workflows`(`docs/contracts.md`).
- 화면: `frontend/src/components/AnalysisWorkflowPanel.tsx`(메인 화면과 화학 작업 화면), 순수 판단 `frontend/src/lib/analysis.ts`, `PocketPanel.tsx`의 흐름 결과 열기·체인 가져오기 prop, `design/components.css`.
- QA 도구: `frontend/tests/offscreen/workflows-flow.cjs`(`npm --prefix frontend run test:offscreen:workflows`), `scripts/m13_offscreen_acceptance.py`, `scripts/test_m13_offscreen_acceptance.py`, M11 수락 실행기의 남은 프로세스 확인을 수락 루트로 좁힘(`881f947`).
- 테스트: `backend/tests/test_analysis_workflows.py`(테스트 함수 66개), `backend/tests/test_execution_links.py`, `frontend/tests/analysis.test.cjs`.

## 진행 중 사용자 결정 (2026-09-29)
- 입력은 화면 선택 가져오기. 원자 두 개·CA 대응표·화학 준비 요청은 기존 화면에서 만든 것만 읽기 전용으로 쓴다.
- 한 번 누르면 한 단계. 여러 단계를 이어 실행하는 버튼·백그라운드 루프는 없다.
- 완료 결과는 요약 화면 + 요약 JSON + 단계별 기존 보고서. 합친 Markdown 보고서는 만들지 않는다.
- 회귀에 M11 수락 실행기 전체를 포함하고, 그 전에 M11 실행기의 남은 프로세스 확인 범위를 고친다.
- 흐름 패널을 화학 작업 화면에도 둔다. 화학 템플릿은 `create_new`·`attach_existing` 두 준비 방식 모두 지원.
- dry-run run의 계획은 미리보기 전용 + 안내 문장(다른 run으로 옮기지 않음).
- 완료 기록은 M12와 같은 방식(결정 0018).
- 계획 크기 한도를 64 KiB에서 1 MiB로(입력을 두 번 저장하지 않음). 계획 생성 요청 본문 1 MiB, 그 밖의 분석 요청 64 KiB(결정 0019).
- 커밋하는 증거는 작은 텍스트만, 큰 증거는 Git 제외 artifacts로 옮기고 해시를 남긴다(결정 0020).

조율 세션이 계약 범위 안에서 정한 세부: 작업 시간 초과는 1회 재시도 가능, 자식 시작 없이 풀린 dispatch 뒤 철회는 `awaiting_approval`로 복귀, 요약의 `last_event_seq`는 마지막 단계 완료 이벤트 순번, 복구 조정은 모든 변경 요청 시작 때, 공유 작업은 관찰만, run 예산 소진이면 아무것도 dispatch하지 않고 `ready`에 머물며 안내, 화학 범주는 고정 5개.

## 커밋

| 작업 | 커밋 |
|---|---|
| 템플릿·계획 컴파일러·계획 API·capability | `8842ebf` (병합 `e704b95`) |
| `Run.call`·작업 큐·보고서 실행 연결 | `29833e5` (병합 `452f803`) |
| M11 수락 실행기 남은 프로세스 확인 범위 | `881f947` (병합 `dff536f`) |
| 실행 driver·복구·실행 API | `a652f31`, `8dddfa6` (병합 `7814524`) |
| 흐름 패널, PocketPanel 열기·체인 prop | `0b3dc26`, `76a9291` (병합 `d3b2401`) |
| 오프스크린 흐름·M13 수락 실행기 | `b3698b3` (병합 `b2927dd`) |
| 검토 수정 | 패널 `c96a3dc`(병합 `7404a7b`), 백엔드 `9b2c7b7`(병합 `65bbf4e`), 남은 항목 `03904ef` |
| 제품 고정 | `d1eaf48` |
| 수락 실행기 대장 판정 수정 | `af1500b` |
| 게이트·수락 QA 증거(1·2차 실행) | `f630e20` |
| 완료 기록·하네스 문서 | `c08e475` |
| 최종 검토 수정(최종 고정) | `86bbff3` (병합 `e83071b`) |
| 최종 게이트·수락 QA 증거(3차 실행) | 이 기록과 같은 커밋 |

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 구현 중 driver 명세 검토: **needs-fix**. 모든 변경 요청이 판단 전에 복구 조정을 하도록 고치고, probe·철회·작업 재시도 규칙을 고쳤다(`8dddfa6`).
- 독립 코드 검토: 막는 지적 1개, 권고 6개. 계약·명세 변경이 필요한 지적은 없었다.

| 구분 | 지적 | 처리 |
|---|---|---|
| 막음 | run 예산 checkpoint로 풀린(release) 연결 호출이 재진행 때 같은 호출 키 제안을 다시 세어 자율 분기 가드를 올림 | 수정: 연결 호출은 제안 전에 활동 시간 예산과 열린 작업을 먼저 확인해, 풀린 호출이 가드를 올리지 않음(`9b2c7b7`) |
| 권고 | `resource_exceeded` 작업 실패를 재시도 가능으로 분류 | 수정: 시간 초과만 1회 재시도 가능, 그 밖의 `resource_exceeded`는 재시도 불가 |
| 권고 | 흐름이 소유한 작업을 `/jobs`에서 수동 시작·재시도 가능 | 수정: 412 `job_owned_by_analysis_execution`. 수동 취소는 허용하고, 흐름은 그 단계를 재시도 불가 `job_cancelled`로 기록 |
| 권고 | 한도(24회·1800초)가 보고서 단계까지 거절 | 수정: 한도는 lane 범위(보고서 단계는 물리 시작이 없어 제외, `03904ef`) |
| 권고 | 실행 목록이 실행마다 이벤트를 다시 읽고, 손상된 실행 하나가 목록 전체를 실패시킴 | 수정: 한 번 읽어 접고, 손상 행은 `error: execution_record_invalid` |
| 권고 | 패널의 busy 해제, 계획 초점, 이벤트 새로고침, 폴링, 안내 문구 | 수정(`c96a3dc`), 보고서 목록 새로고침(`03904ef`) |

- 독립 증거 검토(코드 검토자와 다른 인스턴스): **approve**, 막는 지적 없음, 권고 8개. 권고는 코드를 바꾸지 않고 기록으로 처리했다: 아래 수락 QA의 1차 실행 해석, 대체한 과거 검증 범위, `docs/tracking/findings.md`의 새 항목(상단 예산 카운터 지연, M10 측정 원자 선택 flake, 화학 화면 공동 찾기 다시 열기 미관찰, 스크롤된 결과 프레임), M8–M10 회귀 행의 렌더러 문자열 부재.

- 최종 검토(Opus 5.5, 앞의 검토자들과 다른 인스턴스): 막는 지적 1개와 추가 지적. 모두 `86bbff3`에서 고쳤다. 명세 변경은 없고, `docs/contracts.md`·`docs/business-rules.md`의 작업 API 규칙 문장(412는 소유 실행이 진행 중일 때만)을 새 동작에 맞췄다.

| 구분 | 지적 | 처리 |
|---|---|---|
| 막음 | 흐름이 끝난 뒤에도 흐름 소유 작업의 `/jobs` 수동 시작·재시도가 영구히 412로 막혀, 종료된 실행의 작업을 사람이 다시 돌릴 수 없음 | 수정: 소유 실행이 종료 상태가 아닐 때만 거절(API의 `owner_active` 확인). 실행이 끝나면 기존 수동 재시도 규칙을 따름 |
| 지적 | 한도 소진 실패·`compatibility_changed` 차단 때 열린 소유 작업 dispatch가 queued/claimed로 남음 | 수정: 그 작업을 취소 |
| 지적 | 승인 철회가 실제 자식 시작이 아닌 호출까지 세어, 예산으로 풀린 호출 뒤 `awaiting_approval`로 돌아가지 못함 | 수정: 실제 자식 시작만 셈 |
| 지적 | 다음 단계 실행 요청 중 화면의 busy 상태가 승인 철회 버튼을 막음 | 수정: 승인 철회를 중지처럼 busy 예외로(`frontend/src/lib/analysis.ts`) |
| 지적 | Stop 훅 pytest 그룹에 M13 실행기 단위 테스트가 없음 | 수정: 세 번째 그룹에 추가(`.codex/hooks/stop.py`) |
| 지적 | 수락 실행기가 일부 phase만 돌려도 `acceptance`가 true가 될 수 있고, `--build auto`가 옛 빌드를 재사용할 수 있음 | 수정: 모든 phase가 돌고 통과할 때만 `acceptance: true`, 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용 |

## 최종 전체 게이트 (최종 고정 `e83071b`)

| 명령 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 593 passed, skip 0 (fpocket·ProLIF 작업 환경 설치), 970.8 s |

최종 재검토 권고로 `88796bc`에서 소유 작업 수동 거절 확인이 계획을 읽지 못할 때도 412 `job_owned_by_analysis_execution`을 돌려주게 하고(닫힌 쪽 유지) 테스트 4개를 더했다. 이 변경 뒤 `pytest backend/tests -q -rs` 597개 통과·skip 0, ruff 통과. 바뀐 코드는 계획을 읽지 못하는 오류 경로뿐이라 수락 QA(3차 실행)는 다시 돌리지 않았다.
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 |
| `pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py -q` | 90 passed |
| `node --check` `pocket-flow.cjs`, `workflows-flow.cjs` | 통과 |
| `test:events`, `typecheck`, `build` | 148 passed, 통과, 통과(게이트 빌드 `byXhIMdNy_vdg0qZB-eX7`) |

수락 실행기는 `--build auto`로 같은 소스에서 typecheck → build를 한 번 더 해 소스 도장을 찍은 빌드 `NUugf8EWW7h480ZPwlhqc`로 QA를 돌렸다(`docs/qa/m13-workflows-20260929-final/gate-results.md`).

## 이전 전체 게이트 (제품 고정 `d1eaf48`, 이력)

| 명령 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 589 passed, skip 0 (fpocket·ProLIF 작업 환경 설치), 957.6 s |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 |
| `pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 85 passed |
| `node --check` `pocket-flow.cjs`, `workflows-flow.cjs` | 통과 |
| `test:events`, `typecheck`, `build` | 148 passed, 통과, BUILD_ID `WCnxUsptjGLeenXzwlYhV` |

최종 고정 `af1500b`는 `scripts/`만 바뀌었으므로 `ruff check scripts`, `py_compile`, 게이트 3(85 passed), `pytest scripts/test_m13_offscreen_acceptance.py`(3 passed)만 다시 돌렸다. 나머지 게이트는 `backend/`·`frontend/`가 같으므로 위 결과가 그대로 적용된다(`docs/qa/m13-workflows-20260929/gate-results.md`).

## 수락 QA

### 1차 실행 (`d1eaf48`, 증거 `docs/qa/m13-workflows-20260929-run1/`)
- 판정 **fail**. M13 제품 사례는 모두 통과했다(사례 27/27, S-no-egress 제외).
- 주원인은 M13 수락 실행기였다. M11 대장(`m11_case_ledger@1`)에는 `verdict` 키가 없고 `summary`·`nonLoopbackRequestsTotal`만 있는데 실행기가 `verdict`를 읽어 M11 단계가 fail, 외부 요청 수가 None으로 기록되었고 그 때문에 S-no-egress도 fail이 되었다. M11 실행기 자체는 exit 0, 17/17, 비-loopback 0이었다. `af1500b`에서 대장별 판정 함수(`sub_ledger_verdict`)로 고쳤다.
- `RUN1-NOTE.md`의 첫 문장은 원인을 실행기 하나로 적었지만, M12 하위 대장의 fail은 실행기 오독만이 아니다. M12 실행기의 `regression-m10-measure` 사례 C02-repeat-reverse가 실제로 한 번 실패했다(기준 원자 클릭 3회 모두 Mol* `empty_loci`). M12 실행기 `--only regression-m10-measure` 1회 재실행은 통과했지만(`case-ledger-partial.json`, 수락 아님) 그 재실행은 1차 폴더에 없다. 원인은 확인하지 못했다(`findings.md`).

### 2차 실행 (`af1500b`, 빌드 `WCnxUsptjGLeenXzwlYhV`, 증거 `docs/qa/m13-workflows-20260929/`)
- 판정 **pass**. 단계 17/17, 사례 28/28, 모든 단계 1회 시도, 재실행 없음.
- 흐름 사례(W-*) 9개: `inspect_ligand` 원본·전처리 소스, `find_cavities` 메인(전처리 구조)·화학 작업 화면(화학 구조), `measure_atoms`, `compare_structures`, `minimize_protein`(1UBQ), `chemical_interactions` `create_new`·`attach_existing`. 각 사례는 계획 미리보기 → 실행 만들기 → 계획 승인 → (계산 승인) → 단계 실행 반복 → 결과 열기 → 보고서 다운로드 → 요약·JSON → 다시 열기.
- 상태 사례(S-*) 19개: 사용할 수 없음, 자연어 계획 사용 불가, 선행 조건 미충족(리간드·체인·CA 쌍·화학 요청), 오류, 재시도(표시된 작업 프로세스 SIGKILL fixture), 중지(계획 승인 대기·계산 승인 대기·작업 실행 중), 공유 작업, 이 run에서 이미 계산 승인됨, 경쟁(빠른 두 번 클릭·두 번째 창·run 전환), dry-run, 화학 결과 위치, 외부 요청 0건.
- 회귀: M8 normal, M9 openmm full → scenes core, M10 measure·alignment 통과. M11 수락 실행기 전체(모든 모드) exit 0, 사례 17/17, 29행, 비-loopback 0. M12 수락 실행기 31/31, 외부 요청 0.
- 비-loopback 요청 0건, 제품의 제공자 호출 0회, 남은 프로세스·포트 없음.

### 3차 실행 — 최종 수락 증거 (`e83071b`, 빌드 `NUugf8EWW7h480ZPwlhqc`, 증거 `docs/qa/m13-workflows-20260929-final/`)
- 최종 검토 수정이 공유 작업 경로(`jobs/queue.py`, `api/app.py`의 작업 시작·재시도)를 바꿔 수락 QA 전체를 새 루트 `runs/m13-acceptance-20260929c`에서 다시 돌렸다.
- 판정 **pass**, `acceptance: true`. 단계 17/17, 사례 28/28(W-* 9개, S-* 19개), 모든 단계 1회 시도, 재실행 없음. 수락 시작 때 작업 트리 변경 없음.
- 회귀: M8 normal, M9 openmm full → scenes core, M10 measure·alignment 통과. M11 수락 실행기 전체 exit 0, 사례 17/17, 29행, 비-loopback 0. M12 수락 실행기 31/31, 외부 요청 0. 1차 실행의 M10 측정 원자 선택 flake는 세 M10 measure 실행 모두에서 재발하지 않았다.
- 비-loopback 요청 0건, 제품의 제공자 호출 0회, 남은 프로세스·포트 없음.

## 대체한 과거 검증 범위
- M13이 바꾼 공유 소스: `backend/mw/runtime/orchestrator.py`, `jobs/queue.py`, `core/events.py`, `api/app.py`, 보고서 모듈(`reports.py`, `chemical_reports.py`, `comparison_reports.py`, `method_reports.py`, `openmm_reports.py`, `pocket_reports.py`), `frontend/app/page.tsx`, `ChemicalWorkspace.tsx`, `PocketPanel.tsx`, `src/lib/api.ts`, `contracts.ts`, `pockets.ts`, `design/components.css`.
- 최종 고정 `e83071b`(빌드 `NUugf8EWW7h480ZPwlhqc`)의 3차 실행이 대체한 범위(2차 실행 `af1500b`·`WCnxUsptjGLeenXzwlYhV`와 같은 범위): 전체 백엔드 테스트(593, skip 0), M8 normal-flow, M9 openmm-flow full → scenes-flow core, M10 comparison measure·alignment(M13·M11·M12 실행기에서 세 번), M11 수락 실행기 전체(17/17, 29행: faults, restrictions, 잘못된 입력, replay, 연결 map/replace, 실행 중 취소, 작업 프로세스 없음·버전 불일치 포함), M12 수락 실행기 전체(31/31).
- 다시 돌리지 않은 범위(과거 증거가 공유 소스 변경 이전): scenes-flow의 core 외 모드(faults, replay, identity, projection, readiness, post-races, encoding, restore/detail manual, focus, scope-large, overlap-restore), openmm-flow queued/running-cancel, `openmm-faults`·`openmm-persistence`·`openmm-post-races`·`openmm-retry`·`history-keyboard`·`dry-run.cjs`, 과거 단계 `execute.py --verify`(오래된 상태 그대로), 모든 온라인·제공자 경로(설계상 호출 0회). M8–M10 회귀 행에는 WebGL 렌더러 문자열이 없다.

## 증거 위치
- 커밋(최종): `docs/qa/m13-workflows-20260929-final/`(README, `gate-results.md`, `freeze-manifest.txt`, 사례 대장, 텍스트 증거, `SHA256SUMS`, `binary-artifacts.json`, `ARCHIVED-EVIDENCE.sha256`; 7.4 MB, 427개 파일). 옮긴 텍스트 증거 50개(331,007,991 bytes)는 `frontend/tests/offscreen/artifacts/m13-acceptance/20260929c/export-full/`.
- 커밋(이력): `docs/qa/m13-workflows-20260929/`(2차, README, `gate-results.md`, `freeze-manifest.txt`, 사례 대장, 텍스트 증거, `SHA256SUMS`, `binary-artifacts.json`, `ARCHIVED-EVIDENCE.sha256`; 7.4 MB, 427개 파일), `docs/qa/m13-workflows-20260929-run1/`(7.3 MB, `RUN1-NOTE.md`).
- Git 제외: 스크린숏·paint 프레임·다운로드 원본은 `frontend/tests/offscreen/artifacts/m13-acceptance/20260929c/`(3차, 최종), `.../20260929b/`(2차), `.../20260929/`(1차). 실행마다 256 KiB를 넘는 텍스트 증거 50개(2차 331,398,166 bytes, 1차 330,975,167 bytes; M11 하위 실행기의 `chemical-evidence.json`은 최대 약 62 MB)를 각 폴더의 `export-full/`로 옮겼다. 대장(`case-ledger*.json`, `ledger-row.json`)은 크기와 관계없이 커밋했다. 옮긴 파일의 해시는 `ARCHIVED-EVIDENCE.sha256`과 `SHA256SUMS`에, 확인 명령은 각 README 끝 절에 있다(결정 0020).
- QA runs 루트: `runs/m13-acceptance-20260929c`(3차, 최종), `runs/m13-acceptance-20260929b`(2차). Git 제외.
