# M20 변이 후보 생성 완료 기록

- 판정: **완료** (2026-10-04). main 병합: `5ed9835`(push 없음). 사용자가 병합을 승인했다.
- 브랜치: `dryforge/m20-mutation-candidates` (`phase/m20-mutation-candidates` = main `356b268`에서 분기). M19는 시작 전에 main에 병합되어 있었다(`20e652c`, 기록 `356b268`).
- 고정 소스: `ea2913c`(`ea2913c7346bf2660853e6415a4dbb5b27e2d298`, 독립 코드 검토 수정 커밋). 증거 커밋 `c32e9fb`, 증거 문구 커밋 `0133360`(증거 검토 권고: 재현 검사 문구). 고정 뒤 소스 변경은 없다. 고정 뒤 커밋은 증거·기록 문서뿐이다.
- 수락 증거: `docs/qa/m20-mutations-20261003/`(`preflight.txt` 착수 확인, `gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M20 수락, `m19-regression/`, `m18-regression/`, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 51개 331,879,749 B, m14-regression 1개 1,191,726 B, m15-regression 1개 590,107 B, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 외부 요청 0건, OpenRouter 호출 0회(흐름 행과 재현 검사).

## 결과물
- 값싼 도구 `generate_mutation_candidates`(`Run.call`, `cost_class: cheap`, 작업 큐·승인·예산 단위 없음, dry-run에서도 실행) → 불변 결과 `mutation_candidate_set@1`(`method_version` `mw.mutation_candidates/v1`). 등록 네 곳: `config/tools.yaml`, `backend/mw/tools/mutations.py`(사전 검사 훅 + 구현), `workspace.py`의 `build_registry()`, `app.py`의 `SUPPORTED_TOOLS`.
- 서버 모듈(gemmi·numpy·표준 라이브러리만, RDKit·Meeko·MDAnalysis·OpenMM·ProLIF import 없음): `mutation_constants.py`(닫힌 집합·상한·기본값·한계 문장 5개, 의존성 없음), `mutation_candidates.py`(요청 정규화·입장 검사 일부, 위치 출처, 거리, 보호·제외·해제, 후보, 결과 객체, `validated_set`), `mutation_reads.py`(읽기 4개), `mutation_reports.py`(보고서).
- API: `GET /runs/{id}/mutation_candidate_sets`, `/mutation_candidate_sets/{handle}`, `/{handle}/positions`, `/{handle}/candidates`(handle은 경로), `/capabilities`의 `methods.mutation_candidates`(항상 사용 가능), `GET /tools`에 새 도구, 방법 보고서 `analysis_type: "mutation_candidates"`.
- 화면: 단백질 공학 탭의 `frontend/src/components/MutationPanel.tsx`(순수 로직 `src/lib/mutations.ts`), `app/page.tsx`(마운트), `WorkspaceTabs.tsx`(단백질 탭 안내 제거, `protein` 슬롯), `lib/workspace-tabs.ts`(`UNAVAILABLE_NOTICES` 빈 표), `lib/api.ts`·`contracts.ts`, `lib/report-library.ts`("변이 후보 보고서"), 스타일 `design/components.css`와 생성물.
- Fixture: `backend/tests/fixtures/mutation/`(표시된 합성 mmCIF·PDB 구조, 손 계산 기대값 `expected.json`, `SYNTHETIC-PROVENANCE.md`, `build_mutation_fixtures.py --check`). 공개 구조는 기존 `public_1mq4.cif`·`public_1hsg.cif`.
- 테스트: 백엔드 `test_mutation_candidates.py`, `test_mutation_tool.py`, `test_mutation_api.py`, `test_mutation_reports.py`. 프런트 `tests/mutations.test.cjs`. 스크립트 `test_m20_offscreen_acceptance.py`.
- QA 도구: `frontend/tests/offscreen/mutation-flow.cjs`(`test:offscreen:mutations`, 모드 `main`), `scripts/m20_offscreen_acceptance.py`(단계 `reference-import`·`mutation-main`, 재현 검사, `--regressions`).

## 사용자 결정 (2026-10-03, 명세 확정 때)
근거는 결정 0028. 사용자는 모든 질문에서 추천안을 골랐다.
- 위치 출처 셋(포켓·리간드 껍질·직접 선택)을 요청마다 골라 합집합. 전처리 구조만.
- 기본 보호 = 사용자 목록 + KLIFS 주요 부위 10개(주석이 있을 때) + 금속 근접(`METALS` 10종, 3.0 Å, 요청마다 1.0–5.0) + 이황화 Cys(SG–SG 2.5 Å 고정). 촉매 잔기 데이터베이스는 "사용할 수 없음"(M26).
- 단일 변이만, 위치마다 원래를 뺀 표준 19종(허용 목록으로 줄임). 후보 정보는 기하 사실만. 해제는 잔기를 지정해서. 표 + 보고서만. 새 값싼 도구 + 새 불변 결과. 변형 이름은 M12의 10개.
- 주석 없이 요청하면 `not_checked`로 진행(화면은 같은 구조의 가장 최근 주석과 그 번호 대응을 미리 고름).
- 실행 중 사용자가 승인한 명세 수정: 포켓 결과는 store 기반 RunView로 `validated_pocket_set`(게시 확인)까지 검사, `ligand_required`를 `ligand_invalid`보다 먼저, `methods.mutation_candidates`는 항상 사용 가능·도구 목록은 `GET /tools`.
- 조율 세션이 정하고 사용자가 최종 확인에서 바꿀 수 있는 것(닫힌 이름, 고정 문장 5개, 상한 400/400 거절, 기본 반경 5.0 Å [1, 12], 해제 범위·효과 없음 기록·충돌 거절, 위치 행 하나, 빈 결과 유효, 경로 handle 읽기 4개, M13 미확장, `candidate_set_invalid`, 수소만 리간드 `ligand_invalid`, 중원자 없는 잔기 거리 null, 리간드 자동 선택 없음(명세 10절 문구와의 편차), 보고서의 "촉매" 허용)은 결정 0028에 적었다.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인, 합성 fixture | `472ba50` |
| T2 순수 계산 모듈과 테스트 | `ae0673c` |
| T3 도구 연결(등록 네 곳, 사전 검사 훅) | `39daab4` |
| T4 읽기 API | `b99574d` |
| T5 `mutation_candidates` 보고서 | `423ed8b` |
| T6 프런트 API·순수 로직 | `5b508ae` |
| T7 단백질 공학 탭 변이 후보 패널 | `efb680f` |
| T8 오프스크린 흐름과 M20 수락 실행기(M14 탭 기대 최소 수정 포함) | `f33aacd` |
| T9 독립 코드 검토 수정 | `ea2913c`(= 고정 소스) |
| T10 게이트·수락·회귀 증거 | `c32e9fb` |
| T11 증거 검토 권고: 재현 검사 문구 | `0133360` |
| T12 완료 기록·결정 0028·프로젝트 문서 | 이 기록과 같은 커밋들 |

## 착수 확인 (`preflight.txt`, 기준 `356b268`)
- 기존 읽기 경로(`structure_residues`·`_parse`·`METALS`·`_selected_ligand`)로 위치(폴리머 7필드), 리간드 해석, 중원자 최소 거리, 금속 잔기, SG 원자, 변형 이름 원래 `resname` 보존이 모두 가능했다. 합성 구조로 전처리 경로를 지나 거리 330쌍(mmCIF)·224쌍(PDB)이 독립 계산과 최대 2.8e-14 Å 안에서 같았다.
- 실제 M12·M15·M16 객체(1MQ4·1HSG, 실제 fpocket)의 필드는 명세와 같았다. 다른 점은 포켓 결과 검증 방법 하나(M1: 훅의 store에 이벤트가 있어 `validated_pocket_set`을 부를 수 있음)이며 사용자 승인으로 명세를 고쳤다. 모호한 두 곳(A1 `ligand_required` 순서, A2 capability·도구 목록)도 같이 정했다.
- 1MQ4 + ADP oracle: 5.0 Å 껍질 20위치, 금속 3.0 Å 근접 ASN A261·ASP A274(MG A2088, ASP274는 KLIFS `xDFG.81`과 동시 사유), 이황화 0쌍. 1HSG + MK1: 같은 서열 두 체인 33위치, 금속 없음.
- 위치 400 × 후보 19 합성 결과: 내용 0.90 MiB, `object_created` 이벤트 한 줄 1.20 MiB(코드에 크기 상한 없음, 문제 없음).
- 하드코딩된 도구·탭 기대: 백엔드 테스트 3곳, 프런트 테스트 2파일, M14 실행기 1파일(아래 "바뀐 기존 기대").

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토(고정 전): **막는 지적 1**, 권고 여럿. 막는 지적: 리간드를 준 요청에서 중원자가 없는 위치(수소만 남은 잔기)의 거리는 구현이 null로 만들지만 `validated_set`은 숫자만 받아, 저장은 되고 읽기·보고서에서는 검증 실패로 읽을 수 없는 결과가 생길 수 있었다. 고친 것(`ea2913c`): 거리 null 허용(0이 아님), 도구 구현이 저장 전에 `validated_set`을 돌려 통과하지 못하면 저장하지 않고 `candidate_set_invalid`로 실패, 수소만 있는 리간드는 사전 검사에서 `ligand_invalid`, 보고서 금지어 검사를 식별자를 뺀 고정 템플릿 문장에만(체인 이름 `BEST` 같은 식별자가 보고서를 깨지 않게), 늦게 끝난 보고서 생성도 같은 run이면 보고서 목록을 다시 읽게(`mutationReportSavedForRun`). 권고는 모두 반영했다.
- 기록한 편차: 화면은 리간드를 하나뿐이어도 자동으로 고르지 않는다(명세 10절 "리간드가 있으면 선택자" 문구보다 엄격, 결정 0028). 보고서는 필수 문장 "촉매 잔기 데이터베이스: 사용할 수 없음" 때문에 "촉매"를 금지어에 넣지 않았다(M16 보고서와 다름).
- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 고정 뒤): **approve**. 문구 권고 둘(재현 검사가 같은 서버 프로세스의 새 run이며 콜드 재시작이 아님을 `summary.txt`와 `acceptance/README.md`에 밝힘)을 `0133360`에 반영했다.

## 게이트 (고정 `ea2913c`, `gate.txt`, 2026-10-03 14:02:47–14:29:42 UTC)
시작 때 작업 트리 깨끗함, 다른 세션의 Stop 훅 pytest가 끝난 뒤 시작(겹침 없음), 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 끝난 뒤 작업 트리 깨끗함, HEAD 그대로, 남은 프로세스 없음, 8000/3000 비어 있음.

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 1761 passed, 0 skipped(1615초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 15개 파일(M19 게이트 14개 + `test_m20_offscreen_acceptance.py`) | exit 0, 344 passed, 0 skipped |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow`·`ligand-flow`·`docking-flow`·`docking-batch-flow`·`mutation-flow` | exit 0 ×9 |
| `npm --prefix frontend run test:events` | exit 0, 298 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `ea2913c`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m20_offscreen_acceptance.py --root runs/m20-acceptance-20261003-attempt1 --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/attempt1 --out docs/qa/m20-mutations-20261003/acceptance --regressions --kbase <home>/Projects/kbase_kinase` (분리 실행, 14:30:01–15:17:06 UTC, 회귀 포함 약 47분). 실패한 시도·재시도 없음.
- 빌드 `vPeuYWb5CrtGZ__mURwva`(gitHead `ea2913c`, 소스 도장 일치, `dirtyFiles` 없음). `verdict: pass`, `acceptance: true`, 판정 사례 24개(`mutation-main` 22 + `M-reproducible` + `S-no-egress`), 단계 `reference-import`·`mutation-main` 통과. 환경(`mutation_candidates` 사용 가능, fpocket 4.2.3)·참조 가져오기(세트 `999392929c37…9375`)·남은 프로세스 행 통과. 비-loopback 요청 0건, 제공자 호출 0회.
- 관찰 요약(공개 1MQ4 실제 바이트, 실제 fpocket 한 번): run 없음은 이유만 → 불러왔지만 전처리하지 않은 run은 "사용할 수 없음"과 이유만(숫자·컨트롤·도구 호출 없음) → 전처리 → ADP·PO4가 보이지만 아무것도 자동으로 고르지 않고 리간드 껍질은 ADP를 고를 때까지 막힘 → 주석 없는 요청: 요청 영역의 KLIFS "검사하지 않음" 안내, 저장·표시 `not_checked`(`annotation_not_given`), KLIFS 칸 "— (검사하지 않음)" → ADP 5.0 Å 껍질 20위치·거리(≤ 1e-9 Å)·`ROUND_HALF_UP` 칸·MG 근접 제외(ASN261·ASP274, MG A2088)가 T1 numpy oracle과 같음, 후보 342 → 기존 화면으로 번호 대응·주석 → 탭에 들어올 때 목록 다시 읽기(GET만), 구조를 고르면 가장 최근 주석과 그 번호 대응 미리 선택 → 보호·해제 충돌은 화면에서 막힘, KLIFS 주요 부위 이름표와 함께 제외, ASP274 KLIFS + 금속 동시 사유, LEU139 사용자 보호, ASN261 해제(후보), ARG126 해제 효과 없음 → 허용 A/G/W(`AGW`, 새 handle) → 같은 요청 = 같은 handle(새 저장 없음) → 금속 5.0 Å 근접 = oracle, 목록 빼기·다시 읽기 → 포켓 출처(저장된 모든 포켓 번호 + 껍질 12 Å) 위치 = 저장된 안쪽 잔기 합집합 → 필터 4개·거리 정렬(값 없는 행 끝)·후보 필터·페이지 = 저장 페이지 → 후보 0개(ALA A:160, 허용 A) = 빈 결과와 저장된 제외 사유 수(실패 아님) → 표시된 요청 변조 fixture로 실제 서버 거절 `structure_invalid`·`annotation_invalid`·`protect_release_conflict`·`ligand_required`(422, 한국어 이름 + 코드, 저장 없음) → 보고서 → 지식 탭 "변이 후보 보고서", 내용 = 저장 Markdown(고정 문장 5개), Markdown·JSON 다운로드 = 백엔드 바이트 → 표시된 보류 응답 fixture로 다른 결과·다른 run으로 바꾼 뒤 늦은 응답 버림 → 구조 분석 탭 상태 유지 → 고정 문장 밖에 순위·추천·효과 낱말 없음.
- 재현 검사(`M-reproducible`): 흐름의 주석 없는 껍질 요청(ADP A:2001, 반경 5 Å, 20종 허용, 금속 3 Å, 후보 342)을 **같은 서버 프로세스**의 새 run 두 개에서 API로 run마다 두 번씩 보냈다(콜드 재시작이 아님). run 안에서 같은 handle이 두 번 나왔고, obj:// handle만 자리표시로 바꾼 저장 내용 SHA-256 `5fc0f30e…293da5`가 흐름의 결과와 같았다. handle은 run마다 다르므로 run 사이 handle 동일은 주장하지 않는다.

### 관찰하지 못한 사례
- `M-map-conflict`: 이 흐름에는 구조마다 번호 대응이 하나뿐이라 화면의 번호 대응·주석 충돌 안내에 닿지 않는다. `frontend/tests/mutations.test.cjs`(`annotationMapConflict`)와 `backend/tests/test_mutation_tool.py`(`annotation_map_mismatch`)가 덮는다.
- `M-too-many-positions`: 1MQ4의 단백질 잔기는 261개로 상한 400 아래다. `test_mutation_tool.py::test_too_many_positions_is_429_and_nothing_is_stored`가 덮는다.
- `M-nonstandard-disulfide`: 1MQ4에는 변형 이름 잔기와 2.5 Å 안의 SG–SG 쌍이 없다(T1). `backend/tests/test_mutation_candidates.py`의 합성 fixture 테스트가 덮는다.

### 단위 테스트로만 확인한 것
- 독립 코드 검토 수정(`ea2913c`) 가운데 수소만 있는 잔기의 거리 null(`test_hydrogen_only_position_with_a_ligand_is_stored_with_a_null_distance`), 수소만 있는 리간드의 `ligand_invalid`(`test_hydrogen_only_ligand_is_ligand_invalid_before_the_implementation`), 저장 전 검증(`test_a_built_set_that_does_not_validate_is_never_stored`), 식별자 속 금지어(`test_identifiers_containing_forbidden_words_do_not_fail_a_report`)는 오프스크린 흐름에서 닿을 수 없다. 1MQ4 좌표에는 수소가 없고(전처리도 기본은 수소 제거이며 `hydrogens: keep`일 때만 남음), 정상 입력으로는 저장 전 검증 실패를 만들 수 없기 때문이다.
- 늦게 끝난 보고서 생성의 목록 갱신(`mutationReportSavedForRun`)은 `frontend/tests/mutations.test.cjs`로만 확인했다. 흐름의 늦은 응답 사례는 상세·위치·결과 목록 응답을 다룬다.

### 회귀 (고정 `ea2913c`, 같은 빌드 `vPeuYWb5CrtGZ__mURwva`, M20 실행기 `--regressions`가 차례로)
- 각자 새 `--root runs/m20-acceptance-20261003-attempt1-m1X-regression`·`--artifacts frontend/tests/offscreen/artifacts/m20-acceptance/attempt1/regressions/m1X`, `--code-root <repo>`(M16·M15는 `--kbase`).
- M19 `m19-regression/` → `acceptance: true`, 26/26(`B-dry-run-shortfall`·`B-null-result`·`B-time-limits` 관찰하지 않음, M19와 같음). M18 `m18-regression/` → 24/24(`D-zero-modes` 관찰하지 않음). M17 → 21/21. M16 → 19/19. M15 → 14/14. M14 → 15/15. M8–M13 `m13-regression/`(`--phases workflows,unavailable,regressions,m11,m12,ledger`) → 사례 28개·필수 단계 17개, M11·M12 하위 실행기 통과.
- 모두 외부 요청 0건, 남은 프로세스 없음. 제공자 호출 필드가 있는 흐름 행은 모두 0회(M13 하위 실행기·회귀 행은 이 필드를 기록하지 않음, M18·M19와 같음).

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님).
- `backend/tests/test_api.py`: `GET /tools` 이름 집합에 `generate_mutation_candidates`.
- `backend/tests/test_residue_numbering.py`, `test_reference_site_annotation.py`: 사전 검사 훅이 있는 도구 집합에 `generate_mutation_candidates`.
- `backend/tests/test_ligand_api.py` 2줄: `/capabilities` 방법 집합에 `mutation_candidates`.
- `frontend/tests/workspace-tabs.test.cjs`: `UNAVAILABLE_NOTICES`가 비었음(단백질 탭 안내와 그 여는 단계 사례 삭제).
- `frontend/tests/offscreen/tabs-flow.cjs`와 `scripts/m14_offscreen_acceptance.py`(`T-unavailable` 설명): 단백질 공학 탭이 안내 대신 변이 후보 화면을 보이고, 그 화면은 GET 읽기만 보낸다(리간드 탭 선례). 명세 12절이 의도한 변경이다.
- 그 밖의 수락 실행기(M13·M15–M19)와 흐름 스크립트의 기대는 바뀌지 않았다. 과거 검토 파일·해시는 건드리지 않았다.

## 알려진 한계
- 촉매 잔기는 판정하지 않는다(데이터베이스는 M26). KLIFS 주요 부위 보호는 같은 구조의 주석을 줄 때만 검사한다. 주석의 `absent` 부위(번호 대응 없음 등)는 보호되지 않는다.
- 포켓 출처는 그 run의 fpocket 결과를 그대로 쓴다. fpocket은 실행마다 포켓 수·안쪽 잔기가 다를 수 있다(`fresh_execution_deterministic: false`).
- 리간드는 물·`METALS`가 아닌 모든 HETATM 잔기(MSE HETATM 포함)라서 "리간드가 여럿"이 흔하다(1MQ4: ADP·PO4). 화면은 자동으로 고르지 않는다.
- 후보 구조·에너지·히스티딘 양성자 상태는 없다(M21). 동시 변이는 없다(M23).
- 읽기는 매번 저장 객체 전체를 다시 검증하고 목록은 이벤트 로그를 다시 읽는다(위치 400 × 후보 19 결과면 객체 약 0.9 MiB).

## 대체한 과거 검증 범위
- M20은 공유 소스를 바꿨다: 백엔드 `api/app.py`(`SUPPORTED_TOOLS`, capability, 보고서 분기·목록, 읽기 라우트), `workspace.py`, `config/tools.yaml`. 프런트 `app/page.tsx`, `WorkspaceTabs.tsx`, `lib/workspace-tabs.ts`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, 스타일.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(1761개, skip 0)와 M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `ea2913c`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합 완료(`5ed9835`). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): 관찰하지 못한 사례, 오프스크린에서 닿지 않는 검토 수정, `candidate_set_invalid`가 상수 모듈·화면 이유 이름표에 없음, Stop 훅 나머지 그룹에 M20 실행기 단위 테스트가 없음, 화면의 리간드 자동 선택 없음(명세 문구와의 편차, 사용자 확인 대상).
