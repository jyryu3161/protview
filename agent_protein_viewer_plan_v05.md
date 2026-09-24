# Agent-Friendly Protein Viewer Platform
## v0.5 — 인터뷰 반영판

기준일: 2026-09-23
전제 문서: `agent_protein_viewer_plan.md` (v0.4-general)

---

## 0. 인터뷰 결과와 그 파급

| 항목 | 답 | 설계에 주는 영향 |
|---|---|---|
| 1차 사용자 | 나/소수 팀의 개인 도구 | 멀티테넌시·인증·과금·권한 모델 **전부 제거**. single-user 가정. UI는 "내가 쓰기 편한 것" 기준이지 온보딩 대상이 아님 |
| 실행 환경 | 전부 로컬/온프렘, PyRosetta 보유 | 좌표는 프로세스 밖으로 안 나감. 단 **OpenRouter는 외부 egress** → 경계가 정확히 한 군데로 좁혀짐 |
| 툴 체이닝 | 에이전트가 자율 분기/재시도 | 가장 큰 변경점. 툴을 "함수"가 아니라 **재시도 가능한 잡**으로 설계해야 함. v0.4의 `max_steps: 20` 수준 가드로는 부족 |

v0.4에서 바뀌는 것은 과학 코어가 아니라 **런타임 계약**이다. 3장·4장이 이 문서의 본론이다.

---

## 1. 제품 정의 (수정)

> **로컬 단백질 구조 워크스페이스 + 자율 에이전트 런타임**
> 좌표는 로컬, 판단은 compact state, 외부로 나가는 것은 토큰 수천 개뿐

바뀐 한 줄: "A2A-compatible"은 목표가 아니라 **부산물**이다. 개인 도구인데 A2A 서버부터 세우면 순서가 뒤집힌다. A2A는 MVP 5 이후, 혹은 오픈소스로 돌릴 때.

---

## 2. 개인 도구라서 잘라내는 것

의식적으로 **안 만드는** 목록 (나중에 유혹이 오면 이 절을 다시 볼 것):

- 사용자 계정, 세션, RBAC, 조직/워크스페이스 개념
- 결과 공유 링크, 퍼블릭 갤러리
- 멀티테넌트 잡 스케줄러 (로컬 큐 하나면 충분)
- Knowledge Pack SDK, 플러그인 마켓
- 관리자 대시보드, 사용량 미터링
- 온보딩 위저드 / 튜토리얼

대신 이것에 시간을 쓴다: **스키마 안정성, 재현성, 에이전트가 실수해도 망가지지 않는 런타임.**

---

## 3. 툴 체이닝 — Handle 기반 설계 (핵심)

에이전트가 자율 분기·재시도를 하는 순간, "툴이 JSON을 반환하고 모델이 그걸 다음 툴에 붙여넣는" 방식은 세 군데서 깨진다.

1. 큰 결과(원자 좌표, 궤적, 에너지 테이블)가 컨텍스트를 태운다
2. 모델이 중간 결과를 **미묘하게 변형해서** 다음 툴에 넘긴다 (숫자 재타이핑 = hallucination 표면)
3. 재시도 시 같은 입력인지 보장이 안 된다

### 3.1 규칙

> 툴은 **데이터를 반환하지 않는다. 핸들과 요약을 반환한다.**

```json
{
  "handle": "obj://run_20260923_a91/interactions/v1",
  "kind": "interaction_set",
  "summary": { "n_edges": 47, "n_hbond": 12, "n_hydrophobic": 26 },
  "preview": [ { "residue": "A:45", "type": "hbond", "distance_A": 2.8 } ],
  "schema": "interaction_set@1.2",
  "produced_by": "call_0007"
}
```

- `handle`은 **content-addressed** — 같은 입력 + 같은 툴 버전 = 같은 해시. 재시도가 공짜가 되고 캐시가 저절로 생긴다.
- 모델은 핸들을 **문자열로 전달만** 한다. 내용을 절대 재구성하지 않는다.
- `preview`는 최대 N개(기본 5). 모델이 감을 잡는 용도지 계산 근거가 아니다.
- 전체 내용이 필요하면 `materialize(handle, projection)`으로 **필요한 컬럼만** 뽑는다.

