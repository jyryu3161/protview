# M13 T8 전체 게이트·수락 QA 결과

- 소스 고정: `dryforge/m13-workflows` HEAD `d1eaf48243e26301528c7593780c6ad2b630583b` (main `1e91848` 대비 바뀐 파일 SHA-256은 `freeze-manifest.txt`). 게이트 시작 전 `git status --porcelain` 비어 있음.
- 실행: 2026-09-29, 프로젝트 루트 `<repo>`, 8000·3000 포트 비움, 다른 pytest·서비스 동시 실행 없음. typecheck와 build는 순서대로 실행.

## 게이트 (명세 12절, 8개)

| # | 명령 | exit | 결과 |
|---|---|---|---|
| 1 | `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 589 passed, 0 skipped, 1 warning (StarletteDeprecationWarning), 957.6 s |
| 2 | `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 3 | `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 0 | 85 passed |
| 4 | `node --check frontend/tests/offscreen/pocket-flow.cjs` | 0 | 출력 없음 |
| 5 | `node --check frontend/tests/offscreen/workflows-flow.cjs` | 0 | 출력 없음 |
| 6 | `npm --prefix frontend run test:events` | 0 | pass 148, fail 0, skipped 0 |
| 7 | `npm --prefix frontend run typecheck` | 0 | tsc --noEmit 오류 없음 |
| 8 | `npm --prefix frontend run build` | 0 | BUILD_ID `WCnxUsptjGLeenXzwlYhV` (수락 실행이 이 빌드를 사용) |

## 수락 QA (1차 실행)

```bash
.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-20260929 \
    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/20260929 \
    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-20260929
```

exit 1, M13 case-ledger verdict **fail** (`README.md`, `evidence/case-ledger.json`). 원인별:

| phase | 결과 | 내용 |
|---|---|---|
| workflows | pass | main, m10, race, minimize, chemical-create, attach-setup, chemical-attach, chemical-error, dry-run 모두 pass. 비-loopback 0, 제공자 호출 0 측정 |
| unavailable | pass | 엔진 없는 표시 layout |
| regressions | pass | M8 normal, M9 openmm full → scenes core, M10 measure, M10 alignment 모두 pass, 비-loopback 0 |
| m11 | **실행기 판정 fail (M11 자체는 pass)** | `scripts/m11_offscreen_acceptance.py` exit 0, 자체 ledger 사례 17/17 pass, 29행, 비-loopback 합계 0, 측정 불명 행 없음. 그러나 M11 ledger(`m11_case_ledger@1`)에는 `verdict` 키가 없고 `summary`만 있어, M13 실행기 `sub_runner`의 `.get("verdict") == "pass"` 판정이 None → fail, externalRequestCount None으로 기록됨. M13 실행기(`scripts/m13_offscreen_acceptance.py` 526행)의 통합 결함이며 소스 고정 중이라 고치지 않음 |
| m12 | fail (1개 단계) | M12 실행기 31단계 중 30 pass, `regression-m10-measure` 사례 C02-repeat-reverse fail: 측정 모드에서 기준 원자 클릭 3회가 모두 Mol* `empty_loci`("Mol* observation did not become ready"). 같은 comparison-flow measure가 이 실행의 M13 regressions와 M11 실행기 회귀에서는 pass. 비-loopback 합계 0 |
| ledger | fail | 위 두 sub-runner 행 때문에 steps·cases(S-no-egress: sub-runner 행 externalRequestCount None) 실패. 나머지 27개 사례 pass |

## 재실행 (1회)

- M12 `regression-m10-measure`만 M12 실행기 `--only`로 같은 루트·같은 artifacts에서 1회 재실행: `.venv/bin/python scripts/m12_offscreen_acceptance.py --root runs/m13-acceptance-20260929/m12-acceptance --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/20260929/m12-acceptance/evidence --phases regressions,ledger --only regression-m10-measure` → exit 0, `case-ledger-partial.json` verdict partial_not_acceptance, 해당 단계 pass(시도 2회, 최신 pass). 실패한 1차 증거는 그대로 남겼다. 간헐적 Mol* 원자 선택 타이밍 문제로 판단하지만 원인은 확인하지 않았다.
- 이 재실행은 1차 실행에서 내보낸 이 폴더의 `evidence/`·`SHA256SUMS`에는 들어 있지 않다(내보내기가 재실행 전에 끝남).
- M11 판정 결함은 재실행으로 바뀌지 않으므로 재실행하지 않았다.

## 외부 요청·남은 프로세스

- 모든 M13 흐름 행 externalRequestCount 0, providerCallsZero true(회귀 행은 측정 대상 아님=null). M11 비-loopback 합계 0, M12 비-loopback 합계 0. 합계 0.
- 실행기 leftover-processes pass(수락 루트 안 작업 프로세스 없음, 8000·3000 리스너 없음). 종료 뒤 `lsof`로 8000·3000 비어 있음 재확인.
- 내보낸 텍스트 증거에 절대 경로(`/Users/`, `/private/`)·자격 증명 문자열 없음(grep 0건). 스크린숏·다운로드는 Git 제외 artifacts 폴더에만 있고 `binary-artifacts.json`에 해시만 기록.

## 커밋한 증거 범위

사용자 결정(2026-09-29)으로 256 KiB를 넘는 텍스트 증거 50개는 Git 제외 artifacts 폴더의 `export-full/`로 옮겼다. 목록·크기·SHA-256은 `README.md` 끝 절과 `ARCHIVED-EVIDENCE.sha256`, 원래 해시는 `SHA256SUMS`에 있다. 옮긴 파일 50개 모두 해시 재확인 OK, 폴더에 남은 파일은 모두 `SHA256SUMS`와 일치.
