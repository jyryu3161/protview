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
- **M18 관찰**: 착수 확인 worktree에서 `PYTHONPATH` 없이 전체 백엔드 pytest를 돌리자, 경로를 비교하는 두 테스트(`test_ligand_jobs`의 guardian 경로, `test_reference_snapshots`의 `.deps/reference` 경로)가 주 체크아웃 경로와 달라 실패했다. 그 결과는 회귀 증거로 쓰지 않았다(`docs/qa/m18-docking-20261002/preflight.txt` 마지막 절). 설치 스크립트도 worktree의 `.deps` 심볼릭 링크가 아니라 주 체크아웃의 절대 경로(`--prefix`·`--destination`)로 실행했다(`t2-install.txt`).

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

### KLIFS 포켓은 일부 구역에서 잔기를 gap 표시 없이 뺀다
- **증상**: M15 KLIFS 번호 초안에서 b.l 구역이 대부분 번호를 얻지 못했다. 예: EGFR b.l 포켓 `VDPHVCR`에 대해 UniProt은 `VDNPHVCR`이라 연속 일치가 없다. linker 등 다른 구역에도 드물게 있다.
- **원인**: KLIFS 85자 포켓은 구조 정렬로 만든 것이라, 포켓 번호 사이의 서열 잔기를 `-`/`_` 없이 건너뛰는 경우가 있다.
- **대응**: 첫 단계(연속 일치가 유일한 구역만)는 그대로 두고, 바로 앞·뒤 구역이 모두 해결된 구역만 그 사이 구간에서 순서 유지 배치가 정확히 하나일 때 `klifs_match: "gapped_unique"`로 번호를 준다(결정 0023). 두 번째 단계 대상을 "가장 가까운 해결 구역"으로 넓히지 않는다(M15 독립 코드 검토에서 명세보다 넓다고 지적되어 좁혔다). a.l·I처럼 처음·마지막 구역은 이 단계 대상이 아니다.
- **검증**: `pytest backend/tests/test_klifs_numbering.py -q`, 측정 `scripts/measure_klifs_numbering.py`(`gapped_unique` 1,613 일치·17 불일치, 첫 고정 `c1d824d`).

### kbase SIFTS의 PDBe 번호는 엔티티마다 다시 시작하고, 예외 행의 `uniprot_resnum`은 UniProt 위치가 아니다
- **증상**: SIFTS 잔기 행을 PDBe 번호만으로 찾으면 같은 체인 행 안의 리간드·물 엔티티 행과 섞인다. 예외 행의 `uniprot_resnum`을 UniProt 위치로 읽으면 엉뚱한 위치가 나온다.
- **원인**: kbase `pdbe-residue-runs-v1`은 PDBe 잔기 목록을 run으로 압축한 것이다. 한 체인 행에 여러 엔티티가 섞여 있고 PDBe 번호는 엔티티마다 1부터 다시 시작한다. 예외 행은 PDBe 번호를 `uniprot_resnum`이라는 이름의 필드에 담는다(kbase 쪽 이름). 열 값과 `insertion_codes`는 kbase의 행 정렬 순서로 색인된다.
- **대응**: 잔기는 항상 (엔티티, PDBe 번호)로 다루고, 그 체인에 UniProt segment가 있는 엔티티만 잇는다. 예외 행 필드는 PDBe 번호로 읽는다. 복원한 행 수·열 길이·삽입 코드·`not_observed` ↔ `observed_ratio == 0`을 교차 확인하고, 하나라도 어긋나면 그 체인을 `sifts_chain_lookup_failed`로 쓰지 않는다(추측하지 않음). kbase 코드는 import하지 않고 형식만 읽어 `backend/mw/sifts_mapping.py`에 다시 구현했다.
- **검증**: `pytest backend/tests/test_sifts_mapping.py -q`, 1MQ4 체인 A PDBe 번호 = `label_seq_id` 확인(`docs/qa/m15-numbering-20260930/pdbe_label_check.txt`).

### SIFTS segment의 `chain_id`가 author 체인 ID와 다를 수 있다
- **증상**: 6Z1Q의 segment 행은 `chain_id`가 `AAA`/`BBB`인데 잔기 행 체인은 `A`/`B`다.
- **대응**: segment는 `chain_id == chain_auth`로만 고른다. 맞는 segment가 없으면 그 체인은 `sifts_chain_no_segments`(또는 잔기 행 조회 실패면 `sifts_chain_lookup_failed`)로 SIFTS를 쓰지 않는다. 이름이 비슷하다고 이어 붙이지 않는다. segment 행에는 `chain` 키가 없을 수도 있다(그 엔트리를 가져오게 한 체인일 뿐).

### 최적 정렬이 여럿이면 동점 규칙이 떨어진 말단 잔기를 틀린 위치에 둔다
- **증상**: 1MQ4 체인 A의 C 말단 S388은 구조에서 앞 잔기들과 떨어져 있어, 고정 동점 규칙(M > X > Y, 끝에서 역추적)만으로는 UniProt 403에 놓였다. SIFTS는 다른 위치를 준다. 교차 확인 없는 정렬 경로라면 틀린 `mapped`가 된다.
- **원인**: 떨어진 잔기 하나를 여러 자리에 두어도 점수가 같은 최적 정렬이 여럿 있다. 동점 규칙은 결정적이지만 맞다는 보장은 없다.
- **대응**: 앞·뒤 Gotoh 계산으로 모든 최적 정렬을 정확히 보고, 어떤 잔기가 모든 최적 정렬에서 같은 UniProt 위치에 놓이지 않으면(gap 포함) `alignment_ambiguous`로 답을 없앤다(결정 0023). 통계는 여전히 동점 규칙으로 고른 정렬 하나에서 계산한다.
- **검증**: `pytest backend/tests/test_sequence_alignment.py backend/tests/test_residue_numbering.py -q`, M15 수락 N-conflict-row·N-alignment-only.

