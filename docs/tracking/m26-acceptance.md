# M26 효소 반응 지식 연결 완료 기록

- 판정: **완료** (2026-10-09 UTC). main 병합 전이다. 병합 해시는 병합 뒤 기록한다.
- 브랜치: `dryforge/m26-reaction-knowledge` (`phase/m26-reaction-knowledge` = main `72f4d1e`에서 분기). M25는 시작 전에 main에 병합되어 있었다(`877d5cf`, 기록 `72f4d1e`).
- 고정 소스: `3fcac53`(T10 독립 코드 검토 수정). 고정 뒤 제품 소스(`backend/mw`·`frontend/src`·`frontend/app`·`design`·`config`·`scripts`) 변경은 없다. 고정 뒤 커밋은 둘째 가져오기 기록(`06679e4`), M23 오프스크린 하네스 한 파일(`frontend/tests/offscreen/sequence-ga-flow.cjs`, `8964179`), 최종 수락·회귀 증거(`01b09b9`, 작업 중 예비 증거 폴더 `fixture-stage/`·`real-stage/`·`regression-prep/`를 대체하고 지움), 게이트 기록(`6430e2a`), 독립 증거 검토 메모(`61c9d20`), 이 기록 문서들뿐이다.
- 해시 대응: 증거 장부·README의 `gitHead` 값은 역사 정리 전 해시다. `dac2755`는 지금 `06679e4`, `1735338`(소스 고정 당시)은 지금 `3fcac53`이다. 예비 증거 커밋에 들어 있던 실제 외부 자료 보고서 두 개를 빼려고 어디에도 올리지 않은 로컬 작업 브랜치의 끝 9개 커밋을 `git filter-branch`로 정리했고, 브랜치 끝의 트리 해시(`5f0c5c43…`)는 정리 전후 같다.
- 수락 증거: `docs/qa/m26-reaction-20261008/`(`preflight-network.md`·`preflight-local.md` 착수 확인, `v1-baseline/` v1 기준선, `import1.md`·`import2.md` 실서버 가져오기, `network-ledger.txt` 요청 장부 95줄, `gate.txt` 게이트, `acceptance/` 새 기능 수락, `regression/m25/` 회귀 사슬, `regression/m23/` M23 단독 재실행, `regression-chain.txt` 사슬 기록). 256 KiB를 넘는 텍스트 증거 53개(`m13-regression` 51개 331,913,811 B, `m14-regression` 1개 1,191,724 B, `m15-regression` 1개 590,107 B)는 결정 0020에 따라 Git 제외 `frontend/tests/offscreen/artifacts/m26-final/export-full/<폴더>/`로 옮겼다(해시는 각 증거 폴더의 `ARCHIVED-EVIDENCE.sha256`, 이 기록을 쓸 때 `shasum -a 256 -c` 53개 모두 OK).
- 외부 요청: 수락·회귀 QA의 브라우저 비-loopback 요청 0, 제공자 호출 0, OpenRouter 호출 0. 가져오기 명령 시험은 가짜 전송과 `127.0.0.1` 로컬 서버만 쓴다. 실서버 요청은 사용자 한도 안의 개발·검증 요청뿐이다: 탐색 48/100, 전체 가져오기 2/2(각 22요청), RCSB mmCIF 3/3(장부 95줄). 가져오기 요청에는 키·쿠키·인증 헤더가 없고, 두 세트 폴더와 명령 출력에서 그런 문자열은 0건이다(`import1.md`·`import2.md`).

## 범위
효소 구조에 M-CSA(촉매 잔기)·UniProt(Active site·Binding site·Site 부위, 촉매 활동)·Rhea(반응식) 참조값을 출처·날짜·라이선스(CC BY 4.0)와 함께 붙여 지식 탭에서 보이고, M-CSA와 PDB·체인·번호·잔기 이름이 모두 같은 촉매 잔기("대응됨")를 변이 후보(M20)의 기본 보호 근거로 쓴다. 변이의 효과, 효소 활성·속도·특이성, 반응 메커니즘이 유지된다는 주장과 촉매 정보로 후보를 고르거나 점수화하는 기능은 만들지 않았다. 범위 밖: 뷰어 표시·저장된 보기 형식 변경, M-CSA에 없는 구조를 서열 정렬로 잇기, UniProt 부위·충돌·대응 없음 행을 보호 근거로 쓰기, M-CSA 메커니즘·그림, M24·M25 전송에 M26 자료를 새로 보내기, M13 흐름 연동, 새 한도 증액 경로.

## 결과물 (작업별)

