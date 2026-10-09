# 0034. M26 효소 반응 지식 연결은 사용자가 실행하는 가져오기 명령 하나가 세 공개 서버(M-CSA API·UniProt REST·Rhea)에서 받은 가공 참조 스냅샷(M15와 별개 가족)을 서버가 읽기만 하고, 값싼 도구가 M-CSA에 적힌 PDB 항목 기준으로 구조 잔기를 대응해 촉매 잔기·UniProt 부위·반응 정보를 참조값으로 보이며, M-CSA "대응됨" 행만 M20 v2 후보 집합의 기본 보호 근거로 쓴다

- 상태: 채택 (사용자 결정 2026-10-08, M26 명세 확정 전 질문에서 모두 추천안을 골랐다(자유 입력 없음). 착수 확인(2026-10-08)과 실데이터 사전 검증(2026-10-09) 뒤의 추가 결정 ⑭–⑱도 추천안이다. 아래 "조율 세션이 정한 것"은 사용자 선택이 아니며 최종 확인에서 이의를 받는다). 결정 0005·0015의 "외부 HTTP는 `EgressGate`만"(0005의 "새 외부 기능(데이터베이스 조회 등)도 같은 게이트를 거친다" 포함)에 사용자가 실행하는 가져오기 명령 하나의 예외를 둔다(사용자 결정 ①). 결정 0022(kbase 가공 스냅샷을 가져오기 명령으로)·0028(M20 촉매 잔기 데이터베이스 "사용할 수 없음")의 다음 단계이고, 실서버 요청 한도는 결정 0012처럼 사용자가 정했다.

## 배경
M20은 촉매 잔기 데이터베이스 보호 검사를 "사용할 수 없음"(`not_available`, `not_implemented`)으로 두었다(결정 0028). M15 참조 스냅샷(`../kbase_kinase/ref` 가공본)에는 M-CSA·Rhea·UniProt 기능 주석이 없고 SIFTS는 약 658체인(kinase)뿐이라 일반 효소 구조를 다룰 수 없다. 로드맵 M26은 M-CSA 촉매 잔기와 Rhea·UniProt 반응 주석을 지식 탭에 연결하는 단계다(여는 시나리오 "반응 정보를 보며 효소 서열 변경", 선행 M15). 위험은 다섯 가지였다: 서버·도구가 네트워크를 쓰게 되는 것, 참조값이 ProtView의 판정(역할·활성·효과)으로 읽히는 것, M-CSA가 다루지 않은 체인이 "검사했고 없음"으로 보여 보호 장치가 거짓으로 "검사함"이 되는 것, M20 변경이 저장된 v1 집합과 M21·M23·M24·M25 기록 바이트를 흔드는 것, 잔기 7필드·M-CSA 항목을 합치거나 하나를 고르는 것.

