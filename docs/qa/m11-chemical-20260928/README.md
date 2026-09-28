# M11 화학 상호작용 수락 QA — 2026-09-28 (고정 빌드)

M11 마무리 계획의 T9 증거다. 소스를 고정한 뒤 그 빌드 하나로 전체 게이트, M11 오프스크린 모드 전부(H01–H17), M8·M9·M10 회귀, events-only 복구, 작업 프로세스 능력 불일치 확인, 기본 오프스크린 확인, 실제 :3000/:8000 Host 검사를 실행했다. 이 폴더는 텍스트 증거만 담는다. 스크린숏·다운로드 원본·browser-profile은 git에서 제외된 로컬 폴더에 두고, 여기에는 SHA-256만 적는다(`omitted-files.json`).

## 고정 소스와 빌드

| 항목 | 값 |
|---|---|
| git HEAD | `4ec584f2bd5e82f7cb8550eb8148b26e31dfaf5d` (브랜치 `dryforge/m11-finish-T9`, `git status` 깨끗함) |
| Next buildId | `aqV29Ar7twWJLHni63lRZ` (`frontend/.next/BUILD_ID`) |
| 소스 해시 목록 | `source-hashes.json`: 추적 파일 138개(`backend/mw`, `frontend/src`, `frontend/app`, `frontend/middleware.ts`, `design/`, `scripts/m11_*.py`, `frontend/tests/offscreen/*.cjs`, `config/`)의 SHA-256과 합계 해시 |
| 수락 실행기 | `scripts/m11_offscreen_acceptance.py` sha256 `8cefc14367573c97edac787dc46cb0a6ed2a5fc04aa7c2de88b7c819dfdaf893` |
| 하네스 | `chemical-flow.cjs` `c834569a…d967`, `m11-case-ledger.cjs` `445666ab…6f43`, `m11-ledger.cjs` `9e4ffb3d…95fb`, `driver.cjs` `85769a0e…00b2`, `main.cjs` `4787a2cf…bd13`(전체 값은 `steps/runner-state.json`) |

고정 이후 제품·테스트 소스는 바뀌지 않았다. 실행기는 매 실행 시작 시 HEAD와 빈 `git status`를 `steps/runner-state.json`에 기록했다.

## 실행 환경

- macOS 15.6 (arm64), Python 3.11.11(`.venv`), Node v24.3.0, Next 15.5.26, Mol* 5.11.0, Electron 44.4.5 (Chrome 152)
- ProLIF 작업 프로세스 환경 `.deps/prolif/venv-locked`: ProLIF 2.2.2, RDKit 2026.03.6, MDAnalysis 2.10.0
- 작업 위치: 워크트리 `/Users/jaeyongryu/Projects/protview/.dryforge/worktrees/T2`. 모든 python 명령에 `PYTHONPATH=<워크트리>/backend`를 지정했다(`import mw`가 워크트리 소스를 가리키는지 확인함).
- 서비스는 `127.0.0.1:8000`(uvicorn)과 `127.0.0.1:3000`(`next start -H 127.0.0.1`)에만 바인딩했다. QA runs 루트는 `runs/m11-acceptance-20260928`(`/tmp` 아님, git 제외)이다.
- 로컬 원본: `frontend/tests/offscreen/artifacts/m11-acceptance/20260928/`(수락 실행), `…/20260928-hostcheck/`(Host 검사·기본 확인). 모두 git 제외.

## 명령과 결과

전체 명령, 종료 코드, 요약 줄은 `gate-results.json`, 각 출력은 `gate-logs/`에 있다.

