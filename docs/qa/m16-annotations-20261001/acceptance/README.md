# M16 참조 주석 오프스크린 수락 QA 증거

- 생성: 2026-10-01T00:49:33.638788+00:00 · verdict **fail** · acceptance **false**
- 빌드: {"buildId": "q6eypdtQJ4Qgom9x2qBFB", "gitHead": "b23cb10f624d1942666d0f0080e49e449055b53e", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "9b7ed3549ff86364bc200cc11117ca049a6f76ef26edb8475dc31f4877741141", "dirtyFiles": ["?? docs/qa/m16-annotations-20261001/gate.txt"], "recordedAt": "2026-10-01T00:48:35.336656+00:00", "codeRoot": "<repo>", "harnessSha256": {"annotation-flow.cjs": "b6f0c4eec249e7ec5af4242518314ca2644cb36ca234b6c3af65fb35323649c2", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "7172edb88a386383d8ba5e43e65ab7a427687aedb89469d5ee1ac6dedfd47394"}
- 참조 스냅샷: 격리 폴더에 실제 kbase 가져오기 `67e062ad2daaa52f2f63e52542000816228c8934415dbe6d93041ddc57cab9e5`
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
| A-figure-legend | viewer_scene@2 (legend on) + viewer_figure@2 molstar_image_pass+legend; PNG/JSON download bytes equal the backend; legend pixels only in the lower-left box | fail | annotation-main:fail |
| A-figure-no-legend | legend unticked → redraw → viewer_scene@2 legend false → figure capture molstar_image_pass | fail | annotation-main:fail |
| A-figure-pixels | same camera: annotation-on vs annotation-off PNG differ; polar line colour only with annotation | fail | annotation-main:fail |
| A-scene-v1-unchanged | annotation off → viewer_scene@1 body without annotation key, viewer_figure@1 | fail | annotation-main:fail |
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
| annotation-main | fail | status fail |
| annotation-minimized | pass |  |
| reference-import | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/<label> --kbase ../kbase_kinase \
    --out docs/qa/m16-annotations-<YYYYMMDD>/acceptance
```
