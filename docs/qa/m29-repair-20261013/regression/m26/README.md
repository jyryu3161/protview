# M26 효소 반응 지식 오프스크린 수락 QA 증거

- 생성: 2026-10-13T16:06:10.213512+00:00 · verdict **pass** · acceptance **true** (두 단계가 이번 실행에서 모두 돌고 통과할 때만 true)
- 요청한 단계: fixture, real · 빠진 단계: 없음
- 사례: 58/58 통과
- 빌드: {"buildId": "zHxijM08Zpd_R8U7RDu8X", "gitHead": "5fe7f208c0e544e92382fc0f87f93c0795c9245c", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "b9355b8ac813f75d14bf5ab2e03af96da626d3610e6bca03386154cbd5193c70", "dirtyFiles": ["?? docs/qa/m29-repair-20261013/regression/"], "recordedAt": "2026-10-13T16:04:19.167699+00:00", "codeRoot": "<repo>", "harnessSha256": {"reaction-knowledge-flow.cjs": "6ee3b14cbdc2b15034c2bc11b01aaa76cd2203699bb4349cad841b73047eef6e", "mutation-flow.cjs": "e971c3571d4a26b0584ddd29c58df76730e08a9d1d7385fb9992514fae200165", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "51e3ea61d46eb8b32e0ff078b58615abccea1294b516f51d2b6d9dba8c94a352"}
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0 · 접촉한 외부 호스트: 없음

**fixture 단계의 반응 참조값(M-CSA·UniProt·Rhea 행)은 모두 합성(SYNTHETIC)이다.** `backend/tests/fixtures/reaction/t9/build_qa_set.py`가 T2·T6·T9 합성 행으로 만든 세트이며 (`SYNTHETIC-PROVENANCE-t2.md`·`-t6.md`·`-t9.md`), 지어낸 PDB ID(0T91·0T92·0SY6·0SY2 등)를 사람이 구조에 준 것으로 보고 입력했다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 과학 결과가 아니다. 촉매 잔기·부위·반응에 대한 사실이나 변이의 효과를 뜻하지 않는다.

**real 단계의 반응 참조값은 설치된 실제 세트를 격리 폴더로 복사한 것이다**(`--reaction-set`, M-CSA·UniProt·Rhea 공개 서버에서 가져온 가공본, CC BY 4.0, 세트 해시는 대장 `checks.real.reaction.copy`). 구조는 공개 PDB 항목 1S9I·1A30·1A4I(RCSB CC0)와 저장소의 1HSG·1MQ4·1UBQ이고, 1S9I 파생 구조(ASP A194 → GLU, `derived_1s9i_A194_asp_to_glu.cif`)만 합성(SYNTHETIC)이다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 숫자는 개수, 상태는 닫힌 집합 값이다. 잔기의 역할·활성이나 변이의 효과를 판정하지 않는다.

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

## 단계 `real` — pass

| 사례 | 내용 | 결과 | 단계 |
|---|---|---|---|
| X-snapshot-real | the copied real set: hash, three sources with dates, CC BY 4.0, row counts, skipped list | pass | real-main:pass |
| X-request-defaults | nothing chosen by itself on 1S9I: the file's PDB ID suggestion unconfirmed, no chain ticked, no numbering map, 연결하기 disabled | pass | real-main:pass |
| X-matched-real | 1S9I chain A covered by M-CSA 282 (loaded and prepared): rows 0 and 1 matched with the 7-field identity, the role text verbatim in "M-CSA 원문, 계산 아님", the reference-structure flag, the reaction section (EC of both sources, M-CSA compounds, UniProt activities with Rhea equations); chain B chain_not_listed with UK4 | pass | real-main:pass |
| X-two-chains | 1A30: chains A and B both covered by M-CSA 175, three matched rows each | pass | real-main:pass |
| X-two-entries | 1A4I chain A: M-CSA entries 389 and 458 both listed (none chosen), six matched rows | pass | real-main:pass |
| X-conflict-derived | labelled synthetic derived 1S9I (ASP A194 renamed GLU): the A194 row is 충돌 (residue_name_differs) with the structure name GLU, the A221 row matched | pass | real-main:pass |
| X-pdb-not-in-snapshot | 1UBQ and 1HSG: pdb_not_in_snapshot, the empty result; prepared 1MQ4: pdb_not_in_snapshot with the UniProt part only | pass | real-main:pass |
| X-uniprot-link | the real M15 numbering maps of prepared 1S9I (P36507) and 1MQ4 (O14965) in the isolated folder: UniProt sites linked through the map (mapped 11 / not_in_map 2 and 9 / 0, the stored counts) | pass | real-main:pass |
| X-report | report of the 1S9I result + Markdown / JSON downloads equal to the backend bytes, RK1–RK6, no forbidden word outside fixed sentences and reference strings, the library entry | pass | real-main:pass |
| X-dry-run | a dry-run run (record over the loopback API) links 1UBQ by real clicks and stores the result | pass | real-main:pass |
| X-results-list | the result list equals the stored list; counts not made are — with the reason | pass | real-main:pass |
| X-m20-uk3 | M20 request area on prepared 1S9I: the newest same-structure result (linked through the map) is pre-selected, UK3 shown, nothing posted | pass | real-main:pass |
| X-no-zero | not checked / not available / not computed values are — with the reason, never 0 | pass | real-main:pass, real-mutation:pass |
| X-wording | no rank / recommendation / importance / activity / effect wording outside fixed sentences and reference strings | pass | real-main:pass, real-mutation:pass |
| X-tabs | 구조 분석 hidden and inert, run selection only there, other tabs unchanged | pass | real-main:pass |
| X-m20 | M20 v2 on prepared 1A30 with the real results: UK2 without a result, pre-selection of the newest, the chain-A result → chains_not_covered (B not_in_annotation), the A+B result → checked with M-CSA 175 rows protecting the matched positions (ARG A8 checked, none), empty conflict / unmatched lists, release → 해제됨; labelled derived 1S9I → checked with its conflict row in the conflict list | pass | real-mutation:pass |
| X-picker-marks | "촉매 잔기 검사 안 함" on not-checked sets and none on the checked 1A30 set: M20 list, M21 handoff, M23 select, M24 sources, M25 protein loop pool | pass | real-mutation:pass |
| S-real-no-egress | every flow row: 0 non-loopback browser requests (no host contacted) and zero provider calls | pass |  |
| S-real-references | the reaction set copied into the isolated folder and the M15 import, read back | pass |  |

| 흐름 단계 | 결과 | 문제 |
|---|---|---|
| real-main | pass |  |
| real-mutation | pass |  |
| reaction-copy | pass |  |

관찰하지 않은 사례:

- X-unmatched-reasons: the real set gave no unmatched row and no conflict row on the public structures (import1.md §4); the one conflict here is the labelled derived 1S9I. The five unmatched and two conflict reasons, refusals, field errors, paging, link reasons and the unset / invalid / stale snapshot states are observed on synthetic rows in the fixture stage.
- X-v1-set: the stored v1 run and the three limitation variants are the fixture stage's (C-v1-set, C-limitation-variants); this stage makes v2 sets only.

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
