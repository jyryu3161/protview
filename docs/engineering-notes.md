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
- **대응**: 두 곳 모두 이 프로토콜만 7800을 허용한다(API는 `le=7800`, 큐가 다른 프로토콜을 각자 상한으로 거절. M22부터 API `le`는 GA 때문에 15000, 아래 M22 항목). 긴 작업을 새로 만들면 두 곳과 마감 계산(min(남은 활동 시간, `timeout_s`))을 함께 본다. guardian의 `MAX_GO_WAIT_S` 3600은 GO 대기 상한일 뿐이고 실행 시간 상한이 아니다. psutil 신원 기록에는 나이·만료 개념이 없다.

### 증액 직후 런타임 오버헤드 과금으로 다시 부족해진다 (M19)
- **증상**: 활동 시간 부족분만큼 정확히 올리면, 증액 요청 자체의 `_mutation`이 끝날 때 `runtime_overhead`를 몇 ms 청구해 잔여가 필요량보다 작아지고 일괄 제출이 다시 `batch_limit_raise_required`가 된다.
- **대응**: 활동 시간 증가분에 `RAISE_MARGIN_S` 60초를 더한다(조정 가능, 결정 0027). 증액 판단·계획·응답은 모두 `Run.raise_limits`가 실행 잠금 안에서 쓰는 `run.budget.snapshot()`(과금된 사용량)으로 한다. 활동 중 경과를 더한 `budget_snapshot()`으로 판단하면 승인 응답과 실제 증액이 어긋난다(T11 검토 수정 `4aa9fc2`). 시작 전 확인은 `budget_snapshot()`을 보여 주므로 두 값이 활동 중에는 조금 다를 수 있다.
- 사용량이 이미 한도를 60초 넘게 넘은 run은 한 번의 증액으로 부족분이 0이 되지 않는다(증가분이 필요량 + 60초로 묶임). 다시 명시적으로 승인한다.

### `Run.update_limits`에는 HTTP 경로가 없다 (M19)
- `update_limits`는 테스트에서만 불린다. 사람의 증액은 형제 함수 `Run.raise_limits(plan, by="human")`(실행 잠금 안에서 스냅숏으로 증가분을 계획, 증가분이 모두 0이면 이벤트 없음, `budget_limit_updated`에 `context` 추가)이고, 이것을 부르는 곳은 `docking_batch_jobs.limit_approval`, M22부터 `ligand_ga_jobs.limit_approval`, M23부터 `sequence_ga_jobs.limit_approval` 셋이고(서로 부르지 않음), 각자 자기 HTTP 라우트 하나(`POST /runs/{id}/docking/batches/limit_approval`, `POST /runs/{id}/ligand/ga/limit_approval`, `POST /runs/{id}/sequence_ga/limit_approval`)에서만 불린다(`test_docking_batch_budget.py`·`test_ligand_ga_budget.py`·`test_sequence_ga_budget.py`가 AST로 확인). 다른 경로(도구·흐름·뷰어)에서 한도를 올리는 코드를 더하면 이 테스트가 실패해야 한다. `budget_limit_updated`의 재생(`_refresh`)은 `limits`만 읽으므로 맥락 필드를 더해도 events-only 복구가 같다.

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
- 일괄 작업 모듈 테스트가 실제 qvina를 돌려 나머지 그룹이 480초 제한을 넘었다. 일괄 테스트 일곱 파일을 별도 그룹으로 나눴다(`b8fafd5`, 그때 다섯 그룹). M23 뒤 그룹을 열넷으로 다시 나눴고 M25에서 열여섯이 되었다(아래 "Stop 훅 그룹 시간과 그룹 나눔", "무거운 루프 테스트가 나머지 그룹을 480초 넘게 했다"). 지금 그룹 목록은 `.codex/hooks/stop.py`의 `PYTEST_GROUPS`(M29 뒤 열아홉, 아래 M29 함정)이고, 마지막 나머지 그룹은 `backend/tests`에서 거기 적힌 파일을 `--ignore`로 뺀 것(목록은 자동으로 만듦)과 실행기 테스트 `SCRIPT_TESTS`다. `scripts/test_codex_hooks.py`는 `--collect-only` 없이 모든 `backend/tests/test_*.py`·`scripts/test_*.py`가 정확히 한 그룹에 들어 있는지, 테스트 단위로 나눈 파일은 모듈 수준 테스트 이름이 정확히 한 번씩 적혔는지 검사한다. 그래서 새 실행기 테스트 파일을 `SCRIPT_TESTS`에 넣지 않거나 나눈 파일에 테스트를 더하고 적지 않으면 이 테스트가 실패한다. 그룹 수를 바꾸면 같은 파일의 그룹 수 기대도 고친다. 실행기 스레드 수는 그룹 수(`len(CHECKS) - 1`)와 같아 모든 그룹이 동시에 돈다(M19 마무리 때 `max_workers=4`를 고침, `8a327c8`).
- `/capabilities`가 M17·M18·M19 작업 모듈 handshake까지 실행하므로, `test_m11_job_api.py`의 handshake 캐시 테스트를 그룹 단독으로 돌리면 다른 작업 모듈 실행도 셌다. 테스트가 화학 작업 모듈 argv만 세도록 좁혔다(`b2c6436`). capability에 handshake를 더하는 단계는 subprocess 수를 세는 기존 테스트를 확인한다.

### 사전 검사 훅의 store로도 게시 확인 읽기를 할 수 있다 (M20)
- **증상**: 명세 초안은 "사전 검사 훅에는 run·이벤트가 없으니 `validated_pocket_set` 대신 내용만 검사한다"고 했다. 내용만 보면 취소·오래된 시도가 store에 남긴 미게시 `pocket_set`(`pocket_bundle.publish`의 `store.put` 뒤 `job_terminal` 전)이나 원본 출력과 어긋난 객체도 통과한다.
- **원인**: 훅은 `precheck(self.store, args, bound)`로 store를 받는데, `ObjectStore`는 `events`와 `run_id`를 가진다(`runtime/orchestrator.py`, `core/handles.py`).
- **대응**: `type("RunView", (), {"store": store, "events": store.events, "run_id": store.run_id})()`로 만든 보기를 게시 확인 읽기에 넘긴다(`tools/comparison.py`가 선례, M20 `tools/mutations._pocket_set`). 다른 도구가 저장된 작업 결과를 입력으로 받을 때도 내용 검사가 아니라 그 결과의 검증 읽기를 쓴다(착수 확인 M1, 결정 0028).

### fpocket 결과는 실행마다 다를 수 있다 (M20)
- 포켓 결과의 `method.fresh_execution_deterministic`은 false다(fpocket 시계 seed). 같은 구조로 다시 검출하면 포켓 수·순번·안쪽 잔기가 바뀔 수 있다. 포켓 출처 테스트·QA는 그 실행에서 저장된 `pocket_set`을 읽어 기대값을 만들고 고정 숫자를 쓰지 않는다. `lining_residues`의 순서도 파일 순서가 아니므로(1HSG 포켓 1: PRO A81 다음 ARG A8) 위치 순서는 구조 파일 순서로 다시 정한다.

### "리간드"는 물·금속이 아닌 모든 HETATM 잔기다 (M20)
- `structure_residues`의 `ligands`(그리고 `_selected_ligand`)는 `het_flag == "H"`, 물 아님, `METALS` 아님인 잔기 전부다. HETATM으로 적힌 MSE·CD·PO4 등도 리간드 후보가 되어 "리간드가 여럿"이 흔하다(1MQ4: ADP·PO4, 합성 mmCIF: 4개). 같은 MSE도 ATOM이면 폴리머(위치가 되고 `non_standard_residue`로 제외), HETATM이면 리간드다. 그래서 리간드는 7필드 선택자로만 받고 화면도 자동으로 고르지 않는다. 금속 판정은 이름(`METALS`)이며 CD·FE2 같은 이름은 금속이 아니다.

### 수소는 전처리에서 `hydrogens: keep`일 때만 남는다 (M20)
- 전처리 기본은 수소 제거이고 공개 1MQ4·1HSG에는 수소가 없다. 수소만 있는 잔기·리간드(중원자 거리 null, `ligand_invalid`) 경로는 오프스크린 흐름에서 닿지 않으며 `hydrogens: keep`으로 전처리한 합성 입력의 백엔드 테스트로만 확인한다. 거리 계산은 원소 H·D를 늘 빼므로 수소를 남겨도 값은 같다(착수 확인).

### 저장은 되었는데 읽을 수 없는 결과를 만들면 안 된다 (M20)
- **증상**: 독립 코드 검토에서, 리간드를 준 요청의 수소만 남은 위치는 구현이 거리 null을 만들지만 `validated_set`은 숫자만 받아, 객체는 저장되고 읽기·보고서는 검증 실패(422)로 읽을 수 없는 결과가 생길 수 있었다(막는 지적).
- **원인**: 결과를 만드는 코드와 결과를 검증하는 코드가 따로 있고, 저장 전에 검증하지 않았다.
- **대응**: 검증 규칙을 고치고(거리 null 허용, 0이 아님), 구현이 `ObjectStore.put` 전에 `validated_set`을 돌려 통과하지 못하면 저장하지 않고 `candidate_set_invalid`로 실패한다(`ea2913c`). 불변 객체는 고칠 수 없으므로, 읽을 때 검증하는 새 결과 종류는 저장 전에 같은 검증을 한다.

### 보고서 금지어 검사는 식별자가 아니라 템플릿 문장에 한다 (M20)
- **증상**: 렌더된 Markdown 전체에 금지어 정규식을 돌리면 체인 이름 `BEST`, 리간드·CCD 코드, handle 같은 식별자가 우연히 금지어와 맞아 정상 보고서가 거부될 수 있다.
- **대응**: `render_mutation_report`는 값·식별자를 자리(`\x00n\x00`)로 둔 고정 템플릿에 금지어 검사를 한 뒤 자리를 채운다(`test_identifiers_containing_forbidden_words_do_not_fail_a_report`). 고정 한계 문장 5줄은 문자 그대로 같을 때만 건너뛴다. M20 보고서는 필수 문장 때문에 "촉매"를 금지어에 넣지 않았다(M16 보고서는 금지).

### 경로에 handle을 넣는 라우트는 하위 경로를 먼저 등록한다 (M20)
- handle(`obj://<run>/<kind>/<sha>`)은 슬래시를 담으므로 `/mutation_candidate_sets/{handle:path}`로 받는다. Starlette는 등록 순서대로 맞추므로 상세 라우트를 먼저 두면 `…/{handle}/positions`도 상세가 handle `…/positions`로 삼킨다(없는 handle로 거절됨). `/positions`·`/candidates`를 상세보다 먼저 등록했다(`app.py` M20 읽기 구역 주석). 프런트 `api.ts`는 handle을 `encodeURIComponent`로 붙이지만 서버가 경로를 디코드한 뒤 맞추므로 등록 순서가 여전히 필요하다. M18·M19 읽기는 `?handle=`를 쓰므로 둘의 방식이 다르다.

### 탭 흐름의 단백질 공학 탭은 이제 GET 요청을 낸다 (M20)
- M14 `tabs-flow.cjs`의 단백질 공학 탭 사례는 "안내가 보이는 동안 새 요청 없음"을 단언했다. M20부터 그 탭은 변이 후보 화면이 들어올 때 이벤트·포켓·번호 대응·주석·결과 목록을 GET으로 읽으므로, 리간드 탭 선례처럼 "GET 읽기만"으로 바꿨다(`f33aacd`, M14 실행기의 `T-unavailable` 설명도). 탭에 화면을 붙이는 단계는 이 단언과 `workspace-tabs.test.cjs`의 안내 기대를 함께 고친다.

### PDBFixer 생성자는 파일만 받는다 — 위상을 텍스트로 넘기고 좌표를 이식한다 (M21)
- **증상**: M7 작업 모듈이 만든 OpenMM `Topology`를 PDBFixer에 바로 넘기는 공개 경로가 없다. PDBFixer는 좌표를 nm로 옮겨 담아 돌려주므로 변이 잔기 밖 좌표가 값은 같아도 마지막 비트가 다르다(1UBQ 594원자 중 약 410개, 최대 7.1e-15 Å).
- **대응**: M7과 같은 위상(체인 id `str(chain_index)`, 잔기 id `str(전역 순번+1)`)을 `app.PDBxFile.writeFile(…, keepIds=True)`로 쓰고 `PDBFixer(pdbxfile=StringIO)` → `findMissingResidues` → `applyMutations([f"{old}-{순번}-{NEW}"], chain_id)` → `findMissingAtoms`(여기서 누락 표시가 변이 잔기 하나뿐인지 검사, `addMissingAtoms` 전) → `addMissingAtoms(seed)`. 출력은 이식(`_graft`)한다: 변이 잔기 밖은 이름·원소·순서가 같고 차이 ≤ 1e-9 Å일 때만 받아 입력 좌표를 쓰고, 입력에 있던 원자는 변이 잔기 안에서도 입력 좌표, 새 원자만 PDBFixer 좌표다. 그래야 "변이 잔기 밖 좌표는 최소화 전에 입력과 같다"가 비트 단위로 성립한다(`test_oracle1_*`).

### `applyMutations`는 새 템플릿에 같은 이름이 있는 원래 곁사슬 원자를 남긴다 (M21)
- ILE→TRP·PHE·TYR의 CD1, ILE→THR의 CG2, ILE→VAL의 CG1·CG2, MET→PRO·TRP의 CG, HIS→TYR의 CG·CD2·CE1, LYS→HIS의 CG처럼 화학적으로 다른 자리인데도 이름이 같아 남는다. 명세는 PDBFixer 공개 API를 그대로 쓰는 쪽(변형 A)을 골랐다. 그래서 최소화 전 전위가 매우 클 수 있다(T1: P38W는 변형 A 209,742,676 kJ/mol, 같은 이름 원자를 남기지 않는 변형 B 58,015 kJ/mol. 반대로 I44W는 A −8,046, B 30,744 kJ/mol). 최소화 뒤 `after ≤ before` 검사만 하고 값의 좋고 나쁨을 판정하지 않는다. `added_heavy_atoms`에는 PDBFixer가 새로 놓은 원자만 들어가므로 남은 원자는 거기 없다.

### C 말단 변이에서 PDBFixer가 OXT를 지웠다 다시 놓는다 (M21)
- 표준 템플릿에 OXT가 없어 `applyMutations`가 말단 잔기의 OXT를 지우고 `findMissingAtoms`가 `missingTerminals`로 다시 놓는다. 새 위치는 원래와 0.35–0.69 Å 다르다(G76A·G76P·G76W). 이식에서 OXT는 입력에 있던 원자이므로 입력 좌표를 쓴다. `missingTerminals`는 C 말단 변이에서만, 그것도 변이 잔기에만 나타나야 한다.

### 자유 Cys의 변형 이름은 null이다 (M21)
- `Modeller.addHydrogens`가 돌려주는 변형 목록은 HIS면 HID·HIE·HIP, 이황화 CYS면 CYX이고, 자유 CYS는 기본 템플릿이라 None이다. 결과 `protonation_variants`는 이 값을 그대로 저장한다(자유 Cys `variant: null`, "CYS"로 바꾸지 않음). 이황화가 끊기거나 생기면 상대 Cys가 CYX↔null로 바뀌어 `protonation_differences`와 L5가 생긴다(변이 잔기가 아니므로 명세대로의 동작, 착수 확인 N1).

### OpenMM mmCIF 읽기는 결합표가 없으면 이황화를 찾지 않는다 (M21)
- 저장 mmCIF에는 `struct_conn`이 없다. 독립 oracle이 내보낸 mmCIF를 `app.PDBxFile`로 다시 읽으면 표준 결합만 생기고 이황화 결합이 빠져 System이 달라진다. 독립 재계산은 `createDisulfideBonds(positions)`를 직접 부르거나 저장 `final_bonds`로 위상을 만든다(`test_mutation_model_worker.py`의 `_independent_system`). M18 수용체도 거리 추론이 아니라 `final_bonds`·`atom_mapping`으로 결합을 받는다.

### M18 화학 추론이 OpenMM 구조의 C 말단 카르복실을 거부했다 (M21)
- **증상**: 착수 확인에서 M7을 통과한 1UBQ·합성 파생 구조의 수용체 5개가 모두 M18 `receptor_prep_failed`(`receptor_graph_invalid`, "backbone inferred bond order invalid", GLY A76)였다. qvina는 한 번도 돌지 않았다.
- **원인**: M7 규칙상 사슬 끝마다 OXT가 있고, MDAnalysis 추론은 원자 순서가 C, O, OXT이면 이중결합을 C–OXT에, 음전하를 O에 붙인다. M18 `_protein_chemistry`는 모든 잔기에 C=O 이중결합을 요구한다. 기존 M18 입력은 말단 캡이 있는 예제라 드러나지 않았다. 원자 순서만 바꾸면(OXT를 O 앞에) 통과한다.
- **대응(사용자 승인)**: `receptor_source`가 `mutation_model`일 때만 `terminal_carboxylate_either`로 OXT 잔기의 C–O·C–OXT 중 하나가 이중결합이고 다른 쪽이 단일결합·전하 −1이면 받는다. 원자 순서에 기대는 길(OXT를 앞에 쓰기)은 쓰지 않았다. 수소가 있는 자유 C 말단을 **가져온** 수용체는 지금도 거부된다(`test_imported_free_c_terminus_receptor_is_still_refused`, 기존 M18 동작). HID·CYX 같은 변형 이름으로 쓴 수용체는 거부되므로(CYX는 비표준) 저장 mmCIF는 표준 이름 HIS·CYS로 쓴다.

### 사용할 수 없음 412는 순수 입장 422 뒤, M7 사전 검사 422 앞이다 (M21)
- 명세 표는 412 세 줄을 끝에 두지만 실제 순서는 순수 입장 검사 1–7(422) → dry-run 계획 → 412(`process_identity_unavailable` → `openmm_unavailable` → `pdbfixer_unavailable`) → M7 사전 검사(422 `openmm_preflight_failed`)다(독립 코드 검토 N2). 엔진이 없어도 잘못된 후보는 422로, 엔진이 없고 입력이 맞으면 412로 거절된다. 사전 검사가 OpenMM을 쓰므로 엔진 확인이 그 앞에 와야 한다. 둘 다 예약·과금 전이다.
- `JobSubmit`의 `timeout_s`가 빠지면 예전에는 API가 모든 프로토콜에 60초를 넣었다. M21부터 빠진 값은 큐로 None이 가고 큐가 프로토콜 기본값(이 프로토콜 120, 나머지 60)을 채운다. API 본문 모델이 이 프로토콜의 `timeout_s`·`args`를 거절하면 닫힌 이유 `argument_invalid`로 바꾼다(독립 코드 검토 N1).

### 변이 모델을 출처로 한 읽기는 모델을 매번 다시 검증한다 (M21)
- `mutation_model_bundle.validated_result`는 저장 객체 전체를 `validated_model`로 다시 검사하고(저장 좌표에서 접촉을 다시 계산) 단일 게시·후보 집합·mmCIF 바이트를 대조한다. 이 출처의 M18 결과는 입장·스테이징·게시·모든 읽기에서 모델을 다시 검증하고 저장 mmCIF·사이드카 해시를 대조하며, `docking_pairs`는 모델과 짝마다 두 M18 결과를 다시 검증한다(독립 코드 검토 N6). 정확성을 위한 설계이고, 1UBQ 크기에서는 문제가 없었지만 큰 단백질·짝이 많은 run에서는 읽기가 느려진다(이벤트 로그 재파싱 항목과 같은 원인). 모델이 검증되지 않으면 그 모델을 출처로 한 M18 결과도 읽히지 않는다.

### 호출 키의 의존 파일 해시와 그 밖의 파일 (M21)
- 호출 키·작업 기록 `method`에 들어가는 것은 작업 모듈 `openmm_mutation_worker.py`와 `DEPENDENCIES` 다섯 개(`mutation_model_math.py`, `mutation_model_constants.py`, `jobs/openmm_worker.py`, `tools/openmm_method.py`, `mutation_candidates.py`)의 SHA-256과 고정 방법 기록이다(독립 코드 검토 R1, `4a3dabe`). 이 중 하나라도 바꾸면 그 전 결과가 자동 재사용되지 않고, 대기 중 작업은 시작 때 `worker_version_invalid`로 막힌다(`test_changed_dependency_changes_the_key_and_refuses_the_pinned_start`).
- 작업 모듈이 import하지만 해시하지 않는 파일: `mutation_constants.py`(M20 상수), `openmm_bundle.py`, `core/handles.py`, `core/errors.py`, `tools/structural.py`, `tools/sasa.py`, `jobs/process_identity.py`. 이 파일의 동작을 바꾸면 같은 호출 키로 다른 결과가 나올 수 있으므로, 바꿀 때 `DEPENDENCIES`에 넣을지 함께 정한다.
- M18 쪽도 같다: M21이 `docking_worker.py`·`docking_constants.py`를 바꿔 M21 전 M18·M19 결과의 자동 재사용이 끝났다(결정 0029, 저장 결과·읽기는 그대로).

### 1UBQ 작업 하나는 약 20초, 큰 구조의 시간은 재지 않았다 (M21)
- 착수 확인 단독 측정에서 1UBQ(중원자 602) 작업 하나(두 구조의 수소·System·최소화, PDBFixer, SASA·접촉·mmCIF)는 22.6–23.0초였다(구조 하나 약 11초). 사전 검사·스테이징·guardian 시간은 빠졌다. `NoCutoff` GBn2라 원자 수에 비례 이상으로 늘 수 있고, M7을 통과하는 큰 공개 fixture가 없어 큰 구조는 재지 못했다. 기본 120초·최대 240초에서 시간 초과가 나면 결과 없이 1단위가 청구된다.

### M7을 통과해도 M18이 받지 않는 크기 구간이 있다 (M21)
- M7 한도는 단백질 중원자 6,000개이고 M18 수용체 한도는 수소 포함 10,000원자다. 1UBQ의 수소/중원자 비율 1.045로 보면 중원자 약 4,890개를 넘는 모델은 모델링은 되지만 같은 조건 도킹이 입장에서 `receptor_invalid`로 거절된다(`test_receptor_atom_limit_is_a_clear_admission_refusal`). 한도는 바꾸지 않았다.

### M20 회귀의 참조 세트 해시가 M20 기록과 다르다 (M21)
- M21 수락의 M20 회귀가 가져온 세트(`8c608e2b…`)는 M20 기록(`99939292…`)과 해시가 다르지만 매니페스트의 파일 다섯 개 SHA-256은 같다. 위 "같은 스냅샷 파일을 다시 가져와도 세트 해시가 바뀐다"와 같은 원인(`imported_at`)이며 회귀 판정에는 영향이 없다.

### GA `finish`는 개체를 먼저 모두 게시한 뒤에 실행의 끝을 판단한다 (M22)
- **증상**: 첫 구현은 세대 기록 하나가 읽히지 않거나 종료 기록이 세대 기록과 맞지 않으면 예외로 요약 만들기를 멈춰, 이미 끝난 새 도킹 결과도 게시되지 않았다(M19와 다름).
- **대응**(독립 코드 검토 수정 `a71b2e6`): `ligand_ga_jobs.finish`가 읽을 수 있는 세대 기록(처음 읽히지 않는 기록 앞까지, 풀 후보·쓰지 않은 `eval_index`·시작 때 재사용 계획과 같은 평가인 기록만)의 새 도킹 개체를 M18 검사로 모두 게시한 다음에 종료 이유를 정한다. 틈·이상한 파일·읽히지 않는 기록·종료 기록 불일치는 예외가 아니라 `worker_failed`다. 요약 자체를 만들 수 없을 때만 예외(작업 `failed` "invalid scientific output")이고, 그때도 게시한 개체는 자기 게시 증거로 읽히고 재사용된다.
- **검증**: `pytest backend/tests/test_ligand_ga_jobs.py -k "unreadable_generation_record" -q`.

