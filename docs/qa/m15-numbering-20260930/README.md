# M15 잔기 번호 대응 오프스크린 수락 QA 증거

- 생성: 2026-09-30T04:36:45.438422+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "mc98KdfOBAIUwmBLTIM0q", "gitHead": "c1d824d8bb6400f98790b1196c04cf84c6950264", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "dc7f03a106c4f81373f7b2071b191950e95a621bd93107a2d52702bf1392bc47", "dirtyFiles": ["?? docs/qa/m15-numbering-20260930/"], "recordedAt": "2026-09-30T04:36:14.684146+00:00", "codeRoot": "<repo>", "harnessSha256": {"numbering-flow.cjs": "8996b7fc22495aeeca03600e7f97a4988dc2955ffb05d0b21deeb0e5c9944b8f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "fbf063db5d81af19dc14213a1f5b67d7c9b2308beb774f062e2248ce0dcb5a90"}
- 참조 스냅샷: 빈 폴더로 시작 → 실제 kbase 가져오기 `1ad8413f8440a52bfdc64002f6ddbafdf709f7419587c5f43bf5251c731ea7c0` → 표시된 fixture 세트 `8e2307d4321f3285f5ca8c91cf10e7f8a3dfa55049370c1debe0653586c20b9e`
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

256 KiB를 넘는 텍스트 증거 1개(589,907 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m15-acceptance/final/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m15-acceptance/final/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m15-numbering-20260930/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/numbering-main/downloads/1790742989252-24961-2-protview-report-f1e84d1ed388.json` | 589,907 | `68654bd6f4077ec405d17a1a4fd16460473fdfa9a56a8534ce7ec09671556a1c` |

## T13 소스 고정·게이트·KLIFS 측정·회귀 요약

- 고정 소스(FROZEN): `c1d824d8bb6400f98790b1196c04cf84c6950264` (브랜치 `dryforge/m15-numbering`, 고정 시 작업 트리 깨끗함). 고정 뒤 소스 변경 없음. 세 수락 실행기의 `build.gitHead`가 모두 이 커밋이고 `buildCurrentWithSource: true`, `dirtyFiles`는 이 증거 폴더뿐이다.
- kbase_kinase: `77354f94b844a8c64e7cd47691ac20a2e96214b3`, 작업 트리 깨끗함(읽기 전용).

### 전체 게이트 (`gate.txt`, 2026-09-30T04:19–04:35Z, 순서대로)

| 명령 | exit | 결과 |
|---|---:|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 806 passed, 0 skipped |
| `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 스크립트 pytest 8개 파일(`docs/standards.md` 줄, `-rs` 추가) | 0 | 131 passed |
| `node --check` pocket-flow / workflows-flow / tabs-flow / numbering-flow | 0 | 4개 모두 ok |
| `npm --prefix frontend run test:events` | 0 | 180 pass, 0 fail, 0 skipped |
| `npm --prefix frontend run typecheck` | 0 | tsc --noEmit 통과 |
| `npm --prefix frontend run build` | 0 | 빌드 성공 |

### KLIFS 번호 측정 (`klifs_measurement.txt`, `klifs_measurement.json`)

명령: `.venv/bin/python scripts/measure_klifs_numbering.py --reference-dir .deps/reference --out docs/qa/m15-numbering-20260930/klifs_measurement.txt` (stdout JSON → `klifs_measurement.json`), 고정 소스에서 실행, exit 0, 네트워크 없음. 텍스트 머리글의 "draft" 문구는 스크립트에 고정된 문자열이다.

- 참조 세트 `.deps/reference` 활성 세트 `aa21ead9930f82ebea3a2acf976449d9b1c6280ed17206d74d8cb9dc3f923317` (uniprot SNAP-uniprot-2026-09-15, sifts SNAP-sifts-2026-09-20, klifs SNAP-klifs-2026-09-19). 수락 실행기가 새로 가져온 세트 `1ad8413f…c7ea0c0`와 `files/` 내용은 바이트 동일하다(파일 해시 목록의 해시가 같음). 세트 해시가 다른 것은 매니페스트의 `imported_at` 때문이다.
- 비교 구조 279(match_residues 행 318, 건너뜀 39), 비교 위치 22,618: 일치 22,211, 불일치 407(일치율 98.201%), ours_missing 852, ours_extra 104, 숫자 아닌 Xray_position 제외 244, label 불일치 0.
- 이 결과는 초안(`docs/qa/m15-numbering-draft/klifs_measurement.txt`, 커밋 `01d3e2c`)과 바이트 동일하여 초안 파일은 지웠다.

### PDBe 번호 확인 (`pdbe_label_check.txt`)

T5 구현자가 커밋 `01d3e2c`에서 만든 초안을 `git mv`로 옮겼다(내용 그대로, 다시 생성하지 않음; 이를 만드는 스크립트는 저장소에 없다). 1MQ4 chain A 261 잔기 모두 PDBe 번호 = `label_seq_id`.

### 오프스크린 수락

| 실행 | 명령 | exit | acceptance | 사례 | 비-loopback | 남은 프로세스 |
|---|---|---:|---|---|---:|---|
| M15 | `.venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/final --out docs/qa/m15-numbering-20260930 --kbase <home>/Projects/kbase_kinase` | 0 | true | 14/14 | 0 | 없음 |
| M14 회귀 | `.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m15-m14-regression-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m14-regression --out docs/qa/m15-numbering-20260930/m14-regression` | 0 | true | 15/15 | 0 | 없음 |
| M13 회귀(전체 phase) | `.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m15-m13-regression-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m13-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m15-numbering-20260930/m13-regression` | 0 | true | 28/28 (M11 하위 17/17, M12 하위 acceptance true, 단계 31개 pass) | 0 | 없음 |

제공자(OpenRouter) 호출 0회: M15·M14 행은 모두 `providerCallsZero: true`, M13 행 중 하위 실행기·회귀 행 7개는 이 필드를 만들지 않아 null이며(M14 회귀 증거와 같음) 그 행들의 외부 요청은 0건이다. 다시 실행한 것 없음.
