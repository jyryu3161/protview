# M27 kinase 전례·문헌 연결 완료 기록

- 판정: **완료** (2026-10-10 UTC, 기록 2026-10-11). main 병합 `<병합 해시>`.
- 브랜치: `dryforge/m27-kinase-precedents` (`phase/m27-kinase-precedents` = main `6ac3a59`에서 분기). M26은 시작 전에 main에 병합되어 있었다(`8b95cc9`, 기록 `6ac3a59`).
- 고정 소스: `b414728`(T10 Stop 훅 그룹 두 번째 분할). 첫 고정 후보 `7e33951`(M27 백엔드 테스트의 이름 있는 그룹 하나)에서 나머지 그룹이 다른 그룹과 동시에 476초(제한 480초)였으므로 무거운 두 파일을 그룹 하나로 더 나눴다(`7e33951` → `b414728`은 `.codex/hooks/stop.py`·`scripts/test_codex_hooks.py`만 바꿈). 고정 뒤 제품 소스(`backend/mw`·`frontend/src`·`frontend/app`·`design`·`config`·`scripts`·`.codex`) 변경은 없다(`git diff b414728 fdad79c -- backend frontend scripts config design .codex`가 빔). 고정 뒤 커밋은 `docs/qa/m27-precedents-20261010/`만 바꾼 게이트 기록(`a81e0ee`), 수락 증거(`e595ca4`), 회귀 증거(`d9d5df7`), 게이트 기록 보충(`8110cc4`·`fdad79c`)과 이 기록 문서들뿐이다.
- 결정: 0035(사용자 결정 2026-10-10, `docs/tracking/decisions/0035-m27-kinase-precedents.md`).
- 수락 증거: `docs/qa/m27-precedents-20261010/`(`preflight.md` 착수 확인, `network-ledger.txt` 요청 장부, `kbase_check.py` 착수 확인 시제품(표준 라이브러리 + YAML 읽기, `mw`·네트워크 없음, 실제 문구 없음), `gate.txt` 게이트, `acceptance/` 새 기능 수락, `regression/m26/`·`regression/m25/`·`regression/m24-regression/`…`m13-regression/` 회귀, `regression-chain.txt` 사슬 기록). 256 KiB를 넘는 텍스트 증거 54개(`m13-regression` 52개, `m14-regression` 1개, `m15-regression` 1개, 합계 약 334 MB)는 결정 0020에 따라 Git 제외 `frontend/tests/offscreen/artifacts/m27-final/export-full/<폴더>/`로 옮겼다(해시는 각 증거 폴더의 `ARCHIVED-EVIDENCE.sha256`, 이 기록을 쓸 때 `shasum -a 256 -c` 54개 모두 OK). 수락 QA의 화면 캡처·paint 프레임·보고서 내려받기는 Git 제외 `frontend/tests/offscreen/artifacts/m27-acceptance/20261010-final2/`에 있고 커밋 증거에는 경로·크기·SHA-256만 있다(`acceptance/binary-artifacts.json`).
- 외부 요청: 사용자가 허용한 RCSB 공개 구조 mmCIF 2건뿐이다(T1, `https://files.rcsb.org/download/1M17.cif` 307,709 B·`1FIN.cif` 999,052 B, 각 1회·200·재시도 없음, `network-ledger.txt`). 제품 코드·가져오기 명령·테스트·오프스크린 QA는 0건이다(수락·회귀의 브라우저 비-loopback 요청 0, 제공자 호출 0, 가져오기 두 번의 소켓 시도 0/0). 실제 JEV·OpenRouter 호출은 없고 키가 필요 없는 단계였다.
- 커밋 증거의 실제 kbase 문구: 0개(수락 실행기가 문자열 7,479개를 검사). 실제 kbase 자료로 만든 증거(인용문·관찰 문장·서지 제목이 들어갈 수 있는 것)는 Git 제외 폴더에만 있다.

## 범위
구조 체인의 표적(UniProt accession)과 같은 표적에 대해 `kbase_kinase`가 기록해 둔 전례(Design Move: 논문 속 화합물 변형 한 건과 그 논문이 보고한 측정 변화, 인용문, 논문 위치)를 출처·검사 상태와 함께 지식·보고서 탭에서 보여 주고 보고서에 출처 목록으로 남긴다. 전례는 "kbase_kinase가 논문에서 기계로 추출한 미검수 기록"이며 ProtView는 전례를 해석·평가·추천하지 않고 내 구조·변이·리간드·후보와 맞추지 않는다. 범위 밖: 다른 키나아제의 전례를 가설로 보이는 것(같은 KLIFS 위치·anchor·계열 전이), 구조에서 서술자를 계산해 전례를 거르는 것, 번호 대응 없이 accession만으로 조회하는 것, Mol* 뷰어 표시·저장된 보기 변경, M24·M25 전송에 전례를 보내는 것, M13 흐름 연동, M17·M19 행과의 자동 연결(전례 891건 모두 SMILES가 없음), 논문 원문 대조, 문헌 검색 색인, kbase `structures`·`figures`·`tactics`·`interactions`·`mutations`·`CONTRACT.md`·`AGENTS.md`와 kbase 코드의 사용, 순위·추천·유망도·성공률·집계·배수·차이·평균, 새 한도 증액 경로.

## 결과물 (작업별)