### 새 도킹은 `max_new_dockings`가 아니라 `reserved_units`까지다 (M22)
- **증상**: 첫 명세·oracle은 `max_new_dockings`에서 `docking_limit`을 냈다. 그런데 예약은 `reserved_units = min(max_new_dockings, P + (G − 1)(P − E))`이라, 점수 있는 개체가 `elite_count`보다 적어 새 자리가 늘면 예약하지 않은 단위를 쓰게 된다.
- **대응**(T2 수정 `613a707`, 명세 3·6절 수정): 작업 모듈이 다음 개체가 새 도킹을 필요로 할 때 새 도킹 수가 `reserved_units`에 닿았으면 그 자리에서 `docking_limit`으로 멈춘다. 요약 검증은 `new_dockings_used ≤ reserved_units`와 `docking_limit`이면 `new_dockings_used = reserved_units`를 요구한다. 작업 모듈은 `reserved_units` 식을 자기 사본으로 계산한다(서버 `ligand_ga_inputs.reserved_units`와 같아야 함, `test_ligand_ga_worker.py`가 대조).

### 도킹이 끝난 뒤의 늦은 신호가 결과를 잃게 하지 않는다 (M22)
- **증상**: M19 일괄은 `dock_row`가 끝난 직후 개인 작업 폴더를 지우는 동안 늦은 타이머·SIGTERM이 오면 끝난 행을 잃거나 `qvina_work`를 남길 수 있었다(`docs/tracking/findings.md` M19 항목).
- **대응**(`a71b2e6`): GA 작업 모듈의 `_dock`은 `dock_row`가 돌아오자마자 `_quiet()`(SIGALRM·SIGTERM 막기, 타이머 해제, 중단 구간 종료)를 부른 뒤에 폴더를 지운다. 막힌 신호는 다음 개체 시작 전 확인에서 `cancelled`·시계로 처리된다. 시작할 때 남아 있던 `qvina_work`는 먼저 지운다. M19 작업 모듈은 바꾸지 않았다.
- **검증**: `test_ligand_ga_worker.py::test_a_finished_docking_survives_a_late_sigterm_and_a_stale_private_directory`.

### 15000초 작업 한도는 세 곳에 반영해야 한다 (M22)
- M19 "숨은 900초 상한" 함정과 같다. API `JobSubmit.timeout_s`의 `le`(7800 → 15000), `JobQueue.submit`의 프로토콜별 `bound` 연쇄(`GA_TIMEOUT_MAX_S`, 이 프로토콜은 기본값 없이 인자 검사에서 `[total_s + 600, 15000]`), 그리고 M19 `BATCH_PROTOCOL` 분기를 본뜬 GA 분기(`SUMMARY_PROTOCOLS`: 시도 1회·재시도 거절·정리 뒤 `_finish_batch` 게시·복구, 예약 단위, 스테이징 한도, adapter 이름)다. guardian에는 진입점·도킹 인터프리터·감시 대상·종료 기록 한도(64 KiB) 항목을 더했다.
- API `le`를 올린 결과 다른 프로토콜의 7800 < `timeout_s` ≤ 15000 요청은 422 상태는 같고 본문만 요청 모델 오류에서 큐의 "invalid job timeout"으로 바뀌었다(결정 0030, `test_ligand_ga_jobs.py::test_registration_capability_and_protocol_timeout_bound`). 긴 작업을 또 만들면 이 세 곳과 마감 계산(min(남은 활동 시간, `timeout_s`))을 함께 본다.

### `producer()`의 GA 개체 증거 순번은 요약 게시가 있으면 그 순번이다 (M22)
- `docking_bundle._ga_individual_producer`는 예약 < 정리 확인 < `ligand_ga_individual_published`이고 후보가 그 GA의 적격 풀 후보일 때 증거로 인정하며, 비교에 쓰는 `published_seq`는 같은 시도의 요약 게시(`ligand_ga_published`)가 있으면 그 순번, 없으면 개체 게시 순번이다(M19 일괄 행과 같은 규칙). 가장 먼저 게시한 쪽이 이기므로 같은 handle을 M18·M19가 먼저 게시했으면 GA 게시가 기존 대조 기준을 바꾸지 않는다. GA가 이기면 `job`을 그 개체의 다시 만든 M18 보기(`ligand_ga_jobs.individual_view`, 후보 행은 검증된 후보 집합에서 다시 읽음)로 바꿔 돌려준다. GA 이벤트가 없는 run에서는 반환값이 그대로다(착수 확인 (a2)).

### 재사용 크기는 시작 때 다시 본다 (M22)
- 입장의 `ga_reuse_too_large` 검사는 제출 때의 재사용 계획으로 한다. 대기 중에 같은 run에 저장 결과가 늘면 시작 때의 계획이 더 커질 수 있다. 큐는 시작 때 run 실행 잠금 안에서 재사용 계획을 다시 정한 뒤 `reserve_attempt` 전에 128 MiB를 다시 검사한다(`a71b2e6`, 넘으면 422 `ga_reuse_too_large`, 예약·dispatch 없음, `test_ligand_ga_jobs.py::test_admission_refusals_record_and_charge_nothing`).

### 유사도는 문자열로 저장된다 (M22)
- 요약의 `similarity`는 숫자가 아니라 정확 분수를 6자리 `ROUND_HALF_UP`한 문자열(`"0.913043"`, `ligand_ga_bundle.SIMILARITY_RE`)이다. float 반올림 오차 없이 독립 oracle과 바이트로 맞추기 위해서다. 화면의 `lineageText`가 처음에는 숫자만 보여 오프스크린 흐름에서 Tanimoto가 표에 나오지 않았다(T8에서 찾아 고침, `448e912`). 저장 문자열을 그대로 보이고 화면에서 다시 반올림하지 않는다. 이웃 정렬은 저장 문자열이 아니라 전체 정밀도 값이므로, 6자리에서 같아 보이는 두 후보의 순서가 풀 순서와 다를 수 있다.

### 동점은 어디서나 풀 순서다 (M22)
- 이어받음(점수 오름차순), 토너먼트 부모(점수가 가장 낮은 개체), 이웃(Tanimoto 내림차순) 모두 동점이면 후보 집합 저장 순서(`pool` index)가 이긴다. Morgan Tanimoto 동점은 흔하다(착수 확인 (a): 작은 풀 P0 행에 0.842105 셋). 서버 요약 검증도 이어받음을 같은 규칙으로 다시 계산하므로, 동점 규칙을 바꾸면 기존 요약이 검증을 통과하지 못한다.

### GA 요약 읽기는 후보 집합을 한 번만 검증한다 (M22)
- `validated_summary`는 단일 게시·GA 선택 기록·평가한 개체마다 다시 만든 M18 선택·모든 개체 결과(`docking_bundle.validated_result`, 이벤트 로그 재파싱)를 다시 검증한다. 개체 결과 검증이 `producer()` → `individual_view` → `pool_rows`를 다시 불러 후보 집합 검증 읽기가 개체 수만큼 반복되었다. 요약 읽기 하나 동안 `_one_pool_check`(contextvar 메모, 같은 run·후보 집합·GA 기록 값일 때만)로 한 번만 하게 했다(`a71b2e6`). 그래도 개체 결과 검증은 개체마다 하므로 개체 ≤ 101개 요약이 많은 run에서는 목록·폴링이 느려질 수 있다(M19 "일괄 읽기" 항목과 같은 원인).

### GA 진행 개수는 새 도킹 파일만 센다 (M22)
- 진행 `ga.individuals_started`·`individuals_result_files`·`individuals_finished`는 시도 디렉터리 `individuals/`의 파일 수이고 재사용 개체는 파일을 만들지 않는다. 그래서 화면은 "새 도킹 시작·끝"으로 이름 붙이고 재사용은 `reused_planned`(시작 때 계획)로 따로 보인다(`a71b2e6`). 실행 중에는 객체를 게시할 수 없으므로(M19 함정과 같음) 진행에는 점수가 없다.

### 여러 곳 변이를 M21 함수로 이어서 적용하면 둘째 단계가 `coordinates_changed`로 실패한다 (M23)
- **증상**: 1UBQ에서 I44W 다음 K6H처럼 두 곳을 `mutant_projection`으로 차례로 적용하면 둘째 단계에서 `coordinates_changed`(최대 이동 4.29e-05–4.98e-05 Å)가 났다. 인접 위치도 같았다(착수 확인 8조합 모두).
- **원인**: M21 `_pdbfixer`가 PDBx 텍스트로 위상을 넘기는데 `PDBxFile.writeFile`이 좌표를 소수 4자리로 쓴다. 앞 단계에서 PDBFixer가 새로 놓은 원자는 전체 정밀도 좌표라 다음 단계 입력에서 반올림된 값과 어긋나고, `_graft`의 `GRAFT_TOLERANCE_A` 1e-9 Å 검사가 이를 변이 잔기 밖 좌표 변경으로 본다.
- **대응**: 단계 사이에 앞 단계에서 새로 놓은 원자의 좌표만 소수 넷째 자리로 반올림한다(변경 ≤ 5e-5 Å, 입력에 있던 원자 불변, `method.multi_mutation: "sequential_structure_order_round4"`로 기록). M21 모듈은 바꾸지 않는다(허용오차를 키우면 M21 호출 키가 바뀐다). 적용 순서를 바꾸면 모델이 달라지므로(착수 확인에서 최대 6.2e-02 Å) 구조 순서로 고정하고 한계 문장 S6에 적는다.

### 도킹 환경 작업 모듈이 띄우는 모델링 자식은 인터프리터 경로를 풀면 안 된다 (M23)
- **증상**: GA 작업 모듈이 프로젝트 `.venv`의 python으로 모델링 프로그램을 띄울 때 `resolve()`한 경로를 쓰면 `mw`·OpenMM을 찾지 못한다.
- **원인**: `.venv/bin/python`은 기본 인터프리터로 가는 심볼릭 링크이고, 링크를 푼 대상에는 이 프로젝트 가상환경의 site-packages가 없다. `-I`는 링크 경로 기준으로 가상환경을 찾는다.
- **대응**: 서버·작업 모듈 모두 `<프로젝트 루트>/.venv/bin/python`을 작업 모듈 파일 위치에서 계산해 쓰고(guardian `DOCKING_PYTHON`과 같은 방식) 풀지 않는다. 스테이징의 `project_python`은 `sys.executable`이 아니라 이 고정 경로이고 다르면 `fatal`이다.

### 자식 프로세스는 부모의 막힌 SIGTERM을 상속한다 (M23)
- **증상**: GA 작업 모듈이 도킹 직후 신호를 막은 구간에서 모델링 자식을 띄우면 자식이 취소(SIGTERM)에 반응하지 않는다.
- **원인**: 신호 마스크는 `fork` 뒤 `exec`로 이어진다. 자식을 띄우는 시점에 SIGTERM이 막혀 있으면 그대로 물려받는다.
- **대응**: 자식을 띄울 때 신호 마스크를 풀고(실제 확인: 막힌 채로 띄운 자식은 SIGTERM을 받지 못함) 테스트가 자식의 신호 차단 상태를 확인한다.

### 개체 도킹의 수용체 사이드카는 저장되기 전 mmCIF handle을 가리킨다 (M23)
- 모델 mmCIF 객체는 작업이 끝난 뒤에야 저장되지만 handle은 내용 해시(`obj://<run_id>/<kind>/<sha256(kind \0 schema \0 raw)>`, `core/handles.py`)로 정해진다. 모델링 프로그램이 `run_id`와 같은 공식으로 handle을 미리 계산해 사이드카 `source_handle`로 쓰고, 서버가 게시 때 저장된 handle·사이드카 해시와 도킹 결과의 수용체 해시가 같은지 대조한다. 그래서 개체 도킹 결과가 단독 M18 작업 결과와 바이트·호출 키·handle이 같다. 사이드카는 서버와 같은 `docking_inputs` 함수로 만들어야 한다(다른 함수로 만들면 호출 키가 달라진다).

### 한 읽기 안에서 이벤트 로그를 개체마다 다시 읽으면 수십 초가 걸린다 (M23)
- 이벤트 로그 165 MB(이전 GA 개체 200개 규모) run에서 M19·M22식 "개체마다 `validated_result` → 이벤트 로그 재파싱"은 요약 상세 한 번에 28.6–44.3초, 재사용 색인 검증 44.4초였다. M23 읽기는 한 읽기마다 이벤트 스냅숏을 한 번만 만들어 모든 개체·기준 행 검증에 넘긴다(T1 측정: 상세 3.0초·재사용 색인 8.8초, 반환 바이트 동일. 구현 뒤 합성 패딩 로그로 다시 잰 값은 상세 0.84초·재사용 색인 1.10초이고 커밋한 증거는 없다). 시작 전 확인은 입장·재사용 색인·같은 호출 키 확인을 한 호출에서 하므로 로그를 여러 번 읽고(같은 규모에서 4.4초), 작업 목록 폴링(`GET /jobs`의 `progress`)은 요약이 있으면 매번 `validated_summary`를 다시 부른다(M22와 같은 구조).

### 변이 모델 객체는 게시 증거가 생기기 전에도 검증되어야 한다 (M23)
- 개체 도킹 결과의 선택 기록을 만들 때 모델 객체는 아직 `sequence_ga_individual_published` 이벤트가 없다(그 이벤트는 모델·도킹 결과를 모두 게시한 뒤에 쓴다). 서버 `finish`가 게시자로서 증거 없이 저장 바이트·내용으로 검증하는 경로와, 이후 읽기(증거 필요)를 구분한다. M18 수용체 읽기 경로는 기준 모델 비교 없이 `validated_model_alone`을 쓰고(수용체에는 `structure_object`·`structure_sha256`·`atom_mapping`·`final_bonds`·`model_number`만 필요) 요약 읽기가 기준 모델과의 관계(양성자 차이·새 이황화 재계산)를 전체 검증한다. mmCIF 원자 행 대조(`openmm_bundle._cif`)는 `validated_model`이 아니라 게시 때 돈다.

### 첫 비싼 계산 승인 뒤 `claimed` 작업에서 "작업 시작"이 사라진다 (M23 화면, M17·M18·M19·M22 패널은 그대로)
- **증상**: 첫 비싼 계산이면 `/start`가 409 `approval`을 돌려주고 작업은 `claimed` + `blocked_reason: approval_or_cancel`로 남는다. 큐 `start`는 이 상태에서 다시 시작을 받는데, 공유 `dockingJobPhase`는 `claimed`를 "실행 중"으로 보아 2초 폴링이 새 상태를 읽은 뒤 "작업 시작" 단추가 사라진다. 승인된 GA를 화면에서 시작할 수 없었다(M23 하네스 개발 실행에서 발견).
- **대응**: M23 패널은 순수 함수 `gaJobPhase`(`lib/sequence-ga.ts`, 큐 `start`가 `claimed`에서 재시작을 받는 `blocked_reason` 집합 `approval_or_cancel`·`global_concurrency_busy`·`global_job_cleanup_pending`·`global_job_ledger_unavailable`를 테스트가 `queue.py`에서 읽어 대조)로 판단한다. M17·M18·M19·M22 패널은 같은 `dockingJobPhase`를 쓰며 같은 잠재 결함이 있다(해당 하네스는 1–2초 폴링 창 안에 클릭해 통과). 바꾸지 않았고 `docs/tracking/findings.md`에 기록했다.

### 큰 구조에서는 출력 총량 256 MiB가 개체 수보다 먼저 닿을 수 있다 (M23)
- 개체당 작업 출력은 1UBQ에서 약 1.6 MB(65개 ≈ 104 MB)지만 M18 수용체 한도 근처 구조(중원자 약 4,890개, 1UBQ의 약 8배)에서는 개체 하나가 약 11 MB(모델 객체 ≈ 2.4 MB, 그 이벤트 줄 ≈ 3.2 MB, mmCIF·결과 포함)라 65개 ≈ 700 MB가 된다. 작업 모듈은 평가가 끝나면 게시하지 않는 큰 중간 파일(`model_input.json`·`receptor_bonds.json`)을 지우고 새 평가를 시작하기 전에 출력 총량 + 개체당 최대(32 MiB)가 256 MiB를 넘으면 `resource_exceeded`로 멈춘다(조용히 자르지 않고 부분 완료). 이벤트 로그도 개체 65개에 약 39–210 MB 늘 수 있다.

### 서버의 리간드·상자 부분 점검은 작업 모듈보다 엄격하면 안 된다 (M23)
- 서버는 RDKit 없이 V2000 파싱·원소 집합·중원자 수·평면·연결성·상자 값만 점검한다(작업 모듈은 RDKit으로 한다). 같은 입력에서 서버가 더 엄격하면 유효한 입력을 막으므로 서버는 작업 모듈이 같은 이유로 거절할 입력만 거절하고 테스트가 도킹 환경 작업 모듈과 27가지 입력으로 이유를 대조한다. 결함이 둘 이상인 SDF에서는 두 이유가 다를 수 있고(둘 다 거절), M18 상자 값 규칙(수동 상자 한 변 8 Å 미만·margin 범위)은 단독 M18 서버처럼 `box_invalid`로 거절한다(작업 모듈은 5 Å도 통과시키고 margin 21은 `box_too_large`). `box_no_receptor_atoms`는 서버가 M7 투영(최소화 전)으로 보므로 상자 면에 걸친 원자에서 드물게 작업 모듈(최소화된 기준 모델)과 다를 수 있다.

### 같은 인자 재제출은 예산 부족이면 화면이 막지만 서버는 기존 작업을 돌려준다 (M23, M22와 같음)
- 서버는 같은 호출 키의 기존 작업을 예산 검사 전에 돌려주지만 화면은 `preflight.existing_job`이 있어도 부족분이 있으면 시작을 막는다. 하네스는 이미 끝난 GA를 다시 보이려고 화면의 증액을 한 번 눌렀다(되돌리지 않는 증액). 의도한 동작이면 이 노트가 설명이다.

### Stop 훅 그룹 시간과 그룹 나눔 (M21–M23, M23 병합 뒤 해결)
- **증상**: Stop 훅이 매 턴 나머지 pytest 그룹을 "480초 시간 초과"로 보고했다(테스트 실패가 아님). 다섯 그룹을 제한 없이 따로 돌렸을 때 나머지 그룹은 M21 고정 게이트 1,833개 602초(`docs/qa/m21-mutations-20261004/gate.txt`), M22 2,063개 1324초(`docs/qa/m22-ga-20261005/gate.txt`), M23 2,538개 2432초(`docs/qa/m23-sequence-ga-20261005/gate.txt`)였다. M20–M23 실행기 단위 테스트 넷은 훅 목록에 없었다.
- **원인**: M21–M23 백엔드 테스트(실제 OpenMM·PDBFixer·qvina·RDKit 작업 모듈)가 모두 `backend/tests` 전체로 나머지 그룹에 들어갔고, 실행기 테스트는 파일 이름으로만 들어가 새 파일이 저절로 들어가지 않았다.
- **대응**: 다른 pytest 없이 파일별로 8개씩 병렬로 시간을 재고(백엔드 80개 파일과 실행기 18개 파일 한 묶음, 벽시계 합 4,245초·CPU 합 6,095초) 그룹을 열넷으로 나눴다(목록은 `docs/operations.md`의 Stop 훅 문단). 혼자 536초인 `test_sequence_ga_jobs.py`는 테스트 단위로 나눴다(가장 긴 두 테스트 약 290초, 나머지 열두 테스트 약 250초. 모듈 범위 `base` 준비는 0.2초). 같은 세션 world(실제 GA 작업 넷, 약 230초)를 공유하는 `test_sequence_ga_api.py`·`test_sequence_ga_reports.py`는 한 그룹이면 약 390초로 가늠되어 따로 두고 world를 그룹마다 만든다. M21 읽기·보고서 네 파일은 world를 공유하므로 M21 다른 세 파일, `test_openmm.py`와 한 그룹에 둔다. 테스트 본문·제품 코드는 바꾸지 않았고 그룹 합집합은 이전 다섯 그룹 + 실행기 테스트 넷(3,158개)과 같다.
- **실측**: 훅 진입점(`echo '{}' | python3 .codex/hooks/stop.py`)을 끝까지 두 번 돌려 둘 다 통과, 총 342.1초·341.5초, 그룹 약 256–340초(가장 긴 그룹 `test_chemical_interactions.py`). 많은 파일이 자식 프로세스·스레드를 써서 CPU가 벽시계보다 크다(예: 파일별 측정에서 `test_mutation_model_worker.py` 64초에 CPU 300초, `test_sequence_ga_worker.py` 203초에 CPU 501초). 그래서 그룹은 벽시계와 CPU를 함께 보고 맞췄고, 같은 열네 그룹을 동시에 돌렸을 때 그룹 CPU는 295–725초였다.
- **새 테스트를 더할 때**: 새 백엔드 테스트 파일은 저절로 나머지 그룹(약 290초)에 들어가므로 실제 엔진을 돌리는 파일이면 다른 그룹에 넣거나 새 그룹을 만든다. 파일 하나가 그룹 제한에 가까워지면 테스트 단위로 나누되 모듈 범위·세션 fixture가 그룹마다 다시 만들어지는 비용을 잰다.

### 과학 전송이 도는 동안 같은 run의 다른 변경 요청은 503 busy다 (M24)
- **증상**: 전송이 응답을 기다리는 동안 같은 run의 `POST /commands`(`build_jev_projection` 포함)·작업 시작·보고서 만들기가 503 busy를 받는다.
- **원인**: `request_science`는 `request_viewer`처럼 HTTP 동안 run 실행 잠금(`Run._mutation()`)을 쥔다(제한 시간 최대 15초).
- **대응**: 전송 라우트는 잠금 전에 프로세스 메모리 집합 `ACTIVE_SENDS`를 보고 409 `send_in_progress`를 돌려준다(두 번째 전송이 503으로 새지 않음). 상태·미리보기·목록·상세 읽기는 잠금 없이 이벤트 로그를 한 번 읽고, 동의 라우트는 짧은 전이 잠금(`_transition()`)만 쓴다. 화면은 전송 중 "보낼 내용 만들기"를 막는다. 다른 요청이 잠금을 쥐고 있으면 전송은 503 `busy`이고 승인 이벤트도 쓰지 않는다(승인은 잠금 안의 콜백이 쓴다). 이벤트 추가가 매번 로그 전체를 다시 읽으므로 큰 로그에서 전송 한 번이 async 라우트의 이벤트 루프를 잠깐 막는다(착수 확인: 50 MB에서 약 1.5초, 뷰어와 같은 성질).

