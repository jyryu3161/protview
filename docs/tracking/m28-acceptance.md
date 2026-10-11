# M28 종단 검증과 마감 기록

- 판정: **검증 통과, 사용자 확인 대기** (QA 2026-10-11 UTC, 기록 2026-10-12). 두 단계 대장을 합친 정의 6항목이 모두 `pass`이고(아래 "정의 6항목"), fixture 단계와 실제 live 단계의 `acceptance`가 모두 참이며, 독립 증거·기록 검토(T19)의 지적을 모두 문서·증거 텍스트 수정으로 반영했다(아래 "독립 검토 요약"). 명세 §3.3의 `보류` 사유 — (a) 통과하지 못한 항목이 있거나, (b) `호출 키 해시 파일·닫힌 집합·고정 문장·상한을 바꿔야 하는 결함이 남았거나`(명세 문구 그대로), (c) 남은 `fail` 사례가 있거나, (d) 실호출 결과가 `completed`가 아닐 때 — 중 (a)·(c)·(d)는 해당하지 않는다. (b)는 해석에 기댄다: 남은 `사용자 결정 필요` 항목 중(그리고 `수용` 일부에도) 고치려면 이런 변경이 필요한 절이 있다는 점을 N10의 해석(결함이 아니라 이월된 한계로 읽음, 사용자 확인 필요)으로 셈해 (b)에 넣지 않았다(해당 절은 N10에 열거). 사용자가 다르게 읽으면 판정은 `보류`가 된다. 판정 문구를 명세 §3.3의 셋째 값으로 바꾸는 것은 사용자가 확인한 뒤에만 메인 세션이 한다(아래 "사용자 확인 기록"). 사용자 결정 필요로 남은 미해결 문제는 85개다.
- 브랜치: `dryforge/m28-final-verification`(단계 브랜치 `phase/m28-final-verification` = main `287a37a8`에서 분기, M27 main 병합 `b7d7f49` 포함). 문서·실행기 뼈대 일부는 git worktree의 하위 브랜치에서 하고 작업 브랜치에 병합했다.
- 고정 소스: `a18dd488`(M28 T11: second review fixes on the real-call path). 고정 뒤 허용 경로는 명세 §8.2의 (a) `docs/**`·`README.md`·`CLAUDE.md`·`AGENTS.md`와 (b) 회귀 사슬이 요구하는 옛 하네스·실행기 기대 수정이고, (b)는 필요 없었다(`regression-harness-changes.txt` 없음). 이 기록을 쓰기 직전(`f44c8c10`) `git diff --name-only a18dd488..HEAD`는 936개 경로로, `docs/**` 933개(증거 `docs/qa/m28-final-20261011/` 925개 + 문서 `business-rules.md`·`contracts.md`·`engineering-notes.md`·`operations.md`·`security.md`·`standards.md`·`system-architecture.md`·`tracking/findings.md` 8개), `README.md`, `scripts/AGENTS.md`, `frontend/AGENTS.md`뿐이다. 마지막 두 파일은 명세 §8.2 (a)의 "AGENTS.md"를 이름이 `AGENTS.md`인 모든 문서로 읽어 허용했다(문서이며 코드·시험·훅이 읽지 않는다. `gate.txt` 끝 "note on the post-freeze path set", 해석 메모 N8). 실제 live 단계(`ec21309d`에서 실행) 뒤의 변경은 `docs/**`·`README.md`·`CLAUDE.md`·`AGENTS.md`·`scripts/AGENTS.md`뿐이다(T20 기점 `93f4ed8e`에서 `git diff --name-only ec21309d..HEAD`의 문서 밖 경로가 이 넷이고 나머지는 `docs/**`. 모두 명세 §8.2 (a)의 문서이며 `scripts/AGENTS.md`는 N8의 해석. `frontend/AGENTS.md`는 live 전 T17 `0f79d8fd`에서 바뀌어 `a18dd488..HEAD`에는 있고 `ec21309d..HEAD`에는 없다). 이 기록의 커밋(T18b `82ce1758`)은 `docs/**`·`README.md`·`CLAUDE.md`·`AGENTS.md`만, T20 반영 커밋은 거기에 `scripts/AGENTS.md`(아래 독립 검토 요약의 D)를 더한 문서만 바꾼다.
- `CLAUDE.md`·`AGENTS.md`: 구조(절 순서·표·트리)는 그대로이고(사용자 결정 ⑥) 머리말, M28 항, 구조 트리의 표기 두 줄(22–23행: 완료 기록 목록 끝 `m27-acceptance.md` → `m28-acceptance.md`, 결정 기록 범위 `0001–0035` → `0001–0036`)만 바꿨다. 트리 두 줄은 새 파일을 가리키는 표기 갱신이며 구조 불변 원칙 안이다(`git diff phase/m28-final-verification -- CLAUDE.md`, 두 파일은 `cmp` 동일).
- 증거를 만든 소스: 게이트 `a18dd488`, 설치 시험 `6da1670a`, 종단 fixture 수락 `8e96c142`, 회귀 사슬 `5a5ba3f2`, live 연습 `e6889653`, 실제 live `ec21309d`. 모두 `a18dd488`에 문서·증거만 더한 커밋이다(`git diff --name-only a18dd488..<커밋>`의 문서 밖 경로 0개, 수락 대장의 빌드 도장 `buildCurrentWithSource: true`·작업 트리 변경 0).
- 결정: 0036(사용자 결정 ①–⑩ 2026-10-11, `docs/tracking/decisions/0036-m28-final-verification.md`).
- 수락 증거: `docs/qa/m28-final-20261011/`(아래 "증거 위치"). 큰 증거(스크린숏·paint 프레임·보고서 내려받기·256 KiB 초과 텍스트)는 결정 0020에 따라 Git 제외 `frontend/tests/offscreen/artifacts/m28-final/`에 있고 커밋 증거에는 경로·크기·SHA-256만 있다(옛 실행기 회귀 증거 `regression/`에 커밋된 내려받기 파일 110개는 해석 메모 N14).
- 외부 요청: 사용자가 정한 실제 JEV 호출 2회(둘 다 `completed`)와 새 컴퓨터 설치 시험의 패키지 저장소 내려받기(`pypi.org`·`files.pythonhosted.org`·`registry.npmjs.org`, `github.com` 0건)뿐이다(`network-ledger.txt`). 그 밖의 새 외부 요청은 0건이다.
- 커밋 증거의 키·placeholder·실제 kbase 문구·사용자 절대 경로: 실행기 내보내기 검사에서 걸린 파일 0개(fixture·live·연습 세 단계 모두 `exportScan.ok: true`, `files: {}`, 키·placeholder 적중 0). 절대 경로는 `<repo>`·`<home>`으로 바꿨다.

## 범위
M0–M27이 만든 제품을 로드맵 "완성의 정의"(`docs/tracking/roadmap.md`) 여섯 항목에 비추어 로컬 공개 실데이터로 끝까지 돌려 보고 문서·미해결 문제를 마감했다. 새 기능은 만들지 않았다. 한 일은 다섯 가지다: 세 분기(A 구조 분석·지식, B 리간드 설계·탐색, C 단백질 공학)의 실제 Electron 오프스크린 클릭 종단 검증(새 실행기 `scripts/m28_offscreen_acceptance.py`), 실제 JEV 호출 2회, 회귀 사슬·게이트 전량과 새 컴퓨터 설치 시험, 코드 수정 둘(간헐 실패 시험 넷, M20 보고서 참조 출처표), 문서·미해결 문제 마감. 범위 밖은 아래 범위 표 8번이다.

## 결과물 (작업별)

| 작업 | 내용 | 커밋 |
|---|---|---|
| T1 착수 확인 | 기준선(해시 파일 27개·골든 셋), 자료(보관 반응 세트 `1a7b131a…`, kbase HEAD `77354f9`·핀, M15 세트 `aa21ead9…`), M7 사전 검사 표(8구조 × 물 정책 2), 사례 사슬 지도, 시간·예산·GA 설정 둘, 간헐 실패 원인, M20 보고서 출처표 설계, 미해결 문제 수, 설치 준비, Stop 훅 여유, 역추적 감사 어댑터 20종 | `57f2d0e7` |
| T2 간헐 실패 시험 | 시험 쪽 원인 넷을 고침(`test_sequence_ga_worker.py`·`test_pocket_jobs.py`·`test_jev_reports.py`), 제품 코드 변경 없음 | `bc1e180b` |
| T3 M20 보고서 출처표 | `backend/mw/mutation_reports.py`: 참조값을 인용하는 새 보고서만 `mutation_candidates_markdown@2`(스냅샷 출처·이용 조건 표), 저장된 @1은 같은 바이트로 다시 열림. 시험과 @1 보고서 run 로그 fixture | `7812289b`, `f4ec1b6b` |
| T4 README·설치 문서 | README를 현재 기능·설치·검증 진입점 중심으로 다시 쓰고 `python3.11 -m venv`로 바로잡음, `docs/operations.md` 필요 조건·처음 설치 | `34160f2c`(병합 `1c1296dc`) |
| T5 실행기 뼈대 | `scripts/m28_offscreen_acceptance.py`·`m28_common.py`·`m28_trace_audit.py`·`m28_export_fixed_sentences.py`, 단위 시험, 실호출 대장 | `f180f241`(병합 `38dc02dd`) |
| T6–T8 분기 하네스 | `scripts/m28_branch_{a,b,c}.py`, `frontend/tests/offscreen/endtoend-{a,b,c}-flow.cjs`, `scripts/test_m28_branch_{a,b,c}.py` | `675301b2`, `73a7a36e`, `4dbb4046` |
| T9 배선 | 분기 등록, X4 줄 단위 예외 19개, npm 스크립트 `test:offscreen:endtoend` | `19207f31` |
| T10–T11 독립 코드 검토와 수정 | 검토 셋의 막는 지적 반영(아래 "독립 검토 요약") | `9c5d49eb`, `c1644221`, `a18dd488` |
| T12 소스 고정·게이트 | 고정 `a18dd488`, 게이트 기록 | `902a7595`, `8935ba01` |
| T13 설치 시험 | 새 로컬 클론에서 README 명령만, Electron 문장 정정 | `8e96c142` |
| T14 종단 fixture 수락 | `acceptance-fixture/` | `5a5ba3f2` |
| T15 회귀 사슬 | M27 → M26 → M25(M24 … M13) | `72c024a2`, `72f7cdfa` |
| T16 실제 JEV 호출 2회 | 연습 증거, 실제 live 증거, 장부 줄 | `ec21309d`, `2ccdd5ad` |
| T17 문서 마감 | 구조·운영·규칙 문서, 모듈 안내 | `0f79d8fd`(병합 `a5e07c81`), `6da1670a` |
| T18 기록 | 미해결 문제 최종 분류(T18a), 낡은 문장 세 곳 정정(커밋 메시지의 "four"는 실제로 셋), 이 기록·상태 문서·결정 0036(T18b) | `285cdff5`(병합 `e6889653`), `f44c8c10`, `82ce1758`(병합 `05585ac5`), `93f4ed8e` |
| T19 독립 증거·기록 검토 | 검토자 둘(증거 쪽·문서 쪽), 읽기 전용(아래 "독립 검토 요약") | 커밋 없음 |
| T20 반영 | 증거 쪽 지적은 조율 세션이 증거 텍스트로(장부 시각, 설치 호스트 절, 게이트 원 로그, 회귀 사슬 기록), 문서 쪽 지적 A–G는 이 기록·미해결 문제·상태·결정·모듈 안내 문서로 | `5b4ad1f5`, `210e8ded`, T20 문서 커밋 |

