# 과학·도메인 규칙

ProtView의 결과는 연구실 구성원이 논문·보고서의 근거로 쓸 수 있다. 결과는 계산으로 뒷받침되는 것만 주장한다.

## 용어

- **handle**: `obj://<run_id>/<kind>/<sha256>` 형식의 불변 객체 식별자. SHA-256은 kind, schema, 정규화한 내용 바이트로 계산하고, 시각·호출 ID는 포함하지 않는다. 같은 내용이면 같은 handle이다.
- **호출 키(call key)**: 도구 이름, 도구 버전, 정규화한 유효 인자(기본값 포함), seed, dry-run 여부, 입력 내용 지문으로 만든 캐시 키. handle과 다른 개념이다. 호출 키가 같으면 캐시를 재사용하고, handle이 같으면 결과 내용이 같다는 뜻이다.
- **scientific_null**: 입력이 유효하고 계산도 성공했지만 조건을 만족하는 결과가 없는 상태(`null_result=true`). 실패가 아니며 재시도하지 않는다.
- **geometric contact**: 원자 좌표 사이 거리만으로 정한 접촉. 두 원자가 모두 N/O이면 `polar_contact`, 모두 C이면 `hydrophobic_contact`, 나머지는 `contact`로 분류한다. 원소만 보고 나눈 것이며 수소결합·염다리 판정이 아니다.
- **chemical interaction assignment**(M11): ProLIF가 사용자가 제공한 수소·연결 정보·화학 그래프로 판정한 상호작용 범주. geometric contact와는 다른 결과 종류이며, 둘 중 하나로 다른 하나를 덮어쓰지 않는다.

## 식별자

- 잔기 식별자는 7개 필드를 모두 가진다: `model_number`, `chain_auth`, `chain_label`, `seq_auth`, `seq_label`, `icode`, `resname`. 원본에 label 값이 없으면 `null`로 둔다. 추측으로 채우거나, 표시 문자열을 파싱해서 식별자를 만들지 않는다.
- 두 잔기는 7개 필드가 전부 같을 때(null은 null과만 같음)만 같은 잔기다. author 번호가 같아도 모델, 체인, 삽입 코드, label 중 하나가 다르면 다른 잔기다.
- 원자 식별자(AtomRef)는 structure handle, 잔기 7필드, `atom_name`, 정규화한 `altloc`(빈 문자열은 대체 위치 없음), `element`, `site_index`(선택한 소스 원자를 서버가 결정적으로 순회한 순번)로 이루어진다. 이름·altloc이 같은 중복 원자는 `site_index`로 구분하고, 첫 번째 것을 골라 쓰지 않는다.
- Mol*가 만들어 낸 label ID나 원자 이름은 표시용이다. 브라우저 선택을 서버 식별자로 되돌릴 때는, 실제 제공한 바이트의 SHA-256에 묶인 Mol* `sourceIndex` ↔ AtomRef 일대일 대응만 쓴다. 대응이 모호하거나 불완전하면 실패로 처리한다. 가장 가까운 좌표나 첫 번째 일치 항목으로 대신하지 않는다.
- 같은 이름의 리간드가 여러 개면 인스턴스별로 따로 다룬다. 이름만 보고 합치거나 첫 번째를 고르지 않는다.

## 구조 불러오기와 전처리

- 입력은 로컬 PDB/mmCIF 바이트, 최대 25 MiB. 비었거나 형식이 틀린 입력은 거부한다. 원격 구조 조회는 지원하지 않는다.
- 모델은 명시적으로 고른다(`model_index`). 암묵적으로 첫 모델을 쓰지 않는다.
- 지원하는 전처리 정책은 다음이 전부다:
  - altloc: `highest_occupancy`(기본), `first`. highest_occupancy는 점유율이 같을 때 안정적인 순서로 동점을 깨고, 공유 원자는 유지한다.
  - waters: `keep_all`(기본), `strip_all`.
  - hydrogens: `strip`(기본), `keep`.
  - missing_residues는 `leave_gaps`, symmetry_mates는 `ignore`만 가능하다.
- protonation, 누락 원자 재구성, 대칭 확장, bridging water는 지원하지 않는다. 요청하면 `input_invalid`로 거부한다. 요청만 기록해 두고 적용한 것처럼 보이게 하는 것은 금지다.
- 전처리 결과는 항상 `preparation_manifest`에 연결된다. manifest에는 선택한 모델, 원본 structure handle, 제거 개수, 모든 정책 값이 들어간다. identifier를 잃지 않도록 전처리 출력은 mmCIF로 보존할 수 있다. 모든 입력을 PDB로 변환하는 것은 허용하지 않는다.

