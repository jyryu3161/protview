# M14 탭 오프스크린 수락 QA 증거

- 생성: 2026-09-29T15:08:47.477148+00:00 · verdict **pass** · acceptance **true** · phases tabs, ledger
- 빌드: {"buildId": "jaO5G-sFo9B5sB5owJLyf", "gitHead": "4501aa1ed9eee1e958f047826c2be1ed968ce3df", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "0531ab42674d36afb7034eccbbb07fb3a3ec19fa3338c961e8cad9fccfe99689", "dirtyFiles": ["?? docs/qa/m14-tabs-20260930/"], "recordedAt": "2026-09-29T15:06:53.512782+00:00", "codeRoot": "<repo>", "deps": {"present": true, "symlink": false, "resolved": "<repo>/.deps"}, "harnessSha256": {"tabs-flow.cjs": "8a66964c6f82137d5466f243b10827316de35d6fb166ac9040619bc6c9555893", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "31f03794554e4e83082800bf15e780483b58d28e1b627a58cccbbc0db3f06b20"}
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
| T-unavailable | unavailable tabs: 사용할 수 없음, reason, opening stage; no numbers/controls; no requests of their own | pass | tabs-main:pass |
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

256 KiB를 넘는 텍스트 증거 1개(1,191,726 bytes)는 Git에 넣지 않고 `frontend/tests/offscreen/artifacts/m14-acceptance/20260930/export-full/`로 옮겼다(이 폴더 기준 상대 경로 유지). 해시는 `ARCHIVED-EVIDENCE.sha256`, 원래 줄은 `SHA256SUMS`에 남아 있다.

확인: `cd frontend/tests/offscreen/artifacts/m14-acceptance/20260930/export-full && shasum -a 256 -c ../../../../../../../docs/qa/m14-tabs-20260930/ARCHIVED-EVIDENCE.sha256`

| 파일 | bytes | SHA-256 |
|---|---:|---|
| `evidence/tabs-main/downloads/1790694440881-92878-4-protview-report-422b19d2be61.json` | 1,191,726 | `5ec6f5f75da1bf74b39377b78db89120bed8cd85bc3a22b4a2cc660f5dc2da2e` |