### 같은 스냅샷 파일을 다시 가져와도 세트 해시가 바뀐다
- **증상**: `.deps/reference`의 측정 세트(`aa21ead9…`)와 수락 QA가 새로 가져온 세트(`1ad8413f…`)는 파일 바이트가 같은데 세트 해시가 다르다. 다시 가져온 뒤에는 기존 대응이 모두 "이전 스냅샷 기준"으로 보이고, 같은 요청도 새로 계산된다.
- **원인**: 세트 해시는 매니페스트 바이트의 SHA-256이고, 매니페스트에 `imported_at`이 들어간다.
- **대응**: 설계대로다(가져오기마다 새 기록). 두 세트의 파일이 같은지 보려면 매니페스트의 파일별 SHA-256을 비교한다. 다시 가져오기를 "변경 없음"으로 취급하려면 별도 결정이 필요하다.

### M15 수락 실행기의 `--kbase` 기본값은 git worktree에서 틀리다
- **증상**: worktree에서 `scripts/m15_offscreen_acceptance.py`를 기본값으로 돌리면 `--kbase has no ref/manifest.json`으로 멈춘다.
- **원인**: 기본값이 `<저장소>/../kbase_kinase`라서, worktree 위치 기준으로는 kbase 체크아웃이 없다.
- **대응**: `--kbase`에 절대 경로를 준다(2026-09-30 수락 QA도 그렇게 실행).

### git worktree에는 `.deps`와 `frontend/node_modules`가 없다
- **증상**: worktree에서 전체 백엔드 pytest의 분석 흐름 테스트(작업 프로세스 환경을 쓰는 것)가 실패하고, 프런트 테스트·빌드는 모듈을 찾지 못한다.
- **원인**: `.deps/`(ProLIF·fpocket 작업 환경, 참조 폴더)와 `frontend/node_modules/`는 Git 제외라 worktree에 따라오지 않는다.
- **대응**: 테스트하는 동안만 주 체크아웃의 `.deps`와 `frontend/node_modules`를 worktree에 심볼릭 링크로 두고, 커밋 전에 링크를 지운다(커밋하지 않음). 백엔드는 여전히 `PYTHONPATH=<worktree>/backend`가 필요하고(위 함정), kbase를 읽는 테스트는 `MW_KBASE_REF`를 준다.

### 하네스의 PNG 범례 영역은 제품의 줄바꿈 기하를 따라야 한다
- **증상**: M16 수락 시도 1에서 픽셀 검사 `M13-pixels`가 실패했다(legendInside 0.0831 < 20 × legendOutside 0.00466). 제품 PNG의 범례는 올바르게 그려져 있었다.
- **원인**: 코드 검토 수정(`cc3da8e`)이 범례를 같은 글자 크기로 줄바꿈하게 바꿔 상자가 47 px에서 54 px(729–782행)로 커졌는데, 하네스 `legendRegion()`은 예전 높이(y0=734)를 고정값으로 가정했다.
- **대응**: 하네스가 범례 영역을 제품의 `wrapLegendText`와 같은 글자 크기·여백·줄 간격 상수로 계산한다(`3a2e20c`). 이 검사는 제품과 기하 계산을 공유하므로 제품 줄바꿈 계산 자체의 오류는 잡지 못한다. 판정은 "범례 상자 안 변화 픽셀 밀도 ≥ 20 × 상자 밖 밀도, 상자 밖 ≤ 0.01"이며 상자 밖 변화 픽셀이 0이라는 뜻이 아니다(다시 렌더링한 그림 사이의 안티앨리어싱 차이가 상자 밖에도 있다). 범례 모양을 바꾸면 하네스도 함께 확인한다.

### Mol* 이미지 패스에는 주석 도형(점선 등)이 담긴다 (픽셀로 확인)
- **증상**: 명세는 "그림 캡처에 이름표·점선이 담기지 않으면 멈춘다"를 조건으로 두었다. Mol* 측정 도형(`addLabel`·`addDistance`)이 PNG 이미지 패스에 들어가는지는 코드만으로 확실하지 않았다.
- **확인**: M16 수락 시도 2에서 같은 카메라의 세 PNG를 디코드해 점선 색 픽셀을 셌다. 범례 켠 그림 139, 범례 끈 그림 87, 주석 끈 그림 0. 주석을 켠 그림과 끈 그림은 다르다(이름표는 색으로 따로 세지 않았다)(`docs/qa/m16-annotations-20261001/acceptance-attempt2/`).
- **대응**: 그림 저장은 뷰어가 그린 주석과 보기의 주석이 같을 때만 허용하고(`captureScene`·`captureFigure`가 다르면 거부), 범례는 그 뒤 PNG에 합성한다. Mol* 버전을 바꾸면 이 픽셀 확인을 다시 한다.

### null을 허용하는 handle 인자는 사전 검사 훅으로 검증한다
- **증상**: `annotate_reference_sites`의 `contacts`를 일반 `accepts` handle 인자로 선언하면 null(접촉 없이 주석)을 보낼 수 없고, 잘못된 종류의 handle은 `input_invalid`가 아니라 `precondition`으로 분류된다.
- **원인**: 레지스트리의 일반 인자 검사(`check_args`)는 handle 인자의 null을 거부하고, 종류 불일치를 선행 조건 부족으로 본다.
- **대응**: `contacts`는 `params`(기본 null)로 두고, 두 handle은 M15와 같은 레지스트리 사전 검사 훅(`precheck`)에서 일반 검사보다 먼저 검증한다(종류·run·구조 일치, 중복 부위 행). 이 훅은 `bound`를 돌려주지 않으므로 호출 키는 정규화한 인자 그대로다. 훅이 없는 기존 도구의 호출 키·이벤트는 바뀌지 않는다(`test_residue_numbering.py`의 훅 도구 집합 기대값에 이 도구를 더했다).