## 사용자 결정 (2026-10-11)
근거는 결정 0036. 사용자는 모든 질문에서 추천안을 골랐다(자유 입력·메모 없음): ① 실데이터 = 저장소와 이 컴퓨터에 있는 로컬 공개 구조·자료만, 새 외부 요청 0 ② 실제 JEV 호출 2회(리간드 루프 한 바퀴 + 단백질 루프 한 바퀴) ③ 새 기능 없음(Linux 잠금·다른 탭 알림·run 전체 작업 목록·GPCR은 범위 밖으로 기록) ④ 미해결 문제 = 선별 수정 + 최종 분류 ⑤ 판정 문구 = 범위를 명시한 완성 문구(사용자 확인 뒤에만) ⑥ 문서 = 최신화 + 빈틈 메우기(`CLAUDE.md` 구조 그대로) ⑦ 설치 시험 = 핵심 설치를 새로 시험, 선택 환경은 정적 확인 ⑧ 통과 규칙 = 분기 하나에서 끝까지 + 완성 문구는 사용자 확인 뒤에만 기록 ⑨ 코드 수정 = M20 보고서 출처표(보고서 형식 @2)와 간헐 실패 시험뿐(POST JSON 형식 검사·M20 v2 "0 저장" 변경은 하지 않음) ⑩ QA = fixture 회귀 전량 + M28 실데이터 단계. 사용자에게 묻지 않고 조율 세션이 정한 것(실호출 대상 목표, 실패한 호출도 할당에서 셈, 실행 순서, @2 규칙, B2 입력, A1 기본 정책, 감사 예외 등)은 결정 0036과 아래 해석 메모에 있다.

## 정의 6항목 (두 단계 대장을 합친 최종 상태)
최종 상태는 `scripts/m28_common.combine_items`의 규칙(fixture 대장의 각 부분 + 항목 5만 live 대장의 `live` 부분)으로 두 단계 대장(`acceptance-fixture/evidence/case-ledger.json`, `acceptance-live/evidence/case-ledger.json`)을 합친 값이다. 값은 `pass`·`fail`·`not_observed` 셋뿐이다.

| 항목 | 자료 | 분기 | 사례 사슬 | fixture 대장 | live 대장 | 최종 |
|---|---|---|---|---|---|---|
| 1 구조 분석 | 공개 `public_1m17.cif`(EGFR 키나아제 도메인 + AQ4) | A | A1 → A2 → A3 → A4 → A6 | `pass`(chain) | 해당 없음(null) | **pass** |
| 2 지식 | M15 활성 세트 복사본(1M17 A, 1FIN A·C, 1MQ4 A), M16 주석, 로컬 `kbase_kinase`를 M27 가져오기 명령으로 격리 설치한 세트, M26 보관 실세트(`.deps/reaction_qa/import2`)의 격리 복사 + 공개 1S9I·1A30·1A4I | A | 키나아제 A5 → A6 → A7, 효소 A8 | `pass`(kinase `pass`, enzyme `pass`) | 해당 없음 | **pass** |
| 3 리간드 설계·탐색 | ProLIF 공개 예제 준비 수용체·포즈, 공개 파생 부모 SDF, 합성 표시 building block·반응 규칙 | B | B2 → B3 → B4 | `pass`(chain) | 해당 없음 | **pass** |
| 4 단백질 공학 | 보호: 공개 1A30 + M26 보관 실세트. 모델링·평가: 공개 1UBQ + 합성 표시 페놀 SDF | C | 보호 C1, 모델링·평가 C2 → C3 | `pass`(protection `pass`, modelling `pass`) | 해당 없음 | **pass** |
| 5 GA·JEV | B·C 자료와 같음. B6·B7·C5·C6은 M25 fixture 서버, L-B7·L-C6은 제품 백엔드의 실제 `SCIENCE_GATE` | B, C | 리간드 B5(설정 둘)·B6·B7, 단백질 C4(설정 둘)·C5·C6, live L-B7·L-C6 | `pending_live`(ligand `pass`, protein `pass`, live 비어 있음) | `pass`(live `pass`: L-B7·L-C6 둘 다 `completed`) | **pass** |
| 6 보고서 | 위 사례들이 만든 저장 보고서 | A, B, C | A2–A8의 보고서, B8, C7, X1-A·X1-B·X1-C, X2 | `pass`(reports·lists·audit) | 해당 없음 | **pass** |

## 범위 표
명세 §3.2의 1–10번은 처음부터 정해진 항목이고 11–18번은 실행과 독립 검토에서 늘어난 항목이다. "실모델 미관찰" 면제는 필요 없었다(두 실호출 모두 `completed`).

| 번호 | 항목 | 이번 단계에서 보인 것과 못 한 것 |
|---|---|---|
| 1 | M7 사전 검사 결과 | 로컬 공개 구조 8개 × 물 정책 둘 = 16회 중 통과는 1UBQ뿐이다(중원자 602, 제외 58). 1M17·1S9I·1A4I = `sequence_gap`, 1FIN = `duplicate author chain identity`, 1MQ4·1A30 = `heavy_template_mismatch`, 1HSG = `missing_terminal_oxt`(`m7-probe.txt`, 2026-10-11, 두 정책 같은 결과). 그래서 변이 모델링(M21·M23·M25 단백질 루프)은 1UBQ(효소 아님)에서만, 촉매 보호(M26 → M20 v2)는 M-CSA 효소 1A30에서 보였고 두 반쪽은 같은 구조에서 이어지지 않는다(14번) |
| 2 | 변이 도킹의 맥락 | 1UBQ에는 리간드가 없어 같은 조건 도킹 짝(C3)·서열 GA(C4)·단백질 루프 도킹(C6, L-C6)은 합성 표시 페놀 SDF(`mutation_model/synthetic-phenol-ligand.sdf`)를 썼다. 생물학적으로 의미 있는 자세가 아니라 경로의 기계적 검증이다 |
| 3 | 리간드 설계 자료 | 수용체·포즈 = ProLIF 공개 예제(`chemical/prolif-vina-rec.pdb`·`prolif-vina-output.sdf`), 부모 = 공개 파생 SDF(`public-derived-parent-record0.sdf`), building block·반응 규칙 = 합성 표시 목록(실제 벤더 카탈로그 없음, 11번). PDB에서 받은 실제 결정구조 수용체는 사용자 손질 없이 도킹되지 않는다(기존 미해결 문제) |
| 4 | 키나아제 분기의 도킹 | 1M17·1FIN은 원본 결정구조라 M18 수용체 규칙을 통과하지 못해 도킹하지 않았다. 키나아제 구조는 구조 분석·지식(분기 A)에만 쓰고 도킹은 분기 B의 준비 수용체로 했다 |
| 5 | JEV | 실제 모델 호출은 합계 2회(바퀴 한 번씩)이고 나머지 바퀴(B6·B7 두 목표, C5·C6 두 목표)는 fixture 서버로 같은 코드 경로를 지났다. 고른 목록 위치는 관찰값이다(L-B7 2개 중 2번째, L-C6 3개 중 1번째). M24 6회가 모두 목록 첫 후보였다는 관찰과 목록 위치가 효과의 근거가 아니라는 점은 그대로이고, JEV 판정은 "JEV 판정(모델 선택)"이며 순위·추천이 아니다 |
| 6 | 외부 요청 | 실호출 2회 + 설치 시험의 패키지 저장소 내려받기 외 0건. fixture 단계·연습·회귀 사슬·게이트는 브라우저 비-loopback 요청 0, fixture 단계 제공자 호출 0이다. 구조 새로 받기·M26 다시 가져오기는 하지 않았다 |
| 7 | 지원 환경 | 구조·전처리·접촉·SASA·OpenMM·보고서는 POSIX(Darwin·Linux, psutil 신원 확인 가능)로 쓰도록 설계되어 있으나 검증은 macOS arm64 CPython 3.11(3.11.11, Node.js 24.3.0, npm 11.4.2)에서만 했다. ProLIF·fpocket·qvina·도킹 작업 환경의 잠금은 macOS arm64 전용이라 Linux·Intel Mac에서는 화학·포켓·리간드·도킹·GA·루프 기능이 숫자 없이 "사용할 수 없음 + 이유"로 보인다. PDBFixer(M21 모델링)는 플랫폼 잠금이 아니라 `backend/pyproject.toml`의 핀(sdist 해시 고정)이고 새 컴퓨터 설치에서 sdist로 빌드되어 설치됐다(`clean-install/record.txt` 발견 1). 다만 검증은 macOS arm64에서만 했다(해석 메모 N9). "자기 컴퓨터나 혼자 쓰는 서버" 전제는 그대로다 |
| 8 | 범위 밖 | GPCR 계열 지식(완성 정의 문구에만 있고 M15–M27 어디에도 없다), Linux·Intel Mac용 작업 환경 잠금, M14에서 미룬 "다른 탭 알림"과 "run 전체 작업 목록" 화면, 외부 구조 새로 받기, 실제 결합 맥락(효소 + 기질/억제제)에서의 변이 도킹, `CLAUDE.md`(= `AGENTS.md`) 재구성, POST JSON 형식 검사와 M20 v2의 "0 저장" 변경(명세 §1·§10.3, 사용자 결정 ③·⑨) |
| 9 | 관찰하지 못한 사례·큰 구조·긴 실행 미측정 | 이번 단계의 사례는 모두 관찰했다(아래 "관찰하지 못한 사례"). 그 밖의 기존 관찰 공백·큰 구조·긴 실행 미측정은 `docs/tracking/findings.md`의 해당 절과 최종 분류를 따른다(예: 절 76 M21 시간·크기, 절 81 GA 실행 시간, 절 86 서열 GA 큰 구조) |
| 10 | 역추적 감사의 한계 | 값 재계산은 제품의 다시 열기 검증과 사례별 독립 기대값이 맡고 감사(`scripts/m28_trace_audit.py`)는 근거 구조·출처의 존재를 본다. Markdown 서술 속 숫자는 파싱하지 않는다. 금지 표현은 X4의 핵심 금지어 검사와 줄 단위 예외 목록이 맡는다. 점검 보고서와 `interface_sasa` 보고서는 제품이 다시 열 때 주장·Markdown을 다시 만들지 않아 감사의 1번 전제("제품 검증이 재계산을 맡는다")가 성립하지 않으므로 `partialProductRecheck`로 표시하고 A2·A3의 독립 기대값으로 보완했다. A3는 SASA를 독립으로 다시 계산하지 않고 저장 필드와 화면·Markdown 줄을 대조했다(해석 메모 N7) |
| 11 | 합성 표시 자료 | B2 building block(`ligand_ga/synthetic-ga-small-blocks.smi`·`ligand/synthetic-blocks.sdf`)·반응 규칙(`ligand_ga/synthetic-ga-pool2000-rules.json`의 `user_2`·`user_3`), C3·C4·C6·L-C6의 페놀 SDF. 증거 입력 목록에 `syntheticLabeled: true`로 적혀 있다. 수용체·포즈는 ProLIF 공개 예제, 부모 SDF는 공개 파생이며 합성 표시 자료가 아니다 |
| 12 | 관찰되지 않은 상태 | 공개 구조에서 M26 `unmatched`·`conflict` 행은 나오지 않았다(A8: 1S9I A 대응됨 2, 1A30 A·B 각 3, 1A4I A 6, 대응 없음·충돌 0, 1S9I B·1A4I B는 `chain_not_listed`로 세지 않음). 점수 없는 행이 정렬에서 늘 끝인 조건(B4, `unscoredLast` 빈 목록)과 GA G2의 조건(B5, 두 설정 모두 `complete`·`generations_complete`)은 생기지 않았다. 이 상태들은 기존 단계의 시험·수락이 덮는다 |
| 13 | A 분기 세부 | 1M17 전처리 구조는 체인 하나라 체인 선택 단계(M12 하네스 P04)를 생략했다. A6 극성 접촉 점선 수(2)는 입력 좌표로 계산한 기대값과 대조했다 |
| 14 | 서로 다른 구조 | C1(1A30)과 C2–C6(1UBQ)는 서로 다른 구조다(증거 `structures: {"c1": "1A30", "c2": "1UBQ", "same": false}`) |
| 15 | 보고서 목록 라우트 | `GET /runs/{rid}/reports`는 모든 보고서를 다시 열어 보고서가 많은 run에서 느려질 수 있고 하나가 깨지면 목록 전체가 422다(절 129). 그래서 X1은 보고서마다 `GET /runs/{rid}/reports/selected`로 열림을 판정했다 |
| 16 | 선택 작업 환경 | ProLIF·fpocket·qvina·도킹 작업 환경은 새 컴퓨터에서 설치하지 않고 문서의 명령이 `scripts/setup_*.py` 인자·`config/` 잠금 파일 이름·아카이브 수(33·35·8·26)와 맞는지 정적으로만 확인했다(사용자 결정 ⑦) |
| 17 | 증거 파일 없는 측정 | 보고서 목록 라우트가 분기 B run의 보고서 9건에 처음 약 15초 걸린 것은 구현 중 측정이고 증거 파일이 없다(`docs/engineering-notes.md` "보고서 목록 라우트는 모든 보고서를 다시 연다") |
| 18 | 하네스·실행기 단언 깊이의 한계 | 독립 코드 검토 권고 중 T11이 고치지 않고 문서 입력으로 미룬 것(아래 "독립 검토 요약"): (1) 분기 A의 수소결합 문구 검사 `hbondLines`는 "수소결합/hydrogen bond"를 쓴 줄에 "아님·아닙니다·아니다·아니며·아니고·not·no" 중 하나만 있으면 부정으로 보고 통과시킨다(`endtoend-a-flow.cjs` 53–54행 `HBOND`·`NEGATION`, 305–310행). 같은 줄의 다른 부정어 때문에 단정이 빠져나갈 수 있고 X4 핵심 금지어 검사가 이를 보완한다. (2) X2의 `partialProductRecheck` 보완은 run이 아니라 보고서 종류 단위로 짝짓는다(`inspection` → A2, `interface_sasa` → A3, 실행기 `AUDIT_SUPPLEMENTS`). 이번 실행에서 두 종류는 분기 A run에 하나씩뿐이었다. (3) `not_observed`를 허용하는 조건은 덮는 시험 이름이 비어 있지 않은지만 보고 그 시험이 실제로 있는지는 보지 않는다(`m28_common.py`). 이번에는 `not_observed` 사례가 없어 쓰이지 않았다. (4) C1의 "제외 이유" 열은 보이는 열 글자가 아니라 행의 `data-exclusion-reasons` 속성을 저장 행의 `exclusion_reasons`와 대조했다(`endtoend-c-flow.cjs` 651행 `positionsMatch`, 보호 위치는 2098행). 촉매 칸은 글자·`data-catalytic`·`data-released`까지 봤다. (5) C2의 "HIS·CYS 상태 표시"는 화면에서 두 구조 사이 양성자화 차이 영역만 단언했다: 차이가 0이라 `mutation-model-protonation-none`이 있고 그 `data-count`가 "0"인지(2374–2375행). 구조별 HIS·CYS 변이형 값(HIS A:68이 두 구조 모두 HID)은 저장 객체의 `protonation_variants`에서 증거로 옮겼을 뿐 화면의 구조별 값 칸을 직접 단언하지 않았다. (6) 옛 하네스에서 복사 때 빠졌던 단언 중 T11 R4가 복원한 것은 B4 일괄 표 대조(`batchTableEquals`: 문장 ID·상태·점수 대상·이유 단언과 열 머리 전체 대조)와 문구 검사 넷(일괄 영역·GA 영역 금지어, 분기 A 뷰어 이름표의 수소결합, M23 사전 확인 문구, 하네스의 `T11 R4` 주석)이고, 그 밖의 표 대조 함수는 옛 함수를 고쳐 쓴 것("adapted from" 주석)이라 옛 단언과 같지 않은 곳이 있다(예: 리간드 GA 요약 `gaResultEquals`는 풀이 이번 run의 후보 집합이라 유사도 값을 형식과 부모만 확인하고 M22 fixture 지문으로 대조하지 않는다). 복원하지 않은 옛 단언의 전체 목록은 증거로 남기지 않았다 |

