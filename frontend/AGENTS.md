# frontend/ — Next.js 작업 화면과 Mol* 뷰어

## 담당 범위
- 최상위 탭 `src/components/WorkspaceTabs.tsx`(정의는 `src/lib/workspace-tabs.ts`): `구조 분석` / `단백질 공학` / `리간드 설계·탐색` / `지식·보고서`와 전역 줄(현재 run `.mw-app-run`, 예산 `.mw-app-budget`). `app/page.tsx`가 이 탭 안에 기존 화면을 넣는다.
- `src/components/ReportLibraryPanel.tsx`: 지식·보고서 탭의 run 전체 보고서·그림·완료된 흐름 요약 목록. 순수 판단은 `src/lib/report-library.ts`.
- 메인 화면 `app/page.tsx`: run·업로드·모델·전처리·리간드·cutoff 선택, 접촉표, 기록, Inspector 보고서, SASA·OpenMM 작업 패널, 저장된 보기·그림, M10 측정·비교, M11 화학 작업 공간, M12 포켓 패널, M13 분석 흐름 패널.
- `src/components/MolstarViewer.tsx`: Mol* 5.11.0 인스턴스, 직렬화된 native 명령 큐, `captureScene`/`restoreScene`/`captureFigure`, sourceIndex ↔ AtomRef 대응, 적용 확인(ack).
- `src/components/PocketPanel.tsx`: M12 포켓 패널. 메인 화면(전처리·최소화 구조)과 `ChemicalWorkspace`(화학 구조)에 같은 컴포넌트를 둔다. 순수 판단은 `src/lib/pockets.ts`.
- `src/components/AnalysisWorkflowPanel.tsx`: M13 분석 흐름 패널. 메인 화면(`panel="main"`: `inspect_ligand`, `measure_atoms`, `compare_structures`, 전처리·최소화 구조 `find_cavities`, `minimize_protein`)과 `ChemicalWorkspace`(`panel="chemical"`: `chemical_interactions`, 화학 구조 `find_cavities`)에 같은 컴포넌트를 둔다. 순수 판단은 `src/lib/analysis.ts`. 결과 열기는 페이지·`PocketPanel`의 `openRequest` 같은 기존 보호 경로로 넘긴다.
- `src/components/ViewerAgentPanel.tsx`: 뷰어 세션 소유, 로컬 명령·자연어 요청, 온라인 동의.
- `src/lib/`: API 클라이언트(`api.ts`)와 순수 로직(이벤트 정규화, 보고서 선택, 보기·비교·화학 상태).
- `src/design/`: `npm run tokens`(`design/build_tokens.py`)가 만드는 생성물이다. `tokens.css`/`tokens.ts`는 `design/tokens.json`에서, `components.css`는 `design/components.css`에서 복사된다(Google Fonts `@import`는 제거).
- 테스트: `tests/*.test.cjs`(node --test), `tests/offscreen/`(Electron 오프스크린 QA 하네스와 흐름 스크립트).
- `middleware.ts`: 모든 요청의 Host를 `src/lib/host-allowlist.ts`로 검사해 `127.0.0.1`·`localhost`·`[::1]`이 아니면 400으로 거부한다. 프록시가 Host를 바꿔 보내므로 백엔드 검사만으로는 :3000 경로를 막지 못한다.

## 담당하지 않는 것
- 과학 계산, 단위 변환, 요약 수치 재계산: 백엔드 handle을 표시만 한다.
- 외부 네트워크: 모든 요청은 `/api/*`(→ `127.0.0.1:8000`)로만 간다. 원격 글꼴·CDN·예시 구조를 쓰지 않는다. 글꼴은 `@fontsource` 로컬 패키지다.
- 자격 증명: 브라우저에는 API 키 입력란, 설정, localStorage 저장이 없다.
- `app/gallery/`는 디자인 fixture 전시용이다. 메인 화면(`app/page.tsx`)이 gallery의 가짜 수치를 import하면 안 된다.
- 건드리지 말 것: `.next/`, `node_modules/`, `tsconfig.tsbuildinfo`(생성물), `tests/offscreen/artifacts/`의 과거 실패 증거.
- 스타일 원본은 `design/components.css`다. `src/design/components.css`를 직접 고치면 다음 `npm run tokens` 실행 때 사라진다. 원본을 고친 뒤 `npm --prefix frontend run tokens`로 복사한다.

