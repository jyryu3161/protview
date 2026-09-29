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
| 409 | `approval`(비싼 계산 승인 필요), `loop_stop`(자율 분기 가드), `cancelled`, `run_corrupt`(이벤트·payload 손상), `upload_conflict`, 멱등 요청 UUID 충돌, 뷰어 `stale_scene`·`stale_revision`(세션·세대·revision 불일치), 작업 시작의 `global_concurrency_busy`·`global_job_cleanup_pending`·`global_job_ledger_unavailable`(전역 heavy-worker 게이트) |
| 412 | `precondition`(선행 조건 부족, 예: 리간드 선택 필요, 승인할 작업 없음) |
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
| `POST /runs/{id}/commands` | `{tool, args, decided_by?: "human"|"rule"}`. tool은 `load_structure`, `prepare_structure`, `compute_interactions`, `compute_interface_sasa`, `measure_distance`, `align_structures`, `compile_state` 중 하나 | 200, `{ok: true, handle: <envelope>}` | 도구 실패 본문(422/412/429/503), 409 |
| `POST /runs/{id}/inspect_complex` | 업로드 ID 또는 같은 run의 구조 handle, 모델, 전처리 정책, 선택적 리간드, cutoff | 완료된 handle 목록 또는 `needs_selection`/`no_ligand` | 412, 422, 409 |

`load_structure`의 `source`는 이 run의 업로드 ID여야 한다. 파일 경로나 URL은 받지 않는다. `decided_by`는 기록용 출처 정보일 뿐이며, 승인 권한을 주지 않는다.

## 읽기

| 호출 | 설명 |
|---|---|
| `GET /capabilities` | 모드, 에너지 프로토콜 표, `methods.{interface_sasa, openmm_protein_minimize, chemical_interactions, pocket_detection}` 사용 가능 여부와 이유, 지원·미지원 기능 목록. 무거운 엔진을 import하지 않는다 |
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
| `POST /runs/{id}/method_reports` | SASA·OpenMM·거리·정렬 결과 handle | 201, 방법 보고서 handle |
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
| `POST/GET /runs/{id}/viewer/scenes`, `/scenes/selected` | `viewer_scene@1` 저장 요청과 현재 바인딩(본문 최대 64 KiB) | 201, 보기 handle. 바인딩이 오래됐으면 거부, run당 100개 |
| `POST/GET /runs/{id}/viewer/figures`, `/figures/selected`, `/figures/download?format=png|json` | 저장된 보기 handle, PNG(최대 8 MiB) | 201, 그림 handle. run당 100개, PNG 총 64 MiB |

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

## 과거 단계 실행기 (CLI)

`scripts/execute.py <phase> [--dry-run | --resume | --verify | --record-review N --review-report … --reviewed-files … --reviewer-model gpt-6-astra]`. `--verify`는 모델을 호출하지 않고 검토 해시와 수락 명령을 다시 확인한다. 실패하면 0이 아닌 값으로 끝나고 단계 상태를 `error`로, 통과하면 새 `completed_at`을 `phases/index.json`과 그룹 `index.json`에 기록한다. 기본 실행과 `--record-review`는 Codex·GPT-6 전용이다.
