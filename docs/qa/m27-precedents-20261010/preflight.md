# M27 T1 착수 확인 — 실데이터 형식·비용·실구조·결합 지도·격리·기준선 (2026-10-10)

계획 T1의 (a)–(h)를 코드 전에 잰 기록이다. 기준은 작업 브랜치 `dryforge/m27-kinase-precedents`의 `6ac3a59`(= main)이고, 저장소에 더한 것은 이 폴더(`preflight.md`·`network-ledger.txt`·시제품 `kbase_check.py`)와 공개 구조 fixture 둘(`backend/tests/fixtures/public_1m17.cif`·`public_1fin.cif`와 각 `.provenance.json`)뿐이다. 제품 코드(`backend/mw`·`frontend`·`config`·`scripts`)는 바꾸지 않았다. `kbase_check.py`는 실제 문구가 없고 `mw`를 import하지 않는 측정 시제품이라 이 폴더에 두었다. `mw`를 쓰는 측정 스크립트(`numbering_real.py`·`sifts_accessions.py`·`sifts_only_probe.py`)와 실제 kbase 자료로 만든 모든 출력은 저장소 밖 세션 스크래치패드(아래 `<S>` = `…/scratchpad/m27_t1/`)에만 있고 커밋하지 않는다. 이 문서에는 실제 kbase 문구(인용문·관찰 문장·서지 제목·표적 이름 원문·레코드 조각)가 없고 숫자·해시·ID·개수·닫힌 코드값만 있다. Python은 모두 `/Users/jaeyongryu/Projects/protview/.venv/bin/python`(3.11.11)이다.

외부 요청은 사용자가 허용한 RCSB 두 건뿐이다(`network-ledger.txt`, 각 1회, 재시도 없음, 둘 다 200). 그 밖의 모든 단계는 네트워크 0건이고 `.env`는 열지 않았다.

## (a) 실데이터 형식 (명세 §3.3·§3.4)

**명령.** `.venv/bin/python docs/qa/m27-precedents-20261010/kbase_check.py validate /Users/jaeyongryu/Projects/kbase_kinase` (이 폴더의 시제품: 표준 라이브러리 + 어휘 YAML 읽기용 `yaml`만, `mw`·kbase 코드 import 없음, 네트워크 없음, 실제 문구 없음; 명세 §3.4 규칙을 그대로 옮긴 `validate_move`·`validate_reference`·`canonical_json`·`content_hash`. 제품 코드가 아니며 T2 구현의 근거도 아니다 — T2는 명세에서 독립적으로 구현한다) → exit 0, 출력 `<S>/validate.json`(8,988 B, 실제 자료에서 센 값이라 커밋하지 않음; 이 문서의 수치는 그 출력에서 옮김). 읽기 전용 git: `GIT_OPTIONAL_LOCKS=0 git -C ../kbase_kinase rev-parse HEAD` / `log -1 --format=%H%n%cI -- dist` / `status --porcelain -- dist ref/pubmed` → 모두 exit 0.

**kbase 체크아웃.**

| 항목 | 명세·인계 기대 | 측정 | 일치 |
|---|---|---|---|
| HEAD | `77354f9` | `77354f94b844a8c64e7cd47691ac20a2e96214b3` | 예 |
| `dist/`를 마지막으로 바꾼 커밋·날짜 | `43a935e`, 2026-09-21T00:05+09:00 | `43a935e4637d986700fa61a4deae8300e405edb7`, `2026-09-21T00:05:28+09:00` | 예 |
| `status --porcelain -- dist ref/pubmed` | (dirty 기록) | 0줄 → `dirty = false` (저장소 전체 `status --porcelain`도 0줄) | — |
| `43a935e..77354f9` 사이 `src/domains/kinase/vocab`·`dist`·`ref/pubmed`·`ref/manifest.json` 변경 | — | `git diff --stat` 0줄(그 사이 커밋 14개는 다른 경로) | — |
| `dist/manifest.json` | 크기 ≤ 1 MiB, 날짜·라이선스 없음 | 2,074 B, SHA-256 `d61d9981625a11041bf90563287946d4a1398ddcf8d6fa60943a508f58676919`, 최상위 키 `files`·`kb_version`·`meta`뿐 | 예 |
| `ref/manifest.json` | 크기 ≤ 64 MiB | 2,221,400 B, SHA-256 `fb0c0abb1e9f583133255725705f82006da1fa79f9b93af26685311d01581089`, 최상위 키 `snapshots`뿐 | 예 |

**`KBASE_PINS`(엄격 고정).** `meta.schema_version` = `"1"`, `meta.effect_rules_version` = `"1"`, `meta.vocab_version` = `contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:024a47d5a62eab2a1ad1a52a0bb8f8e2740cbe3f8ad279bc6c62055c778cc11e` — 셋 다 명세 값과 문자 그대로 같다(`match: true` ×3). 기록만 하는 값: `kb_version` = `kbv1:ae11f41d19e5bef9`, `meta.source_snapshots` = `SNAP-interpro-2026-09-15`, `SNAP-kincore-2026-09-19`, `SNAP-kinhub-2026-09-15`, `SNAP-klifs-2026-09-19`, `SNAP-rcsb-2026-09-20`, `SNAP-sifts-2026-09-20`, `SNAP-uniprot-2026-09-15`(7개).

**파일 대조(dist 매니페스트 `files[]`의 `sha256`·`bytes`·`records` ↔ 실제 파일).**

| 파일 | 바이트 | 줄(= `\n` 수, 마지막 바이트 `0a`) | SHA-256 | 매니페스트와 일치 | 64 MiB·100,000줄 안 |
|---|---|---|---|---|---|
| `dist/moves.jsonl` | 4,293,797 | 891 | `2ad983addd8ff3fe563a2b18bba553d84c7c90401310da65902f6832572435be` | 예 | 예 |
| `dist/moves_flagged.jsonl` | 5,544,181 | 885 | `0699270358cfb4b250f8278968383e73e6b0dc347723faca135c30628301d658` | 예 | 예 |
| `dist/references.jsonl` | 4,357,502 | 555 | `70a09223477d77bf77b8720d92ff40a85f8fa591c5faa4ea0f49f23f6a0e544e` | 예 | 예 |

**서지 스냅샷(`ref/manifest.json` `snapshots[]` 중 `source == "pubmed"`, 날짜 2026-09-15·09-17·09-18 셋 중 최신).** `SNAP-pubmed-2026-09-18`, 라이선스 `public-domain-ncbi`, `pubmed/2026-09-18/documents.jsonl` 76,396 B·252행·SHA-256 `8bad29967d065d131949219545c2b4b95117246b4a047940bdc1812affda179d` — 매니페스트 `sha256`·`bytes`·`rows`와 일치. 행 252개 모두 JSON, `id`는 모두 `^\d+$`이고 유일, 행 키 집합은 252개 모두 `data,id,pmid,status`, `data` 키는 252개 모두 `doi,journal,pmc,pmid,title,year`, `status`는 252개 모두 `ok`, `data.pmid == id`인 서지 대상 행 252개, `data.year`가 정수 문자열이 아닌 행 0개. 두 전례 파일의 서로 다른 PMID 167개(`moves` 128, `moves_flagged` 138)를 최신 스냅샷이 **167개 모두** 덮는다.

**레코드 해시 재계산**(`"sha256:" + sha256(canonical_json(최상위 content_hash만 뺀 레코드))`): `moves` 891/891, `moves_flagged` 885/885, `references` 555/555 일치(불일치 0), `references_without_hash` 0. → 명세 기대 891·885·555와 같다.