| 작업 | 내용 | 커밋 |
|---|---|---|
| T1 착수 확인 | 실제 kbase `dist/` 형식·핀·레코드 해시, 비용·결과 크기, RCSB 구조 2개 내려받기와 M15 번호 대응 실제 실행, M15 kinase ⊂ kbase 참조와 `not_in_kbase_references` 도달 가능성, 카디널리티 결합 지도, 회귀 실행기 격리 결정, 원자적 설치·고정·캐시 패턴, 호출 키 해시 파일·골든 기준선 | `18becbd` |
| T2 상수·고정·매칭 | `precedent_constants.py`(닫힌 집합·핀·어휘·상한·고정 문장·정규 JSON·레코드 형식 검사, 표준 라이브러리만)·`precedent_snapshots.py`(활성 세트 고정·파일 해시 검증)·`kinase_precedents.py`(세트 색인 캐시·체인/표적 판정·전례 사본·무결성·결과·`validated_result`), 독립 oracle(`fixtures/precedent/t2/independent_match.py`) | `b660490`(병합 `46639a8`) |
| T3 가져오기 명령 | `scripts/import_precedent_snapshots.py`(`run_import`, 확인 화면, 검증 순서, 읽기 전용 git, 원자적 설치)와 시험(합성 kbase 흉내 폴더) | `fff7e7c`(병합 `1f1f0dd`) |
| T4 도구·읽기 | `tools/kinase_precedents.py`의 `link_kinase_precedents`(사전 검사 412 → 입장 422 다섯, 상한 429), `kinase_precedents_reads.py`와 읽기 API 셋, `methods.kinase_precedents`, 명세 검토 지적 반영(`limit`·`offset` 자릿수 상한) | `c0a0d22`·`528a3d9`(병합 `d3bbb40`) |
| T5 보고서 | `kinase_precedents_reports.py`(계산값·참조값 분리, 고정 문장, 출처 표, 금지어 검사), 보고서 종류 등록, 여섯 서버 모듈의 AST·문자열 검사 `test_kinase_precedents_ast.py` | `a01472c`(병합 `7c7a59f`) |
| T6 프런트 순수 로직 | `lib/kinase-precedents.ts`(새), `lib/api.ts`·`contracts.ts`·`report-library.ts` | `44e149c` |
| T7 화면 | `KinasePrecedentsPanel.tsx`(새), `WorkspaceTabs.tsx`·`app/page.tsx` 슬롯, `design/components.css`와 생성 복사본(`npm run tokens`) | `eb33d9a`, `1981edb` |
| T8 오프스크린·수락 실행기 | 하네스 `kinase-precedents-flow.cjs`, `scripts/m27_offscreen_acceptance.py`·단위 테스트, 합성 QA 세트 빌더 `fixtures/precedent/t8/build_qa_set.py`, 예비 수락 증거 | `37a00ef`, `a17c5db` |
| T9 독립 코드 검토 수정 | 백엔드·가져오기: `move_id` 숫자 부분 변환 실패 거절, 가져오기 git 강화(T9a). 프런트·하네스: "그 밖의 kbase 필드" 블록, 패널 문자열 금지어 시험, 빈 결과 문구, 실행기 유출 검사 강화 | `cdb5411`(병합 `3e8ec12`), `a0cc1b8` |
| T10 고정·게이트·QA·회귀 | Stop 훅 이름 있는 그룹 둘(`7e33951` → `b414728` = 고정 소스), 게이트 기록, 최종 수락 증거, 회귀 증거 | `7e33951`, `b414728`, `a81e0ee`, `e595ca4`, `d9d5df7`, `8110cc4` |
| T11 독립 증거 검토 | 고정 뒤 증거 검토, 지적(게이트 기록의 회귀 실행 HEAD 한 줄, 사슬 단계 기록) 반영 | `fdad79c` |
| T12 기록 | 기술 문서(T12a), 이 기록·상태 문서·모듈 안내(T12b) | 이 기록의 커밋들 |

- 서버 모듈 여섯: `backend/mw/precedent_constants.py`(상수·닫힌 집합·고정 문장·순수 형식 검사, 표준 라이브러리만이고 `mw`를 import하지 않음), `precedent_snapshots.py`(세트 고정), `kinase_precedents.py`(색인·체인/표적 판정·결과·`validated_result`), `kinase_precedents_reads.py`(읽기 필터·정렬·facets), `kinase_precedents_reports.py`(보고서), `backend/mw/tools/kinase_precedents.py`(도구·사전 검사 훅). 등록: `config/tools.yaml`, `workspace.py`, `api/app.py`.
- 가져오기: `scripts/import_precedent_snapshots.py`(`run_import(kbase_dir, dest, *, yes=False, now=None, input_fn=None)`, 인자 `--from`·`--dest`·`--yes`). 네트워크를 쓰지 않는다: 로컬 파일 읽기와 읽기 전용 `git -C <kbase> -c core.fsmonitor=false -c protocol.allow=never`(`rev-parse HEAD`, `log -1 --format=%H%n%cI -- dist`, `status --porcelain --untracked-files=normal -- dist ref/pubmed`, 각 60초) 하위 프로세스만 쓰고, `precedent_constants.py`를 파일 경로로만 불러 쓴다.
- API: `GET /precedent_reference/status`, `GET /runs/{rid}/kinase_precedents`, `GET /runs/{rid}/kinase_precedents/{handle}`(서버 쪽 필터·검색·정렬·쪽 나눔), 도구 호출은 기존 `POST /runs/{rid}/commands`, `/capabilities`의 `methods.kinase_precedents`(`methods.reaction_knowledge`와 같은 다섯 키), 방법 보고서 `analysis_type: "kinase_precedents"`("키나아제 전례 보고서", 렌더 `kinase_precedents_markdown@1`).
- 화면: 지식·보고서 탭 "키나아제 전례" 영역(`KinasePrecedentsPanel.tsx`, 순수 판단 `lib/kinase-precedents.ts`). 지식 탭 영역 순서는 번호 대응 → 효소 반응 지식 → **키나아제 전례** → JEV 판정 → 보고서 목록.
- 테스트: 백엔드 새 파일 일곱 557개(`test_precedent_constants` 151, `test_precedent_snapshots` 35, `test_kinase_precedents` 142, `test_kinase_precedents_tool` 63, `test_kinase_precedents_api` 109, `test_kinase_precedents_reports` 31, `test_kinase_precedents_ast` 26), 스크립트 `test_import_precedent_snapshots.py` 97개·`test_m27_offscreen_acceptance.py` 55개(Stop 훅 `SCRIPT_TESTS`에 추가), 프런트 `tests/kinase-precedents.test.cjs` 38개(`test:events` 전체 534개). Fixture: `backend/tests/fixtures/precedent/`(작업별 하위 폴더 `t2`·`t3`·`t8`과 각자의 `SYNTHETIC-PROVENANCE-<작업>.md`, 실제 kbase 레코드·서지 조각 없음), 세트 만들기 도우미 `tests/precedent_fixture.py`(가져오기 명령과 같은 상수 모듈 함수로 세트 폴더를 씀), 공개 구조 `public_1m17.cif`·`public_1fin.cif`(+ `.provenance.json`, RCSB CC0).

