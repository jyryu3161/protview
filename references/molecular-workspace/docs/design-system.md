# Design system — Molecular Workspace

Source of truth: `design/tokens.json` (tokens) · `design/components.css` (component classes, `mw-` prefix) · `design/previews/*.html` (visual reference; open `design/index.html`).

React implementations: `frontend/src/components/<file>.tsx` (table below). After editing tokens: `make tokens`.

## Component → file

| component | file | preview |
|---|---|---|
| Button | `src/components/primitives.tsx` | `design/previews/Button.html` |
| Segmented | `src/components/primitives.tsx` | `design/previews/Segmented.html` |
| HandleChip | `src/components/primitives.tsx` | `design/previews/HandleChip.html` |
| ResidueId | `src/components/primitives.tsx` | `design/previews/ResidueId.html` |
| FailureBadge | `src/components/status.tsx` | `design/previews/FailureBadge.html` |
| DecisionTag | `src/components/status.tsx` | `design/previews/DecisionTag.html` |
| StepRow | `src/components/run.tsx` | `design/previews/StepRow.html` |
| BudgetMeter | `src/components/run.tsx` | `design/previews/BudgetMeter.html` |
| ApprovalGate | `src/components/run.tsx` | `design/previews/ApprovalGate.html` |
| ToolError | `src/components/run.tsx` (ToolErrorCard) | `design/previews/ToolError.html` |
| EgressGate | `src/components/run.tsx` (EgressGateView) | `design/previews/EgressGate.html` |
| InteractionTable | `src/components/data.tsx` | `design/previews/InteractionTable.html` |
| GoalComposer | `src/components/input.tsx` | `design/previews/GoalComposer.html` |
| CommandBar | `src/components/input.tsx` | `design/previews/CommandBar.html` |
| PromptInspector | `src/components/model.tsx` | `design/previews/PromptInspector.html` |
| ModelRoute | `src/components/model.tsx` | `design/previews/ModelRoute.html` |
| ExplainPanel | `src/components/model.tsx` | `design/previews/ExplainPanel.html` |
| ModelPanel | `src/components/viewer.tsx` | `design/previews/ModelPanel.html` |
| SequenceTrack | `src/components/viewer.tsx` | `design/previews/SequenceTrack.html` |
| PAEPlot | `src/components/viewer.tsx` | `design/previews/PAEPlot.html` |
| ScaleLegend | `src/components/viewer.tsx` | `design/previews/ScaleLegend.html` |
| EnergyBreakdown | `src/components/energy.tsx` | `design/previews/EnergyBreakdown.html` |
| DdgTable | `src/components/energy.tsx` | `design/previews/DdgTable.html` |
| InterfaceScorecard | `src/components/energy.tsx` | `design/previews/InterfaceScorecard.html` |
| JobQueue | `src/components/energy.tsx` | `design/previews/JobQueue.html` |
| WorkspaceShell | `src/components/shell.tsx` | `design/previews/WorkspaceShell.html` |

## Brand book

로컬 단백질 구조 워크스페이스와 자율 에이전트 런타임을 위한 UI 체계. 한 사람이 하루 종일 켜 두는 도구이므로 화면은 조용하고 밀도가 높으며, 색은 장식이 아니라 **런타임의 상태를 읽는 언어**로만 쓴다.

## 원칙

1. **핸들이 보이는 단위다.** 툴 결과는 데이터가 아니라 핸들로 표시한다 — `HandleChip`. 원자 좌표, 서열 전문, 궤적은 UI의 어떤 텍스트 영역에도 풀어 쓰지 않는다. 내용이 필요하면 `materialize`로 필요한 컬럼만 테이블에 그린다.
2. **빈 결과는 실패가 아니다.** `scientific_null`은 `result-null`(중립 회색), 점선, ∅로 표시하고 스텝 상태는 done. 경고색·빨강을 절대 쓰지 않는다.
3. **모든 판단에는 출처가 붙는다.** 분기, 순위, 결론 옆에는 `DecisionTag`(`rule ≡ | jev ◆ | frontier ✦ | human ●`). rule도 빠짐없이 표시한다.
4. **사람 차례는 한 가지 모양이다.** 승인·예산 소진·egress 확인은 모두 `ApprovalGate` — 위 테두리 `focus` 색은 이 뜻으로만 쓴다.
5. **색만으로 말하지 않는다.** 모든 상태 색에는 글리프와 enum 문자열이 함께 있다.

