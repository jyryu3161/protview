# M27 T3 fixture — 합성 kbase 흉내 폴더 (가져오기 명령 시험)

2026-10-10 M27 T3(가져오기 명령 `scripts/import_precedent_snapshots.py`)에서 만들었다. **이 작업의 시험 자료는 모두 합성(SYNTHETIC)이다.** 실제 kbase_kinase 레코드·인용문·관찰 문장·서지 제목이나 그 조각을 하나도 담지 않았고, 만드는 동안과 시험하는 동안 네트워크 요청은 0건이며 키·자격 증명도 없다. 실제 kbase 체크아웃은 시험이 읽지 않는다.

이 폴더에는 정적 자료 파일이 없다. 합성 kbase 흉내 폴더는 시험 `scripts/test_import_precedent_snapshots.py`의 `build_kbase`가 pytest 임시 폴더 안에 매번 새로 만든다:

| 경로(임시 폴더 안) | 내용 |
|---|---|
| `dist/moves.jsonl`·`moves_flagged.jsonl`·`references.jsonl` | T2가 커밋한 합성 파일(`backend/tests/fixtures/precedent/t2/dist/`, 출처 `t2/SYNTHETIC-PROVENANCE-t2.md`)의 바이트 그대로, 또는 사례마다 `backend/tests/precedent_fixture.py`의 `make_move`·`make_reference`·`rehash`·`jsonl`로 바꾼 합성 레코드(형식 위반·해시 불일치·중복 `move_id` 같은 거절 사례). |
| `dist/structures.jsonl`·`figures.jsonl`·`CONTRACT.md` | 가져오지 않아야 하는 파일. 한 줄짜리 합성 표시 문자열뿐이다. |
| `dist/manifest.json` | kbase 매니페스트 모양(최상위 `files`·`kb_version`·`meta`, 원소 `name`·`bytes`·`records`·`sha256: "sha256:<hex>"`)을 흉내 낸 합성 값. `meta`의 세 핀 값만 명세 `KBASE_PINS`와 같고 `kb_version` `kbv1:synthetic-t3`·`source_snapshots` `SNAP-synthetic-t3-…`·`counts`·`consumer_agents_sha256`은 지어낸 값이다. |
| `ref/manifest.json` | `snapshots[]` 셋: 합성 pubmed 스냅샷 두 날짜(`2026-09-01`은 앞 두 줄만, `2026-09-30`이 최신 — 최신 하나를 고르는지 시험)와 고르지 않아야 하는 합성 `uniprot` 스냅샷 하나. `snapshot_id`·라이선스 `synthetic-t3-license`·`urls`(`synthetic-url-…`, 주소 아님)·`raw_sha256`은 지어낸 값이다. |
| `ref/pubmed/<날짜>/documents.jsonl` | T2 합성 서지 행(`t2/pubmed/documents.jsonl`) 또는 `make_pubmed_row`로 만든 합성 행. 지어낸 PMID `9000000n`. |
| `.git` | 시험이 `git init`·`commit`으로 만든 일회용 저장소(작성자 `fixture <fixture@invalid>`, 고정 날짜 `2026-09-21T00:05:28+09:00`, 전역·시스템 git 설정 없음). 커밋 해시는 매번 그 자리에서 계산된다. |

실제 kbase `dist/`로 한 실행(가져오기 실검증, 명세 §10)은 저장소 밖 세션 스크래치패드의 격리 폴더에서 했고, 그 결과는 개수·해시만 작업 보고에 있으며 실제 자료는 커밋하지 않았다.