## 사용자 결정 (2026-10-10)
근거는 결정 0035. 사용자는 모든 질문에서 추천안을 골랐다(자유 입력·메모 없음): ① kbase 접근 = 로컬 복사본 + 가져오기 명령 ② 연결 기준 = 같은 표적만(다른 키나아제 전이 가설·자동 서술자 제외) ③ 인용 검증 = ProtView 무결성 확인 + kbase 기계 검사 표시(원문 대조 없음) ④ 문헌 색인 만들지 않음 ⑤ 논문 서지(`ref/pubmed`)도 가져옴 ⑥ `moves_flagged`는 가져오되 기본 숨김(호출 때 포함 선택) ⑦ 보고서 = 요약 + 출처 목록(인용문·측정 변화 값 제외) ⑧ 실데이터 QA용 RCSB 구조 2개 ⑨ 범위 밖 전부(뷰어·JEV·M13·accession 단독 조회·전이 가설·M17/M19 연결) ⑩ 저장 = 두 경로만 뺀 사본 + 원본 해시 ⑪ 표적 미해석 전례는 연결하지 않고 안내 ⑫ 체인 자격 = accession 하나 + mapped 잔기 1개 이상 ⑬ 표시 = kbase 필드 전부 + 산출 근거 ⑭ PDB 언급 일치 표시 안 함 ⑮ 이용 조건 문구 표시 + 커밋 증거엔 해시만 ⑯ kbase 버전 세 값 엄격 고정 ⑰ 개수는 변이 표기별 분리 + 미포함 안내. 사용자에게 묻지 않고 조율 세션이 원칙("하지 않은 검사를 한 것처럼 보이지 않는다"·"선택하지 않고 보여 준다"·fail-closed)과 M15·M26 선례에서 정한 세부(같은 accession 체인의 표적 하나·체인 행 각자, 측정 변화(effects) 안 다른 표적 이름은 매칭하지 않음, 변이 표기 원문(UP3), 정렬 키에서 효과·방향·크기 제외, 서지 없음은 오류 아님, `quotes_within_limit` 거짓이어도 제외하지 않음, 호출 때 레코드 해시 불일치는 412, 필터 선택지는 결과 `facets`에서, `dirty`는 기록만, 1 MiB 초과는 자르지 않고 거절, 파일 이름은 "통과/실패"가 아닌 이름 그대로)는 결정 0035에 적었다.

## 착수 확인 (`preflight.md`, 기준 `6ac3a59`)
- 실제 kbase(`../kbase_kinase` HEAD `77354f9`, `dist/`를 마지막으로 바꾼 커밋 `43a935e` 2026-09-21T00:05:28+09:00, `kb_version` `kbv1:ae11f41d19e5bef9`, `dirty` 아님): `dist/manifest.json`의 세 버전 값이 `KBASE_PINS`와 문자 그대로 같고, `moves.jsonl` 891행·`moves_flagged.jsonl` 885행·`references.jsonl` 555행의 바이트·SHA-256·줄 수가 매니페스트와 같으며, 레코드 해시 재계산 891·885·555 모두 일치, `references_without_hash` 0, 형식 위반 0(21개 최상위 키, `review_status` 모두 `unreviewed`, 어휘 20·12·18 순서까지 같음). 서지 `ref/pubmed` 최신 스냅샷(2026-09-18, 252행, `public-domain-ncbi`)이 전례 PMID 167개를 모두 덮는다.
- 비용: 캐시 없이 세 파일 + 서지 해석·검사·해시·색인 약 0.32초·+105 MB → 세트 단위 캐시(M26 방식). 결과 크기: 단일 표적 최대는 BTK `Q06187` `moves_flagged` 포함 855,798 B(1 MiB 안), 68개 표적 모두 단독으로 1 MiB 안.
- 실구조: 1MQ4 A → `O14965`(mapped 260/261), 1M17 A → `P00533`(311/312), 1FIN A·C → 둘 다 `P24941`(각 298/298). 1FIN B·D(cyclin A)를 번호 대응 요청에 넣으면 호출 전체가 422 `no_usable_method`. 연결된 accession의 kbase 전례 수가 기대와 같다(EGFR 76 + 66, CDK2 32 + 24, Aurora A 0 + 0).
- 결합 지도: 도구·capability·보고서 종류·읽기 라우트·지식 탭 영역이 닿는 실제 파일 목록을 grep으로 확정했다. 지식 탭 하네스는 `tabs-flow.cjs`가 지식 탭의 `section.mw-unavailable` 0개를 단언하므로 새 영역은 그 요소를 쓰지 않는다.
- 회귀 격리: 옛 실행기가 `MW_PRECEDENT_REFERENCE_DIR`를 넘기지 않으므로 실행기를 고치지 않고 회귀 동안 `.deps/precedent_reference`(와 `.deps/reaction_reference`)를 없는 채로 둔다(M26 선례).
- 기준선: 호출 키 해시 파일 27개의 git blob과 골든 셋(`golden_science_m24.json`·`golden_egress_events.json` `--check`, `golden_call_keys.json` 재기록 `cmp`) 통과.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 의도 감사(작성 전): 표적 해석 경계·체인 자격·측정 변화(effects) 표시 필드와 산출 출처·검사 세부와 "duplicate" 뜻·이용 조건·PDB 언급 수·kbase 버전 고정·변이별 개수를 사용자에게 물어 확정했다(결정 0035).
- 명세 적합성 검토 2건(T2·T4): 각각 pass, 지적 1건 수정(T4는 `528a3d9`).
- 독립 코드 검토 2건(T9, 고정 전): 백엔드·가져오기·보고서 쪽 **막는 지적 하나**(`move_id`의 숫자 부분이 4,300자리를 넘으면 가져오기는 통과하고 서버의 정렬 키 `int()`가 파이썬 자릿수 상한에 걸려 `/capabilities`·`/precedent_reference/status`가 500) → `cdb5411`에서 `validate_move`가 숫자 부분 변환 실패를 형식 위반으로 거절하게 고침(가져오기 거절, 폴더에 직접 넣은 세트는 `snapshot_invalid`), 권고(가져오기 git에 `-c core.fsmonitor=false -c protocol.allow=never`) 반영, 나머지 권고는 보류해 아래 N13에 적음. 프런트·하네스 쪽은 막는 지적 없이 승인, 권고를 `a0cc1b8`에서 반영(상세의 "그 밖의 kbase 필드" 접힘 블록, 패널 TSX 문자열 금지어 시험, PDB ID 없음 이유, 연결된 표적이 없을 때의 빈 결과 문구, 실행기 실제 문구 유출 검사 강화).
- 독립 증거 검토(T11, 고정 뒤): 게이트 기록의 회귀 실행 HEAD 한 줄(`a81e0ee` → `e595ca4` = `b414728` + 수락 증거)을 정정하고 M25 실행기의 사슬 단계 결과를 `regression-chain.txt`에 적었다(`fdad79c`).