## 글쓰기

- 한국어 문장 + 영문 식별자. 툴 이름, kind, 실패 분류, 모드 값(`local_only`, `scientific_null`)은 코드와 같은 문자열을 mono로, 번역하지 않는다. 설명은 한국어.
- 짧게, 존댓말 평서문. 느낌표·이모지 없음. 버튼은 동사: "실행", "선행 실행", "여기서 멈춤".
- 질문형은 승인 게이트에서만: "relax_structure를 실행할까요?"
- 수치는 항상 단위와 함께, 핸들에서 온 값만. `2.80 Å`, `ΔΔG −0.41 REU`. 단위는 `ink-muted`. 소수점 자릿수는 열 안에서 통일(거리 2자리, 에너지 2자리).
- 결과가 비었을 때: "포켓 0개 — 결과로 기록, 재시도 안 함". "실패", "오류"라고 쓰지 않는다.
- 잔기는 auth 기준 `A/100A`로 쓰고, label 값은 필요할 때만 `label B·97`로 덧붙인다.

## 색

두 테마. **dark가 기본**(뷰어와 장시간 작업), light는 리포트·인쇄·밝은 환경용. 텍스트 색 토큰의 usage 노트에 적힌 지면 위에서 두 테마 모두 4.5:1 이상을 지킨다.

- 지면: 앱 바탕 `surface-000`, 패널 `surface-100`, 호버·입력 `surface-200`, 선택 `surface-300`. Mol* 뷰포트만 `canvas`.
- 글자: `ink`, 보조 `ink-muted`. 두 단계뿐이다.
- 경계: 패널·행 구분은 `line`(장식), 컨트롤 테두리는 `line-strong`(3:1). 그림자는 떠 있는 것(`shadow-pop`: 팝오버, 명령 팔레트, 승인 드로어)에만.
- 브랜드 `brand`(청록)는 주 액션, running 상태, 선택 강조. 채움 위 글자는 `on-brand`. 옅은 선택 바탕 `brand-soft`.
- 런타임 의미색 — 한 토큰, 한 뜻:
  - 실패 분류 `fail-transient ↻` `fail-input ✎` `fail-precondition ⇢` `fail-resource ⊘` `fail-fatal ■`, 결과 `result-null ∅`
  - 스텝 `state-pending ○` `state-running ◐` `state-done ✓` `state-failed ✕`
  - 결정 출처 `prov-rule` `prov-jev` `prov-frontier` `prov-human`
  - 비용 `cost-expensive`, egress `egress-local` `egress-online` `egress-blocked`
- 과학 데이터 색: 상호작용 `int-hbond` `int-hydrophobic` `int-salt-bridge` `int-pi-stack` `int-cation-pi` `int-metal` `int-water-bridge` — 테이블 스와치와 3D 표현이 같은 토큰을 공유한다. 신뢰도는 AlphaFold 표준 `plddt-very-high` `plddt-confident` `plddt-low` `plddt-very-low`(테마 무관, 3D·범례 전용).
- 에너지는 발산 척도 `energy-favorable-strong` `energy-favorable` `energy-neutral` `energy-unfavorable` `energy-unfavorable-strong` — 파랑 = 음수(안정화), 주황 = 양수(불안정화). 빨강·초록 금지(`fail-fatal`, `state-done`과 섞이지 않게). |값| < 0.5 REU는 중립.
- 디자인 마스크(resfile) `mask-design` / `mask-repack` / `mask-fixed`, PAE 연속 척도 `pae-0…pae-4`, 중첩 비교 모델 `model-a…model-d`(Okabe–Ito, 테마 무관).
- 포커스: `focus` 2px 실선, 2px 간격(`outline-offset`). 모든 지면 위 3:1 이상. brand와 일부러 다른 색이다.

## 타입

IBM Plex Sans(UI, 한글은 Noto Sans KR로 폴백)와 IBM Plex Mono(데이터). 둘 다 Google Fonts에서 호스팅되며 `components/bundle.css`가 불러온다.

- UI: `display` 28/32(화면당 하나), `title` 16/22, `body` 14/20, 밀집 UI는 `body-sm` 13/18, 버튼·칩 `label` 12/16, 섹션 헤더 `eyebrow` 11/14 대문자 영문.
- Data: 핸들·툴 이름·run id `mono` 13/18, 칩 안 축약 `mono-sm` 12/16, 수치 `num` 13/18 (tabular).
- 규칙: 코드에 존재하는 문자열은 mono, 사람을 위한 문장은 sans.

