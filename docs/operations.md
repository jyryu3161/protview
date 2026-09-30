# 운영

## 필요 조건

- CPython 3.11 이상. 검증 환경은 3.11.11이다. M11 ProLIF 작업 프로세스는 **CPython 3.11, macOS arm64**에서만 설치할 수 있다.
- Node.js 22 이상, npm. 검증 환경은 Node 24.3.0, npm 11.4.2다.
- POSIX 운영체제(Darwin 또는 Linux). 작업 감독은 psutil 7.2.2 기반 프로세스 신원이 Darwin/Linux에서만 동작하므로, 다른 OS에서는 새 작업이 시작되지 않는다.
- 설치할 때만 네트워크가 필요하다. 설치 후 구조 검사, 계산, 보고서 생성은 오프라인으로 동작한다.

## 처음 설치 (프로젝트 루트에서, 순서대로)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
```

- 2단계는 1단계의 `.venv`가 있어야 한다. 백엔드 코드와 훅은 `.venv/bin/python`을 기준으로 한다.
- 4단계(build)는 3단계 뒤에 실행한다. `start`는 build 산출물(`frontend/.next/`)이 필요하다.
- `backend[science]` 추가 설치 항목(rdkit, prolif, plip, MDAnalysis)은 서버 환경에 설치하지 않는다. 화학 엔진은 아래의 별도 작업 프로세스 환경에만 둔다.

### M11 화학 작업 프로세스 환경 (선택)

```bash
.venv/bin/python scripts/setup_prolif_worker.py --wheelhouse <33개 wheel이 있는 디렉터리>
```

- 기본 설치 위치는 `.deps/prolif/venv-locked/`이며, 서버는 이 경로의 `bin/python`만 작업 프로세스 인터프리터로 쓴다.
- 스크립트는 `config/chemical/prolif-wheel-hashes-macos-arm64-py311.json`의 33개 파일 이름과 SHA-256이 모두 맞을 때만 설치한다. 버전 조합은 ProLIF 2.2.2, RDKit 2026.3.6, MDAnalysis 2.10.0, gemmi 0.7.5다.
- 이 스크립트를 실행하는 인터프리터가 CPython 3.11 macOS arm64가 아니면 설치를 거부한다.
- 설치하지 않으면 `/capabilities`의 `chemical_interactions`가 사용할 수 없음으로 표시되고, 나머지 기능은 정상 동작한다.

### M12 fpocket 작업 환경 (선택)

```bash
.venv/bin/python scripts/setup_fpocket.py --pkgs <35개 conda archive가 있는 디렉터리>
```

- conda와 macOS ≥ 14.5 arm64가 필요하다. 이 조건이 아니면 설치를 거부하고, 포켓 검출은 `/capabilities`에서 사용할 수 없음으로 표시된다(나머지 기능은 정상).
- `--pkgs`에는 로컬 conda 패키지 캐시(예: `~/anaconda3/pkgs`)나 archive를 모아 둔 폴더를 준다. 스크립트는 `config/pockets/`의 잠금과 35개 이름·SHA-256을 모두 맞춘 뒤 `conda create --offline`으로 `.deps/fpocket/env/`에 설치하고, 실행 파일 SHA-256(`a79058e4…2894`)과 설치 기록 `.deps/fpocket/install-record.json`을 남긴다. 다운로드는 하지 않는다.
- 이미 설치되어 있으면 거부한다. 다시 설치하려면 서비스를 멈추고 `.deps/fpocket/`을 직접 옮긴 뒤 실행한다.
- conda 23.3.1은 새 환경을 `~/.conda/environments.txt`에 등록한다.

### M15 참조 스냅샷 (선택)

```bash
.venv/bin/python scripts/import_reference_snapshots.py --from ../kbase_kinase
```

- `--from`에는 로컬 `kbase_kinase` 체크아웃을 준다(읽기만). 그 `ref/manifest.json`에서 출처별 가장 최근 날짜 스냅샷(UniProt `entries.jsonl`, SIFTS `residues.jsonl`·`segments.jsonl`, KLIFS `kinases.jsonl`·대조용 `match_residues.jsonl`)만 `--dest`(기본 `.deps/reference/`)로 복사한다. kbase 가공본이며 원출처 원본 바이트가 아니다(결정 0022).
- 복사 전에 파일마다 SHA-256·바이트·행 수를 kbase 매니페스트와 대조하고, 하나라도 다르면 아무것도 바꾸지 않고 실패한다. 네트워크를 쓰지 않는다(kbase 커밋은 `git -C`로 읽고, 작업 트리가 깨끗하지 않으면 그 사실을 기록한다).
- 다시 가져오기: 실행할 때마다 새 세트 폴더 `sets/<set_hash>/`를 쓰고 `active.json`을 rename 한 번으로 바꾼다. 매니페스트에 가져온 시각(`imported_at`)이 들어가므로 같은 파일을 다시 가져와도 세트 해시가 새로 생기고, 이전 세트로 만든 대응은 화면에서 "이전 스냅샷 기준"으로 보인다. 이전 세트 폴더는 지우지 않는다. 서버가 도는 중에 바꿔도 되며(호출마다 세트를 한 번 고정), 서버 재시작은 필요 없다.
- 가져오지 않으면 `/capabilities`의 `residue_numbering`과 지식 탭이 사용할 수 없음(`not_installed`)으로 표시되고, 나머지 기능은 정상이다.

## 실행

터미널 두 개에서 각각 실행한다.

```bash
.venv/bin/python -m uvicorn mw.api.app:app --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend run start -- -p 3000
```

- 브라우저로 `http://127.0.0.1:3000`을 연다. 개발 중에는 `start` 대신 `npm --prefix frontend run dev`를 써도 된다(`127.0.0.1` 바인딩).
- 프런트엔드는 `/api/*`를 `http://127.0.0.1:8000`으로 프록시한다. 백엔드 포트를 바꾸면 `frontend/next.config.mjs`의 rewrite도 같이 바꿔야 한다.
- 원격 서버: 그 서버를 혼자 쓰는 경우에만 위와 똑같이 loopback으로 실행하고, 내 컴퓨터에서 `ssh -L 3000:127.0.0.1:3000 <server>`로 접속한다. `--host 0.0.0.0`은 쓰지 않는다.

