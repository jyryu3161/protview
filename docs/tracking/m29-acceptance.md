# M29 구조 보완 기록

- 판정: **검증 통과, 사용자 확인 대기** (기록 초안 T18, 2026-10-14). 이 초안을 쓸 때 정의 항목 ⑥-2(독립 증거·기록 검토, T19)·⑦(`CLAUDE.md`·`AGENTS.md`, T20)은 아직 끝나지 않았다(⑤ 회귀 사슬은 T16에서 채웠다)(아래 "정의 항목"의 `대기`). 위 판정 값은 그 둘이 통과했을 때의 값이고, 판정 문구를 바꾸는 확인 권한은 사용자에게만 있다. 사용자 확인 뒤의 판정 문구와 병합 정보는 메인 세션이 한 커밋에서 바꾼다.
- 목적: 변이 구조 모델링(M21)·서열 GA(M23)·단백질 JEV 루프(M25)·M21 수용체 출처 도킹(M18)의 입구인 OpenMM 사전 검사(M7)에서 막히던 실제 결정구조를, 사용자가 명시적으로 요청할 때 승인된 결손 다섯 종류(체인 조각 합치기·곁사슬 원자·C 말단 OXT·내부 틈 1–20잔기·MSE→MET)만 PDBFixer로 채운 새 전처리 구조로 만들어 모델링 경로에만 들이고, 무엇을 더하고 바꿨는지를 보완 기록 `structure_repair@1`과 화면·보고서의 "보완 구조 기준" 표시로 남긴다. 관측 원자는 하나도 바꾸지 않는다(좌표 1e-9 Å 이내, 식별자 유지, MSE→MET만 예외).
- 브랜치: `dryforge/m29-structure-repair`(main `3c5994e4` "Record the M28 merge hash"에서 분기).
- 소스 고정: `52aa4265`(M29 T14: source freeze). 게이트는 이 커밋에서 돌았다(`gate.txt` 머리, 작업 트리 변경 0). 수락은 고정에 게이트 기록만 더한 `1802a32f` 위에서 돌았다(`git diff --name-only 52aa4265 1802a32f`는 `docs/qa/m29-repair-20261013/gate.txt`와 `gate-raw/`의 파일 12개, 모두 13개뿐, 수락 대장의 빌드 도장 `gitHead` `1802a32f`·`buildCurrentWithSource: true`·`dirtyFiles: []`). 두 커밋은 문서·증거만 다르다.
- 고정 뒤 변경: `git diff --name-only 52aa4265..HEAD`는 `docs/**`, `README.md`, `backend/`·`frontend/`·`scripts/` 아래 `AGENTS.md` 셋, 그리고 옛 단계 하네스의 기대 수정 하나(`frontend/tests/offscreen/jev-loop-flow.cjs`, 이유 `docs/qa/m29-repair-20261013/regression-harness-changes.txt`, 명세 §11.2 (b), 회귀 사슬 T16에서 M25 하네스가 새 `repair-panel` 영역을 첫 항목으로 기대하도록 한 줄)만이다. 명세 §11.2 (a)가 `backend/`·`frontend/`·`scripts/` 아래 `AGENTS.md`를 허용 경로로 적었으므로 해석이 필요 없다. 루트 `CLAUDE.md`·`AGENTS.md`는 T20에서 바꾼다.
- 결정: 0037(사용자 결정 2026-10-12~13, `docs/tracking/decisions/0037-m29-structure-repair.md`). 요약은 아래 "사용자 결정".
- 수락 증거: `docs/qa/m29-repair-20261013/`(아래 "증거 위치"). 스크린숏 68개·화면 글자 17개·내려받은 mmCIF 1개는 Git 제외 `frontend/tests/offscreen/artifacts/m29-repair/acceptance-20261014/`에 있고 커밋 증거에는 경로·크기·SHA-256만 있다(`acceptance/binary-artifacts.json`, 보류 텍스트 0).
- 외부 요청: RCSB 공개 구조 GET 5회(모두 HTTP 200, 재시도·검색·헤더·키 없음)뿐이다. 8VF6 1회(STK33 점검 때 사용자 요청, 장부는 Git 제외 `runs/stk33-8vf6-20261013/network-ledger.txt`, 내용은 `backend/tests/fixtures/public_8vf6.provenance.json`의 `download_note`)와 사용자가 승인한 1RNH·4INS·1AY7·1CLL 각 1회(`network-ledger.txt`). 실제 JEV 호출 0, 제품·시험·QA의 그 밖의 외부 요청 0(수락 브라우저 비-loopback 0, 제공자 호출 0, 제품 키 해석기 읽기 0, dispatch 이벤트 0).
- 커밋 증거 위생: 수락 내보내기 관문 `exportClean` 참(키 모양·placeholder·사용자 절대 경로 0, 절대 경로는 `<repo>`·`<home>`). 실제 kbase 문구는 없다.

## 범위
M29는 새 작업 전용 도구 `repair_structure`(프로토콜 `pdbfixer_repair_v1`, 비싼 계산 1단위)와 무료 사전 검사 읽기, 보완 기록 `structure_repair@1`, 보완 구조(기존 형식 `prepared_structure@1`, manifest의 `repair` 키가 유일한 표지), 게시 전 검증(관측 원자 불변·추가 원자 일치·새 잔기 식별자·M7 사전 검사·기록 재생성), 모델링 경로 밖의 기본 거절(`repaired_structure_not_accepted`), M20의 원본 구조 기준 참조 결과 인계와 모델링 원자 표시(`modeled_basis`), 하류 읽기 필드 `structure_origin`과 고정 문장 RP1–RP6·SO1–SO3·JW1, 하류 보고서 형식 버전(보완 구조일 때만), 보완 보고서 `structure_repair_markdown@1`, 단백질 공학 탭의 "구조 보완" 영역, 수락 실행기 `scripts/m29_offscreen_acceptance.py`를 더했다.

하지 않은 것(명세 §1.2): 구조에서 리간드 SDF 뽑기·수소 붙이기, 틈을 캡(ACE·NME)으로 끊기, 체인 이름 바꾸기, 말단 꼬리 만들기, MSE 밖 비표준 잔기 치환, 뼈대 결손 잔기 보완, 여러 모델(NMR) 보완, 사슬 일부만 보완, 같은 전처리 구조의 여러 번 보완, 보완 구조를 M7 단독 최소화·M11·M12·M13·접촉·SASA·거리·정렬·번호 대응·참조 주석·M26·M27·Mol* 뷰어에 쓰는 것, M24 와이어·`jev_choice@1`·골든 변경, 실제 JEV 호출, 호출 키 해시 파일 변경, M21 시간 상한(120/240초) 올리기.

## 사용자 결정 (2026-10-12~13)
근거는 결정 0037의 "결정 (사용자, 2026-10-12~13)" ①–④다. ① 플랫폼 일반화 요청에 "구조보완으로 해."로 정하고 질문에서 모두 추천안을 골랐다(틈은 내부만 메움·20잔기 초과 거절, MSE→MET만, 모델링 경로에서만, 충돌은 기록만, 화면·보고서에 "보완 구조 기준", 뷰어에 올리지 않음, 검증 구조는 로컬 + RCSB 최대 4개, 같은 저자 체인의 조각은 이름을 바꾸지 않고 합침, M20은 원본 구조 기준 참조 결과를 받고 모델링 원자 기준을 표시, 저장값은 그대로·읽기 계층이 덮어 보임, JEV 전송은 허용하되 경고, M23 보고서는 바꾸지 않고 화면만). ② M21 시간 상한 유지(T1 측정: 보완한 8VF6 M21 작업 하나 1,035초). ③ 명세 정정 둘(새 원자 좌표 소수 넷째 자리, PDB 형식 틈 잔기의 `chain_label`). ④ RCSB 구조 넷(1RNH·4INS·1AY7·1CLL) 승인. 사용자에게 묻지 않고 조율 세션이 정한 것은 결정 0037의 "조율 세션이 정한 것" 1–22이고, 수락 판정과 관련된 읽기는 아래 해석 메모다.

