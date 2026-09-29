# ProtView

로컬 PDB/mmCIF 구조를 불러와 전처리하고, Mol*로 렌더링하고, 실제 좌표로 기하 접촉·SASA·단백질 전위·원자 거리·강체 정렬·화학 상호작용·포켓 후보를 계산해, 근거가 필드 단위로 연결된 보고서를 만드는 단일 사용자 작업 공간이다. 연구실·팀 구성원이 각자 자기 컴퓨터나 혼자 쓰는 서버에 설치해 쓴다. FastAPI 백엔드(Python 3.11)와 Next.js 프런트엔드로 이루어져 있고, 기본 작업은 네트워크나 API 키 없이 끝난다. M0–M14는 끝났고(M14 완료 기록: `docs/tracking/m14-acceptance.md`, 탭 4개 골격과 기존 화면 이관), 다음은 M15(참조 스냅샷과 잔기 번호 대응)이며 전체 로드맵은 `docs/tracking/roadmap.md`(M13–M28)다.

## 프로젝트 구조

```
protview/
├── CLAUDE.md / AGENTS.md          → 이 파일. 프로젝트 개요, 필수 규칙 요약, 작업 전 확인 사항
├── docs/
│   ├── system-architecture.md     → 구성 요소, 의존 방향, 업로드→보고서 흐름, 외부 경계
│   ├── business-rules.md          → 식별자, 전처리, 계산 방법별 의미·단위·한계, 보고서 증거, 예산·재시도
│   ├── security.md                → 신뢰 모델, 외부 전송 허용 목록, 자격 증명, 감사 기록, 입력 제한
│   ├── standards.md               → 역할 분담, 과학 결과 규칙, 수정 금지 파일, Git, 검증 게이트, 모듈 경계
│   ├── engineering-notes.md       → 알려진 함정(증상→원인→대응), 동작 원리, 반복 작업 체크리스트
│   ├── operations.md              → 설치, 실행, 환경 설정, 검증·오프스크린 QA 명령, run 보관
│   ├── contracts.md               → loopback HTTP API 계약(입력·출력·오류), 과거 단계 실행기 CLI
│   ├── tracking/
│   │   ├── status.md              → 완료·검증 상태와 남은 작업
│   │   ├── roadmap.md             → M13–M28 단계 로드맵(탭·시나리오·하지 않는 것)
│   │   ├── roadmap-analysis-20260929.md → 로드맵 배경 분석(작성 시점 스냅숏)
│   │   ├── m11-acceptance.md … m14-acceptance.md → 단계 완료 기록
│   │   ├── decisions/index.md     → 결정 기록 목록(0001–0021)
│   │   └── findings.md            → 지금 해결하지 못한 문제와 그 이유
│   └── (대문자 문서들)             → M0–M13 단계별 원본 설계·계약·검토 기록. 수정·이동 금지
├── backend/AGENTS.md              → mw 패키지: API, 런타임, 객체·이벤트, 도구, 작업 큐, 외부 게이트
├── frontend/AGENTS.md             → Next.js 화면, Mol* 브리지, 오프스크린 QA 하네스
└── scripts/AGENTS.md              → 과거 단계 실행기, 훅 테스트, ProLIF 작업 환경 설치
```

## 필수 규칙 (요약. 전체 규칙은 docs/standards.md)

1. **과학 값을 만들어 내지 않는다.** 실제 엔진 실행 결과만 고유 단위로 기록한다. 구현하지 않았거나 설치되지 않은 기능은 숫자 없이 "사용할 수 없음"과 이유를 보여 준다. 기하 접촉을 수소결합이라 부르지 않고, SASA·OpenMM·RMSD 값을 ΔΔG·친화도·안정성·Rosetta 이름으로 바꾸지 않는다.
2. **외부 전송은 게이트 하나로, 키는 절대 밖으로 내보내지 않는다.** 외부 HTTP는 `EgressGate`만 보내고 전송 전에 감사 기록을 남긴다. 구조·좌표·서열·리간드·분석 결과는 JEV 같은 외부 모델로 보내도 된다(결정 0015, 2026-09-29). API 키·자격 증명은 요청·이벤트·로그·보고서·커밋 어디에도 넣지 않는다. 서버는 `127.0.0.1`에만 바인딩한다. 제품이 실제로 OpenRouter를 호출하는 검증은 사용자가 정해 준 횟수 안에서만 한다.
3. **기록은 불변이다.** 객체, 이벤트, 저장된 보고서 바이트를 바꾸지 않는다. 완료된 단계 검토에 해시로 묶인 대문자 `docs/*.md`, `phases/*/reviews/`, `phases/*/step*.md`, 원본 참고 자료를 수정·이동하지 않는다. 이 디스크는 대소문자를 구분하지 않으므로 대문자 문서와 소문자만 다른 이름의 파일을 만들지 않는다.
4. **식별자를 보존한다.** 잔기 7필드(model, chain_auth/label, seq_auth/label, icode, resname)와 AtomRef를 null까지 그대로 유지한다. 리간드 인스턴스를 이름으로 합치거나 첫 번째를 고르지 않는다.
5. **구현자와 검토자를 분리한다.** 메인 세션은 조율, 설계 결정, Git, 단계 기록을 맡는다. 구현은 Opus 5.5 구현 서브에이전트가, 검토는 그 코드를 쓰지 않은 새 Opus 5.5 서브에이전트가 한다. 커밋과 push는 사용자가 요청할 때만 하고, 파일 경로를 지정해서 스테이징한다.