## 환경 설정

| 항목 | 위치 | 의미와 범위 |
|---|---|---|
| `MW_RUNS_DIR` | 백엔드 환경변수 | run 데이터 루트. 기본값 `runs`는 uvicorn을 시작한 디렉터리 기준 상대 경로이므로 백엔드는 저장소 루트에서 시작한다(그래야 Git에서 제외된 루트 `runs/`가 된다). 저장소 안의 다른 경로로 바꾸면 그 경로를 직접 `.gitignore`에 추가해야 한다. 백엔드를 시작하기 전에 설정한다 |
| `MW_REFERENCE_DIR` | 백엔드 환경변수 | M15 참조 폴더. 기본 `<저장소>/.deps/reference`, 상대 값은 저장소 루트 기준. 수락 QA는 격리 폴더를 준다. 가져오기 명령은 이 변수가 아니라 `--dest`를 쓰므로 둘을 같은 곳으로 맞춘다 |
| `OPENROUTER_API_KEY` | 루트 `.env`(권한 0600) 또는 환경변수 | 온라인 뷰어 해석과 M3 결정에만 쓴다. 없으면 온라인 기능만 사용할 수 없고, 나머지는 정상이다 |
| `config/default.yaml` | 저장소 | run 기본 예산(1800초, 비싼 계산 8회, 토큰 120,000, USD 2.00), 재시도·루프 가드, egress 기본 모드(`local_only`), Jev 엔드포인트·모델 pin. 새 run에만 적용되고, 이미 만든 run의 한도는 그 run의 `run_started` 이벤트가 기준이다 |
| `config/tools.yaml` | 저장소 | 도구 명세(허용 입력 종류, 파라미터 범위, 비용 등급). 여기 있다고 모두 노출되지는 않는다 |
| `config/pipelines/inspect_complex.yaml` | 저장소 | 고정 inspect_complex 파이프라인 정의 |
| `NEXT_TELEMETRY_DISABLED=1` | npm 스크립트에 고정 | Next.js 텔레메트리 차단 |

