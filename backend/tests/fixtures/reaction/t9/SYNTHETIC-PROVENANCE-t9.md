# M26 T9 fixture — 오프스크린 수락 QA용 합성 반응 참조 행·합성 파생 구조

2026-10-09 M26 T9b(오프스크린 하네스·수락 실행기)에서 만들었다. **이 폴더의 반응 참조 행은 모두 합성(SYNTHETIC)이고, 두 `.cif`는 공개 구조에서 잔기 이름 하나만 바꾼 합성 파생 구조다.** 실제 M-CSA·UniProt·Rhea 응답이나 그 조각을 담지 않았고, 만드는 동안 실서버 요청은 0건이며 키·자격 증명도 없다. 필드 이름과 값의 형(型)만 명세 §3.3·§3.4(가공 형식)를 따랐다.

- 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다. "대응됨(matched)"은 이 합성 행과 구조의 PDB·체인·번호·잔기 이름이 같다는 뜻뿐이고, 파생 구조의 "충돌(conflict)"은 사람이 바꾼 이름 때문일 뿐 변이 구조·실험 구조가 아니다.
- PDB ID `0T91`·`0T92`(행에는 `0t91`·`0t92`)는 지어낸 값이다(실제 PDB ID는 `0`으로 시작하지 않는다). 수락 QA에서 사람이 저장소의 공개 구조 `../../public_1hsg.cif`(와 그 파생 구조)에 이 PDB ID를 직접 입력한 것으로 보고 연결한다. 1HSG 자체는 M-CSA에 없다(T1 실측).
- M-CSA 항목 ID `691`·`692`, 효소 이름 "SYNTHETIC fixture enzyme t9 …", UniProt accession `Q0SYT9`, EC `9.99.9.11`·`9.99.9.12`·`9.99.9.21`, ChEBI `990901`–`990903`, `EMO_990911`, 역할 문구 "SYNTHETIC fixture role text t9 …"·"fixture function text t9 …"·"fixture ptm t9"는 모두 지어낸 값이다.
- `uniprot_entries_t9.json`의 accession `O14965`는 실제 accession을 그대로 쓴다. 수락 QA가 M15 번호 대응(실제 kbase SIFTS 스냅샷, 1MQ4 체인 A → O14965)으로 UniProt 부위 연결을 시험하려면 반응 스냅샷에도 같은 accession의 행이 있어야 하기 때문이다. **그 행의 내용(항목 이름 `SYNTHETIC_T9_STANDIN`, 단백질 이름, 생물 이름 `Fixtureus syntheticus`, EC, 촉매 활동, 부위 위치 5·160·211–213과 설명)은 모두 지어낸 값이며 UniProt 항목 O14965의 내용이 아니다.** 부위 위치는 1MQ4 구조에 있는 번호(160·211–213, 번호 대응 행 있음)와 없는 번호(5, 번호 대응에 없음)를 고른 것뿐이다.

## 파일

| 파일 | 내용 | SHA-256 |
|---|---|---|
| `derive_structures.py` | 두 파생 구조를 만드는 생성기(표준 라이브러리만, `mw`·gemmi 없음). `--write`로 쓰고 `--check`는 커밋된 파일이 새로 만든 바이트와 같을 때만 0으로 끝난다. | (git) |
| `derived_1hsg_A25_asp_to_glu.cif` | `../../public_1hsg.cif`(SHA-256 `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`)에서 아래 두 가지만 바꾼 파일(212,147바이트). | `a0e5aa06b6f1dc91e3b52e9c9fe82329d7c9232ff3ce025038dbceff01eef920` |
| `derived_1s9i_A194_asp_to_glu.cif` | `../../public_1s9i.cif`(SHA-256 `3db038cdfa23f9d2b8d88e552162fa153c915402827cb4ebb24936171ef08810`, T9a 내려받기)에서 같은 방식으로 바꾼 파일(565,129바이트). 실제 세트 단계(T9c)용. | `c7ffea5813ae8b74d8e457a9e04ab97d16d2d2d023f0eabdef958d31251969ad` |
| `mcsa_entries_t9.json` | 가공 형식 `mcsa/entries.jsonl` 행 둘(691·692, 아래 표). | `d43fc4cc17c6967376526716600e85ff2e465923430ab17434020ffaf66874c0` |
| `uniprot_entries_t9.json` | 가공 형식 `uniprot_function/entries.jsonl` 행 하나(O14965 자리의 합성 행). | `8592ab8f5a91c73fa3c119197c67e4b369e14da171e03efaac8660ed636adecd` |
| `build_qa_set.py` | 수락 실행기가 하위 프로세스로 부르는 세트 생성기. T2 행(`../t2/`)·T6 0SY6 행(`../t6/mcsa_entries_0sy6.json`)·이 폴더의 행을 `reaction_fixture.build_set`(가져오기 명령과 같은 배치)으로 격리 폴더에 쓴다. 건너뜀 목록·요청 기록은 `reaction_fixture`의 합성 기본값이다. `--imported-at`으로 같은 행의 다른 세트(다른 세트 해시)를 만든다. | (git) |