## 정의 항목 (명세 §15)
값은 `pass`·`대기` 둘을 쓴다. `not_observed`와 `fail`은 통과로 세지 않는다.

| 항목(명세 §15) | 상태와 증거 |
|---|---|
| ① 게이트(§11.2, 소스 고정 뒤 다시 돌리기 없이 연속 3회) | **pass** — 고정 `52aa4265`에서 ruff + pytest 20그룹(이름 있는 19 + 나머지)을 한꺼번에(그룹별 480초) 연속 3회, 다시 돌리기 0. 매회 모든 체크 exit 0, **6,703 passed·0 skipped**, 가장 긴 그룹 377.9·379.6·375.2초. 차례로 돌린 명령: ruff exit 0, `node --check` 35개(옛 34 + `structure-repair-flow.cjs`) 실패 0, `test:events` 553/553, typecheck → build exit 0, `golden_science_m24.py --check`·`prototype_golden_egress.py --check` exit 0, `prototype_golden_call_keys.py` 재기록이 커밋된 `golden_call_keys.json`과 `cmp` 동일(다시 기록하지 않음), 호출 키 해시 파일 27개 blob = `BASELINE_BLOBS`, 작업 트리 변경 전·후 0. 증거 `gate.txt`, `gate-raw/`(회차별 `round1.json`–`round3.json`, 명령별 로그, `other-commands.txt`) |
| ② 간헐 실패 시험 셋(§12) 연속 3회 | **pass** — T2가 시험 쪽만 고쳤다(`backend/tests/`, `e1da210b`·`16aa05d8`·`ea608e33`·`0218cfa5`·`0a9a602a`·`cddc638a`, 제품 코드·해시 파일 변경 없음). T2 계열 C(`cddc638a`, 열아홉 그룹)가 다시 돌리기 없이 연속 3회 통과(6,531개, 가장 긴 그룹 385.6·388.0·390.0초, 회 밖 pytest 그룹 프로세스 최대 0·2·3으로 오염 없음), 고정 게이트 3회(스무 그룹)에서도 그 셋이 모두 통과. 증거 `t2-flaky-tests.md`, `t2-flaky-tests.txt`("VERDICT" 절), `gate.txt` 끝 메모 |
| ③ §3.4 게시 전 검증·§5.2 인벤토리·§6 표시와 보고서 형식 버전 시험 | **pass** — 게이트 3회에 모두 들어 있다: §3.4는 `test_structure_repair_build.py`(빌더·기록·순수 검증기)·`test_structure_repair_jobs.py`(8VF6 실제 작업, 닫힌 실패·시간 초과·취소에서 객체 0)·`test_structure_repair_lane.py`, §5.2는 `test_structure_repair_consumers.py`(정의마다 선언)·`test_structure_repair_refusals.py`, §6은 `test_structure_repair_downstream_reads.py`·`test_structure_repair_reports_downstream.py`(새 형식 버전은 보완 구조일 때만, 옛 저장 보고서 같은 바이트). 수락의 pytest 단계가 다시 돌렸다: R6 10 passed, R9 79 passed, R10 1 passed, 해시 파일 27개 blob 변경 0(`acceptance/evidence/evidence/pytest.json`) |
| ④ 수락 사례 전부 `pass` + 구조 분류 표 + 독립 기대값 대조(§10) | **pass** — `acceptance: true`, 사례 12개 모두 `pass`(`fail` 0, `not_observed` 0), 관문 11개 모두 참, 모든 단계·13구조를 돈 연습 아닌 실행. 사례 안의 허용된 관찰 공백은 R4b 도킹 하나(`no_model_time_limit`). 분류 표 26행(13구조 × 물 정책 둘) 모두 문서 = 독립 분류 = 제품. 증거 `acceptance/README.md`·`summary.json`·`cases.json`·`classification-table.md`·`.json` |
| ⑤ 회귀 사슬(§11.1) | **pass** — 소스 고정 뒤 문서·증거 커밋 위에서(실행기마다 빌드 도장의 git head가 다르다: M28 `ccd4a900`, M27 `993138bb`, M26·M25 첫 실행·M24·M23 `5fe7f208`, M22 `7572a986`, M21 … M13·M25 재실행 `b7e637cc`; 모두 고정 `52aa4265`과 문서·`README.md`·`AGENTS.md`만 다르다) M28 종단 실행기 `--phase fixture` → M27 `--stages fixture,real` → M26 `--stages fixture,real` → M25 `--phase fixture --regressions`(M24 … M13)를 한 번에 하나, 8000·3000 비움, `.deps/precedent_reference`·`.deps/reaction_reference` 없음(앞·사이·뒤 `ls` 기록). 기준 사례 수와 같다: M28 fixture 31 → 31, M27 46, M26 58, M25 57, M24 26, M23 35, M22 25, M21 23, M20 24, M19 26, M18 24, M17 21, M16 19, M15 14, M14 15, M13 28(M27 … M13 합 441 → 441), 모두 `pass`, 사례 증감 0. **옛 단계 하네스 기대 수정 하나**: 첫 M25 실행에서 M25 자체 fixture 단계만 실패했다(같은 실행의 M24 … M13 회귀 단계 열둘은 모두 exit 0). `frontend/tests/offscreen/jev-loop-flow.cjs`가 단백질 공학 탭 영역 목록을 정확히 비교하는데 M29의 새 첫 영역 `repair-panel`이 더해져 리간드 갈래 사례가 시작에서 중단(리간드 갈래 `L-*` 28개와 증거 문구 검사 `S-wording-evidence` 1개, 모두 29개 실패; 단백질 갈래 `P-*` 22개와 `X-*` 3개·`S-*` 3개, 모두 28개 통과). 그 한 줄 기대를 고치고(제품 코드 아님, 명세 §11.2 (b)) M25 fixture 단계만 새 root에서 다시 돌려 57/57 `pass`, 실호출 0. 첫 실행의 증거도 그대로 둔다. 증거 `regression/`, `regression-chain.txt`, `regression-harness-changes.txt`(256 KiB 넘는 텍스트 54개 약 334 MB는 Git 제외 `export-full/`에 두고 해시는 폴더별 `ARCHIVED-EVIDENCE.sha256`) |
| ⑥-1 독립 코드 검토(T12, 고정 전) | **pass**(남은 막는 지적 0) — 세 갈래 중 둘(A 서버 코어, B 하류·읽기·보고서)은 `approved`, 화면·실행기 갈래(C)는 `needs-fix`(막는 지적 1건: R4a 도킹 공백 판정이 원자 상한이 아닌 거절까지 받아들임). T13에서 고친 뒤 새 검토자 한 명이 수정분을 다시 보고 `approved`(막는 지적 0, 권고 넷). 아래 "독립 검토 요약". 검토 기록은 Git 제외 조율 메모 `.dryforge/run-notes.md`의 "T12 독립 검토 결과"·"T13 재검토" 절 |
| ⑥-2 독립 증거·기록 검토(T19, 고정 뒤) | **대기** — 아직 하지 않았다 |
| ⑦ `CLAUDE.md`와 `AGENTS.md` 바이트 동일, 구조·절 순서 불변 | **대기** — T20에서 M29 줄과 작업 전 확인 항목을 넣고 `cmp`로 확인한다(이 초안을 쓸 때 두 파일은 `cmp` 동일이고 M29 줄은 아직 없다) |

## 수락 사례 (`acceptance/`, 2026-10-13 15:14–15:42 UTC = 한국 시각 10-14 00:14–00:42)
실행기 `scripts/m29_offscreen_acceptance.py`(fixture 단계만, 단계 `r1`·`r3`·`r4a`·`table`·`r8`·`r7`·`r6`·`r4b`·`pytest`·`r9`), 실제 Electron 오프스크린, 서버는 M25 fixture 서버(제품 앱 그대로이고 외부 게이트만 스크립트 없는 `MockTransport`). 기대값은 제품 답이 아니라 `scripts/m29_oracle.py`(입력 파일과 설치된 Amber14 템플릿만)와 `scripts/m29_common.py`의 문서 값에서 왔다. 관측값은 `cases.json`·`acceptance/evidence/evidence/*.json`에서 옮겼다.

