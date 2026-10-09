# M26 T9a — 실서버 가져오기 첫 회(import1)·공개 구조 3개·실데이터 대응 점검 (2026-10-09)

명세 §4.6·§12 "가져오기 실검증"의 첫 회 기록이다. 숫자·해시·상태만 적고 실제 응답 내용(M-CSA·UniProt·Rhea 본문이나 그 조각, 항목별 실제 값)은 싣지 않는다. 원본 응답은 저장하지 않았고(가져오기 명령의 설계), 사전 검증용 원본 두 건은 저장소 밖 scratchpad에만 있다. 설치한 세트는 Git 제외 폴더 `.deps/reaction_qa/import1/`에만 있다.

## 0. 요청 회계 (사용자 한도 2026-10-08)

| 구분 | 이 작업 | 누계 / 한도 | 장부 줄 |
|---|---|---|---|
| 형식 확인용 탐색 요청 | 2 (UniProt 일괄 요청 2건, 사전 검증) | 48 / 100 | 47–48 (`T9a`) |
| 전체 가져오기 | 1 (import1) — 요청 22건 | 1 / 2 | 49–70 (`T9a-import1`) |
| RCSB 공개 구조 mmCIF | 3 (`1S9I`·`1A30`·`1A4I`) | 3 / 3 | 71–73 (`T9a`) |

장부 `network-ledger.txt`는 73줄이다. 이 가져오기의 요청(`T9a-import1` 22줄)과 같은 작업의 구조 내려받기 3줄·확인 요청 2줄은 모두 HTTPS GET, 상태 200이었고 실패·재시도·리다이렉트는 없었다(장부의 404·400 상태는 착수 확인 `T1-A` 탐색 줄에만 있다). `T9a-import1` 줄은 설치된 세트의 `files/request_log.jsonl` 22행을 그대로 옮긴 것이며(URL·상태·바이트·본문 SHA-256), 시각은 가져오기 명령이 그 요청의 진행 줄 `[seq] …`을 출력한 UTC 시각(응답 직후)이다.

## 1. 사전 검증 (오프라인 재생 + 탐색 요청 2건)

- T3b 재생 하네스를 바꾸지 않은 가져오기 명령에 붙여(소켓 금지) 명령 자신의 계획 코드로 UniProt 일괄 요청 URL 두 개를 얻었다: 합집합 1,630 = M-CSA 1,094 ∪ M15 kinase 541(직접 지정 0), 일괄 1,000 + 630, 구성은 T1의 합집합 일괄 요청(장부 16·17)과 같다.
- 그 두 URL만 가져오기 명령의 실제 전송 계층(`UrllibTransport`)으로 한 번씩 받았다(장부 47–48, 5,203,717 B·2,721,772 B, 결과 1,622개).
- 새 두 본문 + T1에 저장한 M-CSA 11쪽·Rhea 표·비활성 8건으로 가져오기 전체를 오프라인 재생했더니 **형식 오류로 멈췄다**: UniProt 결과 1,622개 중 한 항목(P12821)의 Binding site 3개가 `location`에 `sequence` 키(같은 accession의 동형체 `<accession>-<n>`, 값 한 종류)를 가졌다. 다른 엄격 검사 층(최상위·부위·리간드·촉매 활동·반응·교차참조 키, 위치 수식어)에서는 1,622개 모두 명세 §3.4와 같았다(부위 11,090개 중 11,087개는 `location {start, end}`, 위치 22,180개 모두 `EXACT` 정수).
- 사용자 결정(2026-10-09, 명세 §3.4 갱신): 같은 accession의 동형체 위치 부위는 저장하지 않고 건너뛰며 개수는 명령 출력에만 보인다. 다른 `sequence` 값·알 수 없는 키는 형식 오류 그대로. 가져오기 명령 수정과 합성 회귀 시험(`backend/tests/fixtures/reaction/t9a/`)을 실서버 가져오기 **전에** 커밋했다(`075e38e`).
- 수정 뒤 같은 재생: 설치 성공, 행 M-CSA 1,003 · UniProt 1,622 · Rhea 18,611, 건너뜀 8(obsolete 4·demerged 4), 동형체 위치 부위 3, 요청 22.

