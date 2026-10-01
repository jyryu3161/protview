# M17 리간드 부분 교체 후보 생성 완료 기록

- 판정: **완료** (2026-10-01). main 병합 전(병합 방법은 사용자에게 묻는다).
- 브랜치: `dryforge/m17-ligand` (`phase/m17-ligand-candidates` = main에서 분기). M16은 시작 전에 main에 병합되어 있었다(`0fb3426`, 기록 `fb5f108`).
- 고정 소스: `e6ab4f9`(`e6ab4f9b82808aaddb67c1e2d53ef80628dc097a`, 독립 코드 검토 수정). 증거 커밋 `a81f50a`. 고정 뒤 소스 변경 없음(이 기록 커밋은 기록 문서와 Stop 훅 테스트 목록만 바꾼다, 아래 "기존 검사 스크립트").
- 수락 증거: `docs/qa/m17-ligand-20261001/`(`preflight.txt` 착수 확인, `gate.txt` 게이트, `acceptance/` M17 수락, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 큰 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(각 폴더의 `ARCHIVED-EVIDENCE.sha256`, `m16-regression/`은 옮길 파일 없음).
- 외부 요청 0건, OpenRouter 호출 0회(모든 흐름 행).

## 결과물
- 작업 프로토콜 2개(기존 `JobQueue` 비싼 작업 경로, 시간 상한 120초): `rdkit_inspect_v1`(도구 `rdkit_inspect_ligand`) → `ligand_inspection@1`, `rdkit_enumerate_v1`(도구 `rdkit_enumerate_ligands`) → `ligand_candidate_set@1`. 작업 모듈 `backend/mw/jobs/ligand_worker.py`(`.deps/prolif/venv-locked`, RDKit 2026.03.6). `jobs/queue.py`(`LIGAND_PROTOCOLS`, 스테이징 한도 48 MiB), `jobs/guardian.py`(고정 진입점), `tools/energetic.py`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`, 작업 전용 등록), `config/tools.yaml` 등록.
- 서버 모듈(RDKit import 없음): `ligand_constants.py`(닫힌 집합·상한·고정 한계 문장), `ligand_inputs.py`(block 가져오기 경량 검사), `ligand_site.py`(부위 순수 그래프 검사), `ligand_filters.py`(필터 평가·정렬·페이지), `ligand_bundle.py`(capability handshake, 입장 검사, 호출 키, 스테이징, 게시 검증, 검증 읽기), `ligand_reads.py`(읽기 API), `ligand_reports.py`(보고서). `chemical_inputs.py`는 새 두 종류를 `ligand_inputs`로 넘기는 분기만 더했다(`ligand_sdf`·M11 동작 불변).
- API: 가져오기 종류 `building_blocks_sdf`·`building_blocks_smiles`, 읽기 7개(`/ligand/prerequisites`, `/ligand/inspections`, `/ligand/inspections/detail`, `/ligand/candidate_sets`, `/ligand/candidate_sets/detail`, `/ligand/candidate_sets/rows`, `POST /ligand/preview`), `/capabilities`의 `methods.ligand_candidates`, 방법 보고서 `analysis_type: "ligand_candidates"`(요청 `filters`).
- 화면: 리간드 설계·탐색 탭의 `frontend/src/components/LigandPanel.tsx`(순수 로직 `src/lib/ligand.ts`), `WorkspaceTabs.tsx`·`workspace-tabs.ts`(리간드 탭 안내 제거, 단백질 공학 안내 유지), `app/page.tsx`(탭 마운트, 보고서 목록 `reloadToken`), `lib/api.ts`·`contracts.ts`·`report-library.ts`("리간드 후보 보고서"), 스타일 `design/components.css`와 생성물. `lib/site-annotation.ts`의 `decimalHalfUp`이 지수 표기를 풀도록 고쳤다(아래 "알려진 한계").
- Fixture: `backend/tests/fixtures/ligand/`(표시된 합성: 4-methoxyacetanilide 부모 두 판(수소 명시·무수소), 입체 부모, block SDF·SMILES, 반응 규칙, PAINS 패널, 손 계산 기대값 `expected.json`, `SYNTHETIC-PROVENANCE.md`).
- 테스트: 백엔드 `test_ligand_inputs.py`, `test_ligand_site_filters.py`, `test_ligand_worker.py`, `test_ligand_inspection.py`, `test_ligand_enumeration.py`, `test_ligand_jobs.py`, `test_ligand_api.py`, `test_ligand_reports.py`(+ `ligand_job_fixture.py`). 프런트 `tests/ligand.test.cjs`, `workspace-tabs`·`report-library`·`site-annotation` 테스트 수정. 스크립트 `test_m17_offscreen_acceptance.py`.
- QA 도구: `frontend/tests/offscreen/ligand-flow.cjs`(`test:offscreen:ligand`, 모드 `main`·`unavailable`), `scripts/m17_offscreen_acceptance.py`(단계 `ligand-main`·`ligand-unavailable`).

## 사용자 결정 (2026-10-01, 명세 확정 때)
근거는 결정 0025. 모든 질문에서 추천안을 골랐다.
- 고정 교체 + 직접 쓴 반응 규칙 둘 다, 번호 붙은 2D 그림 + 원자 표 체크(그림 클릭 없음), block은 SDF와 SMILES 목록 둘 다.
- 부위는 나머지와 단일 결합 하나로만 이어진 것(링커 제외), 반응물 2개.
- 후보는 모두 보관하고 필터별 통과·실패만 표시(기본 범위 없음), 필터는 화면·보고서에서 저장값에 적용.
- 점검·생성 각각 작업·예산 1단위(기존 작업 경로, 승인·예산). 부모를 올릴 때마다 점검 1단위, 규칙을 고치려면 다시 점검(알려진 비용).
- 상한 block 1,000·후보 2,000·입력 10 MiB, 허용 원소 H C N O S P F Cl Br I, 수소·양성자화 그대로, 후보는 SMILES만.
- 입체는 부모 유지·새 중심 미지정, 표시 원자 `*` 정확히 1개는 고정 교체에만.
- 독립 명세 감사에서 나온 열린 점도 추천안으로: 후보 집합은 점검 handle 참조, 같은 입력은 같은 handle, 상한 도달만 부분 저장, 보고서는 요약 증거만, 원자 번호는 SDF 순번, block 이름 없으면 순번.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인: RDKit 기능, 크기 한도, 합성 fixture, 손 계산 oracle | `24d4eab` |
| T2 서버 순수 모듈: block 가져오기, 부위 검사, 필터 | `3613bef` |
| T3a 격리된 RDKit 작업 모듈(점검·생성) | `3cc825b` |
| T3b 작업 경로, 결과 객체, 서버 검증 | `1c63c44` |
| T4 읽기 API, 부위 미리보기, capability | `f754d06` |
| T5 `ligand_candidates` 보고서 | `e041741` |
| T6 프런트 API·타입·순수 로직 | `78753d5` |
| T7 리간드 탭 화면 | `91d3da3` |
| T8 오프스크린 흐름·M17 수락 실행기(M14 실행기 사례 문구·`tabs-flow.cjs` 최소 수정 포함) | `6db5648` |
| T9 독립 코드 검토 수정 = 고정 소스 | `e6ab4f9` |
| T10 게이트·수락·회귀 증거 | `a81f50a` |
| 완료 기록·결정 0025·프로젝트 문서·Stop 훅 목록 | 이 기록과 같은 커밋 |

## 착수 확인 (`preflight.txt`, 기준 `fb5f108`)
- 작업 환경 RDKit 2026.03.6에서 `rdChemReactions`, `FilterCatalog` PAINS A·B·C(16·55·409항목), `rdMolDraw2D` SVG가 동작한다. SMILES `*`, SDF `*`, SDF `R#`(M RGP 있음·없음)는 모두 원자번호 0으로 읽힌다(`R#` + RGP는 `[1*]`로 보임).
- 원자 번호는 `MolFromMolBlock(removeHs=False)` 뒤 원자마다 `sdf_serial` 속성을 넣고 `RemoveHs`해야 남는다. 그림 번호는 `atomNote`에 SDF 번호를 넣는다(`addAtomIndices`는 내부 인덱스라 틀림).
- 이벤트·객체 크기 한도는 코드에 없다. 후보 2,000행 실측 0.77 MiB(작은 코어)–3.24 MiB(191 중원자 코어). 작업 입력 스테이징은 일반 한도 4,000,000 B에 걸리므로 이 프로토콜 전용 한도가 필요했다(T3에서 48 MiB).
- SVG 크기: 기본(FreeType) 출력은 중원자 약 120개부터, `noFreetype` 출력도 약 230개부터 256 KiB를 넘는다 → 제품은 `noFreetype`을 쓰고, 그보다 큰 부모는 점검 `resource_exceeded`(명세대로).
- 손 계산 oracle(분자량 = 원자량 합, HBD/HBA = Lipinski NH+OH / N+O, TPSA = Ertl 조각 합, 회전 결합 Strict·NonStrict 손 적용, 산출물 SMILES = 코어 문자열 + 치환기 문자열 조립)과 RDKit 프로토타입 경로 교차 확인 83항목 전부 일치. 두 라이브러리·고정+규칙 합집합 고유 후보 10개.
- 구현이 정할 점 4개(Lipinski 함수, 회전 결합 Strict, 이름 순번 규칙, `outside_site` 단위)는 T2·T3에서 정했다: `CalcNumLipinskiHBD/HBA`, `CalcNumRotatableBonds` 기본(Strict, 정의 이름을 `property_methods`에 기록), 건너뛴 줄을 세지 않는 레코드 순번(T9에서 라이브러리를 이어 세도록 고침), RDKit 반응물 매치 하나 = (규칙, block, 매치) 한 건.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 명세 검토 2회: 의도 완전성 감사 1회 + 명세·계획·인계 세 문서 검토 1회. 지적은 문서에 반영했다.
- 독립 코드 검토(고정 전): 막는 지적 3건과 권고 다수. `e6ab4f9`에서 고친 것: 작업 시작·queued 이탈 때 승인 안내 지움, `decimalHalfUp`의 지수 표기 풀기, 보고서 위조 테스트가 함수 범위 run 복사본을 씀, 이름 없는 block을 가져온 순서대로 라이브러리를 이어 번호 붙임, 생성 작업 취소·시간 초과 테스트 추가(후보 집합 저장 없음), 행 읽기 쿼리는 필터 경계를 입력 문자열 그대로 보내고 보고서 본문은 숫자를 유지. 고치지 않은 권고는 아래 "알려진 한계"와 `docs/tracking/findings.md`에 적었다.
- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 고정 뒤): **approve**. 권고 4개는 아래처럼 처리했다.