| 사례 | 관찰(증거 값) |
|---|---|
| R1 8VF6 종단(UI) | 불러오기 → 전처리 `strip_all` → 사전 검사(걸림돌 없음) → 확인·승인·작업 → 결과 → mmCIF 내려받기(저장 바이트와 같음) → 보완 보고서. 기록: 추가 잔기 24·추가 원자 266(곁사슬 91·OXT 2·틈 잔기 173), 곁사슬 잔기 23, OXT 2, 틈 2, 체인 조각 합치기 2, 치환 0, 보완 뒤 단백질 중원자 4,538. 관측 원자 4,338개 모두 그대로(출력 4,604, 관측 원자 최대 이동 0.0 Å). 기록의 개수와 보고서 주장이 독립 기대값과 같음 |
| R2 M7 통과 | 보완 8VF6이 두 물 정책에서 게시되고(게시 이벤트), 후보 집합 → M21 작업 제출이 200·`queued`(`openmm_preflight_failed` 없음) |
| R3 M20 인계(UI) | 보완 8VF6 + 원본 구조 기준 번호 대응·주석·fpocket 포켓으로 M20: 원본의 `klifs_key_site` 제외 일곱 자리(A/145 LYS·A/192 MET·A/193 GLU·A/194 LEU·A/195 CYS·A/264 THR·A/265 ASP)가 보완 구조에서도 그대로 제외, 설명이 필요한 그 밖의 제외 0. 위치 37개 중 `modeled_basis` 참 3(독립 기대 3), 틈 잔기 A/279 MET의 번호 대응·KLIFS 칸은 읽기에서 "검사 안 함(모델링 잔기)". SO1–SO3 표시, M20 보고서 `mutation_candidates_markdown@3`, 저장된 후보 집합 바이트는 M20이 만든 그대로 |
| R4a `completes` 구조(1HSG, UI) | 보완(OXT 2, 중원자 1,516) → M20 → M21 작업 `done`(`timeout_s` 240) → M21 보고서 `mutation_model_markdown@2`(구조 출처 절) → 합성 표시 페놀 SDF로 같은 조건 도킹 두 작업(야생형 참조·변이형) 모두 `done`, M18 보고서 구조 출처 절. 허용 공백 `receptor_atom_limit`은 쓰이지 않았다 |
| R4b 시간 상한 관측(8VF6) | M21 작업 하나(`timeout_s` 240)가 242.4초에 `failed`(`resource_exceeded`, 메시지 "job timeout"), 출력 handle 0, 모델 객체 0 → 0, 사용 단위 1 → 2(환불 없음), 남은 작업 프로세스 0. 도킹은 모델이 없어 `not_observed`(`no_model_time_limit`, 허용 공백) |
| R5 분류 표 | 26행 모두 문서 = 독립 분류 = 제품(아래 "구조 분류 표"). `in_scope`는 보완 → M20 → M21 입장까지 API로, `out_of_scope`는 사전 검사와 입장이 같은 코드로 거절하고 작업·단위 0 |
| R6 기본 거절 | 보완 1HSG를 API 대상 22곳에 보내 모두 422 `repaired_structure_not_accepted`, 객체·작업·단위·계획·보기·보고서 저장 0. 인벤토리·거절 시험 10 passed. R1·R3의 8VF6 run에서 구조 분석 탭의 선택 요소 15개 어디에도 보완 구조 선택지가 없고(원본 전처리 구조 선택지 3) 뷰어 소스는 원본 전처리 구조 |
| R7 입장 거절 | 1UBQ `nothing_to_repair`, 1S9I `gap_too_long`, R1의 보완 구조로 `already_repaired`, 합성 표시 소형 구조 다섯으로 `chain_identity_duplicate`·`unsupported_residue`·`unexpected_atoms`·`backbone_atoms_missing`·`gap_listing_missing`(독립 분류 = 사전 검사 = 제출 422). 작업·단위 0 |
| R8 MSE | 실제 결정구조 1RNH의 MSE 셋(A/47·A/50·A/142)이 두 물 정책에서 MET로 치환(파일의 MSE와 같은 셋), 화면 치환 표 3행·RP5 표시 |
| R9 다시 열기 | 두 번째 fixture 서버(이벤트만)에서 보완 기록·보완 구조·보완 보고서·M20 `@3` 보고서가 다시 열림. 저장된 M20 `@1` 셋·`@2` 하나·M21 `@1` 하나가 같은 바이트로 열림. 하류 읽기·보고서 시험 79 passed(보완 구조가 아닌 응답 바이트 동일 포함) |
| R10 JEV 경고(UI) | M24 단독·M25 단백질 루프의 미리보기·승인 화면에 JW1, 전송 0·dispatch 0, 미리보기 본문에 보완 사실 문자열 없음. M23 화면의 후보 집합 선택지에 "보완 구조" 배지. M23 보고서·읽기 파일(`sequence_ga_reports.py`·`sequence_ga_reads.py`) blob이 기준과 같음 |
| R11 금지어·비폭로 | 새 화면 글자 17개·새 보고서 글자 4개(보완 보고서, M20 `@3`·M21 `@2`·M18 `@2`의 구조 출처 절)에서 금지어 적중 0·유출 0, 고정 문장 내보내기와 문구 일치 |

- 외부·안전 관문(`summary.json`): 브라우저 비-loopback 0, 제공자 호출 0, dispatch 이벤트 0, 금지 라우트 전송 0(API 요청 508건), 프록시 시간 초과로 분류된 500 1건(R4a M21 시작, 최종 `done`, 해석 메모 N6), 그 밖의 5xx 0, 백엔드 서비스 로그 실패 줄 0(`backend-main.log`·`backend-reopen.log`), 남은 프로세스·포트 0, 기본 참조 폴더 `.deps/precedent_reference`·`.deps/reaction_reference` 전·후 없음.
- 관찰하지 못한 사례: 없다. 사례 수준의 `not_observed`는 0이고, 부분 수준의 허용 공백은 R4b 도킹 `no_model_time_limit` 하나다(그 이유와 조건은 N4).

## 구조 분류 표 (명세 §10.1, `acceptance/classification-table.md` 요약)
독립 분류는 `scripts/m29_oracle.py`, 제품은 사전 검사 읽기다. 26행 모두 문서 = 독립 분류 = 제품이고 결과 `pass`다. `m21_band` 출처의 "측정"은 T1 측정 표(`preflight.md` S1, 2026-10-13, 부하가 있던 한 기계, CPU 스레드 하나), "규칙"은 보완 뒤 단백질 중원자 수 구간(1,600 이하 `completes`, 2,200 이하 `near_limit`, 그 위 `exceeds`)이며 둘 다 독립 계산이 아니다(N5). 보완 종류는 수락에서 게시된 기록의 `classes_applied`다.