### 전송 중 메모리의 `run.cancelled`는 갱신되지 않는다 (M24)
- `Run.cancel()`은 취소 표시 파일과 `cancel_requested` 이벤트만 쓰고, 전송이 쥔 run 객체의 메모리 플래그 `cancelled`는 그대로였다(착수 확인 실측 False). 그래서 게이트의 `cancelled` 거절은 취소 이벤트 또는 표시 파일로(`jev_sends.cancel_seen`), 늦은 응답은 그 전송의 `jev_science_dispatch_started` 뒤에 오는 취소·동의 끄기 이벤트의 순서로만(`late_arrival`) 판정한다. 시계·메모리 플래그를 쓰지 않는다.

### 과학 예약에는 외부 토큰과 USD가 둘 다 있어야 하고, 환불은 정산이 먼저다 (M24)
- `budget_reserved`에 `expensive_calls` 없이 `external_tokens`·`usd`만 담아도 `_refresh`·`_settle_egress`·`_reconcile_egress`·`would_exceed`는 그대로 동작하지만 두 축 중 하나라도 빠지면 정산이 `KeyError`다(`reservation[axis]`).
- 예약 뒤 보내지 못하면 음수 delta `egress_budget_settled`를 먼저 쓰고 `dispatch_skipped` 감사를 쓴다(`request_viewer`와 같은 순서). 감사를 먼저 쓰면 그 사이 충돌이 미정산 예약 = 재시작 때 `usage_unknown` 멈춤이 된다. 정산 뒤·감사 전 충돌은 재시작 때 `wall_charged`(egress) 하나가 더 붙을 뿐 멈추지 않는다. 비싼 계산 축이 없으므로 `_reconcile_egress`가 "보내지 않음"을 아는 표지는 `dispatch_skipped` 감사뿐이다.

### 새 백엔드 모듈은 `raise_limits`·`limit_approval` 문자열을 쓰지 않는다 (M24)
- 기존 증액 AST 테스트 셋(`test_docking_batch_budget.py`·`test_ligand_ga_budget.py`·`test_sequence_ga_budget.py`)은 `backend/mw` 아래 모든 파일 본문에서 이 두 문자열을 찾아 파일 집합을 고정한다. 주석·docstring에 써도 깨진다. M24 모듈은 쓰지 않고 `test_jev_ast.py`가 새 모듈마다 확인한다.

### 게이트는 승인 콜백을 부른 뒤 로그에서 승인을 다시 대조한다 (M24)
- `request_science(gate, run, projection, send_id, *, admit)`는 `admit`가 없거나 호출할 수 없으면 아무것도 쓰기 전에 `TypeError`다. run 실행 잠금과 전이 잠금 안에서 `admit(events)`를 부르고(`run_send`의 콜백이 `jev_send_approved`를 씀, 같은 `send_id`의 승인이 이미 있으면 기존 기록을 돌려주는 경로로 빠짐), 이어서 로그에서 그 `send_id`의 첫 승인이 이 본문 해시·질문·소스·후보 수·`approved_by: "human"`과 같은지 확인한다. 다르면 `PermissionError`이고 감사·예약·키 읽기·요청이 없다(라우트는 500 `internal_error`). 그래서 다른 호출자가 생겨도 기록된 사람 승인 없이는 보내지 못하며, 호출자 자체는 AST 테스트가 라우트 하나로 묶는다.

### 결과 기록(`_finish`)은 실행 잠금을 다시 잡지 않는다 (M24)
- `request_science`가 돌아오면 run 실행 잠금이 풀린 뒤다. `_finish`는 결과 판정·제안 객체 저장·`jev_send_outcome`을 짧은 전이 잠금(`_transition()`, 기다리는 잠금)만 잡고 한다. 실행 잠금(`_mutation()`)은 다른 요청이 쥐고 있으면 기다리지 않고 busy로 실패하므로, 실제로 보낸 뒤의 결과 기록이 그 때문에 빠지지 않게 한다. `ObjectStore.put`·`EventLog.append`는 취소를 보지 않으므로 취소된 run에서도 늦은 응답의 제안 객체와 결과 이벤트가 저장되고 events-only로 다시 열린다(착수 확인 (f)).

### 보내지 않았는데 기록이 `delivery_unknown`으로 읽히는 경우가 있다 (M24)
- **증상**: `prepared` 감사 저장이 실패하거나(디스크 오류) 승인 대조가 실패하면(`PermissionError`) 라우트는 500 `internal_error`이고, 전송 기록은 `failed`/`delivery_unknown`으로 도출된다.
- **원인**: 기록은 이벤트만으로 만든다. 승인 이벤트는 있고 결과 이벤트·dispatch 이벤트가 없으며 진행 중도 아니면 닫힌 이유 집합에서 `delivery_unknown`밖에 없다.
- **대응**: 실제로 보냈는지는 감사로 판단한다: `prepared` 저장 실패는 게이트가 음수 정산 뒤 `dispatch_skipped`(`reason_code: "prepared_not_recorded"`, `transport_invoked=false`)를 쓰려 하고(디스크가 그것도 못 쓰면 미정산 예약이 남아 재시작 때 `usage_unknown` 멈춤), 승인 대조 실패는 감사가 없다. 두 경우 모두 `jev_science_dispatch_started`가 없어 전송 상한을 쓰지 않는다. 응답을 받은 뒤 `_finish`가 실패하면(`response_received`는 있음) `outcome_not_recorded`다. 닫힌 이유 집합을 넓히려면 사용자 결정이 필요하다.

### JEV POST는 `application/json`이 아니면 본문을 읽기 전에 415다 (M24)
- **증상**: `Content-Type`이 없거나 `text/plain`·폼·multipart인 `POST /runs/{id}/jev/consent`·`/jev/preview`·`/jev/sends`가 415 `unsupported_media_type`을 받고 어떤 이벤트·상태도 바뀌지 않는다. M11–M23 원시 본문 라우트(`_chemical_json(await _bounded_chemical_body(...))`: 화학·도킹·GA)는 같은 본문을 받아 주고, FastAPI 본문 모델 라우트(예: `/viewer/online`)는 415가 아니라 422로 거절한다(FastAPI `strict_content_type` 기본값).
- **원인**: 다른 사이트 페이지의 단순 POST(사전 요청 없음)가 과학 데이터 전송 동의·전송 라우트를 막지 못하는 성질을 막으려고 `_jev_request`(`api/app.py`)가 쿼리 검사 다음, 본문을 읽기 전에 매개변수(`; charset=utf-8`)를 허용하는 대소문자 무시 `application/json`만 받는다.
- **대응**: 테스트·하네스·스크립트 클라이언트는 `content-type: application/json`을 붙인다(프런트 `jsonPost`는 이미 붙인다). 원시 본문으로 JSON 형식·크기 거절(422·413)을 시험하는 테스트도 이 헤더가 있어야 거기까지 간다. 도구 호출(`POST /runs/{id}/commands`)은 이 검사를 받지 않는다. 다른 라우트도 같은 검사가 필요해지면 공통 요청 헬퍼로 합친다(`docs/tracking/findings.md`).

### 서열 구간 한 글자는 M20 이름 규칙을 따르고, HETATM 변형 잔기는 구간에서 빠진다 (M24)
- 구간 글자는 M20 위치의 `one_letter` 규칙(표준 20종 + 이름 대응 10개: HID·HIE·HIP·HSD·HSE·HSP → H, CYX → C, ASH → D, GLH → E, LYN → K)이고 그 밖의 이름은 `X`다. 대응 이름을 `X`로 두면 같은 잔기의 위치 `one_letter`와 구간 글자가 어긋난다.
- 단백질 잔기는 M20 위치 정의와 같은 ATOM 레코드(`het_flag == "A"`, 물 아님)다. MSE처럼 HETATM으로 기록된 변형 잔기는 구간 글자·이웃에 들어가지 않고(`X`로도 나오지 않음), 그 자리를 지나는 구간은 `seq_auth`가 건너뛰어 `contiguous: false`다.
- 대상 잔기에 중원자가 없으면 이웃은 `null`(계산하지 않음)이며 빈 목록 `[]`(계산했는데 없음)과 구분한다.
- 이웃 거리 비교 테스트는 허용 오차로 한다: NumPy 최소 거리와 `math.dist`는 1UBQ·1MQ4 단백질 잔기 쌍의 약 19%에서 마지막 비트가 다르다(최대 7.1e-15 Å). 5.0 Å 포함 여부는 모두 같고 경계까지 최소 여유는 0.00126 Å이다.

### 전역 "과학 전송 허용" 표시는 `.mw-app-run` 밖에 둔다 (M24)
- 탭 흐름(`tabs-flow.cjs`)이 `.mw-app-run` 요소의 글자가 run id와 같다고 확인하므로 표시를 그 안에 넣으면 M14 회귀가 깨진다. 표시는 형제 요소 `.mw-app-science`(`data-science-consent="on"`)이고 현재 run의 동의가 켜졌을 때만 보인다. 페이지는 run이 바뀔 때 상태를 한 번 읽고(새 폴링 없음) 그 뒤로는 JEV 영역이 읽거나 바꾼 상태(`onStatus`)를 받아 요청 순서(`scienceMarkGate`)로 늦은 답을 버린다.

### 오프스크린 fixture 서버는 모듈 전역 `SCIENCE_GATE`를 바꾼다 (M24)
- `backend/tests/offscreen_jev_fixture/server.py`는 제품 앱(`mw.api.app`)을 import한 뒤 모듈 전역 `SCIENCE_GATE`를 스크립트된 `httpx.MockTransport` 게이트(placeholder 자격 증명)로, `VIEWER_GATE`를 거절하는 게이트로, `RUNS_DIR`를 격리 폴더로 바꿔 같은 프로세스에서 uvicorn으로 띄운다. 전송 라우트가 요청마다 모듈 전역을 읽으므로 치환이 듣는다(게이트를 import 때 붙잡는 코드로 바꾸면 fixture가 실제 네트워크로 나간다). 치환하지 않은 서버만 실제 OpenRouter로 나간다.
- 응답은 control 폴더 `script.json`의 스크립트(`good`·`good_no_extras`·`alias_outside`·`http_500`·`no_usage`·`model_mismatch`·`slow`)가 정하고 `slow`는 `release` 파일이 생길 때까지 최대 12초 붙잡아(붙잡는 동안 `inflight.json`) 전송 중 동의 끄기로 늦은 응답을 만든다. 확률·사용량은 표시된 fixture 값이며 모델 판단이 아니다. `calls.jsonl`에는 본문 SHA-256·바이트·스크립트·불리언만 남고 본문·헤더·자격 증명은 없다. run 취소에 의한 늦은 응답은 HTTP 취소 경로가 없어 백엔드 테스트로 덮는다.

### 실호출은 저장소 단위 대장으로 세고, 증거만 빠진 calibrate는 `--finalize`로 마무리한다 (M24)
- **증상**: calibrate 단계의 첫 실호출이 끝난 직후 실행기가 증거를 쓰기 전에 멈췄다(전송 상세 dict를 기록 함수에 `**`로 펼쳐 그 안의 `status` 키가 인자와 겹친 `TypeError`). 같은 단계를 다시 돌리면 실호출을 또 쓴다.
- **대응**: 기록 함수에는 상세를 키워드 하나(`detail`)로 넘긴다. 실호출 수는 root의 `jev_science_dispatch_started` 이벤트로 확정하고 저장소 단위 대장 `runs/m24-live-ledger.json`(주 체크아웃의 Git 제외 폴더, git common dir로 찾음)에 단계 시작을 먼저, 끝에 root의 run별 수를 적는다. 단계 시작 전에 대장 합계(기록된 root를 다시 셈) + 계획이 6을 넘거나 대장을 읽을 수 없으면 아무것도 시작하지 않는다. 증거만 빠진 calibrate root는 `--phase calibrate --finalize`가 저장 파일만 읽어 증거를 다시 만들고 호출·서비스·빌드·대장 쓰기를 하지 않는다(2026-10-06 첫 실호출 root에 쓴 경로). 실패한 실호출도 1회이며 다시 시도하지 않는다.

### 과학 본문은 바이트당 토큰이 뷰어 본문보다 많다 (M24)
- M24 실호출 6회(2026-10-06, 응답 모델 모두 `typesafe/jev-1.13-20260917`, 모두 `completed`)의 본문 바이트/입력 토큰: 리간드 1.63–1.70(5개 3,539 B → 2,087 토큰, 10개 5,607 B → 3,433 토큰), 변이 1.71–1.79(1UBQ 5개 7,030 B → 3,921, 1UBQ 20개 25,428 B → 14,619, 1MQ4 20개 29,151 B → 17,011 두 번). M8 뷰어형 JSON은 약 2.24였다. 출력 65–200 토큰, 비용 호출당 약 0.00009–0.00071 USD였다.
- 예약식 `min(50000, 4096 + ceil(body_bytes × 2 / 3))`은 1.5 B/토큰을 가정해 모든 실측 사용량보다 컸다(예: 3,539 B 본문 예약 6,456 대 사용 2,152. 같은 본문의 첫 식 `4096 + ceil(body_bytes / 2)`는 5,866이었다). 식은 조정 가능한 기본값이므로 바꿀 때는 이 실측과 대조한다. 예약이 사용량보다 작으면 기존 규칙대로 그 run의 모든 온라인 전송이 `budget_exhausted`로 멈춘다.
- 여섯 응답 모두 `confidence`와 보낸 후보 수만큼의 `probabilities`를 담았고, 모두 첫 별칭(`c01`·`m01`)을 골랐다(같은 본문 재전송 포함, J4 참고).
- M25 루프 실호출 8회(2026-10-07, 모두 `completed`, 응답 모델 `typesafe/jev-1.13-20260917`)의 본문 바이트/입력 토큰은 리간드 1.79–1.85(3,855–4,257 B → 2,154–2,302 토큰), 1UBQ 변이 1.91(7,900–7,963 B → 4,146–4,175 토큰)이었고 사용 토큰은 예약의 0.33–0.45배였다. 첫 호출 보정에서 예약식을 바꿀 필요가 없었다.

### 작업 큐는 같은 호출 키의 기존 작업을 상태와 무관하게 돌려준다 (M25)
- **증상**: 루프가 승인한 작업을 시작 전에 취소한 뒤 같은 후보로 다시 계산을 시작해도 새 작업이 생기지 않는다. 다른 `timeout_s`로 다시 제출해도 같은 `job_id`이고 첫 `timeout_s`가 남는다.
- **원인**: `JobQueue.submit`은 같은 호출 키의 작업이 있으면 상태(`cancelled`·`failed`·`queued`·`done` 등)와 무관하게 그 작업을 돌려주고, M18·M21 호출 키에는 `timeout_s`가 들어가지 않는다. 시작 전 취소는 `cancelled`(무과금)이고 `retry`는 `failed`·`interrupted`만 받는다(착수 확인 (a)·(l), `docs/qa/m25-jev-loop-20261007/preflight.txt`).
- **대응**: 루프는 시작 전에 취소·종료된 단계를 `unavailable`로 읽고(그 후보는 이 run에서 다시 계산할 수 없음, 사용자 결정. 새 run에서는 된다) 자기 작업이든 남의 작업이든 시작·재시도·취소하지 않는다. 루프 밖의 쓸 수 없는 같은 키 작업은 `candidate_unavailable`, 후보 상태를 읽은 뒤 경합으로 나타나면 `step_unavailable`(승인 이벤트 직전에 큐를 다시 봄)이다. 화면은 승인 대기 작업을 취소하기 전에 이 결과를 안내한다.

### 프로세스가 떴는지는 `budget_reserved.root_call_id`로만 가린다 (M25)
- **증상**: `job_terminal`의 `attempt_id`나 종료 상태 이름으로 판정하면 예약 직후·dispatch 전 취소가 "시작 전"으로 읽혀 과금 단위와 바퀴 셈이 어긋난다.
- **원인**: 비싼 계산 예약 이벤트는 `budget_reserved{attempt_id, root_call_id=<job_id>, tool, expensive_calls: 1}`이고 `job_id` 필드가 없다. 예약 뒤 dispatch 전에 취소된 작업은 과금 1·프로세스 없음으로 끝난다.
- **대응**: 단계 상태·바퀴 시작·`units_charged`·요약 검증 모두 그 작업의 마지막 대기열 표시 뒤 `budget_reserved.root_call_id == job_id`가 있느냐 하나로 가른다(해석 N3). 있으면 실패해도 `failed`(과금, 바퀴 시작), 없으면 `unavailable`(무과금)이다.

### 첫 계산 승인 대기와 예산 막힘은 같은 작업 표시다 (M25)
- 시작이 막힌 작업은 두 경우 모두 `claimed` + `blocked_reason: "approval_or_cancel"`이다. 루프는 run의 첫 계산 승인 요청(`approval_requested`, gate `expensive_first_call`)이 아직 풀리지 않았는지로 `current.job.start_blocked: "approval_required"`를 가린다. 그 상태에서 서버가 다시 시작되면 복구가 무과금 `interrupted`로 닫으므로 그 단계는 `unavailable`이다.

### M21에는 호출 키 → 모델 handle 색인이 없다 (M25)
- M18에는 `docking_batch_inputs.published_m18_results`(호출 키 → 결과 handle, 단독·M19 행·M22 개체)가 있지만 M21에는 없다. 루프는 `jev_loop_store.model_index`가 같은 이벤트 스냅숏의 `job_submitted`(M21 프로토콜 작업의 호출 키)와 `job_terminal(done)`의 `output_handles[0]`을 이어 만들고, 그 handle을 `mutation_model_bundle.validated_result`와 입력 대조로 다시 검증한 것만 저장 모델로 친다. 변이 쪽 도킹 호출 키는 모델 handle이 들어가므로 모델이 검증되기 전에는 없다.

### 전이 잠금 안에서 `submit`하면 같은 스레드가 교착한다 (M25)
- **증상**: 승인 이벤트와 작업 제출을 `Run._transition()` 안에서 하면 응답이 돌아오지 않는다. 실행 잠금을 쥔 채 `JobQueue.start`를 부르면 busy다.
- **원인**: `_transition`은 `threading.Lock` + `flock`이라 재진입하지 않고 `submit`이 스스로 전이 잠금을 잡는다. `start`는 작업이 도는 동안 run 실행 소유권(`_owner`)을 쥐고 소유권도 재진입하지 않는다(착수 확인 (e)).
- **대응**: 계산 라우트는 실행 잠금 안에서 루프 판정 → 작업 입장 검사 → 승인 이벤트(짧은 전이 잠금 안, 같은 키 작업·취소 재확인) → `submit`(전이 잠금 밖)을 하고, 실행 잠금을 놓은 뒤 기존 시작 라우트처럼 `start`를 부른다. 응답은 작업이 끝날 때까지 기다리고(기존 시작 라우트와 같은 성질) 읽기는 잠금 없이 계속된다. 다른 요청이 잠금을 쥐고 있으면 아무것도 쓰거나 시작하지 않는 답(거절, 시작이 필요 없는 멱등 답)만 잠금 없이 주고 나머지는 503 `busy`다.

### 작업은 승인과 제출 사이에 끼어든 이벤트가 없을 때만 그 단계의 것이다 (M25)
- **증상**: T11 검토에서, 제출이 사라진 승인 뒤에 같은 요청의 루프 밖 작업이 생기면 그 작업이 루프 단계로 읽혀 끝난 바퀴가 다시 `running`이 되거나 기록·목록·끝내기가 500이 되는 경우를 찾았다.
- **원인**: "같은 호출 키의 가장 가까운 앞 승인"만으로 귀속하면 루프 밖 작업과 구분할 수 없다.
- **대응**: `jev_loops.job_owners` 하나가 모든 루프 읽기와 M21 짝 표의 귀속을 정한다: 사이에 어느 루프의 `jev_loop_*` 이벤트나 M24 과학 전송 이벤트(`J.EVENT_APPROVED`·`EVENT_DISPATCH`·`EVENT_OUTCOME`, 실행 잠금 보유자만 씀)가 있으면 끊기고, 단위 0 승인(저장 결과 채택)은 작업을 소유하지 않는다(`490cfc7`·`43a3e5d`). 계산 라우트는 승인과 제출을 한 번의 실행 잠금 안에서 하므로 자기 작업은 늘 귀속된다. 귀속되지 않은 같은 키 작업은 루프 밖이며 그 단계는 제출이 사라진 `unavailable`이다.

### 끝난 루프의 기록은 끝 이벤트 시점으로 동결해서 읽는다 (M25)
- 끝난 뒤 루프 밖에서 같은 키의 결과가 생기면 지금 로그로 도출한 후보 상태·`counts`·LJ8이 저장 요약과 달라져 요약 검증이 실패한다. 그래서 끝난 루프는 `jev_loop_ended`까지의 이벤트로 다시 도출하고 저장 요약이 그 도출과 정확히 같아야 한다(`8079024`). 지금 값은 `current.remaining`과 쓰기 거절 입력(run 취소 이벤트, 진행 중 전송)뿐이라 끝난 루프에도 쓰기 라우트는 `cancelled`를 `loop_ended`보다 먼저 답한다. 요약 저장과 끝 이벤트 사이에 멈추면 루프는 끝나지 않았고 다음 `end`가 같은 handle로 이벤트만 쓴다.

### 루프 제안은 자기 전송에만 맞고, 늦은 응답은 이벤트 순서로만 가린다 (M25)
- 저장된 `jev_loop_choice@1`은 내용만으로는 어느 전송의 응답인지 보증되지 않는다. 기록·전송 상세·요약·보고서는 `jev_loops.proposal_matches_send`로 그 전송의 첫 결과 이벤트가 이 handle·`audit_id`를 가리키는 `completed`이고 첫 승인이 이 투영·본문 해시이며 `arrival`이 이벤트 순서 판정과 같을 때만 제안으로 센다(`853a43c`). 늦음은 M24처럼 dispatch 뒤 취소·동의 끄기 이벤트로만 판정하고(시계·메모리 플래그 없음), 늦은 제안은 저장되지만 바퀴의 선택이 아니다(계산 시작에 넘기면 `proposal_late`).

### 루프 전송 검사는 승인 콜백이 받은 이벤트 목록만 쓴다 (M25)
- 루프 전송 검사는 게이트의 실행 잠금·전이 잠금 아래 승인 콜백에서 돈다. 로그를 다시 읽거나 잠금을 다시 잡으면 교착하거나 다른 스냅숏을 본다. 그래서 `jev_loop_store.loop_send_check`는 콜백이 받은 이벤트 목록으로 만든 `LoopReadView`만 쓰고, 프로세스 메모리의 전송 진행 여부는 `app.py`가 `jev_sends.send_active` 값을 넘긴다. 거절(409 `loop_send_invalid`)은 승인 이벤트 앞이라 감사·예약·키 읽기가 없지만 게이트가 끝에 남기는 `wall_charged`는 남을 수 있다. 같은 `send_id`의 재생(`_replayed`)이 루프 검사보다 먼저라 두 번 눌러도 한 전송이다. `send_ordinal`은 이 바퀴의 dispatch 수라 실패한 전송 뒤에는 투영을 다시 만들어야 하고(`ordinal_mismatch`), 투영 뒤 계산 상태가 바뀌면 `state_changed`다.

### `jev_loop_*` 이벤트는 예산·egress 정산·재생에 영향이 없다 (M25)
- `core/events.py` `EventType`은 타입 표기(`Literal`)뿐이고 `jev_loop_compute_approved`의 `units`·`call_key`를 읽는 기존 접기가 없다. 착수 확인 (g)에서 루프 이벤트 넷을 끼운 run과 안 끼운 run의 예산·egress 멈춤·작업 상태·재사용 색인·전송 기록·재열기·GET 25개 상태 코드가 모두 같았다. 승인 이벤트는 예산 이벤트가 아니고 비싼 계산 과금은 기존 작업 예약(`budget_reserved`)으로만 생긴다.