| 작업 | 내용 | 커밋 |
|---|---|---|
| T1 착수 확인 | 실서버 응답 모양·규모·등록 구조(탐색 46건), M20 변경 영향·도구 비용·결합 지도·J6 분기 시제품, 골든 기록기 선수정(저장된 v1 내용을 넣음)과 v1 기준선 | `5672200`, `714a7f2`, `78ba8df` |
| T2 상수·고정·대응 | `reaction_knowledge_constants.py`(닫힌 집합·상한·고정 문장·`SOURCE_FORMATS`·`ALLOWED_HOSTS`·정규 JSON·매니페스트 검사, 표준 라이브러리만)·`reaction_snapshots.py`(활성 세트 고정·파일 해시 검증)·`reaction_knowledge.py`(해석·세트 색인 캐시·세 절·결과·`validated_result`), 독립 대응 oracle | `704fa76`(병합 `063929e`) |
| T3 가져오기 명령 | `scripts/import_reaction_references.py`(전송 계층 주입, `validate_url`, 원자적 설치, 건너뜀·거절 규칙, `compare_manifests`)와 시험(가짜 전송·`127.0.0.1` 전송 계층) | `8b457d1`(병합 `4509764`) |
| T4 도구·읽기 | `tools/reaction_knowledge.py`의 `link_reaction_knowledge`(사전 검사 412 → 입장 422 아홉, 상한 429), `reaction_knowledge_reads.py`와 읽기 API 넷, `methods.reaction_knowledge` | `4feac0d`(병합 `8106cd8`) |
| T5 보고서 | `reaction_knowledge_reports.py`(계산값·참조값 분리, RK1–RK6, 출처 표), 보고서 종류 등록 | `12966bb`(병합 `5192dd5`) |
| T6 M20 v2·소비자 | v2 보호 판정·`protection_checks.catalytic_residue_database`·두 세대 `validated_set`(T6a), M24 J6 상태별 변형·v2 fixture·M21·M23·M25 수용 시험·`golden_call_keys.json` 재기록(T6b) | `6bcd33c`(병합 `b5b31bf`), `ac88f87`(병합 `17da65b`) |
| T7 프런트 순수 로직 | `lib/reaction-knowledge.ts`(새), `lib/mutations.ts`·`lib/jev.ts`·`api.ts`·`contracts.ts`·`report-library.ts` | `eda5c7f` |
| T8 화면 | `ReactionKnowledgePanel.tsx`(새), M20 촉매 칸·검사 칸·목록, 다섯 곳의 "촉매 잔기 검사 안 함" 표시, `npm run tokens` | `06d6996`, `ab7b784` |
| T9 오프스크린·실서버 첫 회 | 장부, 동형체 위치 부위 건너뜀(⑱), import1·공개 구조 셋·실데이터 대응 점검(T9a), 하네스·두 단계 수락 실행기(T9b), real 단계와 옛 M20·M24 하네스의 v2 기대(T9c), 보고서 내려받기는 해시만·예비 내려받기 삭제 | `8a0dcc6`, `075e38e`, `2bb3721`, `b3131fd`, `38489ad`, `0df2167`, `f5ba9fe` |
| T10 독립 코드 검토 수정 | F1–F6(증거 원문 보관, 문구, 검사하지 않은 개수, M20 읽기 실패 내성, 고르는 곳 표시) | `3fcac53`(= 고정 소스) |
| T11 고정·게이트·QA | import2와 재현 비교, M23 하네스 v2 기대 수정, 최종 수락·회귀 증거, 게이트 기록 | `06679e4`, `8964179`, `01b09b9`, `6430e2a` |
| T12 독립 증거 검토 | 막는 지적(역사 정리)과 조언 다섯 반영 | `61c9d20` |
| T13 기록 | 기술 문서(T13a), 결정 0034·이 기록·상태 문서·모듈 안내(T13b) | 이 기록의 커밋들 |

