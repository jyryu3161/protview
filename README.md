# ProtView

로컬 PDB/mmCIF 구조를 불러와 전처리하고, 실제 분자 구조와 원자 사이의 기하 접촉을 살펴보는 단일 사용자 작업 공간입니다. 계산 결과는 변경 불가능한 객체 handle과 이벤트 기록에 연결됩니다. 기본 작업에는 외부 서비스나 API 키가 필요하지 않습니다.

M0–M5의 선택된 구현 범위는 실제 테스트·브라우저 검증과 GPT-6 Astra 검토를 통과했습니다. 단계 완료는 현재 파일 해시에 연결된 검토 기록과 최종 `--verify` 결과로 확정하며, 최종 상태와 증거는 [단계 기록](phases/protview-mvp/index.json)을 따릅니다. 사용할 수 없는 선택적 에너지 엔진의 과학적 검증을 뜻하지 않습니다.

## 설치와 실행

Python 3.11 이상, Node.js 22 이상과 npm이 필요합니다. 구현 검증 환경은 Python 3.11.11, Node.js 24.3.0, npm 11.4.2입니다. 초기 의존성 설치에는 네트워크가 필요하며, 설치 후 일반 구조 검사 및 보고서 생성은 로컬에서 동작합니다.

프로젝트 루트에서 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
```

터미널 두 개에서 각각 백엔드와 프런트엔드를 실행합니다.

```bash
.venv/bin/python -m uvicorn mw.api.app:app --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend run start -- -p 3000
```

브라우저에서 <http://127.0.0.1:3000>을 엽니다. 개발 중에는 프런트엔드의 `start` 대신 `dev`를 사용할 수 있습니다. 프런트엔드는 로컬 백엔드의 8000번 포트로 API 요청을 전달합니다.

run 데이터는 기본적으로 루트의 `runs/`에 저장됩니다. 별도 위치를 사용할 때는 백엔드를 실행하기 전에 `MW_RUNS_DIR`을 지정합니다. run 디렉터리에는 업로드와 구조 데이터가 포함됩니다. 기본 `runs/`와 `.env` 파일은 Git에서 제외됩니다. `MW_RUNS_DIR`을 저장소 안의 다른 경로로 지정하면 그 경로도 직접 `.gitignore`에 추가해야 합니다. API 키는 소스 파일에 넣지 않습니다.

## 현재 사용 흐름

1. 새 run을 만들고 로컬 `.pdb`, `.cif` 또는 `.mmcif` 파일을 업로드합니다. 파일 한도는 25 MiB입니다.
2. 모델을 선택해 구조를 불러오고, altloc·물·수소 처리 정책을 지정해 전처리합니다.
3. 정확한 리간드 인스턴스와 거리 cutoff를 선택해 기하 접촉을 계산합니다.
4. 접촉 행을 선택해 해당 잔기에 초점을 맞추고, cartoon·ball-and-stick·surface 표시를 전환합니다.
5. 선택한 측정의 Inspector에서 보고서를 만들고 저장된 Markdown 미리보기와 Markdown/JSON 다운로드를 엽니다. 과거 측정을 선택하면 그 측정의 구조와 보고서가 표시됩니다. 저장된 run을 다시 열어 보고서를 읽을 때 도구를 재실행하지 않습니다. 새 계산은 “최신 구조로 돌아가기”에서 이어갑니다.

접촉이 없는 정상 결과는 `scientific_null`로 표시됩니다. 읽기나 계산 실패와 리간드 부재/다중 선택 요구는 별도 상태입니다. 거리는 Å 단위이며, 기하학적 polar/hydrophobic contact는 검증된 수소결합·친화도·안정성·에너지를 뜻하지 않습니다. 지원하지 않는 전처리와 과학 계산은 거부하거나 사용 불가로 표시합니다. PyRosetta relax, Cartesian ddG, interface analysis, residue energies는 실제 구현·검증된 엔진이 없어 사용할 수 없으며 보고서에 점수나 순위가 없습니다. `/gallery`는 디자인 예시입니다.

고정된 API 워크플로 `POST /runs/{id}/inspect_complex`는 동일한 검증 업로드 ID 또는 같은 run의 구조 handle을 받아 명시한 모델/전처리와 정확한 리간드 선택으로 `Run.call`을 순서대로 실행합니다. 리간드가 하나일 때만 자동 선택합니다. 보고서 API는 `POST /runs/{id}/reports`에 선택한 `interaction_handle`을 전달합니다. `GET /runs/{id}/reports`, `/reports/selected?handle=...`, `/reports/download?handle=...&format=markdown|json`으로 저장된 결과를 읽고 내려받습니다. 외부 요청이나 키가 필요하지 않습니다. [M5 구현 문서](docs/M5_REPORTS.md)에 요청·증거 형식과 한계가 있습니다.

선택적인 내부 Jev 연동은 명시적으로 설정한 온라인 run에서만 접촉표의 보기를 추천합니다. API 키가 있어도 일반 UI의 새 run은 `local_only`로 생성됩니다. 합성 집계값을 사용한 OpenRouter 실호출 1회를 검증했으며, 이는 연결 검증입니다. 과학적 판단의 품질 검증이나 벤치마크를 뜻하지 않습니다. 설정·전송 범위·사용량 기록은 [M3 구현 문서](docs/M3_EGRESS.md)를 따릅니다.

## 설계와 단계별 검증

- [아키텍처](docs/ARCHITECTURE.md), [채택·보류 결정](docs/DECISIONS.md), [M0–M5 구현 계획](docs/IMPLEMENTATION_PLAN.md)
- [구조 API](docs/M1_API.md), [뷰어 동작과 검증](docs/M1_VIEWER.md), [M1 승인 검토](phases/protview-mvp/reviews/step1.md)
- [실행·복구 계약](docs/RUNTIME_CONTRACT.md), [외부 요청 계약](docs/EGRESS_CONTRACT.md), [작업 계약](docs/JOBS_CONTRACT.md), [보고서 계약](docs/REPORT_CONTRACT.md)
- [단계 실행기 사용법](docs/HARNESS.md)

GPT-6 Astra가 설계와 검토를 맡고 GPT-6 Sol이 구현합니다. `../kbase_kinase`에서는 범용 단계 실행기·훅·관련 검사만 가져와 이 프로젝트에 맞게 수정했습니다. 실행기는 단계 검사와 파일 해시가 연결된 검토 기록을 요구하며, Git 커밋이나 push를 자동으로 수행하지 않습니다.

전체 백엔드·하네스 및 프런트엔드 검사는 다음과 같습니다. 프런트엔드 typecheck와 build는 순서대로 실행합니다.

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
.venv/bin/python scripts/execute.py protview-mvp --dry-run
```

각 단계의 추가 검사 명령은 `phases/protview-mvp/stepN.md`와 `index.json`에 있습니다. 전체 `--verify`는 모든 단계가 구현·검토된 뒤의 최종 게이트입니다. 단계 검사만으로 미검토 단계를 완료로 표시하지 않습니다.

제공된 `agent_protein_viewer_plan_v05.md`, `molecular-workspace.zip` 및 `references/molecular-workspace/`는 원본 참고 자료로 보존합니다. 제품에 채택한 범위와 현재 동작은 위의 설계 문서 및 실제 검증 기록을 따릅니다.