### 구조 분석 탭 패널은 탭에 들어올 때 번호 대응 목록을 다시 읽어야 한다
- **증상**: 지식 탭에서 번호 대응을 만든 뒤 구조 분석 탭으로 돌아와도 참조 주석 패널에 새 대응이 보이지 않았다(M16 흐름 작업 중 발견, `1e94779`에서 수정).
- **원인**: 구조 분석 탭은 다른 탭이 보일 때도 언마운트하지 않으므로(M14 불변 조건), 패널이 처음 마운트될 때 한 번만 목록을 읽었다.
- **대응**: 페이지가 구조 분석 탭에 들어올 때마다 `mapsReloadToken`을 올려 패널이 목록을 다시 읽는다(읽기만, 이벤트·도구 없음). 숨긴 채 유지되는 화면이 다른 탭에서 만든 객체를 보여야 하면 같은 방식을 쓴다.

### RDKit의 HBD/HBA 함수는 두 정의가 있다 (M17)
- **증상**: methacetin의 HBA가 함수에 따라 3 또는 2로 나온다.
- **원인**: `rdMolDescriptors.CalcNumLipinskiHBD/HBA`(Lipinski 정의: NH+OH / N+O)와 `CalcNumHBD/HBA`(`Lipinski.NumHDonors/NumHAcceptors`, 다른 정의)가 다르다.
- **대응**: 명세의 "Lipinski 정의"는 반드시 `CalcNumLipinskiHBD/HBA`로 계산하고 정의 이름을 결과의 `property_methods`에 남긴다. 회전 결합은 `CalcNumRotatableBonds` 기본값(Strict)이다(`docs/qa/m17-ligand-20261001/preflight.txt` 5.1–5.2).

### RDKit 원자 인덱스는 SDF 번호가 아니다 (M17)
- **증상**: 수소가 명시된 SDF에서 원자 표·그림의 번호가 SDF 원자 블록 순번과 다르다.
- **원인**: `RemoveHs` 뒤 RDKit 인덱스는 중원자만 다시 센 내부 번호다. `MolFromMolBlock`의 기본(`removeHs=True`)은 원래 순번 속성을 남기지 않고, `MolDraw2D`의 `addAtomIndices`는 내부 인덱스를 그린다.
- **대응**: `MolFromMolBlock(removeHs=False)`로 읽어 모든 원자에 `sdf_serial` 정수 속성을 넣은 뒤 `RemoveHs`한다(속성은 남는다). 그림 번호는 원자 속성 `atomNote`에 SDF 번호 문자열을 넣는다. 번호가 필요한 모든 곳(원자 표, 결합 목록, 부위, `retained_parent_atoms`, 생성물의 코어 원자 추적)은 `sdf_serial`만 쓴다.

### 표시 원자 `*`·`R#`는 원자번호 0으로만 판별한다 (M17)
- **증상**: SDF `R#`에 `M  RGP` 줄이 있으면 기호가 `R1`, 정규 SMILES가 `[1*]…`로 나온다(R 라벨이 isotope로 들어감). 없으면 `R#`·`*…`다.
- **대응**: 표시 원자는 `GetAtomicNum() == 0`으로만 판별한다. 기호나 SMILES 문자열로 판별하지 않는다. 고정 교체는 표시 원자를 지우므로 산출물에는 R 라벨이 남지 않는다(착수 확인 1.4).

### 2D 그림 SVG가 큰 부모에서 256 KiB를 넘는다 (M17)
- **증상**: 기본(FreeType) `MolDraw2DSVG`는 번호 라벨을 글자 모양 경로로 그려, 중원자 약 120개부터 256 KiB를 넘는다.
- **대응**: `noFreetype` 출력(라벨이 `<text>`)을 쓴다. 그래도 중원자 약 230개를 넘으면 넘으므로(부모 한도 256보다 낮음) 그런 부모의 점검은 `resource_exceeded`(`svg_limit`)로 실패한다. 상한을 올리거나 그림 없이 점검을 성공시키려면 사용자 결정이 필요하다(`docs/tracking/findings.md`).

### 리간드 작업의 입력 스테이징은 일반 작업 한도를 넘는다 (M17)
- **증상**: 부모와 block 파일 두 개(각 10 MiB)를 base64로 넘기면 일반 작업 입력 한도 4,000,000 B에 걸린다.
- **대응**: 이 두 프로토콜만 스테이징 한도 48 MiB(`ligand_bundle.STAGED_LIMIT`, 작업 모듈의 읽기 한도와 같음)를 쓰고, 결과 한도는 32 MiB다. 입력 바이트는 작업 기록에 넣지 않고 스테이징 때 불변 가져오기 객체에서 다시 읽어 SHA-256을 대조한다. 다른 프로토콜의 한도는 바꾸지 않았다.

### 생성 작업은 규칙 텍스트를 요청에서 받지 않는다 (M17)
- 생성(`rdkit_enumerate_v1`) 요청은 `rule_ids`만 받고, 서버가 점검 객체에서 `valid`인 규칙의 텍스트를 꺼내 스테이징한다. 화면이 규칙 텍스트를 다시 보내게 바꾸면 점검하지 않은 규칙이 생성에 들어갈 수 있다. 규칙 SMARTS 오류는 서버가 RDKit 없이 알 수 없으므로 점검 작업(예산 1단위)을 돌려야 드러난다.

### 보고서 금지어 "활성" 때문에 "활성 필터"라고 쓸 수 없다 (M17)
- 리간드 보고서는 "활성"을 해석 금지어로 거부하고, 화면도 같은 문구를 쓴다. 필터가 켜진 상태는 "적용한 필터"라고 쓴다(`frontend/src/lib/ligand.ts`). 새 문구를 더할 때 `ligand_reports.INTERPRETIVE`에 걸리는지 확인한다.

### 필터 경계는 화면과 서버에서 숫자 형식이 다르다 (M17)
- 화면은 사용자가 입력한 경계 문자열을 그대로 쿼리로 보내고(코드 검토 수정 `e6ab4f9`), 서버(`ligand_reads._number`)는 정수 모양이면 int, 아니면 float로 바꾼다. 그래서 `1.0000000000000001`은 서버에서 1.0이 된다. 경계 비교는 서버만 하고 화면은 다시 하지 않는다. 보고서 요청 본문은 숫자 그대로 보낸다.