## 기하 접촉 (`compute_interactions`)

- 입력: `prepared_structure`, 정확한 리간드 인스턴스, cutoff_A(2.5–6.0, 기본 4.0), 접촉 종류.
- 처리: 선택한 리간드의 중원자와 단백질 중원자 사이 유클리드 거리를 실제 좌표로 계산한다. cutoff 이하인 원자 쌍을 결정적인 순서로 기록한다.
- 출력: 행마다 잔기·원자 식별자 양쪽과 거리(Å). 저장값은 반올림하지 않는다.
- 리간드가 하나면 자동 선택하고, 둘 이상이면 `needs_selection`, 없으면 `no_ligand` 선제 조건 실패를 돌려준다. 어느 쪽도 "접촉 0개"가 아니다.
- 접촉 0개는 scientific_null이다. cutoff를 늘려 다시 시도하지 않는다.

## 대체 계산 방법

| 방법 | 계산 | 단위 | 의미하지 않는 것 |
|---|---|---|---|
| FreeSASA (M6) | 단백질 + 선택 리간드 1개. Lee–Richards 100 slices, probe 1.4 Å, 스레드 1. 단백질 매몰, 리간드 매몰, 총 SASA 손실, 잔기별 값 | Å² | 친화도, 에너지, 결정 전체 환경. 다른 리간드·물·이온은 제외한다 |
| OpenMM (M7) | 표준 단백질만. Amber14-all + GBn2, pH 7 수소 재구성, 제한된 최소화. `protein_only`와 `rebuild_pH7`를 명시적으로 확인해야 실행 | kJ/mol | 리간드 결합 에너지, ΔΔG, 안정성, Rosetta 점수 |
| 원자 거리 (M10) | 같은 소스의 정확한 원자 두 개 사이 원본 좌표 유클리드 거리 | Å | — 겹친 좌표의 0 Å은 정상 값이며 scientific_null이 아니다 |
| 강체 정렬 (M10) | 사용자가 고른 단백질 CA 쌍 3–1000개로 float64 Kabsch 회전(반사 금지) | RMSD Å | 모델 품질, 결합, 안정성. 선택한 쌍에만 해당한다 |
| ProLIF (M11) | 사용자가 준비한 수용체(명시적 수소, 완전한 연결 정보) + SDF 리간드 1개. 프로토콜 `prolif_prepared_explicit_h@1` | D···A 거리 Å, D–H···A 각도 ° | 실험적 수소결합 확인, 염다리 에너지, 친화도, 안정성 |

- FreeSASA의 Shrake–Rupley 1000점 설정은 단일 구·분리 구 해석 검사에서 오차 한도(0.5% 겹침 허용)를 넘어 채택하지 않았다. 실패 증거는 보존한다. 숫자를 보정해서 맞추지 않는다.
- 정렬 퇴화 조건: 중심화한 P, Q, H의 두 번째 특이값이 `max(1e-12, 1e-8 × 첫 번째)` 이하이면 `input_invalid`다. 세 점이 동일 평면에 있어도 한 직선 위만 아니면 유효하다.
- 원자 거리는 두 원자가 같은 소스일 때만 계산한다. 정렬 오버레이에서 서로 다른 층의 원자 거리는 거부한다. 표시용 변환 좌표와 원본 좌표를 섞지 않는다.
- 정렬 결과의 변환은 표시용이다. 원본 구조 좌표와 저장된 객체는 바꾸지 않는다.

## 포켓 후보 (M12, `detect_pockets` / `fpocket_detect_v1`)

