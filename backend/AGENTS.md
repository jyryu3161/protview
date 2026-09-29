# backend/ — FastAPI 서버와 과학 런타임 (`mw` 패키지)

## 담당 범위
- HTTP API(`mw/api/app.py`), 실행 경로 `Run.call`(`mw/runtime/`), 불변 객체·이벤트(`mw/core/`), 과학 도구(`mw/tools/`), 영속 작업 큐와 작업 프로세스 감독(`mw/jobs/`), 외부 요청 게이트(`mw/egress/`, `mw/llm/`), 보고서(`mw/*reports.py`), 뷰어 의도·저장된 보기(`mw/viewer_intents.py`, `mw/saved_scenes.py`), M11 화학 입력·번들·결과(`mw/chemical_*.py`), M12 포켓 투영·출력 파서·번들·보고서(`mw/pocket_*.py`, `mw/jobs/pocket_worker.py`), 고정 파이프라인(`mw/workflows.py`), M13 분석 흐름의 템플릿·계획(`mw/analysis_plans.py`)과 실행 driver(`mw/analysis_executions.py`).
- 테스트: `backend/tests/`. fixture는 `backend/tests/fixtures/`에 있다. `chemical/`에는 출처(`PROVENANCE.json`, `SYNTHETIC-PROVENANCE.md`)와 라이선스가 함께 있다. 새 fixture는 공개·합성·파생 여부와 출처를 같은 방식으로 기록한다.

## 담당하지 않는 것
- 화면, Mol* 렌더링, 브라우저 적용 확인: `frontend/`가 담당한다. 백엔드는 브라우저가 보낸 좌표로 측정하지 않고, 브라우저가 보낸 ack를 과학 사실로 취급하지 않는다.
- 단계 기록과 과거 검증: `scripts/`, `phases/`가 담당한다. `mw`는 이것들을 import하지 않는다.
- ProLIF/RDKit/MDAnalysis 코드: `.deps/prolif/venv-locked` 인터프리터에서 도는 `mw/jobs/chemical_worker.py`에만 둔다. 서버 프로세스 모듈에서 이 패키지들을 import하면 안 된다.
- fpocket 실행: `mw/jobs/pocket_worker.py`만 한다(guardian GO 뒤, 고정 argv, 해시 확인한 실행 파일 복사본, 허용 목록 환경, 시도별 상대 TMPDIR). 서버 쪽 capability 확인은 fpocket을 실행하지 않고 해시만 본다. `mw/pocket_output.py`는 표준 라이브러리만 쓴다(작업 프로세스에서도 import).
- 건드리지 말 것: `molecular_workspace.egg-info/`(생성물), `backend/tests/offscreen_agent_fixture/`(M8 QA 전용 fixture 서버).