### 루프 서버 모듈은 `jev_sends`를 import하지 않는다 (M25)
- `egress/science.py`가 `jev_sends`를 import하므로 루프 모듈이 `jev_sends`를 import하면 순환이 생기고 `test_jev_ast.py`의 `jev_sends` 임포터 집합(`api/app.py`·`egress/science.py`·`jev_reports.py`)이 깨진다. 전송 수·늦음·동의 같은 이벤트 도출은 `jev_loops`에 순수 함수로 다시 쓰고 M24 함수와 같은 결과임을 대조 테스트로 확인한다. M24 이벤트 이름은 `jev_constants`의 `EVENT_*` 속성으로만 가리킨다(이름 문자열의 위치는 `jev_constants.py`·`core/events.py`로 고정). 반대 방향(`jev_sends`·`egress/science.py`·`mutation_model_reads.py`가 루프 모듈을 import)은 허용이다. 루프 모듈도 `raise_limits`·`limit_approval` 문자열을 쓰지 않는다.

### 1MQ4는 M7 사전 검사를 통과하지 못해 단백질 루프를 만들 수 없다 (M25)
- 1MQ4 집합은 M21 입장 1–7을 통과하지만 제출 때 M7 사전 검사에서 422 `openmm_preflight_failed`가 난다. 루프 만들기는 이 사전 검사까지 서버 쪽 입장으로 보아 `setup_invalid`/`setup_reason: "openmm_preflight_failed"`로 거절한다(해석 N1, 수락 사례 `P-create-refused`). 로컬 공개 구조 중 M7을 통과하는 것은 1UBQ뿐이라 단백질 루프의 QA·실호출은 1UBQ 풀로 했다(M21 기록과 같음).

### M24 오프스크린 하네스의 다른 탭 검사가 `jev-` 선택자로 루프 영역을 셌다 (M25)
- **증상**: 고정 소스(`4360598`)에서 M24 회귀의 fixture 단계가 실패했다: `jev-flow.cjs`의 F01이 단백질 공학 탭 `jev-` 요소 41개·리간드 설계·탐색 탭 35개를 0이어야 한다고 거절했고, 연습 단계의 P-other-tabs는 탭 글자 서명에서 루프 영역의 동의 줄이 달라 거절했다(`docs/qa/m25-jev-loop-20261007/regression-harness-changes.txt`).
- **원인**: M24 하네스가 다른 탭의 `[data-testid^="jev-"]`를 모두 세고 탭 전체 글자를 비교했는데, M25 루프 영역의 `data-testid`도 `jev-loop-` 접두사다.
- **대응**: `tabSignature`만 고쳤다(`9a9a625`): 글자 서명에서 `[data-testid="jev-loop-panel"]` 하위 트리를 빼고, M24 요소 수를 `[data-testid^="jev-"]:not([data-testid^="jev-loop-"])`로 센다. 다른 단언·실행기는 그대로다. 새 영역에 `jev-` 접두사를 쓰면 이 선택자 결합을 함께 확인한다.

### 오프스크린 루프 fixture 서버도 모듈 전역 `SCIENCE_GATE`를 바꾼다 (M25)
- `backend/tests/offscreen_jev_loop_fixture/server.py`는 M24 fixture 서버와 같은 방식으로 제품 앱의 `SCIENCE_GATE`를 스크립트된 `httpx.MockTransport` 게이트(sentinel placeholder 자격 증명)로, `VIEWER_GATE`와 기본 인자로 만드는 게이트를 거절하고 `.env`를 읽지 않는 게이트로 바꾼다. 스크립트는 `good`·`good_second`(두 번째 `criteria` 키, 목록 위치 2/m)·`computed_alias`·`http_500`·`slow`·`no_usage`·`model_mismatch`이고 `calls.jsonl`·`credentials.json`에는 본문 SHA-256·바이트·개수·불리언만 남는다(본문·헤더 값·자격 증명 없음). 수락 실행기는 `server.json`의 pid가 방금 띄운 pid이고 8000 포트의 유일한 리스너일 때만 하네스를 띄우고(하네스도 `--backend-pid`로 확인), 연습(`--rehearse`)은 제품 백엔드를 띄우지 않는다. QA run은 `offscreen_jev_loop_fixture/qa_setup.py`가 loopback API로 만든다.

### 무거운 루프 테스트가 나머지 그룹을 480초 넘게 했다 (M25)
- **증상**: 루프 API·읽기·도구·제안·전송 테스트(실제 엔진, 약 175초)가 이름 없는 나머지 그룹에 들어가자 Stop 훅이 480초 시간 초과를 보고했다.
- **대응**: 그 다섯 파일(`test_jev_loops_read.py`·`test_jev_loop_sends.py`·`test_jev_loop_tool.py`·`test_jev_loop_choice.py`·`test_jev_loops_api.py`)을 열넷째 이름 있는 그룹으로(`b0d0f96`), `test_jev_loops_compute.py`를 열다섯째로(`da37288`) 나눴다(`PYTEST_GROUPS` 열다섯 + 나머지 = 열여섯 그룹, `CHECKS` 17, `scripts/test_codex_hooks.py`의 기대 17). M25 고정 게이트에서 두 그룹은 175초·224초, 가장 긴 그룹은 나머지 그룹 398초였다(`docs/qa/m25-jev-loop-20261007/gate-backend.txt`).

### Stop 훅 동시 실행 중의 간헐 실패 셋 (M25 기간, 환경·우연)
- 그룹을 동시에 돌릴 때 한 번씩 실패하고 따로 돌리면 통과한 테스트가 셋 있었다: 부하 때 psutil `proc_cmdline`의 `SystemError`(`test_sequence_ga_worker`), M23 SIGTERM 타이밍 테스트, M24 `test_jev_reports.py`의 `'0.1234' not in dumped`가 보고서의 `time_utc` 숫자와 우연히 겹친 경우. 제품 동작과 무관하며 고정 게이트(`gate-backend.txt`)에서는 재현되지 않았다. 기록은 `docs/tracking/findings.md`.

### M-CSA API는 `page_size`를 조용히 100으로 자르고 `next`는 요청 값을 되풀이한다 (M26)
- **증상**: 착수 확인에서 `page_size=1003`을 보내도 오류 없이 100개만 오고, `next` URL에는 요청한 `page_size=1003`이 그대로 있었다(`docs/qa/m26-reaction-20261008/preflight-network.md` (a-1)). `next`를 따라가거나 큰 쪽 크기를 믿으면 항목을 빠뜨린 채 "전부 받음"이 된다.
- **대응**: 가져오기 명령은 `page_size=100`을 고정하고 첫 쪽의 `count`로 쪽 수를 계산해 `page=1..ceil(count/100)`을 직접 돈다(`next`는 형만 검사하고 따르지 않음). 모든 쪽의 `count`가 같고, 쪽마다 정확히 제 몫의 항목이 오고, 받은 항목 수 = `count`, `mcsa_id` 중복 없음을 확인한다(2026-10-09: 1,003개, 11쪽).

### UniProt 여러 accession 요청은 받지 못한 accession을 이유 없이 뺀다 (M26)
- **증상**: `/uniprotkb/accessions`(한 요청 최대 1,000개, 1,001개는 400)는 삭제·분할·보조·없는 accession을 오류 없이 결과에서 빼고 `X-Total-Results`는 요청한 개수를 보인다. 대표 accession으로 바꿔 주지도 않는다.
- **대응**: 빠진 accession마다 `/uniprotkb/{accession}.json?fields=accession` 한 건으로 분류한다: 200 + `entryType: "Inactive"`이면 `inactiveReasonType` `DELETED` → `obsolete`, `MERGED` → `merged`(대상 하나), `DEMERGED` → `demerged`(`mergeDemergeTo` 1–3개), 404 → `not_found`, 그 밖 → `fetch_failed`. 빠진 파생 accession이 `MAX_SKIPPED`(50)보다 많으면 분류 요청 없이 멈춘다. 실측 받지 못한 8개는 `DELETED` 4·`DEMERGED` 4였고 `MERGED`는 관찰하지 못해 합성 시험으로만 덮는다. 보조 accession(P02023)도 `DEMERGED`로 대표 셋을 돌려줬다.

### UniProt 부위 일부는 같은 accession의 동형체 위치다 (M26)
- **증상**: 첫 실서버 가져오기 전 오프라인 재생에서 형식 오류로 멈췄다. 활성 1,622개 중 P12821의 Binding site 3개가 `location.sequence`(= `<같은 accession>-<n>`) 키를 가졌다(`import1.md` 1절).
- **대응(사용자 결정 2026-10-09)**: 그 모양의 부위만 정규 서열 위치가 아니므로 저장하지 않고 건너뛰며 개수는 명령 출력에만 보인다(매니페스트 키 집합이 고정이라 세트에는 남지 않음). 다른 `sequence` 값이나 알 수 없는 위치 키, `EXACT` 정수가 아닌 위치는 여전히 형식 오류로 설치를 중단한다. 실서버 가져오기 전에 명령 수정과 합성 회귀 시험(`backend/tests/fixtures/reaction/t9a/`)을 커밋했다(`075e38e`).

### UniProt 촉매 활동의 Rhea 교차참조에 `RHEA-COMP:`가 섞인다 (M26)
- `reactionCrossReferences`의 `database: "Rhea"` ID는 반응 `RHEA:<n>`과 고분자 화합물 `RHEA-COMP:<n>`이 섞여 있다(착수 확인 표본에서 592·527개). `rhea_ids`에는 `^RHEA:[0-9]+$`만 넣는다. `physiologicalReactions`의 방향 있는 Rhea ID는 필드가 없어 버린다. 연결된 `RHEA:` ID는 모두 방향 없는 대표 반응이라 Rhea는 대표 반응만 받는다(REST 한 요청 18,611행, `limit=20000`. 전체 개수 헤더가 없어 받은 행 수가 `limit` 이상이면 잘림으로 보고 형식 오류). FTP `txt/rhea-reactions.txt.gz`는 README가 옛 호환 형식이라 적어 쓰지 않는다.

### M-CSA 목록 응답의 `main_annotation`은 늘 빈 문자열이고 `residue_sequences[].resid`는 UniProt 위치다 (M26)
- entries 끝점의 `main_annotation`은 5,248개 잔기 모두 빈 문자열이고 같은 문구는 `residues` 끝점에만 있다. 사용자 결정으로 저장하지 않는다(요청을 더하지 않음). `residue_sequences[].resid`는 UniProt 서열 위치(4,918/4,932 일치)이지만 구조 연결에 쓰지 않으므로 버린다.
- 그 밖의 실측 모양: `reference_uniprot_id`는 74개 항목에서 accession 여럿을 `", "`로 이은 문자열이라 accession 집합은 `,`로 나눠 공백을 지워 만들고(원문은 그대로 저장), `residue_sequences[].uniprot_id` 279행은 빈 문자열이라 accession이 아니다. `assembly`는 정수 또는 빈 문자열(783행)이라 빈 문자열을 null로 바꾼다. M-CSA 화합물 `chebi_id`는 `CHEBI:` 접두 없는 숫자 문자열이거나 ChEBI가 아닌 `X006nn` 모양이라 원문 그대로 두고 Rhea와 잇지 않는다.

### M-CSA 번호는 `auth_resid`(저자)와 `resid`(label) 둘이고, 체인은 저자 체인이다 (M26)
- **원인**: `chain_name`은 저자 체인 ID다(숫자 `1`, `L`·`S` 같은 서브유닛 이름이 있고 87개 항목은 `A` 없이 이런 이름만 씀). `resid`는 mmCIF `label_seq_id`, `auth_resid`는 저자 번호다(1,612행에서 다름, 1S9I는 `resid` 140·`auth_resid` 194, 7행은 `auth_resid` null). `assembly_chain_name`은 289행에서 `chain_name`과 다르다(조립체 파일 이름).
- **대응**: 대응은 `auth_resid`와 구조 `seq_auth`로만 하고(삽입 코드 무시) `resid`는 `seq_label`과 비교하지 않고 값으로만 보인다. 체인은 `chain_name` = `chain_auth`로만 맞추고 조립체 이름은 무시한다. 같은 번호의 사슬 잔기가 둘 이상(삽입 코드 변형·같은 번호 이질 잔기)이면 고르지 않고 `ambiguous_residue_number`, 하나뿐인데 삽입 코드가 있으면 `insertion_code_present`(잔기 7필드는 담음), `auth_resid` null이면 `no_author_number`, `code`가 `Sec`·`X`이면 `non_standard_code`다. 구조 이름은 M20 `standard_name`(표준 20종 + HID·HIE·HIP·HSD·HSE·HSP·CYX·ASH·GLH·LYN)으로 비교하므로 HID 구조의 His 행은 `matched`, MSE는 `residue_name_differs`다.
- 저장소 안 구조(1HSG·1MQ4·1UBQ)는 M-CSA에 없어 모두 `pdb_not_in_snapshot`이다. 1HSG는 M-CSA 175(PDB 1A30)와 같은 단백질이고 같은 저자 번호에 같은 잔기 이름이 있지만, 다른 PDB에 서열로 잇는 것은 범위 밖이라 연결하지 않는다. 그래서 수락 QA용 공개 구조 셋(1S9I·1A30·1A4I, 사용자 결정)을 받았다.

### v1·v2 후보 집합을 함께 받는 곳은 `validated_set`의 세대 분기 하나에 기댄다 (M26)
- `validated_set`은 `method_version`이 `mw.mutation_candidates/v2`일 때만 v2 규칙을 돌리고 그 밖은 v1 경로 그대로다. 이름 없는 상수(`EXCLUSION_REASONS`·`LIMITATIONS`·`CATALYTIC_NOT_AVAILABLE_REASON` 등)는 v1 값을 바이트 그대로 지키고 v2는 `_V2` 이름과 촉매 블록을 쓴다. 이름 없는 상수를 v2 값으로 바꾸면 저장된 v1 집합(M23 fixture `m20-candidate-set-*.json`, `fixtures/reaction/t1/`)이 읽히지 않는다. M21·M23 작업 모듈이 `mutation_candidates`를 통해 `mutation_constants`를 간접 import하므로 v1 경로의 값은 바꾸지 않는다(해시 집합 밖이라 바꿔도 호출 키는 그대로인데 결과가 바뀔 수 있음).
- v2 `catalytic_residue_database.annotation`은 반응 결과 handle 문자열이다(KLIFS 칸의 `annotation` 선례). 아무 체인도 덮이지 않았으면 `exclusion_reason_counts.catalytic_residue`가 0(주석을 주지 않은 경우 포함), 주석을 주었으면 행 수도 0, 목록이 `[]`로 저장된다(명세 형식 그대로). 화면·M20 보고서는 이 경우 "—"와 이유를 보이고 숫자 주장을 만들지 않지만(독립 코드 검토 F4) 집합 상세 읽기의 원본 `result`에는 0이 있으므로 읽는 쪽은 `status`·`covered_chains`를 함께 본다.
- `validated_set`은 반응 결과 객체와 교차 대조하지 않는다(도구 시점과 보고서 만들기·다시 열기가 한다). 사용자가 확인한 PDB ID를 번호 대응·주석의 PDB ID와 서로 비교하지 않는다. v1 집합에 `exclusion_reason=catalytic_residue` 필터를 주면 422가 아니라 빈 목록이다.

### 골든 기록기는 M20 도구 대신 저장된 v1 집합을 넣는다 (M26)
- **증상**: `golden_science_m24.py`·`prototype_golden_call_keys.py`는 M20 도구로 후보 집합을 만들었으므로 M20이 v2가 되면 골든 바이트(v1 J6·`not_available`)가 바뀐다. 계획대로 저장된 v1 내용을 맨 `store.put`으로 넣으면 M20 `Run.call`의 이벤트 5개가 1개가 되어 `golden_science_m24.json`의 절대 이벤트 순번 네 곳이 −4 달라졌다.
- **대응**(M20 v2 전에 커밋, `5672200`): `golden_science_m24.py`는 M20 `Run.call` 봉투를 그대로 두고 그 run 레지스트리의 구현만 `backend/tests/fixtures/reaction/t1/`의 v1 내용을 `store.put`하게 바꿨다(인자·구조 handle 대조, handle 단언). `prototype_golden_call_keys.py`는 순번이 없어 맨 `store.put`이다. 옛 `--check` 둘이 바꾸기 전후 exit 0, 골든 JSON 불변(`docs/qa/m26-reaction-20261008/v1-baseline/`). `golden_call_keys.json`은 M20 v2 뒤 다시 기록했고 차이는 세 값뿐이다(`hashed_files`의 `mutation_candidates.py` SHA, M21 의존 pin, M21 호출 키. 모델·도킹 handle은 그대로).
- `backend/tests/fixtures/sequence_ga/build_sequence_ga_fixtures.py --check`는 이제 설계상 실패한다(도구가 v2를 만든다). `--write`로 다시 쓰면 M23 테스트가 쓰는 v1 fixture를 덮으므로 하지 않는다.

### `mutation_candidates.py` 변경으로 업그레이드 전 큐 작업과 진행 중 M25 단백질 루프가 막힌다 (M26)
- **원인**: `mutation_candidates.py`의 SHA-256이 M21 `DEPENDENCIES`로 M21·M23 호출 키와 시작 때 pin 확인에 들어간다(M26 해시 파일 변경은 이것 하나). 그래서 M26 전 M21 변이 모델·M23 서열 GA 저장 결과의 자동 재사용이 끝났다(사용자 수용, 저장 결과·읽기는 그대로).
- **업그레이드 전에 큐에 있던 M21·M23 작업**: 시작 때 과금 전 412 `worker_version_invalid`로 거절되고 `failed`가 아니라 `claimed`로 남는다(예약 0, 착수 확인 `preflight-local.md` (d)). 그 작업을 취소하고 다시 제출한다(새 호출 키 = 새 작업).
- **진행 중이던 M25 단백질 루프**: 계산 단계(모델 단계와 이미 만든 모델의 도킹 단계 모두)가 `jev_loop_store.step_capability`의 pin 비교로 412 `capability_unavailable`(`capability.reason_code: "missing_configuration"`)이고 아무것도 쓰지 않는다. 막힘은 계산 단추를 누를 때 응답으로만 보이고 루프 읽기 바이트는 같다. 끝난 루프는 끝 이벤트 시점으로 동결이라 보이는 값이 바뀌지 않고, 리간드 루프는 M18 pin만 쓰므로 영향이 없다. 그 루프를 끝내고 새 루프를 만들어 이어 간다(새 루프 풀은 v1·v2 집합을 모두 받음).

### git worktree에서 `-I`로 띄운 작업 모듈은 주 체크아웃의 `mw`를 import한다 (M26)
- **원인**: M21·M23 작업 모듈과 guardian은 `<python> -I <작업 모듈>`로 뜬다. `-I`는 `PYTHONPATH`를 무시하므로 worktree에서 `PYTHONPATH=<worktree>/backend`를 줘도 자식 프로세스의 `mw`는 editable 설치가 가리키는 주 체크아웃의 `backend/mw`에서 온다(2026-10-09 확인: `PYTHONPATH=<worktree>/backend .venv/bin/python -I -c 'import mw'`가 주 체크아웃 경로를 출력, `-I` 없이는 worktree 경로). 그래서 worktree에서 고친 `mw` 코드(예: `mutation_candidates.py`)는 작업 모듈 자식 프로세스에 반영되지 않고, 서버 프로세스와 자식이 서로 다른 `mw`를 쓴다.
- **대응**: 작업 모듈 자식 프로세스를 띄우는 시험·QA·실서버 가져오기는 주 체크아웃의 작업 브랜치에서 돌린다(위 "git worktree에서 테스트가 주 체크아웃의 코드를 돌린다"와 같은 원인의 다른 경로). 가져오기 명령 시험은 반대로 `-I`와 `mw`·네트워크 차단으로 그 스크립트가 `mw` 없이 도는지 확인한다.

### 옛 오프스크린 하네스·실행기의 v1 기대가 v2 집합에서 깨졌다 (M26)
- **증상**: 도구로 새로 만드는 집합이 v2 `not_checked`가 되자 v1 값을 단언하던 하네스가 실패했다: `mutation-flow.cjs`의 `main` 모드(`catalytic == "not_available"`), `jev-flow.cjs`(J6 고정 기대), 최종 회귀 사슬의 `sequence-ga-flow.cjs` C02(도구로 만든 작은 집합의 제외 사유를 v1 fixture의 여섯 키로 기대).
- **대응**: 제품 결함이 아니라 하네스 기대였다. `mutation-flow.cjs` `main`과 `jev-flow.cjs`는 도구가 만든 v2 집합이 보이는 값(`not_checked`, 셋째 문장 변형, 와이어에서 고른 J6n·J6c)을 기대하도록 고쳤고, `sequence-ga-flow.cjs`는 저장된 v1 fixture와의 비교는 두고 v2 추가분(`mw.mutation_candidates/v2`, 촉매 검사 `not_checked`, `catalytic_residue` 0)만 따로 단언하게 고친 뒤 M23 실행기를 단독으로 다시 돌렸다(35/35, 실패한 사슬 증거는 그대로 둠, `regression-chain.txt`). 도구가 만드는 집합의 모양을 바꾸는 단계는 M20·M21·M23·M24·M25 하네스의 기대를 함께 확인한다.
- M13–M25 실행기는 `MW_REACTION_REFERENCE_DIR`를 넘기지 않아(`m13.child_env` 허용 목록) 백엔드가 기본 폴더 `.deps/reaction_reference`를 읽는다. 회귀 동안 그 폴더를 없는 채로 둔다(2026-10-09 회귀 사슬, `regression-chain.txt`).

### 제3자 참조 원문과 실제 응답 조각은 저장소·증거에 넣지 않는다 (M26)
- M-CSA 역할 문구·UniProt 설명·Rhea 반응식은 CC BY 4.0 원문이다. 실제 공개 응답 조각은 커밋하지 않고 형식 시험은 합성 fixture(`backend/tests/fixtures/reaction/`, 출처 파일 `SYNTHETIC-PROVENANCE-*.md`)로 한다. 착수 확인의 원본 응답과 분석 스크립트는 저장소 밖에만 두었고, 가져오기 기록(`import1.md`·`import2.md`)은 숫자·해시·상태만 적는다.
- 수락 증거 내보내기는 보고서 다운로드(Markdown·JSON)와 실패한 단계의 화면 HTML(`*-failure.panel.html`)을 경로·크기·SHA-256으로만 남긴다(`scripts/m26_offscreen_acceptance.py` `held_downloads`). 처음에는 공용 내보내기가 모든 텍스트 산출물을 증거 폴더에 써서 예비 real 단계의 보고서 다운로드가 증거 커밋에 들어갔다. 실행기를 해시만 남기게 고치고 그 다운로드를 지웠으며 역사에서도 뺐다(아래 "증거 장부의 커밋 해시는 역사 정리 전 값이다"). 독립 코드 검토 뒤에는 실패 화면 HTML도 막고 하네스의 보고서 목록 단계·탭 서명이 글자 대신 길이 + SHA-256을 돌려주게 했다(소스 고정 `3fcac53`에 포함).

