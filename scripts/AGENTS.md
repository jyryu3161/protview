# scripts/ — 단계 실행기, 개발 훅 테스트, 설치 스크립트

## 담당 범위
- `execute.py`: `phases/<group>/index.json` 단계 실행기. 수락 명령(argv 배열)을 셸 없이 실행하고, SHA-256으로 묶인 검토 증거를 기록하며, `--verify`로 다시 확인한다.
- `test_execute.py`, `test_codex_hooks.py`: 실행기와 `.codex/hooks/`(PreToolUse 위험 명령 차단, Stop 훅의 ruff·pytest) 테스트.
- `setup_fpocket.py`: M12 fpocket 작업 환경을 `config/pockets/`의 35개 conda 패키지 해시 잠금으로 오프라인 설치하는 명시적 설정 명령(conda 필수, macOS ≥ 14.5 arm64). 테스트 `test_setup_fpocket.py`.
- M13 QA 도구(런타임에서 호출되지 않음): `m13_offscreen_acceptance.py`(분석 흐름 수락 QA 전체 실행기. 흐름·엔진 없음·M8–M10 회귀를 자기 서비스로 돌리고, M11·M12 수락 실행기 전체를 하위 루트에서 실행해 그 대장을 합친다. `mw`를 import하지 않음), `test_m13_offscreen_acceptance.py`(하위 대장 판정·`acceptance` 판정·빌드 출처 확인 단위 테스트, 서비스 없음).
- M14 QA 도구(런타임에서 호출되지 않음): `m14_offscreen_acceptance.py`(탭 수락 QA 실행기. `frontend/tests/offscreen/tabs-flow.cjs`의 `main`·`chemical` 모드를 자기 서비스로 돌리고 사례 대장을 만든다. `mw`를 import하지 않음), `test_m14_offscreen_acceptance.py`(사례 판정·`acceptance` 판정 단위 테스트, 서비스 없음). M8–M13 회귀는 이 실행기가 아니라 M13 실행기 전체로 돌린다.
- `import_reference_snapshots.py`: M15 참조 스냅샷 가져오기(사용자가 실행하는 설정 명령). `../kbase_kinase/ref`의 출처별 최신 가공 스냅샷을 해시·바이트·행 수 대조 뒤 `.deps/reference/`로 복사하고 `active.json`을 rename으로 바꾼다. 네트워크 없음, `mw`를 import하지 않음. 테스트 `test_import_reference_snapshots.py`.
- M15 QA·측정 도구(런타임에서 호출되지 않음): `m15_offscreen_acceptance.py`(번호 대응 수락 QA 실행기. `numbering-flow.cjs` 세 모드를 자기 서비스로 돌리고, 사이에 가져오기 명령과 표시된 fixture 세트 활성화를 하위 프로세스로 실행한다. `mw`를 import하지 않음), `test_m15_offscreen_acceptance.py`(판정 단위 테스트, 서비스 없음), `measure_klifs_numbering.py`(우리 KLIFS 번호 vs KLIFS `match_residues` 측정), `test_measure_klifs_numbering.py`.
- M16 QA 도구(런타임에서 호출되지 않음): `m16_offscreen_acceptance.py`(참조 주석 수락 QA 실행기. 가져오기 명령을 하위 프로세스로 실행한 뒤 `annotation-flow.cjs`의 `main`·`minimized` 모드를 자기 서비스로 돌리고 사례 19개 대장을 만든다. `mw`를 import하지 않음), `test_m16_offscreen_acceptance.py`(사례 계획·판정·`acceptance` 판정·`/tmp` 거부·`mw` 미import 단위 테스트, 서비스 없음).
- M12 QA 도구(런타임에서 호출되지 않음): `m12_offscreen_acceptance.py`(수락 QA 전체 실행기, `mw`를 import하지 않음), `m12_qa_inputs.py`(표시된 합성 잘못된 입력 2개, SHA-256 고정).
- `setup_prolif_worker.py`: M11 ProLIF 작업 프로세스 환경을 해시 잠금 wheelhouse에서 설치하는 명시적 설정 명령. 런타임에는 호출되지 않는다.
- M11 QA 도구(런타임에서 호출되지 않음):
  - `m11_qa_inputs.py`: 공개 fixture에서 합성 파생 QA 입력 3개를 결정적으로 만들고 SHA-256을 대조한다. 어긋나면 아무것도 쓰지 않고 실패한다.
  - `m11_attach_browser_setup.py`: loopback API로 run의 실제 원자 카탈로그를 읽어 연결 모드용 결합 sidecar, 매핑, 요청 JSON을 만든다. 최근접 좌표 매칭을 쓰지 않는다.
  - `m11_invalid_inputs.py`: H06용 잘못된 입력(표시된 합성 파생)과 기대하는 문제 원자를 만든다.
  - `m11_replay_probe.py`: GET 전용 replay 확인 도우미. `docs/qa/m10-comparison-20260927/commands/replay_probe.py`에서 복사했고 원본은 바꾸지 않는다.
  - `m11_offscreen_acceptance.py`: M11 수락 QA 전체 실행기(`docs/operations.md` 참고). `mw`를 import하지 않고 하위 프로세스로만 확인한다.

