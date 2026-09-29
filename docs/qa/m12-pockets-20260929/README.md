# M12 포켓 후보 수락 QA (2026-09-29)

## 대상 소스
- 소스 고정: `9e4edcb` (브랜치 `dryforge/m12-pockets`). 고정 뒤 바뀐 것은 수락 실행기 `scripts/m12_offscreen_acceptance.py`의 남은 프로세스 확인 범위(`1eb88a1`)뿐이며, 그 뒤 수락 QA 전체를 다시 실행했다(`acceptance-r2`).
- 엔진: fpocket 4.2.3 conda-forge `osx-arm64` `hb88c64c_2`, 실행 파일 SHA-256 `a79058e4…2894`(`.deps/fpocket/env`). ProLIF 작업 환경 `.deps/prolif/venv-locked`.

## 게이트 (고정 소스 `9e4edcb`, 프로젝트 루트)
| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | 497 passed, 0 skipped (13분 56초) |
| `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 (`9e4edcb`, 그리고 증거 커밋 뒤 다시 실행: `gates/ruff.txt`) |
| `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 85 passed (`9e4edcb`, 그리고 증거 커밋 뒤 다시 실행: `gates/scripts-pytest.txt`) |
| `npm --prefix frontend run test:events` | 106 passed, 0 failed, 0 skipped |
| `npm --prefix frontend run typecheck` → `npm --prefix frontend run build` (순서대로) | 통과 / 통과 |
| `node --check frontend/tests/offscreen/pocket-flow.cjs` | 통과 (`gates/node-check.txt`) |

백엔드 전체 테스트와 순수 로직 테스트의 원래 출력 끝부분은 `gates/backend-pytest.txt`, `gates/test-events.txt`에 있다. typecheck·build는 종료 코드 0을 확인했으나 출력 전체는 남기지 않았다.

## 수락 QA
명령: `.venv/bin/python scripts/m12_offscreen_acceptance.py --root runs/m12-acceptance-20260929-r2 --artifacts frontend/tests/offscreen/artifacts/m12-acceptance/20260929-r2`

- `acceptance-r2/`: 판정 **pass**. 31개 단계 전부 통과(포켓 13개 흐름, M8·M9·M10·M11 회귀 12개, events-only 복구 4개, 엔진 없음·해시 불일치 2개), 남은 프로세스 없음, loopback이 아닌 요청 0건. 요약은 `case-ledger.json`, 단계 순서는 `runner-summary.jsonl`.
- `attempt-1-leftover-check-fail/`: 첫 번째 전체 실행. 기능 단계 31개는 모두 통과했지만 `leftover-processes`가 실패로 기록됐다. 잡힌 프로세스(guardian 1개, ProLIF 작업 2개)는 이 실행의 것이 아니다: 세 PID는 어떤 실행 이벤트 기록에도 없고, 마지막 작업 실행(PID 1554) 뒤의 단계들은 작업을 시작하지 않는다. 같은 시각에 돌던 Stop 훅 pytest의 것으로 추정한다(작업 폴더를 기록하지 않아 직접 증명은 못 함). 이 실행의 작업 16개는 모두 종료 상태이고, 프로세스를 띄운 13개는 정리 완료가 기록됐다. 확인 방식이 이 컴퓨터의 같은 이름 프로세스를 모두 잡았기 때문이며, 확인 범위를 수락 루트로 좁힌 뒤 전체를 다시 실행했다. 실패 기록은 그대로 둔다.

## 검증하지 못한 것 (독립 증거 검토에서 확인)
- 최소화 구조에서 포켓을 선택했을 때 원래 복합체의 접촉 행이 숨는지: 최소화 가능한 공개 fixture(1UBQ)에 리간드가 없어 실제 화면에서 확인하지 못했다(`minimized-source` 증거에 `not exercised`로 기록). 범례·초점·이전 보기 복귀는 확인했고, 접촉 행을 숨기는 조건은 범례와 같은 상태 값이다.
- M11 회귀는 일부 모드만 다시 돌렸다(capability-ready, empty, prepare-only, detect-controls, job-controls, running-cancel, reopen, 그리고 m11-create). 연결(attach) 두 모드, restrictions, faults, 잘못된 입력, M11 replay, 작업 프로세스 없음·버전 불일치, 화학 구조 표시 중 M9 저장 보기 복원(H13)은 다시 돌리지 않았다. `ChemicalWorkspace.tsx` 변경은 포켓 패널과 주석·오버레이 상호 배타만 더했다.
- M8·M9·M10 회귀 행에는 WebGL 렌더러 문자열이 없다(옛 하네스가 기록하지 않음). offscreen·하드웨어 가속·paint·첫 paint 바이트·외부 요청 0건은 기록되어 있다.
- 화면에서의 취소는 승인 대기 중인 작업으로 확인했다. 실행 중인 fpocket 취소는 백엔드 테스트로 확인했다(1HSG 실행이 너무 빨리 끝남).

## 이 폴더에 있는 것과 없는 것
- 있는 것: 각 단계의 사례 행(`ledger-row.json`), 포켓 증거 요약(`pocket-evidence.json`), 64 KiB 이하 텍스트 증거, 전체 텍스트 증거의 SHA-256 목록(`SHA256SUMS`), 스크린숏·paint 프레임·다운로드 원본의 크기와 SHA-256(`binary-artifacts.json`).
- 없는 것: 큰 텍스트 증거(흐름 jsonl, 화학 증거 전체 등)와 이진 파일. 로컬 경로를 `<repo>`·`<home>`으로 바꾼 전체 사본이 Git 제외 폴더 `frontend/tests/offscreen/artifacts/m12-acceptance/export-20260929/`에 있고, 해시는 `SHA256SUMS`와 대조할 수 있다.
- 과학 값은 모두 실제 fpocket 실행 결과다. 파생 fixture(`derived_1hsg_first10_fixture.cif`)와 합성 입력(`scripts/m12_qa_inputs.py`)은 출처에 표시되어 있고 실험 증거가 아니다.