### 가져오기 명령의 알려진 한계 (M26)
- 요청 전체 제한 시간(120초)은 64 KiB 읽기 사이에서만 확인하므로 한 번의 읽기는 소켓 제한 시간 안에서 길어질 수 있다. 전송이 `ssl` 기본 문맥이라 `SSL_CERT_FILE`·`SSL_CERT_DIR`가 신뢰 CA를 바꿀 수 있다(호스트·스킴은 못 바꿈). 설치 중 프로세스가 죽으면 `sets/.staging-*`·`.active.json.*.tmp`가 남고 서버는 무시하며 명령은 청소하지 않는다. `--reference-dir`가 포인터 없는 M15 폴더면 그 폴더에 설치한다(포인터 스키마만 검사함). 응답 없음(전송 오류)은 다시 시도하지 않고 429·5xx만 최대 2회 다시 시도한다.
- 명세는 재현 비교를 수락 실행기가 한다고 적었지만 실제로는 가져오기 스크립트의 라이브러리 함수 `compare_manifests`를 직접 불러 두 매니페스트를 비교했다(독립 증거 검토가 같은 결과를 다시 계산함, `import2.md` 3절).

### Stop 훅 나머지 그룹의 여유는 약 63초다 (M26)
- M26 백엔드 테스트는 모두 이름 없는 나머지 그룹에 들어갔다. 소스 고정 `3fcac53`에서 나머지 그룹 단독 3,553개 416.8초(제한 480초)였다. 다음에 테스트를 더하면 그룹을 나누고 `scripts/test_codex_hooks.py`의 그룹 수 기대(`CHECKS` 17)를 함께 고친다. 실행기 단위 테스트 두 파일은 `SCRIPT_TESTS`에 손으로 넣었다.
- 그룹을 동시에 돌릴 때 부하로 흔들리는 프로세스 시험 둘(`test_pocket_jobs.py::test_running_engine_is_stopped_with_its_process_group[output_files]`, `test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`)이 최종 게이트에서 실패했고 단독 재실행에서 7 passed였다. 독립 증거 검토의 재실행도 단독 7 passed, 다른 Stop 훅 pytest와 겹치면 `[qvina-worker]` 변형이 다시 실패했다(`gate.txt` 보충). 실패하면 코드 문제로 단정하지 말고 그 시험만 단독으로 다시 돌려 기록한다.

### 증거 장부의 커밋 해시는 역사 정리 전 값이다 (M26)
- 실제 외부 자료 보고서 두 개가 든 예비 증거 커밋을 로컬 작업 브랜치(어디에도 올리지 않음)에서 `git filter-branch`로 빼면서 브랜치 끝 9개 커밋의 해시가 바뀌었다. 증거 안의 `gitHead`·고정 해시는 정리 전 값이다: `dac2755` = 지금 `06679e4`, 소스 고정 `1735338` = 지금 `3fcac53`. 트리는 전후 같다(트리 해시 `5f0c5c43…`). 대응표는 `docs/tracking/m26-acceptance.md`에도 있다.

### 실제 kbase `dist/`의 모양과 실데이터에 없는 값 (M27)
- 착수 확인(`docs/qa/m27-precedents-20261010/preflight.md` (a))에서 실제 `dist/`(HEAD `77354f9`, dist 커밋 `43a935e`)는 명세 형식을 그대로 통과했다: 전례 레코드의 최상위 키 집합은 두 파일 모두 한 종류이고 정확히 21개, 모든 레코드 `review_status: "unreviewed"`, `move_id` 1,776개 유일, 레코드 해시 재계산 891·885·555 일치. 명세 필수 목록 밖의 중첩 키(`source.parser`, `extraction.chunks`·`dropped_effects`·`notes`, 선택 키 `target.resolution_evidence`)는 보존 대상이고, 참조 레코드는 필수 10개 + 8개 키(18개)다.
- **표적 미해석 396건**: `moves` 193 + `moves_flagged` 203이 `target.uniprot` null이다(해석 근거 `unmapped` 272·`absent` 122·`ambiguous` 2, 서로 다른 이름은 문자열 34개 + null). 어떤 체인에도 연결하지 않고 UP5와 이름별 표로만 알린다. 해석된 `moves` 698건 중 75건은 추정 근거(`name_token` 38·`pubmed_title` 20·`alias` 14·`notation` 3)라 연결하되 근거를 보인다.
- 그 밖의 실측: 측정 변화 3,832개 중 `off_target` 888개(약 23%), `fold_change` null 1,904개, 관찰 인용 `quote_truncated` 136건(`moves` 83 + `moves_flagged` 53)과 교환 인용 `quote_truncated` 27건(8 + 19)은 따로 센다(합치면 163). 표적별 `moves`/`moves_flagged`: EGFR `P00533` 76/66, BTK `Q06187` 70/97, CDK2 `P24941` 32/24, Aurora A `O14965` 0/0(참조 있음). `moves`에는 없고 `moves_flagged`에만 있는 표적이 17개(모두 참조 있음)라 `none_in_included_files` + UP2(N > 0)가 실제로 나온다.
- **실데이터에 없는 닫힌 값**: 25단어 초과 인용(그래서 `quotes_within_limit` 거짓), `direction_basis` `none`, 위치 `kind` `figure`, `structure_links.basis` `sole_candidate`, `resolution_basis` `klifs_gene_name`, 체인 상태 `multiple_accessions`(이번 QA 구조로는 만들 수 없었다. M15 SIFTS 스냅샷에는 융합 체인이 있지만 저장소에 그 구조가 없고 내려받기 한도 밖이다). 닫힌 집합은 명세 그대로 두고 합성 fixture(`backend/tests/fixtures/precedent/`, 출처 `SYNTHETIC-PROVENANCE-*.md`)로만 시험한다. 실제 레코드·서지 조각은 fixture로 커밋하지 않는다.

### `checks.duplicate` 실패는 전례 중복이 아니다 (M27)
- **증상**: `moves`(통과 파일처럼 보이는 이름)에도 `duplicate` 검사 실패가 61건 있다(`moves_flagged` 129건). 이름만 보면 "같은 전례가 두 번 있다"로 읽힌다.
- **원인**: 이 kbase 검사는 한 전례 안 측정 변화 둘이 서로 충돌한다는 뜻이다. `move_id`는 두 파일을 합쳐 모두 유일하다.
- **대응**: 검사 이름·상태를 kbase 원문 그대로 보이고("kbase 기계 검사") 해석 문장을 붙이지 않는다. 파일 이름 `moves`·`moves_flagged`를 "통과/실패"라 부르지 않는다(KP3).

### 사본에서 뺀 두 경로와 원본 `content_hash` (M27)
- 결과의 전례 사본은 `source.parser`와 `checks.cross_parser_numbers.measurements` 두 경로만 뺀 것이다(`kbase_record_minus_2_paths@1`). `content_hash`는 원본 전체 레코드의 해시를 그대로 두므로 **사본에서 다시 계산하면 맞지 않는다**. 이것은 변조가 아니다. 무결성 확인(`hash_verified`)은 도구가 호출 때 세트 바이트의 원본 레코드로 한다(불일치면 412 `snapshot_invalid`, 저장 안 함).
- 읽기·보고서·화면이 사본으로 해시를 다시 확인하려 하면 안 된다. 화면 상세는 "해시는 원본 레코드의 것" 안내를 붙이고, "그 밖의 kbase 필드" 블록은 뺀 두 경로를 나열하지 않는다. `validated_result`는 사본에 두 경로가 없는지와 `integrity`가 사본에서 다시 계산한 단어 수·쪽 검사와 같은지를 본다.

### 서로 다른 accession 두 체인은 1 MiB를 넘을 수 있다 (M27)
- **증상**: 단일 표적 결과는 최악(BTK `moves_flagged` 포함)도 상한 안이지만(착수 확인 시제품 측정 855,798 B, 제품 도구로 잰 값은 수락 증거의 855,943 B), 서로 다른 accession 두 체인(실데이터 구조로는 만들 수 없어 1FIN 번호 대응에 `P00533`·`Q06187`을 준 합성 변형)에 `moves_flagged`를 포함하면 1,605,026 B로 1 MiB를 넘는다(끄면 737,133 B).
- **대응**: 자르지 않고 429 `result_too_large`로 거절하고 아무것도 저장하지 않는다. 거절 상세 `size_without_flagged`·`target_sizes`가 표적별 단독 크기와 `include_flagged`를 끈 크기를 알려 화면이 "체인을 나누거나 포함을 끄라"고 안내한다(두 경우를 모두 계산하므로 거절 응답이 결과 만들기를 몇 번 더 한다).

### `move_id` 숫자 부분 정렬과 정수 변환 자릿수 제한 (M27)
- 전례 순서는 `move_id` 숫자 부분(정수) 오름차순이고 동점(`MOVE-0001`·`MOVE-00001`처럼 앞자리 0만 다름)은 `move_id` 문자열 오름차순이다(`kinase_precedents.move_key`). 문자열 정렬만 쓰면 `MOVE-10000`이 `MOVE-9999` 앞에 온다.
- **증상(T9 검토 지적)**: 숫자 부분이 파이썬의 정수 문자열 변환 제한(기본 4,300자리)을 넘는 `move_id`는 정규식(`MOVE-[0-9]{4,}`)을 통과해 가져오기가 받았고 서버 정렬에서 `ValueError` → 500이었다.
- **대응**: `validate_move`가 숫자 부분을 정수로 읽지 못하면 형식 오류로 거절한다(가져오기와 서버가 같은 함수). 읽기 질의의 `limit`·`offset`과 서지 `year`도 같은 제한을 넘으면 422이거나 "정수 아님"(늘 끝)으로 다룬다.

### 서지 행 모양이 어긋나면 "서지 없음"이다 (M27)
- 서지 파일의 `id`는 숫자 문자열이고 유일해야 하며 아니면 가져오기를 거절한다. 그러나 `status`가 `ok`가 아니거나 `data.pmid`가 `id`와 다르거나 `title`·`journal`·`year`·`doi`·`pmc` 중 하나가 없거나 문자열|null이 아닌 행은 거절하지 않고 그 PMID를 "서지 없음"(결과의 `bibliography[pmid] = null`)으로 둔다(T9 검토에서 보류로 기록한 선택). 스냅샷이 덮지 않는 PMID와 같은 취급이며 오류·0이 아니다. 실데이터 최신 스냅샷 252행은 모두 이 모양을 만족하고 전례 PMID 167개를 모두 덮는다.
- 정렬 `year`는 서지 `year` 문자열을 정수로 읽을 수 있을 때만 값이고 서지 없음·정수 아님은 `order`와 무관하게 늘 끝이다.

### 가져오기 명령의 git 호출과 `--from`은 저장소 루트 (M27)
- 가져오기 명령은 읽기 전용 git 셋만 부른다. 상속한 `GIT_*` 환경을 지우고(`GIT_DIR` 등으로 다른 저장소를 읽지 않게) `GIT_CEILING_DIRECTORIES=<kbase 상위>`로 탐색을 kbase 폴더에서 멈추며, `-c core.fsmonitor=false`(설정된 fsmonitor 명령을 실행하지 않음)와 `-c protocol.allow=never`(부분 클론의 누락 객체 지연 가져오기가 원격에 닿지 않고 실패)를 준다(T9 검토 권고 반영). `status`는 `--untracked-files=normal`로 추적되지 않는 파일까지 `dirty`에 넣는다.
- 그래서 `--from`은 `.git`이 있는 kbase 저장소 루트여야 한다. 그 폴더 자체에 `.git`이 없으면(git 없는 복사본 등) `dist/` 검사를 통과해도 마지막 git 단계에서 `git` 거절이다(저장소의 하위 폴더는 보통 `dist/manifest.json`이 없어 먼저 거절된다). `--from` 상대 경로는 현재 작업 폴더 기준, `--dest` 상대 경로는 저장소 루트 기준이다. git worktree에서는 주 체크아웃 기준 `../kbase_kinase`가 맞지 않으므로 절대 경로를 준다.
- `dest`의 `active.json`이 다른 가족(M15 `reference_active`, M26 `reaction_active`)의 포인터면 거절한다(폴더를 잘못 준 경우). 가장 늦은 날짜의 pubmed 스냅샷이 둘이면 고르지 않고 거절한다. kbase 매니페스트의 `sha256:<hex>` 문자열은 소문자까지 정확히 같아야 한다.

### 1FIN B·D를 번호 대응에 넣으면 호출 전체가 실패한다 (M27)
- **증상**: 1FIN의 네 체인(A·C CDK2, B·D cyclin A)을 모두 `map_residue_numbering`에 넣으면 422 `no_usable_method`(`chain_auth: B`)로 호출 전체가 실패하고 객체가 생기지 않는다. B에 자기 SIFTS accession(`P20248`)을 주면 422 `accession_not_in_uniprot_snapshot`이다(M15 UniProt 스냅샷은 kinase만).
- **원인**: M15 SIFTS 스냅샷의 1FIN 잔기 행은 A·C뿐이라 B·D에는 쓸 방법이 없다.
- **대응**: 실데이터 QA는 번호 대응 체인을 A·C만 넣는다(한 표적 `P24941`에 체인 행 둘). 실데이터로 `no_mapped_residues`를 만드는 길은 B에 맞지 않는 kinase accession(`P24941`)을 직접 준 입력 실수뿐이라(mapped 0/260) 정상 사례로 쓰지 않고, `no_mapped_residues`·`multiple_accessions`는 합성 번호 대응 객체로 시험한다.

### `not_in_kbase_references`는 원리상 실데이터로도 도달한다 (M27)
- 명세는 "실데이터로 도달 불가"라고 적었지만 착수 확인 (d)에서 바로잡았다. M15 UniProt `ok` kinase 541개는 모두 kbase 참조에 있다. 그러나 M15는 SIFTS 체인의 단일 accession이 UniProt 스냅샷에 없으면 SIFTS만 쓰는 계획을 세우고 그 행을 `mapped`로 만든다. 활성 SIFTS 스냅샷에 그런 체인이 둘 있다: `7Z87` A → `P78527`, `8H7G` A → `Q15393`. 두 accession은 kbase 참조에 없으므로 그 구조를 올리고 PDB ID를 주면 체인이 `linked`가 되고 표적 상태가 `not_in_kbase_references`가 된다.
- 두 구조는 저장소에 없고 이번 단계의 요청 한도(구조 2개) 밖이라 합성으로만 시험했다. 상태 정의("kbase가 이 표적을 모름, 전례 없음과 다름")는 이 경우에도 맞으므로 코드·상수는 그대로다. 융합(여러 accession) SIFTS 체인 5개(`4WTV` A·`4YC4` A·`5EZV` A·`5JGA` A·`6DC0` A)는 `multiple_accessions`가 될 체인이다.

### 번호 대응 목록은 탭에 들어올 때만 다시 읽는다 (M27)
- "키나아제 전례" 영역은 탭 진입 때 스냅샷 상태·번호 대응 목록·결과 목록을 GET으로 읽는다. 같은 탭 방문 중에 번호 대응 영역에서 새 대응을 만들어도 전례 영역의 선택지는 자동으로 갱신되지 않고 다음 탭 진입 때 보인다(M26 반응 지식 영역과 같은 동작, T9 검토 수용). 체인 미리 상태(`chainPreviews`)는 번호 대응 행을 다 읽은 뒤에만 정확하므로 그 전에는 "다 읽은 뒤 미리 보입니다"를 보이고, 연결 여부는 늘 서버가 결과로 정한다.

### 상세 측정값 칸은 null·빈 qualifier·unit을 감춘다 (M27, 알려진 표시 한계)
- 측정 변화 표의 before/after 칸은 `value`가 null이면 "— (kbase 기록에 값 없음)"이고, `value`가 있으면 `qualifier`·`value`·`unit` 중 null·빈 문자열을 빼고 잇는다. 이 세 경로는 칸이 "보인" 경로로 치므로 "그 밖의 kbase 필드" 블록에도 나오지 않는다. 0으로 보이지는 않지만 null `qualifier`·빈 `unit`이 있었다는 사실은 화면에서 보이지 않는다(T11 증거 검토 기록). 값 자체는 결과 객체·JSON 읽기에 그대로 있다.

### 회귀 격리: 옛 실행기는 기본 참조 폴더를 읽는다 (M27)
- M13–M26 수락 실행기의 백엔드 환경은 `m13.child_env` 허용 목록 + 실행기가 정한 변수뿐이고 `MW_PRECEDENT_REFERENCE_DIR`를 넘기지 않으므로, 옛 실행기의 백엔드는 코드 루트 기본 폴더 `.deps/precedent_reference`를 읽는다(M26의 `.deps/reaction_reference`와 같은 문제).
- **대응(T1 결정)**: 실행기는 고치지 않고 회귀 동안 `.deps/precedent_reference`와 `.deps/reaction_reference`를 없는 채로 둔다. 설치되지 않은 상태의 새 영역은 숫자·컨트롤 없이 이유와 명령만 보이므로 옛 하네스가 다루는 컨트롤과 겹치지 않는다. 2026-10-10 회귀 사슬은 두 폴더가 시작 전·후 모두 없는 상태로 돌았다(`regression-chain.txt`). 새 영역은 "사용할 수 없음" 상태에 `section.mw-unavailable`을 쓰지 않는다(`tabs-flow.cjs`가 지식 탭의 그 요소 0개를 단언).

### 수락 실행기의 실제 문구 유출 검사와 `/tmp` 금지 (M27)
- 실제 kbase 문구가 커밋 증거에 새지 않게 실행기는 설치된 세트에서 관찰 문장·인용·교환 문장·인용·변형 설명·측정 조건(`assay`·`assay_context`·`comparability_reason`)·서지 제목·저널·참조 필드(`gene`·`klifs_name`·`group`·`family`·`coverage`)를 메모리에만 모은다. 공백을 접고 대소문자를 무시한 뒤(정규화) 24자 이상인 문자열에 대해 40자 조각 하나라도, 또는 24–39자 문자열 전체가 커밋 후보 텍스트에 있으면 그 파일을 Git 제외 artifacts 폴더로 보낸다. JSON `\uXXXX`·Markdown·HTML 이스케이프를 풀어서도 찾는다. 식별자·해시·닫힌 코드는 모으지 않으므로 증거에 남는다. 하네스는 real 단계 기록에 24자 미만 문자열만 남긴다(`realSafe`). 2026-10-10 수락 증거는 7,479개 문자열로 검사해 0개 파일이었다.
- 이 조각·정규화·이스케이프 풀기 방식과 양성·음성 대조 시험은 T9 검토 권고로 강화한 것이다(`a0cc1b8`). 보고서 다운로드(Markdown·JSON)와 실패 화면 HTML은 처음부터 증거에 경로·크기·SHA-256만 남긴다(M26 교훈). 실행기 `--root`는 새 폴더여야 하고 `/tmp` 아래면 거절한다(저장소 `runs/` 아래 같은 격리 폴더를 쓴다).

### Stop 훅 나머지 그룹이 다시 480초에 닿아 그룹 둘을 더했다 (M27)
- **증상**: M27 전 나머지 그룹 단독 3,554개 408.77초(여유 약 71초)에 M27 테스트(백엔드 557개 + 스크립트 152개)가 더해지면 한도를 넘는다(착수 확인 (e)). M27 백엔드 일곱 파일을 이름 있는 그룹으로 나눈 첫 고정 후보(`7e33951`)에서도 모든 그룹을 동시에 시작하면 나머지 그룹이 3,706개 476초(단독 423.9초)로 480초에 거의 닿았다.
- **대응**: 가장 무거운 남은 두 파일 `test_analysis_workflows.py`·`test_jev_loop_reports.py`(129개, 나머지 그룹과 둘만 함께 돌렸을 때 197초, 열여덟 그룹 전부 함께는 231.6초)를 또 한 그룹으로 나눴다(`b414728`, `PYTEST_GROUPS` 열일곱 + 나머지 = 열여덟 그룹, `CHECKS` 19, `scripts/test_codex_hooks.py`의 기대 19). 고정 `b414728` 게이트에서 열여덟 그룹을 동시에 시작하면 나머지 그룹 3,577개 323.2초, 전체 357.5초, 합계 6,037 passed였다(`gate.txt`). 새 스크립트 테스트 둘은 `SCRIPT_TESTS`에 손으로 넣었다.
- 서열 GA SIGTERM 프로세스 시험(`test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`)은 훅이 다른 작업과 겹치면 흔들리는 알려진 현상이 이 단계에서도 재현됐고 단독 3 passed 143.8초였다. 고정 게이트에서는 통과했다. 실패하면 그 시험만 단독으로 다시 돌려 기록한다.

### 하네스 문구 검사는 "그 밖의 kbase 필드" 항목을 뺀다 (M27)
- **원인**: 금지어 목록에 `\beffects?\b`·`효과`가 있는데, 상세의 "그 밖의 kbase 필드" 블록은 kbase 경로를 그대로 보이므로(`effects[0].evidence` 같은 경로 이름) 그대로 검사하면 kbase 필드 이름을 ProtView의 효과 주장으로 잡는다. 표 머리말 "측정 변화(kbase 추출 effects)"와 버전 키 `effect_rules_version`도 같은 이유로 걸린다.
- **대응**: `kinase-precedents-flow.cjs`는 문구 검사 전에 고정 문장, 그 머리말·버전 키(Markdown 이스케이프 형태 포함), 서버가 준 저장 문자열 전부, 그리고 "그 밖의 kbase 필드" 블록의 항목(경로와 JSON 값)을 지운다. 블록의 제목·안내 문장은 그대로 검사한다. 금지어는 ProtView가 쓴 템플릿 글자에만 건다(보고서 금지어 검사와 같은 원칙).

### 부하에서 흔들리던 시험은 단계를 붙잡은 뒤 신호를 보낸다 (M28)
- **증상**: Stop 훅처럼 그룹을 동시에 돌릴 때 한 번씩 실패하고 따로 돌리면 통과하던 시험 넷: 서열 GA SIGTERM 시험 `test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]`가 작업 폴더에 `0.model.cif` 등이 더 있는 채 실패, 포켓 `test_running_engine_is_stopped_with_its_process_group[output_files]`가 출력 상한 실패 대신 정상 완료, `test_a_failed_reference_row_ends_the_run_before_any_individual[…]`가 psutil `proc_cmdline`의 `SystemError`, M24 `test_jev_reports.py`의 `'0.1234' not in dumped` 실패(위 M25·M26 항목).
- **원인(모두 시험 쪽, `docs/qa/m28-final-20261011/preflight.md` (f))**: (1) 시험이 단계 프로세스를 "본 뒤" 신호·결함을 넣었는데, 부하 중에는 시스템 전체 프로세스를 한 번 훑는 데 약 1초가 걸려 짧은 단계(qvina2 약 0.8초, 이 입력의 fpocket 약 1.7초)가 그 사이에 끝났다. guardian의 출력 상한 표본은 작업 프로세스가 살아 있는 동안에만 뜬다. (2) psutil 7.2.2 `process_iter(["name", "cmdline"])`의 미리 읽기는 생성기 안, 곧 시험의 `try` 밖에서 돌아 읽는 순간 끝난 아무 프로세스의 `SystemError`가 그대로 새어 나왔다(그 시험은 `cmdline`을 쓰지도 않았다). 제품 `backend/mw`에는 명령줄 읽기가 없다. (3) 부분 문자열 검사가 manifest 스냅숏의 `time_utc`·벽시계 부동소수 숫자와 우연히 겹쳤다.
- **대응(M28 T2, 시험만 고침, 제품 코드·해시 파일 변경 없음)**: 단계 직전에 쓰이는 표지 파일(서열 GA `individuals/0.started`·`ligand.pdbqt`, 포켓 `engine.stderr`)을 본 뒤 작업 프로세스 그룹에 SIGSTOP을 보내고, 첫 멈춤이 닿는 동안 fork된 자식을 잡으려고 한 번 더 보낸 상태에서 단계 프로세스를 찾아 멈춰 둔 다음에만 신호·결함을 넣는다(qvina2는 CPU를 50 ms 쓴 뒤 붙잡고, 포켓 시험은 fpocket만 멈춘 채 guardian·작업 프로세스를 다시 돌린다). 중간에 실패하면 그룹에 SIGCONT를 보내 멈춘 프로세스를 남기지 않는다. `SystemError`는 `psutil.Error`와 같이 "이미 없는 프로세스"로 다루고 쓰지 않는 미리 읽기를 뺐다. 확률 표지는 앞뒤가 숫자·소수점이 아닌 온전한 숫자로만 찾는다(새는 값을 여전히 잡는지 보는 시험을 더함).
- 같은 모양의 부분 문자열 검사(`str(value) not in dumped`)가 `backend/tests/test_jev_api.py`와 `test_jev_loop_reports.py`에는 남아 있다(T2 범위 밖). 이런 시험이 실패하면 코드 문제로 단정하지 말고 그 시험만 단독으로 다시 돌려 진단 기록으로 남긴다.