### 3.2 객체 저장소

로컬 파일시스템이면 충분하다.

```
runs/<run_id>/objects/<sha256>.{json,parquet,pdb,cif}
runs/<run_id>/index.sqlite     # handle → path, schema, provenance, 크기
```

Parquet을 쓰는 이유: interaction/candidate 테이블이 수천 행 넘어가면 JSON은 파싱 비용과 디스크 양쪽에서 진다. `projection` 질의도 자연스러워진다.

### 3.3 타입 계약

핸들에는 `kind`가 있고, 각 MCP 툴은 받는 `kind`를 선언한다.

```yaml
tool: estimate_stability
accepts:
  structure: [structure, relaxed_structure]
  mutations: [mutation_set]
emits: energy_table
cost_class: expensive          # cheap | moderate | expensive
idempotent: true
typical_runtime_s: 180
```

에이전트가 타입이 안 맞는 핸들을 넘기면 **툴 실행 전에** 거부하고, 왜 안 맞는지와 변환 경로(`relax` 를 먼저 돌려야 함)를 돌려준다. 이게 자율 루프에서 가장 자주 살려주는 방어선이다.

### 3.4 체이닝 형태

세 가지를 모두 지원하되 우선순위를 둔다.

1. **암묵적 체이닝** (P0) — 에이전트가 핸들을 다음 툴 인자로 넘김. 기본 경로.
2. **선언적 파이프라인** (P1) — 자주 쓰는 순서를 YAML로 고정. 에이전트 판단 없이 한 방에 실행.
   ```yaml
   pipeline: inspect_complex
   steps:
     - load_structure: { source: $input }
     - prepare: { protonate: true, strip_waters: keep_bridging }
     - detect_pockets: { from: $1 }
     - compute_interactions: { from: $1, pocket: $2 }
     - compile_state: { from: [$1, $2, $3] }
   ```
3. **에이전트 조립** (P2) — 사용자가 GUI에서 드래그. 개인 도구에선 후순위.

선언적 파이프라인이 중요한 이유: **자율 루프의 비용 상한을 결정론으로 눌러주기 때문.** 정해진 것은 정해진 대로 돌리고, 에이전트는 진짜 분기가 필요한 지점에서만 판단한다.

---

## 4. 자율 분기 / 재시도 런타임

v0.4의 `max_steps: 20`, `max_rosetta_jobs: 8`은 예산 가드일 뿐 **실패 처리 정책이 아니다.**

### 4.1 실패 분류 (툴이 반드시 이 중 하나로 라벨)

| 분류 | 예 | 에이전트가 해도 되는 것 |
|---|---|---|
| `transient` | 디스크 잠금, OpenRouter 5xx, 일시적 OOM | 지수 백오프 재시도 (최대 3) |
| `input_invalid` | 체인 ID 없음, 리간드 파싱 실패 | 인자 고쳐서 **1회** 재시도, 그 후 사람 |
| `precondition` | relax 안 된 구조로 에너지 요청 | 선행 툴 실행 후 재시도 |
| `resource_exceeded` | 잡 타임아웃, 메모리 한도 | 재시도 금지. 파라미터 축소 제안만 |
| `scientific_null` | 포켓 0개, 접촉 0개 | **재시도 금지.** 이건 결과지 에러가 아님 |
| `fatal` | PyRosetta 초기화 실패 | 즉시 중단 + 사람 |

`scientific_null`을 따로 두는 이유: 에이전트가 "결과가 비었네 = 실패네"로 읽고 파라미터를 흔들면서 무한히 도는 게 이런 루프의 대표적 폭주 패턴이다. 빈 결과는 **정상 종료**로 타입화한다.

### 4.2 재시도 규칙

```yaml
retry:
  transient:      { max: 3, backoff: exponential, base_s: 2 }
  input_invalid:  { max: 1, requires_different_args: true }
  precondition:   { max: 1, must_run: <declared prerequisite> }
  default:        { max: 0 }

loop_guards:
  no_progress_steps: 4        # 새 핸들이 안 생기면 중단
  repeated_call_hash: 2       # 동일 (tool, args) 2회 → 중단
  oscillation_window: 6       # A→B→A→B 패턴 감지
```

