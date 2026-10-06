# 보안 정책

## 보호 대상과 신뢰 모델

ProtView 인스턴스 하나는 한 사람이 자기 컴퓨터나 혼자 쓰는 서버에서 실행한다. 연구실 구성원은 각자 따로 설치하고, 인스턴스를 공유하지 않는다. 이 전제 때문에 로그인·계정·권한 분리 기능이 없다. 같은 컴퓨터를 쓰는 사람은 모두 run 데이터 전체에 접근할 수 있는 신뢰 대상으로 본다.

보호 대상, 중요한 순서대로:
1. **미공개 구조와 서열**: 업로드한 구조 바이트, 좌표, 서열, 원본 파일 이름. 외부 모델(JEV 등)로 보내는 것은 허용되지만(결정 0015), 반드시 `EgressGate`를 거치고 무엇을 보냈는지 감사 기록에 남아야 한다.
2. **OpenRouter API 키**: 루트 `.env`의 `OPENROUTER_API_KEY` 하나.
3. **과학 기록의 무결성**: 불변 객체, 이벤트 로그, 저장된 보고서 바이트. 조작되거나 몰래 바뀌면 안 된다.
4. **예산**: 외부 호출 비용(USD)과 비싼 계산 횟수. 외부 토큰·USD 예산과 "사용량 모름" 멈춤 상태는 run 안에서 뷰어 모델 명령과 M24 과학 전송이 함께 쓴다(한쪽이 다 쓰거나 사용량을 모르면 다른 쪽도 멈춤).

## 네트워크 노출

- 백엔드(uvicorn)와 프런트엔드(next dev/start)는 `127.0.0.1`에만 바인딩한다. `0.0.0.0`이나 외부 인터페이스에 바인딩하는 것은 인증이 없는 상태로 모든 run을 네트워크에 공개하는 것과 같으므로 금지한다.
- 원격 서버에서 쓸 때는 그 서버를 한 사람이 쓰고, SSH 포트 포워딩으로 접속한다. 여러 사람이 계정을 가진 서버에서는 다른 계정도 loopback 포트에 접속할 수 있다. 이 경우를 막는 장치는 현재 없다.
- Host 헤더 허용 목록: 백엔드(FastAPI 가장 바깥 미들웨어)와 프런트엔드(`frontend/middleware.ts`, 모든 경로) 둘 다 Host 이름이 `127.0.0.1`, `localhost`, `[::1]`(포트 유무 무관, 대소문자 무시)일 때만 받는다. 그 밖의 Host는 400 고정 문구로 거부하고 Host 값을 되돌려 주지 않는다. Next 프록시가 백엔드로 Host를 `127.0.0.1:8000`으로 바꿔 보내므로 두 곳 모두에 둔다. 이것으로 브라우저가 연 외부 페이지의 DNS 리바인딩 접근을 막는다. Origin 검사나 로컬 토큰은 쓰지 않는다(결정 0013).
- 알려진 한계: :3000에 Host 헤더를 두 개(허용 값이 먼저) 보내면 Node가 첫 값만 남겨 통과한다. 브라우저는 Host를 하나만 보내므로 리바인딩 방어에는 영향이 없지만, 같은 컴퓨터의 로컬 프로그램은 이 검사를 막을 수 없다(로컬 프로그램은 어차피 loopback 포트에 직접 접근할 수 있다).
- M24 JEV POST 셋(`/runs/{id}/jev/consent`·`/jev/preview`·`/jev/sends`)은 `Content-Type: application/json`만 받고 그 밖은 본문을 읽기 전에 415로 거부한다. 다른 사이트의 페이지가 보내는 단순 POST(text/plain·form·multipart·형식 없음)로 과학 전송 동의를 바꾸거나 전송을 승인할 수 없게 하기 위해서다(`application/json` 요청은 브라우저가 CORS preflight를 먼저 보내며 백엔드 CORS 허용 출처는 `http://localhost:3000`·`http://127.0.0.1:3000`뿐이다). 투영 도구는 기존 `POST /runs/{id}/commands`를 그대로 쓴다(외부 요청 없음).
- 브라우저는 로컬 번들 자산만 불러온다. 원격 글꼴, CDN 스크립트, 텔레메트리(`NEXT_TELEMETRY_DISABLED=1`)가 없다.

