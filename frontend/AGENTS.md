# frontend/ — Next.js 작업 화면과 Mol* 뷰어

## 담당 범위
- 메인 화면 `app/page.tsx`: run·업로드·모델·전처리·리간드·cutoff 선택, 접촉표, 기록, Inspector 보고서, SASA·OpenMM 작업 패널, 저장된 보기·그림, M10 측정·비교, M11 화학 작업 공간.
- `src/components/MolstarViewer.tsx`: Mol* 5.11.0 인스턴스, 직렬화된 native 명령 큐, `captureScene`/`restoreScene`/`captureFigure`, sourceIndex ↔ AtomRef 대응, 적용 확인(ack).
- `src/components/ViewerAgentPanel.tsx`: 뷰어 세션 소유, 로컬 명령·자연어 요청, 온라인 동의.
- `src/lib/`: API 클라이언트(`api.ts`)와 순수 로직(이벤트 정규화, 보고서 선택, 보기·비교·화학 상태).
- `src/design/`: `npm run tokens`(`design/build_tokens.py`)가 만드는 생성물이다. `tokens.css`/`tokens.ts`는 `design/tokens.json`에서, `components.css`는 `design/components.css`에서 복사된다(Google Fonts `@import`는 제거).
- 테스트: `tests/*.test.cjs`(node --test), `tests/offscreen/`(Electron 오프스크린 QA 하네스와 흐름 스크립트).

## 담당하지 않는 것
- 과학 계산, 단위 변환, 요약 수치 재계산: 백엔드 handle을 표시만 한다.
- 외부 네트워크: 모든 요청은 `/api/*`(→ `127.0.0.1:8000`)로만 간다. 원격 글꼴·CDN·예시 구조를 쓰지 않는다. 글꼴은 `@fontsource` 로컬 패키지다.
- 자격 증명: 브라우저에는 API 키 입력란, 설정, localStorage 저장이 없다.
- `app/gallery/`는 디자인 fixture 전시용이다. 메인 화면(`app/page.tsx`)이 gallery의 가짜 수치를 import하면 안 된다.
- 건드리지 말 것: `.next/`, `node_modules/`, `tsconfig.tsbuildinfo`(생성물), `tests/offscreen/artifacts/`의 과거 실패 증거.
- 스타일 원본은 `design/components.css`다. `src/design/components.css`를 직접 고치면 다음 `npm run tokens` 실행 때 사라진다. 원본을 고친 뒤 `npm --prefix frontend run tokens`로 복사한다.

## 불변 조건
- 화면의 과학 수치는 모두 백엔드 객체에서 온다. 미리보기 5행을 전체 결과처럼 표시하지 않는다.
- Mol* 조작은 모두 MolstarViewer 브리지의 직렬 큐를 거친다. 매 await 전후에 session, client, generation, source handle, catalog hash, action revision을 확인한다. 하나라도 바뀌었으면 그 작업은 적용하지 않는다.
- "적용됨"은 native 작업을 커밋하고 다시 읽어 확인한 뒤에만 보고한다. React state만 바꾸고 성공으로 표시하지 않는다. 부분 적용은 적용된 명령과 거부된 명령을 나눠 보여 주고, 롤백했다고 주장하지 않는다.
- 브라우저 선택 → 잔기·원자 식별자 변환은 제공된 바이트의 SHA-256에 묶인 `atomSourceIndex` 일대일 대응만 쓴다. Mol*가 합성한 label, PDB serial, 좌표 최근접을 쓰지 않는다. 대응이 준비되기 전에는 선택·초점·저장 컨트롤이 기다리거나, 재시도 가능한 오류를 보여 준다.
- 바인딩 6필드가 모두 같은 재발행은 새 사용자 동작이 아니다. 카탈로그 준비나 검증 같은 관찰은 `onSelect`를 호출하거나 복원을 취소하면 안 된다. 실제 클릭, 빈 곳 클릭, 회전은 대기 작업을 취소한다.
- 최소화된 단백질을 표시할 때는 원래 복합체의 접촉 행을 숨기거나 비활성화하고, 범례에 OpenMM 최소화 구조임을 명시한다. 비교(오버레이) 중에는 단일 소스 저장 보기·PNG·M8 프롬프트를 비활성화하고 이유를 보여 준다.
- 화학 구조 보기는 M8·M9·M10의 입력으로 쓸 수 없다.
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
- 바뀐 컨트롤은 실제 Electron 오프스크린에서 하나씩 실제 입력으로 검증한다(`isOffscreen()===true`, GPU·WebGL, paint, 외부 요청 0건). 공유 뷰어·페이지 코드를 바꿨다면 M8 normal-flow, M9 scenes-flow, M10 comparison-flow 회귀도 돌린다.
- 반드시 다룰 경우: 빠른 소스 전환(A→B 뒤 B가 최종), 늦은 응답, WebGL 컨텍스트 손실, 읽기 오류 후 재시도, 비활성 상태의 이유 표시, null label·삽입 코드·비첫 모델 잔기 선택.
- 실패한 실행 결과는 지우지 않고 회귀 증거로 남긴다.