## 검증 명령

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py scripts/test_m14_offscreen_acceptance.py scripts/test_import_reference_snapshots.py scripts/test_m15_offscreen_acceptance.py scripts/test_measure_klifs_numbering.py -q
node --check frontend/tests/offscreen/pocket-flow.cjs
node --check frontend/tests/offscreen/workflows-flow.cjs
node --check frontend/tests/offscreen/tabs-flow.cjs
node --check frontend/tests/offscreen/numbering-flow.cjs
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

- `scripts/test_import_reference_snapshots.py`(가져오기: 해시 불일치 시 무변경, 원자적 교체, 매니페스트 필드, 네트워크 없음), `scripts/test_m15_offscreen_acceptance.py`(M15 실행기 판정), `scripts/test_measure_klifs_numbering.py`(측정 분류)는 서비스를 띄우지 않으며 Stop 훅 세 번째 그룹에 들어 있다. 백엔드 M15 테스트는 대부분 커밋된 fixture 세트(`backend/tests/reference_fixture_set.py`)를 임시 참조 폴더에 만들어 쓰므로 `.deps/reference`가 없어도 돈다. 예외로 `backend/tests/test_klifs_numbering.py`의 실제 스냅샷 테스트 2개는 `/Users/jaeyongryu/Projects/kbase_kinase/ref`(고정 절대 경로)를 읽고, 없으면 skip한다(`docs/tracking/findings.md`).
- `scripts/test_m14_offscreen_acceptance.py`는 M14 실행기의 사례 판정·`acceptance` 판정을 보는 단위 테스트다(서비스를 띄우지 않음, Stop 훅 세 번째 그룹).
- `scripts/test_m13_offscreen_acceptance.py`는 M13 실행기의 하위 대장 판정, `acceptance` 판정, 빌드 출처 확인을 보는 단위 테스트다(서비스를 띄우지 않음). Stop 훅의 세 번째 pytest 그룹에 들어 있다.
- git worktree에서 백엔드 테스트나 서비스를 돌릴 때는 `PYTHONPATH=<worktree>/backend`를 준다. `.venv`의 editable 설치가 주 체크아웃의 `backend/`를 가리키므로, 주지 않으면 worktree의 `mw`가 아니라 주 체크아웃의 `mw`를 import한다.
- 과학 네이티브 테스트(FreeSASA, OpenMM, M11 ProLIF, M12 fpocket)는 해당 엔진이 설치되어 있어야 의미가 있다. M11 테스트는 `.deps/prolif/venv-locked`, M12 테스트는 `.deps/fpocket/env`가 필요하며, 없으면 skip이 아니라 실패한다.
- Claude Code와 Codex의 Stop 훅(`.codex/hooks/stop.py`)은 대화 턴이 끝날 때 ruff(45초 제한)를 돌린 뒤, pytest 세 그룹을 동시에 실행한다: `test_chemical_interactions.py`, `test_m11_job_api.py`, 나머지 백엔드와 실행기 테스트. 그룹마다 480초 제한이 있고, 전체 제한은 600초다. 세 번째 그룹(나머지 백엔드·실행기·fpocket 설치·M13·M14·M15 수락 실행기·가져오기·측정 단위 테스트)은 M13 테스트가 들어간 뒤 2026-09-29 단독 실행에서 382초(634개)였다(M14 실행기 테스트 8개는 서비스를 띄우지 않아 몇 초 이내, 다시 재지 않음. M15에서 백엔드 테스트가 806개로 늘었고 전체 백엔드 pytest 단독 실행이 963초였다(게이트, 두 화학 그룹 포함). 세 번째 그룹만 다시 재지는 않았다). 그룹 제한 480초에 여유가 크지 않으므로, 테스트가 더 늘면 그룹을 나눈다. ruff가 실패하면 pytest는 돌리지 않는다. 실패하면 턴 종료를 한 번 막고 오류를 돌려준다. 그 뒤 다시 종료할 때(`stop_hook_active`)는 무한 반복을 막으려고 통과시키므로, 훅을 지나갔다고 게이트를 통과한 것은 아니다.

