# M20 변이 후보 오프스크린 수락 QA 증거

- 생성: 2026-10-10T13:52:15.664955+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "wbonjE7nah2kMcCTup7fP", "gitHead": "e595ca404b2ffa210eb6d372d8983c86fc7538b4", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "151e9f6f2346add9c4d499b08749474564601c2fc6dcaab1ceb580ea07a505fd", "dirtyFiles": ["?? docs/qa/m27-precedents-20261010/regression/"], "recordedAt": "2026-10-10T13:51:36.683996+00:00", "codeRoot": "<repo>", "harnessSha256": {"mutation-flow.cjs": "e971c3571d4a26b0584ddd29c58df76730e08a9d1d7385fb9992514fae200165", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "8ebd1be88e14dcc0c90072012a17af92fbb9021fa72df6e675143d477047a3ff"}
- 환경: mutation_candidates 사용 가능 · fpocket 포켓 검출 사용 가능
- 참조 스냅샷: 격리 폴더에 실제 kbase 가져오기 `a97b251df112eb9503deb7c74a4c7711bbb4f060949d5f2df913c9f58525113f`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

재현 검사: handle은 run마다 다르다(obj://<run>/…). 그래서 새 run 두 개에서 흐름의 주석 없는 요청을 각각 두 번 보내 run 안에서 같은 handle인지, 저장 내용(obj:// handle만 자리표시로 바꿈)이 흐름의 결과와 같은지 본다. 흐름 안에서는 같은 요청을 다시 보내 같은 handle을 받는다(사례 M-same-handle).

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| M-no-run | fresh root, no run: the protein tab shows 사용할 수 없음 + the no-run reason only (no numbers, no controls, no mutation reads) | pass | mutation-main:pass |
| M-load-prepare | public_1mq4.cif loaded and prepared through the structure screen | pass | mutation-main:pass |
| M-unprepared | a run with a loaded but not prepared structure (run A before 전처리, run B): 사용할 수 없음 with the reason, no numbers, no controls, no tool call | pass | mutation-main:pass |
| M-ligand-explicit | ADP and PO4 offered, none chosen automatically; ligand shell blocked until ADP is chosen; the request carries the 7 ADP fields | pass | mutation-main:pass |
| M-not-checked | no annotation: the KLIFS 검사하지 않음 notice in the request area; stored and shown check row not_checked (annotation_not_given), KLIFS cells — (검사하지 않음), list row status not_checked | pass | mutation-main:pass |
| M-shell-oracle | ADP 5.0 Å shell: 20 positions, distances (≤1e-9 Å) and ROUND_HALF_UP cells, MG contact exclusions ASN261/ASP274 (MG A2088) equal the T1 numpy oracle; 342 candidates | pass | mutation-main:pass |
| M-numbering-annotation | numbering map (지식·보고서, PDB ID 1MQ4) and annotation without contacts (구조 분석) through the existing screens; annotated sites equal the T1 list | pass | mutation-main:pass |
| M-reread-on-entry | entering the tab re-reads events, pockets, maps, annotations and results (GET only); choosing the structure pre-selects the newest annotation and its map | pass | mutation-main:pass |
| M-protect-release | protect/release conflict blocked on screen; KLIFS key sites excluded with labels, ASP274 KLIFS + metal, LEU139 user protected, ASN261 released (candidate), ARG126 release effect none; excluded list = stored | pass | mutation-main:pass |
| M-allowed-shrink | allowed A/G/W: request AGW, a new handle, per-position candidate counts and targets | pass | mutation-main:pass |
| M-same-handle | the S1 request sent again returns S1's handle and stores nothing new | pass | mutation-main:pass |
| M-request-controls | annotation/map selects (the 검사하지 않음 notice follows the annotation choice), metal distance 5.0 Å → MG contacts in the shell equal the T1 oracle, 빼기 on the direct and protect lists, 결과 목록 다시 읽기 (GET only) | pass | mutation-main:pass |
| M-pocket | real fpocket on the prepared structure (approval), then pocket source with every stored pocket number + shell 12 Å: pocket positions = union of the stored lining residues | pass | mutation-main:pass |
| M-tab-state | the structure screen keeps its prepared source across protein-tab trips | pass | mutation-main:pass |
| M-filters-sort | four position filters and the distance sort equal the stored pages (rows without a value last); candidate position and target filters | pass | mutation-main:pass |
| M-paging | position and candidate pagers (다음/이전) equal the stored pages | pass | mutation-main:pass |
| M-zero | zero candidates (ALA A:160, allowed A): 빈 결과 state with the stored exclusion counts, not 실패 | pass | mutation-main:pass |
| M-refused | labeled in-flight request alterations → the real server refuses structure_invalid, annotation_invalid, protect_release_conflict, ligand_required (422); the screen shows the Korean name and code; nothing stored | pass | mutation-main:pass |
| M-report | 보고서 만들기 → 변이 후보 보고서 in the knowledge-tab library; content = stored Markdown with the five fixed sentences; Markdown/JSON downloads equal the backend bytes | pass | mutation-main:pass |
| M-late-result | held detail / position responses of another result released after switching are not applied | pass | mutation-main:pass |
| M-late-run | a held run A result-list response released after switching to run B is not applied | pass | mutation-main:pass |
| M-wording | no rank/recommendation/effect wording in the panel outside the five fixed sentences | pass | mutation-main:pass |
| M-reproducible | the flow's request without annotation made twice in each of two fresh runs: the same handle twice per run and the stored content (obj:// handles replaced) equal to the flow's set | pass | runner:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 관찰하지 않은 사례

- M-map-conflict: only one numbering map exists per structure in this flow, so the screen's map/annotation conflict notice is not reached; covered by frontend/tests/mutations.test.cjs (annotationMapConflict) and backend annotation_map_mismatch in backend/tests/test_mutation_tool.py.
- M-too-many-positions: 1MQ4 has 261 protein residues, below the 400-position cap; covered by backend/tests/test_mutation_tool.py::test_too_many_positions_is_429_and_nothing_is_stored.
- M-nonstandard-disulfide: 1MQ4 has no modified-name residue and no SG–SG pair within 2.5 Å (T1 preflight); covered by the synthetic fixture tests in backend/tests/test_mutation_candidates.py.

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| mutation-main | pass |  |
| reference-import | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m20_offscreen_acceptance.py --root runs/m20-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/<label> --kbase <abs>/kbase_kinase \
    --out docs/qa/m20-mutations-<YYYYMMDD>/acceptance [--regressions]
```
