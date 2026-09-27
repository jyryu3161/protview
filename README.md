# ProtView

로컬 PDB/mmCIF 구조를 불러와 전처리하고, 실제 분자 구조와 원자 사이의 기하 접촉을 살펴보는 단일 사용자 작업 공간입니다. 계산 결과는 변경 불가능한 객체 handle과 이벤트 기록에 연결됩니다. 기본 작업에는 외부 서비스나 API 키가 필요하지 않습니다.

M0–M5는 기준 커밋 `d22fe15`에서 실제 테스트·브라우저 검증·GPT-6 Astra 검토와 최종 `--verify`를 통과했습니다. [기존 단계 기록](phases/protview-mvp/index.json)은 그 기준의 이력입니다. 이후 확장으로 바뀐 공유 파일의 현재 검토를 대신하지 않으며, 사용할 수 없는 에너지 엔진의 과학적 검증을 뜻하지 않습니다.

M6 단백질–리간드 SASA는 실제 수치·호스트 테스트·브라우저 검증과 [GPT-6 Astra 검토](docs/M6_SASA_REVIEW.md)를 통과했습니다. 이 확장 검토가 변경된 공유 파일과 기존 기능의 회귀 검증을 담당합니다. 실제 단계 기록 여부와 현재 해시의 게이트 상태는 [확장 단계 기록](phases/protview-methods/index.json)을 따릅니다. M7 OpenMM 단백질 전용 최소화도 실제 계산·독립 전위 재계산·호스트 288개 검사(건너뜀 0개)·브라우저 검증과 [Astra 검토](docs/M7_OPENMM_REVIEW.md)를 통과했습니다. 최종 단계 기록과 현재 해시의 `--verify` 결과는 확장 단계 기록을 따릅니다. 기존 M0–M5에는 단계별 Git 브랜치가 없었으며, 실제 확장 작업은 `phase/m6-interface-sasa`의 승인 커밋 `50569ee` 이후 그 커밋에서 만든 `phase/m7-openmm-minimization`에서 이어졌습니다.

M8은 실제 `phase/m8-agent-viewer` 브랜치에서 이어집니다. 프롬프트→실제 모델→typed viewer 명령→Mol* 적용 확인과 Electron의 실제 offscreen 렌더러를 사용한 86항목 클릭 검증을 완료했습니다. [M8 검증 결과](docs/M8_QA_RESULTS.md), [항목별 증거](docs/qa/m8/COVERAGE.md), [M8 단계·리뷰·현재 해시 기록](phases/protview-agent-ui/index.json)을 확인하세요. 앞선 M0–M7 기록은 당시 승인 기준이며, M8에서 바뀐 공유 파일의 현재 검증은 새 M8 리뷰에 연결됩니다.

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
4. 접촉 행이나 캔버스의 잔기를 클릭해 선택·초점을 맞추고, cartoon·ball-and-stick·surface 표시를 전환합니다. 다른 잔기를 클릭하면 선택이 바뀌고 빈 공간을 클릭하면 해제됩니다.
5. 선택한 측정의 Inspector에서 보고서를 만들고 저장된 Markdown 미리보기와 Markdown/JSON 다운로드를 엽니다. 과거 측정을 선택하면 그 측정의 구조와 보고서가 표시됩니다. 저장된 run을 다시 열어 보고서를 읽을 때 도구를 재실행하지 않습니다. 새 계산은 “최신 구조로 돌아가기”에서 이어갑니다.

뷰어 요청 패널의 로컬 명령(`/representation surface`, `/zoom in`, `/clear`, `/reset`)은 offline에서도 작동합니다. 자연어 요청은 해당 run에서 **온라인 해석 허용**을 명시적으로 켠 뒤 보냅니다. 예: “표현 방식을 cartoon으로 바꾸고 현재 선택을 해제한 뒤 카메라 시점을 초기화해줘.” 입력 문장과 제한된 대상 식별자가 전송되며 좌표·구조 파일·서열·경로는 전송하지 않습니다. run별 실제 요청 한도는 4회이고, 이 동의는 과학 계산 승인을 부여하지 않습니다. 설정과 전송·취소·적용 확인 계약은 [M8 구현 안내](docs/M8_AGENT_VIEWER.md)를 따릅니다.

