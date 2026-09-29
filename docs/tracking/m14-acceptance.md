# M14 탭 4개 골격과 기존 화면 이관 완료 기록

- 판정: **완료** (2026-09-30)
- 브랜치: `dryforge/m14-tabs` (`phase/m14-tab-skeleton` = main `36b5679`에서 분기). 시작 전에 M13을 main에 병합했다(`50ca0b4`, 기록 커밋 `36b5679`). M14 main 병합 `da5e4bc`(2026-09-30).
- 고정 소스: `4501aa1`. 게이트·수락 QA·회귀를 모두 이 고정에서 돌렸다. 증거 커밋 `fb47056`(매니페스트 README 해시 갱신 `c661502`).
- 수락 증거: `docs/qa/m14-tabs-20260930/`(M14 수락), `docs/qa/m14-tabs-20260930/m13-regression/`(M8–M13 회귀). 큰 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다.
- 백엔드 변경 없음(`git diff 36b5679..4501aa1 -- backend/`가 비어 있음). 외부 요청 0건, OpenRouter 호출 0회.

## 결과물
- 최상위 탭 `frontend/src/components/WorkspaceTabs.tsx`와 순수 정의 `frontend/src/lib/workspace-tabs.ts`: 탭 4개(`구조 분석`, `단백질 공학`, `리간드 설계·탐색`, `지식·보고서`), 기본 구조 분석, 주소 불변, `tablist`/`tab`/`tabpanel`. 같은 줄에 현재 run(`.mw-app-run`)과 예산(`.mw-app-budget`, 기존 `.mw-top-budget`과 별개).
- 구조 분석 탭: 기존 메인 화면과 화학 작업 화면을 그대로 담는다. 화학 화면의 조기 반환을 같은 자리의 삼항으로 바꿨고 key·진입·퇴장 규칙은 그대로다. 다른 탭이 보일 때 구조 분석 패널은 언마운트하지 않고 `visibility:hidden`·`pointer-events:none`·`inert`로 숨긴다(`display:none`이 아니므로 Mol* 캔버스 크기가 0이 되지 않아 복귀 뒤 크기 재계산이 필요 없다). `WorkspaceShell` 높이는 `100vh`에서 `100%`로.
- 전역 예산: 새 주기적 폴링 없이, 탭 전환 때와 화학 화면의 `onObjectsChanged` 때 페이지가 `/budget`을 한 번 읽는다(`refreshGlobalBudget`, OpenMM 예산 읽기와 같은 요청 순번 공유).
- 기능 없는 탭: 단백질 공학(M20·M21), 리간드 설계·탐색(M17·M18, M11은 구조 분석 탭 안내), 지식(M15)에 "사용할 수 없음", 이유, 여는 단계만. 선택된 동안에만 렌더링한다.
- 보고서 목록 `frontend/src/components/ReportLibraryPanel.tsx`와 순수 로직 `frontend/src/lib/report-library.ts`: 저장된 보고서(`/reports` 전체), 저장된 그림(`/viewer/figures` 끝까지, 서버 순서), 완료된 흐름 요약(`status=complete`이고 `summary_handle`이 있으며 `error`가 없는 행). 목록별 독립 오류와 다시 시도, 보고서 Markdown 원문 `<pre>`, PNG 이미지, 요약 JSON, 기존 다운로드 링크. run·요청 순번으로 늦은 응답을 버린다. 백엔드 API는 새로 만들지 않았다.
- 스타일: `design/components.css`(`mw-app-*`, `mw-library-*`)와 생성물 `frontend/src/design/components.css`.
- QA 도구: `frontend/tests/offscreen/tabs-flow.cjs`(`test:offscreen:tabs`, 모드 `main`·`chemical`), `scripts/m14_offscreen_acceptance.py`, `scripts/test_m14_offscreen_acceptance.py`(Stop 훅 세 번째 pytest 그룹에 추가, `scripts/test_codex_hooks.py`의 기대 목록 한 줄).
- 테스트: `frontend/tests/workspace-tabs.test.cjs`, `frontend/tests/report-library.test.cjs`.

## 진행 중 사용자 결정 (2026-09-29)
- M13을 main에 병합한 뒤 M14를 시작한다. push는 요청할 때만.
- 기능 없는 탭은 누를 수 있게 두고 사용할 수 없음 + 이유 + 여는 단계만 보여 준다.
- 지식·보고서 탭은 run 전체 보고서·그림·흐름 요약 목록. 내용 보기와 다운로드만, 구조 분석으로 건너가 여는 기능 없음. 보고서는 원문 텍스트. 흐름은 완료된 요약만.
- 탭을 바꿔도 구조 분석 상태 유지(한 페이지 안의 탭, 주소 불변). 화학 작업 화면은 구조 분석 탭 안에서 그대로.
- 공용화는 지금 공유하는 것만(결정 0021). run 전체 작업 목록 없음, 다른 탭 알림 없음, run 선택은 구조 분석에만.