## 게이트 (고정 `b414728`, 2026-10-10, `gate.txt`)
| 명령 | 결과 |
|---|---|
| 백엔드·스크립트 pytest 열여덟 그룹(Stop 훅 `CHECKS[1:]`, 같은 인자로 한꺼번에 시작, 그룹별 제한 없이) | 모두 exit 0, 합계 **6,037 passed**, 동시 실행 전체 357.5초(그룹 제한 480초). 그룹 16 = M27 백엔드 일곱 파일 557개(42.3초), 그룹 17 = `test_analysis_workflows.py` + `test_jev_loop_reports.py` 129개(231.6초), 나머지 그룹 = 나머지 백엔드 + 스크립트 3,577개(323.2초). 서열 GA SIGTERM 프로세스 시험(`test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`) 통과 |
| 둘째 분할 전(첫 고정 후보 `7e33951`, 열일곱 그룹) | 나머지 그룹 3,706개가 단독 423.9초, 모든 그룹과 동시 476초 → 그룹 17을 나눔 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0(`7e33951`, 훅 수정 뒤 `b414728`에서도 exit 0) |
| `scripts/test_codex_hooks.py`(`b414728`) | 25 passed(`CHECKS` 19 = ruff 1 + pytest 18) |
| `node --check frontend/tests/offscreen/*.cjs`(31개) | 실패 0 |
| `npm --prefix frontend run test:events` | 534 pass, 0 fail |
| `typecheck` → `build`(차례로) | exit 0 → exit 0 |
| 골든 `--check`: `golden_science_m24.py`·`prototype_golden_egress.py` | exit 0, exit 0 |
| `prototype_golden_call_keys.py` 재기록 | 커밋된 `golden_call_keys.json`과 `cmp` 동일 |
| 호출 키 해시 파일 | `git diff --name-only 6ac3a59 HEAD -- backend/mw`에 `docking_*`·`openmm_mutation_worker`·`mutation_model_*`·`mutation_candidates`·`ligand_ga_*`·`sequence_ga_*`·`docking_batch_*` 없음(`test_kinase_precedents_ast.py`가 27개 blob을 착수 기준선과 대조) |

`ruff`·`node --check`·`test:events`·`typecheck`·`build`·골든 셋은 `7e33951`에서 돌렸다. `b414728`은 `.codex/hooks/stop.py`·`scripts/test_codex_hooks.py`만 바꾼다.

## 가져오기 실검증과 재현 (수락 real 단계, `acceptance/README.md`·`summary.json`)
- 수락 실행기가 사용자 가져오기 명령 `scripts/import_precedent_snapshots.py --from <kbase> --dest <root>/real/precedent_reference --yes`를 소켓 연결·이름 조회를 막고 세는 자식 프로세스에서 두 번 돌렸다. 두 번 모두 exit 0, 소켓 시도 0/0.
- 세트: 첫째 `614f5ecd…04dd6a`(imported_at 2026-10-10T13:27:30Z), 둘째 `8ac7496b…8fbc`(13:27:32Z, 활성). 행 `dist/moves.jsonl` 891·`dist/moves_flagged.jsonl` 885·`dist/references.jsonl` 555·서지 252(`pubmed/2026-09-18/documents.jsonl`), `records_hash_verified` 891·885·555, `references_without_hash` 0, `dirty` false, `kbase.commit` `77354f9…`, `dist_commit` `43a935e…`.
- 재현: 두 세트의 파일 네 개 SHA-256이 모두 같다(`reproducible: true`). 세트 해시는 `imported_at` 때문에만 다르다. 기본 폴더 `.deps/precedent_reference`는 만들어지지 않았다(`defaultFolderUntouched`, 폴더 부재로 판정).
- 소요: 가져오기 약 0.45초(구현 중 스모크 측정, 증거 파일은 없다), 서버 쪽 해석·색인(캐시 없이) 약 0.32초·+105 MB(착수 확인, `preflight.md`).

