# M21 변이 구조 모델링 완료 기록

- 판정: **완료** (2026-10-04). main 병합: **하지 않음**(사용자 통합 승인 대기, push 없음).
- 브랜치: `dryforge/m21-mutation-model` (`phase/m21-mutation-model` = main `a6334a6`에서 분기). M20은 시작 전에 main에 병합되어 있었다(`5ed9835`, 기록 `a6334a6`).
- 고정 소스: `4a3dabe`(`4a3dabe51af0ef8b6328bf7f09fa7f719e4ef7e1`, 독립 코드 검토 수정 커밋). 증거 커밋 `c12b70d`. 고정 뒤 소스 변경은 없다. 고정 뒤 커밋은 증거·기록 문서뿐이다.
- 수락 증거: `docs/qa/m21-mutations-20261004/`(`preflight.txt` 착수 확인, `offscreen-acceptance/` T10 개발 실행(`1f56dc4`, 수락 시도 아님), `gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M21 수락, `m20-regression/`, `m19-regression/`, `m18-regression/`, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 51개 331,886,193 B, m14-regression 1개 1,191,725 B, m15-regression 1개 590,108 B, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 외부 요청 0건, OpenRouter 호출 0회(흐름 행과 재현 검사 두 run). 외부 요청은 착수 확인의 PDBFixer 내려받기(환경 준비)뿐이다.

## 결과물
- 작업 전용 도구 `openmm_mutation_model`, 프로토콜 `openmm_mutation_model_v1`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`·작업 승인 허용 목록·guardian·큐 dispatch, `SUPPORTED_TOOLS` 아님) → 불변 결과 `mutation_model@1`(`method_version` `mw.mutation_model/v1`)과 mmCIF 객체 `mutation_model_structure@1` 둘. 작업 하나 = 후보 하나 = 비싼 계산 1단위. `config/tools.yaml`(L3, `durable_job`), `tools/energetic.py`(등록·작업 전용 표시).
- 서버 모듈: `mutation_model_constants.py`(닫힌 집합·범위·기본값·한계 문장 L1–L7, 의존성 없음), `mutation_model_inputs.py`(입장 검사 1–7, M7 사전 검사 실패 변환), `mutation_model_math.py`(접촉·위상 해시·이황화·양성자 상태·비교·`validated_model`, gemmi·numpy·표준 라이브러리만), `mutation_model_bundle.py`(capability, 412, 사전 검사, 호출 키·의존 파일 해시, 스테이징, 오류 봉투, 게시, 검증 읽기), `mutation_model_reads.py`(읽기 4개 + 같은 조건 도킹 짝), `mutation_model_reports.py`(보고서). 작업 모듈 `jobs/openmm_mutation_worker.py`(PDBFixer는 여기서만 import). 큐·guardian·`api/app.py` 연결.
- M18 확장(단독만): `docking_constants.py`(입장 전용 `mutation_model_invalid`, 열두째 한계 문장, `RECEPTOR_SOURCE_KINDS`), `docking_inputs.py`(`receptor_source` 모양·SDF 전용·사이드카 만들기), `docking_bundle.py`(모델 검증 읽기·스테이징·게시 대조·`inputs.receptor.source`), `jobs/docking_worker.py`(출처 표시, 이 출처에서만 말단 카르복실 O/OXT 완화와 열두째 문장), `docking_reads.py`(목록 `receptor_handle` null 허용), `docking_reports.py`(출처 표기). M19 코드는 바꾸지 않았다.
- 설치: `backend/pyproject.toml`에 `pdbfixer==1.12.0`(sdist SHA-256 `82e54074…4143`, 프로젝트 `.venv`, 새 격리 환경 없음).
- API: `GET /runs/{id}/mutation_models`, `/{handle}`, `/{handle}/contacts`, `/{handle}/structure`, `/{handle}/docking_pairs`(handle은 경로), `/capabilities`의 `methods.mutation_model`, `GET /tools?levels=…L3…`의 새 작업 도구, 방법 보고서 `analysis_type: "mutation_model"`, 작업 `artifacts.mutation_model`.
- 화면: `frontend/src/components/MutationModelPanel.tsx`(새, M20 패널 다음 형제), 순수 로직 `src/lib/mutation-model.ts`(새), `MutationPanel.tsx`(후보 행 "변이 구조 모델링", `onModelCandidate`), `lib/mutations.ts`(`MODELING_NOTE` 문장), `app/page.tsx`(마운트·후보 전달), `lib/api.ts`·`contracts.ts`, `lib/docking.ts`(열두째 문장·새 이유, `dockingConditionArgs` 추출, 변이 모델 수용체 표시), `lib/report-library.ts`("변이 구조 모델 보고서"). M18 `DockingPanel.tsx`는 바꾸지 않았다.
- Fixture: `backend/tests/fixtures/mutation_model/`(1UBQ에서 만든 표시된 합성 파생 Cys 구조 둘, 합성 표시 페놀 SDF, 손 계산 `expected.json`, `SYNTHETIC-PROVENANCE.md`, `build_mutation_model_fixtures.py --check`), 도우미 `backend/tests/mutation_model_fixture.py`. 공개 구조는 기존 `public_1ubq.cif`.
- 테스트: 백엔드 `test_mutation_model_inputs.py`, `_worker.py`, `_jobs.py`, `_api.py`, `_reports.py`, `_docking.py`, `_pairs.py`. 프런트 `tests/mutation-model.test.cjs`. 스크립트 `test_m21_offscreen_acceptance.py`.
- QA 도구: `frontend/tests/offscreen/mutation-model-flow.cjs`(`test:offscreen:mutation-model`, 모드 `main`), `scripts/m21_offscreen_acceptance.py`(단계 `model-main`, 재현 검사, 예산 사례, `--regressions`).

