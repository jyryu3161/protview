# 엔지니어링 노트

## 함정

### psutil 공개 `create_time()`이 같은 프로세스인데 2초 다르게 나온다 (Darwin)
- **증상**: M7 호스트 테스트에서 작업 프로세스의 공개 생성 시각이 인증된 STARTED 관측값과 정확히 2초 차이 났고, 새 guardian의 신원 인증이 실패했다.
- **원인**: psutil 7.2.2의 Darwin 구현은 공개 `create_time()`을 import한 프로세스의 `INIT_BOOT_TIME`과 현재 부팅 시각으로 보정한다. 인터프리터마다 보정값이 달라질 수 있다. psutil 자체의 PID 재사용 판정은 보정하지 않은 내부 값을 쓴다.
- **대응**: 프로세스 신원은 `backend/mw/jobs/process_identity.py`의 어댑터만 쓴다. 이 어댑터는 `psutil.Process(pid)._proc.create_time(monotonic=True)`를 `{"kind":"psutil_raw_start_v1","platform":"darwin|linux","psutil_version":"7.2.2","value":…}` 형식으로 기록한다. 공개 `create_time`은 진단용으로만 쓰고, 신호 전송 권한 판단에는 쓰지 않는다. psutil 버전을 올리면 private 경로가 바뀔 수 있으므로 어댑터가 dispatch 전에 거부한다. 새 버전은 어댑터를 다시 검증해야 쓸 수 있다.
- **검증**: `pytest backend/tests/test_jobs.py -q`. 옛 공개 시각 형식의 활성 기록은 신호를 보낼 권한이 없다.

### Mol*가 붙인 label과 Gemmi label이 다르다
- **증상**: 일반 PDB에서 잔기를 클릭하면 Mol*는 `label_asym_id=A`를 내놓는데, 서버의 Gemmi 잔기는 `chain_label=Axp`, `seq_label=null`이다. label로 매칭하면 선택·초점·저장된 보기가 틀린 잔기를 가리키거나 실패한다.
- **원인**: Mol* 파서는 PDB에 없는 label을 자체적으로 합성한다. Gemmi는 subchain을 다르게 부여한다. 둘 다 "틀린" 것은 아니며, 서로 다른 표시 체계다.
- **대응**: 브라우저 ↔ 서버 대응에는 Mol* `StructureProperties.atom.sourceIndex`(`atomicHierarchy.atomSourceIndex`, 입력 파일 행 번호)만 쓴다. 이 대응은 서버가 제공한 바이트의 SHA-256에 묶어 두고, 로드한 모델에 대해 일대일인지 검증한다. 역방향(잔기 → Mol* loci)은 7개 필드를 null까지 정확히 매칭해 그 잔기의 모든 site를 모은 뒤 loci를 만든다. Gemmi의 subchain을 Mol* label 선택자에 그대로 넣으면 안 된다. PDB serial, Mol* element index, 좌표 최근접 매칭도 대안이 될 수 없다.
- **검증**: 오프스크린 M8 normal-flow에서 리간드 → 접촉 행 초점이 새 잔기를 정확히 잡고 카메라가 바뀌는지, M9에서 선택 잔기가 있는 보기를 저장·복원했을 때 7필드가 같은지 확인한다.

### 같은 바인딩을 다시 알리면 대기 중인 초점 작업이 취소된다
- **증상**: 서버가 초점 동작을 확인하면서 기존과 같은 바인딩을 다시 publish하자, 대기 중이던 native focus가 "새 사용자 동작"으로 간주되어 스스로 취소됐다.
- **대응**: `ViewerBinding` 6필드(`sessionId`, `clientId`, `generation`, `sourceHandle`, `catalogHash`, `actionRevision`) 중 하나라도 바뀔 때만 작업을 무효화한다. 카탈로그 검증과 준비 상태 갱신은 관찰일 뿐이므로 `onSelect`를 호출하거나 저장된 보기 복원을 취소하면 안 된다. 실제 포인터 클릭(같은 잔기를 다시 누른 경우 포함), 빈 캔버스 클릭, 회전은 계속 취소를 일으켜야 한다.