- 엔진: fpocket 4.2.3(conda-forge `osx-arm64` `hb88c64c_2`, 실행 파일 SHA-256 고정). 고정 argv `-m 3.4 -M 6.2 -D 2.4 -C s -e e -i 15 -p 0.0 --number_apol_asph_pocket 3 -v 300 -w p`(짧은 `-A`는 이 빌드의 getopt에 없다). 유효 파라미터와 소스 근거는 `config/pockets/fpocket-4.2.3-parameters.json`.
- 입력: 같은 run의 `prepared_structure`, M11 `chemical_structure`, `openmm_minimized_structure`. 원본 `structure`는 먼저 전처리해야 한다(precondition). 체인은 `chain_auth`로 명시 선택하고, 비우면 단백질 잔기가 있는 모든 체인이다. 호출 키에는 정렬된 실제 체인 목록이 들어가므로 빈 목록과 전체 명시는 같은 호출이다. 화면은 모두 해제한 상태로 실행하지 못하게 막는다.
- 투영: 20개 표준 잔기의 중원자만. 물·리간드·이온·H/D·비선택 체인은 범주별 개수로 기록한다. 잔기 이름 대응은 정확히 10개다: `HID`·`HIE`·`HIP`·`HSD`·`HSE`·`HSP` → `HIS`, `CYX` → `CYS`, `ASH` → `ASP`, `GLH` → `GLU`, `LYN` → `LYS`. 원래 이름은 `resname_mapping`, 결과 식별자, 보고서에 남는다. 그 밖의 변형 잔기(MSE, TPO, CYM 등)는 `modified_residue_unsupported`로 거부한다.
- 전송 PDB: 합성 잔기 번호·체인 ID, 원래 원자 이름·원소, 소수 셋째 자리 좌표(되읽기 축별 차이 ≤ 0.0005 Å). 한도: 중원자 10,000, 잔기 3,000, 체인 62, 입력 10 MiB, 겹치는 좌표 없음, 4원자·좌표 계수 3 이상. 넘거나 모자라면 실행 전에 거부하며 빈 결과가 아니다.
- 주변 원자 대응은 (합성 체인, 합성 잔기 번호, 원자 이름, 원소)로만 하고 출력 정밀도로 좌표를 확인한다. serial, 최근접 좌표, 표시 문자열은 쓰지 않는다.
- 결과 분류: 성공, scientific_null(exit 0, 0바이트 `protein_info.txt`, 원자 레코드 없는 `protein_pockets.pqr`, 포켓별 파일 없음, stdout은 시작·끝 배너만, stderr는 `! No Pockets Found while refining` 1줄 + `! No pocket to reindex.` 2줄 정확히), 실패, `resource_exceeded`(포켓 200개·알파 구 50,000개·출력 30 MiB·파일 1,000개·stdout/stderr 각 1 MiB 초과). 잘라서 저장하지 않는다.
- 노출 기술자 5개: Score(무차원), Druggability Score(무차원, "fpocket 고유 점수이며 약물성 증거가 아님"을 항상 함께), Number of Alpha Spheres(개수), Total SASA(Å²), Volume(Å³, 몬테카를로 추정). Score와 Druggability Score는 같은 실행의 포켓들 안에서 정규화한 상대 점수다. 나머지 native 필드는 단위를 붙이지 않은 원래 문자열이다. 표시 중심은 저장된 구 중심의 산술 평균이며 fpocket 값이 아니다.
- 결정성: fpocket이 시각으로 난수를 초기화하므로 `seed_control: unsupported`, `fresh_execution_deterministic: false`. 같은 호출은 저장 결과를 돌려주고, 원하는 결과가 나올 때까지 다시 돌리지 않는다. 취소한 호출도 같은 호출 키면 기존 작업을 돌려준다.
- 원본 출력 보관: 파서가 읽는 파일과 stdout·stderr만 바이트로, 나머지는 경로·크기·해시만. 게시된 결과 기준 run당 64 MiB. 읽을 때마다 보관한 원본 출력을 다시 파싱해 저장 값과 대조한다.
- 의미하지 않는 것: 확인된 결합 부위, 친화도, druggability, 해석적 부피.
- 화면: 오버레이 중 M9 저장·PNG와 M8 요청 비활성, M10 비교 중 포켓 검출·오버레이 비활성, 같은 소스 거리 측정은 허용(알파 구는 선택 대상이 아님), 화학 작업 화면에서 M11 주석과 포켓 오버레이는 동시에 켜지 않는다.

## PyRosetta와 에너지 표시

- `relax_structure`, `estimate_stability`(Cartesian ddG), `score_interface`, `residue_energies`는 현재 사용할 수 없다. 이유를 담은 unavailable/precondition 응답을 돌려주고, 숫자 자리표시자나 순위는 만들지 않는다.
- import에 성공했다는 것은 "엔진 감지"일 뿐 "사용 가능"이 아니다. 사용 가능하려면 설정된 엔진, 허용 목록에 있는 구현, 호환 버전, 실제 검증 증거가 모두 필요하다.
- 에너지는 해당 엔진 고유 단위(Rosetta는 REU, OpenMM은 kJ/mol)를 유지한다. 임의로 kcal/mol로 변환하거나, 다른 방법의 값을 Rosetta·ΔΔG·친화도 이름으로 바꿔 부르지 않는다.
- 돌연변이 순위는 SASA, RMSD, OpenMM 전위에서 만들어 내지 않는다.

