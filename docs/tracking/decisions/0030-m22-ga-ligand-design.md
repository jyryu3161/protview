# 0030. M22 리간드 GA 설계는 게시된 M17 후보 집합 안에서 작업 하나가 GA 한 번을 돌려 어느 후보를 도킹할지 세대마다 정하고, 개체 점수는 단독 M18 자유 도킹의 qvina 점수뿐이며, 예산은 시작 전에 예약 단위를 한 번 잡는다

- 상태: 채택 (사용자 결정 2026-10-05, M22 명세 확정 때 사용자가 모든 질문에서 추천안을 골랐다. 아래 "조율 세션이 정한 것"은 실행 중 조율 세션이 승인한 세부·결과이며 사용자가 최종 확인에서 바꿀 수 있다)

## 배경
M22는 리간드 설계·탐색 탭의 넷째 기능이고 여는 시나리오는 "GA 기반 리간드 설계"다(로드맵 M22: GA 설계 엔진(리간드 공간)과 파라미터 편집 화면·가드, seed·세대 기록). M17은 후보 집합(최대 2,000개)까지, M19는 사람이 고른 후보 ≤ 50개를 한 설정으로 도킹하는 데까지 왔다. 넓은 풀에서 도킹 상한 안에 어디를 볼지 정하는 탐색 방법이 없었다. 위험은 다섯 가지였다: 선택 규칙("점수가 낮은 개체를 남김")이 순위·최고·개선·추천으로 읽히는 것, 세대 간 최솟값 변화가 "개선"으로 읽히는 것, 같은 seed인데 저장 결과 집합이 달라 다른 경로가 나오는 것이 숨는 것, 시간·상한으로 멈춘 실행이 끝난 것처럼 보이거나 계산하지 않은 개체가 0점으로 보이는 것, M17·M18·M19 코드·호출 키를 바꿔 기존 결과 재사용이 끝나는 것.

## 결정 (사용자, 2026-10-05)
- **개체 = 부위 하나 × building block**: 후보 풀은 같은 run에 게시된 M17 후보 집합 하나(한 부모의 한 부위에 building block을 붙인 후보, 저장 순서)이며 새 후보를 만들지 않는다. 개체 하나 = 풀의 후보 하나다. 부위 여러 개(슬롯)·교차는 없다.
- **적합도 = qvina 점수 단일 + M17 필터 통과**: 개체의 점수는 그 후보의 단독 M18 자유 도킹 결과의 첫 모드 qvina 점수(kcal/mol)뿐이다. M17 필터(저장값에 서버 평가)를 통과한 후보만 적격이다. 다목적(가중 합·Pareto)은 하지 않는다.
- **작업 하나 = GA 한 번**: 프로토콜 `qvina_ga_dock_v1`(도구 `qvina_ga_design`) 작업 하나가 모든 세대를 돈다. 세대마다 사람 승인을 받지 않는다. 시도는 1회, 이어서 하기 없음.
- **규모 상한**: 세대당 개체 ≤ 24, 세대 ≤ 8, 새 도킹 ≤ 100. 기본 12·5·60.
- **다음 세대 = 이어받음 + 토너먼트 부모의 유사 후보 + 무작위 후보**: 직전 세대의 점수 있는 개체 중 점수가 낮은 `elite_count`개(기본 2)를 다시 도킹하지 않고 이어받고, 새 자리 중 `random_fraction`(기본 0.2) 비율은 아직 뽑히지 않은 적격 후보에서 무작위, 나머지는 토너먼트로 고른 부모와 Morgan 지문(반지름 2, 2048비트) Tanimoto가 큰 미평가 후보 `neighbor_count`개 중 하나다. 교차는 없다.
- **자유 도킹만, 세대별 점수 표만**: 코어 고정·부모 기준 행은 없다. 화면·보고서는 세대별 개체 표와 세대별 최솟값·최댓값(값만)을 보이며 순위·최고·개선·승자·추천 낱말과 개체 간·세대 간 차이·평균 비교를 만들지 않는다.
- **M13 분석 흐름 연동 없음**(M25 몫).
- **예산 = 시작 전 `reserved_units` 예약, 환불 없음**: `reserved_units = min(max_new_dockings, P + (G − 1) × (P − E))`를 시작 때 한 번 예약하고 중간에 멈추거나 재사용이 있어도 돌려주지 않는다. 재사용 개체는 과금하지 않고 `max_new_dockings`에 세지 않는다.
- **시간**: GA 전체 시간 `total_s` 기본 7200초·최대 14400초(수용체 준비 포함), 개체 도킹 한 건 300초 고정(M19 `PER_CANDIDATE_S`).
- **조기 중단**: 그때까지 모든 평가의 점수 최솟값이 `patience`(기본 3) 세대 연속 작아지지 않으면 `no_change`("점수 최솟값 변화 없음")로 끝낸다. 세대 1은 비교 대상이 없고 마지막 세대는 `generations_complete`가 먼저다.
- **seed 둘**: GA seed(`ga.seed`, 후보 선택 난수)와 도킹 seed(`parameters.seed`, qvina 난수)를 따로 입력한다.
- **재현성 = 같은 저장 결과가 있을 때만 같은 결과**: 같은 환경·입력·GA seed·같은 저장 결과(재사용 가능 집합)면 같은 호출 키·같은 요약이다. 재사용 여부는 개체마다(`evaluation: reused | docked`) 기록하고, 저장 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있음을 고정 문장 G3으로 적는다. 시간·상한으로 멈춘 실행의 재현은 약속하지 않는다(G2).
- **사용자가 따로 묻지 않아 선례로 둔 것(명세에 적힘)**: 동점은 풀 순서, 실패한 도킹은 재시도 없이 평가한 것으로 센다, 중간에 멈춘 세대는 평가를 끝낸 개체만 담아 게시, 적격 후보가 개체 수보다 적으면 거절(`ga_pool_too_small`), 부모·유사도 연결은 서버가 검증하지 못한다고 명시(G1), 같은 설정 중복 제출은 `complete`로 끝난 것만 기존 handle을 돌려준다.