## 외부 요청 권한

외부 HTTP는 `EgressGate` 하나만 보낼 수 있다. 다른 모듈이 httpx 등으로 직접 외부에 요청하면 정책 위반이다(`httpx` import는 `backend/mw/egress/` 안, 클라이언트 생성은 `egress/gate.py`뿐임을 `backend/tests/test_jev_ast.py`가 확인).

| 주체 / 모드 | 외부 요청 | 조건 |
|---|---|---|
| 모든 새 run | 불가 | 항상 `local_only`로 시작하고 과학 전송 동의는 꺼져 있다. API 키가 있어도 모드·동의는 바뀌지 않는다 |
| `local_only` / `dry_run` run의 뷰어 의도·M3 결정 | 불가 | 이 경로들은 키를 읽지도 않고, transport를 만들지도 않는다. 온라인 캐시가 있어도 규칙 경로를 쓴다. `local_only`·`online`은 뷰어 모델 해석 모드이며 아래 M24 과학 전송 동의와 별개다 |
| 온라인 모드 + 뷰어 동의가 있는 run | 뷰어 의도 요청만 | 동의 한 번에 최대 4회, 요청마다 예산 예약 |
| M3 inspection-view 결정 | 접촉 집계 숫자만 | 온라인 설정, 모델 pin, 키가 모두 있을 때 |
| M24 과학 전송(`POST /runs/{id}/jev/sends` 하나) | 사람이 승인한 투영 본문 하나 | run의 과학 전송 동의(`jev_science_consent_changed`)가 켜져 있고, 사람이 미리보기한 정확한 본문을 그 SHA-256으로 승인했을 때만, 승인 한 번에 HTTP 최대 1회. run당 10회·본문 64 KiB·후보 20개, 전송마다 외부 토큰·USD 예약. 뷰어 모드(`local_only`·`online`)와 무관하며 뷰어 동의와 서로 권한을 주지 않는다. dry-run run은 동의를 켤 수 없고 전송도 `dry_run`으로 거절된다 |
| 과학 도구·작업·보고서 | 불가 | 뷰어 동의·과학 전송 동의는 과학 계산 승인을 주지 않는다. 투영 도구 `build_jev_projection`과 `jev_choice` 보고서도 외부 요청을 하지 않는다. 게이트의 과학 전송(`EgressGate.request_science`)을 부르는 코드는 위 사람 승인 라우트 하나뿐이다(도구·작업·M13 흐름·뷰어 명령·모델 응답·`Run.call`은 부를 수 없고 `backend/tests/test_jev_ast.py`가 확인) |
| M13 분석 흐름(계획·실행·요약) | 불가 | 로컬 규칙만 쓴다. 자연어 계획·모델 보조 실행은 사용할 수 없음이며 게이트를 부르지 않는다. 뷰어 동의·온라인 모드·과학 전송 동의는 흐름 권한을 주지 않는다 |
| M15 번호 대응(도구·읽기 API·보고서)과 참조 스냅샷 가져오기 명령 | 불가 | 서버는 로컬 참조 폴더만 읽는다. 가져오기 명령은 로컬 `kbase_kinase` 체크아웃의 파일을 복사하고 `git -C`로 커밋만 읽는다(네트워크 없음) |
| 작업 프로세스(OpenMM, ProLIF, fpocket, M17 RDKit, M18 도킹, M19 일괄 도킹) | 불가 | 자격 증명·프록시를 뺀 허용 목록 환경변수로 실행한다. fpocket은 네트워크 코드가 없는 고정 실행 파일(해시 확인한 복사본)을 실행하지만, 운영체제 수준의 네트워크 차단은 없다. M18 도킹 작업 모듈은 파이썬 소켓을 막지만 자식 `qvina2`에는 운영체제 수준 차단이 없다(qvina 실행 파일 경로는 코드 고정이고 SHA-256을 설치 기록과 대조한다, Meeko 수용체 `Polymer` 경로는 모르는 잔기에 외부 조회를 시도하므로 쓰지 않는다). M19 일괄 작업 모듈은 같은 인터프리터에서 M18 작업 모듈을 불러 쓰므로(불러올 때 소켓 차단) 같은 조건이다 |

