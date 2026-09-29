# 0016. M12 완료도 새 흐름 문서에 기록하고 옛 단계 폴더는 그대로 둔다

- 상태: 채택 (사용자 결정 2026-09-28, M12 계획 확정 때)

## 배경
`phases/protview-pockets/`에는 옛 실행기용 `step0.md`만 있고 index가 없다. 옛 실행기는 GPT-6 Astra 검토만 기록할 수 있어 Opus 5.5 검토를 기록할 수 없다(결정 0002).

## 결정
- M12 완료는 `docs/tracking/m12-acceptance.md`와 `docs/qa/m12-pockets-20260929/`에 기록한다.
- `phases/protview-pockets/`에 index를 만들거나 기존 파일을 고치지 않는다.

## 결과
- `scripts/execute.py --verify`로 M12를 확인할 수 없다. 현재 기준 검증은 완료 기록과 QA 증거가 대신한다(M11과 같은 방식, 결정 0014).