## 사례 대장 요약
수치는 `acceptance-fixture/cases.json`·`summary.json`·`evidence/*-evidence.json`과 `acceptance-live/` 같은 파일에서 옮겼다(사례별 관찰값은 독립 기대값과 대조한 값이며 제품이 저장·표시한 값 그대로다).

- **fixture 단계**(`scripts/m28_offscreen_acceptance.py --phase fixture`, 분기 셋, 2026-10-11 17:07–17:25 UTC): `acceptance: true`, 사례 31개 모두 `pass`(A1–A8·B1–B8·C1–C7 23 + X1-A·X1-B·X1-C·X2–X6 8), `unobserved` 빈 목록. 브라우저 비-loopback 요청 0, 제공자 호출 0, fixture 서버 dispatch 이벤트 6(B6 1 + B7 2 + C5 1 + C6 2, 스크립트 응답), 제품 키 해석기는 단계 중 0회(대장 `external.product_key_resolver_calls` 0)이고 끝의 증거 키 검색(`key_scan`)에서 자식 프로세스로 1회(`checks.exportScan.productKeyResolverCalls` 1, 키·placeholder 적중 0, 자식은 불리언·경로만 출력), 남은 프로세스·포트 없음, 기본 폴더 `.deps/precedent_reference`·`.deps/reaction_reference` 만들지 않음.
- **live 연습**(`--phase live --rehearse`, fixture 서버, 실호출 0, 18:40–18:43 UTC): 사례 9개 모두 `pass`, `rehearsalPassed: true`(연습 대장의 `acceptance`는 설계상 늘 거짓, 해석 메모 N14). 제품 키 해석기 0회(키 존재 확인 건너뜀, 증거 검색은 `skipped: rehearsal`로 placeholder·키 모양만).
- **실제 live 단계**(`--phase live --live-calls 2`, 18:43–18:46 UTC): `acceptance: true`, 사례 9개 모두 `pass`(L-pre-B2·L-pre-B3·L-pre-B4·L-pre-C2·L-B7·L-C6·L-X3·L-X4·L-X6), `unobserved` 빈 목록. 제품 키 해석기는 자식 프로세스로 2회(키 존재 확인 1 + 증거 키 검색 1, `checks.exportScan.productKeyResolverCalls` 2, 대장 `external.product_key_resolver_calls`는 내보내기 전 값 1), 키 적중 0.

| 사례 | 관찰(증거 값) |
|---|---|
| A1 | 1M17 전처리(화면 기본 물 정책 `strip_all`): 잔기 313·원자 2,526(물 20·altloc 14 제거), 입력 파일에서 독립으로 센 값과 같음 |
| A2 | AQ4 인스턴스 7필드 선택, 기하 접촉 65행(`contact` 33·`polar_contact` 7·`hydrophobic_contact` 25), 입력 원자와 맞지 않는 행 0 |
| A3 | SASA 잔기별 312행, 요약 필드 6개가 저장 객체와 같음, 보고서 만듦 |
| A4 | fpocket 후보 27개(화면 10개), 기술자 5개의 단위(무단위 `score`·`druggability_score`, 개수 `alpha_sphere_count`, Å² `total_sasa_A2`, Å³ `volume_A3`), 알파 구 오버레이 |
| A5 | 1M17 A mapped 311·conflict 1, 1FIN A·C mapped 각 298, 1MQ4 A mapped 260·conflict 1, unmapped 0, 화면 = 저장 행 |
| A6 | 부위 10개 모두 `annotated`(xDFG.82·xDFG.83은 접촉 없음 문장, 0 아님), 극성 접촉 점선 2, PNG 1200 × 800·457,086 B + 출처 JSON(범례 켬, 그림 상한 안) |
| A7 | 1M17 A → `P00533` 포함 76·미포함 `excluded_flagged` 66(변이 표기 L834R 1·L858R 15·T790M 4·WT 3·not_reported 53), 1FIN A·C → `P24941` 포함 32·미포함 24, 설치 세트 JSONL에서 독립으로 센 값과 같음(가져오기 행 891·885·555·서지 252, 네트워크 시도 0) |
| A8 | 1S9I A 대응됨 2, 1A30 A·B 각 3, 1A4I A 6(대응 없음·충돌 0), 1S9I B·1A4I B `chain_not_listed`(세지 않음, 0 아님), 보고서 만듦 |
| B1 | ProLIF 상호작용 36행, 역할·D···A 거리·각도 불일치 0, 보고서 만듦 |
| B2 | block SDF 10·SMILES 10, 후보 14개(출처 `fixed`·`user_1`·`user_2`), 필터 = 저장값 서버 평가(불일치 0) |
| B3 | 실제 qvina, 점수 = 첫 모드 값, 모드 1개(요청 2, 엔진 출력 그대로), 같은 인자 재제출 = 같은 작업·0단위 |
| B4 | 일괄 5행(후보 4 + 부모 기준 행, 새 계산 2행), 행 점수 = 단독 M18 첫 모드 값(불일치 0), 사람 증액 +1 |
| B5 | 설정 1(seed 11·개체 4·세대 2·무작위 0.2): 예약 6·새 도킹 5·재사용 1. 설정 2(세대 3·무작위 0.5): 예약 8·새 도킹 2·재사용 6. 둘 다 `complete`·`generations_complete`, 사람 증액 +6·+8 |
| B6 | 미리보기 본문 해시 = 전송 바이트 해시 = `prepared` 해시, `completed` |
| B7 | 탐색형: 계산된 후보 1개를 보냈고 본문에 점수 없음(빈 확인 아님). 활용형: 계산된 후보 2개의 저장 점수가 본문에 있음. 바퀴마다 전송 승인 → 계산 시작 승인 → 실제 qvina |
| B8 | 보고서 목록 9 = 만든 수 9 = 이벤트 9, JSON 내려받기 해시 불일치 0 |
| C1 | 1A30: 체인 A만 덮은 집합 `not_checked`(`chains_not_covered`), 두 체인 집합 `checked`, `catalytic_residue` 보호 ASP A:25·THR A:26·ASP B:25·GLY B:27, ASP A:25 잔기 단위 해제, 보고서 `mutation_candidates_markdown@2`(반응 세트 `1a7b131a…`) |
| C2 | 1UBQ M7 최소화(중원자 602·제외 58) → M20 직접 선택 4위치·후보 6 → M21 I44W, 두 구조의 전위(kJ/mol)·변이 위치 SASA·접촉이 저장 객체와 같고 차이 키 없음, HIS A:68 두 구조 모두 HID |
| C3 | 같은 조건 도킹 짝 두 결과, 각 점수 = 해당 M18 첫 모드 값 |
| C4 | 설정 1(seed 21·개체 4·세대 3·무작위 0.25): 예약 22(= 2 × (10 + 1))·새 평가 10. 설정 2(개체 6·세대 2·무작위 0.5): 예약 14(= 2 × (6 + 1))·새 평가 3·재사용 7(기준 행 재사용). 둘 다 `complete`·`generations_complete`, 사람 증액 +22·+14 |
| C5 | B6과 같은 조건(본문 해시 같음), 촉매 표시 `not_checked` |
| C6 | 탐색형: 계산된 후보 1개, 본문에 점수 없음(빈 확인 아님). 활용형: 계산된 후보 2개의 저장 점수가 본문에 있음. 계산은 M21 모델링 → 변이 구조 M18 도킹 |
| C7 | 보고서 목록 9 = 만든 수 9 = 이벤트 9, JSON 내려받기 해시 불일치 0 |
| X1-A·B·C | 보고서별 다시 열기 200: A 10·B 9·C 9, 이벤트 수 = 사례가 센 생성 수 |
| X2 | 역추적 감사 `pass`(아래) |
| X3 | 브라우저 비-loopback 0, 제공자 호출 0 |
| X4 | 탭·보고서·증거 글자 73개 검사, 핵심 금지어 적중 0(예외 19개가 줄 66개를 덮음) |
| X5 | 정직한 부재 표시 관찰 28건 모두 0이나 "없음"으로 보이지 않음 |
| X6 | 남은 프로세스·포트 없음, 기본 참조 폴더 만들지 않음 |
| L-pre-B2·B3·B4 | 후보 14개, 같은 인자 재제출 0단위, 일괄 5행(새 계산 4) |
| L-pre-C2 | M7(602·58) → 후보 6 → M21 I44W |
| L-B7·L-C6 | 둘 다 `completed`(아래 "실호출") |
| L-X3 | 브라우저 비-loopback 0, 계수 2 = 대장 2 = dispatch 이벤트 2 |
| L-X4 | 글자 26개 검사, 적중 0 |
| L-X6 | 남은 프로세스·포트 없음, 기본 참조 폴더 만들지 않음 |

