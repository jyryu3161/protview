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
| 415 | M11·M17 가져오기에 `application/octet-stream`이 아닌 본문 |
| 422 | `input_invalid`, `report_evidence_invalid`, `method_evidence_invalid`, `scene_invalid` |
| 429 | 도구의 `resource_exceeded`(예산·한도 소진, 저장 보기·그림 개수 초과, M19 일괄 제출의 `batch_limit_raise_required`) |
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
| `GET /capabilities` | 모드, 에너지 프로토콜 표, `methods.{interface_sasa, openmm_protein_minimize, chemical_interactions, pocket_detection, analysis_workflows, residue_numbering, reference_site_annotation, ligand_candidates, ligand_docking, ligand_docking_batch}` 사용 가능 여부와 이유, 지원·미지원 기능 목록. 무거운 엔진을 import하지 않는다 |
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
| `POST /runs/{id}/method_reports` | SASA·OpenMM·거리·정렬·화학·포켓·번호 대응·참조 주석·리간드 후보·리간드 도킹·리간드 도킹 일괄 결과 handle(`filters`는 리간드 후보에만) | 201, 방법 보고서 handle |
| `GET /runs/{id}/reports` | — | 저장된 보고서 목록 |
| `GET /runs/{id}/reports/selected?handle=…` | — | 보고서 manifest |
| `GET /runs/{id}/reports/download?handle=…&format=markdown|json` | — | UTF-8 Markdown 또는 JSON 파일 |

증거 검증에 실패하면 422 `report_evidence_invalid`다. 보고서 생성은 외부 요청을 하지 않는다.

## 비싼 계산 작업

순서(실제 UI 흐름):
1. (OpenMM만) `GET /jobs/preflight?structure=<handle>`: 입력 적합성, 제외 항목, 필요한 확인.
2. `POST /jobs`: `{protocol_id, args, timeout_s?}`(timeout_s 기본 60, 0 초과 900 이하(OpenMM·화학·포켓·리간드 후보는 120 이하, M19 `qvina_batch_dock_v1`만 7800 이하), 다른 필드는 거부). 본문은 최대 512 KiB. 실행 파일·경로·환경변수는 받지 않는다. 200으로 queued 작업을 돌려주고, dry-run run이면 계획만 돌려준다. 형식 오류는 422다.
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

- `POST /runs/{id}/chemical/imports?kind=receptor|ligand_sdf|receptor_bonds&filename=…`(M17이 `building_blocks_sdf`·`building_blocks_smiles`를 더했다, 아래 "M17 리간드 후보". M18 도킹은 세 종류를 그대로 쓴다): `application/octet-stream` 본문, 최대 10 MiB. 201로 `{schema: "chemical_raw_input@1", handle, kind, format, sha256, size}`를 돌려준다. 리간드는 V2000 SDF만 받고, V3000은 형식 오류로 거부한다.
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

## M17 리간드 후보

규칙은 `docs/business-rules.md` "리간드 후보 (M17)". 읽기 호출은 run 객체만 읽고 도구·작업·이벤트·RDKit·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 서버 프로세스는 RDKit을 import하지 않는다.

