# M26 T6 fixture — M20 v2 촉매 잔기 보호 시험용 합성 M-CSA 행

2026-10-08 M26 T6a(M20 후보 집합 v2 핵심)에서 만들었다. **이 폴더의 모든 자료는 합성(SYNTHETIC)이다.** 실제 M-CSA·UniProt·Rhea·RCSB 응답이나 그 조각을 담지 않았고, 만드는 동안 네트워크 요청은 0건이며 키·자격 증명도 없다. 필드 이름과 값의 형(型)만 명세 §3.3·§3.4(가공 형식 `mcsa/entries.jsonl`)를 따랐다.

- PDB ID `0SY6`(행에는 `0sy6`)과 `0SY7`(어느 행에도 없음)은 지어낸 값이다(실제 PDB ID는 `0`으로 시작하지 않는다).
- 행이 가리키는 구조는 저장소의 합성 구조 `backend/tests/fixtures/mutation/synthetic-mutation-fixture.cif`(M20 T2 합성, 체인 A·B·CC)다. 사람이 그 구조에 PDB ID `0SY6`을 준 것으로 보고 `link_reaction_knowledge`를 부른다.
- UniProt accession `Q0SYN1`·`Q0SYN2`·`Q0SYN5`, EC `9.99.6.x`, `EMO_900601`은 지어낸 값이다. 역할 문구는 "SYNTHETIC fixture roles summary …", "fixture function text …" 같은 표시 문자열이다.
- 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다. "대응됨(matched)"은 이 합성 자료에서 PDB·체인·번호·잔기 이름이 같다는 뜻뿐이다.

`mcsa_entries_0sy6.json`은 저장소 밖 일회용 생성기(scratchpad, 커밋하지 않음)로 위 표대로 손으로 정한 값을 JSON으로 썼다. UniProt·Rhea 행은 T2 합성 행(`fixtures/reaction/t2/`)을 그대로 쓴다.

| 항목/잔기 | 체인·번호·코드 | 그 구조에서의 결과(§5.3 규칙) |
|---|---|---|
| 601/0 | A 6 His | HID A6과 대응됨(M12 이름 대응), 기준 구조 행 |
| 601/1 | A 26 Asp | ASP A26과 대응됨, `is_reference` 거짓(기준 구조 아닌 행도 보호함을 시험) |
| 601/2 | A 9 Met | MSE A9(표준 밖 이름) → 충돌 `residue_name_differs` |
| 601/3 | A 10 Leu | LEU A10과 ILE A10A(같은 번호 둘) → 대응 없음 `ambiguous_residue_number` |
| 601/4 | A 99 Lys | 구조에 없음 → 대응 없음 `residue_not_in_structure` |
| 601/5 | A (번호 없음) Cys | 대응 없음 `no_author_number` |
| 601/6 | A 5 Cys | CYS A5와 대응됨 |
| 601/7 | A 2 Ala | ALA A2와 대응됨(주사슬 위치 문구) |
| 601/8 | B 6 His | HID B6과 대응됨 |
| 601/9 | B 2 Ala | ALA B2와 대응됨(`ptm` 문구 있음) |
| 601/10 | B 13 Asn·Asp(두 멤버) | 충돌 `mcsa_rows_disagree` |
| 601/11 | A 3 X | 대응 없음 `non_standard_code` |
| 602/0 | A 6 His | HID A6과 대응됨(한 잔기에 두 항목), `is_reference` 거짓 |
| 602/1 | A 27 His | HIS A27과 대응됨 |
| 602/2 | B 7 Val | VAL B7과 대응됨 |

체인 CC에는 행이 없다(요청에 넣으면 `chain_not_listed`). 목록 상한 시험은 `backend/tests/m20_catalytic_fixture.py`가 601/4를 본떠 번호 1000부터 구조에 없는 체인 A 잔기를 가진 항목 603을 테스트 안에서 덧붙인다(401개 → 대응 없음 405개로 거절, 396개 → 정확히 400개로 통과).

## 쓰는 곳

- `backend/tests/m20_catalytic_fixture.py`: 위 행과 T2 UniProt·Rhea 행으로 가져오기 명령과 같은 배치의 합성 세트를 pytest 임시 폴더에 만들고(`reaction_fixture.build_set`, `MW_REACTION_REFERENCE_DIR`), 제품 도구 `link_reaction_knowledge`로 결과를 만든다.
- `backend/tests/test_mutation_tool.py`·`test_mutation_api.py`·`test_mutation_reports.py`: M20 v2 보호 판정·입장 검사·읽기·보고서 시험. 기대값은 위 표에서 손으로 쓴 값과 저장된 결과 행에서 시험 코드가 다시 도출한 값이다.
- `backend/tests/test_mutation_candidates.py`의 순수 함수 시험은 이 파일을 읽지 않고 같은 모양의 합성 행을 시험 안에서 손으로 만든다.