### FreeSASA Shrake–Rupley는 해석 검사를 통과하지 못했다
- **증상**: Shrake–Rupley 1000점 설정의 단일 구·분리 구 SASA가 해석값과 0.5% 허용 오차 밖으로 어긋났다.
- **대응**: Lee–Richards 100 slices, probe 1.4 Å, 스레드 1로 고정했다. 설정을 바꾸려면 해석 검사를 먼저 통과시켜야 하고, 숫자를 보정해서 맞추면 안 된다. 실패 증거는 보존 대상이다.

### 결정 캐시의 "성공"과 실제 전송은 다르다
- **증상**: 온라인 run에서 캐시 적중이 나도 `sent=false`여야 하는데, 모드가 online이라는 이유로 전송된 것처럼 표시하기 쉽다.
- **대응**: 전송 여부는 `true|false|unknown` 세 값으로 기록한다. 서버 응답이 있으면 true(4xx 포함), 시간 초과나 연결 오류는 unknown, 캐시 적중과 거부는 false다. unknown인 요청은 재시작해도 자동으로 다시 보내지 않는다.

### M11 화학 작업 시작이 전역 동시 실행 검사에서 거부된다
- **증상**: 화학 작업 시작이 run/job 이름이 담긴 진단과 함께 거부된다.
- **원인**: 무거운 작업 프로세스의 동시 실행을 관리하려고 runs 루트 전체의 이벤트 로그를 훑는 검사가 있다. 로그를 한 줄씩 읽고, 작업 수명 주기 이벤트가 아닌 줄(객체 payload)과 `job_submitted`는 JSON 파싱 없이 건너뛴다. 한도는 run 항목 1,000개, 파싱한 수명 주기 이벤트 250,000개, 이벤트 한 줄 256 MiB, 검사 시간 20초, 잠금 대기 1초다(로그 전체 바이트 한도는 없다). 한도를 넘거나, 마지막 줄이 잘렸거나, 정리되지 않은 guardian이 있으면 입장을 막는다. 1.3 GB·run 99개 루트에서 검사는 약 0.9초였다(M11 마무리 중 로컬에서 한 번 잰 값, 로그는 커밋하지 않음).
- **대응**: 진단에 나온 run/job의 supervisor부터 정리한다. 공간이 필요하면 서비스를 멈추고, 보관할 run에 running·cleanup-pending 작업이 없는지 확인한 뒤, run 디렉터리 **전체**(이벤트와 객체 포함)를 오프라인 보관소에 복사한다. 파일 해시를 검증하고, 디렉터리를 runs 루트 밖으로 옮긴 다음, 옮긴 위치를 기록한다. 보관한 run은 디렉터리 전체를 되돌려 놓기 전까지 API로 열 수 없다. 이벤트 로그를 자르거나 객체를 그 자리에서 지우면 안 된다. 예약 전에 거부된 시도는 과금되지 않았으므로 조건을 해결한 뒤 다시 시작하면 된다.

### 오래 걸리는 작업 시작이 화면에서 실패로 보인다
- **증상**: 화학 작업 시작(동기 실행)이 30초를 넘기면 브라우저가 500을 받고 "작업 start 실패"를 보이지만, 백엔드에서는 작업이 끝까지 실행된다.
- **원인**: Next.js `/api` 프록시가 30초에 연결을 끊는다.
- **대응**: 승인 요청이 아닌 시작 오류가 나면 화면이 저장된 작업을 다시 읽어 실제 상태를 보여 준다(`chemicalStartProgressed`). 시작 응답만 보고 실패를 확정하지 않는다.

