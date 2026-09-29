# M13 최종 게이트·수락 QA 결과 (최종 검토 수정 뒤)

## 소스 고정

- 최종 고정: `dryforge/m13-workflows` HEAD `e83071b7e74b42e34a64595f41f66fcabbfa68b5` (최종 검토 수정 `86bbff3`, 병합 `e83071b`). 게이트 시작 전·수락 시작 때 `git status --porcelain` 비어 있음.
- 이전 수락 고정 `af1500b` 대비 바뀐 소스·문서 목록과 main 대비 파일 SHA-256은 `freeze-manifest.txt`(커밋된 `docs/qa/` 증거 폴더는 목록에서 뺐다). 공유 작업 경로(`backend/mw/jobs/queue.py`, `backend/mw/api/app.py` 작업 시작·재시도)가 바뀌어 게이트 8개와 수락 QA 전체를 다시 돌렸다.

## 게이트 (명세 12절, 8개)

2026-09-29, 프로젝트 루트, 8000·3000 포트 비움, 다른 pytest·서비스 동시 실행 없음, typecheck → build 순서.

| # | 명령 | exit | 결과 |
|---|---|---|---|
| 1 | `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 593 passed, 0 skipped, 1 warning (StarletteDeprecationWarning), 970.8 s |
| 2 | `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 3 | `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py -q` | 0 | 90 passed |
| 4 | `node --check frontend/tests/offscreen/pocket-flow.cjs` | 0 | 출력 없음 |
| 5 | `node --check frontend/tests/offscreen/workflows-flow.cjs` | 0 | 출력 없음 |
| 6 | `npm --prefix frontend run test:events` | 0 | pass 148, fail 0, skipped 0 |
| 7 | `npm --prefix frontend run typecheck` | 0 | tsc --noEmit 오류 없음 |
| 8 | `npm --prefix frontend run build` | 0 | BUILD_ID `byXhIMdNy_vdg0qZB-eX7` |

게이트 빌드에는 수락 실행기의 소스 도장이 없으므로 수락 실행기가 `--build auto`로 같은 소스에서 typecheck → build를 한 번 더 했다(`frontend-typecheck`, `frontend-build` pass). 수락 QA는 그 빌드 `NUugf8EWW7h480ZPwlhqc`(`buildCurrentWithSource: true`)를 사용했다.

## 수락 QA

```bash
.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-20260929c \
    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/20260929c \
    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-20260929-final
```

exit 0, case-ledger verdict **pass**, acceptance true. gitHead `e83071b`, 작업 트리 변경 없음.

| phase | 결과 |
|---|---|
| workflows | pass: main, m10, race, minimize, chemical-create, attach-setup, chemical-attach, chemical-error, dry-run |
| unavailable | pass |
| regressions | pass: M8 normal, M9 openmm full → scenes core, M10 measure, M10 alignment |
| m11 | pass: `scripts/m11_offscreen_acceptance.py` 전체, exit 0, 사례 17/17, 29행, 비-loopback 합계 0, 측정 불명 행 없음 |
| m12 | pass: `scripts/m12_offscreen_acceptance.py` 전체, 단계 31/31, 외부 요청 합계 0, 측정 불명 행 없음 |
| ledger | pass: 단계 17/17, 사례 28/28(S-no-egress 포함), 남은 프로세스 없음 |

- 재실행 없음. 모든 단계 시도 1회. M10 측정 원자 선택 flake(1차 실행)는 M13·M11·M12 실행기의 세 M10 measure 실행 모두에서 재발하지 않았다.

## 외부 요청·남은 프로세스·증거 위생

- 모든 M13 흐름 행 externalRequestCount 0, providerCallsZero true. 회귀 행 externalRequestCount 0(제공자 호출은 측정 대상 아님). M11·M12 하위 실행기 행 externalRequestCount 0(각 대장 측정값). 합계 0.
- 실행기 leftover-processes pass. 종료 뒤 `lsof`로 8000·3000 리스너 없음 확인.
- 내보낸 텍스트 증거에 절대 경로·자격 증명 문자열 없음(grep 0건). 스크린숏·paint·다운로드 원본은 Git 제외 artifacts 폴더에만 있고 `binary-artifacts.json`에 SHA-256만 기록.

## 커밋한 증거 범위

결정 0020에 따라 256 KiB를 넘는 텍스트 증거 50개(대장 제외, 331,007,991 bytes)는 `<repo>/frontend/tests/offscreen/artifacts/m13-acceptance/20260929c/export-full/`로 옮겼다. 목록·크기·SHA-256은 `README.md` 끝 절과 `ARCHIVED-EVIDENCE.sha256`, 원래 해시는 `SHA256SUMS`에 있다.