## 커밋

| 작업 | 커밋 |
|---|---|
| M13 main 병합, 병합 기록 | `50ca0b4`, `36b5679` (main) |
| 보고서 목록 순수 로직 | `4bc6fb0` (병합 `feeb47a`) |
| 탭 막대·전역 상단 줄·구조 분석 탭 이관·기능 없는 탭 | `8d57af3` (병합 `0e958f0`) |
| 보고서 목록 화면 | `b3d532e` (병합 `8916ccc`) |
| 보고서 화면 연결·스타일 | `21b3ff9` |
| 오프스크린 탭 흐름·M14 수락 실행기 | `c4962e2` (병합 `d3e5914`) |
| 코드 검토 권고 반영(탭 전환 예산 읽기 확인, 소스 도장 빌드 필수) = 고정 소스 | `4501aa1` |
| 게이트·수락 QA·회귀 증거 | `fb47056`, `c661502` |
| 완료 기록·프로젝트 문서 갱신 | 이 기록과 같은 커밋 |

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토: **approved**, 막는 지적 없음, 권고 6개.

| 권고 | 처리 |
|---|---|
| 늦은 응답 사례는 패널 언마운트 + 요청 중단 경로를 시험한다(리듀서의 마운트 중 run 전환 경로는 UI로 도달 불가, 단위 테스트만) | 기록(아래 수락 QA 해석) |
| 예산 사례가 탭 전환 때의 `/budget` 읽기를 따로 확인하지 않음 | 수정(`4501aa1`): 탭 클릭 뒤 `GET /runs/{id}/budget`를 요청 기록에서 확인 |
| 전역 예산 읽기가 실패하면 앞선 OpenMM 예산 읽기까지 밀려 값이 다음 읽기까지 멈춤 | 기록(`docs/tracking/findings.md`) |
| 수락 판정이 소스 도장 빌드를 요구하지 않음 | 수정(`4501aa1`): `acceptance`는 `buildCurrentWithSource`가 true일 때만 |
| 대기 중 저장 보기 복원이 탭 왕복을 견디는지 직접 확인하지 않음 | 수용(M14 수락 사례 범위 밖, 탭 전환이 복원 취소 경로를 부르지 않음은 코드 검토로 확인) |
| 탭 사이 화살표 키 이동 없음 | 수용(M14 범위 밖) |

- 독립 증거 검토(코드 검토자와 다른 인스턴스): **approve**, 막는 지적 없음, 권고 6개.

| 권고 | 처리 |
|---|---|
| 두 증거 폴더의 `SHA256SUMS`에서 README 줄이 결정 0020 절 추가 뒤 오래됨 | 수정(`c661502`) |
| 늦은 응답 사례의 실제 기제(언마운트 + 중단), R04의 `delivered: true`는 Playwright fulfill 호출 성공일 뿐 | 기록(아래) |
| 기능 없는 탭의 무요청 확인은 단백질 공학·리간드 설계·탐색만. 지식·보고서는 목록이 요청하므로 안내·컨트롤 없음만 확인. 탭 클릭의 `/budget` 읽기는 기준선 경로라 허용 | 기록(아래) |
| 화학 화면 예산 단계의 통과 행에 `refreshRead` 값이 남지 않음(단계는 읽기가 없으면 실패하며 요청 기록에 해당 GET이 있음) | 기록 |
| 화학 왕복 비교에서 뷰어 세션·선택은 양쪽 모두 null이라, 유지는 handle·결과 행·카메라·작업·paint로 확인 | 기록 |
| 게이트 빌드와 수락 빌드가 같은 소스의 다른 빌드 | 기록(아래) |

## 게이트 (고정 소스 `4501aa1`, `docs/qa/m14-tabs-20260930/gate-results.txt`)

| 명령 | 결과 |
|---|---|
| `git diff 36b5679..HEAD -- backend/` | 0줄 |
| `npm --prefix frontend run test:events` | exit 0, 168 pass, 0 fail |
| `npm --prefix frontend run typecheck` → `build` | exit 0 → exit 0 (BUILD_ID `p77m8rQ1Ft43uHAK9vXUz`) |
| `ruff check scripts .codex/hooks` | exit 0 |
| `pytest scripts/test_m14_offscreen_acceptance.py scripts/test_m13_offscreen_acceptance.py scripts/test_codex_hooks.py -q` | 37 passed |
| `node --check` `tabs-flow.cjs`, `workflows-flow.cjs` | exit 0 |

백엔드가 바뀌지 않으면 전체 백엔드 pytest는 필수 게이트가 아니라고 M14 착수 때 정했으므로 돌리지 않았다(M13 기준 597개 통과, skip 0).

## 수락 QA