## 간격 · 모서리 · 크기

- 4px 격자: `space-1` 4 … `space-6` 32. 패널 패딩은 `space-3`(밀집) 또는 `space-4`.
- 모서리는 작다: 칩 `radius-xs` 2, 컨트롤 `radius-sm` 4, 패널 `radius-md` 6. `radius-pill`은 진행 바와 상태 점에만.
- 높이: 컨트롤 `control-md` 28, 칩·테이블 안 `control-sm` 24, 행 `row` 28, 상단 바 `topbar` 44. 레이아웃 폭 `rail` 320, `inspector` 360.

## 입력과 명령

- run은 `GoalComposer` 하나로 시작한다: 자연어 목표 + 컨텍스트 **핸들**(구조, 사람이 고른 selection, 이전 run 결과) + pipeline / budget / egress. 기본 권장 액션은 "계획만"(dry_run).
- 사람과 에이전트는 같은 툴 어휘를 쓴다. 사람이 `CommandBar`에 친 명령도 에이전트 호출과 똑같이 `events.jsonl`에 남고, 로그는 재생 가능한 스크립트다. `#2`, `P1` 같은 짧은 참조는 실행 전에 항상 전체 핸들 JSON으로 풀어서 보여준다.
- 대화 말풍선 UI는 만들지 않는다. 대화 이력은 Run 타임라인이다.

## 모델 연결

- 모델 호출 스텝은 Inspector에서 `PromptInspector`(무엇이 몇 토큰 들어갔나, 템플릿 버전·해시, 스키마, 캐시)와 `ExplainPanel`(스트리밍 설명 + 문장별 검증)로 연다.
- 역할별 연결 상태는 `ModelRoute`: 핀 고정 모델, 키 위치(OS 키체인), provider 정책(`data_collection: deny`, `zdr`, `require_parameters`, 폴백 끔). 응답 모델이 핀과 다르면 `fail-transient` 테두리 알림으로 표시한다.
- 검증기가 버린 문장은 숨기지 않고 `mw-dropped` 취소선 + 실제 핸들 값을 보여준다. 수치 문장 끝에는 근거 핸들 `mw-cite`.

## 에너지 표기

- Rosetta 값은 **REU 원값**으로 표시한다. kcal/mol 환산은 표시 옵션이며 켜면 환산 계수를 라벨에 적는다.
- 에너지가 보이는 곳에는 점수 함수 이름, Rosetta 버전, 시드를 같은 줄에 둔다(`ref2015 · rosetta@a1b2c3 · seed 1207`).
- ΔΔG는 평균 ± 표준편차와 라운드별 점을 함께(`DdgTable`). 판정은 색 + 단어.
- 인터페이스는 InterfaceAnalyzer 컬럼명을 그대로 쓴다(`InterfaceScorecard`).

## 뷰어 도구

ChimeraX에서 검증된 패턴을 가져온다: 모델 트리(`ModelPanel`, `#1`·`#2.1` 번호 = 명령줄 참조), 서열–구조 연동(`SequenceTrack`, 드래그로 design 마스크 칠하기), 속성으로 채색(`ScaleLegend` — 잔기별 값이 있는 핸들 컬럼이면 무엇이든), AlphaFold PAE 행렬(`PAEPlot`, 영역 선택 → 3D 표시).

## 레이아웃

`WorkspaceShell`: 상단 바 / 레일(`Run` · `Models` · `Jobs` 탭) / Mol* 캔버스 + 하단 스트립(SequenceTrack, CommandBar) / Inspector. 패널 사이는 1px `surface-000` 틈. 캔버스 위 오버레이는 왼쪽 위 뷰 전환과 오른쪽 아래 범례 두 개뿐이다. 타임라인의 스텝을 선택하면 캔버스가 그 스텝의 `viewer_state`로 돌아가고 Inspector가 그 스텝의 출력 핸들을 연다.

## 글리프

아이콘 세트 대신 유니코드 글리프를 쓴다(sans 굵게): ↻ ✎ ⇢ ⊘ ∅ ■ / ○ ◐ ✓ ✕ / ≡ ◆ ✦ ● / ▶ ↺. 이모지 표현이 나오는 문자는 쓰지 않는다. 로고는 아직 없으며 이름을 일반 타입으로 쓴다.

## 쓰는 법

