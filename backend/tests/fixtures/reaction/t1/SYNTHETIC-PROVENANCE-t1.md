# M26 T1 fixture — 저장된 M20 v1 후보 집합

2026-10-08 M26 T1(착수 확인)에서, M26 제품 코드를 하나도 바꾸지 않은 상태(작업 브랜치 `dryforge/m26-reaction-knowledge`, 기준 커밋 `72f4d1e`, `backend/mw` 변경 없음)에서 만들었다. 만든 명령은 `docs/qa/m26-reaction-20261008/v1-baseline/make_v1_fixtures.py`이다(한 번만 쓰는 생성기. M20 v2가 켜진 뒤에는 같은 파일을 다시 만들 수 없다 — 그때 도구는 v2 집합을 만든다).

- 입력은 저장소 안 공개 구조 `../../public_1ubq.cif`(유비퀴틴, 공개 구조이며 여기 값의 실험 검증이 아님) 하나뿐이다. 수정하지 않은 M20 v1 도구 `generate_mutation_candidates`(`mw.mutation_candidates/v1`)가 낸 저장 객체 내용을 그대로 담았다.
- **실서버 자료는 없다.** M-CSA·UniProt·Rhea·RCSB 등 어떤 공개 서버 응답도 담지 않았고, 이 파일을 만드는 동안 네트워크 요청은 0건이다. 키·자격 증명도 없다.
- 위치(1UBQ 체인 A MET1·ILE44·LYS48, 또는 M1·Q2·I3·K6·L8·I44·G75·G76)와 허용 잔기는 시험용 선택이며 설계 제안이 아니다. 후보는 위치와 바꿀 잔기의 조합일 뿐이고 점수·순위·안정성·ΔΔG·활성을 뜻하지 않는다. `catalytic_residue_database`는 v1 그대로 `{"status": "not_available", "reason": "not_implemented"}`이다.

| 파일 | 내용 | SHA-256 |
|---|---|---|
| `m20-v1-candidate-set-golden_m24_mutation.json` | `backend/tests/fixtures/jev/golden_science_m24.py`의 일반 run(`golden_m24_mutation`) 템플릿이 M20 도구로 만들던 집합의 `{handle, content}`(정규 JSON + 줄바꿈). 파일 경로로 불러온 1UBQ, 기본 전처리, 사용자 위치 MET1·ILE44·LYS48, 허용 잔기 기본값(위치 3 × 19 = 후보 57). handle `obj://golden_m24_mutation/mutation_candidate_set/f7f7b292…a00d`는 골든 `golden_science_m24.json`에 적힌 것과 같다. | `d883c1e3269b086d6bf47285faf9d4d88b91c63c01a79fa2e7b29fc0f501c341` |
| `m20-v1-candidate-set-golden_m24_dry.json` | 같은 기록기의 dry-run run(`golden_m24_dry`) 집합. 내용은 run id를 담은 구조 handle만 다르다. handle `obj://golden_m24_dry/mutation_candidate_set/fd21366f…32d8`(골든과 같음). | `9bcfb8530e7581cc6c7a3b1738e1ce253a5c01dc4b00be124412e1cc79b30d08` |
| `m20-v1-candidate-set-run_m23_golden_keys-8pos.json` | `backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py`가 HTTP로 만들던 집합(업로드한 1UBQ, 명시 전처리, 8위치, 허용 `AFHWY`, 후보 40). `../../sequence_ga/m20-candidate-set-1ubq-8pos.json`과 바이트가 같다(생성기가 확인). 골든 기록기가 이 폴더의 사본을 쓰는 것은 `build_sequence_ga_fixtures.py`를 v2 뒤에 다시 써도 골든 입력이 바뀌지 않게 하기 위해서다. handle `obj://run_m23_golden_keys/mutation_candidate_set/47a93045…19b8`(`golden_call_keys.json`과 같음). | `06c5980a8c5a05bd15503d35a1249c2836d64cc5b63e139664e5eb0f43e503b7` |
| `v1-run-run_m23_golden_keys.events.jsonl` | `build_sequence_ga_fixtures.py` 경로(업로드 → `load_structure` → `prepare_structure` → M20 v1 도구 두 번: 8pos, tiny)로 만든 run의 이벤트 로그 전체(25줄, 232,554바이트). 시각·호출 ID는 그 생성 때의 로컬 값이며 절대 경로·키는 없다. v1 집합이 도구 출처(`tool_called`·`tool_succeeded`)와 함께 저장된 run을 M20 v2 뒤에도 events-only로 다시 열어 v1 보고서 바이트를 대조하는 데 쓴다(M20 보고서는 도구 출처가 없으면 `missing_successful_tool_provenance`로 거절한다). 두 집합은 `../../sequence_ga/m20-candidate-set-1ubq-{8pos,tiny}.json`과 handle·내용이 같다. | `1980fbc305a769eeee6d5915931b19edf51a92fb6dabe8d16829c186960e56c3` |

## 쓰는 곳

- `golden_science_m24.py`: 템플릿의 M20 호출을 같은 인자의 `Run.call` 그대로 두고, 그 run의 레지스트리에서 M20 구현만 이 fixture 내용을 `store.put`하는 함수로 바꾼다(M20 구현은 실행되지 않음). 맨 `store.put`만 쓰면 템플릿 이벤트가 5개에서 1개로 줄어 골든의 절대 이벤트 순번 네 개(`jev_choice` 보고서의 `provenance.dispatch_event_seq`·`created_event_seq`, `snapshot.event_seq`, `method_report_created.snapshot_event_seq`)가 4씩 줄기 때문이다(`docs/qa/m26-reaction-20261008/v1-baseline/checks/variant-bare-store-put.txt`).
- `prototype_golden_call_keys.py`: HTTP 업로드·전처리 뒤 run을 다시 열고 8pos 내용을 `store.put`으로 넣는다(이 골든에는 이벤트 순번이 없다).
- `docs/qa/m26-reaction-20261008/v1-baseline/record_v1_baseline.py`: v1 읽기 응답·보고서 바이트·`validated_set` 결과의 기준선.
