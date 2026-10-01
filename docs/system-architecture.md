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
  ├─ 참조 스냅샷 읽기 (reference_snapshots.py) ─ .deps/reference/ (MW_REFERENCE_DIR, 읽기 전용)
  │     └─ 쓰는 쪽: scripts/import_reference_snapshots.py ← ../kbase_kinase/ref (사용자가 실행, 서버는 kbase를 읽지 않음)
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
| `frontend/app/page.tsx` | 최상위 탭을 두고, 구조 분석 탭 안에 메인 작업 화면(업로드, 모델·전처리 선택, 접촉표, 기록, 보고서, 작업 패널)과 화학 작업 화면을 담는다 | `src/lib/api.ts`, `src/components/*` |
| `frontend/src/components/WorkspaceTabs.tsx` | M14 최상위 탭 4개와 전역 run·예산 줄. 구조 분석 탭은 숨긴 채 유지, 기능 없는 탭은 사용할 수 없음·여는 단계 안내 | `src/lib/workspace-tabs.ts` |
| `frontend/src/components/ReportLibraryPanel.tsx` | M14 지식·보고서 탭의 run 전체 보고서·그림·완료된 흐름 요약 목록, 내용 보기, 기존 다운로드 | `src/lib/report-library.ts`, `api.ts`(기존 읽기 API만) |
| `frontend/src/components/NumberingPanel.tsx` | M15 지식·보고서 탭의 잔기 번호 대응 화면: 스냅샷 상태, 대응 만들기(PDB ID 확인·SIFTS 미리 채움·UniProt 검색), 대응 목록·체인 요약·행 표, 보고서 만들기 | `src/lib/numbering.ts`, `api.ts` |
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
| `backend/mw/reference_snapshots.py` | M15 로컬 참조 폴더의 사용 중 세트를 호출마다 한 번 고정(`PinnedSet`)하고 매니페스트·파일 해시를 확인한다. 내용은 해석하지 않는다 | core(표준 라이브러리) |
| `backend/mw/sifts_mapping.py`, `sequence_alignment.py`, `klifs_numbering.py` | M15 순수 해석·계산: kbase SIFTS 형식 해석, Gotoh 전역 정렬(numpy), KLIFS 포켓 → UniProt 위치 표 | reference_snapshots(SIFTS만), numpy |
| `backend/mw/residue_numbering.py`, `tools/numbering.py` | M15 `map_residue_numbering`: 사슬 잔기 판단, 체인별 방법 결정, 행 상태, `residue_numbering_map@1`. 도구 모듈의 사전 검사 훅이 세트 고정·입력 검증을 구현 전에 한다 | 위 세 모듈, tools(structural 파서), core |
| `backend/mw/numbering_reads.py`, `numbering_reports.py` | M15 읽기 API(스냅샷·SIFTS 체인·UniProt 검색·PDB ID 제안·대응 목록·행 페이지·capability)와 계산값·참조값을 분리한 보고서 | residue_numbering, reports, core |
| `backend/mw/site_annotation.py`, `tools/site_annotation.py` | M16 `annotate_reference_sites`: 번호 대응 1개 + 선택적 기하 접촉 결과 1개를 KLIFS 주요 10자리 기준으로 합친 `reference_site_annotation@1`. 사전 검사 훅이 두 handle·같은 구조를 구현 전에 검사한다. 참조 폴더를 읽지 않는다. 목록·상세 읽기 API | residue_numbering 결과, tools(structural 잔기 목록), core |
| `backend/mw/site_annotation_reports.py` | M16 부위 주석 보고서: 참조값(대응 행)·계산값(접촉 행 count·minimum) 분리, 다시 열 때 주석을 대응·접촉·구조 잔기와 대조 | site_annotation, reports, core |
| `frontend/src/components/SiteAnnotationPanel.tsx` | M16 구조 분석 탭 메인 화면의 참조 주석 패널: 같은 구조의 대응·접촉 결과 선택, 주석 만들기·켜기, 범례, 부위 표, 보고서 만들기. Mol* 그리기는 MolstarViewer 브리지의 `siteAnnotation` | `src/lib/site-annotation.ts`, `api.ts`, MolstarViewer 브리지 |
| `backend/mw/workflows.py` | 고정 파이프라인 `inspect_complex`를 `Run.call` 순서로 실행 | runtime |
| `backend/mw/analysis_plans.py` | M13 템플릿 6개, 불변 계획 `analysis_plan@1` 컴파일·검증·저장, 계약 이름 ↔ 실제 도구·프로토콜·보고서 대응 표, `/capabilities`의 `analysis_workflows`. 과학 구현을 부르지 않는다 | core, tools(순수 검사), 방법별 읽기 전용 사전 검사 |
| `backend/mw/analysis_executions.py` | M13 실행 driver: 실행 기록 접기, 계획 승인·철회, 한 단계 진행, 재시도, 범위 한정 중지, 충돌 복구, `workflow_summary@1`. 과학은 `ExecutionLink`를 단 `Run.call`·`JobQueue`·기존 보고서 함수로만 실행 | analysis_plans, runtime, jobs, 보고서 모듈 |
| `frontend/src/components/AnalysisWorkflowPanel.tsx` | M13 분석 흐름 패널(메인 화면과 화학 작업 화면 공용): 화면 선택 가져오기, 계획 미리보기, 두 승인, 단계 목록, 결과 열기, 요약 | `src/lib/analysis.ts`, `api.ts`, PocketPanel·페이지의 결과 열기 콜백 |
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