스타일은 `components.css`의 `mw-` 클래스, React 구현은 `frontend/src/components`(`@/components`에서 import). 페이지에는 tokens.css와 components.css를 넣고 루트에 `mw-root`를 붙인다. 테마는 `<html data-theme="dark|light">`. 폰트는 앱에서 `@fontsource`로 자체 호스팅한다(런타임에 Google 요청 없음). `design/previews/*.html`만 Google Fonts를 불러온다.


## Component guidelines

### Button

툴 실행, 승인, 중단 같은 명령 하나를 수행한다. 한 화면에 `mw-btn--primary`는 하나만 둔다.

- 소비자가 제공: 버튼 라벨(동사로 시작하는 한국어, 툴 이름은 원문 영문 그대로), 선택적 앞 글리프.
- 변형: 기본(`mw-btn`), `--primary`(`brand` 채움, 글자 `on-brand`), `--ghost`(툴바), `--stop`(`fail-fatal` 윤곽 — 루프 중단 전용), 크기 `--sm`(`control-sm`).
- Do: 비싼 작업은 라벨에 비용을 드러낸다("relax · expensive").
- Don't: `--stop`을 삭제나 일반 취소에 쓰지 않는다. 비활성 버튼은 왜 막혔는지 괄호로 적는다.

### Segmented

2–4개의 상호배타 모드를 전환한다. Egress 모드(`online | local_only | dry_run`)와 뷰어 표현 전환에 쓴다.

- 소비자가 제공: 옵션 목록(값은 코드상의 enum 문자열 그대로, mono), 선택값.
- Egress 모드는 항상 상단 바에 있고, 앞의 점 색이 `egress-online` / `egress-local`을 따른다. `dry_run`은 점 없음.
- Don't: 5개 이상 옵션, 또는 다중 선택에 쓰지 않는다.

### HandleChip

툴이 반환한 핸들 하나(`obj://…`)를 kind·축약 해시·스키마 버전과 함께 표시한다. 워크스페이스에서 데이터가 보이는 기본 단위다.

- 소비자가 제공: `kind`, `handle`(전체 문자열 — 툴팁과 복사용), `schema`. 해시는 앞 4·뒤 2자로 축약하고 `brand`로 강조한다.
- 클릭 = Inspector에서 열기(summary + preview 최대 5행). 두 번째 동작은 복사.
- Do: 에이전트 스텝, 리포트 각주, 에러의 `fix` 인자 등 핸들이 나오는 모든 곳에서 이 칩을 쓴다. 리포트의 수치는 반드시 출처 핸들 칩을 옆에 둔다.
- Don't: 핸들 내용을 칩 안에 풀어 쓰지 않는다. 핸들은 전달만 되는 문자열이다.

### ResidueId

잔기 식별자를 사람이 읽는 **auth** 기준(`chain/seq+icode`)으로 표시한다. label 기준 값은 보조로만 붙는다.

- 소비자가 제공: 정규 잔기 객체 `{chain_auth, seq_auth, icode, chain_label, seq_label, resname}`. 표시 문자열 `uid`를 파싱해서 만들지 않는다.
- label과 auth가 다를 때만 `mw-res__label`을 붙인다(Inspector에서는 항상).
- 클릭 = 뷰어에서 해당 잔기 선택·포커스.

### FailureBadge

툴 실패 분류 여섯 가지를 글리프+enum 문자열+색으로 표시한다. 색만으로 구분하지 않는다.

- 소비자가 제공: 분류 enum, 선택적 재시도 카운트(`2/3`, transient만).
- `scientific_null`은 **에러가 아니다**: 경고색 대신 `result-null`(중립 회색), 점선 테두리, 글리프 ∅. 스텝 상태도 done으로 둔다.
- `fatal`만 2px 테두리. 화면에 fatal이 있으면 다른 어떤 것보다 먼저 보여야 한다.
- Don't: 분류를 한국어로 번역해 배지에 쓰지 않는다(로그·이벤트와 같은 문자열이어야 검색된다). 설명은 툴팁/본문에 한국어로.

### DecisionTag

`decisions.jsonl`의 결정 출처 라벨(`rule | jev | frontier | human`)을 표시한다. 모든 분기 지점과 리포트의 결론 옆에 붙는다.

