# 진행 현황

기준: 2026-10-03, 브랜치 `dryforge/m19-batch-docking`(`phase/m19-batch-docking` = main `2c04db4`에서 분기). M18까지 main에 병합됨(M18 병합 `e0b84ea`, 기록 `2c04db4`). M19 완료(고정 `858bd45`, 증거 커밋 `c11bfb4`, 수락 증거 `docs/qa/m19-batch-20261003/`). main 병합: `20e652c`.

## 완료 (단계 게이트와 당시 검토 통과)

| 단계 | 기능 | 커밋 | 당시 검증 | 현재 해시 기준 재검증 |
|---|---|---|---|---|
| M0–M5 | 불러오기·전처리, Mol* 뷰어·기하 접촉, 제한된 재시작 가능 런타임, 로컬 전용 외부 게이트, 영속 작업 큐(Rosetta는 사용 불가), 증거 연결 보고서·inspect_complex | `d22fe15` | 테스트, 브라우저, 검토, `--verify` 통과 | 오래됨(README 변경) |
| M6 | FreeSASA 단백질–리간드 SASA(Å²)와 방법 보고서 | `50569ee` | 테스트, 해석 검사, 브라우저, 검토 통과 | 오래됨(README·AGENTS·ARCHITECTURE) |
| M7 | OpenMM 단백질 전용 최소화(kJ/mol), 영속 복구, 프로세스 신원 수정 | `e0abffc` | 실제 계산, 독립 전위 재계산, 호스트 288개 검사(skip 0), 브라우저, 검토 통과 | 오래됨 |
| M8 | 프롬프트 → 실제 모델 → typed 뷰어 명령 → Mol* 적용 확인, Electron 오프스크린 86항목 클릭 검증, 실제 모델 호출 4회(할당 소진) | `392d45a`, `052b6cd` | 검토 통과 | 오래됨(README, 새 AGENTS.md) |
| 통합 | M6–M8을 main에 병합, 오프스크린 보고서 캡처 안정화 | `ef6f2c7`, `6894ab4` | 통합 검증 통과 | — |
| M9 | 저장된 보기(원본·전처리·최소화 구조), PNG + 출처 JSON 내보내기 | `479d961` | 검토 통과 | 오래됨(README) |
| M10 | 원자 거리(Å), 명시적 CA 쌍 Kabsch 정렬·오버레이, 공유 선택 어댑터 수정 | `4ab0186` | 검토 통과 | 오래됨(README) |
| M11 | ProLIF 화학 상호작용(준비된 수용체 + V2000 SDF, 새로 만들기·기존 복합체 연결), 작업 수명 주기 보강, Host 허용 목록 | 고정 소스 `4ec584f`, main 병합 `adb6291` | 전체 게이트, 수락 QA H01–H17, M8–M10 회귀, 코드·증거 독립 검토(Opus 5.5) 통과 | M13 수락 QA에서 M11 수락 실행기 전체 재실행(17/17) |
| M12 | fpocket 4.2.3 로컬 포켓 후보(단백질만 투영, 알파 구·주변 잔기·fpocket 기술자 5개), Mol* 알파 구 오버레이(메인·화학 작업 화면), 포켓 보고서, 작업 수명 주기, 잔기 이름 대응 10개 | 고정 소스 `9e4edcb`, main 병합 `eb73d12` | 전체 게이트, 수락 QA 31단계, M8–M11 회귀, 코드·증거 독립 검토(Opus 5.5) 통과 | M13 수락 QA에서 M12 수락 실행기 전체 재실행(31/31) |
| M13 | 결정적 로컬 분석 흐름: 목표 템플릿 6개, 불변 계획 `analysis_plan@1`(`local_rules`), 계획 승인과 계산 승인 분리, 한 번에 한 단계, 재시도 1회, 범위 한정 중지, 충돌 복구, `workflow_summary@1`, 메인·화학 작업 화면 흐름 패널, `Run.call`·작업·보고서 내부 실행 연결 | 최종 고정 `e83071b`(최종 검토 수정 `86bbff3`), main 병합 `50ca0b4` | 전체 게이트, 수락 QA 17단계·28사례, M8–M12 회귀(M11·M12 실행기 전체), 코드·증거 독립 검토(Opus 5.5) 통과 | M14 회귀(M13 수락 실행기 전체, 고정 `4501aa1`) |
| M14 | 최상위 탭 4개(구조 분석 / 단백질 공학 / 리간드 설계·탐색 / 지식·보고서)와 전역 run·예산 줄, 기존 화면(화학 작업 화면 포함)을 숨긴 채 유지하는 구조 분석 탭으로 이관, 기능 없는 탭의 사용할 수 없음·여는 단계 안내, run 전체 보고서·그림·완료 흐름 요약 목록(내용 보기·다운로드). 백엔드 변경 없음 | 고정 `4501aa1`, main 병합 `da5e4bc` | 게이트, M14 수락 QA 15사례, M8–M13 회귀(M13 실행기 전체), 코드·증거 독립 검토(Opus 5.5) 통과 | M19 회귀(M14 수락 실행기 15/15, 고정 `858bd45`) |
| M15 | 지식 탭 첫 기능: `kbase_kinase/ref` 가공 참조 스냅샷 가져오기·세트 고정(결정 0022), 잔기 번호 대응 `map_residue_numbering`(SIFTS + 자체 전역 정렬, 두 방법이 같을 때만 대응됨, 충돌·대응 없음과 이유, KLIFS 포켓 번호, 결정 0023), `residue_numbering_map@1`, 읽기 API, 계산값·참조값을 분리한 보고서, 지식 탭 번호 대응 화면 | 첫 고정 `c1d824d`(증거 `4737847`), 최종 고정 `93c4fb1`(최종 검토 수정 `975cccf`, 증거 `0e376aa`), main 병합 `beaffcb` | 첫 고정: 전체 게이트(백엔드 806개), KLIFS 측정, M15 수락 QA 14사례, M14 회귀, M8–M13 회귀, 코드(수정 필요 → 반영)·증거(approve) 독립 검토. 최종 검토(approve, 권고 반영) 뒤 최종 고정: 전체 게이트(백엔드 815개, skip 0), M15 수락 QA 14사례, M14 회귀. 검토는 모두 Opus 5.5 | M19 회귀(M15 수락 실행기 14/14, 고정 `858bd45`) |
| M16 | 구조 분석 탭 참조 주석: 값싼 도구 `annotate_reference_sites` → `reference_site_annotation@1`(KLIFS 주요 부위 10개 `kinase_key_sites@1`, 같은 구조의 기하 접촉을 부위별로, 결정 0024), 읽기 API, 참조 주석 패널, Mol* 부위 강조·이름표·극성 접촉 점선(저장 거리), `viewer_scene@2`·`viewer_figure@2`(범례 기본 켬), 보고서 `reference_site_annotation`, 포켓 오버레이·M10 비교·M8 자연어와 배타. 그림 상한 유지 | 첫 고정 `b23cb10`(코드 검토 수정 `cc3da8e`, 증거 `a4ca298`), 재고정 `3a2e20c`(하네스만, 증거 `6f14094`), 테스트 추가 `71a3fa1`, main 병합 `0fb3426` | 첫 고정: 전체 게이트(백엔드 886개, skip 0), M16 수락 시도 1 실패(하네스 범례 영역), M15·M14·M13 회귀. 재고정: 하네스 관련 게이트, M16 수락 시도 2 19/19. 명세 검토 2회 통과, 코드 검토(권고 6, 반영), 증거 검토(approve, 권고 처리). 검토는 모두 Opus 5.5 | M19 회귀(M16 수락 실행기 19/19, 고정 `858bd45`) |
| M17 | 리간드 설계·탐색 탭 첫 기능: 부모 V2000 SDF 한 분자의 한 부위(나머지와 단일 결합 하나로 이어진 중원자 집합)를 고정 교체 `replace_single_bond_v1`·사용자 반응 SMARTS `user_reaction_smarts_v1`로 바꾼 2D 후보(SMILES), RDKit 속성 8개·PAINS A/B/C 구조 경고 일치, 작업 두 개 `rdkit_inspect_v1` → `ligand_inspection@1`·`rdkit_enumerate_v1` → `ligand_candidate_set@1`(각 승인·예산 1단위, 격리된 RDKit 2026.03.6 작업 프로세스), block SDF·SMILES 가져오기, 읽기 API 7개(필터는 저장값에 서버 평가), 보고서 `ligand_candidates`(요약 증거, `count_where`), 리간드 탭 화면(결정 0025) | 고정 `e6ab4f9`(코드 검토 수정), 증거 `a81f50a`, main 병합 `45ccad6` | 전체 게이트(백엔드 1206개, skip 0), M17 수락 QA 21사례, M16·M15·M14 회귀, M8–M13 회귀(M13 실행기 전체). 명세 검토 2회(지적 반영), 코드 검토(막는 지적 3 → 반영, 권고 다수), 증거 검토(approve, 권고 4 처리). 검토는 모두 Opus 5.5 | M19 회귀(M17 수락 실행기 21/21, 고정 `858bd45`) |
| M18 | 리간드 설계·탐색 탭 도킹 영역: 수용체 하나(M11 입력 규칙, 지정한 리간드 인스턴스 하나만 빼고 나머지 비표준 요소 거부) + 리간드 하나(3D SDF 또는 M17 후보)를 격리된 QuickVina 2.1(`qvina2`, conda-forge 2.1.0)로 자유 도킹하거나 코어 고정 구속 샘플에 `--score_only`만, 작업 `qvina_dock_v1` → `docking_result@1`(승인·예산 1단위, seed 직접·CPU 1, Meeko 0.8.0·RDKit 2026.03.6·MDAnalysis 2.10.0 작업 환경), 상자 출처 셋, 기하 접촉 표, 포즈 SDF 내려받기, 읽기 API 7개, 보고서 `ligand_docking`, 점수는 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"(결정 0026) | 고정 `23e2c03`(코드 검토 수정 `283cc72`), 증거 `8cb5d31`, main 병합 `e0b84ea` | 전체 게이트(백엔드 1404개, skip 0), 착수 확인(재도킹 RMSD 1.30 Å, 같은 seed 바이트 동일), M18 수락 QA 24사례(재현 검사 포함), M17·M16·M15·M14 회귀, M8–M13 회귀(M13 실행기 전체). 코드 검토(막는 지적 1 → 반영, 권고 반영·기록), 증거 검토(approve). 검토는 모두 Opus 5.5 | M19 회귀(M18 수락 실행기 24/24, 고정 `858bd45`) |
| M19 | 리간드 설계·탐색 탭 일괄 도킹 영역: M17 후보 집합의 후보 ≤ 50개(+ 자유 방식에서만 선택 부모 기준 행)를 한 수용체·상자·seed·방식·값으로 작업 하나(`qvina_batch_dock_v1`, 새로 계산하는 행마다 1단위, 시도 1회, 행당 300초·전체 7200초·작업 한도 7800초·출력 128 MiB)에서 차례로 도킹, 행 결과 = 단독 M18 `docking_result@1`(같은 handle, 수용체 한 번 준비), 행별 스테이징 + 종료 상태마다 서버 게시, 요약 `docking_batch_result@1`(`complete`/`partial`·멈춘 이유, 첫 행 점수 사본), 저장된 결과 자동 재사용(과금 없음), 시작 전 확인·사람 한도 증액 승인(부족분만, `budget_limit_updated` `by: human`), 결과표·열 정렬(점수 없는 행은 늘 끝)·행 → M18 상세, 보고서 `ligand_docking_batch`(결정 0027) | 고정 `858bd45`(코드 검토 수정 `f3cc8c6`·`4aa9fc2`·`b505830`·`858bd45`), 증거 `c11bfb4`, main 병합 `20e652c` | 전체 게이트(백엔드 1613개, skip 0), 착수 확인(수용체 한 번 준비 = 단독 M18 바이트 동일), M19 수락 QA 26사례(재현 검사 포함), M18·M17·M16·M15·M14 회귀, M8–M13 회귀(M13 실행기 전체). 코드 검토(막는 지적 없음, 권고 4건 반영·나머지 기록), 증거 검토(approve). 검토는 모두 Opus 5.5 | 현재 기준(`docs/tracking/m19-acceptance.md`) |