### `decimalHalfUp`은 지수 표기를 푼다 (M17, M16과 공용)
- **증상**: `frontend/src/lib/site-annotation.ts`의 `decimalHalfUp`은 JS `String(value)`가 `1e-7`처럼 지수 표기이면 그대로 돌려줬다.
- **대응**: 코드 검토 수정(`e6ab4f9`)에서 Python `Decimal(str(v))`처럼 지수 표기를 풀어 반올림한다(`1e-7` → `0.00`). M16 사용처는 지수 표기 입력에서만 결과가 달라진다(M16 회귀 통과).

### 이름 없는 block 번호와 거부 목록 `ordinal`은 다른 순번이다 (M17)
- `block_<n>`은 가져온 순서의 모든 라이브러리를 이은 연속 레코드 순번이고(코드 검토 수정 `e6ab4f9`, 그 전에는 라이브러리마다 다시 세어 두 라이브러리의 이름 없는 레코드가 같은 이름이 될 수 있었다), 거부 레코드 목록의 `ordinal`은 그 라이브러리 안 순번이다. 두 값을 섞어 레코드를 찾지 않는다.

### 미리보기와 후보 집합의 `retained_parent_atoms`는 뜻이 다르다 (M17)
- 미리보기 `site_check.retained_parent_atoms`(`ligand_site.check_site`)는 코어 중원자 + 코어에 붙은 명시적 수소 번호다. 후보 집합(과 후보 행)의 같은 이름 필드는 코어 중원자만이다(명세 4.4). 화면은 후보 집합 쪽을 쓴다. 이름을 바꾸면 저장 객체·보고서·화면이 함께 바뀌므로 그대로 두었다(`docs/tracking/findings.md`).

### 비싼 계산 승인 UI는 run의 첫 작업에서만 나온다 (M17)
- 승인은 run 단위라 리간드 탭에서는 보통 첫 점검에서만 승인 안내가 나오고, 같은 run의 생성 작업은 승인 없이 시작된다. 오프스크린 검사에서 생성 쪽 승인 UI를 기대하면 안 된다. 승인 안내는 작업 시작·queued 이탈 때 지운다(`e6ab4f9`).

### 리간드 탭 패널의 늦은 응답은 두 층으로 버린다 (M17)
- 패널은 run·점검 선택이 바뀌면 진행 중 요청을 abort하고, 영역별 요청 순번(stamp)이 맞지 않는 응답도 버린다. M17 수락 QA의 run 전환 사례(`L-run-switch-late`)는 abort 층만 실제로 관찰했다. stamp 층은 `frontend/tests/ligand.test.cjs`로만 확인한다.

### Meeko 수용체 준비(`Polymer`)는 모르는 잔기 템플릿을 인터넷에서 받으려 한다 (M18)
- **증상**: 공개 준비 예제 `prolif-vina-rec.pdb`에 `Polymer.from_pdb_string`을 부르면 `PolymerCreationError`가 나고, 그 전에 `https://files.rcsb.org/ligands/download/HSE.cif`를 받으려 했다(착수 확인의 socket 차단기가 getaddrinfo 5회를 막음). 히스티딘 템플릿을 지정해도 합쳐진 말단 캡 잔기 4개(A:38, A:249, B:298, B:387)가 템플릿과 맞지 않았다.
- **원인**: Meeko 0.8.0은 `residue_templates`에 없는 잔기 이름(CHARMM `HSD`·`HSE`)을 만나면 `chemtempgen.fetch_from_pdb`로 템플릿을 내려받는다. `allow_bad_res=True`는 맞지 않는 잔기를 지우고 진행하며, 출력은 원자 이름을 템플릿 이름으로 바꾼다(`HN`→`H` 등).
- **대응**: `Polymer` 경로를 쓰지 않는다. M11 화학 추론(MDAnalysis `MDAnalysisInferrer`)으로 만든 RDKit 그래프를 공유 결합 조각마다 `MoleculePreparation`에 넘기고(분자 전체를 넘기면 "RDKit molecule has 2 fragments. Must have 1."), 입력 순서·이름·좌표로 ATOM 줄을 쓴다. 작업 모듈은 화학 패키지 import 전에 Python socket을 막는다(`_deny_network`). Meeko 자체 수용체 경로와 비교해 AD4 유형 불일치 0, 전하 차 ≤ 0.004였다(`docs/qa/m18-docking-20261002/preflight.txt` (c)).

### Meeko는 평면 SDF를 말없이 받고, 암시 수소 SDF에는 자기 오류를 낸다 (M18)
- **증상**: z가 모두 0인 SDF도 Meeko가 PDBQT로 만든다. 암시 수소가 남은 SDF는 Meeko가 "RDKit molecule has implicit Hs. Need explicit Hs."로 `ValueError`를 낸다.
- **대응**: 작업 모듈이 Meeko 전에 직접 검사한다: 모든 원자의 z가 같으면 `ligand_not_3d`, 암시 수소가 있으면 `ligand_hydrogens_missing`(닫힌 이유). Meeko 예외 문자열을 이유로 쓰지 않는다.

### qvina 탐색은 상자 값의 마지막 비트에 민감하다 (M18)
- **증상**: 범위 상자 중심이 `0.7175000000000002` 같은 부동소수 잡음을 가지면, 기록한 값과 qvina가 읽는 값이 달라질 수 있다.
- **대응**: 범위 상자(리간드·인스턴스)의 중심·크기를 1e-6 Å로 반올림해(`BOX_DECIMALS = 6`) 기록하고, 같은 값을 `repr`로 qvina 인자에 넘긴다. 입력 좌표는 소수 셋째(PDB)·넷째(SDF) 자리라 이 반올림은 잡음만 없앤다.

### `--score_only`는 상자를 보지 않는다 (M18)
- 기준 포즈의 `--score_only` 값(−12.21087)은 상자 인자를 줘도 빼도 같았다(착수 확인 (e)). 코어 고정은 상자 인자 없이 `--score_only --cpu 1`만 부른다. 상자는 코어 고정에서 `atoms_outside_box` 계산과 `box_no_receptor_atoms` 검사에만 쓰인다.
- qvina는 큰 충돌 값을 지수 표기(예: `1.2e+05`)로 낼 수 있다. 파서는 유한 10진수(지수 허용)만 받고 nan·inf·넘침·형식 오류는 `engine_output_invalid`다(코드 검토 수정 `283cc72`).