- 소비자가 제공: 출처 enum, 선택적 모델 핀(툴팁: `typesafe/jev-1.13`).
- human은 유일하게 채운 칩(`prov-human` 바탕, `surface-100` 글자) — 사람이 개입한 지점이 타임라인에서 가장 먼저 눈에 띄어야 한다.
- Do: rule 결정도 반드시 표시한다. 모델 기여 측정(결정 귀속)은 rule이 보여야 가능하다.

### StepRow

Run 레일 타임라인의 한 줄 = `events.jsonl`의 툴 호출 하나. 번호, 상태 글리프, 툴 이름, 오른쪽 메타(결정 출처·실패 분류·비용·시간)로 구성된다.

- 소비자가 제공: step 번호, 상태(`pending ○ | running ◐ | done ✓ | failed ✕`), 툴 이름, 메타 배지들, 선택적 하위 줄(`mw-step__sub`: 입력/출력 핸들, 짧은 설명).
- 선택된 스텝(`aria-selected`)은 `brand-soft` 바탕이고, 선택하면 뷰어가 그 스텝의 `viewer_state`로 복원된다.
- 캐시로 건너뛴 스텝(idempotency_key 일치)은 시간 대신 `↺ cached`를 `ink-muted`로.
- Don't: 스텝을 카드로 만들지 않는다. 100스텝 run도 한 화면에서 훑어져야 한다.

### BudgetMeter

run 예산 네 축(`wall_clock_s`, `expensive_calls`, `external_tokens`, `usd`)의 사용량을 한눈에 보여준다. 상단 바에는 가장 많이 쓴 축 하나만 축약해 두고, 펼치면 이 전체 형태.

- 소비자가 제공: 축별 used/limit.
- 막대 색: 기본 `brand`, 75% 이상 `--warn`(`fail-transient`), 소진 `--out`(`fail-fatal`). 값 텍스트는 항상 병기.
- 소진은 루프 종료가 아니라 ApprovalGate(`checkpoint_and_ask`)로 이어진다.

### ApprovalGate

자율 루프가 사람을 기다리는 지점. 네 가지 게이트(expensive 첫 호출, run 디렉터리 밖 쓰기, L2+ 데이터 egress, 최종 후보 선정)와 예산 소진 시 뜬다.

- 소비자가 제공: 게이트 종류(eyebrow), 질문 한 문장, 이유(비용·예산·입력 출처), 다음 계획(최대 5줄, mono), 액션 2–3개.
- 위쪽 2px 테두리는 `focus` 색 — "당신 차례"를 뜻하는 유일한 장식이다. 워크스페이스 하단 드로어 또는 Run 레일 끝에 붙는다.
- 질문은 "…할까요?"로 끝나고, 주 액션은 질문의 동사를 그대로 쓴다("실행"). 거절 버튼은 "여기서 멈춤"(run은 체크포인트되어 재개 가능).

### ToolError

툴 에러를 "다음 행동"과 함께 보여준다. 에러 JSON의 `message`와 `fix`를 그대로 렌더링한다.

- 소비자가 제공: 툴 이름, 한 문장 메시지, 실패 분류, 선택적 `fix { tool, args }`.
- `fix`가 있으면 한 번 클릭으로 그 호출을 실행할 수 있어야 한다. 인자는 HandleChip으로.
- 타입 계약 위반(툴 실행 전 거부)도 이 컴포넌트로, 변환 경로를 fix에 담는다.
- Don't: 스택 트레이스를 기본으로 펼치지 않는다(events.jsonl 링크로).

### EgressGate

외부로 나가는 호출(OpenRouter) 하나의 페이로드 구성을 필드 단위로 보여준다. 허용 필드는 일반 칩, 차단 필드는 `egress-blocked` + 취소선.

- 소비자가 제공: 대상(모델 역할), 토큰 수, 필드 목록과 허용/차단 여부, egress.jsonl 항목 번호.
- 서열 전문 허용처럼 기본 차단을 푸는 경우에는 ApprovalGate를 먼저 띄운다.
- `local_only` 모드에서는 이 컴포넌트 대신 "외부 호출 없음 · rule 폴백" 한 줄.

### InteractionTable

`interaction_set` 핸들을 `materialize(handle, projection)`으로 뽑은 행을 밀집 테이블로 보여준다.