**Move 레코드 형식 검사(§3.4 전 항목).** `moves` 891건·`moves_flagged` 885건 모두 위반 0건(`failing_records: 0`, `error_counts: {}`). 최상위 키 집합은 두 파일 모두 한 종류이고 정확히 21개(명세 목록과 같음), `review_status`는 모두 `unreviewed`, `schema_version`은 모두 정수 1, `move_id`는 모두 `^MOVE-\d{4,}$`이고 두 파일 합쳐 1,776개 유일. 어휘 밖 태그 0, 닫힌 집합 밖 값 0.
- 명세 필수 목록 밖의 중첩 키(보존 대상): `source.parser` 1,776, `extraction.chunks`·`extraction.dropped_effects`·`extraction.notes` 각 1,776, `target.resolution_evidence` 1,520(명세상 선택 키). `effects[]` 원소·`checks`·`observation`의 직속 키에는 필수 목록 밖 키가 없다(각 검사 객체 안의 세부 키는 검사마다 다르며 그대로 보존 대상).
- 사본에서 뺄 두 경로 `source.parser`와 `checks.cross_parser_numbers.measurements`는 1,776건 모두에 있다(없어서 못 빼는 레코드 0).
- 실제로 나온 닫힌 값(효과·검사·위치 단위 개수): `resolution_basis` absent 122 · alias 20 · ambiguous 2 · gene 1,120 · klifs_name 90 · name_token 103 · notation 3 · pubmed_title 44 · unmapped 272(`klifs_gene_name` 0); `target_role` on_target 2,584 · off_target 888 · not_applicable 360; `direction` improved 1,232 · worsened 1,014 · unchanged 839 · unknown 747; `direction_basis` numeric 2,261 · text 1,571(`none` 0); `magnitude_bucket` small 1,161 · moderate 651 · large 709 · unknown 1,311; 검사 상태 pass 13,283 · fail 1,084 · not_applicable 3,142 · lookup_failed 251; 위치 `kind` table 2,147 · text 1,836(`figure` 0); `structure_links[].basis` pdb_title 162 · paper_context 236(`sole_candidate` 0). `structure_links` 원소 키는 한 종류(`basis,candidates,chain,confidence_note,ligand,pdb_id,structure_id`).

**참조 레코드.** 555건 위반 0, `ref_id` 유일, 키 집합 한 종류(명세 필수 10개 + `source_snapshots`·`klifs_gene_name`·`domain`·`klifs_pocket_seq`·`pocket_positions`·`pocket_positions_provenance`·`anchors`·`conflicts`), 서로 다른 `uniprot` 542개 중 참조가 둘인 accession 13개(최대 2), `coverage` partial 521 · unmapped 34.

**어휘 상수.** kbase `src/domains/kinase/vocab/{site,goal,tactic}.yaml`의 `terms[].id`를 파일 순서대로 읽어 명세 §9.2 목록과 비교:

| 축 | YAML 용어 수 | 명세 수 | 순서까지 같음 | YAML `version` | YAML SHA-256 |
|---|---|---|---|---|---|
| site | 20 | 20 | 예 | 2 | `addd64b26d32d95fd7f32db68cc5d013475fe0a806a73523c5fe87471e2d9ea1` |
| goal | 12 | 12 | 예 | 1 | `96bc3b2bd647c15210e6989d4ab7c21f735759f62e76eedf7c3a3a4eeda6ed7d` |
| tactic | 18 | 18 | 예 | 1 | `708e4dd8750382da095f735b184a65cb1ea421b487830382216871cf262a1d61` |

kbase `vocabulary.py`의 `vocab_version` 식(읽기만 함: 다섯 축 `<axis>@<version>`을 이름순으로 잇고 `+target_aliases@<version>:` + `sha256(target_aliases.yaml 바이트)`)을 체크아웃의 YAML로 다시 계산하면 핀 값과 같다(`vocab_version_recomputed_equals_pin: true`). 이 핀은 site·goal·tactic의 **버전 번호**와 `target_aliases.yaml` 바이트만 묶고 용어 목록 자체는 묶지 않으므로, 용어 목록은 위 표의 직접 대조와 레코드에 실제로 쓰인 태그(축마다 20·12·18개 모두 쓰임, 어휘 밖 0)로 확인했다.

**인계 문서의 실데이터 사실 재확인.** 표적 미해석 396건 = `moves` 193(absent 72·unmapped 121) + `moves_flagged` 203(absent 50·unmapped 151·ambiguous 2) → 근거 unmapped 272·absent 122·ambiguous 2(일치). 해석된 `moves` 698건 중 추정 근거 75건 = name_token 38·pubmed_title 20·alias 14·notation 3(일치). 해석된 표적의 `uniprot`이 `references`에 없는 경우 0(두 파일 모두). `moves`에는 없고 `moves_flagged`에만 있는 표적 17개(그중 참조 없는 것 0). `moves`의 `duplicate` 검사 fail 61건(`moves_flagged` 129건). 관찰 인용 `quote_truncated` 참 136건(`moves` 83 + `moves_flagged` 53; 교환 인용까지 세면 +27, 아래 다른 점 2). `checks.quote_in_source` 안의 `quote_assembled` 8건(3 + 5). `structure_links`가 있는 `moves` 142건, 서로 다른 PDB `moves` 88개·두 파일 132개. SMILES가 있는 전례 0건. 25단어 넘는 인용 0건. `fold_change`가 null인 효과 1,904개(`moves` 1,056 + `moves_flagged` 848). 효과 중 off_target 888/3,832(약 23%). 표적별(`moves` + `moves_flagged`, 참조 수):

| 표적 | accession | `moves` | `moves_flagged` | 참조 | `moves`의 `target.variant`별 | on_target 효과 없는 `moves` |
|---|---|---|---|---|---|---|
| EGFR | P00533 | 76 | 66 | 1 | not_reported 53 · L858R 15 · T790M 4 · WT 3 · L834R 1 | 20 |
| BTK | Q06187 | 70 | 97 | 1 | not_reported 70 | 11 |
| CDK2 | P24941 | 32 | 24 | 1 | not_reported 32 | 2 |
| Aurora A | O14965 | 0 | 0 | 1 | — | 0 |

**결론.** 실제 `dist/` 세 파일과 최신 서지 스냅샷은 명세 §3.4의 핀 세 값·파일 대조·21개 최상위 키·닫힌 값 집합·어휘(20·12·18)·레코드 해시 재계산(891·885·555)을 모두 통과한다. 멈출 조건 없음.

## (b) 비용 (캐시 없이)

**명령.** `kbase_check.py cost <kbase>`를 새 프로세스로 세 번(각 exit 0, `<S>/cost_{1,2,3}.json`), `/usr/bin/time -l … kbase_check.py sizes <kbase>`(exit 0, `<S>/sizes.json`).

| 단계 | 세 번 측정(초) | 최솟값 |
|---|---|---|
| 세 dist 파일 + 서지 파일 읽기 | 0.0059 · 0.0057 · 0.0058 | 0.006 |
| 파일 SHA-256(고정 검증) | 0.0051 · 0.0059 · 0.0054 | 0.005 |
| JSONL 해석(4파일) | 0.154 · 0.156 · 0.159 | 0.154 |
| 형식 검사(§3.4) | 0.012 · 0.013 · 0.013 | 0.012 |
| 레코드 해시 재계산(2,331건) | 0.144 · 0.139 · 0.141 | 0.139 |
| 색인(§3.5: `by_uniprot` 68 표적, `references_by_uniprot` 542, `bibliography` 252, `unresolved` 2파일·이름 35, `resolution_basis_counts` 6) | 0.0034 · 0.0022 · 0.0027 | 0.002 |
| **합계** | 0.3245 · 0.3219 · 0.3266 | **0.322** |

최대 RSS: 시작 18.2–18.5 MB → 해석·색인 뒤 119.7–123.1 MB(약 +105 MB). 크기 측정 전체 실행은 최대 RSS 140,263,424 B(0.70 s). 도구가 한 호출에서 표적 하나의 원본 레코드 해시를 다시 계산하는 비용은 최대 표적(BTK, 167건)에서 0.0086 s(5회 최솟값, 나머지 그룹 pytest가 동시에 돌던 중).

**결과 크기.** 명세 §5.6 최상위 키 전부를 갖춘 결과 모양(체인 하나·표적 하나, 레코드 사본은 정확히 두 경로를 뺀 것, `integrity`·`references`·`counts`·`bibliography`·`set_summary`(미해석 이름 상위 100)·KP1–KP6 포함, handle·해시 자리는 같은 길이의 자리 표시값)을 정규 JSON(`sort_keys`, `(",", ":")`, `ensure_ascii=False` — `mw.core.handles.canonical_json`과 같은 식)으로 쟀다. 상한 1 MiB = 1,048,576 B.