## 사용자 결정 (2026-10-04)
근거는 결정 0029. 사용자는 명세 확정 때 모든 질문에서 추천안을 골랐다.
- PDBFixer 곁사슬 + M7과 같은 OpenMM 최소화(프로젝트 `.venv`, `pdbfixer==1.12.0` 고정). FoldX·ProteinMPNN·ESM 불허.
- 각 구조의 OpenMM 전위만 보이고 차이·구조 안 전후 변화량은 만들지 않는다. HIS·CYS는 구조마다 pH 7 자동 지정·기록, 다르면 목록과 L5. PDBFixer는 변이 잔기에만(M7 사전 검사 먼저). 새 이황화 허용·기록(L6). 작업 하나 = 후보 하나, 야생형 기준은 같은 작업·같은 절차. 비교는 변이 잔기 SASA·1–3결합 제외 중원자 접촉·각 구조 전위·같은 조건 도킹. 뷰어 표시 없음. M18 확장은 단독만, M19 제외. 보고서에 도킹 점수 없음.
- 실행 중 사용자가 승인한 명세 수정: **D1**(착수 확인) `receptor_source`가 `mutation_model`일 때만 말단 카르복실 이중결합 O/OXT 둘 다 허용(가져온 수용체 검사 불변), **R2**(코드 검토) 이 출처는 SDF 리간드만, 그리고 M18 호출 키 해시 변경으로 기존 M18·M19 결과의 자동 재사용이 끝나는 대가를 수용.
- 착수 확인 뒤 명세에 반영한 설계 선택: **B1** 같은 이름 곁사슬 원자는 PDBFixer가 남기는 대로(변형 A), **B2** 입력에 있던 원자는 입력 좌표를 이식(밖 허용 1e-9 Å, C 말단 OXT 포함). 조절 가능한 값(cutoff 4.0 [2.5, 6.0], 시간 120/240, 접촉 2,000행, 읽기 페이지)은 결정 0029에 적었다.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인, PDBFixer 고정, fixture | `b27f5f9` |
| T2 순수 상수·입장·접촉·검증기 | `5fe62af` |
| T3 작업 모듈(PDBFixer 이식, 독립 oracle) | `068cd51` |
| T4 작업 경로·결과 객체·capability | `cfdc72b` |
| T5 읽기 API와 `mutation_model` 보고서 | `9462247` |
| T6 M18 수용체 출처 `mutation_model` | `e60e347` |
| T7 같은 조건 도킹 짝 읽기(+ 엔진 미import 테스트 예외) | `5866ff7`, `28a9403` |
| T8 프런트 API·순수 로직 | `67dac53` |
| T9 단백질 공학 탭 변이 구조 모델링 화면 | `1f56dc4` |
| T10 오프스크린 흐름과 M21 수락 실행기 | `6194f41` |
| T11 독립 코드 검토 수정 | `4a3dabe`(= 고정 소스) |
| T12 게이트·수락·회귀 증거 | `c12b70d` |
| T13 독립 증거 검토 | 커밋 없음(approve) |
| T14 완료 기록·결정 0029·프로젝트 문서 | 이 기록과 같은 커밋 |