## 결정 (사용자, 2026-10-08·09)
- ① **자료는 가져오기 명령이 공개 서버에서 받는다**: `scripts/import_reaction_references.py`가 M-CSA API(`www.ebi.ac.uk`)·UniProt REST(`rest.uniprot.org`)·Rhea(`www.rhea-db.org`)에서 받아 가공한다(`docs/security.md`의 "가져오기 명령은 네트워크 없음"을 이 명령에 한해 고친다).
- ② **적용 범위는 M-CSA에 적힌 PDB 항목 기준**이다(M15 확장·kinase 한정이 아님). UniProt 위치 → 구조 잔기 연결은 M15 번호 대응이 있는 체인에서만 한다.
- ③ **M20 촉매 칸을 켠다**: 새 보호 사유 `catalytic_residue`, 선택 입력 `catalytic_annotation`, M21·M23 재사용 종료를 수용한다.
- ④ **뷰어 표시 없음**(표·보고서만). ⑤ **M-CSA 역할 문구는 영어 원문 그대로 참조값**으로 보인다(번역·요약·해석 없음).
- ⑥ **보호 근거는 M-CSA "대응됨"(`matched`)만**이다. 충돌·대응 없음은 보호하지 않고 눈에 띄게 알린다.
- ⑦ **개발·검증 중 실서버 요청 한도**: 전체 가져오기 2회(둘째는 재현 비교) + 형식 확인용 탐색 요청 100건 이하 + RCSB 공개 구조 mmCIF 3개(CC0).
- ⑧ **수집 범위**: M-CSA에 나오는 accession 전부 + M15 kinase 세트의 `status: ok` accession(실측 541개) + 가져올 때 직접 지정한 accession. Cofactor 문구는 저장하지 않고 부위는 Active site·Binding site·Site 셋이다.
- ⑨ **후보 집합 v1·v2를 모두 받는다**(저장된 v1 집합은 바이트 그대로 유효).
- ⑩ **가져오기는 원자적이고 파생 accession의 실패는 건너뛰고 기록**한다.
- ⑪ **대응됨 행은 모두 보호 근거**다(기준 구조 행·역할로 거르지 않음). ⑫ **M-CSA가 다루지 않은 체인은 "검사하지 않음"**이다.
- ⑬ **직접 지정한 accession이 하나라도 받아지지 않으면 명령 전체를 거절**한다(자동 대체 없음).
- 착수 확인 뒤(2026-10-08): ⑭ M-CSA `main_annotation`(목록 응답에서 늘 빈 문자열)은 저장하지 않는다. ⑮ 받지 못한 accession 이유에 `demerged`를 더하고 대상 accession 목록(`target_accessions`)을 그대로 기록한다. ⑯ Rhea는 방향 없는 대표 반응 전부(실측 18,611개)다. ⑰ 수락 QA용 공개 구조는 `1S9I`·`1A30`·`1A4I`다.
- 실데이터 사전 검증 뒤(2026-10-09): ⑱ UniProt 부위가 같은 accession의 동형체 위치(`location.sequence` = `<같은 accession>-<n>`)면 그 부위만 건너뛰고 나머지는 저장한다. 건너뛴 개수는 명령 출력에만 보인다(실측 P12821의 Binding site 3개).

