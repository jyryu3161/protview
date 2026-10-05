# M23 서열 GA 설계 완료 기록

- 판정: **완료** (2026-10-05). main 병합: 사용자 승인 대기(`--no-ff`, push 없음).
- 브랜치: `dryforge/m23-sequence-ga` (`phase/m23-sequence-ga` = main `ec75fd0`에서 분기). M22는 시작 전에 main에 병합되어 있었다(`4161dc6`, 기록 `ec75fd0`).
- 고정 소스: `7871e83`(`7871e83ffafbee001eb0f849595b0a59c5615fef`, 독립 코드 검토 수정 커밋). 증거 커밋 `c4d1d8d`. 고정 뒤 소스 변경은 없다. 고정 뒤 커밋은 증거·기록 문서뿐이다.
- 수락 증거: `docs/qa/m23-sequence-ga-20261005/`(`preflight.txt` 착수 확인, `gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M23 수락, `m22-regression/`, `m21-regression/`, `m20-regression/`, `m19-regression/`, `m18-regression/`, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 51개 332,086,790 B, m14-regression 1개 1,191,726 B, m15-regression 1개 590,108 B, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`). 커밋한 폴더는 약 10 MB다(추적 파일 합 9.5 MB).
- 외부 요청 0건, OpenRouter 호출 0회(흐름 행 셋과 재현 검사 두 run).