- 사람의 한도 증액 클릭(하네스의 실제 클릭, `by: human-click`): fixture 분기 B 3번(B4 +1, B5 설정 1 +6, 설정 2 +8, 최종 한도 23단위), 분기 C 2번(C4 설정 1 +22, 설정 2 +14, 최종 44단위), live 0번. 분기 C와 live 분기 B는 단위 여유가 0이라 하네스가 각 계산 전에 남은 단위를 단언했다.

## 실호출 (실제 live 단계)
사용자가 정한 2회를 모두 썼다(재시도·새 run 없음). 저장소 대장 `runs/m28-live-ledger.json`(Git 제외)은 시작 전 0, 계획 2, 끝난 뒤 2이고 대장 합계 = dispatch 이벤트 2다. 외부 요청 장부 `network-ledger.txt`의 두 줄은 QA root의 `jev_science_dispatch_started` 이벤트 시각(18:44:51Z·18:45:50Z)을 적는다(T19 지적으로 조율 세션이 `5b4ad1f5`에서 고침). 키는 자식 프로세스의 제품 키 해석기로 있는지만(불리언) 보고 루트 `.env`는 `os.lstat`로 모드(0600)만 확인했다. 증거(`acceptance-live/evidence/{b,c}-live/endtoend-{b,c}-evidence.json`의 `live.send`)에 키·헤더·응답 본문은 없다.

| 바퀴 | 목표 | 결과 | 응답 모델 | 본문 바이트 | 토큰(입력/출력) | 비용(USD) | 고른 목록 위치(관찰값) | 계산 |
|---|---|---|---|---|---|---|---|---|
| L-B7 리간드 루프 | 활용형(본문에 저장 점수 4개) | `completed` | `typesafe/jev-1.13-20260917` | 4,684 | 2,590(2,552/38) | 0.000107 | 2개 중 2번째 | 실제 qvina `scored` |
| L-C6 단백질 루프 | 탐색형(점수 미전송) | `completed` | `typesafe/jev-1.13-20260917` | 3,736 | 1,955(1,908/47) | 0.000080 | 3개 중 1번째 | M21 모델링 → M18 도킹 `scored` |

- 두 호출 합계 토큰 4,545, 비용 USD 0.000187. 응답에 `confidence`·`probabilities`가 있었다(증거에는 있음 여부만 적고 값은 적지 않음). 고른 위치는 관찰값이며 효과의 근거가 아니다.
- L-C6 탐색형의 "전송 본문에 점수 없음" 확인은 비어 있다: live 선행 상태(L-pre-C2)는 대상 변이를 모델링만 하고 도킹하지 않아 풀에 계산된 후보가 없었다(`vacuous: true`, 절 134). 같은 확인은 fixture C6·B7(탐색형)에서 비어 있지 않게 했다.

## 역추적 감사 결과 (X2, `acceptance-fixture/evidence/trace-audit.json`)
- fixture 단계: 저장 보고서 28개(분기 A 10·B 9·C 9), 종류 18개(`chemical_interactions` 1, `inspection` 1, `interface_sasa` 1, `jev_choice` 2, `jev_loop` 4, `kinase_precedents` 2, `ligand_candidates` 1, `ligand_docking` 1, `ligand_docking_batch` 1, `ligand_ga` 2, `mutation_candidates` 2, `mutation_model` 1, `openmm_protein_minimize` 1, `pocket_detection` 1, `reaction_knowledge` 3, `reference_site_annotation` 1, `residue_numbering` 1, `sequence_ga` 2). 검사 다섯(다시 열기 `reopen`, 근거 객체 존재 `evidence_exists`, 주장 필드 `claim_fields`, 참조값 출처 `reference_source`, 증거 종류 섞임 없음 `no_mixing`)이 모두 28/28 통과, 실패 0, 감사되지 않은 run 0.
- 어댑터 표: 보고서 종류 20종(점검 1 + 방법 19: 위 18종과 이번 run에 보고서가 없는 `atom_distance`·`rigid_alignment`). 어댑터가 없는 종류는 건너뛰지 않고 실패다. 표는 감사 모듈 머리와 `trace-audit.json`의 `adapters`에 있다.
- `partialProductRecheck`: `inspection`(주장 재검증·Markdown 재생성 없음)과 `interface_sasa`(Markdown 재생성 없음)는 A2·A3 사례의 독립 대조로 보완했다(`auditSupplements`, 두 사례 `pass`).
- M20 보고서 둘(`mutation_candidates`: C1, C2)도 참조값 출처 검사를 통과했다. 반응 지식을 인용한 C1 보고서는 `mutation_candidates_markdown@2`이고 보고서 자체의 출처표(반응 세트 `1a7b131a…`)로 통과했다(명세 §10.2의 수정 뒤).
- live 단계: 보고서 8개(종류 7: `jev_loop` 2, `ligand_candidates`·`ligand_docking`·`ligand_docking_batch`·`mutation_candidates`·`mutation_model`·`openmm_protein_minimize` 각 1), 다섯 검사 모두 8/8.

## 회귀 사슬 결과 (`regression-chain.txt`, 실행 소스 `5a5ba3f2` = 고정 + 문서·증거)
순서대로 한 번에 하나(8000/3000 비움): M27 `--stages fixture,real` → M26 `--stages fixture,real`(보관 실세트의 격리 복사) → M25 `--phase fixture --regressions`(M24 fixture → M23 → … → M13, M13은 M8–M12 포함). 종료 코드 M27 0(95초)·M26 0(109초)·M25 0(4211초, `failedSteps=[]`, `acceptance=true`). 사슬 전·사이·뒤에 `.deps/precedent_reference`·`.deps/reaction_reference`는 없었고 기본 폴더를 만들지 않았다. 외부 요청 0(M27 가져오기 네트워크 시도 [0, 0], M26 실서버 요청 0, 브라우저 비-loopback 0, 실호출 0). 옛 하네스·실행기 수정은 필요 없었다.

| 실행기 | M27 기록의 기준 | 이번 | 결과 |
|---|---|---|---|
| M27(fixture + real) | 46 | 46 | 모두 pass |
| M26(fixture 39 + real 19) | 58 | 58 | 모두 pass |
| M25(fixture) | 57 | 57 | 모두 pass |
| M24(fixture) | 26 | 26 | 모두 pass |
| M23 | 35 | 35 | 모두 pass |
| M22 | 25 | 25 | 모두 pass |
| M21 | 23 | 23 | 모두 pass |
| M20 | 24 | 24 | 모두 pass |
| M19 | 26 | 26 | 모두 pass |
| M18 | 24 | 24 | 모두 pass |
| M17 | 21 | 21 | 모두 pass |
| M16 | 19 | 19 | 모두 pass |
| M15 | 14 | 14 | 모두 pass |
| M14 | 15 | 15 | 모두 pass |
| M13(M8–M12 포함) | 28 | 28 | 모두 pass |

- 합계 441사례, 사례 수가 기준과 모두 같아 M20 보고서 변경(T3)이나 다른 M28 변경이 사례를 더하거나 빼지 않았다. 256 KiB를 넘는 텍스트 증거 53개(M13 51·M14 1·M15 1, 약 318 MB)는 결정 0020대로 `frontend/tests/offscreen/artifacts/m28-final/export-full/`로 옮겼다(해시는 각 폴더 `ARCHIVED-EVIDENCE.sha256`).
- 기록 대조 메모: `regression-chain.txt` 머리의 시각 범위 끝이 처음에 18:50Z로 잘못 적혀 있었다(실행기 소요 합 95 + 109 + 4211초, 단계 끝 시각 17:27:39Z·17:29:28Z·18:39:39Z와 맞지 않음). 조율 세션이 독립 검토 전에 사슬 기록 머리를 17:26Z–18:40Z와 단계 끝 시각으로 바로잡았다(그 파일은 이번 단계의 증거이고 `a18dd488` 이후 문서·증거 변경 규칙 안이다). 독립 증거 검토(T19) 뒤에는 같은 파일 끝에 `.deps/precedent_reference`·`.deps/reaction_reference`가 없음을 보인 `ls` 줄(사슬 전·m27과 m26 사이·m26과 m25 사이·뒤)과 커밋된 내려받기 파일 110개의 해석을 더했다(`5b4ad1f5`·`210e8ded`). `regression/` 아래에는 옛 실행기가 쓰는 대로의 내려받기 파일 110개(`downloads/` 폴더, Markdown 53·JSON 57: 보고서와 그림 출처·흐름 요약 JSON)가 커밋되어 있고 M27 회귀 증거(`docs/qa/m27-precedents-20261010/regression/`, 같은 110개)와 같은 구성이다. 명세 §5의 "보고서 다운로드는 Git 제외"를 M28 실행기의 증거에만 적용한 해석이다(해석 메모 N14).

## 게이트 (고정 `a18dd488`, `gate.txt`)

| 명령 | 결과 |
|---|---|
| 백엔드·스크립트 pytest 열여덟 그룹(Stop 훅 `CHECKS[1:]`, 한꺼번에 시작, 그룹별 제한 없이) 연속 3회, 다시 돌리기 없음 | 3회 모두 열여덟 그룹 exit 0, 매회 **6,379 passed**·0 skipped, 벽시계 360.7·359.2·358.6초(최장 그룹 360.2·358.7·358.1초, 그룹 제한 480초). 합계 = M27 게이트 6,037 + M28이 더한 시험(`gate.txt`: `scripts/test_m28_*.py`와 시험 수정) |
| 간헐 실패 시험 셋(명세 §10.1) | 서열 GA SIGTERM `[qvina-worker]`(그룹 12)·포켓 `[output_files]`(그룹 03) 등이 3회 모두 통과, 실패한 시험 없음 |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| `node --check` 오프스크린 하네스 | 34개(옛 31 + `endtoend-a/b/c-flow.cjs`), 실패 0 |
| `npm --prefix frontend run test:events` | 534 pass, 0 fail |
| `typecheck` → `build`(차례로) | exit 0 → exit 0 |
| 골든 `golden_science_m24.py --check`·`prototype_golden_egress.py --check` | exit 0, exit 0 |
| `prototype_golden_call_keys.py` 재기록(새 runs 폴더) | 커밋된 `golden_call_keys.json`과 `cmp` 동일(다시 기록하지 않음) |
| 호출 키 해시 파일 | `git diff --name-only 287a37a8 HEAD -- backend/mw`는 `mutation_reports.py`(해시 파일·`also_hashed_files` 아님)만, `test_kinase_precedents_ast.py`의 `BASELINE_BLOBS` 대조(그룹 16) 3회 통과 |

- 원 로그: 처음 게이트 기록은 그룹별 원 로그를 세션 임시 폴더에만 두었다. 독립 증거 검토(T19) 뒤 조율 세션이 원 로그를 `docs/qa/m28-final-20261011/gate-raw/`에 커밋했다(`5b4ad1f5`): 명령별 로그 7개(`ruff.log`·`frontend-test-events.log`·`frontend-typecheck.log`·`frontend-build.log`·`golden-science-m24.log`·`golden-egress.log`·`golden-call-keys-record.log`), 회차별 그룹 로그 18개와 `summary.json`(`round1/`–`round3/`), 차례로 돌린 명령의 결과 `other-commands.txt`. 절대 경로는 `<repo>`·`<scratch>`로 바꿨다.
- 회차의 읽기: 1회차가 명세 §8.2의 최종 게이트(다시 돌리기 없이 한 번에 통과)와 §10.1·§13의 "연속 3회"의 첫째를 겸했고 2·3회차는 같은 소스에서 이어 돌렸다(`gate.txt` 끝 "note on the three rounds", 해석 메모 N14).

