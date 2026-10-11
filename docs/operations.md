# 운영

## 필요 조건

- CPython 3.11 이상(`backend/pyproject.toml`의 `requires-python = ">=3.11"`). 검증 환경은 3.11.11이다. 가상환경은 `python3.11`로 만든다: 선택 작업 환경 설치 스크립트(`setup_prolif_worker.py`·`setup_docking_worker.py`)는 실행 인터프리터(아래 명령의 `.venv/bin/python`)가 **CPython 3.11, macOS arm64**가 아니면 거부하고 그 인터프리터로 작업 환경 venv를 만든다. `python3`은 다른 버전을 가리킬 수 있다(2026-10-11 검증 컴퓨터에서는 anaconda Python 3.10.9였고, 그 `.venv`로는 2단계가 `requires-python`에 걸린다).
- Node.js 22 이상, npm. 검증 환경은 Node 24.3.0, npm 11.4.2다.
- POSIX 운영체제(Darwin 또는 Linux). 작업 감독은 psutil 7.2.2 기반 프로세스 신원이 Darwin/Linux에서만 동작하므로, 다른 OS에서는 새 작업이 시작되지 않는다.
- 지원 환경: 구조 불러오기·전처리·기하 접촉·SASA·OpenMM·보고서는 위 POSIX 조건에서 쓰도록 설계되어 있으나 **검증은 macOS arm64 CPython 3.11에서만** 했다. 선택 작업 환경의 잠금은 macOS arm64 전용이다: M11·M17 ProLIF 작업 환경과 M18 도킹 작업 환경은 CPython 3.11 macOS arm64, M12 fpocket은 conda가 있는 macOS ≥ 14.5 arm64, M18 qvina는 conda가 있는 macOS ≥ 11.0 arm64에서만 설치되고(설치 스크립트가 그 밖의 플랫폼을 거부), Linux·Intel Mac용 잠금은 없다. 그래서 그 밖의 환경에서는 화학 상호작용·리간드 후보·포켓 후보·도킹·일괄 도킹·리간드 GA·서열 GA·같은 조건 도킹·JEV 루프 계산이 `/capabilities`와 화면에서 숫자 없이 사용할 수 없음과 이유로 보인다. M21 변이 구조 모델링의 OpenMM·PDBFixer는 프로젝트 `.venv`에 들어가 이 잠금에 묶이지 않지만 역시 macOS arm64에서만 검증했다. 한 사람이 자기 컴퓨터나 혼자 쓰는 서버에서 쓰는 전제는 그대로다(`docs/security.md`).
- 설치할 때만 네트워크가 필요하다: PyPI(2단계, PDBFixer 1.12.0 sdist 빌드의 격리 빌드 환경 포함), npm 레지스트리(3단계, Electron 설치 스크립트가 실행 파일을 따로 받는다. 캐시가 있으면 받지 않을 수 있다). 설치 후 구조 검사, 계산, 보고서 생성은 오프라인으로 동작한다. 그 밖에 외부 요청을 하는 것은 사용자가 터미널에서 실행하는 M26 반응 참조 가져오기 명령(아래)과, run에서 사람이 명시적으로 켠 JEV 모델 호출(온라인으로 설정한 run의 뷰어 해석·M3 결정, M24·M25 과학 전송)뿐이다(`docs/security.md` "외부 요청 권한").