## 담당하지 않는 것
- 제품 런타임: `backend/mw`를 import하지 않고, `backend/mw`도 이 디렉터리를 import하지 않는다. 이름을 정한 예외는 `measure_klifs_numbering.py`와 그 테스트 `test_measure_klifs_numbering.py`뿐이다. 측정은 제품의 해석·KLIFS 표 함수를 그대로 재야 하므로 `mw`를 import한다(측정 전용, 제품 경로에서 부르지 않음). 가져오기 명령과 M15·M16 실행기는 import하지 않는다.
- Git: 실행기는 스테이징, 커밋, 브랜치 변경, push를 하지 않는다. 그런 코드를 추가하면 안 된다.
- 새 단계 구현: 새 작업은 `ready`→`go` 흐름으로 진행한다. `execute.py`의 기본 실행과 `--record-review`는 Codex CLI와 `gpt-6-sol`/`gpt-6-astra`에 고정되어 있어, 이 환경에서 새 단계 기록에 쓸 수 없다.

## 불변 조건
- `IMPLEMENTER_MODEL = "gpt-6-sol"`, `REVIEWER_MODEL = "gpt-6-astra"`를 새 모델 이름으로 바꾸지 않는다. 바꾸면 기존 검토 기록(`review.model`)과 불일치해 모든 과거 단계의 `--verify`가 실패한다. 새 흐름이 이 실행기를 써야 하는 상황이 오면, 과거 기록 호환성을 유지하는 별도 설계가 필요하다.
- 수락 명령은 argv 배열이다. 셸 래퍼(`sh -c`, `bash -lc` 등)는 거부한다. 명령은 프로젝트 루트에서 실행한다.
- 검토 증거 경로에 `.env*`, `.venv`, `references/`를 넣을 수 없다.
- 시간 초과 시 프로세스 그룹에 SIGTERM, 유예 후 SIGKILL을 보내고, 회수까지 마친 뒤 결과를 보고한다.
- 수락 명령 실패나 오래된 검토는 `completed`를 무효화하고, 단계 그룹 상태를 `error`로 만든다. 성공 결과를 미리 채워 넣지 않는다.
- `--verify`는 확인 전용으로 쓴다. 실행 전에 `phases/index.json`과 대상 그룹 `index.json`을 복사해 두고, 끝나면 복사본으로 되돌린다. 과거 단계 기록 변경을 커밋하지 않는다.
- `setup_fpocket.py`는 35개 archive의 이름·SHA-256, 플랫폼, 실행 파일 해시가 모두 맞을 때만 설치를 완료로 둔다. 이 확인을 느슨하게 하면 안 된다.
- M15 실행기는 M13 실행기의 빌드 도장·환경·경로 가리기·포트 확인 함수를 import해 쓴다(M14와 같음). 수락 참조 폴더는 `<root>/reference`(`MW_REFERENCE_DIR`)이며 실제 `.deps/reference`를 건드리지 않는다. `acceptance`는 모든 단계가 이번 실행에서 돌고 두 참조 변경이 성공했을 때만 true다.
- M16 실행기는 M13 실행기(빌드 도장·환경 허용 목록·포트·경로 가리기)와 M15 실행기(서비스·빌드·참조 가져오기·증거 내보내기)를 import해 쓴다. 두 실행기의 이 함수들을 바꾸면 M16 수락도 바뀌므로 세 실행기의 단위 테스트를 함께 돌린다. 수락 참조 폴더는 `<root>/reference`이고 실제 `.deps/reference`를 건드리지 않는다. `acceptance`는 모든 단계가 이번 실행에서 돌고 가져오기가 성공했으며 모든 사례 통과, 외부 요청 0건·제공자 호출 0회, 소스 도장 빌드, 남은 프로세스 없음일 때만 true다. 흐름의 픽셀 검사가 쓰는 범례 영역은 제품의 `wrapLegendText`와 같은 기하를 따른다(`docs/engineering-notes.md`).
- `import_reference_snapshots.py`는 kbase 매니페스트와 SHA-256·바이트·행 수가 모두 맞을 때만 새 세트를 활성화하고, 실패하면 `--dest`를 바꾸지 않는다. 이전 세트 폴더를 지우는 코드를 넣지 않는다.
- 수락 실행기(M11·M12·M13·M14·M15·M16)의 남은 프로세스 확인은 작업 폴더가 수락 루트 안인 프로세스만 센다(같은 컴퓨터의 다른 pytest를 잡지 않도록). M11 실행기도 M13에서 같은 방식으로 좁혔다.
- M13 실행기는 하위 실행기 대장을 schema별로 판정한다(`sub_ledger_verdict`: M11은 `summary`·`nonLoopbackRequestsTotal`, M12는 `verdict`·`externalRequestsTotal`). 외부 요청 수를 모르는 행이 있으면 실패다. `--only`는 `partial_not_acceptance`이며 증거를 내보내지 않는다. 서비스는 `PYTHONPATH=<code root>/backend`로 띄우고 `import mw` 경로를 먼저 확인한다.
- M14 실행기는 M13 실행기를 import해 빌드 도장(`build_is_current`·`stamp_build`), 서비스 환경(`child_env`), 경로 가리기(`redact`), 포트 확인(`listening`)을 그대로 쓴다. M13 실행기의 이 함수들을 바꾸면 M14 수락도 바뀌므로 두 실행기의 단위 테스트를 함께 돌린다. M14의 `acceptance`는 모든 사례가 돌고 통과했으며 빌드가 현재 소스 도장과 맞을 때만 true다.
- `setup_prolif_worker.py`는 33개 wheel의 이름·SHA-256이 모두 맞고, 실행 인터프리터가 CPython 3.11 macOS arm64일 때만 설치한다. 이 확인을 느슨하게 하면 안 된다.
- Stop 훅(`.codex/hooks/stop.py`)의 pytest 세 그룹을 합치면 전체 백엔드·실행기 테스트와 같아야 한다. 그룹을 추가하거나 나눌 때 빠지는 테스트가 없게 한다. 전체 제한 600초는 `.claude/settings.json`과 `.codex/hooks.json`의 timeout과 같아야 한다.

## 테스트 지침
- `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py scripts/test_m13_offscreen_acceptance.py scripts/test_m14_offscreen_acceptance.py scripts/test_import_reference_snapshots.py scripts/test_m15_offscreen_acceptance.py scripts/test_measure_klifs_numbering.py scripts/test_m16_offscreen_acceptance.py -q`
- 훅을 바꾸면 위험 명령 패턴 차단(`rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE`)과 비차단 사례, Stop 훅의 시간 초과·실패 전달·프로세스 그룹 정리를 테스트한다.
- `execute.py --dry-run`은 파일을 바꾸지 않아야 한다.