## 착수 확인 (`preflight.txt`, 기준 `a6334a6`)
- (a) PDBFixer 1.12.0 설치·고정, OpenMM 8.6.0 포스필드 지문 6개 그대로, 기존 M7 테스트 26개·SASA 11개 통과.
- (b) 1UBQ 변이 행렬 37경우(I44 → 19종, N·C 말단, Gly→X, X→Pro, Pro→X, HIS 관련) × 변형 A·B와 합성 파생 Cys 8경우 × 2 = 90회: 변이 잔기 밖 원자 추가·좌표 변경 0건, 변이 잔기 중원자 = 템플릿, 최소화 모두 완료, `mutation_modeling_failed` 0건. 남은 설계 선택 B1·B2.
- (c) 같은 입력·seed 두 번 바이트 동일, 작업 하나 약 23초(단독), 결과 JSON 약 0.6 MB, 접촉 최대 418행(6 Å).
- (d) **명세와 다름 → 멈춤(D1)**: M18 화학 추론이 OXT 말단을 C=OXT로 추론해 수용체 5개 모두 `receptor_prep_failed`. 원자 순서만 바꾼 탐침에서는 5개 모두 통과, qvina 두 번 바이트 동일. 사용자가 이 출처에서만 완화를 골랐다.
- (e) M7 사전 검사를 통과하는 로컬 공개 구조는 1UBQ뿐(리간드 없음). 같은 조건 도킹은 1UBQ + 합성 표시 페놀 SDF로 기계적으로 검증한다.
- (f) 접촉·1–3결합 제외·SASA 손 계산 oracle을 `expected.json`에 고정하고 별도 계산으로 교차 확인.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토(고정 전): **막는 지적 없음**, 권고 2건을 반영했다(`4a3dabe`): R1 작업 모듈이 import하는 프로젝트 모듈 다섯 개의 SHA-256을 호출 키와 시작 재확인에 넣음, R2 같은 조건 도킹의 리간드를 SDF만으로(후보 출처는 `mode_source_mismatch`, 화면도 막음, 사용자 승인). 같은 커밋에 참고 지적 N4(짝 동작 중 다른 모델 열기 막음)와 N1(`JobSubmit` 본문 모델의 `timeout_s`·`args` 거절을 `argument_invalid`로)도 반영했다. 참고 지적 N2(412가 순수 입장 422 뒤·M7 사전 검사 422 앞)와 N6(이 모델을 출처로 한 읽기가 매번 모델을 다시 검증하는 비용)은 동작을 바꾸지 않고 `docs/engineering-notes.md`에 기록했다.
- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 고정 뒤): **approve**.

