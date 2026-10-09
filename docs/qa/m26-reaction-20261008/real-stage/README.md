# M26 효소 반응 지식 오프스크린 수락 QA 증거

- 생성: 2026-10-09T03:32:50.445562+00:00 · verdict **pass** · acceptance **false** (두 단계가 이번 실행에서 모두 돌고 통과할 때만 true)
- 요청한 단계: real · 빠진 단계: fixture
- 사례: 19/19 통과
- 빌드: {"buildId": "4-fB1d-vH135JEpv-hR4g", "gitHead": "b3131fd74c174b6cda84418fb53b00cc08dac03a", "buildCurrentWithSource": true, "gitStatusPorcelainSha256": "7283bad556333c438bb3333921e8c9de3576afabc952146954b98d44234ab2aa", "dirtyFiles": [" M frontend/tests/offscreen/jev-flow.cjs", " M frontend/tests/offscreen/mutation-flow.cjs", " M frontend/tests/offscreen/reaction-knowledge-flow.cjs", " M scripts/m26_offscreen_acceptance.py", " M scripts/test_m26_offscreen_acceptance.py"], "recordedAt": "2026-10-09T03:31:56.604369+00:00", "codeRoot": "<repo>", "harnessSha256": {"reaction-knowledge-flow.cjs": "9364111cd11de0fd93c12035d40f0d4028327c9fb58fea260c3e75ead4b36d7f", "mutation-flow.cjs": "f3312872f81a88a3c5ba6299b53f36863acc568fd7476cabfce6979a2253c53f", "driver.cjs": "92af5114465812a096f88dfee0fe6ef73d851f051f25cef61139b3e72467b8eb", "main.cjs": "afb73f99c288d0040759a511210b6d63e07f7c47178f68940747731c9f17174a", "normal-flow.cjs": "fa5712e698b94c26ec5b1853b3029e151ae4f43b9a4a9a1f1f314ff3e288be3d"}, "runnerSha256": "e167bf27e2c7f2fbe78de51e3c99009f5fb59f08f5622ff19ca89ff339fe0f5a"}
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0 · 접촉한 외부 호스트: 없음

**real 단계의 반응 참조값은 설치된 실제 세트를 격리 폴더로 복사한 것이다**(`--reaction-set`, M-CSA·UniProt·Rhea 공개 서버에서 가져온 가공본, CC BY 4.0, 세트 해시는 대장 `checks.real.reaction.copy`). 구조는 공개 PDB 항목 1S9I·1A30·1A4I(RCSB CC0)와 저장소의 1HSG·1MQ4·1UBQ이고, 1S9I 파생 구조(ASP A194 → GLU, `derived_1s9i_A194_asp_to_glu.cif`)만 합성(SYNTHETIC)이다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 숫자는 개수, 상태는 닫힌 집합 값이다. 잔기의 역할·활성이나 변이의 효과를 판정하지 않는다.

스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 단계 `fixture` — missing

- stage fixture was not run in this invocation (--stages real)

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
| X-wording | no rank / importance / activity wording outside fixed sentences and reference strings | pass | real-main:pass, real-mutation:pass |
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
