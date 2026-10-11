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
| 404 | 이 run에 없는 handle/job, M25 루프 라우트의 `loop_not_found` |
| 409 | `approval`(비싼 계산 승인 필요), `loop_stop`(자율 분기 가드), `cancelled`, `run_corrupt`(이벤트·payload 손상), `upload_conflict`, 멱등 요청 UUID 충돌, 뷰어 `stale_scene`·`stale_revision`(세션·세대·revision 불일치), 작업 시작의 `global_concurrency_busy`·`global_job_cleanup_pending`·`global_job_ledger_unavailable`(전역 heavy-worker 게이트), 분석 흐름의 `stale_revision`·`request_id_conflict`·`busy`, M24 과학 전송의 `preview_mismatch`·`send_id_conflict`·`send_in_progress`, M25 루프의 `loop_id_conflict`·`loop_active`·`loop_ended`·`send_in_progress`·`iteration_invalid`·`phase_invalid`·`iteration_cap_reached`·`proposal_invalid`·`proposal_late`·`candidate_unavailable`·`candidate_computed`·`step_unavailable`·`job_running`·`docking_pending`, 루프 전송의 `loop_send_invalid` |
| 412 | `precondition`(선행 조건 부족, 예: 리간드 선택 필요, 승인할 작업 없음, M15·M26·M27 참조 스냅샷 없음·손상 `not_installed`·`snapshot_invalid`, M27 호출 때 레코드 해시 불일치 `snapshot_invalid`), 분석 흐름의 상태 거절(`plan_blocked`, `dry_run_plan_only` 등), M24 dry-run run의 과학 전송 동의 켜기(`dry_run`), M25 루프 만들기의 `dry_run`·`capability_unavailable`, 루프 계산 시작의 `capability_unavailable`, 루프 투영의 상태 거절(`loop_ended`·`iteration_mismatch`·`selection_done`·`phase_invalid`·`cap_reached`·`too_few_candidates`) |
| 413 | 본문 크기 초과(`resource_exceeded`) |
| 415 | M11·M17 가져오기에 `application/octet-stream`이 아닌 본문, M24 JEV POST(`/jev/consent`·`/jev/preview`·`/jev/sends`)와 M25 루프 POST(`/jev_loops`, `/jev_loops/{loop_id}/compute`·`/abandon_docking`·`/end`)에 `application/json`이 아닌 본문(`unsupported_media_type`, 본문을 읽기 전) |
| 422 | `input_invalid`, `report_evidence_invalid`, `method_evidence_invalid`, `scene_invalid` |
| 429 | 도구의 `resource_exceeded`(예산·한도 소진, 저장 보기·그림 개수 초과, M19 일괄 제출의 `batch_limit_raise_required`, M22 GA 제출의 `ga_limit_raise_required`, M23 서열 GA 제출의 `ga_limit_raise_required`·`staged_input_bytes`, M20 변이 후보의 `too_many_positions`·`catalytic_list_too_long`, M24·M25 투영의 `payload_too_large`, M26 반응 지식의 `result_too_large`·`too_many_links`, M27 키나아제 전례의 `result_too_large`), M25 루프 계산 시작의 `budget_blocked` |
| 500 | M24 과학 전송 라우트의 `internal_error`(기록 중 디스크 오류·승인 대조 실패, 고정 문장만, 예외 텍스트 없음), M25 루프 라우트·루프 투영의 미리보기·전송에서 루프 라우트가 쓰지 않는 이벤트 순서(`internal_error`, 고정 문장) |
| 503 | 도구의 `transient` 또는 `fatal`, M24 과학 전송·M25 루프 쓰기 라우트의 `busy`(run 실행 잠금이 잡혀 있음, 아무것도 쓰지 않음) |

- **멱등성**: 뷰어 의도·저장 보기·그림 생성은 클라이언트 요청 UUID를, M24 과학 전송은 `send_id`(v4 UUID)를, M25 루프 만들기는 `loop_id`(v4 UUID)를 받는다. UUID와 정규화한 본문이 같으면 같은 결과를 돌려주고 다시 실행하지 않는다. UUID가 같은데 본문이 다르면 409다. M25 계산 시작은 UUID 없이 같은 단계의 가장 최근 승인과 인자가 같으면 새 이벤트·작업을 만들지 않는다.
- **목록**: `offset`/`limit` 페이지 단위다. 기본·최대 개수는 호출마다 다르다: 객체 행·저장 보기·그림·화학 결과 행 50/100, 원자 카탈로그 100/500, 화학 원자 목록 100/1000, 이벤트 200/500.
- **다운로드**: 파일 이름은 서버가 handle 앞부분으로 만든다(`protview-figure-<prefix>.png` 등). 저장된 산출물은 다시 받아도 같은 바이트다.

## run과 입력

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs` | `{goal?, context?, dry_run?: bool, egress?: "local_only"}`. egress에는 `local_only`만 넣을 수 있다 | 201, run 요약 | 422 |
| `GET /runs`, `GET /runs/{id}` | — | run 요약 목록/단건 | 400, 404 |
| `POST /runs/{id}/uploads?filename=x.pdb` | 원본 바이트(최대 25 MiB), 확장자 `.pdb/.cif/.mmcif` | 201, `{upload_id, sha256, size, …모델·체인 요약}` | 413, 422(형식·파싱), 409(같은 해시인데 다른 내용) |
| `POST /runs/{id}/commands` | `{tool, args, decided_by?: "human"\|"rule"}`. tool은 `load_structure`, `prepare_structure`, `compute_interactions`, `compute_interface_sasa`, `measure_distance`, `align_structures`, `compile_state`, `map_residue_numbering`(M15), `annotate_reference_sites`(M16), `generate_mutation_candidates`(M20), `build_jev_projection`(M24), `build_jev_loop_projection`(M25), `link_reaction_knowledge`(M26), `link_kinase_precedents`(M27) 중 하나 | 200, `{ok: true, handle: <envelope>}` | 도구 실패 본문(422/412/429/503), 409 |
| `POST /runs/{id}/inspect_complex` | 업로드 ID 또는 같은 run의 구조 handle, 모델, 전처리 정책, 선택적 리간드, cutoff | 완료된 handle 목록 또는 `needs_selection`/`no_ligand` | 412, 422, 409 |

`load_structure`의 `source`는 이 run의 업로드 ID여야 한다. 파일 경로나 URL은 받지 않는다. `decided_by`는 기록용 출처 정보일 뿐이며, 승인 권한을 주지 않는다.

## 읽기

| 호출 | 설명 |
|---|---|
| `GET /capabilities` | 모드, 에너지 프로토콜 표, `methods.{interface_sasa, openmm_protein_minimize, chemical_interactions, pocket_detection, analysis_workflows, residue_numbering, reaction_knowledge, kinase_precedents, reference_site_annotation, mutation_candidates, ligand_candidates, ligand_docking, ligand_docking_batch, ligand_ga_design, jev_choice, jev_loop}` 사용 가능 여부와 이유(`jev_loop`은 갈래별), 지원·미지원 기능 목록. 무거운 엔진을 import하지 않는다 |
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
| `POST /runs/{id}/method_reports` | SASA·OpenMM·거리·정렬·화학·포켓·번호 대응·참조 주석·리간드 후보·리간드 도킹·리간드 도킹 일괄·리간드 GA 설계 요약·변이 후보·변이 구조 모델 결과·서열 GA 설계 요약·JEV 판정 제안·JEV 루프 요약·효소 반응 지식 결과·키나아제 전례 결과 handle(`filters`는 리간드 후보에만) | 201, 방법 보고서 handle |
| `GET /runs/{id}/reports` | — | 저장된 보고서 목록 |
| `GET /runs/{id}/reports/selected?handle=…` | — | 보고서 manifest |
| `GET /runs/{id}/reports/download?handle=…&format=markdown\|json` | — | UTF-8 Markdown 또는 JSON 파일 |

증거 검증에 실패하면 422 `report_evidence_invalid`다. 보고서 생성은 외부 요청을 하지 않는다.

## 비싼 계산 작업

순서(실제 UI 흐름):
1. (OpenMM만) `GET /jobs/preflight?structure=<handle>`: 입력 적합성, 제외 항목, 필요한 확인.
2. `POST /jobs`: `{protocol_id, args, timeout_s?}`(timeout_s 기본 60, 0 초과 900 이하(OpenMM·화학·포켓·리간드 후보는 120 이하, M19 `qvina_batch_dock_v1`만 7800 이하, M22 `qvina_ga_dock_v1`과 M23 `sequence_ga_dock_v1`은 기본값 없이 `ga.total_s + 600` 이상 15000 이하이고 범위 밖이면 422 `invalid_job_arguments`, M21 `openmm_mutation_model_v1`은 기본 120·240 이하이고 범위 밖이면 422 `argument_invalid`), 다른 필드는 거부). 본문은 최대 512 KiB. 실행 파일·경로·환경변수는 받지 않는다. 200으로 queued 작업을 돌려주고, dry-run run이면 계획만 돌려준다. 형식 오류는 422다.
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
  M21 수용체 출처(단독 M18만): 네 수용체 키(`receptor_handle`·`receptor_model_number`·`connectivity`·`receptor_instance`) 대신 `"receptor_source": {"kind": "mutation_model", "mutation_model": "obj://…/mutation_model/…", "side": "wild_type_reference" | "mutant"}`를 준다. 둘을 섞거나 네 키 중 하나라도 같이 주면 `invalid_job_arguments`, `receptor_source` 모양이 틀리면(`kind` 포함) `invalid_job_arguments`, handle이 빈 문자열·문자열 아님이거나 `side`가 둘 밖이면 `mutation_model_invalid`. 이 출처의 리간드는 `sdf`만이다(`candidate`는 `mode_source_mismatch`). 정규화 인자는 네 키 대신 `receptor_source`를 담아 출처가 호출 키에 들어간다. `receptor_source`가 없으면 모양·정규화·호출 키가 M21 전과 같다.
  `seed`는 필수, `exhaustiveness`·`num_modes`·`energy_range`·`margin_A`와 코어 고정의 `conformers`는 빼면 기본값으로 채운다. 자유 도킹에 `conformers` 키가 있으면(null 포함) 거절하고 정규화 때 null로 둔다. 정수는 bool·float가 아니어야 한다. 호출 키에는 `acknowledgement`를 뺀 정규화 인자와 고정 환경 pin이 들어간다.
- 입장 거절(작업을 만들지 않음, 예산 없음, 422 `input_invalid`, `detail.reason_code`): `invalid_job_arguments`(모양·범위·종류·다른 run handle), `mode_source_mismatch`, `acknowledgement_missing`, `mutation_model_invalid`(M21 `receptor_source`: 같은 run의 게시·검증된 `mutation_model@1`이 아님, 없는 side, 저장 mmCIF 원자가 모델 `atom_mapping`과 다름, 저장 결합이 원자를 가리키지 않음), `box_invalid`, `box_too_large`(직접 입력 한 변 > 40 Å), `candidate_unknown`, `parent_mismatch`, 수용체 이유(`receptor_invalid`, `receptor_hydrogens_missing`, `receptor_unsupported_residue`, `receptor_altloc_present`, `receptor_instance_unknown`, `receptor_instance_ambiguous`, `receptor_instance_covalent`). `receptor_unsupported_residue`·`receptor_altloc_present`의 `detail`은 `items`(최대 20개: `{residue(7필드), atom_names}` 또는 `{residue, atom_name, altloc}`)와 `total`, `receptor_instance_covalent`의 `detail`은 `bonds`(최대 20쌍의 원자 식별자)와 `total`이다. 환경을 쓸 수 없으면 412 `precondition`(`detail.reason_code`는 capability 이유).
- 작업 실패(과금됨, 결과 객체 없음, `failure{error, reason_code, message, detail}`): `input_invalid` — 수용체·리간드·후보·코어·상자 이유(작업 프로세스가 같은 검사를 다시 함), `resource_exceeded` — 모드당 접촉 500행 초과·결과 4 MiB 초과, `fatal` — `engine_failed`, `engine_output_invalid`, 잘못된 오류 봉투. 시작 때 고정 pin이 바뀌었으면 `precondition`(`worker_version_invalid`). 시간 초과·취소는 결과 없음. dry-run run은 계획만.
- `POST /jobs/{id}/start`는 작업이 끝날 때까지 응답하지 않는다. 화면은 제출 응답의 job id로 `GET /jobs/{id}`·`POST /jobs/{id}/cancel`을 따로 부른다. 도구 `qvina_dock_ligand`는 작업 전용이라 `/commands`로 실행되지 않는다.
- M21 출처 결과: `inputs.receptor` = `{source: {kind, mutation_model, side}, sha256, model_number, connectivity: {kind: "mutation_model_topology"}, removed_instance: null, acknowledgement}`(`handle` 없음), `limitations`는 맨 뒤에 열두째 문장이 붙는다. 결과 목록 행의 `receptor_handle`은 null이다. 이 결과를 읽을 때마다(상세·접촉·포즈·보고서) 출처 모델을 다시 검증하고 저장 mmCIF·사이드카가 제출 때와 같은지 대조하므로, 모델이 검증되지 않으면 이 결과도 검증 실패로 읽히지 않는다. M18 수용체 규칙(원자 수 10,000 등)은 그대로 `receptor_invalid` 등이다. M19 `qvina_batch_dock_v1`은 `receptor_source`를 알 수 없는 키로 거절한다(M19 이유 집합 그대로).

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
- `/capabilities`의 `methods.ligand_docking`(`docking_capability@1`): `{available, status, reason_code, reason, protocol_id, tool_id, engine: "qvina", execution_lane: "durable_job", methods{free, core_fixed}, timeout_s{default: 600, max: 900}, limits{input_bytes_per_file, receptor_atoms, ligand_heavy_atoms, active_torsions, box_side_A, result_bytes, contacts_per_mode}, score_label, limitations, pins, versions}`. 사용할 수 없으면 `available: false`, `reason_code`는 `worker_missing | engine_missing | engine_hash_mismatch | handshake_failed | version_mismatch`, `pins`·`versions`는 null. 서버는 `qvina2` 파일 해시를 재고 작업 모듈 `--handshake`만 실행하며(qvina를 실행하지 않음), 구조가 맞는 handshake만 캐시한다(판정은 매번 다시 함). `limitations`는 고정 문장 전부이며 M21부터 열두째 문장(변이 모델 수용체 출처일 때만 결과에 붙음)까지 12개다.

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
- `{protocol_id: "qvina_batch_dock_v1", args, timeout_s}`. `timeout_s`는 0 초과 7800 이하(이 프로토콜만. API 모델은 M22부터 15000까지 받고 다른 프로토콜은 `JobQueue`가 각자 상한으로 거절한다). 화면은 7800을 보낸다. 호출 키에 들어가지 않는다.
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

## M20 변이 후보

규칙은 `docs/business-rules.md` "변이 후보 (M20, `generate_mutation_candidates`)". 읽기 호출은 run 객체만 읽고 도구·작업·이벤트·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 읽기 라우트의 handle은 쿼리(`?handle=`)가 아니라 **URL 경로**에 그대로 넣는다(`obj://…`의 슬래시 포함, `{handle:path}`). 새 쓰기 라우트는 없다.

