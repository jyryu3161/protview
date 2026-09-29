# M13 T8 전체 게이트·수락 QA 결과

## 소스 고정

- 1차 고정: `d1eaf48243e26301528c7593780c6ad2b630583b`. 이 고정에서 게이트 8개를 모두 돌렸고, 수락 1차 실행은 실행기 결함으로 fail이었다(`../m13-workflows-20260929-run1/`, `RUN1-NOTE.md`).
- 최종 고정: `af1500b60f93a4fa24865f0e059ad2abe70b8126` ("Fix M13 acceptance runner reading of M11/M12 sub-runner ledgers"). main 대비 바뀐 파일 SHA-256은 `freeze-manifest.txt`.
- 두 고정 사이의 차이(`git diff --stat d1eaf48 af1500b`): `scripts/m13_offscreen_acceptance.py`(+24 −2, sub-runner ledger 판정 함수 `sub_ledger_verdict`), `scripts/test_m13_offscreen_acceptance.py`(새 파일, 35줄). 제품 코드(`backend/mw`, `frontend/`)와 오프스크린 하네스는 바뀌지 않았다.

## 게이트 (명세 12절, 8개) — 1차 고정 `d1eaf48`에서 실행

2026-09-29, 프로젝트 루트, 8000·3000 포트 비움, 다른 pytest·서비스 동시 실행 없음, typecheck → build 순서.

| # | 명령 | exit | 결과 |
|---|---|---|---|
| 1 | `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 589 passed, 0 skipped, 1 warning (StarletteDeprecationWarning), 957.6 s |
| 2 | `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 3 | `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 0 | 85 passed |
| 4 | `node --check frontend/tests/offscreen/pocket-flow.cjs` | 0 | 출력 없음 |
| 5 | `node --check frontend/tests/offscreen/workflows-flow.cjs` | 0 | 출력 없음 |
| 6 | `npm --prefix frontend run test:events` | 0 | pass 148, fail 0, skipped 0 |
| 7 | `npm --prefix frontend run typecheck` | 0 | tsc --noEmit 오류 없음 |
| 8 | `npm --prefix frontend run build` | 0 | BUILD_ID `WCnxUsptjGLeenXzwlYhV` (두 수락 실행 모두 이 빌드 사용) |

## 고정 변경 뒤 다시 돌린 게이트 — 최종 고정 `af1500b`

바뀐 파일이 `scripts/`의 수락 실행기와 그 테스트뿐이므로 영향을 받는 게이트만 다시 돌렸다. 게이트 1, 4–8은 `backend/mw`·`backend/tests`·`frontend/`가 두 고정 사이에 같으므로 1차 결과가 그대로 적용된다.

| 명령 | exit | 결과 |
|---|---|---|
| `.venv/bin/python -m ruff check scripts` | 0 | All checks passed |
| `.venv/bin/python -m py_compile scripts/m13_offscreen_acceptance.py` | 0 | — |
| `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` (게이트 3) | 0 | 85 passed |
| `.venv/bin/python -m pytest scripts/test_m13_offscreen_acceptance.py -q` (새 단위 확인) | 0 | 3 passed |

## 수락 QA (최종, 2차 실행)

```bash
.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-20260929b \
    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/20260929b \
    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-20260929
```

exit 0, case-ledger verdict **pass** (acceptance true). gitHead `af1500b`, 작업 트리의 유일한 변경은 추적되지 않은 1차 실행 증거 폴더 `docs/qa/m13-workflows-20260929-run1/`.

| phase | 결과 |
|---|---|
| workflows | pass: main, m10, race, minimize, chemical-create, attach-setup, chemical-attach, chemical-error, dry-run |
| unavailable | pass |
| regressions | pass: M8 normal, M9 openmm full → scenes core, M10 measure, M10 alignment |
| m11 | pass: `scripts/m11_offscreen_acceptance.py` 전체, exit 0, 사례 17/17 pass, 29행, 비-loopback 합계 0, 측정 불명 행 없음 |
| m12 | pass: `scripts/m12_offscreen_acceptance.py` 전체, 단계 31/31 pass, 외부 요청 합계 0, 측정 불명 행 없음 |
| ledger | pass: 단계 17/17, 사례 28/28(S-no-egress 포함), 남은 프로세스 없음 |

- 재실행 없음. 모든 단계 시도 1회. 1차 실행에서 한 번 실패했던 M12 실행기의 `regression-m10-measure`(C02-repeat-reverse, Mol* `empty_loci`)는 이번에 재발하지 않았다. 원인은 확인하지 않았다.
- 1차 실행 증거는 `../m13-workflows-20260929-run1/`에 그대로 보존했다.

## 외부 요청·남은 프로세스·증거 위생

- 모든 M13 흐름 행 externalRequestCount 0, providerCallsZero true. 회귀 행 externalRequestCount 0(제공자 호출은 측정 대상 아님). M11·M12 sub-runner 행 externalRequestCount 0(각 ledger 측정값). 합계 0.
- 실행기 leftover-processes pass. 종료 뒤 `lsof`로 8000·3000 리스너 없음 확인.
- 내보낸 텍스트 증거에 `/Users/`·`/private/`·자격 증명 문자열 없음(grep 0건). 스크린숏·paint·다운로드 원본은 Git 제외 artifacts 폴더에만 있고 `binary-artifacts.json`에 SHA-256만 기록.

## 커밋한 증거 범위

사용자 결정(2026-09-29)으로 256 KiB를 넘는 텍스트 증거 50개는 Git 제외 artifacts 폴더의 `export-full/`로 옮겼다. 목록·크기·SHA-256은 `README.md` 끝 절과 `ARCHIVED-EVIDENCE.sha256`, 원래 해시는 `SHA256SUMS`에 있다. 옮긴 파일 50개 모두 해시 재확인 OK, 폴더에 남은 파일은 모두 `SHA256SUMS`와 일치.