### 표현을 바꾼 뒤 저장·확대 버튼이 계속 비활성으로 남는다
- **증상**: M9 scenes-flow가 표현 변경 직후 "뷰어 세션 준비 중…"에서 멈췄다. M11 이전 main 빌드에서도 같았다(기존 결함).
- **원인**: 페이지는 렌더링할 때 Mol* 상태를 읽어 준비 여부를 계산한다. 서버 응답으로 먼저 다시 렌더링된 뒤 표면 재구성이 끝나면, 그 뒤로 렌더링을 일으키는 것이 없었다.
- **대응**: 표현 재구성이 끝나면(이미 ready를 보고한 경우에만) 뷰어가 ready를 다시 알린다. 바인딩을 바꾸지 않으므로 대기 작업을 취소하지 않는다. 같은 읽기에서 handle·hash가 같은 원자 카탈로그가 다시 오면 검증된 기존 객체를 유지한다(`retainCatalogState`).

### Host 헤더가 두 개면 프런트엔드 검사를 지나간다
- **증상**: :3000에 `Host: 127.0.0.1:3000`과 외부 Host를 차례로 보내면 200이 나오고 백엔드까지 간다.
- **원인**: Node HTTP 서버가 첫 번째 Host만 남기고, Next 미들웨어는 그 값만 본다. 프록시는 Host를 `127.0.0.1:8000`으로 바꿔 보내므로 백엔드 검사도 잡지 못한다.
- **대응**: 알려진 한계로 둔다(2026-09-28 사용자 결정). 브라우저는 Host를 하나만 보내므로 DNS 리바인딩은 막힌다. :8000은 uvicorn이 Host가 없거나 여러 개인 요청을 앱 전에 400으로 거부한다.

### 프런트엔드 CSS 수정이 토큰 재생성 후 사라진다
- **증상**: `frontend/src/design/components.css`에 추가한 스타일이 `npm --prefix frontend run tokens` 실행 뒤 없어진다.
- **원인**: 이 파일은 `design/build_tokens.py`가 `design/components.css`를 복사해서 만드는 생성물이다(첫 줄에 "edit the source" 주석이 있다). 복사하면서 원격 Google Fonts `@import`는 뺀다.
- **대응**: 스타일은 `design/components.css`에서 고치고 tokens 스크립트로 복사한다. 앱은 `@fontsource` 로컬 글꼴만 쓴다.
- **검증**: tokens 실행 뒤 `git diff frontend/src/design/components.css`가 의도한 변경만 보여야 한다.

### `.env`가 있는데 온라인 모드가 사용할 수 없음으로 나온다
- **증상**: 루트 `.env`에 `OPENROUTER_API_KEY`를 넣었는데 뷰어 온라인 해석이 unavailable로 표시된다.
- **원인**: 게이트는 환경변수를 먼저 보고, 없으면 루트 `.env`를 읽는다. 이때 `.env`가 일반 파일이 아니거나(심볼릭 링크 등) 그룹·기타 사용자 권한 비트가 하나라도 있으면 조용히 무시한다.
- **대응**: `chmod 600 .env`로 권한을 맞추거나 환경변수로 넘긴다. 키 노출을 막기 위한 동작이므로 완화하지 않는다.

### 과거 단계 `--verify`가 실패한다
- **증상**: `scripts/execute.py <phase> --verify`가 완료된 M0–M10 단계를 오래된 검토(stale)로 판정한다.
- **원인**: 검토 기록은 당시 파일의 SHA-256에 묶여 있다. 그 뒤 README.md 같은 공유 파일이 바뀌면 해시가 달라진다(현재 M11 작업 중 README 변경으로 대부분의 과거 단계가 이 상태다).
- **대응**: 과거 검토 파일이나 해시를 고쳐서 통과시키지 않는다. 현재 작업의 검토에서 바뀐 공유 소스와 회귀를 다시 검증하고, 어떤 과거 범위를 대체했는지 명시한다.
- **부작용 주의**: `--verify`는 실패할 때 `phases/index.json`과 그룹 `index.json`의 상태를 `error`로 고쳐 쓴다. 실행 전에 두 파일을 복사해 두고, 끝나면 복사본으로 되돌린다. `git checkout`은 커밋되지 않은 다른 단계 기록까지 되돌릴 수 있어 쓰지 않는다.

