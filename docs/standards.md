# 필수 규칙

## 작업 역할과 진행 방식

- 메인 세션이 사용자와 대화하고, 설계를 결정하고, Git 전이(브랜치·커밋)와 단계 기록을 맡는다. 구현은 Opus 5.5 구현 서브에이전트가, 검토는 그 코드를 쓰지 않은 새 Opus 5.5 검토 서브에이전트가 맡는다. 구현한 에이전트가 자기 작업을 승인하면 안 된다.
- 검토자는 과학 계약(단위, 식별자, 결과가 뜻하는 범위)과 구현·테스트를 함께 본다. 검토에서 나온 지적은 해결하거나, 선택한 범위 밖이라고 명시적으로 기록한 뒤에만 작업을 완료로 표시한다.
- M11 이후 새 작업 순서: 메인 세션이 사용자와 작업 명세(범위, 수락 기준, 검증 명령)를 확정한다(`ready`) → 구현 서브에이전트가 구현하고 게이트 명령을 실행한다 → 새 검토 서브에이전트가 명세와 실제 코드·테스트·증거를 검토한다 → 지적 사항을 해결한 뒤 메인 세션이 결과를 보고한다(`go`). `scripts/execute.py`는 끝난 단계(M0–M10)를 `--verify`로 다시 확인할 때만 쓴다. 이 실행기는 `codex exec`와 `gpt-6-sol`/`gpt-6-astra`를 호출하고 검토자 모델이 `gpt-6-astra`가 아니면 기록을 거부하므로, 새 단계를 이 실행기로 기록하면 안 된다.
- 과거 검토 기록에 적힌 GPT-6 Astra/Sol 이름은 그대로 둔다. 당시 실제로 실행한 모델 기록이다. 새 기록은 실제 실행한 모델(Opus 5.5)로 적고, 다른 모델 이름으로 바꿔 적지 않는다.

## 과학 결과

- 실험값이나 계산 결과를 만들어 내거나, 조정하거나, 바꿔 넣거나, 코드에 박아 넣어 원하는 결과를 만들면 안 된다. 테스트 fixture는 파일 이름이나 메타데이터에 fixture라고 표시한다. 런타임 UI와 보고서는 계산한 handle만 쓰고, 디자인용 가짜 데이터(`/gallery`)를 쓰지 않는다.
- 새 과학 값은 실제 엔진을 실행해서 얻고, 고유 단위와 가정을 그대로 기록한다. 이름을 Rosetta, ΔΔG, 친화도, 안정성으로 바꿔 부르지 않는다.
- 구현하지 않은 기능을 지원한다고 표시하면 안 된다. 사용할 수 없는 기능은 `/capabilities`, UI, 보고서에서 같은 이유로 일관되게 사용할 수 없다고 보여 준다. 숫자 자리표시자는 없다.
- dry-run 출력과 lifecycle fixture 작업 출력은 계획이거나 시뮬레이션이다. 측정한 과학 증거로 쓰면 안 된다.

## 불변성과 과거 기록

