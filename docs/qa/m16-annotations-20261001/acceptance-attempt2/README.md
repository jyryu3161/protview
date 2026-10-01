# M16 참조 주석 오프스크린 수락 QA 증거

- 생성: 2026-10-01T01:39:38.285668+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "q6eypdtQJ4Qgom9x2qBFB", "gitHead": "3a2e20c8e65c550a492cb51c7298e07215970231", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "8c28f30e15bb5421532bded2eec1b19d79d0dd8a733bd44ed4313a1aadfcc930", "dirtyFiles": [" M docs/qa/m16-annotations-20261001/gate.txt"], "recordedAt": "2026-10-01T01:38:40.038364+00:00", "codeRoot": "<repo>", "harnessSha256": {"annotation-flow.cjs": "8f670b8262fa02ca11c29625fb3be563e305d475df43935f7f31f1cf61fd5d85", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "7172edb88a386383d8ba5e43e65ab7a427687aedb89469d5ee1ac6dedfd47394"}
- 참조 스냅샷: 격리 폴더에 실제 kbase 가져오기 `96abf6e4842c2999c03c22ad1e27febf535c30142c7d96f180f52767dec17d3c`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·PNG·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| A-load-prepare-contacts | public_1mq4.cif loaded, 전처리, 기하 접촉 with the ADP instance chosen explicitly (7 fields equal the T1 preflight ligand; PO4 also offered) | pass | annotation-main:pass |
| A-numbering-prepared | 지식·보고서: numbering map on the prepared structure with PDB ID 1MQ4 confirmed | pass | annotation-main:pass |
| A-panel-create | panel lists only same-structure maps and contact results, chooses nothing automatically; map + ADP contacts → 주석 만들기 (annotate_reference_sites) | pass | annotation-main:pass |
| A-site-table | site table labels/status/counts/min distance equal the stored annotation and the T1 numpy oracle; computed zero shown as 0, no contact within cutoff shown as text | pass | annotation-main:pass |
| A-show-readback | Mol* readback: 10 sites, labels equal display_labels (Glu211 (hinge.46)), lines equal the 10 T1 polar pairs between the exact catalog atoms, distance labels ROUND_HALF_UP, 0 undrawn | pass | annotation-main:pass |
| A-figure-legend | viewer_scene@2 (legend on) + viewer_figure@2 molstar_image_pass+legend; PNG/JSON download bytes equal the backend; legend pixels only in the lower-left box | pass | annotation-main:pass |
| A-figure-no-legend | legend unticked → redraw → viewer_scene@2 legend false → figure capture molstar_image_pass | pass | annotation-main:pass |
| A-figure-pixels | same camera: annotation-on vs annotation-off PNG differ; polar line colour only with annotation | pass | annotation-main:pass |
| A-scene-v1-unchanged | annotation off → viewer_scene@1 body without annotation key, viewer_figure@1 | pass | annotation-main:pass |
| A-restore-redraw | annotation off, restore the @2 view → stored annotation redrawn (no tool call) | pass | annotation-main:pass |
| A-blocked-m8 | annotation shown: natural-language request blocked with reason, nothing sent; /zoom in works | pass | annotation-main:pass |
| A-report | 보고서 만들기 → 참조 주석 보고서 in the knowledge-tab library; downloads equal the backend bytes | pass | annotation-main:pass |
| A-no-contacts | 접촉 결과 없이 → annotation with contacts null; 접촉 결과 없음 cells, 0 lines | pass | annotation-main:pass |
| A-blocked-pocket | annotation on blocks the pocket overlay (reason); overlay on blocks the annotation and refuses the @2 restore without clearing the overlay | pass | annotation-main:pass |
| A-blocked-comparison | M10 comparison start turns the annotation off; it cannot be turned on; @2 restore refused | pass | annotation-main:pass |
| A-run-switch-late | run switch turns the annotation off; a held run A annotation-list response is not applied | pass | annotation-main:pass |
| A-read-retry | labeled read failures (map list, annotation list, detail) → 다시 읽기 controls recover | pass | annotation-main:pass |
| B-minimized | OpenMM-minimized 1UBQ source: only the unavailable reason, no numbers or controls | pass | annotation-minimized:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| annotation-main | pass |  |
| annotation-minimized | pass |  |
| reference-import | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/<label> --kbase ../kbase_kinase \
    --out docs/qa/m16-annotations-<YYYYMMDD>/acceptance
```

## 시도 2 (T10 재고정 `3a2e20c8e65c550a492cb51c7298e07215970231`)

- 시도 1(`../acceptance/`, 고정 `b23cb10`)은 M13-pixels 단계에서 실패했다. 하네스 `legendRegion()`이 T9 범례 줄바꿈(`cc3da8e`) 전의 상자 높이(47 px, y0=734)를 가정해 실제 상자(54 px, 729–782행)의 윗부분을 범례 밖으로 셌다(legendInside 0.0831 < 20 × legendOutside 0.00466). 시도 1 증거는 그대로 둔다.
- `3a2e20c`는 하네스 `frontend/tests/offscreen/annotation-flow.cjs`만 고쳤다(범례 상자 기하를 제품의 `wrapLegendText`·상수에서 가져옴). `b23cb10` 이후 제품 소스는 바뀌지 않았다. 시도 2의 M13-pixels: legendInside 0.1872, legendOutside 0.00393, 노란 점선 픽셀 legend 139 / plain 87 / off 0.
- 회귀(M15·M14·M13 실행기)는 다시 돌리지 않았다. 세 실행기 모두 `annotation-flow.cjs`를 불러오지 않고, 제품 소스와 빌드 입력은 `b23cb10`과 같다. 회귀 증거는 `../m15-regression/`, `../m14-regression/`, `../m13-regression/`(고정 `b23cb10`, 모두 acceptance true)에 있다.
- 바뀐 하네스에 영향받는 게이트 명령(`node --check frontend/tests/offscreen/annotation-flow.cjs`, 스크립트 pytest 9개 파일)은 `../gate.txt`의 "re-freeze" 절에 다시 기록했다.
