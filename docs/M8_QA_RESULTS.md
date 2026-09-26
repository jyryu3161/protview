# M8 실제 오프스크린 검증 기록

2026-09-25 · 실제 작업 브랜치 `phase/m8-agent-viewer` · 부모 커밋 `e0abffc`.

실제 오프스크린 검증 목록 **86/86을 완료**했다. 지원 기능의 정상 동작과 미지원·오류·dry-run의 정확한 차단/안내를 함께 검증했다. [읽기 쉬운 항목별 표](qa/m8/COVERAGE.md), [전체 하위 동작·판정·증거](qa/m8/coverage.json)를 확인할 수 있다. 단계의 정식 검사·리뷰·파일 hash 기록은 [M8 index](../phases/protview-agent-ui/index.json)에 연결된다.

## 실제 실행 환경과 범위

Electron 44.4.5 / Chromium 152.0.7977.130 / Playwright 1.63.0의 같은 렌더러를 조작했다. `BrowserWindow(show:false, offscreen:true)`, `webContents.isOffscreen()=true`, `visible=false`, GPU 활성, 실제 WebGL Mol*와 paint 비트맵을 확인했다. 일반 숨김 탭을 오프스크린 결과로 대신하지 않았다. [호스트 기록](qa/m8/raw/host-baseline.json), [실제 paint](qa/m8/screenshots/actual-offscreen-paint.png).

[실행 계획](M8_OFFSCREEN_QA_PLAN.md)의 W/I/V/C/S/R/O/B/A 총 86개 항목에 대해 실제 클릭·키보드·파일 선택·다운로드를 실행했다. 정상 과학 계산은 실제 FastAPI/엔진 결과를 사용했다. 실패·지연 응답은 해당 loopback 요청에만 주입하고 별도로 표시했다. 에이전트 오류/경합 테스트는 별도 fixture API의 `MockTransport`를 사용했으며 실제 모델 품질의 증거로 세지 않았다. 각 원본 기록에는 입력, 실행/run/source, 렌더러 관찰, 스크린샷 경로가 있다. [보존 파일과 SHA-256 목록](qa/m8/archive.json).

기본 `runs/`와 분리한 `/tmp/protview-qa/m8-runs`에서 검사했다. 완료 후 기본 서비스를 복원하고 실제 1HSG 정상 흐름·1UBQ OpenMM 완료·모델 실호출 기록의 세 run을 새 ID 그대로 바이트 복사해 두었다. 기존 run을 덮어쓰지 않았다. [복사 기록](qa/m8/raw/demo-copy.json), [복원 후 실제 offscreen 열기·키보드 재검증](qa/m8/raw/default-service.json). 새 기본 예제는 offline/모델 사용 0이며, 다시 열어도 계산·모델·worker를 재실행하지 않았다. 기존 M6/M7 데이터의 34개 보호 파일은 원본 바이트 또는 append-only 이벤트 접두부가 유지됐다. [보존 검사](qa/m8/raw/preservation.json). 공개 1HSG/1UBQ 입력과 별도로 식별자·altloc·다중 모델·빈 결과 검사용 합성 입력을 명시했다. 브라우저 프로필과 비밀키는 증거 저장소에 포함하지 않았다.

## 프롬프트가 실제 뷰어를 조절한 증거

운영 API→단일 OpenRouter gate→`typesafe/jev-1.13` 요청→실제 `typesafe/jev-1.13-20260917` 응답→typed command→Mol* 적용 ACK를 확인했다. 실제 모델 호출은 정확히 4회, 사용량 55,745 tokens / USD 0.00212793이다. [모델·한도·사용량 기록](qa/m8/raw/live-summary.json).

| 호출 | 실제 결과 |
| --- | --- |
| 1 | surface 전환 + auth A/25 잔기 선택·초점, 3/3 실제 적용 ACK |
| 2 | ball-and-stick + model 1/auth B/902/label C의 MK1 리간드 선택 + 확대, 3/3 ACK |
| 3 | `viewer_questions@1`에서 선택 해제 요청을 기존 리간드 재선택으로 해석: 의미 검증 실패를 보존 |
| 4 | 동일 한국어 문장에 `viewer_questions@2`: cartoon + clear + reset, 실제 선택 null과 카메라 확인, 3/3 ACK |