### 같은 seed라도 qvina stdout은 실행마다 다르다 (M18)
- **증상**: 같은 입력·seed·`--cpu 1` 두 번의 stdout이 "searching finished in … seconds" 줄만 다르다.
- **대응**: 재현 비교는 stdout이 아니라 출력 PDBQT(또는 파싱한 점수·좌표)로 한다. 착수 확인에서 출력 PDBQT 두 개가 바이트 동일했고, 수락 QA 재현 검사는 저장 점수와 전체 모드 SDF 바이트를 비교했다. 출력 PDBQT의 점수는 소수 첫째 자리 문자열뿐이다(`REMARK VINA RESULT: -13.6 …`).

### 도킹 포즈의 원자 순서는 입력 순서가 아니다 (M18)
- **증상**: Meeko `RDKitMolCreate.from_pdbqt_mol`로 되돌린 분자는 정규 SMILES는 같지만 원자 순서가 입력 SDF 순서가 아니라 SMILES 순서였다.
- **대응**: 리간드 PDBQT를 `add_index_map=True`로 써서 `REMARK INDEX MAP`(입력 순번 ↔ PDBQT 순번)을 읽고, 포즈 좌표를 입력 원자 순서로 되돌린다(`restore_pose`). PDBQT에 없는 원자는 Meeko가 병합한 비극성 수소뿐이어야 하며, 그 위치는 포즈 중원자에서 RDKit `AddHs(addCoords=True)`로 다시 놓는다. 그래서 포즈 SDF 원자 i = `ligand_serial` i = 입력 SDF 순번 i다.

### 구속 임베딩은 코어 좌표를 그대로 두지 않는다 (M18)
- **증상**: `EmbedMultipleConfs(coordMap=…)`로 만든 형태는 코어 원자 사이 거리만 구속되어 좌표계가 부모와 다르고, 코어로 강체 맞춤해도 최대 이탈이 0.118–0.125 Å 남았다(착수 확인 참고 절).
- **대응**: 맞춤 뒤 코어 중원자 좌표를 부모 좌표로 덮어쓴다(연결부 결합 길이가 조금 변형됨). 그래서 `core_max_deviation_A`는 정의상 0에 가깝고 덮어쓰기 전 잔차는 기록하지 않는다(결정 0026, `docs/tracking/findings.md`).

### qvina conda 패키지에는 `vina`도 들어 있다 (M18)
- conda-forge `qvina 2.1.0`은 `qvina2` 외에 `vina`(AutoDock Vina 1.1.2), `vina_split`, `qvina2_split`, `qvinaw`, `qvinaw_split`을 설치한다. 작업 모듈은 고정 경로 `qvina2`만 실행하고 `vina`는 설치 기록에 해시만 남긴다. 엔진 출력은 "affinity (kcal/mol)"라고 쓰지만 제품은 이 낱말을 옮기지 않는다.

### 도킹 작업의 입력 스테이징도 일반 작업 한도를 넘는다 (M18)
- 수용체·사이드카·SDF(각 최대 10 MiB)를 base64로 넘기면 일반 작업 입력 한도 4,000,000 B에 걸린다. `qvina_dock_v1`은 스테이징 한도 48 MiB(`docking_bundle.STAGED_LIMIT`, 작업 모듈 읽기 한도와 같음), 결과 한도 4 MiB를 쓴다. M17처럼 입력 바이트는 작업 기록에 넣지 않고 스테이징 때 불변 가져오기 객체에서 다시 읽어 SHA-256을 대조한다.

### 작업이 도는 동안에는 행 결과를 게시할 수 없다 (M19)
- **증상**: 명세는 "행이 끝날 때마다 게시"를 원했지만, 착수 확인에서 M18과 같은 게시 검증으로는 실행 중 게시가 불가능했다.
- **원인**: 게시 증거 순서는 예약(`budget_reserved`) → 정리 확인(`job_cleanup_verified`) → 결과 후보 → 종료이고, 정리 확인은 작업 프로세스 그룹이 비었음을 확인한 뒤에만 기록된다. guardian 메시지도 STARTED·RESULT 둘뿐이고 RESULT는 작업 프로세스가 끝난 뒤에 온다. `_terminal`은 `cancelled`·`interrupted`·`failed`에서 `output_handles`를 비운다. 게다가 감독 루프는 0.05초마다 이벤트 로그 전체를 다시 접으므로 실행 중 수백 KB 객체 이벤트를 쓰면 폴링이 점점 무거워진다.
- **대응**: 작업 모듈이 `rows/<n>.started`·`<n>.result.json`·`<n>.status.json`과 `prepared.json`을 원자적으로(임시 파일 + fsync + `os.replace` + 디렉터리 fsync, 쓰는 동안 SIGALRM·SIGTERM 막음) 쓰고, 서버(`docking_batch_jobs.finish`)가 정리 확인 뒤 어떤 종료 상태에서든 그 파일로 행을 게시(`docking_batch_row_published`)하고 요약을 마지막에 게시한다(결정 0027). `done` 작업의 `output_handles`에는 요약 하나만 둔다(작업 읽기가 목록의 모든 handle을 읽으므로 51개를 넣지 않음). 진행 표시는 이벤트가 아니라 시도 디렉터리의 `rows/*.status.json` 개수다.
- **검증**: `pytest backend/tests/test_docking_batch_jobs.py -q`(취소·시간 소진·작업 프로세스 중단·서버 재시작 복구 뒤 행 결과와 요약).