## 불변 조건
- 구조 분석 탭(메인 화면과 화학 작업 화면)은 다른 탭이 보일 때도 언마운트하지 않는다. `visibility:hidden`·`pointer-events:none`·`inert`로 숨기고 `display:none`이나 조건부 렌더링·key 변경을 쓰지 않는다(Mol* 캔버스 크기와 뷰어·선택·진행 중 폴링을 유지하기 위해). 탭 전환은 뷰어 브리지의 사용자 동작 콜백이나 복원 취소를 부르지 않는다. 다른 탭 패널은 선택된 동안에만 렌더링한다(기존 검사의 텍스트 locator와 겹치지 않게).
- 최상위 탭 이름은 레일 탭 이름(`run`, `models`)으로 시작하지 않는다. 전역 예산 요소에 `.mw-top-budget`을 쓰지 않는다(기존 검사가 이 클래스로 값을 읽는다). 전역 예산은 새 주기적 폴링 없이 탭 전환과 화학 화면 `onObjectsChanged` 때 `/budget`을 한 번 읽는다.
- run 선택·전환은 구조 분석 탭(메인 레일, 화학 화면)에만 있다. 기능 없는 탭은 사용할 수 없음·이유·여는 단계만 보여 주고 숫자·컨트롤·요청이 없다.
- 보고서 목록은 저장된 바이트만 보여 준다(Markdown은 `<pre>` 원문, 렌더링하지 않음). 흐름은 `complete`이고 `summary_handle`이 있으며 `error`가 없는 실행만 넣는다. 목록 세 개는 오류가 서로 독립이고, run·요청 순번이 맞지 않는 응답은 버린다. 다운로드는 사용자가 누른 링크로만 일어난다. 구조 분석으로 건너가 여는 버튼과 보고서 생성 버튼은 두지 않는다.
- 화면의 과학 수치는 모두 백엔드 객체에서 온다. 미리보기 5행을 전체 결과처럼 표시하지 않는다.
- Mol* 조작은 모두 MolstarViewer 브리지의 직렬 큐를 거친다. 매 await 전후에 session, client, generation, source handle, catalog hash, action revision을 확인한다. 하나라도 바뀌었으면 그 작업은 적용하지 않는다.
- "적용됨"은 native 작업을 커밋하고 다시 읽어 확인한 뒤에만 보고한다. React state만 바꾸고 성공으로 표시하지 않는다. 부분 적용은 적용된 명령과 거부된 명령을 나눠 보여 주고, 롤백했다고 주장하지 않는다.
- 브라우저 선택 → 잔기·원자 식별자 변환은 제공된 바이트의 SHA-256에 묶인 `atomSourceIndex` 일대일 대응만 쓴다. Mol*가 합성한 label, PDB serial, 좌표 최근접을 쓰지 않는다. 대응이 준비되기 전에는 선택·초점·저장 컨트롤이 기다리거나, 재시도 가능한 오류를 보여 준다.
- 바인딩 6필드가 모두 같은 재발행은 새 사용자 동작이 아니다. 카탈로그 준비나 검증 같은 관찰은 `onSelect`를 호출하거나 복원을 취소하면 안 된다. 실제 클릭, 빈 곳 클릭, 회전은 대기 작업을 취소한다.
- 최소화된 단백질을 표시할 때는 원래 복합체의 접촉 행을 숨기거나 비활성화하고, 범례에 OpenMM 최소화 구조임을 명시한다. 비교(오버레이) 중에는 단일 소스 저장 보기·PNG·M8 프롬프트를 비활성화하고 이유를 보여 준다.
- 화학 구조 보기는 M8·M9·M10의 입력으로 쓸 수 없다.
- 포켓 오버레이는 저장된 알파 구 중심·반지름 그대로 그리고, 구는 선택 대상이 아니다(주변 잔기는 선택 가능). 오버레이 중 M9 저장·PNG와 M8 요청을 비활성화하고 이유를 보여 준다. M10 비교 중에는 포켓 검출·오버레이를 막는다. 최소화 구조의 포켓은 OpenMM 최소화 보기와 같은 상태로 보여 준다. run·소스가 바뀌면 늦은 포켓 응답은 패널과 페이지 두 곳에서 버린다.
- 체인을 모두 해제한 상태로 포켓 검출을 실행하지 못한다(빈 목록은 서버에서 전체 체인을 뜻하므로).
- 분석 흐름 패널은 서버가 컴파일한 계획만 보여 주고 단계를 보내지 않는다. 입력은 목표를 고르거나 "화면 선택 다시 가져오기"를 누를 때만 화면에서 가져오며, 만든 계획은 이후 화면 선택으로 바뀌지 않는다. 원자 두 개·CA 대응표·화학 준비 요청은 읽기 전용이고 없으면 "기존 화면에서 먼저 만드세요" 선행 조건이다. 리간드·체인을 자동으로 고르지 않는다.
- 계획 미리보기는 "로컬 규칙으로 만든 계획이며 모델 판단이 아닙니다"와 계획은 측정 결과가 아니라는 안내를 보여 준다. 계획 승인과 계산 승인은 따로 각각의 상태로 보여 준다("이 run에서 이미 계산 승인됨" 포함). 자연어 계획은 누를 수 없는 항목으로 이유와 함께 보여 준다. dry-run run에서는 미리보기 전용 안내를 보여 준다.
- "다음 단계 실행"은 한 번에 한 단계다. 여러 단계를 이어 누르는 자동 진행을 만들지 않는다. 모든 거절(409·412) 뒤에는 실행 기록을 다시 읽는다. 자동으로 다시 보내는 것은 `stale_revision`을 받은 중지 한 번뿐이다(`stopResend`). 폴링은 단계·작업이 진행 중이거나 이 패널의 요청이 도는 동안의 읽기만 하며 이벤트를 쓰지 않는다.
- 화학 구조 결과는 화학 작업 화면에서만 연다. 메인 패널은 "화학 작업 화면에서 열기"로 안내한다. run·실행이 바뀌면 늦은 응답은 패널과 페이지 두 곳에서 버린다.
- 사용할 수 없는 기능은 숫자 없이 이유를 보여 주고, 구현하지 않은 컨트롤은 누를 수 없게 한다.
- 요청 중에 run이나 선택이 바뀌면, 늦게 도착한 응답이 새 화면을 덮거나 다운로드를 시작하면 안 된다. 대기·결과·오류 상태는 run과 handle 기준으로 관리한다.