| 권고 | 처리 |
|---|---|
| 생성 작업의 승인 UI가 수락에서 관찰되지 않음 | 기록: 비싼 계산 승인은 run 단위라 run의 첫 비싼 계산인 점검에서만 나타난다(L-inspect-job). 생성(L-enumerate-job)은 같은 run이라 승인 없이 시작된다(제품 규칙대로) |
| `docs/standards.md` 게이트 목록 갱신 | 이 기록 커밋: `docs/standards.md`·`docs/operations.md`·`scripts/AGENTS.md`에 `scripts/test_m17_offscreen_acceptance.py`와 `node --check frontend/tests/offscreen/ligand-flow.cjs` |
| M14 사례 수정 이유를 기록할 것 | 아래 "기존 검사 스크립트" |
| 일부 단계의 page PNG와 paint PNG가 같음 | 증거 검토자 판단으로 문제 아님. 기록만 |

## 게이트 (고정 `e6ab4f9`, `gate.txt`, 2026-10-01 10:18:33–10:35:43 UTC)
시작 때 작업 트리 깨끗함, 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 끝난 뒤 작업 트리 깨끗함, HEAD 그대로.

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 1206 passed, 0 skipped(1016초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 10개 파일(`test_m17_offscreen_acceptance.py` 포함) | exit 0, 167 passed |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow`·`ligand-flow` | exit 0 ×6 |
| `npm --prefix frontend run test:events` | exit 0, 224 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `e6ab4f9`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m17_offscreen_acceptance.py --root runs/m17-acceptance-20261001 --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/final --out docs/qa/m17-ligand-20261001/acceptance`
- 빌드 `sqA-QDPAIvtGu2INokvMg`(gitHead `e6ab4f9`, 소스 도장 일치). `verdict: pass`, `acceptance: true`, 사례 21개(ligand-main 18 + ligand-unavailable 2 + S-no-egress), 두 단계 모두 통과. 비-loopback 요청 0건, 제공자 호출 0회, 남은 프로세스·포트 없음. 작업 환경 있음, 주 백엔드 capability 사용 가능, 환경 없는 layout 백엔드 `worker_missing`.
- 관찰 요약: 구조 분석 탭에서 새 run + 1MQ4 → 리간드 탭(전역 run, capability 줄) → 파일 선택으로 수소 명시 부모 SDF·block SDF·block SMILES와 규칙 6개 → 가져오기 → 점검 시작 → 비싼 계산 승인 → 실제 `rdkit_inspect_v1`(1단위) → 점검 객체를 손으로 고름(자동 선택 없음) → 번호 붙은 그림이 저장 SVG와 같은 `<img>` data URI(인라인 SVG 없음) → 원자 표 = 수소 명시판 중원자 SDF 번호(수소 번호 건너뜀)와 원소·이웃이 T1 oracle과 같음 → 규칙 `user_1`–`3` valid, `user_4` `reactant_count`, `user_5` `reaction_parse_failed`, `user_6` `duplicate_rule`, 생성에 고를 수 없음 → 부위 19만 `crossing_bond_count`(시작 비활성), 19+20은 교차 결합 14–19 하나·부위 수소 21–23 → 생성(고정 + `user_1`–`3`, 1단위) → 후보 10개 SMILES가 손 oracle과 같고 id = `c_` + SHA-256 앞 16, 중복 origin·거부 개수가 손 추적과 같음, 한계 5문장 → 필터 경계(중원자 12–14 포함, 분자량 max = 저장 경계값), 잘못된 입력은 읽기 없이 거절, PAINS 제외 → 통과만 보기(전체·필터로 숨긴 수 표시) → 분자량 내림차순 정렬 → 표시된 생성 사슬 목록으로 후보 62개: 페이지 50 + 12, 이전·다음, id 겹침 없음 → 보고서 만들기(필터 기록) → 지식 탭 목록 "리간드 후보 보고서", 다운로드 바이트 동일 → 고정 끄고 `user_3`(부위 밖)만: 후보 0 = 빈 결과(실패 아님), `outside_site` 개수 → 구조 분석 탭은 숨긴 채 유지(같은 Mol* 세션·소스·세대), 전역 예산이 백엔드와 같음 → run 전환 뒤 run A의 늦은 점검 목록 응답 버림. `ligand-unavailable`: run 없음은 이유만, 작업 환경 없는 백엔드는 `worker_missing` 이유만(숫자·컨트롤·리간드 요청 없음).
- run 전환 늦은 응답 사례는 패널의 요청 취소(abort) 층만 관찰했다. 순번(stamp) 층은 `tests/ligand.test.cjs` 단위 테스트로만 확인했다.

### 회귀 (고정 `e6ab4f9`, 같은 빌드 `sqA-QDPAIvtGu2INokvMg`)
- M16: `scripts/m16_offscreen_acceptance.py --root runs/m17-m16-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/m17-regression --kbase <home>/Projects/kbase_kinase --out docs/qa/m17-ligand-20261001/m16-regression` → `acceptance: true`, 19/19, 단계 3개.
- M15: `scripts/m15_offscreen_acceptance.py --root runs/m17-m15-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m17-regression --kbase <home>/Projects/kbase_kinase --out docs/qa/m17-ligand-20261001/m15-regression` → `acceptance: true`, 14/14, 단계 5개.
- M14: `scripts/m14_offscreen_acceptance.py --root runs/m17-m14-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/m17-regression --out docs/qa/m17-ligand-20261001/m14-regression` → `acceptance: true`, 15/15.
- M8–M13: `scripts/m13_offscreen_acceptance.py --root runs/m17-m13-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/m17-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m17-ligand-20261001/m13-regression` → `acceptance: true`, 필수 단계 17개·사례 28개, M11 수락 실행기 17/17, M12 수락 실행기 31단계 통과. 하위 실행기 행의 `providerCallsZero`는 null(M15·M16 회귀와 같은 형식, 외부 요청 0건).
- 넷 다 외부 요청 0건, 남은 프로세스 없음. 큰 텍스트 증거는 결정 0020대로 옮겼다.

### 기존 검사 스크립트
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다.
- M14 수락 사례 `T-unavailable`: 리간드 설계·탐색 탭이 이제 "사용할 수 없음" 안내 대신 M17 후보 화면을 보여 준다. `frontend/tests/offscreen/tabs-flow.cjs`는 리간드 탭에서 안내 대신 화면(`data-testid="ligand-panel"`)이 보이고 쓰기 요청이 없는지 보도록(화면이 자기 목록을 GET으로 읽으므로 "새 요청 없음" 검사는 리간드 탭에서만 뺐다), `scripts/m14_offscreen_acceptance.py`는 사례 설명 문자열만 바꿨다(판정 논리 불변, `6db5648`). 단백질 공학 탭 검사는 그대로다.
- `frontend/tests/workspace-tabs.test.cjs`(리간드 탭 안내 없음), `frontend/tests/report-library.test.cjs`(보고서 종류 이름 1줄), `frontend/tests/site-annotation.test.cjs`(`decimalHalfUp` 지수 표기 사례).
- `.codex/hooks/stop.py` 세 번째 pytest 그룹과 `scripts/test_codex_hooks.py` 기대 목록에 `scripts/test_m17_offscreen_acceptance.py`(이 기록 커밋. 게이트 명령에는 T10부터 들어 있었다).
- M13·M15·M16 수락 실행기와 그 밖의 흐름 스크립트는 고치지 않고 통과했다. 과거 검토 파일·해시는 건드리지 않았다.

## 알려진 한계
- 규칙 SMARTS 오류는 점검 작업(예산 1단위)을 돌려야 드러나고, 규칙을 고치려면 다시 점검해야 한다(서버는 RDKit 없이 SMARTS를 검사할 수 없다).
- 코어가 끊기는 규칙 매치도 첫째 템플릿이 부위 밖 원자를 맞춘 것이므로 `outside_site`로 센다.
- 이름 없는 block의 `block_<n>`은 가져온 순서의 모든 라이브러리를 이은 연속 레코드 순번이다. 거부 레코드 목록의 `ordinal`은 그 라이브러리 안 순번이라 둘이 다를 수 있다.
- 미리보기 응답의 `site_check.retained_parent_atoms`는 코어 수소 번호를 포함하고, 후보 집합의 같은 이름 필드는 코어 중원자만이다. 화면은 후보 집합 쪽을 쓴다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`는 새 두 종류를 리간드 검증 없이 그대로 노출한다(M12 포켓과 같은 관례). 검증된 읽기는 `/ligand/*`다.
- 리간드 탭에서 작업을 끝내도 전역 예산 줄은 탭 전환 때만 다시 읽는다(M14 규칙, 새 폴링 없음). 패널 안 예산 표시는 작업이 끝나면 다시 읽는다.
- 2D SVG 상한 256 KiB 때문에 중원자 약 230개를 넘는 부모는 점검이 `resource_exceeded`(`svg_limit`)로 실패한다(부모 한도 256보다 낮음).
- 서버 필터 파서는 경계 문자열을 float로 바꾸므로 `1.0000000000000001`은 서버에서 1.0이 된다(화면은 입력 문자열 그대로 보낸다).
- 화면·보고서 문구는 "활성"이 보고서 금지어라 "적용한 필터"를 쓴다.
- `decimalHalfUp`(M16과 공용)이 지수 표기(1e-7, 1e21)를 Python `Decimal(str(v))`처럼 풀도록 바뀌었다. M16 사용처는 지수 표기 입력에서만 결과가 달라진다(M16 회귀 통과).
- 생성 작업의 승인 UI는 run 단위 승인 규칙 때문에 run의 첫 비싼 계산(보통 점검)에서만 나타난다.

## 대체한 과거 검증 범위
- M17은 공유 소스를 바꿨다: 백엔드 `api/app.py`(가져오기 종류, capability, 작업 결과 artifacts, 보고서 분기·목록, 리간드 읽기 라우트), `jobs/queue.py`, `jobs/guardian.py`, `tools/energetic.py`, `chemical_inputs.py`, `config/tools.yaml`. 프런트 `app/page.tsx`, `WorkspaceTabs.tsx`, `lib/workspace-tabs.ts`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, `lib/site-annotation.ts`, 스타일.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(1206개, skip 0)와 M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `e6ab4f9`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합(방법은 사용자에게 묻는다). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): 규칙 SMARTS 오류를 점검 뒤에야 알 수 있음, 후보에 3D·점수 없음(M18), 부모 2D 그림 크기 때문에 중원자 약 230개 초과 부모를 점검할 수 없음, 미리보기와 후보 집합의 `retained_parent_atoms` 뜻이 다름, 일반 객체 읽기가 리간드 검증을 거치지 않음, 리간드 탭 작업 뒤 전역 예산 줄 지연, run 전환 늦은 응답의 stamp 층 미관찰, 필터 경계의 float 변환.