### M20 보고서 형식 @2는 인용할 때만 쓰고, @1 경로는 출처표를 찾지 않는다 (M28)
- **원인**: 저장된 M20 보고서는 다시 열 때 `render_version`·manifest 키 집합·Markdown 바이트를 다시 만들어 비교하므로, 출처표를 렌더에 그냥 더하면 이미 저장된 보고서가 모두 `report_evidence_invalid`가 된다. "새 보고서는 모두 @2"로 해도 인용 없는 보고서의 바이트가 바뀌어 수정 금지 기준선(`docs/qa/m26-reaction-20261008/v1-baseline/baseline/`)과 비교하는 `backend/tests/test_mutation_api.py::test_stored_v1_sets_keep_the_t1_baseline_reads_validation_and_report_bytes`가 깨진다(착수 확인 (g) ★A).
- **대응(M28 T3)**: 형식 버전을 둘로 두고(`MANIFEST_KEYS_BY_VERSION`) 새 보고서는 참조값을 인용할 때만 `@2`다. 다시 열기는 저장된 `render_version`으로 갈라 `@1`은 `@1` 규칙만 쓰고 출처표 함수(`reference_snapshot_sets`)를 부르지 않는다. 참조값을 인용한 `@1` 보고서 두 개가 든 run 로그(`backend/tests/fixtures/mutation_report_v1/`, T3 전 코드로 기록)로 같은 바이트를 확인하고, 그 경로에서 M15 검증을 부르면 실패하도록 시험한다. 반응 표는 반응 지식 결과를 주었다는 사실이 아니라 M-CSA 항목 ID 주장이 있을 때만 싣는다(덮인 체인이 없으면 `@1` 그대로).
- **순환 import**: `reaction_knowledge_reports.py`가 불러올 때 `mutation_reports`(공용 한도·금지어)를 import하므로, `mutation_reports.py`는 반응 표 문구(`SOURCE_LABELS`·`LICENSE_LABEL`·`PROCESSED_LABEL`)를 쓰는 `_reference_set_lines` 함수 안에서만 `reaction_knowledge_reports`를 import한다. 모듈 맨 위로 올리면 순환이 된다.
- **더 엄격해진 만들기**: `@2`를 만들거나 다시 열 때 인용한 번호 대응을 M15 보고서 검증(`numbering_reports.validated_numbering_map`)으로 확인하고 주석의 세트 해시가 그 번호 대응의 세트와 같아야 한다(`mutation_reference_set_mismatch`). `@1`에는 없던 검사다.
- 새 하위 제목·표 머리글은 템플릿 글자이고 고정 문장이 아니다(슬롯을 비운 금지어 검사 대상). `mutation_reports.py`는 호출 키 해시 집합 밖이라 바꿔도 M21·M23 재사용에 영향이 없다.

### 보고서 목록 라우트는 모든 보고서를 다시 연다 (M28, 알려진 한계)
- **증상**: M28 T7 개발 중 분기 B run에서 지식·보고서 탭 보고서 목록(`GET /runs/{rid}/reports`)이 보고서 9건에 처음 약 15초 걸렸고 GA 보고서는 한 건에 4–5초였다(구현 중 측정, 증거 파일 없음). 보고서가 더 쌓인 run에서는 Next.js `/api` 프록시의 30초 한도(위 "오래 걸리는 작업 시작이 화면에서 실패로 보인다")에 닿을 수 있다.
- **원인**: 목록 라우트가 이벤트에 있는 모든 보고서를 종류별 다시 열기 검증(`_saved_any_report`)으로 연 뒤에야 목록을 돌려준다. 보고서 하나라도 검증에 실패하면 목록 전체가 422 `report_evidence_invalid`다.
- **대응**: 제품은 바꾸지 않았다(M28은 새 기능 없음). 종단 수락은 보고서마다 `GET /runs/{rid}/reports/selected`로 열림을 판정하고 목록 라우트를 열림 판정에 쓰지 않는다(X1, 역추적 감사).

### 점검 보고서와 `interface_sasa` 보고서는 다시 열 때 다시 만들지 않는다 (M28)
- 점검 보고서(`report_manifest@1`, `reports.saved_report`)는 다시 열 때 종류·상태·Markdown 연결·`report_created` 이벤트만 보고 주장도 Markdown도 다시 만들지 않는다. `interface_sasa` 방법 보고서(`method_reports.saved_method_report`)는 결과 객체와 필드·주장을 대조하지만 Markdown은 다시 렌더하지 않는다.
- 그래서 "다시 열기 200 = 제품이 값을 다시 확인함"은 이 두 종류에 그대로 성립하지 않는다. M28 역추적 감사는 두 종류를 `partialProductRecheck`로 표시하고, A2(점검 보고서)·A3(SASA 보고서) 사례가 입력 파일에서 독립으로 계산한 기대값으로 값을 대조한다.

### 물 정책 기본값이 두 곳에서 다르다 (M28 확인)
- 도구 명세(`config/tools.yaml`의 `prepare_structure`)와 `docs/business-rules.md` "구조 불러오기와 전처리"의 기본값은 `keep_all`이고, 화면(`frontend/app/page.tsx`의 물 선택 기본 "제거")과 고정 파이프라인(`backend/mw/workflows.py`의 `InspectionRequest`, `config/pipelines/inspect_complex.yaml`의 `preparation_defaults`)의 기본값은 `strip_all`이다.
- 기대값을 계산하거나 "기본 정책"이라고 쓸 때 어느 기본값인지 밝힌다. M28 A1은 화면 기본값(`strip_all`)으로 클릭했고 1M17 기대 잔기·원자 수도 그 정책으로 셌다. 코드는 바꾸지 않았다.

### M7 사전 검사를 통과하는 로컬 공개 구조는 1UBQ뿐이다 (M28 착수 확인)
- 저장소의 공개 구조 8개를 물 정책 둘로 M7 사전 검사에 넣으면 1UBQ만 통과한다(중원자 602, 제외 58). 1M17·1S9I·1A4I는 `sequence_gap`, 1MQ4·1A30은 `heavy_template_mismatch`, 1HSG는 `missing_terminal_oxt`, 1FIN은 이유 코드 없는 `duplicate author chain identity`(`input_invalid`)다(`docs/qa/m28-final-20261011/preflight.md` (c), `m7-probe.txt`).
- 변이 구조 모델링(M21·M23·M25 단백질 루프)은 M7 사전 검사를 거치므로 로컬 공개 자료로는 1UBQ에서만 돈다. 그래서 M28 분기 C는 촉매 보호(C1)를 M-CSA 효소 1A30에서, 모델링·같은 조건 도킹 짝·서열 GA·단백질 루프(C2–C6)를 1UBQ에서 보이고 두 반쪽은 같은 구조에서 이어지지 않는다. 1UBQ에는 리간드가 없어 도킹에는 합성 표시 페놀 SDF를 쓴다.

### 종단 수락 실행기의 함정 (M28)
- **실제 live 단계는 분기 둘을 함께 돌린다**: `--phase live`에서 `--branches`가 b·c 둘이 아니면 거절한다(계획이 두 바퀴이고 보낸 바퀴가 완료되지 않으면 다음 바퀴를 보내지 않아야 하므로). 한 분기만은 연습(`--rehearse`)에서만 돌리고 그때 계획은 고른 분기의 바퀴만 센다. fixture 단계에서 일부 분기만 돌리면 돌기는 하지만 `acceptance`는 늘 거짓이다.
- **실호출 계수는 이벤트로 정한다**: 바퀴를 보냈는지는 하네스의 자기 보고가 아니라 분기 앞뒤의 `jev_science_dispatch_started` 이벤트 수로 정한다. 하네스가 죽거나 멈춰져 증거를 남기지 못해도 dispatch가 늘었으면 보낸 바퀴이고 완료 결과가 없으면 `product_failed`다(다음 바퀴는 보내지 않음). 대장 합계도 root의 runs 폴더 이벤트를 다시 세어 정한다.
- **X4 줄 예외 키는 세 방식이다**: `X4_EXCEPTIONS`의 키는 정규화한 줄의 SHA-256(`line`), 숫자를 `#`로 바꾼 줄의 SHA-256(`template`, 실행마다 숫자가 다른 줄), 첫 ": " 앞 머리의 SHA-256(`label`, 머리만 예외이고 나머지는 계속 검사)이다. 예외마다 이유가 있어야 하고(없으면 오류) 줄 종류·사례·출처 코드를 적는다. 요청 본문처럼 JSON인 줄은 건너뛰지 않고 문자열마다 검사한다.
- **`*.tabtext`·`*.held`는 커밋 증거에서 빠진다**: 실행기가 텍스트로 내보내는 확장자는 `.json`·`.jsonl`·`.log`·`.md`·`.txt`·`.html`뿐이라 하네스의 탭 글자(`texts/*.tabtext`, 지식 탭의 참조 원문이 들 수 있음)와 분기 A의 참조 오류 글자(`endtoend-a-real-errors.held`)는 `binary-artifacts.json`에 경로·크기·SHA-256만 남는다. 이 확장자를 텍스트 목록에 더하면 참조 원문이 커밋 증거에 들어간다.
- **연습은 키를 건드리지 않는다**: 연습은 키 존재 확인을 건너뛰고 증거 검색도 placeholder·키 모양만 찾으며 제품 키 해석기를 부르지 않는다(연습에서 해석기를 부르면 증거 내보내기가 실패로 기록된다). 제품 키 해석기는 연습이 아닌 단계에서 자식 프로세스로만 부르고 불리언과 파일 경로만 받는다: fixture 단계는 끝의 증거 키 검색(`key_scan`) 1회, 실제 live 단계는 키 존재 확인 1회 + 증거 키 검색 1회(대장 `checks.exportScan.productKeyResolverCalls` fixture 1·live 2·연습 0). 대장의 `external.product_key_resolver_calls`는 증거 내보내기 전에 적히므로 fixture 0·live 1이다.
- **기본 `--out`은 실행한 날짜 폴더다**: 기본값이 `docs/qa/m28-final-<실행한 날짜>/acceptance-<단계>`이므로 착수 날 폴더(`m28-final-20261011`)에 모으려면 `--out`을 준다.
- **분기 시험은 로컬 자료가 있어야 한다**: `scripts/test_m28_branch_a.py`·`test_m28_branch_c.py`는 `../kbase_kinase/dist`·`.deps/reaction_qa/import2`를 시험 파일이 있는 저장소 루트 기준으로 찾고 없으면 실패한다(skip 아님). git worktree에서는 실패하므로 주 체크아웃에서 돌린다.
- **기본 참조 폴더**: X6은 끝날 때 `.deps/precedent_reference`·`.deps/reaction_reference`가 없어야 통과다(실행 전부터 있었어도 실패). 실행기와 분기 모듈은 단계 격리 폴더에만 설치·복사한다.

### 작업 모듈·의존 파일을 고치면 이전 보완 작업이 재사용되지 않는다 (M29)
- **증상**: T13에서 작업 모듈 `jobs/structure_repair_worker.py`의 엔진 오류 메시지 길이 처리(T12 검토 A1, 300자, `43742f19`)를 고치자 그 전에 연습 root에서 만든 보완 작업은 같은 호출 키가 아니게 되었다. Stop 훅 실패 기록 8(2026-10-13)에서는 훅이 도는 동안 같은 파일이 고쳐져 `test_structure_repair_jobs.py`의 두 시험이 메서드 pin의 `worker_sha256` 불일치와 `job_id` 불일치로 실패했다(시험 준비의 `real` 픽스처는 옛 파일 해시로 작업을 만들고 시험 본문은 새 해시로 대조). 파일이 안정된 뒤 같은 두 시험은 2 passed(32.8초).
- **원인**: 호출 키와 작업 기록의 pin(`structure_repair_jobs.require_ready`)에 작업 모듈 SHA-256, `DEPENDENCIES` 다섯(`structure_repair.py`·`structure_repair_constants.py`·`jobs/openmm_worker.py`·`tools/openmm_method.py`·`mutation_model_constants.py`)의 SHA-256, 고정 방법 기록이 들어간다(M21과 같은 설계). `timeout_s`는 들어가지 않는다.
- **대응**: 제품 결함이 아니다. 이 여섯 파일 중 하나를 바꾸면 같은 전처리 구조의 보완은 새 작업(1단위)이 되고, 대기 중이던 보완 작업은 시작 때 예약 전에 412 `worker_version_invalid`로 막힌다(취소하고 다시 제출). 그래서 M29 수락은 소스 고정 뒤 새 `--root`로 돌렸다. `jobs/openmm_worker.py`·`tools/openmm_method.py`·`mutation_model_constants.py`는 다른 단계의 호출 키 해시 파일·`also_hashed_files`이므로 보완 작업은 이 셋을 import·해시만 하고 바꾸지 않는다.

### PDBFixer 호출: 틈은 `missingResidues`로 직접, MSE는 미리 바꾸고, 작업 모듈은 추가 원자만 돌려준다 (M29)
- **원인**: PDBFixer `findMissingResidues`는 서열을 저자 번호와 label 체인 id로 맞추므로 서버 분석이 미관측 잔기 목록에서 확정한 틈과 다를 수 있다(착수 확인 `docs/qa/m29-repair-20261013/preflight.md` (g)). PDBFixer의 표준 치환(MSE→MET)은 SD를 템플릿 위치에 새로 놓아 SE 좌표를 지키지 못한다.
- **대응**: `jobs/structure_repair_worker.py`(PDBFixer를 import하는 유일한 M29 모듈, 프로젝트 `.venv`)는 (1) MSE 잔기의 이름·원소만 PDBFixer에 넣기 전에 바꾸고(SE→SD, Se→S, 좌표 그대로) (2) M21과 같은 위상(체인 id `str(체인 순번)`, 잔기 id `str(전역 순번 + 1)`)을 `PDBxFile.writeFile(keepIds=True)` 텍스트로 `PDBFixer(pdbxfile=…, platform=CPU Threads=1)`에 넘기고 (3) `missingResidues`를 스테이징한 틈 목록으로 직접 설정한 뒤 `findMissingAtoms` → `addMissingAtoms(seed=1)`을 한다. 출력은 계획한 잔기 순서와 대조한다: 관측 원자는 이름·원소가 같고 1e-9 Å 안이어야 하고(아니면 `coordinates_changed`), 잔기 수·체인·이름이 계획과 다르면 `repair_identity_mismatch`이며, 나머지 원자만 `added_atoms`(`side_chain`·`oxt`·`gap_residue`)로 돌려준다.
- 관측 원자는 작업 프로세스에서 오지 않는다. 서버가 `structure_repair.build_repaired`로 전처리 구조에 새 원자를 끼워 넣고(MSE→MET 이름·원소·HETATM→ATOM, 입력 `calc_flag` 정리, 새 원자 `calc_flag = c`도 서버가 한다) `validated_repair`로 다시 검증한다. 시드는 상수 1이다(T1: 시드 2로 바꾸면 8VF6 새 원자 266개가 모두 바뀌고 최대 9.875 Å 움직임). PDBFixer에는 단백질만 넣으므로 물 정책에 따라 새 원자가 달라지지 않는다.

### 새 원자 좌표는 소수 넷째 자리다 — M21 PDBx 왕복과 `_graft` 1e-9 Å (M29)
- **증상**: T1에서 PDBFixer 원정밀도 새 원자를 넣은 보완 8VF6은 M7 사전 검사는 통과했지만 M21 작업이 0.5초 만에 `coordinates_changed`(`max_abs_shift_A` 4.566e-05, A/100/LYS)로 실패했다(`preflight.md` D1).
- **원인**: M21 작업 모듈(해시 파일 `openmm_mutation_worker.py`)이 단백질 위상을 `PDBxFile.writeFile`로 텍스트화할 때 좌표를 `%10.4f`로 쓰고, `_graft`가 변이 잔기 밖 좌표를 `GRAFT_TOLERANCE_A` 1e-9 Å로 대조한다. 위 M23 "여러 곳 변이를 M21 함수로 이어서 적용하면…"과 같은 원인이다.
- **대응(명세 정정, 사용자 승인 2026-10-13)**: 서버가 새 원자 좌표를 `NEW_ATOM_DECIMALS = 4`로 반올림해 구조와 보완 기록 `added_atoms`에 같은 값을 넣고, PDBFixer 원값과의 차이를 `new_atom_rounding.max_abs_delta_A`로 남긴다(엔진이 낸 값이라 검증기는 0 이상 0.5e-4 이하 범위만 본다). 검증기는 새 원자 좌표가 넷째 자리 값인지도 확인한다. M21 허용오차는 바꾸지 않았다(해시 파일).
- **남은 한계**: 같은 PDBx 왕복이 보완 작업 모듈 안에도 있다. 관측 원자의 입력 좌표가 소수 다섯째 자리 이상이면 PDBFixer에 넘긴 텍스트가 반올림되어 작업 모듈의 1e-9 Å 대조가 `coordinates_changed`로 실패하고 예약한 1단위는 환불되지 않는다(사전 검사는 이를 미리 알리지 않는다, T5 독립 검토). 로컬 공개 구조의 입력 좌표는 셋째 자리까지다.

### 게시 전 M7 사전 검사는 읽기 전용 겹침 보기로 돈다 (M29)
- **원인**: M7 `openmm_method.preflight`는 저장된 객체 handle을 받는다. 저장한 뒤 검사하면 `ObjectStore.put`이 `object_created`를 바로 써서 검사가 실패해도 고아 객체가 남는다(T1 (f) F4).
- **대응**: handle은 내용 해시라 저장 전에 계산할 수 있으므로 `structure_repair_bundle.Overlay`(run store 위에 메모리의 보완 좌표·보완 기록·manifest·보완 구조 넷을 겹친 보기)를 넘긴다. `meta`·`load`만 있고 쓰기 메서드·이벤트 로그·그 밖의 store 속성은 없다(슬롯은 이름을 감춘다. T5 독립 검토가 이벤트를 드러낸 첫 구현을 고치게 했다). T1에서 실제 저장 뒤 검사와 결과가 바이트로 같았고 실패해도 이벤트·객체가 늘지 않았다. 실패는 `repair_incomplete`(`detail.m7_reason`). M7 코드는 바꾸지 않았다. 저장 전에 M7을 돌릴 다른 경로가 생기면 같은 보기를 쓴다.

### 게시와 끝 상태 기록은 한 전이 잠금 안에서 한다 (M29)
- **증상**: T5 첫 구현은 객체 넷과 게시 이벤트를 저장한 뒤 따로 `done`을 기록해, 그 사이에 들어온 취소가 결과를 남긴 채 작업을 `cancelled`로 만들 수 있었다(T5 독립 검토).
- **대응**: `JobQueue._publish_structure_repair`가 순수 부분(`structure_repair_jobs.prepare`: 출력 읽기, 끼워 넣기, 검증기, 겹침 보기 M7)을 잠금 밖에서 하고, run 전이 잠금(`run._transition()`) 하나 안에서 취소·시도를 다시 확인한 뒤에만 `structure_repair_bundle.store`(객체 넷 + `structure_repair_published`) → `job_result_candidate` → `JobQueue._terminal_locked(…, "done")`을 한다. `_terminal_locked`는 전이 잠금을 이미 쥔 호출자용 `_terminal`이다(잠금은 재진입하지 않으므로 `_terminal`을 부르면 안 된다). 취소가 그 앞이면 아무것도 저장하지 않고, 뒤면 작업이 이미 끝 상태다.
- M21 등 기존 프로토콜은 확인 → 잠금 밖 저장 → 따로 끝 상태 순서라 코드상 같은 틈이 있다. M29는 그쪽을 바꾸지 않았다.

### 게시 직전 환경 상실은 닫힌 실패 이유 밖의 `precondition` 기록이다 (M29, 의도)
- **증상**: 작업이 끝난 뒤 게시 전 검증 중 설치된 Amber14 템플릿을 읽지 못하거나 M7 엔진·프로세스 신원 어댑터가 없어지면 작업 실패 기록이 `error: "precondition"`과 `reason_code` `openmm_unavailable`·`process_identity_unavailable`이다. 명세 §4.4의 작업 실패 닫힌 집합(`repair_incomplete` … `engine_failed`, 잘못된 봉투는 `fatal`)에 없는 값이다(T12 독립 검토 A2).
- **원인**: T5 재작업에서 정한 의도다. 환경이 없다는 사실을 "증거 무효"나 `repair_record_mismatch`로 보이지 않으려고 `structure_repair_jobs.prepared_objects`·`m7_check`가 class `precondition`의 `ToolFailure`를 그대로 올리고 `JobQueue._publish_structure_repair`가 그 분류·이유로 실패를 적는다.
- **대응**: 고치지 않고 예외로 기록한다(결정 0037). 객체는 남지 않고 예약한 1단위는 환불되지 않는다. 실패 기록을 닫힌 집합으로 판정하는 코드·시험은 이 두 값을 함께 받아야 한다.

### 보완 구조 판별: 서버는 manifest `repair` 키, 화면은 게시 이벤트 (M29, 알려진 한계)
- 서버의 모든 소비자는 `structure_origin.is_repaired`(전처리 기록 manifest의 `repair` 키 하나)로 판별한다: 기본 거절 `reject_if_repaired`, M20 인계, 하류 읽기의 `structure_origin`. 화면은 객체를 열지 않고 run 이벤트의 `structure_repair_published`로 보완 구조를 고른다(`lib/structure-repair.ts`의 `repairedStructureHandles`: 뷰어 소스 `app/page.tsx`의 `sourceOptions`, 화학 `ChemicalWorkspace`, 번호 대응 목록에서 빼고 M20 구조 선택에 "보완 구조" 배지).
- 그래서 게시 이벤트 없이 일부만 저장된 보완 구조(객체 넷을 저장하는 도중의 디스크 오류 같은 부분 저장. 추가 전용 로그라 지울 수 없고 같은 작업의 재시도가 완성한다)는 화면 목록에 일반 구조처럼 보일 수 있다. 골라도 서버가 받지 않는다: 기본 거절 소비자는 422 `repaired_structure_not_accepted`, M20은 게시 증거가 없어 422 `structure_invalid`(`mutation_handoff.validated_origin`)다(T12 검토 B4). 이미 받아들인 부분 저장 한계의 한 모습이라 고치지 않았다.

