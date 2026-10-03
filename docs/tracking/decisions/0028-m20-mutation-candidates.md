# 0028. M20 변이 후보는 한 전처리 구조의 위치(포켓·리간드 껍질·직접 선택의 합집합)마다 단일 치환 목록만 만들고, 근거 있는 보호 잔기를 기본으로 빼며, 점수·순위·효과를 말하지 않는다

- 상태: 채택 (사용자 결정 2026-10-03, M20 명세 확정 때 사용자가 추천안을 골랐다. 아래 "조율 세션이 정한 것"은 사용자가 최종 확인에서 바꿀 수 있다)

## 배경
M20은 단백질 공학 탭의 첫 기능이고 여는 시나리오는 "포켓 잔기 변이 스캔"(로드맵 M20: 포켓 주변 위치 × 허용 잔기, 촉매·보호 잔기 기본 제외)이다. 이 단계는 목록 단계일 뿐이며 변이 구조 모델링·평가는 M21이다. 위험은 다섯 가지였다: 후보 목록의 순서나 보호 판정이 추천·안전·순위처럼 읽히는 것, 검사하지 않은 보호(주석 없는 KLIFS 부위, 데이터베이스가 없는 촉매 잔기)가 "없음"이나 0으로 보이는 것, 다른 구조의 포켓·번호 대응·주석이 섞이는 것, 위치가 많을 때 조용히 잘리는 것, 잔기 식별자(변형 이름, null label, 같은 서열의 여러 체인)가 합쳐지거나 바뀌는 것.

## 결정 (사용자, 2026-10-03)
- **위치 출처 셋, 요청마다 고른 것의 합집합**: 포켓 검출(같은 구조의 저장된 `pocket_set@1`에서 고른 순번의 안쪽 잔기), 리간드 껍질(고른 리간드 중원자에서 반경 이하의 단백질 잔기), 직접 선택(잔기 목록). 한 잔기가 여러 출처에 있으면 위치 행 하나에 출처 목록으로 남는다.
- **기본 보호는 근거 있는 것만**: 사용자 보호 목록, KLIFS 주요 부위 10개(M16 주석을 줬을 때만, `status == "annotated"` 부위), 금속 근접(프로젝트 기존 `METALS` 목록 Zn·Mg·Ca·Mn·Fe·Cu·Co·Ni·Na·K, 기본 3.0 Å, 요청마다 1.0–5.0 Å), 이황화 Cys(SG–SG ≤ 2.5 Å 고정 상수, 모든 체인). 보호 잔기는 이유와 함께 제외 목록에 남는다.
- **촉매 잔기 데이터베이스는 없다**: M-CSA 등은 M26이다. 이 단계는 결과·화면·보고서에 "사용할 수 없음"(`not_available`, `not_implemented`)으로만 표시하고 촉매 잔기를 추측하지 않는다.
- **단일 변이만**: 위치마다 원래 잔기를 뺀 표준 19종(요청에서 허용 목록을 줄일 수 있음). 동시 변이는 M23이다.
- **후보 정보는 기하 사실만**: 원래·바꿀 잔기, 잔기 7필드, 번호 대응(참조값), 위치 출처, 리간드까지 중원자 최소 거리, 보호 이유. 점수·순위·안정성·ΔΔG·친화도·활성 값은 없다.
- **보호 해제는 잔기를 지정해서, 그 잔기의 보호 사유 전부를 한꺼번에**(사유별 해제 없음).
- **표와 보고서만**: Mol* 강조·CSV/JSON 내려받기는 없다. 보고서 `mutation_candidates`는 있다.
- **새 값싼 도구 + 새 불변 결과**: `generate_mutation_candidates`(`Run.call`, `cost_class: cheap`, 작업 큐·승인·예산 단위 없음) → `mutation_candidate_set@1`.
- **전처리 구조만**(`prepared_structure`). 원본·화학 작업용·OpenMM 최소화 구조는 받지 않는다.
- **변형 이름은 M12와 같은 10개만 표준으로 인정**: `HID`·`HIE`·`HIP`·`HSD`·`HSE`·`HSP`→`HIS`, `CYX`→`CYS`, `ASH`→`ASP`, `GLH`→`GLU`, `LYN`→`LYS`. 그 밖의 이름(MSE 등)은 `non_standard_residue`로 제외하고 원래 `resname`은 식별자에 그대로 남는다.
- **주석 없이 요청하면 진행하고 "검사하지 않음"을 남긴다**: `protection_checks.klifs_key_sites.status = "not_checked"`(`annotation_not_given`), 위치의 `klifs_sites`는 null. 화면은 같은 구조의 주석이 있으면 가장 최근 것과 그 주석이 기록한 번호 대응을 미리 고르고, 주석이 없으면 요청 영역에 "검사하지 않음"을 눈에 띄게 알린다.
- **명세 수정(착수 확인 M1, 사용자 승인)**: 사전 검사 훅의 `store`는 이벤트 로그와 run ID를 가지므로, `pocket_set`은 store 기반 RunView로 `pocket_bundle.validated_pocket_set`을 불러 게시가 끝난 결과인지까지 확인한다(내용만 보는 검사는 취소·오래된 시도의 미게시 객체를 받아들인다). 실패하면 `pocket_set_invalid`.
- **명세 수정(착수 확인 A1, 사용자 승인)**: `ligand_shell`이 켜졌는데 `ligand`가 null이면 리간드 수와 상관없이 `ligand_required`(자동 선택 없음)이며 `ligand_invalid`보다 먼저 검사한다. `ligand_invalid`는 null이 아닌 선택자가 리간드 하나로 해석되지 않을 때만이다.
- **명세 수정(착수 확인 A2, 사용자 승인)**: `/capabilities`에는 도구 목록이 없으므로 "도구 목록"은 `GET /tools`에 나타나는 것이고, `/capabilities`의 `methods.mutation_candidates`는 M16 `reference_site_annotation`처럼 항상 `{available: true, reason_code: null, reason: null}`이다(run의 저장 객체만 읽음).

