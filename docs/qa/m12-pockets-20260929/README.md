# M12 포켓 후보 수락 QA (2026-09-29)

## 대상 소스
- 소스 고정: `9e4edcb` (브랜치 `dryforge/m12-pockets`). 고정 뒤 바뀐 것은 수락 실행기 `scripts/m12_offscreen_acceptance.py`의 남은 프로세스 확인 범위(`1eb88a1`)뿐이며, 그 뒤 수락 QA 전체를 다시 실행했다(`acceptance-r2`).
- 엔진: fpocket 4.2.3 conda-forge `osx-arm64` `hb88c64c_2`, 실행 파일 SHA-256 `a79058e4…2894`(`.deps/fpocket/env`). ProLIF 작업 환경 `.deps/prolif/venv-locked`.

## 게이트 (고정 소스 `9e4edcb`, 프로젝트 루트)
| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | 497 passed, 0 skipped (13분 56초) |
| `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 (`1eb88a1`에서 다시 통과) |
| `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 85 passed (`1eb88a1`에서 다시 통과) |
| `npm --prefix frontend run test:events` | 106 passed, 0 failed, 0 skipped |
| `npm --prefix frontend run typecheck` → `npm --prefix frontend run build` (순서대로) | 통과 / 통과 |
| `node --check frontend/tests/offscreen/pocket-flow.cjs` | 통과 |

## 수락 QA
명령: `.venv/bin/python scripts/m12_offscreen_acceptance.py --root runs/m12-acceptance-20260929-r2 --artifacts frontend/tests/offscreen/artifacts/m12-acceptance/20260929-r2`

- `acceptance-r2/`: 판정 **pass**. 31개 단계 전부 통과(포켓 13개 흐름, M8·M9·M10·M11 회귀 12개, events-only 복구 4개, 엔진 없음·해시 불일치 2개), 남은 프로세스 없음, loopback이 아닌 요청 0건. 요약은 `case-ledger.json`, 단계 순서는 `runner-summary.jsonl`.
- `attempt-1-leftover-check-fail/`: 첫 번째 전체 실행. 기능 단계 31개는 모두 통과했지만 `leftover-processes`가 실패로 기록됐다. 잡힌 프로세스(guardian 1개, ProLIF 작업 2개)는 같은 시각에 돌던 Stop 훅 pytest의 것이었다. 이 실행의 작업 16개는 모두 종료 상태이고, 프로세스를 띄운 13개는 정리 완료가 기록됐다. 확인 방식이 이 컴퓨터의 같은 이름 프로세스를 모두 잡았기 때문이며, 확인 범위를 수락 루트로 좁힌 뒤 전체를 다시 실행했다. 실패 기록은 그대로 둔다.

## 이 폴더에 있는 것과 없는 것
- 있는 것: 각 단계의 사례 행(`ledger-row.json`), 포켓 증거 요약(`pocket-evidence.json`), 64 KiB 이하 텍스트 증거, 전체 텍스트 증거의 SHA-256 목록(`SHA256SUMS`), 스크린숏·paint 프레임·다운로드 원본의 크기와 SHA-256(`binary-artifacts.json`).
- 없는 것: 큰 텍스트 증거(흐름 jsonl, 화학 증거 전체 등)와 이진 파일. 로컬 경로를 `<repo>`·`<home>`으로 바꾼 전체 사본이 Git 제외 폴더 `frontend/tests/offscreen/artifacts/m12-acceptance/export-20260929/`에 있고, 해시는 `SHA256SUMS`와 대조할 수 있다.
- 과학 값은 모두 실제 fpocket 실행 결과다. 파생 fixture(`derived_1hsg_first10_fixture.cif`)와 합성 입력(`scripts/m12_qa_inputs.py`)은 출처에 표시되어 있고 실험 증거가 아니다.