## 분석 흐름 (M13)

`POST /analysis/plans`는 템플릿과 저장된 객체 메타데이터·capability만 읽어 불변 계획을 저장한다(과학 호출 없음). 실행을 만들고 계획을 승인하면, 사용자가 "다음 단계 실행"을 누를 때마다 driver가 짧은 워크플로 잠금 안에서 요청을 입장시키고 이전 자식 결과를 조정한 뒤, 다음 단계의 dispatch 기록을 남기고 잠금을 놓은 채 자식 하나를 실행한다. `run_call` 단계는 `Run.call`, `durable_job` 단계는 `JobQueue` 제출+시작, `report` 단계는 기존 보고서 함수다. 자식에는 내부 `ExecutionLink(execution_id, step_id, operation_id)`가 붙어, 자식 입장과 같은 전이 안에서 승인·순서·중지·인자 일치를 확인하고 물리 시도마다 시도 수를 먼저 기록한다. 링크는 이벤트의 `execution_link` 필드로 남고, 재시작 뒤에는 이 링크로 정확한 자식을 찾아 복구한다. 백그라운드 루프는 없고, 끝난 작업의 반영도 다음 요청이 한다. 흐름은 외부 요청을 하지 않는다.

## 참조 스냅샷과 번호 대응 (M15)

참조 데이터는 사용자가 실행하는 가져오기 명령 `scripts/import_reference_snapshots.py`만 쓴다. 이 명령이 `../kbase_kinase/ref`의 가공 스냅샷을 해시 대조 뒤 `.deps/reference/sets/<set_hash>/`로 복사하고 `active.json`을 rename으로 바꾼다. 서버는 이 폴더만 읽는다. `POST /commands`의 `map_residue_numbering`은 `Run.call`에서 사전 검사 훅이 세트를 고정하고 구조·스냅샷으로 입력을 검증한 뒤(세트 해시가 호출 키에 들어감), 구현이 같은 세트로 SIFTS 답·정렬 답·행 상태·KLIFS 번호를 만들어 `reference_snapshot_set@1`(처음 쓰는 세트면)과 `residue_numbering_map@1`을 저장한다. 대응 객체는 세트 해시와 계산에 쓴 참조 행을 담으므로 참조 폴더 없이 이벤트만으로 다시 열린다. 지식 탭은 읽기 API로 스냅샷·대응을 보여 주고, 보고서는 기존 `method_reports` 경로로 만든다. 네트워크는 쓰지 않는다.

## 참조 주석 (M16)

구조 분석 탭 패널에서 사용자가 현재 표시 구조와 같은 handle의 번호 대응과(선택적으로) 기하 접촉 결과를 고르면, `POST /commands`의 `annotate_reference_sites`가 `Run.call` 값싼 도구로 `reference_site_annotation@1`을 저장한다. 결과는 대응 객체의 행과 접촉 행을 그대로 옮겨 담으므로 이벤트만으로 다시 열린다. 패널은 읽기 API로 주석을 받아 MolstarViewer 브리지에 넘기고, 브리지는 검증된 원자 카탈로그로만 점선 끝 원자를 찾아 그린 뒤 native readback으로 적용을 확인한다. 주석이 켜진 보기는 `viewer_scene@2`, 그 그림은 `viewer_figure@2`(범례 합성 여부 기록)로 저장되고, 보고서는 기존 `method_reports` 경로로 만든다. 네트워크는 쓰지 않는다.

## 외부 경계

- 넘어가는 것: 해당 run에서 온라인 모드와 뷰어 전용 동의를 켠 뒤, 사용자가 입력한 뷰어 요청 문장(최대 512자)과 생성된 별칭 대상 카탈로그(최대 256개)만 OpenRouter로 간다. M3 경로에서는 접촉 집계 숫자 몇 개만 간다.
- 넘어가지 않는 것(현재 코드 기준): 좌표, 구조 파일, 서열, 원자·리간드 이름, 로컬 경로, handle, run ID, 자격 증명, 이전 대화.
- 정책 변경(결정 0015, 2026-09-29): 구조·좌표·서열·리간드·분석 결과는 외부 모델로 보내도 된다. 아직 게이트 투영이 이 데이터 종류를 만들지 않으므로 실제 전송은 다음 단계에서 구현한다. 자격 증명은 계속 전송 금지다.
- 브라우저의 글꼴·스크립트·Mol* 자산·예시 구조는 모두 로컬 번들이다. 오프스크린 QA는 loopback이 아닌 요청을 전부 차단하고 기록한다.
- 초기 설치(`pip`, `npm ci`, ProLIF wheelhouse)에만 네트워크가 필요하다. 실행 중에는 다운로드하지 않는다. 참조 스냅샷 가져오기도 로컬 kbase 체크아웃에서 복사할 뿐 네트워크를 쓰지 않는다.

## 저장소 배치

`runs/<run_id>/`에는 `events.jsonl`(원본 데이터), 불변 객체 파일, 없애도 되는 SQLite 색인, 작업 시도 디렉터리가 있다. 위치는 `MW_RUNS_DIR`로 바꿀 수 있다. 참조 스냅샷은 run 밖의 `.deps/reference/`(`MW_REFERENCE_DIR`)에 있고, 세트 폴더는 지우지 않는다. 객체와 색인을 지워도 이벤트만으로 전부 다시 만들 수 있다. 이 복구 방식은 작은 구조 작업을 전제로 하며, 큰 궤적 데이터는 다루지 않는다.
