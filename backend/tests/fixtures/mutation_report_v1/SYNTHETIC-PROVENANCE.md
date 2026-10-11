# M28 T3 fixture — 참조값을 인용하는 저장된 M20 보고서(@1)의 run 로그

2026-10-11 M28 T3에서, M20 보고서 코드를 바꾸기 전(작업 브랜치 `dryforge/m28-final-verification`, 기준 커밋 `38dc02dd`, `backend/mw/mutation_reports.py` blob `290a1cf0c63e6f8ee413cbd80e36a72f131aa65e`)에 만들었다. 만든 명령은 이 폴더의 `record_v1_cited_reports.py`이다(한 번만 쓰는 기록기. T3 뒤에는 같은 요청의 새 보고서가 `mutation_candidates_markdown@2`가 되므로 같은 파일을 다시 만들 수 없다 — 기록된 파일이 증거다).

- 쓰는 곳: `backend/tests/test_mutation_reports.py`의 `frozen` fixture. 로그를 새 폴더에 복사해 이벤트만으로 다시 열고, 저장된 @1 보고서 둘이 T3 뒤에도 같은 Markdown·manifest 바이트로 다시 열리는지(`GET /reports/selected`·목록·다운로드), 같은 run에서 새로 만든 보고서가 인용이 있으면 @2(출처표), 없으면 @1인지(두 버전 병존), @2 출처표가 인용 객체의 `snapshot_set`과 같고 M15·M26 보고서의 표 문구와 같은지를 본다.
- **네트워크 요청 0건**, `.env`를 읽지 않음, 키·자격 증명 없음. 업로드로 구조를 넣었으므로 로그에 절대 경로가 없다(`upload://` handle만). 시각·호출 ID는 기록 때의 로컬 값이다.
- 입력은 모두 저장소 안 fixture이며 실험 검증이 아니다.
  - 파생 공개 구조 `../structures_m15/derived_1mq4_a200_285_fixture.pdb`(공개 PDB 1MQ4 체인 A 200–285의 파생 fixture, CC0 원본) + M15 참조 **FIXTURE** 세트(`tests/reference_fixture_set.py`, `../reference/`의 kbase_kinase 가공 스냅샷 행 발췌; 이미 저장소에 있는 행이다)로 만든 번호 대응(`pdb_id` 1MQ4, 체인 A)과 참조 주석.
  - 표시된 합성 구조 `../mutation/synthetic-mutation-fixture.cif` + **합성** 반응 참조 세트 `0SY6`(`tests/m20_catalytic_fixture.py`, 지어낸 PDB ID·M-CSA 행; 실제 M-CSA·UniProt·Rhea 응답 아님)로 만든 `reaction_knowledge@1` 결과(체인 A·B).
- 위치(`map_annotation`: 조각에서 주석된 KLIFS 주요 부위 잔기 전부 + 대응된 잔기 230·250, `catalytic`: ALA A2·HID A6·LEU A10·ASP A26(해제)·HID B6, `plain`: CYS A5·ALA A2)와 허용 잔기 기본값은 시험용 선택이며 설계 제안이 아니다. 후보는 위치와 바꿀 잔기의 조합일 뿐이고 점수·순위·안정성·ΔΔG·활성을 뜻하지 않는다.

| 파일 | 내용 | 크기 | SHA-256 |
|---|---|---|---|
| `v1-cited-reports.events.jsonl` | run `run_m28_t3_v1_cited`의 이벤트 로그 전체(66줄): 업로드 → `load_structure` → `prepare_structure`(조각, 합성 구조) → `map_residue_numbering` → `annotate_reference_sites` → `link_reaction_knowledge` → `generate_mutation_candidates` 셋(`map_annotation`·`catalytic`·`plain`) → `POST /method_reports` 둘 | 527,011 B | `7a2e0c6d2e1ec8a8bbe20e4ae9d6d67204c6e66a5a128393869f7e4c80e403a7` |
| `record_v1_cited_reports.py` | 위 로그를 만든 기록기(제품 경로 그대로, HTTP) | — | — |

저장된 @1 보고서(`render_version: mutation_candidates_markdown@1`, 두 보고서 모두 참조값 주장이 있음):

| 이름 | 보고서 handle 끝 | 인용 | Markdown SHA-256 | 정규 manifest SHA-256 |
|---|---|---|---|---|
| `map_annotation` | `…174d26820b23` | 번호 대응 + 주석(UniProt accession 1, KLIFS 부위 이름표 8) | `a2ddcba8ef9f30a32525d85b47194f6536f38924ba5841ad8761c28881908a1d` | `a5f71cb5983d2eb1fdc5886702313463ee600db0996b936f47b8ba1ae2a03f86` |
| `catalytic` | `…c36fa4ca4330` | 반응 지식 결과(M-CSA 항목 ID 주장 3) | `55cadf549ace58bc477ba8d9babcd8db2376149101f42ba8eaf1c4b77c6cda75` | `527577aa2d11825ffdd6fe92de49da911614147f41259e6ce0d9b87296af0c81` |

로그 크기가 256 KiB를 넘는 것은 조각 구조·준비 좌표·번호 대응 객체의 payload 때문이다(결정 0020은 커밋 증거에 관한 규칙이고 이 파일은 시험 입력이다). 기록 때의 작업 폴더(참조 세트·run 폴더)는 저장소 밖 임시 폴더였고 로그만 이 폴더로 복사했다.