- 소비자가 제공: projection 결과 행(잔기 객체, type enum, 수치+단위, 합의 출처). 전체 테이블을 한 번에 그리지 않고 페이지 단위로 materialize한다.
- 유형 스와치 색은 `int-*` 토큰이며 3D 뷰어의 상호작용 표현과 **같은 색**이어야 한다. hbond와 water bridge는 점선(`mw-int--dashed`).
- 수치는 `num` 스타일, 소수 둘째 자리, 단위는 `ink-muted`. 행 높이 `row`.
- Do: 행 호버 = 뷰어에서 해당 접촉 하이라이트. Don't: 색만으로 유형을 전달하지 않는다 — 항상 type 문자열을 같이.

### GoalComposer

사람이 run을 시작하는 유일한 입구. 자연어 목표 + 컨텍스트 핸들 + 실행 옵션을 한 덩어리로 받는다.

- 소비자가 제공: 목표 텍스트, 컨텍스트 핸들 목록(구조·선택·이전 run 결과 — 드래그로 추가), pipeline / budget 프리셋 / egress 모드 값, 예상 토큰(state 컴파일 후 추정).
- 목표 텍스트는 Frontier `plan`의 입력이며 그대로 `events.jsonl`에 기록된다. 컨텍스트는 텍스트로 붙여 넣지 않고 **핸들로만** 첨부한다.
- 두 개의 액션: "계획만"(dry_run — expensive 잡은 스텁) / "실행". "계획만"을 기본 권장한다.
- 컨텍스트 칩에 선택(selection) 핸들이 들어갈 수 있어야 한다 — 뷰어에서 사람이 고른 잔기 집합을 에이전트가 그대로 받는다.
- Don't: 채팅 말풍선 UI로 만들지 않는다. 대화 이력은 Run 타임라인이 대신한다.

### CommandBar

사람과 에이전트가 **같은 툴 어휘**를 쓰는 명령줄(ChimeraX 명령줄에서 가져온 패턴). 사람이 친 명령도 에이전트 호출과 똑같이 `events.jsonl`에 기록되고, 로그는 그대로 재생 가능한 스크립트가 된다.

- 소비자가 제공: MCP 툴 스키마(인자 이름·타입·enum·기본값·cost_class). 자동완성은 스키마에서만 만든다.
- `#1`, `P1` 같은 짧은 참조는 입력 편의일 뿐, 실행 전 **전체 핸들로 해석한 JSON 미리보기**를 반드시 보여준다(`mw-cmd__preview`). DSL 문자열이 그대로 툴에 가지 않는다.
- ↑/↓ 이력, Tab 완성, ↵ 실행. expensive 툴이면 ↵가 ApprovalGate를 연다.
- ⌘K 명령 팔레트와 같은 컴포넌트다. 팔레트는 툴 이름부터, 명령줄은 캔버스 하단에 상주.

### PromptInspector

모델 호출 하나에 **정확히 무엇이 들어갔는지**를 부분별 토큰으로 보여준다. 프롬프트 템플릿의 버전·해시, 구조화 출력 스키마, 캐시 적중, egress 차단 요약을 함께.

- 소비자가 제공: 호출 역할(`jev.decide | frontier.plan | frontier.explain | repair`), 템플릿 id@version + 해시, 부분별 토큰 수, response_format, 캐시 키/적중, egress 요약.
- 프롬프트 템플릿은 코드처럼 버전 관리한다(`prompts/plan@0.7.md`). 이벤트에는 템플릿 해시가 남고, "이전 버전과 diff"로 바뀐 줄을 본다.
- "픽스처로 저장" = 이 입력/출력을 회귀 테스트 픽스처로 떨어뜨린다(`local_only` 재생용).
- 막대는 이 호출 전체 대비 비율이며 `brand` 하나로만 칠한다.

### ModelRoute

OpenRouter 연결 하나(역할별: jev, frontier)의 상태 카드. 설정 화면과 Inspector에서 쓴다.

- 소비자가 제공: 역할, 핀 고정 모델 id, 키 상태(저장 위치), provider 정책 플래그, 최근 호출 통계, 응답 모델이 핀과 다를 때의 알림.
- 기본 정책: `provider.data_collection: "deny"`, `zdr: true`, 구조화 출력을 쓰는 역할은 `require_parameters: true`, 핀 고정 역할은 `allow_fallbacks: false` + `models` 폴백 목록 없음. 폴백을 켜면 응답의 실제 `model`을 매 결정에 기록하고 핀과 다르면 이 알림을 띄운다.
- 키는 OS 키체인에만. `runs/` 아래 어떤 파일에도, egress 로그에도 남지 않는다.
- HTTP 상태 → 실패 분류: 408/429/5xx = transient, 400(스키마) = input_invalid, 402(크레딧) = fatal + ApprovalGate.