## 오프스크린 UI 검증

백엔드와 프런트엔드를 위처럼 loopback으로 띄운 상태에서 실행한다.

```bash
npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000
npm --prefix frontend run test:offscreen:normal
npm --prefix frontend run test:offscreen:scenes
npm --prefix frontend run test:offscreen:chemical
```

- 첫 명령은 Electron 44.4.5의 보이지 않는 오프스크린 창을 띄워 GPU 가속과 `isOffscreen()`을 확인하고, paint 프레임과 스크린숏을 `frontend/tests/offscreen/artifacts/`에 저장한다. loopback이 아닌 요청은 모두 차단하고 기록한다.
- `--interactive`를 붙이면 stdin으로 JSON 명령을 한 줄씩 받아 실제 마우스·키보드 입력을 보낸다.
- 이 외에 `:keyboard`, `:openmm`, `:retry`, `:faults`, `:post-races`, `:dry-run`, `:persistence` 흐름 스크립트가 있다. M10 비교 흐름은 npm 스크립트가 없으므로 `node frontend/tests/offscreen/comparison-flow.cjs --url http://127.0.0.1:3000 --mode <모드> --run <run_id> --artifacts <디렉터리>`로 직접 실행한다(`--other-run`은 두 run 전환 모드에서 쓴다).

### M11 화학 상호작용 수락 QA

프런트엔드를 먼저 빌드하고(`typecheck` 다음 `build`), 8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스를 직접 띄우고 끝나면 정리한다.

```bash
.venv/bin/python scripts/m11_offscreen_acceptance.py --root runs/m11-acceptance-<날짜> --artifacts frontend/tests/offscreen/artifacts/m11-acceptance/<이름>
```

- runs 루트는 새 폴더여야 하고 `/tmp` 아래면 거부한다. 전역 작업 검사의 한도(run 1,000개 등)에 걸리지 않도록 QA마다 새 루트를 쓴다.
- 단계: M11 모드 전체(H01–H17) → M8 normal·OpenMM 준비·M9 scenes·M10 measure/alignment 회귀 → events-only 복구(원본 입력 없이, 작업 프로세스 없이) → 작업 프로세스 없음·버전 불일치 표시 → `case-ledger.json` 집계. `--only 단계,...`로 한 단계만 다시 돌리면 새 디렉터리에 기록하고 이전 증거를 덮어쓰지 않는다.
- 입력: 공개 fixture는 `backend/tests/fixtures/chemical/`의 파일을 그대로 쓴다. 합성 파생 입력(연결용 복합체 PDB, 빈 결과 SDF, 수용체 결합 목록)은 `scripts/m11_qa_inputs.py --out <디렉터리>`가 만들고 기록된 SHA-256과 대조한다. run에 묶인 연결 입력은 `scripts/m11_attach_browser_setup.py`가 그 run의 실제 카탈로그로 만든다. 잘못된 입력 사례는 `scripts/m11_invalid_inputs.py`가 만든다.
- 커밋하는 증거는 `docs/qa/m11-chemical-<날짜>/`에 두고, 스크린숏·다운로드 원본은 git에서 제외된 artifacts 폴더에 두며 해시만 기록한다. 절대 경로는 `<repo>` 같은 표시로 바꾼다.

### M12 포켓 후보 수락 QA