### 기본 거절 인벤토리 시험은 정의마다 선언을 요구한다 (M29)
- **원인**: 명세 §5.2 기본 거절은 "전처리 구조를 받는 모든 곳"이어야 하므로 `backend/tests/test_structure_repair_consumers.py`가 `backend/mw`를 AST·문자열로 훑어 소비 지점(`prepared_structure` 등 문자열, manifest 필드, 종류 비교, 알려진 소비 함수 호출, 정책·handle 필드, `structure` 질의 라우트)을 찾는다(T1 측정 스크립트를 시험으로 옮긴 것, `mw` import 없음). T12 검토 B2: 파일 단위 `*` 선언이 같은 파일의 새 소비 함수를 그대로 통과시켰다.
- **대응**: 선언은 정의 하나를 qualname으로 정확히 가리킨다(클래스 선언은 그 본문만, 메서드 `Class.method`와 중첩 `outer.inner`는 따로, 와일드카드는 보고됨. `46273bc9`·`90e57b56`). 범주는 `receive`·`refuse`·`read_only`·`blocked_upstream`·`judgement`·`unrelated`이고, `refuse`·`blocked_upstream`은 기대는 guard 함수 이름을 적어야 하며 그 guard에 `reject_if_repaired`(또는 API 도우미 `_repaired_refusal`) 호출이 있어야 한다. `receive`·`read_only`·`judgement`는 거절하면 안 된다. `Run.call` 허용 목록은 정확히 `generate_mutation_candidates`다. 거절 동작 자체는 `test_structure_repair_refusals.py`가 본다.
- **새 코드를 더할 때**: 전처리 구조를 읽는 새 함수·메서드·라우트는 이 시험의 선언 표에 한 줄(범주와 이유)을 더하거나 스스로 `reject_if_repaired`를 부른다. 둘 다 없으면 시험이 실패한다. M13 분석 흐름은 코드를 바꾸지 않고 계획 라우트 입구에서 막으므로 `blocked_upstream`이다.

### 읽기와 M20 `@3` 보고서는 같은 판정 함수 `modeled_residue_view`를 쓴다 (M29)
- **원인**: M20 저장 형식(해시 파일 `mutation_candidates.py`)은 원본 구조 결과와 잔기 7필드로 이어지지 않는 위치(틈 잔기, MSE→MET 치환 잔기)를 "검사함, 해당 없음"(`numbering.status: not_in_map`, `klifs_sites: []`, `catalytic: []`)으로 저장한다. 읽기 계층은 보완 기록으로 그 칸을 "검사 안 함(모델링 잔기)"으로 덮어 보이는데, T12 검토 B1에서 M20 `@3` 보고서에는 이 사실이 없었다. 둘이 따로 판정하면 화면과 보고서가 서로 다른 위치를 "검사 안 함"으로 보일 수 있다.
- **대응**: `mutation_handoff.modeled_residue_view(store, content, origin)`가 (인계된 참조 결과, 위치마다 None 또는 `reference_not_checked` 목록)을 한 번 판정하고, 읽기(`read_view` → `mutation_reads`)와 `@3` 보고서(`mutation_reports`의 주장 `repair_modeled_residue_position_count`, subject 키 `reference_not_checked`, 줄 셋)가 같은 함수를 부른다(`600c7e69`). `modeled_basis`(리간드 껍질·금속 3.0 Å·이황화 2.5 Å을 관측 원자만으로 다시 판정)와 SO2는 읽기·화면에만 있다. 판정 규칙을 바꾸면 이 함수 한 곳에서 바꾸고 읽기·보고서 시험을 함께 본다. 저장 객체만 읽는 쪽은 여전히 "해당 없음"을 본다(알려진 한계).

### M23 보고서·읽기는 바이트 고정이고 `structure_origin`은 `app.py`가 더한다 (M29)
- **원인**: `sequence_ga_reports.py`·`sequence_ga_reads.py`는 호출 키 해시 파일 27개(`BASELINE_BLOBS`)에 들어 있어 바꾸면 M23 호출 키·골든이 바뀐다.
- **대응**: M23 목록·상세·개체 읽기의 `structure_origin`은 서버 응답 계층(`api/app.py`의 `sequence_ga_results`와 상세·개체가 부르는 `_sequence_ga_origin`)이 `structure_origin_reads.Origins`로 더한다(보완 구조일 때만. 기록이 검증되지 않으면 목록 행은 `valid: false`, 상세는 422 `method_evidence_invalid`, 환경 없음은 412). M23 보고서는 형식 버전을 올리지 않아 보완 사실을 담지 않고 후보 집합·구조 handle만 인용한다. 보완 사실은 화면 표시("보완 구조 기준")와 같은 후보 집합의 M20 `@3` 보고서·보완 보고서가 싣는다. 수락 R10이 두 파일의 blob이 기준과 같음을 확인했다. 다른 해시 파일 읽기에 필드를 붙일 때도 같은 방식이다.

### 긴 동기 작업 시작이 Next.js 프록시 시간 제한에 걸려 화면에 500이 보인다 (M29 수락, M29 전부터 있던 동작)
- **증상**: 연습 07b·07c(R4a, 1HSG)에서 새 5xx 관문이 `POST /api/runs/<run>/jobs/<job>/start` 500을 잡았다. 프런트 로그는 `Failed to proxy http://127.0.0.1:8000/runs/<run>/jobs/<job>/start [Error: socket hang up] { code: 'ECONNRESET' }`이었고 백엔드 로그에는 오류가 없었으며 작업은 `done`으로 끝났다. 2026-10-13 UTC 수락에서도 R4a의 M21 시작 한 건이 같았다(최종 `done`).
- **원인**: 작업 시작 라우트는 작업이 끝날 때 응답한다(1HSG M21 한 건 약 2분). Next.js rewrite 프록시(`frontend/next.config.mjs`, 시간 제한 설정 없음 = 기본 30초)가 그 전에 연결을 끊는다. 위 "오래 걸리는 작업 시작이 화면에서 실패로 보인다"와 같은 원인이다.
- **대응**: 제품은 바꾸지 않았다. 화면(`StructureRepairPanel`·`MutationModelPanel`의 `start()`)은 시작 응답을 잃으면 저장된 작업을 다시 읽어 실제 상태를 보인다. M29 실행기는 정확한 조건일 때만 이 500을 `proxyTimeouts`로 분류한다: POST, 상태 500, busy 아님, 경로 `/api/runs/<run>/jobs/<job>/start`, 같은 run·job의 프런트 로그 `Failed to proxy … socket hang up|ECONNRESET` 줄이 500 하나에 한 줄(`5b01c72f`·`ac9e03ea`), 하네스 단계 뒤 읽은 그 작업 상태가 끝 상태. 그 밖의 5xx는 `noServerError` 관문 실패이고, 백엔드 서비스 로그에 Traceback·ASGI 예외·Internal Server Error 줄이 있으면 `noBackendTraceback` 관문이 실패한다. 증거에는 로그 원문이 아니라 `<run>`·`<job>`으로 다시 만든 요약만 남는다. 보완 작업도 같은 동기 시작이라 큰 구조(8VF6은 PDBFixer만 약 23초에 서버 검증·M7 사전 검사가 더해진다)는 화면에서 같은 500을 볼 수 있다(수락 R1에서는 나지 않았다).

### M21 시간 상한 120/240초는 그대로이고 큰 보완 구조는 M21을 끝내지 못한다 (M29, 사용자 결정 2026-10-13)
- **증상**: T1 측정에서 보완한 8VF6(단백질 중원자 4,538) M21 작업 하나가 1,035초였다. 수락 R4b에서 같은 구조의 M21 작업을 `timeout_s` 240으로 돌리자 242.4초에 `failed`(`resource_exceeded`, 메시지 "job timeout", `detail.reason_code` 없음)로 끝났고 모델 객체 0, 예약 1단위 환불 없음(사용 단위 1 → 2), 남은 작업 프로세스 0이었다.
- **원인**: NoCutoff GBn2 System 두 개(야생형 참조 + 변이형)를 각각 수소화·최소화하므로 시간이 단백질 중원자 수의 대략 제곱으로 는다. 상한 `TIMEOUT_DEFAULT_S = 120`·`TIMEOUT_MAX_S = 240`은 해시 파일 `mutation_model_constants.py`에 있다.
- **대응**: 상한을 올리지 않고 한계로 기록했다. 실행기는 구조마다 `m21_band`를 적는다. 측정한 구조는 T1 표 상수(`scripts/m29_common.py`의 `M21_BAND_MEASURED`, 부하가 있던 한 기계에서 CPU 스레드 하나로 잰 값): 1UBQ 602개 20.7초·1HSG 1,516개 118초·1A30 1,542개 123초는 `completes`, 1MQ4 2,160개 233초는 `near_limit`, 1M17 2,594개 310초·1A4I 4,476개 992초·8VF6 4,538개 1,035초는 `exceeds`. 측정하지 않은 구조는 보완 뒤 중원자 수 규칙(1,600 이하 `completes`, 2,200 이하 `near_limit`, 그 위 `exceeds`)이며 독립 계산이 아니다.
- `exceeds` 구조는 보완 → M7 통과 → M20 → M21 입장까지만 보이고 M21 작업을 끝내지 못한다(8VF6 M21 한 번 관측, 나머지는 T1 측정에서 옮긴 값. 그 M21 모델이 있어야 하는 M21 수용체 출처 도킹도 그 구조에서는 할 수 없다)(수락 분류 표는 입장이 열린 M21 작업을 시작하지 않고 취소해 `cancelled_queued`). 1HSG는 기본 120초 안(T1 118초, 여유 약 1.5초)이라 부하가 있으면 넘을 수 있고, 1A30·1MQ4는 `timeout_s` 240이 필요하다(1A30은 T1 123초, 수락에서 `timeout_s` 240으로 116.5–116.6초). M25 단백질 루프의 모델 단계 작업은 `timeout_s`가 120초 고정이다(`jev_loop_constants.STEP_TIMEOUT_DEFAULTS_S["model"]`을 `jev_loop_store.step_job`이 그대로 씀, 루프에는 240초로 바꾸는 경로가 없음). 그래서 T1 측정으로 보면 `exceeds` 셋뿐 아니라 1A30·1MQ4의 모델 단계도 끝나지 않을 것으로 보고(1A30은 경계), 1HSG는 여유가 약 1.5초다(M25 계산은 실행하지 않았다). M23 개체 모델링(한 구조, `sequence_ga_constants.MODEL_STEP_S = 240`)은 이 크기에서 측정하지 않았다. 시간 초과는 결과 없이 1단위가 청구된다. 8VF6 모델의 M18 수용체 원자 수(수소 포함)는 9,143으로 상한 10,000 안이다(T1). 상한을 올리는 일은 해시 파일 변경이라(M21·M23 호출 키·골든 재기록) 별도 사용자 결정이다.

### guardian의 pid 순서 SIGTERM 때문에 취소한 행이 `engine_failed`가 될 수 있다 (M29 T2 발견, 제품 기존 경합, 고치지 않음)
- **증상**: T2 게이트 계열 A 3회째에 `test_docking_batch_reports.py` 11개가 fixture 단언으로 ERROR였다. qvina2를 붙잡은 뒤 큐 취소를 했는데 행 상태가 `rows[2:] = [("failed", "engine_failed"), ("cancelled", "cancelled")]`였다(`docs/qa/m29-repair-20261013/t2-flaky-tests.md` 2.3).
- **원인**: guardian은 그룹을 정리할 때 `members()`(psutil `pids()` 오름차순)로 구성원마다 SIGTERM을 보낸다. pid가 한 바퀴 돌아 qvina2의 pid가 작업자보다 작으면 엔진이 먼저 죽고(멈춘 프로세스도 기본 동작의 SIGTERM이면 바로 끝남), 작업자는 자기 SIGTERM보다 엔진의 −15 종료를 먼저 처리해 "qvina2 exited" → `engine_failed`로 적는다. 실제 일괄 작업 모듈로 따로 재현했다(엔진 먼저 → 두 번 모두 `failed/engine_failed`, 작업자 먼저 → 두 번 모두 `cancelled`).
- **대응**: 시험만 고쳤다(`0218cfa5`, 아래 `engine_hold.hold_then_cancel`). 제품 경합은 남는다: 실제 사용에서도 qvina2 실행 중에 취소가 닿고 qvina2의 pid가 작업자보다 작으면 사용자가 취소한 행이 드물게 `engine_failed`로 기록될 수 있다. 고칠 자리는 guardian의 신호 순서(`jobs/guardian.py`, 호출 키 해시 파일 아님)나 엔진 종료를 `engine_failed`로 적는 작업 모듈(`docking_worker.py`, 호출 키 해시 파일)인데 M29 범위 밖이라 둘 다 바꾸지 않았고 `docs/tracking/findings.md`의 미해결 문제로 넘긴다.

### 간헐 실패 시험의 원인은 psutil 전체 훑기였다 — `engine_hold` (M29 T2)
- **증상**: Stop 훅 동시 실행에서 서열 GA SIGTERM 시험 `[qvina-worker]`가 "individual 0 ended before it was held"로, M19 world fixture(`docking_batch_fixture.build_world`)의 셋업 단언으로 `test_docking_batch_api.py` 13개·`test_docking_batch_reports.py` 11개가 ERROR로, 분석 흐름 정지 시험 `test_analysis_workflows.py::test_stop_during_owned_real_job_cancels_only_that_job`이 상태 `running`으로 실패했다. 단독으로는 통과했다.
- **원인(측정, `t2-flaky-tests.md`)**: (1) T1 가설(CPU 0.05초 조건의 재개 구간)이 아니었다. 그룹을 SIGSTOP한 뒤 psutil `children(recursive=True)`가 모든 pid를 훑는 데 실패 시행에서 1.15–2.35초가 걸려(부하 중 측정 단위 중앙값 365 ms, 최대 8,078 ms), 정지 순간 fork/exec 중이던 qvina2(이 입력에서 CPU 약 0.9초)가 그 사이에 끝까지 돌았다. 시험 프로세스가 스케줄러에 굶은 것은 아니었다(`sleep(0.01)` 깨어남 지연 최대 13 ms). (2) M19 fixture의 취소는 큐 → guardian STOP → guardian의 표본·`members()`·`cleanup()` 훑기 뒤에야 작업자에 닿아 약 1초짜리 행보다 늦었다(그리고 위 pid 순서 경합). (3) 분석 흐름 정지 시험: 큐가 STOP 뒤 guardian 답을 4초만 기다리고(`_stopped_result`) `job_cleanup_pending`으로 작업을 `running`에 남기는데(run을 다시 열 때 `reconcile_run`이 닫음) 시험이 조정하지 않았다.
- **대응(시험만, `backend/tests/`, `e1da210b`·`16aa05d8`·`ea608e33`·`0218cfa5`·`0a9a602a`·`cddc638a`)**: 새 보조 모듈 `backend/tests/engine_hold.py`: libproc `proc_listchildpids`로 작업자의 직계 자식만 한 번 조회(약 0.6 ms, 최대 30 ms), `hold`(멈췄고 CPU에 스레드가 없고 20 ms 동안 CPU 시간이 그대로일 때까지 SIGSTOP 반복), `hold_past_exec`, `wait_blocked`(모든 스레드 WAITING + CPU 시간 세 번 같음), `hold_job_engine`, 신호 순서를 고정한 취소 hook `hold_then_cancel`(엔진 붙잡기 → guardian 멈춤 → 큐 취소와 STOP 전송 확인 → 작업자에게 SIGTERM 먼저 → guardian 재개). 서열 GA `_held_step`, 포켓 `_held_engine`, M19·M22 취소 시험이 이를 쓰고, 분석 흐름 시험은 미룸 이유(`guardian_result_missing`·`group_not_verified_empty`)를 확인한 뒤 API처럼 조정한다. psutil 미리 읽기의 `SystemError` 넷과 manifest 부분 문자열 검사 둘도 고쳤다. T2 계열 C에서 열아홉 그룹 연속 3회(6,531개), 소스 고정 게이트 3회에서도 실패 0이었다.
- **남은 것**: `engine_hold`의 정확한 정지 판정은 macOS libproc에 기대고 다른 플랫폼의 psutil 대체 경로는 돌려 보지 않았다. 큐가 guardian 답을 4초만 기다리는 경로는 guardian으로 취소하는 다른 작업 시험에도 있다(Stop 훅을 두 벌 이상 겹치면 나올 수 있음). 이런 시험이 실패하면 코드 문제로 단정하지 말고 그 시험만 단독으로 다시 돌려 진단 기록으로 남긴다.

### Stop 훅은 pytest 20그룹 + ruff = 체크 21개이고, 부하와 편집 중 상태가 거짓 실패를 만든다 (M29)
- **증상**: M29 동안 Stop 훅이 여러 번 실패했다(실패 기록 1–10은 Git 제외 조율 메모 `.dryforge/run-notes.md`, 요약은 `gate.txt`·`t2-flaky-tests.md`). 나머지(REST) 그룹은 새 M29 시험이 쌓이며 부하 속에서 4,038개 454.52초(기록 6), 실패한 시험 없이 480초 시간 초과(기록 7·9), 부하 없이 단독 2,655개 372.0초(가장 긴 파일 `test_structure_repair_handoff.py` 65.8초), 부하 속 4,091개 414.9초(기록 10)였다. 고정 직전 진단에서는 모든 그룹을 함께 돌리면 REST가 414.3초(전체 6,703개)였다. 훅이 구현자의 편집 도중을 본 거짓 실패도 둘 있었다: 기록 8(위 "작업 모듈·의존 파일을 고치면…"), 기록 10(`scripts/test_m29_acceptance.py` 두 시험이 `leak_kinds`에 목록이 들어간 중간 상태를 봄, 편집이 끝난 `ac9e03ea`에서 73 passed). 진짜 회귀는 하나였다(기록 6: T8b가 M20 입장을 게시 증거 검사로 맞춘 뒤 T6 시험이 손으로 저장한 보완 객체가 `structure_invalid`로 거절됨 → 시험이 제품 보완 작업으로 게시하게 고침).
- **원인**: 모든 pytest 그룹이 동시에 돌고 그룹마다 480초 제한이다. 다른 작업의 전체 그룹 실행·QA와 겹치면 기계가 포화되고, 훅은 같은 체크아웃에서 고치는 중인 파일을 그대로 읽는다.
- **대응**: 그룹 둘을 더했다(`2da787e9` 보완 작업 경로, T8b 병합 `9c69a53f`에서 하류 읽기를 따로). T13에서 `test_structure_repair_handoff.py`를 REST에서 마지막 M29 그룹으로 옮기고(`12636a4b`), 소스 고정 커밋 `52aa4265`에서 중간 크기 파일 여섯(`test_jobs.py`·`test_ligand_worker.py`·`test_ligand_jobs.py`·`test_mutation_tool.py`·`test_jev_ast.py`·`test_site_annotation_reports.py`)을 M27 그룹으로 옮겼다(진단 시도에서 가장 긴 그룹 371.4초). 지금 `PYTEST_GROUPS` 열아홉 + REST = pytest 20그룹, ruff까지 `CHECKS` 21(`scripts/test_codex_hooks.py`의 기대 21). 고정 게이트(다른 부하 없이 연속 3회, `docs/qa/m29-repair-20261013/gate.txt`): 6,703개 skip 0, 가장 긴 그룹 377.9·379.6·375.2초, 1회째 REST 3,894개 323.8초, M29 두 그룹 103개 272.8초·43개 177.6초.
- 게이트·QA는 Stop 훅이 돌지 않고 소스를 고치지 않을 때 한 번에 하나만 돌린다. 편집 중에 난 훅 실패는 파일이 안정된 뒤 같은 시험을 다시 돌려 진단으로만 기록한다(게이트 통과가 아님). 다음에 시험을 더해 한 그룹이 480초에 가까워지면 다시 나누고 `scripts/test_codex_hooks.py`의 기대를 함께 고친다.

### 단백질 공학 탭의 새 GET 읽기는 옛 하네스의 요청 비교를 깨지 않는다 (M29 확인)
- 구조 보완 영역(`StructureRepairPanel`)은 단백질 공학 탭 맨 위에 있고, 탭에 들어올 때 run 이벤트·보완 기록 목록·작업 목록을 GET으로 읽으며 보완 작업이 진행 중일 때만 1초마다 그 작업을 GET으로 읽는다. POST는 사람이 누르는 제출·승인·시작·취소·보고서 만들기뿐이다.
- 옛 하네스의 요청 비교는 쓰기만 센다: `tabs-flow.cjs`(M14)의 탭 표시 단계는 GET이 아닌 요청이 없음을, `annotation-flow.cjs`·`numbering-flow.cjs`는 GET이 아닌 요청 목록(`writes`)을, `mutation-flow.cjs`·`mutation-model-flow.cjs`·`sequence-ga-flow.cjs`·`jev-flow.cjs`·`jev-loop-flow.cjs` 등은 POST를 본다. 그래서 옛 하네스의 기대를 바꿀 필요가 없었고, 소스 고정 전 진단으로 M14 탭 흐름(`--mode main`)을 한 번 돌려 통과했다(게이트·회귀 증거가 아님. 회귀 사슬 결과는 `docs/tracking/m29-acceptance.md`).
- 한 검사는 약해질 수 있다: `tabs-flow.cjs`의 "다른 탭이 보이는 동안 숨은 OpenMM 패널이 폴링한다"는 `/runs/{runB}/jobs`가 들어간 GET이 하나 이상인지와 숨은 패널 글자가 `상태 done`이 되는지를 함께 보는데, 보완 영역의 작업 목록 읽기(`/runs/{id}/jobs`)도 앞 조건을 채울 수 있다. 뒤 조건은 그대로 확인한다. 새 영역을 다른 탭에 붙일 때는 그 탭을 보는 옛 하네스가 GET 경로까지 비교하는지 먼저 본다.

