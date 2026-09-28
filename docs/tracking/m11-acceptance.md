# M11 화학 상호작용 완료 기록

- 판정: **완료** (2026-09-28)
- 브랜치: `dryforge/m11-finish` (`phase/m11-chemical-interactions`의 `0c8abba`에서 분기). main 병합은 사용자 결정 대기.
- 고정 소스: `4ec584f`, Next buildId `aqV29Ar7twWJLHni63lRZ`
- 증거: `docs/qa/m11-chemical-20260928/` (README, source-hashes.json, gate-results.json, case-ledger.json, host-check.json, steps/)
- 옛 단계 기록 `phases/protview-chemical-interactions/index.json`은 pending으로 둔다(결정 0014).

## 진행 순서
1. 남은 수정과 정리: 행 초점 카메라 정지 대기(최대 3초, 넘으면 재시도 가능한 오류), QA 입력·도구 저장소 이전, 스타일 원본 이동(M11 19줄 + M8 12줄), Host 허용 목록(결정 0013), 옛 `/harness`·`/review` 명령 삭제.
2. 연결(attach) 두 방식과 detect-controls 실패 해결: 화학 표시 읽기의 단일 30초 제한을 요청별 제한으로, 30초를 넘는 시작 응답 뒤 실제 작업 상태 재확인, guardian의 GO 대기(고정 3초 → 작업 남은 시간 + 5초, 최대 3600초), 작업 상태 읽기의 잠금 제거.
3. H01–H17 하네스 완성과 한 번에 도는 실행기(`scripts/m11_offscreen_acceptance.py`), 사례 대장.
4. 기존 M9 결함 수정(표현 재구성 뒤 ready 재알림, 같은 카탈로그 유지). M11 이전 main 빌드에서도 3/3 실패하던 결함이다.
5. 독립 코드 검토 → 수정 → 소스 고정 → 전체 게이트·수락 QA·회귀 → 독립 증거 검토.

## 독립 코드 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 대상: `git diff main..0926e42`(M11 전체)와 바뀐 공유 소스.
- 판정: **APPROVED** (막는 지적 없음). 계약 변경이 필요한 지적 없음.
- 검토 당시 공유 소스 SHA-256 앞 16자(0926e42): README.md `7547dc2fc3eda91f`, backend/mw/api/app.py `be6cb28a61f926ab`, backend/mw/jobs/queue.py `6428c7d80ce078b8`, backend/mw/jobs/guardian.py `b73c0a0fc520b099`, backend/mw/core/handles.py `7b1320ebba3b9b68`, backend/mw/runtime/orchestrator.py `a370dfe34bbb77fa`, backend/mw/tools/energetic.py `2765d942512a70c0`, frontend/src/components/MolstarViewer.tsx `f9fb2eceaa0b6501`, frontend/app/page.tsx `ca71c51ff6cbda1f`, frontend/src/lib/api.ts `e1c6da142afd4dfe`, frontend/src/lib/comparison.ts `e885b45c3a169149`, frontend/middleware.ts `dabe036b9646b574`, frontend/src/lib/host-allowlist.ts `31db11189ca271ac`, design/components.css `328d1d8f3f4c7467`, backend/mw/chemical_bundle.py `0fb7a2a3c6648569`, backend/mw/chemical_inputs.py `787d65f74eaad1a8`, backend/mw/chemical_reports.py `70fe8c39dd224a45`, backend/mw/jobs/chemical_worker.py `4fb1eb2a978dbf33`, frontend/src/components/ChemicalWorkspace.tsx `f06b5564c0ada206`, frontend/src/lib/chemical.ts `8853ac0445e34d30`. 이 파일들 중 코드 검토 수정(`9d80dbf`)이 바꾼 것은 queue.py, guardian.py, chemical_bundle.py이며, 고정 소스의 전체 해시는 `docs/qa/m11-chemical-20260928/source-hashes.json`에 있다.
- 지적 처리(수정 커밋 `9d80dbf`, 병합 `4ec584f`):