### 가져오기
- `POST /runs/{id}/chemical/imports?kind=building_blocks_sdf|building_blocks_smiles&filename=…`: `application/octet-stream`, 최대 10 MiB. 확장자 `.sdf`(SDF) / `.smi`·`.txt`(SMILES), UTF-8·NUL 없음, SDF는 `$$$$` 기준 레코드 1–1,000개, SMILES는 레코드 줄 1개 이상. 201 `{schema: "chemical_raw_input@1", handle, kind, format: "sdf_multi"|"smiles_list", sha256, size}`. 부모는 기존 `kind=ligand_sdf`(M11 그대로). 같은 바이트를 다른 종류로 가져오면 422.

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
- `{protocol_id: "rdkit_inspect_v1", args: {parent_sdf_handle, block_handles?: [<0–2개, 종류마다 1개>], rules?: [<반응 SMARTS 문자열, 0–10개>]}, timeout_s}` → 완료 작업의 `artifacts.ligand_inspection`.
- `{protocol_id: "rdkit_enumerate_v1", args: {inspection_handle, site_atoms: [<SDF 번호>], use_fixed: bool, rule_ids?: ["user_<n>", …]}, timeout_s}` → `artifacts.ligand_candidate_set`. 규칙 텍스트는 받지 않는다(서버가 점검 객체에서 꺼냄).
- `timeout_s` 상한 120. 다른 인자는 거부한다. 요청 필드로 인터프리터·모듈·경로를 고를 수 없다. 두 도구(`rdkit_inspect_ligand`, `rdkit_enumerate_ligands`)는 작업 전용이라 `/commands`로는 실행되지 않는다.
- 입장 거절(작업을 만들지 않음, 422 `input_invalid`, `detail.reason_code`): `invalid_job_arguments`, `rule_text_invalid`, `parent_import_invalid`, `block_import_invalid`, `no_generation_method`, `inspection_invalid`, `site_atoms_invalid`, 부위 이유 5개(`site_empty`, `site_atom_unknown`, `core_empty`, `crossing_bond_count`, `crossing_bond_not_single`, `detail.site_check` 포함), `rule_invalid`(`detail.rule_id`, `detail.status`). 환경을 쓸 수 없으면 412 `precondition`(`detail.reason_code`는 capability 이유).
- 작업 실패(과금됨, 결과 객체 없음, `failure{error, reason_code, message}`): `input_invalid` — 부모 거부 이유 5개(`unparseable`, `record_count`, `multiple_fragments`, `element_not_allowed`, `too_many_atoms`), 작업 안 부위·규칙 재검사 이유. `resource_exceeded` — `svg_limit`(2D SVG > 256 KiB), `output_limit`. `fatal` — `staged_input_invalid`, `rdkit_version_mismatch`, `worker_internal_error`, 잘못된 오류 봉투. 시간 초과·취소는 결과 없음.
- 같은 정규화 입력은 같은 호출 키(부모·block handle은 종류별, 규칙은 요청 순서, 부위 오름차순, 불리언, 상한, 고정 환경 pin)라 기존 작업을 돌려준다. dry-run run은 계획만.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/ligand/prerequisites` | — | `ligand_prerequisites@1`: `{capability, import_counts{ligand_sdf, building_blocks_sdf, building_blocks_smiles}, imports:[{handle, input_kind, sha256, created_seq}], inspections, candidate_sets, requires, starts_job: false}` | 422 모르는 파라미터 |
| `GET /runs/{id}/ligand/inspections?offset&limit` | limit 1–100(기본 50) | `ligand_inspection_list@1`: `{total, offset, limit, rows:[{handle, created_seq, valid, reason_code, job_id, parent_handle, parent_sha256, parent_canonical_smiles, heavy_atom_count, block_handles, blocks_accepted, rules_total, rules_valid}]}`. 만든 순서(오래된 것 먼저). 검증에 실패한 행은 `valid: false`, `reason_code: "evidence_invalid"`, 나머지 null | 409 `run_corrupt` |
| `GET /runs/{id}/ligand/inspections/detail?handle=` | 점검 handle | `ligand_inspection_detail@1`: `{handle, job_id, inspection, meta}`(SVG 포함) | 404 없는 handle, 422 다른 종류, 422 `method_evidence_invalid` |
| `GET /runs/{id}/ligand/candidate_sets?inspection=&offset&limit` | `inspection`(선택, 점검 handle로 거르기) | `ligand_candidate_set_list@1`: `{inspection_handle, total, offset, limit, rows:[{handle, created_seq, valid, reason_code, job_id, inspection_handle, site_atoms, use_fixed, rule_ids, candidates, raw_products, null_result, limit_reached, stop_reason}]}` | 409 `run_corrupt` |
| `GET /runs/{id}/ligand/candidate_sets/detail?handle=` | 후보 집합 handle | `ligand_candidate_set_detail@1`: `{handle, job_id, candidate_count, candidate_set(후보 행 제외), meta}` | 404, 422, 422 `method_evidence_invalid` |
| `GET /runs/{id}/ligand/candidate_sets/rows?handle=&offset&limit&sort&direction&passes_only&pains_exclude&<속성>_min&<속성>_max` | 각 파라미터 최대 1번. limit 1–100(기본 50), offset ≤ 1,000,000, `sort`는 `generation_order`·속성 8개, `direction` `asc|desc`, 불리언은 `true|false`, 경계는 10진 숫자(경계 포함) | `ligand_candidate_page@1`: 후보 집합의 부모·부위·규칙·개수·상한·`limitations` + `{total, passing, failing, filter_pass_counts, matched, hidden_by_filter, sort, direction, offset, limit, passes_only, filter_spec, rows:[{generation_order, candidate, filters, passes_all}]}`. 적용한 필터가 없으면 `passing`·`failing`·`passes_all`은 null | 422 모르는·반복·잘못된 파라미터, `min > max`, 404, 422 `method_evidence_invalid` |
| `POST /runs/{id}/ligand/preview` | `{inspection_handle, site_atoms, use_fixed, rule_ids?}`(본문 최대 64 KiB, 다른 키 거부) | `ligand_site_preview@1`: `{inspection_handle, site_check, use_fixed, rules:[{rule_id, status, usable}], generation_method_selected, ready, blocking_reasons, starts_job: false}`. `site_check`(`ligand_site_check@1`)는 `{valid, reason, site_atoms, unknown_atoms, core_atoms, crossing_bonds, site_hydrogens, retained_parent_atoms}`이며 판정하지 않은 필드는 null. `blocking_reasons`는 `no_generation_method`, 부위 이유, `rule_invalid` | 412 `inspection_required`(run에 점검 없음), 422 `invalid_preview_request`·`inspection_invalid`·`site_atoms_invalid`(도구 실패 본문) |

- 미리보기의 `site_check.retained_parent_atoms`는 코어 수소 번호를 포함한다. 후보 집합의 `retained_parent_atoms`는 코어 중원자만이다.
- 서버의 경계 파서는 10진 문자열을 int 또는 float로 바꾼다(그래서 `1.0000000000000001`은 1.0). 화면은 사용자가 입력한 문자열을 그대로 보낸다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 두 종류를 읽을 수 있지만 리간드 검증을 거치지 않는다(M12 포켓과 같은 관례). 화면은 위 `/ligand/*`만 쓴다.

### capability
- `/capabilities`의 `methods.ligand_candidates`(`ligand_capability@1`): `{available, status, reason_code, reason, engine: "rdkit", rdkit_version_expected: "2026.03.6", protocols, tools, execution_lane: "durable_job", timeout_s: 120, limits{input_bytes_per_file, blocks, rules, rule_bytes, parent_heavy_atoms, candidates, attempts, svg_bytes, inspection_bytes}, limitations, pins, pains_catalog_entries}`. 사용할 수 없으면 `available: false`, `reason_code`는 `worker_missing | handshake_failed | rdkit_version_mismatch | pains_catalog_unavailable`, `pins`·`pains_catalog_entries`는 null. 서버는 작업 모듈의 handshake만 실행하고, 성공한 handshake만 캐시한다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <ligand_candidate_set>, filters?: {ranges?: {<속성>: {min?, max?}}, pains_exclude?: bool}}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "ligand_candidates"`, `render_version: "ligand_candidates_markdown@1"`, 정규화한 `filter_spec`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다. 다른 결과 종류에 `filters`를 보내면 422 `report_evidence_invalid`.
- 주장은 모두 `evidence_kind: "computed"`. statement ID: `parent_property`, `candidate_count`, `generation_count`, `rejected_count`, `not_applicable_count`, `limit_state`, `site_atoms`, `rule_text`(저장 필드), `pains_match_count`, `stereo_flag_count`, `filter_pass_count`, `filter_all_pass_count`(`count_where`, 조건은 `row_selector`). 주장 필드는 `{statement_id, evidence_kind, source_handle, source_kind, source_schema, source_sha256, field_path, row_selector, subject, quantity, unit, exact_value, rendered_value, rounding, operation}`. 다른 statement의 필드 경로, 틀린 반올림·개수, 해석 문장, 완료되지 않았거나 변조된 후보 집합은 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `capability`, `budget`.

## M18 리간드 도킹

규칙은 `docs/business-rules.md` "리간드 도킹 (M18, `qvina_dock_v1`)". 읽기 호출은 run 객체(수용체 인스턴스 목록은 가져오기 바이트를 gemmi로)만 읽고 도구·작업·이벤트·RDKit·Meeko·qvina·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 가져오기는 M11 `kind=receptor|receptor_bonds|ligand_sdf` 그대로다.

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
- `{protocol_id: "qvina_dock_v1", args, timeout_s}`. `timeout_s` 상한은 공통 900이고 화면은 600을 보낸다(인자가 아니며 호출 키에 들어가지 않음). 완료 작업의 `artifacts.docking_result`.
- `args`(고정 모양, 알 수 없거나 빠진 키는 `invalid_job_arguments`):
```json
{"receptor_handle": "obj://…/chemical_raw_input/…",
 "receptor_model_number": 1,
 "connectivity": {"kind": "pdb_conect" | "sidecar", "sidecar_handle": null | "obj://…"},
 "receptor_instance": null | {"model_number": 1, "chain_auth": "A", "chain_label": null, "seq_auth": 300,
                              "seq_label": null, "icode": "", "resname": "XYZ"},
 "ligand": {"source": "sdf", "sdf_handle": "obj://…"} |
           {"source": "candidate", "candidate_set_handle": "obj://…", "candidate_id": "c_…",
            "parent_sdf_handle": "obj://…"},
 "mode": "free" | "core_fixed",
 "box": {"source": "ligand_range" | "instance_range", "margin_A": 8.0} |
        {"source": "manual", "center_A": [0, 0, 0], "size_A": [20, 20, 20]},
 "parameters": {"seed": 0, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3, "conformers": 50},
 "acknowledgement": {"keep_input_protonation": true, "tool_assigned_types_charges": true,
                     "rigid_no_optimization": true}}
```
  `seed`는 필수, `exhaustiveness`·`num_modes`·`energy_range`·`margin_A`와 코어 고정의 `conformers`는 빼면 기본값으로 채운다. 자유 도킹에 `conformers` 키가 있으면(null 포함) 거절하고 정규화 때 null로 둔다. 정수는 bool·float가 아니어야 한다. 호출 키에는 `acknowledgement`를 뺀 정규화 인자와 고정 환경 pin이 들어간다.
- 입장 거절(작업을 만들지 않음, 예산 없음, 422 `input_invalid`, `detail.reason_code`): `invalid_job_arguments`(모양·범위·종류·다른 run handle), `mode_source_mismatch`, `acknowledgement_missing`, `box_invalid`, `box_too_large`(직접 입력 한 변 > 40 Å), `candidate_unknown`, `parent_mismatch`, 수용체 이유(`receptor_invalid`, `receptor_hydrogens_missing`, `receptor_unsupported_residue`, `receptor_altloc_present`, `receptor_instance_unknown`, `receptor_instance_ambiguous`, `receptor_instance_covalent`). `receptor_unsupported_residue`·`receptor_altloc_present`의 `detail`은 `items`(최대 20개: `{residue(7필드), atom_names}` 또는 `{residue, atom_name, altloc}`)와 `total`, `receptor_instance_covalent`의 `detail`은 `bonds`(최대 20쌍의 원자 식별자)와 `total`이다. 환경을 쓸 수 없으면 412 `precondition`(`detail.reason_code`는 capability 이유).
- 작업 실패(과금됨, 결과 객체 없음, `failure{error, reason_code, message, detail}`): `input_invalid` — 수용체·리간드·후보·코어·상자 이유(작업 프로세스가 같은 검사를 다시 함), `resource_exceeded` — 모드당 접촉 500행 초과·결과 4 MiB 초과, `fatal` — `engine_failed`, `engine_output_invalid`, 잘못된 오류 봉투. 시작 때 고정 pin이 바뀌었으면 `precondition`(`worker_version_invalid`). 시간 초과·취소는 결과 없음. dry-run run은 계획만.
- `POST /jobs/{id}/start`는 작업이 끝날 때까지 응답하지 않는다. 화면은 제출 응답의 job id로 `GET /jobs/{id}`·`POST /jobs/{id}/cancel`을 따로 부른다. 도구 `qvina_dock_ligand`는 작업 전용이라 `/commands`로 실행되지 않는다.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/docking/prerequisites` | — | `docking_prerequisites@1`: `{capability, import_counts{receptor, receptor_bonds, ligand_sdf}, imports:[{handle, input_kind, input_format, size, sha256, created_seq}], candidate_sets:[{handle, valid, candidates, parent_handle, parent_sha256, parent_sdf_handles}], docking_results, starts_job: false}`. `parent_sdf_handles`는 SHA-256이 후보 집합의 `parent_sha256`과 같은 이 run의 `ligand_sdf` 가져오기. 검증에 실패한 후보 집합은 `valid: false`, 나머지 null | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/docking/receptor_instances?handle=` | 같은 run의 `receptor` 가져오기 handle | `{schema: "docking_receptor_instances@1", handle, sha256, format: "pdb"|"cif", model_numbers, models:[{model_number, water_residue_count, instances:[{residue(7필드), atom_count, element_counts}]}], selection_aid_only: true, starts_job: false}` | 422 `input_invalid`(handle·종류·형식), 422 도구 실패 본문 `receptor_invalid`(구조로 읽히지 않음), 409 `run_corrupt` |
| `GET /runs/{id}/docking/results?offset&limit` | limit 1–100(기본 50) | `docking_result_list@1`: `{total, offset, limit, rows:[{handle, created_seq, valid, reason_code, job_id, method, mode, ligand_source, candidate_id, receptor_handle, seed, box_source, modes, null_result}]}`. 만든 순서(오래된 것 먼저). 행마다 다시 검증하고, 실패한 행은 `valid: false`, `reason_code: "evidence_invalid"`, 나머지 null | 409 `run_corrupt` |
| `GET /runs/{id}/docking/results/detail?handle=` | 도킹 결과 handle | `docking_result_detail@1`: `{schema, handle, job_id, score_label, result, meta}`. `result`는 저장 객체에서 모드 행의 `pose_sdf`·`contacts`를 빼고 행마다 `contact_count`를 더한 것 | 404 없는 handle, 422 다른 종류, 422 `method_evidence_invalid` |
| `GET /runs/{id}/docking/results/contacts?handle=&mode=&offset&limit` | `mode` 1–20(필수), limit 1–500(기본 100) | `docking_contact_page@1`: `{handle, mode, method, cutoff_A, total, offset, limit, rows}`. 행은 저장 순서(`ligand_serial`, `site_index`) | 404 없는 모드·handle, 422, 422 `method_evidence_invalid` |
| `GET /runs/{id}/docking/results/pose_sdf?handle=&mode=` | `mode` 1–20(필수) | 그 모드의 저장 `pose_sdf` 바이트 그대로(레코드 하나, `$$$$` 없음), `chemical/x-mdl-sdfile`, 첨부 이름 `protview-docking-<handle 해시 앞 12>-mode_<n>.sdf` | 404 없는 모드, 422, 422 `method_evidence_invalid` |
| `GET /runs/{id}/docking/results/poses_sdf?handle=` | — | 모든 모드의 저장 `pose_sdf`를 모드 순서로, 레코드마다 뒤에 `$$$$`(제목은 저장된 `mode_<n>`), 첨부 이름 `…-modes.sdf` | 404 모드 0개(빈 과학 결과), 422, 422 `method_evidence_invalid` |

- 모드별 `pose_sdf`와 전체 `poses_sdf`는 경로 이름이 한 글자(`s`) 다르다. 모드별은 `mode`가 필수이고 `$$$$`가 없으며, 전체는 `mode`를 받지 않는다(보내면 422).
- 모든 결과 읽기는 `docking_bundle.validated_result`(크기 제한 읽기, 완료된 게시 한 건, 입력·닫힌 집합 대조)를 거친다. 일반 `GET /runs/{id}/objects`·`/objects/meta`도 `docking_result`를 읽을 수 있지만 이 검증을 거치지 않는다(M12·M17과 같은 관례). 화면은 위 `/docking/*`만 쓴다.

### capability
- `/capabilities`의 `methods.ligand_docking`(`docking_capability@1`): `{available, status, reason_code, reason, protocol_id, tool_id, engine: "qvina", execution_lane: "durable_job", methods{free, core_fixed}, timeout_s{default: 600, max: 900}, limits{input_bytes_per_file, receptor_atoms, ligand_heavy_atoms, active_torsions, box_side_A, result_bytes, contacts_per_mode}, score_label, limitations, pins, versions}`. 사용할 수 없으면 `available: false`, `reason_code`는 `worker_missing | engine_missing | engine_hash_mismatch | handshake_failed | version_mismatch`, `pins`·`versions`는 null. 서버는 `qvina2` 파일 해시를 재고 작업 모듈 `--handshake`만 실행하며(qvina를 실행하지 않음), 구조가 맞는 handshake만 캐시한다(판정은 매번 다시 함).

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <docking_result>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "ligand_docking"`, `render_version: "ligand_docking_markdown@1"`, `result_schema: "docking_result@1"`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다.
- 주장은 모두 `evidence_kind: "computed"`. statement ID: `mode_count`, `sample_count`, `score`, `score_minimum`, `score_maximum`, `contact_count`, `contact_kind_count`, `atoms_outside_box`, `min_heavy_atom_distance`, `core_max_deviation`, `box`, `parameter`, `engine`, `preparation`, `receptor_input`, `removed_instance`, `ligand_input`. 주장 필드는 M17과 같다. 다른 statement의 필드 경로, 틀린 반올림·개수, 해석 문장, 필수 필드(후보 출처·`core_max_deviation_A`) 누락, 완료되지 않았거나 변조된 결과는 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `capability`(`available`, `status`, `reason_code`, `pins`), `budget`.

## M19 리간드 일괄 도킹

규칙은 `docs/business-rules.md` "리간드 일괄 도킹 (M19, `qvina_batch_dock_v1`)". 읽기 호출(시작 전 확인 POST 포함)은 run 객체와 가져오기 바이트(수용체 M11 검사, gemmi)만 읽고 도구·작업·이벤트·예약·한도 변경·RDKit·Meeko·qvina·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 새 가져오기 종류는 없다(M11·M17 가져오기 그대로). 후보별 결과는 M18 `/docking/results/*`로 읽는다.

### 일괄 인자 (`args`, 시작 전 확인·증액 승인·작업 제출이 같은 본문)
```json
{"receptor_handle": "obj://…", "receptor_model_number": 1,
 "connectivity": {"kind": "pdb_conect" | "sidecar", "sidecar_handle": null | "obj://…"},
 "receptor_instance": null | {<잔기 7필드>},
 "candidate_set_handle": "obj://…/ligand_candidate_set/…", "parent_sdf_handle": "obj://…/chemical_raw_input/…",
 "candidate_ids": ["c_…", …], "include_parent": false,
 "mode": "free" | "core_fixed", "box": <M18 상자>, "parameters": <M18 값>,
 "acknowledgement": {"keep_input_protonation": true, "tool_assigned_types_charges": true, "rigid_no_optimization": true}}
```
`candidate_ids`는 1–50개, 중복 금지, 순서는 서버가 후보 집합 순서로 바꾼다. 나머지 필드의 기본값·정수 규칙·자유 도킹의 `conformers` 거절은 M18과 같다. `ligand` 키는 없다(있으면 `invalid_job_arguments`).

### 입장 거절 (작업을 만들지 않음, 예산 없음, 도구 실패 본문 `detail.reason_code`)
- 422 `input_invalid`: `invalid_job_arguments`(모양·범위·종류·다른 run handle, 검증되지 않는 후보 집합, 중복 id), `batch_empty`, `batch_too_large`, `batch_parent_not_allowed`, `candidate_unknown`, `parent_mismatch`, `mode_source_mismatch`, `acknowledgement_missing`, `box_invalid`, `box_too_large`, 수용체 이유 7개(`detail`의 거부 목록 모양은 M18과 같음).
- 412 `precondition`: 환경을 쓸 수 없음(`detail.reason_code`는 capability 이유).
- 429 `resource_exceeded`: `batch_limit_raise_required`, `detail: {reason_code, needed{expensive_calls, wall_clock_s}, shortfall{expensive_calls, wall_clock_s}}`. 작업 제출에서만 난다(시작 전 확인은 부족분을 숫자로 돌려주고 증액 승인은 부족분을 올린다).

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
- `{protocol_id: "qvina_batch_dock_v1", args, timeout_s}`. `timeout_s`는 0 초과 7800 이하(이 프로토콜만. API 모델은 7800까지 받고 다른 프로토콜은 `JobQueue`가 각자 상한(120 또는 900)으로 거절한다). 화면은 7800을 보낸다. 호출 키에 들어가지 않는다.
- 같은 일괄 호출 키의 작업이 `queued`·`claimed`·`running`이거나 그 키의 검증된 `complete` 요약을 게시한 작업이 있으면 200으로 그 작업을 돌려준다(새 작업 없음). `partial` 요약만 있으면 새 작업을 만든다. dry-run run은 계획만 돌려준다.
- 첫 비싼 계산이면 `/start`가 409 `approval`(`tool: "qvina_dock_batch"`)을 돌려주고 `/jobs/approve`가 기록한다(작업 승인 허용 목록에 `qvina_dock_batch`). `/start`는 작업이 끝날 때까지 응답하지 않는다. 화면은 제출 응답의 job id로 `GET /jobs/{id}`를 폴링하고 `POST /jobs/{id}/cancel`로 취소한다.
- 시도는 1회다. `POST /jobs/{id}/retry`는 412 `precondition`이다. 시작 때 고정 pin(M18 pin + 일괄 작업 모듈·상수 해시)이 바뀌었으면 412 `precondition`(`worker_version_invalid`).
- 작업 기록 상태: 정상 종료·작업 프로세스 자체 전체 시계·출력 총량 정지는 `done`(`artifacts.docking_batch_result` = 요약 handle, `output_handles`는 요약 하나), 사용자 취소는 `cancelled`, 작업 마감은 `failed`(`failure.error: "resource_exceeded"`, "job timeout"), 크래시·자원 한도·출력 오류는 `failed`, 서버 재시작 복구는 `interrupted`. `done`이 아니어도 요약이 게시되었을 수 있다(아래 `batch.summary_handle`). 첫 행 전에 멈춘 작업(수용체 준비 실패 등)은 `failed`이고 요약이 없다. 요약을 만들 수 없으면 `failed`(`fatal`, "invalid scientific output")이고 이미 게시된 행 결과는 남는다.
- 일괄 작업의 `GET /jobs`·`GET /jobs/{id}`·`/start` 응답에는 `batch: {rows, reused_rows: [행 번호], finished_rows, summary_handle, summary_status, summary_stop_reason}`가 붙는다. `finished_rows`는 이 시도의 `rows/*.status.json` 수(재사용 행은 세지 않음), `summary_handle`은 어떤 종료 상태든 요약이 게시되면 채워지고, `summary_status`·`summary_stop_reason`은 그 요약을 검증해 읽은 값(검증 실패면 null)이다. 작업 기록 상태와 요약 상태는 따로 본다(작업 마감 정지는 작업 `failed` + 요약 `partial`/`time_exhausted`).

### 읽기와 증액 승인

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs/{id}/docking/batches/preflight` | 일괄 인자(본문 최대 512 KiB, 중복 키 거부) | 200 `docking_batch_preflight@1`: `{starts_job: false, capability, score_label, budget{expensive_calls, wall_clock_s}, remaining{…}, admission{admitted, error, reason_code, message, detail}, batch_input_sha256, mode, include_parent, candidate_ids, rows:[{row_index, kind, candidate_id, reuse, reused_handle, new_docking}], new_dockings, reused_rows, needed{expensive_calls, wall_clock_s}, shortfall{…}, full_batch_may_be_partial, statements{batch:[{id, text}], m18:[{number, text}]}, existing_job: {job_id, status, summary_handle} | null}`. 입장 거절과 환경 없음도 200이며 `admission.admitted: false`, 거절 이유·`detail`(수용체 거부 목록 포함)만 있고 행·필요량 필드는 null. `budget`·`remaining`은 활동 중 경과를 포함한 run 예산 | 413(본문), 422(JSON·쿼리), 404 없는 run |
| `GET /runs/{id}/docking/batches?offset&limit` | limit 1–100(기본 50) | `docking_batch_list@1`: `{total, offset, limit, rows:[{handle, published_seq, valid, reason_code, job_id, attempt_id, reused_rows, method, mode, status, stop_reason, batch_input_sha256, include_parent, candidate_set_handle, counts}]}`. 요약 handle의 첫 게시 순서. 행마다 다시 검증하고 실패한 행은 `valid: false`, `reason_code: "evidence_invalid"`, 나머지 null | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/docking/batches/detail?handle=` | 요약 handle | `docking_batch_detail@1`: `{handle, job_id, attempt_id, published_seq, reused_rows, score_label, score_column_label, statements{batch, m18}, summary(저장 요약 그대로), rows:[요약 행 + reused, detail_available], meta}`. `reused`는 게시 기록에서, `detail_available`은 행 결과 handle이 있을 때 true | 404 없는 handle, 422 다른 종류, 422 `method_evidence_invalid` |
| `POST /runs/{id}/docking/batches/limit_approval` | 일괄 인자(본문 최대 512 KiB) | 200 `{raised, batch_input_sha256, new_dockings, needed, shortfall_before, increase{expensive_calls, wall_clock_s}, limits_before, limits_after, shortfall_after, event_seq, budget}`. 부족분이 없으면 `raised: false`, `increase` 0, `event_seq: null`, 이벤트 없음(멱등) | 422 입장 거절(위와 같은 이유), 412 `precondition`(dry-run run `dry_run`, 환경 없음), 409 `{"ok": false, "error": "cancelled", "message": "run cancelled"}`(취소된 run, 아무것도 쓰지 않음), 503 `transient`(run 실행 잠금이 잡혀 있음, 예: 일괄 실행 중), 413 |

- 증액 승인은 사람이 화면에서 누르는 경로 하나뿐이다. 도구·분석 흐름 단계·뷰어 명령·작업 인자로 부를 수 없고, 첫 비싼 계산 승인을 기록하지 않으며 예약·과금·환불하지 않는다. 부족분은 호출 시점의 run 실행 잠금 안에서 과금된 사용량 기준으로 다시 계산한다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 `docking_batch_result`를 읽을 수 있지만 검증을 거치지 않는다(M12·M17·M18과 같은 관례). 화면은 위 읽기와 `/docking/results/*`만 쓴다.

### 이벤트
- `docking_batch_row_published {job_id, attempt_id, row_index, handle}`: 작업 프로세스 그룹 정리 확인 뒤 행 결과 하나를 게시할 때. 이 이벤트가 그 행 결과의 게시 증거이며(요약 게시가 없어도) M18 읽기·보고서·재사용이 받아들인다.
- `docking_batch_published {job_id, attempt_id, summary_handle, reused_rows: [행 번호]}`: 모든 행 게시 뒤 요약을 게시할 때(마지막).
- `job_dispatch_intent`에 `batch_reused: [{row_index, handle}]`가 붙고, `budget_reserved.expensive_calls`는 새로 계산하는 행 수(0 가능)다. N = 0이면 작업 프로세스 없이 `job_cleanup_verified`(`source: "no_go_or_no_launch"`)를 쓰고 요약만 게시한다.
- `budget_limit_updated {limits, by: "human", context{purpose: "docking_batch_limit_raise", batch_input_sha256, new_dockings, needed, shortfall, increase, limits_before, limits_after}}`: 증액 승인. 재생은 `limits`만 읽는다.

### capability
- `/capabilities`의 `methods.ligand_docking_batch`(`docking_batch_capability@1`): `{protocol_id: "qvina_batch_dock_v1", tool_id: "qvina_dock_batch", engine: "qvina", execution_lane: "durable_job", available, status, reason_code, reason, pins, batch_pins{batch_worker_sha256, batch_constants_sha256}, methods{free, core_fixed}, timeout_s{max: 7800}, limits{max_candidates, per_candidate_s, total_s, output_bytes, summary_bytes}, score_label, batch_statements{B1, B2, B3}}`. `ligand_docking`이 사용 가능하고, 일괄 작업 모듈·상수 파일이 있고, 일괄 작업 모듈 `--handshake`(같은 고정 인터프리터, 프로토콜·두 작업 모듈 해시 확인, 파일 해시 키로 캐시)가 맞을 때만 사용 가능. 아니면 `available: false`, `reason_code`는 M18 집합(`ligand_docking`의 이유를 그대로, 일괄 파일 없음은 `worker_missing`, 일괄 handshake 실패는 `handshake_failed`), `pins`·`batch_pins`는 null이고 `methods`·`timeout_s`·`limits`는 없다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <docking_batch_result>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "ligand_docking_batch"`, `render_version: "ligand_docking_batch_markdown@1"`, `result_schema: "docking_batch_result@1"`, 요약에서 복사한 `method, batch_input_sha256, inputs, box, parameters, engine, preparation, limits, stop_reason, counts, rows`, `batch_status`, `mode`, `score_label`, `score_column_label`, `score_row_label`, `limitation_ids`, `limitations`, `claims`, `snapshot`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 종류 이름 "리간드 도킹 일괄 보고서").
- 주장은 모두 `evidence_kind: "computed"`. statement ID: `receptor_input`, `removed_instance`, `candidate_set_input`, `box`, `parameter`, `engine`, `preparation`, `row_count`(`count(rows)`·`count_where(state == …; rows)`), `row_score`(요약 `rows[i].score_kcal_mol`), `row_result_score`(행 결과 `modes[0].score_kcal_mol`, `source_kind: "docking_result"`). 점수 주장은 `scored` 행만, `row_selector: {row_index}`. 주장 필드는 M18과 같다. 점수 없는 행의 점수 주장, 다른 statement의 필드 경로, 틀린 반올림·개수, 해석 문장, 방식이 섞인 결과, 요약 점수와 행 결과 첫 행 점수의 불일치, 변조·미완료 요약은 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `capability`(`available`, `status`, `reason_code`, `pins`, `batch_pins`), `budget`(올라간 한도 포함).

## 과거 단계 실행기 (CLI)

`scripts/execute.py <phase> [--dry-run | --resume | --verify | --record-review N --review-report … --reviewed-files … --reviewer-model gpt-6-astra]`. `--verify`는 모델을 호출하지 않고 검토 해시와 수락 명령을 다시 확인한다. 실패하면 0이 아닌 값으로 끝나고 단계 상태를 `error`로, 통과하면 새 `completed_at`을 `phases/index.json`과 그룹 `index.json`에 기록한다. 기본 실행과 `--record-review`는 Codex·GPT-6 전용이다.
