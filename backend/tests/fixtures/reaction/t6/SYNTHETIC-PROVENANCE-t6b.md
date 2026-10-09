# M26 T6b fixture — 소비자(M21·M23·M24·M25) 시험용 저장된 M20 v2 후보 집합과 합성 M-CSA 행

2026-10-09 M26 T6b(두 세대 소비자)에서 만들었다. **반응 참조 자료는 모두 합성(SYNTHETIC)이다.** 실제 M-CSA·UniProt·Rhea·RCSB 응답이나 그 조각을 담지 않았고, 만드는 동안 네트워크 요청은 0건이며 키·자격 증명도 없다. T6a의 `SYNTHETIC-PROVENANCE-t6.md`(0SY6 행)는 고치지 않았다.

## `mcsa_entries_0sy8.json` (합성 M-CSA 가공 행, 명세 §3.3 모양)

- PDB ID `0SY8`(행에는 `0sy8`)은 지어낸 값이다(실제 PDB ID는 `0`으로 시작하지 않는다). 시험이 저장소의 공개 구조 `../../public_1ubq.cif`(유비퀴틴)에 사람이 이 PDB ID를 준 것으로 보고 `link_reaction_knowledge`를 부른다. 유비퀴틴은 M-CSA 항목이 아니다(T1 실측: 1UBQ는 M-CSA에 없음).
- M-CSA 항목 ID `611`, 효소 이름 "SYNTHETIC fixture enzyme t6b (1UBQ stand-in)", UniProt accession `Q0SYN8`, EC `9.99.6.11`, `EMO_900611`, 역할 문구 "SYNTHETIC fixture roles summary …"·"fixture function text …"는 모두 지어낸 값이다. 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다. "대응됨(matched)"은 이 합성 행과 구조의 PDB·체인·번호·잔기 이름이 같다는 뜻뿐이다.
- 손으로 정한 행(체인 A, 모두 `is_reference: true`)과 1UBQ에서의 결과(§5.3 규칙):

| 항목/잔기 | 번호·코드 | 1UBQ 체인 A에서의 결과 |
|---|---|---|
| 611/0 | 6 Lys | LYS A6과 대응됨 |
| 611/1 | 68 His | HIS A68과 대응됨 |
| 611/2 | 76 Ala | GLY A76 → 충돌 `residue_name_differs` |
| 611/3 | 300 Lys | 구조에 없음 → 대응 없음 `residue_not_in_structure` |

UniProt·Rhea 행은 T2 합성 행(`../t2/`)을 그대로 쓴다. 세트는 `backend/tests/m20_v2_fixture.py`의 `activate_ubq`가 `reaction_fixture.build_set`(가져오기 명령과 같은 배치)으로 pytest 임시 폴더에 쓴다.

## `m20-candidate-set-v2-1ubq-{not_checked,checked}.json` (저장된 v2 후보 집합)

- 만든 명령: `PYTHONPATH=backend .venv/bin/python backend/tests/fixtures/reaction/t6/build_v2_fixtures.py --write`(두 번 만든 결과가 같을 때만 씀, `--check`는 새로 만든 결과와 바이트를 비교). 기준 코드: 작업 브랜치 `dryforge/m26-t6b`(T6a 병합 `b5b31bf` 위, M20 v2 `mutation_candidates.py` SHA-256 `6436a06251d2…b8a3b66c82a62`).
- 입력: run id `run_m26_t6b_v2`, 파일 경로로 불러온 공개 1UBQ(`load_structure`) → 기본값 `prepare_structure` → 제품 M20 v2 도구 `generate_mutation_candidates`(`Run.call`). 위치는 `../../sequence_ga/m20-candidate-set-1ubq-tiny.json`과 같은 사용자 목록(ILE3·LYS6·ILE44·GLY76, ILE3 사용자 보호, 허용 잔기 `AW`)이며 시험용 선택이지 설계 제안이 아니다.
- `not_checked`: 촉매 주석 없음. `catalytic_residue_database = {status: not_checked, reason: annotation_not_given, annotation: null}`, 모든 위치의 `protection.catalytic`은 null, 한계 문장 셋째는 M20-3(`not_checked`) 변형. 후보 6개.
- `checked`: 같은 run에서 위 0SY8 세트로 `link_reaction_knowledge`(PDB `0SY8`, 체인 A, accession 없음, 번호 대응 없음)를 부른 결과를 `catalytic_annotation`으로 준 집합. 체인 A가 `covered`라 `status: checked`, `matched_rows 2`·`conflict_rows 1`(A76)·`unmatched_rows 1`(A300). LYS6은 `catalytic_residue`로 보호되어 후보가 없고(합성 행 때문일 뿐 실제 촉매 잔기라는 뜻이 아니다), ILE44·GLY76에 후보 4개. 반응 결과 객체 자체는 저장하지 않았다(집합의 handle 값으로만 남음 — 소비자는 집합을 `validated_set`으로만 검증한다).
- 각 파일은 `{handle, content}`의 정규 JSON + 줄바꿈이다. 후보는 위치와 바꿀 잔기의 조합일 뿐이고 점수·순위·안정성·ΔΔG·활성을 뜻하지 않는다.
- **저장된 집합이다.** 이후 M20 코드가 바뀌면 `--check`는 설계상 실패할 수 있고, 저장된 사본은 그대로 둔다(일부러 다시 기록할 때만 `--write`). v1 저장 fixture(`../t1/`, `../../sequence_ga/m20-candidate-set-*.json`)는 건드리지 않았다.

| 파일 | handle | SHA-256 |
|---|---|---|
| `mcsa_entries_0sy8.json` | — | `428d49ebdea842f96a7cad0ff79239bdf3522ec90b61263eb364dead8b7041b6` |
| `m20-candidate-set-v2-1ubq-not_checked.json` | `obj://run_m26_t6b_v2/mutation_candidate_set/48fdbef1…6376` | `3c549ecac68efa92fa0d5bf693be1d6cb5483bbe43eaaa5ba4891bba5c4c45c0` |
| `m20-candidate-set-v2-1ubq-checked.json` | `obj://run_m26_t6b_v2/mutation_candidate_set/738bf7e9…9d04` | `a81d491bbbf59ac7473c7a4e970025ddb147882e3ed0f1eaf048de2152882d3d` |

## 쓰는 곳

- `backend/tests/m20_v2_fixture.py`: 0SY8 세트 설치(`activate_ubq`)·연결(`link_ubq`)·두 집합 만들기(`make_sets`)와 저장된 집합을 같은 run id의 run에 `store.put`으로 넣기(`stored_world`, M20 도구 호출 없음).
- `backend/tests/jev_send_fixture.py`의 `stored_set_world`, `test_jev_projection.py`·`test_jev_sends.py`·`test_jev_reports.py`: M24 투영·본문·전송·제안·보고서에서 v1(`../t1/`)은 기존 J6 바이트, v2 `not_checked`는 J6n, `checked`는 J6c(명세 §9).
- `test_mutation_model_inputs.py`(저장된 두 집합의 M21 입장), `test_mutation_model_jobs.py`·`test_sequence_ga_inputs.py`·`test_jev_loops_api.py`(0SY8 세트로 도구가 그 자리에서 만든 `checked` 집합을 M21 실제 작업·M23 입장·M25 단백질 루프 풀이 받음).