## 2. 실서버 가져오기 첫 회 (import1)

- 명령(메인 체크아웃, 작업 브랜치 `dryforge/m26-reaction-knowledge`, `MW_REACTION_REFERENCE_DIR`·`MW_REFERENCE_DIR` 미설정):
  `.venv/bin/python scripts/import_reaction_references.py --yes --reference-dir <repo>/.deps/reaction_qa/import1`
- 시작 2026-10-09T01:58:27Z, 끝 02:00:24Z, **벽시계 117초**, 종료 코드 0. 확인 화면의 M15 kinase 목록: 541개(M15 세트 `aa21ead9930f82ebea3a2acf976449d9b1c6280ed17206d74d8cb9dc3f923317`), 이전 활성 세트 없음.
- **세트 해시 `fbeed900ef01b68e00b874ca923abcdbd683f0f2caf2eea117eb3037300fcb52`**, `imported_at` 2026-10-09T02:00:23Z, `importer_version` `reaction_import/1`, 매니페스트 2,505 B(정규 JSON, SHA-256 = 세트 해시), `active.json`은 정규 `reaction_active@1` 포인터. 폴더의 세트는 이것 하나.

| 출처 | 날짜 | 라이선스 | 행 | 바이트 | 가공 파일 SHA-256 | 원본 응답 수 | `raw_sha256_digest` |
|---|---|---|---|---|---|---|---|
| `mcsa` | 2026-10-09 | CC-BY-4.0 | 1,003 | 5,310,675 | `c373557bb89315d95862e595ee30f371e22819bf45d2a1e6eb593a8dd9b16ad9` | 11 | `87d5bb9274c38b1f9911234c1f99f43dafdf78e42ee048a67cdd708db999fe16` |
| `uniprot_function` | 2026-10-09 | CC-BY-4.0 | 1,622 | 2,401,807 | `c4e4322de03e665afe541507fc0026d396e12fc28f39f84a3745b15ba49485e6` | 10 | `6f1cc3b9779e735a8023f95c842a761c4bc8d20da9ab964744e86491a1a2f282` |
| `rhea` | 2026-10-09 | CC-BY-4.0 | 18,611 | 8,297,875 | `80109f69b5d614b96f4109c89aa099966a38a0fc287b2821fbb1d390832351da` | 1 | `d7bdfb4b281b0b9def5f2307ad86857f08db8c77be9b01a2090de73a73cefd6e` |

- 요청 기록 `files/request_log.jsonl`: 22행, 16,846 B, SHA-256 `b4f676cce6e5b1dd2e9436ec8e03988bdb18218f2db76b7c9ed06e98e7115274`. 행 키는 정확히 `seq`·`source`·`method`·`url`·`status`·`bytes`·`sha256`. 출처별 M-CSA 11·UniProt 10(일괄 2 + 분류 8)·Rhea 1, **접촉한 호스트는 `www.ebi.ac.uk` 11·`rest.uniprot.org` 10·`www.rhea-db.org` 1뿐**, 모두 GET·200, 받은 바이트 합 24,262,908.
- `requested_accessions`: `from_mcsa` 1,094, `from_m15_kinase_set` {위 M15 세트, 541}, `m15_kinase_list` `present`, `user_named` [], `dropped_previous_user_named` [], `union_count` 1,630.
- `skipped_accessions` 8개(모두 M-CSA 파생, kinase 쪽 0): `obsolete` 4(대상 0개), `demerged` 4(대상 accession 2·2·1·1개). 명령 출력과 매니페스트의 목록이 같다. T1(2026-10-08)이 관찰한 8개와 같은 accession이다.
- 명령 출력의 "동형체 위치라 저장하지 않은 부위": **3**(세트에는 남기지 않음).
- 오프라인 사전 검증 재생이 만든 가공 파일 세 개와 SHA-256이 모두 같다(사전 검증한 바로 그 자료가 설치됨).
- 서버 고정: `MW_REACTION_REFERENCE_DIR=<import1>`로 `reaction_snapshots.pin_active_set()`·`reaction_knowledge.pin_and_index()`가 같은 세트 해시를 고정했고 `capability()`는 사용 가능, 색인은 M-CSA 항목 1,003·PDB 1,002·UniProt 1,622·Rhea 18,611·건너뜀 8.
- 비밀·헤더 검사: 세트 폴더의 모든 파일(`active.json`, 매니페스트, 가공 파일 셋, 요청 기록)과 명령 출력에서 `Set-Cookie`·`Cookie:`·`Authorization`·`Bearer `·`X-Api-Key`·`api_key`·`User-Agent`·`Content-Type`·`Content-Length`·`X-UniProt`·`sk-or-`·`OPENROUTER`·`password`·`token=` 모두 없음(대소문자 무시).