- 불변 객체, 완료된 호출 기록, 저장된 보고서 바이트, 이벤트 로그는 바꾸지 않는다. 재시도와 재시작도 이것들을 조용히 바꾸면 안 된다. 용량을 확보하려고 이벤트 로그를 자르거나 객체를 그 자리에서 지우면 안 된다(run 디렉터리를 통째로 보관 위치로 옮기는 것만 허용).
- 새 객체 종류를 추가할 때는 이벤트만으로 다시 만들 수 있어야 한다. 원본 입력 경로, 네트워크, 과학 재계산 없이 events-only 복구 테스트를 통과해야 한다.
- 다음 파일은 완료된 단계 검토 기록에 SHA-256으로 묶여 있으므로 내용을 바꾸거나 옮기지 않는다: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/*_CONTRACT.md`, `docs/JOBS_POSIX_ADDENDUM.md`, `docs/reviews/`, `docs/qa/`, `phases/*/reviews/`, `phases/*/step*.md`, 완료된 `phases/*/index.json`. 제공된 원본 자료 `agent_protein_viewer_plan_v05.md`, `molecular-workspace.zip`, `references/molecular-workspace/`도 바꾸지 않는다.
- 이 디스크는 대소문자를 구분하지 않는다. 기존 대문자 문서와 소문자만 다른 이름(예: `docs/architecture.md` ↔ `docs/ARCHITECTURE.md`, `docs/decisions.md` ↔ `docs/DECISIONS.md`)의 새 파일을 만들면 기존 파일을 덮어쓰게 되므로 금지한다.
- `scripts/execute.py --verify`는 실행할 때마다 `phases/index.json`과 해당 `phases/<group>/index.json`을 고쳐 쓴다(실패하면 `error`, 통과하면 새 `completed_at`). 확인용으로만 돌리고, 끝나면 이 파일들을 실행 전 상태로 되돌린 뒤 결과만 보고한다. 되돌리지 않은 `--verify` 결과를 커밋하면 안 된다.
- 공유 소스를 바꾸면 그 소스를 다뤘던 과거 검토 해시가 오래된 상태가 된다. 새 작업의 검토에서 바뀐 공유 소스와 기존 기능 회귀를 다시 검증하고, 그 사실을 명시한다. 과거 결과를 고쳐서 "새로 검증된 것처럼" 만들지 않는다.

## Git

- 커밋, 브랜치 생성, push는 사용자가 명시적으로 요청했을 때만 한다. force push, `git reset --hard`, 재귀 강제 삭제는 하지 않는다. 훅은 `rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE` 문자열만 막는다. `git push -f`나 `rm -fr`는 통과하므로, 훅이 막지 않았다고 허용된 것이 아니다.
- 저장소 전체를 스테이징하지 않는다(`git add -A`/`git add .` 금지). 파일 경로를 지정해서 스테이징한다. 커밋하지 않은 다른 작업이 섞여 있는 경우가 흔하다.
- 단계별 브랜치 이름은 `phase/m<N>-<slug>` 형식이고, 이전 단계에서 실제로 승인된 커밋에서 만든다. 과거 단계의 브랜치나 커밋을 소급해서 만들지 않는다. M0–M5는 브랜치 없이 진행했고, `d22fe15`가 실제 기준선이다.
- 단계 기록(`phases/*/index.json`)의 상태는 처음에 pending이다. 테스트·검토 결과를 미리 채워 넣지 않는다. 기록은 실제 실행이 끝난 뒤에만 한다.

## 검증 게이트

작업을 완료로 표시하기 전에 다음을 모두 통과해야 한다. 프로젝트 루트에서 실행한다.

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py scripts/test_m14_offscreen_acceptance.py scripts/test_import_reference_snapshots.py scripts/test_m15_offscreen_acceptance.py scripts/test_measure_klifs_numbering.py scripts/test_m16_offscreen_acceptance.py scripts/test_m17_offscreen_acceptance.py scripts/test_m18_offscreen_acceptance.py scripts/test_m19_offscreen_acceptance.py scripts/test_setup_qvina.py scripts/test_setup_docking_worker.py scripts/test_m20_offscreen_acceptance.py scripts/test_m21_offscreen_acceptance.py scripts/test_m22_offscreen_acceptance.py scripts/test_m23_offscreen_acceptance.py scripts/test_m24_offscreen_acceptance.py -q
node --check frontend/tests/offscreen/pocket-flow.cjs
node --check frontend/tests/offscreen/workflows-flow.cjs
node --check frontend/tests/offscreen/tabs-flow.cjs
node --check frontend/tests/offscreen/numbering-flow.cjs
node --check frontend/tests/offscreen/annotation-flow.cjs
node --check frontend/tests/offscreen/ligand-flow.cjs
node --check frontend/tests/offscreen/docking-flow.cjs
node --check frontend/tests/offscreen/docking-batch-flow.cjs
node --check frontend/tests/offscreen/mutation-flow.cjs
node --check frontend/tests/offscreen/mutation-model-flow.cjs
node --check frontend/tests/offscreen/ligand-ga-flow.cjs
node --check frontend/tests/offscreen/sequence-ga-flow.cjs
node --check frontend/tests/offscreen/jev-flow.cjs
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

- typecheck와 build는 동시에 돌리지 않고 순서대로 실행한다. 둘 다 같은 프런트엔드 빌드 산출물(`tsconfig.tsbuildinfo`, `.next/`)을 쓴다.
- 사용 가능해야 하는 과학 엔진(FreeSASA, OpenMM, M11의 ProLIF 작업 프로세스, M12의 fpocket, M17의 RDKit 리간드 작업 프로세스, M18의 qvina 도킹 작업 프로세스, M19의 일괄 도킹 작업 프로세스, M22의 GA 작업 프로세스, M23의 서열 GA 작업 프로세스와 모델링 프로그램)의 네이티브 테스트는 엔진이 없을 때 조용히 skip하면 안 된다. 단계 수락 시점에는 실제 엔진으로 실행해야 한다.
- UI를 바꾸면 실제 Electron 오프스크린 렌더러(`webContents.isOffscreen()===true`, GPU·WebGL 켜짐, paint 프레임 확인)에서 바뀐 컨트롤을 하나씩 실제 입력으로 눌러 보고 결과를 관찰해야 한다. 일반 headless 브라우저나 숨긴 탭은 이 증거로 인정하지 않는다. 계획만 세운 클릭을 테스트 완료로 부르지 않는다.
- API와 프런트엔드 연동은 실제 입력 바이트로 확인한다. 공개 구조 fixture(`backend/tests/fixtures/public_1hsg.cif`, `public_1ubq.cif`, M15 번호 대응·M16 참조 주석용 `public_1mq4.cif`)나 표시된 합성 fixture를 쓴다.
- 오프라인 흐름을 검증할 때는 loopback이 아닌 요청이 0건임을 기록한다.
- 제품이 OpenRouter를 실제로 호출하는 검증은 사용자가 그때마다 정해 준 횟수 안에서만 한다. M8의 4회 할당은 모두 썼다. fixture transport 테스트에는 이 제한이 없다.

## 모듈 경계

- 외부 HTTP는 `backend/mw/egress/gate.py`의 `EgressGate`만 보낸다. 다른 백엔드 모듈이 직접 httpx 클라이언트를 만들어 외부로 요청하면 안 된다.
- 과학 계산은 `Run.call`(동기, 저렴·보통 비용)과 `JobQueue`(비싼 비용) 두 경로로만 실행한다. API 라우트나 UI 전용 코드에서 과학 함수를 직접 부르면 안 된다. 읽기 API는 도구를 다시 실행하지 않는다.
- M13 분석 흐름(`backend/mw/analysis_executions.py`)도 과학은 내부 `ExecutionLink`를 단 `Run.call`·`JobQueue`와 기존 보고서 함수로만 실행한다. `tools/` 계산 함수를 직접 부르거나, 자체 재시도 루프·백그라운드 루프를 두거나, 흐름 중지에 `Run.cancel()`을 쓰지 않는다. 계획 생성(`analysis_plans.py`)은 과학 호출을 하지 않는다. 연결 필드가 없는 기존 호출·작업·보고서의 이벤트와 바이트는 바꾸지 않는다.
- 도구 레지스트리는 닫혀 있다. 새 도구는 `config/tools.yaml` 명세, `backend/mw/tools/` 구현, 새 모듈이면 `backend/mw/workspace.py`의 `build_registry()` 등록 호출, `app.py`의 `SUPPORTED_TOOLS` 허용 목록에 모두 추가해야 노출된다. `Run.call`로 실행하는 구현된 도구(`SUPPORTED_TOOLS`)는 `load_structure`, `prepare_structure`, `compute_interactions`, `compute_interface_sasa`, `measure_distance`, `align_structures`, `compile_state`, `map_residue_numbering`(M15), `annotate_reference_sites`(M16), `generate_mutation_candidates`(M20, 값싼 도구)다. yaml에만 있는 `measure`, `align`, `snapshot`, `define_mutations`, `rank_candidates`, Rosetta 도구는 구현이 없으므로 지원한다고 표시하지 않는다. 비싼 작업 전용 도구(`openmm_protein_minimize`, `prepare_chemical_structure`, `compute_chemical_interactions`, `detect_pockets`, `rdkit_inspect_ligand`, `rdkit_enumerate_ligands`, `qvina_dock_ligand`, `qvina_dock_batch`, `qvina_ga_design`)는 `SUPPORTED_TOOLS`가 아니라 `JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`와 작업 승인 허용 목록에 넣는다.
- ProLIF/RDKit/MDAnalysis는 `.deps/prolif/venv-locked` 작업 프로세스 환경에만 설치한다. 서버 프로세스에서 import하면 안 된다. 이 환경에서 도는 작업 모듈은 M11 `mw/jobs/chemical_worker.py`와 M17 `mw/jobs/ligand_worker.py`(RDKit 2026.03.6)뿐이다. 서버와 작업 프로세스는 제한된 버전 JSON과 입력 바이트로만 주고받는다.
- M18 도킹의 Meeko·RDKit·MDAnalysis는 `.deps/docking/venv-locked` 작업 프로세스 환경에만 있고, 이 환경에서 도는 작업 모듈은 M18 `mw/jobs/docking_worker.py`, M19 `mw/jobs/docking_batch_worker.py`, M22 `mw/jobs/ligand_ga_worker.py`뿐이다. 일괄·GA 작업 모듈은 `docking_worker.py`를 파일 경로로 불러 그 함수로 행·개체를 계산한다(계산을 복제하지 않음). 일괄 작업 모듈은 화학 패키지를 직접 import하지 않는다. GA 작업 모듈은 예외로 RDKit을 Morgan 지문 계산에만 직접 import한다(결정 0030). qvina(`.deps/qvina/env/bin/qvina2`)는 이 세 작업 모듈 프로세스 안의 `docking_worker.py` 함수만 실행한다. 서버 프로세스는 이 패키지들을 import하지 않고 qvina를 실행하지 않는다(capability는 실행 파일 해시와 작업 모듈 handshake로만 확인).
- M23 서열 GA는 두 인터프리터를 한 프로세스 그룹에서 쓴다: GA 작업 모듈 `mw/jobs/sequence_ga_worker.py`는 `.deps/docking/venv-locked`에서 돌며 `docking_worker.py`를 파일 경로로 불러 개체 도킹만 하고(OpenMM·PDBFixer를 import하지 않음), 개체 모델링은 프로젝트 `.venv`의 `mw/jobs/sequence_model_worker.py`를 `[<repo>/.venv/bin/python, "-I", 프로그램]` 자식 프로세스로 실행한다(RDKit·Meeko·MDAnalysis를 import하지 않고, 경로는 `resolve()`하지 않는다). 모델링 프로그램은 M21 `openmm_mutation_worker.py`를 바꾸지 않고 불러 쓴다. 서버 프로세스는 PDBFixer를 import하지 않고(OpenMM은 M7 `dependencies()`·`preflight()`로만) 두 프로그램을 실행하지 않는다. 해시되는 M18·M21 파일(`docking_worker.py`·`docking_constants.py`·`openmm_mutation_worker.py`·`mutation_model_constants.py`·`mutation_model_math.py`·`mutation_candidates.py`)과 `ligand_ga_*`는 M23이 바꾸지 않았다(바꾸면 기존 M18·M19·M21·M22 결과의 자동 재사용이 끝난다). M18 수용체 출처 `mutation_model`은 서버 쪽에서만 `mutation_set_model@1`까지 받는다(결정 0031).
- run 한도 증액(`Run.raise_limits`)을 부르는 코드는 `docking_batch_jobs.limit_approval`(M19)·`ligand_ga_jobs.limit_approval`(M22)·`sequence_ga_jobs.limit_approval`(M23) 셋이고 서로를 부르지 않는다. 각각을 부르는 코드는 자기 HTTP 라우트 하나다: `POST /runs/{id}/docking/batches/limit_approval`, `POST /runs/{id}/ligand/ga/limit_approval`, `POST /runs/{id}/sequence_ga/limit_approval`(`backend/tests/test_docking_batch_budget.py`·`test_ligand_ga_budget.py`·`test_sequence_ga_budget.py`가 AST로 확인). 도구 구현, M13 분석 흐름, 뷰어 의도·모델 응답 처리, 작업 큐에서 한도를 바꾸는 호출을 더하면 안 된다. `Run.update_limits`는 테스트 전용이다.
- 프런트엔드는 `/api/*` 프록시(백엔드 `127.0.0.1:8000`)로만 통신한다. 과학 수치를 브라우저에서 계산하거나, 브라우저가 보낸 좌표를 측정에 쓰면 안 된다.

## 의존성

- 과학 결과에 영향을 주는 의존성은 정확한 버전으로 고정한다: gemmi 0.7.5, numpy 2.4.6, freesasa 2.2.1, openmm 8.6.0, psutil 7.2.2 (`backend/pyproject.toml`), molstar 5.11.0, electron 44.4.5 (`frontend/package.json`). 버전을 바꾸면 해당 엔진의 수치 검증을 다시 해야 한다.
- 프런트엔드 설치는 `npm ci`(lockfile 기준)만 쓴다.
- fpocket은 `config/pockets/`의 35개 conda 패키지 해시 잠금으로만 설치한다(`scripts/setup_fpocket.py`, conda 필수, macOS ≥ 14.5 arm64, 오프라인). 실행 파일 SHA-256이 고정값과 다르면 사용할 수 없음으로 표시한다(결정 0017).
- ProLIF 작업 프로세스 환경은 `config/chemical/`의 33개 wheel 해시 잠금 파일로만 설치한다(`scripts/setup_prolif_worker.py`, CPython 3.11 macOS arm64 전용). M17 리간드 작업도 같은 환경을 쓰며, RDKit 버전·PAINS 카탈로그 항목 수가 고정값과 다르면 `ligand_candidates`를 사용할 수 없음으로 표시한다. 런타임에 설치하거나 다운로드하지 않는다. `/tmp`의 조사용 경로를 운영 설정에 쓰지 않는다.
- M18 도킹 환경 둘은 `config/docking/`의 잠금으로만 설치한다: qvina는 conda 패키지 8개 해시 잠금(`scripts/setup_qvina.py`, conda 필수, macOS ≥ 11.0 arm64, 오프라인), 작업 환경은 wheel 26개 해시 잠금(`scripts/setup_docking_worker.py`, CPython 3.11 macOS arm64 전용, Meeko 0.8.0·RDKit 2026.3.6·MDAnalysis 2.10.0·gemmi 0.7.5). `qvina2` SHA-256이 고정값·설치 기록과 다르거나 작업 환경 버전이 고정값과 다르면 `ligand_docking`을 사용할 수 없음으로 표시한다. 기존 `.deps/prolif`·`.deps/fpocket`과 섞지 않는다.
- `../kbase_kinase`에서 가져올 수 있는 것은 범용 실행기·훅 인프라와, `ref/`의 가공 스냅샷(UniProt·SIFTS·KLIFS)뿐이다(결정 0022). 스냅샷은 가져오기 명령 `scripts/import_reference_snapshots.py`로만 로컬 참조 폴더(`.deps/reference/`, `MW_REFERENCE_DIR`)에 복사하고, 서버는 그 폴더만 읽는다. 화면·보고서에는 "kbase_kinase 가공본"으로 표시한다. 그쪽의 과학 코드(import·복사), `dist/`의 데이터·결론은 가져오지 않는다. 형식을 이해하려고 kbase 소스를 읽는 것은 된다.

## 입력 검증과 오류

- 도구 입력은 실행 전에 검증한다: 알 수 없는 도구, 구현 없는 도구, 스칼라/리스트 handle 형태 오류, NaN·Infinity, 잘못된 enum, 잘못된 handle 종류. 실패하면 도구 구현을 호출하지 않고 typed failure를 돌려준다.
- `ToolFailure`가 아닌 예외는 로컬 진단과 함께 fatal로 분류한다. 분류되지 않은 API 오류로 새어 나가거나 재시도를 일으키면 안 된다.
- UI 상태는 loading, ready, 빈 과학 결과(scientific_null), 실패, 사용할 수 없음 다섯 가지를 구분해 보여 준다. 실패를 빈 결과로 보여 주거나 빈 결과를 실패로 보여 주면 안 된다.
- 한국어 설명을 쓰더라도 도구 식별자(`compute_interactions` 등)는 번역하지 않는다.