| 게이트 | 명령 | 종료 코드 | 요약 |
|---|---|---|---|
| typecheck | `npm --prefix frontend run typecheck` | 0 | 진단 없음 |
| build | `npm --prefix frontend run build` (typecheck 뒤, 동시 실행 안 함) | 0 | buildId `aqV29Ar7twWJLHni63lRZ` |
| 백엔드 전체 | `.venv/bin/python -m pytest backend/tests -q -rs` | 0 | 377 passed, **skip 0**, 718초 |
| ruff | `.venv/bin/python -m ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 0 | All checks passed |
| 스크립트 테스트 | `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q` | 0 | 57 passed |
| test:events | `npm --prefix frontend run test:events` | 0 | 86/86 pass |
| 문법 확인 | `node --check frontend/tests/offscreen/chemical-flow.cjs` | 0 | — |
| 토큰 | `npm --prefix frontend run tokens`, 이어서 `git diff --exit-code frontend/src/design/components.css` | 0 / 0 | diff 없음, 작업 트리 깨끗함 |
| `/tmp` 경로 잔존 | `git grep -n '/tmp/protview-m11-qa' -- scripts frontend backend docs/operations.md` | 1 | 0줄(일치 없음 = 기대값) |
| M11 수락 | `.venv/bin/python scripts/m11_offscreen_acceptance.py --root runs/m11-acceptance-20260928 --artifacts frontend/tests/offscreen/artifacts/m11-acceptance/20260928` | 0 | `failedSteps: []`, 대장 17/17 pass |
| 기본 오프스크린 | `npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000` | 0 | offscreen true, paint 7회, 차단 요청 0 |

### 수락 실행 단계별 결과

한 번의 실행으로 끝났다. 실패한 단계가 없어 재실행도 없다(`steps/runner-summary.jsonl`, `steps/acceptance-runner-stdout.log`). 모든 단계가 새 runs 루트에서 실행됐다.

| 단계 | 결과 | run |
|---|---|---|
| capability-ready | pass | run_b4f60055… |
| create | pass | run_6772ccb8… |
| empty | pass | run_2a2af597… |
| prepare-only / detect-controls | pass / pass | run_cf06945c… |
| job-controls | pass | run_0d7c24c8… |
| job-controls-failure | pass | run_5c4a362f… |
| running-cancel | pass | run_a1102e7e… |
| attach-setup(API 준비, 사례 없음) | pass | run_9022d05c… |
| attach-map / attach-replace / reopen-complete / restrictions / faults / invalid-attach | 모두 pass | run_9022d05c… |
| invalid-inputs | pass | run_b76a78fe… |
| reopen | pass | run_6772ccb8… |
| regression-m8-normal (public_1hsg) | pass | run_c4778c22… |
| regression-m9-openmm / regression-m9-scenes-core | pass / pass | run_8f21abdf… |
| regression-m10-measure | pass | run_77a55c44… |
| regression-m10-alignment | pass | run_460de59e… |
| replay-snapshot, replay-probe-prebrowser, replay-create, replay-empty, replay-attach, replay-probe-postbrowser | 모두 pass | create·empty·attach run |
| capability-worker-missing | pass | run_0cf7c00e… |
| capability-worker-version-invalid | pass | run_2f15def6… |
| leftover-processes | pass(남은 프로세스·포트 없음) | — |
| case-ledger | pass | — |

events-only 복구는 원래 입력 폴더를 치운 상태에서, 작업 프로세스가 없는 표시된 런타임 배치(`steps/layout-worker-missing.json`, backend/mw·config를 바이트 그대로 복사)로 실행했다. 능력 불일치는 고정되지 않은 인터프리터를 가리키는 배치(`steps/layout-worker-mismatch.json`)로 실행했다. 두 배치 모두 성공을 흉내 내지 않는다.

## 사례 대장 (H01–H17)

`case-ledger.json`은 실행기의 집계기(`m11-case-ledger.cjs`)가 만든 파일을 그대로 복사한 것이다. 요약은 pass 17, fail 0, missing 0이고, 행 29개, buildId 하나(`aqV29Ar7twWJLHni63lRZ`), **loopback이 아닌 요청 합계 0**, 요청 수를 모르는 행 0이다. 각 행에는 증거 종류(`real_electron_offscreen`, `direct_api`, `labeled_api_setup`), 모드, run·handle, 입력 fixture SHA-256과 출처 라벨(공개 ProLIF 예제는 "prepared docking example; not experimental validation", 합성 파생 입력은 "not experimental evidence"), 외부 요청 수가 들어 있다.

| 사례 | 결과 | 덮은 모드 |
|---|---|---|
| H01 | pass | capability-ready, worker_missing, worker_version_invalid |
| H02 | pass | create |
| H03 | pass | create, attach-map |
| H04 | pass | create |
| H05 | pass | attach-map, attach-replace, invalid-attach |
| H06 | pass | invalid-inputs, invalid-attach, job-controls-failure |
| H07 | pass | create, detect-controls, job-controls, job-controls-failure, running-cancel, attach-replace |
| H08 | pass | create, attach-map |
| H09 | pass | empty, job-controls-failure |
| H10 | pass | create, reopen-complete |
| H11 | pass | create, reopen-complete, restrictions |
| H12 | pass | create, restrictions |
| H13 | pass | restrictions |
| H14 | pass | create, attach-map, reopen-complete, reopen, replay |
| H15 | pass | create, job-controls, running-cancel, faults |
| H16 | pass | replay, replay-probe-prebrowser, replay-probe-postbrowser |
| H17 | pass | M8 normal, M9 openmm·scenes-core, M10 measure·alignment |

대장의 백엔드 테스트 항목은 위 전체 백엔드 게이트(377 passed, skip 0)가 근거다.

## Host 검사 (실제 :3000, :8000)

`host-check.json`에 사례 27개를 관찰한 그대로 적었다. raw TCP 소켓으로 HTTP/1.1 요청을 보냈고, 요청마다 어느 계층이 결정했는지와 백엔드 도달 여부(백엔드 접근 로그 줄 증가)를 함께 기록했다. 스크립트는 `host-and-smoke/host_check.py`에 있다.

| 포트·경로 | Host | 관찰 | 결정한 계층 |
|---|---|---|---|
| :3000 `/api/capabilities`, `/` | `evil.example`, `evil.example:3000` | 400 "Host header not allowed", 백엔드 미도달 | Next 미들웨어 |
| :3000 | `127.0.0.1:3000`, `LOCALHOST:3000`, `[::1]:3000` | 200(`/api`는 프록시로 백엔드 도달) | Next 미들웨어 허용 |
| :3000 | 없음 | 400, 빈 본문·content-type 없음, 백엔드 미도달 | Node HTTP 서버(Next 앞 단계) |
| :3000 | `evil.example` 다음 `127.0.0.1:3000` | 400, 백엔드 미도달 | Next 미들웨어 |
| :3000 | `127.0.0.1:3000` 다음 `evil.example` | **200, `/api`는 백엔드 도달** | 거부 안 됨. **observed pass-through — accepted known limitation per user decision 2026-09-28; browsers send a single Host so DNS rebinding remains blocked** |
| :3000 | `127.0.0.1:3000` 다음 `localhost:3000` | 200 | 둘 다 허용 목록 값 |
| :8000 `/capabilities` | `evil.example`, `evil.example:3000` | 400 JSON `{"detail":"Host header not allowed"}` | 앱 `HostAllowlistMiddleware` |
| :8000 | 허용 Host 3종 | 200 | 앱 미들웨어 허용 |
| :8000 | 없음, 그리고 Host가 두 개인 세 경우 모두 | 400 "Invalid HTTP request received." | uvicorn HTTP 프로토콜 계층(h11), 앱에 도달하기 전 |

알려진 한계: Node HTTP 서버는 중복 Host 헤더 가운데 첫 값만 `req.headers.host`에 남기고, 두 값 모두 rawHeaders에만 남는다. `frontend/middleware.ts`는 `request.headers.get("host")`를 검사하므로 첫 값이 허용 목록 값이면 통과한다. 사용자가 2026-09-28에 코드를 바꾸지 않고 재고정 없이 알려진 한계로 기록하기로 정했다. 이 사례는 pass로 세지 않는다(`host-check.json` 요약: pass 25, knownLimitation 2(`/api/capabilities`와 `/`), fail 0).

`curl -H 'Host: a' -H 'Host: b'`는 이 curl(7.87.0)에서 첫 Host만 보낸다(`-v`로 확인). 그래서 `host-and-smoke/host-check-curl.txt`는 중복 헤더 시험이 아니며 참고로만 둔다. 누락 Host를 어느 계층이 거부했는지는 같은 빌드로 프런트엔드만 다시 띄워 응답 헤더 전체를 확인했다(`host-and-smoke/host-diag-headers.txt`).

기본 오프스크린 확인(`host-and-smoke/offscreen-smoke.log`, `host-and-smoke/offscreen-smoke/baseline.json`)은 Host 검사가 들어간 같은 빌드에서 `127.0.0.1:3000`로 통과했다.

## 폴더 구성

- `source-hashes.json`: 고정 소스 해시 목록
- `gate-results.json`, `gate-logs/`: 게이트 명령·종료 코드·요약·출력
- `case-ledger.json`: H01–H17 대장(집계기 출력 원본)
- `host-check.json`: Host 사례별 관찰과 결정 계층
- `steps/<단계>/`(저장소 `.gitignore`가 모든 `runs/` 폴더를 제외하므로 이름을 `steps/`로 했다): 단계별 `ledger-row.json`, `chemical-evidence.json`, 회귀 jsonl, 실행 로그, `steps/replay/`(events-only 기준·검증 결과), `steps/services/`(서비스 로그), `steps/runner-state.json`, `steps/runner-summary.jsonl`
- `host-and-smoke/`: Host 검사 원자료, 스크립트, 서비스 로그, 기본 오프스크린 확인 결과
- `omitted-files.json`: 옮기지 않은 원본 목록

256 KiB 이하 텍스트 파일은 그대로 복사했다. 그보다 큰 JSON·JSONL(`chemical-evidence.json`, 회귀 jsonl 등 23개)은 `*.compact.json(l)`로 줄였다. 이 파일들은 8 KiB를 넘는 중첩 값을 바이트 수와 SHA-256으로 바꾸고, 원본 전체의 바이트 수와 SHA-256을 머리에 적는다. 스크린숏(png), 다운로드, 하네스 소스 사본, 큰 서비스 로그 523개는 경로·크기·SHA-256만, browser-profile 27개는 파일 수와 합계 해시만 `omitted-files.json`에 적었다.

## 과거 관찰

`/tmp/protview-m11-qa-20260927/`의 release1–3 오프스크린 관찰은 옛 빌드 기준이다. 원인 분석에 참고했을 뿐 이 수락 증거에는 쓰지 않았다. 이 폴더의 모든 결과는 위 고정 HEAD와 buildId에서 새로 만들었다.

## 정리

수락 실행기의 leftover-processes 확인이 통과했다. Host 검사용으로 띄운 서비스도 모두 종료했고, 이후 :8000·:3000은 비어 있으며 이 워크트리의 guardian·worker·Electron 프로세스는 남지 않았다.