M9의 저장된 보기는 현재 표시된 원본·과거 전처리·OpenMM 최소화 구조의 정확한 source/model, 선택 잔기, 표현, 카메라, 테마를 이름과 함께 보관합니다. 복원은 새 로컬 뷰어 세션에서만 이루어지며, 선택한 보기의 실제 Mol* 뷰포트를 PNG와 출처 JSON 한 쌍으로 내보낼 수 있습니다. 이 그림은 새로운 과학 측정이 아닙니다. 사용 순서, 재시도, 저장 한도와 한계는 [M9 저장 보기·그림 안내](docs/M9_SCENES_EXPORT.md)를 따릅니다. 최종 완료 여부는 [M9 단계 기록](phases/protview-scenes/index.json)에 따릅니다.

M10의 원자 거리 측정과 두 구조 정렬은 명시적으로 선택한 원자 site와 단백질 CA 대응을 사용합니다. 원본 구조 좌표는 바뀌지 않으며, 두 구조 비교와 원자 측정 표시는 M9 단일 구조 보기로 저장하거나 PNG로 내보낼 수 없습니다. 사용법과 결과 한계는 [M10 원자 거리·정렬 안내](docs/M10_MEASUREMENT_ALIGNMENT.md)를 따릅니다. 완료 여부는 [M10 단계 기록](phases/protview-comparison/index.json)에 따릅니다.

M6에서는 전처리 구조의 정확한 리간드 인스턴스를 선택하거나 접촉 결과의 정확한 입력을 선택하여 FreeSASA Lee–Richards 100-slice SASA를 계산합니다. 단백질 매몰, 리간드 매몰, 총 SASA 손실과 잔기별 값을 Å²로 표시합니다. 선택한 SASA 결과의 별도 방법 보고서를 Markdown/JSON으로 저장하고 다시 열 수 있습니다. 이 면적은 친화도나 에너지가 아닙니다. 방법·한계·검증 범위는 [M6 기록](docs/M6_SASA.md)을 따릅니다.

접촉이 없는 정상 결과는 `scientific_null`로 표시됩니다. 읽기나 계산 실패와 리간드 부재/다중 선택 요구는 별도 상태입니다. 거리는 Å 단위이며, 기하학적 polar/hydrophobic contact는 검증된 수소결합·친화도·안정성·에너지를 뜻하지 않습니다. 지원하지 않는 전처리와 과학 계산은 거부하거나 사용 불가로 표시합니다. PyRosetta relax, Cartesian ddG, interface analysis, residue energies는 실제 구현·검증된 엔진이 없어 사용할 수 없으며 보고서에 점수나 순위가 없습니다. `/gallery`는 디자인 예시입니다.

고정된 API 워크플로 `POST /runs/{id}/inspect_complex`는 동일한 검증 업로드 ID 또는 같은 run의 구조 handle을 받아 명시한 모델/전처리와 정확한 리간드 선택으로 `Run.call`을 순서대로 실행합니다. 리간드가 하나일 때만 자동 선택합니다. 보고서 API는 `POST /runs/{id}/reports`에 선택한 `interaction_handle`을 전달합니다. `GET /runs/{id}/reports`, `/reports/selected?handle=...`, `/reports/download?handle=...&format=markdown|json`으로 저장된 결과를 읽고 내려받습니다. 외부 요청이나 키가 필요하지 않습니다. [M5 구현 문서](docs/M5_REPORTS.md)에 요청·증거 형식과 한계가 있습니다.

