# M26 T3 fixture — 가져오기 명령 시험용 합성 서버 응답

2026-10-08 M26 T3(가져오기 명령 `scripts/import_reaction_references.py`)에서 만들었다. **이 폴더의 모든 자료는 합성(SYNTHETIC)이다.** 실제 M-CSA·UniProt·Rhea 응답이나 그 조각을 하나도 담지 않았고, 만드는 동안 실서버 요청은 0건이며 키·자격 증명도 없다. 필드 이름·중첩·값의 형(型)만 T1 실측 기록(`docs/qa/m26-reaction-20261008/preflight-network.md`의 (a) 모양 기록)과 명세 §3.4를 따랐고, 값은 모두 손으로 지어냈다.

- UniProt accession `Q0SYT1`·`P0SYT2`·`Q0SYT3`·`Q0SYU9`·`P0SYU1`·`Q0SYU2`·`Q0SYZ9`, 시험 코드가 만드는 `A0SYN<n>T<nnn>` 꼴 10자 accession은 명세 §4.1 형식에만 맞춘 지어낸 값이며 실제 항목을 뜻하지 않는다.
- PDB ID `0sy7`(실제 PDB ID는 `0`으로 시작하지 않는다), EC 번호 `9.99.3.*`(존재하지 않는 9번 계열), ChEBI ID `993xxx`·`CHEBI:993xxx`·`X00699`, Rhea ID `RHEA:94`·`RHEA:9310`·`RHEA:93002`·`RHEA:93003`·`RHEA-COMP:93009`, EMO ID `EMO_9900n`, 증거 코드 `ECO:9999999`, 생물 이름 `Synthetica fixturae`·`Synthetica secunda`, UniParc `UPISYNTHETIC000n`도 지어낸 값이다. 이름·반응식·역할 문구는 "SYNTHETIC fixture …", "synthetic …" 같은 표시 문자열이다.
- 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다.

| 파일 | 내용 |
|---|---|
| `mcsa_entry_raw.json` | M-CSA `entries` 목록 응답의 `results[]` 원소 하나 모양(가공 전). 가공에서 버리는 필드(`is_reference_uniprot_id`·`url`·`description`·`protein`·`reaction.mechanisms`·`reaction.is_polymeric`·`compounds[].count`·`compounds[].mol_file`·`residues[].mcsa_id`·`main_annotation`·`domain_name`·`domain_cath_id`·`residue_sequences[].resid`)를 모두 담고, `assembly`가 정수인 행과 빈 문자열인 행, `auth_resid` null, 빈 `roles`, 빈 `residue_chains`, 빈 `residue_sequences[].uniprot_id`, `"Q0SYT1, P0SYT2"`처럼 여럿을 이은 `reference_uniprot_id`, 정렬되지 않은 `all_ecs`, 같은 화합물 두 번, ChEBI가 아닌 `X00699`를 넣었다. |
| `mcsa_entry_processed.json` | 위 응답에서 명세 §3.3·§3.4대로 손으로 쓴 기대 가공 행(허용 필드만, `assembly` "" → null, `all_ecs` 오름차순, 문자열 그대로, 객체 목록 순서 유지). 제품 출력이 아니라 시험의 기대값이다. |
| `uniprot_entry_raw.json` | UniProt `/uniprotkb/accessions` 결과 원소 하나 모양(Swiss-Prot 꼴). EC가 `recommendedName`·`alternativeNames`·`includes`·`contains`에 흩어져 있고(중복 포함), 부위 넷(Active site, 범위 Binding site + `ligand.id`·`label`·`note`·`ligandPart`, `ligand.id` 없는 Binding site, Site + `featureCrossReferences`), 촉매 활동 둘(`RHEA:`·`RHEA-COMP:`·ChEBI 교차참조와 `physiologicalReactions`, EC 없음 + `molecule`), `extraAttributes`, `organism`의 나머지 필드를 담는다. |
| `uniprot_entry_processed.json` | 위 응답의 손으로 쓴 기대 가공 행(EC 서로 다른 값 오름차순, `RHEA-COMP:`·방향 있는 반응 ID 버림, ChEBI ID 오름차순, 설명 빈 문자열 그대로, 없는 `ligand_id`는 null). |
| `uniprot_entry_trembl_raw.json` / `_processed.json` | `recommendedName` 없이 `submissionNames`만 있는 TrEMBL 꼴(첫 이름을 씀, 그 EC), `features`·`comments` 키 없음 → 빈 목록. |
| `uniprot_inactive.json` | 빠진 accession 분류 응답 `/uniprotkb/{acc}.json?fields=accession`의 모양 다섯: `DELETED`(→ obsolete), `MERGED`(대상 하나), `DEMERGED`(대상 둘, 일부러 정렬하지 않음), 알 수 없는 이유 종류(→ fetch_failed), 404 본문. `ACCESSION` 자리는 시험이 요청 accession으로 바꾼다. |
| `rhea_reactions.tsv` | Rhea REST TSV 모양(정확한 머리줄 다섯 열 + 행 셋). ID 정수 순서와 문자열 순서가 다르게 골랐고(`94`·`9310`·`93002`), EC 빈 칸·EC 둘(정렬 시험)·ChEBI 둘·셋을 담는다. |
| `rhea_reactions_processed.json` | 위 표의 손으로 쓴 기대 가공 행(정수 순서, `EC:` 뗌, ChEBI ID·이름 위치 짝). |

## 쓰는 곳

- `scripts/test_import_reaction_references.py`: 위 응답을 가짜 전송 함수(소켓 없음)로 돌려준다. 시험 코드가 같은 틀에서 accession·`mcsa_id`만 바꿔 M-CSA 항목 250개(3쪽)와 accession 1,000개 넘는 합집합(UniProt 2회)을 만들고, 가짜 응답 머리글에는 토큰처럼 보이는 표시 문자열(`SENTINEL-TOKEN-…`)을 넣어 그것이 어떤 파일·출력에도 남지 않음을 확인한다. 합성 M15 참조 폴더(`reference_active@1` + `reference_snapshot_set@1` + `uniprot/…/entries.jsonl`)도 시험 코드가 pytest 임시 폴더에 만든다. 전송 계층 자체는 시험이 연 `127.0.0.1` 서버로만 시험한다.