## 설치 시험 (`clean-install/record.txt`, 2026-10-11 17:01–17:05 UTC)
- 고정 소스에 문서만 더한 `6da1670a`를 Git 제외 `runs/` 아래 새 폴더에 로컬 `git clone --no-hardlinks`(네트워크 없음)하고 README "설치와 실행"의 명령만 순서대로 했다. 클론한 커밋은 고정 `a18dd488`이 아니라 문서만 다른 `6da1670a`이고(`git diff --name-only a18dd488 6da1670a`: `docs/` 문서 여섯 `business-rules.md`·`contracts.md`·`engineering-notes.md`·`operations.md`·`standards.md`·`system-architecture.md`, `scripts/AGENTS.md`·`frontend/AGENTS.md`, 증거 폴더 `docs/qa/`), README는 같다(`git diff a18dd488 6da1670a -- README.md`가 비어 있음, `record.txt` 끝). 그래서 설치 결과는 고정 커밋의 클론과 같다고 읽었다(해석 메모 N14). 클론에는 `.deps`·`.env`·`runs/`·`.venv`·`frontend/node_modules`가 없었다. 패키지 캐시는 비운 상태(`PIP_NO_CACHE_DIR=1`, 클론 안 npm 캐시)였다.
- `python3.11 -m venv .venv` exit 0(2초) → `.venv/bin/python -m pip install -e ./backend[dev]` exit 0(52초) → `npm --prefix frontend ci` exit 0(79초) → `npm --prefix frontend run build` exit 0(20초). Python 3.11.11, Node.js v24.3.0, npm 11.4.2, `pip freeze` 41줄(`pip-freeze.txt`), `npm ls` 최상위 15줄(`npm-ls.txt`).
- 서버 기동 뒤 `GET /capabilities` 200(백엔드)·`GET /api/capabilities` 200(프런트 프록시)·`GET /` 200, `public_1hsg.cif` 업로드 201 → `inspect_complex` 200 `complete` → 보고서 201 → 다시 열기 200(서버 증거 검증) → Markdown·JSON 내려받기 200. 사용할 수 없음으로 보인 항목 19개(Rosetta 이름 에너지 프로토콜 넷은 M0부터 미구현, 나머지 15개는 화학·포켓·분석 템플릿 둘·자연어 계획·번호 대응·반응 지식·전례·리간드 후보·도킹·일괄 도킹·리간드 GA·서열 GA·JEV 루프 두 갈래가 숫자 없이 이유와 함께). 종료 뒤 남은 프로세스·8000/3000 리스너 없음, 원래 체크아웃 `git status` 0줄(시험 전과 같음).
- 기록의 발견 넷: (1) README 명령 그대로 핵심 설치 통과, PDBFixer 1.12.0은 `pyproject.toml` 핀으로 sdist에서 빌드되어 M21 모델링 방법이 새 설치에서도 쓸 수 있음 (2) 선택 기능은 숫자 없이 이유와 함께 사용할 수 없음 (3) 문서 오류: README·`docs/operations.md`의 "`npm ci`가 Electron 실행 파일을 받는다"는 electron 44.4.5에서 사실이 아니어서 고정 뒤 문서로 정정했다(실행 파일은 첫 사용 때나 `npx install-electron --no`가 GitHub 릴리스에서 받는다. 이 컴퓨터는 캐시에 있어 실행 파일 내려받기를 관찰하지 못했다, 해석 메모 N11) (4) 핀·잠금 파일 변경 필요 없음.
- 외부 요청: `pypi.org`(색인 조회, 횟수는 로그에 없음), `files.pythonhosted.org`(내려받기 68건), `registry.npmjs.org`(캐시를 비운 채 GET 262건 + `npm ci` 기본 audit의 POST 1건(의존성 이름·버전만), 같은 실행 안 캐시 hit 257건), `github.com` 0건(`npm ci`는 Electron 실행 파일을 받지 않고, 손으로 돌린 `install.js` 확인은 컴퓨터 캐시 hit). 키·쿠키·사용자 데이터를 보내지 않았고 제품 실행 확인은 `127.0.0.1`만 썼다(`network-ledger.txt`). 호스트와 개수의 근거는 단계 로그에서 센 값이며(네트워크 캡처 아님) `record.txt`의 "package and binary repository hosts" 절에 있고, 원 로그(`pip-install.log`·`npm-ci.log`·`npm-build.log`·`electron-install.log`·`backend.log`·`frontend.log`)는 Git 제외 `frontend/tests/offscreen/artifacts/m28-final/clean-install-logs/`에 있으며 커밋 증거에는 경로·크기·SHA-256만 있다(T19 지적으로 `5b4ad1f5`에서 더함).
- 선택 작업 환경(ProLIF·fpocket·qvina·도킹)은 설치하지 않고 정적으로만 대조했다: 문서의 명령 플래그가 각 스크립트 `--help`에 있고 스크립트 경로가 있으며, 아카이브 수가 잠금 파일과 같다(prolif 33, fpocket 35, qvina 8, docking 26). 고칠 문서는 없었다.

## 이번 단계에서 고친 것
- **간헐 실패 시험 넷(T2, `bc1e180b`, 시험만)**: 서열 GA 작업자 시험의 psutil `proc_cmdline` `SystemError`(명령줄 미리 읽기 제거, `SystemError`를 `psutil.Error`와 함께 "이번에 못 찾음"으로), SIGTERM `[qvina-worker]` 시험(단계 직전 표지 파일 뒤 프로세스 그룹을 붙잡고 신호), 포켓 `[output_files]` 시험(같은 방식으로 fpocket을 붙잡음), M24 JEV 보고서 시험의 `'0.1234'` 우연 겹침(정수 전체 일치). 제품 코드·해시 파일 변경 없음. 고정 게이트에서 연속 3회 통과(절 99 `해결`).
- **M20 보고서 참조 출처표(T3, `7812289b`·`f4ec1b6b`)**: 보고서 형식 버전 올림 `mutation_candidates_markdown@2`(해석 메모 N4). M20 고정 문장 5개·닫힌 집합·결과 객체·호출 키 해시 파일은 그대로다(절 72 `해결`).
- **README·설치 문서(T4, `34160f2c`)와 설치 시험의 Electron 문장 정정(T13, `8e96c142`)**.
- **독립 코드 검토 지적(T11, `9c5d49eb`·`c1644221`·`a18dd488`)**: 아래 "독립 검토 요약".
- **문서 마감(T17, `0f79d8fd`·`6da1670a`)**: `docs/system-architecture.md` M20–M27 구성 요소(절 89 `해결`), `docs/operations.md` "M28 종단 수락 QA"·"업그레이드 뒤 할 일"·공유 제외 폴더, 게이트 목록(`docs/standards.md`), M20 보고서 형식(`docs/business-rules.md`·`docs/contracts.md`), M28 함정(`docs/engineering-notes.md`), `scripts/AGENTS.md`·`frontend/AGENTS.md`의 M28 불변 조건.
- **낡은 문장 세 곳(T18, `f44c8c10`)**: `docs/contracts.md`(method_reports 목록)·`scripts/AGENTS.md`(실행기 목록의 M23)·`docs/security.md`(이벤트 이름)의 M24 기록 밖 낡은 문장, 남은 문장 셋(절 98 `해결`). 커밋 메시지는 "four"라고 적었으나 절 98의 다섯 문장 중 `/capabilities` 목록은 M28 전(`287a37a8`, `docs/contracts.md` 445·564행)에 이미 있었고 증액 승인 수는 M25에서 고쳐졌다.
- **독립 증거·기록 검토(T19) 지적 반영(T20)**: 증거 텍스트(`5b4ad1f5`·`210e8ded`)와 문서(이 기록, `findings.md` 절 97·98·130의 분류 줄·사실, `findings-triage.md`, `status.md`, 결정 0036, `CLAUDE.md`·`AGENTS.md`의 M28 항, README 문서 목록, `scripts/AGENTS.md`·`docs/engineering-notes.md`·`docs/system-architecture.md`의 제품 키 해석기 서술). 아래 "독립 검토 요약".

## 고치지 않기로 한 것
- 명세 §10.3(사용자 결정 ⑨): 화학·도킹·GA POST 라우트의 JSON 형식 검사(415)와 아무 체인도 덮이지 않은 M20 v2 집합의 "0 저장 → null" 변경(후자는 M20 해시 파일과 저장 형식을 바꿔 M21·M23 옛 결과 재사용이 끝난다). 두 절은 `수용`이다.
- 이번 단계에서 찾았으나 고정 소스·호출 키 해시 파일·새 기능 금지 때문에 고치지 않은 것(`docs/tracking/findings.md` 끝 "(M28)" 절): 보고서 목록 라우트의 비용과 422(절 129), JEV 시험 둘의 확률 표지 부분 문자열 검사(절 130), `run_qvina`의 qvina2 시작 직후 신호 틈(절 131, 해시 고정 `docking_worker.py`라 `수용`), 실호출 대장과 `.lock`을 함께 지우면 상한이 되돌려짐(절 132), 단백질 바퀴만 다시 보낼 수 없음(절 133), live L-C6 탐색형의 빈 확인(절 134), 보고서 목록의 한국어 이름표 없는 종류(절 135), 점검·`interface_sasa` 보고서의 부분 재확인(절 136), 물 정책 기본값 두 곳(절 137).
- 하네스 일관성 두 가지는 미해결 문제 절을 더하지 않고 여기에만 적는다(제품 결함이 아니라 M28 하네스 모양): 분기 A에는 B·C의 2차 선행 단계(`apply_needs`)가 없어 A2가 독립 기대값 불일치로 `fail`이어도 A6이 `pass`로 남을 수 있고(`acceptance`는 거짓이라 거짓 통과는 아님), 분기 노트 `syntheticInputs`의 모양이 B(dict)와 C(list)로 다르다.
- 그 밖의 `사용자 결정 필요` 85개 전체(아래)는 고칠지·언제 할지를 사용자가 정한다.

## 미해결 문제 최종 분류 요약 (`docs/tracking/findings.md` 맨 위 표와 같음)

| 분류 | 절 수 |
|---|---|
| 해결 | 14 |
| 수용 | 33 |
| 사용자 결정 필요 | 85(본문 근거 24 + 기본값 61) |
| 범위 밖 | 5 |
| 합계 | 137(M27까지 128 + 이번 단계 9) |