| 구조 | `strip_all` | `keep_all` | 보완 종류(수락 기록) | 보완 뒤 단백질 중원자 | `m21_band`(출처) | 수락에서 간 곳 |
|---|---|---|---|---|---|---|
| 1A30 | `in_scope` | `in_scope` | 곁사슬 1잔기(원자 6), `keep_all`은 + 체인 조각 합치기 | 1,542 | `completes`(측정) | 보완 → M20 → M21 `done`(두 정책) |
| 1HSG | `in_scope` | `in_scope` | OXT 2, `keep_all`은 + 체인 조각 합치기 | 1,516 | `completes`(측정) | M21 `done`(두 정책), R4a(UI, M21·같은 조건 도킹), R6(API 거절 대상) |
| 1RNH | `in_scope` | `in_scope` | OXT 1 + MSE→MET 3 | 1,207 | `completes`(규칙) | M21 `done`(두 정책), R8 |
| 4INS | `in_scope` | `in_scope` | 체인 조각 합치기만 | 806 | `completes`(규칙) | M21 `done`(두 정책) |
| 1CLL | `in_scope` | `in_scope` | 곁사슬 1잔기(원자 4) + OXT 1 | 1,135 | `completes`(규칙) | M21 `done`(두 정책) |
| 1AY7 | `out_of_scope(nothing_to_repair)` | `in_scope` | `keep_all`만 체인 조각 합치기(물 조각) | 1,466 | `keep_all`: `completes`(규칙) | `strip_all` 거절, `keep_all` M21 `done` |
| 1MQ4 | `in_scope` | `in_scope` | 곁사슬 8잔기 + OXT 1 + 틈 1(2잔기) | 2,160 | `near_limit`(측정) | M21 입장 열림 → 시작 전 취소(`cancelled_queued`) |
| 1M17 | `in_scope` | `in_scope` | OXT 1 + 틈 1(12잔기) | 2,594 | `exceeds`(측정) | M21 입장 열림 → 시작 전 취소 |
| 1A4I | `in_scope` | `in_scope` | 체인 조각 합치기 + OXT 2 + 틈 1(10잔기) | 4,476 | `exceeds`(측정) | M21 입장 열림 → 시작 전 취소 |
| 8VF6 | `in_scope` | `in_scope` | 체인 조각 합치기 + 곁사슬 23잔기(원자 91) + OXT 2 + 틈 2(13·11잔기) | 4,538 | `exceeds`(측정) | M21 입장 열림 → 시작 전 취소, R1·R3·R10(UI)·R6 뷰어 경로, R2, R4b(M21 시간 상한 실패 관측) |
| 1FIN | `out_of_scope(atom_limit_exceeded)` | `out_of_scope(atom_limit_exceeded)` | — | (합친 뒤 8,998, M7 상한 6,000 초과) | — | 사전 검사·제출 422, 작업·단위 0 |
| 1S9I | `out_of_scope(gap_too_long)` | `out_of_scope(gap_too_long)` | — (틈 27·34잔기) | (5,205) | — | 사전 검사·제출 422, 작업·단위 0 |
| 1UBQ | `out_of_scope(nothing_to_repair)` | `out_of_scope(nothing_to_repair)` | — (이미 M7 입구 조건 만족) | (602) | — | 사전 검사·제출 422, 작업·단위 0 |

- 모든 `in_scope` 행에서 관측 원자 최대 이동은 0.0 Å이다(`classification-table.json`의 `invariance`).
- `completes` 행의 M21 작업은 API로 `timeout_s` 240으로 돌았고 작업 이벤트의 처음–끝 간격은 1A30 116.6·116.5초, 1HSG 112.4·112.0초, 1RNH 67.1·67.0초, 4INS 31.0·31.0초, 1AY7(`keep_all`) 94.2초, 1CLL 58.0·58.1초였다. 이 값은 관측이고 `m21_band`의 출처가 아니다.

## 범위 표

| 번호 | 항목 | 이번 단계에서 보인 것과 못 한 것 |
|---|---|---|
| 1 | M21까지 끝난 구조 | 보완 1A30·1HSG·1RNH·4INS·1CLL(두 정책)과 1AY7(`keep_all`)의 11행: 보완 → M7 통과(게시) → M20 → M21 작업 `done`. M28까지 변이 모델링이 1UBQ에서만 보였던 한계(M28 범위 표 1번)는 이 구조들로 넓어졌다. 화면에서 M21 완료와 같은 조건 도킹까지 보인 것은 1HSG(R4a) 하나다 |
| 2 | 입장만 열리고 M21이 끝나지 않는 구조 | 8VF6·1M17·1A4I(`exceeds`)와 1MQ4(`near_limit`)의 8행: 보완 → M7 통과 → M20 → M21 입장(200·`queued`)까지 보이고 작업은 시작 전에 취소했다. M21 시간 상한 120/240초는 사용자 결정 ②로 그대로이며, 8VF6에서 한 번 돌려 시간 상한 결과를 관측했다(R4b, 242.4초, 환불 없음). 1MQ4는 T1 측정 233초로 상한 안이지만 여유가 약 7초라 수락에서 돌리지 않았다 |
| 3 | 보완 대상이 아니거나 거절된 구조 | 1FIN `atom_limit_exceeded`(조각 합치기 뒤 중원자 8,998), 1S9I `gap_too_long`(27·34), 1UBQ `nothing_to_repair`(이미 M7 통과), 1AY7 `strip_all` `nothing_to_repair`(물을 빼면 조각 분리가 없음)의 7행. 모두 작업·단위 0 |
| 4 | 화면(UI) 사례 | 8VF6(R1·R3·R10과 R6의 뷰어 경로), 1HSG(R4a), 1RNH(R8). 그 밖의 구조·사례(R2·R5·R6·R7·R4b)는 loopback API 수준이다 |
| 5 | 합성·대역·시험 전용 자료 | 아래 "합성·대역·시험 전용 자료" 표. 수락의 보완 작업은 모두 실제 PDBFixer 1.12.0 작업 모듈이 돌았다(대역 guardian은 시험에서만) |
| 6 | 검증하지 않은 것 | (a) M23 서열 GA를 보완 구조 후보 집합으로 실제로 돌린 것: 수락은 M23 화면 배지와 보고서·읽기 파일 blob만 봤고, 시험은 표시된 합성 대역 결과로 응답 계층만 본다. (b) 크기별 측정: M21 시간은 T1의 한 기계 측정(7구조)과 수락의 `completes` 관측뿐이고, 규칙으로 정한 구간(1RNH·4INS·1AY7·1CLL)과 크기·시간 관계를 따로 재지 않았다. 보완 작업 자체의 크기별 시간도 재지 않았다. (c) 실제 JEV 호출 0: JW1은 미리보기·승인 화면까지만 봤고 M24 `jev_choice_markdown@2`·M25 `jev_loop_markdown@2`는 수락에서 만들지 않았다(시험 `test_structure_repair_reports_downstream.py`가 가짜 게이트로 덮음). (d) 8VF6·1M17·1A4I의 M21 완료, 그 구조들의 M25 단백질 루프 계산, M21 모델을 수용체로 쓴 도킹은 관측하지 않았다. 보완 구조 후보의 M25 루프는 어느 구조에서도 계산 시작(M21 → M18)까지 가지 않았다(R10은 만들기·동의·미리보기·승인 화면까지). (e) M26 촉매 연결 결과의 M20 인계는 수락에서 만들지 않았다(R3은 번호 대응·주석·포켓). 촉매 인계는 합성 반응 세트를 쓴 시험으로만 덮였다. (f) PDB 형식 입력의 틈 보완과 `m7_condition_unsupported`(사슬 끊김), 틈 길이 경계(20·21), 입력 `calc_flag` 정리, 판정 불가(null) 체인 끝은 합성 자료 시험으로만 덮였다 |
| 7 | 외부 요청 | RCSB GET 5회 외 0건. 수락·게이트·시험은 네트워크를 쓰지 않았다. 구조 새로 받기·실제 JEV 호출은 하지 않았다 |
| 8 | 지원 환경 | 검증은 macOS arm64(Apple M3 Ultra, 착수 확인 기록) 한 기계의 프로젝트 `.venv`(OpenMM 8.6.0·PDBFixer 1.12.0·gemmi 0.7.5)에서만 했다. T2가 만든 시험 보조 `engine_hold`의 정확한 정지 판정은 macOS libproc에 기대고 다른 플랫폼의 psutil 대체 경로는 돌려 보지 않았다 |
| 9 | 범위 밖 | 위 "범위"의 하지 않은 것(명세 §1.2) |
| 10 | M20 저장값과 읽기 표시 | 모델링 잔기(틈 잔기·MSE→MET 잔기)는 저장 집합(해시 파일 형식)에 "검사함, 해당 없음"으로 남고, "검사 안 함(모델링 잔기)"은 M20 위치 읽기·화면과 M20 `@3` 보고서만 보인다(R3에서 틈 잔기 A/279 MET로 관측) |

