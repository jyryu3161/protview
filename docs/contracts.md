# 외부 인터페이스 계약

ProtView의 외부 인터페이스는 loopback HTTP API(`http://127.0.0.1:8000`, 프런트엔드에서는 `/api` 접두사) 하나다. 이 API를 쓰는 쪽은 번들된 프런트엔드, 오프스크린 QA 스크립트, 로컬 스크립트다. 인증은 없다. loopback 바인딩과 "한 인스턴스를 한 사람만 쓴다"는 전제가 접근 통제를 대신한다.

## 공통 규칙

- **식별자 형식**: run ID는 `run_<32자리 hex>`, handle은 `obj://<run_id>/<kind>/<sha256>`, 업로드 ID는 `upload://<run_id>/<sha256>.<pdb|cif|mmcif>`. 다른 run의 handle이나 업로드 ID를 넘기면 `input_invalid`(422) 또는 `not_found`(404)다.
- **handle envelope**: 과학 결과는 `{handle, kind, schema, summary, preview(최대 5행), produced_by, null_result}`로 돌려준다. preview는 전체 결과가 아니다. 전체 행은 `GET /runs/{id}/objects?handle=…`(페이지·열 선택 가능)로 읽는다.
- **scientific_null**: `null_result=true`인 성공 응답(200/201)이다. 오류가 아니다.
- **단위**: 거리·RMSD·cutoff는 Å(`_A` 접미사), 면적은 Å², OpenMM 에너지는 kJ/mol, 각도는 도(°). 숫자는 반올림하지 않은 원래 값이다.
- **오류 본문은 세 가지 형태다.**
  - 도구 실패: `{"ok": false, "error": <분류>, "message": <문장>, "fix": <제안 또는 null>, "detail": <구조화 정보>}`. `fix`는 제안일 뿐이며, 서버가 그 내용을 자동으로 실행하지 않는다.
  - HTTP 경계 오류(형식·크기·경로·not_found·run_corrupt 등): `{"detail": {"error": <코드>, "message": <문장>}}`.
  - 승인·가드: `{"ok": false, "approval": {gate, tool, reason}}` 또는 `{"ok": false, "loop_stop": {reason, …}}`. `error` 필드가 없으므로 키로 구분한다.

| 상태 코드 | 의미 |
|---|---|
| 200 / 201 | 성공(scientific_null 포함) |
| 400 | run ID 형식 오류, 경로 오류, 잘못된 Content-Length |
| 404 | 이 run에 없는 handle/job |
| 409 | `approval`(비싼 계산 승인 필요), `loop_stop`(자율 분기 가드), `cancelled`, `run_corrupt`(이벤트·payload 손상), `upload_conflict`, 멱등 요청 UUID 충돌, 뷰어 `stale_scene`·`stale_revision`(세션·세대·revision 불일치), 작업 시작의 `global_concurrency_busy`·`global_job_cleanup_pending`·`global_job_ledger_unavailable`(전역 heavy-worker 게이트), 분석 흐름의 `stale_revision`·`request_id_conflict`·`busy` |
| 412 | `precondition`(선행 조건 부족, 예: 리간드 선택 필요, 승인할 작업 없음), 분석 흐름의 상태 거절(`plan_blocked`, `dry_run_plan_only` 등) |
| 413 | 본문 크기 초과(`resource_exceeded`) |
| 415 | M11 가져오기에 `application/octet-stream`이 아닌 본문 |
| 422 | `input_invalid`, `report_evidence_invalid`, `method_evidence_invalid`, `scene_invalid` |
| 429 | 도구의 `resource_exceeded`(예산·한도 소진, 저장 보기·그림 개수 초과) |
| 503 | 도구의 `transient` 또는 `fatal` |

- **멱등성**: 뷰어 의도·저장 보기·그림 생성은 클라이언트 요청 UUID를 받는다. UUID와 정규화한 본문이 같으면 같은 결과를 돌려주고 다시 실행하지 않는다. UUID가 같은데 본문이 다르면 409다.
- **목록**: `offset`/`limit` 페이지 단위다. 기본·최대 개수는 호출마다 다르다: 객체 행·저장 보기·그림·화학 결과 행 50/100, 원자 카탈로그 100/500, 화학 원자 목록 100/1000, 이벤트 200/500.
- **다운로드**: 파일 이름은 서버가 handle 앞부분으로 만든다(`protview-figure-<prefix>.png` 등). 저장된 산출물은 다시 받아도 같은 바이트다.