## M11 화학 입력 규칙

- 수용체는 명시적 수소 좌표와 완전한 공유 연결 정보가 있어야 한다. 연결 정보는 완전한 PDB CONECT 레코드나 `receptor_bonds@1` JSON 사이드카로만 받는다. 거리로 결합을 추론하지 않는다. 역방향 중복 CONECT는 결합 하나로 합치고, 자기 결합·범위 밖 참조·모호한 serial은 거부한다.
- 리간드는 V2000 SDF 레코드 하나(최대 10 MiB). V3000은 거부한다. 리간드 수소 좌표는 SDF에서만 가져오며 AddHs로 만들지 않는다.
- 사용자는 제출 전에 세 가지를 확인한다: 제공한 protonation/tautomer 상태를 그대로 쓴다, 수용체 결합 차수·전하는 추론한다, protonation이나 최적화는 하지 않는다. "pH 7 가정"은 기본값이 아니다. 사용자가 입력한 pH·준비 설명은 검증되지 않은 로컬 메모로만 저장한다.
- 소스를 만드는 방법은 두 가지다.
  1. 수용체 + SDF로 새 `chemical_structure@1`을 만든다. 리간드 식별자는 사용자가 정하고 충돌을 검사한다. 원자 이름이 없으면 SDF 인덱스로 이름을 붙이고, 그 명명 방식을 기록한다.
  2. 기존 준비 복합체의 정확한 리간드 인스턴스에 SDF를 연결한다. 모든 중원자가 원소 일치, 고유 site, 좌표 차이 ≤ 0.002 Å인 일대일 대응을 이뤄야 한다. 모호하면 거부하고, 자동 형태 정렬은 하지 않는다.
- 화학 구조 보기는 M8 프롬프트, M9 저장 보기·PNG, M10 측정·비교의 입력 종류가 아니다.

## 보고서

- 모든 수치 주장은 특정 위치에 묶인다: source handle(해시), 허용된 필드 경로(예: `rows[i].distance_A`), 행 인덱스와 잔기·원자 식별자, 단위, 정확한 값, 렌더링 값. 같은 숫자가 다른 행, 다른 잔기, 다른 단위, 다른 구조에 있어도 증거가 되지 않는다.
- 파생값은 같은 불변 행 배열에 대한 검토된 연산만 쓴다: `count(rows)`, `count_distinct(잔기 식별자)`, `minimum(distance_A)`, 종류별 개수. 검증할 때마다 다시 계산한다. 행이 0개면 개수는 0, 최소 거리는 정의되지 않음(null)이다. null을 0 Å로 바꾸지 않는다.
- 거리 렌더링: `Decimal(str(value))`를 0.01 단위로 `ROUND_HALF_UP`하고 소수 둘째 자리까지 표시한다. 2.6264… Å은 2.63 Å이 맞고 2.62 Å은 틀리다. 허용 오차(±1% 등)로 통과시키지 않는다. 개수는 정확히 일치해야 한다.
- 모델 번호, 잔기 번호, run ID, 날짜, 스키마 버전은 과학 수량이 아니다. "모델 5"가 "접촉 5개"를 입증하지 못한다.
- 보고서는 생성 시점의 능력 목록·예산·결정 상태를 이벤트 순번 기준 스냅숏으로 담는다. 저장한 보고서는 바꾸지 않고, 다시 생성하면 새 객체가 된다.
- "stabilizes", "stronger affinity", "best mutation" 같은 근거 없는 서술은 숫자가 맞더라도 거부한다. 사용자 메모는 검증되지 않았다고 표시하고 증거와 분리한다.

## 실행 결과 분류

| 결과 | 자동 처리 |
|---|---|
| 성공 / scientific_null | 종료. 재시도 없음 |
| transient | 같은 요청 체인 전체에서 최대 3회 추가 실행(2·4·8초 후) |
| input_invalid | 자동 재실행 없음. 정규화한 인자가 실제로 다른 수정 1회만 허용 |
| precondition | 선언된 선행 작업 1회 실행 후 원래 도구 1회 재시도. 선행 작업의 선행 작업은 없음 |
| resource_exceeded / fatal | 종료, 자동 재시도 없음 |
| cancelled / interrupted | 종료 상태. scientific_null이 아니며 새 재시도 허용량을 주지 않음 |