- 목적지는 `POST https://openrouter.ai/api/alpha/decisions` 하나로 고정한다. 리다이렉트를 따르지 않고, 환경변수 프록시를 무시하며(`trust_env=False`), 사용자가 헤더·URL·provider 옵션을 넣을 수 없다.
- 요청 모델은 `typesafe/jev-1.13`, 허용하는 응답 모델은 `typesafe/jev-1.13-20260917`뿐이다. provider 정책은 `data_collection=deny`, `zdr=true`, `allow_fallbacks=false`로 고정한다. 응답 모델이 목록에 없거나 비어 있으면 결정을 거부하고 로컬 규칙으로 돌아간다(과학 전송은 `model_mismatch`·`missing_model` 실패로 기록하고 제안을 만들지 않는다).
- 요청 한 번에 HTTP는 최대 1회만 보내고 라이브러리 재시도는 끈다. 제한 시간은 기본 15초이며 남은 run 활동 시간을 넘지 않는다. 응답 본문은 파싱하기 전에 64 KiB로 제한한다.
- 과학 전송은 `app.py`의 모듈 전역 `SCIENCE_GATE`(뷰어의 `VIEWER_GATE`와 별개 인스턴스, 같은 목적지·pin)만 쓴다. 테스트와 오프스크린 fixture 서버는 이 전역을 가짜 transport 게이트로 바꾸며, 바꾸지 않은 서버만 실제 네트워크로 나간다.

## 외부로 나가는 내용 (허용 목록)