### 합성·대역·시험 전용 자료

| 자료 | 성격 | 쓴 곳 | 이유 |
|---|---|---|---|
| `backend/tests/fixtures/structure_repair/synthetic-*.cif`·`synthetic-*.pdb` 12개(공개 1UBQ를 고친 것, 출처 `synthetic-fixtures.provenance.json`) | 합성 | 수락 R7의 다섯 거절. 시험의 틈 경계(20·21), PDB 형식 틈, 사슬 끊김(`m7_condition_unsupported`), 입력 `calc_flag`, 서열 없는 끝 | 로컬·RCSB 13구조에는 MSE 밖 비표준 잔기·뼈대 결손·템플릿 밖 원자·단백질 체인 이름 중복·`gap_listing_missing`·`m7_condition_unsupported`가 없다(`preflight.md` (a), `t3b-classification.tsv`) |
| `backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf` | 합성 | R4a 같은 조건 도킹, 하류 시험 | 구조에서 리간드 SDF를 뽑는 일은 범위 밖이다. 생물학적으로 의미 있는 자세가 아니라 경로의 기계적 확인이다(M28 선례) |
| 시험 안에서 만드는 SYNTHETIC 편집(1UBQ A48 LYS NZ 제거, 1UBQ A/30–32 틈 + A6 LYS CE·NZ 제거, 1CLL A20 ASP 곁사슬 제거, 4INS A6 CYS SG 제거, 1HSG 모델 번호 2·삽입 코드) | 합성 | 하류 읽기·보고서 형식 버전·M20 인계(`modeled_basis`의 금속·이황화 판정) 시험 | 작은 입력으로 하류 경로를 실제 작업 모듈로 돌리고 판정 조건을 만들기 위해. 파일 이름·주석에 SYNTHETIC 표시 |
| `_simulated_worker`(시험의 표시된 대역 guardian, `test_structure_repair_handoff.py`·`test_structure_repair_refusals.py`, 작업 시험의 게시 경계 검사) | 대역(PDBFixer를 실행하지 않음) | PDBFixer 측정 고정 자료의 추가 원자를 작업 출력으로 써서 제품 게시 경로(입장·승인·서버 검사·M7 사전 검사·게시 이벤트)를 지남 | 시험 시간. 수락의 보완은 모두 실제 작업 모듈이 돌았다 |
| `backend/tests/fixtures/structure_repair/*-additions.pdbfixer-measured.json`(1CLL·1HSG·1MQ4·1RNH·8VF6) | 합성 아님: 실제 PDBFixer 1.12.0 출력의 측정 고정 자료(출처 `pdbfixer-measured-fixtures.provenance.json`) | 위 대역의 출력, 빌더·검증기 시험 | 시험 입력이며 제품 값이 아니다 |
| `backend/tests/fixtures/structure_repair/reference-8vf6/` | 합성 아님: 로컬 참조 스냅샷 가공 행(SIFTS 8VF6·KLIFS STK33·UniProt Q9BYT3)의 바이트 그대로 사본, 시험 전용, kbase 전례 문구가 아님(`provenance.json`) | M20 인계 시험에서 `.deps` 없이 원본 8VF6의 번호 대응·주석 | 수락 R3은 이 사본이 아니라 M15 활성 세트의 읽기 전용 복사본(`--m15-reference`)을 썼다 |
| 시험의 합성 M26 반응 참조 세트(지어낸 PDB ID 둘) | 합성 | M20 인계의 촉매 연결 시험(관측 잔기·틈 잔기·MSE 잔기) | 범위 표 6 (e) |
| 시험의 합성 M23 결과 대역(`sequence_ga_result` 하나)과 합성 `residue_numbering_map@1` 대역 | 합성 | M23 읽기 응답의 `structure_origin`(응답 계층만), 거절 시험 | 실제 GA는 몇 분 걸리고 M23 읽기 모듈은 해시 고정이다. 보완 구조로는 번호 대응을 만들 수 없다 |

## 독립 검토 요약 (Opus 5.5, 구현하지 않은 서브에이전트)
근거는 Git 제외 조율 메모 `.dryforge/run-notes.md`(검토 원문은 커밋 증거에 없다).
- 구현 중 작업별 검토: T4(코어) 명세 위반 0, T7(M20 인계) 명세 위반 0, T5(작업·API)는 `needs-fix` 1건(게시 중 취소가 결과를 남기는 틈)과 권고(겹침 보기가 이벤트를 드러냄, 환경 없음이 증거 무효로 보임)를 T5 재작업에서 고쳤다(`docs/engineering-notes.md` M29 "게시와 끝 상태 기록은 한 전이 잠금 안에서 한다"·"게시 전 M7 사전 검사는 읽기 전용 겹침 보기로 돈다").
- 독립 코드 검토(T12, 고정 전, 세 갈래): 해시 파일 27개·`also_hashed_files`·골든·M13 변경 0을 A·B가 따로 확인했고, 닫힌 집합·고정 문장(RP1–RP6·SO1–SO3·JW1)이 명세 원문과 같으며, 고아 객체 없음 경로 시험(실패·취소·시간 초과·환경 없음)이 실효가 있다고 봤다. 막는 지적은 C1 하나였다: R4a 도킹 공백 판정이 정규식 때문에 원자 상한이 아닌 거절도 허용 공백으로 분류 → 정확한 코드·메시지 일치로(`24a4647f`).
- T13에서 고친 권고: A1 엔진 오류 메시지 300자 초과가 `fatal` 분류 오류(`43742f19`), B1 M20 `@3` 보고서에 "검사 안 함(모델링 잔기)" 사실 없음 → 주장 `repair_modeled_residue_position_count`와 줄 셋(`600c7e69`, 결정 0037 조율 17), B2 인벤토리 `*` 선언이 새 소비 지점을 통과시킴 → 정의별 선언(`46273bc9`), C2–C11 실행기·하네스 판정 보강(`24a4647f`·`b68a5533`). 같은 시기 T13 연습에서 드러난 프록시 시간 초과는 실행기 분류로(`5b01c72f`·`ac9e03ea`, N6), A3(나머지 그룹 시간)은 `12636a4b`와 고정 커밋의 재균형으로 처리했다(N13).
- T13 수정분 재검토(새 검토자 한 명): `approved`, 막는 지적 0. 권고 넷 중 셋은 고쳤고(R3 "정확히 일곱"이 fpocket 비결정성에 거짓 실패할 수 있음 → 그 밖의 제외를 설명하는 계산 `f357993b`, 인벤토리 클래스 단위 선언 → 정확한 qualname `90e57b56`, `nothingLeft`의 `lsof` 실패 처리 `f357993b`), 하나(새 statement id·subject 키·줄 셋의 문서화)는 T17 문서(결정 0037 조율 17, `docs/business-rules.md`, `docs/contracts.md`)로 반영했다.
- 고치지 않고 기록으로 옮긴 T12 관찰: 아래 "알려진 한계" 1·2·3·4·14·15와 결정 0037 조율 16. `scripts/AGENTS.md`의 그룹 수는 T17(`366edb29`)에서 고쳤다.
- 독립 증거·기록 검토(T19)는 아직 하지 않았다.