한 요청(root)에서 요청 도구는 최대 6번(최초 1 + transient 3 + 인자 수정 1 + 선행 조건 후 재시도 1), 선행 도구는 최대 1번 실행된다.

## 예산과 승인

- 기본 run 한도: 활동 시간 1800초, 비싼 계산 8회, 외부 토큰 120,000, USD 2.00. 소진되면 checkpoint를 남기고 사용자에게 묻는다.
- 비싼 계산 1단위는 실제 프로세스를 띄우기 직전에 예약하고, 성공·실패·시간 초과·중단 모두 과금한다(환불 없음). 입력 거부, 캐시 적중, dry-run 계획, 승인 거부, 대기 중 취소는 과금하지 않는다.
- run에서 첫 비싼 계산에는 명시적으로 기록된 승인 이벤트가 필요하다. JSON 필드(`decided_by=human` 등), 재시도, 재시작으로 승인이 생기지 않는다. 승인은 소진된 예산을 채워 주지 않는다. 한도를 바꾸려면 따로 기록된 변경이 필요하다.
- 활동 시간에는 도구 실행, 작업 대기, 재시도 대기, 정리 시간이 들어간다. 승인·checkpoint 대기와 깔끔하게 종료된 뒤의 꺼진 시간은 제외한다. 비정상 종료로 닫히지 않은 구간은 기록된 마감 시각까지 보수적으로 과금하고 interrupted로 둔다.
- 자율 분기 가드: 같은 호출 키 제안은 2번까지 허용하고 3번째에서 멈춘다. 새 handle이 나오지 않는 완료 제안이 4번 이어지면 멈춘다. 6개 창 안에서 A/B 반복이 진전 없이 계속되면 멈춘다. 사람이 반복해서 읽는 캐시 조회는 가드에 걸리지 않는다.
- dry-run은 저렴한 로컬 구조 검사만 실제로 실행한다. 비싼 계산은 `planned_call@1` 계획만 만들고 실제 함수로 넘어가지 않는다. 계획은 실제 과학 객체의 입력이 될 수 없다.

## 분석 흐름 (M13)

미리 정한 분석 목표 템플릿으로 기존 계산을 한 단계씩 실행하고 기록하는 기능이다. 계획은 로컬 규칙이 만든 것이며(`planner=local_rules@1`, `source=local_rules`) 모델 판단이 아니다. 계획·실행 기록·요약은 측정 결과가 아니고, 과학 값은 각 단계가 기존 `Run.call`·작업 큐·보고서 함수로 만든 결과뿐이다.

### 템플릿 (goal 6개, 단계 순서 고정)

| goal | 필수 입력 | 단계 |
|---|---|---|
| `inspect_ligand` | 원본 `structure`(전처리 정책 altloc·waters·hydrogens 명시) 또는 `prepared_structure`, 정확한 리간드 인스턴스(7필드), cutoff_A 2.5–6.0, 접촉 종류(비지 않은 부분집합) | [원본이면 `prepare_structure`] → `compute_interactions` → `compute_interface_sasa` → `inspection_report` → `method_report`(SASA) |
| `measure_atoms` | 같은 소스의 AtomRef 두 개(M10에서 고른 것) | `measure_distance` → `method_report` |
| `compare_structures` | 기준·이동 소스, 명시적 CA 쌍 3–1000개(M10 대응표) | `align_structures` → `method_report` |
| `chemical_interactions` | M11 준비 요청 하나(`create_new` 또는 `attach_existing`, 미리보기 ready). 범주는 고정 5개 | `prolif_prepare_v1` → `prolif_detect_v1` → `method_report` |
| `find_cavities` | `prepared_structure`·`chemical_structure`·`openmm_minimized_structure` 중 하나, 비지 않은 체인 목록 | `fpocket_detect_v1` → `method_report` |
| `minimize_protein` | `prepared_structure`, `protein_only`·`rebuild_pH7` 확인 | `openmm_protein_minimize` → `method_report` |

