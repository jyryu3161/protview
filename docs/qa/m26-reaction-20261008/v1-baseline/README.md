# M26 T1 v1 기준선 (M20 v2를 켜기 전)

2026-10-08, 작업 브랜치 `dryforge/m26-reaction-knowledge`, 기준 커밋 `72f4d1e`(M26 제품 코드 변경 없음, `git diff 72f4d1e -- backend/mw config frontend scripts`가 빈 상태)에서 기록했다. 네트워크 요청은 0건이고 `.env`는 읽지 않았다. T6(M20 v2)은 이 기준선으로 "v1 저장 집합·읽기 응답(기존 키·값)·보고서 바이트·골든 바이트가 그대로"를 보인다.

## 1. 골든 파일 SHA-256 (바꾸기 전 = 바꾼 뒤, `git diff`가 빈 상태)

| 파일 | SHA-256 |
|---|---|
| `backend/tests/fixtures/jev/golden_science_m24.json` | `78d4cf12078c443b7525d16c6af3df7afcc3be135a49de431bf0f7616fee482c` |
| `backend/tests/fixtures/jev/golden_egress_events.json` | `a662f8ecbb311d5e6efdba68f2e16036061e5a9c8b54dc0738297ffdd53e042f` |
| `backend/tests/fixtures/sequence_ga/golden_call_keys.json` | `879d0ccf7db4273d9da6d8fc772c0404adeaad0dd56a9ce5e41c70a9ed277719` |
| `backend/tests/fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json` | `06c5980a8c5a05bd15503d35a1249c2836d64cc5b63e139664e5eb0f43e503b7` |
| `backend/tests/fixtures/sequence_ga/m20-candidate-set-1ubq-tiny.json` | `e591b1b947a45983e681b4297b0b680964385497f7b296227e434ceee1c7aa78` |
| `backend/mw/mutation_candidates.py`(호출 키 해시 파일, 기준값) | `d0f2b7a80f4923b7bf3ea7b7e1c98562b016942b3e01bb248a4d7e0cf188968f` |
| `backend/mw/mutation_constants.py`(호출 키에 들지 않음, 기준값) | `151720de942b2a8a38ba5c4e76e3b7be5ec1754cb47139b7e18b7a6307a7a1df` |

## 2. 골든 확인 명령과 종료 코드 (`checks/`에 출력)

| 명령 | 기록기 바꾸기 전 | 바꾼 뒤 |
|---|---|---|
| `.venv/bin/python backend/tests/fixtures/jev/golden_science_m24.py --check --work <scratch>` | exit 0 (`before-golden-science-check.txt`) | exit 0 (`after-golden-science-check.txt`) |
| `.venv/bin/python backend/tests/fixtures/jev/prototype_golden_egress.py --check` | exit 0 | exit 0 |
| `.venv/bin/python backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py <scratch>/runs <scratch>/golden_call_keys.json` 다음 `cmp <scratch>/golden_call_keys.json backend/tests/fixtures/sequence_ga/golden_call_keys.json` (이 골든에는 `--check`가 없고 재기록하지 않는다) | exit 0, cmp 0 (바이트 동일) | exit 0, cmp 0 |
| `.venv/bin/python -m pytest -q "backend/tests/test_sequence_ga_jobs.py::test_golden_m18_m19_m21_call_keys_results_and_hashed_files_are_unchanged" backend/tests/test_jev_science_gate.py -k golden` | — | 2 passed, exit 0 (`after-targeted-tests.txt`) |
| M20 구현을 실행하면 실패하게 바꾼 상태(`mutation_candidates.build_candidate_set`이 예외)의 `golden_science_m24.py --check` | — | exit 0, 구현 호출 0회 (`after-golden-science-no-m20-builder.txt`) |
| 비교용 변형: 템플릿의 M20 호출을 맨 `store.put`으로만 바꾼 기록 | — | 다름 4곳(`variant-bare-store-put.txt`), `Run.call` 안 `store.put`은 동일(`variant-runcall-store-put.txt`) |

## 3. 저장된 v1 후보 집합 기준선 (`baseline/`)

다시 만드는 명령(T6 이후에도 그대로 돈다. M20 도구를 부르지 않고 커밋된 fixture만 쓴다):

    .venv/bin/python docs/qa/m26-reaction-20261008/v1-baseline/record_v1_baseline.py --check --work <scratch>

`--write`는 두 번 기록해 같을 때만 쓴다(이 폴더의 `baseline/`은 그렇게 썼다). `--check`는 다른 파일과 다른 JSON 경로(`… (added)` 포함)를 모두 출력하고 하나라도 다르면 exit 1이다. T6 뒤 기대 차이는 명세 8.5의 목록·상세 행 `catalytic_status` 키 추가뿐이다(기존 키·값·보고서 바이트는 같아야 한다).

대상 fixture(저장소의 저장된 v1 M20 집합 전부):

- `backend/tests/fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json`, `…-tiny.json`(M23 T1, 수정하지 않은 v1 도구 출력)
- `backend/tests/fixtures/reaction/t1/m20-v1-candidate-set-golden_m24_mutation.json`, `…golden_m24_dry.json`, `…run_m23_golden_keys-8pos.json`(이번 T1, 출처 `SYNTHETIC-PROVENANCE-t1.md`)
- 도구 출처를 가진 v1 run 로그 `backend/tests/fixtures/reaction/t1/v1-run-run_m23_golden_keys.events.jsonl`

| 파일 | 내용 |
|---|---|
| `frozen-run_m23_golden_keys.json` | v1 run 로그를 events-only로 연 run: M20 목록 읽기, 집합 둘(8pos·tiny)의 상세·위치·후보 읽기, `validated_set` 결과, `POST /method_reports`(201)와 `GET /reports`. 보고서는 집합마다 로그의 새 사본에서 만든다(앞 보고서의 생성 시각이 다음 보고서 snapshot에 들어가지 않게). |
| `frozen-8pos-report.manifest.json`, `frozen-8pos-report.md`, `frozen-tiny-report.manifest.json`, `frozen-tiny-report.md` | 저장된 보고서 manifest(정규 JSON)와 Markdown 바이트 그대로. |
| `stored-<label>.json` | 각 fixture를 handle의 run id로 만든 새 run에 `store.put`: handle 일치(전부 참), `method_version`(전부 v1), `catalytic_residue_database`(전부 `not_available`/`not_implemented`), `validated_set`(전부 통과, 돌려준 값 = 입력), 목록·상세·위치·후보 읽기(전부 200), 보고서(전부 422 `report_evidence_invalid`/`missing_successful_tool_provenance` — 도구 출처 없는 집합은 v1에서도 보고서가 없다). |
| `SHA256SUMS` | 위 파일들의 SHA-256. |

## 4. 생성기

`make_v1_fixtures.py`는 `backend/tests/fixtures/reaction/t1/`의 fixture를 수정하지 않은 v1 도구로 한 번 만든 명령이다(M20 v2 뒤에는 같은 파일을 만들지 못한다. 확인용이 아니라 만든 방법의 기록).