## 조율 세션이 정한 것 (사용자 선택이 아님, 최종 확인에서 이의를 받는다)
- **검사 범위**: M-CSA가 다루지 않은 체인의 위치는 `catalytic: null`이고, `catalytic_residue_database.status`는 위치를 가진 모든 체인이 `covered`일 때만 `checked`다(그 밖에는 `not_checked` `chains_not_covered`, 그래도 `covered` 체인의 `matched` 행은 보호한다).
- **미리 고르기**: M20 요청 영역은 같은 구조의 가장 최근 M26 결과를 미리 고르되 자동 제출은 없고, 결과가 없으면 "검사 안 함"(UK2)을 알린다(결정 0028의 KLIFS 주석 미리 고르기 예외의 확장).
- **체인 대응은 저자 체인 ID만**(조립체 이름 바꿈·형제 체인 전파 없음). 해제된 위치는 새 필드 없이 사유 목록이 남고 "해제됨"으로 표시한다. M15 세트가 없어도 가져오기는 kinase 목록 없이 진행한다(`m15_kinase_list: "absent"`).
- **배지·문구는 세대가 아니라 `catalytic_residue_database.status` 기준**이다. 사용자는 "v1 배지·세대별 문구"를 골랐지만 v2인데 검사하지 않은 집합이 검사한 것처럼 읽히지 않도록, `checked`가 아닌 집합은 모두 같은 "촉매 잔기 검사 안 함" 표시(상세 이유는 따로)이고 문구는 `not_available`·`not_checked`·`checked` 셋이다.
- **UniProt 부위는 보호에 쓰지 않고** M20 요청 영역에 그 사실을 한 줄 알린다(UK3). 새 참조 가족(`.deps/reaction_reference/`, `MW_REACTION_REFERENCE_DIR`, `reaction_active@1`)은 M15와 따로 둔다.
- **닫힌 이름 전부**: 도구 `link_reaction_knowledge`, 결과 `reaction_knowledge@1`(`mw.reaction_knowledge/v1`), 매니페스트 `reaction_reference_set@1`, 상태 `reaction_reference_status@1`, 보고서 `reaction_knowledge`, M20 `mw.mutation_candidates/v2`, 입장 이유 아홉 개와 그 순서, 절 상태·`coverage` 셋·행 상태 셋·`unmatched` 이유 다섯·`conflict` 이유 둘·UniProt 이유 셋·연결 상태 둘·`link_reason` 셋·건너뜀 이유 다섯·M20 `uncovered_chains[].coverage` 넷, 상한(결과 1 MiB·연결 위치 2,000·M20 충돌/대응 없음 목록 각 400). 조정 가능한 기본값은 `MAX_ACCESSIONS` 20,000·`MAX_SKIPPED` 50·요청 제한 시간·크기·간격·재시도·읽기 페이지다.
- **고정 문장 RK1–RK6·UK1–UK4·M20 한계 문장 셋째의 변형 둘·M24 J6n·J6c 문구는 초안이다(승인 대기: 사용자 최종 확인).** J6n·J6c는 `STATEMENTS`(J1–J7)가 아닌 별도 상수 `J6_BY_CATALYTIC_STATUS`에 두고 `not_available`이면 기존 J6 바이트 그대로다. M25 문장 LJ1–LJ8·UL1–UL3은 바꾸지 않는다.
- **실측 반영(T1)**: `residue_sequences[].resid`(UniProt 서열 위치)는 버리고, `reference_uniprot_id`는 원문 그대로 저장하되 `,`로 나눠 accession 집합을 계산하며(74개 항목이 여럿), `assembly`의 빈 문자열은 null, UniProt `protein_name`은 `recommendedName`이 없으면 `submissionNames[0]`, `ec_numbers`는 `proteinDescription` 안 모든 `ecNumbers`의 합집합이다. 부위 위치가 EXACT 정수가 아니면 설치를 멈추고, Rhea 행 수가 `limit` 이상이면 형식 오류이며, 받지 못한 accession은 하나씩 한 요청으로 분류한다. `catalytic_residue_database.annotation` 값은 결과 handle 문자열이다(KLIFS 칸 선례).
- **PDB 경로 세부**: 삽입 코드 → `unmatched`(`insertion_code_present`), 같은 번호 여럿 → `ambiguous_residue_number`, 이름 대응은 M20 `standard_name`과 같은 표준 20종 + M12 이름 10개, M-CSA `resid`와 구조 `seq_label`은 비교하지 않고 값으로만, 조립체 이름은 무시. 반응 절은 EC·M-CSA 반응 화합물·UniProt 촉매 활동과 Rhea ID(`in_snapshot`)이며 Rhea는 촉매 활동의 Rhea ID로만 잇는다(EC에서 넓게 잇지 않음). M-CSA 메커니즘·그림은 저장하지 않는다.
- 독립 의도 감사(고정 전) 여덟 항목과 재점검 다섯 항목은 사용자에게 묻거나 사용자의 원칙("하지 않은 검사를 한 것처럼 보이지 않는다", "선택하지 않고 보여 준다")과 M15·M16·M20 선례에서 도출해 닫았다.

## 이유
- 가져오기를 사용자가 실행하는 명령 하나에 가두면 서버·도구·작업·보고서·화면은 계속 네트워크 없이 동작하고, 외부로 나가는 것은 고정 세 호스트에 대한 읽기 요청의 URL 질의(쪽 번호·accession 목록·열 이름)뿐이다.
- PDB 항목 기준 대응은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같을 때만 "대응됨"이므로 서열 정렬 같은 추정이 끼지 않는다. 다루지 않은 체인을 null로 두면 보호 칸이 거짓으로 "검사함"이 되지 않는다.
- 새 세대(v2)로 칸을 켜고 `validated_set`이 `method_version`으로 가르면 저장된 v1 집합·보고서·M24 투영·`jev_choice@1`·M25 기록의 바이트가 그대로다.
- 참조 가족을 M15와 나누면 M15 폴더·형식·세트 해시·번호 대응 코드를 건드리지 않는다.

