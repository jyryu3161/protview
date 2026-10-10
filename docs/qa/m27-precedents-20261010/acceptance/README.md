# M27 키나아제 전례 오프스크린 수락 QA 증거

- 생성: 2026-10-10T13:28:14.561837+00:00 · verdict **pass** · acceptance **true** (두 단계가 이번 실행에서 모두 돌고 통과하고, 실제 kbase 문구가 커밋 증거에 없을 때만 true)
- 요청한 단계: fixture, real · 빠진 단계: 없음
- 사례: 46/46 통과
- 남은 프로세스/포트: 없음
- 브라우저 비-loopback 요청 합계: 0 · 접촉한 외부 호스트: 없음
- 커밋 증거에서 찾은 실제 kbase 문구: 0개 파일 (검사한 문자열 7479개)

**fixture 단계의 전례 값은 모두 합성(SYNTHETIC)이다.** `backend/tests/fixtures/precedent/t8/build_qa_set.py`가 `precedent_fixture.py`로 만든 세트(지어낸 accession P0QA01–P0QA04, PMID 9100000n, `MOVE-7xxx`, SYNTHETIC 문구; `SYNTHETIC-PROVENANCE-t8.md`)이고, 파생 번호 대응(d-two·d-fusion·d-big)은 M15 도구가 만든 실제 번호 대응의 mapped 행 accession만 지어낸 값으로 바꾼 합성 변형이다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 과학 결과가 아니다.

**real 단계는 실제 kbase_kinase `dist/`를 사용자 가져오기 명령으로 격리 폴더에 두 번 설치해 썼다**(소켓을 막고 센 자식 프로세스, 시도 0). 구조는 공개 PDB 항목 1MQ4(저장소)·1M17·1FIN(T1 내려받기, RCSB CC0)이고 1FIN은 체인 A·C만 번호 대응에 넣었다. 크기 시험용 d-size 하나만 합성 변형(1FIN 번호 대응의 두 체인에 P00533·Q06187을 준 것, 1 MiB 초과로 거절되어 저장되지 않음)이다. 이 폴더에는 실제 전례 문구(인용문·관찰 문장·교환 문장·변형 설명·서지 제목)가 없다: 화면 캡처·paint 프레임·보고서 다운로드·실패 패널은 Git 제외 artifacts 폴더에만 있고 아래 목록에는 경로·크기·SHA-256만 있다. 기록한 숫자는 개수이고 상태는 닫힌 집합 값이다.

## 무엇이 커밋이고 무엇이 Git 제외인가

| 커밋(이 폴더) | Git 제외(artifacts 폴더, 해시만 여기) |
|---|---|
| `README.md`, `summary.json`(요약), `cases.json`(사례 목록), `SHA256SUMS`(해시 목록), `binary-artifacts.json`(Git 제외 파일 목록과 해시), `evidence/`(대장·단계 기록·계획·요청 기록, fixture 합성 결과) | PNG(스크린숏·paint), `downloads/`(보고서 Markdown·JSON), 실패 패널 HTML, 256 KiB 초과 텍스트(결정 0020), 실제 kbase 문구가 든 텍스트, 실데이터 세트·run 폴더(`--root`) |

Git 제외로 둔 텍스트 4개: download 4

절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

## 가져오기 실검증 (real)

| 설치 | 종료 | 소켓 시도 | 세트 해시 | 행 수 | verification | dirty |
|---|---|---|---|---|---|---|
| 1 | 0 | 0 | `614f5ecd1e6233c55e56491d356216ebc8d448d589aef468e4fea82d7c04dd6a` | {"files": {"dist/moves.jsonl": 891, "dist/moves_flagged.jsonl": 885, "dist/references.jsonl": 555}, "bibliography": 252} | {"records_hash_verified": {"moves": 891, "moves_flagged": 885, "references": 555}, "references_without_hash": 0} | False |
| 2 | 0 | 0 | `8ac7496b169c5adf62ab995855abb3dafce01925cd937c1d064d2c93afea8fbc` | {"files": {"dist/moves.jsonl": 891, "dist/moves_flagged.jsonl": 885, "dist/references.jsonl": 555}, "bibliography": 252} | {"records_hash_verified": {"moves": 891, "moves_flagged": 885, "references": 555}, "references_without_hash": 0} | False |

- 두 설치의 파일 SHA-256 같음(재현): True · 활성 세트 = 두 번째 설치: True · 기본 폴더 `.deps/precedent_reference` 만들지 않음: True

## 단계 `fixture` — pass

