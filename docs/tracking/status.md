# 진행 현황

기준: 2026-09-29, 브랜치 `dryforge/m12-pockets`(`phase/m12-pocket-candidates` = main `adb6291`에서 분기). M11은 main에 병합됨(`adb6291`). M12 완료, main 병합은 사용자 결정 대기.

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
| M11 | ProLIF 화학 상호작용(준비된 수용체 + V2000 SDF, 새로 만들기·기존 복합체 연결), 작업 수명 주기 보강, Host 허용 목록 | 고정 소스 `4ec584f`, main 병합 `adb6291` | 전체 게이트, 수락 QA H01–H17, M8–M10 회귀, 코드·증거 독립 검토(Opus 5.5) 통과 | M12 수락 QA에서 일부 모드 회귀 확인 |
| M12 | fpocket 4.2.3 로컬 포켓 후보(단백질만 투영, 알파 구·주변 잔기·fpocket 기술자 5개), Mol* 알파 구 오버레이(메인·화학 작업 화면), 포켓 보고서, 작업 수명 주기, 잔기 이름 대응 10개 | 고정 소스 `9e4edcb` (작업 브랜치, main 미병합) | 전체 게이트, 수락 QA 31단계, M8–M11 회귀, 코드·증거 독립 검토(Opus 5.5) 통과 | 현재 기준(`docs/tracking/m12-acceptance.md`) |

"오래됨"은 기능이 망가졌다는 뜻이 아니다. 검토 당시 파일 해시와 현재 파일이 달라, `scripts/execute.py --verify`가 그 검토를 현재 증거로 인정하지 않는다는 뜻이다. 현재 기능이 동작하는지는 아래 검사로 확인한다.

## 현재 검사 결과 (고정 소스 `9e4edcb`, 2026-09-29)

| 검사 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 497개 통과, skip 0 (fpocket·ProLIF 작업 환경 설치) |
| `ruff check …`, 실행기·훅·fpocket 설치 테스트 | 통과, 85개 통과 |
| `test:events`, `typecheck`, `build` | 106개 통과, 통과, 통과 |
| M12 수락 QA(`scripts/m12_offscreen_acceptance.py`) | 31단계 통과, 외부 요청 0건, 남은 프로세스 없음 |
| M8 normal·M9 OpenMM·scenes·M10 measure/alignment·M11 일부 모드 회귀 | 통과 |

증거: `docs/qa/m12-pockets-20260929/`(M12), `docs/qa/m11-chemical-20260928/`(M11). 옛 단계 기록은 M11 index pending(결정 0014), M12 index 없음(결정 0016).

## 남은 전체 범위 (우선순위 순)

1. **M13 결정적 로컬 분석 워크플로**: 미리 정한 분석 목표 템플릿, 계획 미리보기, 계획 승인과 과학 계산 승인을 따로 받기, 단계별 실행·취소·복구, 증거 연결 보고서. 계획은 `source=local_rules`로 표시한다. 자연어 계획과 모델 보조 과학 실행은 별도 투영·동의 설계와 새 호출 할당이 필요하므로 사용할 수 없음으로 둔다. 설계는 끝났고 구현 전이다.
2. **M14–M28**: `docs/tracking/roadmap.md`.
3. **정리 작업**: ProLIF·fpocket 작업 환경의 Linux용 잠금. `docs/tracking/findings.md`의 후속 항목(중복 Host 한계, 이벤트 로그 재파싱, GO 전 guardian 종료 정리, M12 QA 미검증 영역, 보고서 Markdown 이스케이프).

## 전체 로드맵

M13 이후 단계는 `docs/tracking/roadmap.md`에 정했다(2026-09-29 사용자 결정): M13 포함 16단계(M13–M28), 탭 4개(구조 분석 / 단백질 공학 / 리간드 설계·탐색 / 지식·보고서), JEV·GA 두 설계 모드, building block·reaction rule 리간드 설계, 계열 지식 연결. 각 단계의 세부 구현은 그 단계 착수 때 정한다. 배경 분석·출처 조사는 `docs/tracking/roadmap-analysis-20260929.md`.

## 계획에 없는 것 (별도 결정 필요)

돌연변이 설계와 ΔΔG, 리간드 힘장 매개변수화와 복합체 OpenMM, 형태 앙상블과 자유 에너지, 보존성 데이터베이스와 원격 조회, PAE·신뢰도 보기, 큰 궤적 데이터(현재 이벤트 payload 방식으로는 불가), 다중 사용자·인증·공유 서버·외부 공개, 플러그인, GUI 파이프라인 편집.

## 차단 요소

없음. M11 작업 브랜치의 main 병합 여부는 사용자가 정한다.
