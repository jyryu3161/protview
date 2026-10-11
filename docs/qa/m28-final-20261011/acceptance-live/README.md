# M28 종단 실데이터 수락 증거 (live)

- 생성: 2026-10-11T18:46:25.479809+00:00 · acceptance **true**
- 요청한 분기: b, c (분기 일부만 돌리면 acceptance는 늘 false)
- 소스: ec21309dce08a59bc431cdb78e0969fca608eaec · 작업 트리 변경 0개
- 외부 요청: {"browser_non_loopback_requests": 0, "provider_calls": null, "live_calls_counted": 2, "dispatchEvents": 2, "product_key_resolver_calls": 1}
- 남은 프로세스·포트: {"processes": [], "ports": []}
- 역추적 감사: {"status": "pass", "reportCount": 8, "byKind": {"jev_loop": 2, "ligand_candidates": 1, "ligand_docking": 1, "ligand_docking_batch": 1, "mutation_candidates": 1, "mutation_model": 1, "openmm_protein_minimize": 1}, "checks": {"reopen": {"pass": 8, "fail": 0, "not_checked": 0}, "evidence_exists": {"pass": 8, "fail": 0, "not_checked": 0}, "claim_fields": {"pass": 8, "fail": 0, "not_checked": 0}, "reference_source": {"pass": 8, "fail": 0, "not_checked": 0}, "no_mixing": {"pass": 8, "fail": 0, "not_checked": 0}}, "partialProductRecheck": [], "noReports": false, "failures": 0}

## 정의 항목

| 항목 | 이름 | 상태 | 사례 |
|---|---|---|---|
| 1 | 구조 분석 | None | A1, A2, A3, A4, A6 |
| 2 | 지식 | None | A5, A6, A7, A8 |
| 3 | 리간드 설계·탐색 | None | B2, B3, B4 |
| 4 | 단백질 공학 | None | C1, C2, C3 |
| 5 | GA·JEV | pass | B5, B6, B7, C4, C5, C6, L-B7, L-C6 |
| 6 | 보고서 | None | A2, A3, A4, A5, A6, A7, A8, B8, C7, X1-A, X1-B, X1-C, X2 |

## 사례

| 사례 | 분기 | 상태 | 이유 |
|---|---|---|---|
| L-pre-B2 | b | pass |  |
| L-pre-B3 | b | pass |  |
| L-pre-B4 | b | pass |  |
| L-pre-C2 | c | pass |  |
| L-B7 | b | pass |  |
| L-C6 | c | pass |  |
| L-X3 | x | pass |  |
| L-X4 | x | pass |  |
| L-X6 | x | pass |  |

## 관찰하지 못한 사례

- 해당 없음

Git 제외로 둔 텍스트 2개(경로·크기·SHA-256은 binary-artifacts.json). 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

