# ProtView

로컬 PDB/mmCIF 구조를 불러와 전처리하고, Mol*로 보고, 실제 좌표로 계산한 결과(기하 접촉·SASA·단백질 전위·원자 거리·강체 정렬·화학 상호작용·포켓 후보·도킹·변이 구조 모델 등)를 근거가 필드 단위로 연결된 보고서로 남기는 단일 사용자 작업 공간입니다. 연구실·팀 구성원이 각자 자기 컴퓨터나 혼자 쓰는 서버에 설치해 씁니다(로그인·계정·권한 분리가 없습니다). FastAPI 백엔드(Python 3.11)와 Next.js 프런트엔드로 이루어져 있고, 기본 작업은 네트워크나 API 키 없이 끝납니다.

계산 결과는 바뀌지 않는 객체 handle과 run 이벤트 기록에 연결되고, 저장된 결과와 보고서는 도구를 다시 실행하지 않고 다시 열립니다. 구현하지 않았거나 설치되지 않은 기능은 숫자 없이 "사용할 수 없음"과 이유로 보입니다.

M0–M27 단계를 마쳤습니다. 단계별 기능·검증 기록과 진행 중인 단계는 [진행 현황](docs/tracking/status.md)과 [로드맵](docs/tracking/roadmap.md)에 있습니다.

## 화면 구성 (탭 네 개)

| 탭 | 하는 일 |
|---|---|
| 구조 분석 | 구조 올리기(`.pdb`·`.cif`·`.mmcif`, 25 MiB까지)와 모델 불러오기, 전처리(altloc·물·수소 정책), Mol* 뷰어와 잔기 선택, 리간드 인스턴스와 단백질의 기하 접촉(Å), 단백질–리간드 SASA(FreeSASA, Å²), OpenMM 단백질 전용 최소화(kJ/mol), 원자 거리와 두 구조 CA 정렬, 저장된 보기와 PNG + 출처 JSON 그림, 뷰어 요청(로컬 명령, 온라인 해석을 허용한 run에서만 자연어), 화학 상호작용(ProLIF, 화학 작업 화면), 포켓 후보(fpocket), 로컬 규칙 분석 흐름(M13), kinase 참조 주석(KLIFS 주요 부위 10개, M16) |
| 단백질 공학 | 변이 후보 집합(위치와 바꿀 잔기의 조합, 근거 있는 보호 잔기와 잔기 단위 해제, M20), 변이 구조 모델링(PDBFixer + OpenMM으로 야생형 기준과 변이형을 각각, 같은 조건 도킹 짝, M21), 서열 GA 설계(M23), JEV 설계 루프 단백질 갈래(M25) |
| 리간드 설계·탐색 | 리간드 후보(부모 SDF 한 부위의 고정 교체·사용자 반응 SMARTS, "RDKit 추정값" 속성·"구조 경고 일치" PAINS·저장값 필터, M17), 단독 도킹(QuickVina 2.1, M18), 일괄 도킹(M19), 리간드 GA 설계(M22), JEV 설계 루프 리간드 갈래(M25) |
| 지식·보고서 | 잔기 번호 대응(SIFTS·KLIFS 참조값, M15), 효소 반응 지식(M-CSA·UniProt·Rhea 참조값, M26), 키나아제 전례(kbase_kinase가 논문에서 기계로 추출한 미검수 기록, M27), JEV 판정(과학 전송, M24), run 전체 보고서·그림·흐름 요약 목록(M14) |

값은 실제 엔진 실행 결과를 고유 단위로만 보입니다. 기하 접촉은 거리 기준 근접이며 수소결합 판정이 아닙니다. 도킹 점수는 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"이고, OpenMM 전위는 각 구조의 값일 뿐 두 구조를 빼거나 비교하지 않습니다. 참조값(번호 대응·KLIFS·반응 지식·전례)은 계산값과 섞지 않고 출처와 함께 보입니다. GA·JEV 결과의 정렬과 선택은 순위·추천이 아닙니다. PyRosetta처럼 구현·검증된 엔진이 없는 기능은 사용할 수 없음으로 표시됩니다. `/gallery`는 디자인 예시이며 과학 결과가 아닙니다. 방법별 의미·단위·한계는 [과학·도메인 규칙](docs/business-rules.md)에 있습니다.