## 3. 공개 구조 mmCIF 3개 (RCSB, CC0)

`https://files.rcsb.org/download/<ID>.cif`에서 한 번씩, 고정 `User-Agent`·`Accept-Encoding: identity`만, 리다이렉트 처리기 없이 받았고 바꾸지 않았다. 출처 기록은 1MQ4 선례대로 같은 폴더의 `public_<id>.provenance.json`.

| 파일 | 바이트 | SHA-256 | `_entry.id` | 체인(gemmi 사슬 잔기 수) | 파일의 마지막 개정 |
|---|---|---|---|---|---|
| `backend/tests/fixtures/public_1s9i.cif` | 565,105 | `3db038cdfa23f9d2b8d88e552162fa153c915402827cb4ebb24936171ef08810` | 1S9I | A 303, B 291 | 2024-04-03 (v1.4) |
| `backend/tests/fixtures/public_1a30.cif` | 222,024 | `40ab7868e9b40c19ca2aec74dc7f13364e523fb76854ac46aeeb319f2001eb47` | 1A30 | A 99, B 99, C 3(펩타이드) | 2024-02-07 (v1.4) |
| `backend/tests/fixtures/public_1a4i.cif` | 530,681 | `afa6bd62e3183d1e574ef4c61139148fe4d92c0a5bbac7575b5a418cd664e712` | 1A4I | A 285, B 295 | 2024-02-07 (v1.3) |

셋 모두 gemmi로 읽히고 모델 1개, 데이터 블록 이름과 `_entry.id`가 ID와 같다.

## 4. 실데이터 대응 점검 (제품 코드, 프로세스 안, 네트워크 0)

import1 세트를 활성으로 두고 `Run.call("link_reaction_knowledge", …)`(dry-run run, 일회용 runs 폴더는 scratchpad)로 돌렸다. 번호 대응 행은 실제 M15 세트(`.deps/reference`, 읽기만)로 `map_residue_numbering`을 먼저 돌렸다. 도구는 저장 전에 `validated_result`를 돌리고, 점검 스크립트는 표의 체인 B 두 행(따로 돌림)을 뺀 여덟 결과를 다시 검증했다(모두 통과). 숫자는 개수, 상태는 닫힌 집합 값이다(참조값 아님).