### fpocket이 긴 TMPDIR에서 SIGTRAP으로 죽는다
- **증상**: 설치된 fpocket 4.2.3이 exit −5(SIGTRAP)로 끝난다. pytest 임시 폴더처럼 깊은 run 루트에서만 난다.
- **원인**: TMPDIR 문자열이 약 220자를 넘으면 엔진 내부 경로 버퍼가 넘친다.
- **대응**: 작업 프로세스가 TMPDIR을 시도별 상대 경로 `../fpocket_tmp`로 준다(여전히 시도마다 비공개). qhull 임시 파일도 엔진 작업 폴더 기준이다. 절대 경로로 되돌리지 않는다.

### fpocket은 모르는 옵션을 조용히 무시한다
- **증상**: `--bogus_option 3`도 exit 0으로 끝난다. 짧은 `-A 3`(시험 실행)도 받아들인 것처럼 보였지만 getopt 문자열에 없다.
- **대응**: 옵션이 실제로 적용되는지는 exit code가 아니라 고정 소스의 옵션 표(`src/fparams.c`)로 확인한다. 근거는 `config/pockets/fpocket-4.2.3-parameters.json`에 있다. argv를 바꾸면 소스 근거부터 다시 확인한다.

### fpocket의 "포켓 없음" 진단은 stderr로 나온다
- **증상**: M12 계약은 빈 결과 진단이 stdout에 나온다고 적었지만, 실제로는 stdout에 시작·끝 배너만 있고 진단은 stderr에 나온다.
- **원인**: `src/refine.c`가 `fprintf(stderr, …)`로 쓴다. 시험 기록은 두 출력을 한 파일에 합쳐 저장했다.
- **대응**: scientific_null은 stdout 배너와 stderr `! No Pockets Found while refining` 1줄 + `! No pocket to reindex.` 2줄이 정확히 일치할 때만이다. 소스상 다른 빈 경로(정제 전 포켓 없음)는 관찰되지 않았으므로 거부하며, 받아들이려면 검토된 파서 버전이 필요하다.

### Score·Druggability Score는 같은 실행 안의 상대 점수다
- fpocket은 두 점수를 같은 실행에서 찾은 포켓들의 최소–최대 정규화로 계산한다. 다른 구조·다른 실행의 점수와 비교하거나 절대 기준으로 쓰지 않는다. 화면과 보고서는 이 한계를 항상 적는다.

### 1HSG는 OpenMM 최소화에 쓸 수 없다
- 공개 1HSG는 말단 OXT가 없어 OpenMM 준비가 거부한다(누락 원자를 만들지 않는 규칙). 최소화 구조가 필요한 QA는 1UBQ를 쓴다. 1UBQ에는 리간드가 없어 "최소화 구조에서 접촉 행 숨김"은 실제 화면으로 확인하지 못했다(`docs/tracking/findings.md`의 "M12 수락 QA에서 실제 화면으로 확인하지 못한 영역").

### 포켓 오버레이는 M8 작업 토큰이 아니라 자체 revision으로 보호한다
- 오버레이는 뷰어 세션·세대·소스·검증된 카탈로그와 자체 revision으로 확인한다. M8 작업 토큰을 쓰면 세션 재바인딩 때 오버레이가 조용히 취소된다. 세션이 바뀌면 오버레이를 다시 그린다.
- 포켓 패널은 run을 바꾸면 이전 패널의 대기 응답을 모두 버리고, 페이지도 현재 run의 소스가 아닌 오버레이·소스 전환 요청을 거부한다(두 겹). 늦은 geometry 응답이 새 run 화면에 적용되던 결함의 대응이다.

### git worktree에서 테스트가 주 체크아웃의 코드를 돌린다
- **증상**: worktree에서 고친 백엔드 코드가 테스트·서비스에 반영되지 않는다.
- **원인**: `.venv`의 `pip install -e './backend[dev]'`는 주 체크아웃의 `backend/`를 가리킨다. worktree에서 `.venv/bin/python`을 쓰면 `mw`를 주 체크아웃에서 import한다.
- **대응**: worktree에서는 `PYTHONPATH=<worktree>/backend`를 주고 돌린다. M13 수락 실행기는 서비스를 띄울 때 `PYTHONPATH=<code root>/backend`를 주고, `import mw`가 그 경로에서 오는지 먼저 확인한다.