비싼 계산(OpenMM 최소화, 화학 상호작용, 포켓, RDKit 작업, 도킹, 변이 구조 모델링, GA)은 run의 첫 비싼 계산 승인 뒤 작업 큐에서 돌고 run 예산에서 단위를 씁니다. 새 run의 기본 예산은 `config/default.yaml`(활동 시간 1800초, 비싼 계산 8회, 외부 토큰 120,000, USD 2.00)입니다. 한도 증액은 일괄 도킹·리간드 GA·서열 GA 화면에서 사람이 누를 때만 부족분만큼 올라갑니다. 같은 입력·인자로 저장된 결과가 있으면 다시 계산하지 않고 그 결과를 씁니다(예: 일괄 도킹·GA의 재사용 행은 과금하지 않음).

## 설치와 실행

전제:

- Python 3.11 이상(`backend/pyproject.toml`). 설치는 `python3.11`로 가상환경을 만듭니다. 선택 작업 환경(아래)의 설치 스크립트는 `.venv`의 인터프리터가 CPython 3.11일 때만 동작하고, `python3`은 다른 버전을 가리킬 수 있습니다(3.10이면 백엔드 설치가 실패합니다).
- Node.js 22 이상과 npm.
- 검증한 환경: macOS arm64, CPython 3.11.11, Node.js 24.3.0, npm 11.4.2.
- 설치할 때만 네트워크가 필요합니다(PyPI, npm 레지스트리). 오프스크린 QA에 쓰는 Electron 실행 파일은 제품 실행에 필요 없고 `npm ci`가 받지 않습니다. QA를 처음 돌릴 때나 `npx install-electron --no`가 GitHub의 Electron 릴리스에서 받습니다(이 컴퓨터에 캐시가 있으면 받지 않습니다).

