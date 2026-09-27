# 진행 현황

기준: 2026-09-27, 브랜치 `phase/m11-chemical-interactions`(기준 커밋 `4ab0186`), M11 변경은 커밋되지 않은 상태.

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

"오래됨"은 기능이 망가졌다는 뜻이 아니다. 검토 당시 파일 해시와 현재 파일이 달라, `scripts/execute.py --verify`가 그 검토를 현재 증거로 인정하지 않는다는 뜻이다. 현재 기능이 동작하는지는 아래 검사로 확인한다.

## 현재 작업 트리 검사 결과 (2026-09-27 실행)

| 검사 | 결과 |
|---|---|
| `ruff check backend/mw backend/tests scripts .codex/hooks` | 통과 |
| `pytest scripts/test_execute.py scripts/test_codex_hooks.py` | 57개 통과 |
| `npm --prefix frontend run test:events` | 72개 통과, 실패 0 |
| `pytest backend/tests` | 330개 통과, skip 0 (약 11분 45초). M11 화학 테스트 포함, `.deps/prolif/venv-locked` 설치 상태 |
| `typecheck`, `build`, 오프스크린 전체 회귀 | 이번에는 실행하지 않음 |

## 진행 중: M11 화학 상호작용 (pending)

- **만들어진 것(커밋 전, 검토 전)**: 화학 입력 가져오기(`chemical_inputs.py`), 번들 조립(`chemical_bundle.py`), 결과·보고서(`chemical_reports.py`), ProLIF 작업 프로세스(`jobs/chemical_worker.py`), 큐·guardian 확장, M11 API 라우트, `ChemicalWorkspace.tsx`, 테스트(`test_chemical_interactions.py`, `test_m11_job_api.py`, `chemical.test.cjs`), 오프스크린 `chemical-flow.cjs`, 잠금 파일과 설치 스크립트, `.deps/prolif/venv-locked` 설치.
- **관찰했지만 검토 전인 오프스크린 결과**: Release2 빌드에서 create-new, 대기·실행 중 취소, 실패한 준비의 재시도(합성 fixture).
- **남은 것**: 기존 복합체에 연결(attach) 두 모드, 빈 결과, 장애 경우, events-only 재생, M8·M9·M10 회귀, "camera still moving" 초점 대기 수정, `/tmp` QA 입력을 저장소 fixture로 옮기기, 바뀐 공유 소스(README·app.py·queue.py·guardian.py·MolstarViewer.tsx 등)의 현재 기준 통합 검토, 독립 검토 서브에이전트의 승인.
- **완료 판정 방식**: 새 흐름의 검증 게이트와 독립 검토로 판정한다. `phases/protview-chemical-interactions/index.json`은 기존 실행기 형식이라 새 흐름에서 `completed`로 기록할 수 없다. 이 파일을 계속 둘지, 어떻게 마감할지는 M11 마무리 때 정한다.

## 남은 전체 범위 (우선순위 순)

1. **M11 완료**: 위의 남은 항목.
2. **M12 로컬 포켓 후보**: fpocket 4.2.3(conda-forge osx-arm64 빌드 `hb88c64c_2`, 패키지·실행 파일 해시 고정, macOS ≥ 14.5)을 단백질만 대상으로 격리 작업 프로세스에서 실행한다. 포켓 기하, 잔기 구성, fpocket 고유 기술자, Mol* 공동 오버레이, 보고서, 작업 수명 주기를 포함한다. 결과는 결합 부위나 druggability의 증거가 아니다. 설계는 끝났고 구현 전이다.
3. **M13 결정적 로컬 분석 워크플로**: 미리 정한 분석 목표 템플릿, 계획 미리보기, 계획 승인과 과학 계산 승인을 따로 받기, 단계별 실행·취소·복구, 증거 연결 보고서. 계획은 `source=local_rules`로 표시한다. 자연어 계획과 모델 보조 과학 실행은 별도 투영·동의 설계와 새 호출 할당이 필요하므로 사용할 수 없음으로 둔다. 설계는 끝났고 구현 전이다.
4. **정리 작업**: `.claude/commands/harness.md`·`review.md`를 새 역할 구조에 맞게 바꾸거나 삭제. ProLIF 작업 프로세스의 Linux용 잠금 파일.

## 계획에 없는 것 (별도 결정 필요)

돌연변이 설계와 ΔΔG, 리간드 힘장 매개변수화와 복합체 OpenMM, 형태 앙상블과 자유 에너지, 보존성 데이터베이스와 원격 조회, PAE·신뢰도 보기, 큰 궤적 데이터(현재 이벤트 payload 방식으로는 불가), 다중 사용자·인증·공유 서버·외부 공개, 플러그인, GUI 파이프라인 편집.

## 차단 요소

없음. M11의 남은 오프스크린 모드는 부모 세션이 새 백엔드·프런트엔드 빌드를 고정해야 실행할 수 있다.