## 작업 전 확인

- 항상: `docs/standards.md`, `docs/engineering-notes.md`, 작업할 모듈의 `AGENTS.md`, `docs/tracking/status.md`.
- **M11 화학 작업**: `docs/business-rules.md`의 "M11 화학 입력 규칙"과 원본 상세 계약 `docs/M11_CHEMICAL_INTERACTIONS_CONTRACT.md`, `docs/M11_BACKEND_API.md`, `docs/M11_OFFSCREEN_QA_PLAN.md`(입력 경로 안내는 오래됨). 현재 QA 실행 방법은 `docs/operations.md`, 완료 기록은 `docs/tracking/m11-acceptance.md`.
- **M12 포켓 작업**: `docs/business-rules.md`의 "포켓 후보"와 원본 계약 `docs/M12_POCKET_DETECTION_CONTRACT.md`(빈 결과 진단 stream·잔기 이름 대응·기록 방식은 business-rules와 완료 기록이 우선). 완료 기록은 `docs/tracking/m12-acceptance.md`.
- **M13 분석 흐름 작업**: `docs/business-rules.md`의 "분석 흐름 (M13)", `docs/contracts.md`의 분석 흐름 API, 완료 기록 `docs/tracking/m13-acceptance.md`. 원본 계약 `docs/M13_WORKFLOWS_CONTRACT.md`와 다른 곳(계획 1 MiB(결정 0019), Astra/Sol 역할·step0 index 미적용(결정 0018) 등)은 business-rules와 완료 기록이 우선한다.
- **탭·화면 구조를 바꿀 때(M14)**: `frontend/AGENTS.md`의 최상위 탭 불변 조건(구조 분석 탭은 숨긴 채 유지), 완료 기록 `docs/tracking/m14-acceptance.md`, 공용화 범위 결정 0021.
- **M15 이후 착수**: `docs/tracking/roadmap.md`. 세부 구현은 착수 때 사용자와 정하고, 실제 스키마·도구 버전과 맞는지 다시 확인한다.
- **뷰어·선택·저장된 보기를 바꿀 때**: `docs/engineering-notes.md`의 Mol* label 함정과 바인딩 재발행 함정, `frontend/AGENTS.md`의 브리지 불변 조건.
- **작업 큐·프로세스를 바꿀 때**: `docs/engineering-notes.md`의 psutil 신원 함정과 시작 핸드셰이크, `backend/AGENTS.md`의 예약·잠금 규칙.
- **외부 요청·모델 관련**: `docs/security.md` 전체와 결정 0015. 새 데이터 종류를 보내려면 게이트 투영과 UI 미리보기·예산 설계를 추가한다(보내는 것 자체는 허용됨).
- **보고서나 새 결과 종류를 추가할 때**: `docs/business-rules.md`의 보고서 규칙과 `docs/engineering-notes.md`의 "새 과학 도구 추가" 체크리스트.
- **과거 단계 `--verify`를 돌릴 때**: `docs/engineering-notes.md`의 오래된 검토 함정. 해시를 고쳐서 통과시키지 않는다.

## 문제 대응

즉시 사용자에게 알릴 것:
- API 키·자격 증명이 외부 요청·이벤트·로그·보고서·커밋에 들어갔거나 들어갈 수 있는 경로, 또는 `EgressGate`와 감사 기록을 거치지 않고 데이터가 외부로 나가는 경로를 발견한 경우.
- 저장된 보고서 바이트, 불변 객체, 이벤트 로그, 해시로 묶인 과거 문서가 바뀌었거나 복구할 수 없게 된 경우.
- 화면이나 보고서에 계산하지 않은 수치, fixture 값, 다른 방법 이름으로 바꾼 값이 과학 결과로 표시되는 경우.
- 잔기·원자·리간드 식별자가 섞이거나 잘못 매칭되어 다른 원자의 값이 표시되는 경우.
- 예산·승인 없이 비싼 계산이나 외부 호출이 시작되거나, 작업 프로세스가 정리되지 않고 남는 경우.
- 서버가 loopback이 아닌 주소로 열려 있는 경우.

그 밖의 문제는 원인을 추적해 해결을 먼저 시도한다. 그 자리에서 해결할 수 없으면 이유와 함께 `docs/tracking/findings.md`에 기록한다.