## 수락 QA (`acceptance/`, `scripts/m27_offscreen_acceptance.py --stages fixture,real`, 2026-10-10)
- `verdict: pass`, `acceptance: true`, 사례 46개 모두 통과(fixture 28 = P 26 + S 2, real 18 = X 15 + S 3), 두 단계가 한 실행에서 모두 돌았다. 실제 Electron 오프스크린, 단계마다 격리 폴더(`MW_RUNS_DIR`·`MW_REFERENCE_DIR`(M15 활성 세트 `aa21ead9…3317`의 읽기 전용 복사본)·`MW_PRECEDENT_REFERENCE_DIR`·빈 `MW_REACTION_REFERENCE_DIR`), 브라우저 비-loopback 요청 0·제공자 호출 0, 남은 프로세스·리스너 없음, 커밋 증거의 실제 kbase 문구 0. 빌드 도장 `a81e0ee`(제품 소스는 `b414728`과 같음, 작업 트리 깨끗함).
- fixture 단계: 합성 표시 세트(`backend/tests/fixtures/precedent/t8/build_qa_set.py`, 지어낸 accession `P0QA01`–`P0QA04`·PMID·`MOVE-7xxx`)와 공개 1MQ4·합성 파생 번호 대응(d-two·d-fusion·d-big, 실제 M15 번호 대응의 mapped 행 accession만 바꾼 것)으로 세트 없음 → 세트 A → `active.json` 치움 → 파일 변조 → 세트 B를 차례로 바꾸며 관찰했다. 관찰한 것: 스냅샷 블록 세 상태(숫자·컨트롤 없는 `not_installed`·`snapshot_invalid`와 가져오기 명령), 요청 기본값(가장 최근 번호 대응 미리 고르기·제출 없음·체인 모두·토글 꺼짐), 체인 미리 상태, 입장 거절 다섯 이유 "한국어 (code)"(저장 없음), 체인 상태 셋, 체인 고르기, 표적 상태 셋(합성 세트에 없는 실제 accession `O14965`로 `not_in_kbase_references` 포함)과 UP2(`excluded_flagged`가 정수일 때, 0 포함), 표적 탭, `moves_flagged` 토글, 필터(파일·site/goal/tactic 축 안 OR·축 사이 AND·변이·글자 검색, 101자 검색 거절), 정렬(PMID 내림·서지 연도 오름, 정수 아닌 연도 끝), 쪽 나눔(30건 → 1–25·26–30), 상세(서지 있음/없음, 위치 전부, 인용 잘림·조합 표시, 교환 인용 null "—", 측정 변화 표의 `target_role`·`direction_basis`·`fold_change` null "—"와 이유, 구조 연결과 UP4, kbase 검사 열 개와 따로 둔 ProtView 무결성 확인(25단어 상한 거짓), 해시 안내), KP1–KP6·KT1·UP1–UP5 문자 그대로, 1 MiB 초과 429 `result_too_large`(크기 안내, 저장 없음), 보고서 만들기·내려받기(백엔드 바이트와 같음, 인용·관찰 문장 없음), 결과 목록, dry-run run, "이전 스냅샷 기준"·"사용 중 스냅샷 없음", 다른 탭 불변, 0·"없음" 단독 표시 없음, 금지 표현 없음.
- real 단계: 실제 kbase `dist/`를 위 가져오기로 격리 폴더에 설치하고 공개 1MQ4·1M17·1FIN(A·C만)의 번호 대응을 화면에서 만들어 관찰했다. 1MQ4 → `O14965` `none_in_included_files`(포함 `moves` 0, `moves_flagged` "—"(포함하지 않음), UP2의 N 0). 1M17 → `P00533` `precedents_found`, `moves` 76건·`excluded_flagged` 66건, 변이 표기 not_reported 53·L858R 15·T790M 4·WT 3·L834R 1, 토글을 켜면 76 + 66 = 142. 1FIN A·C → 한 표적 `P24941`에 체인 행 둘, 32건·미포함 24건(켜면 56). 스냅샷 블록은 kbase HEAD `77354f94b844`·dist 커밋 `43a935e4637d`와 날짜·`dirty` false·행 891/885/555·서지 252·UP5 396·미해석 이름 35. 크기 시험용 합성 변형(1FIN 번호 대응의 두 체인에 `P00533`·`Q06187`)은 `moves_flagged` 포함 1,605,026 B → 429 `result_too_large`, 끄면 737,133 B로 상한 안. 변이 L858R 필터(15건)·다음 쪽·상세 두 건(메모리에서만 비교, ID만 기록)·보고서(해시만)도 관찰했다.

### 관찰하지 못한 사례 (위조하지 않음)
- 늦은 응답(`P-late-response`): 순수 가드 시험(`frontend/tests/kinase-precedents.test.cjs`의 `precedentResponseCurrent`)이 덮는다. 호출 때 레코드 해시 불일치 412(`P-record-hash-412`)는 고정과 호출 사이에 세트가 바뀌어야 해 `backend/tests/test_kinase_precedents_tool.py`가 덮는다.
- real 단계의 연결 안 함 체인(`X-chain-states`): 공개 구조는 연결된 체인만 만들고(1FIN B·D는 M15가 거절) `no_mapped_residues`·`multiple_accessions`는 fixture 단계에서 관찰했다. `not_in_kbase_references`(`X-not-in-kbase`)는 허용된 내려받기 밖의 구조가 필요해 fixture 단계에서 관찰했다(아래 N1). 스냅샷 상태 변화(`X-snapshot-states`)는 합성 세트로 fixture 단계에서 관찰했다.