- `사용자 결정 필요` — 본문 근거 24개(본문이 닫힌 집합·해시 고정 파일·한도·저장 형식·명세 동작을 바꿔야 하거나 사용자와 정한다고 적은 것): 절 10 포켓 보고서 Markdown의 작은따옴표 이중 이스케이프, 17 실패한 공유 작업을 흐름에서 다시 돌릴 수 없음, 20 PDB 형식 입력의 `chain_label`에 gemmi가 만든 값, 25 번호 대응 보고서 스냅숏에 `residue_numbering` capability 없음, 41 중원자 약 230개를 넘는 부모의 2D 그림 상한, 42 `retained_parent_atoms`의 두 뜻, 46 리간드 필터 경계의 float 변환, 47 도킹 리간드·수용체 좌표계 일치 미검증, 61 멈춘 일괄의 재사용 행 `scored`, 63 2시간 일괄 작업 모듈의 stdout·stderr 1 MiB 상한, 71 변이 후보 화면의 리간드 자동 선택 없음(명세 문구와의 편차), 76 M21 시간·크기는 1UBQ에서만 쟀고 M7 통과·M18 거부 크기 구간, 87 서열 GA 읽기·폴링의 재검증 비용과 검증 틈, 88 M23이 M22에서 물려받은 복구·신호 경계, 91 M24 "보내지 않음"과 `delivery_unknown` 구분, 94 M24 서열 구간·이웃의 HETATM 변형 잔기, 101 단백질 루프는 1UBQ로만 검증, 112 M20 v2 검증과 PDB ID 교차 확인, 123 전례 상세의 null·빈 `qualifier`/`unit`, 125 서지 행 모양이 어긋날 때 "서지 없음", 128 M27 코드 검토의 보류한 권고 둘, 133 단백질 바퀴만 다시 보낼 수 없음, 136 점검·`interface_sasa` 보고서의 다시 열기 재생성 없음, 137 물 정책 기본값 두 곳.
- `사용자 결정 필요` — 기본값 61개(본문에 사용자 수용 근거가 없어 명세 §11.3대로 둔 것, 대부분 해시 고정 파일이나 닫힌 집합을 건드리지 않고 고칠 수 있음. 절 97은 T19 지적으로 `수용`에서 옮김): 관찰 공백 18개(시험·fixture로만 덮였거나 재지 않은 사례: 절 5·9·16·33·45·52·66·67·68·74·80·81·85·96·103·115·127·134), 읽기 성능·검증 비용·잠금 8개(이벤트 로그 증분 읽기·검증 캐시 설계: 절 3·12·53·62·77·82·92·129), 작업·예산·승인 경계와 표시 지연 7개(절 4·14·19·44·54·60·84), 화면·뷰어 작은 결함과 원인 미확인 흔들림 8개(절 15·34·35·36·38·100·114·135), 참조 세트·가져오기·옛 실행기 운영 10개(절 23·24·29·107·109·110·117·118·124·126), 코드·시험·문서 정리 6개(절 26·30·31·43·64·130), 고정 소스 뒤로 미룬 검토 관찰과 실호출 대장 4개(절 97·104·105·132).
- 목록 전체(제목·근거·이유)는 `docs/tracking/findings.md` 맨 위 "`사용자 결정 필요` 목록"과 요약 사본 `docs/qa/m28-final-20261011/findings-triage.md`, 절별 분류 표·판단 기록도 그 사본에 있다. 분류 줄은 각 절 끝의 `- **최종 분류(M28)**: …` 한 줄이며 기존 본문은 바꾸지 않았다.

## 관찰하지 못한 사례
없다. fixture 단계 31사례와 실제 live 단계 9사례가 모두 `pass`이고, 두 대장의 `unobserved`가 빈 목록이며 `not_observed` 상태의 사례가 하나도 없다. 그래서 닫힌 이유(`no_public_input`·`unreachable_by_ui`·`engine_unavailable_by_design`)와 덮는 시험 이름으로 면제한 `not_observed`도 없다(모든 사례의 `covering_tests`가 빈 목록). 관찰은 했으나 조건이 생기지 않은 상태는 범위 표 12번, 빈 확인은 L-C6 탐색형(범위 표 위 "실호출", 절 134)이다.

## 증거 위치

| 경로(`docs/qa/m28-final-20261011/` 아래) | 내용 |
|---|---|
| `preflight.md`, `m7_probe.py`, `m7-probe.txt` | 착수 확인(기준선·자료·M7 사전 검사 표·사례 사슬 지도·시간·예산·간헐 실패 원인·M20 보고서·미해결 문제 수·설치 준비·Stop 훅·감사 어댑터) |
| `gate.txt` | 고정 `a18dd488` 게이트, 고정 뒤 경로 집합 해석, 세 회차의 읽기("note on the three rounds") |
| `gate-raw/` | 게이트 원 로그(T19 뒤 `5b4ad1f5`에서 커밋): 명령별 로그 7개, `round1/`–`round3/`의 그룹 로그 18개와 `summary.json`, `other-commands.txt`(절대 경로는 `<repo>`·`<scratch>`) |
| `acceptance-fixture/` | 종단 fixture 수락(`README.md`·`summary.json`·`cases.json`·`SHA256SUMS`·`binary-artifacts.json`·`evidence/`: 사례 대장 `case-ledger.json`, 감사 `trace-audit.json`, X4 `x4-scan.json`, 고정 문장 `fixed-sentences.json`, 분기별 증거·계획) |
| `acceptance-live-rehearsal/` | live 연습(fixture 서버, 실호출 0) |
| `acceptance-live/` | 실제 live 단계(실호출 2회) |
| `regression-chain.txt`, `regression/m27/`·`regression/m26/`·`regression/m25/`·`regression/m24-regression/` … `regression/m13-regression/` | 회귀 사슬(기록 끝에 `.deps` 두 폴더가 없음을 보인 `ls` 줄과 커밋된 내려받기 파일 110개의 해석) |
| `clean-install/record.txt`·`pip-freeze.txt`·`npm-ls.txt` | 새 컴퓨터 설치 시험(`record.txt`의 "package and binary repository hosts" 절: 호스트 넷과 개수, Git 제외 원 로그 `frontend/tests/offscreen/artifacts/m28-final/clean-install-logs/`의 경로·크기·SHA-256, 클론 커밋 `6da1670a`와 README 동일) |
| `network-ledger.txt` | 외부 요청 장부(설치 호스트 넷 줄, 실호출 두 줄. 실호출 줄의 시각은 dispatch 이벤트 시각 18:44:51Z·18:45:50Z, 시각의 출처를 적은 끝 줄) |
| `findings-triage.md` | 미해결 문제 최종 분류 요약 사본 |
| `doc-existence-check.txt` | 문서 마감(T17)의 모듈 이름 존재 표·게이트 목록 대조·금지 표현 검사 |

Git 제외(경로·크기·SHA-256만 커밋 증거에): `frontend/tests/offscreen/artifacts/m28-final/fixture-official/`(파일 308개 + 보류 텍스트 39개), `…/live/`(94개 + 보류 2개), `…/live-rehearsal/`(94개 + 보류 2개), `…/export-full/`(회귀 큰 텍스트 53개), `…/clean-install-logs/`(설치 시험 단계 로그, `record.txt`가 경로·크기·SHA-256을 적은 6개와 빈 로그 둘 `clone.log`·`venv.log`). QA run과 대장은 `runs/m28-*`·`runs/m28-live-ledger.json`.

## 독립 검토 요약 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 의도 감사(명세 작성 전): "M7을 통과하는 로컬 구조는 1UBQ뿐"이라는 전제를 8구조 사전 검사로 다시 확인했고(전제 맞음), 통과 기준·결함 처리·완성 선언 주체(⑧), 고칠 항목(⑨), QA 범위(⑩)를 사용자에게 물어 정했다.
- 독립 코드 검토 셋(T10, 고정 전, 읽기 전용): 검토자 둘(실행기·감사·대장 / 분기 하네스·T2·T3)과 T11 수정분 재검토 하나. 막는 지적은 모두 고친 뒤 고정했다.
  - 첫 검토 둘의 막는 지적 R1–R5(`9c5d49eb`): R1 실제 live에서 분기 일부만 보내는 것을 거절하고 예약 수 = 실행 상한, R2 바퀴를 보냈는지를 하네스 자기 보고가 아니라 분기 앞뒤 dispatch 이벤트로 판정(dispatch가 있는데 완료 결과가 없으면 `product_failed`), R3 B8·C7은 앞 사례가 모두 있어야 통과하고 기대 보고서 종류·개수를 계획에 둠, R4 B4 머리말·일괄·GA 영역 문구와 복원 단언·C4·A6 단언 보강, R5 선행 사례 연쇄(B4는 B2·B3·B7, B5는 B2·B3, C6은 C3)를 하네스와 실행기가 같게. 권고 가운데 일부(유출 파일 되돌림, 대장 없는 잠금 거절, 분기별 dispatch 상한, 모든 run 감사, 분기별 탭 글자 필수, 감사의 `row_fingerprint`·빈 주장 규칙, 첫 대장 쓰기를 비관적으로 등)를 반영했고(`c1644221` 포함) 나머지는 조율 세션의 T11 지시("고치지 말고 이유와 함께 보고", Git 제외 작업 문서)대로 고치지 않고 문서 입력으로 미뤘다(아래 하위 항목). 권고가 모두 반영된 것은 아니다. T2·T3·분기 A·해시 고정 파일 27개 불변은 문제없음으로 확인됐고, X4 `label` 일치·전송 본문 JSON 줄 문자열 검사·두 반응 가족의 표 비대칭·루프 풀 선택·분기별 도킹 설정 차이·M7 "전위 변화" 줄은 문제없음 또는 범위 표 기재 권고였다.
  - 고치지 않고 문서 입력으로 미룬 권고와 기록한 곳: `hbondLines`의 부정어 판정이 느슨함(같은 줄에 "아님/not/no" 등만 있으면 통과, X4가 보완, 범위 표 18번 (1)), X2 보완 사례를 run이 아니라 보고서 종류 단위로 맞춤(18번 (2)), `covering_tests` 이름의 존재 검사 없음(지금 쓰는 사례 없음, 18번 (3)), C1 "제외 이유" 열과 C2 HIS·CYS 구조별 값 칸을 화면에서 직접 단언하지 않고 data 속성·`protonation-none` 위주로 확인(18번 (4)·(5)), 옛 하네스 표 대조 단언 중 복원하지 않은 것(18번 (6)), A3이 SASA를 독립으로 다시 계산하지 않고 저장 필드·Markdown과 대조함(범위 표 10번, N7), B4 "점수 없는 행은 늘 끝"과 B5 G2의 조건이 생기지 않음(범위 표 12번), M20 @2의 새 하위 제목 둘의 문서화(`docs/business-rules.md` M20 보고서 형식 절·`docs/engineering-notes.md`, N4), 기본 `--out`이 실행한 날짜 폴더임(`docs/engineering-notes.md` M28 함정, 공식 실행은 `--out`을 명시).
  - 재검토의 막는 지적 둘(`a18dd488`): 첫 실제 live가 대장 쓰기 전에 거절되면 잠금 파일만 남는 문제(첫 입장에서 빈 대장과 잠금을 함께 만들고, 실제 live는 `--live-calls 2`만 받아 대장 전에 거절), 리간드 바퀴가 `not_sent`여도 단백질 바퀴가 나가는 문제(L-B7이 dispatch 정확히 1건으로 `completed`일 때만 L-C6 전송). 권고 넷(바퀴당 dispatch 정확히 1, 둘째 내보내기 예외 보호, 유출된 `SHA256SUMS` 되돌림, X4 탭 글자를 요청 분기 기준으로)도 반영했다. 고치지 않고 미룬 관찰은 절 132·133·134다.