## 알려진 한계
1. 게시 직전 환경 상실(설치 템플릿·M7 엔진·프로세스 신원)은 명세 §4.4 닫힌 실패 집합 밖의 `error: precondition` + `reason_code` `openmm_unavailable`·`process_identity_unavailable`로 기록된다(의도, 결정 0037 조율 16, 객체 0, 환불 없음).
2. 망가진 보완 기록일 때 M25 루프 만들기·계산 시작·도킹 포기·끝내기 라우트가 이벤트를 기록한 뒤 보완 기록 검증 오류(422/412)로 답할 수 있다.
3. 화면은 게시 이벤트, 서버는 manifest `repair` 키로 보완 구조를 판별하므로 게시 이벤트 없이 부분 저장된 객체가 화면 목록에 일반 구조처럼 보일 수 있다(고르면 서버가 422).
4. 내려받은 보완 mmCIF를 다시 올리면 `calc_flag = c`가 남아 있어도 일반 구조로 다룬다(M21 모델 내려받기와 같음).
5. 입력 좌표가 소수 다섯째 자리 이상이면 작업 모듈의 PDBx 왕복(`%10.4f`) 때문에 `coordinates_changed`로 실패하고 1단위가 과금된다(사전 검사가 미리 알리지 않음, 로컬 구조는 셋째 자리).
6. 시간 초과 실패에는 `detail.reason_code`가 없다(`resource_exceeded`, 메시지 "job timeout").
7. 취소된 작업은 재시도 대상이 아니어서 그 run에서 그 전처리 구조를 다시 보완할 수 없다.
8. 객체 넷을 저장하는 도중 I/O가 실패하면 추가 전용 로그에 일부 객체가 남는다(읽기는 `valid: false`, 같은 작업의 재시도가 나머지를 채운다).
9. `timeout_s` 범위 오류는 API 모델 단계에서 먼저 나와 입장 순서(`unknown_field` 등)보다 앞설 수 있다(M21과 같음).
10. 틈 잔기·MSE→MET 잔기는 M20에서 새 위치(후보)가 될 수 있고 참조 보호가 연결되지 않으며, "검사 안 함(모델링 잔기)"은 M20 위치 읽기·화면과 `@3` 보고서에만 있다(후보 읽기·M21·M24·M25 화면과 저장 집합에는 없음).
11. M21 시간 상한 120/240초는 그대로라 보완 뒤 중원자가 큰 구조(8VF6·1M17·1A4I)는 M21 작업이 시간 상한 안에 끝나지 않는다(관측은 8VF6 M21 한 번의 242.4초 시간 초과·환불 없음, 1M17·1A4I는 T1 측정값 310·992초에서 옮긴 값; 사용자 결정 ②). 그 M21 작업을 쓰는 M21 수용체 출처 도킹도 같은 한계를 받는다고 보지만 관측하지 않았다. M25 루프의 모델 단계 작업은 `timeout_s` 120초 고정(`jev_loop_constants.STEP_TIMEOUT_DEFAULTS_S["model"]`)이라 T1 측정으로는 1A30(123초)·1MQ4(233초)의 모델 단계도 넘을 것으로 보지만 M25 계산은 이번에 실행하지 않았다. M23 개체 모델링은 구조 하나라 이 크기에서 측정하지 않았다(`docs/tracking/findings.md` 절 140).
12. 긴 동기 작업 시작 POST가 Next.js rewrite 프록시의 기본 30초 제한에 걸려 브라우저에 500이 보일 수 있다(R4a M21 시작에서 1건 관측, 작업은 계속되어 `done`, 화면은 저장된 작업을 읽어 복구, M29 전부터 있던 동작).
13. guardian이 그룹 구성원에게 pid 순서로 SIGTERM을 보내므로 pid가 한 바퀴 돈 뒤 엔진이 작업자보다 먼저 신호를 받으면 사용자가 취소한 행이 `engine_failed`로 기록될 수 있다(T2 발견, 제품 기존 경합, 고치지 않음).
14. M27 `link_kinase_precedents`에는 지도의 구조를 직접 거절하는 방어선이 없다(상위의 번호 대응에서 막혀 도달하지 않음).
15. 서버가 설치 템플릿을 읽은 뒤 파일이 실행 중에 바뀌면 캐시 때문에 서버를 다시 시작하기 전까지 412가 나지 않는다(검증 결과는 틀리지 않음).
16. 보완 구조에서는 "같은 구조 포켓 결과" 출처로 M20을 만들 수 없다(원본 구조 포켓 결과를 인계로 씀). MSE→MET 잔기가 포켓 lining에 있으면 `pocket_residue_mismatch`이지만 제품 경로에서는 M12가 MSE 구조를 먼저 거절해 닿지 않는다(순수 함수 시험으로만 고정).
17. JEV 전송 본문과 M23 보고서는 보완 사실을 담지 않는다(JW1 경고와 같은 후보 집합의 M20 `@3`·보완 보고서에만 있음).
18. 메운 틈 구간은 단순한 기하로 놓은 가상 좌표이고 충돌은 기록만 한다(예: 1MQ4 보완 곁사슬이 리간드와 1.24 Å, 2.0 Å 미만 5개, 결정 0037 "한계").
19. 큐가 STOP 뒤 guardian 답을 4초만 기다리는 경로는 guardian으로 취소하는 다른 작업 시험에도 있어 Stop 훅을 두 벌 이상 겹치면 시험이 흔들릴 수 있다(T2는 실패가 확인된 분석 흐름 시험만 고침).
20. 검증은 macOS arm64 한 기계에서만 했다(범위 표 8).

