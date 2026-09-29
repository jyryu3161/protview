# 시스템 구성

## 전체 구조

ProtView는 같은 컴퓨터 안에서 도는 두 프로세스와, 필요할 때만 띄우는 격리된 작업 프로세스로 이루어진다.

```
브라우저 (127.0.0.1:3000)
  └─ Next.js 15 프런트엔드 (frontend/)
       ├─ Mol* 5.11.0 뷰어 — 구조 바이트를 로컬 API에서 받아 WebGL로 렌더링
       └─ /api 요청을 로컬 백엔드 8000번으로 전달
            │ HTTP (loopback)
            ▼
FastAPI 백엔드 (backend/mw/api/app.py, 127.0.0.1:8000)
  ├─ Run.call 실행 경로 (runtime/orchestrator.py) ─ 도구 레지스트리 (tools/, config/tools.yaml)
  ├─ ObjectStore + EventLog (core/) ─ runs/<run_id>/ 아래 불변 객체·이벤트·SQLite 색인
  ├─ JobQueue + guardian (jobs/) ─ POSIX 프로세스 그룹으로 작업 프로세스 감독
  │     ├─ OpenMM 작업 프로세스 (프로젝트 .venv 인터프리터)
  │     ├─ ProLIF 작업 프로세스 (.deps/prolif/venv-locked 별도 인터프리터)
  │     └─ fpocket 작업 프로세스 (프로젝트 .venv, .deps/fpocket/env/bin/fpocket 고정 실행 파일)
  └─ EgressGate (egress/) ─ 유일한 외부 HTTP 출구
        └─ OpenRouter Decisions API (POST https://openrouter.ai/api/alpha/decisions)
           — 해당 run에서 온라인 모드를 명시적으로 켰을 때만
```

프런트엔드는 과학 값을 직접 계산하지 않는다. 화면의 모든 수치는 백엔드 handle을 읽어서 표시한다. 백엔드는 과학 계산의 유일한 실행자이고, 계산 경로는 동기 `Run.call`과 비동기 `JobQueue` 두 가지뿐이다.

## 구성 요소와 의존 방향

| 구성 요소 | 역할 | 의존 대상 |
|---|---|---|
| `frontend/app/page.tsx` | 메인 작업 화면: 업로드, 모델·전처리 선택, 접촉표, 기록, 보고서, 작업 패널 | `src/lib/api.ts`, `src/components/*` |
| `frontend/src/components/MolstarViewer.tsx` | Mol* 인스턴스를 소유하고 명령을 직렬화하는 브리지. 적용 확인(ack)을 만드는 유일한 곳 | Mol* 패키지, 백엔드 구조 바이트 |
| `frontend/src/components/ViewerAgentPanel.tsx` | 뷰어 세션 생성, 로컬 명령·자연어 요청, 온라인 동의 UI | `api.ts`, MolstarViewer 브리지 |
| `frontend/src/components/ChemicalWorkspace.tsx` | M11 화학 입력·미리보기·작업·결과 화면 | `src/lib/chemical.ts` |
| `backend/mw/api/app.py` | HTTP 경계. 입력 검증, run 디렉터리 제한, 업로드 한도 | runtime, core, jobs, egress, 보고서 모듈 |
| `backend/mw/runtime/orchestrator.py` | `Run`: 검증 → 캐시 → 가드 → 승인·예산 예약 → 실행 → 결과·실패 기록 → 과금 | core, tools |
| `backend/mw/tools/` | 버전이 붙은 과학 도구: structural(불러오기·전처리·기하 접촉), sasa(FreeSASA), comparison(원자 거리·Kabsch 정렬), openmm_method, energetic(Rosetta 사용 불가 표시) | gemmi, numpy, freesasa, openmm |
| `backend/mw/core/` | handle·객체 해시, 추가 전용 이벤트 로그, 잔기 식별자, 오류 분류 | 없음 (최하층) |
| `backend/mw/jobs/` | 영속 작업 큐, 프로세스 신원 기록, guardian의 정리·복구, 작업 프로세스 진입점 | core, runtime, psutil |
| `backend/mw/egress/`, `backend/mw/llm/` | 외부 요청 게이트(`gate.py`), 뷰어 의도 투영(`viewer.py`), Decisions 어댑터 | httpx, core |
| `backend/mw/*_reports.py`, `reports.py` | 증거가 연결된 불변 보고서 생성·검증·렌더링 | core, tools 결과 객체 |
| `backend/mw/viewer_intents.py`, `saved_scenes.py` | 뷰어 세션·대상 카탈로그·명령 컴파일러, 저장된 보기와 PNG | core, egress |
| `backend/mw/chemical_*.py` | M11 입력 가져오기, 번들 조립, 결과·보고서 | core, jobs |
| `backend/mw/pocket_input.py`, `pocket_output.py`, `pocket_bundle.py`, `pocket_reports.py`, `jobs/pocket_worker.py` | M12 단백질 투영·전송 PDB, fpocket 출력 엄격 파싱, capability·호출 키·게시·검증 읽기, 포켓 보고서, fpocket 실행 작업 프로세스 | core, jobs, tools |
| `frontend/src/components/PocketPanel.tsx` | M12 포켓 패널(메인 화면과 화학 작업 화면 공용) | `src/lib/pockets.ts`, MolstarViewer 브리지 |
| `backend/mw/workflows.py` | 고정 파이프라인 `inspect_complex`를 `Run.call` 순서로 실행 | runtime |
| `scripts/execute.py`, `phases/` | M0–M11 단계 기록과 과거 검증 도구. 제품 런타임과는 분리 | 없음 (제품 코드를 import하지 않음) |