## 구현 패턴
- API 호출은 `src/lib/api.ts`에 모으고, 응답 타입은 `src/lib/contracts.ts`에 정의한다.
- 상태 판단 로직은 `src/lib/*.ts`의 순수 함수로 분리해 `tests/*.test.cjs`에서 테스트한다(예: `report-selection`, `saved-scene`, `event-model`).
- 한국어 문구를 쓰되 도구 식별자는 번역하지 않는다. 식별자와 사용자 입력 문자열은 이스케이프해서 렌더링한다.
- 오프스크린 QA 조작은 Playwright locator의 실제 마우스·키보드·파일 선택 입력으로만 한다. DOM `.click()`이나 애플리케이션 핸들러를 직접 호출하지 않는다. 읽기 전용 관찰은 뷰어의 data 속성이나 제한된 관찰 브리지로 하고, 이 브리지로 성공을 만들어 내면 안 된다.

## 테스트 지침
- 순수 로직: `npm --prefix frontend run test:events`.
- 타입과 빌드: `npm --prefix frontend run typecheck` 다음에 `npm --prefix frontend run build`(동시 실행 금지).
- 바뀐 컨트롤은 실제 Electron 오프스크린에서 하나씩 실제 입력으로 검증한다(`isOffscreen()===true`, GPU·WebGL, paint, 외부 요청 0건). 공유 뷰어·페이지 코드를 바꿨다면 M8 normal-flow, M9 scenes-flow, M10 comparison-flow 회귀도 돌린다. 포켓 흐름은 `test:offscreen:pockets`, 전체 수락은 `scripts/m12_offscreen_acceptance.py`. 탭은 `test:offscreen:tabs`(`tests/offscreen/tabs-flow.cjs`, 순수 로직은 `tests/workspace-tabs.test.cjs`·`tests/report-library.test.cjs`), 전체 수락은 `scripts/m14_offscreen_acceptance.py`이고 M8–M13 회귀는 `scripts/m13_offscreen_acceptance.py` 전체다. 분석 흐름은 `test:offscreen:workflows`(`tests/offscreen/workflows-flow.cjs`, 순수 로직은 `tests/analysis.test.cjs`), 전체 수락과 M8–M12 회귀는 `scripts/m13_offscreen_acceptance.py`.
- 반드시 다룰 경우: 빠른 소스 전환(A→B 뒤 B가 최종), 늦은 응답, WebGL 컨텍스트 손실, 읽기 오류 후 재시도, 비활성 상태의 이유 표시, null label·삽입 코드·비첫 모델 잔기 선택.
- 실패한 실행 결과는 지우지 않고 회귀 증거로 남긴다.