| 표적 | `include_flagged` 거짓 | `include_flagged` 참 |
|---|---|---|
| BTK `Q06187` (70 + 97) | 365,192 B | **855,798 B (0.816 MiB)** |
| EGFR `P00533` (76 + 66) | 377,767 B | 755,053 B |
| CDK2 `P24941` (32 + 24) | 153,529 B | 258,260 B |
| 세트에서 가장 큰 표적 | EGFR 377,767 B | BTK 855,798 B |

68개 표적 모두 단독으로는 두 경우 모두 1 MiB 안(넘는 표적 0). `include_flagged` 참 상위 다섯: Q06187 855,798 · P00533 755,053 · O60674 486,430 · P52333 477,145 · P29597 463,667. 참고: BTK 레코드만의 정규 JSON은 원본 전체 946,330 B, 두 경로를 뺀 사본 815,118 B(두 경로가 약 14%). 서로 다른 accession 두 체인이 한 결과에 들어가는 경우 BTK + EGFR은 `include_flagged` 거짓 736,991 B(안), 참 **1,604,884 B(초과)** — 명세대로 자르지 않고 `result_too_large`(429)로 거절되어야 하는 실제 크기 사례다(그런 구조는 이 단계 자료에 없다).

**결론.** 단일 표적 결과는 최악(BTK, `moves_flagged` 포함)도 0.816 MiB로 1 MiB 안이다(명세의 "약 0.8 MiB"와 같음). 캐시 없이 해석·검사·해시·색인을 하면 호출마다 약 0.32 s와 약 105 MB가 든다. `/capabilities`의 `methods.kinase_precedents`와 `GET /precedent_reference/status`도 "§3.4·§3.5 내용 해석 통과"를 요구하므로 화면이 읽을 때마다 이 비용이 들게 된다 → **세트 단위 캐시가 필요하다**: M26 `reaction_knowledge.reaction_index`(`_INDEX_CACHE`, 키 `(set_hash, pinned.files_identity)`, 성공만, 새 항목을 넣을 때 비워 세트 하나만)와 같은 방식. 도구의 호출당 레코드 해시 재계산(표적 하나, 10 ms 미만)은 캐시와 별개로 해도 비용 문제가 없다.

## (c) 실구조: RCSB 내려받기와 M15 번호 대응 실제 실행

**요청(장부 `network-ledger.txt`).** `curl -sS --proto '=https'`(추가 헤더·키·쿠키 없음, 리다이렉트 따르지 않음, 재시도 없음)로 한 번씩:

| UTC | URL | HTTP | 바이트 | SHA-256 |
|---|---|---|---|---|
| 2026-10-10T07:47:07Z | `https://files.rcsb.org/download/1M17.cif` | 200 | 307,709 | `849bd2548dffb7ddcb7229a05202c1e2e41019a1fd69ec39483654cf984fc4d0` |
| 2026-10-10T07:47:26Z | `https://files.rcsb.org/download/1FIN.cif` | 200 | 999,052 | `dfe5da37b2e28d3d74eefa0edee97d57ea127538beead9e68a8a42a5c363a1ac` |

받은 바이트를 그대로 `backend/tests/fixtures/public_1m17.cif`·`public_1fin.cif`로 복사했다(`cmp` 동일). 출처 기록 `public_1m17.provenance.json`·`public_1fin.provenance.json`은 `public_1mq4.provenance.json`과 키 집합이 같고(`file, label, source_url, downloaded, sha256, bytes, entry, latest_revision_in_file, license, modified, download_note, purpose`), `test_public_1mq4_matches_provenance`와 같은 검사(URL·`modified: false`·SHA-256·바이트·`data_<ID>\n` 시작)를 둘 다 통과한다. 파일 안 마지막 개정: 1M17 2024-02-14(ordinal 4, version 1.3), 1FIN 2024-02-07(ordinal 4, version 1.3). gemmi로 본 모양: 1M17 모델 1, 고분자 체인 A(완전 서열 333), 리간드 AQ4; 1FIN 모델 1, 고분자 엔티티 둘(A·C 298, B·D 260), ATP 둘.

**번호 대응 실행.** `<S>/numbering_real.py`(커밋하지 않음): FastAPI `TestClient`로 제품 라우트만 거친다 — `POST /runs` → `POST /runs/{id}/uploads` → `load_structure` → `prepare_structure`(M15 API 테스트와 같은 인자) → `map_residue_numbering`(`POST /runs/{id}/commands`). runs 폴더는 `<S>/num1/runs`, `MW_REFERENCE_DIR`는 비워 기본 `.deps/reference`(활성 M15 세트 `aa21ead9930f82ebea3a2acf976449d9b1c6280ed17206d74d8cb9dc3f923317`, 읽기 전용 — `reference_snapshots`는 `O_RDONLY|O_NOFOLLOW`로 읽기만 함), 네트워크 없음. 저장된 `residue_numbering_map@1`을 `run.store.load`로 읽어 명세 §5.3(체인 판정)·§5.4(표적 판정)를 시제품이 계산하고, 표적 전례 수는 실제 `dist/`에서 셌다. 실행 exit 0, 출력 `<S>/numbering.json`.

| 사례 | 요청 체인(accession) | HTTP | 결과 |
|---|---|---|---|
| 1MQ4 | A(null), `pdb_id` 1MQ4 | 200 | A: methods sifts+local_alignment, cross_check 참, mapped 260 / 전체 261(conflict 1: `one_method_only`, SER 388), accession O14965 |
| 1M17 | A(null), `pdb_id` 1M17 | 200 | A: methods sifts+local_alignment, cross_check 참, mapped 311 / 전체 312(conflict 1: `one_method_only`, LEU 977), accession P00533 |
| 1FIN A·C | A, C(null), `pdb_id` 1FIN | 200 | A·C 각각 methods sifts+local_alignment, cross_check 참, mapped 298 / 298, accession P24941 |
| 1FIN A·B·C·D | 넷 모두(null) | **422** | `reason_code: no_usable_method`, `chain_auth: B` — 호출 전체가 실패(객체 없음) |
| 1FIN B 단독 | B(null) | 422 | `no_usable_method`(B) |
| 1FIN B + 자기 SIFTS accession | B(P20248, cyclin A2) | 422 | `accession_not_in_uniprot_snapshot`(B) — M15 UniProt 스냅샷은 kinase만 |
| 1FIN A·C + B에 **일부러 틀린** accession | A, C(null), B(P24941) | 200 | B: methods local_alignment만, cross_check 거짓(`chain_not_in_sifts_snapshot`), mapped 0 / 260(전부 unmapped) |
| 1M17, `pdb_id` 없음 + 사용자 accession | A(P00533) | 200 | A: local_alignment만, cross_check 거짓(`pdb_id_not_given`), mapped 311 / 312(unmapped 1) |
| 1M17, `pdb_id` 없음, accession 없음 | A(null) | 422 | `no_usable_method`(A) |

**명세 §5.3·§5.4 판정(시제품, `include_flagged` 거짓 / 참).**

| 번호 대응 | 체인 판정 | 표적 | 상태 | 포함 `moves` | 포함 `moves_flagged` | `excluded_flagged` |
|---|---|---|---|---|---|---|
| 1MQ4 A | linked, O14965 | O14965(체인 A, 참조 1) | `none_in_included_files` | 0 / 0 | null / 0 | 0 / null |
| 1M17 A | linked, P00533 | P00533(체인 A, 참조 1) | `precedents_found` | 76 / 76 | null / 66 | 66 / null |
| 1FIN A·C | A linked P24941, C linked P24941 | P24941(체인 A·C — 표적 하나, 체인 행 둘, 참조 1) | `precedents_found` | 32 / 32 | null / 24 | 24 / null |
| 1FIN A·C + B(틀린 accession) | A·C linked, **B not_linked `no_mapped_residues`** (accessions `[]`) | P24941(체인 A·C) | `precedents_found` | 32 / 32 | null / 24 | 24 / null |
| 1M17(로컬 정렬만) | linked, P00533 (cross_check 거짓, 사유 `pdb_id_not_given`) | P00533 | `precedents_found` | 76 / 76 | null / 66 | 66 / null |