### 수용체 PDBQT를 한 번만 준비해도 행 결과는 바이트 동일하다 (M19)
- `docking_result@1` 내용에는 수용체 PDBQT 텍스트가 들어가지 않고, 같은 수용체 바이트에서 준비한 PDBQT는 같다. 그래서 일괄은 `docking_worker.receptor_inputs`·`receptor_prepared`를 한 번 부르고 행마다 `dock_row(…, prepared)`를 부른다. 착수 확인에서 7행 모두 단독 M18 작업과 출력 바이트·handle·`input_sha256`이 같았고, 같은 프로세스에서 행을 이어 돌려도(RDKit·Meeko 상태 공유) 바뀌지 않았다(`docs/qa/m19-batch-20261003/preflight.txt` (a)). 행 계산을 일괄 작업 모듈에 복제하지 않고 M18 모듈의 함수를 파일 경로로 불러 쓰는 것이 이 동등성을 구조적으로 지킨다. M18 `dock()`은 `dock_row(…, None)`이며 동작·바이트가 같다(M18 테스트 전부 통과).
- 수용체 준비 결과를 행 사이에 공유하는 다른 최적화(예: Meeko 상태 재사용 범위 확대)를 더하면 단독 M18 결과와의 바이트 비교를 다시 한다(`test_docking_batch_worker.py`).

### M18 호출 키에 작업 모듈 해시가 들어가 추출만 해도 재사용이 끊긴다 (M19)
- **증상**: M19 전에 만든 M18 도킹 결과가 같은 입력의 일괄 행에서 재사용되지 않고 새로 계산된다(handle은 같다).
- **원인**: 재사용 키는 M18 호출 키 전체이고 pin에 `docking_worker.py` SHA-256이 들어간다. M19가 행 계산 함수를 동작 변경 없이 추출해 파일 해시가 바뀌었다.
- **대응**: 설계대로다(결정 0027, 같은 호출 키 = 같은 계산 규칙 유지). `docking_worker.py`를 고치면 그 전 결과의 재사용이 모두 끊긴다는 점을 변경 때 기록한다.

### 숨은 900초 상한이 두 군데 있다 (M19)
- **증상**: 프로토콜 상수만 7800초로 두면 일괄 제출이 `invalid job timeout` 또는 422로 거절된다.
- **원인**: `JobQueue.submit`의 프로토콜별 상한(OpenMM·화학·포켓·리간드 후보 120, 그 밖 900)과 API 모델 `JobSubmit.timeout_s`(`le=900`)가 따로 있다. `docking_constants.TIMEOUT_MAX_S = 900`은 M18 capability 표시용이다.
- **대응**: 두 곳 모두 이 프로토콜만 7800을 허용한다(API는 `le=7800`, 큐가 다른 프로토콜을 각자 상한으로 거절). 긴 작업을 새로 만들면 두 곳과 마감 계산(min(남은 활동 시간, `timeout_s`))을 함께 본다. guardian의 `MAX_GO_WAIT_S` 3600은 GO 대기 상한일 뿐이고 실행 시간 상한이 아니다. psutil 신원 기록에는 나이·만료 개념이 없다.

### 증액 직후 런타임 오버헤드 과금으로 다시 부족해진다 (M19)
- **증상**: 활동 시간 부족분만큼 정확히 올리면, 증액 요청 자체의 `_mutation`이 끝날 때 `runtime_overhead`를 몇 ms 청구해 잔여가 필요량보다 작아지고 일괄 제출이 다시 `batch_limit_raise_required`가 된다.
- **대응**: 활동 시간 증가분에 `RAISE_MARGIN_S` 60초를 더한다(조정 가능, 결정 0027). 증액 판단·계획·응답은 모두 `Run.raise_limits`가 실행 잠금 안에서 쓰는 `run.budget.snapshot()`(과금된 사용량)으로 한다. 활동 중 경과를 더한 `budget_snapshot()`으로 판단하면 승인 응답과 실제 증액이 어긋난다(T11 검토 수정 `4aa9fc2`). 시작 전 확인은 `budget_snapshot()`을 보여 주므로 두 값이 활동 중에는 조금 다를 수 있다.
- 사용량이 이미 한도를 60초 넘게 넘은 run은 한 번의 증액으로 부족분이 0이 되지 않는다(증가분이 필요량 + 60초로 묶임). 다시 명시적으로 승인한다.

### `Run.update_limits`에는 HTTP 경로가 없다 (M19)
- `update_limits`는 테스트에서만 불린다. 사람의 증액은 형제 함수 `Run.raise_limits(plan, by="human")`(실행 잠금 안에서 스냅숏으로 증가분을 계획, 증가분이 모두 0이면 이벤트 없음, `budget_limit_updated`에 `context` 추가)이고, 이것을 부르는 곳은 `docking_batch_jobs.limit_approval` 하나, 그것을 부르는 곳은 HTTP 라우트 하나다(`test_docking_batch_budget.py`가 AST로 확인). 다른 경로(도구·흐름·뷰어)에서 한도를 올리는 코드를 더하면 이 테스트가 실패해야 한다. `budget_limit_updated`의 재생(`_refresh`)은 `limits`만 읽으므로 맥락 필드를 더해도 events-only 복구가 같다.

### 재사용 색인은 일괄로 게시된 행도 넣어야 한다 (M19)
- **증상**: 단독 M18 작업만 색인하면, 일괄로 계산한 후보를 같은 설정의 두 번째 일괄이 다시 계산한다.
- **원인**: 일괄 행 결과는 `job_terminal`의 `output_handles`가 아니라 `docking_batch_row_published`로만 게시된다.
- **대응**: `docking_batch_inputs.published_m18_results`가 단독 작업의 완료 기록과 일괄 행 게시를 모두 넣는다(행의 M18 호출 키는 일괄 작업 기록의 행 선택 기록과 일괄의 M18 pin으로 다시 만든다). 재사용 전에 `docking_bundle.validated_result`로 다시 검증하고 `input_sha256`도 대조한다.