- 리간드는 사용자가 확인한 인스턴스 하나다. 하나뿐이어도 자동으로 고르지 않는다. 없거나 고르지 않았으면 선행 조건 미충족(`ligand_required`)이며 scientific_null이 아니다. 체인 자동 선택, 검출기 대체, 대체 단계(FreeSASA가 없을 때 SASA를 빼는 것 포함)는 없다. 방법을 사용할 수 없으면 계획은 실행할 수 없음으로 표시된다.
- 원본에서 시작한 `inspect_ligand`와 화학 `attach_existing`은 준비 결과에서 선택 식별자가 요청과 같은지 다시 확인한다. 달라졌으면 단계는 막히고(`identity_changed`) 다른 식별자로 바꾸지 않는다.
- 입력은 화면에서 고른 것을 가져온다. 원자 두 개·CA 대응표·화학 준비 요청은 기존 화면에서 만든 것만 읽기 전용으로 쓴다. 계획을 만든 뒤 화면 선택이 바뀌어도 계획은 바뀌지 않는다. 입력을 고치면 새 계획이고, 이전 승인은 새 실행에 적용되지 않는다.

### 계획 `analysis_plan@1`
- 불변 객체다. handle은 내용 해시이므로 같은 입력이면 같은 계획이다. 해시에 시각·승인·요청 ID·진행 상태는 들어가지 않는다.
- 단계는 1–8개, 연산·lane(`run_call`, `durable_job`, `report`)·바인딩(기존 handle 또는 앞 단계 출력만)·고정 인자·기대 출력으로 이루어진다. 작업 단계의 `timeout_s`는 120초 고정이다. 임의 도구 이름·경로·식은 받지 않는다.
- 호환성 지문(도구·프로토콜 버전, 보고서 schema·렌더 버전, 방법 capability 지문)을 담는다. 계획 승인과 각 단계 dispatch 때 다시 확인하고, 달라졌으면 실행은 `blocked`(`compatibility_changed`)이다.
- 계획 JSON은 1 MiB 이하, run당 100개 이하다(결정 0019). 같은 입력은 `inputs`에 한 번만 저장하고 단계는 `{"input_ref": <이름>}`으로 가리킨다.
- 계획 생성은 저장된 바이트·메타데이터·capability와 기존 읽기 전용 사전 검사만 쓴다. 과학 구현·작업 제출·보고서 생성·화학 추론·수치 미리보기를 하지 않는다. 비용 표시는 고정 한도와 현재 남은 예산뿐이다.
- 자연어 계획과 모델 보조 실행은 사용할 수 없다. 과학 데이터 전송 통로(게이트 투영·전송 전 미리보기·예산, 로드맵 M24)와 새 실제 호출 할당이 없기 때문이다. M8 뷰어 동의는 흐름·모델·과학 권한을 주지 않는다.

### 실행과 승인
- 실행 상태: `plan_only`, `awaiting_approval`, `ready`, `executing`, `waiting_job`, `awaiting_scientific_approval`, `blocked`, `failed`, `cancelled`, `complete`. 단계 상태: `pending`, `dispatched`, `waiting_job`, `completed`(`null_result` 포함), `failed`, `interrupted`, `cancelled`, `blocked`. 종료 상태는 `complete`, `cancelled`, `blocked`, `retryable_step=null`인 `failed`다. run당 실행 100개.
- 계획 승인은 실행·계획 handle·계획 해시·단계 집합·호환성에 묶인 기록 이벤트다. 요청에 계획 해시가 있어야 한다. 계획 승인은 비싼 계산 승인(`expensive_first_call`), 작업 시작 승인, 온라인 동의, 예산 한도를 만들지 않는다. 반대로 계산 승인이 계획 승인을 대신하지도 않는다.
- 계산 승인은 기존 run 단위 규칙 그대로다. run에서 이미 받았으면 다시 묻지 않고 "이 run에서 이미 계산 승인됨"으로 보여 준다. 아직 없으면 작업 시작 때 요청이 기록되고 실행은 `awaiting_scientific_approval`이 된다.
- 철회: 아직 자식을 시작한 단계가 없으면(dispatch가 자식 시작 없이 풀린 경우 포함) `awaiting_approval`로 돌아간다. 시작했으면 이후 단계를 막고 소유 작업에 범위 한정 취소를 걸며 `cancelled`가 된다.
- "다음 단계 실행" 한 번은 끝난 자식 결과를 기록하는 조정(물리 작업 없음) 뒤 최대 한 단계 또는 작업 전이 하나를 한다. 작업 단계는 제출과 시작을 한 전이로 한다. 끝난 작업을 실행 기록에 반영하는 것도 다음 "다음 단계 실행"이 한다. 읽기·목록·다시 열기는 이벤트를 쓰지 않는다. 여러 단계를 이어 실행하는 버튼과 백그라운드 루프는 없다.
- 모든 변경 요청은 `request_id`(UUID)를, 실행 요청은 `expected_revision`을 받는다. 같은 ID·같은 본문은 기록된 결과를 다시 돌려주고, 같은 ID·다른 본문은 409 `request_id_conflict`, revision 불일치는 409 `stale_revision`이다. 모든 변경 요청은 판단 전에 복구 조정을 하므로, 거절된 요청도 복구 이벤트를 남겨 revision을 올릴 수 있다.
- run 예산이 소진돼 있으면 아무것도 dispatch하지 않고(과금 없음) `ready`에 머물며 이유를 보여 준다. 흐름은 한도를 올리지 않는다.