## 해석 메모 (사용자 확인을 구하는 것)
명세가 말하지 않았거나 세션이 정해 받아들인 읽기 중 수락 판정과 관련된 것이다. 결정 0037의 "조율 세션이 정한 것" 번호와 겹치는 것은 그 번호("결정 0037 조율 N")를 가리키고 이번 수락에서 실제로 어떻게 쓰였는지만 적는다. 각 메모는 무엇이 / 어떻게 정했나 / 왜 괜찮나 순서다.
- N1 R11 "비폭로 규칙". 명세 §10.3 R11은 낱말만 적었다. / 두 조건으로 읽었다: (a) 새 화면 글자·보고서 글자에 절대 경로·키 모양·placeholder가 없음(`m29_common.leak_kinds`, R11 `leaks` 21개 모두 빈 목록), (b) R10에서 만든 JEV 미리보기 본문(M24 단독·M25 루프, 보내지 않음)에 `repair`·`보완`·`structure_origin`·`calc_flag`·`obj://`·`/Users/` 문자열이 없음(하네스 `BODY_FORBIDDEN`, 증거 `bodyMentions: []`). / (b)는 명세 §6.4("전송 본문은 보완 사실을 담지 않는다")의 확인이고, 보완 사실은 JW1로 사람에게만 보인다.
- N2 R10의 클릭 범위. / 하네스는 M25 단백질 루프 만들기(탐색형, 반복 상한 1)와 run 수준 과학 전송 동의 켜기를 실제로 클릭하고 보낼 내용 만들기·승인 화면까지 가지만 확인 상자와 전송 단추는 누르지 않는다. 실행기는 하네스 단계마다 dispatch 이벤트 한도 0으로 감시해 하나라도 생기면 하네스와 백엔드를 바로 멈춘다. 결과 전송 0·dispatch 0·감시 발동 없음(`harnessDispatchGuard: false`). / 동의 켜기는 QA 격리 run에 이벤트를 남기는 쓰기이지만 외부 요청이 아니고, 서버의 외부 게이트는 스크립트 없는 `MockTransport`라 전송이 나갈 수 없다.
- N3 R6가 덮은 범위. / API로 보낸 22곳(`compute_interactions`·`compute_interface_sasa`·`measure_distance`·`align_structures`(기준·이동 두 자리)·`compile_state`·`map_residue_numbering`·`link_reaction_knowledge`, M7 사전 검사 읽기·최소화 작업, PyRosetta 작업 둘, M12 사전 검사 읽기·fpocket 작업, M11 미리보기·준비 작업, 뷰어 세션·저장된 보기·그림, 점검 보고서, `inspect_complex`, M13 계획)과 시험으로 덮은 곳(`annotate_reference_sites`는 번호 대응 앞단에서 막힘, M27은 번호 대응만 받음, 뷰어 의도, `/method_reports`는 거절된 도구·작업의 결과만 받음, M13 모듈은 계획 라우트 입구: `test_structure_repair_consumers.py`의 `blocked_upstream` 선언과 `test_structure_repair_refusals.py`). / 인벤토리 시험이 정의마다 선언이나 거절 호출을 요구하므로 새 소비 지점이 빠지면 게이트가 실패한다.
- N4 R4a·R4b와 허용 공백 둘(결정 0037 조율 18). / 허용 공백은 R4a 도킹 `receptor_atom_limit`(하네스가 본 도킹 거절이 모두 M18의 정확한 원자 상한 거절이고 입력 파일과 템플릿으로 계산한 수용체 원자 수 하한이 10,000을 넘을 때만, 1HSG는 약 3,100이라 그 거절이 나오면 `fail`)과 R4b 도킹 `no_model_time_limit`(시간 상한으로 모델이 없음)뿐이다. 이번에는 R4a 도킹이 두 작업 모두 `done`이라 R4a 공백은 쓰이지 않았고 R4b 공백 하나만 쓰였다. / R4b는 한계 관측이지 모델링 성공이 아니며, 다르게 나왔으면(결과가 남거나 단위가 환불되거나 프로세스가 남으면) `fail`이다.
- N5 `m21_band`의 출처. / 측정 표가 있는 일곱 구조(1UBQ·1HSG·1A30·1MQ4·1M17·1A4I·8VF6)는 T1 측정 상수(`scripts/m29_common.py`의 `M21_BAND_MEASURED`), 측정이 없는 넷(1RNH·4INS·1AY7·1CLL)은 보완 뒤 단백질 중원자 수 구간 규칙이다. 분류 표의 출처 열이 둘을 구분한다. `acceptance/classification-table.md` 머리말은 실행기가 만든 문장이라 `m21_band`를 모두 "T1 측정 표 상수"라고 적었는데, 7행(1RNH·4INS·1CLL 두 정책씩, 1AY7 `keep_all`)은 규칙이다(실행기는 고정 뒤라 고치지 않았고 이 메모와 표의 출처 열이 정정한다). 수락은 `completes`만 M21 작업 완료를 요구했고 API 사례는 `timeout_s` 240으로 돌렸다. / 측정은 부하가 있던 한 기계의 값이고 규칙은 독립 계산이 아니므로 구간은 문서화한 사실로만 쓴다. 규칙으로 정한 넷은 수락에서 모두 `done`이었다(31.0–94.2초). 1HSG는 기본 120초 안의 여유가 약 1.5초라(T1) 부하가 있으면 넘을 수 있다.
- N6 실행기 안전 제약과 프록시 시간 초과 분류(결정 0037 조율 19 (a)). / 실행기는 `mw`를 import하지 않고 loopback API에 GET과 run 만들기·업로드·명령·작업 제출·승인·시작·취소·R6 거절 탐침 POST만 보내며, 한도 증액과 `/jev`·`/jev_loops` 쓰기 라우트는 `m29_common.Api`가 거절한다(API 요청 508건, 금지 라우트 전송 0). 화면이 받은 500은 POST `/api/runs/<run>/jobs/<job>/start`이고 같은 run·job의 프런트 로그 `Failed to proxy … socket hang up` 줄이 500 하나에 한 줄 있고 단계 뒤 작업이 끝 상태일 때만 `proxyTimeouts`로 분류한다. 이번에는 R4a M21 시작 1건(`job_3b64933a…`, 최종 `done`)이 그렇게 분류됐고 그 밖의 5xx는 0이다. / 백엔드 오류가 아니라 M29 전부터 있던 프록시 동작이며(알려진 한계 12), 그 밖의 5xx는 관문 실패로 남는다.
- N7 백엔드 로그 관문(결정 0037 조율 19 (b)). / `noBackendTraceback`은 백엔드 서비스 로그에 Traceback·ASGI 예외·Internal Server Error 줄이 하나라도 있으면 실패다. 이번에는 `backend-main.log`·`backend-reopen.log` 모두 0줄이다. / 500을 프록시 시간 초과로 분류하는 규칙이 서버 예외를 덮지 않게 하는 보완이다.
- N8 R3 설명 계산(결정 0037 조율 19 (c)). / 원본 집합의 `klifs_key_site` 제외가 문서의 일곱 자리를 모두 담고, 그 밖의 제외는 저장된 원본 포켓 결과·입력 파일로 다시 센 5.0 Å 리간드 껍질·직접 잔기 중 하나로 설명될 때만 받는다(fpocket이 실행마다 다를 수 있음). 이번에는 원본·보완·문서 셋이 같은 일곱 자리였고 설명이 필요한 그 밖의 제외는 0이었다(`extra: {}`, `unexplained: []`). / 거짓 실패와 거짓 통과를 함께 막는다.
- N9 R2의 "M7 통과" 근거. / M7 단독 최소화 라우트는 보완 구조를 거절하므로(§5.2) 관측 경로로 쓰지 않고, 게시 전 검증 4(M7 사전 검사, 읽기 전용 겹침 보기)를 통과해야만 나오는 게시 이벤트와 M21 입장(200·`queued`)을 근거로 했다. / 게시는 M7 사전 검사를 통과한 뒤에만 일어나므로 같은 사실을 가리킨다.
- N10 M23은 화면 표시만(명세 §6.3). / R10은 M23 화면의 후보 집합 선택지 배지 "보완 구조"와 `sequence_ga_reports.py`·`sequence_ga_reads.py` blob이 기준과 같음을 봤고, M23 GA를 보완 구조로 돌리지 않았다. 시험의 M23 쪽은 합성 대역 결과로 `app.py` 응답 계층의 `structure_origin`만 본다. / M23 모듈이 해시 고정이라 바꿀 수 없고, 실제 GA 실행은 범위 표 6 (a)의 관찰 공백으로 남는다.
- N11 화면 보완 작업 시간과 API 사례의 차이(T11 해석). / 화면은 보완 작업에 늘 기본 `timeout_s` 120을 보내고(`REPAIR_TIMEOUT_DEFAULT_S`, 화면에 "고정값으로 보냄"), API 사례는 240을 보낸다(`REPAIR_TIMEOUT_S`). R1의 8VF6 보완은 화면 120초 안에 끝났다. / `timeout_s`는 호출 키에 들어가지 않고 상한 240 안의 조정 가능한 기본값이다.
- N12 T11 연습과 공식 수락의 관계. / 연습(T11 전체 연습과 T12 수정 뒤 부분 연습 07a–07h)은 고정 전 코드에서 돌았고 증거로 세지 않는다. 연습 관찰(Git 제외 조율 메모): 전체 연습 12사례 `pass`·약 28.5분, R4b 242.7초, M21 시간 1A30 117·1HSG 114·1AY7 96·1RNH 68·1CLL 59·4INS 31초. T13이 작업 모듈을 고쳐 보완 작업 호출 키가 바뀌었으므로 연습의 보완 작업은 재사용되지 않고, 연습 run에 저장된 M20 `@3` 보고서는 새 코드에서 다시 열리지 않아 폐기했다(결정 0037 "수용한 대가"). 공식 수락은 고정 뒤 새 `--root`에서 한 번 돌았다. / 공식 값(R4b 242.4초, `completes` 31.0–116.6초)은 연습과 몇 초 안에서 같았고 판정은 공식 수락만 쓴다. 연습 값에는 커밋 증거 파일이 없다.
- N13 게이트의 그룹 재균형(결정 0037 조율 20). / 고정 직전 진단에서 모든 그룹을 함께 돌리면 나머지 그룹이 414.3초여서 중간 크기 파일 여섯(`test_jobs.py`·`test_ligand_worker.py`·`test_ligand_jobs.py`·`test_mutation_tool.py`·`test_jev_ast.py`·`test_site_annotation_reports.py`)을 M27 그룹으로 옮겼고(고정 커밋 `52aa4265`), 진단 둘째 시도에서 가장 긴 그룹이 371.4초가 됐다. 고정 게이트 1회째에서 나머지 그룹은 3,894개 323.8초이고 가장 긴 그룹은 `test_ligand_ga_jobs.py` 그룹(377.9초)이며 `test_chemical_interactions.py`(375.3초)·M18 도킹 그룹(376.1초)이 뒤를 잇는다. / 진단 시도는 게이트가 아니고, 게이트 세 회차 모두 제한 480초 안(여유 약 100초)이다. M29 동안의 Stop 훅 실패(부하·편집 중 상태)는 진단 기록일 뿐 게이트 통과가 아니다(`docs/engineering-notes.md` M29 함정).
- N14 R9가 기대는 Git 제외 자료. / R9는 M28 fixture 단계 폴더(`--saved-report-runs`, 기본 `runs/m28-fixture-20261012/fixture`)의 저장된 M20 `@2`·M21 `@1` 보고서와 커밋된 M20 `@1` fixture를 다시 연다. 그 폴더는 Git 제외라 다른 체크아웃에서는 R9가 `not_observed`(`saved_report_fixture_missing`)가 되어 `acceptance`가 거짓이다. / 이번 기계에는 그 폴더가 있었고, 저장 바이트 비교는 그 폴더의 이벤트만으로 했다.