## 조율 세션이 정한 것 (사용자가 최종 확인에서 바꿀 수 있음)
- **닫힌 이름**(`backend/mw/mutation_constants.py`): 출처 종류 `pocket`·`ligand_shell`·`user`, 보호 사유 4개(`user_protected`, `klifs_key_site`, `metal_contact`, `disulfide_cys`), 제외 사유 6개(보호 사유 4개 + `non_standard_residue`, `no_allowed_alternative`, 저장 순서 `non_standard_residue` 먼저), 위치 상태 `candidate`·`excluded`, 해제 효과 `released`·`none`, 번호 상태 `mapped`·`unmapped`·`conflict`·`not_in_map`, `protection_checks` 키 5개와 상태 `checked`·`not_checked`·`not_available`, 입장 reason_code 17개(순서 고정), `too_many_positions`.
- **고정 한계 문장 5개**(결과 `limitations`, 보고서, 화면에 문자 그대로): `docs/business-rules.md` "변이 후보 (M20)".
- **상한**: 위치 400, 잔기 목록(직접·보호·해제)·포켓 순번 각 400. 넘으면 잘라 저장하지 않고 거절한다(위치는 `resource_exceeded` 429 `too_many_positions`, 목록은 `argument_invalid`).
- **기본값·범위**: 리간드 껍질 반경 기본 5.0 Å(1.0–12.0, 양끝 포함), 금속 거리 기본 3.0 Å(1.0–5.0), 이황화 2.5 Å(요청 필드가 아님).
- **해제 범위**: 해제는 보호 사유 전부를 한꺼번에 푼다. 보호 사유가 없는 잔기를 해제하면 오류가 아니라 `effect: "none"`으로 기록한다. 같은 잔기를 보호와 해제에 모두 넣으면 `protect_release_conflict`로 거절한다. 해제는 `non_standard_residue`·`no_allowed_alternative`에 영향이 없다.
- **여러 출처의 위치는 행 하나**(출처 목록). 체인은 같은 서열이어도 합치지 않는다.
- **후보 0개는 유효한 빈 과학 결과**(`null_result: true`), 실패가 아니다.
- **읽기 라우트 4개와 필터·정렬 값**: 목록, 상세, 위치 페이지(`status`·`source`·`exclusion_reason`·`chain_auth`, 정렬 `order`·`ligand_distance`), 후보 페이지(`position_index`·`to`). handle은 쿼리가 아니라 URL **경로**에 `{handle:path}`로 넣는다(M18·M19 읽기의 `?handle=`와 다름).
- **번호 대응·주석은 둘 다 선택 입력**이며 둘 다 주면 주석이 기록한 `numbering_map`과 같아야 한다(`annotation_map_mismatch`).
- **바꿀 히스티딘의 양성자 상태와 후보 구조의 형태는 정하지 않는다**(M21).
- **M13 분석 흐름에서 이 도구를 부르지 않는다**(M17–M19와 같음). 기존 `define_mutations`(구현만 있고 노출되지 않음)는 바꾸지 않는다.
- **새 실패 이유 `candidate_set_invalid`**: 도구 구현이 만든 결과가 `validated_set`을 통과하지 못하면 저장하지 않고 `input_invalid`(422) `candidate_set_invalid`로 실패한다(입장 검사 이유가 아니라 구현 단계의 실패. 저장되었는데 읽을 수 없는 결과를 만들지 않기 위해, 독립 코드 검토 수정).
- **수소만 있는 리간드는 `ligand_invalid`**: 선택한 리간드 인스턴스에 중원자가 없으면 사전 검사에서 거절한다.
- **중원자가 없는 잔기의 `ligand_min_distance_A`는 null**(0이 아님). 리간드를 줬어도 그 위치만 null이며 화면은 "— (중원자 없음)"으로 보인다.
- **화면은 리간드를 자동으로 고르지 않는다(하나뿐이어도)**: 명세 10절 "리간드가 있으면 선택자, 여럿이면 직접 선택"의 느슨한 문구와 다르게, 전처리 구조·포켓 결과·리간드 어느 것도 자동으로 고르지 않는다(명시적 편차, 사용자가 바꿀 수 있음). 예외는 주석과 그 번호 대응의 미리 선택뿐이다(사용자 결정).
- **보고서에서 "촉매"는 허용**: M16 보고서는 "촉매"를 금지어로 두지만, M20 보고서는 필수 문장 "촉매 잔기 데이터베이스: 사용할 수 없음"을 써야 하므로 금지어 목록에 넣지 않았다. 역할 주장은 하지 않는다(촉매 잔기를 판정하지 않았다고만 씀).