선택적인 내부 Jev 연동은 명시적으로 설정한 온라인 run에서만 접촉표의 보기를 추천합니다. API 키가 있어도 일반 UI의 새 run은 `local_only`로 생성됩니다. 합성 집계값을 사용한 OpenRouter 실호출 1회를 검증했으며, 이는 연결 검증입니다. 과학적 판단의 품질 검증이나 벤치마크를 뜻하지 않습니다. 설정·전송 범위·사용량 기록은 [M3 구현 문서](docs/M3_EGRESS.md)를 따릅니다.

## 설계와 단계별 검증

- [아키텍처](docs/ARCHITECTURE.md), [채택·보류 결정](docs/DECISIONS.md), [M0–M5 구현 계획](docs/IMPLEMENTATION_PLAN.md)
- [구조 API](docs/M1_API.md), [뷰어 동작과 검증](docs/M1_VIEWER.md), [M1 승인 검토](phases/protview-mvp/reviews/step1.md)
- [실행·복구 계약](docs/RUNTIME_CONTRACT.md), [외부 요청 계약](docs/EGRESS_CONTRACT.md), [작업 계약](docs/JOBS_CONTRACT.md), [보고서 계약](docs/REPORT_CONTRACT.md)
- [M8 에이전트 계약](docs/M8_AGENT_VIEWER_CONTRACT.md), [오프스크린 검증 계획](docs/M8_OFFSCREEN_QA_PLAN.md), [실제 검증 결과](docs/M8_QA_RESULTS.md)
- [M9 저장 보기·PNG 사용 안내](docs/M9_SCENES_EXPORT.md), [M9 계약](docs/M9_SCENES_EXPORT_CONTRACT.md), [M9 오프스크린 검증 계획](docs/M9_OFFSCREEN_QA_PLAN.md)
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
.venv/bin/python scripts/execute.py protview-agent-ui --dry-run
```

현재 M8 확장의 검사 명령은 `phases/protview-agent-ui/step0.md`와 `index.json`에 있습니다. M6/M7 기록은 `phases/protview-methods/`에 보존됩니다. 기존 MVP 명세는 `phases/protview-mvp/`에 보존되어 있습니다. 전체 `--verify`는 모든 단계가 구현·검토된 뒤의 최종 게이트입니다. 단계 검사만으로 미검토 단계를 완료로 표시하지 않습니다.

제공된 `agent_protein_viewer_plan_v05.md`, `molecular-workspace.zip` 및 `references/molecular-workspace/`는 원본 참고 자료로 보존합니다. 제품에 채택한 범위와 현재 동작은 위의 설계 문서 및 실제 검증 기록을 따릅니다.

### OpenMM protein-only potential (M7)

The local method-job panel preflights a prepared standard protein, shows explicit exclusions, then requires `protein_only` and `rebuild_pH7` confirmation before submission. Start requests first-expensive approval; approval is a separate recorded UI action. Status, bounded retry, cancel, exact kJ/mol result, minimized-protein viewer and separate Markdown/JSON method report are available through the same run. Install from `backend/pyproject.toml` in the project environment; OpenMM is pinned to 8.6.0. See [docs/M7_OPENMM.md](docs/M7_OPENMM.md) for the fixed settings, evidence, unsupported inputs and scientific limits. M7 scientific, host/browser and Astra review evidence passed; the phase index records the actual acceptance/review binding and final verification state.

The worker durably records validated hydrogenated preparation and System bytes before its first protocol potential evaluation. Failed, cancelled or interrupted attempts can retain a preparation handle without an energy result; the job API returns the exact prepared input handle for UI selection. Missing OpenMM, mismatched fixed force-field files, or unavailable pinned raw process identity prevent unsafe dispatch before budget reservation. The queue and guardian require psutil 7.2.2 on Darwin or Linux for new launches; legacy active public-time records cannot authorize signals. The UI preflight uses the exact prepared-structure query, refreshes the charged budget after job transitions, resets input-specific policy acknowledgments, and keeps saved result/report read errors separate. Actual host and browser checks passed. M8 now labels minimized protein coordinates explicitly in the canvas; the method panel and return-to-original action retain the exact separate input identity.