**동일 호출 해시 감지**가 실무에서 제일 많이 잡는다. `(tool_name, normalized_args)` 해시를 세고 2회 넘으면 그 분기를 죽인다.

### 4.3 예산

토큰이 아니라 **세 축**으로 잡는다.

```yaml
budget:
  wall_clock_s: 1800
  expensive_calls: 8          # cost_class=expensive 총합
  external_tokens: 120000     # OpenRouter 전체 (Jev + Frontier)
  usd: 2.00
on_exhaustion: checkpoint_and_ask   # 죽이지 말고 멈춰서 물어봄
```

`checkpoint_and_ask`가 중요: 개인 도구라 옆에 사람이 있다. 예산 끝에서 죽이지 말고 "여기까지 했고 다음은 이거, 계속?"으로 넘긴다.

### 4.4 체크포인트와 재개

자율 루프는 **반드시 중간에 죽는다** (PyRosetta 잡, 노트북 sleep, OpenRouter 타임아웃).

```
runs/<run_id>/
  run.sqlite            # 상태 머신: 각 step의 pending/running/done/failed
  events.jsonl          # append-only, 이것만 있으면 전체 재구성 가능
  objects/
```

- 모든 툴 호출은 `idempotency_key = sha256(tool, version, normalized_args)`
- 재개 시 done인 스텝은 핸들만 다시 붙여서 건너뜀
- `events.jsonl`이 **단일 진실 원천**. sqlite는 파생 인덱스일 뿐 (날려도 재생성 가능)

### 4.5 승인 게이트

자율 루프에서도 사람이 반드시 끼는 지점:

1. `cost_class: expensive` 첫 호출 (이후는 예산 내 자동)
2. 파일 쓰기가 run 디렉터리 **밖**으로 나갈 때
3. 외부 egress에 L2 이상 데이터가 실릴 때 (§6)
4. 최종 후보 선정

드라이런 모드를 기본 옵션으로: 에이전트가 계획만 세우고 `expensive` 잡은 스텁 결과로 돌려서 **루프 로직만** 검증한다. 이거 없으면 Rosetta 돌려가며 프롬프트 디버깅하게 된다.

---

## 5. MCP 툴 설계 — 에이전트 친화의 실체

"에이전트 친화적"은 툴 개수가 아니라 **에이전트가 틀리기 어려운 인터페이스**다.

### 5.1 원칙

- **툴 20개 이하.** 많으면 선택 정확도가 떨어진다. 파라미터로 흡수할 수 있으면 흡수한다.
- **enum > 자유 문자열.** `selection: "A:100-120"` 같은 DSL은 에이전트가 매번 조금씩 틀린다. `{ chain: "A", range: [100,120] }`.
- **에러가 다음 행동을 알려준다.**
  ```json
  { "error": "precondition",
    "message": "energy_table requires relaxed structure",
    "fix": { "tool": "relax_structure", "args": { "structure": "obj://.../structure/v1" } } }
  ```
- **읽기/쓰기 분리.** 조회 툴은 언제 몇 번 불러도 안전하다고 명시 → 에이전트가 확인 호출을 주저하지 않는다.
- **기본값이 안전한 쪽.** `detect_pockets`의 기본은 상위 3개지 전체가 아니다.

### 5.2 레벨별 툴 (v0.4 §10 재정리)

```
L1 viewer      load, select, camera, snapshot, restore_scene
L2 structural  prepare_structure, detect_pockets, compute_interactions,
               measure, align, compute_sasa, conservation
L3 energetic   relax_structure, estimate_stability, score_interface
L4 state       compile_state, materialize, diff_states
L5 workspace   inspect_complex, compare_models, rank_candidates
```

에이전트는 기본적으로 **L5만** 본다. L1–L4는 필요할 때 `expand_toolset`으로 열어준다. 툴 20개를 한 번에 노출하는 것보다 계층적 노출이 라우팅 정확도에 낫다.

### 5.3 `prepare_structure`가 P0인 이유 (v0.4에 빠져 있던 것)

구조 준비는 결과 전체를 좌우하는데 v0.4에는 명시적 단계가 없다. 재현성 주장("같은 PDB → 같은 interaction table")도 여기서 깨진다.