### 실패, 재시도, scientific_null
- 기존 실패 분류와 `Run.call`의 transient 재시도(2·4·8초)를 그대로 쓰고, 그 바깥에 자동 재시도를 두르지 않는다. 작업 단계에는 자동 재시도가 없다.
- `input_invalid`·`precondition`·식별자 재확인 실패는 단계·실행 `blocked`다(새 계획 필요).
- transient 소진, interrupted, 소유 작업 실패, 작업 시간 초과는 그 단계에 대해 명시적 재시도를 **한 번** 허용한다(`failed` + `retryable_step`). 이때 "다음 단계 실행"은 412 `retry_or_stop_required`다. 재시도는 같은 단계의 새 시도이며 이전 시도의 과금·시도 수를 되돌리지 않는다. 소유 작업은 기존 `JobQueue.retry` 허용량(시도 순번 4 미만) 안에서만 재시도한다.
- 재시도 불가(종료 `failed`): 재시도를 이미 씀, 시간 초과가 아닌 `resource_exceeded`, fatal, 자율 분기 가드(`loop_guard_*`), run 취소, 수동으로 취소된 소유 작업(`job_cancelled`), 공유 작업 실패(`shared_job_failed`).
- scientific_null은 성공이다. 단계를 `completed`(`null_result=true`)로 기록하고, 정상적인 빈 결과 보고서를 만들고, 이후 단계를 계속한다.
- 한도: 실행당 물리 시도 24회(실패·취소·transient 시도 포함, 각 물리 시작 전에 영속 기록), 활동 시간 1800초(연결된 시도의 과금 시간 합, 승인 대기 제외). 한도는 `run_call`·`durable_job` 단계에만 적용하고, 물리 시작이 없는 보고서 단계는 거절하지 않는다. 넘으면 다음 시작을 거절하고 `failed`(`resource_exceeded`)다. run·방법의 더 엄격한 한도가 우선하고, 기존 비싼 계산 예약·과금은 바뀌지 않는다.
- 캐시 적중은 진전이 아니다. 기존 자율 분기 가드를 유지하고, 복구 조정이나 예산 때문에 풀린 dispatch가 새 제안을 만들어 가드를 올리지 않는다. 캐시로 끝난 단계는 물리 시도 0으로 보일 수 있다.

### 중지
- 중지는 이 실행만 끝낸다. `Run.cancel()`(run 전체 취소)을 쓰지 않는다. 다른 실행과 수동 도구는 계속 쓸 수 있다. 중지와 철회는 `busy`로 거절하지 않으며 `plan_only`에서도 받는다.
- 시작 전: 원자적으로 확인해 시작하지 않는다. `Run.call` 진행 중·재시도 대기 중: 다음 transient 재시도·대기 전에 이 실행의 중지 표시를 확인해 더 시도하지 않는다. 이미 시작된 동기 도구 시도는 중간에 끊지 못한다. 그 시도는 끝까지 가서 그대로 과금·기록되지만, 결과는 이 실행에 채택하지 않고 다음 단계도 시작하지 않는다.
- 소유 작업: 기존 작업 취소(`request_cancel`)와 정리를 기다리고, 과금을 유지하며, 늦은 결과를 채택하지 않는다.
- 단계가 도는 동안 시도 이벤트가 revision을 올리므로, 첫 중지 요청이 409 `stale_revision`을 받을 수 있다. 화면은 기록을 다시 읽고 중지를 한 번 자동으로 다시 보낸다.