**결론.**
- 1M17 체인 A → accession P00533, mapped 311(전체 312). 1FIN 체인 A·C → 둘 다 P24941, mapped 298(전체 298). 1MQ4 체인 A → O14965, mapped 260(전체 261). 연결된 accession의 kbase 전례 수는 기대와 같다: EGFR 76 + 66, CDK2 32 + 24, Aurora A 0 + 0(참조 1 → `none_in_included_files`, `excluded_flagged` 0). 명세 §10의 실데이터 사례(1M17 → `precedents_found`, 1FIN A·C → 한 표적 두 체인)가 허용된 구조 2개로 만들어진다.
- 1FIN B·D를 번호 대응 요청에 넣으면 **호출이 통째로 422 `no_usable_method`로 실패한다**(B가 첫 실패). 명세의 가정("체인 목록에서 뺀다")이 맞다. B에 자기 SIFTS accession(P20248)을 주면 422 `accession_not_in_uniprot_snapshot`이다.
- 실데이터로 `no_mapped_residues`가 나오는 길은 사용자가 체인에 맞지 않는 kinase accession을 직접 준 경우뿐이다(1FIN B + P24941 → 로컬 정렬만, mapped 0). 제품에서 도달 가능한 입력 실수 경로지만 과학적으로 맞는 사용이 아니므로 수락 증거의 정상 사례로 쓰지 않고, 테스트는 합성 번호 대응 객체로 한다. `multiple_accessions`는 허용된 구조로는 만들 수 없다(아래 (d)의 SIFTS 융합 체인 5개는 구조 파일이 저장소에 없고 내려받기 한도 밖) → 합성으로만.
- 참고: 사용자 accession만 준 로컬 정렬 단독 번호 대응도 `linked`가 된다(cross_check 거짓과 사유가 결과 체인 행에 그대로 남는다 — 명세 §5.3의 "교차 확인 상태가 결과에 그대로").

## (d) M15 kinase 541개 ⊂ kbase 참조, `not_in_kbase_references` 도달 가능성

**명령.** `kbase_check.py m15 <kbase> .deps/reference`(표준 라이브러리만, M26 preflight (g)의 `m15_kinase_accessions` 읽기 방식) → exit 0. `<S>/sifts_accessions.py`·`<S>/sifts_only_probe.py`(스크래치패드에서 `mw.reference_snapshots`·`mw.residue_numbering`를 읽기 전용으로 사용, 커밋하지 않음) → 둘 다 exit 0.

- 활성 M15 세트 `aa21ead9…3317`, `uniprot/2026-09-15/entries.jsonl` 542행 = `ok` 541 + `lookup_failed` 1(`O43930`). **541개 모두 kbase `references`의 `uniprot`에 있다**(빠진 것 0). kbase 참조의 서로 다른 accession 542개 중 M15 `ok`가 아닌 것은 `O43930` 하나(M15에서 `lookup_failed`).
- 그러나 M15 번호 대응이 `mapped` 행에 붙이는 accession은 UniProt `ok` 집합에만 있지 않다. M15 `plan_chain`은 SIFTS 체인의 단일 accession이 UniProt 스냅샷에 없으면 SIFTS만 쓰는 계획(`methods: ["sifts"]`, `cross_check_absent_reason: sifts_accession_not_in_uniprot_snapshot`)을 세우고, `row_status`는 방법이 하나일 때 위치가 있으면 `mapped`를 준다(`row_status({"accession": "X", "position": 1}, None) → ("mapped", …)`). 활성 SIFTS 스냅샷의 쓸 수 있는 체인 624개 중:
  - 단일 accession이 UniProt 스냅샷에 없는 체인 **2개**: `7Z87` A → `P78527`, `8H7G` A → `Q15393`. 두 체인 모두 `plan_chain` 결과가 `methods: ["sifts"]`이고, 스냅샷의 SIFTS 잔기 행을 그대로 잔기로 넣어 `sifts_answers` → `row_status`를 돌리면 `7Z87` A는 4,128개 중 3,689개, `8H7G` A는 1,217개 중 1,168개가 `mapped`다(구조 파일로 한 실행이 아니라 M15 함수에 스냅샷 행을 넣은 탐침). 두 accession 모두 **kbase 참조에 없다**.
  - 여러 accession(융합) 체인 5개: `4WTV` A(P00720·Q8TCG2), `4YC4` A(D9IEF7·Q9BTU6), `5EZV` A(P54646·Q13131), `5JGA` A(O43318·Q15750), `6DC0` A(P49715·Q96RU8) — M27에서는 `not_linked` `multiple_accessions`가 될 체인이다.
  - 그 밖 617개는 두 방법을 쓸 수 있는 체인이다. 쓸 수 없는 체인 34개(`sifts_chain_no_segments` 28·`sifts_chain_lookup_failed` 6).
- **결론.** "M15 UniProt `ok` 541개 ⊂ kbase 참조"는 참이지만, "`not_in_kbase_references`는 실데이터로 도달 불가"는 **원리상 거짓이다**: 사용자가 `7Z87`이나 `8H7G` 구조를 올리고 `pdb_id`를 주면 그 체인은 SIFTS만으로 `mapped`가 되어 `linked`(P78527 / Q15393)가 되고, kbase 참조가 없으므로 표적 상태가 `not_in_kbase_references`가 된다. 이 두 구조는 저장소에 없고 내려받기 한도 밖이라 **이 단계의 실데이터 QA로는 만들 수 없으며 테스트는 명세대로 합성으로만 한다.** 명세의 상태 정의("kbase가 이 표적을 모름이며 전례 없음이 아니다")는 이 경우에도 정확하므로 코드·상수 변경은 필요 없고, T12 문서의 "실데이터로 도달 불가" 문장만 위 사실로 고쳐 적어야 한다(아래 다른 점 1). 멈출 조건 아님.

## (e) 카디널리티 결합 지도 (grep으로 확정한 실제 위치, `6ac3a59`)

명령: `grep -rn "link_reaction_knowledge\|\"reaction_knowledge\"" backend/tests frontend/src frontend/tests scripts .codex config docs/standards.md docs/operations.md`, `grep -n "SUPPORTED_TOOLS\|methods\[\"\|reaction_knowledge" backend/mw/api/app.py`, `grep -rn "\.prechecks\|SUPPORTED_TOOLS\|set(methods)" backend/tests`, `grep -n "mw-app-panel-knowledge\|tabSignature\|section.mw-unavailable" frontend/tests/offscreen/*.cjs` 등. M26이 새 도구·보고서·capability·읽기 라우트·지식 탭 영역을 더하며 고친 곳을 같은 방식으로 따라갔다.

**서버 등록 지점(새 항목을 더해야 하는 곳).**
- `config/tools.yaml`: 새 도구 명세(M26 `link_reaction_knowledge`는 252행부터).
- `backend/mw/workspace.py:12–23`(`from .tools import …`)·`34–46`(`build_registry`의 `register` 호출 목록).
- `backend/mw/api/app.py:134–137` `SUPPORTED_TOOLS`; `669–671`(`methods["residue_numbering"]`·`methods["reaction_knowledge"]` 다음에 `methods["kinase_precedents"]`; `analysis_workflows`는 668행에서 그보다 먼저 계산되므로 M13 템플릿에 영향 없음 — 모양 시험 선례 `test_numbering_api.py:80–108`); `1272` `create_method_report`의 종류 분기(M26 분기 `1326–1330`, 끝은 `raise EvidenceError("wrong_method_result_kind")`); `1354–1359` `list_reports`의 bounded-load 분석 종류 집합; `1373–1378` `_saved_any_report`의 같은 집합과 `1413–1414` 다시 열기 분기; 읽기 라우트(M26 선례 `1694–1752`: `/reaction_reference/status`, `/runs/{rid}/reaction_knowledge`, 경로 handle 라우트 `/{handle:path}`를 하위 경로 뒤에).
- `backend/mw/tools/registry.py`는 바꿀 필요 없음(사전 검사 훅은 `reg.register(..., precheck=...)`로 등록).