- API: `GET /reaction_reference/status`, `GET /reaction_reference/pdb/{pdb_id}`, `GET /runs/{rid}/reaction_knowledge`, `GET /runs/{rid}/reaction_knowledge/{handle}`(쪽 나눔), 도구 호출은 기존 `POST /runs/{rid}/commands`, `/capabilities`의 `methods.reaction_knowledge`(`methods.residue_numbering`과 같은 다섯 키), 방법 보고서 `analysis_type: "reaction_knowledge"`("효소 반응 지식 보고서"). M20 읽기 행에 `catalytic_status`가 늘었다(기존 키·값 그대로).
- 테스트: 백엔드 새 파일 여섯(`test_reaction_constants`·`test_reaction_snapshots`·`test_reaction_knowledge`·`test_reaction_knowledge_tool`·`test_reaction_knowledge_api`·`test_reaction_knowledge_reports`) 449개, 스크립트 `test_import_reaction_references.py` 213개·`test_m26_offscreen_acceptance.py` 45개(Stop 훅 `SCRIPT_TESTS`에 추가), 프런트 `tests/reaction-knowledge.test.cjs`·`tests/reaction-knowledge-panel.test.cjs`. Fixture: `backend/tests/fixtures/reaction/`(작업별 하위 폴더 `t1`·`t2`·`t3`·`t6`·`t9`·`t9a`, 합성 표시와 `SYNTHETIC-PROVENANCE-<작업>.md`, 실제 응답 조각 없음), 세트 만들기 도우미 `tests/reaction_fixture.py`, M20 v2 도우미 `tests/m20_catalytic_fixture.py`·`tests/m20_v2_fixture.py`, 공개 구조 `public_1s9i.cif`·`public_1a30.cif`·`public_1a4i.cif`(+ `.provenance.json`).

## 사용자 결정 (2026-10-08·09)
근거는 결정 0034. 사용자는 모든 질문에서 추천안을 골랐다(자유 입력 없음): ① 공개 서버에서 가져오는 명령 ② M-CSA에 적힌 PDB 항목 기준 ③ M20 촉매 칸 켬 ④ 뷰어 표시 없음 ⑤ 역할 문구 원문 ⑥ 대응됨만 보호 근거 ⑦ 실서버 한도(가져오기 2·탐색 100·RCSB 3) ⑧ 수집 범위 ⑨ v1·v2 모두 받음 ⑩ 원자적 + 파생 건너뜀 기록 ⑪ 대응됨 행 전부 보호 ⑫ 다루지 않은 체인은 검사하지 않음 ⑬ 직접 지정 실패는 전체 거절. 착수 확인 뒤 ⑭ `main_annotation` 저장 안 함 ⑮ `demerged`와 대상 목록 ⑯ Rhea 대표 반응 전부 ⑰ QA 구조 `1S9I`·`1A30`·`1A4I`, 실데이터 사전 검증 뒤 ⑱ 동형체 위치 부위만 건너뜀. 세션이 정한 세부(검사 범위 규칙, 미리 고르기, 상태 기준 표시, 닫힌 이름, 실측 반영)는 결정 0034의 "조율 세션이 정한 것"이다. 고정 문장 RK1–RK6·UK1–UK4·M20 셋째 문장 변형 둘·J6n·J6c 문구는 초안이다(승인 대기: 사용자 최종 확인).

## 착수 확인 (`preflight-network.md`·`preflight-local.md`, 기준 `72f4d1e`)
- 실제 응답: M-CSA API는 항목 1,003개·11쪽이고 `page_size` 상한 100(더 크게 주면 조용히 100으로 자름), `chain_name`은 저자 체인, `resid`는 label 번호·`auth_resid`가 저자 번호, 잔기마다 `residue_chains` 0 또는 1개, `is_reference`는 모두 참. UniProt `/uniprotkb/accessions`는 한 요청 1,000개이고 비활성·없는 accession을 이유 없이 빼므로 하나씩 분류한다. Rhea는 REST 한 요청으로 대표 반응 전부(5열 TSV). 허용 호스트는 셋으로 정했다.
- 규모: 합집합 1,630 = M-CSA 1,094 ∪ M15 kinase 541. 예상 가져오기 요청 약 22건.
- 등록 구조: 저장소 안 1HSG·1MQ4·1UBQ와 파생 1HSG는 M-CSA에 없고 M15 SIFTS ∩ M-CSA는 `1S9I` 하나. 1MQ4는 M15 번호 대응을 통한 UniProt 부위 연결 시험에 쓴다.
- M20 영향: 호출 키 해시 파일 중 바뀌는 것은 `mutation_candidates.py` 하나, 업그레이드 전 큐 작업은 과금 전 412 `worker_version_invalid`·`claimed`, 끝난 M25 루프의 읽기 바이트 불변·진행 중 단백질 루프 계산만 412 `capability_unavailable`. J6 분기 시제품에서 골든 둘과 M24 테스트 통과. 도구 비용은 캐시 없이 호출당 0.17–1.7초·최대 RSS 648 MB(합성 최악) → 세트 단위 캐시.

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 의도 감사(고정 전): 여덟 항목과 재점검 다섯 항목을 사용자 결정이나 사용자 원칙·선례로 닫았다(결정 0034).
- 독립 명세 대조 3건: T2·T4·T6a 통과, 작은 결함 하나는 T4에서 고쳤다.
- 독립 코드 검토 2건(T10, 고정 전): 백엔드·가져오기·보안 **approved**, 프런트·하네스 막는 지적 셋 → `3fcac53`에서 F1–F6으로 반영했다(실패 단계 패널 HTML·보고서 내려받기를 해시만 남김, 하네스·화면 금지어에 효과·중요·핵심·필수, 덮인 체인이 없을 때 `catalytic_residue` 제외 수를 "—"로, 반응 결과 목록·상세 읽기가 실패해도 M20 요청 영역이 쓸 수 있음, UK2 표시 문구·상세 확인과 real 단계 사례가 헛되이 통과하지 않게).
- **독립 증거 검토(T12, 고정 뒤): 막는 지적 하나**(예비 증거 커밋에 실제 외부 자료 보고서 두 개가 들어 있음 → 위 "해시 대응"의 역사 정리), 조언 다섯을 `61c9d20`에서 증거 메모로 반영했다(200 상태 주장의 범위, 회귀 사슬 기록, 게이트 세부 등).