### 예산 때문에 풀린 연결 호출이 자율 분기 가드를 올렸다
- **증상**: M13 코드 검토에서, run 활동 시간 예산 checkpoint로 시작하지 못하고 풀린(release) 흐름 단계를 다시 실행하면 같은 호출 키 제안이 쌓여 가드(`loop_stop`)가 걸렸다.
- **원인**: `Run.call`은 자율 branch 제안(`_propose`)을 기록한 뒤 실행 체인에서 활동 시간 예산·열린 작업을 확인한다. 흐름 호출(`decided_by=rule`, autonomous)도 이 순서를 따르면 시작하지 않은 호출이 제안으로 세어진다.
- **대응**: 연결된 호출은 제안을 기록하기 전에 활동 시간 예산과 닫히지 않은 작업을 먼저 확인한다. 시작할 수 없으면 제안 없이 풀린다. 연결 없는 호출의 순서와 이벤트는 바꾸지 않았다(기존 바이트 불변). 검증: `test_run_budget_release_never_raises_the_loop_guard_and_resumes_after_the_limit_change`, `test_retry_released_by_the_run_budget_never_raises_the_loop_guard`.

### 흐름 중지가 첫 요청에서 `stale_revision`을 받는다
- **증상**: 작업 단계가 도는 중에 "중지"를 누르면 409 `stale_revision`이 돌아온다(M13 수락 ST05에서 관찰).
- **원인**: 중지는 `expected_revision`을 요구하는데, 단계가 도는 동안 시도 기록·조정 이벤트가 revision을 올린다. 거절된 요청도 복구 조정 이벤트를 남길 수 있다.
- **대응**: 화면은 모든 거절 뒤 실행 기록을 다시 읽고, 중지는 `stale_revision`이면 새 revision으로 한 번 자동으로 다시 보낸다(`stopResend`). 다른 동작은 자동으로 다시 보내지 않는다. 이미 시작된 동기 도구 시도는 중지로 끊기지 않는다(끝까지 가서 과금되고 채택되지 않음).

### 하위 수락 실행기의 대장 형식이 서로 다르다
- **증상**: M13 수락 1차 실행이 fail이었다. M11 하위 실행기는 exit 0, 17/17 통과였는데 M13 대장에는 M11 단계 fail, 외부 요청 수 None으로 기록되었다.
- **원인**: M11 대장(`m11_case_ledger@1`)에는 `verdict` 키가 없고 `summary{pass, fail, missing}`·`nonLoopbackRequestsTotal`이 있다. M12 대장(`m12_case_ledger@1`)은 `verdict`·`externalRequestsTotal`이다.
- **대응**: 대장 schema별로 판정하는 `sub_ledger_verdict`(`scripts/m13_offscreen_acceptance.py`)와 단위 테스트(`scripts/test_m13_offscreen_acceptance.py`)를 둔다. 하위 실행기를 추가하면 그 대장 형식을 여기에 넣고 테스트한다.

### 수락 증거가 저장소에 넣기엔 너무 크다
- **증상**: M13 수락 실행 한 번의 내보낸 텍스트 증거가 약 331 MB였다. M11 하위 실행기의 `chemical-evidence.json`은 파일 하나가 최대 약 62 MB다.
- **대응**: 256 KiB를 넘는 텍스트 증거는 대장을 빼고 Git 제외 artifacts 폴더 `export-full/`로 옮기고 해시를 남긴다(결정 0020). 삭제하지 않는다.

### Mol* 측정 모드 원자 클릭이 가끔 빈 loci를 돌려준다
- **증상**: M13 수락 1차 실행의 M12 하위 실행기 `regression-m10-measure` C02-repeat-reverse에서 기준 원자 클릭 3회가 모두 Mol* `empty_loci`였고 "Mol* observation did not become ready"로 실패했다. 같은 사례를 단독으로 다시 돌리면 통과했고, 2차 실행에서는 세 실행기 모두 통과했다.
- **대응**: 원인은 확인하지 못했다. 실패 증거는 지우지 않고, 재실행 통과를 수락으로 세지 않는다(`--only`는 partial).

