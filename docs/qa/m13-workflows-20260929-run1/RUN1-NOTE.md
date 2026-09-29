# M13 수락 QA 1차 실행 (실패 실행 증거로 보존)

- 소스 고정 `d1eaf48243e26301528c7593780c6ad2b630583b`, 빌드 `WCnxUsptjGLeenXzwlYhV`. 게이트 8개는 모두 exit 0(`gate-results.md`).
- verdict **fail**. 원인은 제품이 아니라 M13 수락 실행기(`scripts/m13_offscreen_acceptance.py` `sub_runner`)가 M11 ledger(`m11_case_ledger@1`)를 잘못 읽은 것이다. 이 ledger에는 `verdict` 키가 없고 `summary`·`nonLoopbackRequestsTotal`만 있어 판정이 None → fail, 외부 요청 수가 None으로 기록되어 S-no-egress도 fail이 되었다. M11 실행기 자체는 exit 0, 사례 17/17 pass, 비-loopback 0이었다. 실행기는 `af1500b`에서 고쳤고 전체 수락을 `docs/qa/m13-workflows-20260929/`에 다시 실행했다.
- 제품 사례는 모두 pass였다(M13 workflows·unavailable·M8–M10 회귀, M13 사례 27/27; S-no-egress만 위 결함으로 fail, 측정된 비-loopback 합계는 0).
- M12 실행기의 `regression-m10-measure` 사례 C02-repeat-reverse가 한 번 실패했다(측정 모드 기준 원자 클릭 3회 모두 Mol* `empty_loci`, "Mol* observation did not become ready"). M12 실행기 `--only regression-m10-measure`로 1회 재실행해 pass했다(`case-ledger-partial.json`, partial_not_acceptance). 이 재실행은 이 폴더의 `evidence/`·`SHA256SUMS`에는 없다(내보내기가 재실행 전에 끝남).
- 이 폴더는 원래 `docs/qa/m13-workflows-20260929/`로 내보냈다가 이름을 바꿨다. `SHA256SUMS`와 README의 경로는 원래 폴더 이름 기준 상대 경로다(폴더 안에서 `shasum -a 256 -c SHA256SUMS`로 확인 가능).