반드시 명시적·기록 대상이어야 하는 결정들:

- **altloc 선택** — A/B 중 무엇? 점유율 기준?
- **protonation** — pH, 히스티딘 tautomer, reduce/PropKa/OpenBabel 중 무엇
- **물 분자** — 전부 제거 / 브리징만 보존 / 전부 보존
- **결측 잔기·측쇄** — 모델링할지 비워둘지
- **다중 모델 (NMR/앙상블)** — 어느 모델? 앙상블 전체?
- **대칭 짝 (crystal symmetry mate)** — 인터페이스가 대칭 짝에 있으면 접촉 계산이 통째로 틀린다
- **리간드 결합 차수** — CCD 사전 기반 vs 추론. RDKit으로 sanitize 실패 시 정책
- **금속·보조인자** 처리

준비 결정은 전부 `preparation_manifest`로 핸들화한다. 이게 없으면 "같은 PDB 다시 열면 같은 테이블"은 성립하지 않는다.

### 5.4 잔기 식별자 규약 — 지금 정해야 할 것

mmCIF의 `label_asym_id/label_seq_id`와 PDB의 `auth_asym_id/auth_seq_id`가 다르고, **insertion code**가 있다. 여기서 섞이면 나중에 전부 다시 짜야 한다.

```json
{ "chain_auth": "A", "chain_label": "B",
  "seq_auth": 100, "icode": "A", "seq_label": 97,
  "resname": "ASP", "uid": "A/100A" }
```

- 내부 정규형은 **label 기반**, 사람·모델에게 보이는 표시는 **auth 기반**
- 문자열 `uid`는 표시·로그용이며 파싱해서 쓰지 않는다
- Mol*, ProLIF, PLIP, PyRosetta가 각자 다른 규약을 쓰므로 **어댑터마다 변환 테스트**를 둔다 (여기가 조용히 틀리는 1순위 지점)

---

## 6. 프라이버시 — 경계가 한 군데로 좁혀짐

전부 로컬이므로 신경 쓸 외부 경계는 **OpenRouter 호출 하나**다. 그래서 거기에 게이트를 건다.

```
Egress Gate (모든 외부 호출이 반드시 통과)
  ├ 허용: compact state, 요약 통계, 잔기 식별자, 거리/에너지 스칼라
  ├ 차단: 원자 좌표 배열, 서열 전문, 파일 경로, 원본 파일명
  ├ 로깅: 나가는 페이로드 전문을 runs/<id>/egress.jsonl 에 그대로 기록
  └ 모드: online | local_only | dry_run
```

- `local_only` 모드에서도 앱이 **동작해야 한다** — Jev/Frontier 호출은 규칙 기반 폴백으로 대체. 비행기/에어갭 환경뿐 아니라 **회귀 테스트**에 쓰인다.
- 서열은 생각보다 민감하다. 미공개 구조를 다룰 여지가 있으면 서열 전문은 기본 차단, 필요 시 명시적 허용.
- egress 로그를 남기는 이유: "뭐가 나갔는지"를 나중에 정확히 말할 수 있어야 한다. 개인 도구라도 이건 싸게 얻는 보험이다.

---

## 7. OpenRouter 연동

### 7.1 어댑터

```text
DecisionClient.decide(state, questions)   # Jev
ChatClient.plan(state, goal)              # Frontier
ChatClient.explain(state, evidence_ids)
```

- SDK 직접 의존 금지 (v0.4 유지). HTTP + 픽스처 테스트.
- **모델 핀 고정**: `typesafe/jev-1.13` 같은 prod 핀을 쓰고, 버전 문자열을 모든 decision 이벤트에 기록. 모델이 바뀌면 벤치마크를 다시 돌린다.
- 프런티어 모델은 설정으로 교체 가능하되, **벤치마크는 핀별로 따로** 남긴다.

### 7.2 자율 루프에서 필요한 추가 사항