프런트엔드를 먼저 빌드하고(`typecheck` 다음 `build`), 8000·3000 포트가 비어 있는 상태에서 실행한다.

```bash
.venv/bin/python scripts/m12_offscreen_acceptance.py --root runs/m12-acceptance-<날짜> --artifacts frontend/tests/offscreen/artifacts/m12-acceptance/<이름> [--export-evidence <폴더>]
```

- 단계: 포켓 흐름 13개(양성, 빈 결과, 잘못된 입력, 취소, 다시 열기, 보고서 다운로드, 오버레이 중 비활성, 거리 측정, 비교 차단, 늦은 응답, 최소화 구조, M11 화학 구조 만들기와 화학 작업 화면) → M8·M9·M10·M11 회귀 → events-only 복구 → 엔진 없음·해시 불일치 → 남은 프로세스 확인 → `case-ledger.json`. 필수 단계가 빠지거나 실패하면 판정은 실패다.
- 엔진 없음·해시 불일치는 수락 루트 안에 만든 코드 복사본(`layout-engine-*`)으로 확인한다. 요청이나 환경변수로 엔진 경로를 바꾸는 방법은 없다.
- `--only 단계,...`는 새 폴더에 기록하고 대장을 `case-ledger-partial.json`(수락 아님)으로 남긴다.
- 남은 프로세스 확인은 작업 폴더가 수락 루트 안인 프로세스만 센다. 그래도 수락 QA 중에는 Stop 훅 pytest가 겹치지 않게 하는 편이 증거를 읽기 쉽다.
- `--export-evidence`는 로컬 경로를 `<repo>`·`<home>`으로 바꾼 텍스트 증거와 `SHA256SUMS`, 이진 파일 해시 목록을 쓴다. 커밋하는 증거(`docs/qa/m12-pockets-<날짜>/`)는 그중 작은 파일과 해시 목록만 둔다.

### M13 분석 흐름 수락 QA

프런트엔드를 먼저 빌드하고(`typecheck` 다음 `build`), 8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root 안>`)를 직접 띄우고 끝나면 정리한다. 수락 QA 중에는 Stop 훅 pytest가 겹치지 않게 한다.

```bash
.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/<이름> \
    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-<YYYYMMDD>
```

- 단계: `workflows`(main, m10, race, minimize, chemical-create, attach-setup, chemical-attach, chemical-error, dry-run: 템플릿 6개와 상태 사례) → `unavailable`(엔진 없음) → `regressions`(이 실행기의 서비스로 M8 normal-flow, M9 openmm-flow full → scenes-flow core, M10 comparison-flow measure·alignment) → `m11`·`m12`(`scripts/m11_offscreen_acceptance.py`·`scripts/m12_offscreen_acceptance.py` 전체를 `<root>/m11-acceptance`·`<root>/m12-acceptance`에서, 각자 서비스를 띄우고 끔) → `ledger`(사례 28개, 남은 프로세스, 외부 요청 합계). 필수 단계·사례가 빠지거나 실패하면 판정은 실패다.
- `--only 단계,...`는 대장을 `partial_not_acceptance`로 남기고 증거를 내보내지 않는다. `--build auto`(기본)는 `frontend/.next/BUILD_ID`가 이 실행기가 현재 프런트엔드 소스(`app/`, `src/`, 설정·package 파일)로 빌드하며 남긴 해시(`.next/protview-source-sha256`)와 맞을 때만 빌드를 건너뛰고, 아니면 typecheck → build를 한다(실행기 밖에서 만든 빌드도 다시 빌드한다). 대장의 `acceptance`는 `workflows,unavailable,regressions,m11,m12`를 한 번에 모두 돌려 통과했을 때만 true다(기본 phase만 돌리면 verdict가 pass여도 false). `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다.
- 흐름 스크립트만 따로 돌리려면 서비스를 띄운 상태에서 `npm --prefix frontend run test:offscreen:workflows -- --mode <모드> --artifacts <디렉터리>`를 쓴다. `race`는 `--run`·`--other-run`, `chemical-attach`는 `scripts/m11_attach_browser_setup.py` 산출물(`--run --complex --mapping --ligand --sidecar`)이 필요하고, 입력 준비 전체 순서는 실행기에 있다.
- 커밋하는 증거(`docs/qa/m13-workflows-<날짜>/`)는 README, `gate-results.md`, `freeze-manifest.txt`, 사례 대장, 텍스트 증거, `SHA256SUMS`, `binary-artifacts.json`이다. 스크린숏·paint·다운로드 원본은 Git 제외 artifacts 폴더에 두고 해시만 기록한다.
- 큰 텍스트 증거(결정 0020): 내보낸 뒤 256 KiB를 넘는 텍스트 파일은 대장(`case-ledger*.json`, `ledger-row.json`)을 빼고 그 실행의 artifacts 폴더 `export-full/`로 같은 상대 경로로 옮긴다(삭제하지 않음). 옮긴 파일의 SHA-256을 `ARCHIVED-EVIDENCE.sha256`에 쓰고, `SHA256SUMS`의 원래 줄은 남기며, README 끝 절에 목록·크기·해시와 확인 명령(`cd <artifacts>/export-full && shasum -a 256 -c <repo>/docs/qa/<폴더>/ARCHIVED-EVIDENCE.sha256`)을 적는다. 이 이동은 실행기가 하지 않으므로 내보낸 뒤 직접 한다. M11 하위 실행기의 `chemical-evidence.json`은 하나가 약 62 MB까지 커진다.