### 같은 handle을 게시한 작업이 둘이면 `producer()`는 가장 먼저 게시한 쪽을 돌려준다 (M19)
- 같은 입력이면 같은 handle이므로 단독 M18 작업과 일괄 행이 같은 `docking_result`를 각각 게시할 수 있다. `docking_bundle.producer()`는 두 증거 중 게시 순번이 이른 쪽을 고른다(일괄 행은 요약 게시가 있으면 그 순번, 없으면 행 게시 순번). 그래서 나중 게시가 이미 만든 읽기·보고서의 대조 기준을 바꾸지 않는다. 일괄 행 증거의 `job`은 그 행의 선택 기록을 끼운 보기(`{**job, "selected": rows[i]["selected"]}`)라 M18 검사가 그대로 적용된다.
- 행 증거는 요약 게시를 요구하지 않는다(T11 검토 수정 `f3cc8c6`). 요약을 만들 수 없어 작업이 실패해도 검증된 행은 읽히고 재사용된다.

### 일괄 읽기는 행마다 다시 검증해 느리다 (M19)
- `GET /docking/batches`·`/detail`·`GET /jobs`(일괄 작업의 `batch` 필드)는 요약을 읽을 때마다 단일 게시, 일괄 선택 기록, 모든 행 결과(`validated_result`, 행마다 이벤트 로그 재파싱)를 다시 검증한다. 입장·시작 전 확인도 행마다 M18 입장 검사(수용체 바이트 gemmi 파싱 포함)를 한다. 51행 일괄이 여러 개인 run에서는 목록·폴링이 눈에 띄게 느려질 수 있다(정확성 문제는 아님, `docs/tracking/findings.md`).

### Stop 훅 그룹과 M11 handshake 수 테스트 (M19)
- 일괄 작업 모듈 테스트가 실제 qvina를 돌려 나머지 그룹이 480초 제한을 넘었다. 일괄 테스트 일곱 파일을 별도 그룹으로 나눴다(`b8fafd5`). 지금 pytest 그룹은 다섯이고(`test_chemical_interactions.py`, `test_m11_job_api.py`, M18 도킹 다섯 파일, M19 일괄 일곱 파일, 나머지), 그룹을 더하면 `scripts/test_codex_hooks.py`의 그룹 수·목록 기대도 함께 고친다. 실행기는 `ThreadPoolExecutor(max_workers=4)`라 다섯 그룹 중 넷만 동시에 돌고 다섯째는 먼저 끝난 그룹을 기다린다(`docs/tracking/findings.md`).
- `/capabilities`가 M17·M18·M19 작업 모듈 handshake까지 실행하므로, `test_m11_job_api.py`의 handshake 캐시 테스트를 그룹 단독으로 돌리면 다른 작업 모듈 실행도 셌다. 테스트가 화학 작업 모듈 argv만 세도록 좁혔다(`b2c6436`). capability에 handshake를 더하는 단계는 subprocess 수를 세는 기존 테스트를 확인한다.

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

### 참조 세트 고정과 사전 검사 훅 (M15)
`map_residue_numbering`은 레지스트리 사전 검사 훅을 쓴다. `Run._validated_bound`가 모든 호출 경로(첫 호출, 인자 수정, 선행 조건 뒤 재시도, transient 재시도)에서 일반 인자 검사보다 먼저 훅을 부른다. 훅은 `active.json`을 한 번 읽어 세트를 고정하고(없거나 손상이면 `precondition`), 스냅샷과 구조를 읽어 입력 전체를 검증한 뒤 체인별 계획을 담은 `bound`를 돌려준다. 호출 키에는 `bound.key_fields`(세트 해시)가 들어가고, 구현은 `ToolContext.bound`로 같은 세트와 계획을 받는다. 같은 호출을 다시 검증할 때는 이전 `bound`를 넘겨 세트가 바뀌지 않게 한다. 훅이 없는 도구는 `bound=None`이라 기존 호출 키·이벤트가 바이트 그대로다. 파일 해시 확인은 세트 폴더·세트 해시·파일 stat이 같으면 서버 프로세스 안 캐시로 건너뛴다(폴더마다 최신 항목 하나). 내용 해석 색인(UniProt·KLIFS·SIFTS)은 세트 해시별로 최대 2개를 캐시한다.

### 리간드 작업 경로 (M17)
`POST /jobs`의 `rdkit_inspect_v1`·`rdkit_enumerate_v1`은 `ligand_bundle.submission`이 RDKit 없이 입장을 검사한다(같은 run 가져오기 handle과 종류, 생성은 저장된 점검 객체의 결합 목록으로 부위 검사·`valid` 규칙 확인). 통과하면 capability handshake로 얻은 고정 pin(RDKit 버전, 작업 모듈·상수·잠금 파일 SHA-256)을 호출 키와 작업 기록에 넣는다. 시작 때 pin이 바뀌었으면 `precondition`으로 막는다. 스테이징은 불변 가져오기 객체에서 바이트를 다시 읽어 SHA-256을 대조하고, guardian이 고정 진입점 `mw/jobs/ligand_worker.py`를 `.deps/prolif/venv-locked` 인터프리터로 띄운다. 작업 모듈의 출력은 게시 전에 현재 시도·취소 상태를 확인하고(`_publish_ligand`), 스테이징한 선택과 닫힌 집합으로 다시 검증한 뒤에만 객체로 저장한다. 객체 내용에는 시각·작업·시도 ID가 없어 같은 입력은 같은 handle이다. 읽기는 매번 완료된 게시 한 건과 입력에 대조한다. capability는 성공한 handshake만 서버 프로세스 안에 캐시하며 키는 인터프리터·작업 모듈·상수·잠금 파일 정보다(ProLIF와 같이, 환경을 제자리에서 바꾸면 백엔드를 다시 시작한다).

