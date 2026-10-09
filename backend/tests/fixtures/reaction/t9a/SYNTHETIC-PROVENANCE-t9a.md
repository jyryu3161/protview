# M26 T9a fixture — 동형체 위치 부위 건너뜀 시험용 합성 UniProt 응답

2026-10-09 M26 T9a에서 만들었다. **이 폴더의 모든 자료는 합성(SYNTHETIC)이다.** 실제 UniProt 응답이나 그 조각을 담지 않았고, 만드는 동안 실서버 요청은 0건이며 키·자격 증명도 없다. 필드 이름·중첩·값의 형(型)만 명세 §3.4와 T3 합성 fixture(`../t3/uniprot_entry_raw.json`)를 따랐고, 값은 모두 손으로 지어냈다.

배경: T9a가 실제 공개 서버 응답을 오프라인으로 다시 돌려 보니 한 항목의 결합 부위 3개가 `location`에 `sequence` 키(같은 accession의 동형체 `<accession>-<n>`)를 갖고 있어 가져오기가 형식 오류로 멈췄다. 사용자 결정(2026-10-09, 명세 §3.4 UniProt 항목): 그런 부위는 정규 서열 위치가 아니므로 저장하지 않고 건너뛰고, 건너뛴 개수는 가져오기 명령 출력에만 보이며 세트에는 남기지 않는다. 다른 `sequence` 값이나 그 밖의 알 수 없는 `location` 키는 여전히 형식 오류다. 이 fixture는 그 규칙만 시험한다(실제 항목의 값은 쓰지 않았다).

- accession `Q0SYT1`·`P0SYT2`, 동형체 이름 `Q0SYT1-2`·`Q0SYT1-3`·`P0SYT2-2`는 명세 §4.1 형식에만 맞춘 지어낸 값이다. 항목 이름 `SYT9_SYNTH`, EC `9.99.9.1`(존재하지 않는 9번 계열), ChEBI `CHEBI:9939xx`, Rhea `RHEA:93901`, 증거 코드 `ECO:9999999`, UniParc `UPISYNTHETIC0009`, 생물 이름 `Synthetica fixturae`도 지어낸 값이다. 이름·설명·반응식은 "SYNTHETIC …", "synthetic …" 같은 표시 문자열이다.
- 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다.

| 파일 | 내용 |
|---|---|
| `uniprot_entry_isoform_raw.json` | UniProt `/uniprotkb/accessions` 결과 원소 하나 모양. 부위 다섯: 정규 위치 Active site 하나, `location.sequence = "Q0SYT1-2"`인 Binding site 하나(건너뜀), 정규 위치 Binding site 하나(같은 리간드), `location.sequence = "Q0SYT1-3"`이고 위치 수식어가 `UNKNOWN`인 Site 하나(건너뜀 — 저장하지 않는 부위의 위치는 해석하지 않음), 정규 위치 Site 하나. 촉매 활동 하나와 EC 하나. |
| `uniprot_entry_isoform_processed.json` | 위 응답에서 명세 §3.3·§3.4대로 손으로 쓴 기대 가공 행: 동형체 위치 부위 둘을 뺀 나머지 그대로(정규 부위 셋, 촉매 활동, EC, 이름). 제품 출력이 아니라 시험의 기대값이다. |

## 쓰는 곳

- `scripts/test_import_reaction_references.py`의 "isoform-located sites" 절: 가공 함수 단독 비교(건너뛴 부위 수 2), T3 가짜 서버 세계에 이 항목을 넣은 전체 가져오기(설치·행 그대로·출력의 건너뜀 개수·세트 파일에 개수나 동형체 이름이 없음), 다른 accession의 동형체·형식이 다른 `sequence` 값·`location`의 다른 알 수 없는 키가 형식 오류로 멈추고 아무것도 쓰지 않음.