## 검토한 대안
- 출처 하나만(포켓만): 로드맵 시나리오는 포켓 주변이지만 리간드가 있는 구조에서는 껍질이, 이미 아는 위치는 직접 선택이 더 정확하다. 사용자가 셋의 합집합을 골랐다.
- 보호 기본값에 서열 보존성·촉매 추정(His·Asp·Ser 등 이름 규칙): 근거 없는 추측이며 데이터베이스는 M26이다. 사용자가 "근거 있는 것만"을 골랐다.
- 주석이 없으면 거절: KLIFS 대상이 아닌 단백질에서 도구를 쓸 수 없게 된다. 진행하되 `not_checked`로 남기기로 했다.
- 사유별 해제: 해제 규칙과 화면이 복잡해지고, 하나만 풀린 위치를 오해하기 쉽다. 잔기 단위로 모두 해제한다.
- 위치 400 초과 시 앞에서부터 잘라 저장: 조용한 잘림은 금지(절대 조건 6). 거절하고 위치 수를 알려 준다.
- 보존적 치환·위치별 허용 잔기: 이번 범위 밖(명세 1절).
- 뷰어 강조·CSV 내려받기: 사용자가 표와 보고서만 골랐다.
- 작업 큐 경로(비싼 계산): 저장 좌표에서 최소 거리를 재는 일이라 값싼 도구로 충분하다(위치 400 × 후보 19 결과 0.90 MiB, 이벤트 한 줄 1.20 MiB).
- 읽기 라우트를 M18·M19처럼 `?handle=`로: 하위 경로(`/positions`, `/candidates`)를 두기 위해 경로 handle을 썼다(라우트 등록 순서 주의, `docs/engineering-notes.md`).

## 결과
- 착수 확인(`docs/qa/m20-mutations-20261003/preflight.txt`): 기존 읽기 경로(`structure_residues`·`_parse`·`METALS`)로 필요한 값을 모두 얻는다. 실제 pocket_set·번호 대응·주석 객체의 필드는 명세와 같았고, 다른 점은 위 M1(검증 방법)뿐이었다. 1MQ4 + ADP·1HSG + MK1 독립 numpy oracle을 남겼다(1MQ4: ADP 5.0 Å 껍질 20위치, MG 근접 ASN261·ASP274, 이황화 0쌍. 1HSG: 같은 서열 두 체인, 금속 없음).
- 단백질 공학 탭은 더 이상 "사용할 수 없음" 안내가 아니라 변이 후보 화면이다(변이 구조 모델링이 아직 없다는 한 줄은 패널 안에 둠). 이제 어느 탭에도 안내가 없다.
- 하지 않게 된 것: 동시 변이, 위치별 허용 잔기·보존적 치환, 구조 모델링·에너지·점수, 촉매 잔기 판정, Mol* 강조, 내려받기, M13 흐름 확장, 원본·최소화 구조 입력.
- 조율 세션이 정한 항목은 사용자의 최종 확인(M20 완료 승인) 때 함께 확인받는다. 변경 요청이 있으면 이 결정을 고친다.
- 규칙 전체: `docs/business-rules.md` "변이 후보 (M20, `generate_mutation_candidates`)". API: `docs/contracts.md` "M20 변이 후보". 완료 기록: `docs/tracking/m20-acceptance.md`.