- 뷰어 의도(`viewer_intent@1`): 사용자가 입력한 문장(1–512자, 2048 UTF-8 바이트 이하, 제어 문자 없음), 현재 표현, 선택한 대상 별칭 또는 null, 범위 완전성 플래그, 대상 카탈로그(최대 256개, 요청 본문 총 64 KiB 이하). 카탈로그 항목에는 생성된 별칭(`t0001`…), 범주, 모델 번호, author 체인·번호·삽입 코드, 선택적 label 체인·번호만 넣는다. 원본에서 온 문자열 식별자는 영문·숫자·`_`·`-`로 된 16자 이하일 때만 넣는다.
- inspection 상태(`inspection_state@1`): 접촉 수, 접촉 잔기 수, 극성·소수성·기타 접촉 수, 최소 거리, cutoff, null_result. 문자열 필드는 없다.
- M24 리간드 후보 투영(`jev_ligand_candidates@1`): 부모 정규 SMILES와 RDKit 추정 속성 8개, 속성 정의 이름 8개(관측한 M17 저장 문자열과 정확히 같을 때만), 고른 후보(최대 20개)마다 별칭(`c01`…)·정규 SMILES·생성 방식 종류(`fixed_replace`·`user_rule`)·`stereo_flag`·속성 8개·PAINS 일치(카탈로그·이름), 고정 `values_note`. 수용체·포켓 정보는 없다.
- M24 변이 후보 투영(`jev_mutation_candidates@1`): 위치마다 별칭(`p01`…)·잔기 7필드·한 글자 코드·출처 이름(`pocket`·`ligand_shell`·`user`)·리간드까지 최소 거리·`protection_released` 불리언·같은 체인 서열 구간(앞뒤 5개 한 글자 문자열, 첫 `seq_auth`, 연속 여부)·5.0 Å 안 이웃 잔기(체인·번호·삽입 코드·잔기 이름), 후보마다 별칭(`m01`…)·위치 별칭·`from`·`to`, 보호 검사 다섯의 상태 문자열, 포켓 출처를 썼으면 포켓 순위와 안쪽 잔기 수, 고정 `values_note`.
- 두 과학 투영 공통: 고정 질문(영어 문구, 별칭마다 고정 `criteria`), 요청 모델, provider 정책. 문자열 식별자는 `[A-Za-z0-9_-]{0,16}`, SMILES·PAINS 이름은 정해진 문자 집합일 때만 들어가고 수는 저장값 그대로다. 미리보기 문자열, 감사 `prepared`의 본문, transport가 받는 바이트는 같은 인코더에서 나와 바이트까지 같고 승인은 그 SHA-256에 묶인다. 규칙은 `docs/business-rules.md` "JEV 과학 전송 (M24)".
- **서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다**(화면 안내 U3). 미공개 단백질을 다룰 때는 이 수준의 노출을 감안해 보낼지 정한다.
- **게이트가 만들지 않는 것**: 좌표, 구조 파일 내용, 전체 서열, 원자 이름, 리간드 인스턴스 이름, 원본 파일 이름, 로컬 경로, handle, run ID, 후보 id(해시), block 이름, 사용자 반응 SMARTS 텍스트, 번호 대응 값(UniProt 번호·accession), KLIFS 부위 이름표, 보호 사유 이름, 준비 메모, 이전 대화. 이 중 과학 데이터(구조·좌표·서열·리간드·분석 결과)는 결정 0015로 전송이 **허용**되었다. 새 종류를 보내려면 이 절에 새 투영 스키마를 추가하고, UI 미리보기·예산·감사 기록을 함께 구현한다.
- **절대 나가지 않는 것**: API 키와 자격 증명. 로컬 경로도 과학 데이터가 아니므로 보내지 않는다.
- UI는 전송 전에 실제로 보낼 내용을 보여 준다(과학 전송은 정확한 본문 문자열). 사용자가 직접 입력한 문장에 민감한 내용이 있을 수 있으므로, 키워드 필터로 안전을 보장한다고 주장하지 않는다.
- 알 수 없는 필드는 게이트에서 거부한다. 투영 코드는 처음부터 허용 필드만 만들고, 객체 메타데이터를 재귀적으로 복사하지 않는다. 과학 와이어는 키 이름 `handle`·`run_id`·`path`와 경로·URL·파일 이름 모양 문자열도 거부한다.

## 참조 스냅샷 (M15)

- 위치: 로컬 참조 폴더 `.deps/reference/`(Git 제외). 관리자 환경변수 `MW_REFERENCE_DIR`로만 바꿀 수 있고(상대 경로는 저장소 루트 기준), 요청으로는 바꿀 수 없다. 수락 QA는 이것으로 격리 폴더를 쓴다.
- 쓰는 주체는 사용자가 실행하는 `scripts/import_reference_snapshots.py` 하나다. `../kbase_kinase`를 읽는 것도 이 명령뿐이며(결정 0022), 서버는 kbase 경로를 모르고 읽지 않는다. 명령은 kbase 매니페스트의 SHA-256·바이트·행 수가 모두 맞을 때만 새 세트 폴더를 쓰고 `active.json`을 rename 한 번으로 바꾼다. 이전 세트 폴더는 지우지 않는다.
- 서버는 참조 폴더를 읽기만 한다. `O_NOFOLLOW`로 일반 파일만 열고, 세트 폴더 밖을 가리키는 파일을 거부하며, 매니페스트 해시(= `active.json`의 세트 해시)와 파일 해시가 맞지 않으면 `snapshot_invalid`로 사용할 수 없음이다. 호출 하나는 시작 때 고정한 세트만 읽는다.
- 네트워크: 가져오기 명령과 서버 모두 외부 요청을 하지 않는다. 개발 중 예외는 테스트 구조 1MQ4 mmCIF를 RCSB에서 한 번 받은 것뿐이다(사용자 승인, `backend/tests/fixtures/public_1mq4.provenance.json`에 URL·날짜·SHA-256·CC0 기록). 제품 코드와 QA는 이 파일을 로컬에서만 쓴다.
- 라이선스 표시: 스냅샷의 라이선스 문자열(UniProt `CC-BY-4.0`, SIFTS `EMBL-EBI-terms`, KLIFS `none-stated`)을 스냅샷 목록과 보고서에 그대로 보여 주고, KLIFS는 "이용 조건 명시 없음(none-stated)"으로 항상 표시한다. 사용자 결정으로 KLIFS 값의 보고서·외부 전송 사용은 따로 막지 않는다(현재 번호 대응 결과를 보내는 게이트 투영은 없다. M24 과학 전송 투영도 번호 대응·KLIFS 값을 넣지 않는다. 만들 때 이 표시를 함께 넘긴다).