| 사례 | 내용 | 결과 | 단계 |
|---|---|---|---|
| P-no-snapshot | no precedent set: the snapshot block shows 사용할 수 없음, not_installed and the import command only (no numbers, no controls); the request block a reason only; entering the tab posts nothing | pass | fixture-empty:pass |
| P-maps-real-m15 | real M15 maps made by clicks in the 잔기 번호 대응 area: 1MQ4 chain A (PDB ID confirmed, SIFTS O14965) and the derived two-chain 1MQ4 fixture (A O14965 + B Q8IU85; A + B O14965) | pass | fixture-maps:pass |
| P-snapshot-ready | set A: hash (12 + full in title), imported date, kbase / dist commits, dist date, dirty, kb_version, three versions, file rows, bibliography snapshot, processed label, KT1, UP5 with the set-wide N, unresolved-name table (opened) and the resolution-basis counts | pass | fixture-main:pass |
| P-request-defaults | the newest numbering map pre-selected and nothing posted; every chain ticked; the moves_flagged toggle off; 전례 연결 enabled | pass | fixture-main:pass |
| P-chain-previews | chain previews before the request: linked (accession), 연결 안 함 (no_mapped_residues) and 연결 안 함 (multiple_accessions with both accessions) | pass | fixture-main:pass |
| P-refusals | five labelled in-flight request alterations → the real server refuses each admission reason (422); the screen shows "한국어 (code)" beside its field; nothing stored | pass | fixture-main:pass |
| P-chain-states | chain table: linked, not_linked no_mapped_residues (real M15 map) and not_linked multiple_accessions (derived map) with reason "한국어 (code)", accessions, mapped / total, cross check | pass | fixture-main:pass |
| P-chain-select | one chain unticked → chains sent as the remaining list; the result lists only that chain | pass | fixture-main:pass |
| P-target-states | precedents_found (전례 N건), none_in_included_files and not_in_kbase_references (real map, accession absent from the synthetic set) phrases; UP2 under the status whenever excluded_flagged is an integer (0 too); references listed or — with the reason | pass | fixture-main:pass |
| P-target-tabs | a result with two targets: the target tabs switch the target block and its record page | pass | fixture-main:pass |
| P-flagged-toggle | the moves_flagged toggle on: its note; included moves_flagged counts become integers and the excluded count — with the reason | pass | fixture-main:pass |
| P-filters | file, site / goal / tactic terms (OR inside an axis, AND across), variant and text search (record and bibliography title, case-insensitive) — server pages equal the GET of the same query and the counts counted from the synthetic records; a 101-character search is refused on the screen; clear | pass | fixture-main:pass |
| P-sort | sort by PMID (desc) and bibliography year (asc, no integer year last): the screen order equals the server order | pass | fixture-main:pass |
| P-paging | 30 records: 1–25, 다음 쪽 → 26–30 (equal to the server page), 이전 쪽 → back; edges disabled | pass | fixture-main:pass |
| P-detail | record details: bibliography and its absence, every location, observation quote with quote_truncated and quote_assembled, tradeoffs (null quote —), change, measured-change table (target_role, direction_basis, fold_change null — with the reason), structure links with UP4, the ten kbase checks apart from the ProtView integrity values (25-word limit false), content hash note | pass | fixture-main:pass |
| P-fixed-notes | KP1–KP6 verbatim and in order, KT1, UP1–UP5 verbatim (UP2 / UP5 with their N) | pass | fixture-main:pass |
| P-too-large | moves_flagged on for a map above 1 MiB → 429 result_too_large: the refusal with the size advice (without moves_flagged fits; per-target fit), nothing stored | pass | fixture-main:pass |
| P-report | 보고서 만들기 → 키나아제 전례 보고서 in the library; Markdown / JSON downloads equal to the backend bytes; KP1–KP6, KT1, UP2, UP5 present; no quote or observation text; no forbidden word outside fixed lines and stored strings | pass | fixture-main:pass |
| P-results-list | 결과 목록 다시 읽기 (GET only): the list equals the stored list; a file not included shows — with the reason; 빈 결과 for null results | pass | fixture-main:pass |
| P-dry-run | a dry-run run (record over the loopback API; later steps real clicks): M15 map and 전례 연결 store the result | pass | fixture-main:pass |
| P-tabs | 구조 분석 hidden and inert while 지식·보고서 shows, run selection only there, the 단백질 공학 and 리간드 tabs' areas and text unchanged by the precedent work | pass | fixture-main:pass |
| P-no-zero | not included, not computed, no bibliography and null fold_change are — with the reason, never 0 or a bare 없음 | pass | fixture-main:pass |
| P-wording | no rank / recommendation / verified / success rate / effect wording outside the fixed sentences and the stored strings | pass | fixture-main:pass |
| P-unset | active.json moved aside: not_installed with the import command, the request block closed, stored results open from events with 사용 중 스냅샷 없음 | pass | fixture-unset:pass |
| P-invalid | one set file tampered: snapshot_invalid, the request block closed, stored results open with 사용 중 스냅샷 없음 | pass | fixture-invalid:pass |
| P-stale | set B active: the new hash; every earlier result shows 이전 스냅샷 기준 (list and detail), nothing recomputed | pass | fixture-stale:pass |
| S-fixture-no-egress | every flow row: 0 non-loopback browser requests (no host contacted) and zero provider calls | pass |  |
| S-fixture-references | the precedent set changes (none, set A, active.json aside, one file tampered, set B) and the read-only M15 copy, read back over the API; the derived maps stored from a real M15 map | pass |  |

