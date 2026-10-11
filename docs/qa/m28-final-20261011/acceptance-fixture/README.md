# M28 종단 실데이터 수락 증거 (fixture)

- 생성: 2026-10-11T17:25:02.852324+00:00 · acceptance **true**
- 요청한 분기: a, b, c (분기 일부만 돌리면 acceptance는 늘 false)
- 소스: 8e96c1421cb81839eb82dcca1f44e0843a561c26 · 작업 트리 변경 0개
- 외부 요청: {"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": null, "dispatchEvents": 6, "product_key_resolver_calls": 0}
- 남은 프로세스·포트: {"processes": [], "ports": []}
- 역추적 감사: {"status": "pass", "reportCount": 28, "byKind": {"chemical_interactions": 1, "inspection": 1, "interface_sasa": 1, "jev_choice": 2, "jev_loop": 4, "kinase_precedents": 2, "ligand_candidates": 1, "ligand_docking": 1, "ligand_docking_batch": 1, "ligand_ga": 2, "mutation_candidates": 2, "mutation_model": 1, "openmm_protein_minimize": 1, "pocket_detection": 1, "reaction_knowledge": 3, "reference_site_annotation": 1, "residue_numbering": 1, "sequence_ga": 2}, "checks": {"reopen": {"pass": 28, "fail": 0, "not_checked": 0}, "evidence_exists": {"pass": 28, "fail": 0, "not_checked": 0}, "claim_fields": {"pass": 28, "fail": 0, "not_checked": 0}, "reference_source": {"pass": 28, "fail": 0, "not_checked": 0}, "no_mixing": {"pass": 28, "fail": 0, "not_checked": 0}}, "partialProductRecheck": [{"kind": "inspection", "note": "제품 재계산 전제 불성립: no claim revalidation, no Markdown regeneration"}, {"kind": "interface_sasa", "note": "제품 재계산 전제 불성립: no Markdown regeneration"}], "noReports": false, "failures": 0}

## 정의 항목

| 항목 | 이름 | 상태 | 사례 |
|---|---|---|---|
| 1 | 구조 분석 | pass | A1, A2, A3, A4, A6 |
| 2 | 지식 | pass | A5, A6, A7, A8 |
| 3 | 리간드 설계·탐색 | pass | B2, B3, B4 |
| 4 | 단백질 공학 | pass | C1, C2, C3 |
| 5 | GA·JEV | pending_live | B5, B6, B7, C4, C5, C6, L-B7, L-C6 |
| 6 | 보고서 | pass | A2, A3, A4, A5, A6, A7, A8, B8, C7, X1-A, X1-B, X1-C, X2 |

## 사례

| 사례 | 분기 | 상태 | 이유 |
|---|---|---|---|
| A1 | a | pass |  |
| A2 | a | pass |  |
| A3 | a | pass |  |
| A4 | a | pass |  |
| A5 | a | pass |  |
| A6 | a | pass |  |
| A7 | a | pass |  |
| A8 | a | pass |  |
| B1 | b | pass |  |
| B2 | b | pass |  |
| B3 | b | pass |  |
| B4 | b | pass |  |
| B5 | b | pass |  |
| B6 | b | pass |  |
| B7 | b | pass |  |
| B8 | b | pass |  |
| C1 | c | pass |  |
| C2 | c | pass |  |
| C3 | c | pass |  |
| C4 | c | pass |  |
| C5 | c | pass |  |
| C6 | c | pass |  |
| C7 | c | pass |  |
| X1-A | a | pass |  |
| X1-B | b | pass |  |
| X1-C | c | pass |  |
| X2 | x | pass |  |
| X3 | x | pass |  |
| X4 | x | pass |  |
| X5 | x | pass |  |
| X6 | x | pass |  |

## 관찰하지 못한 사례

- 해당 없음

Git 제외로 둔 텍스트 39개(경로·크기·SHA-256은 binary-artifacts.json). 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.