### 파생 구조에서 바꾼 것 (정확히 이것뿐)

1. 첫 줄 `data_1HSG` → `data_1HSG_DERIVED_A25_ASP_TO_GLU` (1S9I는 `data_1S9I` → `data_1S9I_DERIVED_A194_ASP_TO_GLU`). 표시용 이름이며 `_entry.id`는 그대로라 제품의 PDB ID 제안은 원래 항목을 가리킨다(사람이 확인하거나 고친다).
2. `_atom_site`에서 `auth_asym_id`가 `A`이고 `auth_seq_id`가 `25`인 8행(원자 id 192–199, N·CA·C·O·CB·CG·OD1·OD2)의 `label_comp_id`와 `auth_comp_id`만 `ASP` → `GLU`(같은 너비라 열 배치와 그 밖의 바이트는 그대로). 1S9I는 `auth_seq_id` `194`의 8행(원자 id 1057–1064).

바꾸지 않은 것: 원자 이름(`OD1`·`OD2` 그대로), 좌표·점유율·B 인자, 체인 B의 같은 번호 잔기, `_entity_poly_seq`(두 체인이 같은 엔티티라 고치면 체인 B도 바뀜)·`_pdbx_poly_seq_scheme`·`_struct_site_gen` 등 다른 모든 범주. 그래서 파일 안에서 이름이 일부러 서로 맞지 않는다. 이 파일은 "잔기 이름이 M-CSA가 적은 이름과 다르면 충돌로 보인다"를 화면에서 보이기 위한 입력일 뿐이며, 모델링한 변이 구조나 관찰된 구조가 아니다.

### `mcsa_entries_t9.json` 행과 기대 결과(명세 §5.3 규칙으로 손으로 정함)

| 항목/잔기 | PDB·체인·번호·코드 | 공개 1HSG에서 | 파생 1HSG(A25 GLU)에서 |
|---|---|---|---|
| 691/0 | 0t91 A 25 Asp (`is_reference` 참) | ASP A25 대응됨 | 충돌 `residue_name_differs`(구조 이름 GLU) |
| 691/1 | 0t91 B 25 Asp (`is_reference` 거짓) | ASP B25 대응됨 | (요청하지 않음) |
| 691/2 | 0t91 A 27 Gly (`roles_summary` 빈 문자열) | GLY A27 대응됨 | 대응됨 |
| 691/3 | 0t91 B 27 Gly (`roles` 빈 목록, `ptm` 있음) | GLY B27 대응됨 | — |
| 691/4 | 0t91 A 29 Glu | ASP A29 → 충돌 `residue_name_differs` | 같음 |
| 691/5 | 0t91 A 150 Lys | 구조에 없음 → 대응 없음 `residue_not_in_structure` | 같음 |
| 691/6 | 0t91 A (번호 없음) Cys | 대응 없음 `no_author_number` | 같음 |
| 692/0–59 | 0t92 A 1–60, 1HSG 체인 A 서열과 같은 코드 | 60행 모두 대응됨(행 쪽 넘김 시험용) | — |

합친 세트에서의 나머지 기대(0SY6·0SY2 행, 건너뛴 accession, UniProt·Rhea 행)는 `../t2/SYNTHETIC-PROVENANCE-t2.md`·`../t6/SYNTHETIC-PROVENANCE-t6.md`의 표와 같고, 수락 실행기의 계획(`scripts/m26_offscreen_acceptance.py` `fixture_plan`)에 체인마다 적혀 있다. 하네스는 화면을 늘 API로 다시 읽은 저장 결과와 비교하고, 계획의 기대는 그 저장 결과가 위 표와 같은지 본다.

## 쓰는 곳

- `scripts/m26_offscreen_acceptance.py` fixture 단계: 격리 폴더에 `build_qa_set.py`로 세트 A를 설치하고, 같은 행으로 세트 B를 만들어 "이전 스냅샷 기준"을 본다. `frontend/tests/offscreen/reaction-knowledge-flow.cjs`가 1HSG·파생 1HSG를 실제 업로드해 PDB ID 0T91·0T92를 입력하고, `mutation-flow.cjs`(모드 `catalytic`)가 전처리한 1HSG에 0T91 결과를 만들어 M20 v2 촉매 칸을 본다.
- 실제 세트 단계(T9c): `derived_1s9i_A194_asp_to_glu.cif`를 1S9I(M-CSA 282 체인 A)의 충돌 사례로 쓴다.
- `scripts/test_m26_offscreen_acceptance.py`: 계획의 기대가 이 파일들의 행을 가리키는지, 파생 구조가 원본과 잔기 이름만 다른지 독립적으로 확인한다.