프로젝트 루트에서 순서대로 실행합니다.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
```

터미널 두 개에서, 둘 다 프로젝트 루트에서 백엔드와 프런트엔드를 실행합니다.

```bash
.venv/bin/python -m uvicorn mw.api.app:app --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend run start -- -p 3000
```

브라우저에서 <http://127.0.0.1:3000>을 엽니다. 프런트엔드는 `/api/*`를 `http://127.0.0.1:8000`으로 전달합니다. 두 서버 모두 `127.0.0.1`에만 바인딩하며 `--host 0.0.0.0`은 쓰지 않습니다. 원격 서버는 혼자 쓰는 경우에만 같은 명령으로 띄우고 SSH 포트 포워딩으로 접속합니다. 개발 중에는 `start` 대신 `npm --prefix frontend run dev`를 쓸 수 있습니다.

여기까지가 핵심 설치입니다. 선택 작업 환경(ProLIF·RDKit 작업 환경: 화학 상호작용·리간드 후보 / fpocket: 포켓 후보 / qvina와 도킹 작업 환경: 도킹·일괄 도킹·GA·같은 조건 도킹·JEV 루프 계산)과 참조 스냅샷(M15: 번호 대응 / M26: 효소 반응 지식, 공개 서버에서 받음 / M27: 키나아제 전례, 로컬 `kbase_kinase`에서 복사)은 [운영 문서](docs/operations.md)의 "처음 설치" 아래 절을 따라 따로 설치합니다. 설치하지 않은 환경을 쓰는 기능은 `/capabilities`와 화면에서 숫자 없이 "사용할 수 없음"과 이유로 보이고, 나머지 기능은 그대로 동작합니다. 환경 변수(`MW_RUNS_DIR`, 참조 폴더, API 키)는 운영 문서의 "환경 설정"에 있습니다.

## 지원 환경

- 구조 불러오기·전처리·기하 접촉·SASA·OpenMM·보고서는 POSIX 운영체제(Darwin·Linux)에서 쓰도록 설계되어 있습니다. 작업 감독이 psutil 7.2.2의 프로세스 신원 확인을 쓰므로 그 밖의 OS에서는 새 작업이 시작되지 않습니다. **검증은 macOS arm64 CPython 3.11에서만 했습니다.**
- ProLIF·fpocket·qvina·도킹 작업 환경의 잠금 파일(`config/chemical/`·`config/pockets/`·`config/docking/`)은 macOS arm64 전용이고, 설치 스크립트가 다른 플랫폼을 거부합니다. Linux·Intel Mac용 잠금은 없습니다. 그래서 그 환경에서는 화학 상호작용·포켓 후보·리간드 후보·도킹·일괄 도킹·리간드 GA·서열 GA·JEV 루프 계산이 숫자 없이 "사용할 수 없음"과 이유로 보입니다. 변이 구조 모델링(M21)의 OpenMM·PDBFixer는 프로젝트 `.venv`에 들어가 이 잠금에 묶이지 않지만, 역시 macOS arm64에서만 검증했습니다.
- 한 인스턴스는 한 사람이 자기 컴퓨터나 혼자 쓰는 서버에서 씁니다. 같은 컴퓨터의 다른 계정을 막는 장치는 없습니다([보안 정책](docs/security.md)).

## 외부 요청 정책

- 기본: 외부 요청은 아래 두 가지뿐이고, 그 밖의 구조 불러오기·계산·도구·작업·보고서·화면·테스트는 외부 요청을 하지 않습니다. 원격 구조 조회는 없고(로컬 업로드만), 브라우저는 로컬 번들 자산만 불러오며 Next.js 텔레메트리를 끕니다.
- 예외 1 — M26 반응 참조 가져오기 명령 `scripts/import_reaction_references.py`: 사용자가 터미널에서 실행할 때만 허용 호스트 셋(`www.ebi.ac.uk`·`rest.uniprot.org`·`www.rhea-db.org`)에 HTTPS GET을 보냅니다. 키·쿠키·사용자 데이터는 보내지 않습니다. M15·M27 가져오기 명령은 네트워크를 쓰지 않습니다.
- 예외 2 — JEV 모델 호출(OpenRouter `https://openrouter.ai/api/alpha/decisions`): `EgressGate` 하나만 보내고, 보내기 전에 run 이벤트에 감사 기록과 예산 예약을 남깁니다. 새 run은 항상 `local_only`로 시작하고 과학 전송 동의는 꺼져 있으며, run마다 사람이 켠 경우에만 나갑니다.
  - 온라인으로 설정한 run: 뷰어 자연어 해석(동의 한 번에 최대 4회)과 M3 보기 결정(접촉 집계 숫자만).
  - M24 과학 전송과 M25 루프 전송: run 수준 과학 전송 동의가 켜져 있고, 전송마다 사람이 미리 본 본문을 그 SHA-256으로 승인할 때만(run당 10회).
- API 키는 `OPENROUTER_API_KEY` 환경 변수나 루트 `.env`(권한 0600)에만 두고 요청 본문·이벤트·로그·보고서·커밋에 넣지 않습니다. 키가 없으면 JEV 호출 기능만 사용할 수 없습니다.
- 보낼 수 있는 내용의 허용 목록과 감사 기록 형식은 [보안 정책](docs/security.md)에 있습니다.

## 데이터 보관과 공유

run 데이터는 기본적으로 저장소 루트의 `runs/`에 쌓입니다(백엔드를 시작한 폴더 기준 상대 경로이므로 루트에서 시작합니다). 다른 위치는 백엔드 시작 전에 `MW_RUNS_DIR`로 정하고, 저장소 안의 다른 경로면 직접 `.gitignore`에 더합니다. 백업과 보관 절차는 운영 문서의 "run 데이터 백업과 보관"을 따릅니다.

다른 사람에게 주거나 압축해 공유할 때는 다음을 뺍니다.

- `runs/` — 사용자 run 폴더(업로드 구조·좌표·서열·이벤트·결과). 키나아제 전례 결과가 든 run 폴더와 그 보고서 다운로드에는 실제 kbase 문구가 들어 있어 공유하지 않는 자료입니다(이용 조건 문구 KT1: "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인").
- `.deps/` — 이 컴퓨터에 설치한 작업 환경과 참조 스냅샷.
- `.env` — API 키.
- `frontend/tests/offscreen/artifacts/` — 오프스크린 QA 스크린숏·다운로드·큰 증거.
- 수락·종단 QA 실행기가 `--root`로 받은 격리 폴더(보통 `runs/` 아래).

Git으로 공유하면 이 폴더들은 `.gitignore`(와 `frontend/tests/offscreen/.gitignore`)로 이미 빠지지만, 폴더를 그대로 압축할 때는 직접 빼야 합니다. `.venv/`·`frontend/node_modules/`·`frontend/.next/`는 이 컴퓨터용 설치 산출물이므로 받는 쪽에서 위 설치 순서로 다시 만듭니다.

## 검증

전체 게이트(백엔드·스크립트 pytest, ruff, 오프스크린 하네스 `node --check`, 프런트엔드 시험·typecheck·build)는 [필수 규칙](docs/standards.md)의 "검증 게이트"에, Stop 훅 그룹·오프스크린 UI 검증·단계별 수락 QA 실행기는 [운영 문서](docs/operations.md)에 있습니다. 대표 명령은 다음과 같습니다.

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

- typecheck와 build는 같은 빌드 산출물을 쓰므로 동시에 돌리지 않고 순서대로 실행합니다.
- 과학 엔진 시험(ProLIF, fpocket, RDKit, qvina 도킹, 일괄 도킹, GA 등)은 해당 선택 작업 환경이 없으면 skip이 아니라 실패합니다. 그래서 핵심 설치만 한 컴퓨터에서는 `backend/tests` 전체가 통과하지 않습니다. `backend/tests/test_klifs_numbering.py`의 실제 스냅샷 시험 2개는 `../kbase_kinase/ref`(또는 `MW_KBASE_REF`)가 없으면 skip됩니다.
- UI 검증은 실제 Electron 오프스크린 렌더러에서 실제 입력으로 합니다(운영 문서 "오프스크린 UI 검증").

## 문서

- 프로젝트 개요와 필수 규칙 요약: [CLAUDE.md](CLAUDE.md)(= [AGENTS.md](AGENTS.md)), 전체 규칙 [docs/standards.md](docs/standards.md)
- 구조와 규칙: [시스템 구조](docs/system-architecture.md), [과학·도메인 규칙](docs/business-rules.md), [API 계약](docs/contracts.md), [보안 정책](docs/security.md), [운영](docs/operations.md), [알려진 함정](docs/engineering-notes.md)
- 상태와 결정: [진행 현황](docs/tracking/status.md), [로드맵](docs/tracking/roadmap.md), [결정 기록](docs/tracking/decisions/index.md), [미해결 문제](docs/tracking/findings.md), 단계 완료 기록 `docs/tracking/m11-acceptance.md` … [`m27-acceptance.md`](docs/tracking/m27-acceptance.md)
- 모듈 안내: [backend/AGENTS.md](backend/AGENTS.md), [frontend/AGENTS.md](frontend/AGENTS.md), [scripts/AGENTS.md](scripts/AGENTS.md)
- 과거 기록(수정·이동 금지): M0–M13 원본 설계·계약·검토(대문자 `docs/*.md`), 단계 실행기 기록 [phases/index.json](phases/index.json)(끝난 단계의 `--verify`는 운영 문서 "과거 단계 재검증"), 원본 참고 자료 `agent_protein_viewer_plan_v05.md`·`molecular-workspace.zip`·`references/molecular-workspace/`