**새 도구·capability·보고서 종류 때문에 기대가 바뀌는 기존 테스트(최소 수정 대상).**
- `backend/tests/test_api.py:279–286` — `/tools`(L1–L5) 이름 집합에 `link_kinase_precedents` 추가.
- `backend/tests/test_ligand_api.py:420–424`·`455–459` — `set(methods) == PRIOR_METHODS | {…}`에 `kinase_precedents` 추가(`PRIOR_METHODS`는 23행).
- `backend/tests/test_reference_site_annotation.py:692–698`, `backend/tests/test_residue_numbering.py:747–753` — `set(build_registry().prechecks)` 집합에 새 도구 추가(새 도구가 사전 검사 훅을 가지므로).
- 고칠 필요 없음(지키기만): `test_*_tool.py`의 `reg.prechecks[TOOL] is …`(자기 도구만), `test_jev_api.py:486`·`test_jev_loops_api.py:791–796`(집합에서 빼고 더하는 패치), `test_*_jobs.py`의 "작업 전용 도구는 `SUPPORTED_TOOLS`에 없음".
- 보고서 종류 집합을 하드코딩한 백엔드 테스트는 grep으로 찾지 못했다(M26도 `app.py` 집합만 고침).

**AST·문자열 검사(고칠 필요 없음, 새 모듈이 지켜야 함).** `backend/tests/test_docking_batch_budget.py:127–151`(모든 `backend/mw` 본문에서 `raise_limits`·`limit_approval` 문자열을 찾음 → 새 모듈의 주석·docstring에도 쓰면 실패), 같은 검사 `test_ligand_ga_budget.py`·`test_sequence_ga_budget.py`; `test_jev_ast.py:113–156`(httpx는 `egress/` 안만, `urllib.request`·`http.client`는 `egress/` 밖 어디에도 없음; `NEW_MODULES` 21행은 M24 모듈 목록이라 M27 모듈을 넣을 필요 없음).

**골든.** `backend/tests/fixtures/jev/golden_science_m24.py`·`golden_science_m24.json`, `fixtures/jev/prototype_golden_egress.py`·`golden_egress_events.json`(`test_jev_science_gate.py`가 subprocess로 `--check`), `fixtures/sequence_ga/prototype_golden_call_keys.py`·`golden_call_keys.json`(`test_sequence_ga_jobs.py::test_golden_m18_m19_m21_call_keys_results_and_hashed_files_are_unchanged`가 다시 만들어 같음을 단언). M27은 다시 기록하지 않는다((h)).

**프런트.**
- `frontend/src/lib/api.ts:75`(`methods` 형에 `kinase_precedents?`), `94–97`(method report manifest `analysis_type` 유니언), `265`(`command`의 도구 이름 유니언), 새 읽기 함수(M26 선례 `544–556`).
- `frontend/src/lib/contracts.ts`(M26 형 블록 `1231–1356`과 같은 새 블록; `1356` 보고서 manifest 형).
- `frontend/src/lib/report-library.ts:99`(`reportKindLabel`에 새 종류 한 줄), `frontend/tests/report-library.test.cjs:53–58`(M26 줄 옆에 새 기대).
- `frontend/src/components/WorkspaceTabs.tsx:14`(슬롯 prop)·`54–59`(지식 탭 패널 안 순서: numbering → reaction → jev → reports), `frontend/app/page.tsx:2067–2073`(M26 `ReactionKnowledgePanel` 슬롯 연결, `key`는 run마다). `page.tsx:23`은 패널을 직접 import하므로 `components/index.ts`는 M26처럼 바꾸지 않아도 된다(계획 T7 대상 목록에 있으나 선택).
- `frontend/tests/workspace-tabs.test.cjs:18·40–` — 탭 id 넷과 "안내 없음"만 보므로 영역을 더해도 그대로.
- 오프스크린 하네스: `jev-flow.cjs:347–368`·`reaction-knowledge-flow.cjs:348–362`의 `tabSignature`는 지금 **단백질·리간드 탭만** 비교한다(M26 preflight 당시 기록과 달리 지식 탭 글자 비교 없음) → 지식 탭 영역 추가로 깨지지 않는다. **`tabs-flow.cjs:262–270` `knowledgeScreen`은 지식 탭 안 `section.mw-unavailable` 개수가 0이어야 한다** → 새 패널의 "사용할 수 없음" 상태는 그 요소·클래스를 쓰면 안 된다(M26 패널은 `p.mw-reaction-unavailable`/`div`를 씀). 지식 탭 선택자는 `#mw-app-panel-knowledge [data-testid="jev-panel"|"reaction-panel"]`처럼 영역 testid로 범위를 좁혀 쓰고 있어(`jev-flow.cjs:372`, `jev-loop-flow.cjs:1157`, `mutation-flow.cjs:1542·2046`, `reaction-knowledge-flow.cjs:395·1209`) 새 영역이 겹치지 않는 testid(`kinase-precedents-panel` 등)를 쓰면 영향이 없다.

**Stop 훅(`.codex/hooks/stop.py`)과 기대(`scripts/test_codex_hooks.py`).**
- `SCRIPT_TESTS` 26–37행(22개): 새 `scripts/test_import_precedent_snapshots.py`(T3)와 `scripts/test_m27_offscreen_acceptance.py`(T8)는 **손으로 넣어야 한다** — `test_codex_hooks.py:151–182`가 모든 `scripts/test_*.py`가 나머지 그룹 인자에 정확히 한 번 있는지, 모든 `backend/tests/**/test_*.py`가 정확히 한 그룹에 있는지 검사한다(fixture 폴더 안 파일 이름도 `test_*.py`면 `backend/tests` 수집과 이 검사에 걸리므로 fixture 스크립트를 `test_`로 시작하지 않는다).
- `PYTEST_GROUPS` 63–88행: 이름 있는 그룹 15개(+ 나머지 그룹 `REST_GROUP` 101행 = pytest 16개), `CHECKS` 104–107행 = ruff 1 + pytest 16 = 17. `test_codex_hooks.py:145` `assert len(stop.CHECKS) == 17`, `146` 모든 pytest 그룹 시간 한도 480 s, `147` 45 + 480 + 4 < 600. `CHECK_TIMEOUT = 480`(115행), `RUFF_TIMEOUT = 45`.
- 새 백엔드 테스트 파일은 자동으로 나머지 그룹에 들어간다. 나머지 그룹 단독 측정은 아래 "나머지 그룹 기준선".
- 문서 게이트 목록: `docs/standards.md:38–58`(스크립트 pytest 한 줄 40행, `node --check` 41–55행), `docs/operations.md:155–164`(Stop 훅 그룹 설명 문단들).

**나머지 그룹 기준선.** `.codex/hooks/stop.py`를 파일 경로로 불러 `REST_GROUP` 인자를 그대로 만든 뒤(`backend/tests` + `SCRIPT_TESTS` 22개 + 이름 있는 그룹 파일의 `--ignore`) 다른 pytest 부하 없이 혼자 돌렸다: `.venv/bin/python -m pytest -q <REST_GROUP>` → **3,554 passed, 408.77 s, exit 0**(제한 480 s, 여유 약 71 s; M26 고정 때 3,553개 416.8 s). 출력 `<S>/rest_group.out`. M26의 새 백엔드 테스트 여섯 파일이 449개였던 것에 비추면 M27의 새 백엔드 테스트(T2·T4·T5의 여섯 파일 안팎)를 나머지 그룹에 그대로 두면 한도를 넘을 가능성이 크다.

## (f) 회귀 실행기 격리 결정

