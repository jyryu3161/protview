# 0014. M11 완료는 새 흐름 문서에 기록하고 옛 단계 기록은 pending으로 둔다

- 상태: 채택 (사용자 결정 2026-09-28)

## 배경
`phases/protview-chemical-interactions/index.json`은 옛 실행기 형식이다. 여기에 `completed`를 적으면 GPT-6 Astra 검토를 받은 것처럼 보이지만, M11은 Opus 5.5 서브에이전트가 검토했다(결정 0002).

## 결정
옛 단계 기록 파일과 `phases/index.json`은 pending 그대로 둔다. M11 완료 판정, 두 독립 검토(코드·증거)의 판정과 검토한 파일 해시, 게이트 결과는 `docs/tracking/m11-acceptance.md`와 `docs/qa/m11-chemical-20260928/`에 기록한다.

## 검토한 대안
- 옛 목록에서 M11 항목 제외: 목록이 실제 진행 이력과 달라진다.
- `blocked`로 표시: 막힌 것이 아니라 다른 흐름으로 끝난 것이다.

## 결과
- `scripts/execute.py protview-chemical-interactions --verify`는 계속 pending을 보여 준다. M11 상태는 이 결정과 완료 기록 문서로 판단한다.