### ExplainPanel

Frontier가 쓴 설명문을 스트리밍으로 보여주고, 숫자 검증기의 판정을 문장 단위로 드러낸다.

- 소비자가 제공: 문장 배열(각 문장의 인용 핸들, 검증 결과), 스트리밍 상태.
- 수치가 있는 문장 끝에는 근거 핸들의 축약 해시 `mw-cite`가 붙고, 클릭하면 그 핸들이 Inspector에 열린다.
- 검증 불일치 문장은 지우지 않고 취소선 + `dropped` 라벨 + 실제 핸들 값을 보여준다(사람은 왜 빠졌는지 알아야 한다). 리포트 내보내기에서는 제외된다.
- 스트리밍 중 커서는 `stream-cursor`. 완료되면 사라진다.

### ModelPanel

열려 있는 구조 모델 목록(ChimeraX Models 패널 패턴). Run 레일의 `Models` 탭.

- 소비자가 제공: 모델 트리(`#1`, 파생은 `#2.1`), 각 모델의 structure 핸들, 표시 여부, 비교 색(`model-a…d`), 한 줄 메타(pLDDT 평균, 기준 대비 RMSD, 총 에너지).
- `#N` 번호는 CommandBar의 짧은 참조와 같다. 번호는 세션 안에서 재사용하지 않는다.
- 파생 구조(relax, 돌연변이, prepare)는 부모 아래 들여쓰기 — provenance가 트리로 보인다.
- ● 표시 / ○ 숨김. 행 클릭 = 선택, 스와치 클릭 = 색 변경.

### SequenceTrack

체인 서열과 잔기별 트랙을 3D와 연동해 보여준다(ChimeraX Sequence Viewer + 속성 채색 패턴). 캔버스 하단 스트립.

- 소비자가 제공: 체인별 잔기 배열(ResidueId 규약, auth 번호로 눈금), 트랙 목록. 트랙 = 잔기별 값이 있는 아무 핸들의 컬럼(pLDDT, 보존도, 잔기 에너지, ΔΔG, SASA).
- `design` 트랙은 resfile 마스크: `mask-design`(아미노산 변경 허용) / `mask-repack`(측쇄만) / `mask-fixed`(고정). 칸을 드래그해 마스크를 칠하면 `design_mask` 핸들이 새로 생긴다 — Rosetta TaskOperation의 입력.
- 선택은 양방향: 서열에서 드래그 = 3D 선택, 3D 선택 = 서열 하이라이트(`brand-soft` + 아래 2px `brand`).
- 서열 문자는 화면에만. egress 페이로드에는 서열 전문이 들어가지 않는다.

### PAEPlot

AlphaFold 예측의 PAE 행렬(ChimeraX `alphafold pae` 패턴). 모델이 예측 구조일 때 Inspector에 뜬다.

- 소비자가 제공: PAE 행렬 핸들(materialize는 다운샘플), 체인·도메인 경계.
- 색은 `pae-0…pae-4`(테마 무관 연속 척도). 체인 경계는 `ink` 1px 구분선.
- 드래그로 사각 영역 선택 → 해당 잔기 쌍을 3D에 표시하고 평균 PAE를 보여준다(선택 테두리 `focus`). "도메인으로 채색"은 PAE 군집으로 도메인을 나눠 `model-a…d`로 칠한다.
- `compare_models`가 1급 시나리오라면 이 컴포넌트가 M1 범위에 들어간다(계획서 열린 질문 3).

### ScaleLegend

"속성으로 채색"(ChimeraX render by attribute 패턴)의 범례. 잔기별 값이 있는 핸들의 아무 컬럼이나 3D 색으로 매핑할 때 캔버스 오른쪽 아래에 뜬다.

- 소비자가 제공: 속성 이름과 단위, 척도 종류(발산 `energy-*` / 연속 `pae-*` / 범주 `plddt-*`, `int-*`), 구간 경계, 값이 있는 잔기 수.
- 에너지는 항상 발산 척도, 파랑 = 음수(안정화), 주황 = 양수(불안정화). 빨강·초록을 쓰지 않는다.
- 끝 눈금에는 방향을 말로 적는다("안정화", "불안정화").

### EnergyBreakdown

Rosetta 점수 항목별 분해(Residue Energy Breakdown / 돌연변이 전후 차이)를 0 중심 막대로 보여준다.

