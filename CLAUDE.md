# ProtView

로컬 PDB/mmCIF 구조를 불러와 전처리하고, Mol*로 렌더링하고, 실제 좌표로 기하 접촉·SASA·단백질 전위·원자 거리·강체 정렬·화학 상호작용·포켓 후보를 계산해, 근거가 필드 단위로 연결된 보고서를 만드는 단일 사용자 작업 공간이다. 연구실·팀 구성원이 각자 자기 컴퓨터나 혼자 쓰는 서버에 설치해 쓴다. FastAPI 백엔드(Python 3.11)와 Next.js 프런트엔드로 이루어져 있고, 기본 작업은 네트워크나 API 키 없이 끝난다. M0–M20이 끝났고(M20 완료 기록: `docs/tracking/m20-acceptance.md`, 변이 후보 생성. main 병합은 사용자 승인 대기), 다음은 M21(단백질 공학: 변이 구조 모델링)이며 전체 로드맵은 `docs/tracking/roadmap.md`(M13–M28)다.

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
│   │   ├── m11-acceptance.md … m20-acceptance.md → 단계 완료 기록
│   │   ├── decisions/index.md     → 결정 기록 목록(0001–0028)
│   │   └── findings.md            → 지금 해결하지 못한 문제와 그 이유
│   └── (대문자 문서들)             → M0–M13 단계별 원본 설계·계약·검토 기록. 수정·이동 금지
├── backend/AGENTS.md              → mw 패키지: API, 런타임, 객체·이벤트, 도구, 작업 큐, 외부 게이트
├── frontend/AGENTS.md             → Next.js 화면, Mol* 브리지, 오프스크린 QA 하네스
└── scripts/AGENTS.md              → 과거 단계 실행기, 훅 테스트, 작업 환경·참조 스냅샷 설치, 수락 QA 실행기
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
- **M15 번호 대응·참조 스냅샷 작업**: `docs/business-rules.md`의 "잔기 번호 대응 (M15)", `docs/contracts.md`의 M15 API, 결정 0022(kbase `ref/` 가공 스냅샷만, 가져오기 명령으로)·0023(대응 규칙), 완료 기록 `docs/tracking/m15-acceptance.md`, `docs/engineering-notes.md`의 SIFTS·KLIFS·정렬 모호성 함정. 상태·이유 집합과 기준값을 바꾸려면 사용자 결정이 필요하다. 위치·KLIFS 번호는 참조 값이며 계산값과 섞지 않는다.
- **M16 참조 주석 작업**: `docs/business-rules.md`의 "참조 주석 (M16)"과 저장된 보기 절(`viewer_scene@2`·`viewer_figure@2`, 범례), `docs/contracts.md`의 M16 API, 결정 0024(부위 10개, 같은 구조에만, 기하 접촉만, 범례 기본 켬, 포켓·M8 배타, 그림 상한 유지), 완료 기록 `docs/tracking/m16-acceptance.md`, `frontend/AGENTS.md`의 참조 주석 불변 조건, `docs/engineering-notes.md`의 하네스 범례 영역·사전 검사 훅 함정. 부위 목록과 상태·이유 집합을 바꾸려면 사용자 결정이 필요하다. 계산하지 않음·검사하지 않음·접촉 결과 없음을 0으로 보이지 않고, 기하 접촉을 수소결합이라 부르지 않는다.
- **M17 리간드 후보 작업**: `docs/business-rules.md`의 "리간드 후보 (M17)", `docs/contracts.md`의 M17 API, 결정 0025(고정 교체 + 사용자 반응 규칙, 단일 결합 하나로 이어진 부위, 후보 모두 보관·필터는 저장값에, 점검·생성 각 예산 1단위, 상한), 완료 기록 `docs/tracking/m17-acceptance.md`, `frontend/AGENTS.md`의 리간드 탭 불변 조건, `docs/engineering-notes.md`의 RDKit 함정(Lipinski HBD/HBA, SDF 번호 `sdf_serial`·`atomNote`, 표시 원자 원자번호 0, SVG 크기, 스테이징 한도). RDKit은 `mw/jobs/ligand_worker.py`(`.deps/prolif/venv-locked`)에서만 import한다. 이유 집합·`stereo_flag`·한계 문장·상한을 바꾸려면 사용자 결정이 필요하다. 속성은 "RDKit 추정값", PAINS는 "구조 경고 일치"이며 약물 유사성·독성·활성·합성 가능성을 말하지 않는다.
- **M18 도킹 작업**: `docs/business-rules.md`의 "리간드 도킹 (M18, `qvina_dock_v1`)", `docs/contracts.md`의 M18 API, 결정 0026(qvina 하나, 점수 문구, 리간드 출처 둘, 상자 출처 셋, 기하 접촉만, 뷰어 표시 없음, 수용체 M11 규칙·인스턴스 하나만 빼기, 코어 고정은 구속 샘플 + `--score_only`만, seed 직접·CPU 1, 격리 환경 둘), 완료 기록 `docs/tracking/m18-acceptance.md`, `frontend/AGENTS.md`의 도킹 영역 불변 조건, `docs/engineering-notes.md`의 M18 함정(Meeko `Polymer` 네트워크 조회, 평면·암시 수소 SDF, 상자 반올림, `--score_only`와 상자, stdout 재현 비교, 포즈 원자 순서, 구속 임베딩 덮어쓰기). Meeko·RDKit·MDAnalysis는 `mw/jobs/docking_worker.py`(`.deps/docking/venv-locked`)에서만 import하고 `qvina2`도 그 작업 모듈만 실행한다. 이유 집합·한계 문장·점수 문구·상자 출처를 바꾸려면 사용자 결정이 필요하다. 점수는 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"이며 친화도·순위·개선을 말하지 않는다.
- **M19 일괄 도킹 작업**: `docs/business-rules.md`의 "리간드 일괄 도킹 (M19, `qvina_batch_dock_v1`)", `docs/contracts.md`의 M19 API, 결정 0027(작업 하나·새 계산 행마다 1단위, 방식 하나, 부모 기준 행은 자유만, M17 필터 + 체크박스, 행 결과 = 단독 M18 결과 + 서버가 만드는 요약, 상한 50(+1)·300초·7200초·7800초·128 MiB, 부분 완료 보관, 점수 표 + 정렬만, 사람의 부족분 증액 승인, 재사용 과금 없음, 행별 스테이징 + 종료 때 게시), 완료 기록 `docs/tracking/m19-acceptance.md`, `frontend/AGENTS.md`의 일괄 도킹 영역 불변 조건, `backend/AGENTS.md`의 일괄 파일 규약·요약은 서버만·증액 경로 하나, `docs/engineering-notes.md`의 M19 함정(실행 중 게시 불가, 수용체 한 번 준비 = 바이트 동일, 호출 키의 작업 모듈 해시, 숨은 900초 상한 두 곳, 증액 직후 오버헤드, `update_limits`·`raise_limits`, 재사용 색인, `producer()` 먼저 게시한 쪽, 읽기 비용, Stop 훅 그룹). 일괄 작업 모듈 `mw/jobs/docking_batch_worker.py`는 화학 패키지를 직접 import하지 않고 `docking_worker.py`를 파일 경로로 불러 행을 계산한다(행 계산 복제 금지). 행 상태·이유·멈춘 이유 집합, 고정 문장 B1–B3, 상한, 점수 대상 문구를 바꾸려면 사용자 결정이 필요하다. 점수 없는 행은 0이 아니고 정렬에서 늘 끝이며, 표의 정렬·첫 행 점수·부모 행과의 차이를 순위·best·개선이라 하지 않는다. 한도 증액은 사람이 화면에서만 하고 다른 경로에 붙이지 않는다.
- **M20 변이 후보 작업**: `docs/business-rules.md`의 "변이 후보 (M20, `generate_mutation_candidates`)", `docs/contracts.md`의 M20 API(읽기 handle은 URL 경로), 결정 0028(위치 출처 셋의 합집합, 근거 있는 보호만: 사용자·KLIFS 주요 부위(주석이 있을 때)·금속 3.0 Å·이황화 2.5 Å, 촉매 데이터베이스 사용할 수 없음, 잔기 단위 전부 해제, 단일 변이, 상한 400 거절, 표 + 보고서만, 리간드 자동 선택 없음), 완료 기록 `docs/tracking/m20-acceptance.md`, `backend/AGENTS.md`·`frontend/AGENTS.md`의 M20 불변 조건, `docs/engineering-notes.md`의 M20 함정(훅 store로 게시 확인 읽기, fpocket 비결정성, HETATM 리간드 정의, 저장 전 검증, 템플릿 금지어 검사, 경로 handle 라우트 순서, 탭 흐름 GET). 서버 모듈은 gemmi·numpy·표준 라이브러리만 쓴다. 닫힌 이유·상태·출처 집합, 고정 문장 5개, 상한·기본값을 바꾸려면 사용자 결정이 필요하다. 후보는 위치와 바꿀 잔기의 조합일 뿐이며 점수·순위·추천·안정성·ΔΔG·활성을 말하지 않고, 검사하지 않음(`not_checked`)·사용할 수 없음(`not_available`)·계산하지 않은 거리(null)를 0이나 "없음"으로 보이지 않는다.
- **M21 이후 착수**: `docs/tracking/roadmap.md`. 세부 구현은 착수 때 사용자와 정하고, 실제 스키마·도구 버전과 맞는지 다시 확인한다.
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