## 동작 원리

### handle과 복구
객체를 저장할 때는 먼저 정규화한 내용(JSON은 canonical JSON)으로 `sha256(kind, schema, raw)`를 계산하고 handle을 정한다. 그다음 객체 파일을 `O_NOFOLLOW`·0600으로 쓰고, 전체 payload(base64 포함)가 든 `object_created` 이벤트를 추가·fsync한 뒤 SQLite 색인을 갱신한다. 복구(`ObjectStore.rebuild_from_events`)는 이벤트를 순서대로 읽어 객체와 색인을 다시 만든다. 이미 있는 객체는 바이트가 같은지 확인하고, 다르면 실패한다. 그래서 객체 디렉터리와 SQLite를 지워도 되지만, `events.jsonl`은 잃으면 복구할 수 없다.

### 실행 소유권
run 하나를 바꾸는 호출 전체는 run 디렉터리의 `execution.lock`(OS advisory lock)을 잡고 실행한다. 잠금을 잡은 뒤 새 이벤트를 다시 읽고 판단한다. 두 번째 API 프로세스가 떠 있어도 같은 캐시 키를 두 번 실행하거나 마지막 예산 단위를 두 번 쓰지 못한다. 취소·종료 전이는 긴 실행 잠금이 아니라 짧은 `transitions.lock`을 쓰므로, 긴 작업이 도는 중에도 취소가 바로 전달된다. 잠금 파일이 있다거나 running 이벤트가 있다는 사실만으로는 작업이 살아 있다는 증거가 되지 않는다. OS 잠금과 검증된 프로세스 신원만 근거가 된다.

### 작업 프로세스 시작 핸드셰이크
1. run 소유권을 잡은 상태에서 검증·승인·예산을 확인하고, 시도 예약과 `dispatch_intent`(무작위 launch nonce 포함)를 먼저 기록한다.
2. guardian을 `start_new_session=True`, 최소 환경(LANG=C, PYTHONUTF8=1, 전용 TMPDIR, 자격 증명 없음)으로 띄운다. guardian은 과학 엔진을 import하지 않은 채 자기 PID·PGID·세션·raw 시작 신원을 receipt 파일에 fsync하고, 전용 socketpair로 HELLO를 보낸다.
3. 부모가 nonce와 신원을 검증해 `launch_identity`·`execution_authorized`를 기록한 뒤 GO를 보내야 guardian이 과학 작업 프로세스를 띄운다. guardian은 GO·STOP·채널 종료를 부모가 넘긴 상한(`--go-wait-s` = 작업의 남은 시간 + 5초, 최대 3600초)까지 기다린다. 예전의 고정 3초 대기는 run에 작업이 쌓여 부모가 느려지면 정상 시작을 포기하게 만들었다(M11 `replace_from_sdf` 실패 원인).
4. GO 전에 채널이 끊기거나 STOP을 받거나 상한이 지나면 과학 작업 없이 종료하고, GO 후에 끊기면 그룹을 정리한다. 부모 API가 죽었다고 과학 작업이 계속 돌지는 않는다.

화학 작업 프로세스 사용 가능 여부 확인은 성공한 핸드셰이크만 서버 프로세스 안에 캐시한다. 키는 인터프리터 경로·파일 정보, 잠금 파일 SHA-256, 작업 파일 SHA-256이다. `.deps/prolif/venv-locked`의 설치 패키지를 제자리에서 바꾸면 키가 바뀌지 않으므로 백엔드를 다시 시작해야 새 상태가 반영된다.

작업 상태 읽기(`JobQueue.get`/`list`, HTTP 조회)는 `transitions.lock`을 잡지 않고 이벤트 로그의 줄 단위 스냅숏에서 상태를 만든다. SQLite 색인은 쓰는 쪽과 `claim_next`만 다시 만든다. 조회가 잠금을 잡으면 1.2초 주기 폴링이 시작 승인·취소를 늦춘다.