## 예산 한도 변경 (M19, M22, M23)

- run 한도(비싼 계산 횟수·활동 시간)를 바꾸는 HTTP 경로는 셋이다: `POST /runs/{id}/docking/batches/limit_approval`(M19 일괄), `POST /runs/{id}/ligand/ga/limit_approval`(M22 GA), `POST /runs/{id}/sequence_ga/limit_approval`(M23 서열 GA). 사람이 각 화면에서 증액 승인 버튼을 누를 때만 불린다. 도구, M13 분석 흐름 계획·단계, M8 뷰어 명령·모델 응답, 작업 인자, 자율 루프는 이 경로를 부를 수 없고(코드에 다른 호출자가 없음을 테스트가 확인), 자동·무인 증액은 없다. 인증이 없으므로 "사람"은 loopback에 접근할 수 있는 같은 컴퓨터의 사용자다(위 신뢰 모델).
- 올리는 양은 그 일괄·GA의 그 시점 부족분뿐이고, 한 번에 그 하나의 필요량(일괄: 비싼 계산 51단위, 활동 시간 7800초 + 여유 60초. M22 GA: 비싼 계산 100단위, 활동 시간 15000초 + 여유 60초 이하. M23 서열 GA: 비싼 계산 140단위(최대 예약 130단위), 활동 시간 15000초 + 여유 60초 이하)을 넘지 않는다. 부족하지 않으면 아무것도 바꾸지 않는다. 올린 한도는 되돌리지 않고 run 끝까지 남는다.
- 모든 증액은 `budget_limit_updated`(`by: "human"`) 이벤트로, 바뀐 축의 전·후 한도·증가분·필요량·부족분·`batch_input_sha256`(GA·서열 GA는 `selection_sha256`·`reserved_units`)과 함께 먼저 기록된다(events-only 재생 가능). 증액은 첫 비싼 계산 승인을 만들지 않고, 예약·과금·환불하지 않으며, 소진된 사용량을 지우지 않는다. dry-run run과 취소된 run은 거절하고 아무것도 쓰지 않는다.
- 외부 비용(토큰·USD) 한도는 이 경로로 바뀌지 않는다. M24 과학 전송에도 한도를 바꾸는 경로가 없다.

## 자격 증명