| 흐름 단계 | 결과 | 문제 |
|---|---|---|
| fixture-empty | pass |  |
| fixture-maps | pass |  |
| fixture-main | pass |  |
| fixture-unset | pass |  |
| fixture-invalid | pass |  |
| fixture-stale | pass |  |
| precedent-empty-at-start | pass |  |
| precedent-set-a | pass |  |
| precedent-unset | pass |  |
| precedent-tamper | pass |  |
| precedent-set-b | pass |  |
| m15-copy | pass |  |
| derived-maps | pass |  |

관찰하지 않은 사례:

- P-late-response: late responses of another run / result are covered by the pure guard tests (frontend/tests/kinase-precedents.test.cjs precedentResponseCurrent); this flow does not hold responses.
- P-record-hash-412: a record whose content_hash no longer matches (412 at call time) needs a set changed between the pin and the call; covered by backend/tests/test_kinase_precedents_tool.py.

## 단계 `real` — pass

| 사례 | 내용 | 결과 | 단계 |
|---|---|---|---|
| X-maps | real M15 maps by clicks: 1MQ4 A (O14965), 1M17 A (P00533), 1FIN chains A and C only (P24941); B and D (cyclin A) not requested | pass | real-maps:pass |
| X-snapshot-real | the imported real set: hash, kbase HEAD 77354f94b844, dist commit 43a935e4637d and its date, dirty false, kb_version, rows 891 / 885 / 555, bibliography 252 rows, UP5 396, 35 unresolved names | pass | real-main:pass |
| X-request-defaults | the newest numbering map pre-selected, nothing posted, chains ticked, toggle off | pass | real-main:pass |
| X-1mq4-none | 1MQ4 → O14965 none_in_included_files: included moves 0, moves_flagged — (not included), UP2 with 0 | pass | real-main:pass |
| X-1m17-found | 1M17 → P00533 precedents_found: 76 moves, excluded 66 (UP2), variants not_reported 53 · L858R 15 · T790M 4 · WT 3 · L834R 1 | pass | real-main:pass |
| X-1m17-flagged | 1M17 with moves_flagged: 76 + 66 = 142; 1FIN with moves_flagged: 32 + 24 = 56 | pass | real-main:pass |
| X-1fin-one-target | 1FIN chains A and C → one target P24941, two chain rows, 32 moves, excluded 24 | pass | real-main:pass |
| X-records-real | 1M17 records: variant L858R filter (15) and 다음 쪽 equal the server pages | pass | real-main:pass |
| X-detail-real | two 1M17 records expanded: bibliography, UP1, UP4, ten kbase checks, integrity, measured-change table rows equal the stored record (observed in memory; only IDs recorded) | pass | real-main:pass |
| X-too-large-real | LABELLED SYNTHETIC size-test map (1FIN map, chains given P00533 and Q06187) with moves_flagged → 429 result_too_large with the advice, nothing stored | pass | real-main:pass |
| X-report-real | report of the 1M17 result: downloads equal to the backend bytes (hash only), fixed sentences, no quote or observation text, the library entry | pass | real-main:pass |
| X-results-list | the result list equals the stored list; a file not included shows — with the reason | pass | real-main:pass |
| X-tabs | 구조 분석 hidden and inert, run selection only there, other tabs unchanged | pass | real-main:pass |
| X-no-zero | not included / not computed values are — with the reason, never 0 | pass | real-main:pass |
| X-wording | no rank / recommendation / verified / effect wording outside fixed sentences and stored strings | pass | real-main:pass |
| S-real-no-egress | every flow row: 0 non-loopback browser requests (no host contacted) and zero provider calls | pass |  |
| S-real-references | the imported real set served, the read-only M15 copy and the derived size-test map stored from the real 1FIN map | pass |  |
| S-real-import | the user import command run twice on the real kbase dist/ (sockets refused and counted: 0): exit 0, rows 891 / 885 / 555 and 252, verification 891 / 885 / 555, dirty false, two sets with byte-identical files | pass |  |

| 흐름 단계 | 결과 | 문제 |
|---|---|---|
| real-maps | pass |  |
| real-main | pass |  |
| precedent-imported | pass |  |
| m15-copy | pass |  |
| derived-maps | pass |  |

관찰하지 않은 사례:

- X-chain-states: the public structures give linked chains only (1FIN B / D are not requested: M15 refuses them, T1); no_mapped_residues and multiple_accessions are observed in the fixture stage.
- X-not-in-kbase: not_in_kbase_references needs a structure outside the allowed downloads (T1 (d)); observed in the fixture stage.
- X-snapshot-states: unset / invalid / stale snapshot states are observed on the synthetic set (fixture stage).

## 다시 실행하는 명령 (메인 체크아웃 루트, 8000·3000 포트 비움)

```bash
.venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m27-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m27-acceptance/<label> \
    --kbase <abs>/kbase_kinase --stages fixture,real --out docs/qa/m27-precedents-<YYYYMMDD>/acceptance
```