**문제.** M13–M26 수락 실행기의 백엔드 env는 `m13.child_env` 허용 목록(PATH·HOME·…·`LC_*`) + 실행기가 정한 변수뿐이다: `m13_offscreen_acceptance.py:308–309`·`m14_offscreen_acceptance.py:259–260`(`MW_RUNS_DIR`만), `m15:243–245`·`m17:216–218`·`m24:674–675`·`m25:945–946`(+`MW_REFERENCE_DIR`), `m26:686–689`(+`MW_REFERENCE_DIR`·`MW_REACTION_REFERENCE_DIR`). 어느 것도 `MW_PRECEDENT_REFERENCE_DIR`를 넘기지 않으므로 그 백엔드는 코드 루트 기본값 `<repo>/.deps/precedent_reference`를 읽는다(M13의 "unavailable" 백엔드는 `.deps` 없는 복사본이라 늘 `not_installed`). 테스트 `scripts/test_m*_offscreen_acceptance.py`에는 env 키를 단언하는 곳이 없다(grep 0건).

**결정: (1) 회귀 동안 `.deps/precedent_reference`를 없는(설치되지 않은) 채로 둔다. 실행기는 고치지 않는다.**

이유:
1. M26의 같은 문제에서 이미 (1)을 골랐고 회귀 사슬 전체가 그렇게 통과했다(`docs/tracking/m26-acceptance.md:79·106`, `docs/qa/m26-reaction-20261008/regression-chain.txt:4`). 같은 규칙을 두 가족에 똑같이 적용하면 절차가 하나로 남는다("옛 실행기를 돌릴 때 `.deps/reaction_reference`와 `.deps/precedent_reference`를 둘 다 없는 채로").
2. 인계 절대 조건 11("바뀐 기존 검사만 최소로")에 맞다. (2)를 고르면 env를 만드는 일곱 곳(위 목록, M26 실행기 포함)을 고치고 각 실행기의 회귀 증거가 바뀐 코드 기준이 된다.
3. 새 가족의 기본 폴더에 실데이터를 둘 이유가 이 단계 개발에 없다. T3·T8·T10의 실제 가져오기는 모두 격리 폴더(`--dest <격리>`, `MW_PRECEDENT_REFERENCE_DIR`)로 하고 기본 폴더에는 쓰지 않는다. 지금 `.deps/precedent_reference`는 없다(`ls` → No such file or directory, `.deps/reaction_reference`도 없음).
4. 설치되지 않은 상태의 새 영역은 숫자·컨트롤 없이 이유와 명령 안내만 보이므로(명세 §8) 옛 하네스가 다루는 컨트롤·버튼 이름과 겹치지 않는다.

뒤 작업이 지킬 것: T7 — 새 영역은 "사용할 수 없음" 상태에 `section.mw-unavailable`을 쓰지 않고, 탭 진입 때 GET만 보내며, 설치되지 않음 상태에는 버튼이 없다. T8 — M27 실행기는 `MW_PRECEDENT_REFERENCE_DIR`(격리 폴더)와 `MW_REFERENCE_DIR`(M15 활성 세트 복사본)를 명시하고 M26 가족은 격리 빈 폴더나 없는 상태로 둔다. T10 — 회귀 시작 전에 `ls .deps/precedent_reference .deps/reaction_reference`가 둘 다 없음을 기록하고, 사슬이 끝날 때까지 기본 폴더에 가져오기를 하지 않는다. (2)가 필요해지는 경우(누군가 기본 폴더에 실세트를 설치한 채 회귀를 돌려야 할 때)에는 일곱 곳의 `child_env` 인자에 빈 격리 폴더의 `MW_PRECEDENT_REFERENCE_DIR` 한 줄씩을 더하는 것이 최소 변경이다.

## (g) 원자적 설치·고정·캐시 패턴: 복사할 것과 공유하면 안 되는 것

**서버 고정 모듈 `precedent_snapshots.py`가 M26 `reaction_snapshots.py`(215줄)에서 옮겨 쓸 것(복사해 별도 구현, import하지 않음):** `reference_dir()`(환경변수, 상대 경로는 저장소 루트 기준, 빈 값이면 기본 폴더), `_read_limited`(`O_RDONLY|O_NOFOLLOW`, `fstat` 일반 파일, 크기 상한, 읽는 중 커짐 거부), `_read_pointer`(키 집합 정확히 `{schema, set_hash}`, 64자 hex, 포인터 크기 상한 4 KiB), 세트 폴더가 `lstat`으로 일반 디렉터리(심볼릭 링크 아님), 매니페스트 바이트 SHA-256 = 포인터 해시 + `canonical_json(json.loads(raw, parse_constant=거부)) == raw` + 형식 검증, 목록의 각 파일이 `resolve(strict=True)`로 세트 폴더 안, `_stat_identity`(dev·ino·size·mtime_ns·ctime_ns)와 "성공한 검증만, 세트 폴더당 하나" 캐시(`_VERIFIED`·`_LOCK`, 검증 전후 stat 비교), `_verify_file`(바이트·SHA-256·줄 수 = `\n` 개수이고 마지막 바이트가 `\n` — 실제 네 파일 모두 이 규칙과 매니페스트 `rows`를 만족, (a) 표), 한 세트 폴더에 묶인 고정 객체(접근자는 그 폴더만, `read_bytes`가 매번 해시 재확인 후 다르면 `snapshot_invalid`), `files_identity`를 내보내 상위 색인 캐시 키로 쓰기, `SnapshotUnavailable(reason_code)`의 `not_installed`(포인터 없음 = `FileNotFoundError`)·`snapshot_invalid`(그 밖 `OSError`/`ValueError`/`RecursionError`), `capability()`의 다섯 키 모양(사용할 수 없으면 `set_hash: null`·`sources: []`).

**세트 단위 색인 캐시(`kinase_precedents.py`)가 M26 `reaction_knowledge.reaction_index`에서 옮겨 쓸 것:** 키 `(pinned.set_hash, pinned.files_identity)`, 성공만, 넣을 때 비워 세트 하나만, 잠금 안에서 조회·교체. 색인 만들기 실패(형식 검사 §3.4 불통과)는 `snapshot_invalid`.

