# M26 T2 fixture — 합성 구조·합성 참조 행·독립 oracle

2026-10-08 M26 T2(상수·스냅샷 고정·순수 대응 로직)에서 만들었다. **이 폴더의 모든 자료는 합성(SYNTHETIC)이다.** 실제 M-CSA·UniProt·Rhea·RCSB 응답이나 그 조각을 하나도 담지 않았고, 만드는 동안 네트워크 요청은 0건이며 키·자격 증명도 없다. 필드 이름과 값의 형(型)만 명세 §3.3·§3.4(T1 실측 `docs/qa/m26-reaction-20261008/preflight-network.md`의 모양 기록)를 따랐다.

- PDB ID `0SY1`·`0SY2`·`0SY3`은 지어낸 값이다(실제 PDB ID는 첫 글자가 1–9이고 `0`으로 시작하지 않는다).
- UniProt accession `Q0SYN1`·`Q0SYN2`·`P0SYN3`·`Q0SYN4`·`Q0SYN5`·`P0SYN6`·`Q0SYN7`·`Q0SYN9`·`P0SYN1`·`P0SYN2`는 명세 §4.1 accession 형식에만 맞춘 지어낸 값이며 실제 항목을 뜻하지 않는다.
- EC 번호는 모두 `9.99.…`(존재하지 않는 9번 계열), Rhea ID(`RHEA:800`·`RHEA:10000`·`RHEA:9000010`·`RHEA:9000020`·`RHEA:90000300`·`RHEA:9000099`)와 ChEBI ID(`CHEBI:9900nn`, M-CSA 쪽 `9900nn`·`X00601`)도 지어낸 값이다. 이름·반응식·역할 문구는 "SYNTHETIC fixture …", "synthetic …", "fixture … text" 같은 표시 문자열이다.
- 효소·잔기의 역할·활성·반응에 대한 어떤 사실도 담지 않는다. "matched"는 이 합성 자료에서 PDB·체인·번호·잔기 이름이 같다는 뜻뿐이다.

파일은 저장소 밖 일회용 생성기(scratchpad, 커밋하지 않음)로 열 위치·JSON 형식만 맞춰 썼고, 값은 아래 표대로 손으로 정했다. `expected.json`만 `independent_match.py`가 만든다.