실패한 3번째 답을 성공으로 고치거나 프롬프트 키워드로 동작을 덮어쓰지 않았다. 모델에 전달하는 질문의 기존 선택/신규 선택/해제 의미를 명확히 했다. [실패 원본](qa/m8/raw/live-v1-semantic-failure.json), [교정 후 원본](qa/m8/raw/live-v2.json), [최종 화면](qa/m8/screenshots/live-clear-reset.png).

다섯 번째 intent 시도는 `viewer_cap_exhausted`로 차단됐고 실제 다섯 번째 외부 요청은 없었다. 온라인 모드 off/on으로 카운터를 초기화할 수 없으며, 최종 상태는 offline이다. 한도를 다 쓴 뒤에도 로컬 `/zoom out`이 실제 동작했다. 자연어 viewer 동의는 OpenMM 계산 승인을 부여하지 않는다.

## 발견해서 수정한 기능 문제

- 과거 구조 선택 후 현재 구조로 돌아왔을 때 준비된 잔기 목록이 사라져 다른 리간드 계산/SASA가 비활성화되는 문제를 수정했다. 동일 이름의 서로 다른 리간드와 반복 cutoff 계산을 다시 검증했다.
- 키보드로 history를 선택할 수 없던 문제를 수정하고 실제 Tab·Enter·Space로 검증했다.
- 25 MiB 초과 업로드를 요청 전 명시적으로 차단해 멈춘 듯 보이는 상태를 없앴다. malformed/empty/oversize 각각 확인했다.
- scope 변경 시 scene generation 충돌, session 갱신 경합, 현재 표현/선택과 전송 preview 불일치를 수정했다. 256개 초과 대상은 정확한 범위 선택을 요구하며 표현/카메라는 계속 동작한다.
- 중복 제출, dispatch 전 취소, 온라인 비활성화, 장면 변경, 수동 조작, 재접속, 두 브라우저 client의 ACK 경계를 보강했다. 비용과 기존 결과는 보존한다.
- dry-run OpenMM 제출의 `plan_only` 응답이 화면에 보이지 않던 문제를 수정했다. 실제로 계획만 반환됐다는 안내, 작업 0개, 계산/예산 0, 다시 열 때 일시 안내 제거를 검증했다. [7개 결과](qa/m8/raw/dry-run-feedback.jsonl), [안내 화면](qa/m8/screenshots/dry-run-plan-feedback.png).
- 부분 적용 후 Stop/ACK 소실에서 toolbar와 전송 preview가 실제 Mol*를 따라가지 못하는 문제를 수정했다. 실제 surface·selection 부분 적용과 취소, 후속 로컬 명령, 늦은 취소 중 수동 조작 우선, ACK 응답 소실, 적용 전 오류에서 기존 focus 보존을 재검증했다. 취소/ACK 0 기록은 유지하며 화면의 실제 상태만 동기화한다. [최종 fixture 24개 결과](qa/m8/raw/agent-adversarial-final.jsonl), [선택 적용 후 취소 화면](qa/m8/screenshots/stop-selection-after.png).

- 캔버스 클릭이 카메라만 움직이고 잔기 선택을 전달하지 않던 문제를 수정했다. 실제 원자 클릭→다른 잔기로 교체→로컬 확대→빈 공간 해제, 최소화 구조와 실제 계산 응답 대기 중 선택을 12개 하위 검사로 확인했다. 빠른 선택의 역순 state POST가 CAS 오류를 표시하던 문제는 즉시 로컬 무효화와 서버 CAS를 유지하면서 같은 세션의 전송 순서를 보장해 해결했다. 최종에는 오류 메시지 부재와 서버·native·legend·preview 일치를 확인했다. [직접 선택](qa/m8/raw/canvas-pick-final.jsonl), [최소화](qa/m8/raw/canvas-minimized-final.jsonl), [계산 중](qa/m8/raw/canvas-busy-final.jsonl), [최종 화면](qa/m8/screenshots/canvas-pick-after.png).
- 업로드만 한 run을 다시 열었을 때 나타나는 숫자 model index 입력도 음수/소수/범위 초과와 실제 model 2 로딩까지 5개 하위 검사로 확인했다. [검증 기록](qa/m8/raw/model-index-reopen.jsonl).

## 과학 계산·기록·장면 전환