- 저장 위치: 서버 환경변수 `OPENROUTER_API_KEY`나 루트 `.env`(`.gitignore`의 `.env*` 규칙으로 제외, 단 `.env.example`은 허용). 게이트는 환경변수를 먼저 보고, 없으면 `.env`를 읽는다. `.env`가 일반 파일이 아니거나 그룹·기타 권한 비트가 있으면(0600이 아니면) 무시한다. keyring은 설치 선택 항목에만 있고 코드는 읽지 않는다. 브라우저 설정, localStorage, 요청 본문, 소스 코드에는 넣지 않는다.
- 사용 시점: 뷰어 의도·M3 결정은 온라인 모드에서 게이트가 transport 안에서 `Authorization` 헤더를 붙일 때만 읽고 local 모드에서는 읽지 않는다. M24 과학 전송은 뷰어 모드와 무관하게, 과학 전송 동의가 켜진 run에서 승인 대조·dry-run·동의·취소·외부 전송 멈춤·전송 상한·예산·pin 검사를 모두 통과한 뒤에만 전송마다 한 번 읽는다(그 전에 거절되면 읽지 않음). dry-run run과 동의가 꺼진 run에서는 읽지도 transport를 만들지도 않는다. 상태·미리보기·capability는 키를 읽지 않는다.
- 노출 금지: 이벤트, egress 감사 기록, 캐시, API 오류, 프런트엔드, 보고서, 스크린숏, 테스트 출력, 검토 증거 파일 목록. 오류는 안전한 enum과 HTTP 상태 번호로만 만든다. `str(exception)`, 응답 본문, 헤더를 그대로 쓰지 않는다.
- 테스트는 가짜(sentinel) 키만 쓰고, 만들어진 모든 산출물에 그 키가 나오지 않는지 검사한다. 실제 `.env`를 읽는 테스트는 없다.
- 교체·폐기: OpenRouter 콘솔에서 새 키를 발급하고 `.env` 값을 바꾼 뒤 백엔드를 다시 시작한다. 이전 키는 콘솔에서 폐기한다. 키가 이벤트나 커밋에 들어갔다면 즉시 폐기하고 사용자에게 알린다.

## 감사 기록

외부 요청은 run 이벤트 스트림에 audit_id로 묶어 전송 전에 먼저 기록하고 fsync한다. 감사 기록 저장에 실패하면 보내지 않는다.

| 상태 | 기록 내용 |
|---|---|
| denied / unavailable | reason_code, 안전한 설정 요약. `transport_invoked=false`, `sent=false`. 거부된 원문 payload는 저장하지 않음 |
| prepared | 승인된 정확한 본문, payload 해시, 목적지, 모델 alias, 질문 버전, 예산 예약 |
| dispatch_started | transport 호출 직전. `sent=unknown` |
| response_received | HTTP 상태, 검증된 모델·사용량, payload 해시. 서버가 응답했으므로 `sent=true`(400/401 응답도 전송된 것) |
| transport_failed | 안전한 오류 enum. `sent=unknown` |
| cache_hit | `sent=false`, 과금 없음 |

재시작 시 결과 없이 끝난 `dispatch_started`는 `delivery_unknown`으로 남기고 자동으로 다시 보내지 않는다. 사용량이 보고되지 않았으면 0이 아니라 "알 수 없음"이다. 보수적인 예약을 유지하고 추가 온라인 지출을 막는다.

M24 과학 전송의 감사는 같은 `egress` 이벤트에 `scope: "science"`와 `send_id`를 더한다. 거절은 첫 실패 하나만 `denied`(`reason_code`, `egress_stopped`면 `stop_reason`, `transport_invoked=false`, `sent=false`)로 남긴다. `prepared`는 승인된 정확한 본문 객체(`body`), `payload_sha256`, `projection_sha256`(투영의 `wire_sha256`), 목적지, 요청 모델, 질문 버전, 예약을 담는다. 예약은 `budget_reserved{audit_id, send_id, external_tokens, usd}`이고 비싼 계산 축이 없다. 예약 뒤 보내지 못하면(`prepared` 저장 실패, 취소, 동의 끄기, 시간 소진) 음수 `egress_budget_settled`를 먼저 쓰고 `dispatch_skipped` 감사를 쓴다(미정산 예약을 남기지 않음). 응답을 받으면 `response_received`(HTTP 상태, 응답 해시, 허용 스냅숏일 때만 응답 모델, 사용량) → 정산 → `settled`. 응답 본문·헤더·원시 provider 오류는 기록하지 않는다.