### M14 탭 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스를 직접 띄우고 끝나면 정리하며, `--build auto`(기본)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. 대장의 `acceptance`는 모든 사례가 돌고 통과했고 빌드가 현재 소스와 맞을 때만 true다. 화학 모드는 코드 루트의 `.deps/prolif/venv-locked`가 필요하다(git worktree에서 돌릴 때는 주 체크아웃의 `.deps`를 Git 제외 심볼릭 링크로 둔다).

```bash
.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m14-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/<이름> --out docs/qa/m14-tabs-<YYYYMMDD>
```

- 모드: `main`(run 없음 → 탭 순서·기본값 → 구조 상태 왕복 → 기능 없는 탭 → 보고서 목록·내용·다운로드·fault → 작업 진행 중 탭 왕복·예산 → run 전환·늦은 응답)과 `chemical`(화학 화면의 탭 막대·상태 유지·예산). 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:tabs -- --mode <main|chemical> --artifacts <디렉터리>`.
- M8–M13 회귀는 M13 실행기를 모든 phase로, 기존 M13 증거 폴더가 아닌 곳에 돌린다: `--phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m14-tabs-<YYYYMMDD>/m13-regression`.
- 내보낸 뒤 큰 텍스트 증거는 결정 0020대로 옮기고, README를 고쳤으면 `SHA256SUMS`의 README 줄도 갱신한다.

### M15 잔기 번호 대응 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`, `MW_REFERENCE_DIR=<root>/reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다.

```bash
.venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/<이름> --kbase ../kbase_kinase \
    --out docs/qa/m15-numbering-<YYYYMMDD>
