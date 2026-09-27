# scripts/ — 단계 실행기, 개발 훅 테스트, 설치 스크립트

## 담당 범위
- `execute.py`: `phases/<group>/index.json` 단계 실행기. 수락 명령(argv 배열)을 셸 없이 실행하고, SHA-256으로 묶인 검토 증거를 기록하며, `--verify`로 다시 확인한다.
- `test_execute.py`, `test_codex_hooks.py`: 실행기와 `.codex/hooks/`(PreToolUse 위험 명령 차단, Stop 훅의 ruff·pytest) 테스트.
- `setup_prolif_worker.py`: M11 ProLIF 작업 프로세스 환경을 해시 잠금 wheelhouse에서 설치하는 명시적 설정 명령. 런타임에는 호출되지 않는다.

## 담당하지 않는 것
- 제품 런타임: `backend/mw`를 import하지 않고, `backend/mw`도 이 디렉터리를 import하지 않는다.
- Git: 실행기는 스테이징, 커밋, 브랜치 변경, push를 하지 않는다. 그런 코드를 추가하면 안 된다.
- 새 단계 구현: 새 작업은 `ready`→`go` 흐름으로 진행한다. `execute.py`의 기본 실행과 `--record-review`는 Codex CLI와 `gpt-6-sol`/`gpt-6-astra`에 고정되어 있어, 이 환경에서 새 단계 기록에 쓸 수 없다.

## 불변 조건
- `IMPLEMENTER_MODEL = "gpt-6-sol"`, `REVIEWER_MODEL = "gpt-6-astra"`를 새 모델 이름으로 바꾸지 않는다. 바꾸면 기존 검토 기록(`review.model`)과 불일치해 모든 과거 단계의 `--verify`가 실패한다. 새 흐름이 이 실행기를 써야 하는 상황이 오면, 과거 기록 호환성을 유지하는 별도 설계가 필요하다.
- 수락 명령은 argv 배열이다. 셸 래퍼(`sh -c`, `bash -lc` 등)는 거부한다. 명령은 프로젝트 루트에서 실행한다.
- 검토 증거 경로에 `.env*`, `.venv`, `references/`를 넣을 수 없다.
- 시간 초과 시 프로세스 그룹에 SIGTERM, 유예 후 SIGKILL을 보내고, 회수까지 마친 뒤 결과를 보고한다.
- 수락 명령 실패나 오래된 검토는 `completed`를 무효화하고, 단계 그룹 상태를 `error`로 만든다. 성공 결과를 미리 채워 넣지 않는다.
- `--verify`는 확인 전용으로 쓴다. 실행 전에 `phases/index.json`과 대상 그룹 `index.json`을 복사해 두고, 끝나면 복사본으로 되돌린다. 과거 단계 기록 변경을 커밋하지 않는다.
- `setup_prolif_worker.py`는 33개 wheel의 이름·SHA-256이 모두 맞고, 실행 인터프리터가 CPython 3.11 macOS arm64일 때만 설치한다. 이 확인을 느슨하게 하면 안 된다.
- Stop 훅(`.codex/hooks/stop.py`)의 pytest 세 그룹을 합치면 전체 백엔드·실행기 테스트와 같아야 한다. 그룹을 추가하거나 나눌 때 빠지는 테스트가 없게 한다. 전체 제한 600초는 `.claude/settings.json`과 `.codex/hooks.json`의 timeout과 같아야 한다.

## 테스트 지침
- `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q`
- 훅을 바꾸면 위험 명령 패턴 차단(`rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE`)과 비차단 사례, Stop 훅의 시간 초과·실패 전달·프로세스 그룹 정리를 테스트한다.
- `execute.py --dry-run`은 파일을 바꾸지 않아야 한다.