실제 1HSG contacts 97 atom pairs/26 residues/minimum 2.6264474104767457 Å를 확인했다. 실제 FreeSASA의 단백질/리간드 burial은 각각 546.4015616674023 / 782.7580589969108 Å²였으며 빈 결과는 오류와 구별했다. OpenMM은 실제 1UBQ CPU 작업의 native kJ/mol 결과, 58개 물 제외 설명, 승인/시작/완료/취소/실패 재시도/최소화 좌표 전환을 확인했다. 보고서 Markdown/JSON은 실제 Electron 다운로드로 저장하고 보존된 보고서 바이트와 비교했다.

모델 요청 중 run·history·다른 모델·최소화 좌표로 전환해 이전 명령이 새 장면에 적용되지 않는지 확인했다. 계산 owner가 사용 중일 때 새로운 구조 load는 명시적인 busy 오류를 낸다. 요청을 해제한 뒤 같은 model 2 load를 다시 실제 클릭해 성공했고, 이전 intent는 ACK 0개로 남아 새 session에서 detached가 됐다. [보충 검증](qa/m8/raw/agent-source-transitions.jsonl).

PyRosetta는 사용 가능한 계산으로 가장하지 않는다. 앞서 실제 반영한 대안은 **FreeSASA의 표면적/매몰 면적**과 **OpenMM의 제한된 단백질 전위/최소화**다. 이 값은 Rosetta score, ΔΔG, 친화도 또는 안정성 예측이 아니다. 실제 1HSG OpenMM 입력의 missing OXT도 예산을 쓰지 않는 명시적 unsupported 결과로 검증했다. Gallery는 제품 계산과 구분된 design fixture다.

## 기록 해석과 재현

일부 root JSONL에서 결과 `status`가 렌더러 관찰 객체로 덮어써졌다. 원본을 수정하지 않고 완료된 assertion·실제 관찰·오류를 대조해 [정규화한 coverage](qa/m8/coverage.json)의 verdict를 따로 기록했다. 실패한 최초 malformed locator/리간드/cutoff 사례와 모델의 잘못된 선택 해제 해석은 성공 집계에서 제외했다. A150 초점 기록의 잘못 연결된 과거 intent 관찰은 [원본 이벤트 대조](qa/m8/raw/root-observation-reconciliation.json)로 보완했다.

정상 37개 흐름, OpenMM/오류/예산 흐름, 입력/읽기/보고서 흐름은 각 수정 시점의 source/build SHA로 검증했다. 마지막 B03/A10/V12 수정은 관련 흐름을 다시 검증했고, 최종 빌드에서 정상 37개·agent fixture 24개·V12 12개를 재실행했다. 앞선 모든 클릭을 최종 빌드에서 다시 실행했다고 주장하지 않는다. 정식 전체 자동 검사와 source hash 리뷰 결과는 M8 index를 따른다.

재현 명령과 전제는 [오프스크린 harness README](../frontend/tests/offscreen/README.md) 및 [격리된 agent fixture README](../backend/tests/offscreen_agent_fixture/README.md)에 있다. 모델 요청은 자동 재현 스크립트가 호출하지 않는다. 실제 모델 QA 한도 4회는 소진됐으며 추가 요청은 이 검증에 필요하지 않다. 추가 I09/V12 검증에 사용한 원본 probe도 `qa/m8/raw/probe-*.cjs`에 보존했다. 이 probe에는 당시 workspace 경로와 QA run 경로가 있어 다른 환경에서는 경로를 맞춰야 한다.

## 검사와 Git 단계

통합 사전 검사에서 Python 309 passed / 0 skipped(기존 Starlette/httpx deprecation warning 1개), 최종 frontend 24 passed, Ruff/typecheck/build가 통과했다. 정식 acceptance 전체 재실행과 Astra 승인·검토 파일 hash·`--verify` 결과는 [단계 기록](../phases/protview-agent-ui/index.json) 및 [리뷰](M8_AGENT_VIEWER_REVIEW.md)를 따른다.

실제 브랜치는 M6 `phase/m6-interface-sasa` → M7 `phase/m7-openmm-minimization` → M8 `phase/m8-agent-viewer`로 이어진다. M0–M5는 당시 단계별 리뷰/검사는 했으나 개별 브랜치 커밋을 만들지 않았다. `master`의 `d22fe15`가 그 정직한 기준이며 과거 기록을 새로 꾸미지 않는다. 이전 M0–M7 리뷰는 당시 승인 기준이고, 현재 변경한 공통 source의 검증은 새 M8 extension 리뷰로 연결한다.
