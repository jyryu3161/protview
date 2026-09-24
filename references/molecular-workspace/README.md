# Molecular Workspace

로컬 단백질 구조 워크스페이스 + 자율 에이전트 런타임.
좌표는 로컬에, 판단은 compact state로. 외부로 나가는 것은 기록된 토큰 수천 개뿐.

이 저장소는 **바이브코딩용 스타터 패키지**다. 설계 문서·계약·디자인 시스템·동작하는 뼈대 코드가
한 곳에 있고, 코딩 에이전트(Claude Code, Cursor, Codex)가 `CLAUDE.md`를 읽고 마일스톤 단위로 이어서 만든다.

## 지금 들어 있는 것

| 영역 | 상태 |
|---|---|
| 백엔드 코어 (핸들, 이벤트, 실패 분류, 계약, 가드, 오케스트레이터, replay) | 동작 · 테스트 24개 통과 |
| EgressGate, OpenRouter 클라이언트(정책·핀·캐시·상태코드), 프롬프트 레지스트리, 숫자 검증기 | 동작 · Mock 테스트 |
| 구조 툴 (gemmi 베이스라인: load / prepare / compute_interactions / compile_state) | 동작 · ProLIF/PLIP은 M1 |
| 에너지 툴 (relax, cartesian_ddg) | dry-run stub만 · PyRosetta 구현은 M4 |
| FastAPI (사람 명령 = 에이전트와 같은 경로) | 동작 |
| 프런트엔드 컴포넌트 26개 + 워크스페이스 + 갤러리 (Next.js, mock 데이터) | 빌드 통과 · Mol*는 M1 |
| 디자인 토큰(dark/light) + 정적 레퍼런스 프리뷰 | `design/index.html` |

## 빠른 시작

```bash
make setup           # pip install -e backend[dev], npm install
make test            # backend tests
make dev-api         # :8000
make dev-web         # :3000  →  /  워크스페이스,  /gallery  컴포넌트
open design/index.html   # 디자인 레퍼런스 (브라우저로 열기)
```

OpenRouter 키: `keyring set molecular-workspace openrouter` (또는 `OPENROUTER_API_KEY`). 기본 egress 모드는 `local_only`라 키 없이도 돈다.
PyRosetta는 라이선스 별도 설치.

## 바이브코딩 순서

1. 코딩 에이전트에게 첫 메시지:
   ```
   CLAUDE.md를 읽고, docs/plan_v0.6.md와 docs/contracts.md를 요약해줘. 그리고 `make check`를 돌려서 현재 상태를 확인해.
   ```
2. 이후 마일스톤마다 `docs/milestones/M*.md` 맨 아래 **세션 프롬프트**를 그대로 붙여넣는다. M0 → M1 → … 순서.
3. 한 세션 = 한 마일스톤(또는 그 절반). 끝날 때 `make check` 통과를 확인하고 커밋.
4. 디자인은 바꾸지 말고 따라가게: "design/previews/<Component>.html과 똑같이 보이게" 라고 지시.
5. 계약을 바꾸는 요청이 나오면 에이전트가 멈추고 이유를 말하도록 CLAUDE.md에 적혀 있다 — 그때 사람이 결정.

## 문서

- `CLAUDE.md` — 에이전트 규칙(불변식, 명령, 작업 방식)
- `docs/plan_v0.5.md` — 원 계획서 · `docs/plan_v0.6.md` — 빈틈 보완 결정
- `docs/contracts.md` — 핸들·이벤트·에러·툴·API·OpenRouter 요청 스펙
- `docs/architecture.md` — 구성도와 흐름
- `docs/design-system.md` — 브랜드북 + 컴포넌트 가이드 + 파일 매핑
- `docs/milestones/M0–M6.md` — 할 일, 완료 기준, 세션 프롬프트
