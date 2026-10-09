# M26 T11b — 실서버 가져오기 둘째 회(import2)·재현성 비교 (2026-10-09)

명세 §4.5 "재현성"과 §4.6·§12 "가져오기 실검증"의 둘째(마지막) 회 기록이다. 첫 회는 `import1.md`(T9a)다. 숫자·해시·상태·필드 이름만 적고 실제 응답 내용(M-CSA·UniProt·Rhea 본문이나 그 조각, 항목별 실제 값)은 싣지 않는다. 원본 응답은 저장하지 않았고(가져오기 명령의 설계), 설치한 세트는 Git 제외 폴더 `.deps/reaction_qa/import2/`에만 있다. 소스는 고정 커밋 `1735338`(작업 브랜치 `dryforge/m26-reaction-knowledge`)에서 바꾸지 않았다.

## 0. 요청 회계 (사용자 한도 2026-10-08)

| 구분 | 이 작업 | 누계 / 한도 | 장부 줄 |
|---|---|---|---|
| 형식 확인용 탐색 요청 | 0 | 48 / 100 | — |
| 전체 가져오기 | 1 (import2) — 요청 22건 | **2 / 2 (소진)** | 74–95 (`T11b-import2`) |
| RCSB 공개 구조 mmCIF | 0 | 3 / 3 | — |

명령은 정확히 한 번 실행했고 재시도하지 않았다. 장부 `network-ledger.txt`는 95줄이다. 이 가져오기의 요청(`T11b-import2` 22줄)은 모두 HTTPS GET, 상태 200이었고 실패·재시도·리다이렉트는 없었다(장부의 404·400 상태는 착수 확인 `T1-A` 탐색 줄에만 있다). `T11b-import2` 줄은 설치된 세트의 `files/request_log.jsonl` 22행을 그대로 옮긴 것이며(URL·상태·바이트·본문 SHA-256), 시각은 import1과 같은 규칙으로 가져오기 명령이 그 요청의 진행 줄 `[seq] …`을 출력한 UTC 시각(응답 직후, 초 미만 버림)이다. 22줄의 URL·상태·바이트·SHA-256 열은 import1 줄(49–70)과 순서까지 모두 같다.

## 1. 실행

- 명령(메인 체크아웃 저장소 루트, `MW_REACTION_REFERENCE_DIR`·`MW_REFERENCE_DIR` 미설정, 표준 입력 없음):
  `.venv/bin/python scripts/import_reaction_references.py --yes --reference-dir <repo>/.deps/reaction_qa/import2`
- 출력(표준 출력 + 표준 오류)은 줄마다 UTC 시각을 붙여 저장소 밖 scratchpad에만 남겼다.
- 시작 2026-10-09T09:44:10Z, 끝 09:46:11Z, **벽시계 121초**(121.2초), 종료 코드 0. 실행 중 기계 부하가 높았다(1분 부하 평균 약 54, 다른 시험 실행과 겹침).
- 확인 화면: M15 kinase 목록 541개(M15 세트 `aa21ead9930f82ebea3a2acf976449d9b1c6280ed17206d74d8cb9dc3f923317`), 직접 지정 0, 이전 활성 세트 없음, 쓸 폴더 `.deps/reaction_qa/import2`. 기본 폴더 `.deps/reaction_reference`는 실행 뒤에도 없다.

## 2. 설치된 세트 (import2)

- **세트 해시 `1a7b131a102684f1f735bb96e6461bd13796c3b13a6d2203d289299cb57acf47`**, `imported_at` 2026-10-09T09:46:09Z, `importer_version` `reaction_import/1`, 매니페스트 2,505 B(정규 JSON, SHA-256 = 세트 해시), `active.json`은 정규 `reaction_active@1` 포인터(108 B). 폴더의 세트는 이것 하나이고 `.staging-*`·임시 포인터는 남지 않았다.

| 출처 | 날짜 | 라이선스 | 행 | 바이트 | 가공 파일 SHA-256 | 원본 응답 수 | `raw_sha256_digest` |
|---|---|---|---|---|---|---|---|
| `mcsa` | 2026-10-09 | CC-BY-4.0 | 1,003 | 5,310,675 | `c373557bb89315d95862e595ee30f371e22819bf45d2a1e6eb593a8dd9b16ad9` | 11 | `87d5bb9274c38b1f9911234c1f99f43dafdf78e42ee048a67cdd708db999fe16` |
| `uniprot_function` | 2026-10-09 | CC-BY-4.0 | 1,622 | 2,401,807 | `c4e4322de03e665afe541507fc0026d396e12fc28f39f84a3745b15ba49485e6` | 10 | `6f1cc3b9779e735a8023f95c842a761c4bc8d20da9ab964744e86491a1a2f282` |
| `rhea` | 2026-10-09 | CC-BY-4.0 | 18,611 | 8,297,875 | `80109f69b5d614b96f4109c89aa099966a38a0fc287b2821fbb1d390832351da` | 1 | `d7bdfb4b281b0b9def5f2307ad86857f08db8c77be9b01a2090de73a73cefd6e` |