## 결과물
- 작업 전용 도구 `sequence_ga_design`, 프로토콜 `sequence_ga_dock_v1`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`·작업 승인 허용 목록·guardian(도킹 인터프리터, 감시 대상, 종료 기록 한도 64 KiB)·큐 dispatch, `SUPPORTED_TOOLS` 아님) → 개체마다 변이 구조 모델 `mutation_set_model@1` + mmCIF `mutation_set_model_structure@1` + 단독 M18 `docking_result@1`(같은 handle) + 요약 `sequence_ga_result@1`. 작업 하나 = GA 한 번(야생형 기준 행 + 모든 세대), 시작 때 `reserved_units` 예약(환불 없음), 시도 1회, 작업 한도 15000초. `config/tools.yaml`(L3, `durable_job`), `tools/energetic.py`, `core/events.py`(이벤트 두 종류).
- 서버 모듈: `sequence_ga_constants.py`(닫힌 집합·파라미터 범위·상한·예산 상수·고정 문장 S1–S6·SL5, 의존성 없음, 작업 모듈도 파일 경로로 읽음), `sequence_ga_inputs.py`(입장 1–9, RDKit 없는 리간드·상자 부분 점검, `ga` 정규화·교차 규칙, 조합 공간 크기, 개체 키, 예약 단위·필요량·부족분·증액량, `conditions_sha256`·호출 키, 재사용 기록), `sequence_model_bundle.py`(모델 객체 구성·`validated_model`·경량 `validated_model_alone`), `sequence_ga_bundle.py`(요약 만들기·검증, 종료 구조·이어받음·교차·편집 관계·단계 전용 실패 이유 검증), `sequence_ga_jobs.py`(capability, 입장, 재사용 계획, 스테이징, `finish` 게시, GA 증액, 진행, 이벤트 스냅숏 검증 읽기), `sequence_ga_reads.py`(시작 전 확인·목록·상세·개체·구조), `sequence_ga_reports.py`(보고서 `sequence_ga`). 작업 모듈 `jobs/sequence_ga_worker.py`(도킹 환경, GA 절차·평가 루프·개체·세대 파일·신호·시간·출력 총량)와 모델링 프로그램 `jobs/sequence_model_worker.py`(프로젝트 `.venv`, M21 `mutant_projection` 연속 적용 + 단계 사이 반올림 + M21 `_prepare`·`_minimize`). 큐(`jobs/queue.py`: 15000초 상한, `SUMMARY_PROTOCOLS`, 시작 계획·스테이징)·guardian·`api/app.py` 연결.
- M18·M19 덧붙임(명세 8절이 허용한 서버 쪽 두 곳): `docking_bundle.producer()`에 GA 개체 증거(`_sequence_individual_producer`), `docking_bundle._mutation_receptor`가 저장 스키마로 `mutation_set_model@1`을 구분(`_set_model`), `docking_batch_inputs.published_m18_results`에 GA 결과 handle(`setdefault`). `docking_worker.py`·`docking_constants.py`·`openmm_mutation_worker.py`·`mutation_model_constants.py`·`mutation_model_math.py`·`mutation_candidates.py`·`ligand_ga_*`는 바꾸지 않았다(골든 호출 키 테스트가 고정).
- API: `POST /runs/{id}/sequence_ga/preflight`, `GET /runs/{id}/sequence_ga/results`, `/results/{handle}`, `/results/{handle}/individual?key=`, `/results/{handle}/structure?key=`(handle은 경로), `POST /runs/{id}/sequence_ga/limit_approval`(사람 증액), `/capabilities`의 `methods.sequence_ga_design`(`GET /tools`에는 나오지 않음), 작업 `artifacts.sequence_ga_result`와 진행 필드 `sequence_ga`, 방법 보고서 `analysis_type: "sequence_ga"`.
- 화면: `frontend/src/components/SequenceGaPanel.tsx`(새, 단백질 공학 탭 M21 영역 다음), 순수 로직 `src/lib/sequence-ga.ts`(새), `app/page.tsx`(마운트), `components/MutationModelPanel.tsx`(M21 `PairInputs` 내보내기, 기본 입력에서는 M21 마크업과 같음), `lib/api.ts`·`contracts.ts`, `lib/report-library.ts`("서열 GA 보고서"), `design/components.css`(+ `npm run tokens`). M18·M21 입력 로직은 가져다 쓰고 바꾸지 않았다.
- Fixture: `backend/tests/fixtures/sequence_ga/`(표시된 합성 후보 집합 둘과 만드는 스크립트 — 실제 M20 도구로 만든 1UBQ 후보 집합, 표준 라이브러리만 쓰는 독립 oracle `independent_sequence_ga_oracle.py --check`, 기대 경로·산식 `expected.json`, 골든 호출 키 `golden_call_keys.json`, 일회용 프로토타입 `prototype_*.py`, `SYNTHETIC-PROVENANCE.md`), 도우미 `backend/tests/sequence_ga_fixture.py`·`sequence_ga_world.py`.
- 테스트: 백엔드 `test_sequence_ga_inputs.py`(150), `_bundle.py`·`test_sequence_model_bundle.py`(106), `test_sequence_model_worker.py`(55), `test_sequence_ga_worker.py`(91), `_jobs.py`(14), `_budget.py`(15), `_api.py`(24), `_reports.py`(20). 프런트 `tests/sequence-ga.test.cjs`(34). 스크립트 `test_m23_offscreen_acceptance.py`(51).
- QA 도구: `frontend/tests/offscreen/sequence-ga-flow.cjs`(모드 `main`·`repro`·`unavailable`), `scripts/m23_offscreen_acceptance.py`(단계 `seqga-main`·`seqga-repro`·`seqga-unavailable`, 화면 재현 검사, oracle 경로 대조, `--regressions`).

## 사용자 결정 (2026-10-05)
근거는 결정 0031. 사용자는 명세 확정 때 모든 질문에서 추천안을 골랐다.
- 개체 = 게시된 M20 후보 집합의 서로 다른 위치 변이 1~N개 조합(상한 1–4, 기본 3). 적합도 = 개체 변이 구조에 사용자 SDF 리간드를 자유 도킹한 qvina 점수 하나(다목적·OpenMM 전위 제외), 동점은 변이 수가 적은 쪽. 야생형 기준 행은 항상 평가·값만 표시.
- 계산 구조 = GA 작업이 도킹 환경에서 돌며 모델링을 프로젝트 환경 자식 프로세스로. 기존 M21·M18 바이트 불변 우선. 연산자 = 이어받음 + 교차 + 변이 편집 + 무작위. 첫 세대·무작위 자리 = 변이 수부터 균등.
- 예산 = 새 평가 2단위, 시작 전 예약·환불 없음·재사용 무과금, 규모 개체 4–16(기본 8)·세대 1–8(기본 5)·새 평가 ≤ 64(기본 32)·시간 기본 7200초·최대 14400초. 개체 상세는 모델 값만. seed 둘. 여러 곳 변이는 구조 순서대로 한 곳씩 M21 함수를 연속 적용(단계 사이 소수 4자리 반올림). 실패 제동 = 기준 행 실패 시 개체 평가 전 중단, 연속 5건 실패 시 중단. 입력 점검 = 서버 부분 점검 + 나머지는 기준 행.
- 실행 중 조율 세션이 정한 세부와 결과(`docs/business-rules.md`의 "세부 규칙"(재시도 횟수·본 키·슬롯 순서·종료 이유 우선순위·멈춤 검사 순서 등), 기준 행이 기록되기 전 중단은 요약 없음, 이벤트 로그 스냅숏 읽기, 단계 전용 실패 이유 검증 등)는 결정 0031.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인과 fixture | `5bab871` |
| T2 서버 순수 모듈(상수·입장·모델·요약 검증) | `67a30c1` |
| T3 모델링 자식 프로그램(실제 OpenMM·PDBFixer 테스트, M21 해시 불변) | `6bf7baf` |
| T4 격리 GA 작업 모듈(실제 엔진 테스트, oracle 16벡터 일치) | `51c7f04`, `27f68b2`, `ae69f16` |
| T5 작업 경로(큐·guardian·스테이징·게시·GA 증액·M18 수용체 출처 서버 확장) | `d4fd7c9`, `5506b8d`, `9bcd20b`, `c7f28e5` |
| T6 읽기 API와 `sequence_ga` 보고서 | `c4d019c`, `5795931`, `e8215ca` |
| T7 프런트 API·순수 로직 | `4f28298` |
| T8 단백질 공학 탭 서열 GA 설계 영역 | `62f4533` |
| T9 오프스크린 흐름과 M23 수락 실행기(흐름이 찾은 "작업 시작" 단추 수정 포함) | `d43d6b5`, `7300816` |
| T10 독립 코드 검토 수정 | `ea1c325`, `7871e83`(= 고정 소스) |
| T11 게이트·수락·회귀 증거 | `c4d1d8d` |
| T12 독립 증거 검토 | 커밋 없음 |
| T13 완료 기록·결정 0031·프로젝트 문서 | 이 기록과 같은 커밋 |

## 착수 확인 (`docs/qa/m23-sequence-ga-20261005/preflight.txt`, 기준 `ec75fd0`)
- (a) 1UBQ에서 여러 곳 변이 11조합(k = 1–4, 인접 위치·사슬 양 끝 포함)이 단계 사이 반올림 규칙으로 변이 잔기 밖 원자 추가 0·좌표 변경 0, `energy_invalid` 없음, 같은 입력 바이트 동일, 개체(조합) 하나의 모델링이 약 9.4–10.4초였다. 반올림이 없으면 k ≥ 2의 8조합 모두 둘째 단계에서 `coordinates_changed`(최대 이동 4.29e-05–4.98e-05 Å)였다. 반대 순서는 다른 모델을 만든다(최대 6.2e-02 Å, S6의 근거). 야생형 경로와 k=1 I44W는 M21 저장 구조 해시와 같다.
- (b) 도킹 환경 프로세스가 `[프로젝트 .venv python, "-I", 프로그램]`을 guardian 환경으로 띄울 수 있고(경로를 `resolve()`하면 안 됨) 취소·시간 초과에서 빈 그룹까지 정리되며 RSS 감시가 자식을 합산한다.
- (c) 저장 전에 계산한 mmCIF handle = 서버가 저장한 handle. 그 수용체로 `dock_row`를 돌린 결과가 서버가 같은 모델을 게시한 뒤 제출한 단독 M18 작업 결과와 바이트 동일. 개체 수용체 준비 0.12–0.14초, `dock_row` 0.8–1.6초.
- (d) 서버 쪽만의 M18 확장으로 기존 호출 키 5개·읽기 4개가 그대로(골든 `golden_call_keys.json`). M18 수용체 한도는 1UBQ 비율로 중원자 약 4,890개이고 1UBQ 모델은 그 12.3%.
- (e) 요약 최악 171,468 B(1 MiB의 16%), 개체 하나 저장 453 KB·이벤트 605 KB, 65개 ≈ 104 MB(출력 256 MiB 안), `N` 최대 1.37e14 < 2^53. 읽기 시간이 설계 조건이 됐다: 개체마다 이벤트 로그를 다시 읽으면 165 MB 로그에서 요약 상세 28.6–44.3초·재사용 색인 44.4초, 읽기마다 이벤트 스냅숏 한 번이면 3.0초·8.8초(반환 바이트 동일). → 명세 9절에 스냅숏 읽기를 넣었다.
- (f) `JobSubmit.timeout_s` `le=15000`과 시간 상한 장치는 M22에서 이미 있고 M23 프로토콜을 같은 방식으로 넓히면 된다. 스테이징은 자기 분기(16 MiB)가 필요하다.
- (g) 독립 oracle(표준 라이브러리, `mw` 미import)로 기대 경로 16벡터(작업 모듈 안에서 정해지는 종료 이유 6개 `generations_complete`·`no_change`·`space_exhausted`·`evaluation_limit`·`reference_failed`·`repeated_failure`, 동점·실패 제동·기준 행 실패·소진·이어받음·교차→편집 전환·재시도; 시간·취소·작업 모듈 실패·출력 한도는 외부 입력이라 작업 모듈·작업 테스트가 덮음)와 산식 표를 `expected.json`에 기록(`--check` 종료 0). 실제 27평가는 모두 `scored`이고 서로 다른 점수 값이 6개뿐이라 동점 규칙이 실제로 쓰였다.
- 명세 모호함 S-1…S-11(재시도 횟수·본 키 시점·교차 자식 축소 순서·난수 호출 순서·소진 처리 등)은 독립 oracle과 같은 해석으로 확정해 명세 3절 "세부 확정"에 넣었다.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 명세 검토 둘(고정 전, 의도 감사와 명세·계획·인계 문서의 실행 가능성 검토): 의도 감사에서 첫 세대 구성·실패 제동·seed 개수·다중 변이 적용 방식 네 가지를 사용자에게 다시 물어 확정했고, 실행 가능성 검토에서 여러 곳 변이의 `coordinates_changed`(→ 반올림, 사용자 선택), 서버가 RDKit 없이 못 하는 리간드·상자 점검(→ 서버 부분 점검 + 나머지는 기준 행, 사용자 선택), GA 절차의 두 구현이 갈리는 지점, 다중 변이 모델 엔트리의 잔기 필드, `+`가 쿼리에서 공백이 되는 개체 키(→ `-`), 예약 단위의 재사용 의존(→ 재사용과 무관)을 바로잡았다.
- 독립 코드 검토(T10, 고정 전, 영역을 셋으로 나눈 새 인스턴스 셋): **막는 지적 없음**(approved ×3). 반영(`ea1c325`, `7871e83`): 상자 불일치 확인을 개체 게시 전으로, 모델링 자식 프로세스 계약 틈(종료 뒤 스트림 크기, 종료 코드 1의 남은·빠진 파일)을 `worker_failed`·`resource_exceeded`로, 실패한 행의 이유와 `model_handle` 유무(단계 전용 집합)와 정수 필드가 bool이 아닌 것을 읽을 때 검사, 죽은 `stage()` 제거, `gaJobPhase`(큐 `start`가 재시작을 받는 `blocked_reason` 집합)와 옵션 타입·문구·기존 작업 안내·실행기 조건 정리. 고치지 않은 권고는 `docs/tracking/findings.md`에 기록했다.
- 독립 증거 검토(T12, 코드 검토자와 다른 새 인스턴스, 고정 뒤): **APPROVE**, 참고 지적은 아래 "증거 검토"에 적었다.

## 게이트 (고정 `7871e83`, `gate.txt`, 2026-10-05 10:55:24Z부터)
시작 때 작업 트리 깨끗함, 다른 세션의 Stop 훅 pytest(10:47:10Z 시작)와 그 작업 모듈이 모두 끝난 뒤 시작(겹침 없음), 모든 명령을 한 줄로 차례로 실행, 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 백엔드 pytest는 Stop 훅의 다섯 그룹(`.codex/hooks/stop.py` `CHECKS[1:]`)을 제한 없이 따로 돌렸다.

| 명령 | 결과 |
|---|---|
| 백엔드 pytest 다섯 그룹(화학 24, M11 작업 API 25, M18 도킹 198, M19 일괄 209, 나머지 2,538 = 백엔드 2,228 + 실행기 310) | exit 0 ×5, 백엔드 합계 2684 passed(수집 2684), 0 skipped. 나머지 그룹 2432초 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 18개 파일(M22 게이트 17개 + `test_m23_offscreen_acceptance.py`) | exit 0, 474 passed, 0 skipped(M23 실행기 51개) |
| `node --check` 하네스 27개(`frontend/tests/offscreen/*.cjs` 전부, 새 `sequence-ga-flow.cjs` 포함) | exit 0 |
| `npm --prefix frontend run test:events` | exit 0, 379 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `7871e83`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m23_offscreen_acceptance.py --root runs/m23-acceptance-20261005-attempt1 --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/attempt1 --out docs/qa/m23-sequence-ga-20261005/acceptance --regressions --kbase <home>/Projects/kbase_kinase` (2026-10-05 11:55:34Z 시작, 13:01:48Z 종료 0, 회귀 포함 약 66분, M23 부분 11:55:35–12:06:16Z). 실패한 시도·재시도 없음. 시작 전 8000·3000 포트 비어 있음. (개발 실행 `runs/m23-t9-dev-20261005-{a..d}`는 T9의 이전 커밋 기준이며 T11 시도가 아니다.)
- 빌드 `8UVqy3iRzm6o2VSKemMX3`(gitHead `7871e83`, 소스 도장 일치, `dirtyFiles` 없음). `verdict: pass`, `acceptance: true`, 판정 사례 35개 모두 통과: `seqga-main` 29 + `SG-no-run`(main·unavailable) + `SG-unavailable` + `SG-repro-runs` + `SG-reproducible` + `SG-oracle-paths` + `S-no-egress`. 환경(`sequence_ga_design` 사용 가능: OpenMM 8.6.0, PDBFixer 1.12.0, Meeko 0.8.0, RDKit 2026.03.6, MDAnalysis 2.10.0, gemmi 0.7.5; `.deps` 없는 layout 백엔드는 `worker_missing`)·남은 프로세스 행 통과. 비-loopback 요청 0건, 제공자 호출 0회.
- 입력: 공개 구조 `public_1ubq.cif`(전처리, 직접 선택 위치 M1·Q2·I3·K6·L8·I44·G75·G76 등으로 실제 M20 후보 집합), 합성 표시 `synthetic-phenol-ligand.sdf`(M21 선례: 리간드가 있고 M7을 통과하는 공개 구조가 로컬에 없음).
- 관찰 요약(실제 Electron 오프스크린, 실제 OpenMM·PDBFixer·qvina): 후보 집합 전 이유만 → 후보 집합 목록·SDF 가져오기 → 초기 상태(자동 선택·제출·승인 없음) → 파라미터 가드(열한 키 범위 밖마다 칸별 이유·시작 막힘)·교차 규칙 둘·"기본값으로"·확인 항목·입장 거절 표시 → 시작 전 확인(예약 단위 = 명세 산식) → 사람이 누르는 증액(부족분만, `by: human`) → 첫 비싼 계산 승인 → 실제 GA 1 시작·진행(기준 행 기록, 세대, 개체 수) → 결과(야생형 기준 행이 개체 표와 따로, 세대 탭, 출처, 점수 문구, S1–S6) → 정렬 → 개체 상세(모델 값, mmCIF 내려받기 해시, M18 상세) → 같은 인자 재제출(기존 작업, 새 작업·단위 없음) → 재사용 → 부분 완료(`evaluation_limit`) → 화면 취소 → `reference_failed` → 늦은 응답 → 보고서 → 탭·프로세스·문구.
- 저장된 GA 요약(run A): GA 1(GA seed 21, 개체 4, 세대 4, 이어받음 1, `max_mutations` 3, `patience` 2, 새 평가 ≤ 32, 평가 seed 20261004, `ligand_range` 상자)은 `complete`/`no_change`, 3세대, 새 평가 10건, 예약 28단위, 기준 행 scored. GA 2(GA seed 13, 새 평가 ≤ 4)는 `partial`/`evaluation_limit`, 4건 새 평가 + 2건 재사용. GA 3는 화면 취소(`partial`/`cancelled`). GA 4(암시 수소 SDF)는 `partial`/`reference_failed`(`ligand_hydrogens_missing`, 기준 행 점수는 "—"이며 0이 아님). 예산: run A 사용 58 / 한도 58(GA마다 시작 전 예약 한 번, 환불 없음, 같은 인자 재제출 0, 모든 증액은 화면 버튼 클릭).
- 재현 검사(`SG-reproducible`): 흐름의 GA 1을 **같은 서버 프로세스**의 새 run 두 개에서 화면으로 다시 돌렸다(콜드 재시작이 아님; 모든 증액이 화면 클릭이라 실행기는 증액 라우트를 부르지 않음). 둘 다 작업 `done`, `complete`/`no_change`, run별 obj:// handle과 그 위에서 계산된 해시(`call_key`·`conditions_sha256`·`selection_sha256`·`input_sha256`)만 자리표시로 바꾼 요약 SHA-256 `63727c14…`가 흐름과 같았고 개체 13행(기준 행 + 3세대)의 모델·M18 결과·포즈 SDF 바이트도 같았다. (T9 개발 실행 c·d는 이전 커밋에서 서로 다른 백엔드 프로세스로도 같은 digest `10e35187…`였다. 모듈 pin이 바뀐 뒤라 T11 digest와 값이 다르다.) 다른 버전 간 비트 동일은 주장하지 않는다.
- 독립 oracle 경로 대조(`SG-oracle-paths`): GA 1·GA 2의 저장 경로가 T1 oracle(`expected.json` `vectors.s4_tiny_observed`, GA 2는 GA 1의 저장 행을 재사용 색인으로)과 같다.

### 관찰하지 못한 사례 (위조하지 않음)
- `SG-individual-without-score`(점수 없는 개체 화면): 1UBQ + 페놀 GA의 모든 개체가 점수를 낸다(점수 없는 기준 행은 `reference_failed` 사례에서 관찰). `frontend/tests/sequence-ga.test.cjs`와 `backend/tests/test_sequence_ga_api.py::test_rows_without_a_score_are_null_never_zero`가 덮는다.
- `SG-heavy-atom-warning`: 1UBQ 중원자 602개 < 4,890. `test_sequence_ga_inputs.py`(경계 4,890/4,891)·`sequence-ga.test.cjs`가 덮는다.
- `SG-other-stop-reasons`(`generations_complete`·`space_exhausted`·`time_exhausted`·`worker_failed`·`resource_exceeded`·`repeated_failure`): `test_sequence_ga_worker.py`·`test_sequence_ga_jobs.py`(테스트에서만 줄인 상수)가 덮는다.
- `SG-model-conditional-sentences`(SL5·L6): 1UBQ에는 Cys가 없고 HIS 상태 차이도 없다. `test_sequence_model_bundle.py`·`test_sequence_model_worker.py`(합성 Cys 구조의 실제 모델링)가 덮는다.
- `SG-dry-run`: `test_sequence_ga_jobs.py::test_dry_run_plans_only`·`sequence-ga.test.cjs`가 덮는다.

### 회귀 (고정 `7871e83`, 같은 빌드 `8UVqy3iRzm6o2VSKemMX3`, M23 실행기 `--regressions`가 차례로)
- 각자 새 `--root runs/m23-acceptance-20261005-attempt1-mXX-regression`·`--artifacts …/regressions/mXX`, `--code-root <repo>`(M20·M16·M15는 `--kbase`). 대장마다 같은 buildId·gitHead, `buildCurrentWithSource: true`, `dirtyFiles`는 이 QA의 Git 미추적 증거 폴더뿐(소스 파일 없음).
- M22 `m22-regression/` → `acceptance: true`, 25/25(`GA-null-result`·`GA-no-change`·`GA-time-and-worker-limits` 관찰하지 않음, M22와 같음). M21 → 23/23(`MM-unavailable`·`MM-pair-approval`·`MM-failed-job`·`MM-zero-contacts`·`MM-conditional-limitations`). M20 → 24/24(`M-map-conflict`·`M-too-many-positions`·`M-nonstandard-disulfide`). M19 → 26/26(`B-dry-run-shortfall`·`B-null-result`·`B-time-limits`). M18 → 24/24(`D-zero-modes`). M17 → 21/21. M16 → 19/19. M15 → 14/14. M14 → 15/15. M8–M13 `m13-regression/`(`--phases workflows,unavailable,regressions,m11,m12,ledger`) → 28/28, 17행 통과, M11·M12 하위 실행기 통과.
- 모두 종료 0, 외부 요청 0건, 남은 프로세스 없음. 제공자 호출 필드가 있는 흐름 행은 모두 0회. 이번에 `MutationModelPanel.tsx`(M21 영역)를 바꿨으므로 M21·M14 회귀가 직접 확인한 것은 M21 영역의 마크업·동작이 그대로라는 점이다.

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님). 기존 수락 실행기와 흐름 스크립트는 하나도 고치지 않았다(회귀 대장의 "Changed existing expectations: none").
- `backend/tests/test_docking_batch_budget.py`·`test_ligand_ga_budget.py`(증액 호출자 AST): `raise_limits`·`limit_approval`을 언급하는 소스 파일 집합·`limit_approval` 라우트 목록·호출자가 둘에서 셋으로 늘고(M23 라우트와 함수), M22 필터 `"/ligand/ga/" not in route.path`가 M23 라우트를 모르는 문제를 고쳤다. M19·M22 함수·라우트가 각각 하나라는 단언은 그대로다. M23 쪽 규칙(호출자 셋, 서로 부르지 않음)은 새 `test_sequence_ga_budget.py`가 확인한다.
- `backend/tests/test_ligand_api.py`: `/capabilities` 방법 집합에 `sequence_ga_design`.
- `backend/tests/test_mutation_model_worker.py::test_only_the_worker_imports_pdbfixer_and_no_module_imports_the_worker`: 이 모듈을 import하는 파일이 없다는 단언을 M23 모델링 프로그램 하나만 import한다는 단언으로(명세 4절이 M21 함수를 불러 쓰라고 요구, 서버 모듈이 import하지 않는다는 규칙은 그대로).
- `frontend/tests/report-library.test.cjs`: `sequence_ga` 종류 이름 "서열 GA 보고서" 단언 추가.
- 모든 회귀가 새 루트라 이전 결과 재사용의 영향이 없다. M23은 M18·M21 호출 키가 묶는 파일을 바꾸지 않았으므로 M18·M19·M21·M22 결과는 계속 재사용된다(골든 호출 키 테스트).

## 알려진 한계
- 서열 GA 입력은 공개 1UBQ(중원자 602개)와 합성 표시 페놀 SDF다. 실제 OpenMM·PDBFixer·qvina로 GA 동작을 검증했을 뿐 생물학적 설계가 아니며 리간드가 있고 M7을 통과하는 공개 구조는 로컬에 없다.
- 시간은 1UBQ(평가 약 11초/건)에서만 쟀다. 큰 구조(중원자 4,890개 근처)·개체 64개 연속·4시간 실행은 재지 않았고(가늠: 개체 하나 ≈ 11 MB, 출력 256 MiB가 먼저 닿을 수 있음) 모델링 240초·도킹 300초 단계 상한에 닿는 입력도 만들지 않았다.
- 개체 점수는 개체마다 다른 수용체의 qvina 값이며 같은 수용체 안의 비교가 아니다(S6). 모델은 PDBFixer 곁사슬 한 가지 형태 + 최대 50회 최소화이고 구조의 충돌·전위를 점수나 선택에 쓰지 않는다. 여러 곳 변이는 구조 순서의 연속 적용이라 순서·곁사슬 크기에 따라 모델이 달라질 수 있다.
- 부모 선택(토너먼트·난수·재시도)은 작업 모듈 기록이며 서버는 부모–자식 변이 관계만 검증한다(S1). 같은 seed라도 저장 결과 집합이 다르면 다른 경로가 나온다(S3). 시간·상한·취소·실패로 멈춘 실행은 재현을 약속하지 않는다(S2).
- 서버 부분 입력 점검은 도킹 작업 모듈보다 엄격하지 않지만 같은 입력에서 이유가 다를 수 있다(상자 값 규칙, 결함이 둘 이상인 SDF). 나머지 입력 오류는 야생형 기준 행에서 드러나 `reference_failed`가 되며 예약 단위는 환불되지 않는다.
- GA가 도는 동안(최대 15000초) run 실행 잠금과 전역 작업 슬롯을 쥔다. 읽기는 한 번의 이벤트 스냅숏으로 모든 개체를 다시 검증하며(T1 측정 165 MB 로그에서 상세 3.0초·재사용 색인 8.8초), `preflight`·작업 목록 폴링은 더 여러 번 읽는다.
- Stop 훅 나머지 그룹은 단독 2432초로 480초 제한을 넘고, M20–M23 실행기 단위 테스트가 훅 목록에 없다(`docs/tracking/findings.md`).

## 대체한 과거 검증 범위
- M23은 공유 소스를 바꿨다: 백엔드 `api/app.py`(읽기·증액 라우트, capability, 작업 승인 허용 목록, 작업 artifacts·진행, 보고서 분기·목록), `jobs/queue.py`, `jobs/guardian.py`, `core/events.py`, `tools/energetic.py`, `config/tools.yaml`, `docking_bundle.py`(`producer()`·`_mutation_receptor`), `docking_batch_inputs.py`(`published_m18_results`). 프런트 `app/page.tsx`, `components/MutationModelPanel.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, `design/components.css`(+ 생성물).
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(2684개, skip 0)와 M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `7871e83`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 증거 검토 (T12, 코드 검토자와 다른 새 인스턴스, 고정 뒤)
**APPROVE**(막는 지적 없음). 검토자가 확인한 것: 증거 커밋은 `docs/qa/m23-sequence-ga-20261005/` 아래의 추가뿐이고(645개 파일, 수정·삭제 0, `preflight.txt` 불변) 고정 뒤 소스 변경이 0이며, 빌드 도장(`gitHead 7871e83`, `buildCurrentWithSource true`, `dirtyFiles []`)과 하네스·실행기 해시가 고정 커밋과 같고, 게이트 명령이 Stop 훅의 pytest 그룹과 표준 게이트를 빠짐없이 덮으며 로그의 exit·통과 개수·시간이 `gate.txt`와 같고(`SKIPPED`·`FAILED`·`ERROR` 0줄) 합계 산식이 맞는다(24 + 25 + 198 + 209 = 456, 2684 − 456 = 2228, 2538 − 2228 = 310, 백엔드 2209 → 2684는 새 M23 테스트 9개 파일 합계, `test:events` 345 + 34 = 379). 수락 35사례가 모두 `pass`이고 관찰하지 못한 5개와 겹치지 않으며 그 이유로 든 테스트가 고정 커밋에 있다. 사례마다 스크린샷·paint 프레임이 있고 세 단계 모두 `offscreen true`·GPU·WebGL2·비-loopback 0, 예산 한도 8 → 28 → 56 → 58과 사용량 58/58, 렌더러가 보낸 `limit_approval` POST는 main 3건·repro 2건이며 실행기와 하네스는 이 라우트를 직접 부르지 않는다. 재현 digest `63727c14…`가 세 곳에서 같고(대체한 키는 handle로 계산되는 `input_sha256`·`selection_sha256`·`conditions_sha256`·`call_key`뿐), oracle 대조 둘이 `conditions true`·`equal true`, 회귀 10개의 사례 키 집합·관찰하지 못한 사례 집합이 M22 T10 증거와 같고, 11개 폴더의 `SHA256SUMS`와 `ARCHIVED-EVIDENCE.sha256`이 모두 OK다.

참고(막지 않음):
- runner의 최종 판정(`failedSteps []`, 회귀 종료 코드)과 게이트 원본 로그(`gate/00–37.log`)는 Git 제외 artifacts 폴더에만 있다(커밋된 `runner-summary.jsonl`은 `case-ledger` 단계에서 끝난다). 이 폴더를 정리하면 이후에는 `gate.txt`·회귀 폴더 ledger의 내부 일관성으로만 판단할 수 있다.
- 재현 검사는 run 사이에서 "같은 호출 키"를 보일 수 없다(`call_key`가 run에 묶인 handle을 포함하는 `selection_sha256`으로 계산됨). 같은 run 안에서 같은 호출 키면 기존 작업을 돌려주는 것은 `SG-dedupe`가 보인다.
- 골든 호출 키(`golden_call_keys.json`)는 M18 둘·M19·M21만 담고 M22는 `ligand_ga_*` 파일 해시·M18 골든 키·M22 회귀 25/25로 간접 덮인다.
- `SG-dedupe`는 이미 끝난 GA를 다시 보이려고 사람이 28단위를 증액했다(한도 28 → 56, 과금 0). 예약 산식이 입력 파라미터만으로 정해지는 명세 7절과 일치하며 M22의 같은 사례는 남은 예산이 있어 증액이 필요 없었다.
- 개체 쪽 `GA 4`는 도킹 단계 기준 행 실패(`ligand_hydrogens_missing`)만 관찰했다. 기준 행 모델링 실패는 `test_sequence_ga_worker.py`의 기준 행 모델링 실패 테스트가 덮는다.

## 남은 일
- main 병합(사용자 승인 대기, `--no-ff`). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): Stop 훅 나머지 그룹 시간 초과와 M23 실행기 단위 테스트 누락, M17·M18·M19·M22 패널의 `claimed` 작업 "작업 시작" 잠재 결함, 관찰하지 못한 사례, 큰 구조·긴 실행 미측정, 읽기·검증 틈, M22 이월 경계.