## 검토한 대안 (기각, 되돌리지 말 것)
M15 스냅샷을 효소 일반으로 확장, kinase에만 한정, 사용자가 받은 파일을 넣는 수동 방식, M20 연결 없이 보호 목록에 직접 입력, M16처럼 뷰어 강조·범례, 역할 문구 생략, 충돌 위치·UniProt Active site를 보호 근거에 포함, 기준 구조 행만 보호하거나 역할로 거르기, 새 계산·전송을 v2 집합에만 허용(기존 테스트 자료·골든 부담), 가져오기 완전 원자적(건너뜀 없음)·출처별 부분 설치, 병합된 accession 자동 대체, 없는 체인을 "검사했는데 없음"으로 보기, "해당 없음" 선언 칸, 형제 체인으로 전파, Cofactor 문구 저장, 직접 지정 accession 자동 이어받기, 실제 응답 조각 커밋.

## 외부 요청 규칙의 예외
- 외부 HTTP는 여전히 `EgressGate`만 보낸다. 예외는 사용자가 터미널에서 실행하는 `scripts/import_reaction_references.py` 하나이며, 허용 호스트 셋(`ALLOWED_HOSTS` = `www.ebi.ac.uk`·`rest.uniprot.org`·`www.rhea-db.org`, 정확히 일치)에 HTTPS GET만 보낸다. 고정 `User-Agent`와 `Accept-Encoding: identity` 말고는 헤더가 없고 키·쿠키·인증 헤더·사용자 데이터·구조·서열을 보내지 않는다. 환경 프록시를 쓰지 않고 리다이렉트를 따르지 않으며(3xx는 실패), 호스트·스킴을 바꾸는 CLI 옵션·환경변수가 없다(시험 전용 loopback 우회는 라이브러리 인자뿐). 요청마다 URL·상태·바이트·본문 SHA-256을 요청 기록에 남긴다.
- 서버·도구·작업·보고서·화면·테스트·오프스크린 QA는 외부 요청을 하지 않는다(새 M26 모듈과 M20 두 파일의 import 검사, `httpx`는 `egress/` 안). `request_science`·`httpx` 위치·`Run.raise_limits` 호출자(M19·M22·M23 셋)는 그대로다.
- 개발·검증 중의 탐색 요청과 RCSB 구조 내려받기는 ⑦의 한도 안에서 사람이 허용한 예외였다(가져오기 명령의 허용 호스트에는 RCSB를 넣지 않음).

## 실서버 요청 할당과 사용 (⑦)
- 탐색 요청 48/100(T1 착수 확인 46 + T9a 사전 검증 2), 전체 가져오기 2/2(import1·import2 각 22요청), RCSB mmCIF 3/3(`1S9I`·`1A30`·`1A4I`, 출처 기록 `backend/tests/fixtures/public_<id>.provenance.json`). 요청마다 `docs/qa/m26-reaction-20261008/network-ledger.txt`(95줄)에 남겼고, 가져오기 요청이 접촉한 호스트는 허용 셋뿐이며 모두 GET·200이었다. 실패한 요청을 몰래 다시 시도하거나 우회하지 않았다.
- 두 가져오기의 가공 파일 셋 SHA-256이 같아 재현되었다(세트 해시는 `imported_at` 때문에 다름). 이후 개발·검증 중 실서버 요청은 사용자가 새로 정해 줄 때만 한다.

## 수용한 대가
- 호출 키 해시 파일 중 바뀐 것은 `mutation_candidates.py` 하나다. 그래서 M21·M23 호출 키가 바뀌어 이전에 저장된 M21 변이 모델·M23 서열 GA 결과의 자동 재사용이 끝난다(같은 입력도 새로 계산, 과금). `golden_call_keys.json` 재기록의 차이는 세 값뿐이다(그 파일 SHA, M21 의존 pin, M21 호출 키. 모델 handle은 그대로).
- 업그레이드 전 큐에 있던 M21·M23 작업은 시작 때 과금 전에 412 `worker_version_invalid`로 거절되고 `claimed`로 남는다(취소 뒤 다시 제출).
- 진행 중이던 M25 단백질 루프의 계산 단계는 만들 때 고정한 해시와 달라 412 `capability_unavailable`(`missing_configuration`)로 막힌다. 끝난 루프는 읽기 바이트가 그대로이고 리간드 루프는 영향이 없다. 막힌 루프는 끝내고 새 루프로 이어 간다.
- 도구가 새로 만드는 집합이 v2라 `backend/tests/fixtures/sequence_ga/build_sequence_ga_fixtures.py --check`는 설계상 실패한다(`--write`하면 M23 테스트가 쓰는 v1 fixture를 덮으므로 하지 않는다).