## 조율 세션이 정한 것 (실행 중 승인한 세부와 그 결과, 사용자가 최종 확인에서 바꿀 수 있음)
- **새 도킹은 `reserved_units`까지만**(T2 수정 `613a707`, 명세 3·6절 수정): `docking_limit`은 다음 개체가 새 도킹을 필요로 하는데 새 도킹 수가 이미 `reserved_units`(≤ `max_new_dockings`)에 닿았을 때 그 시점에 난다. 예약하지 않은 단위는 쓰지 않는다. 요약 검증은 `new_dockings_used ≤ reserved_units`와 `docking_limit`이면 `new_dockings_used = reserved_units`를 요구한다. 조기 중단 규칙도 명세 3절 4단계(수정본)대로 완료한 세대의 최솟값에서 서버가 다시 계산해 대조한다.
- **가벼운 스테이징, 개체 선택 기록은 서버가 다시 만든다**: 작업 기록(`job["selected"]`, `ligand_ga_selection@1`)에는 풀 후보 id 순서·적격 표시·`pool_sha256`·필터·파라미터·수용체·부모 기록만 넣고 후보마다의 M18 행 선택을 넣지 않는다(착수 확인 C2: 2,000개를 담으면 `job_submitted` 한 줄 ≈ 4.0 MB). 작업 모듈 입력 `ligand_ga_worker_input@1`의 풀 행은 `{index, candidate_id, smiles, eligible, retained_parent_atoms, stereo_flag, input_sha256, reuse_result_bytes}`뿐이다(C1). 개체마다의 `docking_selection@1`은 작업이 끝난 뒤 서버가 평가된 개체에 대해서만 입장 때 한 번 검증한 수용체·부모 기록으로 다시 만든다(`ligand_ga_inputs.individual_selection`, 단독 `docking_bundle.submission`과 같은 값).
- **`prepared.json` 전에 멈춘 작업 모듈은 요약이 없다**: 수용체 준비 실패·준비 중 취소·시간 소진이면 `finish`가 요약을 만들지 않고 작업은 실패한다(작업 모듈 오류 봉투가 있으면 그 이유, 없으면 "GA worker stopped before its first individual". 사용자 취소면 작업 `cancelled`. M19 "첫 행 전" 규칙과 같음).
- **중단된 개체는 목록에 없다**: 도킹 중 취소·시간 소진으로 `<k>.started`만 남은 개체, 출력 총량을 넘겨 저장하지 않은 개체는 세대 기록에 오르지 않으므로 서버 쪽 후보 식별이 없고 요약에 넣지 않는다(멈춘 뒤든 크래시든 같음). 평가를 끝낸 개체는 버리지 않는다.
- **M18·M19 코드에는 덧붙임 두 곳만**: `docking_bundle.producer()`가 `ligand_ga_individual_published` 증거(예약 < 정리 확인 < 개체 게시, 적격 풀 후보)도 게시자로 인정하고 가장 먼저 게시한 쪽을 고르는 규칙을 그대로 둔다. `docking_batch_inputs.published_m18_results`가 같은 이벤트의 handle을 `M18 호출 키 → handle`에 `setdefault`로 더한다(호출 키는 GA 작업 기록과 GA 작업의 M18 pin으로 다시 만든다). 둘 다 GA 이벤트가 없는 run에서는 반환값이 그대로다. `docking_worker.py`·`docking_constants.py`·M17·M19 상수·이유 집합은 바꾸지 않았으므로 M21 뒤에 만든 M18·M19 결과의 재사용이 이어진다.
- **RDKit 지문 예외**: 도킹 작업 환경(`.deps/docking/venv-locked`, RDKit 2026.03.6)에서 도는 `mw/jobs/ligand_ga_worker.py`만 Morgan 지문(`rdFingerprintGenerator.GetMorganGenerator`, 반지름 2, 2048비트, 생성기 기본값 고정) 계산을 위해 RDKit을 직접 import한다. 새 환경은 없다. 그 밖의 계산(수용체 준비·도킹)은 M19처럼 `docking_worker.py`를 파일 경로로 불러 `receptor_inputs`·`receptor_prepared`·`dock_row`로만 한다. 서버 모듈은 RDKit·Meeko·MDAnalysis를 import하지 않고 `qvina2`를 실행하지 않는다. 유사도는 지문 수학 값(정확 분수를 6자리 `ROUND_HALF_UP` 문자열로 저장)이며 점수나 활성이 아니다.
- **GA 전용 사람 한도 증액 경로**: `POST /runs/{id}/ligand/ga/limit_approval` → `ligand_ga_jobs.limit_approval` → `Run.raise_limits`(M19 규칙: 부족분만, 멱등, dry-run·취소 run 거절, `budget_limit_updated` `by: "human"`, 맥락 `purpose: "ligand_ga_limit_raise"`). GA 상수 `RAISE_MARGIN_S` 60, `MAX_RAISE_EXPENSIVE_CALLS` 100, `MAX_RAISE_WALL_CLOCK_S` 15000. M19 라우트에 붙이지 않았다. `Run.raise_limits`를 부르는 함수는 M19와 GA의 `limit_approval` 둘이고 서로를 부르지 않는다(`test_ligand_ga_budget.py`·`test_docking_batch_budget.py` AST).
- **새 이벤트 이름 둘**: `ligand_ga_individual_published {job_id, attempt_id, eval_index, candidate_id, handle}`, `ligand_ga_published {job_id, attempt_id, summary_handle, reused_count}`(`core/events.py` `EventType`에 추가).
- **작업 시간 한도 15000초와 다른 프로토콜의 422 본문**: 이 프로토콜만 `timeout_s`가 `[total_s + 600, 15000]`이고 서버 기본값이 없다(화면은 늘 `total_s + 600`). API `JobSubmit.timeout_s`의 `le`를 7800 → 15000으로 올렸으므로, 다른 프로토콜에서 7800 < `timeout_s` ≤ 15000인 요청은 상태 코드 422는 그대로지만 본문이 요청 모델 오류(`{"detail": {"error": "input_invalid", "message": "invalid job request"}}`)에서 큐의 도구 실패(`{"ok": false, "error": "input_invalid", "message": "invalid job timeout", …}`)로 바뀐다(착수 확인 C3). 15000을 넘으면 예전처럼 요청 모델 오류이고, 이 프로토콜은 그 경우도 닫힌 이유 `invalid_job_arguments`로 바꾼다.

