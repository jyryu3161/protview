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