### 회귀 (`regression-chain.txt`, fixture 단계만·실호출 0)
- M26 실행기 `--stages fixture` 39/39(real 단계를 요청하지 않아 `acceptance` false), M25 실행기 `--phase fixture --regressions`: M25 fixture 57/57, M24(fixture) 26/26, M23 35/35, M22 25/25, M21 23/23, M20 24/24, M19 26/26, M18 24/24, M17 21/21, M16 19/19, M15 14/14, M14 15/15, M13 28사례(M11·M12 하위 실행기 포함), 사슬 `failedSteps=[]`, 모두 `acceptance: true`. 사슬 내내 `.deps/precedent_reference`와 `.deps/reaction_reference`는 없었다(시작 전·끝난 뒤 확인). 실행 HEAD는 `e595ca4`(소스는 `b414728`과 같고 `docs/qa`만 다름).
- M25 실행기는 자기 증거를 먼저 내보낸 뒤 사슬을 돌리므로 커밋된 `regression/m25/`에는 사슬 단계 결과가 없다. 사슬 단계(regression-m24 … m13, 각 exit 0과 시각)는 실행기 로그에서 `regression-chain.txt`에 옮겼다.

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님).
- 도구·capability 집합(이름 하나 추가): `test_api.py`(`/tools` 이름), `test_ligand_api.py`(`/capabilities` 방법), `test_reference_site_annotation.py`·`test_residue_numbering.py`(사전 검사가 있는 도구 집합).
- 프런트 `report-library.test.cjs`(새 보고서 종류 이름표 기대를 더함).
- Stop 훅: `.codex/hooks/stop.py`(`SCRIPT_TESTS` 두 파일, 이름 있는 그룹 둘), `scripts/test_codex_hooks.py`(`CHECKS` 17 → 19).
- 옛 실행기·하네스는 고치지 않았다(새 영역은 `section.mw-unavailable`을 쓰지 않고 testid 접두어 `kinase-precedents-`가 기존 선택자와 겹치지 않음). 골든은 다시 기록하지 않았다.