### 계산: `POST /runs/{id}/commands` `{tool: "generate_mutation_candidates", args}`
```json
{"structure": "obj://…/prepared_structure/…",
 "sources": {"pocket": null | {"pocket_set": "obj://…/pocket_set/…", "ranks": [1, 3]},
             "ligand_shell": null | {"radius_A": 5.0},
             "residues": [{"model_number": 1, "chain_auth": "A", "seq_auth": 139, "icode": "", "resname": "LEU",
                           "chain_label": "A", "seq_label": 139}]},
 "ligand": null | {<잔기 참조>},
 "allowed_residues": "ACDEFGHIKLMNPQRSTVWY" | ["A", "G", "W"],
 "protected_residues": [<잔기 참조>], "released_residues": [<잔기 참조>],
 "metal_contact_A": 3.0, "numbering_map": null | "obj://…", "annotation": null | "obj://…",
 "catalytic_annotation": null | "obj://…/reaction_knowledge/…"}
```
- 잔기 참조·리간드 선택자: `model_number`·`chain_auth`·`seq_auth`·`icode`·`resname` 필수, `chain_label`·`seq_label` 선택(null도 값). 기본값: `ligand` null, `allowed_residues` 20종 전부, 목록 `[]`, `metal_contact_A` 3.0(1.0–5.0), `radius_A` 5.0(1.0–12.0), `catalytic_annotation` null(M26, 호출 키에 늘 들어감). 목록·`ranks`는 각 최대 400.
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `mutation_candidate_set`, schema `mutation_candidate_set@1`, summary `{structure, positions, candidate_positions, excluded_positions, released_positions, candidates, exclusion_reason_counts, source_counts, null_result}`. 후보 0개면 `null_result: true`. 같은 정규화 인자면 같은 handle(훅이 `bound`를 돌려주지 않음). dry-run run에서도 실행해 저장한다. M26부터 도구가 만드는 집합은 모두 v2(`method_version` `mw.mutation_candidates/v2`, `exclusion_reason_counts` 일곱 키)이고 저장된 v1 집합은 그대로 읽힌다.
- 실패(도구 실패 본문, `detail.reason_code`):
  - 422 `input_invalid`, 사전 검사 훅(도구 구현을 부르지 않음), 이 순서: `unknown_field`, `structure_invalid`, `no_position_source`, `argument_invalid`, `allowed_residues_invalid`, `residue_invalid`, `duplicate_residue`, `protect_release_conflict`, `ligand_required`, `ligand_invalid`, `pocket_set_invalid`, (`numbering_map_invalid`, `annotation_invalid`, `catalytic_annotation_invalid`), `structure_mismatch`, `pocket_rank_invalid`, `pocket_residue_mismatch`, `annotation_map_mismatch`. handle 네 개의 종류·run 검사(`pocket_set_invalid`·`numbering_map_invalid`·`annotation_invalid`·`catalytic_annotation_invalid`)를 모두 한 뒤 구조 일치(`structure_mismatch`, 반응 결과의 `structure.handle` 포함)를 본다. `catalytic_annotation_invalid`는 handle 아님·다른 run·`reaction_knowledge@1`이 아님, 또는 그 객체가 `reaction_knowledge.validated_result`를 통과하지 못할 때다.
  - 429 `resource_exceeded` `too_many_positions`: `detail: {reason_code, positions, limit: 400}`. 429 `resource_exceeded` `catalytic_list_too_long`(M26): `detail: {reason_code, list: "conflicts"|"unmatched", count, limit: 400}`. 둘 다 아무것도 저장하지 않는다.
  - 422 `input_invalid` `candidate_set_invalid`: 구현이 만든 결과가 `validated_set`을 통과하지 못함(저장하지 않음. 정상 입력에서는 나지 않아야 하는 내부 일관성 실패).
- 결과 객체의 필드는 business-rules "결과 객체"와 같고, v2 저장 형식(`parameters.catalytic_annotation`, `positions[].protection.catalytic`, `protection_checks.catalytic_residue_database`의 v2 키, 일곱 제외 사유, 셋째 한계 문장 변형)은 business-rules "v2 세대: M-CSA 촉매 잔기 보호 (M26)"다.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/mutation_candidate_sets?offset&limit` | limit 1–100(기본 50) | `mutation_candidate_set_list@1`: `{total, offset, limit, rows:[{handle, created_seq, valid, structure, model_number, ligand, sources_used{pocket, ligand_shell, user}, klifs_status, numbering_map, annotation, counts, null_result, catalytic_status}]}`. 최신 순, `created_seq`는 객체를 만든 이벤트 순번. 행마다 다시 검증하고 실패한 행은 `valid: false`, 나머지 필드 null(옛 숫자를 보이지 않음). `klifs_status` = `protection_checks.klifs_key_sites.status`, `catalytic_status`(M26) = `protection_checks.catalytic_residue_database.status`(v1 `not_available`, v2 `not_checked`·`checked`) | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/mutation_candidate_sets/{handle}` | — (쿼리 없음) | `{schema: "mutation_candidate_set_detail@1", handle, result, total_positions, total_candidates, catalytic_status, meta}`(`catalytic_status`는 M26에 더한 키, 기존 키·값은 그대로). `result`는 저장 객체에서 `positions`·`candidates`를 뺀 것(`structure`, `parameters`, `ligand`, `pockets`, `protection_checks`, `released_residues`, `counts`, `null_result`, `limitations` 등), `meta`는 객체 메타(`handle, kind, schema, fmt, size, produced_by, summary, null_result`) | 404 없는 handle, 422 `input_invalid`(다른 종류·형식), 422 `method_evidence_invalid`(검증 실패) |
| `GET /runs/{id}/mutation_candidate_sets/{handle}/positions?status&source&exclusion_reason&chain_auth&sort&offset&limit` | `status` ∈ `candidate`·`excluded`, `source` ∈ `pocket`·`ligand_shell`·`user`, `exclusion_reason` ∈ v2 일곱 사유(v1 집합에 `catalytic_residue`를 주면 거절이 아니라 빈 목록), `chain_auth`(정확히 같음), `sort` ∈ `order`(기본)·`ligand_distance`(오름차순, 값 없는 행은 늘 끝, 동점은 `order`), limit 1–100(기본 50) | `mutation_position_page@1`: `{handle, filters{status, source, exclusion_reason, chain_auth}, sort, total, offset, limit, rows}`. 행은 저장된 위치 행 그대로, `total`은 필터 뒤 개수 | 404, 422(닫힌 값 밖, 모르는 파라미터, 다른 종류), 422 `method_evidence_invalid` |
| `GET /runs/{id}/mutation_candidate_sets/{handle}/candidates?position_index&to&offset&limit` | `position_index` ≥ 0, `to` ∈ 20종 한 글자, limit 1–200(기본 100) | `mutation_candidate_page@1`: `{handle, filters{position_index, to}, total, offset, limit, rows:[{index, position_index, residue, standard_resname, from, to}]}`. 잔기·표준 이름은 위치 행에서 복사, `total`은 필터 뒤 개수 | 404, 422, 422 `method_evidence_invalid` |

- 하위 경로 라우트(`/positions`, `/candidates`)가 상세 라우트보다 먼저 등록되어 있다(경로 handle이 슬래시를 담으므로).
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 이 종류를 읽을 수 있지만 `validated_set`을 거치지 않는다(M12·M17–M19와 같은 관례). 화면은 위 네 읽기만 쓴다.

