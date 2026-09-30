# M15 잔기 번호 대응 오프스크린 수락 QA 증거

- 생성: 2026-09-30T06:23:12.189049+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "pcbgeXT7695xhpke_ImKb", "gitHead": "93c4fb1cc102563ce70f5c4f16e8ff97d65d6497", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "e7b88637a0aa817dc2452ca181f82e1ce0c9b4412cc2744606ed5ed22765a0d8", "dirtyFiles": ["?? docs/qa/m15-numbering-20260930/refreeze-93c4fb1/"], "recordedAt": "2026-09-30T06:22:40.424123+00:00", "codeRoot": "<repo>", "harnessSha256": {"numbering-flow.cjs": "8996b7fc22495aeeca03600e7f97a4988dc2955ffb05d0b21deeb0e5c9944b8f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "fbf063db5d81af19dc14213a1f5b67d7c9b2308beb774f062e2248ce0dcb5a90"}
- 참조 스냅샷: 빈 폴더로 시작 → 실제 kbase 가져오기 `f92cfd9544366ddfc9affc99b9f8bb8e9b70223515549de1c5b9c09b0bd45809` → 표시된 fixture 세트 `865f0faf3f4135ebcc22a798df3566b94b81ca0b18b242415b0a34048eff402f`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| N-no-snapshot | no snapshot: 사용할 수 없음 and reason, import command; no numbers, no run control | pass | numbering-empty:pass |
| N-confirmed-sifts | 1MQ4 uploaded, PDB ID suggestion confirmed → SIFTS accession prefilled → run → chain A cross-checked, rows table equals the stored rows | pass | numbering-main:pass |
| N-klifs-oracle | KLIFS numbers on screen equal the KLIFS match_residues table of 1MQ4:A (author number → KLIFS position; GK.45/hinge/xDFG residues required) | pass | numbering-main:pass |
| N-status-filter | status filter (충돌/대응됨/대응 없음/전체) changes the count text; total kept | pass | numbering-main:pass |
| N-conflict-row | S388 row shows 충돌 (one_method_only) with both answers | pass | numbering-main:pass |
| N-alignment-only | accession picked without confirming the PDB ID → 교차 확인 없음 marker; S388 대응 없음 | pass | numbering-main:pass |
| N-below-identity | another kinase accession → chain unmapped below identity; 대응된 잔기 없음 (scientific_null) | pass | numbering-main:pass |
| N-prepared | prepared structure (structure-tab 전처리) → map with mapped rows | pass | numbering-main:pass |
| N-report | 보고서 만들기 → 잔기 번호 대응 보고서 in the report list; download SHA-256 equal the backend bytes | pass | numbering-main:pass |
| N-read-retry | labeled read failure (snapshots, map list) → failure state with 다시 시도 → recovers | pass | numbering-main:pass |
| N-run-switch | after a run switch the numbering panel shows only the new run's maps | pass | numbering-main:pass |
| N-late-response | a held map-list response of the previous run released after the switch is not applied | pass | numbering-main:pass |
| N-stale | after a different (marked fixture) set is activated, earlier maps show 이전 스냅샷 기준 | pass | numbering-stale:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| numbering-empty | pass |  |
| numbering-main | pass |  |
| numbering-stale | pass |  |
| reference-import | pass |  |
| reference-reimport | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/<label> --kbase ../kbase_kinase \
    --out docs/qa/m15-numbering-<YYYYMMDD>
```

## 옮긴 큰 텍스트 증거 (결정 0020)

256 KiB를 넘는 텍스트 증거 1개(590,108 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m15-acceptance/refreeze2/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m15-acceptance/refreeze2/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m15-numbering-20260930/refreeze-93c4fb1/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/numbering-main/downloads/1790749375178-62687-2-protview-report-2f4e4bc5e196.json` | 590,108 | `79609f132a73380fcba47f97ba8bcb033502ce9ff6f796a5b7ef7ac237167353` |

첫 고정본(`../`, c1d824d)의 같은 보고서는 589,907 bytes였다. 늘어난 201 bytes는 최종 검토 수정으로 보고서 `limitations`에 추가된 참조 스냅샷 범위 문장(`SNAPSHOT_SCOPE`, "kinase 한정 자료")이며, 이 파일에서 그 문장을 확인했다.

## 재고정(re-freeze) 소스·게이트·회귀 요약

- 고정 소스(FROZEN): `93c4fb1cc102563ce70f5c4f16e8ff97d65d6497` (브랜치 `dryforge/m15-numbering`, 시작 시 작업 트리 깨끗함, 고정 뒤 소스 변경 없음). 두 수락 실행기의 `build.gitHead`가 이 커밋이고 `buildCurrentWithSource: true`, `dirtyFiles`는 이 증거 폴더뿐이다.
- 첫 고정 `c1d824d` 대비 `docs/` 밖 변경(`git diff --name-only c1d824d..93c4fb1 -- . ':!docs'`): 코드·테스트 8개 — `backend/mw/numbering_reports.py`, `backend/mw/residue_numbering.py`, `backend/tests/test_klifs_numbering.py`, `backend/tests/test_numbering_reports.py`, `backend/tests/test_residue_numbering.py`, `frontend/src/components/NumberingPanel.tsx`, `frontend/src/lib/numbering.ts`, `frontend/tests/numbering.test.cjs`. 그 밖에 안내 문서 5개(`AGENTS.md`, `CLAUDE.md`, `backend/AGENTS.md`, `frontend/AGENTS.md`, `scripts/AGENTS.md`)만 바뀌었고 실행 코드가 아니다. 수락 실행기·오프스크린 하네스는 바뀌지 않았다(`runnerSha256`·`harnessSha256`이 첫 고정과 같음).
- kbase_kinase: `77354f94b844a8c64e7cd47691ac20a2e96214b3`, 작업 트리 깨끗함(읽기 전용).
- `MW_KBASE_REF`는 설정하지 않았다. `<repo>/../kbase_kinase/ref`가 있어 KLIFS 실제 스냅샷 테스트 2개가 그것으로 실행됐다(skip 0).

### 전체 게이트 (`gate.txt`, 2026-09-30T06:04:47–06:21:26Z, 순서대로)

| 명령 | exit | 결과 |
|---|---:|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 815 passed, 0 skipped |
| `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 스크립트 pytest 8개 파일(`docs/standards.md` 줄, `-rs` 추가) | 0 | 131 passed |
| `node --check` pocket-flow / workflows-flow / tabs-flow / numbering-flow | 0 | 4개 모두 ok |
| `npm --prefix frontend run test:events` | 0 | 183 pass, 0 fail, 0 skipped |
| `npm --prefix frontend run typecheck` | 0 | tsc --noEmit 통과 |
| `npm --prefix frontend run build` | 0 | 빌드 성공 |

`gate.txt`의 pytest 경고 줄에 있던 절대 경로는 `<repo>`로 바꿨다(아래 시도 1 참고).

### 오프스크린 수락

| 실행 | 명령 | exit | acceptance | 사례 | 비-loopback | 남은 프로세스 |
|---|---|---:|---|---|---:|---|
| M15 시도 1 | `.venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-20260930-refreeze --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/refreeze --out docs/qa/m15-numbering-20260930/refreeze-93c4fb1 --kbase <home>/Projects/kbase_kinase` | 1 | true | 14/14 | 0 | 없음 |
| M15 시도 2(채택) | 같은 명령, `--root runs/m15-acceptance-20260930-refreeze2 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/refreeze2` | 0 | true | 14/14 | 0 | 없음 |
| M14 회귀 | `.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m15-m14-regression-20260930-refreeze --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m14-regression-refreeze --out docs/qa/m15-numbering-20260930/refreeze-93c4fb1/m14-regression` | 0 | true | 15/15 | 0 | 없음 |

- 시도 1: 모든 사례·단계가 pass였지만 마지막 `export-evidence` 단계가 fail(`leaked: ["gate.txt"]`)이었다. QA 실행자가 먼저 이 폴더에 써 둔 `gate.txt`의 pytest 경고 줄에 가림 처리하지 않은 절대 경로가 있었기 때문이며 제품 코드 문제가 아니다. 그 `gate.txt`를 가림 처리한 뒤 새 root·artifacts로 다시 실행했다(시도 2). 시도 1의 내보낸 증거와 실행기 출력은 지우지 않고 Git 제외 폴더 `frontend/tests/offscreen/artifacts/m15-acceptance/refreeze/attempt1-export/`에 옮겨 두었다.
- 제공자(OpenRouter) 호출 0회: M15·M14 행 모두 `providerCallsZero: true`.
- 참조 세트: 시도 2의 실제 kbase 가져오기 세트 해시·fixture 세트 해시는 README 머리글에 있다. 첫 고정과 해시가 다른 것은 매니페스트의 `imported_at` 때문이다.

### M13 회귀를 다시 돌리지 않은 이유

- 첫 고정 `c1d824d`에서 M13 회귀(전체 phase: workflows, unavailable, regressions, m11, m12, ledger)가 acceptance true, 28/28로 끝났다(`../m13-regression/`).
- 그 뒤 바뀐 프런트엔드 코드는 `NumberingPanel.tsx`와 `lib/numbering.ts`뿐이다. `NumberingPanel`은 `app/page.tsx`에서 `WorkspaceTabs`의 `numbering` 슬롯으로만 넘겨지고, 그 슬롯은 지식·보고서 탭이 보일 때만 그려진다. `lib/numbering.ts`를 실행 코드로 가져다 쓰는 것은 `NumberingPanel`뿐이다(`lib/api.ts`는 `import type`으로 타입만 가져오며 컴파일 때 지워진다. `api.ts`는 바뀌지 않았다). M13 흐름(분석 흐름·M11·M12 화면)은 이 두 파일을 가져오지 않는다.
- 바뀐 백엔드 코드는 `numbering_reports.py`(번호 대응 보고서의 행·KLIFS 이유 검증을 닫힌 집합으로 제한, `limitations`에 스냅샷 범위 문장 추가, 이전 보고서 다시 열기 허용)와 `residue_numbering.py`(`CONFLICT_REASONS` 상수 1줄)뿐이다. M13·M11·M12의 도구·작업·보고서 경로는 이 모듈을 쓰지 않는다.
- 전체 백엔드 pytest(815, M13·M11·M12 테스트 포함)와 M14 탭 회귀가 이 고정 소스에서 통과했다.