| # | 지적 | 처리 |
|---|---|---|
| 1 | 잘못된 작업 출력의 예외(IndexError·AttributeError)가 작업을 running에 남김 | 수정: 인덱스·형식 검사를 앞으로, 예상 밖 예외는 typed failed. 실제 작업 프로세스 테스트 |
| 2 | 전역 작업 검사가 화학 작업 약 47개 뒤 256 MiB 한도로 모든 작업을 막음 | 수정: 줄 단위 스트리밍, 수명 주기 외 줄은 파싱 없이 건너뜀, 한도를 사건 수·시간 기준으로. 1.3 GB 루트 약 0.9초(로컬 1회 측정, 로그 미커밋) |
| 3 | HTTP 경로의 `JobQueue` 생성이 여전히 잠금·색인 재작성 | 수정: 생성자에서 제거, 색인은 쓰는 쪽과 `claim_next`만 |
| 4 | 테스트가 공개 예제 결과 개수(36, 32/1/1/2)를 기대값으로 확인 | 사용자 결정: "고정 엔진 회귀 기준값"으로 표시하고 잠금 파일 해시(`be320702…999a`)에 묶음. 행별 거리·각도·원소·결합을 다시 계산하는 독립 검사(`backend/tests/chemical_row_oracle.py`) 추가. 제품 코드에는 개수 없음 |
| 5 | guardian 메모리 검사의 `psutil.AccessDenied` 미처리 | 수정: `resource_monitor_unavailable`로 정리 후 RESULT |
| 6 | 사용 가능 여부 확인이 매번 ProLIF 프로세스를 띄움 | 수정: 인터프리터·잠금 파일·작업 파일 해시를 키로 성공 결과만 캐시 |
| 7 | `job_blocked` 기록이 소유 잠금 없이 추가됨 | 수정: 다른 기록과 같은 잠금 순서, 비차단 |
| 8 | 쓰지 않는 `chemical_bundle.capability()`, 페이지마다 소스 재파싱 | 앞은 삭제. 재파싱 캐시는 채택하지 않음: 전체 48 ms 중 12 ms는 해시 검증 적재로 피할 수 없고, 행 복사 비용이 이득을 상쇄하며 읽을 때마다 하는 검증이 약해진다 |
| 9 | 프런트엔드 중복 Host 실측 없음 | 수락 QA에서 실측. 허용 값이 먼저인 중복 Host는 통과 → 알려진 한계(결정 0013) |

## 전체 게이트 (고정 소스 `4ec584f`)

| 명령 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 377 passed, skip 0 (ProLIF 작업 환경 설치) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 |
| `pytest scripts/test_execute.py scripts/test_codex_hooks.py -q` | 57 passed |
| `npm --prefix frontend run test:events` | 86/86 |
| `npm --prefix frontend run typecheck` → `build` | 통과 |
| `node --check frontend/tests/offscreen/chemical-flow.cjs` | 통과 |
| `tokens` 후 생성 CSS diff | 없음 |
| `git grep '/tmp/protview-m11-qa' -- scripts frontend backend docs/operations.md` | 0건 |

## 수락 QA
- 실행기 한 번에 모든 단계 통과, 재실행 없음. H01–H17 모두 통과(29행), 외부 요청 0건.
- M11 모드: 능력 표시, create, empty(scientific_null, 오류와 구분), prepare-only, detect-controls, job-controls, 실패 재시도, running-cancel, attach `map_existing`·`replace_from_sdf`, reopen, restrictions(주석 켬·끔), faults, 잘못된 입력 9종과 공유결합 리간드.
- 회귀: M8 normal, OpenMM 준비, M9 scenes, M10 measure·alignment 통과.
- events-only 복구: 원본 입력과 작업 프로세스 없이 create·empty·attach run을 복구, 보고서 바이트 동일, 과학 이벤트 추가 없음.
- Host 실측 27건: 25건 기대대로, 2건 알려진 한계(중복 Host, 허용 값 먼저), 실패 0.
- `/tmp/protview-m11-qa-20260927/`의 release1–3 관찰은 원인 분석 참고였고 수락 증거로 쓰지 않았다.