### 도킹 작업 경로 (M18)
`POST /jobs`의 `qvina_dock_v1`은 `docking_bundle.submission`이 RDKit·Meeko 없이 입장을 검사한다(작업 인자 모양·범위는 `docking_inputs.validate_arguments`, 같은 run 가져오기 handle과 종류, M17 후보 집합 검증 읽기와 후보 id·부모 해시, 수용체 가져오기 바이트의 M11 규칙 검사와 인스턴스 일치를 gemmi로). 통과하면 capability로 얻은 고정 pin(`qvina2` 해시·패키지, Meeko·RDKit·MDAnalysis·gemmi 버전, 작업 모듈·상수·두 잠금 파일 SHA-256)을 호출 키와 작업 기록에 넣고, 시작 때 pin이 바뀌었으면 `precondition`으로 막는다. capability는 `qvina2` 파일 해시를 설치 기록·고정값과 비교하고 작업 모듈 `--handshake`만 실행한다(qvina는 실행하지 않음). 구조가 맞는 handshake만 서버 프로세스 안에 캐시하며 키는 인터프리터·`qvina2` 파일 정보와 qvina 설치 기록·작업 환경 잠금 파일·작업 모듈·상수의 SHA-256이다(환경을 제자리에서 바꾸면 백엔드를 다시 시작한다). guardian은 고정 진입점 `mw/jobs/docking_worker.py`를 `.deps/docking/venv-locked` 인터프리터로 띄우고, 작업 모듈이 `qvina2`를 같은 프로세스 그룹의 자식으로 실행하므로 정리·빈 그룹 확인이 엔진까지 덮는다. 게시(`_publish_docking`)는 현재 시도·취소를 확인하고, 스테이징한 선택·닫힌 집합으로 출력을 검증하고, 접촉마다 수용체 원자 식별자와 거리를 수용체 가져오기 바이트로 다시 대조한 뒤에만 객체를 저장한다. 서버는 작업 시작 요청을 작업이 끝날 때까지 붙잡으므로, 화면은 제출 응답의 job id로 폴링·취소한다.

### 일괄 도킹 작업 경로 (M19)
`POST /jobs`의 `qvina_batch_dock_v1`은 `docking_batch_inputs.submission`이 입장을 검사한다: 공유 필드는 M18 `docking_inputs.validate_arguments`로, 후보 집합은 M17 검증 읽기로, 행마다 `docking_bundle.submission`(M18 입장 그대로)을 불러 행별 `docking_selection@1`을 만들고 일괄 선택 기록 `docking_batch_selection@1`(행 선택 기록 목록 + `batch_input_sha256`)로 묶는다. 호출 키는 `batch_input_sha256`이며 같은 키의 진행 중 작업이나 검증된 `complete` 요약의 작업만 돌려준다. 새 작업이면 그 자리에서 재사용 계획으로 N을 세고 예산 부족을 429로 거절한다. 작업 기록에는 `method`(행의 M18 pin)와 `batch_method`(일괄 작업 모듈·상수 해시)를 넣고, 시작 때 둘 다 다시 맞춘다. 시작 때 run 실행 잠금 안에서 재사용 계획을 한 번 정하고(`job_dispatch_intent.batch_reused`) `reserve_attempt(units=N)`으로 예약한다. N = 0이면 작업 프로세스 없이 정리 확인 이벤트를 쓰고 요약만 게시한다. 스테이징은 첫 행의 M18 스테이징(수용체·부모 SDF 바이트를 불변 가져오기에서 다시 읽고 해시 대조)에 행 목록(재사용 표시, 후보 SMILES·코어·입체 표시)을 더한 `docking_batch_worker_input@1`이다. guardian은 고정 진입점 `mw/jobs/docking_batch_worker.py`를 `.deps/docking/venv-locked`로 띄우고(감시 대상, 종료 기록 한도 64 KiB), 작업 모듈은 `docking_worker.py`를 파일 경로로 불러 수용체를 한 번 준비한 뒤 행을 차례로 `dock_row`로 계산한다. 행당 300초·전체 7200초 시계와 SIGTERM은 `BaseException`인 `_Stop`을 던져 M18의 `except Exception`이 삼키지 않게 하고, `subprocess.run`이 그 행의 `qvina2`를 정리한다(진행 중인 RDKit·Meeko 네이티브 호출은 끝난 뒤에 멈춘다). 서버는 그룹 정리 확인 뒤 `_finish_batch`에서 종료 원인(사용자 취소·작업 마감·크래시·서버 재시작)을 정하고 `finish`가 스테이징을 크기 제한·`O_NOFOLLOW`·canonical JSON으로 읽어 행을 M18과 같은 검사(`result_content` → `store_result`, 수용체 원자 재대조)로 게시한 뒤 요약을 만들고 검증해 게시한다. 그 다음 작업 종료를 기록한다(`done`이면 요약 handle 하나). 서버 재시작 때는 `reconcile_run`이 그룹 정리를 확인한 뒤 같은 `_finish_batch(recovered=True)`로 게시하고 `interrupted`로 닫는다. capability는 M18 capability + 일괄 파일 해시 + 일괄 작업 모듈 `--handshake`(구조가 맞는 것만, 파일 해시 키로 캐시)다.

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
8. 참조 데이터를 읽는 도구(M15 번호 대응 등)는 호출 시작 때 참조 세트를 고정하고, 그 세트 해시를 호출 키에 넣고(사전 검사 훅의 `key_fields`), 결과 객체에 세트 해시와 계산에 쓴 참조 행을 담아 참조 폴더 없이 다시 열리게 한다. 참조 값과 계산 값은 보고서에서 다른 증거 종류로 둔다.
9. 외부 실행 파일 엔진(fpocket 등)은 해시 잠금 설치 스크립트, 실행 파일 해시 확인, 요청으로 바꿀 수 없는 경로, 허용 목록 환경변수, 알려진 출력 파일만 읽는 파서를 함께 만든다.
10. 기존 결과를 여러 개 묶는 작업(M19 일괄 등)은 행 계산을 복제하지 않고 기존 작업 모듈 함수를 불러 쓰며, 행 결과가 단독 실행과 같은 handle인지 실제 엔진으로 바이트 비교한다. 900초보다 긴 작업 시간 한도가 필요하면 `JobQueue.submit`과 API `JobSubmit.timeout_s` 두 곳을 그 프로토콜에만 넓힌다. 작업 하나가 결과 여러 개를 내면 게시 증거 이벤트·재사용 색인·`producer()`·보고서 입력 검사가 그 결과를 받아들이는지, 시도 1회·예약 단위·환불 없음이 재생과 맞는지 확인한다. 검증: 실제 엔진 테스트, events-only 복구, 기존 프로토콜 테스트 전부.

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