### M14 수락 (`scripts/m14_offscreen_acceptance.py`, 2026-09-29 15:06–15:08 UTC)
- 명령: `.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m14-acceptance-20260930 --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/20260930 --out docs/qa/m14-tabs-20260930`
- 빌드: 실행기가 같은 소스로 다시 만든 `jaO5G-sFo9B5sB5owJLyf`(소스 도장 일치, gitHead `4501aa1`). Electron 44.4.5, Chrome 152, WebGL 2.0(ANGLE Metal), `isOffscreen()===true`.
- 결과: `verdict: pass`, `acceptance: true`, 사례 15/15 통과(T-tabs, T-structure-state, T-running-job, T-chemical-preserved, T-unavailable, T-reports-list, T-reports-content, T-reports-fault, T-no-run, T-run-switch, T-late-response, T-global-run, T-budget-main, T-budget-chemical, S-no-egress), 첫 시도. 외부 요청 0건, 제공자 호출 0회(run 3개), 남은 프로세스 없음.
- run: A `run_e8c684a339b94ecba3bab0003ea80659`(1HSG), B `run_96ea9f9a2b0243d685c122a8ef93f4d3`(1UBQ OpenMM), C `run_e0b0cab0a1eb44ffb409f2be7100b6f8`(화학).
- 관찰 값 요약: 구조 상태 왕복 전후 소스 handle·표현·선택(7필드)·카메라·세션·generation이 같고 복귀 paint가 새로 찍혀 비어 있지 않음(표준편차 약 27). 다른 탭에 있는 10.4초 동안 작업 폴링 10회로 running → done. 보고서 탭에 상호작용 보고서, `interface_sasa` 방법 보고서, 그림 1개, 완료 요약 1개가 보이고 취소된 흐름은 없음. 다운로드 7개의 SHA-256이 백엔드 바이트와 같음. 보고서 목록 fault(표시된 fixture, 422)는 그 목록에만 오류와 다시 시도를 보였고 그림·요약·구조 분석 화면은 정상. 탭 클릭 38 ms 뒤 `/budget` GET, 전역 예산 1/8 = 백엔드 1/8(메인), 2/8 = 2/8(화학).
- 해석:
  - 늦은 응답(R02–R04): 보고서 패널은 탭이 숨겨지면 언마운트되고 진행 중 요청을 중단한다. run 전환은 구조 분석 탭에서만 가능하므로 실제 UI에서 도달하는 경로는 이것뿐이며, 사례는 붙잡아 둔 run B 응답이 run A 화면에 나타나지 않고 선택이 남지 않음을 확인한다. 기록의 `delivered: true`는 Playwright의 fulfill 호출이 성공했다는 뜻이지 페이지가 응답을 받았다는 뜻이 아니다. 마운트된 채 run이 바뀌는 리듀서 경로는 `report-library.test.cjs`가 다룬다.
  - 기능 없는 탭의 무요청 확인은 단백질 공학·리간드 설계·탐색에 적용했다. 지식·보고서는 보고서 목록이 설계대로 요청하므로 지식 안내의 문구·이유·단계·컨트롤 없음만 확인했다. 탭 클릭이 일으키는 전역 `/budget` 읽기는 전환 전에도 있던 경로라 기준선에 포함된다.

### M8–M13 회귀 (`scripts/m13_offscreen_acceptance.py` 전체, 15:13–15:49 UTC)
- 명령: `.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m14-m13-regression-20260930 --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/20260930-m13-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m14-tabs-20260930/m13-regression`
- 결과: `acceptance: true`, 필수 단계 17개·사례 28개 통과(첫 시도), M8 normal·M9 OpenMM·scenes core·M10 measure/alignment, M11 수락 실행기 17/17, M12 수락 실행기 통과. 같은 빌드 `jaO5G-sFo9B5sB5owJLyf` 재사용(소스 도장 일치). 외부 요청 0건, 남은 프로세스 없음.
- 큰 텍스트 증거 50개(331,447,219 bytes)는 `frontend/tests/offscreen/artifacts/m14-acceptance/20260930-m13-regression/export-full/`로 옮겼다(`ARCHIVED-EVIDENCE.sha256`). M14 수락 폴더에서도 1개(1,191,726 bytes)를 `.../20260930/export-full/`로 옮겼다.

### 기존 검사 스크립트
기존 `frontend/tests/offscreen/*.cjs`와 M11·M12·M13 수락 실행기는 고치지 않고 통과했다. 기존 파일 수정은 Stop 훅 세 번째 그룹에 M14 실행기 테스트를 넣은 `.codex/hooks/stop.py` 한 줄과, 그 목록을 고정하는 `scripts/test_codex_hooks.py` 한 줄뿐이다. 과거 검토 파일·해시는 건드리지 않았다.

## 대체한 과거 검증 범위
M14가 공유 화면 코드(`page.tsx`, `shell.tsx`)를 바꿨으므로, M8–M13의 현재 기준 화면 검증은 위 M8–M13 회귀(2026-09-29 15:13–15:49 UTC, 고정 `4501aa1`)로 대체한다. M13 수락 실행기가 돌리지 않는 과거 범위(M8 keyboard·dry-run 등 개별 흐름)는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.