## 독립 증거 검토 (Opus 5.5, 코드 검토자와 다른 서브에이전트)
- 판정: **APPROVED**.
- 확인: `4ec584f`의 138개 소스 해시 전부 일치, 게이트 로그와 요약 일치, 사례 대장 29행 해시 일치, 생략 파일 523개·축약 원본 23개·경로 치환 132개 전부 해시 일치, 중복 Host는 통과가 아닌 한계로 기록.
- 검토한 증거 SHA-256 앞 16자(`056f19d`): README.md `752d461d863b71b4`, source-hashes.json `5a7e0091dbb534d8`, gate-results.json `be638a175aaf02bd`, case-ledger.json `78a91535d0500428`, host-check.json `3f3da88cb32f223b`, omitted-files.json `1ebe577235512a91`, path-scrub.json `62598b9795c61586`.
- 지적 처리:
  - 1·2(기록 문서 미작성): 이 문서, 결정 0013·0014, status·findings·security 갱신으로 처리.
  - 3(회귀 행에 offscreen 요약·fixture 출처 없음), 4(`paint-first.png`가 0바이트 — 실제 paint 증거는 `baseline.paint.png`와 이후 프레임), 5(attach-setup 행의 파일별 출처 라벨 누락, H 사례 아님): 고정 증거는 바꾸지 않고 findings에 하네스 개선 과제로 기록.
  - 6(`harnessStatus: observed_unreviewed`): 하네스 흐름이 단언 실패 없이 끝났다는 뜻이다. 판정은 `status: pass`와 이 문서의 두 검토로 한다.

## 대체한 과거 검증 범위
M11이 공유 소스(README, `app.py`, `queue.py`, `guardian.py`, `handles.py`, `orchestrator.py`, `energetic.py`, `MolstarViewer.tsx`, `page.tsx`, `api.ts`, `comparison.ts`, 스타일)를 바꿔 M0–M10 검토 해시는 오래된 상태다. 이 기능들의 현재 동작은 위 전체 게이트(백엔드 377개), M8 normal·M9 scenes·M10 measure/alignment 오프스크린 회귀, 코드 검토로 다시 확인했다. 과거 검토 기록과 해시는 바꾸지 않았다.

## 수정 금지 문서에 남은 오래된 안내 (의도적)
- `docs/M11_OFFSCREEN_QA_PLAN.md`: `/tmp/protview-m11-qa-20260927/` 입력 경로와 GPT-6 Sol/Astra 역할. 현재 실행 방법은 `docs/operations.md`.
- `docs/HARNESS.md`: `/harness` 명령과 전역 검사 256 MiB 한도. 현재 한도는 `docs/engineering-notes.md`.
- `docs/M11_CHEMICAL_INTERACTIONS_CONTRACT.md`, `phases/protview-chemical-interactions/step0.md`: Astra 검토·부모 기록 절차. 실제 검토는 Opus 5.5가 했다.

## 최종 검토 참고 사항
- 코드 검토 승인은 `0926e42` 파일 해시 앞 16자에 묶여 있다. 고정 소스 `4ec584f`의 전체 해시는 증거 폴더의 `source-hashes.json`에 있다.
- `execute_claim`에서 차단 기록을 남기려고 소유 잠금 파일을 여는 중 `OSError`가 나면 원래 거부 사유 대신 그 오류가 보일 수 있다. 정상 사용에서는 일어나지 않아 고치지 않았다.

## 남은 문제
`docs/tracking/findings.md`에 기록: 중복 Host 한계, 이벤트 로그 전체 재파싱 비용, GO 전에 guardian이 끝난 작업의 running 잔류, 긴 시작 응답 복구의 오프스크린 미검증, 하네스 증거 형식 개선, ProLIF Linux 잠금 파일.
