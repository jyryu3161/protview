# 0019. 분석 계획 크기 한도를 64 KiB에서 1 MiB로 올리고 입력은 한 번만 저장한다

- 상태: 채택 (사용자 결정 2026-09-29, M13 명세 확정 때). `docs/M13_WORKFLOWS_CONTRACT.md`의 "64KiB plan JSON"을 대체한다.

## 배경
M13 계약은 계획 JSON을 64 KiB로 제한했다. 흐름은 기존 화면에서 만든 입력을 그대로 가져오는데, M10 비교는 CA 쌍을 최대 1000개, M11 연결 방식은 리간드 중원자 전체 대응을 받는다. 잔기 7필드와 AtomRef 전체 필드를 null까지 담으면 이 입력들은 64 KiB에 들어가지 않는다.

## 결정
- 계획 JSON(`analysis_plan@1`의 canonical JSON)은 1 MiB 이하, run당 계획 100개 이하다. 넘으면 429 `resource_exceeded`(`plan_too_large`, `plan_limit`).
- 같은 입력을 `inputs`와 단계 `params`에 두 번 저장하지 않는다. 단계는 `{"input_ref": <이름>}`으로 `inputs`를 가리킨다.
- 계획 생성 요청 본문은 1 MiB, 그 밖의 분석 요청 본문은 64 KiB 이하다(넘으면 413).

## 검토한 대안
- 64 KiB 유지: CA 1000쌍·화학 대응 전체를 흐름에서 쓸 수 없어, 기존 화면이 받는 입력의 일부만 지원하게 된다.

## 결과
- `/capabilities`의 `methods.analysis_workflows.max_plan_bytes`는 1048576이다. 1000쌍 CA 계획이 들어가고 한 번만 저장되는지는 `test_compare_plan_with_1000_ca_pairs_fits_and_is_stored_once`가 확인한다.