## 게이트 (고정 `3fcac53` = 당시 `1735338`, 2026-10-09, `gate.txt`)
| 명령 | 결과 |
|---|---|
| 백엔드 pytest 열여섯 그룹(Stop 훅 `PYTEST_GROUPS` 열다섯 + 나머지 그룹, 같은 인자로 동시에 제한 없이) | 합계 5,327개, 열네 그룹 exit 0. 두 그룹에서 동시 실행 부하 프로세스 시험 하나씩 실패(`test_pocket_jobs.py::test_running_engine_is_stopped_with_its_process_group[output_files]`, `test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`), 단독 재실행 7 passed(149초, exit 0). 이 실행은 Stop 훅 자체의 pytest와 겹쳐 부하가 두 배였다 |
| 나머지 그룹 단독(같은 인자, 다른 부하 없음) | 3,553 passed, 416.8초(제한 480초, 여유 약 63초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| `node --check frontend/tests/offscreen/*.cjs`(30개) | 실패 0(고친 `sequence-ga-flow.cjs`도 다시 exit 0) |
| `npm --prefix frontend run test:events` | 496 pass, 0 fail |
| `typecheck` → `build`(차례로) | exit 0 → exit 0 |
| 골든 `--check`: `golden_science_m24.py`·`prototype_golden_egress.py` | exit 0, exit 0 |
| `prototype_golden_call_keys.py` 재기록 | 커밋된 `golden_call_keys.json`과 `cmp` 동일 |

## 실서버 가져오기와 재현 (`import1.md`·`import2.md`)
- 사전 검증(T9a): 가져오기 명령의 실제 전송으로 UniProt 일괄 요청 두 건(장부 47–48)을 받아 오프라인으로 전체를 재생했더니 P12821 Binding site 3개의 동형체 위치 때문에 형식 오류로 멈췄다. 사용자 결정 ⑱ 뒤 명령과 합성 시험(`fixtures/reaction/t9a/`)을 실서버 가져오기 **전에** 고쳤다(`075e38e`).
- import1(2026-10-09T01:58–02:00Z, 117초)과 import2(09:44–09:46Z, 121초)는 같은 명령 `.venv/bin/python scripts/import_reaction_references.py --yes --reference-dir <repo>/.deps/reaction_qa/<import>`를 한 번씩 돌렸다(재시도 없음). 각 22요청(M-CSA 11·UniProt 10(일괄 2 + 분류 8)·Rhea 1), 접촉 호스트는 `www.ebi.ac.uk`·`rest.uniprot.org`·`www.rhea-db.org`뿐, 모두 GET·200, 받은 바이트 합 24,262,908.
- 세트: import1 `fbeed900…fcb52`, import2 `1a7b131a…acf47`. 행 M-CSA 1,003·UniProt 1,622·Rhea 18,611, 건너뜀 8(모두 M-CSA 파생, `obsolete` 4·`demerged` 4), 동형체 위치 부위 3(세트에 남기지 않음), `requested_accessions`는 `from_mcsa` 1,094·M15 kinase 541(`present`)·`union_count` 1,630.
- 재현(명세 4.5): `compare_manifests`로 비교해 가공 파일 셋의 SHA-256이 모두 같다(`reproduced: true`). 원본 응답 요약 차이 없음, 두 매니페스트는 `imported_at` 하나만 달라 세트 해시만 다르다.
- 비밀·헤더 검사: 두 세트 폴더의 모든 파일과 명령 출력에서 쿠키·인증·키·헤더 이름 문자열 0건.
- 실데이터 대응(제품 코드, 개수·상태만): 1S9I 체인 A `covered`(M-CSA 282) `matched` 2, 체인 B `chain_not_listed`; 1A30 체인 A·B 모두 `covered`(175) 각 `matched` 3; 1A4I 체인 A에 항목 둘(389·458) `matched` 6, 체인 B `chain_not_listed`; 1HSG·1MQ4·1UBQ는 `pdb_not_in_snapshot`. M15 번호 대응을 통한 UniProt 부위 연결: 1S9I mapped 11 / not_in_map 2, 1MQ4 mapped 9 / not_in_map 0. 실데이터에서 `unmatched`·`conflict` 행은 없었다.

## 수락 QA (`acceptance/`, `scripts/m26_offscreen_acceptance.py --stages fixture,real`, 2026-10-09)
- `verdict: pass`, `acceptance: true`, 사례 58개 모두 통과(fixture 39 + real 19), 두 단계가 한 실행에서 모두 돌았다. 실제 Electron 오프스크린, 단계마다 격리 참조 폴더(`MW_REFERENCE_DIR`·`MW_REACTION_REFERENCE_DIR`)와 runs 폴더, 브라우저 비-loopback 요청 0·제공자 호출 0, 남은 프로세스·리스너 없음. 빌드 도장 `dac2755`(= 지금 `06679e4`, 제품 소스는 고정과 같음).
- fixture 단계: 합성 표시 세트(`backend/tests/fixtures/reaction/t9/build_qa_set.py`, 지어낸 PDB ID)로 스냅샷 없음·정상·`active.json` 치움·파일 변조·세트 B("이전 스냅샷 기준")를 차례로 바꾸며 관찰했다. 관찰한 것: 요청 기본값(자동 선택 없음), 칸별 거절, 입장 거절 아홉 이유 "한국어 (code)", `matched` 행 7필드·역할 원문 열 "M-CSA 원문, 계산 아님"·기준 구조 여부, 반응 절과 Rhea `in_snapshot` 참·거짓, 합성 파생 구조의 `conflict`, `unmatched` 다섯·`conflict` 둘 이유, 한 체인 항목 둘, UK4, `pdb_not_in_snapshot` 빈 결과, accession 상태(건너뜀·스냅샷에 없음·`accession_differs_from_mcsa`), 번호 대응을 통한 부위 연결과 `link_reason`, 쪽 나눔, 보고서와 내려받기 바이트, dry-run run, "—" 표시(0 아님), 금지 표현 없음, M20 미리 고르기·UK2·UK3·체인별 예측·`chains_not_covered`·`checked`·충돌/대응 없음 목록·"해제됨"·제외 사유 일곱·한계 문장 셋째의 세 변형·저장된 v1 run, 고르는 다섯 곳(M20 목록·M21·M23·M24·M25)의 표시, 다른 탭 불변.
- real 단계: import2 세트를 격리 폴더로 복사(`1a7b131a…acf47`)하고 공개 1S9I·1A30·1A4I·1HSG·1MQ4·1UBQ와 합성 파생 1S9I(ASP A194 → GLU)로 위 실데이터 대응과 같은 개수·상태를 화면에서 관찰했다. M20 v2는 1A30에서 체인 A만의 결과 → `chains_not_covered`(B `not_in_annotation`), A+B 결과 → `checked`와 `matched` 위치 보호, 해제 → "해제됨", 파생 1S9I → 충돌 목록.

### 관찰하지 못한 사례 (위조하지 않음)
- 늦은 응답(`R-late-response`): 순수 가드 시험(`frontend/tests/reaction-knowledge.test.cjs`의 `reactionResponseCurrent`)과 같은 방식의 M15·M20 흐름이 덮는다. 결과 1 MiB·연결 위치 2,000 상한(`R-too-many-links`)은 `backend/tests/test_reaction_knowledge_tool.py`, M20 목록 400 상한(`C-list-too-long`)은 `backend/tests/test_mutation_tool.py`가 덮는다.
- real 단계의 `unmatched` 이유·`conflict`(`X-unmatched-reasons`): 실제 세트가 공개 구조에서 그런 행을 만들지 않았다(합성 파생 1S9I의 충돌 하나뿐). 저장된 v1 run(`X-v1-set`)은 fixture 단계에서 관찰했다.

### 회귀 (`scripts/m25_offscreen_acceptance.py --regressions`, fixture 단계만·실호출 0, `regression-chain.txt`)
- M25 fixture 57/57, M24(fixture) 26/26, M22 25/25, M21 23/23, M20 24/24, M19 26/26, M18 24/24, M17 21/21, M16 19/19, M15 14/14, M14 15/15, M13 28사례(M11·M12 하위 실행기 포함), 모두 `acceptance: true`. 사슬 내내 `.deps/reaction_reference`는 없었다(옛 실행기는 `MW_REACTION_REFERENCE_DIR`를 넘기지 않는다).
- **M23은 사슬에서 실패했다**(35사례 중 4 통과). 하네스가 도구로 만든 집합의 제외 사유 개수를 여섯 키(v1)로 기대했는데 도구가 만드는 집합은 이제 v2(일곱 키, 촉매 칸 `not_checked`)이기 때문이다. 제품 결함이 아니라 하네스의 v1 기대였다. `sequence-ga-flow.cjs` 한 곳을 고쳐(저장된 v1 fixture와의 비교는 유지하고 v2 추가분만 따로 단언) M23 실행기를 단독으로 다시 돌렸다: `regression/m23/acceptance/` 35/35 `acceptance: true`(빌드 도장에 그 하네스 파일이 고친 채 적혀 있고 수정은 `8964179`로 커밋). 실패한 사슬 증거는 `regression/m25/m23-regression/`에 그대로 남겼다.

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다(해시로 묶인 문서는 아님).
- 도구·capability 집합: `test_api.py`(`/tools` 이름), `test_ligand_api.py`(`/capabilities` 방법), `test_reference_site_annotation.py`·`test_residue_numbering.py`(사전 검사가 있는 도구 집합).
- M20 시험 넷(`test_mutation_candidates.py`·`test_mutation_tool.py`·`test_mutation_api.py`·`test_mutation_reports.py`): 도구가 만드는 집합은 v2가 기본이고 v1 동작은 저장된 v1 fixture(`fixtures/reaction/t1/` 등)로 계속 검증한다. JEV 시험(`test_jev_constants.py`·`test_jev_projection.py`·`test_jev_reports.py`·`test_jev_sends.py`)은 J6 변형. `test_sequence_ga_inputs.py`는 도구가 만든 집합이 이제 v2라 저장된 v1 TINY 집합과 `method_version`·위치의 `protection.catalytic`(null)만 다르다는 기대. M21·M25 시험 파일(`test_mutation_model_inputs.py`·`test_mutation_model_jobs.py`·`test_jev_loops_api.py`·`test_jev_loops_compute.py`·`test_jev_loops_read.py`)에는 v2 집합 수용과 해시 변경(진행 중 루프 막힘·끝난 루프 바이트 불변) 시험만 더했다.
- 프런트 `mutations.test.cjs`·`sequence-ga.test.cjs`(v2 기대, `jev.test.cjs`·`report-library.test.cjs`는 단언만 더함), 하네스 `mutation-flow.cjs`(촉매 모드와 v2 기대)·`jev-flow.cjs`(J6 기대가 투영 와이어의 촉매 상태를 따름)·`sequence-ga-flow.cjs`(위 회귀).
- 골든 기록 스크립트 둘(`golden_science_m24.py`·`prototype_golden_call_keys.py`)은 M20 v2를 켜기 전에 M20 도구 대신 저장된 v1 내용을 넣도록 바꿨다(골든 바이트 불변, `v1-baseline/checks/`). `golden_call_keys.json` 재기록의 차이는 세 값뿐이다.
- 증액 호출자 AST 테스트 셋·`test_jev_ast.py`·`scripts/test_codex_hooks.py`는 고치지 않았다(Stop 훅 그룹 열여섯 그대로, `SCRIPT_TESTS`에 두 파일만 추가).

## 해석 메모 (명세가 모호한 곳에서 조율 세션이 정한 해석)
- N1 `coverage`: `covered`는 M-CSA 항목의 `residue_chains`에 이 PDB(대소문자 무시)와 이 저자 체인이 함께 있을 때뿐이다. `chain_not_listed`·`pdb_not_in_snapshot`·`not_checked` 체인은 `entries`·`rows`·`counts`가 null이다(빈 목록이 아님). 조립체 이름은 쓰지 않고 형제 체인으로 넓히지 않는다.
- N2 `checked` 판정: M20 `catalytic_residue_database.status`는 위치를 가진 모든 체인이 `covered`일 때만 `checked`다. 위치가 하나도 없는 집합이거나 덮이지 않은 체인(`chain_not_listed`·`pdb_not_in_snapshot`·`not_checked`·결과에 없는 체인 `not_in_annotation`)이 하나라도 있으면 `not_checked`(`chains_not_covered`)이며, 그래도 `covered` 체인의 `matched` 행은 보호한다. 위치의 `catalytic`은 검사했으면 목록(`[]` 포함), 아니면 null이다.
- N3 "—" 표시: 아무 체인도 덮이지 않으면 저장 형식(명세 8.3)대로 `matched_rows`·`conflict_rows`·`unmatched_rows`와 `exclusion_reason_counts.catalytic_residue`가 0으로 저장된다. 화면과 M20 보고서는 이 경우 "—"와 이유를 보이고 숫자 주장을 만들지 않는다(F4). 저장 객체와 집합 상세 읽기의 원본 `result`에는 0이 상태와 함께 그대로 있다.
- N4 표시 기준: 사용자는 "v1 배지·세대별 문구"를 골랐으나 `catalytic_residue_database.status`를 기준으로 바꿨다. `checked`가 아닌 집합(`not_available`(v1)·`not_checked`(v2))은 고르는 다섯 곳에서 같은 "촉매 잔기 검사 안 함"(UK2) 표시와 상태별 상세를 보이고, M20 셋째 한계 문장·M24 J6은 상태별 세 변형이다.
- N5 UniProt 부위는 어떤 경우에도 보호에 쓰지 않는다. M20 요청 영역은 고른 결과에 연결된 부위가 있으면 UK3 한 줄을 더한다.
- N6 해시만 남기는 증거: 보고서 내려받기와 실패 단계의 패널 HTML은 제3자 참조 원문(M-CSA 역할 문구·UniProt 설명·Rhea 반응식)을 담으므로 수락 증거에는 경로·바이트·SHA-256만 남기고 원문은 Git 제외 artifacts에 둔다.
- N7 동형체 위치 부위(⑱)의 건너뛴 개수는 명령 출력에만 있다(매니페스트 키 집합이 고정이라 세트에 남지 않음). import1·import2 모두 3이었다.
- N8 명세 4.5는 재현 비교를 수락 실행기가 한다고 적었지만 실제로는 가져오기 스크립트의 라이브러리 함수 `compare_manifests`를 파일 경로로 불러 두 매니페스트를 직접 비교했다(독립 증거 검토가 같은 결과를 다시 계산함).
- N9 M20 미리 고르기: 구조를 고르면 같은 구조의 가장 최근 M26 결과를 촉매 주석으로 미리 고르고(가장 최근 KLIFS 주석 미리 고르기와 함께) 자동 제출은 없다. 지식 탭 요청 영역은 제안을 빈 칸에만 채우고 체인 선택·PDB ID 확인·번호 대응 선택을 하지 않는다.

## 업그레이드 뒤 사용자가 할 일
- **업그레이드 전 큐에 있던 M21·M23 작업**: 시작하면 과금 전에 412 `worker_version_invalid`로 거절되고 `claimed`로 남는다. 그 작업을 취소하고 같은 요청을 다시 제출한다(새 호출 키 = 새 작업).
- **진행 중이던 M25 단백질 루프**: 계산 시작이 412 `capability_unavailable`(`missing_configuration`)로 막힌다(만들 때 고정한 `mutation_candidates.py` 해시와 달라서). 그 루프를 끝내고 새 루프를 만든다. 끝난 루프는 보이는 값이 그대로이고 리간드 루프는 영향이 없다. 새 루프 풀은 v1·v2 집합을 모두 받는다.
- **M21·M23 결과 재사용**: 이전에 저장된 변이 모델·서열 GA 결과는 같은 입력으로 다시 요청해도 자동 재사용되지 않고 새로 계산된다(과금). 저장된 객체·읽기·보고서는 그대로다. M20이 새로 만드는 집합은 모두 v2이고 저장된 v1 집합은 그대로 쓸 수 있다.
- **반응 참조 스냅샷 설치**: 터미널에서 `.venv/bin/python scripts/import_reaction_references.py`를 실행한다(확인 화면에 허용 호스트·출처·예상 accession 수·쓸 폴더가 나오고 `--yes`로 생략, `--accession`/`--accessions-file`로 직접 지정, `--no-kinases`로 M15 kinase 목록 제외, `--reference-dir`로 폴더 지정. 기본 폴더 `MW_REACTION_REFERENCE_DIR` 또는 `.deps/reaction_reference`). 이 명령만 세 공개 서버에 읽기 요청을 보낸다(관찰: 22요청, 약 2분). 가져올 때마다 새 세트 폴더가 생기고 이전 세트는 지우지 않으며, 저장된 결과는 다시 계산되지 않고 "이전 스냅샷 기준"으로 표시된다. 설치하지 않으면 지식 탭 영역은 이유와 명령 안내만 보이고, M20은 촉매 잔기를 검사하지 않은 v2 집합(`not_checked`, "촉매 잔기 검사 안 함")을 만든다.
- **옛 수락 실행기(M13–M25)를 돌릴 때**: 그 실행기들은 `MW_REACTION_REFERENCE_DIR`를 넘기지 않아 기본 폴더 `.deps/reaction_reference`를 읽는다. 회귀를 돌리는 동안 그 폴더를 없는 채로 둔다(이번 회귀도 그렇게 돌렸다).

## 알려진 한계
- 촉매 잔기·부위·반응은 참조값이며 ProtView의 판정이 아니다. "대응됨"은 역할·활성을 뜻하지 않고 반응 정보는 활성·속도·특이성·메커니즘 유지의 근거가 아니다. M-CSA에 PDB 항목이 없는 구조는 M-CSA 절을 검사할 수 없다.
- 실데이터 수락 구조에서는 `unmatched`·`conflict` 행이 없어 그 경로는 합성 행·합성 파생 구조로만 관찰했다.
- 위 N3의 저장된 0, 가져오기의 제한 시간 확인 단위·`SSL_CERT_FILE`/`SSL_CERT_DIR`·남는 스테이징 폴더·`--reference-dir` 검사 범위, M20 `validated_set`이 반응 결과와 대조하지 않음·PDB ID 교차 확인 없음·v1 집합의 `catalytic_residue` 필터가 빈 목록, 늦은 연결 응답·거절 문구 유지, Stop 훅 나머지 그룹 여유, `build_sequence_ga_fixtures.py --check`의 설계상 실패는 `docs/tracking/findings.md`에 적었다.

## 대체한 과거 검증 범위
- M26은 공유 소스를 바꿨다: 백엔드 `api/app.py`(읽기 라우트 넷·capability·보고서 등록·`SUPPORTED_TOOLS`), `workspace.py`·`config/tools.yaml`(새 도구, `generate_mutation_candidates`의 `catalytic_annotation`), M20 `mutation_constants.py`·`mutation_candidates.py`·`tools/mutations.py`·`mutation_reads.py`·`mutation_reports.py`, M24 `jev_constants.py`·`jev_projection.py`·`jev_sends.py`·`jev_reports.py`, 프런트 `app/page.tsx`·`WorkspaceTabs.tsx`·`MutationPanel.tsx`·`MutationModelPanel.tsx`·`SequenceGaPanel.tsx`·`JevPanel.tsx`·`JevLoopPanel.tsx`·`lib/mutations.ts`·`lib/jev.ts`·`lib/api.ts`·`contracts.ts`·`report-library.ts`, `design/components.css`.
- 그 밖의 연결 변경: `.codex/hooks/stop.py`(`SCRIPT_TESTS`에 두 파일), 골든 기록 스크립트 둘, `backend/tests/jev_send_fixture.py`(저장된 집합 run).
- 이 소스 기준의 현재 검증은 전체 백엔드·스크립트 pytest(5,327개, 동시 실행 실패 둘은 단독 통과)와 M25(fixture)·M24(fixture)·M23(단독 재실행)·M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함), 두 골든 `--check`로 대체한다. M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 다시 돌리는 방법 (프로젝트 루트, 8000·3000 포트 비움)
```bash
# 새 기능 수락: 두 단계(fixture는 합성 세트, real은 설치된 세트 폴더를 격리 폴더로 복사, 실서버 요청 0)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \
    --stages fixture,real --reaction-set <installed set folder> --out docs/qa/m26-reaction-<YYYYMMDD>/acceptance
# 회귀(M25 fixture → M24 fixture → M23 … M13, 실호출 0, .deps/reaction_reference는 없는 채로)
.venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<label> \
    --out docs/qa/<folder>/acceptance-fixture --regressions --kbase <abs>/kbase_kinase
# 재현 비교: scripts/import_reaction_references.py를 파일 경로로 불러 compare_manifests(<첫 매니페스트>, <둘째 매니페스트>)
```
실서버 가져오기를 다시 돌리는 것은 새 실서버 요청이므로 개발·검증 중에는 사용자가 새로 정해 줄 때만 한다.

## 남은 일
- main 병합(사용자 승인 뒤). 병합 해시는 병합 뒤 이 기록과 `docs/tracking/status.md`에 적는다.
- 고정 문장 초안의 사용자 최종 확인(결정 0034).
- 새 미해결 문제(`docs/tracking/findings.md`): 위 "알려진 한계"의 항목들, 옛 실행기의 참조 폴더, 역사 정리 기록.