## run과 입력

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs` | `{goal?, context?, dry_run?: bool, egress?: "local_only"}`. egress에는 `local_only`만 넣을 수 있다 | 201, run 요약 | 422 |
| `GET /runs`, `GET /runs/{id}` | — | run 요약 목록/단건 | 400, 404 |
| `POST /runs/{id}/uploads?filename=x.pdb` | 원본 바이트(최대 25 MiB), 확장자 `.pdb/.cif/.mmcif` | 201, `{upload_id, sha256, size, …모델·체인 요약}` | 413, 422(형식·파싱), 409(같은 해시인데 다른 내용) |
| `POST /runs/{id}/commands` | `{tool, args, decided_by?: "human"|"rule"}`. tool은 `load_structure`, `prepare_structure`, `compute_interactions`, `compute_interface_sasa`, `measure_distance`, `align_structures`, `compile_state`, `map_residue_numbering`(M15), `annotate_reference_sites`(M16) 중 하나 | 200, `{ok: true, handle: <envelope>}` | 도구 실패 본문(422/412/429/503), 409 |
| `POST /runs/{id}/inspect_complex` | 업로드 ID 또는 같은 run의 구조 handle, 모델, 전처리 정책, 선택적 리간드, cutoff | 완료된 handle 목록 또는 `needs_selection`/`no_ligand` | 412, 422, 409 |

`load_structure`의 `source`는 이 run의 업로드 ID여야 한다. 파일 경로나 URL은 받지 않는다. `decided_by`는 기록용 출처 정보일 뿐이며, 승인 권한을 주지 않는다.

## 읽기

| 호출 | 설명 |
|---|---|
| `GET /capabilities` | 모드, 에너지 프로토콜 표, `methods.{interface_sasa, openmm_protein_minimize, chemical_interactions, pocket_detection, analysis_workflows, residue_numbering, reference_site_annotation}` 사용 가능 여부와 이유, 지원·미지원 기능 목록. 무거운 엔진을 import하지 않는다 |
| `GET /tools?levels=L2,L4` | 노출된 도구 명세. `L3`을 넣으면 OpenMM 작업 프로토콜이 `execution_lane: durable_job`으로 추가된다 |
| `GET /runs/{id}/objects?handle=…`, `/objects/meta` | 객체 내용(페이지·열 선택)과 메타 |
| `GET /runs/{id}/structures/bytes?handle=…` | 뷰어용 구조 원본 바이트. 로컬 뷰어 전용 |
| `GET /runs/{id}/structures/residues`, `/structures/atoms` | 잔기 목록, AtomRef 원자 카탈로그(페이지) |
| `GET /runs/{id}/interface_sasa`, `/openmm_minimization`, `/objects/measurement` | 방법 결과를 검증해서 읽는다(검증 실패 시 422 `method_evidence_invalid`) |
| `GET /runs/{id}/events`, `/budget` | 이벤트 스트림, 예산 한도·사용량 |

읽기 호출은 과학 도구, 작업, 외부 요청을 실행하지 않는다.

## 보고서

| 호출 | 입력 | 출력 |
|---|---|---|
| `POST /runs/{id}/reports` | `{interaction_handle}` | 201, `report_manifest@1` handle |
| `POST /runs/{id}/method_reports` | SASA·OpenMM·거리·정렬·화학·포켓·번호 대응·참조 주석 결과 handle | 201, 방법 보고서 handle |
| `GET /runs/{id}/reports` | — | 저장된 보고서 목록 |
| `GET /runs/{id}/reports/selected?handle=…` | — | 보고서 manifest |
| `GET /runs/{id}/reports/download?handle=…&format=markdown|json` | — | UTF-8 Markdown 또는 JSON 파일 |

증거 검증에 실패하면 422 `report_evidence_invalid`다. 보고서 생성은 외부 요청을 하지 않는다.

## 비싼 계산 작업

순서(실제 UI 흐름):
1. (OpenMM만) `GET /jobs/preflight?structure=<handle>`: 입력 적합성, 제외 항목, 필요한 확인.
2. `POST /jobs`: `{protocol_id, args, timeout_s?}`(timeout_s 기본 60, 0 초과 900 이하, 다른 필드는 거부). 본문은 최대 512 KiB. 실행 파일·경로·환경변수는 받지 않는다. 200으로 queued 작업을 돌려주고, dry-run run이면 계획만 돌려준다. 형식 오류는 422다.
3. `POST /jobs/{job_id}/start`: run에서 첫 비싼 계산이면 409 `{"ok": false, "approval": {gate: "expensive_first_call", tool, reason}}`를 돌려주고 승인 요청을 기록한다.
4. `POST /jobs/approve`: 대기 중인 승인 요청이 있고 해당 도구의 queued 작업이 있을 때만 승인을 기록한다. 없으면 412다.
5. `POST /jobs/{job_id}/start`를 다시 부른다. 전역 heavy-worker 게이트에 걸리면 409와 reason_code를 돌려준다.
6. `GET /jobs/{job_id}`, `GET /jobs`로 상태를 확인한다.

- 상태: `queued`, `running`(정리 대기 표시 포함), `done`, `failed`, `cancelled`, `interrupted`. done이 아닌 상태에는 결과 수치가 없다.
- `POST /jobs/{job_id}/cancel`은 여러 번 불러도 안전하다. 이미 종료된 작업이면 `already_terminal`을 돌려준다.
- `POST /jobs/{job_id}/retry`는 새 시도이며, 비싼 계산 1단위와 root 재시도 허용량을 새로 쓴다.
- OpenMM(`openmm_protein_minimize`)은 args에 `selection_policy: "protein_only"`, `hydrogen_policy: "rebuild_pH7"`가 필수다.
- 실패·취소·중단된 OpenMM 시도에도 준비된 입력 handle이 남을 수 있다. 에너지 결과는 없다.

## 뷰어

| 호출 | 입력 | 출력·제약 |
|---|---|---|
| `POST /runs/{id}/viewer/sessions` | `{client_instance_id, scene_generation, structure_handle, representation?, scope_chain_auth?, scope_target?, selected_target?}` | 201, 세션 ID, 대상 카탈로그 해시 |
| `GET /viewer/sessions/{sid}` | — | 세션 상태 |
| `POST /viewer/sessions/{sid}/state` | `{representation, selected_alias, action_revision}` | 세션 상태 갱신. action_revision은 증가해야 한다(아니면 409 `stale_revision`) |
| `GET/POST /runs/{id}/viewer/online` | `{enabled: bool}` | 실제 적용된 모드와 뷰어 동의 상태. 자격 증명·설정이 없으면 unavailable |
| `POST /runs/{id}/viewer/intents` | `{client_instance_id, viewer_session_id, scene_generation, request_id, prompt}`. ID는 v4 UUID. prompt는 자연어이거나 로컬 명령(`/representation surface`, `/focus <대상>`, `/clear`, `/zoom in`, `/zoom out`, `/reset`) | 201, 저장된 계획. 명령 최대 3개, source는 `local_command` 또는 모델 |
| `GET /viewer/intents`, `/intents/{iid}` | — | 기록과 상태. 읽을 때 모델 요청을 하지 않는다 |
| `POST /viewer/intents/{iid}/cancel` | `{client_instance_id, viewer_session_id, scene_generation}` | 이 의도만 취소한다. 작업이나 승인에는 영향이 없다 |
| `POST /viewer/intents/{iid}/ack` | `{command_id, status: applied|no_change|failed, reason_code?, client_instance_id, viewer_session_id, scene_generation, action_revision}` | 발행한 계획·세션과 정확히 맞아야 한다 |
| `POST/GET /runs/{id}/viewer/scenes`, `/scenes/selected` | `viewer_scene@1` 또는 M16 `viewer_scene@2` 저장 요청과 현재 바인딩(본문 최대 64 KiB) | 201, 보기 handle. 바인딩이 오래됐으면 거부, run당 100개. 목록·상세는 @1과 @2를 모두 돌려준다 |
| `POST/GET /runs/{id}/viewer/figures`, `/figures/selected`, `/figures/download?format=png|json` | 저장된 보기 handle, PNG(최대 8 MiB). schema `viewer_figure@1` 또는 M16 `viewer_figure@2` | 201, 그림 handle. run당 100개, PNG 총 64 MiB. 목록·상세·다운로드는 @1과 @2를 모두 받는다(출처 JSON은 저장된 그림 값 그대로) |

모든 뷰어 요청 모델은 알 수 없는 필드를 거부한다.

의도 상태: requested, interpreting, planned, applying, applied, partial, no_change, clarification, unsupported, rejected, cancelled, failed, detached. `applied`는 브라우저 확인이 온 뒤에만 표시한다.

## M11 화학 (버전 1)

- `POST /runs/{id}/chemical/imports?kind=receptor|ligand_sdf|receptor_bonds&filename=…`: `application/octet-stream` 본문, 최대 10 MiB. 201로 `{schema: "chemical_raw_input@1", handle, kind, format, sha256, size}`를 돌려준다. 리간드는 V2000 SDF만 받고, V3000은 형식 오류로 거부한다.
- `GET /chemical/imports/inspect`, `/chemical/imports/atoms`, `POST /chemical/preview`, `GET /chemical/prerequisites`: 가져온 입력 확인, 원자 목록, 제출 전 미리보기와 부족한 조건.
- 화학 준비와 ProLIF 계산은 위의 작업 경로로 실행한다(`prepare_chemical_structure`, `compute_chemical_interactions`).
- `GET /chemical/structures/view`, `/chemical/structures/atoms`, `/chemical/graphs`, `/chemical/preparation-manifests`, `/chemical/results`, `/chemical/results/rows`: 결과 읽기.
- 화학 요청 본문은 최대 512 KiB다.

## M12 포켓 후보

- `GET /runs/{id}/pockets/preflight?structure=<handle>&chains=A&chains=B`(체인은 파라미터를 반복해서 준다. 빼면 단백질 잔기가 있는 모든 체인): 도구·작업을 실행하지 않는 입력 확인. 사용 가능 여부, 체인 목록, 범주별 제외 개수, 투영 원자·잔기 수, 잔기 이름 대응 예정 목록, 거부 사유(`reject.reason_code`와 식별자), 방법·한도·결정성 한계, capability, run의 원본 출력 보관 잔량, 예산 스냅숏.
- 계산은 비싼 작업 경로로 한다: `POST /jobs` `{protocol_id: "fpocket_detect_v1", args: {structure, chains}, timeout_s}`. 다른 인자는 거부하고, 이 프로토콜의 `timeout_s` 상한은 120이다(화면은 120을 보낸다). 승인·예산·취소·재시도는 공통 작업 규칙과 같다. `detect_pockets`는 작업 전용 도구라 `/commands`로는 실행되지 않는다.
- `GET /runs/{id}/pockets?offset&limit`(limit 최대 100): 이 run의 pocket_set 목록(소스, 소스 종류, 체인, 총 개수, null_result, 작업 ID, 생성 순번, total).
- `GET /runs/{id}/pockets/result?handle=`: 검증된 요약(방법, 총 개수, 포켓별 rank·기술자 5개·주변 잔기 수·표시 중심). 구·원자 전체는 없다.
- `GET /runs/{id}/pockets/geometry?handle=&rank=`: 그 포켓의 알파 구 전체(`x_A, y_A, z_A, radius_A`)와 주변 AtomRef·잔기 전체. 없는 rank는 404.
- 읽기 검증 실패는 422 `method_evidence_invalid`. 읽기는 fpocket을 실행하지 않는다.
- 보고서: `POST /runs/{id}/method_reports` `{result_handle: <pocket_set>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "pocket_detection"`, `result_schema: "pocket_set@1"`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다.
- `/capabilities`의 `methods.pocket_detection.status`: `ready` | `not_installed` | `unreviewed_build` | `handshake_failed` | `unsupported_platform`, 사유 문장과 엔진·build 정보.

## M13 분석 흐름

모든 경로는 `/runs/{id}/analysis/...`이고 same-run handle만 받는다. 요청 모델은 알 수 없는 필드를 거부한다(strict). `request_id`는 UUID, `expected_revision`은 정수이며, 형식이 틀리면 422 `input_invalid`다. 본문은 계획 생성 1 MiB, 그 밖 64 KiB 이하(넘으면 413 `resource_exceeded`). 오류는 도구 실패 형태 `{"ok": false, "error": <코드>, "message", "fix": null, "detail": {...}}`이고, 기록 손상은 HTTP 경계 형태 409 `run_corrupt`다.

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /analysis/templates` | — | `analysis_templates@1`: 템플릿 6개(필수 입력·단계 설명·사용 가능 여부와 이유), `natural_language_planning`, `limits` | 404 |
| `POST /analysis/plans` | `{request_id, goal, inputs}` | 201, `{handle, plan, plan_sha256, executable, ordinal, replayed}`. 같은 내용이면 같은 handle | 422, 429(`plan_too_large` 1 MiB, `plan_limit` 100개), 409 `request_id_conflict` |
| `GET /analysis/plans` | — | `analysis_plan_list@1`: `{total, rows:[{handle, goal, ordinal, created_seq, executable}]}`(최대 100) | — |
| `GET /analysis/plans/detail?handle=` | — | `{handle, plan, plan_sha256, executable, ordinal}` | 422 |
| `POST /analysis/executions` | `{request_id, plan_handle}` | 201 envelope. 일반 run은 `awaiting_approval`, dry-run run은 `plan_only` | 422(모르는·다른 run·계획이 아닌 handle), 412 `plan_blocked`(`detail.codes`), 429 `execution_limit`(run당 100), 409 |
| `GET /analysis/executions` | — | `analysis_execution_list@1`: `{total, rows:[{execution_id, plan_handle, goal, status, revision, created_seq, dry_run, current_step, summary_handle, error}]}`. `total`은 만든 개수, 행은 최대 100. 손상된 실행은 `error: {code: "execution_record_invalid", message}` 행 | — |
| `GET /analysis/executions/{eid}` | — | 실행 기록 `analysis_execution@1` | 404, 409 `run_corrupt` |
| `POST …/{eid}/approve` | `{request_id, expected_revision, plan_hash}` | 200 envelope. 호환성이 바뀌었으면 200과 `status: blocked`, `blocked_reason.reason_code: compatibility_changed` | 412 `dry_run_plan_only`·`not_awaiting_approval`·`plan_hash_mismatch` |
| `POST …/{eid}/revoke` | `{request_id, expected_revision}` | 자식 시작 전이면 `awaiting_approval`, 뒤면 `cancelled`(소유 작업 범위 한정 취소) | 412 `dry_run_plan_only`·`execution_terminal`·`not_approved` |
| `POST …/{eid}/advance` | `{request_id, expected_revision}` | 조정 뒤 최대 한 단계 또는 작업 전이 하나 | 409 `busy`, 412 `dry_run_plan_only`·`plan_not_approved`·`retry_or_stop_required`(`detail.retryable_step`) |
| `POST …/{eid}/retry` | `{request_id, expected_revision, step_id}` | `step_id`가 `retryable_step`일 때만 그 단계의 새 시도 | 409 `busy`, 412 `retry_not_allowed`·`dry_run_plan_only` |
| `POST …/{eid}/cancel` | `{request_id, expected_revision}` | 이 실행만 중지(`plan_only` 포함). 이미 종료면 outcome `already_terminal`. `busy`로 거절하지 않음 | — |
| `POST …/{eid}/scientific-approval` | `{request_id, expected_revision}` | 이 실행의 대기 중 작업 게이트에만 `/jobs/approve`와 같은 규칙으로 승인 기록 | 412 `no_pending_scientific_approval`·`dry_run_plan_only` |
| `GET …/{eid}/summary[?download=json]` | — | `{handle, summary}`(`workflow_summary@1`). `download=json`이면 저장 바이트 그대로 첨부(`protview-workflow-summary-<id>.json`) | 404(완료 실행만) |

- 실행 `POST`는 모두 409 `stale_revision`(`detail`에 현재 revision)이나 409 `request_id_conflict`를 돌려줄 수 있다. 모든 변경 요청이 판단 전에 복구 조정을 하므로 412·409로 거절된 요청도 revision을 올릴 수 있다. 클라이언트는 거절 뒤 항상 기록을 다시 읽는다. 단계가 도는 동안에도 시도 이벤트로 revision이 오르므로, 중지는 `stale_revision`이면 다시 읽고 한 번 더 보낸다.
- 충돌 직후 첫 advance·retry는 중단 기록을 먼저 남기고 412를 돌려줄 수 있다. 읽기(GET)는 짧은 잠금을 잠깐 기다릴 수 있지만 과학 실행 중에는 잡지 않으며, 이벤트를 쓰지 않는다.
- **envelope**: `{execution: <실행 기록>, replayed: bool, request: {request_id, action, state: "completed"|"pending", outcome}}`. outcome은 advance·retry에서 `advanced`, `run_busy`, `no_op_<status>`, `retry_or_stop_required`, `retry_not_allowed`, `resource_exceeded`, `blocked`, 그 밖에서 `created`, `approved`, `revoked`, `cancelled`, `already_terminal`, `interrupted`.
- **실행 기록 `analysis_execution@1`**: `execution_id`(`exec_` + 32 hex), `run_id`, `plan_handle`, `plan_sha256`, `goal`, `template_version`, `source`, `planner`, `dry_run`, `status`, `retryable_step`, `revision`, `created_seq`, `current_step`, `plan_approval{approved, event_seq, plan_sha256, revocations}`, `scientific_approval{required, run_approved, state: not_required|already_approved_in_run|pending|not_yet_requested, pending_tool, recorded_seqs}`, `blocked_reason{reason_code, message, step_id, detail}|null`(`compatibility_changed`, `identity_changed`, `recovery_error`, `step_input_invalid`, `step_precondition`, `report_evidence_invalid`, `analysis_dispatch_mismatch`, `binding_unavailable`, `binding_type_mismatch`), `stop{seq, reason: stop|revoke}|null`, `notice{code, step_id, message}|null`(`run_budget_exhausted`, `run_busy`, `not_started`, `scientific_approval_required`, `global_concurrency_busy` 등), `driver{in_progress, request_ids}`, `recovery_pending`, `steps`, `physical_attempts`, `active_wall_s`, `limits`, `summary_handle`, `event_seqs`, `jobs_readable`.
- **단계**: `step_id`, `operation`, `lane`, `status`, `null_result`(completed만), `operation_id`, `dispatch_seqs`, `completed_seq`, `attempts`, `retries_used`, `outputs{이름: handle}`, `report_handle`, `child_call_ids`, `job_id`, `job_ownership`(`owned`|`observed_shared`), `job_status`, `job_cleanup_status`, `job_blocked_reason`, `job_cancel_requested`, `shared_job_notice`, `deferred_reason`, `failure{status, error, reason_code, message, retryable}|null`. 실패 reason_code에는 `transient_exhausted`, `interrupted`, `job_failed`, `job_timeout`, `job_interrupted`, `job_cancelled`, `shared_job_failed`, `run_cancelled`, `loop_guard_<이유>`, `max_physical_attempts`, `max_active_wall`이 있다. 캐시로 끝난 단계는 `attempts`가 0일 수 있다.
- **요약 `workflow_summary@1`**: `schema`, `plan_handle`, `plan_hash`, `execution_id`, `goal`, `source`, `approval_event_seq`, `first_event_seq`, `last_event_seq`(마지막 단계 완료 이벤트), `steps:[{step_id, operation, status, null_result, output_handles, report_handle, child_call_ids, job_ids, job_ownership, attempts}]`, `physical_attempts`, `note`. 과학 수치는 없다.
- **계획 입력 참조**: 단계 `params`의 값이 `{"input_ref": <이름>}`이거나 `params` 전체가 `{"input_ref": <이름>}`이면 `plan.inputs`의 그 항목이다. 표시할 때는 `plan.inputs`를 읽는다.
- **이벤트**: `analysis_plan_created`, `analysis_execution_created`, `analysis_request_admitted`, `analysis_request_completed`, `analysis_plan_approved`, `analysis_approval_revoked`, `analysis_stop_requested`, `analysis_execution_blocked`, `analysis_step_dispatched`, `analysis_dispatch_released`, `analysis_step_deferred`, `analysis_step_completed`, `analysis_step_failed`, `analysis_attempt_recorded`, `analysis_attempt_refused`, `analysis_scientific_approval_recorded`, `analysis_execution_completed`. 연결된 자식 이벤트(`Run.call`의 호출·캐시·실패, `execution_call_admitted`, `execution_call_stopped`, 작업 제출·시도·취소·재시도, `job_observed`, 보고서 게시)에는 내부 필드 `execution_link: {execution_id, step_id, operation_id}`가 붙는다. 이 필드는 서버 코드만 만들며 어떤 HTTP 요청으로도 넣을 수 없다. 연결이 없는 기존 이벤트에는 이 필드가 없다. 기존 `inspect_complex`의 `workflow_*` 이벤트와는 별개다.
- **작업 API와의 관계**: 흐름이 소유한 작업(`execution_link`가 있는 제출)에 소유 실행이 아직 끝나지 않았을 때 `POST /jobs/{job_id}/start`·`/retry`를 부르면 412 `precondition`, `detail: {reason_code: "job_owned_by_analysis_execution", job_id}`다. 소유 실행이 종료 상태(`complete`, `cancelled`, `blocked`, `retryable_step=null`인 `failed`)가 되면 기존 수동 시작·재시도 규칙(시도 4회까지)이 그대로 적용된다. `/jobs/{job_id}/cancel`은 언제나 허용된다.
- `/capabilities`의 `methods.analysis_workflows`: `available: true`, `planner: "local_rules@1"`, `source`, `plan_schema`, 템플릿별 `{available, method, reason_code, reason}`(해당 방법 capability를 그대로 반영), `natural_language_planning: {available: false, reason}`, `limits{max_steps: 8, max_physical_attempts: 24, max_active_wall_s: 1800, max_retries_per_step: 1}`, `max_plans_per_run: 100`, `max_plan_bytes: 1048576`, `max_executions_per_run: 100`, `execution` 설명.

## M15 잔기 번호 대응

규칙은 `docs/business-rules.md` "잔기 번호 대응 (M15)". 읽기 호출은 로컬 참조 폴더와 run 객체만 읽고 도구·작업·이벤트·외부 요청을 만들지 않는다. 참조 읽기 응답은 스냅샷을 사용할 수 없어도 200이며 `{available: false, reason_code: "not_installed"|"snapshot_invalid", reason, set_hash: null}`와 빈 목록을 담는다.

### 계산: `POST /runs/{id}/commands` `{tool: "map_residue_numbering", args}`
- `args`: `{structure: <같은 run의 structure|prepared_structure handle>, pdb_id: <4자 PDB ID, [0-9][A-Za-z0-9]{3}> | null(기본), chains: [{chain_auth: str, uniprot_accession: str|null}]}`. `chains`는 1개 이상, `chain_auth` 중복 금지. 알 수 없는 필드는 거부한다. `pdb_id`는 대문자로 정규화한다.
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `residue_numbering_map`, schema `residue_numbering_map@1`, summary `{structure, chains, set_hash, mapped, unmapped, conflict}`. `mapped`가 0이면 `null_result: true`. 같은 입력·같은 세트면 같은 handle(호출 키에 세트 해시). 처음 쓰는 세트면 먼저 `reference_snapshot_set@1` 객체가 저장된다.
- 실패(도구 실패 본문, `detail.reason_code`):
  - 412 `precondition`: `not_installed`, `snapshot_invalid`(사용 중 세트 없음·손상, 캐시 조회 전).
  - 422 `input_invalid`(도구 구현을 부르지 않음, 체인 문제는 `detail.chain_auth` 포함): `unknown_field`, `structure_invalid`(handle 형식·다른 run), `structure_kind_not_allowed`, `pdb_id_invalid`, `chains_invalid`, `duplicate_chain`, `chain_not_found`(그 모델에 사슬 잔기 없음), `accession_not_in_uniprot_snapshot`, `no_usable_method`, `accession_with_multiple_sifts_accessions`, `structure_entities_inconsistent`.
- 결과 객체 주요 필드: `schema`, `method_version`(`mw.residue_numbering/v1`), `structure{handle, structure_kind, model_number}`, `snapshot_set{set_hash, origin, sources:[{source, snapshot_id, date, version_hint, license, file_sha256s}]}`, `pdb_id`, `alignment_params{matrix, gap_open, gap_extend, gap_cost, end_gaps, tie_break, implementation, min_identity_pct, min_coverage_pct, max_alignment_cells}`, `chains[]`, `reference_rows{uniprot, sifts, klifs}`, `rows[]`, `null_result`, `limitations`.
  - 체인: `chain_auth`, `requested_uniprot_accession`, `methods_run`, `cross_check`, `cross_check_absent_reason`, `sifts{accessions, sifts_chain_match: "auth_only", sifts_residue_key}|null`, `alignment{accession, identity_pct, coverage_pct, aligned_pairs, identical, chain_residue_count, score, chain_reason, ambiguous_residue_count, aligned_strings{structure, uniprot}}|null`, `klifs[{accession, applied, absent_reason, unresolved_regions, gapped_regions}]`, `residue_rule{rule, modified_residue_count}`, `counts{mapped, unmapped, conflict}`.
  - 행: `residue`(7필드, null 그대로), `status`, `uniprot_accession`, `uniprot_position`, `uniprot_residue`, `residue_match`, `klifs_index`, `klifs_label`, `klifs_match`(`contiguous`|`gapped_unique`), `conflict_reason`, `sifts`·`alignment`(`{accession, position}` 또는 `{absent_reason, absent_reasons}`, 실행 안 했으면 null).

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /reference/snapshots` | — | `reference_snapshots@1`: `{available, reason_code, reason, set_hash, origin, imported_at, kbase_repo{commit, dirty}, sources:[{source, snapshot_id, date, version_hint, license, origin, url_count, raw_sha256, files:[{name, path, sha256, bytes, rows, use}]}]}` | — |
| `GET /reference/sifts_chains?pdb_id=` | 4자 PDB ID | `reference_sifts_chains@1`: `{available, …, pdb_id, chains:[{chain_auth, accessions, reason_code, reason}]}`. 스냅샷에 없는 PDB는 빈 목록 | 422 `input_invalid`(형식) |
| `GET /reference/uniprot?query=&offset=&limit=` | query 최대 100자(빈 값 = 전체), limit 1–100(기본 20) | `reference_uniprot_search@1`: `{available, …, query, offset, limit, total, entries:[{accession, entry_name, gene, protein_name, organism, sequence_length}]}`. `status: ok` 항목만, accession·gene·entry_name·protein_name 부분 일치(대소문자 무시). 서열은 돌려주지 않는다 | 422 |
| `GET /runs/{id}/reference/pdb_id_hint?structure=` | 같은 run의 `structure`·`prepared_structure` | `{structure, structure_kind, format, pdb_id|null, origin: "mmcif_entry_id"|"pdb_header"|null}`. 업로드 원본(전처리 구조는 원본 구조의 업로드)에서 읽은 **제안**일 뿐이다 | 404 없는 handle, 422 다른 kind, 409 `run_corrupt` |
| `GET /runs/{id}/numbering_maps?offset=&limit=` | limit 1–100(기본 50) | `residue_numbering_map_list@1`: `{active_set_hash, snapshot_available, total, offset, limit, rows:[{handle, structure, structure_kind, model_number, pdb_id, chains, cross_checked_chains, chain_details, set_hash, counts{mapped, unmapped, conflict}, row_count, null_result, created_seq, stale_snapshot}]}`. 최신 순. `chain_details`는 객체의 체인 요약에서 `alignment.aligned_strings`만 뺀 것. `stale_snapshot`은 세트 해시가 사용 중 세트와 다르거나 사용 중 세트가 없을 때 true. `snapshot_available`은 사용 중 세트가 있을 때(`active_set_hash`가 null 아님) true. 화면은 `snapshot_available`이 false면 "사용 중 스냅샷 없음", true이고 `stale_snapshot`이면 "이전 스냅샷 기준"으로 표시한다 | 409 `run_corrupt` |
| `GET /runs/{id}/objects?handle=<residue_numbering_map>&offset&limit&columns` | 기존 객체 페이지(50/100) | 대응 객체의 `rows` 배열 한 페이지와 `total`(= 행 수). `columns`는 행의 최상위 키 | 422 모르는 열 |

- `/capabilities`의 `methods.residue_numbering`: `{available, reason_code: null|"not_installed"|"snapshot_invalid", reason, set_hash, sources:[{source, snapshot_id, date, version_hint, license, origin}]}`. 해시와 내용 형식 해석까지 확인한다.
- 보고서: `POST /runs/{id}/method_reports` `{result_handle: <residue_numbering_map>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "residue_numbering"`, `render_version: "residue_numbering_markdown@1"`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다. 주장(claim)의 주요 필드는 `{statement_id, evidence_kind: "computed"|"reference_value", source_handle, field_path, row_selector, subject, quantity, unit, exact_value, rendered_value, rounding, operation, reference}`이며, 종류가 맞지 않는 필드 경로는 422 `report_evidence_invalid`다. 대응 객체의 행 `absent_reasons`·`conflict_reason`과 체인 KLIFS `absent_reason`이 닫힌 이유 집합 밖이거나 KLIFS `applied`와 `absent_reason` null 여부가 맞지 않아도 422 `report_evidence_invalid`(`message`에 `numbering_row_shape`·`numbering_klifs_reason_invalid`)다. manifest `limitations` 마지막 줄은 스냅샷 범위 문장이며, 그 줄이 없는 이전 목록으로 저장된 보고서도 다시 열린다.

## M16 참조 주석

규칙은 `docs/business-rules.md` "참조 주석 (M16)"과 "뷰어 요청과 저장된 보기". 읽기 호출은 run 객체만 읽고 도구·작업·이벤트·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다.

### 계산: `POST /runs/{id}/commands` `{tool: "annotate_reference_sites", args}`
- `args`: `{numbering_map: <같은 run의 residue_numbering_map handle>, contacts: <같은 run의 interaction_set handle> | null(기본)}`. 다른 키는 거부한다.
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `reference_site_annotation`, schema `reference_site_annotation@1`, summary `{numbering_map, contacts, structure, set_hash, annotated, absent}`. `annotated`가 0이면 `null_result: true`. 같은 입력이면 같은 handle(호출 키에 세트 해시 없음, 훅이 `bound`를 돌려주지 않음).
- 실패: 422 `input_invalid`(도구 구현을 부르지 않음, `detail.reason_code`): `unknown_field`, `numbering_map_invalid`(handle 아님·다른 run·없음·다른 종류), `contacts_invalid`(같은 경우), `structure_mismatch`(접촉 결과의 구조 ≠ 대응의 구조), `duplicate_site_residue`(한 그룹에서 같은 KLIFS 번호의 `mapped` 행이 둘 이상).
- 결과 객체: `schema`, `method_version`(`mw.site_annotation/v1`), `site_set{id: "kinase_key_sites@1", sites:[{klifs_index, klifs_label}×10]}`, `numbering_map`, `snapshot_set_hash`, `structure{handle, structure_kind, model_number}`, `contacts{handle, ligand(7필드), cutoff_A, types}|null`, `groups:[{chain_auth, accession, klifs_applied, klifs_absent_reason, sites}]`, `other_contact_residues:[{residue, row_indexes}]|null`, `null_result`, `limitations`(고정 4문장).
  - 부위: `klifs_index`, `klifs_label`, `status`(`annotated`|`absent`), `absent_reason`(`klifs_not_applied`|`pocket_gap`|`region_unresolved`|`no_mapped_residue`|null), `residue`(7필드), `map_row_index`, `residue_match`, `klifs_match`, `display_label`, `contact`.
  - `contact`: `{assessed, not_assessed_reason, by_type:{contact|polar_contact|hydrophobic_contact: {computed, count}}, min_distance_A, min_distance_row_index, polar_pairs:[{contact_row_index, protein_atom, ligand_atom, distance_A}]|null}` 또는 null(`absent` 부위, 접촉 결과 없음).

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/site_annotations?structure=&offset=&limit=` | `structure`(선택, 구조 handle로 거르기), limit 1–100(기본 50) | `reference_site_annotation_list@1`: `{active_set_hash, total, offset, limit, rows:[{handle, structure, structure_kind, model_number, numbering_map, contacts, ligand, set_hash, groups:[{chain_auth, accession}], counts{annotated, absent}, null_result, created_seq, stale_snapshot}]}`. 최신 순. `stale_snapshot`은 사용 중 세트가 없거나 주석의 세트와 다를 때 true(화면은 M15 `snapshotBadge` 규칙으로 표시) | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/site_annotations/detail?handle=` | 주석 handle | `{meta, annotation}`(도구가 쓴 그대로) | 404 없는 handle, 422 다른 종류·모르는 파라미터, 409 `run_corrupt` |

- `/capabilities`의 `methods.reference_site_annotation`: 항상 `{available: true, reason_code: null, reason: null}`(run 객체만 읽음).

### 저장된 보기·그림
- 보기 저장 `POST /runs/{id}/viewer/scenes`: `schema`로 본문을 가른다. `viewer_scene@1` 본문은 그대로이며 `annotation` 키가 있으면 422 `input_invalid`. `viewer_scene@2`는 @1 본문 + 필수 `annotation: {handle, legend: bool}`(없으면 422). 주석 handle이 다른 run·없음·다른 종류면 422 `input_invalid`, 주석의 구조가 보기 소스와 다르면 422 `structure_mismatch`. 멱등(요청 UUID + 정규화 본문) 규칙은 같다. 저장된 @2 보기는 @1 필드 + `annotation{handle, legend}`.
- 그림 저장 `POST /runs/{id}/viewer/figures`: `viewer_figure@2`는 @1 본문 + 필수 `legend_composited: bool`. 그림 schema가 보기 schema와 짝이 맞지 않으면 409 `scene_mismatch`, 보기의 `legend`가 거짓인데 `legend_composited: true`면 422 `input_invalid`. 저장된 @2 그림은 @1 필드 + `capture_method`(`molstar_image_pass+legend`|`molstar_image_pass`) + `annotation{handle, legend, numbering_map, contacts, snapshot_set_hash, display_labels}`(서버가 저장된 주석에서 복사). 다시 열 때 이 값이 주석 객체와 다르면 409 `scene_invalid`.
- PNG 크기·개수 한도는 @1과 같다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <reference_site_annotation>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "reference_site_annotation"`, `render_version: "reference_site_annotation_markdown@1"`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다.
- 주장 statement ID: `computed` — `site_status_count`, `site_absent_reason_count`(주석 객체 인용), `site_contact_count`, `site_min_distance_A`(접촉 결과 행 인용). `reference_value` — `reference_accession`, `reference_uniprot_position`, `reference_klifs_index`, `reference_klifs_label`, `reference_site_residue`(대응 객체 인용). 주장 필드 구조는 M15 보고서와 같다. 종류가 맞지 않는 필드 경로, 주석과 인용 행의 불일치, 닫힌 집합 밖 상태·이유는 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `budget`, `active_set_hash`(보고서 생성 때 사용 중 세트, 없으면 null), `stale_snapshot`.

## 과거 단계 실행기 (CLI)

`scripts/execute.py <phase> [--dry-run | --resume | --verify | --record-review N --review-report … --reviewed-files … --reviewer-model gpt-6-astra]`. `--verify`는 모델을 호출하지 않고 검토 해시와 수락 명령을 다시 확인한다. 실패하면 0이 아닌 값으로 끝나고 단계 상태를 `error`로, 통과하면 새 `completed_at`을 `phases/index.json`과 그룹 `index.json`에 기록한다. 기본 실행과 `--record-review`는 Codex·GPT-6 전용이다.