## 검토한 대안
- 새 후보를 GA가 직접 만들기(RDKit 열거·돌연변이 연산자): 후보 생성은 M17 몫이고 열거 규칙·상한·필터를 다시 정해야 한다. 사용자가 게시된 후보 집합 안에서 고르는 쪽을 골랐다.
- 다목적 적합도(점수 + 속성 가중 합, Pareto): 가중치 선택이 "좋음"의 주장이 된다. 단일 점수 + 필터 통과로 했다.
- 세대마다 사람 승인 / 세대마다 작업 하나: 세대 경계마다 예산·승인·게시가 생겨 GA 한 번의 상태(`partial`·`stop_reason`)를 한곳에 둘 수 없다. 작업 하나로 했다.
- 교차(두 부모의 building block 섞기): 개체가 부위 하나 × block이라 섞을 단위가 없다.
- 개체 행 선택 2,000개를 작업 기록에 담기: 이벤트 한 줄 ≈ 4 MB, 작업 상태 읽기마다 그만큼 다시 읽는다. 서버 재구성으로 대신했다.
- M19 증액 라우트를 GA에도 쓰기: 두 프로토콜의 필요량 식·맥락이 섞이고 AST 규칙("한 라우트 → 한 함수")이 흐려진다. GA 전용 라우트·함수를 두었다.
- 지문을 서버에서 계산해 부모·유사도를 검증: 서버 모듈 RDKit 금지 규칙과 충돌한다. 작업 모듈 기록으로 두고 G1에 적었다.
- 순위·최고 개체 표시, 세대 간 최솟값 차이 열: 사용자가 뺐다.