### 증거 위생 (M29)
- 커밋 증거는 텍스트만이다(결정 0020). M29 실행기 내보내기는 `.json`·`.jsonl`·`.log`·`.md`·`.txt`만 텍스트로 옮기고, 스크린숏·paint 프레임·내려받은 mmCIF(`downloads/`)·하네스 화면 글자(`*.screentext`)는 `binary-artifacts.json`에 경로·크기·SHA-256만 남긴다(2026-10-13 UTC 수락: png 68·screentext 17·cif 1). 256 KiB를 넘는 텍스트(대장 `case-ledger.json` 제외)도 Git 제외 artifacts에 둔다.
- 내보낼 때 절대 경로를 `<repo>`·`<home>`·`<tmp>`로 바꾸고, `m29_common.leak_kinds`(키 모양, placeholder, 사용자 절대 경로)에 걸린 텍스트는 내보내지 않으며(`heldText`, 크기 아닌 이유로 하나라도 있으면 `exportClean` 거짓), 내보낸 뒤 다시 검색해 걸린 파일은 `<artifacts>/held-from-out/`으로 되돌린다. `--root`·`--artifacts`는 Git 제외의 새 폴더여야 하고 `/tmp`·`/private/tmp` 아래면 거절하며, `--out`은 시작할 때 비어 있지 않으면 거절한다(실행 중에는 표지 `.m29-export`가 있는 자기 첫 내보내기만 마지막 관문 값으로 다시 쓴다).
- R11 비폭로 판정(T11 해석): 화면·보고서에 절대 경로·키·placeholder가 없고, R10에서 만든 JEV 미리보기 본문(M24 단독·M25 루프, 보내지 않음)에 `repair`·`보완`·`structure_origin`·`calc_flag`·`obj://`·사용자 경로 문자열이 없다(하네스 `BODY_FORBIDDEN`).
- 커밋한 fixture: `backend/tests/fixtures/public_{8vf6,1rnh,4ins,1ay7,1cll}.cif`(+ `*.provenance.json`, RCSB 장부 `docs/qa/m29-repair-20261013/network-ledger.txt`는 헤더·키 없이 상태·바이트·URL·SHA-256만), `backend/tests/fixtures/structure_repair/`의 합성 표시 자료 `synthetic-*`(출처 `synthetic-fixtures.provenance.json`)와 PDBFixer 측정 고정 자료 `*-additions.pdbfixer-measured.json`(출처 `pdbfixer-measured-fixtures.provenance.json`), `reference-8vf6/`(M15 참조 가공 행 SIFTS·KLIFS·UniProt 사본. kbase 전례 문구가 아님). 합성 자료를 실제 결정구조처럼 서술하지 않는다.

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

### 변이 구조 모델링 작업 경로 (M21)
`POST /jobs`의 `openmm_mutation_model_v1`은 `mutation_model_bundle.admission`이 엔진 없이 인자·`timeout_s`·후보 집합(M20 `validated_set`)·후보 번호·구조·잔기 7필드를 검사하고, dry-run이면 계획만 돌려준다. 그 다음 `selection`이 신원 어댑터·OpenMM(M7 `dependencies()`)·PDBFixer(`importlib.metadata`)를 확인하고(412), M7 `preflight()`로 단백질 중원자 투영을 만들어(422 `openmm_preflight_failed`) 스테이징 payload(투영, seed, 원래 잔기 7필드, 변이 후 이름, cutoff, 고정 방법)를 작업 기록에 넣는다. 호출 키는 정규화 인자 + 작업 모듈·의존 파일 SHA-256 + 방법 기록이다. 시작 때 같은 pin을 다시 맞추고, guardian이 고정 진입점 `mw/jobs/openmm_mutation_worker.py`를 서버와 같은 프로젝트 인터프리터로 띄운다(감시 대상, 출력 64,000,000 B). 작업 모듈은 변이형만 PDBFixer에 넣어 이식하고, 두 구조를 같은 `_prepare` → `_minimize` → `_entry` 경로로 만든 뒤 `result.json` 또는 닫힌 `error.json`을 쓴다. 게시(`_publish_mutation_model`)는 현재 시도·취소를 확인하고 출력 크기·해시, 방법·선택 일치, mmCIF 원자 행, 야생형 중원자 = 스테이징 투영, 추가 원자 집합, `validated_model`을 통과해야 mmCIF 객체 둘과 결과를 저장한다. 같은 조건 도킹은 이 결과를 M18 `docking_bundle`이 `receptor_source`로 다시 검증해 저장 mmCIF와 `final_bonds`로 만든 사이드카를 스테이징하고, `docking_worker.py`는 이 출처 표시가 있을 때만 말단 카르복실 완화와 열두째 문장을 켠다.

### GA 설계 작업 경로 (M22)
`POST /jobs`의 `qvina_ga_dock_v1`은 `ligand_ga_inputs.submission`이 입장 1–3을 검사한다: `ga`·`timeout_s`·필터 정규화와 공유 필드의 M18 `docking_inputs.validate_arguments`(자리표시 후보 id), M17 후보 집합 검증 읽기와 필터 적격 평가, 첫 적격 후보 하나를 대표로 `docking_bundle.submission`(수용체·부모 검증 한 번), `ga_pool_too_small`. 결과는 GA 선택 기록 `ligand_ga_selection@1`(인자, 대표의 수용체·사이드카·부모 기록, 풀 id·적격 표시, `pool_sha256`, `selection_sha256`)이며 후보마다의 M18 선택은 없다. 호출 키는 `selection_sha256` + M18 pin + GA pin이고, 같은 키의 진행 중 작업이나 검증된 `complete` 요약의 작업만 돌려준다. 새 작업이면 그 자리에서 재사용 계획 크기(422)와 예산 부족(429)을 본다. 작업 기록에는 `method`(M18 pin)와 `ga_method`(GA 작업 모듈·상수 해시)를 넣고 시작 때 둘 다 다시 맞춘다. 시작 때 run 실행 잠금 안에서 재사용 계획을 한 번 정하고(`published_m18_results`로 적격 후보의 M18 호출 키 조회, 각 handle을 `validated_result`·`input_sha256`으로 재검증, `job_dispatch_intent.ga_reused`) 크기를 다시 본 뒤 `reserve_attempt(units=reserved_units)`로 예약한다. 스테이징 `ligand_ga_worker_input@1`은 첫 적격 후보의 M18 스테이징에서 가져온 수용체·부모 SDF 블록·상자·값, `ga`, 풀 행(id·SMILES·적격, 적격만 M18 후보 필드·`input_sha256`·재사용 결과 바이트)이며 한도는 48 MiB + 재사용 128 MiB의 base64(`MAX_STAGED_BYTES`)다. guardian은 고정 진입점 `mw/jobs/ligand_ga_worker.py`를 `.deps/docking/venv-locked`로 띄우고(감시 대상), 작업 모듈은 `docking_worker.py`(먼저 불러 socket을 막음)와 의존성 없는 `ligand_ga_constants.py`를 파일 경로로 불러 쓰고 RDKit은 Morgan 지문에만 쓴다. 적격 후보의 지문을 만든 뒤 수용체를 한 번 준비하고(`prepared.json`), 세대마다 개체를 뽑아 차례로 재사용하거나 `dock_row`로 도킹하며 `individuals/<k>.*`와 `generations/<g>.json`을 원자적으로 쓴다(쓰는 동안 SIGALRM·SIGTERM 막음, 개체 시계 300초와 전체 시계·SIGTERM은 `BaseException`인 `_Stop`). 서버는 그룹 정리 확인 뒤 M19와 같은 `_finish_batch`에서 종료 원인을 정하고, `ligand_ga_jobs.finish`가 새 도킹 개체를 M18 검사로 게시한 뒤(`ligand_ga_individual_published`) 개체 선택을 다시 만들어 요약을 만들고 검증해 게시한다(`ligand_ga_published`). 서버 재시작 때는 `reconcile_run`이 같은 경로로 게시하고 `interrupted`로 닫는다. capability는 M18 capability + GA 파일 해시 + GA 작업 모듈 `--handshake`(파일 해시 키로 캐시)다. 사람 증액은 `POST /runs/{id}/ligand/ga/limit_approval` → `ligand_ga_jobs.limit_approval` → `Run.raise_limits`(GA 상수)뿐이다.

### 서열 GA 작업 경로 (M23)
`POST /jobs`의 `sequence_ga_dock_v1`은 큐 `submit`에서 이 순서로 돈다: `sequence_ga_jobs.submission`이 입장 1–4(인자·`ga`·`timeout_s` 정규화 → 두 리터럴·M18 확인 → 후보 집합(M20 `validated_set`)·구조 → RDKit 없는 리간드 SDF·상자 부분 점검)를 검사하고, dry-run이면 여기서 계획만 돌려준다. 그다음 `selection`이 입장 5–8(환경 412 → M7 `preflight()` 투영과 `residue_mismatch`·`box_no_receptor_atoms` → `ga_space_too_small`(조합 공간 크기 `N` = 기본대칭다항식 합) → 스테이징 크기 429)을 하고, 호출 키를 만든 뒤 `complete_job`이 같은 호출 키의 진행 중·`complete` 작업이 있으면 **예산 검사 전에** 그 작업을 돌려준다. 새 작업이면 입장 9(예산 429 `ga_limit_raise_required`)를 한 다음 큐 시작 때 run 실행 잠금 안에서 이벤트 스냅숏으로 재사용 색인(같은 `conditions_sha256`의 `sequence_ga_individual_published`에서 모델·결과가 모두 저장·검증된 개체와 기준 행)을 정하고 `reserved_units`를 한 번 예약한 뒤 guardian이 GA 작업 모듈(도킹 환경)을 띄운다. 시작 전 확인(`admission_plan`)은 읽기 전용으로 1–8단계만 하고 예산은 `shortfall`로 돌려준다. 작업 모듈은 야생형 기준 행을 먼저 평가하고, 세대마다 슬롯을 모두 선택한 뒤 개체마다 모델링 자식 프로세스(프로젝트 `.venv`, 같은 프로세스 그룹) → 개체 수용체 준비 → `dock_row` 순으로 평가하며 개체·세대 파일을 원자적으로 쓴다. 작업이 끝나고 그룹이 비었는지 확인한 뒤 서버 `finish`가 파일을 읽어(`O_NOFOLLOW`·크기 상한·canonical JSON) 엔진·방법·상자를 서버 기록과 대조하고(불일치면 아무것도 게시하지 않고 `fatal`) 새 평가 개체마다 mmCIF → 모델 → 도킹 결과 객체를 게시하고 `sequence_ga_individual_published`를 쓴 다음 요약(`sequence_ga_result@1`)과 `sequence_ga_published`를 게시한다. 야생형 기준 행 상태가 기록되기 전에 멈추면 요약이 없다. 읽기는 한 번의 이벤트 스냅숏으로 요약·모델·도킹 결과를 다시 검증한다.

### JEV 과학 전송 경로 (M24)
투영은 값싼 도구다: `POST /commands`의 `build_jev_projection`이 `Run.call`에서 사전 검사 훅(`tools/jev.precheck`)으로 입장 여덟 단계를 구현보다 먼저 하고 정규화 인자(저장 순서 후보, 정규화 필터)만 호출 키로 돌려준다. 구현은 같은 읽기를 반복해 순수 모듈 `jev_projection`(표준 라이브러리 + numpy, 저장 객체 내용과 파싱한 구조만 받음)으로 와이어를 만들고 `check_wire` → 본문 인코딩·64 KiB 확인 → 저장 형태 `validated_projection`을 통과할 때만 `jev_projection@1`을 저장한다. 미리보기(`jev_sends.preview_for`)는 저장 투영을 다시 검증하고 같은 `projection_body`로 본문 문자열·해시를 만든다(이벤트 없음). 전송 라우트는 요청·투영·해시·멱등·진행 중을 이벤트 없이 확인한 뒤 `ACTIVE_SENDS`에 넣고 `SCIENCE_GATE.request_science`(`egress/science.py`)를 부른다. 게이트는 run 실행 잠금 + 전이 잠금 안에서 승인 콜백 → 승인 대조 → 거절 검사 → 키 → 예약 → `prepared` → 재확인 → `dispatch_started`·`jev_science_dispatch_started`를 쓰고, 전이 잠금 밖에서 기존 `_http_request`로 한 번 보낸 뒤 기존 정산을 하고 `parse_choice`로 답을 검증한다. 결과는 `_finish`가 전이 잠금 안에서 쓴다(완료면 제안 객체를 `validated_choice` 통과 뒤 저장하고, 모든 경우 `jev_send_outcome`). 기록·늦음·상한은 모두 이벤트에서 다시 만든다(`list_sends`, `send_record`, `late_arrival`, `dispatch_count`). 보고서(`jev_reports.py`)는 제안·투영·소스 집합을 다시 검증하고 전송 이벤트 사슬과 대조하며 아무것도 보내지 않는다.

### JEV 설계 루프 경로 (M25)
루프 기록은 저장하지 않는다. `jev_loop_store`가 이벤트 로그를 한 번 읽은 `LoopReadView` 하나로 만들기 이벤트(`jev_loops.parse_created`), 작업 기록(`JobQueue(view)`), 단독 M18·M21 요청 빌더와 만들 때의 pin으로 낸 후보별 호출 키, 저장 결과(`published_m18_results`·`model_index` → `validated_result` + 입력 대조), 루프 제안(`validated_loop_choice` + `proposal_matches_send`), 남은 예산을 모아 순수 함수 `jev_loops.derive_loop`에 넘기고, 나온 `jev_loop@1`을 `validated_loop_record`로 검사한다(읽기는 아무것도 쓰지 않음). 만들기는 실행 잠금 안에서 입장 검사 뒤 `jev_loop_created` 하나를 쓴다. 투영은 값싼 도구다: `build_jev_loop_projection`의 사전 검사 훅이 루프 기록에서 선택 거절(`jev_loops.selection_refusal`)·소스·구조·와이어를 보고 기록 입력을 `bound`로 고정하며, 구현은 수정하지 않은 M24 빌더의 출력을 `jev_loop_projection`이 섞은 순서로 다시 늘어놓고 별칭·`goal`·`computed`·`values_note`를 더해 `validated_loop_projection`을 통과할 때만 저장한다. 미리보기·전송은 M24 라우트 그대로이고 `jev_sends`가 `jev_loop_projection@1`을 받아(`accept_loop`) 미리보기에 `loop`·`loop_blocks`를 더하며, 전송은 승인 콜백 안에서 `jev_loop_store.loop_send_check` 뒤 승인 이벤트를 쓰고 게이트(`egress/science.py`)가 스키마로 루프 검증·본문·`parse_loop_choice`를 고른다. `_finish`는 루프 투영의 답을 `jev_loop_choice@1`로 만들어 검증한 뒤 저장한다. 계산 시작 라우트(`app.py`)는 실행 잠금 안에서 `compute_decision`(거절·멱등·승인) → `step_job`(단독 M18·M21 작업 입장, 호출 키가 승인과 같은지 확인) → `write_approval`(전이 잠금 안 재확인 뒤 `jev_loop_compute_approved`) → `JobQueue.submit`을 하고 잠금을 놓은 뒤 `JobQueue.start`를 부른다. 작업은 기존 큐·guardian·작업 모듈이 그대로 돌리고 루프는 그 기록을 읽기만 한다(단계 결과 = 승인 뒤 그 작업이 처음 맞은 상태 변화, 귀속은 `job_owners`). 도킹 포기는 이벤트 하나, 끝내기는 실행 잠금 + 전이 잠금 안에서 기록을 다시 읽어 `jev_loop_result.build_loop_result` → `validated_loop_result` → 저장 → `jev_loop_ended`다. 보고서(`jev_loop_reports.py`)는 요약을 `stored_result`로 확인하고 끝 이벤트 시점의 저장 M18 결과·제안과 대조하며 아무것도 계산·전송하지 않는다. M21 짝 읽기는 `job_owners`로 루프 도킹 짝에 `loop` 키만 더한다.

### 효소 반응 지식 경로 (M26)
반응 참조 세트는 사용자가 실행하는 가져오기 명령만 쓴다: 명령은 `reaction_knowledge_constants.py`를 파일 경로로 불러(`mw` import 없음) M-CSA 쪽 순회 → accession 합집합(`MAX_ACCESSIONS` 확인) → UniProt 일괄 요청과 빠진 accession 분류 → Rhea 한 요청을 하고, 모든 응답을 `SOURCE_FORMATS`로 가공·검사한 뒤에만 임시 폴더에 쓰고 검증해 `sets/<set_hash>/`로 옮기고 `active.json`을 바꾼다. 서버의 값싼 도구 `link_reaction_knowledge`는 `Run._validated_bound`가 모든 호출 경로에서 부르는 사전 검사 훅(`tools/reaction_knowledge.precheck`)이 `reaction_knowledge.pin_and_index()`로 세트를 고정·해석하고(412) 입장 아홉 단계를 한 뒤(422) 세트·색인·체인 잔기·번호 대응 내용을 `ReactionBound`로 고정하고 `key_fields`로 세트 해시를 호출 키에 더한다. 구현은 그 `bound`로 `build_reaction_knowledge`를 부르고 `validated_result`를 통과할 때만 저장한다(1 MiB·연결 위치 2,000 초과는 429). 읽기(`reaction_knowledge_reads.py`)는 결과 객체를 매번 `validated_result`로 다시 검증하고 지금 활성 세트와 비교만 한다. 보고서(`reaction_knowledge_reports.py`)는 저장 결과에서 주장을 다시 만들어 대조한다. M20 v2는 도구 층(`tools/mutations.py`)이 반응 결과를 검증해 `catalytic_input`으로 평범한 체인별 값만 만들고 `mutation_candidates.catalytic_protection`이 보호 목록과 검사 칸을 만든다. 같은 함수를 M20 보고서가 다시 불러 저장 집합과 대조한다.

### 키나아제 전례 경로 (M27)
전례 참조 세트는 사용자가 실행하는 가져오기 명령만 쓴다: 명령은 `precedent_constants.py`를 파일 경로로 불러(`mw` import 없음) dist 매니페스트·`KBASE_PINS` → 세 dist 파일 대조 → `validate_dist_files`(형식·레코드 해시·`move_id` 유일) → pubmed 최신 스냅샷 대조·`parse_pubmed` → 읽기 전용 git 셋 순으로 검사하고, 확인 뒤에만 임시 폴더에 바이트 그대로 써 `sets/<set_hash>/`로 옮기고 `active.json`을 바꾼다(네트워크 없음). 서버의 값싼 도구 `link_kinase_precedents`는 `Run._validated_bound`가 모든 호출 경로에서 부르는 사전 검사 훅(`tools/kinase_precedents.precheck`)이 `kinase_precedents.pin_and_index()`로 세트를 고정·해석하고(412, 해석·색인은 세트 하나 캐시) 입장 다섯을 검사한 뒤(422, 번호 대응은 훅이 받은 store에서 읽어 `numbering_map_shape_ok`로 지역 모양 검사) 세트·색인·번호 대응 내용·정규화 인자를 `PrecedentBound`로 고정하고 `key_fields`로 세트 해시와 `method_version`을 호출 키에 더한다. 같은 호출을 다시 검증할 때는 이전 `bound`의 세트를 그대로 쓴다. 구현은 그 `bound`로 `build_kinase_precedents`를 부르고(체인 판정 → 표적 판정 → 포함할 원본 레코드마다 `content_hash` 재계산(불일치면 색인 캐시를 비우고 412) → 두 경로를 뺀 사본·무결성 값·서지 → 1 MiB 확인(넘으면 표적별·포함 끈 크기를 다시 재서 429)) `validated_result`를 통과할 때만 저장한다. 읽기(`kinase_precedents_reads.py`)는 질의를 먼저 검사하고(run 조회 전) 결과 객체를 매번 `validated_result`로 다시 검증하며, 한 표적의 전례를 서버에서 거르고 정렬해 한 쪽만 돌려주고 지금 활성 세트와 비교만 한다(목록은 이벤트 로그를 한 번 읽어 생성 순서를 찾음). 보고서(`kinase_precedents_reports.py`)는 저장 결과·도구 호출 기록·구조·번호 대응을 확인하고 주장과 Markdown을 다시 만들어 대조한다. 화면(`KinasePrecedentsPanel.tsx`)은 순수 판단 `lib/kinase-precedents.ts`(요청 가드·결과 모델·질의 구성·늦은 응답 가드·고정 문장 사본)를 쓰고 GET 질의로만 거르기·정렬·쪽을 바꾼다.

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
11. 도구·capability·보고서 종류를 더하면 개수·집합을 고정한 기존 검사가 깨진다(M24에서 실제로 고친 곳, M25도 같은 네 파일·`report-library.test.cjs`와 Stop 훅 그룹 수 기대(`scripts/test_codex_hooks.py`)를 고쳤고, M26도 같은 네 파일·`report-library.test.cjs`를 고쳤으며, M27도 같은 네 파일·`report-library.test.cjs`와 Stop 훅 그룹 수 기대를 고쳤다): `backend/tests/test_api.py`의 `/tools` 이름 집합, 사전 검사 훅이 있는 도구 집합(`test_reference_site_annotation.py`·`test_residue_numbering.py`), `/capabilities` `methods` 집합(`test_ligand_api.py` 두 곳), `app.py`의 보고서 종류 집합 둘(`list_reports`·`_saved_any_report`)과 `create_method_report`·`_saved_any_report` 분기, 프런트 `report-library.ts`(목록 이름)·`api.ts`(명령 도구·보고서 종류·capability 유니언)·`contracts.ts`. 새 실행기 단위 테스트는 `.codex/hooks/stop.py`의 `SCRIPT_TESTS`와 `docs/standards.md` 게이트 목록에 손으로 넣는다. 새 이벤트 종류는 `core/events.py` `EventType`(타입 표기뿐)에 더한다. 새 `backend/mw` 모듈은 `raise_limits`·`limit_approval` 문자열을 쓰지 않는다. 바꾼 기존 검사는 최소로 고치고 이유를 주석에 남긴다.

### UI 컨트롤 변경
1. 새 컨트롤이 MolstarViewer의 직렬화 브리지를 거치는지 확인한다. React state만 바꾸고 적용됐다고 표시하면 안 된다.
2. 백엔드와 프런트엔드를 loopback으로 띄운다: `.venv/bin/python -m uvicorn mw.api.app:app --host 127.0.0.1 --port 8000`과 `npm --prefix frontend run start -- -p 3000`.
3. `npm --prefix frontend run test:offscreen -- --url http://127.0.0.1:3000`으로 `isOffscreen=true`, GPU 켜짐, paint 프레임, 외부 요청 0건을 확인한다.
4. 해당 흐름 스크립트(`test:offscreen:normal`, `:scenes`, `:chemical` 등)를 돌리고, 공유 뷰어·페이지 코드를 바꿨다면 M8 normal, M9 scenes, M10 comparison 회귀도 함께 돌린다.
5. 실패한 실행은 지우지 말고 회귀 증거로 남긴다.

### 제품의 실제 OpenRouter 호출이 필요할 때
1. 사용자에게 필요한 횟수와 이유를 말하고 한도를 받는다. M8 4회, M24 6회, M25 8회 할당은 모두 썼다.
2. 전용 QA run에서 뷰어 요청이면 온라인 모드와 뷰어 동의를, 과학 전송(M24 수동·M25 루프)이면 과학 전송 동의를 켠다(서로 권한을 주지 않음). 과학 전송은 그 단계 수락 실행기의 calibrate·live 단계로만 하고(M24 `scripts/m24_offscreen_acceptance.py`, M25 `scripts/m25_offscreen_acceptance.py`) 저장소 대장(`runs/m24-live-ledger.json`·`runs/m25-live-ledger.json`, 서로 읽지 않음)이 합계를 막는다. 리간드·단백질처럼 비싼 계산 단위를 함께 쓰는 실호출은 run을 나눈다(M25: 리간드 run 5회, 단백질 run 3회). 먼저 키 존재를 불리언으로만 확인한다(`.env` 내용은 열지 않음).
3. 호출마다 served model, 사용량(본문 바이트·예약값과 함께), 발행한 명령 또는 전송 기록, Mol* 확인을 기록한다. 키, 헤더, 원시 provider 오류는 기록하지 않고 증거에서 키 문자열을 검색한다.
4. 한도를 다 쓰면 결과를 그대로 보고한다. 실패한 호출도 1회이며, 추가 호출을 하려고 다시 시도하거나 새 run을 몰래 열지 않는다.