- 요청 기록 `files/request_log.jsonl`: 22행, 16,846 B, SHA-256 `b4f676cce6e5b1dd2e9436ec8e03988bdb18218f2db76b7c9ed06e98e7115274`(매니페스트 기록과 같음). 행 키는 정확히 `seq`·`source`·`method`·`url`·`status`·`bytes`·`sha256`. 출처별 M-CSA 11·UniProt 10(일괄 2 + 분류 8)·Rhea 1, **접촉한 호스트는 `www.ebi.ac.uk` 11·`rest.uniprot.org` 10·`www.rhea-db.org` 1뿐**(scheme은 `https`만), 모두 GET·200, 받은 바이트 합 24,262,908.
- `requested_accessions`: `from_mcsa` 1,094, `from_m15_kinase_set` {위 M15 세트, 541}, `m15_kinase_list` `present`, `user_named` [], `dropped_previous_user_named` [], `union_count` 1,630.
- `skipped_accessions` 8개(모두 M-CSA 파생, kinase 쪽 0): `obsolete` 4(대상 0개), `demerged` 4(대상 accession 2·2·1·1개). 명령 출력과 매니페스트의 목록이 같고, accession·이유·대상까지 import1의 목록과 같다.
- 명령 출력의 "동형체 위치라 저장하지 않은 부위": **3**(세트에는 남기지 않음, import1과 같음).
- 서버 고정: `MW_REACTION_REFERENCE_DIR=<import2>`로 `reaction_snapshots.pin_active_set()`·`reaction_knowledge.pin_and_index()`가 같은 세트 해시를 고정했고, `reaction_snapshots.capability()`·`reaction_knowledge.capability()`는 사용 가능(`reason_code` null, 출처 `mcsa`·`uniprot_function`·`rhea`), 색인은 M-CSA 항목 1,003·PDB 1,002·UniProt 1,622·Rhea 18,611·건너뜀 8.
- 비밀·헤더 검사: 세트 폴더의 모든 파일 6개(`active.json`, 매니페스트, 가공 파일 셋, 요청 기록)와 명령 출력 기록·실행 기록·백그라운드 출력 파일(모두 9개)에서 `Set-Cookie`·`Cookie:`·`Authorization`·`Bearer `·`X-Api-Key`·`api_key`·`User-Agent`·`Content-Type`·`Content-Length`·`X-UniProt`·`sk-or-`·`OPENROUTER`·`password`·`token=` 모두 없음(대소문자 무시).

## 3. 재현성 비교 (명세 §4.5, import1 대 import2)

가져오기 명령의 라이브러리 함수 `compare_manifests`(`scripts/import_reaction_references.py`, 파일 경로로 불러옴, 두 매니페스트 모두 `validate_manifest` 통과)로 두 매니페스트를 비교했다.

| 출처 | 가공 파일 | SHA-256 (import1 = import2) | 같음 |
|---|---|---|---|
| `mcsa` | `entries.jsonl` | `c373557bb89315d95862e595ee30f371e22819bf45d2a1e6eb593a8dd9b16ad9` | 예 |
| `uniprot_function` | `entries.jsonl` | `c4e4322de03e665afe541507fc0026d396e12fc28f39f84a3745b15ba49485e6` | 예 |
| `rhea` | `reactions.jsonl` | `80109f69b5d614b96f4109c89aa099966a38a0fc287b2821fbb1d390832351da` | 예 |

- **판정: 재현됨** (`reproduced: true`, 가공 파일 셋의 SHA-256이 모두 같음).
- 원본 응답 요약 차이(`raw_differences`): **없음**(빈 목록). 세 출처의 `raw_sha256_digest`와 `raw_response_count`(11·10·1)가 import1과 같다. 요청 기록도 URL 순서가 같고 22건 모두 본문 SHA-256·바이트가 같아, 요청 기록 파일 자체가 import1과 바이트 단위로 같다(SHA-256 `b4f676cc…115274`; 기록에 시각이 없기 때문).
- 행 단위 비교(키: `mcsa_id` / `accession` / `rhea_id`): M-CSA 1,003 / 1,003, UniProt 1,622 / 1,622, Rhea 18,611 / 18,611행. 어느 출처에서도 한쪽에만 있는 행 0, 같은 키인데 내용이 다른 행 0, 값이 다른 최상위 필드 없음, 행의 필드 이름 집합도 같다.
- 두 매니페스트는 최상위 필드 `imported_at`(02:00:23Z 대 09:46:09Z) 하나만 다르고 나머지(출처 기록·요청 accession·건너뜀·요청 기록 파일 기록)는 모두 같다. 그래서 세트 해시만 다르다(`fbeed900…fcb52` 대 `1a7b131a…acf47`) — 명세대로 `imported_at`이 매니페스트 안에 있기 때문이며 재현 판정에는 쓰지 않는다.
- import1(02:00Z 무렵)과 import2(09:46Z 무렵) 사이에 세 서버의 응답 변화는 관찰되지 않았다.

## 4. 남긴 파일

- 저장소: 이 문서, `network-ledger.txt`(95줄).
- 저장소 밖: 세트 `.deps/reaction_qa/import2/`(Git 제외; import1 세트 `.deps/reaction_qa/import1/`도 그대로), 출력 기록·실행·점검 스크립트(scratchpad). 실제 응답 조각은 저장소에 없다.