## 불변 조건
- `core/`는 다른 `mw` 하위 패키지를 import하지 않는다.
- 객체 저장 순서는 객체 파일 기록 → 전체 payload를 담은 `object_created` 이벤트 추가·fsync → SQLite 색인 갱신이다. 색인은 지워도 되고, `events.jsonl`에서 다시 만들 수 있어야 한다.
- handle은 `sha256(kind, schema, canonical raw)`다. 시각, 호출 ID, 요청 UUID는 내용 해시에 넣지 않는다.
- 과학 계산은 `Run.call` 또는 `JobQueue`로만 실행한다. 라우트 함수가 `tools/`의 계산 함수를 직접 부르면 안 된다. 읽기 라우트는 도구·작업·외부 요청을 실행하지 않는다.
- run을 바꾸는 호출은 `execution.lock`을 잡은 상태에서 이벤트를 다시 읽고 판단한다. 취소·종료 전이는 `transitions.lock`만 쓰고, 긴 실행 잠금을 기다리지 않는다.
- 비싼 계산 예약은 실제 프로세스를 띄우기 직전에 한 번만 한다. `Run.call`과 큐가 같은 시도를 이중 과금하면 안 된다. 예약 뒤의 실패·취소·시간 초과는 환불하지 않는다.
- 작업 프로세스는 guardian의 HELLO/GO 핸드셰이크를 마친 뒤에만 과학 작업을 시작한다. 프로세스 신원은 `jobs/process_identity.py`의 `psutil_raw_start_v1` 레코드로만 판단한다. 공개 `create_time`, PID, PGID 정수만으로 신호를 보내면 안 된다.
- 모든 HTTP 요청은 가장 바깥 미들웨어에서 Host 허용 목록(`127.0.0.1`·`localhost`·`[::1]`, 포트 선택)을 통과해야 한다. 테스트 클라이언트는 `base_url="http://127.0.0.1"`로 만든다.
- 작업 상태 읽기(`JobQueue.get`/`list`)는 `transitions.lock`을 잡거나 SQLite 색인을 다시 쓰지 않는다. 색인은 쓰는 쪽과 `claim_next`가 다시 만든다.
- 외부 HTTP는 `egress/gate.py`의 `EgressGate`만 보낸다. `follow_redirects=False`, `trust_env=False`, 목적지 1개 고정, 요청당 HTTP 1회를 지킨다. local_only/dry_run에서는 키를 읽지 않는다.
- 새 run은 `NewRun.egress`가 `Literal["local_only"]`이므로 항상 로컬 전용이다. 온라인 전환은 `/viewer/online` 이벤트로만 한다.
- 잔기 식별자 7필드와 AtomRef의 null label은 그대로 보존한다. 표시 문자열을 파싱해서 식별자를 만들지 않는다.
- 포켓 결과를 게시하기 전에 현재 시도·취소·종료 상태를 확인하고, 읽을 때마다 보관한 원본 출력을 다시 파싱해 저장 값과 대조한다. 원본 출력 보관량은 게시된 결과 기준 run당 64 MiB다.
- M13 분석 흐름: 계획 생성은 저장된 메타데이터·capability·읽기 전용 사전 검사만 쓰고 과학 구현·작업·보고서를 부르지 않는다. 실행은 `Run.call`·`JobQueue`·기존 보고서 함수에 `ExecutionLink`를 넘겨서만 하며, 링크는 서버 코드만 만든다(`checked_link`가 다른 타입을 거부). 같은 run의 워크플로 잠금(`analysis.lock`)은 입장·dispatch 기록·결과 기록 같은 짧은 전이에만 잡고 자식 실행 동안에는 놓는다. 실행별 driver 잠금이 advance·retry 전체 동안 한 실행에 driver 연산 하나만 들이고(동시 요청은 409 `busy`), 잠금 순서는 driver → 워크플로 → `Run._transition()`이다. 링크 콜백은 `Run._transition()` 안에서 돌며 잠금을 잡지 않는다. 단계 결과는 반환값이 아니라 연결된 자식 이벤트에서 조정해 얻는다(정상 경로와 충돌 복구가 같은 코드). 중지·철회는 `busy`로 거절하지 않고 `Run.cancel()`을 쓰지 않는다. 읽기(상세·목록·요약)는 이벤트를 쓰지 않는다.
- 연결 필드가 없는 `Run.call`·작업·보고서의 이벤트는 바이트 그대로다(`link_fields(None)`은 빈 dict). 연결된 호출은 제안 전에 활동 시간 예산·열린 작업을 먼저 확인한다(풀린 호출이 가드를 올리지 않게). 흐름이 소유한 작업은 소유 실행이 끝나기 전에는 연결 없는 `start`·`retry`를 거절한다(412 `job_owned_by_analysis_execution`. API가 `owner_active` 콜백으로 `analysis_executions.execution_active`를 넘기고, 콜백이 없으면 거절). 소유 실행이 끝나면 기존 규칙대로 허용한다. 수동 `cancel`은 허용한다.
- 도구 실패는 `ToolFailure(FailureClass.…)`로 던진다. 그 밖의 예외는 fatal로 분류한다. HTTP 매핑은 input_invalid 422, precondition 412, resource_exceeded 429, transient·fatal 503이다.