### 공유 작업
- 같은 호출 키의 작업이 이미 있으면(수동으로 만들었거나 다른 실행의 작업) 흐름은 그 작업을 `observed_shared`로 관찰만 한다. 시작·재시도·취소하지 않는다. 성공으로 끝났으면 결과를 일반 캐시 규칙으로 검증해 단계 완료로 기록한다. 대기·실행 중이면 "원래 화면에서 시작·취소"를 안내한다. 실패·취소로 끝났으면 단계는 재시도 불가 `failed`(`shared_job_failed`)이며, 다시 하려면 원래 작업을 `/jobs`에서 직접 재시도해야 한다. 중지는 관찰만 끊고 작업은 그대로 둔다.
- 반대로 흐름이 소유한 작업은 소유 실행이 끝나기 전에는 `/jobs`에서 수동으로 시작·재시도할 수 없다(412 `job_owned_by_analysis_execution`). 소유 실행이 종료 상태가 되면 흐름은 그 작업을 다시 움직이지 않으므로 기존 수동 시작·재시도 규칙이 그대로 적용된다(끝난 실행 기록은 바뀌지 않음). 수동 취소는 언제나 허용하며, 흐름은 그 단계를 재시도 불가 `job_cancelled`로 기록한다. 시도·시간 한도 소진이나 `compatibility_changed` 차단을 기록할 때 열린 dispatch의 소유 작업이 대기 중이면 흐름이 먼저 그 작업에 범위 한정 취소를 건다.

### dry-run
- dry-run run에서도 계획을 만들고 미리 볼 수 있다. 실행 생성은 `plan_only` 기록만 만들고, 승인·다음 단계 실행·재시도·계산 승인은 412 `dry_run_plan_only`다(중지만 허용). 저렴한 도구를 포함해 어떤 과학 계산·작업 제출·보고서도 만들지 않는다. 기존 `Run.call` dry-run(저렴한 도구는 실제 실행)을 쓰지 않는다.
- 화면 안내: "연습용 run의 계획은 미리보기 전용입니다. 실행하려면 일반 run에서 같은 입력으로 계획을 다시 만드세요." 다른 run으로 옮기는 기능은 없다.

### 완료 요약 `workflow_summary@1`
- 마지막 단계 완료를 기록한 요청이 요약 객체를 만들고 `complete`를 기록한다. 그 사이 충돌은 다음 변경 요청이 같은 요약으로 마무리한다. 실패·취소·차단 실행에는 요약이 없다.
- 요약은 계획 handle·해시, 실행 ID, 승인·첫·마지막 이벤트 순번, 단계별 상태·`null_result`·출력·보고서 handle·자식 호출·작업 ID·작업 소유 여부·시도 수, 전체 물리 시도 수만 담는다. 과학 수치·순위·서술은 담지 않는다. 수치는 각 단계의 기존 보고서에서 본다. 합친 Markdown 보고서는 없다.
- 화학 구조 결과는 화학 작업 화면에서만 연다(메인 화면에서는 "화학 작업 화면에서 열기" 안내).

## 뷰어 요청과 저장된 보기

- 뷰어 명령은 표현(cartoon, ball-and-stick, surface), 정확한 잔기·리간드 선택과 초점, 선택 해제, 확대(1.25배)·축소(0.8배), 카메라 초기화뿐이다. 한 요청은 표현 → 선택 → 카메라 순으로 최대 3개 명령이 된다. 과학 계산, 보고서, 작업 제출·승인, 파일, URL은 뷰어 요청으로 실행할 수 없다.
- "적용됨"은 Mol*가 실제로 반영했다는 브라우저 확인이 온 뒤에만 표시한다. 모델이 고른 계획과 적용 결과는 따로 기록한다. 확인이 오지 않으면 detached/unacknowledged이지 applied가 아니다.
- 모델 요청은 run마다, 동의 한 번에 최대 4회다. 요청 하나가 비싼 계산 1단위, 외부 토큰 16,384, USD 0.05를 예약한다. 온라인 모드를 껐다 켜도 누적 횟수는 초기화되지 않는다. 자동 재시도는 없다.
- 저장된 보기(`viewer_scene@1`)는 소스 handle, 모델, 선택 잔기, 표현, 카메라 11필드, 테마를 담은 보기 기록이며 과학 측정이 아니다. 복원은 명시적인 브라우저 동작이고 도구를 다시 실행하지 않는다. run별로 보기 100개, 그림 100개, PNG 원본 총 64 MiB, PNG 하나 최대 8 MiB(64–2048 px, 400만 픽셀 이하)로 제한한다.
- PNG는 그 시점 렌더링일 뿐이다. GPU마다 픽셀이 다를 수 있으므로 다시 렌더링한 PNG의 바이트가 같다고 주장하지 않는다. 저장한 PNG를 다시 받을 때는 바이트가 같아야 한다.
