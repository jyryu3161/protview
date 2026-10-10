# M17 리간드 부분 교체 후보 오프스크린 수락 QA 증거

- 생성: 2026-10-10T13:59:34.921177+00:00 · verdict **pass** · acceptance **true**
- 빌드: {"buildId": "wbonjE7nah2kMcCTup7fP", "gitHead": "e595ca404b2ffa210eb6d372d8983c86fc7538b4", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "151e9f6f2346add9c4d499b08749474564601c2fc6dcaab1ceb580ea07a505fd", "dirtyFiles": ["?? docs/qa/m27-precedents-20261010/regression/"], "recordedAt": "2026-10-10T13:56:38.022084+00:00", "codeRoot": "<repo>", "harnessSha256": {"ligand-flow.cjs": "61f6503a72b57d0255281afbda7b3c563edde0e6dbb5cc5d656adb27792c3000", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "7583d335fbd25f65b8cc97da0b28e1b9493e4395c8d238447eecb2f91eaedf65"}
- 작업 환경: venv-locked 인터프리터 있음 · 주 backend capability 사용 가능 · 환경 없는 layout backend `worker_missing`
- 남은 프로세스/포트: 없음
- 비-loopback 요청 합계: 0

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 사례

| 사례 | 내용 | 결과 | 모드 |
|---|---|---|---|
| L-run-create | structure tab: 새 run + public_1mq4.cif; the ligand tab uses the global run (ready, capability line) | pass | ligand-main:pass |
| L-inputs-import | explicit-H parent SDF, block SDF, block SMILES chosen through the file chooser, six rules typed, 가져오기 → three chemical_raw_input handles listed by the backend | pass | ligand-main:pass |
| L-inspect-job | 점검 시작 → 비싼 계산 승인 → 작업 시작 → real rdkit_inspect_v1 done, one expensive unit | pass | ligand-main:pass |
| L-inspection-figure | inspection chosen by hand (none automatic); numbered RDKit 2D figure loads as an <img> data URI equal to the stored SVG, no inline SVG | pass | ligand-main:pass |
| L-atom-numbering | atom table = heavy atoms with SDF serials of the explicit-H parent (H serials skipped), elements and heavy neighbours equal the T1 hand oracle | pass | ligand-main:pass |
| L-rules-status | rules user_1–3 valid, user_4 reactant_count, user_5 reaction_parse_failed, user_6 duplicate_rule; block library accepted/rejected counts equal the hand oracle | pass | ligand-main:pass |
| L-invalid-rule | invalid rules shown as invalid with the reason and cannot be chosen for generation | pass | ligand-main:pass |
| L-site-check | site 19 → rejected crossing_bond_count (start disabled); 19+20 → one single crossing bond 14–19, site hydrogens 21–23, start enabled | pass | ligand-main:pass |
| L-enumerate-job | 후보 생성 시작 (fixed + user_1–3) → real rdkit_enumerate_v1 done, one expensive unit | pass | ligand-main:pass |
| L-candidates-oracle | table rows = server rows; 10 candidate SMILES equal the hand oracle, ids = c_ + SHA-256[:16], duplicate origins and rejected counts equal the hand trace, five limitations | pass | ligand-main:pass |
| L-filters | heavy atoms 12–14 (inclusive) and mol_weight max = stored boundary value; invalid input refused without a read; PAINS exclusion per stored matches | pass | ligand-main:pass |
| L-passes-only | 필터 통과만 보기: only passing rows; total and hidden-by-filter counts shown | pass | ligand-main:pass |
| L-sort | sort by mol_weight descending equals the stored values' order | pass | ligand-main:pass |
| L-paging | labeled generated chain list → 62 candidates: page 1 (50), 다음 (12), 이전; ids disjoint and complete | pass | ligand-main:pass |
| L-report | 보고서 만들기 (filters recorded) → 리간드 후보 보고서 in the knowledge-tab list; downloads equal the backend bytes | pass | ligand-main:pass |
| L-zero-candidates | fixed off + user_3 (outside the site) → 0 candidates: 빈 결과 (not 실패), outside_site counts | pass | ligand-main:pass |
| L-structure-kept | structure tab stays mounted (hidden) while the ligand tab is shown; same Mol* session, source and generation on return; global budget equals the backend | pass | ligand-main:pass |
| L-run-switch-late | run B shows only its own lists; a held run A inspection-list response released after the switch is not applied | pass | ligand-main:pass |
| L-no-run | no run: the ligand tab shows only the no-run reason (no numbers, no controls) | pass | ligand-unavailable:pass |
| L-unavailable | backend without the locked environment: 사용할 수 없음 with the capability reason (worker_missing), no numbers, no controls, no ligand requests | pass | ligand-unavailable:pass |
| S-no-egress | non-loopback requests 0 and zero provider calls on every flow row | pass |  |

## 단계

| 단계 | 결과 | 문제 |
|---|---|---|
| ligand-main | pass |  |
| ligand-unavailable | pass |  |

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m17_offscreen_acceptance.py --root runs/m17-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/<label> \
    --out docs/qa/m17-ligand-<YYYYMMDD>/acceptance
```