## 처음 설치 (프로젝트 루트에서, 순서대로)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
```

- 1단계는 `python3.11`로 만든다(위 필요 조건). 표준 `venv`는 pip를 함께 넣으므로 2단계를 그대로 쓸 수 있다.
- 2단계는 1단계의 `.venv`가 있어야 한다. 백엔드 코드와 훅은 `.venv/bin/python`을 기준으로 한다.
- 2단계의 의존성: 과학 결과에 영향을 주는 여섯(gemmi 0.7.5, numpy 2.4.6, freesasa 2.2.1, openmm 8.6.0, pdbfixer 1.12.0, psutil 7.2.2)은 정확한 버전으로 고정되어 있고, 나머지(pydantic, pyyaml, httpx, anyio, fastapi, uvicorn, pyarrow와 `dev`의 pytest, ruff)는 하한만 있다. Python 잠금 파일은 없으므로 설치한 날 PyPI에서 범위 안의 버전을 받는다. 3단계 `npm ci`는 `frontend/package-lock.json` 그대로 설치한다.
- 4단계(build)는 3단계 뒤에 실행한다. `start`는 build 산출물(`frontend/.next/`)이 필요하다.
- `backend[science]` 추가 설치 항목(rdkit, prolif, plip, MDAnalysis)은 서버 환경에 설치하지 않는다. 화학 엔진은 아래의 별도 작업 프로세스 환경에만 둔다.
- 여기까지가 핵심 설치다. 아래 선택 작업 환경과 참조 스냅샷을 설치하지 않으면 그것을 쓰는 기능만 `/capabilities`와 화면에서 숫자 없이 사용할 수 없음과 이유로 보이고 나머지 기능은 동작한다. 과학 엔진 테스트는 해당 환경이 없으면 skip이 아니라 실패한다(아래 "검증 명령").

### M11 화학 작업 프로세스 환경 (선택)

```bash
.venv/bin/python scripts/setup_prolif_worker.py --wheelhouse <33개 wheel이 있는 디렉터리>
```

- 기본 설치 위치는 `.deps/prolif/venv-locked/`이며, 서버는 이 경로의 `bin/python`만 작업 프로세스 인터프리터로 쓴다.
- 스크립트는 `config/chemical/prolif-wheel-hashes-macos-arm64-py311.json`의 33개 파일 이름과 SHA-256이 모두 맞을 때만 설치한다. 버전 조합은 ProLIF 2.2.2, RDKit 2026.3.6, MDAnalysis 2.10.0, gemmi 0.7.5다.
- 이 스크립트를 실행하는 인터프리터가 CPython 3.11 macOS arm64가 아니면 설치를 거부한다.
- 설치하지 않으면 `/capabilities`의 `chemical_interactions`가 사용할 수 없음으로 표시되고, 나머지 기능은 정상 동작한다.
- M17 리간드 후보 작업(`backend/mw/jobs/ligand_worker.py`)도 이 환경의 RDKit을 쓴다. 설치하지 않으면 `ligand_candidates`도 `worker_missing`으로 사용할 수 없고 리간드 탭은 이유만 보여 준다.

### M12 fpocket 작업 환경 (선택)

```bash
.venv/bin/python scripts/setup_fpocket.py --pkgs <35개 conda archive가 있는 디렉터리>
```

- conda와 macOS ≥ 14.5 arm64가 필요하다. 이 조건이 아니면 설치를 거부하고, 포켓 검출은 `/capabilities`에서 사용할 수 없음으로 표시된다(나머지 기능은 정상).
- `--pkgs`에는 로컬 conda 패키지 캐시(예: `~/anaconda3/pkgs`)나 archive를 모아 둔 폴더를 준다. 스크립트는 `config/pockets/`의 잠금과 35개 이름·SHA-256을 모두 맞춘 뒤 `conda create --offline`으로 `.deps/fpocket/env/`에 설치하고, 실행 파일 SHA-256(`a79058e4…2894`)과 설치 기록 `.deps/fpocket/install-record.json`을 남긴다. 다운로드는 하지 않는다.
- 이미 설치되어 있으면 거부한다. 다시 설치하려면 서비스를 멈추고 `.deps/fpocket/`을 직접 옮긴 뒤 실행한다.
- conda 23.3.1은 새 환경을 `~/.conda/environments.txt`에 등록한다.

### M18 도킹 환경 (선택, 둘 다 필요)

```bash
.venv/bin/python scripts/setup_qvina.py --pkgs <8개 conda archive가 있는 디렉터리> [--prefix .deps/qvina/env] [--conda <conda 실행 파일>]
.venv/bin/python scripts/setup_docking_worker.py --wheelhouse <26개 wheel이 있는 디렉터리> [--destination .deps/docking/venv-locked]
```

- `setup_qvina.py`: conda가 필요하고(`--conda`, 없으면 `$CONDA_EXE`나 PATH의 `conda`) macOS ≥ 11.0 arm64가 아니면 거부한다. `config/docking/qvina-conda-lock-hashes-osx-arm64.json`·`qvina-conda-explicit-osx-arm64.txt`의 8개 archive(conda-forge `qvina 2.1.0` `h4a521e9_8`와 의존) 이름·크기·SHA-256을 모두 맞춘 뒤, 검증한 복사본만 가리키는 명시 목록으로 `conda create --offline`을 한다. 기본 위치 `.deps/qvina/env/`, 설치 기록은 그 부모 `.deps/qvina/install-record.json`(`qvina2` SHA-256 `caf5f22a…f79c`, `--version` 출력 해시, 패키지·라이선스 해시, 설치 시각·플랫폼)이며 마지막에 쓴다. 같은 패키지의 `vina`는 해시만 기록하고 실행하지 않는다.
- `setup_docking_worker.py`: 실행 인터프리터가 CPython 3.11 macOS arm64가 아니면 거부한다. `config/docking/docking-wheel-hashes-macos-arm64-py311.json`·`docking-requirements-macos-arm64-py311.txt`의 26개 wheel(Meeko 0.8.0, RDKit 2026.3.6, MDAnalysis 2.10.0, gemmi 0.7.5, numpy 2.4.6, scipy 1.17.1 등. Meeko 밖의 25개는 M11 ProLIF 잠금과 같은 파일)을 맞춘 뒤 `pip --no-index --require-hashes --no-deps`로 새 venv에 설치한다. 기본 위치 `.deps/docking/venv-locked/`, 설치 기록 `.deps/docking/install-record.json`(Meeko 라이선스 LGPL-2.1, `pip check` 결과).
- 둘 다 다운로드하지 않는다. `--pkgs`에는 로컬 conda 패키지 캐시(예: `~/anaconda3/pkgs`)나 archive를 모아 둔 폴더를, `--wheelhouse`에는 잠금과 같은 wheel을 모아 둔 폴더를 준다(받는 일은 이 명령 밖의 준비 단계이고 잠금 해시로 검증한다). 실패하면 이 실행이 만든 것을 지운다. 이미 설치되어 있으면 거부한다("already exists"). 다시 설치하려면 서비스를 멈추고 기존 폴더를 직접 옮긴 뒤 실행한다. 기존 `.deps/prolif`·`.deps/fpocket`은 건드리지 않는다.
- git worktree에서 설치할 때는 `--prefix`·`--destination`에 주 체크아웃의 절대 경로를 준다(worktree의 `.deps`는 심볼릭 링크이거나 없다).
- 하나라도 없거나 해시·버전이 맞지 않으면 `/capabilities`의 `ligand_docking`이 사용할 수 없음(`worker_missing`, `engine_missing`, `engine_hash_mismatch`, `handshake_failed`, `version_mismatch`)으로 표시되고 리간드 탭 도킹 영역은 이유만 보여 준다. 나머지 기능은 정상이다.

### M21 PDBFixer (변이 구조 모델링, 프로젝트 `.venv`)

PDBFixer 1.12.0은 별도 격리 환경이 아니라 프로젝트 `.venv`에 들어간다(`backend/pyproject.toml`에 `openmm==8.6.0` 다음 줄 `pdbfixer==1.12.0`). 위 2단계 `pip install -e './backend[dev]'`가 함께 설치한다. 해시를 확인하며 넣으려면(착수 확인에서 쓴 방법, `.venv`에 pip가 없으면 uv):

```bash
printf 'pdbfixer==1.12.0 --hash=sha256:82e54074b33eb00270e9a439c8633fcf82cd3ab7a36561b01425a260c0fc4143\n' > pdbfixer-req.txt
uv pip install --python .venv/bin/python --no-deps --require-hashes -r pdbfixer-req.txt
uv pip check --python .venv/bin/python
```

- PyPI 1.12.0 배포는 sdist 하나(`pdbfixer-1.12.0.tar.gz`, 665,893 B)이며 빌드할 때 격리 빌드 환경(setuptools)을 내려받는다. 설치할 때만 네트워크가 필요하다. `--no-deps`는 이미 고정된 numpy 2.4.6·openmm 8.6.0을 건드리지 않기 위해서다. 설치 뒤 `.venv/bin/python -c "import importlib.metadata as m; print(m.version('pdbfixer'))"`가 `1.12.0`이어야 한다.
- 표준 20개 잔기 템플릿은 패키지에 들어 있어 변이 적용 중 PDBFixer가 템플릿을 내려받지 않는다(착수 확인, 네트워크 시도 0건).
- 설치하지 않았거나 버전이 다르면 `/capabilities`의 `mutation_model`이 `pdbfixer_unavailable`로 사용할 수 없고 단백질 공학 탭의 변이 구조 모델링 영역은 이유만 보여 준다. 나머지 기능은 정상이다. 서버는 PDBFixer를 import하지 않고 버전만 읽는다.

### M15 참조 스냅샷 (선택)

```bash
.venv/bin/python scripts/import_reference_snapshots.py --from ../kbase_kinase --dest .deps/reference
```

- `--from`에는 로컬 `kbase_kinase` 체크아웃을 준다(읽기만). 그 `ref/manifest.json`에서 출처별 가장 최근 날짜 스냅샷(UniProt `entries.jsonl`, SIFTS `residues.jsonl`·`segments.jsonl`, KLIFS `kinases.jsonl`·대조용 `match_residues.jsonl`)만 `--dest`(기본 `.deps/reference/`, 위처럼 명시해도 같음)로 복사한다. 지식 탭의 "사용할 수 없음" 안내에 나오는 명령도 이 줄과 같다. kbase 가공본이며 원출처 원본 바이트가 아니다(결정 0022).
- 복사 전에 파일마다 SHA-256·바이트·행 수를 kbase 매니페스트와 대조하고, 하나라도 다르면 아무것도 바꾸지 않고 실패한다. 네트워크를 쓰지 않는다(kbase 커밋은 `git -C`로 읽고, 작업 트리가 깨끗하지 않으면 그 사실을 기록한다).
- 다시 가져오기: 실행할 때마다 새 세트 폴더 `sets/<set_hash>/`를 쓰고 `active.json`을 rename 한 번으로 바꾼다. 매니페스트에 가져온 시각(`imported_at`)이 들어가므로 같은 파일을 다시 가져와도 세트 해시가 새로 생기고, 이전 세트로 만든 대응은 화면에서 "이전 스냅샷 기준"으로 보인다. 이전 세트 폴더는 지우지 않는다. 서버가 도는 중에 바꿔도 되며(호출마다 세트를 한 번 고정), 서버 재시작은 필요 없다.
- 가져오지 않으면 `/capabilities`의 `residue_numbering`과 지식 탭이 사용할 수 없음(`not_installed`)으로 표시되고, 나머지 기능은 정상이다.

### M26 반응 참조 스냅샷 (선택, 공개 서버에서 받음)

```bash
.venv/bin/python scripts/import_reaction_references.py [--accession ACC]... [--accessions-file PATH] [--no-kinases] [--reference-dir PATH] [--yes]
```

- ProtView에서 네트워크를 쓰는 유일한 명령이다. M-CSA API(`www.ebi.ac.uk`)·UniProt REST(`rest.uniprot.org`)·Rhea REST(`www.rhea-db.org`)에 HTTPS GET만 보내고 키·로그인이 필요 없다(규칙은 `docs/security.md`). 2026-10-09 실측: 요청 22건, 약 2분, 받은 바이트 약 24 MB, 행 M-CSA 1,003·UniProt 1,622·Rhea 18,611.
- 쓸 폴더: `--reference-dir`, 없으면 `MW_REACTION_REFERENCE_DIR`, 그것도 없으면 `<저장소>/.deps/reaction_reference`(상대 값은 저장소 루트 기준). 서버도 같은 규칙으로 읽으므로 변수를 쓰면 서버와 명령에 같은 값을 준다. M15 폴더(`.deps/reference`)와 따로이며, 다른 스냅샷 가족의 `active.json`이 있는 폴더는 거절한다.
- 가져올 accession: M-CSA에 나오는 accession 전부 + 로컬 M15 활성 세트의 `status: ok` kinase accession(`MW_REFERENCE_DIR` 또는 `<저장소>/.deps/reference`에서 읽기만, `--no-kinases`면 뺌, 세트가 없거나 읽을 수 없으면 `absent`로 기록하고 계속) + `--accession`·`--accessions-file`로 직접 지정한 것. 직접 지정은 다음 가져오기에 이어지지 않으므로 필요하면 매번 준다(이전 세트에만 있던 것은 출력과 매니페스트 `dropped_previous_user_named`에 남는다).
- 확인 화면(허용 호스트, 출처, 예상 accession 수, 상한, 쓸 폴더, 이전 활성 세트)이 나오고 `y`를 입력해야 계속한다. `--yes`는 이 확인을 생략한다. 요청마다 진행 줄이 나오고, 끝나면 폴더·세트 해시·가져온 시각·출처별 행 수·건너뛴 accession과 이유·저장하지 않은 동형체 위치 부위 수·요청 수가 나온다.
- 종료 코드 0은 설치 완료, 1은 거절(이유는 표준 오류, `active.json`·이전 세트는 그대로), 2는 인자 오류다. 직접 지정한 accession을 하나라도 받지 못하면 명령 전체를 거절하고(대체 없음) 받지 못한 파생 accession이 50개(`MAX_SKIPPED`)를 넘어도 설치하지 않는다.
- 다시 가져오기: 실행할 때마다 새 세트 폴더를 쓰고 `active.json`을 rename 한 번으로 바꾼다(이전 세트는 지우지 않음, 같은 내용이어도 `imported_at` 때문에 새 세트 해시). 서버가 도는 중에 바꿔도 되며(호출마다 세트를 한 번 고정) 서버 재시작은 필요 없다. 이전 세트로 만든 결과는 "이전 스냅샷 기준"으로 보인다.
- git worktree에서 돌리지 않는다: worktree에는 `.deps`가 없어 기본 폴더가 worktree 안에 생기고 M15 kinase 목록이 `absent`가 된다. 주 체크아웃에서 실행하거나 두 폴더를 절대 경로로 준다(`--reference-dir`, `MW_REFERENCE_DIR`).
- 가져오지 않으면 `/capabilities`의 `reaction_knowledge`와 지식 탭 "효소 반응 지식" 영역이 사용할 수 없음(`not_installed`)으로 표시되고(저장된 결과는 이벤트만으로 계속 열림), M20 촉매 칸은 결과가 없어 "검사하지 않음"이며, 나머지 기능은 정상이다.

### M27 키나아제 전례 참조 스냅샷 (선택, 로컬 kbase에서 복사)

```bash
.venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로>
```

- 네트워크를 쓰지 않는다. `--from`에는 로컬 `kbase_kinase` 체크아웃의 저장소 루트를 준다(읽기만, 상대 경로는 현재 폴더 기준, 하위 폴더나 `.git` 없는 복사본은 거절). 그 `dist/moves.jsonl`·`dist/moves_flagged.jsonl`·`dist/references.jsonl`과 `ref/manifest.json`의 가장 최근 날짜 pubmed 서지 스냅샷 하나를 바이트 그대로 복사하고, 커밋·`dirty`는 읽기 전용 `git -C`로 읽는다(규칙은 `docs/security.md`). 지식 탭 "키나아제 전례" 영역의 "사용할 수 없음" 안내에 나오는 명령도 이 줄과 같다. 2026-10-10 구현 중 스모크 측정(증거 파일 없음): 약 0.45초, 행 891·885·555, 서지 252.
- 쓸 폴더: `--dest`, 없으면 `MW_PRECEDENT_REFERENCE_DIR`, 그것도 없으면 `<저장소>/.deps/precedent_reference`(상대 값은 저장소 루트 기준). 서버도 같은 규칙으로 읽으므로 변수를 쓰면 서버와 명령에 같은 값을 준다. M15(`.deps/reference`)·M26(`.deps/reaction_reference`) 폴더와 따로이며, 다른 스냅샷 가족의 `active.json`이 있는 폴더는 거절한다.
- 검사: kbase `dist/manifest.json`의 세 버전 값(`schema_version`·`effect_rules_version`·`vocab_version`)이 `KBASE_PINS`와 정확히 같고, 세 파일과 서지 파일의 SHA-256·바이트·행 수가 kbase 매니페스트와 같고, 모든 레코드의 형식(21개 최상위 키, `review_status: "unreviewed"`, 닫힌 값·어휘)과 `content_hash` 재계산이 맞을 때만 설치한다. 하나라도 다르면 아무것도 바꾸지 않는다. kbase를 갱신해 세 버전 값이 달라지면 거절 종류 `pins`이고, 고치려면 사용자 결정으로 상수를 바꿔야 한다. kbase의 `dist/`·`ref/pubmed/`에 커밋되지 않은 변경이 있으면 거절하지 않고 `dirty: true`로 기록한다.
- 확인 화면(네트워크 사용 안 함, kbase 경로·HEAD·dist 커밋과 날짜·`dirty`·`kb_version`, 가져올 파일과 바이트·행 수, 쓸 폴더)이 나오고 `y`를 입력해야 계속한다. `--yes`는 이 확인을 생략한다. 끝나면 폴더·세트 해시·가져온 시각·파일별 행 수·`verification`(레코드 해시 재계산 일치 수)·`dirty`가 나온다.
- 종료 코드 0은 설치 완료, 1은 거절(거절 종류와 이유는 표준 오류, `active.json`·이전 세트는 그대로), 2는 인자 오류다.
- 다시 가져오기: 실행할 때마다 새 세트 폴더 `sets/<set_hash>/`를 쓰고 `active.json`을 rename 한 번으로 바꾼다(이전 세트는 지우지 않음). 매니페스트에 가져온 시각(초 단위)이 들어가므로 같은 내용이어도 새 세트 해시이고, 같은 초에 같은 내용을 다시 가져오면 `set_exists`로 거절된다. 서버가 도는 중에 바꿔도 되며(호출마다 세트를 한 번 고정) 서버 재시작은 필요 없다. 이전 세트로 만든 결과는 "이전 스냅샷 기준"으로 보이고 다시 계산하지 않는다.
- 확인: 설치 뒤 지식·보고서 탭 "키나아제 전례" 영역의 스냅샷 블록(세트 해시 앞 12자, kbase 커밋, 파일별 행 수, 서지 스냅샷)이나 `GET /precedent_reference/status`(`installed: true`), `/capabilities`의 `methods.kinase_precedents`(`available: true`)로 본다.
- git worktree에서 돌리지 않는다: worktree에는 `.deps`가 없어 기본 폴더가 worktree 안에 생기고, 주 체크아웃 기준 상대 경로 `../kbase_kinase`가 맞지 않는다. 주 체크아웃에서 실행하거나 두 경로를 절대 경로로 준다(`--from`, `--dest`).
- 가져오지 않으면 `/capabilities`의 `kinase_precedents`와 지식 탭 "키나아제 전례" 영역이 사용할 수 없음(`not_installed`)으로 표시되고(저장된 결과는 이벤트만으로 계속 열림, "사용 중 스냅샷 없음"), 나머지 기능은 정상이다.
- 결과 객체는 실제 kbase 인용문을 run 이벤트에 저장하므로 run 폴더와 보고서 다운로드는 공유하지 않는 자료다(KT1 "외부 공개 전 확인").

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
| `MW_REACTION_REFERENCE_DIR` | 백엔드 환경변수 | M26 반응 참조 폴더. 기본 `<저장소>/.deps/reaction_reference`, 상대 값은 저장소 루트 기준. 가져오기 명령도 `--reference-dir`가 없으면 이 변수를 쓴다. M26 수락 QA는 단계마다 격리 폴더를 주고, M13–M25 실행기는 이 변수를 넘기지 않아 기본 폴더를 읽는다(아래 M26 수락 QA) |
| `MW_PRECEDENT_REFERENCE_DIR` | 백엔드 환경변수 | M27 전례 참조 폴더. 기본 `<저장소>/.deps/precedent_reference`, 상대 값은 저장소 루트 기준. 가져오기 명령도 `--dest`가 없으면 이 변수를 쓴다. M27 수락 QA는 단계마다 격리 폴더를 주고, M13–M26 실행기는 이 변수를 넘기지 않아 기본 폴더를 읽는다(아래 M27 수락 QA) |
| `MW_KBASE_REF` | 테스트 환경변수 | `backend/tests/test_klifs_numbering.py`의 실제 kbase 스냅샷 테스트 2개가 읽는 `ref/` 폴더. 기본 `<저장소>/../kbase_kinase/ref`. 제품 코드는 쓰지 않는다 |
| `OPENROUTER_API_KEY` | 루트 `.env`(권한 0600) 또는 환경변수 | 온라인 뷰어 해석, M3 결정, M24 과학 전송(과학 전송 동의가 켜진 run에서 사람이 승인한 전송, M25 루프 전송 포함)에만 쓴다. 없으면 이 기능들만 사용할 수 없고(과학 전송은 `missing_credential` 거절, `methods.jev_choice`·`methods.jev_loop`은 키를 보지 않음, 루프의 계산은 키 없이 됨), 나머지는 정상이다 |
| `config/default.yaml` | 저장소 | run 기본 예산(1800초, 비싼 계산 8회, 토큰 120,000, USD 2.00), 재시도·루프 가드, egress 기본 모드(`local_only`), Jev 엔드포인트·모델 pin. 새 run에만 적용되고, 이미 만든 run의 한도는 그 run의 `run_started` 이벤트가 기준이다 |
| `config/tools.yaml` | 저장소 | 도구 명세(허용 입력 종류, 파라미터 범위, 비용 등급). 여기 있다고 모두 노출되지는 않는다 |
| `config/pipelines/inspect_complex.yaml` | 저장소 | 고정 inspect_complex 파이프라인 정의 |
| `NEXT_TELEMETRY_DISABLED=1` | npm 스크립트에 고정 | Next.js 텔레메트리 차단 |

## 검증 명령

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py scripts/test_m14_offscreen_acceptance.py scripts/test_import_reference_snapshots.py scripts/test_m15_offscreen_acceptance.py scripts/test_measure_klifs_numbering.py scripts/test_m16_offscreen_acceptance.py scripts/test_m17_offscreen_acceptance.py scripts/test_m18_offscreen_acceptance.py scripts/test_m19_offscreen_acceptance.py scripts/test_setup_qvina.py scripts/test_setup_docking_worker.py scripts/test_m20_offscreen_acceptance.py scripts/test_m21_offscreen_acceptance.py scripts/test_m22_offscreen_acceptance.py scripts/test_m23_offscreen_acceptance.py scripts/test_m24_offscreen_acceptance.py scripts/test_m25_offscreen_acceptance.py scripts/test_import_reaction_references.py scripts/test_m26_offscreen_acceptance.py scripts/test_import_precedent_snapshots.py scripts/test_m27_offscreen_acceptance.py scripts/test_m28_offscreen_acceptance.py scripts/test_m28_branch_a.py scripts/test_m28_branch_b.py scripts/test_m28_branch_c.py -q
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
node --check frontend/tests/offscreen/jev-loop-flow.cjs
node --check frontend/tests/offscreen/reaction-knowledge-flow.cjs
node --check frontend/tests/offscreen/kinase-precedents-flow.cjs
node --check frontend/tests/offscreen/endtoend-a-flow.cjs
node --check frontend/tests/offscreen/endtoend-b-flow.cjs
node --check frontend/tests/offscreen/endtoend-c-flow.cjs
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

- 게이트 기록은 위에 적은 하네스 말고도 `frontend/tests/offscreen/*.cjs` 전부를 `node --check`했다(M27 게이트 `docs/qa/m27-precedents-20261010/gate.txt`의 `node-check: files=31`). M28 종단 하네스 셋을 더하면 34개다.
- `scripts/test_m28_offscreen_acceptance.py`(M28 종단 실행기·`m28_common.py`·역추적 감사·고정 문장 내보내기를 합성 입력으로: 사례·`acceptance` 판정, 정의 항목 사슬, live 결과 판정, 실호출 대장 규칙, 증거 유출 검사, 감사 검사, 실행기·공용·감사 모듈의 `mw` 미import)와 `scripts/test_m28_branch_a.py`·`test_m28_branch_b.py`·`test_m28_branch_c.py`(분기 모듈의 독립 기대값·사례 판정)는 서비스를 띄우지 않으며 게이트 명령과 Stop 훅 나머지 그룹에 있다(`SCRIPT_TESTS`에 손으로 넣음). 고정 문장 내보내기 시험은 `scripts/m28_export_fixed_sentences.py`를 `PYTHONPATH=backend` 하위 프로세스로 실행한다. 분기 시험은 실제 입력 파일을 읽고 없으면 skip이 아니라 실패한다: `test_m28_branch_a.py`는 저장소 옆 `../kbase_kinase/dist`와 `.deps/reaction_qa/import2`(보관된 M26 실제 세트), `test_m28_branch_c.py`는 `.deps/reaction_qa/import2`를 시험 파일이 있는 저장소 루트 기준으로 찾으므로 그 자료가 있는 주 체크아웃에서 돈다(그 위치에 자료가 없는 git worktree나 새로 설치한 폴더에서는 실패).
- `scripts/test_import_reference_snapshots.py`(가져오기: 해시 불일치 시 무변경, 원자적 교체, 매니페스트 필드, 네트워크 없음), `scripts/test_m15_offscreen_acceptance.py`(M15 실행기 판정), `scripts/test_measure_klifs_numbering.py`(측정 분류), `scripts/test_m16_offscreen_acceptance.py`(M16 실행기 판정), `scripts/test_m17_offscreen_acceptance.py`(M17 실행기 판정)는 서비스를 띄우지 않으며 Stop 훅 나머지 그룹(나머지 백엔드·실행기)에 들어 있다. 백엔드 M15 테스트는 대부분 커밋된 fixture 세트(`backend/tests/reference_fixture_set.py`)를 임시 참조 폴더에 만들어 쓰므로 `.deps/reference`가 없어도 돈다. 예외로 `backend/tests/test_klifs_numbering.py`의 실제 스냅샷 테스트 2개는 kbase 스냅샷을 직접 읽는다. 경로는 `<저장소>/../kbase_kinase/ref`이고 환경변수 `MW_KBASE_REF`로 바꿀 수 있다(git worktree나 다른 위치의 체크아웃). 경로가 없으면 skip하므로 게이트의 "skip 0"을 맞추려면 kbase 체크아웃을 옆에 두거나 `MW_KBASE_REF`를 준다.
- `scripts/test_m14_offscreen_acceptance.py`는 M14 실행기의 사례 판정·`acceptance` 판정을 보는 단위 테스트다(서비스를 띄우지 않음, Stop 훅 나머지 그룹).
- `scripts/test_m19_offscreen_acceptance.py`(M19 실행기 판정, 서비스 없음)는 게이트 명령과 Stop 훅 나머지 그룹에 있다.
- `scripts/test_m20_offscreen_acceptance.py`(M20 실행기 판정, 서비스 없음)는 게이트 명령과 Stop 훅 나머지 그룹에 있다(M23 뒤 그룹을 나눌 때 넣음). 백엔드 M20 테스트 네 파일(`test_mutation_*.py`)은 실제 엔진이 필요 없고 나머지 그룹에서 돈다.
- `scripts/test_m21_offscreen_acceptance.py`(M21 실행기 판정, 서비스 없음)도 게이트 명령과 Stop 훅 나머지 그룹에 있다. 백엔드 M21 테스트 일곱 파일(`test_mutation_model_*.py`)은 실제 OpenMM·PDBFixer 작업 모듈과 qvina 도킹을 돌리며 `test_openmm.py`와 함께 한 그룹에서 돈다(프로젝트 `.venv`의 PDBFixer, `.deps/docking`·`.deps/qvina`가 없으면 skip이 아니라 실패).
- `scripts/test_m22_offscreen_acceptance.py`(M22 실행기 판정, 서비스 없음, 39개)도 게이트 명령과 Stop 훅 나머지 그룹에 있다. 백엔드 M22 테스트 일곱 파일(`test_ligand_ga_*.py`)은 실제 qvina·RDKit 작업 모듈과 실제 M17 작업으로 만든 후보 집합을 쓰며 세 그룹에서 돈다(`test_ligand_ga_jobs.py`, `test_ligand_ga_worker.py`, 나머지 다섯 파일은 M19 일괄 다섯 파일과 함께. `.deps/docking`·`.deps/qvina`·`.deps/prolif`가 없으면 skip이 아니라 실패).
- `scripts/test_m23_offscreen_acceptance.py`(M23 실행기 판정, 서비스 없음, 51개)도 게이트 명령과 Stop 훅 나머지 그룹에 있다. 백엔드 M23 테스트(`test_sequence_ga_*.py`·`test_sequence_model_*.py`, 실제 OpenMM·PDBFixer·qvina·RDKit 작업 모듈과 실제 M20 후보 집합)는 다섯 그룹에서 돈다(`test_sequence_ga_jobs.py`는 테스트 단위로 두 그룹에 나눔, `test_sequence_ga_api.py`, `test_sequence_ga_reports.py`, 작업 모듈·모델 작업 모듈과 작은 네 파일).
- `scripts/test_m24_offscreen_acceptance.py`(M24 실행기 판정·대장·`--finalize`, 서비스 없음)도 게이트 명령과 Stop 훅 나머지 그룹에 있다. 백엔드 M24 테스트(`test_jev_*.py`)는 나머지 그룹에서 돌며, 투영·도구 테스트는 실제 M17 작업(`.deps/prolif/venv-locked`)으로 만든 후보 집합을 쓰므로 그 환경이 없으면 skip이 아니라 실패한다. 외부 요청은 모두 가짜 transport다.
- `scripts/test_m25_offscreen_acceptance.py`(M25 실행기 계획·예산·대장·`--finalize`·`--rehearse`, 서비스 없음, 99개)도 게이트 명령과 Stop 훅 나머지 그룹에 있다. 백엔드 M25 테스트 11개 파일(`test_jev_loop_*.py`·`test_jev_loops_*.py`, 689개)은 세 곳에서 돈다: 무거운 다섯 파일(`test_jev_loops_read.py`·`test_jev_loop_sends.py`·`test_jev_loop_tool.py`·`test_jev_loop_choice.py`·`test_jev_loops_api.py`)이 한 그룹, `test_jev_loops_compute.py`가 한 그룹, 나머지 다섯 파일은 나머지 그룹이다. 계산 테스트는 실제 qvina·M21 OpenMM·PDBFixer 작업과 실제 M17 작업으로 만든 후보 집합을 쓰므로 `.deps/docking`·`.deps/qvina`·`.deps/prolif`가 없으면 skip이 아니라 실패한다. 외부 요청은 모두 가짜 transport다.
- `scripts/test_import_reaction_references.py`(M26 가져오기 명령: 전송 함수를 주입한 가짜 전송과 `127.0.0.1` 로컬 서버만, `validate_url`·리다이렉트 거부·크기·제한 시간·재시도, CLI에 호스트·스킴 우회가 없음, 형식 오류·직접 지정 실패·건너뜀 한도에서 아무것도 쓰지 않음, 원자적 설치, 결정성, 실서버 요청 0)와 `scripts/test_m26_offscreen_acceptance.py`(M26 실행기 판정, 서비스 없음)는 게이트 명령과 Stop 훅 나머지 그룹에 있다(`SCRIPT_TESTS`에 손으로 넣음). 백엔드 M26 테스트(`test_reaction_*.py`)는 합성 세트(`backend/tests/reaction_fixture.py`)를 임시 폴더에 만들어 쓰므로 `.deps/reaction_reference`가 없어도 돌고, M20 v2·M24 J6 변형 테스트와 함께 나머지 그룹에 들어간다.
- `scripts/test_import_precedent_snapshots.py`(M27 가져오기 명령, 97개: 합성 kbase 흉내 폴더로 정상 설치, 핀·파일 바이트·SHA-256·줄 수·레코드 해시·레코드 형식 위반 각각의 거절과 무변경, 중간 실패에서 `active.json`·이전 세트 불변, `dirty` 기록, pubmed 일부 PMID 누락 정상, 같은 입력 두 번째 설치의 파일 SHA-256 동일, 서버 고정이 이 명령이 만든 세트를 받아들임, 읽기 전용 git 세 명령, CLI 옵션이 정확히 `--from`·`--dest`·`--yes`이고 호스트·URL 옵션 없음, 소켓·네트워크 모듈을 막은 자식 프로세스에서 동작)와 `scripts/test_m27_offscreen_acceptance.py`(M27 실행기 판정·유출 검사, 서비스 없음, 55개)는 게이트 명령과 Stop 훅 나머지 그룹에 있다(`SCRIPT_TESTS`에 손으로 넣음). 백엔드 M27 테스트 일곱 파일(`test_precedent_constants.py`·`test_precedent_snapshots.py`·`test_kinase_precedents.py`·`test_kinase_precedents_tool.py`·`test_kinase_precedents_api.py`·`test_kinase_precedents_reports.py`·`test_kinase_precedents_ast.py`, 557개)은 합성 세트(`backend/tests/precedent_fixture.py`)를 임시 폴더에 만들어 쓰므로 `.deps/precedent_reference`가 없어도 돌고, 이름 있는 그룹 하나에서 돈다.
- `scripts/test_m18_offscreen_acceptance.py`(M18 실행기 판정), `scripts/test_setup_qvina.py`·`scripts/test_setup_docking_worker.py`(잠금·플랫폼 불일치 거부, 실패 때 만든 것 삭제, 설치 기록 내용. 실제 설치는 하지 않음)는 서비스를 띄우지 않는다. 이 세 파일은 게이트 명령과 Stop 훅 나머지 그룹에 있다.
- `scripts/test_m13_offscreen_acceptance.py`는 M13 실행기의 하위 대장 판정, `acceptance` 판정, 빌드 출처 확인을 보는 단위 테스트다(서비스를 띄우지 않음). Stop 훅의 나머지 pytest 그룹에 들어 있다.
- git worktree에서 백엔드 테스트나 서비스를 돌릴 때는 `PYTHONPATH=<worktree>/backend`를 준다. `.venv`의 editable 설치가 주 체크아웃의 `backend/`를 가리키므로, 주지 않으면 worktree의 `mw`가 아니라 주 체크아웃의 `mw`를 import한다.
- 과학 네이티브 테스트(FreeSASA, OpenMM, M11 ProLIF, M12 fpocket, M17 RDKit 리간드 작업, M18 qvina 도킹 작업, M19 일괄 도킹 작업, M22 GA 작업, M23 서열 GA 작업과 모델링 프로그램)는 해당 엔진이 설치되어 있어야 의미가 있다. M11·M17 테스트는 `.deps/prolif/venv-locked`, M12 테스트는 `.deps/fpocket/env`, M18·M19·M22·M23 테스트는 `.deps/docking/venv-locked`와 `.deps/qvina/env`(M23은 프로젝트 `.venv`의 OpenMM·PDBFixer도)가 필요하며(M19 일괄·M22 GA 테스트 일부는 M17 작업 환경도 씀), 없으면 skip이 아니라 실패한다.
- Claude Code와 Codex의 Stop 훅(`.codex/hooks/stop.py`)은 대화 턴이 끝날 때 ruff(45초 제한)를 돌린 뒤, pytest 열여덟 그룹을 모두 동시에 실행한다(실행기 스레드 수 = 그룹 수 `len(CHECKS) - 1`, `CHECKS` 19개). 그룹은 `PYTEST_GROUPS` 열일곱과 나머지 그룹이다: (1) `test_chemical_interactions.py`, (2) `test_m11_job_api.py`, (3) M18 도킹 다섯 파일(`test_docking_inputs.py`·`_worker`·`_jobs`·`_api`·`_reports`)과 `test_pocket_jobs.py`, (4) `test_docking_batch_worker.py`·`test_docking_batch_jobs.py`와 `test_pockets.py`·`test_pocket_reports.py`·`test_pocket_output.py`, (5) M19 일괄 나머지 다섯 파일(`test_docking_batch_inputs.py`·`_bundle`·`_budget`·`_api`·`_reports`)과 M22 다섯 파일(`test_ligand_ga_bundle.py`·`_inputs`·`_budget`·`_api`·`_reports`), (6) `test_ligand_ga_jobs.py`, (7) `test_ligand_ga_worker.py`, (8) `test_sequence_ga_jobs.py`의 가장 긴 두 테스트(`SEQUENCE_GA_JOBS_LONG`), (9) 같은 파일의 나머지 열두 테스트(`SEQUENCE_GA_JOBS_OTHER`), (10) `test_sequence_ga_api.py`, (11) `test_sequence_ga_reports.py`, (12) `test_sequence_ga_worker.py`·`test_sequence_model_worker.py`와 작은 네 파일(`test_sequence_ga_inputs.py`·`_budget`·`_bundle`, `test_sequence_model_bundle.py`), (13) M21 일곱 파일(`test_mutation_model_*.py`)과 `test_openmm.py`, (14) M25 무거운 다섯 파일(`test_jev_loops_read.py`·`test_jev_loop_sends.py`·`test_jev_loop_tool.py`·`test_jev_loop_choice.py`·`test_jev_loops_api.py`), (15) `test_jev_loops_compute.py`, (16) M27 백엔드 일곱 파일(`test_precedent_constants.py`·`test_precedent_snapshots.py`·`test_kinase_precedents.py`·`test_kinase_precedents_tool.py`·`test_kinase_precedents_api.py`·`test_kinase_precedents_reports.py`·`test_kinase_precedents_ast.py`), (17) `test_analysis_workflows.py`·`test_jev_loop_reports.py`, (18) 나머지: `backend/tests`에서 앞 그룹에 적힌 파일을 `--ignore`로 뺀 것(목록은 `PYTEST_GROUPS`에서 자동으로 만듦, M26 백엔드 테스트와 M28 T3의 M20 보고서 시험 포함)과 게이트의 실행기 테스트 28개 파일(`SCRIPT_TESTS`, M20–M27 실행기 단위 테스트, M26·M27 가져오기 명령 테스트, M28 종단 실행기·분기 단위 테스트 넷 포함). 새 백엔드 테스트 파일은 저절로 나머지 그룹에 들어가고, 새 실행기 테스트 파일은 `SCRIPT_TESTS`에 넣어야 `scripts/test_codex_hooks.py`가 통과한다. 그룹마다 480초 제한이 있고, 전체 제한은 600초다(`.claude/settings.json`·`.codex/hooks.json`). 그룹 합집합은 게이트의 백엔드 + 스크립트 pytest와 같다(M23 병합 뒤 2026-10-05 `--collect-only` 노드 id 비교로 확인했고 차집합·중복 0, M24 고정 `5218130`에서는 열네 그룹 합계 3,712개, M25 고정 `4360598`에서는 열여섯 그룹 합계 4,500개·가장 긴 그룹 398초(나머지 그룹)·M25 두 그룹 175초·224초, `docs/qa/m25-jev-loop-20261007/gate-backend.txt`). 그룹은 M23 병합 뒤 다른 pytest 없이 파일별로 8개씩 병렬로 잰 시간(백엔드 80개 파일과 실행기 18개 파일 한 묶음, 벽시계 합 4,245초·CPU 합 6,095초)으로 나눴다. 이 측정에서 `test_sequence_ga_jobs.py`가 혼자 536초라 테스트 단위로 둘로 나눴다(모듈 범위 `base` 준비는 0.2초라 두 그룹이 각각 해도 거의 늘지 않는다). 같은 세션 world(실제 GA 작업 넷, 약 230초)를 공유하는 `test_sequence_ga_api.py`·`test_sequence_ga_reports.py`는 한 그룹이면 약 390초로 가늠되어 따로 두고 world를 그룹마다 만든다. M21 읽기·보고서 네 파일은 world를 공유하므로 한 그룹에 둔다. 훅 진입점(`echo '{}' | python3 .codex/hooks/stop.py`)을 다른 pytest 없이 두 번 끝까지 돌렸을 때(2026-10-05) 둘 다 통과(출력 없음)였고 총 342초·342초였다. ruff는 1초 안에 끝났고, 그룹은 약 256–340초였다(가장 긴 그룹은 `test_chemical_interactions.py` 340초). 같은 열네 그룹을 동시에 따로 잰 CPU 시간(사용자+시스템, 기다린 자식 프로세스 포함)은 그룹마다 295–725초, 합 약 5,770초다(자식 프로세스·스레드를 쓰는 그룹은 CPU가 벽시계보다 크다). 다른 ProtView 세션의 Stop 훅이나 수락 QA가 동시에 돌면 그룹 시간이 늘 수 있다. 테스트가 늘어 한 그룹이 480초에 가까워지면 다시 나누고 `scripts/test_codex_hooks.py`의 그룹 수 기대를 함께 고친다(M25에서 루프 테스트가 나머지 그룹을 480초 넘게 해 두 그룹을 더했다, `b0d0f96`·`da37288`). M26은 그룹을 더하지 않았다: 소스 고정 `3fcac53`에서 나머지 그룹을 다른 부하 없이 단독으로 돌리면 3,553개 416.8초(제한 480초, 여유 약 63초)였으므로 **다음에 테스트를 더하면 그룹을 나눈다**. 같은 게이트에서 열여섯 그룹을 제한 없이 한 번에 돌렸을 때(Stop 훅 pytest와 겹쳐 부하 두 배, 그룹 시간 부풀려짐) 열네 그룹이 통과했고 둘은 부하에 흔들리는 프로세스 시험 `test_pocket_jobs.py::test_running_engine_is_stopped_with_its_process_group[output_files]`·`test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`이 실패했으며 단독 재실행에서 7 passed였다(`docs/qa/m26-reaction-20261008/gate.txt`). M27은 그룹 둘을 더했다: M27 전 나머지 그룹 단독 3,554개 408.77초(여유 약 71초, 착수 확인)에 M27 테스트가 더해지자, 먼저 M27 백엔드 일곱 파일(557개)을 이름 있는 그룹으로 나눴고(`7e33951`) 그래도 모든 그룹을 동시에 시작하면 나머지 그룹이 3,706개 476초(단독 423.9초, 제한 480초)라 가장 무거운 두 파일 `test_analysis_workflows.py`·`test_jev_loop_reports.py`(129개, 나머지 그룹과 둘만 함께 돌렸을 때 197초, 열여덟 그룹 전부 함께는 231.6초)를 또 한 그룹으로 나눴다(`b414728`, `scripts/test_codex_hooks.py`의 기대 `CHECKS` 19). 소스 고정 `b414728` 게이트에서 열여덟 그룹을 한꺼번에 제한 없이 시작했을 때 모두 exit 0, 합계 6,037 passed, 전체 357.5초였고 그룹마다 42.3–357.5초(M27 그룹 557개 42.3초, 둘째 새 그룹 231.6초, 나머지 그룹 3,577개 323.2초)였다(`docs/qa/m27-precedents-20261010/gate.txt`). 이 실행에서는 부하에 흔들리는 서열 GA SIGTERM 프로세스 시험도 통과했다(다른 작업과 겹치면 흔들리는 알려진 현상, 단독 3 passed 143.8초). M28은 그룹을 더하지 않았다(`CHECKS` 19 그대로): 새 실행기·분기 단위 테스트 넷은 `SCRIPT_TESTS`로, M20 보고서 시험은 저절로 나머지 그룹에 들어갔다. M28 착수 확인에서 열여덟 그룹을 한꺼번에 돌렸을 때(M28 시험을 더하기 전) 가장 느린 그룹 373.6초, 나머지 그룹 370.7초로 여유는 약 106–109초였다(`docs/qa/m28-final-20261011/preflight.md` (j)). 동시 실행에서 간헐 실패하던 시험 넷(프로세스 타이밍·psutil 셋과 부분 문자열 겹침 하나)은 M28 T2가 시험 쪽에서 고쳤다(제품 코드 변경 없음, `docs/engineering-notes.md`의 M28 함정). 이전 나눔: M18 작업 중 도킹 테스트를 따로 나눴고(`306971b`), M19에서 일괄 테스트를 따로 나눴다(`b8fafd5`, 그때 다섯 그룹). 그 뒤 M21–M23 테스트가 모두 나머지 그룹에 들어가 이 그룹이 M21 고정 게이트 602초, M22 1324초, M23 2432초(2,538개, `docs/qa/m23-sequence-ga-20261005/gate.txt`)로 늘어 훅이 매 턴 시간 초과를 보고했고, 그동안 게이트는 그룹별 개별 실행으로 판단했다. ruff가 실패하면 pytest는 돌리지 않는다. 실패하면 턴 종료를 한 번 막고 오류를 돌려준다. 그 뒤 다시 종료할 때(`stop_hook_active`)는 무한 반복을 막으려고 통과시키므로, 훅을 지나갔다고 게이트를 통과한 것은 아니다.

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
- `--out` 폴더에 실행 전 다른 파일(게이트 기록 등)을 써 둘 때는 절대 경로를 먼저 `<repo>`·`<home>`으로 가린다. 증거 내보내기 단계가 가리지 않은 경로를 누출로 보고 실패한다(재고정 시도 1).
- 2026-09-30 증거: 첫 고정 `c1d824d`는 `docs/qa/m15-numbering-20260930/`(M14·M13 회귀 포함), 최종 고정 `93c4fb1`은 `docs/qa/m15-numbering-20260930/refreeze-93c4fb1/`(게이트, M15 수락, M14 회귀).
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:numbering -- --mode <empty|main|stale> --artifacts <디렉터리>`(`main`·`stale`은 `--set-hash`, `stale`은 `--runs <runA,runB> --previous-set-hash`도 필요). 전체 순서와 참조 폴더 변경은 실행기에 있다.
- 회귀: M14 실행기(`--out docs/qa/m15-numbering-<YYYYMMDD>/m14-regression`)와 M13 실행기 모든 phase(`--phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m15-numbering-<YYYYMMDD>/m13-regression`)를 각각 새 `--root`·`--artifacts`로 돌린다. 큰 텍스트 증거는 결정 0020대로 옮긴다.

### M16 참조 주석 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`, `MW_REFERENCE_DIR=<root>/reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. M15 실행기의 서비스·빌드·가져오기·증거 내보내기 함수를 그대로 쓴다.

```bash
.venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/<이름> --kbase <home>/Projects/kbase_kinase \
    --out docs/qa/m16-annotations-<YYYYMMDD>/acceptance
```

- 순서: `reference-import`(가져오기 명령을 하위 프로세스로 `--dest <root>/reference`. 실제 `.deps/reference`는 건드리지 않음) → `annotation-main`(1MQ4 → 전처리 → ADP 기하 접촉 → 지식 탭에서 전처리 구조 대응(PDB ID 1MQ4 확인) → 패널 주석 만들기·켜기 → Mol* readback을 착수 확인 oracle(`docs/qa/m16-annotations-20261001/preflight.txt`)과 대조 → 범례 켠·끈 `viewer_scene@2`/`viewer_figure@2`, 주석 끈 `viewer_scene@1`, PNG 픽셀, `@2` 복원, M8 막힘, 보고서·다운로드, 접촉 없는 주석, 포켓·비교 배타, 읽기 실패와 다시 읽기, run 전환·늦은 응답) → `annotation-minimized`(1UBQ OpenMM 최소화 소스: 이유만). 대장의 `acceptance`는 모든 단계가 이번 실행에서 돌고 가져오기가 성공했으며 19사례 모두 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 프로세스·리스너 없음일 때만 true다.
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--kbase` 기본값(`<저장소>/../kbase_kinase`)은 git worktree에서 틀리므로 절대 경로를 준다(2026-10-01 실행도 절대 경로).
- 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다(2026-10-01: 시도 1 `--root runs/m16-acceptance-20261001 --artifacts .../m16-acceptance/final --out .../acceptance`, 시도 2 `--root runs/m16-acceptance-20261001-attempt2 --artifacts .../m16-acceptance/attempt2 --out .../acceptance-attempt2`).
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:annotations -- --mode <main|minimized> --artifacts <디렉터리>`(`main`은 `--set-hash <사용 중 참조 세트 해시>`도 필요, `--url` 기본 `http://127.0.0.1:3000`). 전체 순서와 참조 폴더 준비는 실행기에 있다.
- 회귀: M15 실행기(`--kbase <절대 경로> --out docs/qa/m16-annotations-<YYYYMMDD>/m15-regression`), M14 실행기(`--out .../m14-regression`), M13 실행기 모든 phase(`--phases workflows,unavailable,regressions,m11,m12,ledger --out .../m13-regression`)를 각각 새 `--root`·`--artifacts`로 돌린다(2026-10-01: `--root runs/m16-m1X-regression-20261001`, `--artifacts frontend/tests/offscreen/artifacts/m1X-acceptance/m16-regression`). 큰 텍스트 증거는 결정 0020대로 옮긴다.
- 2026-10-01 증거: `docs/qa/m16-annotations-20261001/`(게이트 `gate.txt`와 재고정 절, `acceptance/` 시도 1 실패, `acceptance-attempt2/` 채택, 회귀 3개).

### M17 리간드 후보 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`, `MW_REFERENCE_DIR=<root>/reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. 코드 루트의 `.deps/prolif/venv-locked`(RDKit 2026.03.6)가 있어야 한다. 없으면 "사용할 수 없음"이 아니라 수락 실패다. M13 실행기(빌드 도장·환경·경로 가리기·포트)와 M15 실행기(서비스·빌드)를 그대로 쓴다. 참조 스냅샷은 필요 없어 `--kbase`가 없다.

```bash
.venv/bin/python scripts/m17_offscreen_acceptance.py --root runs/m17-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/<이름> \
    --out docs/qa/m17-ligand-<YYYYMMDD>/acceptance
```

- 순서: 환경 확인 → `ligand-main`(구조 분석 탭 새 run + 1MQ4 → 리간드 탭 → 파일 선택으로 부모·block SDF·block SMILES와 규칙 입력 → 가져오기 → 점검 작업(승인 UI) → 번호 붙은 그림·원자 표(수소 명시판 SDF 번호) → 부위 거절·통과 → 생성 작업 → 후보 표를 T1 손 oracle과 대조 → 필터 경계·통과만 보기·정렬 → 보고서·지식 탭 목록·다운로드 → 후보 0개 → 잘못된 규칙 → 표시된 생성 사슬 목록으로 페이지 → 구조 분석 탭 유지 → run 전환·늦은 응답) → `ligand-unavailable`(`<root>/layout-worker-missing`의 `.deps` 없는 코드 복사본으로 백엔드를 다시 띄워 run 없음·`worker_missing` 이유만). 대장의 `acceptance`는 환경 확인 통과, 모든 단계가 이번 실행에서 돌고 21사례 모두 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스·8000/3000 리스너 없음일 때만 true다.
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:ligand -- --mode <main|unavailable> --artifacts <디렉터리>`(`--url` 기본 `http://127.0.0.1:3000`. `unavailable`은 새 runs 루트와 작업 환경 없는 백엔드가 필요). 전체 순서는 실행기에 있다.
- 회귀: M16 실행기(`--kbase <절대 경로> --out docs/qa/m17-ligand-<YYYYMMDD>/m16-regression`), M15 실행기(`--kbase <절대 경로> --out .../m15-regression`), M14 실행기(`--out .../m14-regression`), M13 실행기 모든 phase(`--phases workflows,unavailable,regressions,m11,m12,ledger --out .../m13-regression`)를 각각 새 `--root`·`--artifacts`로 돌린다(2026-10-01: `--root runs/m17-m1X-regression-20261001`, `--artifacts frontend/tests/offscreen/artifacts/m1X-acceptance/m17-regression`). 큰 텍스트 증거는 결정 0020대로 옮긴다.
- 2026-10-01 증거: `docs/qa/m17-ligand-20261001/`(`preflight.txt`, `gate.txt`, `acceptance/`, 회귀 4개). 수락은 `--root runs/m17-acceptance-20261001 --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/final`로 한 번 돌렸다.

### M18 리간드 도킹 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. 코드 루트의 `.deps/docking/venv-locked`, `.deps/qvina/env/bin/qvina2`, M17 작업 환경 `.deps/prolif/venv-locked`가 있어야 하고 백엔드가 `ligand_docking`·`ligand_candidates`를 사용 가능으로 보고해야 한다. 아니면 "사용할 수 없음"이 아니라 수락 실패다. M13·M15·M17 실행기의 함수(빌드 도장·환경·경로 가리기·포트, 서비스·빌드)를 그대로 쓴다. `--kbase`는 없다.

```bash
.venv/bin/python scripts/m18_offscreen_acceptance.py --root runs/m18-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/<이름> \
    --out docs/qa/m18-docking-<YYYYMMDD>/acceptance
```

- 순서: 환경 확인 → `docking-main`(구조 분석 탭 새 run + 1MQ4 → 리간드 탭 → 공개 수용체·3D SDF 가져오기 → 확인 누락·방식/상자 호환 → 자유 도킹(승인 UI, 실제 qvina) → 요약·모드 표·접촉 표·SDF 다운로드 바이트 → 보고서·지식 탭 목록·다운로드 → 합성 복합체 인스턴스 빼기·인스턴스 범위 상자 → 실제 M17 점검·생성 → 코어 고정 → 구조 분석 탭 유지 → run 전환·늦은 응답 → 평면·암시 수소 SDF·상자 한도 거부 → 물·아연·altloc 수용체 거부 목록 → qvina 실행 중 취소 → 금지어 없음) → 재현 검사(같은 입력·값·seed를 새 run 두 개에서 API로 다시 도킹해 점수와 전체 모드 SDF 바이트 비교) → `docking-unavailable`(`<root>/layout-worker-missing`의 `.deps` 없는 코드 복사본 백엔드로 run 없음·`worker_missing` 이유만). 모드 0개 사례는 입력을 위조하지 않고 "관찰하지 않음"으로 기록한다. 대장의 `acceptance`는 환경 확인 통과, 모든 단계가 이번 실행에서 돌고 모든 사례 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스·`qvina2`·8000/3000 리스너 없음일 때만 true다.
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:docking -- --mode <main|unavailable> --artifacts <디렉터리>`(`main`은 `--runs-dir`도 필요, `--url` 기본 `http://127.0.0.1:3000`. `unavailable`은 새 runs 루트와 작업 환경 없는 백엔드가 필요). 전체 순서는 실행기에 있다.
- 회귀: M17 실행기(`--out docs/qa/m18-docking-<YYYYMMDD>/m17-regression`), M16 실행기(`--kbase <절대 경로> --out .../m16-regression`), M15 실행기(`--kbase <절대 경로> --out .../m15-regression`), M14 실행기(`--out .../m14-regression`), M13 실행기 모든 phase(`--phases workflows,unavailable,regressions,m11,m12,ledger --out .../m13-regression`)를 각각 새 `--root`·`--artifacts`로 하나씩 돌린다(2026-10-02: `--root runs/m18-m1X-regression-20261002`, `--artifacts frontend/tests/offscreen/artifacts/m1X-acceptance/m18-regression`). 큰 텍스트 증거는 결정 0020대로 옮긴다.
- 2026-10-02 증거: `docs/qa/m18-docking-20261002/`(`preflight.txt`, `t2-install.txt`, `lock-inputs.json`, `gate.txt`, `summary.txt`, `acceptance/`, 회귀 5개). 수락은 `--root runs/m18-acceptance-20261002 --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/final`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m18-acceptance/gate/`(Git 제외).

### M19 리간드 일괄 도킹 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. 코드 루트의 `.deps/docking/venv-locked`, `.deps/qvina/env/bin/qvina2`, M17 작업 환경 `.deps/prolif/venv-locked`가 있어야 하고 백엔드가 `ligand_docking_batch`·`ligand_docking`·`ligand_candidates`를 사용 가능으로 보고해야 한다. 아니면 "사용할 수 없음"이 아니라 수락 실패다. 참조 스냅샷은 회귀(M16·M15)에만 필요하다.

```bash
.venv/bin/python scripts/m19_offscreen_acceptance.py --root runs/m19-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/<이름> \
    --out docs/qa/m19-batch-<YYYYMMDD>/acceptance --regressions --kbase <절대 경로>/kbase_kinase
```

- 순서: 환경 확인 → `batch-main`(run A: 수용체 가져오기 + 실제 M17 점검·생성 → 일괄 영역 후보 필터·체크박스 → 물·아연 수용체 시작 전 확인 거절 목록 → 부모 행 포함 자유 일괄(N 4, 부족 없음) → 실제 qvina 일괄 → 표 = 저장값, 정렬, 행 → M18 상세·포즈 SDF → 같은 일괄(기존 작업, 과금 없음) → 부분 집합 일괄(새 계산 0, 재사용 표시) → 코어 고정(부모 행 비활성, 부족 1 → 증액 승인 → 일괄) → 보고서·지식 탭 목록·다운로드. run B: 평면 부모 SDF로 부모 행 `ligand_not_3d`, 일괄 계속. run C: 표시된 생성 사슬 후보 집합(59개)으로 느린 일괄을 첫 행 뒤 취소 → `partial`/`cancelled`, 남은 프로세스 없음 → 50개 상한·꽉 찬 일괄 안내. run D: 표시된 dry-run run 기록. 문구·프로세스) → 재현 검사(같은 자유 일괄을 새 run 두 개에서 API로 다시 돌려 run별 handle·입력 해시만 자리표시로 바꾼 요약·행 결과 내용과 포즈 SDF 바이트 비교) → `batch-unavailable`(`<root>/layout-worker-missing`의 `.deps` 없는 코드 복사본 백엔드로 run 없음·`worker_missing` 이유만) → `--regressions`면 M18·M17·M16·M15·M14 실행기와 M13 실행기 모든 phase를 하나씩, 각자 새 `--root`(`<root>-m1X-regression`)·`--artifacts`(`<artifacts>/regressions/m1X`)와 `--out <out>/../m1X-regression`으로(M16·M15는 `--kbase`를 넘김). 대장의 `acceptance`는 환경 확인 통과, 모든 단계가 이번 실행에서 돌고 모든 사례 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스·`qvina2`·8000/3000 리스너 없음일 때만 true다(회귀 실행기의 판정은 각자 대장이 하고 이 대장은 종료 코드만 기록).
- 실제 환경이 만들 수 없는 사례(dry-run run의 부족분, 모드 0개 행, 행당·전체 시간 소진·작업 프로세스 중단·출력 총량)는 위조하지 않고 "관찰하지 않음"과 그것을 덮는 테스트 이름으로 기록한다.
- 2026-10-03 수락 한 번은 회귀 포함 2718초 걸렸다. 명령을 감싼 도구에 실행 시간 상한이 있으면 실행기를 분리해서 띄운다(2026-10-03 첫 실행은 도구의 2시간 백그라운드 상한 때문에 빌드 직후 스스로 멈추고 분리 실행으로 다시 띄웠다. 흐름이 시작되기 전이라 수락 시도로 세지 않음).
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다. `--kbase`는 git worktree에서 기본값이 틀리므로 절대 경로를 준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:docking-batch -- --mode <main|unavailable> --artifacts <디렉터리>`(`main`은 `--runs-dir <백엔드 MW_RUNS_DIR>`도 필요, `--url` 기본 `http://127.0.0.1:3000`, `--fixture-label`은 선택. `unavailable`은 새 runs 루트와 작업 환경 없는 백엔드가 필요). 전체 순서는 실행기에 있다.
- 2026-10-03 증거: `docs/qa/m19-batch-20261003/`(`preflight.txt`, `gate.txt`, `summary.txt`, `acceptance/`, 회귀 6개). 수락은 `--root runs/m19-acceptance-20261003-attempt1 --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/attempt1 --regressions --kbase <home>/Projects/kbase_kinase`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m19-acceptance/gate/`(Git 제외). 큰 텍스트 증거는 결정 0020대로 `<artifacts>/regressions/m1X/export-full/`로 옮겼다.

### M20 변이 후보 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`, `MW_REFERENCE_DIR=<root>/reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다. 백엔드가 `mutation_candidates`와 `pocket_detection`(코드 루트의 `.deps/fpocket/env`, 실제 fpocket 한 번)을 사용 가능으로 보고해야 한다. 아니면 "사용할 수 없음"이 아니라 수락 실패다. 번호 대응·주석 흐름에 참조 스냅샷이 필요하므로 `--kbase`로 가져온다(격리 폴더 `<root>/reference`, 실제 `.deps/reference`는 건드리지 않음). M13·M15·M16·M18 실행기의 함수(빌드 도장·환경·경로 가리기·포트, 서비스·빌드·가져오기·증거 내보내기, loopback API 도우미)를 그대로 쓴다.

```bash
.venv/bin/python scripts/m20_offscreen_acceptance.py --root runs/m20-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/<이름> \
    --out docs/qa/m20-mutations-<YYYYMMDD>/acceptance --regressions --kbase <절대 경로>/kbase_kinase
```

- 순서: 환경 확인 → `reference-import`(가져오기 명령을 하위 프로세스로 `--dest <root>/reference`) → `mutation-main`(run 없음 → 1MQ4 불러오기, 전처리 전 "사용할 수 없음" → 전처리 → 주석 없는 리간드 껍질 요청(ADP 직접 선택, KLIFS 검사하지 않음, 위치·거리·MG 제외를 착수 확인 oracle과 대조) → 번호 대응·주석 → 직접 + 껍질, 보호·충돌·해제 → 허용 잔기 줄이기 → 같은 요청 같은 handle → 실제 fpocket → 포켓 출처 + 껍질 12 Å → 필터·정렬·페이지 → 후보 0개(빈 결과) → 표시된 요청 변조로 서버 거절 → 보고서·지식 탭 목록·다운로드 → 표시된 보류 응답으로 늦은 응답(결과 바꿈·run 바꿈) → 탭 상태 → 문구) → 재현 검사(흐름의 주석 없는 요청을 같은 서버 프로세스의 새 run 두 개에서 API로 run마다 두 번: run 안 같은 handle, obj:// handle을 자리표시로 바꾼 저장 내용이 흐름과 같음. 콜드 재시작이 아님) → `--regressions`면 M19·M18·M17·M16·M15·M14 실행기와 M13 실행기 모든 phase를 하나씩, 각자 새 `--root`(`<root>-m1X-regression`)·`--artifacts`(`<artifacts>/regressions/m1X`)와 `--out <out>/../m1X-regression`으로(M16·M15는 `--kbase`를 넘김). 대장의 `acceptance`는 환경 확인·가져오기 통과, 모든 단계가 이번 실행에서 돌고 모든 사례 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스·fpocket·8000/3000 리스너 없음일 때만 true다(회귀 실행기의 판정은 각자 대장이 하고 이 대장은 종료 코드만 기록).
- 1MQ4로 만들 수 없는 사례(번호 대응·주석 지도 충돌 화면, 위치 400 초과, 변형 이름·이황화 쌍)는 위조하지 않고 "관찰하지 않음"과 그것을 덮는 테스트 이름으로 기록한다. "사용할 수 없음" 모드는 없다(capability가 항상 사용 가능이고, run 없음·전처리 전은 `mutation-main`이 관찰).
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다. `--kbase` 기본값은 git worktree에서 틀리므로 절대 경로를 준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:mutations -- --mode main --artifacts <디렉터리> --set-hash <사용 중 참조 세트 해시>`(`--url` 기본 `http://127.0.0.1:3000`, 새 runs 루트가 필요). 전체 순서와 참조 폴더 준비는 실행기에 있다.
- 2026-10-03 수락 한 번은 회귀 포함 약 47분 걸렸다(분리 실행).
- 2026-10-03 증거: `docs/qa/m20-mutations-20261003/`(`preflight.txt`, `gate.txt`, `summary.txt`, `acceptance/`, 회귀 7개). 수락은 `--root runs/m20-acceptance-20261003-attempt1 --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/attempt1 --regressions --kbase <home>/Projects/kbase_kinase`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m20-acceptance/gate/`(Git 제외). 큰 텍스트 증거는 결정 0020대로 `<artifacts>/regressions/m1X/export-full/`로 옮겼다.

### M21 변이 구조 모델링 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(빌드가 필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 백엔드가 `mutation_model`(프로젝트 `.venv`의 OpenMM 8.6.0·PDBFixer 1.12.0·신원 어댑터), `mutation_candidates`, `ligand_docking`(`.deps/docking/venv-locked`, `.deps/qvina/env`)을 사용 가능으로 보고해야 한다. 아니면 "사용할 수 없음"이 아니라 수락 실패다. 참조 스냅샷은 회귀(M20·M16·M15)에만 필요하다. M13·M15·M18·M20 실행기의 함수를 그대로 쓴다.

```bash
.venv/bin/python scripts/m21_offscreen_acceptance.py --root runs/m21-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/<이름> \
    --out docs/qa/m21-mutations-<YYYYMMDD>/acceptance --regressions --kbase <절대 경로>/kbase_kinase
```

- 순서: 환경 확인 → `model-main`(run 없음 → 공개 1UBQ 불러오기·전처리 → M20 직접 선택 후보 집합(ILE A:44, 허용 W) → 후보 행 "변이 구조 모델링" → 요청 막힘 확인 → 실제 모델링 작업(승인·시작·완료) → 나란히 표·접촉 표·mmCIF 내려받기·한계 문장·보고서를 저장값과 대조 → 같은 요청 다시(같은 작업·handle, 새 단위 없음) → 보류한 접촉 페이지 → 합성 표시 페놀 SDF 가져오기와 탭 왕복 → 같은 조건 도킹(한 동작, 실제 qvina 작업 둘) → 짝 표 → 한쪽 취소 짝 → 실행 중 모델링 작업 취소 → 보류한 응답과 run 전환 → 문구) → 재현 검사(흐름의 불러오기·전처리·후보·모델 요청을 같은 서버 프로세스의 새 run 두 개에서 API로: run 안 같은 작업·handle, obj:// handle을 자리표시로 바꾼 저장 모델이 흐름과 같음. 콜드 재시작이 아님) → `--regressions`면 M20·M19·M18·M17·M16·M15·M14 실행기와 M13 실행기 모든 phase를 하나씩, 각자 새 `--root`(`<root>-m2X|m1X-regression`)·`--artifacts`(`<artifacts>/regressions/m2X|m1X`)와 `--out <out>/../m2X|m1X-regression`으로(M20·M16·M15는 `--kbase`). 대장의 `acceptance`는 환경 확인 통과, 모든 단계가 이번 실행에서 돌고 모든 사례 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스·`qvina2`·8000/3000 리스너 없음일 때만 true다(회귀 판정은 각자 대장이 하고 이 대장은 종료 코드만 기록).
- 실제 환경이 만들 수 없는 사례(엔진 사용할 수 없음, 도킹 짝 자체 승인 버튼, 실패한 작업, 접촉 0개, L5·L6 조건)는 위조하지 않고 "관찰하지 않음"과 그것을 덮는 테스트 이름으로 기록한다. "사용할 수 없음" 모드는 없다(capability가 `.deps`가 아니라 프로젝트 `.venv`에 달려 있음).
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다. `--kbase`는 절대 경로를 준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:mutation-model -- --mode main --artifacts <디렉터리> --runs-dir <백엔드 MW_RUNS_DIR>`(`--url` 기본 `http://127.0.0.1:3000`, 새 runs 루트가 필요). 전체 순서는 실행기에 있다.
- 2026-10-04 수락 한 번은 회귀 포함 약 48분 걸렸다(분리 실행).
- 2026-10-04 증거: `docs/qa/m21-mutations-20261004/`(`preflight.txt`, `gate.txt`, `summary.txt`, `acceptance/`, 회귀 8개, 개발 실행 `offscreen-acceptance/`). 수락은 `--root runs/m21-acceptance-20261004-attempt1 --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/attempt1 --regressions --kbase <home>/Projects/kbase_kinase`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m21-acceptance/gate/`(Git 제외). 큰 텍스트 증거는 결정 0020대로 `<artifacts>/regressions/m1X/export-full/`로 옮겼다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/mutation-model-flow.cjs`와 `scripts/test_m21_offscreen_acceptance.py`가 더해진 것이다. M21 고정 게이트는 백엔드 pytest를 Stop 훅의 다섯 그룹으로 나눠 제한 없이 따로 돌렸다(`MW_KBASE_REF` 지정, `gate.txt`).

### M22 리간드 GA 설계 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(빌드가 필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 코드 루트의 `.deps/docking/venv-locked`, `.deps/qvina/env/bin/qvina2`, M17 작업 환경 `.deps/prolif/venv-locked`가 있어야 하고 백엔드가 `ligand_ga_design`·`ligand_docking`·`ligand_candidates`를 사용 가능으로 보고해야 한다. 아니면 "사용할 수 없음"이 아니라 수락 실패다. 참조 스냅샷은 회귀(M20·M16·M15)에만 필요하다. M13·M15·M18 실행기의 함수(빌드 도장·환경·경로 가리기·포트, 서비스·빌드·증거 내보내기, 환경 경로·`.deps` 없는 layout·백엔드 시작·정지·loopback API 도우미)를 그대로 쓴다. 실행기는 `mw`를 import하지 않고 증액 라우트를 직접 부르지 않는다(증액은 흐름이 화면 버튼으로만).

```bash
.venv/bin/python scripts/m22_offscreen_acceptance.py --root runs/m22-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/<이름> \
    --out docs/qa/m22-ga-<YYYYMMDD>/acceptance --regressions --kbase <절대 경로>/kbase_kinase
```

- 순서: 환경 확인 → `ga-main`(run A: 후보 집합 전 이유만 → 수용체 가져오기 + 실제 M17 점검·생성(합성 표시 작은 풀 10개) → 파라미터 가드·"기본값으로" → `ga_pool_too_small` 시작 전 확인 거절(기본값, M17 필터) → GA 1 시작 전 확인 = 명세 산식 → 실제 GA 1(진행, 완료, 예약 단위만 과금) → 결과 = 저장값(세대 탭, 개체 행, 이어받음·자리 수, 지문 Tanimoto, 최솟값·최댓값, G1, 종료 이유)·정렬·개체 → M18 상세 → GA 2(다른 GA seed): 부족분 → 화면 증액 → GA 1 다시(기존 작업) → GA 2 재사용(G3) → GA 3 `pool_exhausted` → GA 4 `docking_limit`(G2) → GA 5 실행 중 취소 → 보고서·지식 탭 목록·다운로드 → 전역 예산·프로세스·문구) → 재현 검사(흐름의 GA 1을 같은 서버 프로세스의 새 run 두 개에서 API로 다시: obj:// handle과 그 위의 해시(`input_sha256`·`selection_sha256`·`call_key`)만 자리표시로 바꾼 요약·개체 결과 내용과 포즈 SDF 바이트가 흐름과 같음. 콜드 재시작이 아님) → `ga-unavailable`(`<root>/layout-worker-missing`의 `.deps` 없는 코드 복사본 백엔드로 run 없음·`worker_missing` 이유만) → `--regressions`면 M21·M20·M19·M18·M17·M16·M15·M14 실행기와 M13 실행기(`--phases workflows,unavailable,regressions,m11,m12,ledger`)를 하나씩, 각자 새 `--root`(`<root>-m2X|m1X-regression`)·`--artifacts`(`<artifacts>/regressions/m2X|m1X`)와 `--out <out>/../m2X|m1X-regression`으로(M20·M16·M15는 `--kbase`). 대장의 `acceptance`는 환경 확인 통과, 모든 단계가 이번 실행에서 돌고 모든 사례 통과, 모든 흐름 행의 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 작업 프로세스(`ligand_ga_worker.py`·`docking_worker.py`·`ligand_worker.py`·guardian)·`qvina2`·8000/3000 리스너 없음일 때만 true다(회귀 판정은 각자 대장이 하고 이 대장은 종료 코드만 기록).
- 실제 환경이 만들 수 없는 사례(점수 없는 개체, 조기 중단 `no_change`, 시간 소진·개체 시간 초과·작업 모듈 중단·출력 총량)는 위조하지 않고 "관찰하지 않음"과 그것을 덮는 테스트 이름으로 기록한다.
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--code-root`로 서비스·하네스를 띄울 코드 루트를 바꿀 수 있다. `--kbase`는 절대 경로를 준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:ligand-ga -- --mode <main|unavailable> --artifacts <디렉터리>`(`main`은 `--runs-dir <백엔드 MW_RUNS_DIR>`도 필요, `--url` 기본 `http://127.0.0.1:3000`, `--fixture-label`은 선택. `unavailable`은 새 runs 루트와 작업 환경 없는 백엔드가 필요). 전체 순서는 실행기에 있다.
- 2026-10-05(KST) 수락 한 번은 회귀 포함 약 54분 걸렸다(M22 부분 약 6분, 분리 실행).
- 2026-10-05 증거: `docs/qa/m22-ga-20261005/`(`gate.txt`, `summary.txt`, `acceptance/`, 회귀 9개), 착수 확인 `docs/qa/m22-ga-20261004/preflight.txt`. 수락은 `--root runs/m22-acceptance-20261005-attempt1 --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/attempt1 --regressions --kbase <home>/Projects/kbase_kinase`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m22-acceptance/gate/`(Git 제외). 큰 텍스트 증거는 결정 0020대로 `<artifacts>/regressions/m1X/export-full/`로 옮겼다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/ligand-ga-flow.cjs`와 `scripts/test_m22_offscreen_acceptance.py`가 더해진 것이다. M22 고정 게이트는 백엔드 pytest를 Stop 훅의 다섯 그룹으로 나눠 제한 없이 한 줄로 차례로 돌렸다(`MW_KBASE_REF` 지정, `gate.txt`).

### M23 서열 GA 설계 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 코드 루트의 프로젝트 `.venv`(OpenMM 8.6.0·PDBFixer 1.12.0), `.deps/docking/venv-locked`, `.deps/qvina/env/bin/qvina2`가 있어야 하고 백엔드가 `sequence_ga_design`·`mutation_model`·`mutation_candidates`·`ligand_docking`을 사용 가능으로 보고해야 한다(아니면 "사용할 수 없음"이 아니라 수락 실패, `.deps` 없는 layout 백엔드는 `worker_missing`). 참조 스냅샷은 회귀(M20·M16·M15)에만 필요하다.

```bash
.venv/bin/python scripts/m23_offscreen_acceptance.py --root runs/m23-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/<이름> \
    --out docs/qa/m23-sequence-ga-<YYYYMMDD>/acceptance --regressions --kbase <절대 경로>/kbase_kinase
```

- 순서: 환경 확인 → `seqga-main`(run A: 1UBQ 전처리 + 직접 선택 M20 후보 집합 + 합성 표시 페놀 SDF 가져오기 → 파라미터 가드(열한 키)·교차 규칙·"기본값으로" → 확인 항목·입장 거절 표시 → 시작 전 확인(명세 산식) → 사람이 누르는 증액 → 첫 비싼 계산 승인 → 실제 GA 1(진행, 야생형 기준 행, 세대, 완료) → 결과 = 저장값(세대 탭, 개체 표, 출처, 재사용, 점수 없는 행은 끝, S1–S6) → oracle 경로 대조 → 정렬 → 개체 상세(모델 값, mmCIF 해시, M18 상세) → 같은 인자 재제출(기존 작업) → GA 2(다른 GA seed, 같은 평가 seed) 재사용 → 부분 완료(`evaluation_limit`) → 취소 → `reference_failed`(암시 수소 SDF) → 늦은 응답 → 보고서 → 탭·프로세스·문구) → `seqga-repro`(흐름의 GA 1을 같은 서버 프로세스의 새 run 둘에서 **화면**으로 다시: 모든 증액이 화면 클릭이라 실행기가 증액 라우트를 직접 부르지 않는다. 정규화한 요약 digest와 개체 13행(모델·M18 결과·포즈 SDF 해시)이 같고, 콜드 재시작이 아니다) → `seqga-unavailable`(`.deps` 없는 layout 백엔드) → 외부 요청·제공자 호출·남은 프로세스 → `--regressions`(M22 → M13 실행기 전체).
- 실제 환경이 만들 수 없는 사례(점수 없는 개체, 4,890 경고, 그 밖의 종료 이유, SL5·L6, dry-run)는 위조하지 않고 "관찰하지 않음"과 그것을 덮는 테스트 이름으로 기록한다.
- `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 다시 돌릴 때는 새 `--root`·`--artifacts`·`--out`을 쓰고 실패한 시도의 폴더를 지우지 않는다. `--kbase`는 절대 경로를 준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `node frontend/tests/offscreen/sequence-ga-flow.cjs --mode <main|repro|unavailable> --artifacts <디렉터리> --runs-dir <백엔드 MW_RUNS_DIR>`(`package.json`에 `test:offscreen:sequence-ga` 스크립트는 아직 없다). 전체 순서는 실행기에 있다.
- 2026-10-05(KST) 수락 한 번은 회귀 포함 약 66분 걸렸다(M23 부분 약 11분). 실제 엔진 GA 한 번(개체 4, 세대 2–4)이 평가 약 11초/건이다.
- 2026-10-05 증거: `docs/qa/m23-sequence-ga-20261005/`(`preflight.txt`, `gate.txt`, `summary.txt`, `acceptance/`, 회귀 10개), 수락은 `--root runs/m23-acceptance-20261005-attempt1 --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/attempt1 --regressions --kbase <home>/Projects/kbase_kinase`로 한 번 돌렸다. 전체 게이트 로그는 `frontend/tests/offscreen/artifacts/m23-acceptance/gate/`(Git 제외). 큰 텍스트 증거는 결정 0020대로 `<artifacts>/regressions/m1X/export-full/`로 옮겼다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/sequence-ga-flow.cjs`와 `scripts/test_m23_offscreen_acceptance.py`가 더해진 것이다. M23 고정 게이트는 백엔드 pytest를 Stop 훅의 다섯 그룹으로 나눠 제한 없이 한 줄로 차례로 돌렸다(`MW_KBASE_REF` 지정, `gate.txt`).

### M24 JEV 과학 전송 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`next start`와 백엔드, `PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 코드 루트의 M17 작업 환경 `.deps/prolif/venv-locked`가 있어야 하고 백엔드가 `ligand_candidates`·`mutation_candidates`·`jev_choice`를 사용 가능으로 보고해야 한다(아니면 수락 실패). 후보 집합은 실행기가 loopback API로 만든다: 공개 파생 부모 + 합성 표시 작은 block 목록의 실제 M17 점검·생성 작업(후보 10개), 공개 1UBQ·1MQ4에서 `backend/tests/fixtures/jev/expected.json`의 이웃 수가 많은 Ala 아닌 잔기를 사용자 위치로, A로만 치환한 실제 M20 후보 집합. M13·M15·M18 실행기 함수를 그대로 쓴다. 실행기 프로세스는 `mw`를 import하지 않고 `/jev/` 라우트에 직접 보내지 않는다(동의·미리보기·전송은 모두 하네스의 실제 클릭).

```bash
# fixture 단계(기본, 실호출 0)
.venv/bin/python scripts/m24_offscreen_acceptance.py --root runs/m24-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<이름> \
    --out docs/qa/m24-jev-<YYYYMMDD>/acceptance-fixture [--regressions --kbase <절대 경로>/kbase_kinase]
# 실호출 단계(사용자가 정해 준 횟수 N ≤ 6 안에서만): 새 --root로 calibrate, 통과하면 같은 --root로 live
.venv/bin/python scripts/m24_offscreen_acceptance.py --phase calibrate --live-calls N --root runs/m24-live-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<이름>-calibrate --out docs/qa/m24-jev-<YYYYMMDD>/acceptance-calibrate
.venv/bin/python scripts/m24_offscreen_acceptance.py --phase live --live-calls N --root runs/m24-live-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<이름>-live --out docs/qa/m24-jev-<YYYYMMDD>/acceptance-live
```

- `fixture`: 백엔드는 `backend/tests/offscreen_jev_fixture/server.py`(제품 앱 그대로, 모듈 전역 `SCIENCE_GATE`만 스크립트된 `httpx.MockTransport`와 placeholder 자격 증명으로, `VIEWER_GATE`는 거절하는 게이트로 바꿈, provider 소켓 없음). `jev-fixture`(run A·B·C: 탭 진입, 동의 끄기·켜기, 집합 고르기, 20개 한계, 리간드 필터, 미리보기 = 서버 문자열 = 저장 투영 = `prepared` 본문 = transport 바이트, 확인 체크, 정상·같은 본문 재전송·보고서, 별칭 밖 선택, 응답 모델 불일치, 동의 끈 뒤 늦은 응답, 전송 상한, 다른 탭 불변, 사용량 없음 → 멈춤, HTTP 500, 문구, 브라우저 외부 요청 0) → 실호출 계획을 fixture로 미리 돌리는 `jev-rehearsal-calibrate`·`jev-rehearsal-live`. 실호출 0회는 fixture 서버 기록과 dispatch·응답 감사가 스크립트된 transport 호출과 하나씩 맞는 것으로 확인한다. 실호출 대장은 건드리지 않는다. `--regressions`(fixture 단계만, `--kbase` 필요)면 이어서 M23 → M13(모든 phase) 실행기를 각자 새 폴더로 돌린다.
- `calibrate`: 제품 백엔드(`uvicorn mw.api.app:app`, 실제 `SCIENCE_GATE`)로, 키가 있는지 불리언으로 확인한 뒤 run L1(리간드 + 1UBQ 집합)·L2(1MQ4 + 1UBQ 집합)를 만든다. 첫 클릭 전에 전송 없이 사전 확인(동의 끔 → `consent_off`·전송 단추 닫힘 → 켬, 20개 체크 뒤 21번째 거절 → 5개로, 확인 체크 전 단추 닫힘)을 한 뒤 계획의 첫 항목 하나만 실제로 보내고 사용량(입력·출력 토큰·비용)을 본문 바이트·예약값과 함께 `<root>/live-state.json`에 남긴다. 사용량 모름·예약 초과·외부 전송 멈춤·흐름 실패면 여기서 끝나고 더 보내지 않는다. `--live-calls` ≥ 1.
- `live`: 같은 `--root`에서 calibrate가 통과했을 때 root마다 한 번만, 계획의 나머지 항목(2..N)을 화면으로 보낸다. `--live-calls` ≥ 2. 완료되지 않은 전송이나 외부 전송 멈춤이 나오면 계획을 끝낸다(다시 시도·새 run 없음).
- 실호출 계수: 하네스는 클릭 전마다 `<root>/runs`의 모든 run의 `jev_science_dispatch_started` 이벤트를 보고(계획 상한, run당 3회), 실행기는 하네스가 도는 동안 이벤트를 세어 N을 넘으면 하네스와 백엔드를 바로 멈춘다. 외부 요청 판정은 브라우저 비-loopback 요청 0건 + 서버 쪽 `response_received` 감사 ≤ `--live-calls`다.
- 실호출 대장: 저장소 단위 `runs/m24-live-ledger.json`(주 체크아웃의 Git 제외 `runs/`, git common dir로 찾으므로 worktree에서 돌려도 같은 파일). calibrate·live 단계는 시작 전에 대장 합계(기록된 모든 root의 run 폴더 dispatch 이벤트를 다시 셈) + 이번 계획이 6을 넘거나 대장을 읽을 수 없거나 손상됐으면 아무것도 시작하지 않고 거절한다. 단계 시작을 먼저 적고 끝날 때 root의 run별 dispatch 수(실패한 전송 포함)를 적으므로 중간에 멈춰도 root가 남아 다시 센다. 대장 파일을 지우거나 고쳐 상한을 되돌리지 않는다.
- `--phase calibrate --finalize`(`--live-calls 0`, 같은 `--root`·`--artifacts`, 없거나 빈 `--out`): 실호출은 끝났지만 실행기가 증거를 쓰기 전에 멈춘 calibrate root의 증거를 저장 파일(`live-state.json`, `jev-calibrate` 행, `runner-state.json`, root의 이벤트, 대장)만 읽어 다시 만든다. 빌드·서비스·Electron·POST·호출·대장 쓰기가 없고, 대장이 그 root를 모든 단계 끝남·이벤트·`live-state.json`과 같은 dispatch 수로 기록하지 않았으면 아무것도 쓰지 않고 거절한다.
- 키: 실행기는 키 값을 출력하지 않는다. 자식 프로세스에서 제품 해석기(`env_or_root_dotenv_key`)로 키를 읽어 존재 불리언과, 증거 폴더·QA 루트·내보낸 증거에서 키 문자열이나 fixture placeholder가 나온 파일 경로만 출력한다(나오면 실패). `.env` 내용은 열거나 출력하지 않는다. 서비스는 허용 목록 환경변수로 띄우므로(`OPENROUTER_*` 없음) 제품 백엔드는 루트 `.env`(0600)에서 키를 읽는다.
- 모든 단계 끝: 작업 모듈·fixture 서버·Electron·8000/3000 리스너가 남지 않았는지, 증거 문구(금지 표현, 고정 문장 줄 제외), 대장의 `acceptance`(모든 사례 통과, 환경 있음, 남은 것 없음, 소스 도장 빌드)를 확인한다. `--root`는 fixture·calibrate에서 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 실패한 시도의 폴더를 지우지 않는다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:jev -- --mode <fixture|live> --artifacts <디렉터리> --runs-dir <백엔드 MW_RUNS_DIR> --setup <json> [--control <fixture control 폴더>] [--plan <json>]`(`frontend/tests/offscreen/jev-flow.cjs`, setup·plan 파일은 실행기가 만든다. `fixture`는 `--control` 필수, `live`에 `--control`을 주면 fixture 서버에 대한 미리 돌리기). 전체 순서는 실행기에 있다. 실제 OpenRouter로 보내는 것은 제품 백엔드에 대한 `live` 모드뿐이므로 실행기의 계수·대장 없이 돌리지 않는다.
- 2026-10-06 증거: `docs/qa/m24-jev-20261006/`(착수 확인 `preflight.txt`, 백엔드 게이트 `gate-backend.txt`: 열네 그룹을 제한 없이 동시에 돌려 3,712개 통과·ruff 통과, 그룹 약 259–343초, 실호출 증거 `acceptance-calibrate/`·`acceptance-live/`, fixture 단계 증거). 실호출은 `--root runs/m24-live-20261006`에서 calibrate 1회 + live 5회로 사용자가 정한 6회를 모두 썼다(대장 합계 6/6). 이후 실호출은 사용자가 새로 정해 줄 때만 한다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/jev-flow.cjs`와 `scripts/test_m24_offscreen_acceptance.py`가 더해진 것이다.
- M25 루프 영역이 리간드·단백질 탭에 생긴 뒤 `jev-flow.cjs`의 다른 탭 검사는 `jev-loop-panel` 영역을 빼고 센다(`9a9a625`). M25 회귀로 fixture 단계를 다시 돌렸다(26/26).

### M25 JEV 설계 루프 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 loopback 서비스(`next start`와 백엔드, `PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/runs`)를 직접 띄우고 끝나면 정리하며(서비스는 실행기와 같은 수명, 하네스 한 단계 상한 2시간), `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 코드 루트의 M17 작업 환경 `.deps/prolif/venv-locked`, `.deps/docking/venv-locked`, `.deps/qvina/env/bin/qvina2`, 프로젝트 `.venv`의 OpenMM·PDBFixer가 있어야 하고 백엔드가 `ligand_candidates`·`mutation_candidates`·`ligand_docking`·`mutation_model`·`jev_choice`와 `methods.jev_loop` 두 갈래를 사용 가능으로 보고해야 한다(아니면 수락 실패). QA run 둘은 `backend/tests/offscreen_jev_loop_fixture/qa_setup.py`가 loopback API로 만든다: run L = 공개 준비 수용체 예제·공개 파생 부모·합성 표시 작은 block 목록의 실제 M17 후보 10개, run P = 공개 1UBQ(22곳)·1MQ4(3곳) A 치환 실제 M20 후보 집합과 합성 표시 페놀 SDF(단백질 루프의 풀은 1UBQ 집합에서만 고르고, 1MQ4 집합은 만들기 거절 사례에만 쓴다). 실행기 프로세스는 `mw`를 import하지 않고 `/jev/`·`/jev_loops` 라우트에 직접 보내지 않는다(동의·루프·전송·계산은 모두 하네스의 실제 클릭).

```bash
# fixture 단계(기본, 실호출 0)
.venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<이름> \
    --out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-fixture [--regressions --kbase <절대 경로>/kbase_kinase]
# 실호출 단계(사용자가 정해 준 횟수 안에서만, M25 할당 8회는 소진): 새 --root로 calibrate, 통과하면 같은 --root로 live
.venv/bin/python scripts/m25_offscreen_acceptance.py --phase calibrate --live-calls 8 --root runs/m25-live-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<이름>-calibrate --out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-calibrate
.venv/bin/python scripts/m25_offscreen_acceptance.py --phase live --live-calls 8 --root runs/m25-live-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<이름>-live --out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-live
# 연습(실호출 0): 같은 코드 경로를 fixture 서버로 --phase calibrate --rehearse --live-calls 8, 같은 --root로 --phase live --rehearse
```

- `fixture`: 백엔드는 `backend/tests/offscreen_jev_loop_fixture/server.py`(제품 앱 그대로, 모듈 전역 `SCIENCE_GATE`만 스크립트된 `httpx.MockTransport`와 sentinel placeholder 자격 증명으로, 다른 게이트는 거절하고 `.env`를 읽지 않음). 단계 `jev-loop-fixture`가 리간드·단백질 화면 사례 전부를 돈다(스크립트 `good`·`good_second`·`computed_alias`·`http_500`·`slow`·`no_usage`·`model_mismatch`). 실호출 0회는 dispatch 이벤트·응답 감사 수가 fixture transport 호출 기록과 같고 모든 호출이 placeholder였으며 제품 키 해석기 호출이 0인 것으로 확인한다. fixture 서버는 `server.json`의 pid가 방금 띄운 pid이고 8000 포트의 유일한 리스너일 때만 하네스를 띄운다(하네스도 `--backend-pid`로 확인). 실호출 대장은 건드리지 않는다. `--regressions`(fixture 단계만, `--kbase` 필요)면 이어서 M24(fixture 단계) → M23 → M13(모든 phase) 실행기를 각자 새 폴더로 돌린다.
- `calibrate`: 제품 백엔드(`uvicorn mw.api.app:app`, 실제 `SCIENCE_GATE`)로, 키가 있는지 불리언으로(자식 프로세스의 제품 해석기)·루트 `.env`가 0600인지(`os.lstat`만, 내용은 읽지 않음) 확인한 뒤 전송 없는 사전 확인을 하고 계획의 첫 항목(리간드 탐색형 루프, 풀 5개)의 전송 한 번만 실제로 보낸다. 본문 바이트·사용 토큰·비용·예약값·응답 모양(`answers`·`confidence`·`probabilities`)과 예약식 조정 필요 여부를 `<root>/live-state.json`에 남긴다(예약식은 실행기가 바꾸지 않는다, 사용자 결정). 사용량 모름·예약 초과·완료되지 않은 전송·외부 전송 멈춤·흐름 실패면 여기서 끝나고 더 보내지 않는다.
- `live`: 같은 `--root`에서 calibrate가 통과했을 때 root마다 한 번, 계획의 나머지(리간드 활용형 3바퀴 + 실제 qvina, 단백질 활용형 3바퀴(run P, 실제 PDBFixer·OpenMM 모델링과 qvina 도킹), 섞기 확인 1회(calibrate와 같은 풀·목표, 다른 루프 seed의 첫 바퀴))를 화면으로 보낸다. 완료되지 않은 전송이나 외부 전송 멈춤이 나오면 계획을 끝낸다(다시 시도·새 run 없음). 고른 목록 위치는 관찰값으로만 기록한다.
- 실호출 계수: 계획은 합계 8회(run L 5·run P 3). 하네스는 클릭 전마다 `<root>/runs`의 모든 run의 `jev_science_dispatch_started`를 보고(계획 상한·run별 상한), 실행기는 하네스가 도는 동안 이벤트를 세어 `--live-calls`를 넘으면 하네스와 백엔드를 바로 멈춘다(반쯤 쓴 마지막 이벤트 줄은 다음 읽기에서 셈). 시작 전에 계획의 run별 필요량(비싼 계산 단위·활동 시간·외부 토큰·USD·전송 수)을 run 기본 한도(8단위·1800초·120,000 토큰·USD 2.00·10회)와 남은 예산으로 확인한다.
- 실호출 대장: 저장소 단위 `runs/m25-live-ledger.json`(주 체크아웃의 Git 제외 `runs/`, git common dir로 찾음, M24 대장 `runs/m24-live-ledger.json`은 읽지 않음). calibrate·live 단계는 시작 전에 대장 합계(기록된 모든 root의 dispatch 이벤트를 다시 셈) + 이번 계획이 8을 넘거나 `--live-calls`가 남은 양을 넘거나 대장을 읽을 수 없으면 아무것도 시작하지 않는다. 끝나지 않은 다른 단계는 기록 + 계획 수만큼 잡아 두고, 대장 읽기·쓰기는 옆의 잠금 파일로 하나씩 한다. 대장 파일을 지우거나 고쳐 상한을 되돌리지 않는다.
- `--phase calibrate --finalize`(`--live-calls 0`, 같은 `--root`·`--artifacts`, 없거나 빈 `--out`): 실호출은 끝났지만 증거를 쓰기 전에 멈춘 calibrate root의 증거를 저장 파일만으로 다시 만든다(빌드·서비스·Electron·POST·호출 없음, 맞지 않으면 거절).
- `--rehearse`(calibrate·live·finalize): 같은 단계 코드를 fixture 서버로 돌린다(제품 백엔드를 띄우지 않음, 대장은 root 안 `rehearsal-live-ledger.json`, 실호출 0).
- 모든 단계 끝: 작업 모듈·fixture 서버·Electron·8000/3000 리스너가 남지 않았는지(QA 루트 안 프로세스만), 증거 폴더·QA 루트·내보낸 증거의 키 문자열·fixture placeholder(불리언·경로만 출력), 증거 문구(금지 표현, 고정 문장·지시문·보낸 본문 줄 제외), 대장의 `acceptance`(모든 사례 통과, 환경 있음, 남은 것 없음, 소스 도장 빌드)를 확인한다. 내보낸 폴더 검사가 실패하면 내보낸 README·사례 대장도 `acceptance: false`다. `--root`는 fixture·calibrate에서 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 실패한 시도의 폴더를 지우지 않는다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `npm --prefix frontend run test:offscreen:jev-loop -- --mode <fixture|calibrate|live> --artifacts <디렉터리> --runs-dir <백엔드 MW_RUNS_DIR> --setup <json> [--control <fixture control 폴더> --backend-pid <방금 띄운 fixture 서버 pid>] [--plan <json>]`(`frontend/tests/offscreen/jev-loop-flow.cjs`, setup·plan 파일은 실행기가 만든다. `fixture`는 `--control`·`--backend-pid` 필수, calibrate·live에 `--control`을 주면 fixture 서버에 대한 연습). 실제 OpenRouter로 보내는 것은 제품 백엔드에 대한 calibrate·live 모드뿐이므로 실행기의 계수·대장 없이 돌리지 않는다.
- 2026-10-07 증거: `docs/qa/m25-jev-loop-20261007/`(착수 확인 `preflight.txt`, 게이트 `gate-backend.txt`·`gate-frontend.txt`·`gate-invariants.txt`, fixture 단계 `acceptance-fixture/` 57사례, 실호출 `acceptance-calibrate/`·`acceptance-live/`, 회귀 `m24-regression/`…`m13-regression/`, M24 하네스 수정과 회귀 사슬 `regression-harness-changes.txt`). 실호출은 같은 root에서 calibrate 1회 + live 7회로 사용자가 정한 8회를 모두 썼다(대장 합계 8/8, 모두 `completed`). 이후 실호출은 사용자가 새로 정해 줄 때만 한다. 큰 텍스트 증거는 결정 0020대로 `frontend/tests/offscreen/artifacts/m25-acceptance/regress-20261008a/export-full/`로 옮겼다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/jev-loop-flow.cjs`와 `scripts/test_m25_offscreen_acceptance.py`가 더해진 것이다.

### M26 효소 반응 지식 수락 QA

8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 `next start`(실행 내내)와 단계마다 백엔드(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/<단계>/runs`, `MW_REFERENCE_DIR=<root>/<단계>/reference`, `MW_REACTION_REFERENCE_DIR=<root>/<단계>/reaction_reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 번호 대응 사례에 M15 스냅샷이 필요하므로 `--kbase`로 격리 폴더에 가져온다(실제 `.deps/reference`는 건드리지 않음). 실행기 프로세스는 `mw`를 import하지 않고 한도 증액 라우트를 부르지 않는다(합성 세트 만들기와 M15 가져오기는 하위 프로세스, dry-run run 기록 하나만 loopback API로 만들고 나머지는 하네스의 실제 클릭). 실서버 요청을 하지 않는다.

```bash
# fixture 단계만 (합성 반응 세트)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<이름> --kbase <절대 경로>/kbase_kinase \
    --stages fixture --out docs/qa/m26-reaction-<YYYYMMDD>/fixture-stage
# real 단계만 (설치된 실제 세트 폴더를 격리 폴더로 복사해 씀, 원본은 쓰지 않음)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<이름> --kbase <절대 경로>/kbase_kinase \
    --stages real --reaction-set <설치된 반응 참조 폴더> --out docs/qa/m26-reaction-<YYYYMMDD>/real-stage
# 수락 (두 단계, 기본 --stages fixture,real)
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<이름> --kbase <절대 경로>/kbase_kinase \
    --stages fixture,real --reaction-set <설치된 반응 참조 폴더> --out docs/qa/m26-reaction-<YYYYMMDD>/acceptance
```

- `fixture`: 표시된 합성 세트(`backend/tests/fixtures/reaction/t9/build_qa_set.py`를 하위 프로세스로, 모든 값이 지어낸 값)로 `fixture-empty`(세트 없음) → 세트 A 설치 → `fixture-main`(스냅샷 블록, 요청 기본값, 칸 거절, 입장 거절 아홉, 1HSG·합성 파생 1HSG·1UBQ·합성 0SY6·0SY2·M15 번호 대응을 준 전처리 1MQ4, 페이지, 보고서, dry-run run, 결과 목록, 문구, M20 미리 고르기와 UK3, 탭 불변) → `fixture-mutation`(`mutation-flow.cjs` `catalytic` 모드: M20 v2 UK2·미리 고르기·체인별 예고·`chains_not_covered`·`checked`·목록·해제·제외 사유 일곱·한계 문장 변형(T1 저장 v1 run을 복사해 v1 포함)·M20/M21/M23/M24/M25 고르는 곳 표시) → `active.json`을 치움 → `fixture-unset` → 되돌리고 세트 파일 하나를 변조 → `fixture-invalid` → 세트 B(같은 행, 다른 `imported_at`) → `fixture-stale`.
- `real`: `--reaction-set`(설치된 폴더, `active.json`과 `sets/`가 있어야 하고 `--root` 안이면 거절)을 `<root>/real/reaction_reference`로 복사하고, 공개 구조 1S9I·1A30·1A4I·표시된 합성 파생 1S9I(Asp194 → Glu)·1HSG·1UBQ·1MQ4로 `real-main`·`real-mutation`을 돈다.
- 대장(`case-ledger.json` 하나)의 `acceptance`는 두 단계가 모두 이번 실행에서 돌고 통과했으며, 모든 사례 통과, 모든 흐름 행의 브라우저 비-loopback 요청 0건·제공자 호출 0회, 반응 세트와 M15 참조 변경이 기대대로 되었고, 소스 도장 빌드, 작업 모듈·8000/3000 리스너가 남지 않았을 때만 true다. 요청하지 않은 단계는 "빠짐"으로 기록되며 통과로 세지 않는다. `--root`는 새 폴더여야 하고 `/tmp` 아래면 거부한다. `--artifacts`는 Git 제외 폴더여야 한다. 실패한 시도의 폴더를 지우지 않는다.
- 보고서 다운로드와 실패한 단계가 저장한 화면 HTML(`*-failure.panel.html`)은 제3자 참조 원문(M-CSA 역할 문구·UniProt 설명·Rhea 반응식, CC BY 4.0)을 담으므로 증거 내보내기는 그 파일의 경로·크기·SHA-256만 남기고 내용은 Git 제외 artifacts 폴더에 둔다(`held_downloads`). 보고서 목록 단계와 탭 서명은 글자 대신 길이 + SHA-256을 돌려준다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `node frontend/tests/offscreen/reaction-knowledge-flow.cjs --mode <empty|main|unset|invalid|stale> --artifacts <디렉터리> [--plan <json>] [--runs <runA,runD>] [--set-hash <활성 세트>] [--previous-set-hash <해시>]`(npm 스크립트 없음, `empty` 밖은 `--plan` 필수, `unset`·`invalid`·`stale`은 `--runs`, `stale`은 두 해시 필요, `--url` 기본 `http://127.0.0.1:3000`)와 `npm --prefix frontend run test:offscreen:mutations -- --mode catalytic --plan <json> --artifacts <디렉터리>`. plan 파일과 참조 폴더 변경은 실행기가 만든다.
- 회귀: 이 실행기에는 `--regressions`가 없다. M25 실행기 `--regressions`(fixture 단계만, 실호출 0)로 M25 → M13 사슬을 돌린다. **M13–M25 실행기는 `MW_REACTION_REFERENCE_DIR`를 넘기지 않아 백엔드가 코드 루트의 기본 폴더 `.deps/reaction_reference`를 읽으므로, 회귀 동안 그 폴더를 없는 채로 둔다**(실제 세트를 기본 위치에 두면 지식 탭의 새 영역 글자가 기계마다 달라질 수 있다. 2026-10-09 회귀는 그 폴더 없이 돌았다).
- 2026-10-09 증거: `docs/qa/m26-reaction-20261008/`(착수 확인 `preflight-network.md`·`preflight-local.md`, v1 기준선 `v1-baseline/`, 실서버 가져오기 `import1.md`·`import2.md`, 요청 장부 `network-ledger.txt`(95줄), 게이트 `gate.txt`, 수락 `acceptance/`(사례 58/58, `acceptance: true`, real 단계는 import2 세트의 복사본), 회귀 `regression-chain.txt`·`regression/m25/`·`regression/m23/`). 회귀 사슬의 M23 단계는 하네스의 v1 기대(제외 사유 여섯 키) 때문에 실패했고 `sequence-ga-flow.cjs` 한 곳을 고친 뒤 M23 실행기를 단독으로 다시 돌려 35/35 통과했다(실패한 사슬 증거는 그대로 둠). 큰 텍스트 증거는 결정 0020대로 `frontend/tests/offscreen/artifacts/m26-final/export-full/`로 옮겼다. 실서버 가져오기의 할당(전체 2회·탐색 100건·RCSB 구조 3개)은 `docs/security.md` "반응 참조 스냅샷 (M26)"에 있다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/reaction-knowledge-flow.cjs`와 `scripts/test_import_reaction_references.py`·`scripts/test_m26_offscreen_acceptance.py`가 더해진 것이다.

### M27 키나아제 전례 수락 QA

주 체크아웃에서, 8000·3000 포트가 비어 있는 상태에서 실행한다. 실행기가 `next start`(실행 내내)와 단계마다 백엔드(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/<단계>/runs`, `MW_REFERENCE_DIR=<root>/<단계>/reference`(활성 M15 세트 `--m15-reference`의 읽기 전용 복사본), `MW_PRECEDENT_REFERENCE_DIR=<root>/<단계>/precedent_reference`, 빈 `MW_REACTION_REFERENCE_DIR=<root>/<단계>/reaction_reference`)를 직접 띄우고 끝나면 정리하며, `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). `--root`는 새 폴더여야 하고 `/tmp` 아래면 거절하며, `--artifacts`는 Git 제외 폴더여야 한다. 실행기 프로세스는 `mw`를 import하지 않고 한도 증액 라우트를 부르지 않으며 기본 폴더 `.deps/precedent_reference`에 쓰지 않는다(합성 세트 만들기·파생 번호 대응 만들기·가져오기 명령은 하위 프로세스, dry-run run 기록 하나만 loopback API로 만들고 나머지는 하네스의 실제 클릭). 외부 요청을 하지 않는다.

```bash
.venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m27-acceptance-<date> \
    --artifacts frontend/tests/offscreen/artifacts/m27-acceptance/<label> \
    --kbase <abs>/kbase_kinase --stages fixture,real --out docs/qa/m27-precedents-<YYYYMMDD>/acceptance
```

- 인자: `--kbase`(기본 `<저장소>/../kbase_kinase`, worktree에서는 절대 경로), `--m15-reference`(기본 `.deps/reference`, 읽기만 하고 단계마다 복사), `--stages fixture|real|fixture,real`(기본 둘 다), `--out`(기본 `docs/qa/m27-precedents-<YYYYMMDD>/acceptance`), `--code-root`, `--build`.
- `fixture`: 표시된 합성 전례 세트(`backend/tests/fixtures/precedent/t8/build_qa_set.py`를 하위 프로세스로, 지어낸 accession·PMID·`move_id`, `SYNTHETIC-PROVENANCE-t8.md`)로 `fixture-empty`(세트 없음) → 세트 A 설치 → `fixture-maps`(공개 1MQ4와 파생 두 체인 1MQ4로 클릭해 만든 실제 M15 번호 대응) → 백엔드를 멈추고 실제 번호 대응에서 mapped 행 accession만 바꾼 합성 파생 번호 대응 저장 → `fixture-main`(스냅샷 블록, 요청 기본값, 체인 미리 상태, 입장 거절 다섯, 체인 상태 셋, 체인 선택, 표적 상태 셋과 표적 탭, `moves_flagged` 토글, 필터·검색·정렬·쪽, 상세, 고정 문장, 429 크기 거절, 보고서, 결과 목록, dry-run run, 다른 탭 불변, 문구, 0으로 보이지 않음) → `active.json`을 치움 → `fixture-unset` → 되돌리고 세트 파일 하나를 변조 → `fixture-invalid` → 세트 B(같은 레코드, 다른 `imported_at`) → `fixture-stale`.
- `real`: 실제 `kbase_kinase` `dist/`를 가져오기 명령(`--from <kbase> --dest <root>/real/precedent_reference --yes`)으로 소켓을 막고 시도를 세는 자식 프로세스에서 두 번 설치해 행 수·`verification`·`dirty`·두 설치의 파일 SHA-256 같음을 기록한 뒤, `real-maps`(공개 구조 1MQ4·1M17·1FIN 체인 A·C의 M15 번호 대응을 클릭으로. 1FIN B·D는 M15가 쓸 방법이 없어 넣으면 호출 전체가 실패하므로 넣지 않음) → 1FIN 번호 대응의 두 체인에 `P00533`·`Q06187`을 준 표시된 합성 크기 시험 변형 하나(1 MiB 초과로 거절, 저장 안 됨) → `real-main`을 돈다.
- `acceptance`는 두 단계가 이번 실행에서 모두 돌고 통과했고, 모든 사례가 통과했고, 모든 흐름 행의 브라우저 비-loopback 요청과 제공자 호출이 0이고, 가져오기가 소켓을 쓰지 않았고, 참조 폴더 변경이 의도대로였고, 실제 kbase 문구가 커밋 증거에 없고, 빌드 도장이 현재 프런트엔드 소스이고, 남은 작업 프로세스·8000/3000 포트가 없을 때만 참이다.
- 커밋 증거(`--out`)는 텍스트만이다(요약, 사례 목록, 해시 목록, Git 제외 파일 목록과 해시, 단계 기록, 합성 fixture 단계 결과). 스크린숏·paint 프레임·보고서 다운로드·실패 화면 HTML·256 KiB 초과 텍스트(결정 0020)와 실제 kbase 문구가 든 텍스트는 Git 제외 artifacts 폴더에만 두고 경로·크기·SHA-256만 남긴다. 실제 문구 검사는 설치된 세트에서 모은 문자열(메모리에만)과 비교하며 공백을 접고 대소문자를 무시해 40자 조각 또는 24–39자 전체를 찾는다(JSON `\uXXXX`·Markdown·HTML 이스케이프 안까지).
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `node frontend/tests/offscreen/kinase-precedents-flow.cjs --mode <empty|maps|main|unset|invalid|stale> --artifacts <디렉터리> [--plan <json>] [--runs <runA,runD>] [--set-hash <활성 세트>] [--previous-set-hash <해시>]`(npm 스크립트 없음, `empty` 밖은 `--plan` 필수, `unset`·`invalid`·`stale`은 `--runs`·`--set-hash`, `stale`은 `--previous-set-hash`도 필요, `--url` 기본 `http://127.0.0.1:3000`, loopback만). plan 파일과 참조 폴더 변경은 실행기가 만든다.
- 회귀: 이 실행기에는 `--regressions`가 없다. M26 실행기 `--stages fixture`와 M25 실행기 `--phase fixture --regressions`(실호출 0)로 M26 → M13 사슬을 돌린다. **M13–M26 실행기는 `MW_PRECEDENT_REFERENCE_DIR`·`MW_REACTION_REFERENCE_DIR`를 넘기지 않아 백엔드가 코드 루트의 기본 폴더 `.deps/precedent_reference`·`.deps/reaction_reference`를 읽으므로, 회귀 동안 두 폴더를 없는 채로 둔다**(시작 전에 `ls .deps/precedent_reference .deps/reaction_reference`가 둘 다 없음을 기록하고 사슬이 끝날 때까지 기본 폴더에 가져오기를 하지 않는다. 실제 세트를 기본 위치에 두면 지식 탭의 새 영역 글자가 기계마다 달라질 수 있다). 기본 폴더에 세트를 둔 채 돌려야 한다면 그 실행기들의 `child_env`에 빈 격리 폴더의 변수 한 줄씩을 더하는 것이 최소 변경이다(착수 확인 (f)).
- 2026-10-10 증거: `docs/qa/m27-precedents-20261010/`(착수 확인 `preflight.md`·측정 시제품 `kbase_check.py`, 요청 장부 `network-ledger.txt`(RCSB 2줄), 게이트 `gate.txt`, 수락 `acceptance/`(사례 46/46, `acceptance: true`, 브라우저 비-loopback 요청 0, 가져오기 소켓 시도 0, 두 설치 파일 SHA-256 같음), 회귀 `regression-chain.txt`·`regression/m26/`·`regression/m25/`·`regression/m13-regression/` … `m24-regression/`). M26 fixture 단계 39/39, M25 실행기 사슬 M24(fixture)–M13 전부 통과였고 회귀 동안 두 기본 폴더는 없었다. M25 실행기는 증거를 먼저 내보낸 뒤 사슬을 돌리므로 사슬 단계 결과는 `regression/m25/`가 아니라 `regression-chain.txt`에 있다. 큰 텍스트 증거(54개)는 결정 0020대로 `frontend/tests/offscreen/artifacts/m27-final/export-full/`로 옮겼다.
- 게이트 항목은 위 "검증 명령"에 `node --check frontend/tests/offscreen/kinase-precedents-flow.cjs`와 `scripts/test_import_precedent_snapshots.py`·`scripts/test_m27_offscreen_acceptance.py`가 더해진 것이다.

### M28 종단 수락 QA

주 체크아웃(`.deps`와 `frontend/node_modules`가 있는 곳)에서, 8000·3000 포트가 비어 있는 상태에서 실행한다. QA 서비스는 한 번에 하나이고 다른 QA·설치 시험과 동시에 돌리지 않는다. 실행기 `scripts/m28_offscreen_acceptance.py`가 `next start`와 단계마다 백엔드(`PYTHONPATH=<code root>/backend`, `MW_RUNS_DIR=<root>/<단계>/runs`, `MW_REFERENCE_DIR=<root>/<단계>/reference`(`--m15-reference`의 읽기 전용 복사본), `MW_REACTION_REFERENCE_DIR=<root>/<단계>/reaction_reference`(fixture 단계에 분기 A나 C가 있으면 `--reaction-set`의 격리 복사본, 아니면 빈 폴더), `MW_PRECEDENT_REFERENCE_DIR=<root>/<단계>/precedent_reference`(분기 A가 가져오기 명령으로 설치))를 직접 띄우고 끝나면 정리한다. `--build auto`(기본, `always`·`never`도 있음)는 현재 프런트엔드 소스로 도장 찍은 빌드만 재사용한다(필요하면 typecheck 뒤 build, 동시에 돌리지 않음). 분기 모듈(`scripts/m28_branch_{a,b,c}.py`)은 분기마다 새 run에서 하네스(`frontend/tests/offscreen/endtoend-{a,b,c}-flow.cjs`)를 돌리고 기대값을 입력 파일에서 독립으로 계산한다. 실행기·분기 모듈은 `mw`를 import하지 않고(고정 문장은 하위 프로세스 `scripts/m28_export_fixed_sentences.py`가 내보냄) loopback API에 GET만 보낸다(승인·한도 증액·전송은 모두 하네스의 실제 클릭).

```bash
# fixture 단계(기본, 분기 셋, 실호출 0)
.venv/bin/python scripts/m28_offscreen_acceptance.py --root runs/m28-fixture-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/<이름> \
    --kbase <절대 경로>/kbase_kinase --out docs/qa/m28-final-<YYYYMMDD>/acceptance-fixture
# live 연습(fixture 서버, 실호출 0, 실제 live 단계 전에 통과해야 함)
.venv/bin/python scripts/m28_offscreen_acceptance.py --phase live --rehearse --root runs/m28-rehearse-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/<이름>-rehearse
# 실제 live 단계(사용자가 정한 실호출 할당 안에서만, 새 --root)
.venv/bin/python scripts/m28_offscreen_acceptance.py --phase live --live-calls 2 --root runs/m28-live-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/<이름>-live --out docs/qa/m28-final-<YYYYMMDD>/acceptance-live
```

- npm 진입점: `npm --prefix frontend run test:offscreen:endtoend -- <같은 인자>`(`frontend/package.json`: `cd .. && .venv/bin/python scripts/m28_offscreen_acceptance.py`, 상대 경로 인자는 저장소 루트 기준).
- 인자: `--root`(필수, 새 폴더(없거나 빈 폴더)여야 하고 `/tmp` 아래면 거절), `--artifacts`(필수, Git 제외 폴더), `--out`(기본 `docs/qa/m28-final-<실행한 날짜>/acceptance-<단계>`, 연습은 `<root>/out-live-rehearsal`. 기본값은 실행한 날짜의 폴더이므로 착수 날 폴더 `docs/qa/m28-final-20261011/`에 모으려면 명시한다), `--phase fixture|live`(기본 fixture), `--branches`(a·b·c의 부분집합, fixture 기본 셋·live 기본 b·c. 일부 분기만 돌린 실행의 `acceptance`는 늘 거짓이고, 실제 live 단계는 b·c 둘이 아니면 거절하므로 한 분기만은 연습에서만 돌린다), `--live-calls N`(실제 live 단계는 2만 받는다: 계획이 두 바퀴라 1이면 대장을 건드리기 전에 거절. 연습은 1–2, 생략하면 2. fixture 단계에 주면 거절), `--rehearse`(live 단계만), `--kbase`(기본 `<저장소>/../kbase_kinase`, fixture 단계에 분기 A가 있으면 `dist/manifest.json`이 있어야 함, git worktree에서는 절대 경로), `--m15-reference`(기본 `.deps/reference`, `active.json`·`sets/` 필요), `--reaction-set`(기본 `.deps/reaction_qa/import2`, 보관된 M26 실제 세트. fixture 단계에 분기 A나 C가 있으면 필요), `--build auto|always|never`, `--code-root`(기본 이 저장소). `--m15-reference`·`--reaction-set`은 복사만 하고 쓰지 않으며 `--root` 안에 있으면 거절한다.
- `fixture`: 사례 A1–A8·B1–B8·C1–C7과 공통 사례 X1-A/B/C·X2–X6을 돈다. 백엔드는 M25 fixture 서버(`backend/tests/offscreen_jev_loop_fixture/server.py`: 제품 앱 그대로, 모듈 전역 `SCIENCE_GATE`만 스크립트된 `httpx.MockTransport`와 placeholder 자격 증명으로 바꾸고 `.env`를 읽지 않음)라 실호출은 0이다. 분기 A는 `--kbase`에서 M27 가져오기 명령을 소켓을 막은 자식 프로세스로 단계 격리 폴더에 설치한다(네트워크 0). 이 단계 대장에서는 정의 항목 5의 live 부분이 비어 있어 그 항목만 임시 값 `pending_live`일 수 있다.
- `live`: 새 root에서 같은 사례 코드로 선행 상태(`L-pre-B2`·`L-pre-B3`·`L-pre-B4`, `L-pre-C2`)를 다시 만든 뒤 제품 백엔드(`uvicorn mw.api.app:app`, 실제 `SCIENCE_GATE`)로 리간드 루프 활용형 한 바퀴(`L-B7`, run B)와 단백질 루프 탐색형 한 바퀴(`L-C6`, run C)만 보내고 `L-X3`·`L-X4`·`L-X6`을 본다. 시작 전에 계획이 run 기본 한도(8단위·1800초·120,000 토큰·USD 2.00·전송 10회)에 맞는지, 키가 있는지(자식 프로세스의 제품 키 해석기, 불리언만), 루트 `.env`가 0600인지(`os.lstat`만, 내용은 읽지 않음)를 확인한다. 바퀴 결과는 `completed`·`provider_failed`·`product_failed`·`not_sent`이고, 다시 시도·새 run이 없다. 단백질 바퀴(`L-C6`)는 리간드 바퀴(`L-B7`)가 dispatch 이벤트 정확히 1건으로 `completed`일 때만 보낸다(`L-B7`이 보내지 못했거나 완료되지 않았으면 `L-C6`은 `not_sent:prerequisite_failed:L-B7` 또는 `not_sent:earlier_<provider|product>_failed`이고 할당은 남는다). `completed`·`provider_failed`는 바퀴의 dispatch 이벤트가 정확히 1건일 때만 인정하고, 없거나 둘 이상이면 `product_failed`다.
- 연습(`--phase live --rehearse`): 같은 live 코드 경로를 fixture 서버로 돌린다. 제품 백엔드를 띄우지 않고, 대장은 `<root>/rehearsal-live-ledger.json`, 실호출 0이며, 키 존재 확인을 건너뛰어 제품 키 해석기를 한 번도 부르지 않는다(증거 검색은 placeholder·키 모양만). 연습 대장의 `acceptance`는 늘 거짓이고 통과 여부는 `rehearsalPassed`다(통과하면 종료 코드 0).
- 실호출 대장: 저장소 단위 `runs/m28-live-ledger.json`(주 체크아웃의 Git 제외 `runs/`, git common dir로 찾으므로 worktree에서 돌려도 같은 파일이고, 그 자리가 Git 제외가 아니면 거절). `runs/m24-live-ledger.json`·`runs/m25-live-ledger.json`은 읽지도 고치지도 않는다. live 단계는 시작 전에 대장 합계(기록된 모든 root의 `<root>/live/runs` dispatch 이벤트를 다시 셈) + 이번 계획이 2를 넘거나, `--live-calls`가 남은 양을 넘거나, 대장을 읽을 수 없으면 아무것도 시작하지 않는다. 끝나지 않은 단계는 계획 수만큼 잡아 두고 그 수가 그 단계 하네스의 실행 상한이다. 대장 읽기·쓰기는 옆 잠금 파일(`m28-live-ledger.json.lock`)로 하나씩 하고, 잠금 파일만 있고 대장이 없으면(지워진 대장) 거절한다. 대장 파일을 지우거나 고쳐 상한을 되돌리지 않는다.
- 실호출 계수: 하네스는 클릭 전마다 runs 폴더의 `jev_science_dispatch_started`를 보고 바퀴 한도(1회) 아래일 때만 전송을 누르고, 실행기는 하네스가 도는 동안 이벤트를 세어 한도를 넘으면 하네스와 백엔드를 바로 멈춘다. 바퀴를 보냈는지는 분기 앞뒤의 dispatch 이벤트 수로 정한다(하네스 자기 보고가 아님): 보냈는데 완료 결과가 없으면 `product_failed`다. `L-X3`은 브라우저 비-loopback 요청 0, 계수 = 대장 기록 = dispatch 수 ≤ 2를 본다.
- 판정: 단계마다 `<artifacts>/case-ledger.json`(`m28_case_ledger@1`: `acceptance`, `rehearsalPassed`, `cases[]`, `definition_items`, `external`, `leftover`, `trace_audit`, `unobserved` 등). `acceptance`는 그 단계의 필수 사례가 모두 `pass`(또는 닫힌 이유와 덮는 시험 이름이 있는 `not_observed`)이고, X 사례(fixture: X1-A/B/C·X2–X6, live: L 사례 전부)가 통과하고, 그 단계의 분기를 모두 돌렸고, 소스 도장 빌드이고, 작업 프로세스·fixture 서버·Electron·8000/3000 리스너가 남지 않았고, 외부 요청 판정(fixture: 브라우저 비-loopback 0·제공자 호출 0, live: 위 `L-X3`)이 맞고, runs 폴더의 모든 `run_*`이 분기에 속해 감사되었고, 내보낸 증거에서 키·placeholder·실제 kbase 문구·절대 경로가 나오지 않을 때만 참이다. 정의 항목의 최종 상태는 두 단계 대장을 합쳐서만 정한다.
- 역추적 감사(X2): 백엔드가 떠 있는 동안 `scripts/m28_trace_audit.py`가 단계의 모든 run의 저장 보고서를 GET으로 읽어 다시 열기(`/reports/selected` 200), 근거 객체 존재, 주장 필드, 참조값 출처·세트 식별자(보고서 자체에), 증거 종류 섞임을 검사한다. 어댑터가 없는 종류는 건너뛰지 않고 실패다. 점검 보고서와 `interface_sasa` 보고서는 제품이 다시 열 때 주장·Markdown을 다시 만들지 않으므로 감사 결과에 `partialProductRecheck`로 적고 A2·A3 사례의 독립 기대값으로 보완한다. Markdown 서술 속 숫자는 파싱하지 않는다.
- X4(금지 표현): 하네스가 넘긴 탭 영역 글자(`texts/*.tabtext`), 다시 연 보고서 Markdown, 증거 글자에서 핵심 금지어를 찾는다. 하위 프로세스가 내보낸 고정 문장 줄은 빼고, 제품 본문이 만드는 오탐은 실행기의 줄 단위 예외 `X4_EXCEPTIONS`(예외마다 줄 종류·사례·출처 코드·이유)로 남긴다. 분기마다 탭 글자를 하나 이상 넘기지 않으면 실패다. 커밋 증거 `x4-scan.json`에는 해시·사례·종류·길이·이유만 있고 원문 줄(`x4-lines.json`)은 Git 제외 artifacts에만 둔다.
- 증거: 커밋 증거는 텍스트만이다(결정 0020): `--out` 폴더의 `README.md`·`summary.json`·`cases.json`·`SHA256SUMS`·`binary-artifacts.json`(Git 제외 파일의 경로·크기·SHA-256)·`evidence/`(대장·흐름 행·계획, 절대 경로는 `<repo>`/`<home>`으로 바꿈). 스크린숏·paint 프레임·보고서 내려받기·실패 패널·256 KiB 초과 텍스트, 탭 글자(`*.tabtext`)와 분기 A의 참조 오류 글자(`*.held`), 실제 kbase 문구·키·placeholder·절대 경로가 남은 텍스트는 Git 제외 `--artifacts`(`frontend/tests/offscreen/artifacts/m28-final/…`)에만 두고 경로·크기·SHA-256만 남긴다. 내보낸 뒤 검색에 걸린 파일은 `<artifacts>/held-from-out/`으로 되돌린다. 실패한 시도의 폴더는 지우지 않는다. 같은 증거 폴더 `docs/qa/m28-final-<YYYYMMDD>/`(착수 날 `20261011`)에 착수 확인 `preflight.md`, 게이트, 회귀 사슬, 설치 시험(`clean-install/`), 외부 요청 장부 `network-ledger.txt`를 함께 둔다.
- 흐름만 따로 돌리려면 서비스를 띄운 뒤 `node frontend/tests/offscreen/endtoend-<a|b|c>-flow.cjs --mode <fixture|live> --artifacts <디렉터리> --plan <json> --runs-dir <백엔드 MW_RUNS_DIR> [--control <fixture control 폴더> --backend-pid <방금 띄운 fixture 서버 pid>]`(npm 스크립트 없음, 분기 A는 `fixture`만이고 `--runs-dir`가 선택이며 `--control`·`--backend-pid`는 B·C만 받는다. B·C의 `fixture`는 `--control`·`--backend-pid` 필수, `live`에 주면 연습. plan 파일은 분기 모듈이 만든다). 실제 OpenRouter로 보내는 것은 제품 백엔드에 대한 B·C `live` 모드뿐이므로 실행기의 계수·대장 없이 돌리지 않는다.

회귀 사슬(소스 고정 뒤, 종단 fixture 수락 다음, 실제 live 단계보다 먼저, 순서대로 한 번에 하나, 실호출 0):

```bash
ls .deps/precedent_reference .deps/reaction_reference    # 시작 전: 둘 다 없음을 기록
.venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m28-regress-m27-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/regress-m27 --kbase <절대 경로>/kbase_kinase \
    --stages fixture,real --out docs/qa/m28-final-<YYYYMMDD>/regression/m27
.venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m28-regress-m26-<날짜> \
    --artifacts frontend/tests/offscreen/artifacts/m28-final/regress-m26 --kbase <절대 경로>/kbase_kinase \
    --stages fixture,real --reaction-set <보관 실세트의 격리 복사> --out docs/qa/m28-final-<YYYYMMDD>/regression/m26
.venv/bin/python scripts/m25_offscreen_acceptance.py --phase fixture --regressions --kbase <절대 경로>/kbase_kinase \
    --root runs/m28-regress-m25-<날짜> --artifacts frontend/tests/offscreen/artifacts/m28-final/regress-m25 \
    --out docs/qa/m28-final-<YYYYMMDD>/regression/m25
ls .deps/precedent_reference .deps/reaction_reference    # 끝난 뒤: 둘 다 없음을 기록
```

- M25 실행기의 `--regressions`는 M24(fixture 단계) → M23 → … → M13(M8–M12 포함) 실행기를 각자 새 폴더로 돌린다. M26 실행기는 `--reaction-set` 폴더를 `<root>/real/reaction_reference`로 다시 복사해 읽기만 한다.
- M13–M26 실행기는 `MW_PRECEDENT_REFERENCE_DIR`·`MW_REACTION_REFERENCE_DIR`를 넘기지 않아 백엔드가 기본 폴더를 읽으므로, 사슬 동안 `.deps/precedent_reference`·`.deps/reaction_reference`를 없는 채로 두고 기본 폴더에 가져오기를 하지 않는다(M27 수락 QA의 회귀 절과 같음). M28 실행기도 X6에서 두 기본 폴더가 끝날 때 없어야 통과한다.
- 사례 수가 M27 기록(`docs/tracking/m27-acceptance.md` 회귀 절)과 다르면 이유를 적는다. 옛 하네스·실행기를 고쳐야 하면 바뀐 기대만 최소로 고치고 이유를 `regression-harness-changes.txt`에 적은 뒤 영향받는 단계를 다시 돈다.

새 컴퓨터 설치 시험(README의 명령만 따라 하는지 확인):

- 깨끗한 폴더 `runs/m28-clean-install-<날짜>/`(Git 제외)에 고정 커밋을 로컬 `git clone`(네트워크 없음)하고, 그 폴더에서 `README.md`의 설치·실행 명령만 순서대로 따라 한다: `python3.11 -m venv .venv` → `.venv/bin/python -m pip install -e './backend[dev]'` → `npm --prefix frontend ci` → `npm --prefix frontend run build` → 백엔드·프런트엔드 기동(8000·3000, 다른 QA와 동시에 하지 않음). 이 폴더에는 원본의 `.deps`·`.env`·`runs/`·`.venv`를 가져오지 않는다.
- 확인: 모든 설치·빌드 명령의 종료 코드 0, `GET /capabilities` 응답, `backend/tests/fixtures/public_1hsg.cif` 업로드 → `POST /runs/{id}/inspect_complex` → 보고서 만들기·내려받기와 증거 검증, 선택 기능(화학·포켓·도킹·반응·전례 등)이 숫자 없이 "사용할 수 없음"과 이유로 보임, 종료 뒤 남은 프로세스·포트 없음, 원래 체크아웃의 `git status`가 시험 전과 같음. 기록은 `docs/qa/m28-final-<YYYYMMDD>/clean-install/`(명령과 종료 코드, 해결된 Python·npm 패키지 버전, 사용한 패키지·바이너리 저장소 호스트, 소요 시간).
- 선택 작업 환경(ProLIF·fpocket·qvina·도킹)은 새로 설치하지 않고, 위 "처음 설치" 아래 명령이 `scripts/setup_*.py`의 인자와 `config/` 잠금 파일 이름·항목 수와 맞는지 정적으로만 대조한다. 설치 명령이 `backend/pyproject.toml`·`frontend/package.json`·잠금 파일의 핀 변경을 요구하면 멈추고 사용자에게 묻는다.
- 지원 환경은 위 "필요 조건"의 문장 그대로다(검증은 macOS arm64 CPython 3.11에서만).

외부 요청: M28 단계의 외부 요청은 사용자가 정한 실제 JEV 호출(실제 live 단계, 합계 2회 이하)과 새 컴퓨터 설치 시험의 패키지·바이너리 저장소 내려받기(PyPI·npm 레지스트리, `npm ci` 중 Electron 설치 스크립트가 받는 실행 파일)뿐이다. fixture 단계·연습·회귀 사슬·게이트·하네스는 새 외부 요청 0이다(구조 새로 받기·M26 다시 가져오기 없음). 실호출과 설치 시험 호스트는 증거 폴더의 `network-ledger.txt`에 적는다.

공유할 때 뺄 폴더(README "데이터 보관과 공유"와 같은 목록). 다른 사람에게 주거나 압축해 공유할 때 다음을 뺀다:

- `runs/` — 사용자 run 폴더(업로드 구조·좌표·서열·이벤트·결과). 키나아제 전례 결과가 든 run 폴더와 그 보고서 내려받기에는 실제 kbase 문구가 들어 있어 공유하지 않는 자료다(KT1). 종단 QA 격리 root `runs/m28-*`(QA run, 실호출 대장 `runs/m28-live-ledger.json`, 설치 시험 폴더 `runs/m28-clean-install-<날짜>/` 포함)도 여기에 든다.
- `.deps/` — 이 컴퓨터에 설치한 작업 환경과 참조 스냅샷.
- `.env` — API 키.
- `frontend/tests/offscreen/artifacts/` — 오프스크린 QA 스크린숏·내려받기·큰 증거(`m28-final/…` 포함).

Git으로 공유하면 이 폴더들은 `.gitignore`(와 `frontend/tests/offscreen/.gitignore`)로 이미 빠지지만, 폴더를 그대로 압축할 때는 직접 빼야 한다.

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

## 업그레이드 뒤 할 일

- 단계마다 사용자가 할 일은 그 단계 완료 기록의 "업그레이드 뒤 사용자가 할 일"에 있다(예: `docs/tracking/m26-acceptance.md`의 큐 작업 재제출, `docs/tracking/m27-acceptance.md`).
- M28: 사용자가 할 데이터 이전은 없다. M28이 바꾼 제품 코드는 `backend/mw/mutation_reports.py`(M20 보고서 형식) 하나이고, 호출 키 해시 파일·결과 객체 형식·`backend/pyproject.toml`·`frontend/package-lock.json`·프런트엔드 화면 소스·`config/`는 바뀌지 않았다(`frontend/package.json`에는 npm 스크립트 `test:offscreen:endtoend` 한 줄만 더했다). 그래서 저장된 M18·M19·M21·M22·M23 결과의 자동 재사용과 큐에 있던 작업은 그대로이고, 참조 폴더·환경 변수·`.deps` 작업 환경도 바꿀 것이 없다.
- 이미 저장된 M20 변이 후보 보고서(`mutation_candidates_markdown@1`)는 참조값을 인용한 것도 지금과 같은 바이트로 다시 열리고 내려받힌다(바뀌지 않음). 업그레이드 뒤 새로 만드는 M20 보고서 중 번호 대응·주석이나 M-CSA 항목 ID를 인용하는 것만 참조 스냅샷 출처표가 든 `mutation_candidates_markdown@2`가 된다. 옛 보고서에 출처표가 필요하면 같은 후보 집합으로 보고서를 새로 만든다(옛 보고서는 그대로 남는다).

## run 데이터 백업과 보관

- 다른 사람에게 주거나 압축해 공유할 때 뺄 폴더는 위 "M28 종단 수락 QA"의 "공유할 때 뺄 폴더"(README "데이터 보관과 공유"와 같은 목록)다.
- 백업 단위는 run 디렉터리 전체(`runs/<run_id>/`)다. `events.jsonl`만 있어도 객체와 색인을 복구할 수 있지만, 복사할 때는 디렉터리 전체를 옮긴다.
- 보관 절차: 서비스를 중지 → 해당 run에 running·cleanup-pending 작업이 없는지 확인 → 디렉터리 전체를 복사 → 파일 해시 검증 → runs 루트 밖으로 이동 → 이동 위치를 기록. 되돌릴 때는 디렉터리 전체를 원래 위치로 옮긴다.
- 배포 절차는 없다. 각 구성원이 자기 컴퓨터나 혼자 쓰는 서버에 위 설치 절차를 그대로 따른다.