- 독립 증거·기록 검토(T19, 2026-10-12, 고정 뒤 증거와 T4·T17·T18 문서, 읽기 전용): 증거·문서를 만들지 않은 새 검토자 둘(증거 쪽·문서 쪽). 첫 결과는 둘 다 `issues`였고 막는 지적은 7건(증거 3·문서 4)이었다. 모두 문서·증거 텍스트 수정으로 처리했고(T20) 소스·실호출·게이트·QA는 다시 돌리지 않았다.
  - 증거 쪽 처리(조율 세션, `5b4ad1f5`·`210e8ded`): `network-ledger.txt`의 실호출 두 줄 시각을 dispatch 이벤트 시각(18:44:51Z·18:45:50Z)으로, 설치 호스트 줄을 단계 시작 시각으로 고치고 시각의 출처를 적음. 설치 시험 `record.txt`에 호스트·개수 절, Git 제외 원 로그의 경로·크기·SHA-256, 클론 커밋 설명을 더함. 게이트 원 로그를 `gate-raw/`에 커밋. `regression-chain.txt`에 `.deps` 두 폴더가 없음을 보인 `ls` 줄과 커밋된 내려받기 파일 110개의 해석을 더함. `gate.txt`에 세 회차의 읽기를 더함.
  - 문서 쪽 처리(T20 문서 커밋, 지적 A–G): A 절 97의 분류를 `수용`에서 `사용자 결정 필요`(기본값)로 바꾸고 개수(수용 33·사용자 결정 필요 85, 기본값 61)를 개수가 적힌 모든 문서에 맞춤. B 판정 줄의 명세 §3.3 (b) 인용을 문구 그대로 하고 N10에 해당 절을 열거. C `범위 밖` 적용의 근거(명세 §1 목록)와 경계의 `수용` 판단을 해석 메모 N13으로. D 제품 키 해석기 서술을 실행기 코드대로 정정(연습이 아닌 단계의 증거 키 검색에서도 자식 프로세스로 부름: fixture 1·live 2·연습 0, `scripts/AGENTS.md`·`docs/engineering-notes.md`·`docs/system-architecture.md`·이 기록). E 미룬 권고와 하네스 단언 깊이의 한계(위 하위 항목, 범위 표 18번). F 작은 사실 정정(live 뒤 변경 경로 집합, 절 98의 "세 곳", 절 130의 행 번호, README 문서 목록, `findings-triage.md`의 조정 전 상태 표시, `CLAUDE.md`·`AGENTS.md` 트리 표기, 해석 메모 N14). G 이 줄과 "남은 일".
  - 검토자가 확인한 것의 핵심: 사례 수 fixture 31·연습 9·live 9, dispatch 2 = 대장 2, `SHA256SUMS` 전수 일치(회귀 폴더에서 읽을 수 없는 53개는 `ARCHIVED-EVIDENCE.sha256`에 적힌 Git 제외 보관분), 유출(키·placeholder·실제 kbase 문구·사용자 절대 경로) 0, 호출 키 해시 파일 27개와 `also_hashed_files` 11개 불변, 미해결 문제 137절의 분류 대조.
  - 최종 검토: 새 검토자의 재검토는 하지 않았다(재검토 없음, 반영만 확인). 반영 뒤의 최종 확인은 조율 세션이 지적 반영을 확인하는 것으로 갈음한다. 명세 §3.3의 "독립 증거 검토가 통과"를 "막는 지적을 모두 반영하고 조율 세션이 반영을 확인함"으로 읽은 것은 해석이다(N14, 사용자 확인 요청).

## 해석 메모 (사용자 확인을 구하는 것)
명세가 말하지 않았거나 명세와 다르게 읽은 곳이다. 각 메모는 무엇이 / 어떻게 정했나 / 왜 괜찮나 순서이며, **모두 사용자 확인을 구한다**. 결정이 필요한 것은 특히 N2·N6·N9·N10·N13·N14다.
- N1 사례 실행 순서(사용자 확인 요청). 명세 표 순서대로 한 run에서 돌리면 예산 때문에 B7·C6이 막힌다(루프에는 증액 경로가 없고 M19·M22·M23 증액은 부족분만 올린다). / 분기 안 순서를 B: B1, B2, B3(+같은 인자 재제출), B6, B7(탐색형 → 활용형), B4, B5(설정 1 → 2), B8, C: C1, C2, C3, C5, C6(탐색형 → 활용형), C4(설정 1 → 2), C7로 정했다. 사람 증액 클릭은 B 3번·C 2번이다(근거 `preflight.md` (e)). / 사례 ID와 선행 관계는 그대로이고 명세는 실행 순서를 정하지 않는다. live는 B와 C를 다른 run으로 했다.
- N2 A1의 "기본 정책"(사용자 확인 요청). 도구 명세·`docs/business-rules.md`의 물 정책 기본값은 `keep_all`이고 화면·고정 파이프라인의 기본값은 `strip_all`이다. / 실제 UI 클릭 사례이므로 화면 기본값(`strip_all`)으로 했고 기대값(잔기 313·원자 2,526)도 그 정책으로 입력 파일에서 셌다. / 두 기본값의 차이는 `docs/engineering-notes.md`에 적었고 어느 쪽을 기준으로 할지는 사용자 결정이다(절 137).
- N3 B2 입력(사용자 확인 요청). 고정 교체와 사용자 반응 SMARTS를 함께 쓰는 작은 기존 입력이 없었다. / 기존 합성 표시 파일 조합(`ligand_ga/synthetic-ga-small-blocks.smi` + `ligand/synthetic-blocks.sdf` + `ligand_ga/synthetic-ga-pool2000-rules.json`의 `user_2`·`user_3`)을 썼고 새 합성 파일은 만들지 않았다. / 합성 표시 자료임을 범위 표 11번에 적었다.
- N4 M20 보고서 형식 @2 규칙(사용자 확인 요청). 명세 §10.2는 "새 보고서에 쓰고"라고만 했다. / 참조값(번호 대응·주석 handle 또는 M-CSA 항목 ID 주장)을 인용하는 새 보고서만 @2이고, 인용 없는 새 보고서와 이미 저장된 @1 보고서는 그대로다(바이트 동일). 번호 대응 표는 handle만 있어도 싣고 반응 표는 M-CSA 주장이 있을 때만 싣는다. M15 표의 둘째 문장 하나는 M20에서 사실이 아니라 뺐다. 새 하위 제목 둘은 고정 문장이 아닌 새 템플릿 글자다. / "새 보고서 전부 @2"는 수정 금지 기준선 비교 시험을 깨고, 인용 없는 보고서에 빈 표를 싣지 않는 것이 "인용 없음"을 0이나 "없음"으로 보이지 않는 규칙과 맞는다.
- N5 X4 예외 방식(사용자 확인 요청). 명세는 "줄 단위 예외"라고만 했다. / 예외는 세 방식 19개다: 줄 일치 10, 숫자를 `#`로 바꾼 템플릿 일치 8, `label` 일치 1(포켓 보고서 공동 번호 머리 부분만이며 뒤의 잔기 목록은 계속 검사). 예외마다 종류·사례·소스 위치·이유가 `acceptance-fixture/evidence/case-ledger.json`의 `x4`와 `x4-scan.json`에 있고 원문 줄은 Git 제외다. 전송 본문 JSON 줄은 문자열 단위로 검사한다. / `label` 일치는 명세의 줄 단위 예외를 약간 넓힌 해석이며 fpocket이 실행마다 다른 번호를 내 줄 해시 예외가 불가능해서 택했다. 독립 코드 검토가 문제없다고 봤다.
- N6 실호출 규칙과 한계(사용자 확인 요청). 명세는 합계 2회·재시도 없음만 정했다. / 실제 live는 `--live-calls 2`·분기 전체(b·c)만 받고(부분집합·1회는 대장을 건드리기 전에 거절), 단백질 바퀴(L-C6)는 리간드 바퀴(L-B7)가 dispatch 정확히 1건으로 `completed`일 때만 보내며, `completed`·`provider_failed`는 바퀴의 dispatch가 정확히 1건일 때만 인정한다. 결과는 둘 다 `completed`다. / 한계: 대장과 `.lock`을 함께 지우거나 옛 사본으로 되감으면 상한이 되돌려진다(대장 밖 독립 기준점 없음, M25와 같은 설계, 절 132). L-C6만 못 나갔다면 그것만 다시 보낼 수 없었다(절 133). live L-C6 탐색형의 "본문에 점수 없음" 확인은 비어 있다(절 134, fixture C6·live B7에서는 비어 있지 않게 확인).
- N7 역추적 감사의 범위(사용자 확인 요청). / 검사 다섯(다시 열기, 근거 객체 존재, 주장 필드, 참조값 출처, 증거 종류 섞임), 보고서 종류 어댑터 20종, 없는 종류는 실패다. 점검 보고서·`interface_sasa`는 제품이 다시 열 때 주장·Markdown을 다시 만들지 않아 `partialProductRecheck`로 표시하고 A2·A3의 독립 기대값으로 보완했다. A3가 실제로 한 일은 SASA를 독립으로 다시 계산한 것이 아니라 저장 필드·Markdown 줄과의 대조다. / 범위 표 10번과 절 136에 적었다.
- N8 소스 고정 뒤 경로 집합(사용자 확인 요청). 명세 §8.2 (a)는 `AGENTS.md`라고만 적었다. / `scripts/AGENTS.md`·`frontend/AGENTS.md`도 그 "AGENTS.md"로 읽었다. / 둘 다 문서이고 코드·시험·훅이 읽지 않는다(`gate.txt` 끝에 기록).
- N9 PDBFixer의 지원 환경 문구(사용자 확인 요청). 명세 §3.2 7번은 PDBFixer를 macOS arm64 전용 잠금이라고 적었다. / 착수 때 이 전제를 바로잡았다: PDBFixer 1.12.0은 `backend/pyproject.toml` 핀(sdist 해시 고정)이고 플랫폼 잠금이 아니며 새 컴퓨터 설치에서 sdist로 빌드되어 설치됐다. 범위 표 7번은 사실대로 적었다. / 검증은 macOS arm64에서만 했다는 점은 그대로다.
- N10 `사용자 결정 필요` 85개와 판정(사용자 확인 요청, 결정 필요). 명세 §3.3의 `보류` (b)는 문구 그대로 `호출 키 해시 파일·닫힌 집합·고정 문장·상한을 바꿔야 하는 결함이 남았거나`다. / 고치려면 그런 변경이 필요한 절이 남아 있다(`docs/qa/m28-final-20261011/findings-triage.md` "조율 세션이 판단할 것"과 대조): `사용자 결정 필요`(본문 근거) 중 해시 고정 파일·닫힌 집합·한도 변경이 필요한 11절 — 20(식별자 버전·호출 키), 41(SVG 상한·부모 중원자 한도), 63(guardian 출력 상한·해시 고정 일괄 작업 모듈), 76(M7·M18 한도), 87(`sequence_ga_*`), 91(M24 이유 집합), 94(`mutation_candidates.py`), 101(M7 사전 검사·M21 해시 경로), 112(M20 입장 이유 집합), 125(M27 서지 규칙), 128(M27 보고서 금지어 목록) — 과 저장 형식 변경만 필요한 5절 — 10·25·42·46·136(보고서 렌더 버전·API 계약·필터 형식·다시 열기 규칙) —, 그리고 `수용`이면서 그런 변경이 필요한 8절 — 50(`docking_result@2`), 58(`docking_worker.py`), 59(`docking_batch_worker.py`), 69(M20 이유 집합), 78(M21 호출 키), 106(M20 해시 파일·저장 형식, 명세 §10.3이 닫음), 113(M20 읽기 422 이유), 131(`docking_worker.py`, 이번 단계에서 찾은 `run_qvina`의 작은 틈) — 이다. 이 절들은 M27까지 이월된 한계이거나 이번 단계의 관찰이고 완성 정의 6항목의 사례 사슬을 막지 않으므로 (b)의 "결함"이 아니라 이월된 한계로 읽어 판정을 `검증 통과, 사용자 확인 대기`로 두었다. 이것은 해석이며 사용자 확인이 필요하다. / 사용자가 다르게 읽으면(이 절들 중 하나라도 남은 결함으로 보면) 판정을 `보류`로 바꿀 수 있다.
- N11 설치 시험의 Electron 문장(사용자 확인 요청). / README·운영 문서의 "`npm ci`가 Electron 실행 파일을 받는다"는 electron 44.4.5에서 사실이 아니어서 고정 뒤 문서로 정정했다(실행 파일은 첫 사용 때나 `npx install-electron --no`가 GitHub 릴리스에서 받는다). / 이 컴퓨터는 캐시 hit라 내려받기 자체와 리다이렉트 대상 호스트는 관찰하지 못했다.
- N12 분기 C의 하네스 선택(사용자 확인 요청). / 루프 풀에서 M21 대상(I44W)과 Gly·Pro·Cys 위치를 뺀 것은 하네스 선택이다(fixture 탐색형 풀에는 I44W를 넣어 "본문에 점수 없음" 확인을 비어 있지 않게 했다). 도킹 설정은 분기 C(C3·C4·C6: 상자 여유 8 Å, seed 20261004, exhaustiveness 4, 모드 5)와 분기 B(exhaustiveness 1, 모드 2)가 다르고 각 분기 안에서는 같다. C2의 M7 OpenMM 보고서에 있는 "전위 변화"는 한 구조의 최소화 전후 값이며 두 구조 사이 차이가 아니다. / 모두 합성값이 아니고 제품 규칙 안의 선택이다.
- N13 `범위 밖` 분류의 근거와 경계의 `수용` 판단(사용자 확인 요청). 명세 §11.3의 `범위 밖` 정의는 한 줄("미구현 기능에 관한 것(GPCR, 탭 알림, 작업 목록, Linux 잠금 등)")이다. / `범위 밖` 5절은 이 정의보다 넓게 **명세 §1이 열거한 범위 밖 목록**(GPCR 계열 지식, Linux·Intel Mac 작업 환경 잠금, 다른 탭 알림·run 전체 작업 목록, 외부 구조 새로 받기, 실제 결합 맥락(효소 + 기질/억제제)의 변이 도킹)에 근거해 붙였다: 8(Linux·Intel Mac 잠금), 75(리간드가 있고 M7을 통과하는 공개 복합체가 필요 = 외부 구조 새로 받기·실제 결합 맥락의 변이 도킹), 86(큰 공개 구조의 측정 = 외부 구조 새로 받기), 121(`7Z87`·`8H7G`가 필요 = 외부 구조 새로 받기), 122(영역 사이 알림 = 다른 탭 알림). 외부 구조 새로 받기와 실제 결합 맥락의 변이 도킹은 미구현 기능이라기보다 자료·범위의 선택이다(`findings-triage.md`의 `범위 밖` 정의 문장도 이렇게 고쳤다). 경계에 있는 `수용` 판단도 함께 확인을 구한다: 절 21·28은 결정 0023의 보수적 대응 원칙("틀린 대응보다 대응 없음")에 비추어 `수용`(`findings-triage.md` 판단 3, 보수적으로 읽으면 `사용자 결정 필요`), 절 119는 결정 0034 ⑦의 실서버 가져오기 할당을 모두 썼다는 것이 근거이며 한계 자체를 받아들인 결정은 아니고, 절 1·6·56·65·120은 날짜 있는 사용자 결정이 아니라 기록 불변 규칙(`docs/qa/` 수정 금지)과 결정 0002·0010을 근거로 `수용`했다(판단 2). / 사용자가 좁게 읽으면 이 절들은 `사용자 결정 필요`(기본값)가 되고 개수만 바뀐다. 이 분류들은 정의 6항목의 사례 사슬과 무관하다. 절 86은 본문 사유에 큰 공개 구조뿐 아니라 "몇 시간의 실행 예산"과 "상한과 기본 규모를 사용자와 다시 정한다"는 방향도 있어, 섞인 절은 가장 보수적으로 둔다는 판단 5를 적용하면 `사용자 결정 필요`로 읽힐 수 있다 — 이 경계도 함께 확인을 구한다.
- N14 게이트 회차·회귀 내려받기·연습 대장·설치 클론·T19 통과의 읽기(사용자 확인 요청). / (1) 게이트 1회차가 명세 §10.1(§13)의 "연속 3회" 중 첫째이면서 §8.2의 최종 게이트(다시 돌리기 없이 한 번에 통과)를 겸했다. 명세 문언은 연속 3회 뒤 최종 게이트를 따로 돈다고 읽힐 수 있다. 2·3회차는 같은 소스에서 이어 돌렸으므로 최종 게이트 뒤에도 두 번 더 통과했다(`gate.txt` 끝 "note on the three rounds", 원 로그 `gate-raw/`). (2) 회귀 `regression/` 폴더에는 옛 실행기가 내보낸 내려받기 파일 110개(`downloads/`, Markdown 53·JSON 57)가 커밋되어 있다. M27 회귀 증거와 같은 구성이며, 명세 §5의 "보고서 다운로드는 Git 제외"를 M28 실행기의 증거에만 적용하고 옛 실행기 증거는 각자의 규칙(256 KiB 초과 텍스트는 결정 0020대로 Git 제외)을 따른다고 읽은 것이다(실제 kbase 문구는 없음, `regression-chain.txt` 끝). (3) 연습 대장(`acceptance-live-rehearsal/evidence/case-ledger.json`)은 항목 5를 `pass`, L-B7·L-C6을 `completed`로 적지만 fixture 서버의 스크립트 응답 결과다. 연습 대장의 `acceptance`는 설계상 늘 거짓이고(`rehearsalPassed: true`가 통과 여부) 판정에는 fixture·실제 live 두 대장만 쓴다. (4) 설치 시험은 고정 `a18dd488`이 아니라 문서만 다른 `6da1670a`를 클론했다. README는 같으므로(`git diff a18dd488 6da1670a -- README.md` 비어 있음) 고정 커밋의 클론과 같은 설치로 읽었다(위 "설치 시험"). (5) 명세 §3.3의 "독립 증거 검토가 통과"는 T19의 막는 지적 7건을 모두 반영하고 조율 세션이 반영을 확인한 것으로 읽었다(새 검토자의 재검토 없음, 위 "독립 검토 요약"). / 모두 증거를 바꾸거나 다시 돌리지 않고 기록으로 남긴 읽기이며, 사용자가 다르게 읽으면 닫는 방법(예: (1) 게이트를 한 번 더 돌림, (5) 새 검토자의 재검토)은 사용자가 정한다.