- 소비자가 제공: 대상(잔기 또는 잔기쌍, 돌연변이), 점수 함수 이름·Rosetta 버전·시드, 항목별 값(REU), 막대 척도 범위.
- 머리줄에 **점수 함수와 버전과 시드를 항상** 표시한다. 없으면 재현성 주장이 성립하지 않는다.
- 막대 색은 값의 부호·크기에 따른 `energy-*`. 가운데 0선은 `line-strong`.
- 단위는 REU 원값. kcal/mol 환산은 표시 옵션일 뿐이며, 켜면 환산 계수를 라벨에 적는다.

### DdgTable

`estimate_stability`(cartesian_ddg 등) 결과를 돌연변이별로. 평균만이 아니라 **반복 라운드의 분산**을 같이 보여준다.

- 소비자가 제공: 돌연변이(auth 번호 기준 `L48A`), 평균 ± 표준편차(REU), 라운드별 값, 반복 수 / 수렴 여부, 판정 구간.
- 라운드 점(`ink-muted`)과 평균선(`ink`)을 같은 축에 둔다. 분산이 크면 판정보다 먼저 눈에 띈다.
- 판정은 색 칩 + 단어("안정", "중립", "불안정"). |ΔΔG| < 0.5 REU는 중립.
- 부호 규약: 음수 = 안정화. 헤더에 단위를 쓰고 셀에서 반복하지 않는다.
- 선행 조건: 입력 구조는 같은 점수 함수 설정으로 cartesian relax된 것이어야 한다 — 아니면 ToolError(precondition).

### InterfaceScorecard

`score_interface`(Rosetta InterfaceAnalyzer) 결과 요약 6칸.

- 소비자가 제공: `dG_separated`, `dSASA_int`, `dG_separated/dSASAx100`, `packstat`, `delta_unsatHbonds`, `hbonds_int`, 그리고 인터페이스 정의(체인 쌍, 예: `A_B`).
- 이름은 Rosetta 출력 컬럼 그대로(mono), 설명은 한국어 한 줄.
- 임계값을 넘는 값만 색을 바꾼다(예: `delta_unsatHbonds` 많음 → `fail-input`). 임계값은 rule이며, 그 판단은 DecisionTag rule로 기록된다.

### JobQueue

로컬 PyRosetta 잡 큐(SQLite `jobs` 테이블)의 상태. Run 레일 하단 또는 상단 바에서 펼치는 드로어.

- 소비자가 제공: 잡 id, 프로토콜 + 점수 함수, 진행/대기/완료/실패 분류, 시드, 워커, 경과 시간.
- 시드와 점수 함수는 항상 보인다. 타임아웃은 `resource_exceeded`로 분류하고 재시도 버튼을 두지 않는다.
- kill은 프로세스 강제 종료이며 해당 스텝은 failed가 된다(확인 없이 즉시 — 멈추는 쪽은 늘 안전하다).

### WorkspaceShell

앱 전체 레이아웃. 상단 바(`topbar`) + 왼쪽 Run 레일(`rail`) + 가운데 Mol* 캔버스 + 오른쪽 Inspector(`inspector`). 패널 사이는 1px `surface-000` 틈으로 구분하고 그림자를 쓰지 않는다.

- 상단 바: run id(mono), 파이프라인 이름, Egress Segmented, 축약 BudgetMeter, 명령 팔레트(⌘K), 중단 버튼.
- 레일 탭: `Run`(StepRow 목록, 맨 아래 ApprovalGate — run이 없을 때는 그 자리에 GoalComposer), `Models`(ModelPanel), `Jobs`(JobQueue).
- 캔버스: Mol* 뷰포트, 배경 `canvas`. 오버레이는 왼쪽 위 뷰 Segmented, 오른쪽 아래 범례(상호작용, pLDDT, ScaleLegend)만.
- 캔버스 아래 스트립: SequenceTrack(서열 + design 마스크 등 트랙)과 상주 CommandBar.
- Inspector: 선택된 대상에 따라 — 핸들이면 summary·preview·InteractionTable, 모델 호출 스텝이면 PromptInspector + ExplainPanel, 에너지 스텝이면 DdgTable / EnergyBreakdown / InterfaceScorecard, 예측 구조면 PAEPlot. 맨 아래 provenance(produced_by, schema, seed).
- 소비자가 제공: 네 영역의 내용. 1280px 미만에서는 Inspector가 캔버스 위 오른쪽 오버레이 시트로 접힌다.