- **응답 캐시**: `sha256(model, prompt, params)` → 응답. 루프 디버깅 시 같은 프롬프트를 수십 번 돌리게 되는데 캐시 없으면 돈과 시간이 다 샌다.
- **타임아웃 + 예산 연동**: 호출마다 남은 예산을 확인하고, 초과 예상이면 호출 전에 `checkpoint_and_ask`.
- **구조화 출력 강제**: 프런티어의 `propose_mutations`는 JSON 스키마 강제 + 서버측 검증. 스키마 위반 시 1회 리페어 프롬프트, 실패하면 폐기.
- **숫자 검증기** (v0.4 §8 유지, 강화): LLM 출력에서 단위 붙은 수치(`2.8 Å`, `ΔΔG 0.4`)를 정규식으로 뽑아 **핸들의 실제 값과 대조**. 불일치하면 그 문장을 통째로 버린다. "폐기"를 문장 단위로 하는 게 요령 — 전체 응답을 버리면 루프가 자주 막힌다.

### 7.3 Jev 사용 재검토

v0.4는 Jev를 라우팅·게이트·랭킹에 쓴다. 타당하다. 다만 자율 루프에서 한 가지 추가:

> 규칙으로 되는 판단에 Jev를 쓰지 않는다.

`clash > 0 → 재계산` 같은 건 임계값이지 모델 판단이 아니다. Jev는 **임계값으로 안 잘리는 회색 지대**에만 쓴다. 이 구분을 초기에 안 하면 Jev 호출이 루프 전체에 뿌려지고, 나중에 어느 결정이 실제로 모델 덕인지 측정이 안 된다.

판단을 세 통으로 나누고 이벤트에 라벨을 붙인다: `rule` / `jev` / `frontier` / `human`.

---

## 8. 로컬 잡 실행 (PyRosetta)

PyRosetta 라이선스가 있으니 §6 에너지가 MVP에 들어갈 수 있다. 다만:

- **별도 프로세스에서 실행.** PyRosetta는 전역 상태가 있고 초기화가 무겁다. 워커 프로세스 풀 + 요청당 job 격리.
- **난수 시드 고정 및 기록.** 시드 없으면 재현성 주장이 성립하지 않는다.
- **타임아웃 + 프로세스 강제 종료.** 자율 루프가 relax를 잘못된 구조에 걸면 매달릴 수 있다.
- **큐는 SQLite 하나로 충분.** 개인 도구에 Celery/Redis는 과하다. `jobs` 테이블 + 워커 폴링.
- **관측**: 잡별 wall clock, 시도 횟수, 시드, Rosetta 버전, 스코어 함수 이름을 전부 아티팩트에 남긴다.
- FoldX는 라이선스가 별건이므로 **어댑터 인터페이스만** 두고 구현은 선택.

---

## 9. 아티팩트 (v0.4 §13 확장)

```
runs/<run_id>/
  events.jsonl             # 단일 진실 원천 (append-only)
  run.sqlite               # 파생 인덱스
  objects/<sha256>.*       # 핸들 내용
  preparation_manifest.json
  decisions.jsonl          # rule|jev|frontier|human 라벨 포함
  egress.jsonl             # 외부로 나간 페이로드 전문
  jobs.jsonl               # Rosetta 등 로컬 잡 기록
  report.md
  viewer_state.json
  snapshots/
```

`events.jsonl` 하나로 전체를 재구성할 수 있어야 한다. 이걸 테스트로 강제한다: **run 디렉터리에서 events.jsonl 빼고 다 지운 뒤 재생 → 동일한 핸들 집합이 나오는가.**

---

## 10. MVP 재정렬

v0.4의 순서를 인터뷰 결과에 맞춰 조정. **핸들 저장소와 실패 분류가 앞으로 온다** — 나중에 끼워넣기가 제일 비싼 두 가지이기 때문.

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **M0** | 객체 저장소 + 핸들 + 이벤트 로그 + `prepare_structure` | 같은 PDB 두 번 → 동일 해시. events.jsonl만으로 재생 성공 |
| **M1** | Mol* 뷰어 + L1/L2 MCP 툴 + interaction 스키마 | 잔기 식별자 규약이 Mol*/ProLIF/PLIP 사이에서 왕복 일치 |
| **M2** | 오케스트레이터 + 실패 분류 + 재시도 + 루프 가드 + 드라이런 | 고의로 깨진 입력 10종에 대해 루프가 폭주 없이 멈춤 |
| **M3** | Egress gate + Jev 어댑터 + 결정 라벨링 | `local_only` 모드로 전 경로 통과. 결정 출처가 전부 라벨링됨 |
| **M4** | PyRosetta 잡 큐 + `estimate_stability` + 예산 집행 | expensive 잡이 예산·승인 게이트를 실제로 통과/차단 |
| **M5** | Frontier propose → 툴 피처 → Jev rank → report | 보고서의 모든 수치가 핸들로 역추적됨 |
| **M6** | (선택) AG-UI 동기화, A2A 스킬 | 에이전트 스텝을 한 클릭으로 뷰어 복원 |