## 게이트 (고정 `4a3dabe`, `gate.txt`, 2026-10-04 03:49:19–04:08:28 UTC)
시작 때 작업 트리 깨끗함, 다른 세션의 Stop 훅 pytest가 끝난 뒤(03:49:09Z) 시작(겹침 없음), 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 백엔드 pytest는 Stop 훅의 다섯 그룹을 제한 없이 따로 돌렸고(세 줄 동시 실행), 끝난 뒤 작업 트리 깨끗함, HEAD 그대로, 남은 프로세스 없음, 8000/3000 비어 있음.

| 명령 | 결과 |
|---|---|
| 백엔드 pytest 다섯 그룹(화학 24, M11 작업 API 25, M18 도킹 198, M19 일괄 209, 나머지 1,833 = 백엔드 1,523 + 실행기 310) | exit 0 ×5, 백엔드 합계 1979 passed(수집 1979), 0 skipped. 나머지 그룹 602초 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 16개 파일(M20 게이트 15개 + `test_m21_offscreen_acceptance.py`) | exit 0, 384 passed, 0 skipped(M21 실행기 40개) |
| `node --check` 흐름 10개(M20의 9개 + `mutation-model-flow`) | exit 0 ×10 |
| `npm --prefix frontend run test:events` | exit 0, 328 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `4a3dabe`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m21_offscreen_acceptance.py --root runs/m21-acceptance-20261004-attempt1 --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/attempt1 --out docs/qa/m21-mutations-20261004/acceptance --regressions --kbase <home>/Projects/kbase_kinase` (분리 실행, 04:09:09–04:57:11 UTC, 회귀 포함 약 48분). 실패한 시도·재시도 없음.
- 빌드 `AP8FpT2CpFyqfPjUEREAR`(gitHead `4a3dabe`, 소스 도장 일치, `dirtyFiles` 없음, 실행기의 `--build auto`가 typecheck 뒤 build). `verdict: pass`, `acceptance: true`, 판정 사례 23개 모두 통과(`model-main` 20 + `MM-reproducible` + `MM-budget` + `S-no-egress`). 환경(`mutation_model` 사용 가능: OpenMM 8.6.0, 엔진 빌드 8.6.0.dev-c6173db, PDBFixer 1.12.0, 시간 120/240, cutoff 4.0 [2.5, 6.0]; `mutation_candidates`, `ligand_docking` 사용 가능)·남은 프로세스 행 통과. 비-loopback 요청 0건, 제공자 호출 0회.
- 관찰 요약(공개 1UBQ 실제 바이트, M20 직접 선택 후보 I44W, 실제 OpenMM·PDBFixer·qvina): run 없음은 이유만 → 불러오기·전처리 → 후보 집합 하나(I → W) → 후보 행 동작은 요청 칸만 채움(seed 비움, 확인 없음, 4.0 Å·120초) → seed·확인·cutoff 7.0에서 제출 막힘(요청 없음) → 승인·시작·완료, 1단위, 모델은 저절로 열리지 않음 → 나란히 표 = API 상세 = 이벤트 로그 저장값(전위 before·after, 변이 위치 SASA, 접촉·상대 잔기 수, PDBFixer 원자, 이황화, 원자·수소 수), 차이 필드 없음 → 한계 문장 = 저장 = 명세 순서(L5·L6은 저장 조건대로 없음) → 차이·변화·순위·추천·안정성 낱말·화살표 없음, 두 구조 칸 같은 스타일 → 접촉 표(cutoff 6.0 Å로 여러 페이지) = API = 저장 행 → mmCIF 둘 = 저장 `structure_sha256` = 백엔드 바이트 → 보고서 저장·목록·Markdown/JSON 내려받기 = 백엔드 바이트, 고정 문장, 도킹 값 없음 → 같은 요청 다시 = 같은 작업·handle·새 단위 없음 → 보류한 변이형 접촉 페이지 버림 → 리간드 탭 SDF 가져오기 뒤 돌아오면 GET만 다시 읽고 아무것도 열지 않음 → 같은 조건 도킹: 2단위 안내·체크 전 막힘, 한 번 눌러 `receptor_source.side`만 다른 `qvina_dock_v1` 둘(가져온 수용체 키 없음), 실제 qvina 둘 완료, 2단위 → 짝 행 점수 = `docking_pairs` = 각 M18 결과 첫 모드 점수, 서버 점수 이름, 열 넷, 차이 없음 → 둘째 조건(seed 7)에서 대기 중 변이형 취소: 쪽마다 작업 상태와 "없음(서버 이유)", 시작한 쪽 1단위, 첫 짝 점수 유지 → 실행 중 모델링 작업(seed 7) 취소: 모델 없음, 작업·guardian 프로세스 없음, 실패 상태와 취소 문장, 예약 1단위 유지 → run A 모델 목록 응답을 보류하고 run B로 바꾼 뒤 버림.
- 예산(`MM-budget`, 백엔드 예산에서 셈): run A 5 / 한도 8 = 모델 1 + 같은 요청 0 + 도킹 짝 2 + 한쪽 취소 짝 1(대기 중 취소한 쪽은 0) + 취소한 모델링 1. 재현 run 둘 각 1(반복 요청 0). 세 수락 run 합계 7단위.
- 재현 검사(`MM-reproducible`): 흐름의 불러오기·전처리·후보·모델 요청(seed 20261004, cutoff 6.0 Å, 시간 240초)을 **같은 서버 프로세스**의 새 run 두 개에서 API로 보냈다(콜드 재시작이 아님). run마다 같은 작업·같은 모델 handle이 두 번 나왔고 반복에 새 단위가 없었으며, obj:// handle만 자리표시로 바꾼 저장 모델 SHA-256 `b2ed1464…5857c`와 구조 SHA-256(야생형 기준 `e877b974…df65f`, 변이형 `334ad777…923cb`)이 흐름과 같았다. 다른 버전 간 비트 동일은 주장하지 않는다.

### 관찰하지 못한 사례 (위조하지 않음)
- `MM-unavailable`(엔진·PDBFixer·신원 어댑터 없음): capability가 `.deps`가 아니라 프로젝트 `.venv`와 신원 어댑터에 달려 있어 인터프리터를 위조하지 않고는 만들 수 없다. `backend/tests/test_mutation_model_jobs.py::test_unavailable_engine_pdbfixer_or_identity_is_412_without_reservation`, `frontend/tests/mutation-model.test.cjs`(다섯 상태, capability 없을 때 제출 막힘)가 덮는다.
- `MM-pair-approval`(도킹 짝 자체의 첫 계산 승인 버튼): 승인은 run 단위이고 짝보다 먼저 필요한 모델링 작업이 이미 받았다. `mutation-model.test.cjs`(`pairApprovalRequired`)와 M18 수락(`D-free-job`)이 덮는다.
- `MM-failed-job`(닫힌 이유로 실패한 작업): 유효한 1UBQ 입력은 모두 모델링된다(착수 확인). `test_mutation_model_worker.py`(`test_energy_contact_and_output_limits_are_closed_failures`, `test_pdbfixer_errors_are_mutation_modeling_failed`)와 `test_mutation_model_jobs.py`(`test_tampered_output_typed_errors_size_limit_and_late_cancel_publish_nothing`)가 덮는다.
- `MM-zero-contacts`(접촉 0개 화면): I44W는 두 구조 모두 접촉이 있다. `mutation-model.test.cjs`(접촉 페이지·0개 문장)가 덮는다.
- `MM-conditional-limitations`(L5·L6): 1UBQ I44W에는 양성자 상태 차이도 새 이황화도 없다(흐름은 저장 조건과 화면이 같은지만 확인). 합성 파생 Cys 구조의 작업 모듈 테스트 `test_removed_disulfide_records_the_partner_difference_and_l5`, `test_new_disulfide_is_recorded_with_l5_and_l6`이 덮는다.

### 단위 테스트로만 확인한 것
- null 표시("—"와 이유)는 1UBQ 흐름에서 null 값이 나오지 않아 `mutation-model.test.cjs`의 표시 값 테스트로만 확인했다.
- 코드 검토 수정 N1(`JobSubmit` 본문 모델 거절의 `argument_invalid`)·R1(의존 파일 해시)은 백엔드 테스트(`test_every_admission_reason_reaches_the_api_as_422_without_a_job`, `test_changed_dependency_changes_the_key_and_refuses_the_pinned_start`)로만 확인했다. R2(SDF 전용)와 N4(짝 진행 중 모델 전환 막음)는 프런트 단위 테스트와 백엔드 입장 테스트로 확인했고 흐름은 SDF 리간드만 쓴다.

### T10 개발 실행 기록 (수락 시도 아님)
- T10은 `1f56dc4` 위에서 하네스·실행기 파일이 아직 커밋되지 않은 채(`dirtyFiles`에 표시) 네 번 돌렸다. `t10a`·`t10b`는 실패했다: 하네스가 대장 행 없이 종료 1(`page.waitForResponse: Target page, context or browser has been closed`, 실패 패널 `t10a` V01·J01, `t10b` O03·P03·P13·Q02·V09·X01)이었고 원인은 하네스 단언 문제였다. 하네스만 고쳤다(흐름 SHA-256 `70e04549…` → `dec7232d…` → `3e3c4b7f…`, 제품 소스는 그대로). `t10c`는 통과(23/23), `t10d`는 같은 하네스로 다시 돌려 `docs/qa/m21-mutations-20261004/offscreen-acceptance/`로 내보냈다(통과). 실패 실행의 폴더(`frontend/tests/offscreen/artifacts/m21-acceptance/t10a`·`t10b`, `runs/m21-acceptance-20261004-t10a`·`t10b`)는 지우지 않았다. 그 뒤 T11 수정이 소스를 바꿨으므로 수락 판정은 고정 `4a3dabe`의 T12 시도 1회만으로 한다.

### 회귀 (고정 `4a3dabe`, 같은 빌드 `AP8FpT2CpFyqfPjUEREAR`, M21 실행기 `--regressions`가 차례로)
- 각자 새 `--root runs/m21-acceptance-20261004-attempt1-m2X|m1X-regression`·`--artifacts frontend/tests/offscreen/artifacts/m21-acceptance/attempt1/regressions/m2X|m1X`, `--code-root <repo>`(M20·M16·M15는 `--kbase`).
- M20 `m20-regression/` → `acceptance: true`, 24/24(`M-map-conflict`·`M-too-many-positions`·`M-nonstandard-disulfide` 관찰하지 않음, M20과 같음). M19 → 26/26(`B-dry-run-shortfall`·`B-null-result`·`B-time-limits` 관찰하지 않음). M18 → 24/24(`D-zero-modes` 관찰하지 않음). M17 → 21/21. M16 → 19/19. M15 → 14/14. M14 → 15/15. M8–M13 `m13-regression/`(`--phases workflows,unavailable,regressions,m11,m12,ledger`) → 28/28, 17행 통과, M11·M12 하위 실행기 통과.
- 모두 외부 요청 0건, 남은 프로세스 없음. 제공자 호출 필드가 있는 흐름 행은 모두 0회(M13 하위 실행기·회귀 행 7개는 이 필드를 기록하지 않음, M18–M20과 같음).
- M20 회귀가 가져온 참조 세트 해시(`8c608e2b…`)는 M20 기록(`99939292…`)과 다르지만 매니페스트의 파일 SHA-256 다섯 개는 같다(`imported_at` 차이, `docs/engineering-notes.md`).

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님). 기존 수락 실행기와 흐름 스크립트는 하나도 고치지 않았다.
- `backend/tests/test_api.py`: `GET /tools?levels=L1,…,L5` 이름 집합에 `openmm_mutation_model`(L3 작업 전용 도구, `SUPPORTED_TOOLS` 아님).
- `backend/tests/test_ligand_api.py` 2줄: `/capabilities` 방법 집합에 `mutation_model`.
- `backend/tests/test_docking_inputs.py`: 입장 전용 이유에 `mutation_model_invalid`(작업 이유 집합에는 없음을 함께 단언), 이유 총수 32 → 33, 명세 한계 문장 목록에 열두째 문장(11 → 12). 사용자가 승인한 M18 닫힌 집합 변경이다.
- `frontend/tests/docking.test.cjs`: 백엔드 이유 집합에 `mutation_model_invalid`, 한계 문장 수 11 → 12, 새 테스트 둘(`dockingConditionArgs`가 `dockingArgs`와 같은 값·오류, 변이 모델 수용체 표시).
- `backend/tests/test_mutation_model_reports.py`(T5의 엔진 미import 테스트): T7에서 짝 읽기가 작업 상태를 읽어야 해 `mutation_model_reads.py`만 `jobs`(`JobQueue`) import를 허용했다(`28a9403`, 엔진은 여전히 금지).
- M18 회귀는 가져온 수용체 출처라 11문장 그대로 통과했다. 모든 회귀가 새 루트라 호출 키 해시 변경(옛 결과 재사용 끝)의 영향이 없다.

## 알려진 한계
- 리간드가 있고 M7 사전 검사를 통과하는 공개 구조가 로컬에 없어, 같은 조건 도킹은 1UBQ + 합성 표시 페놀 SDF로 기계적으로만 검증했다(실제 qvina, 생물학적 자세가 아님). M7 규칙은 완화하지 않았다.
- 같은 이름 곁사슬 원자를 남기는 방식(B1)이라 최소화 전 전위가 매우 클 수 있고, 최대 50회 최소화는 수렴을 뜻하지 않는다. 회전이성질체 탐색이 없다.
- 시간은 1UBQ(중원자 602)에서만 쟀다. 중원자 약 4,890개를 넘는 모델은 모델링은 되어도 M18 원자 수 한도(10,000)로 같은 조건 도킹이 거절된다.
- M18 작업 모듈·상수가 바뀌어 M21 전에 만든 M18 결과와 M19 행 결과는 같은 입력이어도 자동 재사용되지 않는다(수용한 대가, 저장 결과·읽기는 그대로).
- 이 모델을 출처로 한 M18 결과와 짝 읽기는 모델을 매번 다시 검증한다(큰 모델·많은 짝에서 느려질 수 있음).
- Stop 훅 나머지 그룹이 480초 제한을 넘고, M20·M21 실행기 단위 테스트가 훅 목록에 없다(`docs/tracking/findings.md`).

## 대체한 과거 검증 범위
- M21은 공유 소스를 바꿨다: 백엔드 `api/app.py`(capability, 도구 목록, 작업 제출의 `timeout_s` 기본값 처리·M21 거절 코드, 작업 승인 허용 목록, 작업 artifacts, 보고서 분기·목록, 읽기 라우트), `jobs/queue.py`, `jobs/guardian.py`, `tools/energetic.py`, `config/tools.yaml`, M18 `docking_*` 모듈과 `jobs/docking_worker.py`. 프런트 `app/page.tsx`, `MutationPanel.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/docking.ts`, `lib/mutations.ts`, `lib/report-library.ts`, `package.json`.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(1979개, skip 0)와 M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `4a3dabe`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합은 사용자 승인을 기다린다. push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): Stop 훅 나머지 그룹의 시간 초과와 M21 실행기 단위 테스트 누락, 관찰하지 못한 사례, 리간드가 있는 M7 통과 공개 구조 없음, 큰 구조의 시간·크기 미측정, 출처 모델 재검증 비용, 해시하지 않는 의존 파일.