**가져오기 명령 `import_precedent_snapshots.py`가 M15 `scripts/import_reference_snapshots.py`(270줄, 로컬 kbase 복사 — 가장 가까운 선례)에서 옮겨 쓸 것:** `ImportFailure`(거절 시 대상 폴더 불변), `canonical_json`(같은 식), `_sha`, `_fsync_dir`, `_write_file`(`O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, 끝까지 쓰고 fsync), 설치 순서(모든 검사 통과 뒤에만 쓰기 → `sets/.staging-<uuid>`에 파일·매니페스트 → 디렉터리 fsync → `os.rename(staging, sets/<hash>)` → `sets` fsync → `.active.json.<uuid>.tmp` 쓰기 → `os.replace` → 상위 fsync, 실패하면 staging·임시 포인터만 지움, 최종 폴더가 이미 있으면 거절), git 하위 프로세스 호출 모양(`subprocess.run(["git", "-C", kbase, …], capture_output=True, text=True, timeout=60, check=False, stdin=DEVNULL, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})`, 0이 아니면 거절), 시계·git 주입 인자(`now=`, `git_info=`)로 시험 가능하게 하기, `_latest`(최신 날짜 스냅샷 고르기)의 "가장 최근 날짜" 규칙.

**공유·복사하면 안 되는 것.**
- M15·M26 모듈 전역 캐시(`reference_snapshots._VERIFIED`·`reaction_snapshots._VERIFIED`·`residue_numbering._INDEXES`·`reaction_knowledge._INDEX_CACHE`)와 잠금: 새 가족은 자기 캐시를 둔다(한 가족의 세트 교체가 다른 가족 캐시를 비우지 않게).
- 상수: `ENV_VAR`·`DEFAULT_DIR(_PARTS)`·`ACTIVE`/`SET`/`POINTER` 스키마 이름·`ORIGIN`·`SOURCES`·`SNAPSHOT_REASONS` 문구(각 가족의 가져오기 명령을 가리킴)·`MAX_FILE_BYTES`(M15·M26 512 MiB, M27 명세 64 MiB)·줄 수 상한(M27 100,000).
- 매니페스트 검증기: M15 `_validate_manifest`(`reference_snapshot_set@1`, `kbase_repo`, `sources[].files` 경로 `source/date/name`), M26 `validate_manifest`(`reaction_reference_set@1`, `files/<source>/<name>`, `request_log`) — M27은 `precedent_reference_set@1`(§3.2: `kbase`·`files[3]`·`bibliography`·`verification`, 경로 `files/dist/<name>`·`files/pubmed/<date>/documents.jsonl`)로 새로 쓴다.
- M15 `_now()`(마이크로초 `%Y-%m-%dT%H:%M:%S.%fZ`) — M27은 초 단위 `YYYY-MM-DDTHH:MM:SSZ`(§3.2). M15 `read_git_info`(저장소 전체 `status --porcelain`, `commit`·`dirty`만) — M27은 `rev-parse HEAD` + `log -1 --format=%H%n%cI -- dist` + `status --porcelain -- dist ref/pubmed`(§4.1, 범위가 좁은 dirty; 실측은 둘 다 0줄). M15 `_rows`(마지막 줄 바꿈 없는 줄도 셈) — 서버 검증과 같게 `\n` 개수 + 마지막 바이트 규칙을 쓴다. M15 `_collect`·`_check_snapshot`(UniProt·SIFTS·KLIFS 전용), M15 CLI(`--from`·`--dest`는 같은 이름이지만 M15는 환경변수를 보지 않음 — M27 `--dest` 기본은 `MW_PRECEDENT_REFERENCE_DIR` 또는 `.deps/precedent_reference`).
- M26 가져오기의 네트워크 전부(`urllib`, 허용 호스트, `validate_url`, 전송 주입, 요청 로그 `request_log.jsonl`) — M27 가져오기는 네트워크 모듈을 import하지 않는다.
- M26 가져오기가 상수 모듈을 파일 경로로 불러 쓰는 방식은 그대로 따른다(`precedent_constants.py`만, `mw` import 없음).

## (h) 호출 키 해시 파일과 골든 기준선

**해시 파일 바이트(`git ls-tree HEAD`, HEAD `6ac3a590eabf55ad0d5e3a31a2e1a933aa5dbdf0`).** 명령: `git ls-files backend/mw | grep -E "docking_worker\.py|docking_constants\.py|openmm_mutation_worker\.py|mutation_model_constants\.py|mutation_model_math\.py|mutation_candidates\.py|ligand_ga_|sequence_ga_|docking_batch_"`(27개) → `git diff --quiet HEAD -- <27개>` exit 0(작업 트리 = HEAD), `git ls-tree HEAD <27개> | shasum -a 256` = `3a2fc4093bbb61b936c347741f06dd2c9b39df21e305c168d9d4d57872193cb0`(뒤 작업이 같은 명령으로 비교).

| git blob | 경로 |
|---|---|
| `99324f07fc9519454330c4195f5036f8344752b2` | `backend/mw/docking_batch_bundle.py` |
| `b9eb497a8edf27d0a38a203d70a4fe9958923851` | `backend/mw/docking_batch_constants.py` |
| `21c96abe501b6c3a01e8dc62435901f2499c6d5b` | `backend/mw/docking_batch_inputs.py` |
| `25db2dbfb5c016b6fff3d78dedc512ade3ffd1d6` | `backend/mw/docking_batch_jobs.py` |
| `b10e8ab712c530d8d3eaebb808be47be13ac7652` | `backend/mw/docking_batch_reads.py` |
| `e5985e188bf8bbcb4862a26be126c8fb529db1d4` | `backend/mw/docking_batch_reports.py` |
| `4097a474d3adaf16a70eb9914d2864fff2c62c68` | `backend/mw/docking_constants.py` |
| `252582abf85478358857837a936a95a8e72a4000` | `backend/mw/jobs/docking_batch_worker.py` |
| `2585689176091e19cae66ac798b37e92d8bc64b0` | `backend/mw/jobs/docking_worker.py` |
| `17c19542bbf8a340b6fa86e3c656bfa191938642` | `backend/mw/jobs/ligand_ga_worker.py` |
| `71e5e9d90409dbb15aba5088b4686f00a832989d` | `backend/mw/jobs/openmm_mutation_worker.py` |
| `6e3a6f9ff8b1eb4a5af6e5647bf45dc41c877763` | `backend/mw/jobs/sequence_ga_worker.py` |
| `0da89ee65d9812819ac0f06acd6fe20ca8de1ceb` | `backend/mw/ligand_ga_bundle.py` |
| `d3dce79f3966272de2d994ddec8dbc8c8c19265d` | `backend/mw/ligand_ga_constants.py` |
| `f6916713dbfef8ce32fcb4be9aad884b0e22b2d5` | `backend/mw/ligand_ga_inputs.py` |
| `1fa628897baaf4bce7e2ea602f16f3b21d8284f1` | `backend/mw/ligand_ga_jobs.py` |
| `3f05e3d6040f17130d0a0c8f807e1f7a8aefbd02` | `backend/mw/ligand_ga_reads.py` |
| `2d0bd4c3160f4bec5d3e014febc83f79a39129cb` | `backend/mw/ligand_ga_reports.py` |
| `ec3f5468b869b4109050ccdb2ade79d8b46ca784` | `backend/mw/mutation_candidates.py` |
| `f9187acf8583d16a595bf7b75ebd4430d48d8d33` | `backend/mw/mutation_model_constants.py` |
| `6cb8b5abb2246ceb02b9d3604b1e44a6cc72b70b` | `backend/mw/mutation_model_math.py` |
| `aaa946823f99b474ffcca2f3c89bc0db84bb5823` | `backend/mw/sequence_ga_bundle.py` |
| `53c679fdc18bd5fd80d198cc2b0664ae640389e2` | `backend/mw/sequence_ga_constants.py` |
| `926a13c267c383798cb1ed5a1c1f1220c716f2e8` | `backend/mw/sequence_ga_inputs.py` |
| `bd11e964b5f6d5533ded1dbc0a2eb1b60e63a154` | `backend/mw/sequence_ga_jobs.py` |
| `e35e0de40469061bbce95229431ab69a2f29b3f1` | `backend/mw/sequence_ga_reads.py` |
| `5074ae2479b984c3c6b78e11dc08f573b3777c1a` | `backend/mw/sequence_ga_reports.py` |

골든 파일 blob: `golden_science_m24.json` `ec5449c45d4c64815915e5aaa0fdceb80c2773d7`, `golden_egress_events.json` `a872d090c459971f0b5990b99c6d451f3d7a2894`, `golden_call_keys.json` `b9b3ca6b50ef0e4f0878e3f151251252e3382cbf`.

**골든 기준선(이 작업 시작 시점, 바꾸지 않은 코드).** `docs/standards.md`의 게이트 목록에는 골든 명령이 없어 M26 완료 게이트(`docs/qa/m26-reaction-20261008/gate.txt:38–47`, `docs/tracking/m26-acceptance.md:58–59`)의 명령을 그대로 썼다.

| 명령 | 종료 코드 | 시간 | 마지막 줄 |
|---|---|---|---|
| `.venv/bin/python backend/tests/fixtures/jev/golden_science_m24.py --check --work <S>/golden/gs_work` | 0 | 6 s | `golden_science_m24.json matches a fresh recording` |
| `.venv/bin/python backend/tests/fixtures/jev/prototype_golden_egress.py --check` | 0 | <1 s | `golden_egress_events.json matches a fresh recording` |
| `.venv/bin/python backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py <S>/golden/gck_runs <S>/golden/golden_call_keys.json` | 0 | 45 s | (실제 qvina·OpenMM 작업) |
| `cmp <S>/golden/golden_call_keys.json backend/tests/fixtures/sequence_ga/golden_call_keys.json` | 0 | — | 바이트 동일 |

골든 실행 뒤 `git status --short`에는 이 작업이 만든 새 파일만 있었다(골든 파일 변경 없음).

**결론.** 호출 키 해시 파일 27개는 HEAD와 같고, 두 골든 `--check`와 `golden_call_keys.json` 재기록 `cmp`가 지금 통과한다. M27 설계(명세 §9.3)는 이 파일들을 건드릴 필요가 없다 — 새 서버 모듈은 이 파일들을 import하지 않고, 번호 대응 객체는 저장소에서 읽기만 한다. 변경이 불가피해 보이는 지점 없음.

## 명세·인계 문서와 다른 점

| # | 항목 | 명세·인계 | 측정 | 영향·처리 |
|---|---|---|---|---|
| 1 | `not_in_kbase_references` 도달 가능성 | "실데이터로 도달 불가, 합성으로만" (§10 ③, 인계 "알려진 환경 사실") | M15 UniProt `ok` 541 ⊂ kbase 참조는 참. 그러나 M15가 SIFTS만으로 `mapped`를 만드는 체인 2개(`7Z87` A → P78527, `8H7G` A → Q15393)의 accession은 kbase 참조에 없다 → 그 구조를 올리면 원리상 도달 | 코드·상수·상태 정의 변경 없음. 이 단계에서는 구조가 없어 합성으로만 시험(명세대로). T12 문서에서 "도달 불가"를 "현재 M15 세트에서는 SIFTS 단독 체인 2개(구조는 저장소에 없음)로만 도달"로 고쳐 적는다. |
| 2 | `quote_truncated` 수 | "두 파일 합쳐 136건(`moves` 83건은 관찰 문장)" | 관찰 인용 136(83 + 53). 교환(tradeoffs) 인용의 `quote_truncated` 참 27(8 + 19)이 따로 있어 표시 대상은 모두 163 | 화면·보고서는 관찰·교환 인용 각각의 플래그를 보인다. 수치 기대를 적는 테스트·문서는 어느 수인지 밝힌다. |
| 3 | 미해석 이름 수 | "서로 다른 이름 35개와 이름 없음" | 문자열 이름 34개 + null(122건, 모두 근거 absent) = 서로 다른 `name_as_written` 값 35개 | `set_summary.unresolved_names_total`(명세: 서로 다른 이름 수, null 포함 목록)은 실데이터에서 35가 된다. 100 상한 안. |
| 4 | 실데이터에 없는 닫힌 값 | — | `direction_basis` `none` 0, 위치 `kind` `figure` 0, `structure_links.basis` `sole_candidate` 0, `resolution_basis` `klifs_gene_name` 0, 25단어 초과 인용 0(→ `quotes_within_limit` 거짓은 실데이터로 도달 불가) | 닫힌 집합은 명세 그대로 두고 해당 값은 합성 fixture로만 시험한다(명세 §10이 이미 25단어 초과를 합성으로 요구). |
| 5 | 1FIN B·D | "체인 목록에서 뺀다"(가정) | 넣으면 호출 전체가 422 `no_usable_method`(B); B에 P20248을 주면 422 `accession_not_in_uniprot_snapshot` | 가정이 맞음. 실데이터 단계는 A·C만 요청. |
| 6 | `no_mapped_residues`·`multiple_accessions` 실데이터 | "있는지 확인, 없으면 합성" | `no_mapped_residues`: 1FIN B에 틀린 kinase accession(P24941)을 직접 준 입력 실수로만 도달(mapped 0/260). `multiple_accessions`: 허용 구조로는 불가, M15 SIFTS에 융합 체인 5개(구조 없음) | 둘 다 합성으로 시험. 틀린 accession 사례는 정상 수락 사례로 쓰지 않는다. |
| 7 | 결과 크기 | "최악 표적 BTK 포함 시 약 0.8 MiB" | 단일 표적 최대 855,798 B(BTK, 포함). 서로 다른 accession 두 체인(BTK + EGFR, 포함)이면 1,604,884 B로 초과 | 명세의 거절 규칙(`result_too_large`, 체인 빼기·`include_flagged` 끄기 안내)으로 처리된다. 합성 크기 초과 시험과 별개로 실제 크기 사례가 있음을 기록. |
| 8 | Stop 훅 나머지 그룹 여유 | 인계: "M26 여유 약 63초, 새 백엔드 테스트는 나머지 그룹이 자동 포함, 시간만 확인" | 나머지 그룹 단독 3,554개 408.77 s(여유 약 71 s) — 새 백엔드 테스트가 수백 개 늘면 넘을 가능성이 큼 | M27 백엔드 테스트 파일들은 이름 있는 새 그룹으로 넣고 `scripts/test_codex_hooks.py:145` 기대를 17 → 18로 같이 고친다(계획 T10 소유; T2·T4 테스트가 들어오는 시점에 Stop 훅이 시간 초과를 보고하면 그때 나눈다). |
| 9 | 지식 탭 글자 비교 | 계획: `jev-flow.cjs`의 `tabSignature`가 지식 탭 글자 비교 | 지금 `tabSignature`는 단백질·리간드 탭만 비교. 대신 `tabs-flow.cjs:262–270`이 지식 탭의 `section.mw-unavailable` 0개를 단언 | T7은 그 요소를 쓰지 않는다. 지식 탭 글자 기대를 고칠 하네스는 지금 없다. |
| 10 | `components/index.ts` | 계획 T7 대상 | M26 패널은 `index.ts`에 없고 `page.tsx`가 직접 import | T7에서 선택(바꾸지 않아도 됨). |
| 11 | 골든 명령의 위치 | 계획: "`docs/standards.md` 게이트 목록에서 명령 확인" | 게이트 목록에 골든 명령이 없다(M26 게이트 기록에만 있음) | 이 문서 (h)의 명령을 기준으로 쓴다. T12에서 게이트 목록에 넣을지 정한다. |
| 12 | 참조 레코드 키 | 필수 10개 | 18개(필수 10 + 8). 결과 사본 대상은 명세 §5.6의 7개 키뿐 | 영향 없음(형식 검사는 필수 키 존재만 봄). |

그 밖에 명세 §3.4·§3.5·§4.5·§5와 다른 점은 없다.

### 작업별로 바꿀 기존 파일 (결합 지도 요약)

| 작업 | 바꿀 기존 파일(새 파일 제외) |
|---|---|
| T2 | 없음. 지킬 것: 증액 문자열 AST 셋, `test_jev_ast.py`, fixture 스크립트 이름을 `test_`로 시작하지 않기 |
| T3 | `.codex/hooks/stop.py` `SCRIPT_TESTS`(+`scripts/test_import_precedent_snapshots.py`) |
| T4 | `config/tools.yaml`, `backend/mw/workspace.py`(import·`build_registry`), `backend/mw/api/app.py`(`SUPPORTED_TOOLS` 134–137, `methods["kinase_precedents"]` 671 다음, 읽기 라우트 셋), `backend/tests/test_api.py:279–286`, `test_ligand_api.py:420–424·455–459`, `test_reference_site_annotation.py:692–698`, `test_residue_numbering.py:747–753` |
| T5 | `backend/mw/api/app.py`(`create_method_report` 분기 1326–1331 근처, 집합 1354–1359·1373–1378, 다시 열기 분기 1413–1414 근처) |
| T6 | `frontend/src/lib/api.ts`(75, 94–97, 265, 새 읽기), `lib/contracts.ts`, `lib/report-library.ts:99`, `frontend/tests/report-library.test.cjs:53–58` |
| T7 | `frontend/src/components/WorkspaceTabs.tsx`(14, 54–59), `frontend/app/page.tsx`(2067–2073 근처), `design/components.css`, 토큰 생성물, (선택) `components/index.ts` |
| T8 | `.codex/hooks/stop.py` `SCRIPT_TESTS`(+`scripts/test_m27_offscreen_acceptance.py`). 옛 실행기 `child_env`는 (f) 결정으로 바꾸지 않음 |
| T10 | 필요하면 `.codex/hooks/stop.py` `PYTEST_GROUPS`(새 이름 있는 그룹)·`scripts/test_codex_hooks.py:145`(17 → 18) |
| T12 | `docs/standards.md:38–58·76·92`, `docs/operations.md:155–164`, 기록 문서 |