## 업그레이드 뒤 사용자가 할 일
`docs/operations.md` "업그레이드 뒤 할 일"의 M29 항과 같다.
1. 사용자가 할 데이터 이전은 없다. 호출 키 해시 파일 27개·`also_hashed_files`·골든 셋과 `backend/pyproject.toml`·`frontend/package.json`·`frontend/package-lock.json`은 바뀌지 않았다(PDBFixer 1.12.0은 M21부터 프로젝트 `.venv`에 있다). 그래서 저장된 M18·M19·M21·M22·M23 결과의 자동 재사용과 큐에 있던 작업은 그대로이고 `.deps` 작업 환경·참조 폴더·환경 변수도 바꿀 것이 없다.
2. 화면(단백질 공학 탭의 "구조 보완" 영역 등)과 `config/tools.yaml`(새 도구 `repair_structure`)이 바뀌었으므로 프런트엔드를 다시 빌드하고(`npm --prefix frontend run build`) 백엔드를 다시 시작한다.
3. 이미 저장된 보고서(M20 `@1`·`@2`, M21·M18·M24·M25 `@1`)는 같은 바이트로 다시 열린다. 새 형식 버전(M20 `mutation_candidates_markdown@3`, M21 `mutation_model_markdown@2`, M18 `ligand_docking_markdown@2`, M24 변이 `jev_choice_markdown@2`, M25 단백질 `jev_loop_markdown@2`)은 보완 구조에서 나온 결과의 보고서를 새로 만들 때만 쓰인다.
4. 보완 작업의 호출 키에는 작업 모듈 `jobs/structure_repair_worker.py`와 의존 파일 다섯(`structure_repair.py`·`structure_repair_constants.py`·`jobs/openmm_worker.py`·`tools/openmm_method.py`·`mutation_model_constants.py`)의 해시가 들어간다. 다음 업그레이드에서 이 중 하나가 바뀌면 같은 전처리 구조의 보완은 재사용되지 않고 새 작업(1단위)이 되며, 큐에 있던 보완 작업은 시작 때 예약 전에 412 `worker_version_invalid`로 막히므로 취소하고 다시 제출한다.
5. 옛 단계 수락 실행기(M13–M26)를 돌릴 때는 `.deps/precedent_reference`·`.deps/reaction_reference`를 없는 채로 둔다(M26–M28과 같음). 다른 사람과 공유할 때 `runs/`(M29 QA 격리 root `runs/m29-*` 포함), `.deps/`, `.env`, `frontend/tests/offscreen/artifacts/`(M29 `m29-repair/` 포함)를 뺀다.
6. 후속 사용자 결정 후보(이번 단계에서 하지 않음): M21 시간 상한 상향(해시 파일 `mutation_model_constants.py` 변경이라 M21·M23 호출 키·골든 재기록이 따르고, 8VF6은 M21 작업 하나(구조 둘)에 17분 이상이다. M23 개체 모델링은 구조 하나라 측정하지 않았다). 1MQ4 보완 곁사슬과 리간드의 1.24 Å 근접은 기록만 했다(충돌로 보완을 거절하지 않는다는 사용자 결정 ①).

## 증거 위치

| 경로(`docs/qa/m29-repair-20261013/` 아래) | 내용 |
|---|---|
| `preflight.md`, `probe/` | 착수 확인 T1(독립 분류, 소비 지점 인벤토리, 새 원자 표지, M20 인계, 보고서, 겹침 보기, PDBFixer·M21·M18 측정 표, 간헐 실패 가설, RCSB 후보, 8VF6 추가 원자 고정 자료) |
| `network-ledger.txt` | RCSB 네 구조(1RNH·4INS·1AY7·1CLL)의 상태·바이트·URL·SHA-256(8VF6 장부는 Git 제외 `runs/stk33-8vf6-20261013/network-ledger.txt`) |
| `t3b-classification.tsv` | RCSB 네 구조의 독립 분류 |
| `t2-flaky-tests.md`, `t2-flaky-tests.txt` | 간헐 실패 시험 고정 T2(재현·원인·고친 것·계열 C 연속 3회, 전체 출력은 Git 제외 `frontend/tests/offscreen/artifacts/m29-repair/t2/`) |
| `gate.txt`, `gate-raw/` | 고정 `52aa4265` 게이트(세 회차, 그룹별 시간, 차례로 돌린 명령, 그룹 수 메모) |
| `acceptance/` | 수락 T15(`README.md`·`summary.json`·`cases.json`·`classification-table.md`·`.json`·`binary-artifacts.json`·`SHA256SUMS`·`evidence/`: 대장 `case-ledger.json`, 단계 기록 `steps/`, 계획 `plans/`, 사례 증거 `evidence/`, pytest 로그 `pytest/`) |
| `regression/` | 회귀 사슬 T16(결과는 위 정의 항목 ⑤) |

Git 제외: 수락 스크린숏·화면 글자·내려받은 mmCIF `frontend/tests/offscreen/artifacts/m29-repair/acceptance-20261014/`, QA run `runs/m29-acceptance-20261014/`, 조율 메모 `.dryforge/run-notes.md`. 커밋한 검증 입력은 `backend/tests/fixtures/public_{8vf6,1rnh,4ins,1ay7,1cll}.cif`(+ `.provenance.json`)와 `backend/tests/fixtures/structure_repair/`다.

## 다시 돌리는 방법 (주 체크아웃 루트, 8000·3000 포트 비움, 한 번에 하나)
```bash
# 수락(모든 단계, 새 --root·--artifacts·--out, 실호출 0·내려받기 0)
.venv/bin/python scripts/m29_offscreen_acceptance.py --root runs/m29-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m29-repair/acceptance-<날짜> \
    --out docs/qa/m29-repair-<YYYYMMDD>/acceptance
```
필요한 것(프로젝트 `.venv`의 OpenMM·PDBFixer, `.deps/fpocket`·`.deps/docking`·`.deps/qvina`, M15 활성 세트, M28 fixture 단계 폴더)과 연습·회귀 사슬 명령은 `docs/operations.md` "M29 구조 보완 수락 QA"에 있다.

## 남은 일
- 독립 증거·기록 검토(T19)와 그 반영(T20), `CLAUDE.md`·`AGENTS.md`의 M29 줄(정의 항목 ⑦), `docs/tracking/status.md`·`roadmap.md` 마무리.
- 해석 메모 N1–N14와 결정 0037의 "조율 세션이 정한 것"에 대한 사용자 확인. 판정 문구와 병합은 사용자 확인 뒤 메인 세션이 한다.
- 새 미해결 문제(위 "알려진 한계")는 `docs/tracking/findings.md`의 M29 절에 있다.
