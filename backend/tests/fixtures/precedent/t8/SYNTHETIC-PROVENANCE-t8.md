# M27 T8 fixture — 오프스크린 수락 QA의 합성 전례 세트와 합성 파생 번호 대응

2026-10-10 M27 T8(오프스크린 하네스·수락 실행기)에서 만들었다. **이 폴더가 만드는 전례 자료는 모두 합성(SYNTHETIC)이다.** 실제 kbase_kinase 레코드·인용문·관찰 문장·서지 제목이나 그 조각을 하나도 담지 않았고, 만들 때 네트워크 요청은 0건이며 키·자격 증명도 없다. 이 폴더에는 실행 스크립트 `build_qa_set.py`와 이 문서뿐이고, 만든 세트는 저장소에 커밋하지 않는다(수락 실행기 `scripts/m27_offscreen_acceptance.py`가 Git 제외 QA 루트의 격리 폴더에 그때마다 만든다).

## `build_qa_set.py set` — 합성 전례 참조 세트

`backend/tests/precedent_fixture.py`의 `make_move`·`make_reference`·`make_pubmed_row`·`build_set`(가져오기 명령과 같은 배치·매니페스트 규칙)으로 만든다. 값은 아래 표대로 코드에서 정했다.

| 내용 | 값 (모두 지어낸 것) |
|---|---|
| accession | `P0QA01`·`P0QA02`·`P0QA03`·`P0QA04` — UniProt accession 형식에만 맞춘 값이며 실제 항목을 뜻하지 않는다. 실제 accession `O14965`는 세트에 일부러 넣지 않았다(실제 M15 번호 대응이 이 accession을 주면 `not_in_kbase_references`가 되는 화면 사례). |
| `moves` | `P0QA01` 30건 `MOVE-7001`–`7030`(두 쪽 분량; 변이 표기 `not_reported` 20·`SYN-A1V` 6·`SYN-G2C` 4, 태그는 site·goal·tactic 순환, 해석 근거 gene·alias·name_token·pubmed_title·notation), `P0QA04` 2건 `MOVE-7101`–`7102`, 표적 미해석 2건(`MOVE-7501` unmapped `SYN-QA-UNRESOLVED-A`, `MOVE-7502` absent 이름 없음). |
| `moves_flagged` | `P0QA01` 6건 `MOVE-7201`–`7206`, `P0QA02` 3건 `MOVE-7301`–`7303`(`moves`에는 없는 표적), `P0QA04` 40건 `MOVE-7401`–`7440`(관찰 문장에 합성 채움 글자 약 25 KB씩 — `moves_flagged`를 넣으면 결과가 1 MiB를 넘는 크기 시험용), 표적 미해석 2건(`MOVE-7601` ambiguous 후보 둘, `MOVE-7602` unmapped). |
| 상세 사례 | `MOVE-7001`: 위치 셋(table·text·figure), 측정 변화 셋(on_target numeric `fold_change` 10.0 / off_target text null / not_applicable none null), 구조 연결 하나, 교환 둘(인용 null 하나), 관찰 인용 `quote_truncated` 참, `checks.quote_in_source.quote_assembled` 하나, `duplicate` fail·`chembl_crosscheck` lookup_failed. `MOVE-7007`: 관찰 문장에 검색어 `QA-SEARCH-ALPHA`. `MOVE-7009`: 26단어 인용(`quotes_within_limit` 거짓), 서지 없는 PMID. |
| 참조 | `REF-QA-0001`·`REF-QA-0002`(`P0QA01`, 한 accession에 참조 둘), `REF-QA-0003`(`P0QA02`), `REF-QA-0004`(`P0QA04`). `P0QA03`은 참조·전례 없음. |
| 서지 | PMID `91000001`–`91000007`(현재 실제 PMID 범위 밖): `91000001` 모든 필드(DOI `10.0000/synthetic.qa1`, PMC `PMC0000091`), `91000003` 제목에 검색어 `QA-TITLE-BETA`, `91000006` 연도·저널 null, `91000007` 연도 `n.d.`(정수 아님). `91000008`–`91000010`은 서지 행이 없다(서지 없음). |
| kbase 블록 | `precedent_fixture.KBASE`(커밋 `c0de…`·`d157…`, `kb_version` `kbv1:synthetic-fixture`)와 서지 스냅샷 ID·라이선스 `synthetic-fixture-license` — 합성 값. |

`expect`(출력)는 이 파일이 만든 레코드에서 직접 센 값이다(제품 코드를 부르지 않음): accession별 `moves`·`moves_flagged`·참조 수와 변이 표기별 수, 표적 미해석 합계, 하네스가 누르는 필터(파일·site·site OR·site+goal AND·변이·검색어 둘)의 건수와 `move_id` 목록. 수락 실행기는 이 값으로 화면 기대를 세운다.

## `build_qa_set.py derive` — 합성 파생 번호 대응

수락 실행기가 백엔드를 멈춘 사이에 실행해, M15 도구가 화면 클릭으로 **실제로 만든** `residue_numbering_map@1` 하나를 같은 run 저장소에서 읽고(`produced_by`가 합성이면 거절), 그 사본의 `mapped` 행 `uniprot_accession`만 바꾼 변형을 `ObjectStore.put`(`produced_by: synthetic_fixture`, 객체 안 `qa_fixture` 표시)으로 저장한다. 체인에 accession 둘을 주면 그 체인 mapped 행의 앞 절반에 첫째, 나머지에 둘째를 준다(융합 체인 사례). 그 밖의 번호 대응 내용은 M15가 쓴 그대로다.

| 단계 | 원본(실제 M15 번호 대응) | 변형 |
|---|---|---|
| fixture | 파생 2체인 1MQ4 fixture(`structures_m15/derived_1mq4_two_chain_fixture.pdb`) 체인 A·B를 `O14965`로 고른 것 | `d-two` A→`P0QA01`, B→`P0QA02` · `d-fusion` A→`P0QA01`+`P0QA03`(multiple_accessions), B→`P0QA03` · `d-big` A→`P0QA04`, B→`P0QA01` |
| real | 공개 1FIN 체인 A·C(PDB ID 확인, SIFTS `P24941`) | `d-size` A→`P00533`, C→`Q06187` — 이런 구조는 없다. 실제 세트에서 `moves_flagged`를 넣은 요청이 1 MiB를 넘는지만 보려는 것이며(거절되어 저장되지 않음) 결과로 쓰지 않는다. |

## 쓰는 곳

- `scripts/m27_offscreen_acceptance.py`: fixture 단계에서 `set`(세트 A와 같은 레코드에 다른 `imported_at`의 세트 B)과 `derive`를 하위 프로세스로 실행한다.
- `scripts/test_m27_offscreen_acceptance.py`: `set` 출력의 기대값과 `DERIVED` 설계를 확인한다.
