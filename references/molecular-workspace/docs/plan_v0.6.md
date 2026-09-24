# Agent-Friendly Protein Viewer Platform — v0.6

기준일: 2026-09-24 · 전제: `plan_v0.5.md` (과학 코어·런타임 계약은 그대로 유효)

v0.6은 v0.5의 **빈틈을 메우는 결정**만 적는다. v0.5가 에이전트 내부(핸들, 실패 분류, 가드)는 탄탄했지만
사람의 입력면과 외부 연동(OpenRouter, Rosetta 작업 명세, 외부 조회)이 비어 있었다.

---

## A. 사람의 입력면

### A1. Goal 입력 (`GoalComposer`)
- run의 유일한 시작점: **자연어 목표 + 컨텍스트 핸들 + 옵션**(pipeline, budget 프리셋, egress 모드).
- 컨텍스트는 텍스트로 붙이지 않고 핸들로만(구조, 사람이 고른 `selection`, 이전 run 결과).
- 목표 텍스트는 `goal` 이벤트로 그대로 기록되며 `frontier.plan`의 입력이 된다.
- 기본 권장 동작은 "계획만"(dry_run).

### A2. 공유 명령 어휘 (`CommandBar`)
- 사람과 에이전트는 **같은 툴 어휘**를 쓴다(ChimeraX 명령줄 패턴). 사람이 친 명령도
  `POST /runs/{id}/commands` → `Run.call`로 가고 `decided_by: human`으로 기록된다.
- `#2`, `P1` 같은 짧은 참조는 UI 편의. 실행 전 **전체 핸들 JSON으로 해석해 보여주고** 그 JSON만 보낸다.
  → v0.5 §5.1 "enum > 자유 문자열" 원칙과 충돌하지 않는다.
- 결과: 이벤트 로그가 곧 재생 가능한 스크립트(ChimeraX `.cxc`에 해당).

### A3. 프롬프트 관리
- `prompts/<id>@<version>.md` (front matter: id, version, role, output_schema). 템플릿 해시와 렌더 해시를
  모든 `llm_call` 이벤트에 기록. 모델 핀과 함께 **프롬프트 버전도 벤치마크 축**이다.
- 역할: `jev.decide`, `frontier.plan`, `frontier.explain`, `repair`.
- `PromptInspector`: 호출 하나의 부분별 토큰(system / tool_schemas / compact_state / goal / prior_decisions),
  response_format, 캐시 적중, egress 차단 요약. "픽스처로 저장" → `local_only` 회귀 테스트용.

### A4. 선택(selection)은 핸들이다
- 뷰어·서열에서 사람이 고른 잔기 집합 = `selection` 핸들. 에이전트가 그대로 받는다.
- 서열 뷰의 design 마스크 칠하기 → `define_mutations` / design_mask 핸들 (Rosetta TaskOperation 입력).

## B. 외부 경계 (v0.5 §6 수정)

- 외부 경계는 **OpenRouter 하나가 아니다.** RCSB/AFDB/UniProt 조회도 egress다(어떤 ID를 봤는지가 나간다).
  → `EgressGate.fetch(url)`로 기록하고 `local_only`에서 차단.
- 차단 규칙(키 + 값 휴리스틱): coords/xyz 배열, 30자 이상 아미노산 문자열, 경로·구조 파일명.
- 로그에는 **정제된 페이로드 전문**을 남긴다. 키는 절대 남지 않는다.

## C. OpenRouter 연동 (v0.5 §7 보강)

| 항목 | 결정 |
|---|---|
| 키 | OS 키체인(`keyring`, service `molecular-workspace`) → 없으면 `OPENROUTER_API_KEY`. runs/·로그·프런트 금지 |
| provider 정책 기본값 | `data_collection: "deny"`, `zdr: true`, 구조화 출력 역할은 `require_parameters: true` |
| 폴백 | 핀 고정 역할은 `allow_fallbacks: false`, `models` 폴백 목록 없음. 켜면 응답 `model`을 매 결정에 기록, 핀과 다르면 벤치마크 제외 + UI 경고(`ModelRoute`) |
| 구조화 출력 | `response_format: json_schema, strict`. 파싱 실패 → `input_invalid` → `repair@` 1회 → 폐기 |
| HTTP → 실패 분류 | 408/429/5xx = transient, 400/422 = input_invalid, 401/403/402 = fatal(402는 크레딧 → ApprovalGate) |
| 비용 | 요청에 usage 포함, 호출별 토큰·비용을 `llm_call` 이벤트에 → Budget `external_tokens`/`usd` 차감 |
| 캐시 | `sha256(model, messages, temperature, max_tokens, response_format)` → 파일 캐시 |
| 스트리밍 | `frontier.explain`만. 검증은 문장 완료 시점에 문장 단위 |

