# M15 잔기 번호 대응 오프스크린 수락 QA 증거

- 생성: 2026-10-06T15:09:53.200552+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "4GG2G1rPmVlN3v96FKAEK", "gitHead": "81fa17583eb355d6d9b9d4b239f354e49568eba9", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "0c3cf49414ec435d8950d34dadc621f9f275c53f049a8960353bef474167b9c4", "dirtyFiles": ["?? docs/qa/m24-jev-20261006/acceptance-fixture/", "?? docs/qa/m24-jev-20261006/m16-regression/", "?? docs/qa/m24-jev-20261006/m17-regression/", "?? docs/qa/m24-jev-20261006/m18-regression/", "?? docs/qa/m24-jev-20261006/m19-regression/", "?? docs/qa/m24-jev-20261006/m20-regression/", "?? docs/qa/m24-jev-20261006/m21-regression/", "?? docs/qa/m24-jev-20261006/m22-regression/", "?? docs/qa/m24-jev-20261006/m23-regression/"], "recordedAt": "2026-10-06T15:09:20.603342+00:00", "codeRoot": "<repo>", "harnessSha256": {"numbering-flow.cjs": "8996b7fc22495aeeca03600e7f97a4988dc2955ffb05d0b21deeb0e5c9944b8f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "fbf063db5d81af19dc14213a1f5b67d7c9b2308beb774f062e2248ce0dcb5a90"}
- 참조 스냅샷: 빈 폴더로 시작 → 실제 kbase 가져오기 `78ad6c460d7f8742b9a5b98b7f132679da3337ab0ccfde4070136c20d3ec7d5e` → 표시된 fixture 세트 `e547e332db4f6d1ab073737b1ad483e972f294accf850e07ffc5cc9e5af11fc4`
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

256 KiB를 넘는 텍스트 증거 1개(590,108 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m24-acceptance/final-20261006/export-full/m15-regression/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m24-acceptance/final-20261006/export-full/m15-regression && shasum -a 256 -c ../../../../../../../docs/qa/m24-jev-20261006/m15-regression/ARCHIVED-EVIDENCE.sha256`

참고: 이 폴더의 `SHA256SUMS`에서 `README.md` 줄만 일치하지 않는다. 해시를 만든 뒤 이 "옮긴 큰 텍스트 증거" 절을 덧붙였기 때문이며, 절을 빼면 기록된 해시와 같다. 나머지 파일은 일치한다.
