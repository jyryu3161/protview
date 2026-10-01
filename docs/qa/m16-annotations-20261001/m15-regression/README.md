# M15 잔기 번호 대응 오프스크린 수락 QA 증거

- 생성: 2026-10-01T00:51:34.285660+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "q6eypdtQJ4Qgom9x2qBFB", "gitHead": "b23cb10f624d1942666d0f0080e49e449055b53e", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "4841b77a6998f734b8c6a5f4eb68825d07e58a78a2e28ac7dc877f3214be22e3", "dirtyFiles": ["?? docs/qa/m16-annotations-20261001/acceptance/", "?? docs/qa/m16-annotations-20261001/gate.txt"], "recordedAt": "2026-10-01T00:51:03.754198+00:00", "codeRoot": "<repo>", "harnessSha256": {"numbering-flow.cjs": "8996b7fc22495aeeca03600e7f97a4988dc2955ffb05d0b21deeb0e5c9944b8f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "fbf063db5d81af19dc14213a1f5b67d7c9b2308beb774f062e2248ce0dcb5a90"}
- 참조 스냅샷: 빈 폴더로 시작 → 실제 kbase 가져오기 `7de2dd22175b94e4e42673f362ed89f70bf57894fd5420d8f6a726c957d483c6` → 표시된 fixture 세트 `0cbd25e5784b412ff5a2eab018a18ce07986f4aaf3818254e3541cb16aeada54`
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

256 KiB를 넘는 텍스트 증거 1개(590,109 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m15-acceptance/m16-regression/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m15-acceptance/m16-regression/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m16-annotations-20261001/m15-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/numbering-main/downloads/1790815878265-18822-2-protview-report-510f45e16df9.json` | 590,109 | `47a33ae681b40610359c3279901c5822ff8962ae1086f9650f06cfd06d15e1e1` |
