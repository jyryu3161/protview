# 0018. M13 완료도 새 흐름 문서에 기록하고 옛 단계 폴더는 그대로 둔다

- 상태: 채택 (사용자 결정 2026-09-29, M13 명세 확정 때)

## 배경
`phases/protview-workflows/`에는 옛 실행기용 `step0.md`만 있고 index가 없다. step0은 index 생성, argv 저장, `--verify`, GPT-6 Astra 승인 기록을 요구하지만, 옛 실행기는 Opus 5.5 검토를 기록할 수 없다(결정 0002). M12도 같은 이유로 새 흐름 문서에 기록했다(결정 0016).

## 결정
- M13 완료는 `docs/tracking/m13-acceptance.md`와 `docs/qa/m13-workflows-20260929/`(최종)·`docs/qa/m13-workflows-20260929-run1/`(1차 실패 실행)에 기록한다.
- `phases/protview-workflows/`에 index를 만들거나 `step0.md`를 고치지 않는다. step0의 index·argv 저장·Astra 검토·`--verify` 절은 적용하지 않는다.
- step0이 정한 파일 이름(`backend/tests/test_analysis_workflows.py`, `frontend/tests/offscreen/workflows-flow.cjs`)은 따른다.

## 결과
- `scripts/execute.py --verify`로 M13을 확인할 수 없다. 현재 기준 검증은 완료 기록과 QA 증거가 대신한다(M11·M12와 같은 방식, 결정 0014·0016).
