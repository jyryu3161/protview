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
  ├─ 반응 참조 스냅샷 읽기 (reaction_snapshots.py) ─ .deps/reaction_reference/ (MW_REACTION_REFERENCE_DIR, 읽기 전용)
  │     └─ 쓰는 쪽: scripts/import_reaction_references.py ← HTTPS GET만: www.ebi.ac.uk(M-CSA)·rest.uniprot.org·www.rhea-db.org
  │          (사용자가 터미널에서 실행, mw를 import하지 않음. 서버·도구·작업은 이 명령을 부르지 않음)
  ├─ JobQueue + guardian (jobs/) ─ POSIX 프로세스 그룹으로 작업 프로세스 감독
  │     ├─ OpenMM 작업 프로세스 (프로젝트 .venv 인터프리터)
  │     ├─ ProLIF 작업 프로세스 (.deps/prolif/venv-locked 별도 인터프리터)
  │     ├─ RDKit 리간드 작업 프로세스 (M17 ligand_worker.py, 같은 venv-locked 인터프리터)
  │     ├─ qvina 도킹 작업 프로세스 (M18 docking_worker.py, .deps/docking/venv-locked 별도 인터프리터,
  │     │    자식으로 .deps/qvina/env/bin/qvina2 고정 실행 파일)
  │     ├─ qvina 일괄 도킹 작업 프로세스 (M19 docking_batch_worker.py, 같은 인터프리터, docking_worker.py를
  │     │    파일 경로로 불러 행마다 같은 계산, 자식 qvina2)
  │     └─ fpocket 작업 프로세스 (프로젝트 .venv, .deps/fpocket/env/bin/fpocket 고정 실행 파일)
  └─ EgressGate (egress/) ─ 외부 HTTP 출구 (예외는 위 반응 참조 가져오기 명령 하나, 결정 0034)
        └─ OpenRouter Decisions API (POST https://openrouter.ai/api/alpha/decisions)
           — 뷰어 의도·M3: 해당 run에서 온라인 모드를 명시적으로 켰을 때만 (VIEWER_GATE)
           — M24 과학 전송: 과학 전송 동의가 켜진 run에서 사람이 미리보기 본문을 승인했을 때만 (SCIENCE_GATE)
             (M25 루프 투영도 같은 라우트·같은 게이트로만, 승인 이벤트 앞의 루프 검사를 더 통과해야 함)
```

프런트엔드는 과학 값을 직접 계산하지 않는다. 화면의 모든 수치는 백엔드 handle을 읽어서 표시한다. 백엔드는 과학 계산의 유일한 실행자이고, 계산 경로는 동기 `Run.call`과 비동기 `JobQueue` 두 가지뿐이다.

## 구성 요소와 의존 방향

| 구성 요소 | 역할 | 의존 대상 |
|---|---|---|
| `frontend/app/page.tsx` | 최상위 탭을 두고, 구조 분석 탭 안에 메인 작업 화면(업로드, 모델·전처리 선택, 접촉표, 기록, 보고서, 작업 패널)과 화학 작업 화면을 담는다 | `src/lib/api.ts`, `src/components/*` |
| `frontend/src/components/WorkspaceTabs.tsx` | M14 최상위 탭 4개와 전역 run·예산 줄. 구조 분석 탭은 숨긴 채 유지, 기능 없는 탭은 사용할 수 없음·여는 단계 안내 | `src/lib/workspace-tabs.ts` |
| `frontend/src/components/ReportLibraryPanel.tsx` | M14 지식·보고서 탭의 run 전체 보고서·그림·완료된 흐름 요약 목록, 내용 보기, 기존 다운로드 | `src/lib/report-library.ts`, `api.ts`(기존 읽기 API만) |
| `frontend/src/components/NumberingPanel.tsx` | M15 지식·보고서 탭의 잔기 번호 대응 화면: 스냅샷 상태, 대응 만들기(PDB ID 확인·SIFTS 미리 채움·UniProt 검색), 대응 목록·체인 요약·행 표, 보고서 만들기 | `src/lib/numbering.ts`, `api.ts` |
| `frontend/src/components/JevPanel.tsx` | M24 지식·보고서 탭의 JEV 판정 영역(번호 대응 화면과 보고서 목록 사이): 과학 전송 동의, 후보 집합·후보 고르기, 보낼 내용 만들기·미리보기(정확한 본문), 승인·전송, 결과 카드, 전송 기록, 보고서 만들기. 페이지는 동의 상태로 전역 줄의 "과학 전송 허용" 표시를 정한다 | `src/lib/jev.ts`, `api.ts`, `LigandPanel`의 `FilterForm` |
| `frontend/src/components/MolstarViewer.tsx` | Mol* 인스턴스를 소유하고 명령을 직렬화하는 브리지. 적용 확인(ack)을 만드는 유일한 곳 | Mol* 패키지, 백엔드 구조 바이트 |
| `frontend/src/components/ViewerAgentPanel.tsx` | 뷰어 세션 생성, 로컬 명령·자연어 요청, 온라인 동의 UI | `api.ts`, MolstarViewer 브리지 |
| `frontend/src/components/ChemicalWorkspace.tsx` | M11 화학 입력·미리보기·작업·결과 화면 | `src/lib/chemical.ts` |
| `backend/mw/api/app.py` | HTTP 경계. 입력 검증, run 디렉터리 제한, 업로드 한도 | runtime, core, jobs, egress, 보고서 모듈 |
| `backend/mw/runtime/orchestrator.py` | `Run`: 검증 → 캐시 → 가드 → 승인·예산 예약 → 실행 → 결과·실패 기록 → 과금 | core, tools |
| `backend/mw/tools/` | 버전이 붙은 과학 도구: structural(불러오기·전처리·기하 접촉), sasa(FreeSASA), comparison(원자 거리·Kabsch 정렬), openmm_method, energetic(Rosetta 사용 불가 표시) | gemmi, numpy, freesasa, openmm |
| `backend/mw/core/` | handle·객체 해시, 추가 전용 이벤트 로그, 잔기 식별자, 오류 분류 | 없음 (최하층) |
| `backend/mw/jobs/` | 영속 작업 큐, 프로세스 신원 기록, guardian의 정리·복구, 작업 프로세스 진입점 | core, runtime, psutil |
| `backend/mw/egress/`, `backend/mw/llm/` | 외부 요청 게이트(`gate.py`), 뷰어 의도 투영(`viewer.py`), M24 과학 전송 단계(`science.py`, `EgressGate.request_science`가 위임), Decisions 어댑터 | httpx, core, `jev_projection`·`jev_sends`(science.py) |
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
| `backend/mw/ligand_constants.py`, `ligand_inputs.py`, `ligand_site.py`, `ligand_filters.py` | M17 서버 쪽 순수 모듈(RDKit 없음): 닫힌 이유 집합·상한·고정 한계 문장, building block 가져오기 경량 검사, 점검 객체 결합 목록으로 하는 부위 그래프 검사, 저장 후보 행의 필터 평가·정렬·페이지 | core(표준 라이브러리) |
| `backend/mw/ligand_bundle.py`, `jobs/ligand_worker.py` | M17 리간드 작업 경로: capability handshake(작업 모듈 `--handshake`만 실행), 입장 검사·호출 키·스테이징(48 MiB), 게시 검증, `ligand_inspection@1`·`ligand_candidate_set@1` 검증 읽기. 작업 모듈은 `.deps/prolif/venv-locked`에서 RDKit으로 점검(원자 표·번호 붙은 2D SVG·속성·block·규칙 검증)과 생성(고정 교체·사용자 반응 규칙·중복·상한·속성·PAINS)을 한다 | 서버: core, ligand 순수 모듈. 작업 모듈: RDKit, `ligand_constants` |
| `backend/mw/ligand_reads.py`, `ligand_reports.py` | M17 읽기 API(준비 상태·목록·상세·후보 행 페이지·부위 미리보기, 이벤트 없음)와 요약 증거 보고서(`count_where`) | ligand_bundle, ligand 순수 모듈, reports, core |
| `frontend/src/components/LigandPanel.tsx` | M17 리간드 설계·탐색 탭 화면: 가져오기, 점검·생성 작업(승인·예산), 번호 붙은 그림(`<img>` data URI)·원자 표·부위 체크, 후보 표·필터·정렬·페이지, 보고서 만들기 | `src/lib/ligand.ts`, `api.ts` |
| `backend/mw/docking_constants.py`, `docking_inputs.py` | M18 서버 쪽 순수 모듈(RDKit·Meeko 없음): 닫힌 이유 집합·값 범위·점수 문구·고정 한계 문장 11개(의존성 없음, 작업 모듈도 파일 경로로 읽음), 작업 인자 입장 검사·호출 키 입력, gemmi로 수용체 인스턴스 목록·M11 규칙 수용체 검사 | core, `chemical_inputs`(상수·gemmi 파서), `tools/structural`(`_res_ref`) |
| `backend/mw/docking_bundle.py`, `jobs/docking_worker.py` | M18 도킹 작업 경로: capability(`qvina2` 해시 + 작업 모듈 `--handshake`만, qvina 실행 없음), 입장 검사·호출 키·스테이징(48 MiB), 게시 검증(접촉의 수용체 원자·거리 재대조), `docking_result@1` 검증 읽기. 작업 모듈은 `.deps/docking/venv-locked`에서 수용체 검사·M11 화학 추론(MDAnalysis)·Meeko PDBQT·리간드 검사·RDKit 형태 생성·`qvina2` 실행(자유 검색 또는 `--score_only`)·포즈 복원·기하 접촉을 한다 | 서버: core, docking 순수 모듈, `ligand_bundle`(후보 집합 검증 읽기). 작업 모듈: gemmi, MDAnalysis, Meeko, RDKit, `docking_constants`, `qvina2` |
| `backend/mw/docking_reads.py`, `docking_reports.py` | M18 읽기 API(준비 상태·수용체 인스턴스·결과 목록·상세·접촉 페이지·포즈 SDF, 이벤트 없음)와 계산값 증거 보고서(`count_where`, 점수 최솟값·최댓값) | docking_bundle, docking 순수 모듈, `ligand_reports`·`numbering_reports`·`pocket_reports`(공용 검사·한도), reports, core |
| `frontend/src/components/DockingPanel.tsx` | M18 리간드 설계·탐색 탭의 도킹 영역(후보 영역 다음): 수용체·사이드카·SDF 가져오기, 인스턴스 선택, 리간드 출처·방식·상자·값·확인 세 항목, 작업(승인·예산·취소), 요약·모드 표·접촉 표·SDF 내려받기·거부 목록, 보고서 만들기 | `src/lib/docking.ts`, `api.ts` |
| `backend/mw/docking_batch_constants.py`, `docking_batch_inputs.py`, `docking_batch_bundle.py` | M19 서버 쪽 순수 모듈(RDKit·Meeko 없음): 상한·상태·이유 집합·고정 문장 B1–B3(의존성 없음, 작업 모듈도 파일 경로로 읽음), 일괄 인자 입장 검사·행별 M18 인자·`batch_input_sha256`·재사용 색인·예산 필요량·부족분·증액량, 스테이징 관찰에서 요약 행·상태를 만들고 요약을 검증 | `docking_inputs`·`docking_bundle`(행 입장·호출 키), `ligand_bundle`(후보 집합 검증 읽기), core |
| `backend/mw/docking_batch_jobs.py`, `jobs/docking_batch_worker.py` | M19 일괄 작업 경로: capability(M18 capability + 일괄 작업 모듈 `--handshake`), 입장·재사용 계획·예산 부족 거절, 스테이징, 종료 상태마다 행 게시와 요약 게시(`finish`), 사람 증액(`limit_approval`), 진행 표시, 요약 검증 읽기. 작업 모듈은 `.deps/docking/venv-locked`에서 수용체를 한 번 준비하고 행마다 M18 `dock_row`를 부르며 행별 스테이징 파일·행·전체 시계·출력 총량을 맡는다 | 서버: core, docking·docking_batch 순수 모듈, jobs, runtime(`raise_limits`). 작업 모듈: `docking_worker.py`(파일 경로), `docking_batch_constants` |
| `backend/mw/docking_batch_reads.py`, `docking_batch_reports.py` | M19 읽기 API(시작 전 확인·요약 목록·상세, 이벤트 없음)와 계산값 증거 보고서(요약 행 점수 + 행 결과 첫 행 점수) | docking_batch_jobs, `docking_reports`·`pocket_reports`(공용 검사), reports, core |
| `frontend/src/components/DockingBatchPanel.tsx` | M19 리간드 설계·탐색 탭의 일괄 도킹 영역(도킹 영역 다음): 가져온 수용체·사이드카·부모 SDF·후보 집합 고르기, M17 필터(`FilterForm` 공용) + 체크박스, 방식·부모 기준 행·상자·값·확인, 시작 전 확인·증액 승인, 작업(승인·폴링·취소), 결과표·정렬, 행 상세는 도킹 영역(`openRequest`)으로, 보고서 만들기 | `src/lib/docking-batch.ts`, `src/lib/docking.ts`, `api.ts`, `LigandPanel`·`DockingPanel`의 공용 구성 요소 |
| `frontend/src/components/SiteAnnotationPanel.tsx` | M16 구조 분석 탭 메인 화면의 참조 주석 패널: 같은 구조의 대응·접촉 결과 선택, 주석 만들기·켜기, 범례, 부위 표, 보고서 만들기. Mol* 그리기는 MolstarViewer 브리지의 `siteAnnotation` | `src/lib/site-annotation.ts`, `api.ts`, MolstarViewer 브리지 |
| `backend/mw/jev_constants.py`, `jev_projection.py`, `tools/jev.py` | M24 과학 전송의 닫힌 상수·질문·고정 문장(표준 라이브러리만), 순수 와이어 빌더·와이어 검사·이웃·구간 기하·본문 인코딩·`validated_projection`·`parse_choice`(numpy), 값싼 도구 `build_jev_projection`(사전 검사 훅 + `jev_projection@1` 저장) | core, `ligand_bundle`·`ligand_filters`(M17 검증 읽기·필터), `mutation_candidates`(M20 검증), tools(structural 파서) |
| `backend/mw/jev_sends.py`, `jev_reports.py` | M24 과학 전송 동의·상태·미리보기, 승인 전송 `run_send`(진행 중 집합 `ACTIVE_SENDS`, 게이트 호출, 결과 기록), 이벤트에서 도출하는 전송 기록, 제안 객체 `jev_choice@1`과 검증, 보고서(계산값·모델 응답 분리, 보내지 않음). 게이트는 import하지 않고 라우트가 넘긴 인스턴스를 쓴다 | jev_constants, jev_projection, `ligand_bundle`·`mutation_candidates`, reports·`numbering_reports`, core |
| `backend/mw/jev_loop_constants.py`, `jev_loop_projection.py`, `jev_loops.py`, `jev_loop_result.py` | M25 JEV 설계 루프의 순수 모듈: 닫힌 상수·질문 지시문·고정 문장(표준 라이브러리만), 섞기 `sha256_order_v1`·루프 와이어·본문·`parse_loop_choice`·제안 `jev_loop_choice@1`과 검증(M24 빌더·인코더를 바꾸지 않고 불러 씀), 이벤트·작업 기록·저장 결과 요약에서 `jev_loop@1`을 도출하는 `derive_loop`·입장 판정·작업 귀속 `job_owners`, 요약 `jev_loop_result@1` 만들기·검증. 저장소·로그·네트워크를 읽지 않는다 | jev_constants(`EVENT_*` 속성), jev_projection, `docking_constants`·`mutation_model_constants`, core |
| `backend/mw/jev_loop_store.py`, `tools/jev_loop.py`, `jev_loop_reports.py` | M25 run을 읽고 쓰는 층: 한 번 읽기 보기(`LoopReadView`), 만들기 입장과 `jev_loop_created`, 단독 M18·M21 요청·호출 키, 저장 결과·제안 읽기, 계산 판정·`jev_loop_compute_approved`·도킹 포기·끝내기, `methods.jev_loop`, 값싼 도구 `build_jev_loop_projection`(사전 검사 훅 + `jev_loop_projection@1` 저장), 보고서 `jev_loop`. `jev_sends`·게이트를 import하지 않고 작업을 제출·시작하지 않는다(계산 시작 라우트가 `JobQueue`로) | 위 순수 모듈, `docking_batch_inputs`·`docking_bundle`·`mutation_model_bundle`·`ligand_bundle`(검증 읽기·입장), jobs(작업 기록 읽기), reports, core |
| `frontend/src/components/JevLoopPanel.tsx` | M25 리간드 설계·탐색 탭(M22 GA 영역 다음)과 단백질 공학 탭(M23 서열 GA 영역 다음)의 "JEV 루프" 영역(갈래 prop): 동의, 만들기, 보낼 내용 만들기·미리보기·승인·전송, JEV 판정 카드, 계산 시작·직접 지정·도킹 시작·포기, 후보 표·바퀴 표, 끝내기·요약·보고서 | `src/lib/jev-loop.ts`, `src/lib/jev.ts`, `src/lib/docking.ts`, `api.ts`, `LigandPanel`의 `FilterForm`, `MutationModelPanel`의 `PairInputs` |
| `backend/mw/reaction_knowledge_constants.py`, `reaction_snapshots.py` | M26 표준 라이브러리 모듈: 닫힌 집합·상한·고정 문장·가공 행 형식(`SOURCE_FORMATS`)·허용 호스트(`ALLOWED_HOSTS`)·정규 JSON·매니페스트 검사(`mw` import 없음, 가져오기 명령도 파일 경로로 읽음), 반응 참조 폴더의 사용 중 세트를 호출마다 한 번 고정(`PinnedReactionSet`)하고 파일 해시·바이트·행 수를 확인. 내용은 해석하지 않는다. M15 스냅샷 모듈과 폴더·포인터·캐시가 따로다 | 표준 라이브러리(`reaction_snapshots`는 상수 모듈만) |
| `backend/mw/reaction_knowledge.py`, `tools/reaction_knowledge.py` | M26 `link_reaction_knowledge`: 고정한 세트의 가공 파일 해석·색인(세트 하나 캐시), 체인마다 M-CSA 절(M-CSA가 적은 PDB 항목 기준 대응)·UniProt 절(번호 대응이 있는 체인만 구조 잔기에 연결)·반응 절, `reaction_knowledge@1`과 `validated_result`. 도구 모듈의 사전 검사 훅이 세트 고정·입장 검사를 구현 전에 한다. M20 v2 도구(`tools/mutations.py`)와 M20 보고서도 `validated_result`로 이 결과를 읽는다 | reaction 상수·스냅샷 모듈, `residue_numbering`(사슬 잔기 규칙), `mutation_candidates`·`mutation_constants`(표준 이름), tools(structural 파서), core |
| `backend/mw/reaction_knowledge_reads.py`, `reaction_knowledge_reports.py` | M26 읽기 API(스냅샷 상태·PDB ID의 M-CSA 항목·결과 목록·상세, 이벤트 없음)와 계산값(저장 행 개수)·참조값을 분리한 보고서 | reaction_knowledge, `mutation_reports`(공용 한도·금지어), reports, core |
| `frontend/src/components/ReactionKnowledgePanel.tsx` | M26 지식·보고서 탭의 "효소 반응 지식" 영역(번호 대응 화면과 JEV 영역 사이): 스냅샷 상태, 연결 요청(구조·확인한 PDB ID·체인 accession·선택적 번호 대응, M-CSA 제안), 체인별 M-CSA·UniProt·반응 절 표, 보고서 만들기. 뷰어 표시 없음 | `src/lib/reaction-knowledge.ts`(→ `src/lib/numbering.ts`), `api.ts` |
| `scripts/import_reaction_references.py` | M26 반응 참조 가져오기 명령(사용자가 터미널에서 실행): 허용 호스트 셋에 HTTPS GET만 보내 받은 응답을 가공하고, 검증 뒤 새 세트를 원자적으로 설치하며 요청마다 기록한다. 제품 런타임과는 분리 | 표준 라이브러리(`urllib`), `reaction_knowledge_constants.py`(파일 경로로만), 로컬 M15 사용 중 세트(kinase accession 목록). `mw`를 import하지 않음 |
| `backend/mw/workflows.py` | 고정 파이프라인 `inspect_complex`를 `Run.call` 순서로 실행 | runtime |
| `backend/mw/analysis_plans.py` | M13 템플릿 6개, 불변 계획 `analysis_plan@1` 컴파일·검증·저장, 계약 이름 ↔ 실제 도구·프로토콜·보고서 대응 표, `/capabilities`의 `analysis_workflows`. 과학 구현을 부르지 않는다 | core, tools(순수 검사), 방법별 읽기 전용 사전 검사 |
| `backend/mw/analysis_executions.py` | M13 실행 driver: 실행 기록 접기, 계획 승인·철회, 한 단계 진행, 재시도, 범위 한정 중지, 충돌 복구, `workflow_summary@1`. 과학은 `ExecutionLink`를 단 `Run.call`·`JobQueue`·기존 보고서 함수로만 실행 | analysis_plans, runtime, jobs, 보고서 모듈 |
| `frontend/src/components/AnalysisWorkflowPanel.tsx` | M13 분석 흐름 패널(메인 화면과 화학 작업 화면 공용): 화면 선택 가져오기, 계획 미리보기, 두 승인, 단계 목록, 결과 열기, 요약 | `src/lib/analysis.ts`, `api.ts`, PocketPanel·페이지의 결과 열기 콜백 |
| `scripts/execute.py`, `phases/` | M0–M11 단계 기록과 과거 검증 도구. 제품 런타임과는 분리 | 없음 (제품 코드를 import하지 않음) |

의존은 위에서 아래로만 흐른다. `core/`는 다른 백엔드 모듈을 import하지 않고, 작업 프로세스는 API 서버 모듈을 import하지 않는다. ProLIF·RDKit 리간드 작업 프로세스는 서버와 다른 인터프리터에서 돌며, 서버와는 JSON 파일과 입력 바이트로만 주고받는다. 리간드 작업 모듈이 서버 쪽에서 가져오는 것은 의존성 없는 `ligand_constants.py`뿐이다. M18 도킹 작업 모듈도 서버와 다른 인터프리터(`.deps/docking/venv-locked`)에서 돌며, 서버 쪽에서 가져오는 것은 의존성 없는 `docking_constants.py`(파일 경로로 읽음)뿐이고 `qvina2`는 이 작업 모듈(의 함수)만 자식 프로세스로 실행한다. M19 일괄 작업 모듈은 같은 인터프리터에서 `docking_worker.py`와 의존성 없는 `docking_batch_constants.py`만 파일 경로로 불러 쓴다. M26 가져오기 명령은 `mw`를 import하지 않고 의존성 없는 `reaction_knowledge_constants.py`만 파일 경로로 불러 쓰며, 서버·도구·작업은 이 명령을 부르지 않는다. 둘은 반응 참조 폴더의 파일로만 이어지고, 서버 쪽 M26 모듈은 네트워크 모듈을 import하지 않는다.

## 대표 흐름: 업로드부터 보고서까지

1. `POST /runs` → run 디렉터리를 만들고, 설정·예산 한도·모드(`local_only`)를 담은 `run_started` 이벤트를 기록한다.
2. `POST /runs/{id}/uploads` → 최대 25 MiB의 PDB/mmCIF 바이트를 받아 검증된 업로드 ID를 돌려준다. 원래 파일 경로는 저장하지 않는다.
3. `POST /runs/{id}/commands` (`load_structure`, `model_index`) → `Run.call`이 인자를 정규화하고, 도구 이름·버전·유효 인자·입력 바이트 지문으로 호출 키를 만든다. 캐시에 없으면 gemmi로 파싱해 `structure` 객체를 저장한다. 객체 저장 → `object_created` 이벤트(전체 payload 포함) → SQLite 색인 순서로 기록한다.
4. `prepare_structure` → altloc·물·수소 정책을 적용하고 `prepared_structure`와 `preparation_manifest`를 만든다.
5. `compute_interactions` (정확한 리간드 인스턴스, cutoff 2.5–6.0 Å) → 중원자 사이 거리 행을 `interaction_set`에 저장한다. 접촉이 없으면 `null_result=true`인 성공이다.
6. 프런트엔드는 handle envelope(요약, 미리보기 최대 5행)을 받고, 전체 행은 `/objects?handle=…`에서 페이지 단위로 읽는다. 구조 바이트는 `/structures/bytes`에서 받아 Mol*에 올린다.
7. `POST /runs/{id}/reports` (`interaction_handle`) → 행에서 수치를 다시 계산해 필드 단위 증거로 검증한 `report_manifest@1`을 저장하고, Markdown/JSON 다운로드를 제공한다.

## 비싼 계산의 작업 경로

OpenMM 최소화, ProLIF 화학 계산, fpocket 포켓 검출, M17 RDKit 리간드 점검·생성, M18 qvina 도킹, M19 일괄 도킹은 `Run.call`로 실행하지 않는다. `/jobs`(제출, queued) → `/jobs/{id}/start`를 부르면, run의 첫 비싼 계산일 때 409로 승인 요청을 기록한다 → 사용자가 `/jobs/approve`로 승인을 명시적으로 기록한다 → 다시 `/start`를 부른다. OpenMM은 제출 전에 `/jobs/preflight`로 입력 적합성을 먼저 확인한다. 시작하면 run 실행 소유권을 얻은 뒤 비싼 계산 1단위를 예약하고, 새 프로세스 세션에서 고정된 모듈 진입점을 띄운다. 작업 프로세스는 개인 입력 파일로 제한된 JSON을 받는다. 결과는 스키마와 작업·시도 ID를 검증한 뒤에만 객체로 저장한다. 시간 초과나 취소가 나면 프로세스 그룹에 SIGTERM, 유예 후 SIGKILL을 보내고, 그룹이 비었음을 확인한 다음에 종료 상태를 기록한다.

## 분석 흐름 (M13)

`POST /analysis/plans`는 템플릿과 저장된 객체 메타데이터·capability만 읽어 불변 계획을 저장한다(과학 호출 없음). 실행을 만들고 계획을 승인하면, 사용자가 "다음 단계 실행"을 누를 때마다 driver가 짧은 워크플로 잠금 안에서 요청을 입장시키고 이전 자식 결과를 조정한 뒤, 다음 단계의 dispatch 기록을 남기고 잠금을 놓은 채 자식 하나를 실행한다. `run_call` 단계는 `Run.call`, `durable_job` 단계는 `JobQueue` 제출+시작, `report` 단계는 기존 보고서 함수다. 자식에는 내부 `ExecutionLink(execution_id, step_id, operation_id)`가 붙어, 자식 입장과 같은 전이 안에서 승인·순서·중지·인자 일치를 확인하고 물리 시도마다 시도 수를 먼저 기록한다. 링크는 이벤트의 `execution_link` 필드로 남고, 재시작 뒤에는 이 링크로 정확한 자식을 찾아 복구한다. 백그라운드 루프는 없고, 끝난 작업의 반영도 다음 요청이 한다. 흐름은 외부 요청을 하지 않는다.

## 참조 스냅샷과 번호 대응 (M15)

참조 데이터는 사용자가 실행하는 가져오기 명령 `scripts/import_reference_snapshots.py`만 쓴다. 이 명령이 `../kbase_kinase/ref`의 가공 스냅샷을 해시 대조 뒤 `.deps/reference/sets/<set_hash>/`로 복사하고 `active.json`을 rename으로 바꾼다. 서버는 이 폴더만 읽는다. `POST /commands`의 `map_residue_numbering`은 `Run.call`에서 사전 검사 훅이 세트를 고정하고 구조·스냅샷으로 입력을 검증한 뒤(세트 해시가 호출 키에 들어감), 구현이 같은 세트로 SIFTS 답·정렬 답·행 상태·KLIFS 번호를 만들어 `reference_snapshot_set@1`(처음 쓰는 세트면)과 `residue_numbering_map@1`을 저장한다. 대응 객체는 세트 해시와 계산에 쓴 참조 행을 담으므로 참조 폴더 없이 이벤트만으로 다시 열린다. 지식 탭은 읽기 API로 스냅샷·대응을 보여 주고, 보고서는 기존 `method_reports` 경로로 만든다. 네트워크는 쓰지 않는다.

## 참조 주석 (M16)

구조 분석 탭 패널에서 사용자가 현재 표시 구조와 같은 handle의 번호 대응과(선택적으로) 기하 접촉 결과를 고르면, `POST /commands`의 `annotate_reference_sites`가 `Run.call` 값싼 도구로 `reference_site_annotation@1`을 저장한다. 결과는 대응 객체의 행과 접촉 행을 그대로 옮겨 담으므로 이벤트만으로 다시 열린다. 패널은 읽기 API로 주석을 받아 MolstarViewer 브리지에 넘기고, 브리지는 검증된 원자 카탈로그로만 점선 끝 원자를 찾아 그린 뒤 native readback으로 적용을 확인한다. 주석이 켜진 보기는 `viewer_scene@2`, 그 그림은 `viewer_figure@2`(범례 합성 여부 기록)로 저장되고, 보고서는 기존 `method_reports` 경로로 만든다. 네트워크는 쓰지 않는다.

## 리간드 후보 (M17)

리간드 탭에서 사용자가 부모 SDF와 building block 파일을 `/chemical/imports`로 가져오고 반응 규칙을 쓰면, 화면이 `POST /jobs`로 `rdkit_inspect_v1`을 제출·승인·시작한다. 서버는 RDKit 없이 입장을 검사하고 가져오기 바이트를 스테이징하며, guardian이 `.deps/prolif/venv-locked`의 `ligand_worker.py`를 띄운다. 작업 모듈이 낸 점검 결과(원자 표·결합·수소, 번호 붙은 2D SVG, 속성, block·규칙 검증)를 서버가 검증해 `ligand_inspection@1`로 저장한다. 사용자가 원자 표에서 부위를 체크하면 `POST /ligand/preview`가 저장된 결합 목록으로 부위를 검사하고(이벤트 없음), 생성 요청 `rdkit_enumerate_v1`은 같은 검사를 입장에서 다시 한 뒤 점검 객체의 `valid` 규칙 텍스트와 함께 작업 모듈에 넘긴다. 결과 `ligand_candidate_set@1`은 필터와 무관하게 모든 후보를 담는다. 후보 표는 `/ligand/candidate_sets/rows`가 저장값에 필터·정렬·페이지를 적용해 돌려주고, 보고서는 기존 `method_reports` 경로로 요약 증거만 만든다. 두 객체는 이벤트만으로 다시 열린다. 네트워크는 쓰지 않는다.

## 리간드 도킹 (M18)

리간드 탭 도킹 영역에서 사용자가 수용체(+결합 사이드카)와 리간드 SDF를 `/chemical/imports`로 가져오고(M11 종류 그대로), 수용체에 비표준 잔기가 있으면 `GET /docking/receptor_instances`(gemmi, 이벤트 없음)에서 뺄 인스턴스 하나를 고른다. 리간드 출처(3D SDF 또는 M17 후보 + 부모 SDF)·방식·상자·값·확인 세 항목을 정하면 화면이 `POST /jobs`로 `qvina_dock_v1`을 제출·승인·시작한다. 서버는 RDKit·Meeko 없이 입장을 검사하고(작업 인자, 같은 run handle, 후보 집합·부모 해시, 수용체 M11 규칙·인스턴스 일치를 gemmi로), 가져오기 바이트를 스테이징하며, guardian이 `.deps/docking/venv-locked`의 `docking_worker.py`를 띄운다. 작업 모듈은 수용체를 다시 검사한 뒤 M11 화학 추론 그래프 → Meeko로 수용체 PDBQT를, Meeko로 리간드 PDBQT를 만들고, `.deps/qvina/env/bin/qvina2`를 자식으로 실행한다(자유: 검색, 코어 고정: RDKit 구속 형태마다 `--score_only`). 포즈를 입력 원자 순서로 되돌려 포즈 SDF·상자 밖 원자·최소 거리·기하 접촉을 만들고, 서버가 이를 검증해(접촉의 수용체 원자·거리를 수용체 가져오기로 재대조) `docking_result@1`로 저장한다. 읽기는 `/docking/*`가 매번 완료된 게시에 대조해 돌려주고, 보고서는 기존 `method_reports` 경로로 만든다. 결과는 이벤트만으로 다시 열린다(qvina·Meeko 없이). 작업 모듈은 화학 패키지 import 전에 Python socket을 막고, 제품 실행 중 네트워크는 쓰지 않는다.

## 리간드 일괄 도킹 (M19)

리간드 탭 일괄 영역에서 사용자가 M18 도킹 영역으로 가져온 수용체·부모 SDF와 M17 후보 집합을 고르고, M17 필터 결과(`/ligand/candidate_sets/rows`) 위에서 후보를 체크하고, 방식·부모 기준 행·상자·값·확인을 정한다. 화면은 `POST /docking/batches/preflight`(이벤트 없는 읽기)로 행별 재사용·새 계산 수 N·필요 예산·부족분을 받는다. 부족하면 사람이 `POST /docking/batches/limit_approval`을 눌러 run 한도를 부족분만큼 올린다(`budget_limit_updated`, `by: "human"`). 그다음 `POST /jobs`로 `qvina_batch_dock_v1`을 제출·승인·시작한다. 서버는 RDKit·Meeko 없이 행마다 M18 입장 검사를 하고, 시작 때 run 실행 잠금 안에서 재사용 행을 정해 N단위를 예약한 뒤 수용체·부모 SDF와 행 목록을 스테이징한다. guardian이 `docking_batch_worker.py`를 띄우면 작업 모듈이 수용체를 한 번 준비하고 행마다 M18 `dock_row`로 `qvina2`를 돌리며, 행마다 `rows/` 아래 시작·결과·상태 파일을 내구적으로 쓴다. 작업이 어떻게 끝나든(완료, 취소, 시간 소진, 크래시, 서버 재시작 복구) 서버는 그룹 정리를 확인한 뒤 검증 가능한 행 결과를 `docking_result@1`로 게시하고(`docking_batch_row_published`), 스테이징 관찰과 종료 원인으로 요약 `docking_batch_result@1`을 만들어 마지막에 게시한다(`docking_batch_published`). 화면은 작업 기록의 `batch` 진행(상태 파일 수, 요약 handle·상태)을 폴링하고, 요약 상세(`/docking/batches/detail`)로 표를 그리며, 행의 "상세 열기"는 M18 도킹 영역의 `/docking/results/*` 상세로 넘긴다. 보고서는 기존 `method_reports` 경로다. 일괄이 도는 동안 run 실행 잠금과 전역 작업 슬롯을 쥐므로 같은 run의 다른 계산과 다른 run의 비싼 작업이 기다린다. 네트워크는 쓰지 않는다.

## JEV 과학 전송 (M24)

지식·보고서 탭 JEV 영역에서 사용자가 이 run의 과학 전송 동의를 켜고(`POST /jev/consent`, 이벤트 하나, 뷰어 모드 불변), 게시된 M17 리간드 후보 집합 또는 M20 변이 후보 집합에서 후보를 최대 20개 고르면, 화면이 `POST /commands`로 값싼 도구 `build_jev_projection`을 부른다. 사전 검사 훅이 같은 run·게시·검증·선택·필터·구조를 검사하고, 구현이 저장 객체(변이는 전처리 구조 좌표에서 이웃·구간까지)로 허용 목록 와이어와 정확한 요청 본문의 바이트 수·SHA-256을 담은 `jev_projection@1`을 저장한다(외부 요청 없음). `POST /jev/preview`는 그 투영을 다시 검증해 보낼 본문 문자열·해시·예약값·차단 이유를 돌려주고(이벤트 없음), 사람이 확인을 체크하고 누르면 `POST /jev/sends`가 해시 일치·멱등·진행 중을 확인한 뒤 `SCIENCE_GATE.request_science`를 부른다. 게이트는 run 실행 잠금 안에서 승인 이벤트를 먼저 쓰고, 거절 검사 → 키 → 외부 토큰·USD 예약 → `prepared` 감사(승인한 본문 그대로) → dispatch를 기록한 뒤 OpenRouter에 한 번 보내고 기존 규칙으로 정산한다. 검증을 통과한 답은 제안 객체 `jev_choice@1`로 저장되고 모든 전송은 `jev_send_outcome`으로 끝난다. 전송 기록·늦은 응답·상한은 이벤트에서 다시 만들며, 보고서는 기존 `method_reports` 경로로 저장 객체·이벤트만 읽어 만든다. JEV의 선택은 어떤 작업·도구도 일으키지 않는다.

## JEV 설계 루프 (M25)

리간드 탭 또는 단백질 공학 탭의 JEV 루프 영역에서 사용자가 게시된 후보 집합 하나에서 풀(2–20)·목표·루프 seed·반복 상한·계산 조건을 정하면 `POST /jev_loops`가 입장 검사 뒤 `jev_loop_created` 하나를 쓴다. 루프 기록 `jev_loop@1`은 저장하지 않고 `GET /jev_loops/{loop_id}`가 이벤트 로그를 한 번 읽어 작업 기록·저장 결과·제안에서 도출한다. 바퀴마다 사람이 "보낼 내용 만들기"를 누르면 `POST /commands`의 `build_jev_loop_projection`이 루프 기록으로 전송마다 섞은 순서의 `jev_loop_projection@1`을 저장하고(외부 요청 없음), 미리보기·전송은 M24 `/jev/preview`·`/jev/sends` 그대로다(승인 콜백 안에서 루프 검사 뒤 승인 이벤트, 게이트는 스키마로 루프 검증·본문·응답 해석만 가름, 답은 `jev_loop_choice@1`). 사람이 JEV의 선택이나 직접 지정한 후보로 `POST /jev_loops/{loop_id}/compute`를 누르면 라우트가 run 실행 잠금 안에서 `jev_loop_compute_approved`를 쓰고 단독 M18(리간드)·M21(단백질 모델링) 작업과 같은 인자·호출 키의 작업을 `JobQueue`에 제출한 뒤, 잠금을 놓고 기존 시작 라우트처럼 시작한다(첫 비싼 계산 승인은 기존 `/jobs/approve`). 단백질은 모델이 게시되면 사람이 같은 라우트로 변이 구조 도킹을 시작하거나 `abandon_docking`으로 포기한다. 작업은 기존 큐·guardian·작업 모듈이 돌리고 루프는 그 기록을 읽기만 한다. `POST /jev_loops/{loop_id}/end`가 요약 `jev_loop_result@1`을 저장한 뒤 `jev_loop_ended`를 쓰고, 보고서는 기존 `method_reports` 경로(`analysis_type: "jev_loop"`)다. 백그라운드·자동 다음 바퀴·자동 계산 시작은 없고 새 한도 증액 경로도 없다.

## 효소 반응 지식 (M26)

반응 참조 데이터는 사용자가 터미널에서 실행하는 가져오기 명령 `scripts/import_reaction_references.py`만 쓴다. 이 명령이 M-CSA API(`www.ebi.ac.uk`)·UniProt REST(`rest.uniprot.org`)·Rhea(`www.rhea-db.org`)에 HTTPS GET만 보내 받은 응답에서 허용 필드만 가공하고, 모든 형식 검사를 통과했을 때만 `.deps/reaction_reference/sets/<set_hash>/`에 원자적으로 설치한 뒤 `active.json`(`reaction_active@1`)을 rename으로 바꾼다. 요청 시도는 설치된 세트의 `files/request_log.jsonl`에 남는다. 서버는 이 폴더만 읽고, M15 참조 폴더와는 따로다. 지식·보고서 탭의 "효소 반응 지식" 영역에서 사용자가 같은 run의 구조, 확인한 PDB ID, 체인과 accession, 선택적으로 같은 구조의 번호 대응을 고르면(M-CSA 제안은 `GET /reaction_reference/pdb/{pdb_id}`), `POST /commands`의 `link_reaction_knowledge`가 `Run.call` 값싼 도구로 돈다. 사전 검사 훅이 사용 중 세트를 고정하고(없거나 손상이면 412) 입장을 검사한 뒤(세트 해시가 호출 키에 들어감), 구현이 같은 세트로 체인마다 M-CSA 절(M-CSA가 적은 PDB·저자 체인·번호와 구조 잔기 이름 대조)·UniProt 절·반응 절을 만들어 `reaction_knowledge@1`을 저장한다. 결과는 쓴 세트 기록과 참조 행을 담으므로 참조 폴더 없이 이벤트만으로 다시 열린다. 읽기는 `/reaction_reference/*`·`/reaction_knowledge*`(이벤트 없음)이고, 보고서는 기존 `method_reports` 경로(`analysis_type: "reaction_knowledge"`)다. 뷰어 표시는 없고 M13 흐름은 이 도구를 부르지 않는다.

기존 흐름에서 바뀐 것: M20 `generate_mutation_candidates`는 선택 입력 `catalytic_annotation`(같은 run의 `reaction_knowledge@1`)을 받아 v2 집합(`mw.mutation_candidates/v2`)을 만든다. 도구 층이 결과를 `validated_result`로 검증해 보호에 필요한 값만 `mutation_candidates.py`의 순수 함수에 넘기고, 그중 M-CSA "대응됨" 행만 보호 근거(`catalytic_residue`)가 되며 검사 칸 `protection_checks.catalytic_residue_database`가 함께 저장된다. 이 단계 뒤 새 집합은 모두 v2이고 저장된 v1 집합은 바이트 그대로 유효하다. M21·M23·M24·M25는 두 세대를 모두 받고, 후보 집합을 고르는 곳은 `catalytic_residue_database.status`로 "촉매 잔기 검사 안 함"을 표시한다. M24 변이 투영·제안(`jev_choice@1`)·보고서의 다섯째 한계 문장은 와이어의 이 상태에 따라 J6(`not_available`, 바이트 그대로)·J6n·J6c(`J6_BY_CATALYTIC_STATUS`)이고, M26 반응 자료는 JEV 와이어에 들어가지 않는다. `mutation_candidates.py`가 바뀌어 M21·M23 호출 키가 달라졌다(영향은 `docs/engineering-notes.md`의 M26 함정).

## 외부 경계

- 넘어가는 것: 해당 run에서 온라인 모드와 뷰어 전용 동의를 켠 뒤, 사용자가 입력한 뷰어 요청 문장(최대 512자)과 생성된 별칭 대상 카탈로그(최대 256개)만 OpenRouter로 간다. M3 경로에서는 접촉 집계 숫자 몇 개만 간다. M24 과학 전송은 과학 전송 동의가 켜진 run에서 사람이 승인한 투영 본문 하나씩만 간다: 리간드 후보(정규 SMILES, RDKit 추정 속성, PAINS 일치, 생성 방식 종류) 또는 변이 후보(잔기 7필드, 서열 구간 앞뒤 5개, 5.0 Å 이웃 잔기 이름, 리간드까지 거리, 보호 검사 상태, 포켓 요약), 고정 질문. M25 루프 전송은 같은 경로로 같은 종류의 후보 필드에 목표(`goal`)·계산된 후보 표시(`computed`, 활용형만 저장된 qvina 점수)·목표별 지시문을 더하고 후보 순서·별칭을 전송마다 섞는다. 서열 구간·이웃 잔기 이름으로 단백질이 알려질 수 있다.
- 넘어가지 않는 것(현재 코드 기준): 좌표, 구조 파일, 전체 서열, 원자 이름, 리간드 인스턴스 이름, 번호 대응·KLIFS 값, M26 반응 자료(M-CSA·UniProt·Rhea 값), 로컬 경로, handle, run ID, 후보 id, 루프 ID·루프 seed·바퀴 번호, 자격 증명, 이전 대화.
- 정책(결정 0015, 2026-09-29): 구조·좌표·서열·리간드·분석 결과는 외부 모델로 보내도 된다. 실제로 보내는 과학 데이터는 M24의 두 투영과 M25의 두 루프 투영뿐이며, 새 종류는 게이트 투영·미리보기·예산·감사를 함께 만들어야 보낸다. 자격 증명은 계속 전송 금지다.
- 게이트 밖 예외(결정 0034): 사용자가 터미널에서 실행하는 M26 반응 참조 가져오기 명령 `scripts/import_reaction_references.py` 하나가 허용 호스트 셋(`www.ebi.ac.uk`·`rest.uniprot.org`·`www.rhea-db.org`)에 HTTPS GET만 보낸다. 보내는 것은 URL 질의(쪽 번호·accession 목록·열 이름)뿐이고 키·쿠키·사용자 데이터는 없으며, 리다이렉트·환경 프록시를 따르지 않고 호스트·스킴을 바꾸는 옵션도 없다. 서버·도구·작업·보고서·화면은 이 명령을 부르지 않는다. 고정 규칙과 요청 기록은 `docs/security.md`.
- 브라우저의 글꼴·스크립트·Mol* 자산·예시 구조는 모두 로컬 번들이다. 오프스크린 QA는 loopback이 아닌 요청을 전부 차단하고 기록한다.
- 초기 설치(`pip`, `npm ci`, ProLIF·도킹 wheelhouse, fpocket·qvina conda archive 준비)와 위 M26 가져오기 명령에만 네트워크가 필요하다. 서버와 작업 프로세스는 실행 중에 다운로드하지 않는다. M15 참조 스냅샷 가져오기 명령(`scripts/import_reference_snapshots.py`)은 로컬 kbase 체크아웃에서 복사할 뿐 네트워크를 쓰지 않는다.

## 저장소 배치

`runs/<run_id>/`에는 `events.jsonl`(원본 데이터), 불변 객체 파일, 없애도 되는 SQLite 색인, 작업 시도 디렉터리가 있다. 위치는 `MW_RUNS_DIR`로 바꿀 수 있다. 참조 스냅샷은 run 밖의 `.deps/reference/`(M15, `MW_REFERENCE_DIR`)와 `.deps/reaction_reference/`(M26, `MW_REACTION_REFERENCE_DIR`, 세트마다 요청 기록 `files/request_log.jsonl`)에 따로 있고, 두 가져오기 명령 모두 이전 세트 폴더를 지우지 않는다. 객체와 색인을 지워도 이벤트만으로 전부 다시 만들 수 있다. 이 복구 방식은 작은 구조 작업을 전제로 하며, 큰 궤적 데이터는 다루지 않는다.