신원이 불확실하면(권한 거부, 열거 실패, 신원 불일치) `cleanup_pending`으로 두고 대체 시도를 막는다. PID를 추측해서 신호를 보내지 않는다.

### 뷰어 세션과 세대
뷰어 세션은 `(run_id, client_instance_id, viewer_session_id, scene_generation, structure_handle)`에 묶인다. 표시 구조, 모델, 기록, 최소화 구조 전환이 일어날 때마다 generation이 올라간다. 명령은 매 await 전후에 session·generation·source·action revision을 다시 확인하고, 하나라도 바뀌었으면 적용하지 않는다. 그래서 늦게 도착한 모델 응답이 더 최근의 사용자 조작을 덮어쓰지 못한다.

## 체크리스트

### 새 과학 도구 추가
1. 결과 스키마를 정한다: 단위, 방법·버전, 한계, 입력 handle, 정확한 식별자.
2. `config/tools.yaml`(accepts, emits, cost_class, params 범위), `backend/mw/tools/` 구현, `workspace.py`의 `build_registry()` 등록, `app.py`의 `SUPPORTED_TOOLS`에 추가한다. 비싼 계산이면 JobQueue 프로토콜로 만든다.
3. 독립적인 수치 oracle 테스트를 쓴다(자기 함수와 비교하는 것은 oracle이 아니다). 좌표를 바꾸면 결과가 바뀌는지, scientific_null, 잘못된 입력, 식별자 경계(null label, 삽입 코드, altloc, 비첫 모델)를 확인한다.
4. events-only 복구 테스트: 원본 업로드·객체·SQLite를 지운 뒤 복구된 바이트가 같은지, 엔진 없이 다시 열리는지 확인한다.
5. 보고서를 만든다면 필드 단위 증거 검증에 새 필드 경로와 단위를 추가하고, 잘못된 행·단위·구조로 같은 숫자를 주장했을 때 거부되는지 테스트한다.
6. `/capabilities`와 UI의 사용 불가 표시가 같은 이유를 말하는지 확인한다.
7. 검증: 전체 게이트 명령과, UI가 있으면 오프스크린 컨트롤 검증까지 실행한다.
8. 외부 실행 파일 엔진(fpocket 등)은 해시 잠금 설치 스크립트, 실행 파일 해시 확인, 요청으로 바꿀 수 없는 경로, 허용 목록 환경변수, 알려진 출력 파일만 읽는 파서를 함께 만든다.

### UI 컨트롤 변경
1. 새 컨트롤이 MolstarViewer의 직렬화 브리지를 거치는지 확인한다. React state만 바꾸고 적용됐다고 표시하면 안 된다.
2. 백엔드와 프런트엔드를 loopback으로 띄운다: `.venv/bin/python -m uvicorn mw.api.app:app --host 127.0.0.1 --port 8000`과 `npm --prefix frontend run start -- -p 3000`.
3. `npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000`으로 `isOffscreen=true`, GPU 켜짐, paint 프레임, 외부 요청 0건을 확인한다.
4. 해당 흐름 스크립트(`test:offscreen:normal`, `:scenes`, `:chemical` 등)를 돌리고, 공유 뷰어·페이지 코드를 바꿨다면 M8 normal, M9 scenes, M10 comparison 회귀도 함께 돌린다.
5. 실패한 실행은 지우지 말고 회귀 증거로 남긴다.

### 제품의 실제 OpenRouter 호출이 필요할 때
1. 사용자에게 필요한 횟수와 이유를 말하고 한도를 받는다.
2. 전용 QA run에서 온라인 모드와 뷰어 동의를 켠다.
3. 호출마다 served model, 사용량, 발행한 명령, Mol* 확인을 기록한다. 키, 헤더, 원시 provider 오류는 기록하지 않는다.
4. 한도를 다 쓰면 결과를 그대로 보고한다. 추가 호출을 하려고 새 run을 몰래 열지 않는다.