| 구조·체인 | accession(출처) | `coverage` | M-CSA 항목 수 | 행: matched / unmatched / conflict | UniProt 절 | 부위 Active / Binding / Site | 연결 | 반응 절: EC 수(M-CSA / UniProt) · M-CSA 화합물 수 · 촉매 활동 수 · Rhea 연결 원소의 in_snapshot 참/거짓 |
|---|---|---|---|---|---|---|---|---|
| 1S9I A | P36507 (user) | covered | 1 (282) | 2 / 0 / 0 — 저자 194 ASP·221 ASP | checked | 1 / 2 / 1 | 없음 (`numbering_map_not_given`) | checked · 1 / 1 · 5 · 3 · 3 / 0 |
| 1S9I A + M15 번호 대응 | P36507 (numbering_map) | covered | 1 | 2 / 0 / 0 | checked | 1 / 2 / 1 | `numbering_map` · 위치 mapped 11 / not_in_map 2 | 위와 같음 |
| 1S9I B | P36507 (user) | chain_not_listed | null | null | checked | (세지 않음) | (세지 않음) | checked(UniProt만) |
| 1A30 A | P04585 (user) | covered | 1 (175) | 3 / 0 / 0 — 저자 25 ASP·26 THR·27 GLY | checked | 1 / 14 / 14 | 없음 (`numbering_map_not_given`) | checked · 1 / 7 · 4 · 5 · 2 / 0 |
| 1A30 B | P04585 (user) | covered | 1 (175) | 3 / 0 / 0 — 저자 25 ASP·26 THR·27 GLY | checked | 1 / 14 / 14 | 없음 | 위와 같음 |
| 1A4I A | P11586 (user) | covered | 2 (389, 458) | 6 / 0 / 0 (항목 389·458 각각의 행) | checked | 1 / 6 / 0 | 없음 | checked · 2 / 3 · 4·6 · 3 · 3 / 0 |
| 1A4I B | P11586 (user) | chain_not_listed | null | null | checked | (세지 않음) | (세지 않음) | checked(UniProt만) |
| 1HSG A·B | P04585 (user) | pdb_not_in_snapshot | null | null | checked | 체인마다 1 / 14 / 14 | 없음 | checked(UniProt만) · null / 7 · null · 5 · 2 / 0 |
| 1MQ4 A | O14965 (user) | pdb_not_in_snapshot | null | null | checked | 1 / 5 / 0 | 없음 | checked(UniProt만) · null / 1 · null · 2 · 2 / 0 |
| 1MQ4 A + M15 번호 대응 | O14965 (numbering_map) | pdb_not_in_snapshot | null | null | checked | 1 / 5 / 0 | `numbering_map` · 위치 mapped 9 / not_in_map 0 | 위와 같음 |
| 1UBQ A | null | pdb_not_in_snapshot | null | null | not_checked (`accession_not_given`) | null | null | not_checked (`no_source`) · `null_result: true` |

- 기대(T1)와 같다: 1S9I 체인 A의 Asp194·Asp221 `matched`, 1A30 A/B 합쳐 여섯 행 `matched`, 1A4I 체인 A에 M-CSA 항목 둘(하나를 고르지 않고 둘 다), 저장소 안 구조 1HSG·1MQ4·1UBQ는 `pdb_not_in_snapshot`. 실데이터에서 `unmatched`·`conflict` 행, `residue_not_in_structure`·`ambiguous_residue_number`는 하나도 없었다. 체인 `flags`는 모두 빈 목록(`accession_differs_from_mcsa` 없음).
- 결과 `counts.rhea`(서로 다른 Rhea ID 수, in_snapshot 참/거짓): 1S9I 3/0, 1A30 1/0(두 연결 원소가 같은 ID), 1A4I 3/0, 1HSG 1/0, 1MQ4 2/0, 1UBQ null. `counts.mcsa_rows`: 1S9I 2/0/0, 1A30 6/0/0, 1A4I 6/0/0, 1HSG·1MQ4·1UBQ null(덮인 체인 없음).
- M-CSA가 적지 않은 체인(1S9I B, 1A4I B)은 `chain_not_listed`이고 행·항목·개수가 null이다(0이 아님).
- 이 표는 M-CSA·UniProt가 적어 둔 참조값이 이 구조의 잔기 번호·이름과 맞는지 센 것일 뿐이며, 잔기의 역할·활성·효과를 판정하지 않는다.

## 5. 남긴 파일

- 저장소: 이 문서, `network-ledger.txt`(73줄), 공개 구조 3개와 출처 기록 3개, 가져오기 명령 수정·합성 시험 fixture(`075e38e`).
- 저장소 밖: 세트 `.deps/reaction_qa/import1/`(Git 제외), 사전 검증 원본 두 건·재생/점검 스크립트(scratchpad). 실제 응답 조각은 저장소에 없다.