## 결과
- 착수 확인(`docs/qa/m22-ga-20261004/preflight.txt`): 도킹 환경 RDKit Morgan·Tanimoto가 독립 정확 분수 계산·별도 RDKit 설치와 전부 같았다. 적격 2,000개의 행 선택은 수용체 한 번 검증이면 0.68초(표본 40개에서 `submission`과 바이트 동일), 행 선택을 모두 실은 스테이징 5,178,143 B였다. 기본 값 자유 도킹 한 건 35.0–82.9초(6건 평균 71.4초), 새 도킹 100건 ≈ 7,140초(기본 `total_s` 7200을 넘을 수 있음), 기본 설정(예약 52) ≈ 3,710초. 최악 요약(8세대 × 24) 74,646 B. 15000초는 두 곳(API `le=7800`, 큐 프로토콜별 상한)에서 거절되어 이 프로토콜만 넓혔다.
- 기본 run 예산(활동 1800초, 비싼 계산 8회)으로는 기본 설정 GA(예약 52, 필요 7800초)가 입장에서 429 `ga_limit_raise_required`가 되므로 화면이 부족분과 증액 승인 버튼을 먼저 보인다. 기본 설정에서도 `full_run_may_be_partial`(예약 × 300 > `total_s`)이 참이므로 화면 문구는 "끝까지 못 갈 수 있음"이며 "부분 완료"가 아니다(C4).
- GA가 도는 동안(최대 15000초) run 실행 잠금과 전역 작업 슬롯을 쥐어 같은 run의 다른 계산·보고서와 다른 run의 비싼 작업이 기다린다. 화면이 시작 전에 이를 안내한다.
- 하지 않게 된 것: 새 후보 생성, 부위 여러 개, 교차, 다목적, 코어 고정·부모 기준 행, 이어서 하기, 실행 간 개체 합치기, 세대마다 승인, M13 연동, 뷰어 표시, 점수 파생값(차이·순위·최고·개선·평균 비교), 외부 요청.
- 규칙 전체: `docs/business-rules.md` "리간드 GA 설계 (M22, `qvina_ga_dock_v1`)". API: `docs/contracts.md` "M22 리간드 GA 설계". 완료 기록: `docs/tracking/m22-acceptance.md`.