| 파일 | 내용 |
|---|---|
| `structure_alpha.cif` | 합성 mmCIF(`0SY1`, 모델 번호 2, `_entity` 넷: 1·4 polymer, 2 non-polymer, 3 water). 체인 A 사슬 잔기 24개: ASP 10, HID 11, HIE 12, HIP 13, CYX 14, ASH 15, GLH 16, LYN 17, HSD 18, HSE 19, GLY 20, SER 20A, SER 21A(21 없음), HSP 23, MSE 30(HETATM, polymer 엔티티), SER 31/THR 31(altloc A/B, 같은 번호 이질 잔기), ALA 40, CYS 41, GLY 42, ASP 43, GLU 44, THR 50, UNK 51. 체인 A의 비사슬 잔기: LIG 10(HETATM, non-polymer, ASP 10과 같은 번호), HOH 301. 체인 B: ALA 1, GLY 2(label 체인 D). 원자는 잔기마다 하나, 좌표는 x축 위 1.5 Å 간격의 합성 값이다. |
| `structure_beta.pdb` | 합성 PDB 형식(`0SY2`, ATOM 레코드만, TER 없음 → label 체인·label 번호가 null). 체인 A: ASP 10, GLY 52, GLY 52A, SER 53A(53 없음), HIS 60. 체인 B: CYX 5, ALA 7. |
| `mcsa_entries.json` | 가공 형식 `mcsa/entries.jsonl` 행 넷(`mcsa_id` 101–104, 오름차순). 101(`0SY1` 체인 A 위주): 대응됨(ASP 10, HID 11), 같은 번호 두 잔기(20), 삽입 코드만 있음(21), 표준 밖 구조 이름(MSE 30, UNK 51), 같은 번호 이질 잔기(31), 이름 다름(ALA 40), 구조에 없음(99), `Sec`·`X` 코드(41·42), `auth_resid` null, 그룹 합침(43: Asp/Glu 두 멤버 → `mcsa_rows_disagree`, 조립체 1·2, `is_reference` 거짓+참, `resid` 33·34; 44: Glu 두 멤버 → 합쳐 대응됨, 조립체 null·3), null 번호 + `Sec`/`Cys` 불일치(우선순위 시험), 한 잔기에 두 저자 번호(50과 null), 다른 PDB만 가리키는 잔기(`0SY2` A 60), `residue_chains` 빈 잔기, 대소문자만 다른 체인 `a`, 빈 `roles`·빈 `roles_summary`. 102(`reference_uniprot_id` `"Q0SYN2, P0SYN3"`, 빈 `residue_sequences.uniprot_id`와 `Q0SYN4`): M12 이름 열 개(HID는 101, HIE·HIP·HSD·HSE·HSP·CYX·ASH·GLH·LYN) 대응, HSD 18에 `Asp`(이름 다름), 101과 같은 잔기(ASP 10)·CYS 41. 103(`0SY2`, `reaction.ec` null): null label 대응, 52/52A, 53A, 체인 B CYX 5, 61(없음), 조립체 null. 104(`0SY3`, 이 폴더의 구조와 무관). |
| `uniprot_entries.json` | 가공 형식 `uniprot_function/entries.jsonl` 행 넷(accession 오름차순). `Q0SYN1`: Active site 10, Binding site 12–14(범위), Site 99(번호 대응에 없는 위치), Binding site 10(`ligand_id` null), EC 9.99.1.1·9.99.1.3, 촉매 활동 넷(Rhea ID 둘·스냅샷에 없는 `RHEA:9000099`·Rhea 없음·같은 ID 반복). `Q0SYN2`: 부위·활동·EC 모두 빈 목록(빈 결과 시험). `P0SYN3`(`protein_name` null). `Q0SYN5`(`RHEA:9000020`과 이어짐). |
| `rhea_reactions.json` | 가공 형식 `rhea/reactions.jsonl` 행 다섯(정수 부분 오름차순: 800, 10000, 9000010, 9000020, 90000300 — 문자열 순서와 다르게 골라 정렬 규칙을 시험). `RHEA:9000020`은 EC 9.99.1.3을 가지지만 `Q0SYN1`의 촉매 활동이 가리키지 않는다(EC → Rhea로 넓히지 않음 시험). |
| `independent_match.py` | **독립 ORACLE**(제품 코드 아님). 표준 라이브러리(`json`·`argparse`)만 쓰고 `mw`·gemmi·numpy를 import하지 않으며 제품 함수를 부르지 않는다. 두 구조 파일을 직접 읽어 M15 사슬 잔기 규칙(ATOM 레코드이거나 polymer 엔티티, 첫 모델, 파일 순서, 7필드)을 다시 쓰고, 명세 §5.3의 그룹·단계 1–5·`coverage`·행 순서·`entries`·`counts`를 자기 코드로 계산한다. PDB 파일에 HETATM이 있으면 멈춘다(gemmi의 엔티티 추정을 흉내 내지 않기 위해). `.venv/bin/python backend/tests/fixtures/reaction/t2/independent_match.py --check`는 `expected.json`이 새로 계산한 값과 같을 때만 0으로 끝나고, `--write`는 다시 쓴다. |
| `expected.json` | `independent_match.py`의 출력(ORACLE 출력, 제품 출력 아님). 사례 일곱(`0SY1` 체인 A·소문자 PDB ID·체인 B `chain_not_listed`·`0SY9` `pdb_not_in_snapshot`·PDB ID null `not_checked`, `0SY2` 체인 A·B): 사례마다 입력, oracle이 읽은 사슬 잔기 7필드 목록, 기대 `mcsa` 절 전체. |

## 쓰는 곳

- `backend/tests/reaction_fixture.py`: 위 세 JSON 행으로 가져오기 명령과 같은 배치의 합성 세트(`active.json` + `sets/<hash>/manifest.json` + `files/…`)를 pytest 임시 폴더에 만든다. 매니페스트의 `skipped_accessions`(`P0SYN6` demerged → `P0SYN1`·`P0SYN2`, `Q0SYN4` merged → `Q0SYN9`, `Q0SYN7` obsolete), `requested_accessions`(합성 M15 세트 해시 `e…e`, kinase 2개), 요청 기록(고정 합성 문자열의 SHA-256, 실제 응답 아님)도 합성 값이다.
- `backend/tests/test_reaction_knowledge.py`: 제품의 사슬 잔기·M-CSA 절을 `expected.json`과 비교하고(oracle을 다시 돌려 현재 값인지도 확인), UniProt 연결·반응 절·결과 객체·`validated_result`는 명세 문장에서 손으로 쓴 기대값과 손으로 만든 합성 번호 대응 dict로 시험한다.
- `backend/tests/test_reaction_constants.py`, `test_reaction_snapshots.py`: 형식 검사·매니페스트·스냅샷 고정 시험에 같은 합성 행을 쓴다.
