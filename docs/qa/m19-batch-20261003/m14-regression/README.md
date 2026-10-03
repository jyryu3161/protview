# M14 탭 오프스크린 수락 QA 증거

- 생성: 2026-10-03T02:48:29.762935+00:00 · verdict **pass** · acceptance **true** · phases tabs, ledger
- 빌드: {"buildId": "HZVIvlS1pgVkSE0gAkqD6", "gitHead": "858bd45217e5bae3e87c4451261c1bc369a079c3", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "a1452c56b807db2cb838082f307b625251556975dec2b363c582aa6552357ad6", "dirtyFiles": ["?? docs/qa/m19-batch-20261003/acceptance/", "?? docs/qa/m19-batch-20261003/gate.txt", "?? docs/qa/m19-batch-20261003/m15-regression/", "?? docs/qa/m19-batch-20261003/m16-regression/", "?? docs/qa/m19-batch-20261003/m17-regression/", "?? docs/qa/m19-batch-20261003/m18-regression/"], "recordedAt": "2026-10-03T02:46:45.065928+00:00", "codeRoot": "<repo>", "deps": {"present": true, "symlink": false, "resolved": "<repo>/.deps"}, "harnessSha256": {"tabs-flow.cjs": "b404797c1228eb2027c99d83a6d9637052e139d44d89ea53c464877d8a75c828", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "0d31abfa50fe8b3cdb49afe28da034f97a08f2a5642bd853fb45fed298688b72"}
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| T-tabs | four tabs in order with their labels; 구조 분석 selected by default; switching keeps the address | pass | tabs-main:pass |
| T-structure-state | source handle, representation, residue selection, camera identical after visiting the other three tabs; non-empty paint after return | pass | tabs-main:pass |
| T-running-job | a running OpenMM job keeps progressing (polling) while another tab is shown | pass | tabs-main:pass |
| T-chemical-preserved | chemical workspace kept across a tab round trip; tab bar visible there | pass | tabs-chemical:pass |
| T-unavailable | unavailable tab (단백질 공학): 사용할 수 없음, reason, opening stage; no numbers/controls; no requests of its own. 지식·보고서 shows the M15 numbering screen and 리간드 설계·탐색 the M17 candidate screen (GET reads only) instead of their former notices | pass | tabs-main:pass |
| T-reports-list | interaction + method report, saved figure, completed summary listed; non-complete execution absent | pass | tabs-main:pass |
| T-reports-content | content shown; download bytes SHA-256 equal the backend bytes of the same format | pass | tabs-main:pass |
| T-reports-fault | reports-list fault (labeled fixture) affects only that list; retry; structure screen intact | pass | tabs-main:pass |
| T-no-run | no run: guidance shown and no list request | pass | tabs-main:pass |
| T-run-switch | after a run switch in 구조 분석 the reports tab shows only the new run's lists | pass | tabs-main:pass |
| T-late-response | held list responses of the previous run released after the switch are dropped | pass | tabs-main:pass |
| T-global-run | global run id equals the structure (and chemical) screen's | pass | tabs-main:pass, tabs-chemical:pass |
| T-budget-main | global budget equals backend /budget after an expensive computation at tab switch (main screen) | pass | tabs-main:pass |
| T-budget-chemical | global budget equals backend /budget after expensive jobs at tab switch (chemical screen) | pass | tabs-chemical:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| tabs-main | pass |  |
| tabs-chemical | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m14-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/<label> \
    --out docs/qa/m14-tabs-<YYYYMMDD>
```

`--build auto`는 현재 frontend 소스로 도장 찍힌 빌드만 재사용하고, 아니면 typecheck 다음 build를 차례로 돌린다. 화학 모드는 `<code root>/.deps/prolif`가 있어야 하며 없으면 실패로 기록한다.

## 옮긴 큰 텍스트 증거 (결정 0020)

256 KiB를 넘는 텍스트 증거 1개(1,191,725 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m19-acceptance/attempt1/regressions/m14/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m19-acceptance/attempt1/regressions/m14/export-full && shasum -a 256 -c ../../../../../../../../../docs/qa/m19-batch-20261003/m14-regression/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/tabs-main/downloads/1790995633283-77916-4-protview-report-ef7b4f7a3dfe.json` | 1,191,725 | `1ef8048f698b04adfa7285311d26d74e1d0aefffec83194a2ecdaf091433bdd0` |
