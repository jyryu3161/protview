# M26 효소 반응 지식 오프스크린 수락 QA 증거

- 생성: 2026-10-09T03:35:54.649341+00:00 · verdict **pass** · acceptance **false** (두 단계가 이번 실행에서 모두 돌고 통과할 때만 true)
- 요청한 단계: fixture · 빠진 단계: real
- 사례: 39/39 통과
- 빌드: {"buildId": "4-fB1d-vH135JEpv-hR4g", "gitHead": "b3131fd74c174b6cda84418fb53b00cc08dac03a", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "11adad347e7d34735507fbaf47e53838871226575a4dbb2801eae3df637124b4", "dirtyFiles": [" M frontend/tests/offscreen/jev-flow.cjs", " M frontend/tests/offscreen/mutation-flow.cjs", " M frontend/tests/offscreen/reaction-knowledge-flow.cjs", " M scripts/m26_offscreen_acceptance.py", " M scripts/test_m26_offscreen_acceptance.py", "?? docs/qa/m26-reaction-20261008/real-stage/", "?? docs/qa/m26-reaction-20261008/regression-prep/"], "recordedAt": "2026-10-09T03:34:53.490601+00:00", "codeRoot": "<repo>", "harnessSha256": {"reaction-knowledge-flow.cjs": "9364111cd11de0fd93c12035d40f0d4028327c9fb58fea260c3e75ead4b36d7f", "mutation-flow.cjs": "f3312872f81a88a3c5ba6299b53f36863acc568fd7476cabfce6979a2253c53f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "e167bf27e2c7f2fbe78de51e3c99009f5fb59f08f5622ff19ca89ff339fe0f5a"}
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0 · 접촉한 외부 호스트: 없음

**fixture 단계의 반응 참조값(M-CSA·UniProt·Rhea 행)은 모두 합성(SYNTHETIC)이다.** `backend/tests/fixtures/reaction/t9/build_qa_set.py`가 T2·T6·T9 합성 행으로 만든 세트이며 (`SYNTHETIC-PROVENANCE-t2.md`·`-t6.md`·`-t9.md`), 지어낸 PDB ID(0T91·0T92·0SY6·0SY2 등)를 사람이 구조에 준 것으로 보고 입력했다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 과학 결과가 아니다. 촉매 잔기·부위·반응에 대한 사실이나 변이의 효과를 뜻하지 않는다.

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 단계 `fixture` — pass

| 사례 | 내용 | 결과 | 단계 |
|---|---|---|---|
| R-no-snapshot | no reaction set: the snapshot block shows 사용할 수 없음, the not_installed reason and the import command only (no numbers, no controls); the request block shows a reason only | pass | fixture-empty:pass |
| R-snapshot-ready | set A: hash (12 + full in title), three sources with date, CC BY 4.0 and row counts, the processed-copy label, user-named and skipped counts, the skipped list, RK1 / UK1 / RK6 verbatim | pass | fixture-main:pass |
| R-request-defaults | nothing chosen by itself: no structure, the file's PDB ID suggestion unconfirmed, no chain ticked, no numbering map, 연결하기 disabled | pass | fixture-main:pass |
| R-field-errors | typed values the screen refuses (PDB ID ABCD confirmed, accession p0syn1): the reason beside the field, 연결하기 disabled, nothing posted | pass | fixture-main:pass |
| R-refusals | nine labelled in-flight request alterations → the real server refuses each admission reason; the screen shows "한국어 (code)" beside its field; nothing stored | pass | fixture-main:pass |
| R-matched-row | 1HSG with PDB ID 0T91 (synthetic rows): both chains covered; matched rows with the 7-field identity, the verbatim text in the column "M-CSA 원문, 계산 아님" ("" for an empty string) and the reference-structure flag; the screen equals the stored rows | pass | fixture-main:pass |
| R-reaction-section | chain A with accession Q0SYN1: EC of both sources, M-CSA compounds, UniProt activities with Rhea in_snapshot true and false (equation or — with the reason) | pass | fixture-main:pass |
| R-conflict-derived | the synthetic derived 1HSG (ASP A25 renamed GLU): the A25 row is 충돌 (residue_name_differs) with the structure name GLU | pass | fixture-main:pass |
| R-unmatched-reasons | synthetic 0SY6 and 0SY2 structures: all five 대응 없음 reasons and both 충돌 reasons, the insertion-code identity and null label fields as — | pass | fixture-main:pass |
| R-two-entries | one chain with two M-CSA entries (601, 602): both listed, none chosen | pass | fixture-main:pass |
| R-uk4 | chains M-CSA does not cover (chain_not_listed, pdb_not_in_snapshot) carry UK4 beside the chain label | pass | fixture-main:pass |
| R-pdb-not-in-snapshot | 1UBQ (file suggestion confirmed): pdb_not_in_snapshot, the area's 빈 결과 state, the PDB lookup sentence without a number | pass | fixture-main:pass |
| R-accession-states | 이 accession 쓰기 (lookup suggestion), an accession skipped at import (demerged + targets), an accession not in the snapshot, the accession_differs_from_mcsa flag | pass | fixture-main:pass |
| R-uniprot-link | prepared 1MQ4 + M15 numbering map (real kbase snapshot in the isolated folder): sites linked through the map, mapped links with the 7 fields and not_in_map links | pass | fixture-main:pass |
| R-link-reasons | without the map: numbering_map_not_given; map with another accession: map_accession_differs | pass | fixture-main:pass |
| R-paging | 60 rows on one chain: M-CSA 행 다음 / 이전 equal the stored pages; chain and site pagers disabled | pass | fixture-main:pass |
| R-report | 보고서 만들기 → 효소 반응 지식 보고서 in the library; Markdown / JSON downloads non-empty and equal to the backend bytes; RK1–RK6 present; no forbidden word outside fixed lines and reference strings | pass | fixture-main:pass |
| R-dry-run | a dry-run run (record made over the loopback API; every later step a real click) still links and stores the result | pass | fixture-main:pass |
| R-results-list | the result list equals the stored list; counts that were not made are — with the reason; 결과 목록 다시 읽기 reads (GET only) | pass | fixture-main:pass |
| R-no-zero | values that were not checked, not available or not computed are — with the reason, never 0 | pass | fixture-main:pass, fixture-mutation:pass |
| R-wording | no rank / recommendation / importance / activity / effect wording outside the fixed sentences and the verbatim reference strings | pass | fixture-main:pass, fixture-mutation:pass |
| R-m20-uk3 | M20 request area: the newest same-structure result is pre-selected (no POST) and, its sites being linked, UK3 is shown | pass | fixture-main:pass |
| R-tabs | 구조 분석 hidden and inert while 지식·보고서 shows, run selection only in 구조 분석, the 단백질 공학 and 리간드 tabs' areas and text unchanged by the reaction work | pass | fixture-main:pass |
| C-uk2-none | M20 with no same-structure result: the not-selected notice and UK2 in the request area | pass | fixture-mutation:pass |
| C-preselect | two results on the prepared 1HSG: choosing the structure pre-selects the newest; nothing is posted | pass | fixture-mutation:pass |
| C-prediction | the partial result chosen: UK2 and one line per uncovered chain (B not_in_annotation) before the request; the covered chains line | pass | fixture-mutation:pass |
| C-chains-not-covered | set from the partial result: not_checked (chains_not_covered), covered A, uncovered B not_in_annotation, chain B positions — (not checked) | pass | fixture-mutation:pass |
| C-checked | set from the full result: checked, row counts, catalytic_residue on matched positions with the M-CSA entry id, the checked limitation sentence | pass | fixture-mutation:pass |
| C-lists | conflict and unmatched lists with the M-CSA positions, prominent | pass | fixture-mutation:pass |
| C-release | the released matched position: candidate, its entries kept, "해제됨" | pass | fixture-mutation:pass |
| C-exclusion-seven | seven exclusion reasons in the counts line and the reason filter | pass | fixture-mutation:pass |
| C-limitation-variants | limitation sentence 3: v1 (stored v1 set), not_checked and checked variants verbatim | pass | fixture-mutation:pass |
| C-v1-set | the stored v1 run (copied T1 fixture, events only): not_available, the v1 mark detail, — (v1) cells | pass | fixture-mutation:pass |
| C-picker-marks | "촉매 잔기 검사 안 함" on not-checked sets and none on the checked set: M20 list, M21 handoff, M23 select, M24 sources, M25 protein loop pool | pass | fixture-mutation:pass |
| R-unset | active.json moved aside: not_installed with the import command, the request block closed, stored results open from events with 사용 중 스냅샷 없음 | pass | fixture-unset:pass |
| R-invalid | one set file tampered: snapshot_invalid, the request block closed, stored results open with 사용 중 스냅샷 없음 | pass | fixture-invalid:pass |
| R-stale | set B active: the new hash; every earlier result shows 이전 스냅샷 기준 (list and detail), nothing recomputed | pass | fixture-stale:pass |
| S-fixture-no-egress | every flow row: 0 non-loopback browser requests (no host contacted) and zero provider calls | pass |  |
| S-fixture-references | the reaction set changes (set A, active.json aside, one file tampered, set B) and the M15 import into the isolated folders, read back over the API | pass |  |

| 흐름 단계 | 결과 | 문제 |
|---|---|---|
| fixture-empty | pass |  |
| fixture-main | pass |  |
| fixture-mutation | pass |  |
| fixture-unset | pass |  |
| fixture-invalid | pass |  |
| fixture-stale | pass |  |
| reaction-empty-at-start | pass |  |
| reaction-set-a | pass |  |
| reaction-unset | pass |  |
| reaction-tamper | pass |  |
| reaction-set-b | pass |  |

관찰하지 않은 사례:

- R-late-response: late responses of another run / result are covered by the pure guard tests (frontend/tests/reaction-knowledge.test.cjs reactionResponseCurrent) and the M15/M20 flows' held-response checks of the same pattern; this flow does not hold responses.
- R-too-many-links: the 2,000-link and 1 MiB caps need inputs far larger than the QA structures; covered by backend/tests/test_reaction_knowledge_tool.py (429, nothing stored).
- C-list-too-long: the 400-item conflict / unmatched cap is covered by backend/tests/test_mutation_tool.py (m20_catalytic_fixture long_unmatched).

## 단계 `real` — missing

- stage real was not run in this invocation (--stages fixture)

## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)

```bash
# fixture 단계만 (실서버 요청 0, 합성 세트)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \
    --stages fixture --out docs/qa/m26-reaction-<YYYYMMDD>/fixture-stage
# real 단계만 (실서버 요청 0, 설치된 실제 세트 폴더를 격리 폴더로 복사)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \
    --stages real --reaction-set <installed set folder> --out docs/qa/m26-reaction-<YYYYMMDD>/real-stage
# 두 단계 (수락: 설치된 실제 세트 폴더를 격리 폴더로 복사)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \
    --stages fixture,real --reaction-set <installed set folder> \
    --out docs/qa/m26-reaction-<YYYYMMDD>/acceptance
```