"오래됨"은 기능이 망가졌다는 뜻이 아니다. 검토 당시 파일 해시와 현재 파일이 달라, `scripts/execute.py --verify`가 그 검토를 현재 증거로 인정하지 않는다는 뜻이다. 현재 기능이 동작하는지는 아래 검사로 확인한다.

## 현재 검사 결과 (M19 고정 `858bd45`, 2026-10-03)

| 검사 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 1613개 통과, skip 0(1515초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 |
| 스크립트 pytest 14개 파일(M13–M19 실행기, 가져오기, 측정, 훅, 실행기, fpocket·qvina·도킹 작업 환경 설치) | 310개 통과, skip 0 |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow`·`ligand-flow`·`docking-flow`·`docking-batch-flow` | 통과 |
| `test:events`, `typecheck`, `build` | 277개 통과, 통과, 통과(수락 QA 빌드 `HZVIvlS1pgVkSE0gAkqD6`, 소스 도장 일치) |
| M19 수락 QA(`scripts/m19_offscreen_acceptance.py --regressions`) | 시도 1회, 26사례·2단계 통과(`acceptance: true`), 재현 검사(자유 일괄, 새 run 2개) 통과, dry-run 부족분·모드 0개 행·시간 한도·크래시·출력 총량 사례는 관찰하지 못함(위조하지 않음, 백엔드·프런트 테스트가 덮음), 외부 요청 0건, 제공자 호출 0회, 남은 프로세스 없음 |
| M18 회귀(`scripts/m18_offscreen_acceptance.py`) | 24사례 통과(`acceptance: true`, `D-zero-modes` 관찰하지 않음) |
| M17 회귀(`scripts/m17_offscreen_acceptance.py`) | 21사례 통과(`acceptance: true`) |
| M16 회귀(`scripts/m16_offscreen_acceptance.py`) | 19사례 통과(`acceptance: true`) |
| M15 회귀(`scripts/m15_offscreen_acceptance.py`) | 14사례 통과(`acceptance: true`) |
| M14 회귀(`scripts/m14_offscreen_acceptance.py`) | 15사례 통과(`acceptance: true`) |
| M8–M13 회귀(`scripts/m13_offscreen_acceptance.py` 전체) | 17단계·28사례 통과(`acceptance: true`), M11·M12 하위 실행기 통과 |

증거: `docs/qa/m19-batch-20261003/`(M19, `m18-regression/`·`m17-regression/`·`m16-regression/`·`m15-regression/`·`m14-regression/`·`m13-regression/` 포함), `docs/qa/m18-docking-20261002/`(M18, 회귀 5개 포함), `docs/qa/m17-ligand-20261001/`(M17, `m16-regression/`·`m15-regression/`·`m14-regression/`·`m13-regression/` 포함), `docs/qa/m16-annotations-20261001/`(M16, `m15-regression/`·`m14-regression/`·`m13-regression/` 포함), `docs/qa/m15-numbering-20260930/`(M15 첫 고정, `m14-regression/`·`m13-regression/` 포함, 최종 고정은 `refreeze-93c4fb1/`), `docs/qa/m14-tabs-20260930/`(M14), `docs/qa/m13-workflows-20260929-final/`(M13 최종), `docs/qa/m12-pockets-20260929/`(M12), `docs/qa/m11-chemical-20260928/`(M11). 옛 단계 기록은 M11 index pending(결정 0014), M12·M13 index 없음(결정 0016·0018). 다시 돌리지 않은 과거 범위는 `docs/tracking/m19-acceptance.md`·`m18-acceptance.md`·`m17-acceptance.md`·`m16-acceptance.md`·`m15-acceptance.md`·`m14-acceptance.md`·`m13-acceptance.md`의 "대체한 과거 검증 범위".

## 남은 전체 범위 (우선순위 순)

1. **M20–M28**: `docs/tracking/roadmap.md`. 다음은 M20(단백질 공학 탭 첫 기능: 변이 후보 생성, 포켓 주변 위치 × 허용 잔기, 촉매·보호 잔기 기본 제외). 리간드 쪽은 M19로 후보 일괄 도킹·점수 표·일괄 보고서까지 왔고, 다음 리간드 단계는 M22(GA 설계)다. M19 일괄은 같은 수용체·상자·seed·방식·값끼리만 나란히 보며 순위·차이를 말하지 않는다. M13 흐름의 계획·승인·한 단계 진행·중지·복구가 M17–M25 설계 루프의 실행 기반이다.
2. **공용화 이어서**: 소스·저장 보기·작업·계획 패널 공용화는 그것을 처음 필요로 하는 탭 단계에서 한다(결정 0021). 다른 탭 알림·run 전체 작업 목록도 M20 이후 다시 정한다(M17–M19는 새 공용 구성 요소를 만들지 않았다. M19는 리간드 탭 안에서 M17 `FilterForm`과 M18 `RefusalList`를 export해 함께 쓴다).
3. **정리 작업**: ProLIF·fpocket·qvina·도킹 작업 환경의 Linux용 잠금. `docs/tracking/findings.md`의 후속 항목(중복 Host 한계, 이벤트 로그 재파싱, GO 전 guardian 종료 정리, M12 QA 미검증 영역, 보고서 Markdown 이스케이프, M13 상단 예산 카운터 지연, M10 측정 원자 선택 flake, 공유 작업 실패 뒤 흐름 재실행, M14 전역 예산 읽기 실패 때의 예산 표시 정지, M15의 PDB 형식 합성 `chain_label`·KLIFS 적용 공백·이유 코드 목록과 범위 문장 중복·화면 체인 목록과 도구 규칙 차이(M16에서 다시 미룸), M16의 뷰어 쪽 `viewer_scene@2` 복원 거부 경로 미관찰·선택 가능한 부위 이름표, M17의 규칙 SMARTS 오류를 점검 뒤에야 앎·큰 부모 2D 그림 상한·일반 객체 읽기의 리간드 검증 없음·리간드 탭 작업 뒤 전역 예산 줄 지연, M18의 좌표계 일치 미검증·포즈 뷰어 표시 없음·수용체 비표준 요소 거부·`core_max_deviation_A`의 뜻, M19의 상자 계산 중복·늦은 신호와 남은 작업 폴더·제출 때만 하는 활동 시간 확인·멈춘 뒤 재사용 행·51행 읽기 비용·Stop 훅 다섯 그룹과 스레드 넷 등).

## 전체 로드맵

M13 이후 단계는 `docs/tracking/roadmap.md`에 정했다(2026-09-29 사용자 결정): M13 포함 16단계(M13–M28), 탭 4개(구조 분석 / 단백질 공학 / 리간드 설계·탐색 / 지식·보고서), JEV·GA 두 설계 모드, building block·reaction rule 리간드 설계, 계열 지식 연결. 각 단계의 세부 구현은 그 단계 착수 때 정한다. 배경 분석·출처 조사는 `docs/tracking/roadmap-analysis-20260929.md`.

## 계획에 없는 것 (별도 결정 필요)

돌연변이 설계와 ΔΔG, 리간드 힘장 매개변수화와 복합체 OpenMM, 형태 앙상블과 자유 에너지, 보존성 데이터베이스와 원격 조회, PAE·신뢰도 보기, 큰 궤적 데이터(현재 이벤트 payload 방식으로는 불가), 다중 사용자·인증·공유 서버·외부 공개, 플러그인, GUI 파이프라인 편집.

## 차단 요소

없음. M19는 사용자 통합 승인을 기다린다(main 병합 전). 다음은 M20.