## 해석 메모 (명세가 말하지 않았거나 명세와 다른 곳에서 정한 해석)
각 메모는 무엇이 명세와 다르거나 명세가 말하지 않았나 / 어떻게 정했나 / 왜 괜찮나 순서다.
- N1 `not_in_kbase_references`의 도달 가능성. 명세 §10 ③과 인계는 "실데이터로 도달 불가, 합성으로만"이라 적었다. / 착수 확인 (d)에서 M15 UniProt `ok` kinase 541개는 모두 kbase 참조에 있지만, M15가 SIFTS만으로 행을 `mapped`로 만드는 체인 2개(`7Z87` A → `P78527`, `8H7G` A → `Q15393`)의 accession은 kbase 참조에 없음을 확인했다. 그 구조를 올리고 PDB ID를 주면 체인이 `linked`가 되고 표적 상태는 `not_in_kbase_references`가 되므로 **원리상 실데이터로 도달할 수 있다**. 그 두 구조는 저장소에 없고 요청 한도(구조 2개) 밖이라 이번 단계에서는 합성으로만 시험했다. / 상태의 뜻("kbase가 이 표적을 모름이며 전례 없음과 다름")은 이 경우에도 맞으므로 코드·상수는 그대로이고 문서의 "도달 불가" 문장만 이렇게 바로잡는다.
- N2 `move_id` 정렬의 동점. 명세 §5.4는 "`move_id`의 숫자 부분 오름차순"만 적었다(`MOVE-0001`과 `MOVE-00001`은 숫자 부분이 같다). / `(숫자 부분, move_id 문자열)` 순으로 정한다(`kinase_precedents.move_key`, 읽기 정렬의 동점 규칙도 같음). / 결정적이고 두 전례를 합치지 않는다.
- N3 명세보다 엄격한 형식 규칙(T2·T9). 명세 §3.4가 형을 다 말하지 않은 곳이다. / `target.variant`는 문자열, `target.name_as_written`은 문자열 또는 null, `parse_jsonl`은 중복 키·BOM·빈 줄·UTF-8이 아닌 바이트를 거절, 매니페스트의 `kbase_sha256`은 `"sha256:" + sha256`과 같아야 하고 `verification` 개수는 파일 행 수와 같아야 한다, 한 전례 안에서 같은 태그가 반복되면 한 번만 센다, `move_id` 숫자 부분이 정수로 바뀌지 않으면(4,300자리 초과) 형식 위반이다. / 실제 kbase 자료는 이 규칙을 모두 통과하고(가져오기 실검증), 어긋나는 자료는 가져오기에서 거절되거나 서버에서 `snapshot_invalid`가 되어 서버가 가정한 모양만 읽는다.
- N4 가져오기 명령의 세부(T3·T9). 명세 §4는 git 명령 세 개와 인자만 적었다. / `git status`에 `--untracked-files=normal`, 상속한 `GIT_*` 환경 변수를 지우고 `GIT_CEILING_DIRECTORIES`로 kbase 폴더 밖 저장소 탐색을 막음(`--from`은 저장소 루트여야 함), `-c core.fsmonitor=false -c protocol.allow=never`(fsmonitor 명령이 돌지 않고 부분 클론의 지연 가져오기가 원격에 닿지 않고 실패), 쓸 폴더의 `active.json`이 다른 참조 가족의 포인터면 거절, 최신 날짜의 pubmed 스냅샷이 둘이면 거절, 매니페스트 sha256 문자열은 소문자 정확 일치, `--from` 상대 경로는 현재 폴더 기준·`--dest` 상대 경로는 저장소 루트 기준(서버와 같음). / 모두 fail-closed 쪽이며 네트워크를 쓰지 않는다는 규칙을 더 단단히 한다.
- N5 도구·읽기 API의 세부(T4). / `chains`가 빈 번호 대응은 `numbering_map_invalid`, 429 상세에 `size_without_flagged`·`target_sizes`를 더해 어느 표적만 또는 `include_flagged`를 끄면 되는지 알림, 검색어 100자는 앞뒤 공백을 떼기 전 길이, 한 번만 받는 질의 키를 반복하면 422, 상세 라우트는 질의 검사가 run 조회보다 먼저(다른 run handle + 나쁜 질의 = 422), `limit`·`offset`이 4,300자리를 넘으면 422. / 거절은 모두 닫힌 이유이고 아무것도 쓰지 않는다.
- N6 보고서의 증거 종류(T5). 명세 §7은 무결성 값(`hash_verified` 등)과 kbase 검사 `pass` 개수를 참조값 목록 안에 적었다. / ProtView가 만든 값이라 계산값(`computed`)으로 두고(명세 §2의 두 확인 채널 분리), `pass`가 아닌 검사의 이름=상태만 참조값(`reference_value`)이다. 보고서 manifest가 8 MiB를 넘으면 `precedent_report_too_large`로 거절, 체인별 mapped/전체 잔기 수는 계산값 목록에 없어 보고서에 넣지 않음, UP2·UP3·UP5는 목록 항목("- ")으로 렌더. / 두 채널이 섞이지 않고 보고서 범위(요약 + 출처 목록)는 그대로다.
- N7 실데이터에 없는 닫힌 값과 개수의 구분. 명세·인계의 몇 수치가 어느 것을 세는지 모호했다. / 실데이터에 없는 값(25단어 초과 인용, `direction_basis` `none`, 위치 `figure`, `structure_links.basis` `sole_candidate`, `resolution_basis` `klifs_gene_name`, `multiple_accessions`)은 이번 QA 구조로는 만들 수 없었고(`multiple_accessions`는 M15 SIFTS 스냅샷에 융합 체인이 있으나 저장소에 그 구조가 없고 내려받기 한도 밖이다) 닫힌 집합에 그대로 두고 합성으로만 시험했다. `quote_truncated`는 관찰 인용 136건(`moves` 83 + `moves_flagged` 53)과 교환 인용 27건(8 + 19)을 따로 센다. 미해석 이름은 문자열 34개 + null = 서로 다른 값 35개다. / 화면·보고서는 관찰·교환 인용 각각의 플래그를 보이고, 수치를 적는 곳은 어느 수인지 밝힌다.
- N8 결과 크기의 실제 초과 사례. 명세는 최악 단일 표적(약 0.8 MiB)만 말했다. / 서로 다른 accession 두 체인(EGFR·BTK)이 한 결과에 `moves_flagged` 포함으로 들어가면 1 MiB를 넘는다(착수 확인 시제품 1,604,884 B, 제품 도구 1,605,026 B). 명세대로 자르지 않고 429 `result_too_large`로 거절하고 끄면 737,133 B로 상한 안이다(수락 real 단계의 합성 변형으로 관찰). / 어느 체인을 빼거나 토글을 끄면 되는지 거절 상세가 알린다.
- N9 1FIN B·D와 `no_mapped_residues`. 명세는 B·D를 번호 대응 체인에서 뺀다고만 가정했다. / 넣으면 번호 대응 호출 전체가 422 `no_usable_method`(M15 SIFTS 스냅샷에 그 체인 행이 없음)이므로 실데이터 단계는 A·C만 요청한다. 실데이터로 `no_mapped_residues`가 나오는 길은 사람이 체인에 맞지 않는 kinase accession을 직접 준 입력 실수(1FIN B + `P24941` → mapped 0/260)뿐이라 정상 수락 사례로 쓰지 않고 합성 번호 대응으로 시험했다. / 연결 규칙은 번호 대응 객체만 읽으므로 어느 쪽이든 같은 코드다.
- N10 Stop 훅 그룹. 인계는 새 백엔드 테스트를 이름 없는 나머지 그룹에 두고 시간만 확인하라고 했다. / 착수 때 나머지 그룹 여유가 약 71초여서 T10에서 M27 백엔드 일곱 파일을 이름 있는 그룹 16으로, 첫 고정 후보에서 나머지 그룹이 동시 476초였으므로 `test_analysis_workflows.py` + `test_jev_loop_reports.py`를 그룹 17로 나눴다(`CHECKS` 17 → 19). / 고정 게이트에서 나머지 그룹은 동시 323.2초다. 프로세스를 띄우는 서열 GA SIGTERM 시험(`[qvina-worker]`)은 훅이 다른 작업과 겹칠 때 흔들리는 알려진 현상이 이 기간에도 다시 나타났고, 단독 재실행은 3 passed(143.8초)였으며 고정 게이트에서는 통과했다(`docs/tracking/findings.md`).
- N11 브라우저의 산술과 미리 상태(T6). 명세 §8은 "브라우저에서 계산하지 않는다"와 "전례 N건" 표시를 함께 요구한다. / 브라우저 산술은 명세가 정한 개수(UP5의 N `unresolvedRecordTotal`, "전례 N건" `includedRecordCount` = 서버가 센 두 파일 개수의 합, "그 밖 N개" `unlistedNameCount`), 쪽 위치(`recordPageText`·`nextOffset`·`previousOffset`), 레코드 한 줄의 kbase 검사 `fail`·`lookup_failed` 배지 개수뿐이다. 체인 미리 상태(`chainPreviews`)는 번호 대응 행을 모두 읽은 뒤에만 보이고 그 전에는 "번호 대응 행을 다 읽은 뒤 미리 보입니다"이며, 연결 여부는 서버가 결과로 정한다. / 과학 값·순서는 서버가 정하고 브라우저는 서버 개수를 다시 셀 뿐이다.
- N12 상세의 표시 범위(T9·T11). 사용자 결정 ⑬은 kbase 필드 전부를 보이라고 했다. / 상세 끝의 접힌 "그 밖의 kbase 필드(원본 값 그대로)" 블록이 표와 상세가 이미 보인 경로를 뺀 저장 사본의 나머지 경로를 모두 JSON 값 그대로 보인다(null·0·`[]`·`{}` 유지, 뺀 두 경로는 나오지 않음). 측정 변화 표의 before/after 칸은 `qualifier`·`value`·`unit`을 이어 보이며 null·빈 `qualifier`/`unit`은 칸에서 빠지고 그 경로는 "보인 경로"로 쳐서 블록에도 나오지 않는다. 값이 null이면 칸 전체가 "—"와 이유다. / 0이나 "없음"으로 보이지 않는다. 다만 null `qualifier`/`unit`이 있었다는 사실은 화면 어디에도 보이지 않는다(`docs/tracking/findings.md`).
- N13 보류한 검토 권고(T9). / 서지 행 모양이 어긋나면(다섯 필드가 문자열|null이 아니거나 `status`가 `ok`가 아니거나 `data.pmid`가 `id`와 다름) 가져오기 거절이 아니라 그 PMID가 "서지 없음"이다. 보고서 금지어는 명세 §7 목록 그대로이고 "최고"·"배수"·"평균"·"차이"·"악화"를 더하지 않았다. 상세 라우트의 질의 검사가 run 조회보다 먼저다(N5). / 셋 다 명세가 정한 범위이며, 바꾸려면 명세·사용자 결정이 필요하다. "전례 N건"이 브라우저 덧셈인 것과 같은 탭 방문 중 번호 대응 목록이 저절로 다시 읽히지 않는 것(탭에 들어올 때 다시 읽음, M26과 같음)도 수용했다.
- N14 말하는 방식. 착수 확인 기록 `preflight.md`는 kbase `effects`를 "효과"라고 부르는 곳이 있다. / 이 기록과 문서는 "측정 변화(effects)"로 쓰고 "효과"를 주장으로 쓰지 않는다(화면 머리말 "측정 변화(kbase 추출 effects)"). / 해시로 묶인 증거는 고치지 않는다.