의존은 위에서 아래로만 흐른다. `core/`는 다른 백엔드 모듈을 import하지 않고, 작업 프로세스는 API 서버 모듈을 import하지 않는다. ProLIF 작업 프로세스는 서버와 다른 인터프리터에서 돌며, 서버와는 JSON 파일과 입력 바이트로만 주고받는다.

## 대표 흐름: 업로드부터 보고서까지

1. `POST /runs` → run 디렉터리를 만들고, 설정·예산 한도·모드(`local_only`)를 담은 `run_started` 이벤트를 기록한다.
2. `POST /runs/{id}/uploads` → 최대 25 MiB의 PDB/mmCIF 바이트를 받아 검증된 업로드 ID를 돌려준다. 원래 파일 경로는 저장하지 않는다.
3. `POST /runs/{id}/commands` (`load_structure`, `model_index`) → `Run.call`이 인자를 정규화하고, 도구 이름·버전·유효 인자·입력 바이트 지문으로 호출 키를 만든다. 캐시에 없으면 gemmi로 파싱해 `structure` 객체를 저장한다. 객체 저장 → `object_created` 이벤트(전체 payload 포함) → SQLite 색인 순서로 기록한다.
4. `prepare_structure` → altloc·물·수소 정책을 적용하고 `prepared_structure`와 `preparation_manifest`를 만든다.
5. `compute_interactions` (정확한 리간드 인스턴스, cutoff 2.5–6.0 Å) → 중원자 사이 거리 행을 `interaction_set`에 저장한다. 접촉이 없으면 `null_result=true`인 성공이다.
6. 프런트엔드는 handle envelope(요약, 미리보기 최대 5행)을 받고, 전체 행은 `/objects?handle=…`에서 페이지 단위로 읽는다. 구조 바이트는 `/structures/bytes`에서 받아 Mol*에 올린다.
7. `POST /runs/{id}/reports` (`interaction_handle`) → 행에서 수치를 다시 계산해 필드 단위 증거로 검증한 `report_manifest@1`을 저장하고, Markdown/JSON 다운로드를 제공한다.

## 비싼 계산의 작업 경로

OpenMM 최소화, ProLIF 화학 계산, fpocket 포켓 검출은 `Run.call`로 실행하지 않는다. `/jobs`(제출, queued) → `/jobs/{id}/start`를 부르면, run의 첫 비싼 계산일 때 409로 승인 요청을 기록한다 → 사용자가 `/jobs/approve`로 승인을 명시적으로 기록한다 → 다시 `/start`를 부른다. OpenMM은 제출 전에 `/jobs/preflight`로 입력 적합성을 먼저 확인한다. 시작하면 run 실행 소유권을 얻은 뒤 비싼 계산 1단위를 예약하고, 새 프로세스 세션에서 고정된 모듈 진입점을 띄운다. 작업 프로세스는 개인 입력 파일로 제한된 JSON을 받는다. 결과는 스키마와 작업·시도 ID를 검증한 뒤에만 객체로 저장한다. 시간 초과나 취소가 나면 프로세스 그룹에 SIGTERM, 유예 후 SIGKILL을 보내고, 그룹이 비었음을 확인한 다음에 종료 상태를 기록한다.

## 외부 경계

- 넘어가는 것: 해당 run에서 온라인 모드와 뷰어 전용 동의를 켠 뒤, 사용자가 입력한 뷰어 요청 문장(최대 512자)과 생성된 별칭 대상 카탈로그(최대 256개)만 OpenRouter로 간다. M3 경로에서는 접촉 집계 숫자 몇 개만 간다.
- 넘어가지 않는 것(현재 코드 기준): 좌표, 구조 파일, 서열, 원자·리간드 이름, 로컬 경로, handle, run ID, 자격 증명, 이전 대화.
- 정책 변경(결정 0015, 2026-09-29): 구조·좌표·서열·리간드·분석 결과는 외부 모델로 보내도 된다. 아직 게이트 투영이 이 데이터 종류를 만들지 않으므로 실제 전송은 다음 단계에서 구현한다. 자격 증명은 계속 전송 금지다.
- 브라우저의 글꼴·스크립트·Mol* 자산·예시 구조는 모두 로컬 번들이다. 오프스크린 QA는 loopback이 아닌 요청을 전부 차단하고 기록한다.
- 초기 설치(`pip`, `npm ci`, ProLIF wheelhouse)에만 네트워크가 필요하다. 실행 중에는 다운로드하지 않는다.

## 저장소 배치

`runs/<run_id>/`에는 `events.jsonl`(원본 데이터), 불변 객체 파일, 없애도 되는 SQLite 색인, 작업 시도 디렉터리가 있다. 위치는 `MW_RUNS_DIR`로 바꿀 수 있다. 객체와 색인을 지워도 이벤트만으로 전부 다시 만들 수 있다. 이 복구 방식은 작은 구조 작업을 전제로 하며, 큰 궤적 데이터는 다루지 않는다.