### capability와 도구 목록
- `/capabilities`의 `methods.mutation_candidates`: 항상 `{available: true, reason_code: null, reason: null}`(run 객체만 읽음, M16 `reference_site_annotation`과 같음).
- `GET /tools`(기본 `levels=L2,L4`)에 `generate_mutation_candidates`(L2, `accepts: {structure: [prepared_structure]}`, `emits: mutation_candidate_set`, `cost_class: cheap`)가 나온다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <mutation_candidate_set>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "mutation_candidates"`, `render_version: "mutation_candidates_markdown@1"` | `"mutation_candidates_markdown@2"`, `status: "complete"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "mutation_candidate_set@1"`, `result_sha256`, 결과에서 복사한 `method_version, structure, parameters, ligand, pockets, protection_checks, released_residues, counts, null_result, limitations`, `claims`, `provenance{call_id, tool, tool_version, created_event_seq, completed_event_seq}`, `evidence_statement`, `snapshot`, `markdown_handle`(@2만 `reference_snapshot_sets` 하나를 더함)이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 종류 이름 "변이 후보 보고서").
- 형식 버전(M28): 새 보고서는 참조값을 인용할 때(집합이 `numbering_map`·`annotation`을 이름 붙였거나 `reference_mcsa_entry_id` 주장이 있을 때) `@2`, 아니면 `@1`이다. `@2`의 `reference_snapshot_sets[]`는 인용한 가족마다 `{set_schema: "reference_snapshot_set@1", copied_from, reference_set_handle, snapshot_set, klifs_terms}`(번호 대응, 주석만 주었으면 주석이 기록한 번호 대응) 또는 `{set_schema: "reaction_reference_set@1", copied_from, snapshot_set}`(반응 지식 결과)이고, Markdown은 `@1` 줄 전부에 "## 참조 스냅샷" 절(하위 제목 "### 번호 대응·주석의 참조 세트"·"### 촉매 잔기 주석의 반응 참조 세트")을 "## Limitations" 앞에 더한다. 요청 모양·응답 모양·라우트는 바뀌지 않았다. `/reports/selected`·`/reports/download`·`/reports` 목록은 두 버전을 모두 받고, 이미 저장된 `@1` 보고서는 같은 바이트로 다시 열린다. 주석의 세트가 번호 대응의 세트와 다르거나(`mutation_reference_set_mismatch`), 출처표를 바꾼 `@2`, 인용이 없는데 `@2`인 보고서, `render_version`을 바꾼 보고서는 422 `report_evidence_invalid`다. 규칙은 `docs/business-rules.md` "참조 스냅샷 출처표와 형식 버전 (M28)".
- 주장 statement ID: `computed` — `position_count`, `position_status_count`, `released_position_count`, `candidate_count`, `exclusion_reason_count`, `source_position_count`, `numbering_status_count`(번호 대응이 있을 때), `ligand_min_distance_A`(`positions[i].ligand_min_distance_A` 인용, 단위 `angstrom`, 0.01 `ROUND_HALF_UP`), `protection_check_status`(다섯 검사), `protection_check_count`(`checked`인 검사만. v2의 `catalytic_residue_database.matched_rows`·`conflict_rows`·`unmatched_rows` 포함), M26 v2만 `catalytic_covered_chain_count`(`checked`일 때만). `exclusion_reason_count`의 `catalytic_residue`(v2)는 덮인 체인이 있을 때만 주장이 있다. `reference_value` — `reference_uniprot_accession`, `reference_klifs_site_label`, M26 v2 `reference_mcsa_entry_id`(`positions[i].protection.catalytic[j].mcsa_id`, 반응 결과 handle 인용)(`reference: {note: "참조 스냅샷 값, 계산 아님", reference_object}`). v2 보고서는 만들고 다시 열 때 `catalytic_annotation`의 반응 결과를 다시 검증하고 같은 구조인지, 그 결과로 다시 만든 촉매 검사 칸·`protection.catalytic`이 집합과 같은지 대조한다(`mutation_catalytic_annotation_invalid`·`mutation_catalytic_annotation_structure_mismatch`·`mutation_catalytic_value_mismatch`). v1 집합의 manifest·주장·Markdown 바이트는 그대로다. 주장 필드는 M15 보고서와 같다. 다른 statement의 필드 경로, 계산값으로 참조 필드 인용, 틀린 개수·반올림, 검사하지 않은 항목의 숫자 주장, 해석 문장, 다른 run·다른 종류의 결과, 변조된 집합·보고서는 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `budget`.

## M21 변이 구조 모델링

규칙은 `docs/business-rules.md` "변이 구조 모델링 (M21, `openmm_mutation_model_v1`)". 읽기 호출은 run 객체만 읽고 도구·작업·이벤트·OpenMM·PDBFixer·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. handle은 URL **경로**에 그대로 넣는다(`{handle:path}`, M20과 같음). 새 쓰기 라우트는 없다(같은 조건 도킹은 기존 `POST /jobs`로 M18 작업 둘).

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
```json
{"protocol_id": "openmm_mutation_model_v1",
 "args": {"candidate_set": "obj://…/mutation_candidate_set/…", "candidate_index": 0, "seed": 20261004,
          "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "contact_cutoff_A": 4.0},
 "timeout_s": 120}
```
- `contact_cutoff_A`는 빼면 4.0(2.5–6.0). `timeout_s`는 빼면 120, 0 초과 240 이하(호출 키에 들어가지 않음). 완료 작업의 `artifacts.mutation_model`. 같은 정규화 인자·같은 고정 pin이면 기존 작업을 돌려준다(새 작업·과금 없음). 작업 기록의 `method`는 `{worker_sha256, dependency_sha256{파일 다섯 개}, method}`이고 시작 때 다시 맞춘다(다르면 412 `worker_version_invalid`).
- 입장 거절(작업을 만들지 않음, 예산 없음, 도구 실패 본문 `detail.reason_code`), 이 순서:
  - 422 `input_invalid`: `unknown_field`, `confirmation_missing`, `argument_invalid`(인자·`timeout_s`. 큐가 막는 `argv`·`executable`·`module`·`env`·`path`·`cwd`·`fixture` 키는 `unknown_field`, 객체가 아닌 `args`는 `argument_invalid`), `candidate_set_invalid`, `candidate_unknown`, `structure_invalid`, `residue_mismatch`.
  - (dry-run run은 여기서 계획만 돌려준다.)
  - 412 `precondition`: `process_identity_unavailable`, `openmm_unavailable`, `pdbfixer_unavailable`(예약·과금 전).
  - 422 `input_invalid` `openmm_preflight_failed`: `detail{reason_code, m7_reason(M7 코드 또는 null), m7_message}`. 사전 검사 투영과 후보가 맞지 않으면 `residue_mismatch`·`structure_invalid`.
  - 429 `resource_exceeded`: 스테이징 입력 4,000,000 B 초과(`detail.limit: "staged_input_bytes"`).
- 작업 실패(과금됨, 결과 객체 없음, `failure{error, reason_code, message, detail}`): `input_invalid` — `mutation_modeling_failed`, `unexpected_atoms_added`, `coordinates_changed`, `topology_unsupported`. `fatal` — `energy_invalid`, `engine_failed`, 잘못된 오류 봉투. `resource_exceeded` — `too_many_contacts`(구조당 2,000행 초과), 작업 출력·결과 64,000,000 B 초과. 시간 초과·취소는 결과 없음. 게시 직전에 취소가 들어오면 아무것도 저장하지 않는다.
- 성공하면 객체 셋을 저장한다: `mutation_model_structure@1`(fmt `cif`) 둘과 `mutation_model@1` 하나(summary `{candidate_set, candidate_index, from, to, structure, seed}`). 도구 `openmm_mutation_model`은 작업 전용이라 `/commands`로 실행되지 않는다.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/mutation_models?offset&limit` | limit 1–100(기본 50) | `mutation_model_list@1`: `{total, offset, limit, rows:[{handle, created_seq, valid, candidate{candidate_set, candidate_index, residue, from, to, mutant_resname}, structure, parameters}]}`. 최신 순. 행마다 다시 검증하고 실패한 행은 `valid: false`, 나머지 null | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/mutation_models/{handle}` | — (쿼리 없음) | `{schema: "mutation_model_detail@1", handle, result, meta}`. `result`는 저장 객체에서 구조 항목마다 `final_bonds`·`atom_mapping`·접촉 `rows`를 뺀 것(접촉은 `cutoff_A`·`excluded_bond_distance`·`count`·`residue_count`만) | 404 없는 handle, 422 `input_invalid`(다른 종류), 422 `method_evidence_invalid` |
| `GET /runs/{id}/mutation_models/{handle}/contacts?structure=&page&page_size` | `structure` ∈ `wild_type_reference`·`mutant`(필수), `page` ≥ 1(기본 1), `page_size` 1–200(기본 100) | `mutation_model_contact_page@1`: `{handle, structure, mutated_residue, cutoff_A, excluded_bond_distance, total, page, page_size, rows:[{index, atom_name, element, partner_residue(7필드), partner_atom_name, partner_element, distance_A}]}`. 저장 순서 그대로 | 404, 422, 422 `method_evidence_invalid` |
| `GET /runs/{id}/mutation_models/{handle}/structure?side=` | `side` ∈ `wild_type_reference`·`mutant`(필수) | 저장 mmCIF 바이트 그대로(모델의 `structure_sha256`과 대조), `chemical/x-mmcif`, 첨부 이름 `protview-mutation-model-<handle 해시 앞 12>-<side>.cif`, `Cache-Control: private, no-store` | 404, 422, 422 `method_evidence_invalid` |
| `GET /runs/{id}/mutation_models/{handle}/docking_pairs` | — (쿼리 없음) | `mutation_model_docking_pairs@1`: `{handle, score_label(M18 점수 문구), total, pairs:[{index, first_submitted_seq, condition{ligand, mode, box, parameters, method_pins_sha256}, both_published, sides{wild_type_reference, mutant: {side, job_id, job_status, submitted_seq, result_handle, score_kcal_mol, score_mode, reason_code, reason}}}], starts_job: false}`. 조건 묶음은 첫 제출 순서. `both_published`일 때만 두 쪽에 결과 handle과 저장된 첫 모드 행 점수(모드 0개면 `no_modes`), 아니면 쪽마다 작업 상태와 점수 null + 닫힌 이유(`not_submitted`, `job_not_finished`, `job_failed`, `job_cancelled`, `job_interrupted`, `result_invalid`, `other_side_missing`). `job_status`는 작업이 없으면 `not_submitted` | 404, 422, 422 `method_evidence_invalid`(모델), 409 `run_corrupt`(도킹 작업 기록) |

- 하위 경로 라우트(`/contacts`, `/structure`, `/docking_pairs`)가 상세 라우트보다 먼저 등록되어 있다(경로 handle이 슬래시를 담으므로).
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 이 종류를 읽을 수 있지만 `validated_result`를 거치지 않는다(M12·M17–M20과 같은 관례). 화면은 위 다섯 읽기만 쓴다.

### capability와 도구 목록
- `/capabilities`의 `methods.mutation_model`(`mutation_model_capability@1`): `{available, reason_code, reason, versions{openmm, openmm_engine_build, pdbfixer} | null, protocol_id, tool_id, execution_lane: "durable_job", result_schema, method_version, timeout_s{default: 120, max: 240}, contact_cutoff_A{default: 4.0, min: 2.5, max: 6.0}, limits{protein_heavy_atoms: 6000, contact_rows_per_structure: 2000, output_bytes: 64000000}}`. 사용할 수 없으면 `reason_code`는 `openmm_unavailable | pdbfixer_unavailable | process_identity_unavailable`이고 `versions`는 null. PDBFixer는 `importlib.metadata`로만 확인한다.
- `GET /tools?levels=…L3…`에 `openmm_mutation_model`(L3, `emits: mutation_model`, `cost_class: expensive`, `execution_lane: "durable_job"`, `submit_protocol_id: "openmm_mutation_model_v1"`)이 나온다(기본 `levels=L2,L4`에는 없음).

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <mutation_model>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "mutation_model"`, `render_version: "mutation_model_markdown@1"`, `status: "complete"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "mutation_model@1"`, `result_sha256`, 결과에서 복사한 `method_version, candidate, structure, parameters, method, excluded_components, comparison, protonation_differences, limitations`, `structures`(행을 뺀 요약), `claims`, `provenance`, `evidence_statement`, `snapshot`, `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 이름 "변이 구조 모델 보고서").
- 주장은 모두 `computed`. statement ID: `candidate`, `openmm_potential`, `mutated_residue_sasa`, `contact_cutoff`, `contact_count`, `contact_residue_count`, `disulfide_pair_count`, `protonation_difference_count`, `added_heavy_atom_count`. 다른 statement의 필드 경로, 틀린 값·반올림·개수, 차이·변화 주장, 도킹 점수 주장, 해석 문장, 다른 run·다른 종류의 결과, 변조된 모델·보고서는 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `budget`.

## M22 리간드 GA 설계

규칙은 `docs/business-rules.md` "리간드 GA 설계 (M22, `qvina_ga_dock_v1`)". 읽기 호출(시작 전 확인 POST 포함)은 run 객체와 가져오기 바이트(수용체 M11 검사, gemmi)만 읽고 도구·작업·이벤트·예약·한도 변경·RDKit·Meeko·qvina·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 요약 handle은 URL **경로**에 그대로 넣는다(`{handle:path}`, M20과 같음). 새 가져오기 종류는 없다. 개체 결과는 M18 `/docking/results/*`로 읽는다.

### GA 인자 (`args`, 시작 전 확인·증액 승인·작업 제출이 같은 본문)
```json
{"receptor_handle": "obj://…", "receptor_model_number": 1,
 "connectivity": {"kind": "pdb_conect" | "sidecar", "sidecar_handle": null | "obj://…"},
 "receptor_instance": null | {<잔기 7필드>},
 "candidate_set_handle": "obj://…/ligand_candidate_set/…", "parent_sdf_handle": "obj://…/chemical_raw_input/…",
 "filter": {"ranges": {}, "pains_exclude": false},
 "box": <M18 상자>, "parameters": <M18 자유 도킹 값, seed = 도킹 seed>,
 "acknowledgement": {"keep_input_protonation": true, "tool_assigned_types_charges": true, "rigid_no_optimization": true},
 "ga": {"seed": 11, "population_size": 12, "generations": 5, "elite_count": 2, "tournament_size": 2,
        "neighbor_count": 10, "random_fraction": 0.2, "patience": 3, "max_new_dockings": 60, "total_s": 7200}}
```
`filter`·`acknowledgement`는 빼도 된다(`filter` 기본 `{}`, 확인은 M18 규칙). `ga`의 키는 열 개 모두 필수이고 범위·교차 규칙은 business-rules 표다. `mode`·`ligand`·그 밖의 키는 `invalid_job_arguments`.

### 입장 거절 (작업을 만들지 않음, 예산 없음, 도구 실패 본문 `detail.reason_code`), 이 순서
- 422 `input_invalid`: `invalid_job_arguments`(모양·범위·교차 규칙·`timeout_s`·필터 사양·검증되지 않는 후보 집합·다른 run handle), M18/M19 입장 이유(첫 적격 후보를 대표로: `parent_mismatch`, `acknowledgement_missing`, `box_invalid`, `box_too_large`, 수용체 이유 7개 등, `detail`의 거부 목록 모양은 M18과 같음), `ga_pool_too_small`(`detail{reason_code, eligible_count, population_size}`), `ga_reuse_too_large`(`detail{reason_code, limit_bytes}`).
- 412 `precondition`: 환경을 쓸 수 없음(`detail.reason_code`는 capability 이유).
- 429 `resource_exceeded`: `ga_limit_raise_required`, `detail: {reason_code, needed{expensive_calls, wall_clock_s}, shortfall{expensive_calls, wall_clock_s}}`. 작업 제출에서만 난다(시작 전 확인은 부족분을 숫자로 돌려주고 증액 승인은 부족분을 올린다).

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
- `{protocol_id: "qvina_ga_dock_v1", args, timeout_s}`. `timeout_s`는 이 프로토콜(M23 서열 GA도 같음)만 `ga.total_s + 600` 이상 15000 이하이고 기본값이 없다(빠지면 `invalid_job_arguments`). 화면은 늘 `total_s + 600`을 보낸다. 호출 키에 들어가지 않는다. API 모델 `JobSubmit.timeout_s`는 15000까지 받는다: 이 프로토콜의 모델 거절(`timeout_s` > 15000, `args` 모양)은 닫힌 이유 `invalid_job_arguments`(도구 실패 본문)로 바꾸고, 다른 프로토콜은 `JobQueue`가 각자 상한(120, 240, 900, 7800)으로 거절한다. 그래서 다른 프로토콜의 7800 < `timeout_s` ≤ 15000 요청은 M22부터 422 `{"ok": false, "error": "input_invalid", "message": "invalid job timeout", …}`이다(전에는 `{"detail": {"error": "input_invalid", "message": "invalid job request"}}`). 15000 초과는 전처럼 요청 모델 오류다.
- 같은 GA 호출 키의 작업이 `queued`·`claimed`·`running`이거나 그 키의 검증된 `complete` 요약을 게시한 작업이 있으면 200으로 그 작업을 돌려준다(새 작업 없음). `partial` 요약만 있으면 새 작업을 만든다. dry-run run은 계획만 돌려준다.
- 첫 비싼 계산이면 `/start`가 409 `approval`(`tool: "qvina_ga_design"`)을 돌려주고 `/jobs/approve`가 기록한다(작업 승인 허용 목록에 `qvina_ga_design`). `/start`는 작업이 끝날 때까지 응답하지 않는다. 화면은 제출 응답의 job id로 `GET /jobs/{id}`를 폴링하고 `POST /jobs/{id}/cancel`로 취소한다.
- 시도는 1회다. `POST /jobs/{id}/retry`는 412 `precondition`이다. 시작 때 고정 pin(M18 pin + GA 작업 모듈·상수 해시)이 바뀌었으면 412 `precondition`(`worker_version_invalid`). 시작 때 재사용 계획의 크기가 128 MiB를 넘으면 예약 전에 422 `ga_reuse_too_large`.
- 작업 기록 상태: 작업 모듈이 스스로 끝나면(자기 전체 시계·출력 총량 정지 포함) `done`(`artifacts.ligand_ga_result` = 요약 handle, `output_handles`는 요약 하나), 사용자 취소는 `cancelled`, 작업 마감은 `failed`(`failure.error: "resource_exceeded"`, "job timeout"), 크래시·자원 한도·출력 오류는 `failed`, 서버 재시작 복구는 `interrupted`. `done`이 아니어도 요약이 게시되었을 수 있다(아래 `ga.summary_handle`). 첫 개체 전(`prepared.json` 전)에 멈춘 작업은 `failed`(사용자 취소면 `cancelled`)이고 요약이 없다. 요약을 만들 수 없으면 `failed`(`fatal`, "invalid scientific output")이고 이미 게시된 개체 결과는 남는다.
- GA 작업의 `GET /jobs`·`GET /jobs/{id}`·`/start` 응답에는 `ga: {pool{size, eligible_count, filter_excluded_count}, reserved_units, reused_planned, individuals_started, individuals_result_files, individuals_finished, generation_records, generations_complete, summary_handle, summary_status, summary_stop_reason}`가 붙는다. 개수는 이 시도 디렉터리의 스테이징 파일 수다: `individuals/*.started`·`*.result.json`·`*.status.json`(새 도킹만, 재사용 개체는 파일이 없음), `generations/*.json`과 그중 `complete: true`인 수. `reused_planned`는 시작 때 재사용 계획의 개체 수. `summary_handle`은 어떤 종료 상태든 요약이 게시되면 채워지고, `summary_status`·`summary_stop_reason`은 그 요약을 검증해 읽은 값(검증 실패면 null)이다. 요약 전에는 객체를 읽지 않는다.

### 읽기와 증액 승인

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs/{id}/ligand/ga/preflight` | GA 인자(본문 최대 512 KiB, 중복 키 거부) | 200 `ligand_ga_preflight@1`: `{starts_job: false, capability, score_label, budget{expensive_calls, wall_clock_s}, remaining{…}, admission{admitted, error, reason_code, message, detail}, selection_sha256, pool{size, eligible_count, filter_excluded_count}, reusable_count, reserved_units, max_new_dockings_expected, needed{expensive_calls, wall_clock_s}, shortfall{…}, full_run_may_be_partial, ga(정규화 값), statements:[{id: "G1", text}], existing_job: {job_id, status, summary_handle} \| null}`. 입장 거절(1–4)과 환경 없음도 200이며 `admission.admitted: false`, 거절 이유·`detail`만 있고 풀·재사용·필요량 필드는 null. 예산 부족은 거절이 아니라 `shortfall`이다. `max_new_dockings_expected` = `reserved_units`(재사용과 무관하게 예약) | 413(본문), 422(JSON·쿼리), 404 없는 run |
| `GET /runs/{id}/ligand/ga/results?offset&limit` | limit 1–100(기본 50) | `ligand_ga_list@1`: `{total, offset, limit, rows:[{handle, published_seq, valid, reason_code, job_id, attempt_id, status, stop_reason, generations_done, new_dockings_used, reused_count, reserved_units, pool, candidate_set_handle, selection_sha256, ga}]}`. 요약 handle의 첫 게시 순서로 최신 순. 행마다 다시 검증하고 실패한 행은 `valid: false`, `reason_code: "evidence_invalid"`, 나머지 null | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/ligand/ga/results/{handle}` | — (쿼리 없음) | `ligand_ga_detail@1`: `{handle, job_id, attempt_id, published_seq, score_label, score_column_label, score_row_label, statements:[{id, text}](저장 G 목록), summary(저장 요약 그대로), generations:[{index, complete, min_score, max_score, individuals:[저장 개체 + detail_available]}], meta}`. `detail_available`은 결과 handle이 있을 때 true | 404 없는 handle, 422 `input_invalid`(다른 종류), 422 `method_evidence_invalid` |
| `GET /runs/{id}/ligand/ga/results/{handle}/individual?candidate_id=` | 후보 id(필수, 이름이 아니라 id로만) | `ligand_ga_individual@1`: `{summary_handle, candidate_id, evaluation, eval_index, state, reason_code, score, result_handle, appearances:[{generation, position, origin}], score_label, score_row_label, m18_detail}`. `m18_detail`은 결과가 있으면 M18 결과 상세 읽기와 같은 값, 없으면 null | 404, 422(`candidate_id` 없음·이 GA의 개체가 아님, 다른 종류), 422 `method_evidence_invalid` |
| `POST /runs/{id}/ligand/ga/limit_approval` | GA 인자(본문 최대 512 KiB) | 200 `{raised, selection_sha256, reserved_units, needed, shortfall_before, increase{expensive_calls, wall_clock_s}, limits_before, limits_after, shortfall_after, event_seq, budget}`. 부족분이 없으면 `raised: false`, `increase` 0, `event_seq: null`, 이벤트 없음(멱등) | 422 입장 거절(위와 같은 이유), 412 `precondition`(dry-run run `dry_run`, 환경 없음), 409 `{"ok": false, "error": "cancelled", "message": "run cancelled"}`(취소된 run, 아무것도 쓰지 않음), 503 `transient`(run 실행 잠금이 잡혀 있음, 예: GA 실행 중), 413 |

- 하위 경로 라우트(`/individual`)가 상세 라우트보다 먼저 등록되어 있다(경로 handle이 슬래시를 담으므로).
- 증액 승인은 사람이 화면에서 누르는 이 경로 하나뿐이다(M19 라우트와 따로). 도구·분석 흐름 단계·뷰어 명령·작업 인자로 부를 수 없고, 첫 비싼 계산 승인을 기록하지 않으며 예약·과금·환불하지 않는다. 필요량은 요청에서 다시 계산하고(`timeout_s`는 `total_s + 600`으로 본다), 부족분은 호출 시점의 run 실행 잠금 안에서 과금된 사용량 기준으로 다시 계산한다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 `ligand_ga_result`를 읽을 수 있지만 검증을 거치지 않는다(M12·M17–M21과 같은 관례). 화면은 위 읽기와 `/docking/results/*`만 쓴다.

### 이벤트
- `ligand_ga_individual_published {job_id, attempt_id, eval_index, candidate_id, handle}`: 작업 프로세스 그룹 정리 확인 뒤 새 도킹 개체의 결과 하나를 게시할 때. 이 이벤트가 그 결과의 게시 증거이며(요약 게시가 없어도) M18 읽기·보고서·M18·M19·GA 재사용이 받아들인다.
- `ligand_ga_published {job_id, attempt_id, summary_handle, reused_count}`: 모든 개체 게시 뒤 요약을 게시할 때(마지막).
- `job_dispatch_intent`에 `ga_reused: [{candidate_id, handle}]`가 붙고, `budget_reserved.expensive_calls`는 `reserved_units`다. 작업 기록 `job_submitted.job`에는 `method`(M18 pin)와 `ga_method`(`{ga_worker_sha256, ga_constants_sha256}`), `selected`(`ligand_ga_selection@1`: 인자, 수용체·사이드카·후보 집합·부모 기록, 풀 `[{index, candidate_id, eligible}]`, `pool_sha256`, `selection_sha256`. 후보마다의 M18 선택은 없음)가 있다.
- `budget_limit_updated {limits, by: "human", context{purpose: "ligand_ga_limit_raise", selection_sha256, reserved_units, needed, shortfall, increase, limits_before, limits_after}}`: 증액 승인. 재생은 `limits`만 읽는다.

### capability와 도구 목록
- `/capabilities`의 `methods.ligand_ga_design`(`ligand_ga_capability@1`): `{protocol_id: "qvina_ga_dock_v1", tool_id: "qvina_ga_design", engine: "qvina", execution_lane: "durable_job", available, status, reason_code, reason, pins, ga_pins{ga_worker_sha256, ga_constants_sha256}, method: "qvina_free_v1", ga_ranges{키: {min, max, default}}, timeout_s{max: 15000, finish_margin: 600}, limits{max_pool, per_candidate_s, max_new_dockings, total_s_max, output_bytes, summary_bytes, reuse_staging_bytes}, score_label, score_row_label, statements{G1, G2, G3}}`. `ligand_docking`이 사용 가능하고, GA 작업 모듈·상수 파일이 있고, GA 작업 모듈 `--handshake`(같은 고정 인터프리터, 프로토콜·세 모듈 해시 확인, 파일 해시 키로 캐시)가 맞을 때만 사용 가능. 아니면 `available: false`, `reason_code`는 M18 집합(`ligand_docking`의 이유를 그대로, GA 파일 없음은 `worker_missing`, GA handshake 실패는 `handshake_failed`), `pins`·`ga_pins`는 null이고 범위·한도·문장 필드는 없다.
- `qvina_ga_design`은 `config/tools.yaml`의 L3 명세(`emits: ligand_ga_result`, `cost_class: expensive`)로 등록되고 작업 전용으로 표시되지만, `GET /tools`(L3 포함)에는 나오지 않는다(M18·M19 작업 도구와 같음, 목록은 OpenMM·M21 작업 도구만 덧붙임). `/commands`로 실행되지 않는다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <ligand_ga_result>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "ligand_ga"`, `status: "complete"`, `render_version: "ligand_ga_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "ligand_ga_result@1"`, `result_sha256`, 요약에서 복사한 `protocol, engine, candidate_set_handle, parent_sdf_handle, receptor, pins, call_key, selection_sha256, box, parameters, filter, ga, pool, stop_reason, generations_done, new_dockings_used, reused_count, reserved_units, generations`, `ga_status`, `method`, `score_label`, `score_column_label`, `score_row_label`, `claims`, `provenance{ligand_ga{job_id, attempt_id, protocol_id, tool_id, created_event_seq, completed_event_seq}, individuals:[{result_handle, job_id, attempt_id, protocol_id}]}`, `evidence_statement`, `limitation_ids`, `limitations`, `snapshot`, `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 종류 이름 "리간드 GA 설계 보고서").
- 주장은 모두 `evidence_kind: "computed"`. statement ID: `receptor_input`, `removed_instance`, `candidate_set_input`, `box`, `parameter`, `ga_parameter`, `pool_count`, `run_count`, `generation_count`, `generation_score_range`, `individual_score`(요약 `generations[g].individuals[p].score`), `individual_result_score`(개체 결과 `modes[0].score_kcal_mol`, `source_kind: "docking_result"`). 점수 주장은 `scored` 개체만, `row_selector: {generation, position}`. 주장 필드는 M18과 같다. 점수 없는 개체의 점수 주장, 다른 statement의 필드 경로, 틀린 반올림·개수, 해석 문장, 요약 점수와 개체 결과 첫 모드 점수의 불일치, 변조·미완료 요약은 422 `report_evidence_invalid`.
- 스냅숏 키: `event_seq`, `time_utc`, `run_egress_mode`, `capability`(`available`, `status`, `reason_code`, `pins`, `ga_pins`), `budget`(올라간 한도 포함).

## M23 서열 GA 설계

규칙은 `docs/business-rules.md` "서열 GA 설계 (M23, `sequence_ga_dock_v1`)". 읽기 호출(시작 전 확인 POST 포함)은 run 객체와 가져오기 바이트(리간드 SDF, 이 run의 M7 사전 검사 투영)만 읽고 도구·작업·이벤트·예약·한도 변경·PDBFixer·RDKit·Meeko·qvina·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다. 요약 handle은 URL **경로**에 그대로 넣는다(`{handle:path}`, 하위 경로 라우트가 상세보다 먼저 등록되어 있다). 새 가져오기 종류는 없다(리간드 SDF는 M11 `ligand_sdf` 가져오기). 개체 도킹 결과는 M18 `/docking/results/*`로 읽는다.

### GA 인자 (`args`, 시작 전 확인·증액 승인·작업 제출이 같은 본문)
```json
{"candidate_set": "obj://…/mutation_candidate_set/…",
 "ligand": {"source": "sdf", "sdf_handle": "obj://…/chemical_raw_input/…"},
 "box": {"source": "ligand_range", "margin_A": 8.0} | {"source": "manual", "center_A": [0, 0, 0], "size_A": [20, 20, 20]},
 "parameters": {"seed": 20261005, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3},
 "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7",
 "acknowledgement": {"keep_input_protonation": true, "tool_assigned_types_charges": true, "rigid_no_optimization": true},
 "ga": {"seed": 21, "population_size": 8, "generations": 5, "elite_count": 2, "tournament_size": 2,
        "crossover_fraction": 0.5, "random_fraction": 0.2, "max_mutations": 3, "patience": 3,
        "max_new_evaluations": 32, "total_s": 7200}}
```
`acknowledgement`는 M18 규칙(M18 세 항목이 모두 true여야 하며 빼거나 하나라도 아니면 입장 2단계 `acknowledgement_missing`, 두 리터럴 `selection_policy`·`hydrogen_policy`가 정확히 같지 않으면 `confirmation_missing`)이고 `ga`의 키는 열한 개 모두 필수다. `mode`·수용체 키(`receptor_*`·`connectivity`·`receptor_instance`·`receptor_source`)·`contact_cutoff_A`·`filter`·그 밖의 키는 거부한다.

### 입장 거절 (작업을 만들지 않음, 예산 없음, 도구 실패 본문 `detail.reason_code`), 이 순서
- 422 `input_invalid`: `invalid_job_arguments`, `confirmation_missing`, `acknowledgement_missing`, `candidate_set_invalid`, `structure_invalid`, M18 리간드·상자 이유의 부분집합(`ligand_record_count`·`ligand_unparseable`·`ligand_multiple_fragments`·`ligand_element_not_allowed`·`ligand_too_many_atoms`·`ligand_not_3d`·`box_invalid`·`box_too_large`).
- (dry-run run은 여기서 계획만 돌려준다.) 412 `precondition`: `process_identity_unavailable`, `openmm_unavailable`, `pdbfixer_unavailable`, 도킹 환경 이유(`worker_missing` 등).
- 422 `input_invalid`: `openmm_preflight_failed`(`detail{reason_code, m7_reason, m7_message}`), `residue_mismatch`, `box_no_receptor_atoms`, `ga_space_too_small`(`detail{reason_code, space_size, population_size}`).
- 429 `resource_exceeded`: `staged_input_bytes`(스테이징 16 MiB 초과), `ga_limit_raise_required`(`detail: {reason_code, needed{expensive_calls, wall_clock_s}, shortfall{…}}`, 과금 없음, 작업 제출에서만).

### 계산: 작업 경로 (`POST /jobs` → `/start` → `/approve` → `/start`, 공통 작업 규칙)
- `{protocol_id: "sequence_ga_dock_v1", args, timeout_s}`. `timeout_s`는 `ga.total_s + 600` 이상 15000 이하이고 기본값이 없다(빠지면 `invalid_job_arguments`). 화면은 늘 `total_s + 600`을 보낸다. 호출 키에 들어가지 않는다.
- 같은 GA 호출 키의 작업이 `queued`·`claimed`·`running`이거나 그 키의 검증된 `complete` 요약을 게시한 작업이 있으면 200으로 그 작업을 돌려준다(새 작업 없음). `partial` 요약만 있으면 새 작업을 만든다. 첫 비싼 계산이면 `/start`가 409 `approval`(`tool: "sequence_ga_design"`)을 돌려주고 `/jobs/approve`가 기록한다. 시도는 1회이고 `POST /jobs/{id}/retry`는 412다. 시작 때 고정 pin(M18 pin + 모델링 pin + GA·모델링·상수·번들 모듈 해시)이 바뀌었으면 412 `worker_version_invalid`.
- 작업 기록 상태: 작업 모듈이 스스로 끝나면 `done`(`artifacts.sequence_ga_result` = 요약 handle), 사용자 취소는 `cancelled`, 마감·크래시·자원 한도·출력 오류는 `failed`, 서버 재시작 복구는 `interrupted`. 야생형 기준 행 상태가 기록되기 전에 멈춘 작업은 요약이 없다. 요약을 만들 수 없으면 `failed`(`fatal`)이고 이미 게시된 개체 결과는 남는다.
- GA 작업의 `GET /jobs`·`GET /jobs/{id}`·`/start` 응답에는 `sequence_ga: {space{positions, candidates, effective_max_mutations, size}, reserved_evaluations, reserved_units, reused_planned, reference_reuse_planned, reference_recorded, individuals_started, individuals_finished, generation_records, generations_complete, summary_handle, summary_status, summary_stop_reason}`가 붙는다(제출·재시도·취소 응답에는 없을 수 있다). 개수는 이 시도 디렉터리의 스테이징 파일 수이고 요약 전에는 객체를 읽지 않는다.

### 읽기와 증액 승인

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs/{id}/sequence_ga/preflight` | GA 인자(본문 최대 512 KiB, 중복 키 거부) | 200 `sequence_ga_preflight@1`: `{starts_job: false, capability, score_label, budget, remaining, admission{admitted, error, reason_code, message, detail}, selection_sha256, conditions_sha256, space{positions, candidates, effective_max_mutations, size}, projection_heavy_atoms, heavy_atom_warning, reusable_count, reference_reusable, reserved_evaluations, reserved_units, needed{expensive_calls, wall_clock_s}, shortfall{…}, full_run_may_be_partial, ga(정규화 값), statements:[{id, text}], existing_job: {job_id, status, summary_handle} \| null}`. 입장 거절(1–8)과 환경 없음도 200이며 `admission.admitted: false`, 이유·`detail`만 있고 나머지 수치는 null. 예산 부족은 거절이 아니라 `shortfall` | 413(본문), 422(JSON·쿼리), 404 없는 run |
| `GET /runs/{id}/sequence_ga/results?offset&limit` | limit 1–100(기본 50) | `sequence_ga_list@1`: `{total, offset, limit, rows:[{handle, published_seq, valid, reason_code, job_id, attempt_id, status, stop_reason, generations_done, new_evaluations_used, reused_count, reserved_units, space, candidate_set, selection_sha256, ga}]}`. 요약 handle의 첫 게시 순서로 최신 순, 행마다 다시 검증하고 실패한 행은 `valid: false`, `reason_code: "evidence_invalid"`, 나머지 null | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/sequence_ga/results/{handle}` | — | `sequence_ga_detail@1`: `{handle, job_id, attempt_id, published_seq, score_label, score_column_label, score_row_label, statements:[{id, text}](저장 문장 목록), summary(저장 요약 그대로), generations:[{index, complete, min_score, max_score, individuals:[저장 개체 + detail_available]}], reference(저장 기준 행 + detail_available), meta}`. `detail_available`은 M18 결과 handle이 있을 때 true | 404, 422 `input_invalid`(다른 종류), 422 `method_evidence_invalid` |
| `GET /runs/{id}/sequence_ga/results/{handle}/individual?key=` | 개체 키 `12-57-203` 또는 `wild_type`(필수, 이름이 아니라 키로만) | `sequence_ga_individual@1`: `{summary_handle, key, mutations, is_reference, eval_index, pick_index, evaluation, state, reason_code, score, model_handle, result_handle, appearances:[{generation, position, origin}], model(저장 모델에서 `final_bonds`·`atom_mapping`을 뺀 값 또는 null), statements:[S5], score_label, score_row_label, m18_detail}`. `m18_detail`은 결과가 있으면 M18 결과 상세 읽기와 같은 값, 없으면 null | 404(없는 키), 422(키 없음·형식·다른 종류), 422 `method_evidence_invalid` |
| `GET /runs/{id}/sequence_ga/results/{handle}/structure?key=` | 같은 키 | 저장 mmCIF 바이트 그대로(모델의 `structure_sha256`·handle 대조), `chemical/x-mmcif`, 첨부 이름 `protview-sequence-ga-<handle 해시 앞 12>-<key>.cif`, `Cache-Control: private, no-store` | 404(모델 없는 행 포함), 422, 422 `method_evidence_invalid` |
| `POST /runs/{id}/sequence_ga/limit_approval` | GA 인자(본문 최대 512 KiB) | 200 `{raised, selection_sha256, reserved_units, needed, shortfall_before, increase{expensive_calls, wall_clock_s}, limits_before, limits_after, shortfall_after, event_seq, budget}`. 부족분이 없으면 `raised: false`, `increase` 0, `event_seq: null`, 이벤트 없음(멱등) | 422 입장 거절, 412 `precondition`(dry-run `dry_run`, 환경 없음), 409 `cancelled`(취소된 run), 503 `transient`(run 실행 잠금이 잡혀 있음, 예: GA 실행 중), 413 |

- 한 읽기(목록·상세·개체·구조) 안에서 이벤트 로그는 한 번만 읽는다(스냅숏). 시작 전 확인은 입장·재사용 색인·같은 호출 키 확인을 한 호출에서 하므로 여러 번 읽는다.
- 증액 승인은 사람이 화면에서 누르는 이 경로뿐이다(M19·M22 라우트와 따로). 도구·분석 흐름 단계·뷰어 명령·작업 인자로 부를 수 없고 첫 비싼 계산 승인을 기록하지 않으며 예약·과금·환불하지 않는다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 새 객체 종류를 읽을 수 있지만 검증을 거치지 않는다(M12·M17–M22와 같은 관례). 화면은 위 읽기와 `/docking/results/*`만 쓴다.

### 이벤트
- `sequence_ga_individual_published {job_id, attempt_id, key, model_handle, result_handle | null, conditions_sha256}`: 작업 프로세스 그룹 정리 확인 뒤 새로 평가한 개체(또는 기준 행 `wild_type`)의 모델이 저장될 때마다. 이 이벤트가 그 결과의 게시 증거이며(요약 게시가 없어도) M18 읽기·보고서·M19·M22·GA 재사용이 받아들인다. 모델링 단계에서 실패한 개체는 쓰지 않는다.
- `sequence_ga_published {job_id, attempt_id, summary_handle, reused_count}`: 모든 개체 게시 뒤 요약을 게시할 때(마지막).
- `job_dispatch_intent`에 `sequence_reuse: {records, reference}`가 붙고 `budget_reserved.expensive_calls`는 `reserved_units`다. `budget_limit_updated`는 `by: "human"`과 GA 맥락을 담는다.

### capability와 도구 목록
- `/capabilities`의 `methods.sequence_ga_design`(`sequence_ga_capability@1`): `{protocol_id: "sequence_ga_dock_v1", tool_id: "sequence_ga_design", engine: "qvina", execution_lane: "durable_job", result_schema, model_schema, available, status, reason_code, reason, pins, versions{model, docking}, ga_ranges{키: {min, max, default}}, timeout_s{max: 15000, finish_margin: 600}, limits{positions, candidates, population, generations, new_evaluations, max_mutations, model_step_s, docking_step_s, total_s_max, model_object_bytes, output_bytes, summary_bytes, staged_bytes, m18_heavy_atom_estimate, consecutive_failures}, units_per_evaluation, score_label, score_row_label, statements{S1…S6}, model_limitations}`. OpenMM 8.6.0 포스필드·PDBFixer 1.12.0·프로세스 신원·도킹 환경 pin·GA 작업 모듈 handshake·프로젝트 인터프리터·모듈 파일이 모두 맞을 때만 사용 가능이고 아니면 `available: false`와 이유만이다(M21·M18 이유를 그대로).
- `sequence_ga_design`은 `config/tools.yaml`의 L3 명세(`emits: sequence_ga_result`, `cost_class: expensive`)로 등록되고 작업 전용이며 `GET /tools`(L3 포함)에는 나오지 않는다. `/commands`로 실행되지 않는다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <sequence_ga_result>}` → 201. manifest는 `method_report_manifest@1`, `analysis_type: "sequence_ga"`, `status: "complete"`, `render_version: "sequence_ga_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_schema: "sequence_ga_result@1"`, `result_sha256`, 요약에서 복사한 핵심 키, `ga_status`, `docking_method`, `claims`, `provenance{sequence_ga, rows[]}`, `limitation_ids`, `evidence_statement`, 스냅숏 키(`event_seq`, `time_utc`, `run_egress_mode`, `capability`, `budget`). 제목 "서열 GA 설계 보고서".
- 주장은 모두 `computed`. statement ID: `candidate_set_input`, `structure_input`, `ligand_input`, `box`, `parameter`, `ga_parameter`, `space_count`, `run_count`, `generation_count`, `generation_score_range`, `individual_score`, `individual_result_score`, `reference_score`, `reference_result_score`. 점수 주장은 `scored` 개체·기준 행만이다. 점수 없는 개체의 점수 주장, 다른 statement의 필드 경로, 틀린 반올림·개수, 해석 문장, 요약 점수와 결과 첫 모드 점수의 불일치, OpenMM 전위·구조 간 비교 주장, 변조·미완료 요약, 다른 run의 증거는 422 `report_evidence_invalid`.

## M24 JEV 과학 전송

규칙은 `docs/business-rules.md` "JEV 과학 전송 (M24, `build_jev_projection` / `request_science`)". JEV 라우트(`/runs/{id}/jev/*`)는 알 수 없는 쿼리 파라미터를 422 `input_invalid`로 거부한다. POST 셋(`/jev/consent`·`/jev/preview`·`/jev/sends`)은 `Content-Type: application/json`(대소문자 무시, 파라미터 허용)만 받고 아니면 본문을 읽기 전에 415 `unsupported_media_type`이며, 본문은 최대 4 KiB(413 `resource_exceeded`), 정해진 키·타입만 담은 JSON 객체 하나다(중복 키·알 수 없는 키·타입 오류는 422 `input_invalid`). 오류는 HTTP 경계 형태(`{"detail": {"error", "message", …}}`)이고 투영 거절은 `detail.reason_code: "projection_invalid"`를 담는다. 읽기(상태·미리보기·목록·상세)는 이벤트·도구·작업·외부 요청을 만들지 않고 키를 읽지 않으며 run 실행 잠금 없이 이벤트 로그를 한 번만 읽는다. 형식이 틀린 run ID는 400, 없는 run은 404다.

### 투영: `POST /runs/{id}/commands` `{tool: "build_jev_projection", args}`
```json
{"source": "obj://…/ligand_candidate_set/…" | "obj://…/mutation_candidate_set/…",
 "candidates": ["c_0123456789abcdef", "c_…"] | [0, 5, 12],
 "filter": null | {"ranges": {"mol_weight": {"min": null, "max": 500}}, "pains_exclude": true}}
```
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `jev_projection`, schema `jev_projection@1`, summary `{kind, source, selection_count, body_bytes, body_sha256}`. 같은 정규화 인자면 같은 handle(훅이 `bound`를 돌려주지 않음). dry-run run에서도 실행해 저장한다.
- 실패(도구 실패 본문, `detail.reason_code`): 422 `input_invalid`, 사전 검사 훅(구현을 부르지 않음), 이 순서: `unknown_field`, `source_invalid`, `selection_invalid`, `candidate_unknown`(`detail.candidates`), `filter_invalid`, `candidate_filtered_out`(`detail.candidates`), `structure_unavailable`, `wire_field_invalid`(`detail.field`). 429 `resource_exceeded` `payload_too_large`(`detail{reason_code, body_bytes, limit: 65536}`)와 422 `input_invalid` `projection_invalid`(구현이 만든 객체가 저장 형태 검증을 통과하지 못함)는 아무것도 저장하지 않는다. 과학 전송이 도는 동안에는 run 실행 잠금 때문에 503 `transient`(busy)다.
- 객체 필드는 business-rules "투영 객체"와 같다. 일반 `GET /runs/{id}/objects`도 이 종류를 읽을 수 있지만 `validated_projection`을 거치지 않는다. 화면은 아래 미리보기로만 본문을 본다.

### 라우트

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /runs/{id}/jev/status` | — | `jev_status@1`: `{schema, enabled, policy: "jev_science@1", send_cap: 10, used, remaining, budget{external_tokens: {used, limit, remaining}, usd: {used, limit, remaining}}, egress_stop_reason, dry_run, cancelled, question_ids, send_in_progress, request_model, allowed_served_model, destination}`. `used` = `jev_science_dispatch_started` 수, `enabled`는 마지막 동의 이벤트, `send_in_progress`는 프로세스 메모리 진행 중 집합 | 422 모르는 파라미터, 404, 409 `run_corrupt` |
| `POST /runs/{id}/jev/consent` | `{enabled: bool}` | 200 `jev_status@1`. 이벤트 `jev_science_consent_changed` 하나(이 라우트가 유일한 writer, 짧은 전이 잠금만이라 전송 중에도 됨). 뷰어 모드·뷰어 동의는 바뀌지 않는다 | 412 `dry_run`(dry-run run에서 켜기, 이벤트 없음), 415, 413, 422, 404 |
| `POST /runs/{id}/jev/preview` | `{projection}` | 200 `jev_preview@1`: `{schema, projection_handle, kind, source{handle, schema}, question{id, key, type, instructions, instructions_sha256}, body(보낼 정확한 본문 문자열), body_sha256, body_bytes, selection(별칭 ↔ 로컬 참조), selection_sent: false, reservation{external_tokens, usd}, send_cap, used, remaining, budget_remaining{external_tokens, usd}, blocked_by, previous_sends}`. `blocked_by`는 지금 성립하는 거절을 모두 이 순서로: `dry_run`, `consent_off`, `cancelled`, `egress_stopped`, `send_cap_exhausted`, `budget_exhausted`(남은 활동 시간 없음 또는 예약 초과), `send_in_progress`(전송 때 게이트가 다시 검사한다). `previous_sends`는 같은 투영으로 dispatch된 전송 수. 이벤트 없음 | 404 이 run에 없는 handle, 422 `input_invalid`(`reason_code: "projection_invalid"`: 다른 종류·검증 실패·다른 run을 가리키는 투영), 415, 413, 422 |
| `POST /runs/{id}/jev/sends` | `{send_id, projection, body_sha256, confirm: "send_to_jev"}` | 200 `jev_send@1`(거절·실패도 200). 같은 `send_id`를 같은 투영·해시로 다시 보내면 기존 기록(진행 중이면 `in_progress`)을 새 이벤트 없이 돌려준다 | 422 `input_invalid`(모양·`confirm`·정규 v4 UUID가 아닌 `send_id`·소문자 hex 64자가 아닌 해시), 404 투영 없음, 422 `projection_invalid`, 409 `preview_mismatch`(해시가 투영 본문과 다름)·`send_id_conflict`(같은 `send_id`가 다른 투영·해시로 승인됨)·`send_in_progress`(이 run의 다른 전송이 진행 중), 503 `busy`(run 실행 잠금), 500 `internal_error`(고정 문장, 기록은 아래 도출 규칙), 409 `run_corrupt`, 415, 413 — 앞의 거절은 모두 이벤트를 쓰지 않는다 |
| `GET /runs/{id}/jev/sends` | — | `jev_send@1` 배열, 승인 순서(오래된 것부터), 이벤트만으로 도출 | 422 모르는 파라미터, 409 `run_corrupt` |
| `GET /runs/{id}/jev/sends/{send_id}` | — | `jev_send@1` + `choice`(`completed`면 투영·소스 집합과 다시 검증한 `jev_choice@1`, 아니면 null) + `local_display`(`choice.answer.local_display` 또는 null) | 404 없는 `send_id`, 422 `method_evidence_invalid`(제안 검증 실패), 409 `run_corrupt` |

- `jev_send@1`: `{schema, send_id, status, reason_code, projection_handle, source{handle, schema}, kind, question_id, selection_count, body_sha256, body_bytes, audit_id, requested_model, served_model, usage, choice_handle, late, late_reason, approved_event_seq, outcome_event_seq}`. `status` ∈ `completed`·`rejected`·`failed`(저장) + 읽기 전용 `in_progress`. `reason_code`는 `completed`·`in_progress`면 null, `audit_id`는 거절이면 `denied` 감사의 id(예약 뒤 되돌린 거절은 `prepared` 감사의 id, 진행 중이면 dispatch 뒤에만), `usage{input_tokens, output_tokens, external_tokens, cost}`는 없으면 null(값마다 null 가능, 0 아님), `choice_handle`은 `completed`만, `outcome_event_seq`는 결과 이벤트가 없으면 null. 결과 이벤트가 없고 진행 중이 아니면 `failed`/`delivery_unknown`(응답 감사 없음) 또는 `failed`/`outcome_not_recorded`(응답 감사 있음, 응답 모델·사용량은 그 감사에서)로 도출한다.

### 이벤트
- `jev_science_consent_changed {enabled, policy: "jev_science@1", send_cap: 10, request_model, allowed_served_model, destination}`: 동의 라우트만 쓴다.
- `jev_send_approved {send_id, projection_handle, body_sha256, question_id, source_handle, selection_count, approved_by: "human"}`: 전송 라우트의 승인 콜백이 run 실행 잠금 안에서 게이트 검사보다 먼저 쓴다.
- `jev_science_dispatch_started {send_id, audit_id}`: HTTP 직전(감사 `dispatch_started` 다음). run당 상한 10회는 이 이벤트 수다.
- `jev_send_outcome {send_id, status, reason_code, audit_id, requested_model, served_model, choice_handle, usage, late, late_reason}`: 모든 전송의 끝(거절 포함). `completed`면 같은 전이에서 제안 객체를 먼저 저장한다.
- 과학 전송의 감사는 기존 `egress` 이벤트에 `scope: "science"`·`send_id`를 더하고, 예약은 `budget_reserved{audit_id, send_id, external_tokens, usd}`(비싼 계산 축 없음), 정산·환불은 기존 `egress_budget_settled`다(security "감사 기록").
- 이 네 이벤트를 쓰는 코드는 `jev_sends.py`(`set_consent`, `run_send`의 승인 콜백, `_finish`)와 `egress/science.py`(`request_science`)뿐이다(`backend/tests/test_jev_ast.py`).

### capability와 도구 목록
- `/capabilities`의 `methods.jev_choice`: `{available, reason_code, reason}`. 투영 도구가 `SUPPORTED_TOOLS`와 레지스트리에 있고 과학 pin(요청 모델·응답 스냅숏·provider·목적지·응답 상한)이 게이트 값과 같으면 `available: true`, 아니면 `tool_unavailable` 또는 `missing_configuration`. 키·run의 동의를 읽지 않는다(키가 없으면 전송 때 `missing_credential` 거절로 드러난다).
- `GET /tools`(기본 `levels=L2,L4`)에 `build_jev_projection`(L2, `accepts: {source: [ligand_candidate_set, mutation_candidate_set]}`, `emits: jev_projection`, `cost_class: cheap`)이 나온다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <jev_choice>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "jev_choice"`, `status: "complete"`, `render_version: "jev_choice_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "jev_choice@1"`, `result_sha256`, `external_response{kind: "jev_choice", scientific_evidence: false}`, `kind`(`ligand`·`mutation`), 제안에서 복사한 `method_version, label, scientific_result, send, source, projection, question, requested_model, served_model, arrival, limitations`, `chosen{local_ref, local_display}`, `claims`, `provenance{send_id, audit_id, approved_event_seq, dispatch_event_seq, created_event_seq, outcome_event_seq}`, `evidence_statement`, `snapshot{event_seq, time_utc, run_egress_mode, science_consent, budget}`, `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 이름 "JEV 판정 보고서"). 만들 때 run 실행 잠금을 잡으므로 과학 전송이 도는 동안에는 503 `transient`다.
- 주장 statement ID: `computed` — `selection_count`(`selection[*]`, `operation: "count(selection[*])"`), `body_bytes`, `usage_input_tokens`, `usage_output_tokens`, `usage_cost`(보고된 값만). `model_response` — `choice_alias`, `confidence`(보고됐을 때만), `served_model`, `arrival_late`, `arrival_late_reason`(늦었을 때만). 모델 응답 주장은 `reference{note: "외부 모델의 응답, 제안이며 과학 증거가 아니다", proposal_handle}`을, 계산값 주장은 `reference: null`을 가진다. 섞인 증거 종류(계산값이 모델 응답 필드를 인용하거나 그 반대), 다른 statement의 필드 경로, 확률 필드, 틀린 값·개수, 해석 문장, 전송 이벤트 사슬 불일치, 변조된 제안·보고서는 422 `report_evidence_invalid`.

## M25 JEV 설계 루프

규칙은 `docs/business-rules.md` "JEV 설계 루프 (M25, `build_jev_loop_projection` / 루프 라우트)". 루프 라우트(`/runs/{id}/jev_loops…`)는 알 수 없는 쿼리 파라미터를 422 `input_invalid`로 거부한다. 쓰기 라우트 넷(만들기·`compute`·`abandon_docking`·`end`)은 `Content-Type: application/json`(대소문자 무시, 파라미터 허용)만 받고 아니면 본문을 읽기 전에 415 `unsupported_media_type`이며, 본문은 만들기 16 KiB·나머지 4 KiB 이하(413 `resource_exceeded`), 중복 키 없는 JSON 객체 하나다. 루프 거절은 HTTP 경계 형태 `{"detail": {"error", "reason_code", "message", …}}`이고 `error`는 422면 `input_invalid`, 그 밖에는 이유 이름 자체다. run 실행 잠금을 잡지 못한 쓰기는 503 `busy`이고 아무것도 쓰지 않는다. 루프 라우트가 쓰지 않는 이벤트 순서는 500 `internal_error`(고정 문장), 다시 읽히지 않는 루프·저장 객체는 409 `run_corrupt`다. 읽기(목록·상세)는 run 실행 잠금 없이 이벤트 로그를 한 번만 읽고 이벤트·작업·도구·외부 요청을 만들지 않으며 키를 읽지 않는다. 라우트 사이에 호출 관계는 없고 어느 루프 라우트도 `request_science`·`run_send`·`Run.raise_limits`를 부르지 않는다. 하위 경로(`/compute`·`/abandon_docking`·`/end`)는 상세보다 먼저 등록되어 있다.

### 투영: `POST /runs/{id}/commands` `{tool: "build_jev_loop_projection", args}`
```json
{"loop_id": "<루프의 v4 UUID>", "iteration": 1}
```
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `jev_loop_projection`, schema `jev_loop_projection@1`, summary `{kind, loop_id, iteration, send_ordinal, selection_count, body_bytes, body_sha256}`. 사전 검사 훅이 루프 기록에서 읽은 입력(풀 순서, 목표, `loop_seed`, `send_ordinal`, 후보 상태·저장 점수)을 `bound`로 고정하고 그 SHA-256을 호출 키에 더한다. 같은 입력이면 같은 handle. dry-run run에는 루프가 없어 `loop_not_found`다.
- 실패(도구 실패 본문, `detail.reason_code`), 사전 검사 훅(구현을 부르지 않음), 이 순서: 422 `input_invalid` `unknown_field`·`loop_not_found` → 412 `precondition` `loop_ended`·`iteration_mismatch`·`selection_done`·`phase_invalid`·`cap_reached`·`too_few_candidates` → 422 `source_invalid`·`structure_unavailable`·`wire_field_invalid` → 429 `resource_exceeded` `payload_too_large`(`detail{reason_code, body_bytes, limit: 65536}`). 구현이 만든 객체가 저장 형태 검증을 통과하지 못하면 422 `projection_invalid`. 거절은 아무것도 저장하지 않는다. 과학 전송이나 루프 작업이 run 실행 잠금을 쥔 동안에는 503 `transient`(busy)다.
- 객체 필드는 business-rules "투영 도구"와 같다. 화면은 아래 미리보기로만 본문을 본다.

### 라우트

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `POST /runs/{id}/jev_loops` | `{loop_id, branch, pool{source, candidates, filter}, goal, loop_seed, iteration_cap, setup}`(키·값 규칙은 business-rules "루프 만들기") | 200 `jev_loop@1`. 이벤트 `jev_loop_created` 하나. 같은 `loop_id`·같은 정규화 요청은 기존 기록을 새 이벤트 없이 | 422 `unknown_field`·`loop_id_invalid`·`branch_invalid`·`pool_invalid`·`goal_invalid`·`seed_invalid`·`iteration_cap_invalid`·`setup_invalid`(`detail.setup_reason`, 기존 M18·M21 닫힌 이름), 409 `loop_id_conflict`·`loop_active`, 412 `dry_run`·`capability_unavailable`(`detail.capability{reason_code, reason}`), 415, 413, 503 `busy` — 모두 이벤트 없음 |
| `GET /runs/{id}/jev_loops` | — | 목록 행 `{loop_id, branch, status, end_reason, goal, pool_size, counts, created_seq}` 배열, 최신 순 | 422 모르는 파라미터, 404 없는 run, 409 `run_corrupt`, 500 `internal_error` |
| `GET /runs/{id}/jev_loops/{loop_id}` | — | `jev_loop@1`(아래) | 404 `loop_not_found`, 422, 409 `run_corrupt`, 500 `internal_error` |
| `POST /runs/{id}/jev_loops/{loop_id}/compute` | `{iteration}` + 첫 단계에서 정확히 하나의 `proposal`(제안 handle) 또는 `candidate`(리간드 후보 id·단백질 후보 `index`), `dock` 단계는 `{iteration}`만 | 200 `jev_loop@1`. 이벤트 `jev_loop_compute_approved` 하나 뒤 단독 M18·M21 작업 제출, 잠금을 놓은 뒤 시작(작업이 끝날 때까지 응답을 기다림). 첫 계산 승인 대기면 200 + `current.job.start_blocked: "approval_required"`(화면은 `POST /jobs/approve` 뒤 같은 요청을 다시 보냄). 같은 단계의 같은 인자 재호출은 새 이벤트·작업 없이 살아 있는 작업의 `start`만. 저장 모델·도킹 결과 채택은 작업 없이 `units: 0` | 422 `unknown_field`·`candidate_invalid`, 404 `loop_not_found`, 409 `cancelled`·`loop_ended`·`send_in_progress`·`iteration_invalid`·`phase_invalid`·`iteration_cap_reached`·`proposal_invalid`·`proposal_late`·`candidate_unavailable`·`candidate_computed`·`step_unavailable`(`detail.job{id, status}`), 412 `capability_unavailable`(`detail.capability`), 429 `budget_blocked`(`detail.blocked_axes`·`needs`), M18·M21 작업 입장 거절(도구 실패 본문, 닫힌 `detail.reason_code`), 503 `busy` — 여기까지 이벤트 없음. 시작 단계의 실패는 작업 시작 라우트와 같음(409 `approval`·`cancelled`·전역 작업 게이트, 도구 실패 본문) |
| `POST /runs/{id}/jev_loops/{loop_id}/abandon_docking` | `{iteration}` | 200 `jev_loop@1`. 이벤트 `jev_loop_docking_abandoned` 하나(후보 `not_run`, 바퀴 끝) | 422 `unknown_field`, 404, 409 `cancelled`·`loop_ended`·`send_in_progress`·`iteration_invalid`·`phase_invalid`, 503 `busy` |
| `POST /runs/{id}/jev_loops/{loop_id}/end` | `{}` | 200 끝난 `jev_loop@1`. 요약 `jev_loop_result@1`을 저장한 뒤 이벤트 `jev_loop_ended` 하나 | 422 `unknown_field`(빈 객체가 아님), 404, 409 `cancelled`·`loop_ended`·`send_in_progress`·`job_running`·`docking_pending`, 503 `busy` |

- `jev_loop@1`: `{schema, loop_id, branch, status, end_reason, exhausted_reason, goal, loop_seed, iteration_cap, effective_cap, pool{source{handle, schema}, structure{handle, model_number}|null, candidates[{ref, display}], filter}, setup, setup_sha256, pins, counts{started, done, jev_decided, human_decided, sends_dispatched, units_charged, reused_count}, candidates[{ref, display, state, evaluation, score_kcal_mol, iteration}], iterations[{index, phase, decided_by, candidate_ref, proposal_handle, list_position, list_size, approvals[{step, candidate_ref, decided_by, proposal_handle, call_key}], sends[{send_id, status, send_ordinal, proposal_handle, late}], steps[{step, candidate_ref, job_id, call_key, result_handle, state, reason_code, evaluation}], state, score_kcal_mol}], current{iteration, phase, step, action, needs, remaining, blocked_axes, send_blocked_axes, can_end, job{job_id, step, status, start_blocked}|null}, result_handle, limitations}`. `needs`·`remaining`은 `{expensive_units, wall_clock_s, external_tokens, usd, sends}`(외부 토큰·USD는 값이 없으면 null). 점수는 저장 결과 첫 모드의 사본이고 점수 없음은 null이며 0이 아니다. 끝난 루프는 그 `jev_loop_ended` 시점에 동결된 기록이고 `current.remaining`만 지금 값이다.

### M24 라우트의 루프 투영
- `POST /runs/{id}/jev/preview` `{projection: <jev_loop_projection handle>}` → 200 `jev_preview@1`에 `loop{loop_id, iteration, send_ordinal, needs, remaining, send_blocked_axes}`와 `loop_blocks`(지금 성립하는 `LOOP_SEND_REASONS` 거절, 없으면 `[]`)가 더해진다. `question`은 루프 질문 id·지시문·`instructions_sha256`이다. M24 투영의 미리보기 응답 모양·바이트는 그대로다.
- `POST /runs/{id}/jev/sends` `{send_id, projection, body_sha256, confirm: "send_to_jev"}`가 루프 투영을 받는다. 라우트 순서는 M24 요청 검사 → 투영 → 409 `preview_mismatch` → 같은 `send_id` 재생 → 409 `send_in_progress` → 루프 검사(승인 콜백 안, 승인 이벤트 앞) → 게이트. 루프 검사 거절은 409 `{"detail": {"error": "loop_send_invalid", "message", "reason"}}`(`reason` ∈ `loop_not_found`, `loop_ended`, `iteration_mismatch`, `selection_done`, `phase_invalid`, `cap_reached`, `too_few_candidates`, `state_changed`, `ordinal_mismatch`)이고 승인·감사·예약·키 읽기가 없다(게이트의 `wall_charged`만 남을 수 있음). 그 밖의 결과·거절·실패는 M24와 같은 200 `jev_send@1`이며 완료된 루프 전송의 제안은 `jev_loop_choice@1`이다.
- `GET /runs/{id}/jev/sends`·`/jev/sends/{send_id}`: 루프 전송의 `jev_send@1`에 `loop{loop_id, iteration, send_ordinal}`(투영 객체 이벤트에서, 읽을 수 없으면 null)가 더해진다. M24 전송 기록에는 `loop` 키가 없다. 상세의 `choice`는 루프 전송이면 투영·후보 집합·그 전송의 승인·결과 이벤트와 다시 검증한 `jev_loop_choice@1`(검증 실패는 422 `method_evidence_invalid`), `local_display`는 그 `answer.local_display`다.
- `GET /runs/{id}/jev/status`의 `used`·`remaining`·예산은 루프 전송을 함께 센다(run당 10회, 외부 토큰·USD 공유).

### 이벤트
- `jev_loop_created {loop_id, branch, pool{source{handle, schema}, structure|null, candidates, filter}, goal, loop_seed, iteration_cap, setup, setup_sha256, pins}`: 만들기 라우트만.
- `jev_loop_compute_approved {loop_id, iteration, step, candidate_ref, decided_by, proposal_handle|null, call_key, units, approved_by: "human"}`: 계산 시작 라우트만, 작업 제출 전(같은 실행 잠금 안). `units`는 저장 결과 채택이면 0, 아니면 1.
- `jev_loop_docking_abandoned {loop_id, iteration, candidate_ref}`: 도킹 포기 라우트만.
- `jev_loop_ended {loop_id, end_reason, result_handle}`: 끝내기 라우트만, 요약 저장 뒤. `end_reason`에 `run_cancelled`는 쓰지 않는다(읽을 때 도출).
- 네 이벤트는 예산 예약·정산·egress 정산·재생에 영향이 없다(`core/events.py` `EventType`에 이름만 더함). 투영·제안·요약 객체는 기존 `object_created`로 저장되고 events-only로 다시 열린다. 루프 전송은 M24 이벤트 넷(`jev_send_approved` 등)을 그대로 쓰고 새 전송 이벤트가 없다.

### capability와 도구 목록
- `/capabilities`의 `methods.jev_loop`: `{ligand: {available, reason_code, reason}, protein: {available, reason_code, reason}}`. 갈래마다 투영 도구가 `SUPPORTED_TOOLS`·레지스트리에 없으면 `tool_unavailable`, 과학 pin이 게이트 값과 다르면 `missing_configuration`, 그다음 그 갈래 엔진의 이유(리간드: `methods.ligand_docking`, 단백질: `methods.mutation_model` 다음 `methods.ligand_docking`)다. 사용할 수 없으면 숫자·pin·버전 없이 이유만. 키·run 동의를 읽지 않는다.
- `GET /tools`(기본 `levels=L2,L4`)에 `build_jev_loop_projection`(L2, `emits: jev_loop_projection`, `cost_class: cheap`, 인자 `loop_id`·`iteration`)이 나온다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <jev_loop_result>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "jev_loop"`, `status: "complete"`, `render_version: "jev_loop_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "jev_loop_result@1"`, `result_sha256`, `external_response{kind: "jev_loop_choice", scientific_evidence: false}`, 요약에서 복사한 `branch, loop_id, goal, loop_seed, iteration_cap, effective_cap, end_reason, pool, setup, setup_sha256, pins, counts, candidates, iterations, unfinished`, `score_label`, `score_column_label`, `chosen[{iteration, proposal_handle, local_ref, local_display}]`, `claims`, `provenance{created_event_seq, ended_event_seq}`, `evidence_statement`, `limitation_ids`, `limitations`, `snapshot{event_seq, time_utc, run_egress_mode, budget}`, `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 이름 "JEV 루프 보고서"). `jev_loop_choice` handle은 422 `wrong_method_result_kind`다.
- 주장 statement ID: `computed` — `pool_size`(`count(pool.candidates)`), `pool_source`, `loop_setting`(`loop_seed`·`iteration_cap`·`effective_cap`·`setup_sha256`), `setup_value`(`setup.parameters.{seed, exhaustiveness, num_modes, energy_range}`, 단백질 `setup.contact_cutoff_A`), `count`(`counts.*` 일곱), `candidate_score`(요약 `candidates[i].score_kcal_mol`)·`candidate_result_score`(그 후보 M18 결과 `modes[0].score_kcal_mol`, `scored` 후보만, `row_selector {"candidate": i}`, 0.1 `ROUND_HALF_UP`). `model_response` — `list_position`, `list_size`, `confidence`(보고됐을 때만), `arrival_late`(JEV가 고른 바퀴만, `row_selector {"iteration": n}`, `reference{note: "외부 모델의 응답, 제안이며 과학 증거가 아니다", proposal_handle}`). 섞인 증거 종류, 다른 statement의 필드 경로, 확률 필드, 틀린 값·개수·반올림, 점수 없는 후보의 점수 주장, 해석 문장, 변조된 요약·제안·보고서는 422 `report_evidence_invalid`.

## M26 효소 반응 지식

규칙은 `docs/business-rules.md` "효소 반응 지식 (M26, `link_reaction_knowledge`)". 읽기 호출은 로컬 반응 참조 폴더와 run 객체만 읽고 도구·작업·이벤트·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다(HTTP 경계 형태). run 범위 읽기는 이벤트 로그를 많아야 한 번 읽고, 결과 객체를 읽을 때마다 `validated_result`로 다시 검증한다(참조 폴더 없이 이벤트만으로 다시 열림). 결과 상세의 handle은 URL **경로**에 그대로 넣는다(`{handle:path}`, M20과 같음, 하위 경로 라우트는 상세보다 먼저 등록한다). 새 쓰기 라우트는 없다.

### 계산: `POST /runs/{id}/commands` `{tool: "link_reaction_knowledge", args}`
```json
{"structure": "obj://…/prepared_structure/…",
 "pdb_id": "1S9I" | null,
 "chains": [{"chain_auth": "A", "uniprot_accession": "P36507" | null}],
 "numbering_map": null | "obj://…/residue_numbering_map/…"}
```
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `reaction_knowledge`, schema `reaction_knowledge@1`, summary `{structure, pdb_id, chains, set_hash, covered_chains}`. `null_result`는 결과 객체의 값이다. 같은 정규화 인자·같은 활성 세트면 같은 handle(호출 키에 고정한 세트 해시). dry-run run에서도 실행해 저장한다.
- 실패(도구 실패 본문, `detail.reason_code`):
  - 412 `precondition`: `not_installed`, `snapshot_invalid`(활성 반응 세트 없음·손상, 입장 검사·캐시 조회 전).
  - 422 `input_invalid`, 사전 검사 훅(도구 구현을 부르지 않음, 체인 문제는 `detail.chain_auth` 포함), 이 순서: `unknown_field`, `structure_invalid`, `pdb_id_invalid`, `chains_invalid`, `chain_not_found`, `accession_invalid`, `numbering_map_invalid`, `structure_mismatch`, `map_pdb_mismatch`.
  - 429 `resource_exceeded`: `result_too_large`(`detail{reason_code, limit: 1048576, actual}`), `too_many_links`(`detail{reason_code, limit: 2000}`). 아무것도 저장하지 않는다(자르지 않음).
  - 422 `input_invalid` `result_invalid`: 구현이 만든 결과가 `validated_result`를 통과하지 못함(저장하지 않음, 내부 일관성 실패).
- 결과 객체의 필드는 business-rules "결과 객체 `reaction_knowledge@1`"와 같다.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /reaction_reference/status` | — (쿼리 없음) | `reaction_reference_status@1`: `{schema, installed, reason: null\|"not_installed"\|"snapshot_invalid", set_hash, imported_at, sources:[{source, date, license, origin, rows}], requested_accessions, skipped_accessions}`(`rows`는 그 출처 가공 파일 행 수의 합, 뒤의 둘은 매니페스트 값 그대로). 설치되지 않았거나 손상이면 200 `installed: false`와 이유뿐이고 나머지는 null. run과 무관 | 422 모르는 파라미터 |
| `GET /reaction_reference/pdb/{pdb_id}` | 4자 PDB ID(`[0-9][A-Za-z0-9]{3}`, 대문자로 정규화) | `{pdb_id, entries:[{mcsa_id, enzyme_name, reference_uniprot_id, chains}]}`: 이 PDB를 `residue_chains`에 가진 M-CSA 항목(`mcsa_id` 오름차순, `chains`는 그 PDB의 `chain_name` 오름차순). 화면의 accession 제안용이며 고르는 것은 사람이다. 스냅샷에 없는 PDB는 빈 목록 | 422 `input_invalid`(형식, 폴더를 읽기 전), 412 도구 실패 본문(`not_installed`·`snapshot_invalid`), 422 모르는 파라미터 |
| `GET /runs/{id}/reaction_knowledge?offset&limit` | limit 1–100(기본 50) | `{items:[{handle, structure_handle, structure_kind, pdb_id, chain_count, covered_chain_count, mcsa_rows{matched, unmatched, conflict}\|null, uniprot_feature_count\|null, null_result, set_hash, active}], total}`. 최신 순, 행마다 다시 검증. `uniprot_feature_count`는 부위 종류 셋의 합, `active`는 결과의 세트 해시가 지금 활성 세트와 같은지 | 422(범위·모르는 파라미터), 404 없는 run, 409 `run_corrupt` |
| `GET /runs/{id}/reaction_knowledge/{handle}?chain_offset&chain_limit&row_offset&row_limit&feature_offset&feature_limit` | `chain_limit` 1–10(기본 10), `row_limit`·`feature_limit` 1–200(기본 50), 오프셋 기본 0 | 저장 객체 전체에서 `chains`를 `chain_offset`·`chain_limit`로 자르고, 각 체인의 `mcsa.rows`를 `row_offset`·`row_limit`, `uniprot.features`를 `feature_offset`·`feature_limit`로 잘라 돌려준다. 잘라 낸 체인마다 `mcsa.row_total`·`uniprot.feature_total`(전체 개수, 목록이 null이면 null)을 더하고 최상위에 `page{chain_total, chain_offset, chain_limit, row_offset, row_limit, feature_offset, feature_limit}`·`active_set{set_hash\|null, same}`을 더한다 | 404 없는 handle·다른 run·다른 종류, 422 `method_evidence_invalid`(검증 실패), 422(범위·모르는 파라미터) |

- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 이 종류를 읽을 수 있지만 `validated_result`를 거치지 않는다. 화면은 위 넷만 쓴다.

### capability와 도구 목록
- `/capabilities`의 `methods.reaction_knowledge`: `methods.residue_numbering`과 같은 다섯 키 `{available, reason_code: null|"not_installed"|"snapshot_invalid", reason, set_hash, sources:[{source, date, license, origin, rows}]}`. 활성 세트의 해시와 내용 형식 해석까지 확인하며, 사용할 수 없으면 `set_hash: null`·`sources: []`다(status 라우트의 null과 다름).
- `GET /tools`(기본 `levels=L2,L4`)에 `link_reaction_knowledge`(L2, `accepts: {structure: [structure, prepared_structure]}`, `emits: reaction_knowledge`, `cost_class: cheap`, 인자 `pdb_id`·`chains`·`numbering_map`)가 나온다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <reaction_knowledge>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "reaction_knowledge"`, `status: "complete"`, `render_version: "reaction_knowledge_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "reaction_knowledge@1"`, `result_sha256`, 결과에서 복사한 `method_version, structure, pdb_id, numbering_map, snapshot_set, chains, counts, null_result, limitations`, `claims`, `provenance{call_id, tool, tool_version, created_event_seq, completed_event_seq}`, `evidence_statement`, `snapshot{event_seq, time_utc, run_egress_mode, budget, active_set_hash}`(보고서를 만들 때의 활성 반응 세트, 없으면 null), `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 이름 "효소 반응 지식 보고서").
- 주장 statement ID: `computed` — `chain_count`, `chain_flag`, `mcsa_status`, `mcsa_coverage`, `mcsa_row_count`, `mcsa_row_status`, `total_mcsa_row_count`, `mcsa_entry_count`, `uniprot_status`, `uniprot_link_state`, `uniprot_feature_count`, `total_uniprot_feature_count`, `feature_link_count`, `total_linked_position_count`, `reactions_status`, `rhea_link_state`, `total_rhea_count`, `unlisted_line_count`. `reference_value` — `reference_snapshot_rows`, `reference_mcsa_entry`, `reference_ec_number`, `reference_mcsa_row`, `reference_mcsa_role`, `reference_uniprot_entry`, `reference_uniprot_site`, `reference_uniprot_activity`, `reference_rhea_id`, `reference_rhea_equation`("참조 스냅샷 값, 계산 아님", 세트 해시, 출처별 날짜·라이선스). 주장 필드는 M15 보고서와 같다. 다른 statement의 필드 경로, 계산값으로 참조 필드 인용, 틀린 개수, 검사하지 않은 절의 숫자 주장, 해석 문장, 다른 run·다른 종류의 결과, 변조된 결과·보고서는 422 `report_evidence_invalid`. 만들기·다시 열기·다운로드는 연결을 다시 계산하지 않는다.

### 가져오기 명령 (CLI) `scripts/import_reaction_references.py`
- 사용: `.venv/bin/python scripts/import_reaction_references.py [--accession ACC]... [--accessions-file PATH] [--no-kinases] [--reference-dir PATH] [--yes]`. 사용자가 터미널에서 실행하며 서버·도구·작업·M13 흐름·`Run.call`은 부르지 않는다.
  - `--accession`(반복 가능)·`--accessions-file`(한 줄에 하나, 빈 줄 무시, 4 MiB 이하 UTF-8): 직접 지정 accession(UniProt accession 형식, 중복 합침). 형식이 틀리면 아무 요청 없이 거절한다.
  - `--no-kinases`: 로컬 M15 kinase 목록(`MW_REFERENCE_DIR` 또는 `<저장소>/.deps/reference`의 활성 M15 세트, 읽기만)을 쓰지 않는다.
  - `--reference-dir`: 쓸 폴더. 없으면 `MW_REACTION_REFERENCE_DIR`, 그것도 없으면 `<저장소>/.deps/reaction_reference`(상대 값은 저장소 루트 기준). 다른 스냅샷 가족의 `active.json`이 있는 폴더·링크인 `sets`는 거절한다.
  - `--yes`: 확인 화면(허용 호스트, 가져올 출처, 예상 accession 수, 상한, 쓸 폴더, 이전 활성 세트, 이번에 빠진 이전 직접 지정)의 대화형 확인을 생략한다. 호스트·스킴을 바꾸는 옵션·환경변수는 없다.
- 출력: 요청마다 진행 줄(출처·URL 경로·상태·바이트, 질의 문자열 제외), 끝나면 쓴 폴더·세트 해시·가져온 시각·출처별 행 수·건너뜀 수와 목록·저장하지 않은 동형체 위치 부위 수·요청 수·이번에 다시 주지 않은 이전 직접 지정·M15 kinase 목록 상태. 키·헤더는 출력하지 않는다.
- 종료 코드: 0 설치 완료, 1 거절(표준 오류에 거절 종류와 이유, `active.json`·이전 세트는 그대로), 2 인자 오류(argparse). 거절 종류(닫힌 집합 `REFUSAL_KINDS`): `invalid_input`, `target_invalid`, `too_many_accessions`, `cancelled`, `fetch_failed`(HTTP 200이 아님·응답 없음, 요청 전에 거부된 URL 포함), `format_error`, `too_many_skipped`, `user_named_unavailable`, `set_exists`, `install_failed`.
- 라이브러리 함수 `run_import(params, *, transport=...)`는 `fetch(url) -> (status, headers, body)` 전송을 인자로 받고(CLI는 `UrllibTransport`), `compare_manifests(first, second)`는 두 매니페스트의 재현 여부(`reproduced`, 파일별 SHA-256, 원본 응답 요약 차이)를 돌려준다.

## M27 키나아제 전례

규칙은 `docs/business-rules.md` "키나아제 전례 (M27, `link_kinase_precedents`)". 읽기 호출은 로컬 전례 참조 폴더와 run 객체만 읽고 도구·작업·이벤트·외부 요청을 만들지 않으며, 알 수 없는 쿼리 파라미터는 422 `input_invalid`다(HTTP 경계 형태 `{"detail": {"error": "input_invalid", "message"}}`). run 범위 읽기는 이벤트 로그를 많아야 한 번 읽고, 결과 객체를 읽을 때마다 `validated_result`로 다시 검증한다(참조 폴더 없이 이벤트만으로 다시 열림). 결과 상세의 handle은 URL **경로**에 그대로 넣는다(`{handle:path}`, 하위 경로 라우트는 상세보다 먼저 등록한다). 새 쓰기 라우트는 없다.

### 계산: `POST /runs/{id}/commands` `{tool: "link_kinase_precedents", args}`
```json
{"numbering_map": "obj://…/residue_numbering_map/…",
 "chains": null | ["A", "C"],
 "include_flagged": false}
```
- 성공: 200 `{ok: true, handle: <envelope>}`, kind `kinase_precedents`, schema `kinase_precedents@1`, summary `{numbering_map, pdb_id, chains, include_flagged, set_hash, linked_chains}`. `null_result`는 결과 객체의 값이다. 같은 정규화 인자·같은 활성 세트면 같은 handle이다(호출 키 = 정규화 인자(`chains`는 늘 정렬한 목록, null이면 번호 대응의 모든 체인) + 고정한 세트 해시 + `method_version`). dry-run run에서도 실행해 저장한다.
- 실패(도구 실패 본문, `detail.reason_code`):
  - 412 `precondition`: `not_installed`, `snapshot_invalid`(활성 전례 세트 없음·손상, 입장 검사·캐시 조회 전). 포함할 레코드의 `content_hash`가 호출 때 다시 계산한 값과 다를 때도 `snapshot_invalid`다(저장하지 않음).
  - 422 `input_invalid`, 사전 검사 훅(도구 구현을 부르지 않음), 이 순서: `unknown_field`, `numbering_map_invalid`, `include_flagged_invalid`, `chains_invalid`, `chain_not_in_map`. `chains_invalid`의 중복과 `chain_not_in_map`은 `detail.chain_auth`를 담는다. `numbering_map_invalid`는 handle이 아님·이 run의 객체가 아님·`residue_numbering_map@1`이 아님·도구가 읽는 필드 모양이 아님·체인이 하나도 없음이다.
  - 429 `resource_exceeded` `result_too_large`: `detail{reason_code, limit: 1048576, actual, size_without_flagged, target_sizes:[{accession, chains, bytes}]}`(`size_without_flagged`는 `include_flagged`를 끈 크기, 이미 꺼져 있으면 null. `target_sizes`는 표적마다 그 표적의 체인만 요청했을 때의 크기). 메시지는 어느 체인을 나누거나 `include_flagged`를 끄면 되는지 알려 준다. 아무것도 저장하지 않는다(자르지 않음).
  - 422 `input_invalid` `result_invalid`: 구현이 만든 결과가 `validated_result`를 통과하지 못함(저장하지 않음, 내부 일관성 실패).
- 체인이 연결되지 않는 것(`no_mapped_residues`·`multiple_accessions`)은 오류가 아니라 결과의 상태다. 결과 객체의 필드는 business-rules "결과 객체 `kinase_precedents@1`"와 같다.

### 읽기

| 호출 | 입력 | 출력 | 오류 |
|---|---|---|---|
| `GET /precedent_reference/status` | — (쿼리 없음) | `precedent_reference_status@1`: `{schema, installed, reason: null\|"not_installed"\|"snapshot_invalid", set_hash, imported_at, importer_version, kbase: {commit, dist_commit, dist_commit_date, dirty, kb_version, schema_version, effect_rules_version, vocab_version, source_snapshots, origin}, files: [{name, rows, bytes}], bibliography: {snapshot_id, date, license, rows}, set_summary}`(`set_summary`는 결과의 `set_summary`와 같은 모양으로 세트에서 계산). 설치되지 않았거나 손상이면 200 `installed: false`와 이유뿐이고 나머지는 null. run과 무관 | 422 모르는 파라미터 |
| `GET /runs/{id}/kinase_precedents?offset&limit` | limit 1–100(기본 50), offset ≥ 0 | `{items:[{handle, numbering_map_handle, pdb_id, include_flagged, chain_count, linked_chain_count, target_count, records{moves, moves_flagged}, null_result, set_hash, active}], total}`. 최신 순, 행마다 다시 검증. `records.moves_flagged`는 포함하지 않았으면 null, `active`는 결과의 세트 해시가 지금 활성 세트와 같은지 | 422(범위·모르는 파라미터), 404 없는 run, 409 `run_corrupt`(저장 결과가 검증되지 않음) |
| `GET /runs/{id}/kinase_precedents/{handle}?target&file&site&goal&tactic&variant&q&sort&order&limit&offset` | `target`: 이 결과 표적의 accession(기본 첫 표적). 필터 `file`(`moves`\|`moves_flagged`), `site`·`goal`·`tactic`(어휘 용어, 반복 가능, 같은 키 안 OR·키 사이 AND), `variant`(원문 정확 일치), `q`(100자 이하, 앞뒤 공백을 뗀 뒤 비어 있으면 거절, 대소문자 무시 부분 문자열). `sort` `move_id`(기본)\|`pmid`\|`year`\|`variant`\|`file`, `order` `asc`(기본)\|`desc`, `limit` 1–100(기본 25), `offset` ≥ 0. 반복할 수 있는 키는 `site`·`goal`·`tactic`뿐 | 키는 정확히 `schema`(`kinase_precedents_detail@1`), `handle`, 저장 객체 값 그대로인 `method_version`·`numbering_map`·`structure`·`pdb_id`·`include_flagged`·`record_format`·`precedent_set`·`chains`·`set_summary`·`counts`·`null_result`·`limitations`, `targets_overview`(표적마다 `accession, chains, status, references, excluded_flagged, counts`), `page{target, total, filtered_total, offset, limit}`, `facets{file, site, goal, tactic, variant}`(각 `[{value, count}]`, `value` 오름차순, 선택한 표적의 필터 전 전례에서 셈), `records`(걸러 정렬한 한 쪽의 전례 원소), `bibliography`(그 쪽 전례의 PMID만), `active_set{set_hash\|null, same}`. 표적이 하나도 없으면 `page.target`·`total`·`filtered_total`이 null, `facets` null, `records` `[]`. 정렬 동점은 `move_id` 오름차순, `year`가 정수가 아니거나 서지 없음은 `order`와 무관하게 늘 끝 | 422 `input_invalid`(모르는 키·값, 어휘 밖 용어, 한 번만 받는 키의 반복, 이 결과에 없는 `target`, 범위 밖 `limit`·`offset`, 4,300자리를 넘는 정수. 질의 검사는 run 조회보다 먼저), 404 없는 run·handle·다른 run·다른 종류, 422 `method_evidence_invalid`(검증 실패) |

- 측정 변화(effects)·방향·크기 값으로 거르거나 정렬하는 키는 없다. 어휘에 있으나 그 표적에 없는 용어로 거르면 오류가 아니라 빈 쪽이다.
- 일반 `GET /runs/{id}/objects`·`/objects/meta`도 이 종류를 읽을 수 있지만 `validated_result`를 거치지 않는다. 화면은 위 셋만 쓴다.

### capability와 도구 목록
- `/capabilities`의 `methods.kinase_precedents`: `methods.reaction_knowledge`와 같은 다섯 키 `{available, reason_code: null|"not_installed"|"snapshot_invalid", reason, set_hash, sources}`. 활성 세트의 해시와 내용 형식 해석(레코드 형식 검사·레코드 해시·색인)까지 확인한다. `sources`는 정확히 두 원소 `{source: "kbase_dist", date, license: "none-stated", origin: "kbase_kinase processed dist", rows}`(`date`는 `dist_commit_date`의 날짜 부분 또는 null, `rows`는 세 dist 파일 행 수의 합)와 `{source: "kbase_pubmed", date, license, origin: "kbase_kinase processed ref/pubmed", rows}`(`date`·`license`는 매니페스트 `bibliography` 값, `rows`는 그 파일 행 수)이다. 사용할 수 없으면 `set_hash: null`·`sources: []`다(status 라우트의 null과 다름).
- `GET /tools`(기본 `levels=L2,L4`)에 `link_kinase_precedents`(L2, `accepts: {numbering_map: [residue_numbering_map]}`, `emits: kinase_precedents`, `cost_class: cheap`, 인자 `chains`(기본 null)·`include_flagged`(bool, 필수))가 나온다.

### 보고서
- `POST /runs/{id}/method_reports` `{result_handle: <kinase_precedents>}` → 201 `{handle, markdown_handle, manifest, markdown}`. manifest는 `method_report_manifest@1`, `analysis_type: "kinase_precedents"`, `status: "complete"`, `render_version: "kinase_precedents_markdown@1"`, `generation_mode: "local_rules_no_egress"`, `result_handle`, `result_schema: "kinase_precedents@1"`, `result_sha256`, 결과에서 복사한 `method_version, numbering_map, structure, pdb_id, include_flagged, record_format, precedent_set, chains, set_summary, counts, null_result, limitations`, 인용문·측정 변화가 없는 출처 목록 `target_sources`(표적마다 `accession, chains, status, references, excluded_flagged, counts, records`(최대 300줄: `file, move_id, pmid, resolution_basis, variant, locations, tags, content_hash, checks`(이름 → 상태), `integrity`(`hash_verified`·`quotes_within_limit`·`locations_have_page`)), `unlisted_records`), `listed_bibliography`(나열한 전례 PMID → `{title, journal, year, doi}` | null), `claims`, `provenance{call_id, tool, tool_version, created_event_seq, completed_event_seq}`, `evidence_statement`, `snapshot{event_seq, time_utc, run_egress_mode, budget, active_set_hash}`(보고서를 만들 때의 활성 전례 세트, 없으면 null), `markdown_handle`이고 기존 `/reports`, `/reports/selected`, `/reports/download`로 읽는다(보고서 목록 이름 "키나아제 전례 보고서"). manifest·Markdown 상한 8 MiB(넘으면 `precedent_report_too_large`).
- 주장 statement ID: `computed` — `chain_count`, `chain_status_count`, `chain_reason_count`, `chain_status`, `target_count`, `flagged_inclusion`, `total_record_count`, `total_excluded_count`, `unresolved_record_count`, `unresolved_record_total`, `target_status`, `target_record_count`, `target_excluded_count`, `target_variant_count`, `target_tag_count`, `target_basis_count`, `unlisted_record_count`, `record_pass_check_count`, `record_integrity`. `reference_value` — `reference_set_rows`, `reference_target_ref`, `reference_record_id`, `reference_record_file`, `reference_record_target`, `reference_record_pmid`, `reference_bibliography`, `reference_record_location`, `reference_record_tag`, `reference_record_hash`, `reference_record_check`(`reference{note: "kbase 가공본 값, 계산 아님", set_hash, kb_version, imported_at, source: "kbase_dist"|"kbase_pubmed"}`). 주장 키는 `statement_id, evidence_kind, source_handle, source_kind, source_schema, source_sha256, field_path, row_selector, subject, quantity, unit, exact_value, rendered_value, rounding, operation, reference`다. 포함하지 않은 파일의 포함 전례 수(`total_record_count`·`target_record_count`) 주장은 없다(`flagged_inclusion` 하나만, 미포함 수는 `total_excluded_count`·`target_excluded_count`). 다른 statement의 필드 경로, 계산값으로 참조 필드 인용·참조값으로 계산 필드 인용, 틀린 개수, 해석 문장, 다른 run·다른 종류의 결과, 결과와 맞지 않는 구조·번호 대응, 변조된 결과·보고서는 422 `report_evidence_invalid`. 만들기·다시 열기·다운로드는 연결을 다시 계산하지 않는다.

### 가져오기 명령 (CLI) `scripts/import_precedent_snapshots.py`
- 사용: `.venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로> [--dest PATH] [--yes]`. 사용자가 터미널에서 실행하며 서버·도구·작업·M13 흐름·`Run.call`은 부르지 않는다. 네트워크를 쓰지 않는다(로컬 파일과 읽기 전용 `git -C` 셋만).
  - `--from`(필수): 로컬 `kbase_kinase` 체크아웃의 저장소 루트(읽기만, 상대 경로는 현재 작업 폴더 기준, 폴더가 아니면 `invalid_input`). git 탐색을 그 폴더에서 멈추므로(`GIT_CEILING_DIRECTORIES`) 그 폴더 자체에 `.git`이 없으면(git 없는 복사본 등) 마지막 git 단계에서 `git` 거절이다.
  - `--dest`: 쓸 폴더. 없으면 `MW_PRECEDENT_REFERENCE_DIR`, 그것도 없으면 `<저장소>/.deps/precedent_reference`(상대 값은 저장소 루트 기준, 서버와 같은 규칙). 폴더가 아닌 대상, 다른 스냅샷 가족의 `active.json`이 있는 폴더, 링크인 `sets`는 거절한다.
  - `--yes`: 확인 화면(네트워크 사용 안 함, kbase 경로, HEAD 커밋, dist 커밋과 날짜, `dirty`, `kb_version`, 가져올 파일과 바이트·행 수, 쓸 폴더)의 대화형 확인을 생략한다. 호스트·URL을 받는 옵션·환경변수는 없다.
- 출력: 확인 화면, 끝나면 쓴 폴더·세트 해시·가져온 시각·파일별 행 수·`verification`(`records_hash_verified`·`references_without_hash`)·`dirty`, 경고(있으면).
- 종료 코드: 0 설치 완료, 1 거절(표준 오류에 거절 종류와 이유, `active.json`·이전 세트는 그대로), 2 인자 오류(argparse). 거절 종류(닫힌 집합 `REFUSAL_KINDS`): `invalid_input`, `target_invalid`, `dist_manifest`, `pins`, `dist_files`, `records`, `bibliography`, `git`, `manifest_invalid`, `cancelled`, `set_exists`, `install_failed`.
- 라이브러리 함수 `run_import(kbase_dir, dest, *, yes=False, now=None, input_fn=None)`는 시계(`now`, 시간대가 있는 `datetime`)와 입력 함수를 주입받고 출력 요약을 dict로 돌려준다(시험용, CLI는 이것을 부름).

## 과거 단계 실행기 (CLI)

`scripts/execute.py <phase> [--dry-run | --resume | --verify | --record-review N --review-report … --reviewed-files … --reviewer-model gpt-6-astra]`. `--verify`는 모델을 호출하지 않고 검토 해시와 수락 명령을 다시 확인한다. 실패하면 0이 아닌 값으로 끝나고 단계 상태를 `error`로, 통과하면 새 `completed_at`을 `phases/index.json`과 그룹 `index.json`에 기록한다. 기본 실행과 `--record-review`는 Codex·GPT-6 전용이다.