## 결과
- 착수 확인(`docs/qa/m26-reaction-20261008/preflight-network.md`·`preflight-local.md`, 기준 main `72f4d1e`): 실제 응답 모양이 명세 초안과 다른 곳을 위 "실측 반영"으로 정리했다. 저장소 안 구조 1HSG·1MQ4·1UBQ와 파생 1HSG는 M-CSA에 없고 M15 SIFTS ∩ M-CSA는 1S9I 하나였다. 도구가 호출마다 해석·색인을 다시 하면 0.17–1.7초·최대 RSS 648 MB(합성 최악)라 세트 단위 해석·색인 캐시(한 세트, 성공만)를 두었다. J6 분기 시제품과 골든 기록기 선수정(`5672200`)으로 v1 바이트 불변을 먼저 증명했다.
- 소스 고정 `3fcac53`: 게이트, 새 기능 수락 58/58(`acceptance: true`, 외부 요청 0), M25 실행기 `--regressions` 사슬(M23은 하네스의 v1 기대로 실패 → 하네스 한 곳 수정 뒤 단독 재실행 35/35). 세부는 `docs/tracking/m26-acceptance.md`.
- 변경하지 않은 것: `docking_worker.py`·`docking_constants.py`·`openmm_mutation_worker.py`·`mutation_model_constants.py`·`mutation_model_math.py`·`ligand_ga_*`·`sequence_ga_*`·`docking_batch_*`, M17 코드, M13 흐름, M15 코드·폴더·형식, M16, `viewer_scene@2`·`viewer_figure@2`, M25 모듈과 문장, `request_jev`·`request_viewer`·뷰어 동의. M24 모듈은 J6 분기에 필요한 최소 확장만 했다(`jev_constants.py`·`jev_projection.py`·`jev_sends.py`·`jev_reports.py`, 골든 `golden_science_m24.json`·`golden_egress_events.json` `--check` 통과).
- 규칙 전체: `docs/business-rules.md` "효소 반응 지식 (M26, `link_reaction_knowledge`)"과 M20 절의 v2. API: `docs/contracts.md`. 보안: `docs/security.md`. 완료 기록: `docs/tracking/m26-acceptance.md`.

## 한계
- 촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 판정한 것이 아니다. "대응됨"은 PDB·체인·번호·잔기 이름이 같다는 뜻뿐이고 역할·활성을 뜻하지 않으며, 반응 정보는 효소 활성·속도·특이성·메커니즘 유지의 근거가 아니다.
- M-CSA에 PDB 항목이 없는 구조는 M-CSA 절을 검사할 수 없다(서열 정렬로 잇지 않음). 실데이터 수락 구조에서는 `unmatched`·`conflict` 행이 나오지 않아 그 경로는 합성 행과 합성 파생 구조로만 관찰했다.
- 아무 체인도 검사하지 않은 집합의 저장 객체에는 촉매 행 수·제외 사유 수가 0으로 남는다(화면·보고서는 "—"). 그 밖의 남은 조언은 `docs/tracking/findings.md`.

## 변경하려면 사용자 결정이 필요한 것
출처 셋·허용 호스트 셋·가공 파일 이름과 허용 필드(`SOURCE_FORMATS`), 부위 종류 셋, 건너뜀 이유 다섯, 절 상태·`coverage`·행 상태·이유 집합, 연결 상태·`link_reason`, 반응 절 상태, `accession_source`, 체인 `flags`, M20 `uncovered_chains[].coverage` 넷, 입장 이유 아홉 개와 순서, 고정 문장 RK1–RK6·UK1–UK4·M20 셋째 문장 변형·J6n·J6c, 상한(결과 1 MiB·연결 위치 2,000·M20 목록 각 400), 보호 근거의 범위(`matched`만·UniProt 부위 제외), `checked` 판정 규칙, 새 실서버 요청 할당. `MAX_ACCESSIONS`·`MAX_SKIPPED`·요청 제한 시간·크기·간격·재시도·읽기 페이지·폴링 간격은 조정 가능한 기본값이다.