## 구현 패턴
- 새 도구: `config/tools.yaml` 명세 + `tools/<name>.py`의 `register(reg)` 함수 안에서 `reg.register("<tool>")`로 구현 연결 + 새 모듈이면 `workspace.py`의 `build_registry()`에서 `<module>.register(reg)` 호출 + `api/app.py`의 `SUPPORTED_TOOLS`. 결과는 `ObjectStore.put(kind, schema, content)`로 저장하고, 결과 dict에 method·version·unit·limitations를 넣는다.
- 새 비싼 프로토콜: `jobs/queue.py`의 코드 소유 dispatch 표에 고정 모듈 진입점을 등록한다. 입력은 개인 입력 파일의 제한된 JSON으로, 출력은 스키마·작업 ID·시도 ID·유한값을 검증한 뒤 저장한다. 테스트용 작업 프로세스는 내부 생성자로만 주입하고, 요청 필드로는 선택할 수 없게 한다.
- 새 보고서: 고정된 템플릿 statement ID + `(source_handle, field_path, row_selector, unit, exact_value, rendered_value)` 증거 구조를 쓴다. 파생값은 count, count_distinct, minimum, 종류별 개수만 허용한다.
- 멱등 요청: 클라이언트 UUID + 정규화한 본문 해시로 판단하고, 입장 처리는 `run._transition()` 안에서 짧게 한다.
- 오류 메시지는 안전한 enum과 고정 문장으로 만든다. provider 응답 본문, 예외 문자열, 헤더를 외부로 향하는 필드나 이벤트에 넣지 않는다.

## 테스트 지침
- 파일별 초점: `test_core`(해시·이벤트·복구), `test_structural`(파싱·전처리·접촉), `test_api`, `test_runtime`(재시도·가드·예산·dry-run·잠금), `test_llm_egress`(투영·전송 거부·감사·사용량), `test_jobs`(큐·실제 프로세스 수명·신원·취소), `test_reports`, `test_sasa`, `test_openmm`, `test_agent_viewer`, `test_saved_scenes`, `test_comparison`, `test_chemical_interactions`, `test_m11_job_api`, `test_pockets`(투영), `test_pocket_output`(파서·실제 엔진), `test_pocket_jobs`(작업·API·수명 주기·복구), `test_pocket_reports`, `test_execution_links`(`Run.call`·작업·보고서의 연결 필드, 연결 없는 이벤트 불변, 범위 한정 중지, 시도 훅), `test_analysis_workflows`(템플릿·계획·한도, dry-run 과학 호출 0회, 두 승인 분리, 멱등·stale revision·busy, 충돌 구간 1–4 결함 주입과 복구, 중지·철회, 재시도·한도·재시도 불가 분류, 공유 작업, 예산 checkpoint, events-only 복구, 실제 FreeSASA·OpenMM·ProLIF·fpocket 경로).
- 반드시 다룰 경계: null label, 삽입 코드, 여러 글자 체인, 첫 모델이 아닌 모델, altloc(A가 이기지 않는 경우 포함), 같은 이름의 리간드 인스턴스, 중복 원자 이름·serial, scientific_null, NaN·Infinity 입력, 다른 run의 handle, 손상된 payload.
- events-only 복구: 임시 run에서 업로드·객체·SQLite를 지우고 복구한 바이트를 비교한다. 엔진이나 모델 없이 다시 열려야 한다.
- 분석 흐름 충돌 복구 테스트는 `analysis_executions._FAULT_HOOK`(테스트 전용 결함 주입)으로 입장 → 자식 → 성공 → 워크플로 이벤트 경계마다 멈춰 본다. 물리 작업 반복, 새 캐시 제안, 가드 증가, 보고서 재작성이 없어야 한다.
- 외부 요청 테스트는 주입한 transport로 실제 transport 호출 수를 센다. sentinel 키가 모든 산출물에 나오지 않는지 검사한다. 실제 `.env`를 읽지 않는다.
- 프로세스 테스트는 실제 하위 프로세스(SIGTERM을 무시하는 손자 프로세스 포함)를 쓰고, finally에서 반드시 정리한다.
- FreeSASA·OpenMM·ProLIF·fpocket 네이티브 테스트는 엔진이 없을 때 성공으로 skip하면 안 된다. 수치 oracle은 해석해나 독립 계산을 쓴다. 같은 함수와 비교하는 것은 oracle이 아니다.
- 실행: `.venv/bin/python -m pytest backend/tests -q`, `.venv/bin/python -m ruff check backend/mw backend/tests`(한 줄 120자).