**M0–M2가 이 프로젝트의 진짜 리스크 구간이다.** 과학 도구는 성숙했고 붙이면 붙는다. 자율 루프가 조용히 망가지는 걸 잡아내는 인프라가 없는 게 실패 사유가 된다.

---

## 11. 벤치마크 (v0.4 §16 + 루프 항목)

v0.4 항목 유지에 더해:

- **루프 종료율**: 100회 자율 실행 중 가드 없이 정상 종료한 비율
- **재시도 낭비율**: 성공에 기여하지 않은 재시도 비용 / 전체 비용
- **결정 귀속**: `jev`/`frontier` 결정을 `rule` 베이스라인으로 바꿨을 때 결과가 달라지는 비율 — **모델이 실제로 기여하는지**의 유일한 측정
- **재현 테스트**: 동일 run 2회 → 핸들 해시 집합 일치
- `scientific_null` 오분류율 (빈 결과를 에러로 읽은 횟수)

§16 원칙 유지: 이 숫자들이 나오기 전에는 구조 성능을 주장하지 않는다.

---

## 12. 스택 (조정)

v0.4 §18에서 개인 도구용으로 축소:

- **Frontend**: Next.js + Mol*. AG-UI는 M6까지 보류 — 초기엔 WebSocket으로 scene JSON 밀어주는 것으로 충분
- **Backend**: FastAPI + Pydantic (유지)
- **저장**: SQLite + Parquet + 파일시스템. Postgres 불필요
- **에이전트**: PydanticAI 또는 LangGraph. **다만 프레임워크에 루프 제어를 맡기지 말 것** — §4의 실패 분류·예산·체크포인트는 직접 소유한다. 프레임워크는 툴 호출 배선용
- **과학**: gemmi, Biopython, RDKit, ProLIF + PLIP(합의용), fpocket/P2Rank, MDAnalysis, PyRosetta

---

## 13. 열린 질문

1. **서열 보존도**: MMseqs2 로컬 DB를 둘 것인가? 로컬 원칙을 지키려면 UniRef 사본이 필요하고 수십 GB다. 보존도를 P1로 미룰지 결정 필요.
2. **Frontier 모델 로컬화**: `local_only` 모드에서 프런티어 역할을 로컬 모델로 대체할 생각이 있는지. 있다면 프롬프트를 처음부터 작은 모델에도 통하게 써야 한다.
3. **앙상블/다중 상태**: 단일 구조만 볼 것인가, 아니면 AlphaFold 모델 여러 개 비교가 1급 시나리오인가. 후자면 `compare_models`가 M1로 올라와야 한다.
4. **MD 포함 여부**: MDAnalysis를 스택에 넣었는데 궤적을 실제로 다룰 계획인지. 다룬다면 핸들 저장소 설계에 대용량 스트리밍이 추가된다.
5. **오픈소스 전환 시점**: 지금 개인 도구로 짜면서도 나중에 공개할 생각이면 라이선스가 갈린다 — PyRosetta/FoldX 어댑터는 처음부터 선택적 확장으로 격리해야 한다.

---

## 14. 핵심 문장 (v0.5)

> 모델은 구조를 보지 않는다. 도구가 만든 state를 판단한다.
> **툴은 데이터를 넘기지 않는다. 핸들을 넘긴다.**
> **빈 결과는 실패가 아니다. 재시도할 실패와 멈출 실패를 타입으로 구분한다.**
> Jev는 예산을 나눈다. Frontier는 목표를 해석하고 설명한다.
> 외부로 나가는 것은 compact state뿐이고, 무엇이 나갔는지는 기록된다.
