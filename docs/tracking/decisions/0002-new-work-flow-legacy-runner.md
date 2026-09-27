# 0002. 새 작업은 ready→go 흐름, 기존 단계 실행기는 과거 검증 전용

- 상태: 채택 (2026-09-27)

## 배경
`scripts/execute.py`는 `codex exec --model gpt-6-sol/gpt-6-astra`를 호출하고, Codex 훅 신뢰 해시를 사전에 확인하며, 검토자 모델이 `gpt-6-astra`가 아니면 기록을 거부한다. M0–M10 단계 기록(`phases/*/index.json`)은 이 실행기가 파일 SHA-256으로 묶어 둔 검토 증거에 의존한다.

## 결정
M11부터 새 작업은 `ready` → `go` 흐름(Opus 5.5 구현·검토 서브에이전트)으로 진행한다. 기존 실행기는 수정하지 않고, 끝난 단계의 `--verify`와 `--dry-run`에만 쓴다.

## 검토한 대안
- 실행기를 Claude용으로 고쳐 계속 쓰기: `phases/` 형식은 유지할 수 있지만, 실행기·훅 테스트(`scripts/test_execute.py`)를 대거 고쳐야 한다. 과거 기록과 새 기록이 같은 코드를 쓰게 되어, 과거 검증 로직이 바뀔 위험도 있다.
- 둘 다 쓰기: 수락 확인을 두 체계에서 이중으로 관리하게 된다.

## 결과
- 진행 중인 M11의 `phases/protview-chemical-interactions/` 기록은 pending 상태로 남는다. M11 완료 판정은 새 흐름의 검증과 독립 검토로 하고, 이 실행기로 `completed`를 기록할 수는 없다.
- `.claude/commands/harness.md`, `review.md`는 옛 역할을 전제로 하므로 새 작업에 쓰지 않는다.
- 이 실행기로 만든 과거 단계 기록은 공유 파일이 바뀌면 오래된 상태가 된다. 해시를 고쳐 통과시키지 않는다.