```

- 순서: `numbering-empty`(빈 참조 폴더: 사용할 수 없음) → `reference-import`(가져오기 명령을 하위 프로세스로 `--dest <root>/reference`) → `numbering-main`(PDB ID 확인·SIFTS 미리 채움, KLIFS 번호 대조, 상태 필터, 충돌 행, PDB ID 없는 정렬, 기준 미달, 전처리 구조, 보고서·다운로드 해시, 읽기 실패와 다시 시도, run 전환·늦은 응답) → `reference-reimport`(표시된 fixture 세트를 테스트 도우미로 활성화: 다른 세트 해시) → `numbering-stale`("이전 스냅샷 기준"). 대장의 `acceptance`는 모든 단계가 이번 실행에서 돌고 두 참조 변경이 성공했으며 모든 사례 통과, 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 프로세스·리스너 없음일 때만 true다.
- `--kbase` 기본값은 `<저장소>/../kbase_kinase`다. git worktree에서는 이 기본값이 틀린 곳을 가리키므로 절대 경로를 준다(2026-09-30 수락 QA는 `--kbase <home>/Projects/kbase_kinase`로 실행).
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:numbering -- --mode <empty|main|stale> --artifacts <디렉터리>`(`main`·`stale`은 `--set-hash`, `stale`은 `--runs <runA,runB> --previous-set-hash`도 필요). 전체 순서와 참조 폴더 변경은 실행기에 있다.
- 회귀: M14 실행기(`--out docs/qa/m15-numbering-<YYYYMMDD>/m14-regression`)와 M13 실행기 모든 phase(`--phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m15-numbering-<YYYYMMDD>/m13-regression`)를 각각 새 `--root`·`--artifacts`로 돌린다. 큰 텍스트 증거는 결정 0020대로 옮긴다.

### M15 KLIFS 번호 측정

```bash
.venv/bin/python scripts/measure_klifs_numbering.py --reference-dir .deps/reference --out docs/qa/m15-numbering-<YYYYMMDD>/klifs_measurement.txt
```

- 사용 중 세트의 KLIFS 구조별 표(`match_residues`, 대조 전용)와 우리 KLIFS 번호를 SIFTS를 거쳐 비교한다(일치·불일치·번호 없음·우리만 번호·숫자 아닌 자리 제외). 요약 JSON은 stdout으로 나온다. 네트워크 없음, 제품 결과가 아니다.
- `--out`을 주지 않으면 지금은 없는 `docs/qa/m15-numbering-draft/`를 가리키므로 항상 준다. 텍스트 머리글의 "draft" 문구는 스크립트 고정 문자열이다.

## 과거 단계 재검증

```bash
.venv/bin/python scripts/execute.py protview-mvp --dry-run
mkdir -p /tmp/protview-phase-snapshot && cp -p phases/index.json /tmp/protview-phase-snapshot/index.json && cp -p phases/protview-mvp/index.json /tmp/protview-phase-snapshot/protview-mvp.json
.venv/bin/python scripts/execute.py protview-mvp --verify
cp -p /tmp/protview-phase-snapshot/index.json phases/index.json && cp -p /tmp/protview-phase-snapshot/protview-mvp.json phases/protview-mvp/index.json
```

`--verify`는 모델을 호출하지 않는다. 검토 증거 해시를 확인하고 수락 명령을 다시 실행한다. 이때 `phases/index.json`과 해당 그룹의 `index.json`을 고쳐 쓰므로(실패하면 `error`, 통과하면 새 `completed_at`), 위처럼 실행 전에 두 파일을 복사해 두고 끝나면 되돌린다. `git checkout`으로 되돌리면 커밋되지 않은 다른 단계 기록 변경까지 사라질 수 있으므로 복사본으로 복원한다. 결과는 출력만 보고한다. 새 단계 구현(`execute.py <phase>` 기본 실행)은 Codex CLI와 GPT-6 모델이 필요하므로 이 환경에서는 쓰지 않는다.

## run 데이터 백업과 보관

- 백업 단위는 run 디렉터리 전체(`runs/<run_id>/`)다. `events.jsonl`만 있어도 객체와 색인을 복구할 수 있지만, 복사할 때는 디렉터리 전체를 옮긴다.
- 보관 절차: 서비스를 중지 → 해당 run에 running·cleanup-pending 작업이 없는지 확인 → 디렉터리 전체를 복사 → 파일 해시 검증 → runs 루트 밖으로 이동 → 이동 위치를 기록. 되돌릴 때는 디렉터리 전체를 원래 위치로 옮긴다.
- 배포 절차는 없다. 각 구성원이 자기 컴퓨터나 혼자 쓰는 서버에 위 설치 절차를 그대로 따른다.