## D. Rosetta 작업 명세 (v0.5 §8 보강)

- 점수 함수는 파라미터(`ref2015`, `ref2015_cart`). 결과·UI에 **scorefxn · Rosetta 버전 · 시드**를 항상 표시.
- `estimate_stability`(cartesian_ddg): 입력은 **같은 설정으로 cartesian relax된 구조**여야 한다 →
  `accepts: relaxed_structure`로 계약화. 결과는 돌연변이별 **평균 ± SD + 라운드별 값**(`energy_table@1`).
- 단위: 저장·표시 모두 **REU 원값**. kcal/mol 환산은 표시 옵션이며 라벨에 계수를 적는다.
- `score_interface`(InterfaceAnalyzer): `dG_separated, dSASA_int, dG_separated/dSASAx100, packstat,
  delta_unsatHbonds, hbonds_int`를 컬럼명 그대로.
- `residue_energies`: 잔기별·항목별 분해 → `EnergyBreakdown`, 속성 채색.
- 디자인 범위: resfile 마스크(design / repack / fixed) — `SequenceTrack`에서 칠하고 핸들로 고정.

## E. 뷰어 기능 (ChimeraX에서 가져온 패턴)

| 패턴 | 컴포넌트 | 비고 |
|---|---|---|
| 모델 트리 `#1`, `#2.1` | `ModelPanel` | 번호 = 명령줄 참조, 세션 내 재사용 금지, 파생 구조는 자식 |
| 서열–구조 연동 | `SequenceTrack` | 양방향 선택, pLDDT/ΔΔG/보존도 트랙 |
| 속성으로 채색 | `ScaleLegend` | 잔기별 값이 있는 핸들 컬럼이면 무엇이든 |
| AlphaFold PAE | `PAEPlot` | 영역 드래그 → 3D 표시, 도메인 채색. 열린 질문 3이 "예"면 M1 |
| 무거운 기능 | (어댑터) | ChimeraX의 `mcp`/REST를 선택형 외부 어댑터로 — 직접 재구현하지 않음 |

## F. MVP 재정렬 (v0.5 §10 수정)

| 단계 | v0.5 대비 추가 | 완료 기준 추가 |
|---|---|---|
| M0 | prompts 레지스트리 뼈대, config 로더 | 템플릿 해시가 이벤트에 남음 |
| M1 | CommandBar(사람 명령 = 같은 경로), ModelPanel, SequenceTrack, Mol* 교체 | 사람 명령이 `decided_by: human`으로 재생됨 |
| M2 | GoalComposer → dry_run 루프 | 깨진 입력 10종 폭주 없음 (v0.5 유지) |
| M3 | EgressGate.fetch, ModelRoute, PromptInspector, provider 정책 | 모든 요청 body에 정책 포함, served≠pin 감지 |
| M4 | resfile 마스크, cartesian_ddg 평균±SD, InterfaceAnalyzer | 시드·scorefxn·버전이 모든 energy 핸들에 |
| M5 | ExplainPanel 문장 단위 검증 표시 | 보고서의 모든 수치가 핸들로 역추적 |
| M6 | (선택) ChimeraX 어댑터, AG-UI | — |

## G. 여전히 열린 질문 (v0.5 §13 + 추가)

1. MMseqs2 로컬 DB (보존도 P1?)
2. local_only에서 frontier를 로컬 모델로?
3. AlphaFold 다중 모델 비교가 1급인가 → 예면 PAEPlot·compare_models가 M1
4. MD 궤적을 다루나 → 예면 핸들 저장소에 스트리밍
5. 오픈소스 전환 시점 → PyRosetta 어댑터 격리(현재 `mw/jobs/rosetta_worker.py`에 격리됨)
6. **(신규)** frontier 모델 핀: 어떤 모델로 고정할지 (`config/default.yaml`의 `CHANGE_ME`)
7. **(신규)** protonation 엔진: reduce / PropKa / OpenBabel 중 기본값