이 밖에 이벤트로 남는 것: run 생성과 모드 변경(`run_egress_changed`/뷰어 동의), M24 과학 전송 동의(`jev_science_consent_changed`), 사람의 과학 전송 승인(`jev_send_approved`, `approved_by: "human"`, 감사보다 먼저), 과학 전송 dispatch(`jev_science_dispatch_started`)와 결과(`jev_send_outcome`), 비싼 계산 승인, 예산 예약·과금·checkpoint, 사람의 한도 증액(`budget_limit_updated`, `by: "human"`, 일괄·GA 맥락), 일괄 행·요약 게시(`docking_batch_row_published`, `docking_batch_published`), GA 개체·요약 게시(`ligand_ga_individual_published`, `ligand_ga_published`), 작업 상태 전이와 프로세스 신원, 뷰어 의도·명령·확인, 저장된 보기·그림, 보고서 생성, 분석 계획·실행의 요청 입장·승인·철회·중지·단계 dispatch·시도·완료(`analysis_*`), 번호 대응이 쓴 참조 스냅샷 세트(`reference_snapshot_set@1` 객체).

## 파일 시스템과 입력

- run ID와 객체 접근은 설정된 runs 루트 안으로 제한한다. 심볼릭 링크를 따라가지 않고(`O_NOFOLLOW`), run 간 handle을 섞으면 거부한다.
- 사용자는 파일 시스템 경로, 실행 파일, 모듈 이름, 환경변수, 출력 디렉터리를 지정할 수 없다. 작업 dispatch 표는 코드에 고정되어 있고, 요청은 프로토콜 ID와 과학 파라미터만 담는다. ProLIF 작업 프로세스 인터프리터 경로는 관리자 설정(`.deps/prolif/venv-locked/bin/python`)이며 요청 본문으로 바꿀 수 없다.
- fpocket 실행 파일 경로는 관리자 설정(`.deps/fpocket/env/bin/fpocket`)이며 요청으로 바꿀 수 없다. 사용자는 argv·설정 파일·출력 모드를 지정할 수 없고, fpocket이 만든 PyMOL/VMD 스크립트는 실행하지 않는다. 출력은 작업 루트 안의 알려진 파일만 읽고 링크·특수 파일을 거부한다.
- 업로드 한도는 구조 25 MiB, M11 화학 입력 10 MiB, 포켓 투영 입력 10 MiB, 화학 요청 본문 512 KiB(M19 일괄·M22 GA 시작 전 확인·증액 승인 본문도 512 KiB), 분석 계획 요청 본문 1 MiB(저장 계획 JSON도 1 MiB), 그 밖의 분석 흐름 요청 본문 64 KiB, 보기 본문 64 KiB, 그림 본문 8 MiB(base64 포함 약 10.7 MiB), M24 JEV POST 본문 4 KiB다.
- 분석 흐름 요청은 목표 이름·명시 입력·same-run handle만 받고 알 수 없는 필드를 거부한다. 도구 이름·스크립트·URL·실행 파일·경로·식은 받지 않으며, 단계는 서버의 체크인된 템플릿이 만든다. 자식 호출·작업·보고서의 내부 실행 연결(`execution_link`)은 서버 코드만 만들고 HTTP 요청으로 넣을 수 없다. 흐름이 소유한 작업은 `/jobs`에서 수동 시작·재시도할 수 없다.
- 다운로드 파일 이름은 서버가 handle 앞부분으로 만든다. 저장된 보기 이름이나 업로드 파일 이름을 파일 경로, HTML, 외부 전송 내용으로 쓰지 않는다. 미리보기는 식별자를 이스케이프하고, Markdown이 원격 이미지나 스크립트를 불러오지 않게 한다.
- 객체 payload 해시가 맞지 않거나 handle이 조작되었으면 실패로 처리하고 신뢰하지 않는다.

## 개발 환경 가드

- Bash 도구 사용 전 훅(`.codex/hooks/pre_tool_use.py`)이 `rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE`을 차단한다. Claude Code와 Codex가 같은 훅을 쓴다.
- 커밋이나 push는 사용자가 명시적으로 요청했을 때만 한다. 검토 증거 경로에는 `.env*`, `.venv`, `references/`를 넣을 수 없다.