## 업그레이드 뒤 사용자가 할 일
`docs/operations.md` "업그레이드 뒤 할 일"과 같다.
1. 사용자가 할 데이터 이전은 없다. M28이 바꾼 제품 코드는 `backend/mw/mutation_reports.py`(M20 보고서 형식) 하나이고 호출 키 해시 파일·결과 객체 형식·`backend/pyproject.toml`·`frontend/package-lock.json`·프런트엔드 화면 소스·`config/`는 바뀌지 않았다(`frontend/package.json`에는 npm 스크립트 `test:offscreen:endtoend` 한 줄만 더했다). 그래서 저장된 M18·M19·M21·M22·M23 결과의 자동 재사용과 큐에 있던 작업은 그대로이고 참조 폴더·환경 변수·`.deps` 작업 환경도 바꿀 것이 없다.
2. 이미 저장된 M20 변이 후보 보고서(`mutation_candidates_markdown@1`)는 참조값을 인용한 것도 지금과 같은 바이트로 다시 열리고 내려받힌다. 업그레이드 뒤 새로 만드는 M20 보고서 중 번호 대응·주석이나 M-CSA 항목 ID를 인용하는 것만 `@2`가 된다. 옛 보고서에 출처표가 필요하면 같은 후보 집합으로 보고서를 새로 만든다(옛 보고서는 그대로 남는다).
3. 옛 단계 수락 실행기(M13–M26)를 돌릴 때는 `.deps/precedent_reference`와 `.deps/reaction_reference`를 없는 채로 둔다(M26·M27 기록과 같음).
4. 다른 사람에게 주거나 압축해 공유할 때는 `runs/`(종단 QA 격리 root `runs/m28-*`·실호출 대장 포함), `.deps/`, `.env`, `frontend/tests/offscreen/artifacts/`를 뺀다(README "데이터 보관과 공유").

## 알려진 한계
- 완성 정의의 항목 2(지식)는 키나아제·효소로만 보였고 GPCR은 범위 밖이다. 항목 4는 촉매 보호(1A30)와 변이 모델링(1UBQ)이 서로 다른 구조에서 보였고, 변이 도킹은 합성 표시 페놀 SDF로 경로만 보였다. 리간드 쪽 building block·반응 규칙은 합성 표시 자료다.
- 실제 모델 호출은 바퀴 한 번씩(2회)이고 나머지 목표는 fixture 서버 응답이다. 고른 목록 위치는 관찰값이다.
- 검증은 macOS arm64 CPython 3.11에서만 했다.
- 역추적 감사는 근거 구조·출처를 보며 값 재계산과 Markdown 서술 속 숫자 파싱을 하지 않는다(점검·`interface_sasa` 보고서는 사례 대조로 보완).
- 이번 단계에서 찾은 문제 9개(절 129–137)와 이월된 문제는 `docs/tracking/findings.md`의 최종 분류를 따른다.
- 기록 대조: 회귀 사슬 기록의 끝 시각(위 "회귀 사슬 결과"의 메모)은 독립 검토 전에 바로잡았고 T19가 검토했다. 실호출 장부의 시각, 설치 호스트 개수, 게이트 원 로그는 T19 지적으로 증거 텍스트를 보강했다(위 "독립 검토 요약").
- 하네스·실행기 단언에는 깊이의 한계가 있다(범위 표 18번).

## 대체한 과거 검증 범위
- M28이 바꾼 공유 소스: `backend/mw/mutation_reports.py`(M20 보고서 형식 @2), 시험 `backend/tests/test_sequence_ga_worker.py`·`test_pocket_jobs.py`·`test_jev_reports.py`(T2)·`test_mutation_reports.py`와 fixture `backend/tests/fixtures/mutation_report_v1/`(T3), `frontend/package.json`(npm 스크립트 한 줄), `.codex/hooks/stop.py`(`SCRIPT_TESTS`에 M28 시험 넷). 새 파일은 `scripts/m28_*.py` 일곱과 `scripts/test_m28_*.py` 넷, `frontend/tests/offscreen/endtoend-{a,b,c}-flow.cjs`다. 호출 키 해시 파일, M13 흐름, M15·M16·M17·M24·M25·M26·M27 모듈, 결과 객체 형식, 닫힌 집합·고정 문장·상한은 바꾸지 않았다.
- 이 소스 기준의 현재 검증은 전체 백엔드·스크립트 pytest(6,379개, 열여덟 그룹 3회 연속), M28 종단 수락(fixture·live), M27(fixture·real)·M26(fixture·real)·M25(fixture)·M24(fixture)·M23·M22·M21·M20·M19·M18·M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함), 골든 셋으로 대체한다. M24·M25 실행기의 실호출 단계는 다시 돌리지 않았고(명세 R7) 실제 JEV 경로는 M28 live 단계 두 바퀴가 대신 보였다. M13 수락 실행기가 돌리지 않는 과거 범위는 M13 기록의 "대체한 과거 검증 범위"와 같다.

## 다시 돌리는 방법 (주 체크아웃 루트, 8000·3000 포트 비움, 한 번에 하나)
```bash
# 종단 fixture 단계(분기 셋, 실호출 0)
.venv/bin/python scripts/m28_offscreen_acceptance.py --root runs/m28-fixture-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/<이름> \
    --kbase <절대 경로>/kbase_kinase --out docs/qa/m28-final-<YYYYMMDD>/acceptance-fixture
# live 연습(fixture 서버, 실호출 0)
.venv/bin/python scripts/m28_offscreen_acceptance.py --phase live --rehearse --root runs/m28-rehearse-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/<이름>-rehearse
# 회귀 사슬(.deps/precedent_reference·.deps/reaction_reference는 없는 채로): docs/operations.md "M28 종단 수락 QA"의 명령
```
실제 live 단계(`--phase live --live-calls 2`)는 사용자가 실호출 할당을 새로 정해 줄 때만 새 `--root`로 돈다(이번 할당 2회는 모두 썼고 대장 `runs/m28-live-ledger.json`이 막는다). 설치 시험·인자 전체·증거 규칙은 `docs/operations.md` "M28 종단 수락 QA"에 있다.

## 사용자 확인 기록
- 상태: **대기**. 확인 문장과 날짜는 사용자가 확인한 뒤 메인 세션이 이 절에 적는다(판정 줄과 `docs/tracking/status.md`·`docs/tracking/roadmap.md` M28 행·`CLAUDE.md`·`AGENTS.md` 머리말도 같은 커밋에서 바꾼다). 사용자가 이의를 내면 판정은 `검증 통과, 사용자 확인 대기` 또는 `보류`로 남는다.

## 남은 일
- 독립 증거·기록 검토(T19)는 끝났고 지적은 T20에서 모두 반영했다(재검토 없음, 조율 세션이 반영을 확인). 남은 것은 사용자 보고와 확인, 단계 브랜치 → main 병합(사용자가 요청할 때)이다.
- 해석 메모 N1–N14(특히 N2·N6·N9·N10·N13·N14)를 사용자가 확인한다.
- `사용자 결정 필요` 85개를 고칠지·언제 할지 사용자가 정한다.