## 업그레이드 뒤 사용자가 할 일
1. 이 단계를 받은 뒤(`git pull` 등) 서버를 다시 시작한다. 새 의존성이 없어 `pip install -e ./backend[dev]`는 필요 없다.
2. 전례를 쓰려면 한 번: `.venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로>`(확인 화면에서 승인, `--yes`로 생략). 기본 설치 위치는 `.deps/precedent_reference/`(`MW_PRECEDENT_REFERENCE_DIR`로 바꿈, `--dest`로 지정). 로컬 파일과 읽기 전용 git만 쓰고 네트워크를 쓰지 않는다. kbase를 갱신해 `dist/manifest.json`의 세 버전 값이 `KBASE_PINS`와 달라지면 가져오기가 거절되고, 고치려면 사용자 결정으로 상수를 바꿔야 한다. 가져올 때마다 새 세트 폴더가 생기고 이전 세트는 지우지 않으며, 저장된 결과는 다시 계산되지 않고 "이전 스냅샷 기준"으로 보인다. 가져오지 않으면 도구는 `not_installed`(412)이고 화면은 숫자 없이 "사용할 수 없음"과 가져오기 명령 안내만 보인다.
3. 옛 단계 수락 실행기(M13–M26)를 돌릴 때는 `.deps/precedent_reference`와 `.deps/reaction_reference`를 없는 채로 둔다(그 실행기들은 새 환경 변수를 넘기지 않아 기본 폴더를 읽는다).
4. 결과 객체는 실제 인용문을 run 이벤트에 저장하므로 사용자 run 폴더는 공유하지 않는 자료다(KT1: kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인).

## 알려진 한계
- 전례는 kbase가 논문에서 기계로 추출한 미검수 기록이며 ProtView는 원문과 대조하지 않았다. 방향·크기는 kbase 규칙 v1의 산출값이고 ProtView의 판정이 아니다. "전례 기록 없음"은 포함한 파일에 기록이 없다는 뜻이고 선행 연구가 없다는 뜻이 아니다.
- `not_in_kbase_references`와 `no_mapped_residues`·`multiple_accessions`는 합성으로만 시험했다(N1·N9). 실데이터에 없는 닫힌 값도 합성으로만 시험했다(N7).
- 같은 탭 방문 중 번호 대응 목록 자동 갱신 없음, 상세의 null `qualifier`/`unit` 표시 없음, 실행기 유출 검사·`defaultFolderUntouched`·소켓 차단의 범위, 서지 행 모양이 어긋날 때의 "서지 없음", 옛 실행기의 기본 전례 참조 폴더, Stop 훅 동시 실행 흔들림은 `docs/tracking/findings.md`에 적었다.

## 대체한 과거 검증 범위
- M27은 공유 소스를 바꿨다: 백엔드 `api/app.py`(`SUPPORTED_TOOLS`, `methods.kinase_precedents`, 보고서 종류 집합 둘·만들기·다시 열기 분기, 읽기 라우트 셋), `workspace.py`·`config/tools.yaml`(새 도구), 프런트 `app/page.tsx`·`WorkspaceTabs.tsx`(지식 탭 슬롯)·`lib/api.ts`·`contracts.ts`·`report-library.ts`, `design/components.css`(+ 생성 복사본), `.codex/hooks/stop.py`·`scripts/test_codex_hooks.py`. 호출 키 해시 파일, M13 흐름, M15·M16·M17·M20·M24·M25·M26 모듈과 `residue_numbering_map@1` 형식은 바꾸지 않았다.
- 이 소스 기준의 현재 검증은 전체 백엔드·스크립트 pytest(6,037개, 열여덟 그룹 모두 exit 0)와 M26(fixture)·M25(fixture)·M24(fixture)·M23·M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함), 골든 셋으로 대체한다. M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 다시 돌리는 방법 (메인 체크아웃 루트, 8000·3000 포트 비움)
```bash
# 새 기능 수락: 두 단계(fixture는 합성 세트, real은 실제 kbase dist/를 가져오기 명령으로 격리 폴더에 두 번 설치, 외부 요청 0)
.venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m27-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m27-acceptance/<label> \
    --kbase <abs>/kbase_kinase --stages fixture,real --out docs/qa/m27-precedents-<YYYYMMDD>/acceptance
# 회귀 1: M26 fixture 단계(.deps/precedent_reference·.deps/reaction_reference는 없는 채로)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \
    --stages fixture --out docs/qa/<folder>/regression/m26
# 회귀 2: M25 fixture → M24 fixture → M23 … M13(실호출 0)
.venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<label> \
    --out docs/qa/<folder>/regression/m25 --phase fixture --regressions --kbase <abs>/kbase_kinase
```
RCSB 구조를 다시 받는 것은 새 외부 요청이므로 사용자가 새로 정해 줄 때만 한다(이번 할당 2개는 모두 썼다).

## 남은 일
- 새 미해결 문제(`docs/tracking/findings.md`): 위 "알려진 한계"의 항목들.
- 다음 단계는 M28(종단 검증과 마감, `docs/tracking/roadmap.md`).
