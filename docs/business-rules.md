# 과학·도메인 규칙

ProtView의 결과는 연구실 구성원이 논문·보고서의 근거로 쓸 수 있다. 결과는 계산으로 뒷받침되는 것만 주장한다.

## 용어

- **handle**: `obj://<run_id>/<kind>/<sha256>` 형식의 불변 객체 식별자. SHA-256은 kind, schema, 정규화한 내용 바이트로 계산하고, 시각·호출 ID는 포함하지 않는다. 같은 내용이면 같은 handle이다.
- **호출 키(call key)**: 도구 이름, 도구 버전, 정규화한 유효 인자(기본값 포함), seed, dry-run 여부, 입력 내용 지문으로 만든 캐시 키. handle과 다른 개념이다. 호출 키가 같으면 캐시를 재사용하고, handle이 같으면 결과 내용이 같다는 뜻이다.
- **scientific_null**: 입력이 유효하고 계산도 성공했지만 조건을 만족하는 결과가 없는 상태(`null_result=true`). 실패가 아니며 재시도하지 않는다.
- **geometric contact**: 원자 좌표 사이 거리만으로 정한 접촉. 두 원자가 모두 N/O이면 `polar_contact`, 모두 C이면 `hydrophobic_contact`, 나머지는 `contact`로 분류한다. 원소만 보고 나눈 것이며 수소결합·염다리 판정이 아니다.
- **chemical interaction assignment**(M11): ProLIF가 사용자가 제공한 수소·연결 정보·화학 그래프로 판정한 상호작용 범주. geometric contact와는 다른 결과 종류이며, 둘 중 하나로 다른 하나를 덮어쓰지 않는다.
- **참조 스냅샷 값**(M15): UniProt accession·위치·잔기 글자, KLIFS 포켓 번호처럼 참조 스냅샷에서 그대로 가져온 값. ProtView가 계산한 값이 아니며, 화면·보고서에서 계산값과 다른 종류로 표시한다("참조 스냅샷 값, 계산 아님").

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
| OpenMM (M7) | 표준 단백질만. Amber14-all + GBn2, pH 7 수소 재구성, 제한된 최소화. `protein_only`와 `rebuild_pH7`를 명시적으로 확인해야 실행. M21 변이 구조 모델링도 같은 설정으로 두 구조(야생형 기준, PDBFixer 변이형)를 각각 최소화한다(아래 "변이 구조 모델링 (M21)") | kJ/mol | 리간드 결합 에너지, ΔΔG, 안정성, Rosetta 점수. M21의 두 구조 값은 서로 빼거나 비교하지 않는다 |
| 원자 거리 (M10) | 같은 소스의 정확한 원자 두 개 사이 원본 좌표 유클리드 거리 | Å | — 겹친 좌표의 0 Å은 정상 값이며 scientific_null이 아니다 |
| 강체 정렬 (M10) | 사용자가 고른 단백질 CA 쌍 3–1000개로 float64 Kabsch 회전(반사 금지) | RMSD Å | 모델 품질, 결합, 안정성. 선택한 쌍에만 해당한다 |
| ProLIF (M11) | 사용자가 준비한 수용체(명시적 수소, 완전한 연결 정보) + SDF 리간드 1개. 프로토콜 `prolif_prepared_explicit_h@1` | D···A 거리 Å, D–H···A 각도 ° | 실험적 수소결합 확인, 염다리 에너지, 친화도, 안정성 |
| qvina (M18, M19 일괄) | QuickVina 2.1 자유 도킹 또는 코어 고정 구속 샘플의 `--score_only`. 강체 수용체(M11 입력 규칙) + 리간드 1개, seed 고정·CPU 1. M19 일괄은 같은 계산을 후보마다 같은 설정으로 반복. 아래 "리간드 도킹 (M18)"·"리간드 일괄 도킹 (M19)" | qvina 점수 kcal/mol(Vina 계열 스코어링 함수 값), 거리 Å | 결합 친화도·자유 에너지, ΔΔG, 순위, 실험 결합 자세 |

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

## 잔기 번호 대응 (M15, `map_residue_numbering`)

사용자 구조의 잔기(7필드)를 참조 스냅샷의 UniProt 위치와 KLIFS 포켓 번호(1–85)에 잇는다. 확실할 때만 "대응됨"이고, 나머지는 "대응 없음"이나 "충돌"로 이유와 함께 남긴다(결정 0023). 위치·번호는 모두 참조 스냅샷 값이고, ProtView가 계산하는 값은 정렬 통계(일치율, 정렬 범위, 개수)뿐이다.

### 참조 스냅샷
- 원천은 `kbase_kinase/ref`의 가공 JSONL이다(원출처 원본 바이트가 아님, kinase 한정. 결정 0022). 출처별 스냅샷 하나씩이 사용 중 세트이며, 세트 매니페스트(출처·kbase `snapshot_id`·날짜·`version_hint`·라이선스·파일별 SHA-256·바이트·행 수·`raw_sha256` 목록·kbase 커밋과 dirty 여부·`origin`·`imported_at`)의 SHA-256이 세트 해시다. `imported_at`이 들어가므로 같은 파일을 다시 가져와도 세트 해시는 새로 생긴다.
- 사용 중 세트가 없으면 `not_installed`, 매니페스트·파일 해시가 맞지 않거나 내용 형식을 해석할 수 없으면 `snapshot_invalid`로 사용할 수 없음이다. 이때 화면은 숫자 없이 이유와 가져오기 명령만 보여 주고, 도구는 캐시 조회 전에 `precondition`으로 실패한다.
- 도구 호출 하나는 시작 때 고정한 세트 하나만 본다. 그 세트가 run에 아직 기록되지 않았으면 대응 객체보다 먼저 `reference_snapshot_set@1`(매니페스트 전체)을 저장한다(같은 내용은 같은 handle). 대응 객체도 세트 해시·출처별 파일 해시와, 계산에 실제로 쓴 참조 행(UniProt 서열, SIFTS 잔기 행·segment, KLIFS 포켓)을 담으므로 참조 폴더 없이 이벤트만으로 다시 열린다.
- 사용 중 세트와 해시가 다른 대응은 "이전 스냅샷 기준"으로 표시한다. 사용 중 세트가 없으면(가져오기 전, 손상) 대응마다 "사용 중 스냅샷 없음"으로 표시하고 "이전 스냅샷 기준"이라 하지 않는다. 대응마다 세트를 고르는 기능은 없다.
- 범위 안내: 지식 탭 스냅샷 영역과 보고서 `limitations`에 "kbase_kinase가 가공한 kinase 한정 자료(원출처 원본 바이트 아님), 스냅샷에 없는 PDB·단백질은 SIFTS 대응이나 KLIFS 번호가 없음"을 숫자 없이 항상 보여 준다(`SNAPSHOT_SCOPE`).
- 표시: 스냅샷 목록과 보고서에 출처·스냅샷 ID·날짜·버전·라이선스·"kbase_kinase 가공본"을 그대로 보여 준다. 라이선스는 UniProt `CC-BY-4.0`, SIFTS `EMBL-EBI-terms`, KLIFS `none-stated`이며, KLIFS는 "이용 조건 명시 없음(none-stated)"으로 항상 표시한다. KLIFS 값의 보고서·외부 전송 사용은 따로 막지 않는다(사용자 결정).

### 입력과 대상 잔기
- 입력: 같은 run의 `structure` 또는 `prepared_structure`, 사용자가 확인한 PDB ID(4자, 대문자로 정규화) 또는 null, 체인 목록 `[{chain_auth, uniprot_accession|null}]`(1개 이상, 중복 없음). `uniprot_accession`은 사용 중 UniProt 스냅샷의 `status: ok` 항목만 받는다. 화학 작업용 구조·OpenMM 최소화 구조는 대상이 아니다.
- PDB ID는 업로드 원본의 mmCIF `_entry.id`나 PDB `HEADER` idcode에서 제안만 한다. 사용자가 확인하지 않으면 `pdb_id: null`이고 SIFTS를 쓰지 않는다.
- 대상 잔기: 구조가 가리키는 모델의 그 체인에서 사슬 잔기만, 파일 순서대로. 사슬 잔기 = gemmi 엔티티 설정(mmCIF `_entity`, PDB SEQRES·MODRES)에서 polymer 엔티티에 속하거나 ATOM 레코드(`het_flag == "A"`)인 잔기(규칙 이름 `gemmi_polymer_entity_or_atom_record@1`). 그래서 HETATM 변형 잔기(MSE 등)도 들어가고 물·리간드는 빠진다. 이 판단은 번호 대응 전용이며 `structure_residues`의 `category`는 바꾸지 않는다. 체인별 변형 잔기 수를 기록한다.
- 입력 검증은 스냅샷·구조를 읽는 검사까지 도구 구현을 부르기 전에 끝난다(모든 호출 경로에 같은 사전 검사). 없는 체인, 다른 run handle, 허용되지 않은 kind, 스냅샷에 없는 accession, 알 수 없는 필드, 쓸 수 있는 방법이 없는 체인은 `input_invalid`다.

### 체인별 방법
- **SIFTS**: `pdb_id`가 있고 스냅샷에 (pdb_id, chain_auth)가 있을 때. 체인은 author ID로만 맞춘다(`sifts_chain_match: "auth_only"`). 조회 실패·알 수 없는 형식·복원 불일치 체인은 쓰지 않는다.
- **로컬 전역 정렬**: 정렬 accession은 사용자가 준 accession, 없으면 SIFTS accession이 하나일 때 그것(화면이 미리 채움). 사용자가 SIFTS와 다른 accession을 주면 SIFTS를 쓰지 않는다. SIFTS accession이 여러 개(융합)면 정렬하지 않고 SIFTS만 쓰며, 이때 accession을 주면 `input_invalid`다.
- 체인 사슬 잔기 수 × UniProt 길이가 20,000,000칸을 넘으면 정렬하지 않는다. 남은 방법이 없으면 `input_invalid`다(사용자가 다른 accession을 골랐는데 상한을 넘는 경우 포함).
- 두 방법이 모두 실행되면 교차 확인이다. 아니면 체인에 "교차 확인 없음"과 이유 하나를 남긴다: `pdb_id_not_given`, `pdb_not_in_sifts_snapshot`, `chain_not_in_sifts_snapshot`, `sifts_chain_lookup_failed`, `sifts_chain_no_segments`, `accession_differs_from_sifts`, `multiple_sifts_accessions`, `sifts_accession_not_in_uniprot_snapshot`, `sifts_accession_uniprot_lookup_failed`, `alignment_too_large`.

### SIFTS 답
- kbase 형식(`pdbe-residue-runs-v1`, 과거 v0 list)을 ProtView 코드로 다시 해석한다. PDBe 번호는 엔티티마다 1부터 다시 시작하므로 (엔티티, PDBe 번호)로 다루고, 그 체인에 UniProt segment가 있는 엔티티만 잇는다. 위치 = `unp_start + (PDBe 번호 − res_start)`. 삽입 코드 `None`·`''`는 `""`로 정규화한다.
- 잔기 일치: 구조 잔기에 `seq_label`이 있으면 PDBe 번호 = `seq_label`, author 번호, 삽입 코드가 모두 같아야 한다(`sifts_residue_key: "label_and_author"`). `seq_label`이 null인 잔기(PDB 형식 등)는 author 번호 + 삽입 코드로 맞추고, 그런 잔기가 있는 체인에는 `"author_only"`를 남긴다. 1MQ4 체인 A에서 PDBe 번호 = `label_seq_id`임을 확인했다.
- 없음 이유: `sifts_no_residue_row`, `sifts_number_mismatch`(label·author·삽입 코드 일부만 맞음), `sifts_ambiguous_residue_row`(완전히 맞는 행이 둘 이상), `sifts_not_observed`, `sifts_outside_segments`, `sifts_position_outside_sequence`(계산 위치가 스냅샷 UniProt 서열 길이를 넘음).

### 정렬 답
- Needleman–Wunsch 전역 정렬, affine gap(Gotoh), BLOSUM62, gap 열기 −10·확장 −0.5(길이 k gap = 10 + 0.5(k−1)), 끝 gap도 같은 벌점(EMBOSS 기본과 다름), 동점은 M > X > Y(끝에서부터 역추적). 구현 `mw.sequence_alignment/gotoh-global-v1`, numpy만. 구조 서열의 표준 20종 밖 잔기(MSE 등)는 `X`, UniProt의 BLOSUM62 밖 글자(U, O 등)도 정렬에서만 `X`다. `X`는 일치로 세지 않는다.
- 통계: `aligned_pairs`(양쪽 모두 gap 아님), `identical`, `identity_pct = identical / aligned_pairs × 100`, `coverage_pct = aligned_pairs / 체인 사슬 잔기 수 × 100`. 고정 동점 규칙으로 고른 정렬 하나에서 계산한다.
- 체인 기준: `identity_pct < 90` 또는 `coverage_pct < 50`이면 그 체인 모든 잔기의 정렬 답이 없음(`alignment_below_identity`, `alignment_below_coverage`, 둘 다면 둘 다). 적용한 기준값·행렬·벌점·동점 규칙·구현 버전·크기 상한은 결과의 `alignment_params`에 있다.
- 기준을 넘으면 각 잔기는 맞춰진 UniProt 위치, gap이면 `alignment_gap`이다. 최고 점수가 같은 정렬 중 하나라도 그 잔기를 다른 위치나 gap에 두면 `alignment_ambiguous`다(앞·뒤 DP로 모든 최적 정렬을 정확히 본다). 체인 요약에 이런 잔기 수(`ambiguous_residue_count`)를 둔다.
- 방법별 없음 답은 `{absent_reason: 첫 이유, absent_reasons: 모든 이유}`다.

### 행 상태
상태는 정확히 `mapped | unmapped | conflict`다.

| 체인 | 두 방법 답 | 상태 |
|---|---|---|
| 교차 확인 | 둘 다 같은 (accession, 위치) | `mapped` |
| 교차 확인 | 둘 다 위치, 서로 다름 | `conflict` (`positions_differ`) |
| 교차 확인 | 한쪽만 위치(정렬 기준 미달로 전부 없음인 경우 포함) | `conflict` (`one_method_only`) |
| 교차 확인 | 둘 다 없음 | `unmapped` |
| 한 방법만 | 위치 있음 / 없음 | `mapped` / `unmapped` (체인에 교차 확인 없음 표시) |

- `conflict` 행은 양쪽 답을 모두 보존하고 어느 쪽도 고르지 않는다. `unmapped` 행은 방법별 없음 이유를 보존한다. UniProt 위치·잔기·KLIFS 번호는 `mapped` 행에만 있다.
- `mapped` 행은 구조 잔기 이름과 그 UniProt 위치의 글자를 함께 둔다. 표준 20종 대응으로 같으면 `residue_match: true`, 다르거나 비표준(MSE 등)이면 `false`이며 상태는 `mapped`로 유지한다. `mapped`가 아니면 null이다.
- `mapped` 행이 0개면 `null_result: true`(scientific_null)다.

### KLIFS 포켓 번호
- 대응된 accession의 KLIFS kinases 항목이 하나이고 포켓이 비어 있지 않을 때만 붙인다. accession 수준 없음 이유: `accession_not_in_klifs`, `klifs_pocket_empty`, `klifs_multiple_entries`, `uniprot_sequence_unavailable`(SIFTS 전용 경로에서 스냅샷에 서열이 없음).
- 85자 포켓을 구역으로 나눈다: I(1–3), g.l(4–9), II(10–13), III(14–19), αC(20–30), b.l(31–37), IV(38–41), V(42–44), GK(45), hinge(46–48), linker(49–52), αD(53–59), αE(60–64), VI(65–67), c.l(68–75), VII(76–78), VIII(79), xDFG(80–83), a.l(84–85). 표기는 `<구역>.<번호>`(예: `GK.45`)로 KLIFS `match_residues`와 대조해 맞췄다.
- 첫 단계: 구역 안의 gap(`-`, `_`)으로 나뉜 연속 조각을 UniProt 서열에 정확히 일치시키되, 구역 순서와 조각 순서를 지키는 배치가 하나뿐인 구역만 번호를 준다(`klifs_match: "contiguous"`). gap 자리는 번호 없음.
- 두 번째 단계: 첫 단계로 해결되지 않은 구역 중 바로 앞·뒤 구역이 모두 첫 단계로 해결된 구역만, 그 사이 구간에서 gap 아닌 글자를 순서대로(중간 잔기 건너뛰기 허용) 맞추는 배치가 정확히 하나일 때 번호를 준다(`klifs_match: "gapped_unique"`). 처음·마지막 구역은 시도하지 않는다. 두 번째 단계 결과는 다른 구역의 구간을 바꾸지 않는다. 남은 구역은 accession별 `unresolved_regions`에 둔다.
- 번호는 `mapped` 행(불일치·교차 확인 없음 포함)에만 붙인다. `conflict`·`unmapped` 행에는 없다.
- KLIFS 구조별 표(`match_residues`)는 대조·측정 전용이며 제품 계산에 쓰지 않는다. 측정(첫 고정 `c1d824d`): 279개 구조 22,618 위치 중 98.2% 일치, KLIFS가 번호를 둔 위치 기준 적용률 약 96.4%(`docs/tracking/m15-acceptance.md`).

### 보고서
- `method_report_manifest@1`, `analysis_type: "residue_numbering"`, 렌더 `residue_numbering_markdown@1`. 문장은 고정 statement ID이고, 각 ID는 증거 종류 하나와 허용 필드 경로 집합을 갖는다. 다른 종류의 필드를 인용하면 값 비교 전에 거부한다.
- **계산값**(`computed`): 체인별 `identity_pct`·`coverage_pct`(`Decimal(str(v))`를 0.1 단위 `ROUND_HALF_UP`, 정확히 일치), 상태별 행 수, 잔기 불일치 수와 (구조 잔기 이름, UniProt 글자) 종류별 수, `alignment_ambiguous` 행 수, 변형 잔기 수.
- **참조값**(`reference_value`): accession, UniProt 위치·글자, KLIFS 번호·표기. 세트 해시와 출처별 스냅샷·버전·날짜·라이선스, "참조 스냅샷 값, 계산 아님"이 붙는다. 잔기 단위 참조값은 KLIFS 번호가 있는 `mapped` 행만 나열하고(체인·accession당 최대 85), 전체 행은 대응 객체에 있다.
- 보고서를 만들고 다시 열 때 대응 객체를 검증한다: 행 상태는 세 가지, 방법별 `absent_reasons`는 그 방법(SIFTS·정렬)의 닫힌 이유 집합, `conflict_reason`은 `positions_differ`·`one_method_only`, 체인 KLIFS 항목은 `applied`가 참이면 `absent_reason`이 null이고 거짓이면 KLIFS 이유 집합 안의 값이어야 한다. 어긋나면 보고서를 만들지 않는다.
- `limitations`는 고정 문장 목록이며 마지막에 스냅샷 범위 문장이 있다. 범위 문장이 들어가기 전 목록(`LEGACY_REPORT_LIMITATIONS`)으로 저장된 보고서도 다시 열린다.
- 스냅샷 출처 표와 KLIFS 조건 안내를 담고, 충돌·대응 없음 개수를 숨기지 않는다. "결합", "중요" 같은 해석 문장은 쓰지 않으며 렌더러가 그런 표현이 든 Markdown을 거부한다. 만들기·다시 열기·다운로드는 대응을 다시 계산하지 않는다.

### 의미하지 않는 것
구조적·기능적 동일성, 잔기의 역할(hinge 결합 등), 대응되지 않은 잔기가 UniProt에 없다는 뜻. 대응 없음·충돌은 "이 스냅샷과 방법으로 확실하지 않음"이다.

## 참조 주석 (M16, `annotate_reference_sites`)

kinase 주요 부위가 어디인지(M15 번호 대응의 KLIFS 번호, 참조값)와 그 부위가 리간드와 어떤 기하 접촉을 이루는지(M1 기하 접촉, 계산값)를 한 결과로 모아 구조 분석 탭 뷰어·PNG 그림·보고서에 보인다(결정 0024). 새 계산은 없다. 모든 번호·위치는 저장된 대응 행, 모든 개수·거리는 저장된 접촉 행에서 온다.

### 부위 목록 `kinase_key_sites@1`
- 10자리, 이 순서로 고정해 결과에 그대로 기록한다: `III.17`, `αC.24`, `GK.45`, `hinge.46`, `hinge.47`, `hinge.48`, `xDFG.80`, `xDFG.81`, `xDFG.82`, `xDFG.83`(`αC`는 그리스 문자 U+03B1). 표기는 M15 `klifs_label`과 문자 그대로 같다.
- 관용 이름(촉매 Lys 자리, gatekeeper 등)은 결과·화면·보고서에 넣지 않는다. 그 잔기가 실제로 Lys·Glu라거나 역할을 한다는 주장이 아니다. KLIFS 구역 이름(`III`, `αC`, `GK`, `hinge`, `xDFG`)만 쓴다. 사용자가 고른 잔기를 부위로 표시하는 길과 85자리 전체 표시는 없다.

### 입력과 같은 구조 규칙
- 입력: `numbering_map`(같은 run의 `residue_numbering_map@1`, 필수), `contacts`(같은 run의 `interaction_set@1` 또는 null, 기본 null). 리간드 인스턴스 하나의 접촉 결과 하나만 받는다. 리간드가 여럿이면 주석을 따로 만든다.
- 접촉 결과의 `structure`는 대응 객체의 `structure.handle`과 같아야 한다(다르면 `input_invalid` `structure_mismatch`). 기하 접촉은 전처리 구조에서만 계산되므로, 접촉과 함께 주석하려면 전처리 구조로 번호 대응을 만든다. 원본 구조로 만든 대응을 전처리 구조에 옮기지 않는다.
- 레지스트리 사전 검사 훅이 구현을 부르기 전에 검증한다: 알 수 없는 인자(`unknown_field`), 잘못된 종류·다른 run handle(`numbering_map_invalid`, `contacts_invalid`), `structure_mismatch`, `duplicate_site_residue`. 모두 `input_invalid`다.
- 참조 폴더·스냅샷을 읽지 않는다(대응 객체에 담긴 참조 행만). 부위 잔기가 접촉 도구의 검사 대상인지만 구조 handle의 잔기 목록(`structure_residues`의 `category`)으로 정한다. 외부 요청 없음. 그래서 capability는 항상 사용 가능이다. 같은 입력이면 같은 handle이고, events-only로 다시 열린다(업로드·참조 폴더 없이). dry-run에서도 실제로 실행한다(값싼 도구).
- 대응 객체가 이전 스냅샷 세트로 만든 것이어도 그대로 쓰고 그 세트 해시를 기록한다(화면은 "이전 스냅샷 기준" 표시).

### 그룹과 부위 상태
- 대응 객체의 체인마다, 그 체인의 KLIFS 항목(accession)마다 그룹 하나 `(chain_auth, accession)`. 대응된 accession이 없는 체인은 `accession: null` 그룹 하나(`klifs_absent_reason: no_mapped_accession`). 융합 체인은 accession마다 그룹이다. 그룹 이유 집합: M15 KLIFS 이유 4개(`accession_not_in_klifs`, `klifs_pocket_empty`, `klifs_multiple_entries`, `uniprot_sequence_unavailable`)와 `no_mapped_accession`.
- 부위 상태는 정확히 `annotated | absent`다. `annotated`는 그 그룹에서 `status == mapped`, `uniprot_accession == accession`, 이 KLIFS 번호인 대응 행이 정확히 하나일 때다. 둘 이상이면 고르지 않고 도구 전체가 `input_invalid`(`duplicate_site_residue`)다. `conflict`·`unmapped` 행은 절대 주석하지 않는다.
- `absent` 이유는 닫힌 집합이며 이 순서로 첫 해당 이유 하나다: `klifs_not_applied`(그룹에 KLIFS 번호 적용 안 됨) → `pocket_gap`(그 accession의 KLIFS 포켓 문자열에서 이 자리가 `-`·`_`) → `region_unresolved`(이 자리의 구역이 그 그룹의 `unresolved_regions`에 있음) → `no_mapped_residue`(그 밖에 이 번호의 `mapped` 행 없음).
- 어느 그룹에도 `annotated` 부위가 없으면 `null_result: true`(scientific_null)다.
- 상태·이유 집합과 순서를 바꾸려면 사용자 결정이 필요하다.

### 접촉 부분 (`contacts`가 있을 때)
- 결과에 접촉 결과 handle, 리간드 인스턴스 7필드, `cutoff_A`, 계산한 접촉 종류(`parameters.types`)를 기록한다.
- `annotated` 부위마다 `contact`:
  - `assessed`: 접촉 도구는 폴리머 레코드(`category == "polymer"`, `het_flag == "A"`) 잔기만 검사한다. 부위 잔기가 그렇지 않으면(HETATM 변형 잔기 MSE 등) `assessed: false`, `not_assessed_reason: "residue_not_checked_by_contact_method"`이고 개수·거리·쌍은 null이다.
  - `by_type`: `contact`, `polar_contact`, `hydrophobic_contact` 각각 `{computed, count}`. 계산하지 않은 종류는 `computed: false`, `count: null`. 계산했으면 그 잔기와 7필드(null 포함)가 정확히 같은 접촉 행 수(0 가능).
  - `min_distance_A`: 계산한 종류 전체에서 그 잔기 행들의 `distance_A` 최솟값(저장값 그대로)과 그 행 인덱스(같은 값이면 가장 작은 인덱스). 행이 없으면 null. "계산한 종류·cutoff 안의 최소"라는 뜻이다.
  - `polar_pairs`: 그 잔기의 `polar_contact` 행마다 `{contact_row_index, protein_atom, ligand_atom, distance_A}`. `polar_contact`를 계산하지 않았으면 빈 목록이 아니라 null.
- `absent` 부위의 `contact`는 null. `other_contact_residues`는 접촉 행이 있으나 `annotated` 부위가 아닌 잔기(7필드, 행 인덱스 목록)다.
- 접촉 결과가 0행이면 계산한 종류의 개수는 0, 거리는 null. `contacts`가 없으면 결과의 `contacts`와 모든 부위의 `contact`·`other_contact_residues`가 null("접촉 결과 없음")이다.
- **0이 아닌 것**: 계산하지 않음, 접촉 도구가 검사하지 않는 잔기, 접촉 결과 없음은 화면·그림·보고서 어디서도 0이나 0 Å으로 보이지 않는다. 0은 계산한 종류에서 행이 없을 때만 쓴다.

### 이름표
- `display_label` = `<잔기 이름><seq_auth><icode> (<klifs_label>)`. 표준 20종이면 첫 글자만 대문자(`MET` → `Met`), 그 밖(`MSE` 등)은 원래 이름. 예: `Met318 (hinge.47)`, `Ala100A (hinge.46)`. 서버가 만들고 화면·그림이 그대로 쓴다. 표시 문자열에서 식별자를 다시 만들지 않는다.

### 결과 객체 `reference_site_annotation@1`
- 최상위 키: `schema`, `method_version`(`mw.site_annotation/v1`), `site_set`, `numbering_map`, `snapshot_set_hash`, `structure{handle, structure_kind, model_number}`, `contacts`, `groups`, `other_contact_residues`, `null_result`, `limitations`. 부위 필드: `klifs_index`, `klifs_label`, `status`, `absent_reason`, `residue`, `map_row_index`, `residue_match`, `klifs_match`, `display_label`, `contact`.
- `limitations`는 이 네 문장, 이 순서·문자 그대로다:
  1. "기하 접촉은 중원자 사이 거리만으로 정한 것이며 수소결합이나 화학 상호작용 판정이 아니다."
  2. "KLIFS 번호는 참조 스냅샷 값이며 잔기의 역할을 뜻하지 않는다."
  3. "없음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이다."
  4. "접촉 도구는 폴리머 레코드 잔기만 검사하므로 HETATM 변형 잔기는 검사하지 않는다."

### 화면과 그림
- 구조 분석 탭 메인 화면에만 있다(화학 작업 화면·지식 탭에는 없음). 표시 소스가 원본 또는 전처리 구조일 때만 동작하고, 최소화 구조는 숫자 없이 "최소화 구조에는 번호 대응이 없어 주석할 수 없음"만 보인다. 대응·접촉 결과 목록은 표시 소스와 구조 handle이 같은 것만이며 자동으로 고르지 않는다(하나뿐이어도).
- 뷰어: `annotated` 부위 잔기는 막대 모형 + 구역 색 + `display_label` 이름표. `polar_pairs`는 쌍마다 점선과 저장된 `distance_A`를 소수 둘째 자리 `ROUND_HALF_UP`(10진 문자열 기준)으로 `2.93 Å`처럼. 점선 끝 원자는 (잔기 7필드 + 원자 이름)이 검증된 원자 카탈로그에서 정확히 원자 하나로 풀릴 때만 그리고, 0개·여럿이면 그리지 않고 "그리지 못함(원자 대응 없음/모호)"으로 패널에 남긴다. 좌표 최근접·Mol* label·PDB serial로 찾지 않는다. 다른 접촉 잔기는 점선 없이 회색 막대 모형으로 겹쳐 그려 강조한다(주 모델 색은 바꾸지 않음), 접촉 결과의 리간드 인스턴스도 보이게 한다.
- 범례: 패널은 "점선: 기하 극성 접촉(N/O–N/O 원자 거리, cutoff 이내). 수소결합 판정 아님."과 KLIFS 번호가 참조값이라는 안내, 구역 색 설명. PNG는 아래 저장된 보기 규칙.
- 배타: 포켓 오버레이와 주석은 동시에 켜지지 않는다(막힌 쪽은 이유 표시). M10 비교를 시작하면 주석이 꺼지고 비교 중에는 켤 수 없다. 주석이 켜진 동안 M8 자연어 뷰어 요청은 막고(로컬 `/` 명령은 그대로), M9 보기 저장·PNG는 허용한다. run·소스가 바뀌면 늦은 응답을 버리고 주석을 끈다.

### 보고서
- `method_report_manifest@1`, `analysis_type: "reference_site_annotation"`, 렌더 `reference_site_annotation_markdown@1`. 입력은 주석 handle 하나. 만들기·다시 열기·다운로드는 주석·대응·접촉을 다시 계산하지 않는다.
- 만들고 다시 열 때 저장된 주석을 저장된 대응·접촉 행과 대조한다: 상태 두 가지, 없음 이유·그룹 이유가 닫힌 집합 안이고 첫 해당 이유와 같음, `assessed`가 저장된 구조 잔기 목록의 polymer 분류와 같음, 개수·최소 거리가 인용한 접촉 행과 같음. 어긋나면 만들지 않는다.
- **참조값**(`reference_value`): 부위별 accession, UniProt 위치, KLIFS 번호·표기, 구조 잔기(7필드). 대응 객체 필드를 인용하고 세트 해시·출처, "참조 스냅샷 값, 계산 아님"이 붙는다.
- **계산값**(`computed`): 부위·종류별 접촉 개수, 부위별 최소 거리(Å, 접촉 행 `distance_A` 인용, 0.01 `ROUND_HALF_UP`), 상태별·없음 이유별 부위 수. statement ID는 고정이며 다른 종류의 필드를 인용하면 거부한다.
- 계산하지 않은 종류는 "계산하지 않음", 검사하지 않은 잔기는 "접촉 도구가 검사하지 않는 잔기", 접촉 결과가 없으면 "접촉 결과 없음"으로 쓰고 숫자를 쓰지 않는다. 접촉 결과의 리간드 인스턴스·cutoff·계산한 종류를 적고, 최소 거리는 "계산한 종류·cutoff 안의 최소"라고 적는다. `absent` 부위와 이유별 개수를 숨기지 않는다.
- 스냅숏에 보고서 생성 때의 사용 중 세트 해시(없으면 null)와 대응의 세트와 다른지(`stale_snapshot`)를 기록한다.
- 해석 금지어: M15 렌더러 목록에 `촉매`, `hydrogen bond`, `H-bond`/`hbond`, `catalytic`를 더해 모든 줄을 검사하고, 위 고정 `limitations` 네 문장과 문자 그대로 같은 줄만 뺀다(부정 안내). 그 밖에 "수소결합"이라는 말을 쓰지 않는다.

### 의미하지 않는 것
수소결합·염다리·화학 상호작용 판정, 잔기의 역할(촉매·hinge 결합 등), 결합 세기·친화도. `absent`는 "이 스냅샷과 방법으로 확실하지 않음"이다. 그림 상한은 올리지 않았다(결정 0024).

## 리간드 후보 (M17, `rdkit_inspect_v1` / `rdkit_enumerate_v1`)

부모 리간드(V2000 SDF 한 분자)에서 사용자가 고른 한 부위를 building block이나 사용자 반응 규칙으로 바꾼 후보 분자를 만들고, 후보마다 RDKit 속성과 PAINS 구조 경고 일치를 붙인다(결정 0025). 후보는 2D 그래프(SMILES)일 뿐이며 3D 배치·점수는 M18의 일이다. 모든 값은 실제 RDKit 2026.03.6 작업 프로세스(`.deps/prolif/venv-locked`)가 낸 저장값이고, 서버 프로세스는 RDKit을 import하지 않는다.

### 입력
- 가져오기는 기존 `chemical_raw_input@1`(파일당 최대 10 MiB)이다. 부모는 기존 `ligand_sdf`(M11 가져오기 그대로, V3000 거부), building block은 새 종류 `building_blocks_sdf`(`.sdf`, `input_format: sdf_multi`, `$$$$` 기준 레코드 1–1,000개)와 `building_blocks_smiles`(`.smi`·`.txt`, `smiles_list`, 비어 있지 않고 `#`로 시작하지 않는 줄 1개 이상). 가져오기는 크기·UTF-8·NUL·레코드 수만 보고, 화학 검증은 점검 작업이 한다. 같은 바이트를 다른 종류로 가져오면 거부한다. 기존 `/chemical/prerequisites`·가져오기 inspect는 M11 세 종류 그대로다.
- **부모**(점검이 검증): SDF 레코드 정확히 1개, 중원자가 연결된 단일 분자, 중원자 ≤ 256, 원소는 H C N O S P F Cl Br I만. 거부 이유(typed 실패): `unparseable`, `record_count`, `multiple_fragments`, `element_not_allowed`, `too_many_atoms`. 수소·양성자화·토토머 상태는 입력 그대로이며 검사·추가하지 않는다. SDF 좌표는 점검 객체에 저장하지 않는다.
- **원자 번호**: 화면·점검 객체·부위·후보의 모든 원자 번호는 SDF 원자 블록의 1-기반 순번(수소 포함)이다. 원자 표와 2D 그림은 중원자만 보여 주되 번호는 SDF 순번 그대로라 수소 자리는 건너뛴다. RDKit 내부 인덱스를 번호로 쓰지 않는다.
- **building block**: SDF는 레코드 제목, SMILES는 줄의 두 번째 토큰이 이름이다. 이름이 비면 `block_<n>`이고, n은 가져온 순서의 모든 라이브러리를 이어서 센 레코드 순번이다(건너뛴 빈 줄·`#` 줄은 세지 않음). 이름은 128자 이하, 한 요청의 모든 라이브러리에서 유일해야 하며 뒤의 중복은 `duplicate_name`(첫 번째 유지). 레코드 거부 이유(이 순서): `unparseable`, `empty`, `multiple_fragments`, `element_not_allowed`, `too_many_atoms`(중원자 > 64), `duplicate_name`. 거부 레코드 목록(최대 200개)의 `ordinal`은 그 라이브러리 안 순번이라 `block_<n>`과 다를 수 있다. 이유별 총 개수는 `rejected_counts`에 따로 있다.
- block 상한 1,000개는 두 라이브러리를 합친 것이다. 넘으면 가져온 순서대로 처음 1,000개 레코드만 읽고 `block_limit_reached`를 표시한다(조용히 자르지 않음).
- **표시(붙임) 원자**: 원자번호 0인 원자(SMILES `*`, SDF `*`·`R#`). `R#`는 `[1*]`로 보일 수 있으므로 기호가 아니라 원자번호로만 판별한다. 표시 원자가 정확히 1개이고 그 이웃이 단일 결합으로 이은 중원자 1개인 block만 고정 교체에, 표시 원자가 없는 block만 사용자 규칙에 쓴다. 맞지 않는 조합은 오류가 아니라 규칙별 `not_applicable` 개수다.

### 부위
- 부모 중원자의 비어 있지 않은 집합이고, 부위 밖(코어)도 비어 있지 않으며, 부위와 코어를 잇는 결합이 정확히 1개이고 그 결합의 `order`가 `single`이다(결합형 `single | double | triple | aromatic`은 RDKit 정리 뒤 값). 부위에 붙은 명시적 수소는 부위와 함께 떨어진다. 연결이 2개 이상인 링커 교체와 부위 자동 제안은 없다.
- 검사는 서버가 RDKit 없이 점검 객체의 원자·결합·수소 목록으로 한다(미리보기 읽기와 생성 요청 입장). 이유(이 순서로 첫 해당 하나): `site_empty`, `site_atom_unknown`(중원자 표에 없는 번호, 수소 번호 포함), `core_empty`, `crossing_bond_count`, `crossing_bond_not_single`. 점검 전에는 부위를 고를 수 없다.

### 생성 방법
- **고정 교체 `replace_single_bond_v1`**(`rule_id: "fixed"`): 부위 원자와 그 수소를 떼고, 교차 결합의 코어 쪽 원자와 block 표시 원자의 이웃을 단일 결합으로 잇는다. 표시 원자는 지운다. 산출물을 정리(sanitize)한다.
- **사용자 반응 규칙 `user_reaction_smarts_v1`**: 요청당 0–10개, 텍스트 4 KiB 이하, 반응 SMARTS 텍스트 그대로 저장. `rule_id`는 요청 순서의 `user_<n>`이며 점검·생성·보고서가 같은 id를 쓴다. 형태는 반응물 템플릿 정확히 2개(부모 쪽 첫째, block 쪽 둘째)·생성물 1개·첫째 반응물에 원자 맵 1개 이상이다. 점검이 규칙마다 `valid` 또는 이유(`reaction_parse_failed`, `reactant_count`, `product_count`, `no_mapped_atom`, `too_large`, `duplicate_rule`)를 기록한다. 규칙 하나가 틀려도 점검은 성공한다. 생성은 점검에서 `valid`인 규칙만 받는다.
- **적용 범위**: 첫째 템플릿이 부모에서 맞춘 모든 원자(맵 유무 무관)가 부위 안이어야 한다. 하나라도 부위 밖이면 그 매치를 `outside_site`로 세고 건너뛴다(RDKit 반응물 매치 하나 = (규칙, block, 매치) 한 건). 코어가 끊기는 매치도 부위 밖 원자를 맞춘 것이므로 `outside_site`다. 그래서 코어는 항상 그대로 남는다.
- 고정 교체만, 규칙만, 둘 다 쓸 수 있고 둘 다 끄면 거절(`no_generation_method`)이다.

### 후보·중복·거부
- 생성 순서(결정적): 고정 교체 → 사용자 규칙(요청 순서), 규칙마다 block 입력 순서 × RDKit 매치 순서.
- 정규 SMILES는 RDKit 이성질체 정규 SMILES(수소 생략형)이다. 부모 코어의 입체는 유지하고 새로 생긴 입체 중심은 미지정이며, 입체이성질체는 열거하지 않는다. `stereo_flag`: `none | parent_stereo_lost`(부모 코어의 지정된 키랄 중심·입체 이중결합이 산출물에서 미지정) `| new_unspecified_center`(부모 코어에서 오지 않은 미지정 입체 중심, `FindMolChiralCenters(includeUnassigned=True)`), 둘 다면 `parent_stereo_lost`.
- 후보 행은 입체 포함 정규 SMILES당 1개다. 같은 SMILES가 다른 경로로 또 나오면 첫 행의 `origins`(`{rule_id, block_name}`)에 더하고 `duplicate_products`만 올린다. 후보 id = `c_` + 그 SMILES의 SHA-256 앞 16 hex.
- 생성물 거부(행 없음, 이유별 개수만): `sanitize_failed`, `element_not_allowed`, `too_many_atoms`(중원자 > 256), `equals_parent`, `outside_site`.
- 상한: 저장 후보 2,000개(`stop_reason: "candidate_limit"`), 원시 생성물 시도 20,000개(`"attempt_limit"`). 닿으면 정해진 순서에서 멈추고 `limit_reached: true`로 저장한다. 부분 결과 저장은 이 두 경우뿐이다. 작업 안에 시간 기반 중단은 없다. 시간 초과·취소·크래시는 결과를 저장하지 않는다.
- 후보 행 `retained_parent_atoms`는 부위 밖 부모 **중원자**의 SDF 번호 오름차순(코어 중원자 전체)이다. 미리보기 응답의 `site_check.retained_parent_atoms`는 코어 수소 번호도 포함하므로 같은 이름이지만 뜻이 다르다(화면은 후보 집합 쪽을 쓴다).
- 후보 0개는 빈 과학 결과(scientific_null)이지 실패가 아니다(거부 이유별·`not_applicable` 개수를 함께 보여 준다).

### 속성과 PAINS
- 후보와 부모 모두 항상 계산·저장(null 없음): `mol_weight`(Descriptors.MolWt, 평균 분자량, Da), `crippen_logp`(Crippen.MolLogP, Wildman–Crippen 추정, 무차원), `hbd`·`hba`(Lipinski 정의 `CalcNumLipinskiHBD`·`CalcNumLipinskiHBA`. `NumHDonors`/`NumHAcceptors`는 다른 정의라 쓰지 않음), `tpsa`(CalcTPSA, Å², S·P 미포함), `rotatable_bonds`(CalcNumRotatableBonds 기본 = Strict), `heavy_atoms`, `formal_charge`(합). 정의 이름은 결과의 `property_methods`에 있다. 값은 RDKit 반환 그대로이고 반올림은 표시 때만 한다.
- PAINS: RDKit `FilterCatalog` PAINS A·B·C(16·55·409항목) 일치 목록 `pains.matches: [{catalog, name}]`. "구조 경고 일치"일 뿐 화합물의 좋고 나쁨 판정이 아니다.
- 표시: 분자량·logP·TPSA는 소수 둘째 자리 `ROUND_HALF_UP`(10진 문자열 기준), 개수는 정수, 단위 Da·Å²·무차원. 속성은 "RDKit 추정값"으로 부른다.

### 필터
- 필터는 생성 입력이 아니다. 후보 집합은 필터와 무관하게 한 번 만들어 저장하고, 필터는 화면 읽기(`/ligand/candidate_sets/rows`)와 보고서 시점에 서버 순수 함수가 저장값으로 평가한다(이벤트 없음). 화면은 경계 비교를 다시 하지 않는다.
- 명세: 속성별 선택적 `min`·`max`(경계 포함, 기본 없음, 미리 채우지 않음)와 `pains_exclude`(기본 끔). 필터별 통과·실패와 `passes_all`(적용한 필터가 없으면 null)을 돌려준다. 후보는 필터와 무관하게 모두 보이며 "필터 통과만 보기"를 고를 수 있다. 전체 수와 필터로 숨긴 수를 함께 보여 준다.
- 정렬 키는 `generation_order`(기본)와 속성 8개, 방향 오름·내림(같은 값은 생성 순서).
- "활성"이 보고서 금지어이므로 화면·보고서는 "적용한 필터"라고 쓴다.

### 작업과 예산
- 점검(`rdkit_inspect_v1`, 도구 `rdkit_inspect_ligand`)과 생성(`rdkit_enumerate_v1`, 도구 `rdkit_enumerate_ligands`)은 둘 다 기존 `JobQueue` 비싼 작업 경로이고 각각 비싼 계산 1단위를 쓴다(run 단위 첫 비싼 계산 승인, 시간 상한 120초). 번호 붙은 2D 그림이 RDKit을 요구하므로 점검도 작업이다. 부모를 올리거나 규칙을 고칠 때마다 점검 1단위가 든다.
- 같은 정규화 입력은 같은 호출 키라 기존 작업·결과를 다시 쓴다(새 작업·과금 없음). 결과 객체에 시각·작업·시도 ID가 없어 같은 입력은 같은 handle이다.
- 생성 요청은 규칙 텍스트를 받지 않는다. 서버가 점검 객체에서 `valid` 규칙의 텍스트를 꺼낸다. 다른 run·종류의 handle, 잘못된 부위, `valid`가 아닌 규칙은 작업을 만들기 전에 거절한다.
- dry-run run에서는 계획(`planned_call`)만 만들고 결과 객체가 없다.
- 2D SVG는 256 KiB 이하(넘으면 점검 `resource_exceeded`), 점검 객체 전체는 1 MiB 이하다. 그래서 중원자 약 230개를 넘는 부모는 점검할 수 없다(부모 한도 256보다 낮음). SVG는 `<img>` data URI로만 표시한다.
- 사용 가능 여부(`methods.ligand_candidates`): 잠긴 환경 존재, RDKit 고정 버전 일치, PAINS 카탈로그 고정 항목 수 로드가 모두 확인될 때만 사용 가능이다(서버는 작업 모듈의 handshake만 실행). 아니면 숫자·컨트롤 없이 이유(`worker_missing`, `handshake_failed`, `rdkit_version_mismatch`, `pains_catalog_unavailable`).

### 결과 객체
- `ligand_inspection@1`(부모가 거부되면 객체 없이 typed 실패): 부모 SHA-256·SDF 원자 수·중원자 수·정규 SMILES, 중원자 원자 표(`serial`, `element`, `formal_charge`, `neighbors`), 결합 목록 `{a, b, order}`, 명시적 수소 `{serial, attached_to}`, 번호 붙은 2D SVG(원자 번호 라벨 = SDF 번호), 부모 속성, block 라이브러리별 요약(수락 개수, 거부 레코드, `rejected_counts`, 고정 교체·규칙 대상 수, `block_limit_reached`), 규칙별 검증 결과, RDKit 버전, 입력 SHA-256.
- `ligand_candidate_set@1`: 점검 handle·부모 handle·block handle, 부위·교차 결합·`retained_parent_atoms`, 사용한 규칙(텍스트 그대로), 방법, block 라이브러리 요약, 후보 행, 개수(`blocks_accepted`, `raw_products`, `candidates`, `duplicate_products`, `rejected{이유별}`, `not_applicable{규칙별}`), 상한·`limit_reached`·`stop_reason`, 부모 속성, `property_methods`, `limitations`.
- 두 객체 모두 게시 전에 현재 시도·취소·종료 상태와 스키마·작업 ID·시도 ID·유한값·닫힌 집합을 검증하고, 읽을 때마다 완료된 게시 한 건과 입력에 대조한다. events-only로 다시 열린다(원본 가져오기·RDKit 없이). 새 부모를 올리면 새 점검 객체이고 이전 객체는 지우지 않는다. 화면은 점검 객체를 자동으로 고르지 않는다.
- `limitations`는 이 다섯 문장, 이 순서·문자 그대로다(결과·보고서·capability 공통):
  1. "속성값은 RDKit 추정값이며 측정값·예측 활성이 아니다."
  2. "PAINS 일치는 구조 경고일 뿐 화합물의 좋고 나쁨 판정이 아니다."
  3. "후보는 2D 그래프이며 3D 배치·점수·합성 가능성은 계산하지 않았다."
  4. "새로 생긴 입체 중심은 미지정이며 입체이성질체는 열거하지 않았다."
  5. "수소·양성자화·토토머 상태는 입력 그대로이다."
- 부모·block·부위·생성물·규칙 이유 집합, `stereo_flag` 값, 한계 문장은 `backend/mw/ligand_constants.py` 상수이며 바꾸려면 사용자 결정이 필요하다.

### 보고서
- `method_report_manifest@1`, `analysis_type: "ligand_candidates"`, 렌더 `ligand_candidates_markdown@1`. 입력은 후보 집합 handle 하나와 선택적 필터 명세(정규화해 manifest에 저장). 만들기·다시 열기·다운로드는 후보를 다시 생성하지 않고, 다시 열 때 후보 집합을 검증한 뒤 manifest·주장·Markdown 바이트를 저장 객체에서 다시 만든 것과 비교한다.
- 증거는 모두 계산값(`computed`)이며 후보 집합 handle·필드 경로에 묶인다: 부모 속성, 후보 수, block·원시 생성물·중복 개수, 거부 이유별·규칙별 `not_applicable` 개수, 상한 상태, 부위 원자 번호, 사용자 규칙 텍스트. `count_where` 파생값(저장 행에 조건을 적용해 검증할 때마다 다시 셈, 조건은 `row_selector`에 기록): 적용한 필터별 통과 수, 모든 필터 통과 수, PAINS 일치 후보 수, `stereo_flag`별 수. 후보를 행 단위 증거로 연결하지 않는다(전체 표는 리간드 탭). 후보가 0개면 행 통계가 없고, 적용한 필터가 없으면 필터 문장도 없다.
- 소수 속성은 `Decimal(str(v))`를 0.01 `ROUND_HALF_UP`, 정수는 그대로. 틀린 반올림, 다른 statement의 필드 인용, 계산하지 않은 값을 0으로 쓰기는 거부한다.
- 해석 금지어: M15·M16 목록에 좋은·나쁜·약물 유사·독성·안전·활성·친화·억제·합성 가능·최적·중요·핵심·기능(과 영어 대응어)을 더해 모든 줄을 검사하고, 고정 한계 다섯 문장과 문자 그대로 같은 줄만 뺀다. 속성·필터 결과를 특성 판정으로 쓰지 않는다.

### 의미하지 않는 것
약물 유사성, 독성·안전성, 활성·친화도, 합성 가능성, 3D 결합 자세. PAINS 일치는 구조 경고일 뿐 화합물을 버리라는 판정이 아니고, 필터 통과는 사용자가 정한 범위 안이라는 뜻일 뿐이다. 후보는 2D 그래프이며 수소·양성자화·토토머는 입력 그대로다.

## 리간드 도킹 (M18, `qvina_dock_v1`)

수용체 하나와 리간드 하나(사용자가 준비한 3D SDF 또는 M17 후보)를 격리된 QuickVina 2.1로 도킹하거나(자유), 후보의 부모 코어 좌표를 그대로 둔 구속 형태 샘플에 점수만 매겨(코어 고정) 포즈·점수·기하 접촉 표를 만든다(결정 0026). 점수는 엔진이 낸 값이며 친화도·결합 강도·순위가 아니다. 모든 값은 실제 qvina·RDKit·Meeko 실행 결과이거나 입력에서 정해진 값이고, 서버 프로세스는 RDKit·Meeko·MDAnalysis를 import하지 않고 qvina를 실행하지 않는다.

### 엔진과 환경
- 엔진은 `qvina2`(conda-forge `qvina 2.1.0`, build `h4a521e9_8`, 실행 파일 SHA-256 고정, `.deps/qvina/env`) 하나다. 같은 패키지의 `vina`(AutoDock Vina 1.1.2)는 호출하지 않는다. 요청 필드로 엔진·실행 파일·모듈을 고를 수 없다.
- PDBQT 준비는 작업 환경 `.deps/docking/venv-locked`(Meeko 0.8.0, RDKit 2026.03.6, MDAnalysis 2.10.0, gemmi 0.7.5)의 `mw/jobs/docking_worker.py`가 한다. 원자 유형은 AutoDock4(`ad4`), 부분 전하는 Gasteiger이며 Meeko·RDKit 버전과 함께 결과 `preparation`에 기록한다.

### 입력
- **M21 수용체 출처 `receptor_source`(단독 M18만, M19는 받지 않음)**: `{kind: "mutation_model", mutation_model: <같은 run의 게시된 mutation_model@1>, side: "wild_type_reference"|"mutant"}`를 주면 `receptor_handle`·`receptor_model_number`·`connectivity`·`receptor_instance`는 모두 없어야 한다(섞으면 `invalid_job_arguments`). 수용체 바이트는 그 쪽의 저장 mmCIF(최소화 좌표, 수소 포함, 표준 이름 HIS·CYS), 공유 결합은 저장된 `final_bonds`·`atom_mapping`(OpenMM 위상)을 `receptor_bonds@1` 사이드카 형태로 만든 것이다(거리 추론 없음, 저장하지 않고 스테이징 때 다시 만듦). 인스턴스는 없다(단백질만). 리간드는 `sdf` 출처만(후보 출처는 `mode_source_mismatch`). 모델이 검증되지 않거나 다른 run·종류·없는 side면 입장 전용 `mutation_model_invalid`. 원자 수 한도·제출 전 확인 세 항목·상자·값 규칙은 그대로다. 이 출처가 아니면 입력·결과·바이트는 M21 전과 같다(결정 0029).
- 새 가져오기 종류는 없다. M11 `chemical_raw_input@1`의 `receptor`(pdb·cif·mmcif), `receptor_bonds`(`receptor_bonds@1`), `ligand_sdf`를 그대로 쓴다(파일당 최대 10 MiB). 후보 입력은 `ligand_candidate_set@1` handle, 후보 `id`, 그 후보 집합의 부모 SDF를 가져온 `ligand_sdf` handle이다. 다른 run·다른 종류의 handle은 작업을 만들기 전에 거절한다.
- 화면 입력 순서: 수용체(+결합 사이드카) → 뺄 인스턴스 하나 또는 "없음(단백질만)" → 리간드 출처 → 방식 → 상자 출처 → 값(seed 필수)과 확인 세 항목 → 작업 시작. 어떤 선택도 자동으로 하지 않는다.

### 수용체 (M11 화학 입력 규칙과의 관계)
- M11 수용체 규칙을 그대로 쓴다: 명시적 수소 좌표와 완전한 공유 연결 정보(완전한 PDB CONECT 또는 `receptor_bonds@1` 사이드카). 연결 정보 검증은 M11 `_bonds`와 같은 규칙(자기 결합·범위 밖 참조·모호한 serial 거부, CONECT 역방향 중복은 합침, 사이드카 중복 결합은 거부)이며, M11 비공개 함수가 M11 요청 모양을 받으므로 `docking_inputs.py`가 같은 규칙을 다시 구현했다. PDB CONECT는 원본이 PDB일 때만이다. 수소·양성자화·토토머·누락 원자는 만들거나 고치지 않는다. 모델은 `receptor_model_number`로 명시한다(파일에 없으면 `receptor_invalid`). 원자 수 ≤ 10,000(뺀 인스턴스 포함).
- 비표준 잔기 인스턴스 = 물이 아니면서 HETATM이거나 이름이 M11 지원 아미노산 목록(`AMINO`, HSD·HSE·HID 등 포함)에 없는 잔기. 인스턴스 목록 읽기는 gemmi로 서버에서 잔기 7필드·원자 수·원소별 개수를 보여 주고 물은 개수만 센다(선택 보조일 뿐, 입장과 작업이 다시 검사).
- **인스턴스 하나 빼기**: `receptor_instance`(잔기 7필드, null 그대로)를 주면 7필드가 정확히 같은 비표준 잔기가 하나일 때만 그 원자(수소 포함)를 뺀다. 없으면 `receptor_instance_unknown`, 둘 이상이면 `receptor_instance_ambiguous`(첫 번째를 고르지 않음), 나머지 수용체와 공유 결합이 있으면 `receptor_instance_covalent`. 뺀 인스턴스(7필드, 원자 수, 원소별 개수)는 결과 `inputs.receptor.removed_instance`에 남는다. 주지 않으면(null) 수용체에 비표준 잔기가 없어야 한다.
- 뺀 뒤에도 물·금속 이온·보조인자·다른 리간드·변형 잔기, H C N O S가 아닌 원소가 남으면 `receptor_unsupported_residue`, altloc이 있으면 `receptor_altloc_present`로 거부한다. 조용히 지우거나 고르지 않는다. 거부 상세는 항목 최대 20개(`items`: 잔기 7필드와 원자 이름, altloc이면 altloc)와 전체 개수(`total`)이며 화면이 그대로 보여 준다.
- 명시적 수소가 하나도 없으면 `receptor_hydrogens_missing`. 일부만 없는 경우는 M11과 같이 거부하지 않는다(화학 추론 결과는 `receptor_prep_failed`로만 막힘).
- 수용체 PDBQT: M11 화학 추론(MDAnalysis `MDAnalysisInferrer(max_iter=200, sanitize=True)`, M11 `chemical_worker._receptor`와 같은 인자와 단백질 그래프 검사)으로 만든 RDKit 그래프를 공유 결합 조각마다 Meeko `MoleculePreparation`에 넘겨 원자 유형·전하를 받고, 입력 순서·입력 좌표로 ATOM 줄을 쓴다(비극성 수소는 Meeko 규칙대로 병합). 수용체는 강체다. Meeko 수용체 준비(`Polymer`)는 쓰지 않는다. 실패는 `receptor_prep_failed`(M11 검사 이름은 `detail.m11_check`). 단백질 그래프 검사는 모든 잔기에 C=O 이중결합을 요구하지만, `receptor_source`가 `mutation_model`일 때만 OXT가 있는 잔기(자유 C 말단 카르복실)는 C–O·C–OXT 중 하나가 이중결합이고 다른 쪽이 단일결합·형식 전하 −1이면 받는다(추론이 이중결합을 어느 산소에 붙이든, 사용자 승인). 가져온 수용체에는 이 완화가 없다.
- 제출 전 확인 세 항목(M11 확인 방식, 모두 true여야 함, 아니면 `acknowledgement_missing`): `keep_input_protonation`(입력 양성자화·수소를 그대로 씀), `tool_assigned_types_charges`(AutoDock4 원자 유형·부분 전하는 Meeko가 정함), `rigid_no_optimization`(수용체는 강체, 양성자화·최적화 없음). 결과 입력에 기록하지만 호출 키에는 넣지 않는다.

### 리간드 (출처 하나)
- **`sdf`**: V2000 SDF 레코드 정확히 1개, 연결된 단일 분자, 원소 H C N O S P F Cl Br I(M17과 같은 집합), 중원자 ≤ 100, Meeko가 센 능동 비틀림 ≤ 32(qvina 한도). V3000 거부. 모든 원자의 z가 같으면(평면) `ligand_not_3d`. 암시 수소가 남은 원자가 있으면 `ligand_hydrogens_missing`(수소를 만들지 않음). 원자 번호는 SDF 원자 블록 1-기반 순번(수소 포함)이다. 입력 좌표가 수용체와 같은 좌표계라고 가정하며(화면에 적음) 도구는 이를 검증하지 못한다.
- **`candidate`**: 부모 SDF의 SHA-256이 후보 집합의 `parent_sha256`과 같아야 한다(`parent_mismatch`, 항상 검사). 후보 `id`가 없으면 `candidate_unknown`. 후보 SMILES에 RDKit `AddHs` 뒤 형태를 만든다(seed 고정, 힘장 최소화 없음). 이 수소·좌표는 "생성된 것"(`generated.hydrogens`·`generated.coordinates` 참)으로 결과·화면·보고서에 표시하고 M11의 "사용자가 준 수소" 지위를 갖지 않는다. 형식 전하·양성자화·토토머는 후보 SMILES 그대로다. 부모 좌표를 쓰는 경우(코어 고정이거나 상자 출처가 `ligand_range`)에만 부모 평면 검사를 한다(`parent_not_3d`).
- 후보의 미지정 입체(M17 `stereo_flag` 포함)는 거부하지 않고 RDKit이 임의로 정한 입체로 형태를 만든다. 후보 행의 `stereo_flag`와 미지정 입체 요소 수 `unspecified_stereo_centers`를 `inputs.ligand`에 기록한다. 중원자·비틀림 한도는 `sdf` 출처와 같다.
- 리간드 준비는 Meeko `MoleculePreparation(rigid_macrocycles=True)`(고리 형태는 입력 형태 그대로)이며 실패는 `ligand_prep_failed`다.

### 상자 (출처 셋, 사용자가 명시적으로 고름)
- `ligand_range`: 입력 리간드(`sdf`는 그 SDF, `candidate`는 부모 SDF) 중원자 좌표의 최솟값·최댓값. 중심 = (최소 + 최대)/2, 한 변 = (최대 − 최소) + 2 × 여백. 여백 기본 8 Å(0–20 Å).
- `instance_range`: 뺀 수용체 인스턴스 중원자 범위에 같은 여백. `receptor_instance`가 있을 때만 쓸 수 있다(아니면 `box_invalid`).
- `manual`: 중심 x,y,z와 크기 x,y,z(Å). 한 변 8–40 Å, 유한수, 중심 절댓값 ≤ 100,000 Å.
- 범위 상자의 중심·크기는 1e-6 Å로 반올림한다(입력 좌표 자릿수 밖의 부동소수 잡음 제거, 기록된 값이 qvina가 읽는 값과 같도록). 한 변이 40 Å을 넘으면 줄이지 않고 `box_too_large`, 상자 안에 수용체 중원자가 하나도 없으면 `box_no_receptor_atoms`(좌표계가 맞지 않는 흔한 실수를 막는 검사이며, 좌표계 일치를 검증하는 것은 이것뿐이다). 그 밖의 잘못된 상자 값은 `box_invalid`. 계산한 상자는 결과 `box`에 그대로 기록한다.

### 값과 재현성
- `seed`(필수, 정수 0–2147483647), `exhaustiveness`(1–32, 기본 8), `num_modes`(1–20, 기본 9), `energy_range`(1–5 kcal/mol, 기본 3), `conformers`(코어 고정만 1–200, 기본 50, 자유 도킹은 키를 보내면 거절). `cpu`는 1 고정. 작업 시간 상한은 작업 인자가 아니라 `POST /jobs`의 `timeout_s`(화면은 600 고정, 최대 900)이며 호출 키에 들어가지 않는다.
- 같은 정규화 입력(수용체·결합·리간드 handle, 후보 id, 인스턴스, 방식, 상자, 모든 값, seed)은 같은 호출 키라 기존 작업·결과를 돌려준다(새 작업·과금 없음). seed가 다르면 새 호출 키다. 결과 객체에는 시각·작업·시도 ID가 없어 같은 입력은 같은 handle이다. 같은 seed·`--cpu 1`은 같은 포즈·점수를 낸다(착수 확인과 수락 QA 재현 검사).

### 방식
- **자유 도킹(`free`, 방법 `qvina_free_v1`)**: `qvina2`를 고정 인자(`--cpu 1 --seed … --exhaustiveness … --num_modes … --energy_range …`, 상자)로 검색 실행한다. 모드는 엔진 출력 순서대로 `mode` 1부터 번호를 붙이고 "모드 n(엔진 출력 순서)"라 부른다. 점수(`score_kcal_mol`)는 엔진이 출력한 값(출력 파일에 소수 첫째 자리까지만 있음), `engine_rmsd_lb_A`·`engine_rmsd_ub_A`는 엔진이 모드 1에 대해 낸 RMSD 한계를 그대로 저장한다. 후보 출처는 RDKit 형태 하나를 시작점으로 쓴다(한계 문장 10). 유효한 입력인데 모드가 0개면 scientific_null이다(`modes: []`, `null_result: true`, 재시도 없음).
- **코어 고정(`core_fixed`, 방법 `qvina_core_fixed_score_only_v1`, `candidate` 출처만, 아니면 `mode_source_mismatch`)**: 코어는 후보 행의 `retained_parent_atoms`(부위 밖 부모 중원자 SDF 번호)다. 후보 그래프에 코어 부분 그래프를 맞춰 대응을 구한다(없으면 `core_match_failed`, 서로 다른 좌표 배치를 주는 일치가 둘 이상이면 `core_match_ambiguous`. 코어 자기 대칭으로 같은 배치가 되는 경우는 허용하고 첫 일치를 씀). RDKit이 코어 중원자 좌표를 부모 값으로 구속한 형태를 `conformers`개 만들고(coordMap ETKDG, seed 고정, 힘장 최소화 없음, 하나도 안 되면 `embed_failed`), 각 형태를 코어로 강체 맞춤한 뒤 코어 중원자 좌표를 부모 좌표로 덮어쓴다. 각 형태에 `qvina2 --score_only --cpu 1`만 매긴다(구조 최적화·충돌 해소 없음, 상자 인자 없음). 형태를 점수 오름차순(같으면 형태 번호 순)으로 나열해 처음 `num_modes`개만 행으로 저장하고, 만든 수 `samples_generated`와 점수를 매긴 수 `samples_scored`를 센다. 이 나열은 순위가 아니며 행은 "샘플 n(점수 오름차순 나열)"이라 부른다. 저장 필드 이름은 두 방식 모두 `mode`다. 행에 `conformer_index`(0부터)를 남기고 `engine_rmsd_*`는 null이다.
- `core_max_deviation_A`(코어 고정만): 포즈의 코어 중원자와 부모 좌표 사이 최대 거리. 덮어쓴 뒤 재므로 정의상 0에 가깝다. 덮어쓰기 전 구속 임베딩 잔차(착수 확인 0.118–0.125 Å)는 기록하지 않는다. 코어 수소는 고정 대상이 아니다(RDKit이 만든 위치).
- 모드마다 상자 밖 중원자 수 `atoms_outside_box`와 포즈 중원자–수용체 중원자 최소 거리 `min_heavy_atom_distance_A`(계산값)를 기록·표시한다. 0이 아니거나 충돌이 커도 모드를 버리거나 점수를 보정하지 않는다(자유 도킹도 상자 밖 원자가 나올 수 있다).
- 포즈 SDF(`pose_sdf`): V2000, 제목 `mode_<n>`, 원자 순서 = 입력 원자 순서(`sdf`는 SDF 순번, `candidate`는 RDKit `AddHs` 순서). 수소를 담는다. qvina 출력에 없는 비극성 수소(Meeko가 병합)는 포즈 중원자에서 RDKit `AddHs(addCoords=True)`로 다시 놓은 위치다.

### 접촉 표 (기하 접촉)
- 모드마다 포즈 리간드 중원자와 수용체 중원자 사이 거리 ≤ 4.0 Å(`cutoff_A`, M2와 같은 값, 이 단계에서 조정 불가) 쌍을 센다. 종류는 M2 원소 규칙(`polar_contact`: 둘 다 N/O, `hydrophobic_contact`: 둘 다 C, 나머지 `contact`)이며 수소결합·염다리 판정이 아니다.
- 행: `ligand_serial`(포즈 SDF 1-기반 순번), `ligand_element`, `ligand_parent_serial`(코어 고정의 코어 중원자만 부모 SDF 번호, 그 밖과 자유 도킹은 null), `receptor_atom`(`residue` 7필드·`atom_name`·`altloc`·`element`·`site_index`. `site_index`는 수용체 파일의 M11 원자 순회 순번이며 뺀 인스턴스 원자도 센다), `distance_A`, `kind`. 정렬 `ligand_serial`, `site_index` 오름차순.
- 접촉 0개 모드는 빈 목록이며 계산하지 않음과 다르다. 모드당 접촉이 500행을 넘으면 자르지 않고 작업이 `resource_exceeded`로 실패한다. 게시할 때 서버가 모든 접촉의 수용체 원자 식별자와 거리를 수용체 가져오기 바이트와 저장 포즈 좌표로 다시 대조한다(거리 허용 1e-3 Å).

### 점수 표기
- 화면·보고서의 점수 이름은 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"(결과 요약·보고서는 이 문구 전체, 표 열 머리는 "qvina 점수(kcal/mol)"). 엔진 출력의 "affinity" 낱말은 옮기지 않는다.
- 점수는 소수 첫째 자리, 거리·상자는 소수 둘째 자리 `ROUND_HALF_UP`(10진 문자열 기준), 개수는 정수. 화면은 점수·접촉을 계산하지 않고 서버 값을 표시한다. 순위·best·최적·최고·개선·결합 강도를 쓰지 않는다.

### 결과 객체 `docking_result@1`
- 최상위 키: `schema`, `protocol`, `method`, `input_sha256`(acknowledgement를 뺀 정규화 입력의 SHA-256), `inputs{receptor{handle, sha256, model_number, connectivity, removed_instance, acknowledgement}, ligand{source, sdf_handle, sdf_sha256, candidate_set_handle, candidate_id, parent_sdf_handle, parent_sdf_sha256, generated{hydrogens, coordinates}, stereo_flag, unspecified_stereo_centers}, mode}`, `box{center_A, size_A, source, margin_A}`, `parameters{seed, exhaustiveness, num_modes, energy_range, conformers, cpu}`, `engine{name, version, binary_sha256, package}`, `preparation{tool, version, rdkit_version, atom_typing, charges}`, `modes[]`, `counts{modes, contacts_by_mode, null_result, samples_generated, samples_scored}`, `limitations`.
- M21 `receptor_source` 결과만 `inputs.receptor` = `{source{kind: "mutation_model", mutation_model, side}, sha256(저장 mmCIF), model_number, connectivity{kind: "mutation_model_topology"}, removed_instance: null, acknowledgement}`(가져오기 `handle` 없음). 정규화 인자가 네 수용체 키 대신 `receptor_source`를 담으므로 출처가 호출 키에 들어간다. 가져온 수용체 결과에는 `source` 키가 없다(기존 바이트 불변). 이 결과를 읽을 때마다 출처 모델도 다시 검증하고 저장 mmCIF·사이드카가 제출 때와 같은지 대조한다.
- 모드 행: `mode`, `score_kcal_mol`, `engine_rmsd_lb_A`, `engine_rmsd_ub_A`, `conformer_index`, `core_max_deviation_A`, `atoms_outside_box`, `min_heavy_atom_distance_A`, `pose_sdf`, `contacts`.
- 객체 전체 ≤ 4 MiB. 넘으면 자르지 않고 `resource_exceeded`. 게시 전에 현재 시도·취소·종료 상태, 스키마, 작업·시도 ID, 유한값, 닫힌 집합, 스테이징한 선택과의 일치를 검증하고, 읽을 때마다 완료된 게시 한 건(예약 → 정리 확인 → 결과 후보 → 종료 순서)과 입력에 대조한다. events-only로 다시 열린다(가져온 원본·qvina·Meeko 없이). 시간 초과·취소·크래시는 결과를 저장하지 않는다. dry-run run에서는 계획(`planned_call`)만 만든다.

### 닫힌 이유 집합 (`backend/mw/docking_constants.py`, 바꾸려면 사용자 결정)
- 수용체: `receptor_invalid`, `receptor_hydrogens_missing`, `receptor_unsupported_residue`, `receptor_altloc_present`, `receptor_instance_unknown`, `receptor_instance_ambiguous`, `receptor_instance_covalent`, `receptor_prep_failed`.
- 리간드: `ligand_unparseable`, `ligand_record_count`, `ligand_multiple_fragments`, `ligand_element_not_allowed`, `ligand_too_many_atoms`, `ligand_too_many_torsions`, `ligand_not_3d`, `ligand_hydrogens_missing`, `ligand_prep_failed`.
- 후보·코어: `candidate_unknown`, `parent_mismatch`, `parent_not_3d`, `core_match_failed`, `core_match_ambiguous`, `embed_failed`.
- 상자: `box_invalid`, `box_too_large`, `box_no_receptor_atoms`. 엔진·자원: `engine_failed`, `engine_output_invalid`, `resource_exceeded`.
- 서버 입장에서만: `invalid_job_arguments`, `mode_source_mismatch`, `acknowledgement_missing`, `mutation_model_invalid`(M21 `receptor_source`만, 작업 이유가 아님). 입장 검사는 작업을 만들기 전에 위 집합(수용체·상자·후보 일부 포함)으로 거절하고 예산을 쓰지 않는다. 작업 프로세스는 같은 검사를 다시 하고 위 집합으로만 실패한다. 스테이징 기록이 잘못된 경우처럼 사용자 입력이 아닌 결함은 가장 가까운 `engine_failed`와 짧은 설명이다.
- capability 이유: `worker_missing`, `engine_missing`, `engine_hash_mismatch`, `handshake_failed`, `version_mismatch`. 작업 시작 때 pin이 바뀌었으면 기존 큐 이유 `worker_version_invalid`.

### 고정 한계 문장 (문자 그대로, 순서 고정, 해당 조건일 때만)
  1. (항상) "점수는 qvina 2.1(Vina 계열 스코어링 함수)이 낸 값(kcal/mol)이며 결합 친화도·결합 자유 에너지가 아니다."
  2. (항상) "같은 수용체·상자·seed·방식(자유/코어 고정)·값에서 나온 점수끼리만 나란히 볼 수 있다."
  3. (항상) "수용체는 입력 그대로의 강체이며 수소·양성자화·토토머를 바꾸지 않았고, AutoDock4 원자 유형·부분 전하는 Meeko가 정한 값이다."
  4. (항상) "리간드 고리 형태는 입력 형태(후보는 RDKit이 만든 형태)로 고정되어 탐색하지 않았다."
  5. (항상) "접촉은 거리만으로 센 기하 접촉이며 수소결합 등 상호작용 판정이 아니다."
  6. (`free`) "포즈는 엔진이 낸 배치이며 실험으로 확인한 결합 자세가 아니다."
  7. (`candidate`) "후보의 3D 좌표와 수소는 RDKit이 만든 것이며 입력 구조가 아니다."
  8. (`core_fixed`) "코어 중원자 좌표만 부모 값으로 고정했고 나머지는 RDKit 구속 형태 샘플이며, 점수만 매기고 구조는 최적화하지 않았다. 이 배치는 실험으로 확인한 결합 자세가 아니다."
  9. (뺀 인스턴스가 있을 때) "수용체에서 지정한 리간드 인스턴스 하나만 뺐고 그 밖의 요소는 바꾸지 않았다."
  10. (`candidate` + `free`) "자유 도킹은 RDKit 형태 하나를 시작점으로 썼다."
  11. (`unspecified_stereo_centers` > 0) "미지정 입체 중심의 입체는 RDKit이 임의로 정한 것이다."
  12. (수용체 출처가 `mutation_model`, M21, 늘 맨 뒤) "수용체는 변이 모델링으로 최소화한 구조이며 리간드 자세는 이 수용체에 맞춰 조정하지 않았다(리간드 좌표는 사용자가 준 SDF 그대로)."
- 결과·보고서·capability가 같은 문장을 쓴다(capability `limitations`는 12문장 전부). 화면은 후보 출처를 고르면 제출 전에 문장 7·10·11을 안내한다.

### 작업과 예산
- 기존 `JobQueue` 비싼 작업 경로(run 단위 첫 비싼 계산 승인, 예산, 취소, 재시도, guardian). 도킹 한 번(수용체 변환·샘플 생성·qvina 실행 전부)이 비싼 계산 1단위다. 한 번에 한 작업만 화면에서 진행한다.
- 사용 가능 여부(`methods.ligand_docking`): 두 잠긴 환경과 설치 기록·잠금 파일이 있고, `qvina2` 해시가 설치 기록과 고정값 모두와 같고, 작업 모듈 handshake의 Meeko·RDKit·MDAnalysis·gemmi 버전이 고정값과 같을 때만 사용 가능. 아니면 숫자·컨트롤 없이 이유만.

### 보고서
- `method_report_manifest@1`, `analysis_type: "ligand_docking"`, 렌더 `ligand_docking_markdown@1`. 입력은 도킹 결과 handle 하나(자유·코어 고정을 한 보고서에 섞지 않음). 만들기·다시 열기·다운로드는 도킹을 다시 하지 않고, 다시 열 때 결과 객체를 검증한 뒤 manifest·주장·Markdown 바이트를 저장 객체에서 다시 만든 것과 비교한다.
- 증거는 모두 계산값(`computed`)이며 결과 handle·필드 경로에 묶인다: 모드 수, 모드별 `score_kcal_mol`, 접촉 수(`count`·종류별 `count_where`, 저장 접촉 행에 조건을 적용해 검증할 때마다 다시 셈, 조건은 `row_selector`), 상자 중심·크기·출처·여백, 파라미터, 엔진 이름·버전, Meeko·RDKit 버전, 수용체 입력, 뺀 인스턴스(7필드·원자 수), 리간드 출처 필드, 상자 밖 원자 수, 최소 거리, 코어 고정이면 샘플 수와 `core_max_deviation_A`. 파생값은 저장 점수의 최솟값·최댓값만("점수 최솟값", "점수 최댓값", "최고·최적"이라 쓰지 않음). 모드가 0개면 행 통계가 없다. null 필드는 주장이 되지 않으므로 0으로 쓰이지 않는다.
- M21 `receptor_source` 결과의 보고서는 수용체 절에 가져오기 줄 대신 출처(변이 모델 handle과 쪽)를 쓰고 가져오기 handle 주장이 없다. 나머지 수용체 주장은 같고, 가져온 수용체 보고서는 바이트 그대로다.
- 후보 출처 결과는 후보 출처·생성된 수소·좌표 표시·부모 해시를, 코어 고정 결과는 모든 행의 `core_max_deviation_A`를 반드시 싣는다(없으면 보고서를 만들지 않음). 코어 고정 행은 "샘플"이라 부른다.
- 점수는 `Decimal(str(v))`를 0.1 `ROUND_HALF_UP`, 거리·상자는 0.01, 개수는 정확히 일치. 틀린 반올림, 다른 statement의 필드 인용, 계산하지 않은 값을 0으로 쓰기는 거부한다.
- 해석 금지어: M17 목록(M15·M16 포함)에 순위·최고·개선·결합 강도·rank·best·improve·stronger를 더해 모든 줄을 검사한다. 고정 한계 문장과 문자 그대로 같은 줄은 건너뛰고, 그 밖의 줄은 고정 점수 문구(`SCORE_LABEL`, 금지어 "친화"를 포함)만 지운 뒤 나머지를 검사한다(명세의 "한계 문장 줄만 제외"보다 한 가지 넓음, 결정 0026).

### 의미하지 않는 것
결합 친화도·결합 자유 에너지·ΔΔG·결합 강도, 후보·포즈의 순위나 개선, 실험으로 확인한 결합 자세, 수소결합·염다리 판정, 약물 유사성·활성·합성 가능성. 점수는 같은 수용체·상자·seed·방식·값에서 나온 것끼리만 나란히 볼 수 있다. 수용체는 입력 그대로의 강체이고, 후보의 3D 좌표·수소는 RDKit이 만든 것이다.

## 리간드 일괄 도킹 (M19, `qvina_batch_dock_v1`)

M17 후보 집합 하나의 후보 여러 개(+ 선택 사항 부모 기준 행)를 한 수용체·상자·seed·방식·값으로 차례로 도킹해, 후보별 qvina 점수를 한 표에서 나란히 보고 일괄 보고서로 남긴다(결정 0027). 한 행의 계산은 M18 "리간드 도킹" 규칙 그대로이며 여기서 바꾸지 않은 M18 규칙(수용체·리간드·상자·값·점수 표기·한계 문장·닫힌 이유)은 모두 적용된다. 일괄은 점수의 "좋음"·순위·개선을 말하지 않는다. 표의 정렬은 표시 순서일 뿐이다.

### 입력과 일괄 조건
- 작업 인자(고정 모양, 알 수 없거나 빠진 키는 `invalid_job_arguments`): M18의 수용체·상자·값·확인 필드(`receptor_handle`, `receptor_model_number`, `connectivity`, `receptor_instance`, `mode`, `box`, `parameters`, `acknowledgement`, 이름·규칙 M18 그대로) + `candidate_set_handle`(`ligand_candidate_set@1`), `parent_sdf_handle`(그 후보 집합의 부모를 가져온 `ligand_sdf`, SHA-256이 후보 집합 `parent_sha256`과 다르면 `parent_mismatch`), `candidate_ids`(비어 있지 않은 문자열 1–50개, 중복 거부), `include_parent`(불리언, 기본 false). `ligand` 키는 없다. 일괄이 행마다 리간드를 만든다: 후보 행은 M18 `candidate` 출처, 부모 행은 `parent_sdf_handle`의 M18 `sdf` 출처.
- 검사 순서: 키 → `candidate_ids` 모양 → `batch_empty`(0개) → `batch_too_large`(50개 초과) → 중복 → `include_parent` → `mode` → `batch_parent_not_allowed`(`include_parent: true` + `core_fixed`) → 공유 필드의 M18 순서 → 후보 집합 검증 읽기(실패는 `invalid_job_arguments`) → `candidate_unknown`(집합에 없는 id) → 행마다 M18 입장 검사(`receptor_*`, `box_*`, `acknowledgement_missing`, `parent_mismatch` 등). 모두 작업을 만들기 전 422 `input_invalid`이고 예산을 쓰지 않는다.
- 행 순서 = 부모 행(있으면 첫 행) 다음, 고른 id를 **후보 집합 안의 순서**로(클릭 순서가 아님). 일괄에는 실제 후보 id 목록만 기록하고 화면의 M17 필터 조건은 기록하지 않는다.
- 일괄 전체에서 수용체·뺀 인스턴스·상자·seed·방식·값은 하나다. 상자는 작업 프로세스가 수용체 준비 뒤 한 번 계산해 모든 행에 쓴다(`ligand_range`는 부모 SDF 중원자 범위라 후보와 무관). 방식을 섞지 않는다. 부모 기준 행은 자유 방식에서만 있다(부모에는 고정할 코어가 없고 새 방법을 만들지 않음).
- 후보 하나의 문제(3D 생성 실패, 코어 일치 실패, 비틀림 초과, 평면 부모 등)는 입장에서 거절하지 않고 그 행의 `failed`(M18 이유)로 남긴다. 부모 SDF가 평면이면 부모 행만 `failed`(`ligand_not_3d`)이고 후보 행은 계속한다.

### 행 = 단독 M18 도킹
- 각 행의 작업 인자·선택 기록·`input_sha256`·호출 키는 같은 입력의 단독 `qvina_dock_v1` 요청과 같다. 그래서 행 결과 `docking_result@1`은 같은 입력의 단독 M18 도킹과 같은 handle이다(착수 확인과 백엔드 테스트로 바이트 비교). 일괄 때문에 M18 객체에 필드를 더하지 않는다.
- 수용체 검사·PDBQT 준비는 일괄마다 한 번이다(결과 객체에 수용체 PDBQT 텍스트가 들어가지 않고 같은 수용체 바이트에서 같은 PDBQT가 나오므로 행 결과가 바뀌지 않는다). 행은 한 번에 하나, 순서대로, `--cpu 1`이다.
- 수용체·상자 문제로 첫 행 전에 멈추면(`receptor_prep_failed`, `box_*`, 엔진 확인 실패) 작업 실패이고 요약을 만들지 않는다.

### 상한 (`backend/mw/docking_batch_constants.py`, 바꾸려면 사용자 결정)
- 후보 ≤ 50(+ 부모 행 1). 행당 ≤ 300초(그 행의 리간드 준비·형태 생성·qvina·접촉 계산 전체). 일괄 전체 ≤ 7200초(작업 프로세스 시작부터, 수용체 준비·부모 행 포함). 두 시계는 작업 프로세스 안에서 잰다.
- 작업 시간 한도(`POST /jobs`의 `timeout_s`)는 이 프로토콜만 최대 7800초(전체 시계 7200초 + 마무리 여유)이고 화면은 7800을 보낸다. 다른 프로토콜의 한도는 그대로다. 실제 마감은 작업 시작 + min(남은 활동 시간, `timeout_s`)다.
- 출력 총량: 행 결과 파일 합 128 MiB(조정 가능한 기본값). 행 하나의 결과는 M18 한도 4 MiB, 요약 객체는 1 MiB.
- 꽉 찬 일괄(새로 계산할 행 N × 300 > 7200)은 설계상 끝까지 못 갈 수 있다. 시작 전 확인이 이를 알린다(`full_batch_may_be_partial`).

### 행 상태와 이유 (닫힌 집합)
- 행 상태는 정확히 `scored`(결과의 모드·샘플 ≥ 1), `null_result`(유효하지만 모드 0개, M18 scientific_null), `failed`, `cancelled`, `not_run`이다. 점수는 `scored` 행만 가진다. 나머지는 점수 없음이며 화면·정렬·보고서 어디서도 0이 아니다.
- 이유: `scored`·`null_result`는 null. `failed`는 M18 닫힌 이유 전부 + `candidate_timeout`(행당 시간 초과, 그 행의 qvina를 정리하고 일괄은 계속) + `worker_failed`(진행 중이던 행에서 작업 프로세스가 사라짐). `cancelled`는 `cancelled`(사용자 취소) | `time_exhausted`(전체 시간 소진). `not_run`은 `cancelled` | `time_exhausted` | `worker_failed` | `resource_exceeded`(출력 총량). 이유는 코드뿐이며 자유 문장 `detail`은 없다.
- 행 하나의 실패는 그 행만 `failed`이고 일괄은 계속한다. 취소·전체 시간·출력 총량은 일괄을 멈춘다. 출력 총량을 넘긴 행은 저장하지 않고 그 행과 남은 행이 모두 `not_run`(`resource_exceeded`)이다.

### 요약 행을 만드는 규칙 (서버)
작업 프로세스는 행 시작 때 `rows/<n>.started`, 행이 끝나면 결과 파일(`scored`·`null_result`만)과 상태 파일을 원자적으로(임시 파일 + fsync + rename + 디렉터리 fsync) 쓴다. 서버는 작업 프로세스 그룹이 비었음을 확인한 뒤, 작업이 어떻게 끝났든 행마다 다음 순서로 상태를 정한다.
1. 재사용 행은 저장된 결과에서 채운다(작업이 계산하지 않으므로 멈춤과 무관).
2. 결과 파일이 M18 게시 검증(행의 선택 기록, 닫힌 집합, 수용체 원자·거리 재대조)을 통과하면 게시하고 그 결과로 `scored`/`null_result`. 상태 파일이 `scored`/`null_result`인데 결과를 게시할 수 없으면 `failed`(`engine_output_invalid`).
3. 상태 파일만 있으면 그 값. 작업 프로세스가 SIGTERM을 받고 쓴 `cancelled`는 서버가 보낸 이유로 해석한다: 사용자 취소면 `cancelled`, 작업 마감이면 `cancelled`(`time_exhausted`), 그 밖(부모 소실·강제 종료)이면 상태 없음으로 본다.
4. `.started`만 있으면 진행 중이던 행: 멈춘 이유가 취소·시간 소진이면 `cancelled`, 출력 총량이면 `not_run`, 그 밖이면 `failed`(`worker_failed`).
5. 아무 파일도 없으면 `not_run`(이유 = 멈춘 이유).
- 멈춘 이유는 상태 파일에 처음 기록된 멈춤, 없으면 서버가 아는 작업 종료 이유다(사용자 취소 `cancelled`, 작업 마감 `time_exhausted`, 크래시·강제 종료·자원 한도·서버 재시작 `worker_failed`, 작업 프로세스가 스스로 끝내며 쓴 종료 기록의 `stop_reason`). 일괄 `stop_reason`은 첫 `cancelled`·`not_run` 행의 이유다.

### 일괄 상태
- `status`는 `cancelled`·`not_run` 행이 하나라도 있으면 `partial`, 아니면 `complete`다. `stop_reason`은 `partial`일 때만 null이 아니며 `cancelled` | `time_exhausted` | `worker_failed` | `resource_exceeded` 중 가장 먼저 일어난 하나다.
- 실패 행이 있어도 `complete`일 수 있다(실패는 행에 이유로 남음). 마지막 행까지 모두 끝났으면 그 뒤에 시간·취소·중단이 와도 `complete`다. 진행 중이던 마지막 행이 `failed`(`worker_failed`)로 끝나면 `not_run` 행이 없으므로 `complete`다.
- 취소·시간 소진·크래시·서버 재시작 어느 경우든 끝낸 행은 남는다. 첫 행 전에 멈춘 일괄(수용체 준비 실패 등)은 요약이 없다. 서버 재시작 복구는 중단된 작업을 닫으며(작업 기록 `interrupted`) 스테이징에 남은 검증 가능한 행을 게시하고 요약(`partial`, 사용자가 이미 취소를 요청했으면 `cancelled`, 아니면 `worker_failed`)을 만든다. 게시하지 못한 행은 잃으며 숨기지 않는다.
- 작업 기록 상태와 요약 상태는 다르다: 작업 프로세스가 스스로 끝까지 가거나 전체 시계 7200초·출력 총량으로 멈추면 작업은 `done`(요약은 `complete` 또는 `partial`), 사용자 취소는 작업 `cancelled`, 작업 마감은 작업 `failed`(`resource_exceeded`, "job timeout"), 크래시·자원 한도는 작업 `failed`이며, 이 셋도 요약이 있으면 `partial`로 남는다. 화면은 작업 실패만 보이지 않고 요약의 상태·멈춘 이유를 함께 보인다.

### 저장된 결과 재사용
- 행의 M18 호출 키 전체(정규화 인자 + 고정 환경 pin, 작업 모듈 해시 포함)와 같은 결과가 이 run에 있고(단독 M18 작업이 낸 것이든 일괄 행으로 게시된 것이든) 지금 검증을 통과하면, 그 행은 새로 계산하지 않고 그 handle을 쓴다. 비싼 계산 단위를 쓰지 않는다. 재사용 여부는 작업 시작 때 run 실행 잠금 안에서 한 번 정한다.
- 작업 모듈 해시가 다른 결과는 같은 handle이 나올 입력이어도 재사용하지 않는다. M19가 `docking_worker.py`에서 행 계산 함수를 추출했으므로 M19 전에 만든 M18 결과는 재사용되지 않는다.
- 이어 하기는 별도 기능이 아니다. 같은 설정으로 새 일괄을 만들면 끝난 행은 재사용되고 못 끝낸 행만 계산된다.
- 재사용 여부는 요약 객체에 넣지 않는다(같은 입력·같은 결과면 같은 요약). 요약 게시 이벤트의 재사용 행 번호와 시작 전 확인으로 화면이 "저장된 결과 재사용"을 표시한다.

### 같은 일괄 (호출 키)
- 일괄 호출 키 = `batch_input_sha256` = 수용체 handle·SHA-256·모델·연결 정보(사이드카 handle·SHA-256)·뺀 인스턴스, 후보 집합 handle, 부모 SDF handle·SHA-256, 후보 id(집합 순서), `include_parent`, 방식, 상자 요청, 값 전체, seed의 정규화 SHA-256. 확인 세 항목·`timeout_s`·재사용·시간·작업 ID는 넣지 않는다. handle이 run마다 다르므로 다른 run의 일괄과 같은 키가 될 수 없다.
- 같은 키의 작업이 대기·실행 중이거나 같은 키의 검증된 `complete` 요약이 있으면 `POST /jobs`가 그 작업을 돌려준다(새 작업·과금 없음). 같은 키의 `partial` 일괄은 새 일괄을 막지 않는다.

### 예산, 첫 계산 승인, 한도 증액
- 과금: 새로 계산하는 행마다 비싼 계산 1단위. 작업 시도 하나가 시작 때(승인된 시작 뒤, 프로세스를 띄우기 직전) N단위를 한 번에 예약하고 중간에 멈춰도 환불하지 않는다. 재사용 행·입장 거절·대기 중 취소·dry-run은 과금하지 않는다. N = 0이면 0단위 예약을 기록하고 작업 프로세스·qvina 없이 저장된 결과로 요약만 게시한다. 활동 시간은 일괄이 실제로 쓴 경과 시간만 더한다.
- 시도는 1회다. 자동 재시도도, `/jobs/{id}/retry`도 없다(작업 중단은 `partial`·`worker_failed`, 다시 하려면 같은 설정으로 새 일괄).
- run의 첫 비싼 계산 승인(`expensive_first_call`)은 M18과 같고 N = 0이어도 필요하다. 한도 증액은 이 승인을 만들지 않고, 이 승인도 한도를 올리지 않는다.
- 필요량: 비싼 계산 N단위, 활동 시간 min(7800, N × 300 + 300)초(N = 0이면 60초). 부족분 = max(0, 필요량 − (한도 − 사용량)) 축마다. 부족분이 하나라도 0보다 크면 작업 입장이 429 `batch_limit_raise_required`로 거절하고(작업·예산 기록 없음) 화면이 증액 승인을 제안한다.
- 증액 승인: 사람이 화면에서만 누른다(HTTP 경로 하나, 도구·M13 분석 흐름 단계·M8 모델 명령·자율 루프에 등록하지 않음). 서버는 run 실행 잠금 안에서 그 시점의 부족분을 다시 계산해 그만큼만 올린다: 비싼 계산 증가분 = min(부족분, 필요량), 활동 시간 증가분 = 부족분이 0이면 0, 아니면 min(부족분, 필요량) + 60초(증액 직후 청구되는 런타임 오버헤드 때문에 다시 부족해지지 않도록). 그래서 증가분은 한 일괄의 필요량(51단위, 7800 + 60초)을 넘지 않는다. 절대 한도에는 상한이 없다. 부족하지 않으면 아무것도 바꾸지 않는다(멱등, 이벤트 없음). 사용량이 이미 한도를 60초 넘게 넘은 run은 한 번의 승인 뒤에도 부족할 수 있고, 그때는 다시 명시적으로 승인한다.
- 기록: `budget_limit_updated`(`by: "human"`) 하나에 새 한도 전체와 맥락(`purpose: "docking_batch_limit_raise"`, `batch_input_sha256`, `new_dockings`, `needed`, `shortfall`, `increase`, 바뀐 축의 `limits_before`·`limits_after`)을 담는다. 재생은 `limits`만 읽으므로 events-only 복구가 같다. 올라간 한도는 run 끝까지 유지되고(취소·부분 완료여도) 예산 표시와 보고서 예산 스냅숏에 그대로 나온다. 승인은 소진된 사용량을 되돌리지 않고 예약·과금·환불도 하지 않는다. dry-run run과 취소된 run은 증액을 거절한다(아무것도 쓰지 않음).

### 요약 객체 `docking_batch_result@1`
- 서버가 모든 행 결과를 게시한 뒤 마지막에 만든다(그래서 요약이 있으면 거기 쓰인 handle은 모두 있다). 최상위 키: `schema`, `protocol`(`qvina_batch_dock_v1`), `method`(`qvina_free_v1` | `qvina_core_fixed_score_only_v1`), `batch_input_sha256`, `inputs{receptor{handle, sha256, model_number, connectivity, removed_instance, acknowledgement}, candidate_set{handle, parent_sdf_handle, parent_sdf_sha256}, candidate_ids, include_parent, mode}`, `box{center_A, size_A, source, margin_A}`, `parameters{seed, exhaustiveness, num_modes, energy_range, conformers, cpu}`, `engine`·`preparation`(행 결과와 같은 값), `limits{max_candidates: 50, per_candidate_s: 300, total_s: 7200}`, `status`, `stop_reason`, `rows`, `counts{rows, scored, null_result, failed, cancelled, not_run}`, `limitations{batch_statements, m18_sentences}`.
- 행: `row_index`(0부터), `kind`(`parent` | `candidate`), `candidate_id`(부모면 null), `state`, `reason_code`, `result_handle`(`scored`·`null_result`만), `score_kcal_mol`(`scored`만, 행 결과 `modes[0].score_kcal_mol`을 그대로 복사), `score_row_label`(`scored`만, 자유 "모드 1(엔진 출력 순서)", 코어 고정 "샘플 1(점수 오름차순 나열)"). 점수 열은 각 행 결과의 첫 행이며 "best"·최솟값이 아니다.
- 시간·재사용·작업 ID를 넣지 않는다. 게시 때와 읽을 때마다 일괄 선택 기록, 모든 행 결과(M18 검증 읽기), 행 입력 일치(`input_sha256`, 후보 id, 출처, 방식, 수용체, 상자, 값, 엔진·준비), 점수 사본, 상태·이유 규칙, 개수, 한계 문장, 크기, 엔진 pin으로 다시 검증한다. 어긋나면 게시하지 않고, 읽기는 증거 오류다. events-only로 다시 열린다.
- 요약을 만들 수 없으면(증거 오류) 작업은 그 이유로 실패하지만 이미 게시한 행 결과는 자기 게시 증거로 읽히고 재사용된다.

### 고정 문장 (문자 그대로, 순서 고정)
  - B1 (항상) "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, 표의 정렬은 표시 순서일 뿐 순위가 아니다."
  - B2 (`partial`) "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다."
  - B3 (부모 행이 있을 때) "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다."
- M18 한계 문장 1–11은 어느 한 행이라도 그 조건(방식, 행의 리간드 출처, 뺀 인스턴스, 미지정 입체 중심 > 0)에 해당하면 번호로 `m18_sentences`에 넣고 본문은 M18 상수에서 가져온다. 시작 전 확인은 요청에서 정해지는 번호만 보이고 문장 11은 결과가 정한다.
- 점수 이름·열 머리·금지어는 M18과 같다("qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)", 열 "qvina 점수(kcal/mol)", 순위·최고·best·최적·개선·결합 강도 금지).

### 보고서
- `method_report_manifest@1`, `analysis_type: "ligand_docking_batch"`, 렌더 `ligand_docking_batch_markdown@1`. 입력은 요약 handle 하나(방식 하나라 자유·코어 고정이 섞이지 않음). 후보별 M18 보고서를 만들지 않는다.
- 증거는 모두 계산값(`computed`): 요약의 공유 설정(수용체 가져오기, 뺀 인스턴스 7필드·원자 수, 후보 집합·부모 SDF, 상자, 값, 엔진, Meeko·RDKit 버전), 행 개수(`count(rows)`, 상태별 `count_where`, 검증할 때마다 다시 셈), `scored` 행마다 점수 주장 둘(요약 `rows[i].score_kcal_mol`과 행 결과 `modes[0].score_kcal_mol`, 같은 `row_selector`, 같은 값이어야 함). 점수는 `Decimal(str(v))`를 0.1 `ROUND_HALF_UP`.
- `failed`·`cancelled`·`not_run`·`null_result` 행에는 점수 주장이 없다. 표 칸은 비우고 이유 코드만 쓴다. 그런 행의 점수 주장, 다른 statement의 필드, 틀린 반올림, 해석 문장은 거부한다.
- 금지어 검사는 M18 목록 그대로, 고정 M18 한계 문장·B1–B3와 문자 그대로 같은 줄은 건너뛰고(B1·B3는 순위·개선을 부정하려고 그 낱말을 씀), 그 밖의 줄은 점수 이름(`SCORE_LABEL`)만 지운 뒤 검사한다.
- 만들기·다시 열기·다운로드는 도킹을 다시 하지 않는다. 다시 열 때 요약과 행 결과를 검증하고 manifest·주장·Markdown 바이트를 저장 객체에서 다시 만든 것과 비교한다. 보고서 예산 스냅숏은 생성 시점 값(올라간 한도 포함)이다.

### 화면 규칙
- 리간드 설계·탐색 탭의 M18 도킹 영역 다음에 있다. 가져오기는 M18 도킹 영역에서 하고 일괄 영역은 이미 가져온 수용체·사이드카·부모 SDF와 후보 집합을 고른다. 입력 순서: 수용체(+사이드카) → 뺄 인스턴스 → 후보 집합 → 후보 선택(M17 필터 결과 + 체크박스, "선택 n / 50", 51번째는 체크할 수 없음) → 방식 → 부모 기준 행(자유에서만) → 상자 → 값과 확인 세 항목 → 시작 전 확인 → (부족하면 증액 승인) → 일괄 시작. 어떤 선택도 자동으로 하지 않는다.
- 시작은 지금 인자와 정확히 같은 인자로 받은 시작 전 확인이 입장 통과·부족분 0일 때만 열린다. 시작 전 확인은 N, 필요 단위·시간, 잔여, 부족분, 재사용 행 수, "시작하면 N단위가 소진되고 중간에 멈춰도 돌려받지 않음", 꽉 찬 일괄 경고, 일괄 중 이 run의 다른 계산·보고서와 다른 비싼 작업이 기다린다는 안내, B1과 M18 문장을 서버 값 그대로 보인다.
- 결과표 열: 행 번호, 후보 id(부모는 "부모(기준 입력)"), 상태, "qvina 점수(kcal/mol)"(`scored`만 숫자), 점수 대상, 이유, 재사용 표시, 상세 열기. 기본 순서는 일괄 행 순서. 행 번호·후보 id·점수 열을 오름·내림차순으로 정렬할 수 있고 점수 없는 행은 방향과 무관하게 늘 끝(행 순서)이다. 순위 열·최고 표시·강조 없음. 결과가 없는 행의 "상세 열기"는 비활성이고 `null_result` 행은 열 수 있다. 일괄 상태·멈춘 이유와 B2를 표 위에 둔다. "상세 열기"는 기존 M18 도킹 영역의 상세(모드·접촉 표·포즈 SDF)를 연다.
- 화면은 점수·집계·부족분을 계산하지 않는다. 부모 대비 차이·잔기 비교 표·뷰어 표시 없음.

### 의미하지 않는 것
M18의 "의미하지 않는 것" 전부. 그에 더해 표의 정렬·첫 행 점수는 후보의 순위·우열이 아니고, 부모 행과의 점수 차이는 개선·악화가 아니며, `partial` 일괄의 빈 칸은 0이 아니라 계산하지 않음이다.

## 리간드 GA 설계 (M22, `qvina_ga_dock_v1`)

같은 run에 게시된 M17 후보 집합 하나(최대 2,000개) 안에서 유전 알고리즘(GA)이 세대마다 어느 후보를 도킹할지 정한다(결정 0030). 개체 하나 = 풀의 후보 하나이고, 개체의 점수는 그 후보의 단독 M18 자유 도킹 결과의 첫 모드 qvina 점수(kcal/mol)뿐이다. 개체 도킹은 M18 "리간드 도킹" 규칙 그대로이며(수용체·상자·값·점수 표기·한계 문장·닫힌 이유) 여기서 바꾸지 않았다. GA는 "넓은 후보 풀에서 도킹 상한 안에 어디를 볼지 정하는 탐색 방법"이며 순위 도구가 아니다. 점수가 낮은 개체를 남기는 것은 탐색 규칙일 뿐 결합이 좋다·친화도가 높다·개선되었다는 뜻이 아니다.

### 입력
- 작업 인자(고정 모양, 알 수 없거나 빠진 키는 `invalid_job_arguments`): M18의 수용체·상자·값·확인 필드(`receptor_handle`, `receptor_model_number`, `connectivity`, `receptor_instance`, `box`, `parameters`, `acknowledgement`, 이름·규칙 M18 그대로, `parameters.seed`가 도킹 seed) + `candidate_set_handle`(같은 run의 게시된 `ligand_candidate_set@1`), `parent_sdf_handle`(그 후보 집합의 부모 SDF, M19와 같은 검증), `filter`(M17 필터 사양 `{ranges, pains_exclude}`, 선택, 기본 `{}`, `ligand_filters.normalize_filter_spec`로 정규화), `ga`(아래 키 전부, 필수). `mode`·`ligand` 키는 없다(자유 도킹 고정).
- GA 파라미터 `ga`(`backend/mw/ligand_ga_constants.py` `GA_RANGES`, 바꾸려면 사용자 결정). 정수는 `bool`이 아니고 `random_fraction`은 유한 실수다.

| 키 | 의미 | 범위 | 기본 |
|---|---|---|---|
| `seed` | GA 탐색 난수 seed(도킹 seed와 별개) | 0–2147483647 | 없음(필수) |
| `population_size` | 세대당 개체 수 | 4–24 | 12 |
| `generations` | 세대 수 상한(첫 세대 = 세대 1) | 1–8 | 5 |
| `elite_count` | 다음 세대로 그대로 이어받는 개체 수 | 0–4, `population_size − elite_count ≥ 2` | 2 |
| `tournament_size` | 부모 선택 토너먼트 크기 | 2–4 | 2 |
| `neighbor_count` | 유사 후보를 뽑는 가장 가까운 미평가 후보 수 | 3–30 | 10 |
| `random_fraction` | 새 자리 중 무작위 후보 비율 | 0–0.5 | 0.2 |
| `patience` | 점수 최솟값이 이 세대 수 연속 작아지지 않으면 중단 | 1–8 | 3 |
| `max_new_dockings` | 이 실행의 새 도킹 건수 상한 | `population_size`–100 | 60 |
| `total_s` | GA 전체 시간 상한(초, 수용체 준비 포함) | 600–14400 | 7200 |

- 작업 시간 한도(`POST /jobs`의 `timeout_s`)는 이 프로토콜(M23 서열 GA도 같음)만 `total_s + 600` 이상 15000 이하이고 서버가 기본값을 채우지 않는다(화면은 늘 `total_s + 600`). 범위 밖은 `invalid_job_arguments`다. 개체 도킹 한 건은 300초 고정(M19 `PER_CANDIDATE_S`).

### 입장 검사 (작업을 만들기 전, 예산 없음, 이 순서)
1. `invalid_job_arguments`(422): 키·형식·범위·교차 규칙(`elite_count`, `max_new_dockings < population_size`), `timeout_s`, 필터 사양 오류, 검증되지 않는 후보 집합(종류·run·게시).
2. M18/M19 입장 이유 그대로(422): 공유 필드의 M18 검사, 그다음 **첫 적격 후보 하나를 대표로** `docking_batch_inputs.row_request` → `docking_bundle.submission`(수용체 M11 규칙·인스턴스 7필드·부모 해시 `parent_mismatch`·상자·확인 등). 적격 후보가 0개면 대표가 없으므로 3이 먼저 난다.
3. `ga_pool_too_small`(422): 적격 후보 수 < `population_size`(`detail{eligible_count, population_size}`).
4. `ga_reuse_too_large`(422): 재사용할 저장 결과의 크기 합 > 128 MiB.
5. `ga_limit_raise_required`(429, 과금 없음): 예산 부족(아래).
- 4·5는 저장 결과와 run 예산이 필요해 `JobQueue.submit` 안에서 호출 키를 만든 뒤 본다(`ligand_ga_jobs.require_admission`). 시작 때 재사용 계획을 다시 정하면서 4를 한 번 더 본다(예약 전).

### 풀과 적격
- 풀 = 후보 집합의 `candidates[]` 저장 순서. 필터를 저장값에 서버가 평가한다(`ligand_filters.evaluate_row`): 사양이 비면 전부, 아니면 `passes_all === true`만 **적격**이다. 필터 탈락 후보는 도킹하지 않고 요약의 `pool.filter_excluded_count`와 사양으로 남는다.
- 유사도 = 저장 SMILES의 RDKit Morgan 지문(반지름 2, 2048비트, 생성기 기본값 고정) 온비트 집합의 Tanimoto(정확 분수 |A∩B|/|A∪B|). 계산은 작업 모듈만 한다. 저장 값은 그 분수를 소수 여섯째 자리 `ROUND_HALF_UP`한 **문자열**이고, 이웃 정렬은 전체 정밀도로 한다. 지문 수학 값이며 점수나 활성이 아니다.

### 절차 (작업 모듈 `mw/jobs/ligand_ga_worker.py`, 결정적)
- 난수는 `random.Random(ga.seed)` 하나이고 호출은 `rng.sample`·`rng.choice`뿐이다. 순서: 세대 1 `rng.sample(적격 후보(풀 순서), population_size)`. 그 뒤 세대마다 유사 자리를 자리 순서대로(자리마다 `rng.sample(직전 세대의 점수 있는 개체(이어받음 먼저, 그다음 평가 순서), min(tournament_size, 개수))` 다음 `rng.choice(이웃)`), 그다음 무작위 자리를 자리 순서대로(`rng.choice(아직 뽑히지 않은 적격 후보(풀 순서))`). 뽑을 후보가 없으면 그 자리에서는 난수를 부르지 않는다.
- **이어받음**: 직전 세대의 점수 있는 개체 중 점수가 낮은 `elite_count`개(동점은 풀 순서)를 다시 도킹하지 않고 넣는다(점수 있는 개체가 모자라면 있는 만큼).
- **새 자리** `slots = population_size − 이어받은 수`, 무작위 자리 `r = floor(random_fraction × slots + 0.5)`, 나머지는 유사 자리. 점수 있는 개체가 하나도 없으면 모든 새 자리가 무작위 자리다.
- **유사 자리**: 토너먼트에서 점수가 가장 낮은 개체(동점 풀 순서)가 부모, 이 실행에서 아직 뽑히지 않은 적격 후보를 (Tanimoto 내림차순, 풀 순서)로 정렬한 앞 `neighbor_count`개 중 하나가 자식이다. "아직 뽑히지 않음" = 이 실행에서 한 번도 뽑히지 않음(만들고 있는 세대의 앞 자리 포함). 교차는 없다.
- **평가**: 개체를 뽑힌 순서대로 하나씩(CPU 1) 평가한다. 같은 M18 호출 키의 저장 결과가 시작 때의 재사용 계획에 있으면 **재사용**(도킹·과금 없음, 새 도킹 수에 세지 않음), 아니면 **새 도킹** 1건. 도킹 실패·모드 0개도 평가한 것이며 새 도킹이면 1건을 쓰고 재시도하지 않는다. 한 실행 안에서 같은 후보를 두 번 평가하지 않는다.
- 세대의 개체 순서 = 이어받음(점수 오름차순, 동점 풀 순서) 다음 새 개체의 평가 순서. `eval_index`는 이어받음을 뺀 평가 순서(0부터, 한 실행에서 유일)다.
- **조기 중단**: 완료한 세대 g ≥ 2마다 그때까지 모든 평가의 점수 최솟값이 세대 g − 1 끝의 값보다 작아졌는지 본다(null → 숫자는 작아짐, null → null은 작아지지 않음). 연속 `patience` 세대 작아지지 않으면 `no_change`로 끝낸다. 마지막 세대(`generations`)에서는 `generations_complete`가 먼저이고 `no_change`를 보지 않는다.
- **풀 소진**: 새 자리를 하나도 채우지 못한 세대는 기록하지 않고 `pool_exhausted`로 끝낸다. 일부만 채우면 채운 만큼만 한다.

### 종료 이유와 상태 (닫힌 집합, `STOP_REASONS`·`STATUS_BY_STOP_REASON`)
- `complete`: `generations_complete`, `no_change`, `pool_exhausted`. `partial`: `docking_limit`, `time_exhausted`, `cancelled`, `worker_failed`, `resource_exceeded`.
- `docking_limit`: 다음 개체가 새 도킹을 필요로 하는데 새 도킹 수가 이미 `reserved_units`(≤ `max_new_dockings`)에 닿았을 때 그 시점에 난다. 예약하지 않은 단위는 쓰지 않는다. 그 전에 뽑힌 재사용 개체는 평가를 끝낸다.
- 확인 순서: 개체마다 시작 전 취소(`cancelled`) → `docking_limit` → 전체 시계(`time_exhausted`). 도킹 중에는 개체 시계 300초(그 개체 `failed` `candidate_timeout`, 실행은 계속), 전체 시계(`time_exhausted`), SIGTERM(`cancelled`). 전체 시계는 작업 모듈 시작부터 min(`total_s`, 14400)초다. 출력 총량(새 도킹 결과 파일 합 128 MiB)을 넘을 결과는 저장하지 않고 `resource_exceeded`로 멈춘다.
- 멈춘 세대는 이어받음 + 평가를 끝낸 개체만 담아 `complete: false`로 게시한다(버리지 않음). 도킹 중 멈춘 개체(`<k>.started`만 남음)와 출력 총량에 걸린 개체는 세대 기록에 없으므로 요약에 나오지 않는다.
- 작업 기록 상태는 요약 상태와 따로다(M19와 같음): 작업 모듈이 스스로 끝나면(자기 전체 시계·출력 총량 포함) 작업 `done`, 사용자 취소는 `cancelled`, 작업 마감은 `failed`(`resource_exceeded`, "job timeout") + 요약 `time_exhausted`, 크래시·자원 한도는 `failed` + 요약 `worker_failed`, 서버 재시작 복구는 `interrupted` + 요약(사용자가 취소를 요청했으면 `cancelled`, 아니면 `worker_failed`). 작업 모듈이 사용자 취소 없이 `cancelled`를 쓰면 `worker_failed`로 다시 해석한다. 첫 개체 전(`prepared.json` 전)에 멈추면 요약이 없고 작업은 실패한다(사용자 취소면 `cancelled`).

### 개체 = 단독 M18 도킹
- 개체의 작업 인자·`input_sha256`·호출 키는 같은 입력의 단독 `qvina_dock_v1` 자유 요청과 같다(`docking_batch_inputs.row_arguments`). 그래서 새 도킹 결과 `docking_result@1`은 단독 M18과 같은 바이트·같은 handle이며 M18·M19·GA가 서로 재사용한다. 작업 모듈은 `docking_worker.py`를 파일 경로로 불러 `receptor_inputs`·`receptor_prepared`를 한 번, 개체마다 `dock_row`를 부른다(행 계산 복제 없음).
- 서버는 정리 확인 뒤 새 도킹 개체마다 M18과 같은 검사(`docking_bundle.result_content` → `store_result`, 수용체 원자·거리 재대조)로 결과를 게시하고 `ligand_ga_individual_published`를 쓴다. 이 이벤트가 그 결과의 게시 증거이며 요약 게시가 없어도 M18 읽기·보고서·재사용이 받아들인다(`docking_bundle.producer()`는 단독·일괄 행·GA 개체 증거 중 가장 먼저 게시한 쪽).

### 요약 개체를 만드는 규칙 (서버, `ligand_ga_bundle.build_summary`)
- 세대·개체 목록은 작업 모듈의 세대 기록(`generations/<g>.json`: 후보 id, 출처, 부모, 유사도, 평가, `eval_index`)에서, 상태·점수는 서버가 읽은 파일과 저장 결과에서 만든다(작업 모듈 기록의 점수를 쓰지 않음).
- 결과 handle이 있으면(새로 게시했거나 재사용) 결과의 모드 수로 `scored`(≥ 1)/`null_result`, 점수 = `modes[0].score_kcal_mol` 사본. 결과가 없고 상태 파일이 `failed`면 그 이유. 상태 파일이 `scored`/`null_result`인데 결과를 게시할 수 없으면 `failed` `engine_output_invalid`. 상태도 결과도 없으면 `failed` `worker_failed`.
- `carried` 개체는 직전 세대의 같은 후보 항목(점수·결과 handle·상태)을 그대로 인용한다(`evaluation`·`eval_index`는 null).
- 읽을 수 없거나 틈이 있는 세대 기록, 풀에 없는 후보·쓴 `eval_index`·재사용 계획과 다른 평가가 있는 기록, 세대 기록과 맞지 않는 종료 기록은 예외가 아니라 그 앞까지만 쓰고 종료 이유를 `worker_failed`로 한다. 이 판단 전에 읽을 수 있는 기록의 새 도킹 개체를 모두 먼저 게시한다.
- 개체마다의 `docking_selection@1`은 서버가 평가한 개체(≤ 101개)에 대해서만 작업 기록과 저장 후보 행으로 다시 만든다(`ligand_ga_inputs.individual_selection`, 단독 `docking_bundle.submission`과 같은 값). 작업 기록에는 후보마다의 선택을 넣지 않는다.

### 저장된 결과 재사용
- 적격 후보의 M18 호출 키 전체(정규화 인자 + M18 pin, 작업 모듈 해시 포함)와 같은 결과가 이 run에 있고(단독 M18 작업·M19 일괄 행·GA 개체 게시 어느 쪽이든, `docking_batch_inputs.published_m18_results`) 지금 검증을 통과하며 `input_sha256`이 같으면 재사용한다. 재사용 계획은 작업 시작 때 run 실행 잠금 안에서 한 번 정한다(`job_dispatch_intent.ga_reused`). 재사용 결과 바이트는 스테이징에 실어 작업 모듈이 첫 모드 점수를 읽는다.
- 재사용 여부는 개체마다 `evaluation: "reused" | "docked"`로 요약에 들어간다(M19와 다름). 그래서 저장 결과 집합이 다르면 같은 GA seed라도 다른 요약이 된다(G3).
- 이어서 하기는 따로 없다. 같은 설정으로 새 GA를 만들면 끝난 개체의 결과가 재사용된다.

### 같은 GA (호출 키)
- GA 호출 키 = `idempotency_key(qvina_ga_dock_v1, qvina_ga_dock_v1@1, {input: selection_sha256, method: M18 pin, ga_method: GA pin})`. `selection_sha256`은 수용체(handle·SHA-256·모델·연결 정보·인스턴스), 후보 집합 handle, 부모 SDF handle·SHA-256, `pool_sha256`(풀 id 순서·적격 표시), 필터, 상자 요청, 값, `ga` 전체의 정규화 SHA-256이다. 확인 세 항목·`timeout_s`·재사용 집합·시간·작업 ID는 넣지 않는다. GA pin은 GA 작업 모듈·상수 파일 SHA-256이고, M18 pin은 개체 호출 키·결과 검사에 쓴다.
- 같은 키의 작업이 대기·실행 중이거나 같은 키의 검증된 `complete` 요약이 있으면 `POST /jobs`가 그 작업을 돌려준다(새 작업·과금 없음). `partial` 요약은 새 GA를 막지 않는다.

### 예산, 첫 계산 승인, 한도 증액
- 과금: 시작 때(승인된 시작 뒤, 프로세스를 띄우기 직전) `reserved_units = min(max_new_dockings, P + (G − 1) × (P − E))`를 한 번 예약하고 환불하지 않는다(중간에 멈춤·재사용이 있어도). 재사용 개체·입장 거절·대기 중 취소·dry-run은 과금하지 않는다. 시도는 1회다(`/jobs/{id}/retry` 없음).
- 필요량: 비싼 계산 `reserved_units`, 활동 시간 min(`total_s` + 600, `reserved_units` × 300 + 300)초. 부족분 = max(0, 필요량 − (한도 − 사용량)) 축마다. 기본 run 예산(1800초, 8회)은 기본 설정 GA(52단위, 7800초)에 모자라 입장이 429 `ga_limit_raise_required`가 되므로 화면이 부족분과 증액 승인을 먼저 보인다.
- `full_run_may_be_partial` = `reserved_units × 300 > total_s`(상한 기준 경고). 기본 설정에서도 참이며 "끝까지 못 갈 수 있음"이라는 뜻이지 부분 완료가 아니다.
- run의 첫 비싼 계산 승인(`expensive_first_call`, 도구 `qvina_ga_design`)은 M18과 같다. 증액은 이 승인을 만들지 않는다.
- 증액 승인: 사람이 화면에서만 누른다(`POST /runs/{id}/ligand/ga/limit_approval`, 이 프로토콜 전용, M19 라우트와 따로). 서버는 run 실행 잠금 안에서 그 시점의 부족분을 다시 계산해 그만큼만 올린다: 비싼 계산 증가분 = min(부족분, 필요량, 100), 활동 시간 증가분 = 부족분이 0이면 0, 아니면 min(부족분, 필요량, 15000) + 60초. 부족하지 않으면 아무것도 바꾸지 않는다(멱등, 이벤트 없음). 기록은 `budget_limit_updated`(`by: "human"`, 맥락 `purpose: "ligand_ga_limit_raise"`, `selection_sha256`, `reserved_units`, `needed`, `shortfall`, `increase`, `limits_before`, `limits_after`). dry-run run과 취소된 run은 거절하고 아무것도 쓰지 않는다. 올라간 한도는 run 끝까지 유지된다.

### 요약 객체 `ligand_ga_result@1` (서버만 만든다, 정리 확인 뒤, 모든 종료 상태, 개체 게시 다음 마지막, 1 MiB 한도)
- 최상위 키: `schema`, `protocol`, `engine` (`qvina`), `candidate_set_handle`, `parent_sdf_handle`, `receptor{handle, sha256, model_number, connectivity, removed_instance, acknowledgement}`, `pins{ga_worker_sha256, ga_constants_sha256, worker_sha256, constants_sha256, qvina_sha256, qvina_package}`, `call_key`, `selection_sha256`, `box`, `parameters`(M18 값 + `cpu`), `filter`(정규화 사양), `ga`(유효 파라미터 전체), `pool{size, eligible_count, filter_excluded_count}`, `status`, `stop_reason`, `generations_done`(완료한 세대 수), `new_dockings_used`, `reused_count`, `reserved_units`, `generations`, `limitations`(G id 목록).
- 세대: `index`, `complete`, `individuals`, `min_score`·`max_score`(그 세대에 평가되거나 이어받은 점수 있는 개체 기준, 값일 뿐 "최고"가 아님, 없으면 null).
- 개체: `candidate_id`, `origin`(`initial` | `carried` | `similar` | `random`), `parent_candidate_id`·`similarity`(유사 자리만, 6자리 문자열), `evaluation`(`reused` | `docked`, 이어받음 null), `eval_index`(이어받음 null), `state`(`scored` | `null_result` | `failed`), `reason_code`(`failed`만: M18 이유 집합 + `candidate_timeout`·`worker_failed`), `score`(`scored`만, 결과 첫 모드 사본), `result_handle`(`failed` 아닌 개체).
- 시각·작업·시도 ID를 넣지 않는다. 게시 때와 읽을 때마다(`validated_summary`) 정확한 키(순위·차이·best·improved 필드는 있을 수 없음), 모든 개체가 적격 풀 후보, 이어받음이 아닌 후보 id가 한 실행에서 유일, 세대 크기 ≤ `population_size`(완료한 세대 1 = `population_size`), 출처 순서(이어받음 → 유사 → 무작위, 세대 1은 초기만), 이어받음 = 직전 세대 점수 낮은 `elite_count`개(동점 풀 순서), `eval_index` 순서, 개체 점수 = 저장 결과 첫 모드, 결과 = 그 개체 자신의 M18 자유 입력, 최솟값·최댓값, 개수, `new_dockings_used ≤ reserved_units`, `reserved_units` 산식, 예약 이벤트 = `reserved_units`, 종료 이유와 상태·구조(`docking_limit`이면 새 도킹 = `reserved_units`, `no_change` 지점은 서버가 세대 최솟값으로 다시 계산), G 목록, pin, 해시, 크기를 다시 검증한다. 서버는 지문을 계산하지 않으므로 `parent_candidate_id`·`similarity`는 모양만 검사한다(G1).
- 요약을 만들 수 없으면(증거 오류) 작업은 그 이유로 실패하지만 이미 게시한 개체 결과는 자기 게시 증거로 읽히고 재사용된다. events-only로 다시 열린다.

### 고정 문장 (문자 그대로, 순서 고정, `ligand_ga_constants.STATEMENTS`, 바꾸려면 사용자 결정)
  - G1 (항상) "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. 부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다."
  - G2 (`partial`) "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다."
  - G3 (재사용이 있을 때) "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, 저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다."
- 점수 이름·열 머리는 M18과 같고("qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)", 열 "qvina 점수(kcal/mol)"), 점수 대상은 M19 `SCORE_ROW_LABELS["free"]`와 같은 "모드 1(엔진 출력 순서)"이다. 조기 중단 표시 이름은 "점수 최솟값 변화 없음"이다.

### 보고서
- `method_report_manifest@1`, `analysis_type: "ligand_ga"`, 렌더 `ligand_ga_markdown@1`. 입력은 요약 handle 하나. 개체별 M18 보고서를 만들지 않는다.
- 증거는 모두 계산값(`computed`): 공유 설정(수용체 가져오기, 뺀 인스턴스 7필드·원자 수, 후보 집합·부모 SDF, 상자, 값, `ga` 값), 풀 개수, 실행 개수(`generations_done`·`new_dockings_used`·`reused_count`는 저장 세대·개체 위의 `count_where`로 검증할 때마다 다시 셈, `reserved_units`), 세대마다 개체 수(`count`·`count_where(state == …)`)와 저장 `min_score`·`max_score`(값만, 그 세대 저장 점수의 끝값과 같아야 함), `scored` 개체마다 점수 주장 둘(요약 `generations[g].individuals[p].score`와 개체 결과 `modes[0].score_kcal_mol`, 같은 `row_selector {generation, position}`, 같은 값). 점수는 `Decimal(str(v))`를 0.1 `ROUND_HALF_UP`.
- 점수 없는 개체(`null_result`, `failed`)와 계산하지 않은 개체에는 점수 주장이 없고 표 칸은 비운다(0이 아님). 그런 개체의 점수 주장, 다른 statement의 필드, 틀린 반올림, 해석 문장은 거부한다. 점수 없는 개체는 그 세대의 점수 있는 개체 뒤에 둔다(표시 순서일 뿐).
- 금지어 검사는 M18 목록에 승자·우승·평균·추천·우수·우월·상위·하위·향상·악화(와 영어 대응어)를 더하고, G1–G3과 문자 그대로 같은 줄은 건너뛰며(G1은 순위·추천을 부정하려고 그 낱말을 씀), 그 밖의 줄은 점수 이름(`SCORE_LABEL`)만 지운 뒤 검사한다. 출처 표시는 "초기·다음 세대로 이어받음·유사·무작위"다.
- 만들기·다시 열기·다운로드는 도킹을 다시 하지 않는다. 다시 열 때 요약과 개체 결과를 검증하고 manifest·주장·Markdown 바이트를 저장 객체에서 다시 만든 것과 비교한다. 보고서 예산 스냅숏은 생성 시점 값(올라간 한도 포함)이다.

### 화면 규칙
- 리간드 설계·탐색 탭의 M19 일괄 도킹 영역 다음 "GA 설계" 영역. 가져오기는 M18 도킹 영역에서 하고 GA 영역은 이미 가져온 수용체·사이드카·부모 SDF와 후보 집합을 고른다. 입력: 수용체(+사이드카) → 뺄 인스턴스 → 후보 집합·부모 SDF → M17 필터(`FilterForm`) → 상자 → 도킹 값(도킹 seed)과 확인 세 항목 → GA 파라미터 → 시작 전 확인 → (부족하면 증액 승인) → GA 시작. 어떤 선택도 자동으로 하지 않는다. 자유 도킹 고정이며 그 사실을 보인다.
- 파라미터 편집: `ga`의 모든 키를 입력란으로, 칸마다 범위·기본값을 보이고(GA seed는 비어 있음, 필수), 범위·형식·교차 규칙을 벗어나면 그 칸의 이유를 보이며 시작 전 확인·시작을 막는다(요청 없음). "기본값으로"는 GA seed를 남기고 나머지를 기본값으로 되돌린다. 유효 파라미터 전체와 작업 시간 한도(`total_s` + 600)를 요약하고, 새 도킹 상한 × 300초 > `total_s`이면 "끝까지 못 갈 수 있음" 안내를 보인다. GA seed와 도킹 seed가 다른 난수라는 안내를 둔다.
- 시작은 지금 인자와 정확히 같은 인자로 받은 시작 전 확인이 입장 통과·부족분 0일 때만 열린다. 시작 전 확인은 풀·적격·필터 제외 수, 재사용 가능 후보 수, 예약 단위 = 예상 최대 새 도킹, 필요·잔여·부족분, "시작하면 n단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음", `full_run_may_be_partial`일 때 "끝까지 못 갈 수 있음", GA 중 이 run의 다른 계산·보고서와 다른 비싼 작업이 기다린다는 안내, G1을 서버 값 그대로 보인다. 같은 인자의 작업이 있으면 그 작업을 알린다.
- 진행: 저장된 작업 기록의 `ga` 진행(완료한 세대·세대 기록 수, 새 도킹 시작·끝·결과 파일 수, 재사용 예정 수, 예약 단위)을 2초마다 읽어 보인다. 재사용 개체는 파일이 없으므로 새 도킹 수에 세지 않는다.
- 결과: 세대 탭(멈춘 세대 표시), 개체 표(자리, 후보 id, 출처 "초기/이어받음/유사/무작위", 부모·지문 Tanimoto(저장 문자열), 평가 "새 도킹/저장된 결과 재사용/다시 도킹하지 않음(이전 세대 결과 인용)", 상태, qvina 점수(점수 대상 문구, `scored`만 숫자), 이유 "한국어 (code)", 상세 열기), 세대별 점수 최솟값·최댓값(값만), 상태·종료 이유·G 문장(서버가 준 저장 id 문장 그대로), 요약 줄. 자리·후보 id·점수 열은 오름·내림차순으로 정렬할 수 있고 점수 없는 개체는 어떤 정렬에서도 늘 끝(자리 순서)이다. 순위 열·최고 표시·강조·차이 열은 없다. "상세 열기"는 기존 M18 도킹 영역의 상세를 연다.
- 화면은 점수·집계·부족분·유사도를 계산하지 않는다. 기능을 쓸 수 없을 때(엔진 없음, run 없음, 후보 집합 없음)는 이유만 보이고 숫자를 만들지 않는다. Mol* 표시는 없다.

### 의미하지 않는 것
M18의 "의미하지 않는 것" 전부. 그에 더해 이어받음·부모 선택·표의 정렬은 후보의 순위·우열·추천이 아니고, 세대별 최솟값이 작아진 것은 개선이 아니라 탐색 규칙의 관찰값이며, 유사도는 지문 수학 값일 뿐 점수·활성이 아니고, `partial` 실행의 빈 칸·나오지 않은 개체는 0이 아니라 계산하지 않음이다.

## 변이 후보 (M20, `generate_mutation_candidates`)

한 전처리 구조에서 위치(단백질 잔기)를 모으고, 근거 있는 보호 잔기를 기본으로 뺀 뒤, 남은 위치마다 단일 아미노산 치환 후보를 만든다(결정 0028). 후보는 위치와 바꿀 잔기의 조합일 뿐이다. 구조 모델링·에너지·점수·순위는 만들지 않는다(구조 모델링은 M21). 모든 거리는 저장된 전처리 좌표에서, 번호·KLIFS 부위는 저장된 번호 대응·주석 객체에서, 포켓 안쪽 잔기는 저장된 포켓 결과에서 온다. 닫힌 집합·상한·문장은 `backend/mw/mutation_constants.py`에 있고 바꾸려면 사용자 결정이 필요하다.

### 입력
- 도구 인자(알 수 없는 키는 최상위·`sources`·`pocket`·`ligand_shell`에서 거부): `structure`(같은 run의 `prepared_structure`, 필수), `sources{pocket, ligand_shell, residues}`(필수), `ligand`(null | 리간드 선택자), `allowed_residues`(한 글자 코드 문자열 또는 목록, 기본 표준 20종 전부), `protected_residues`, `released_residues`, `metal_contact_A`(기본 3.0, 1.0–5.0, 양끝 포함), `numbering_map`(null | 같은 run의 `residue_numbering_map`), `annotation`(null | 같은 run의 `reference_site_annotation`).
- `pocket` = null | `{pocket_set, ranks}`(순번 1개 이상), `ligand_shell` = null | `{radius_A}`(기본 5.0, 1.0–12.0, 양끝 포함), `residues` = 잔기 참조 목록(비어 있어도 됨). 세 출처 중 하나 이상이 실제로 위치를 요청해야 한다.
- **잔기 참조** = `{model_number, chain_auth, seq_auth, icode, resname}` 필수 + `chain_label`·`seq_label` 선택(주면 일치해야 하고 null도 값이다, 타입까지 비교). 구조 첫(유일) 모델의 단백질 잔기(`category == "polymer"`, ATOM 레코드) 정확히 하나로 해석되어야 하고 결과에는 해석한 7필드를 저장한다. 이름·표시 문자열로 잔기를 찾지 않는다.
- **리간드 선택자**는 같은 모양이며 물·`METALS`가 아닌 HETATM 잔기(`structure_residues`의 `ligands`, MSE HETATM 포함) 정확히 하나로 해석되어야 한다. 그 인스턴스에 중원자가 없으면(수소만) `ligand_invalid`다. 리간드가 여럿이어도 첫 번째를 고르지 않는다.
- 목록(직접·보호·해제)과 포켓 순번은 각각 최대 400개이며 한 목록 안의 같은 잔기는 거부한다. 같은 잔기를 보호와 해제에 모두 넣으면 거부한다.
- 호출 키 = 정규화한 인자: 목록은 구조 파일 순서·7필드 전체, `ranks` 오름차순, `allowed_residues`는 `ACDEFGHIKLMNPQRSTVWY` 순서의 문자열, 기본값 채움. 같은 집합이면 순서·표기와 상관없이 같은 호출·같은 handle이다.

### 입장 검사 (사전 검사 훅, 모든 호출 경로에서 도구 구현보다 먼저, 이 순서)
`unknown_field` → `structure_invalid` → `no_position_source` → `argument_invalid`(형식·범위, NaN·Infinity·bool, 400 초과 목록, 빈 `ranks`) → `allowed_residues_invalid`(비었음·20종 밖·중복) → `residue_invalid`(없음·둘 이상·비폴리머) → `duplicate_residue` → `protect_release_conflict` → `ligand_required`(`ligand_shell`이 켜졌는데 `ligand`가 null, 리간드 수와 무관, 자동 선택 없음) → `ligand_invalid` → `pocket_set_invalid`(handle 아님·다른 run·다른 종류, 게시되지 않은 결과, 포켓 없음 결과) → `numbering_map_invalid`·`annotation_invalid`(handle·run·종류) → `structure_mismatch`(포켓 결과의 `source_handle`, 번호 대응·주석의 `structure.handle`이 요청 구조와 다름) → `pocket_rank_invalid`(결과에 없는 순번·중복) → `pocket_residue_mismatch`(안쪽 잔기 7필드가 구조 단백질 잔기와 다름) → `annotation_map_mismatch`(둘 다 줬는데 주석이 기록한 `numbering_map`이 다름). 모두 `input_invalid`(422)이고 구현을 부르지 않는다. 포켓 결과는 훅이 받은 store(이벤트 로그·run ID 있음)로 만든 RunView에서 `pocket_bundle.validated_pocket_set`을 불러 게시가 끝난 결과인지까지 확인한다. fpocket을 다시 돌리지 않는다.

### 위치
- 위치 = 구조 첫 모델의 단백질 잔기 하나. 체인마다 따로이며 같은 서열의 체인도 합치지 않는다. 세 출처의 합집합이고, 여러 출처에 있는 잔기는 위치 행 하나에 출처 목록(`pocket`은 순번마다, 오름차순 → `ligand_shell` → `user`)으로 남는다.
  - `pocket`: 고른 순번마다 저장된 `lining_residues`.
  - `ligand_shell`: 리간드 중원자와 잔기 중원자 사이 최소 거리 ≤ `radius_A`(경계 포함)인 모든 단백질 잔기(모든 체인).
  - `user`: `residues` 목록.
- 위치 순서는 구조 파일 순서이고 `index`는 0부터다. 순서는 순위가 아니다.
- 위치가 400개를 넘으면 `resource_exceeded`(429) `too_many_positions`(`detail.positions`, `detail.limit`)이고 아무것도 저장하지 않는다(잘라 저장하지 않음).
- `ligand_min_distance_A`: `ligand`를 줬으면 출처와 무관하게 모든 위치에 계산한다(잔기 중원자 전부와 리간드 중원자 전부의 최소 거리, float64, 저장 좌표 그대로, 원소 H·D 제외). `ligand`가 null이면 모든 위치에서 null, 리간드를 줬어도 중원자가 없는 잔기는 null이다(0이 아님).
- `numbering`: `numbering_map`이 null이면 null. 주었으면 같은 7필드 행의 `status`·`uniprot_accession`·`uniprot_position`·`uniprot_residue`·`klifs_index`·`klifs_label`을 그대로 복사하고(참조값, 계산 아님), 지도에 없는 잔기는 `status: "not_in_map"`과 나머지 null.

### 표준 이름
표준 20종 이름이거나 M12 이름 대응 10개(`HID`·`HIE`·`HIP`·`HSD`·`HSE`·`HSP`→`HIS`, `CYX`→`CYS`, `ASH`→`ASP`, `GLH`→`GLU`, `LYN`→`LYS`)면 `standard_resname`·`one_letter`가 정해진다. 그 밖(MSE·SEP 등)은 둘 다 null이고 제외 사유 `non_standard_residue`다. 원래 `resname`은 식별자에 그대로 남는다.

### 보호, 해제, 제외
- 보호 사유(닫힌 집합, 이 순서): `user_protected`(보호 목록에 있음), `klifs_key_site`(주석의 `status == "annotated"` 부위 잔기와 7필드가 같음. 해당 부위의 `klifs_label`을 KLIFS 번호 순으로 `klifs_sites`에), `metal_contact`(금속 잔기(`het_flag == "H"`, 물 아님, 이름이 `METALS`(ZN MG CA MN FE CU CO NI NA K))의 원자와 이 잔기 중원자 사이 최소 거리 ≤ `metal_contact_A`. 가장 가까운 금속 잔기 7필드와 거리를 `metal`에), `disulfide_cys`(CYS·CYX이고 다른 CYS·CYX의 `SG`와 SG–SG ≤ 2.5 Å, 모든 체인. 가장 가까운 짝을 `disulfide_partner`에, 동점이면 파일 순서 먼저).
- 주석을 주지 않으면 KLIFS 보호를 검사하지 않는다: 위치의 `klifs_sites`는 null(검사했는데 해당 없으면 `[]`). 주석의 `absent` 부위는 보호하지 않는다.
- 해제: `released_residues`의 잔기에 보호 사유가 하나라도 있으면 모든 보호 사유가 한꺼번에 풀리고 `protection.released: true`다(사유별 해제 없음, 사유 목록은 그대로 남음). 사유가 없는 잔기의 해제는 오류가 아니라 `released_residues[].effect: "none"`이다(위치가 아닌 잔기도 `none`). 해제는 `non_standard_residue`·`no_allowed_alternative`에 영향이 없다.
- 제외 사유(닫힌 집합, 저장 순서): `non_standard_residue`, `user_protected`, `klifs_key_site`, `metal_contact`, `disulfide_cys`, `no_allowed_alternative`. 위치의 제외 사유 = 해제되지 않은 보호 사유 + 비표준이면 `non_standard_residue` + 표준이고 허용 목록에서 원래 잔기를 뺀 것이 비면 `no_allowed_alternative`. 하나라도 있으면 `status: "excluded"`(후보 없음, 이유와 함께 남음), 없으면 `"candidate"`.
- 촉매 잔기는 판정하지 않는다(데이터베이스 없음, M26).

### 보호 검사 상태 `protection_checks` (결과에 항상)
- `user_list {status: "checked", protected, released}`(목록 길이), `klifs_key_sites {status: "checked"|"not_checked", reason: null|"annotation_not_given", annotation, annotated_sites, absent_sites}`(검사하지 않았으면 handle·개수 null), `metal_contact {status: "checked", threshold_A, metal_residues, metal_names}`, `disulfide {status: "checked", threshold_A: 2.5, pairs}`, `catalytic_residue_database {status: "not_available", reason: "not_implemented"}`.
- 하지 않은 검사를 한 것처럼 보이지 않는다: `not_checked`·`not_available`은 0이나 "없음"과 다르며 화면·보고서 어디서도 숫자로 보이지 않는다.

### 후보
제외되지 않은 위치마다 허용 목록에서 원래 `one_letter`를 뺀 코드를 `ACDEFGHIKLMNPQRSTVWY` 순서로 하나씩 후보 `{index, position_index, from, to}`로 만든다(단일 변이, 위치당 최대 19개). 번호는 위치 순서, 그 안에서 코드 순서다. 후보 0개(모든 위치 제외 등)는 실패가 아니라 `null_result: true`인 유효한 빈 결과다.

### 결과 객체 `mutation_candidate_set@1`
- 최상위 키: `schema`, `method_version`(`mw.mutation_candidates/v1`), `structure{handle, model_number, structure_kind: "prepared_structure"}`, `parameters`(정규화한 요청 + `disulfide_sg_A: 2.5`), `ligand`(null | `{residue, heavy_atom_count}`), `pockets`(null | `{pocket_set, ranks, lining_residue_count}`), `protection_checks`, `released_residues[{residue, effect}]`, `positions`, `candidates`, `counts{positions, candidate_positions, excluded_positions, released_positions, candidates, exclusion_reason_counts(여섯 사유 전부), source_counts{pocket, ligand_shell, user}}`, `null_result`, `limitations`.
- 위치 필드: `index`, `residue`(7필드), `standard_resname`, `one_letter`, `sources`, `ligand_min_distance_A`, `numbering`, `protection{reasons, released, klifs_sites, metal, disulfide_partner}`, `exclusion_reasons`, `status`, `candidate_count`.
- 객체 내용에 시각·호출 ID가 없어 같은 입력은 같은 handle이다. 이벤트가 전체 payload를 담아 events-only로 다시 열린다(위치 400 × 후보 19 결과 내용 약 0.90 MiB, 이벤트 한 줄 약 1.20 MiB).
- `validated_set`(순수 함수): 스키마, 닫힌 집합, 개수와 목록 일치, 후보↔위치 일관성, 제외 사유와 상태 일치, 해제 효과, `null_result`, 고정 문장 5개, 7필드 모양을 검사한다. 도구는 저장 전에 이것을 돌려 통과하지 못하면 저장하지 않고 `input_invalid` `candidate_set_invalid`로 실패한다. 읽기·보고서는 저장 객체를 매번 이것으로 다시 검증한다.

### 실행 경로
값싼 도구(`Run.call`, `cost_class: cheap`)다. 작업 큐·승인·예산 단위를 쓰지 않고 외부 엔진·네트워크·참조 폴더를 쓰지 않는다. 입력은 이 run의 저장 객체(구조 바이트, 포켓 결과, 번호 대응, 주석)만이다. dry-run run에서도 실행해 결과를 저장한다(다른 값싼 도구와 같음). capability `methods.mutation_candidates`는 항상 사용 가능이다. M13 분석 흐름은 이 도구를 부르지 않는다.

### 고정 한계 문장 (결과 `limitations`, 보고서, 화면에 문자 그대로, 순서 고정)
  1. "후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다."
  2. "이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다."
  3. "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 사용하지 않았다(없음)."
  4. "거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다."
  5. "바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다."

### 상한과 기본값 (`mutation_constants.py`)
위치 400, 목록·순번 각 400(넘으면 거절, 자르지 않음). 껍질 반경 기본 5.0 Å(1.0–12.0), 금속 거리 기본 3.0 Å(1.0–5.0), 이황화 SG–SG 2.5 Å(요청 필드가 아닌 상수). 읽기 페이지: 목록 1–100(기본 50), 위치 1–100(기본 50), 후보 1–200(기본 100).

### 보고서
- `method_report_manifest@1`, `analysis_type: "mutation_candidates"`, 렌더 `mutation_candidates_markdown@1`. 입력은 후보 집합 handle 하나. 만들기·다시 열기·다운로드는 후보를 다시 만들지 않는다.
- **계산값**(`computed`, 저장 행을 다시 셈): 위치 수, 상태별 위치 수, 해제된 위치 수, 후보 수, 제외 사유별 위치 수(여섯 개), 출처별 위치 수(셋), 번호 상태별 위치 수(번호 대응을 줬을 때만), 리간드까지 최소 거리의 최솟값(리간드가 있고 거리가 있는 위치가 있을 때만, Å, 그 최솟값을 가진 첫 위치 인용, `Decimal(str(v))` 0.01 `ROUND_HALF_UP`), 보호 검사 다섯 개의 상태, 검사한 항목의 개수(보호·해제 목록 길이, 주석된·없는 부위, 금속 잔기, SG–SG 쌍). 검사하지 않은 KLIFS 항목은 "검사하지 않음" 상태 주장만 있고 숫자가 없다. 촉매 잔기 데이터베이스는 "사용할 수 없음"이며 숫자가 없다.
- **참조값**(`reference_value`, "참조 스냅샷 값, 계산 아님" + 참조 객체 handle): 위치들의 서로 다른 UniProt accession(번호 대응 행에서 복사), 보호된 위치의 서로 다른 KLIFS 부위 이름표(주석에서 복사). 계산값 주장이 참조 필드를 인용하면 거부한다.
- 위치 행 전체 목록은 보고서에 넣지 않는다(저장 객체에 있음). 리간드를 주지 않았거나 거리가 있는 위치가 없으면 거리 절에 "계산하지 않음"과 이유를 쓰고 숫자를 쓰지 않는다.
- 만들고 다시 열 때 저장된 집합을 검증하고, 그것이 이름 붙인 번호 대응·주석·포켓 결과가 같은 구조인지, 복사한 번호 값과 KLIFS 부위 개수·이름표가 저장 객체와 같은지 대조하고, manifest·주장·Markdown 바이트를 다시 만든 것과 비교한다. 틀린 개수·반올림, 검사하지 않은 항목을 검사했다거나 0으로 쓰는 주장, 섞인 증거 종류, 다른 구조·다른 run의 증거는 `report_evidence_invalid`다.
- 해석 금지어: M15 목록에 안정성·ΔΔG·순위·추천·최적·개선·활성·예측·유망·좋은·나쁜·안전·점수·에너지·수소결합(영문 rank·best·recommend·optimal·improve·predict·promising·good·safe·active·score·energy·hydrogen bond·H-bond 포함)을 더해, 고정 한계 문장 5개와 문자 그대로 같은 줄을 빼고 모든 줄을 검사한다. 검사는 식별자·값을 빈 자리로 둔 고정 템플릿 문장에 하므로 체인·리간드 이름 같은 식별자는 보고서를 깨지 않는다. "촉매"는 금지어가 아니다(필수 문장 "촉매 잔기 데이터베이스: 사용할 수 없음" 때문, M16 보고서와 다름). 촉매 역할 주장은 쓰지 않는다.

### 화면 규칙
- 단백질 공학 탭(선택된 동안에만 렌더링, 페이지가 run마다 `key`로 새로 만들고 탭에 들어올 때마다 이벤트·포켓·번호 대응·주석·결과 목록을 다시 읽음, GET만). 패널 안에 변이 구조 모델링은 후보 행에서 따로 시작한다는 한 줄(숫자 없음, M21부터. M21 전에는 아직 없다는 문장이었다). 후보 행마다 "변이 구조 모델링" 동작이 있고, 누르면 그 후보 집합과 후보 번호만 아래 M21 영역의 요청 칸에 넘긴다(아무것도 보내지 않음).
- run이 없거나 전처리 구조가 없으면 숫자·컨트롤 없이 "사용할 수 없음"과 이유만. 전처리 구조·포켓 결과·리간드는 자동으로 고르지 않는다(리간드가 하나뿐이어도). 예외로 구조를 고르면 같은 구조의 가장 최근 주석과 그 주석이 기록한 번호 대응을 미리 고른다. 번호 대응을 따로 골라 주석의 지도와 다르면 충돌을 알리고 요청을 막는다. 주석을 고르지 않으면 요청 영역에 "KLIFS 주요 부위 보호를 검사하지 않음"을 눈에 띄게 알린다. 포켓·번호 대응·주석 목록은 같은 구조 것만(포켓은 포켓 있는 결과만).
- 값은 서버 응답만 보이고 브라우저에서 계산하지 않는다. 거리는 소수 둘째 자리 `decimalHalfUp`, null은 "—"와 이유(예: "— (리간드를 고르지 않아 계산하지 않음)", "— (중원자 없음)", "— (검사하지 않음)"). 보호 판정을 "안전", 후보를 "추천·좋은·유망", 목록 순서를 순위로 부르지 않는다. 점수·순위 열·막대 그래픽 없음. 이유 코드는 "한국어 (code)".
- 다섯 상태(불러오는 중·준비·빈 결과·실패·사용할 수 없음). 후보 0개는 저장된 제외 사유별 개수와 함께 빈 결과다. 늦은 응답은 run + 결과 handle + 영역별 요청 번호가 모두 같을 때만 반영한다. 보고서 생성이 늦게 끝나도 run이 같으면 보고서 목록을 다시 읽게 한다.

### 의미하지 않는 것
변이의 효과(안정성·결합·활성·특이성), ΔΔG·친화도·에너지, 순위·추천·우선순위, 보호 판정의 "안전", 촉매 잔기 여부, 변이 구조의 형태·양성자 상태. 리간드·금속까지 거리는 기하 사실이며 결합·상호작용을 뜻하지 않는다. KLIFS 부위 이름표·UniProt 번호는 참조값이다.

## 변이 구조 모델링 (M21, `openmm_mutation_model_v1`)

M20 변이 후보 하나를 골라, 같은 작업 안에서 같은 절차로 야생형 기준 구조와 변이 구조를 만들고(PDBFixer 1.12.0 곁사슬 + M7과 같은 OpenMM 최소화), 두 구조 각각의 OpenMM 전위·변이 위치 잔기 SASA·변이 잔기 주변 중원자 접촉을 나란히 남긴다(결정 0029). 모든 값은 실제 OpenMM·FreeSASA 실행 결과이고, 두 구조의 값을 서로 빼거나 구조 안 최소화 전후 변화량을 만들지 않는다. 같은 조건 도킹은 단독 M18에 이 모델을 수용체 출처로 넘겨 두 구조에 각각 돌린다. 닫힌 집합·상한·문장은 `backend/mw/mutation_model_constants.py`에 있고 바꾸려면 사용자 결정이 필요하다.

### 입력
- 작업 전용 도구 `openmm_mutation_model`, 프로토콜 `openmm_mutation_model_v1`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`·작업 승인 허용 목록, `SUPPORTED_TOOLS` 아님). 제출·시작·승인·상태·취소·재시도는 기존 작업 API다.
- 인자(알 수 없는 키 거부): `candidate_set`(같은 run의 게시된 `mutation_candidate_set@1`, 필수), `candidate_index`(정수 ≥ 0, 후보 집합 `candidates[].index`, 필수. `from`·`to` 문자로 찾지 않음), `seed`(정수 0–2147483647, 필수), `selection_policy`(리터럴 `"protein_only"`), `hydrogen_policy`(리터럴 `"rebuild_pH7"`), `contact_cutoff_A`(유한수 2.5–6.0 양끝 포함, 기본 4.0). 구조 handle은 요청에 없고 후보 집합의 `prepared_structure`에서 온다.
- 작업 시간은 인자가 아니라 `JobSubmit` 최상위 `timeout_s`다: 이 프로토콜 기본 120초(빼면 120, 화면은 항상 보냄), 0 초과 240 이하. 호출 키에 들어가지 않는다.
- 호출 키 = 정규화 인자(기본값 채움) + 작업 모듈 SHA-256 + 작업 모듈이 쓰는 프로젝트 모듈 다섯 개(`mutation_model_math.py`, `mutation_model_constants.py`, `jobs/openmm_worker.py`, `tools/openmm_method.py`, `mutation_candidates.py`)의 SHA-256 + 고정 방법 기록. 같은 입력은 같은 작업·같은 handle이고 새 단위를 쓰지 않는다. seed나 cutoff가 다르면 새 호출 키다.

### 입장 검사 (작업을 만들기 전, 예산 없음, 이 순서, 첫 실패만)
1. 422 `input_invalid`, `detail.reason_code`: `unknown_field` → `confirmation_missing`(두 리터럴 중 하나라도 다름) → `argument_invalid`(형식·범위, bool·NaN·Infinity, cutoff null, `timeout_s` 범위 밖. API 본문 모델이 `timeout_s`·`args`를 거절해도 이 코드) → `candidate_set_invalid`(handle 아님·다른 run·다른 종류·미게시, 저장 집합이 M20 `validated_set`을 통과하지 못함. 제출 때마다 다시 검증) → `candidate_unknown`(그 번호의 후보 없음, 후보 0개 집합 포함) → `structure_invalid`(집합의 구조가 이 run의 `prepared_structure@1`이 아님) → `residue_mismatch`(위치 7필드가 구조에서 정확히 하나로 풀리지 않거나 후보 `from`이 그 잔기의 표준 한 글자와 다름).
2. dry-run run이면 여기서 계획만 돌려준다(엔진 확인 없음).
3. 412 `precondition`(예약·과금 전): `process_identity_unavailable` → `openmm_unavailable` → `pdbfixer_unavailable`(고정 OpenMM 8.6.0 포스필드 지문·PDBFixer 1.12.0·psutil 신원 어댑터).
4. 422 `openmm_preflight_failed`: M7 사전 검사 실패 전부(완전한 표준 중원자 템플릿, 사슬 끝 OXT, 잔기 간격 없음, 펩티드 C–N 1.1–1.7 Å, 단백질만, 중원자 6,000 등). M7이 precondition·resource_exceeded로 낸 것도 이 422로 바꾸고 `detail.m7_reason`(M7 코드 또는 null)·`detail.m7_message`를 붙인다. 입력을 복구하지 않는다. 사전 검사 투영에서 후보 잔기가 하나로 풀리지 않으면 `residue_mismatch`, 모델 번호가 다르면 `structure_invalid`.
5. 429 `resource_exceeded`(`limit: "staged_input_bytes"`): 스테이징 입력이 4,000,000 B 초과.

### 모델링 절차 (작업 모듈 `mw/jobs/openmm_mutation_worker.py`, 두 구조가 같은 코드 경로)
- 입력은 M7 사전 검사의 단백질 중원자 투영(체인·잔기·원자 순서, 잔기 7필드)이다. 야생형 기준과 변이형이 같은 투영에서 시작한다.
- **변이형만** PDBFixer를 거친다: M7과 같은 위상을 PDBx 텍스트로 써서 `PDBFixer(pdbxfile=…)` → `findMissingResidues`(하나라도 있으면 `unexpected_atoms_added`) → `applyMutations([<원래 이름>-<순번>-<새 이름>])` → `findMissingAtoms`(변이 잔기가 아닌 잔기에 누락 원자·말단이 표시되면 `unexpected_atoms_added`) → `addMissingAtoms(seed)`. PDBFixer 예외는 `mutation_modeling_failed`다.
- **이식**: 변이 잔기 밖은 잔기·원자 이름·원소·순서가 같아야 하고(더해진 원자 `unexpected_atoms_added`, 그 밖의 변경 `mutation_modeling_failed`) 좌표 차이가 1e-9 Å 이하여야 한다(넘으면 `coordinates_changed`). 그러면 입력 좌표를 그대로 쓴다. 변이 잔기 안에서도 입력에 있던 이름의 원자(뼈대, 새 템플릿에도 있는 같은 이름 곁사슬 원자, C 말단 OXT)는 입력 좌표를 쓰고, PDBFixer가 새로 놓은 원자만 PDBFixer 좌표다(`added_heavy_atoms`). 변이 잔기 중원자 이름 집합은 포스필드 템플릿(말단이면 말단 템플릿)과 같아야 한다(아니면 `mutation_modeling_failed`). 곁사슬은 한 가지 형태다.
- 두 구조 각각: Python·NumPy 난수를 `seed`로 시드 → 위상(`createStandardBonds` + 거리 기반 `createDisulfideBonds`) → `Modeller.addHydrogens(pH 7.0, CPU 1스레드)` → Amber14-all + GBn2 System(XML은 해시만) → 전위 `before` → 최대 50회 최소화(허용 오차 10 kJ/mol/nm) → 전위 `after`. `after > before + 1e-4`이거나 비유한이면 `energy_invalid`. 수렴은 주장하지 않는다. 포스필드 XML 지문은 M7 `FORCEFIELD_SHA256`으로 다시 확인한다.
- 양성자 상태: 두 구조의 모든 HIS·CYS 행 `{residue(7필드), variant}`. `variant`는 OpenMM이 돌려준 이름(HID·HIE·HIP·CYX) 그대로이며 기본 템플릿(자유 Cys 등)은 null이다. 변이 잔기를 뺀 잔기 중 두 구조에서 값이 다른 잔기가 `protonation_differences`(`{residue, wild_type_reference, mutant}`)다. 이황화가 끊기거나 새로 생기면 상대 Cys의 상태가 바뀌므로 이 목록이 생긴다.
- 이황화: 각 구조 `final_bonds`의 SG–SG 결합 잔기 쌍. 변이 잔기는 원래 7필드로 짝지어 변이형에만 있는 쌍이 있으면 `new_disulfide_in_mutant: true`.
- SASA: FreeSASA 2.2.1, Lee–Richards 100 slices, probe 1.4 Å, 스레드 1, gemmi 원소 반지름. 최소화한 모델의 단백질 중원자 전체로 계산하고 **변이 위치 잔기 하나**의 값(Å², float)만 저장한다. 리간드는 없다. 주변 잔기 SASA는 만들지 않는다.
- 접촉: 변이 잔기 중원자와 다른 모든 잔기(모든 체인) 중원자의 유클리드 거리 ≤ cutoff(경계 포함, float64, 반올림 없이 저장). 최종 결합 위상에서 그래프 거리 1–3결합 이내 쌍은 뺀다. 행 `{atom_name, element, partner_residue(7필드), partner_atom_name, partner_element, distance_A}`, 순서는 (변이 잔기 원자의 구조 내 순서, 상대 잔기 구조 순서, 상대 원자 순서). 0개는 계산한 0이며 null과 다르다. 구조당 2,000행을 넘으면 자르지 않고 `resource_exceeded`(`too_many_contacts`). "수소결합"이라 부르지 않는다.
- 구조 파일: 구조마다 최소화 최종 좌표(수소 포함)의 mmCIF(M7 `_coordinates`와 같은 쓰기, 표준 이름 HIS·CYS, 변이 잔기 `resname`은 변이 후 표준 이름). 변이 잔기의 행은 원래 7필드로 짝짓는다.

### 결과 객체 `mutation_model@1`
- 최상위 키: `schema`, `method_version`(`mw.mutation_model/v1`), `candidate{candidate_set, candidate_index, position_index, from, to, residue(원래 7필드), mutant_resname}`, `structure{handle, model_number, structure_kind: "prepared_structure"}`, `parameters{seed, contact_cutoff_A, selection_policy, hydrogen_policy}`, `method`(M7 방법 기록 + `engine_build`·`forcefield_files_sha256` + `pdbfixer_version`), `excluded_components`(M7 범주 셋, 개수 0 포함), `structures{wild_type_reference, mutant}`, `comparison`, `protonation_differences`, `limitations`.
- 구조 항목(두 쪽 같은 모양): `structure_object`(mmCIF 객체 `mutation_model_structure@1` handle), `structure_sha256`, `system_xml_sha256`, `topology_sha256`, `heavy_atoms`, `added_hydrogens`, `added_heavy_atoms`(야생형 기준은 `[]`), `protonation_variants`, `disulfide_bonds`, `final_bonds`, `atom_mapping`(원자마다 잔기 7필드·원자 이름·원소·최종 좌표, mmCIF 원자 순서), `energy{before_kJ_mol, after_kJ_mol, unit: "kJ/mol", engine: "OpenMM", force_field: "amber14-all + implicit/gbn2", convergence: "convergence_not_claimed"}`, `sasa{residue, engine: "FreeSASA", value_A2, parameters}`, `contacts{cutoff_A, excluded_bond_distance: 3, rows, count, residue_count}`.
- `comparison{mutated_residue, resnames{wild_type_reference, mutant}, new_disulfide_in_mutant, protonation_difference_count}`. 에너지·SASA·접촉 수의 차이 필드는 없다(있으면 검증 실패).
- 게시 전에 순수 검증기 `mutation_model_math.validated_model`(엔진 import 없음: 모양·닫힌 집합, 저장 좌표에서 접촉 다시 계산, 위상 해시·이황화 쌍·비교·양성자 차이·한계 문장 다시 만들기, 차이 필드 부재)과 작업 선택 기록 대조(야생형 중원자 = 스테이징한 M7 투영, 변이형 추가 원자 = 변이 잔기에서 새로 생긴 이름, mmCIF 바이트 해시·원자 행)를 통과해야 mmCIF 객체 둘과 결과 하나를 저장한다. 객체 내용에 시각·작업·시도 ID가 없어 같은 입력은 같은 handle이고, 이벤트가 전체 payload를 담아 events-only로 다시 열린다(엔진 없이). 결과 64,000,000 B를 넘으면 자르지 않고 `resource_exceeded`. 1UBQ 결과는 약 0.6 MB다(착수 확인).

### 고정 한계 문장 (결과 `limitations`, 보고서, 화면에 문자 그대로, 이 순서, 해당 조건일 때만)
  1. (L1, 항상) "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다."
  2. (L2, 항상) "OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 없고 ΔΔG·안정성·친화도가 아니다."
  3. (L3, 항상) "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다."
  4. (L4, 항상) "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다."
  5. (L7, 항상) "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다."
  6. (L5, `protonation_difference_count > 0`) "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 하나만이 아니다."
  7. (L6, 변이형에만 이황화 결합이 있음) "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다."
- L1–L7은 상수 이름이며 화면에 번호를 보이지 않는다.

### 닫힌 집합
- 입장 422 8개(위 순서), 사용할 수 없음 412 3개(위).
- 작업 실패 `detail.reason_code` 7개와 실패 분류: `mutation_modeling_failed`·`unexpected_atoms_added`·`coordinates_changed`·`topology_unsupported`(`input_invalid`), `energy_invalid`·`engine_failed`(`fatal`), `resource_exceeded`(`too_many_contacts`, 출력·결과 크기). 그 밖의 작업 모듈 예외는 `engine_failed`, 잘못된 오류 봉투는 `fatal`. 시간 초과·취소·재시도는 기존 작업 상태다. 실패·취소·시간 초과 작업은 결과를 남기지 않고 예약한 1단위는 환불하지 않는다. 시작 때 고정 pin(작업 모듈·의존 파일 해시·방법 기록)이 바뀌었으면 `worker_version_invalid`(412).
- 같은 조건 도킹 짝의 점수 없음 이유 8개: `not_submitted`, `job_not_finished`, `job_failed`, `job_cancelled`, `job_interrupted`, `result_invalid`, `other_side_missing`, `no_modes`(`mutation_model_reads.PAIR_REASONS`, 고정 한국어 문장).

### 작업과 예산
- 작업 하나 = 비싼 계산 1단위(두 구조를 만들어도). run의 첫 비싼 계산이면 `expensive_first_call` 승인이 필요하다(M7과 같음). dry-run run은 계획만 만든다.
- guardian이 고정 작업 모듈을 프로젝트 인터프리터로 띄우고(감시 대상, 출력 64,000,000 B) M7과 같은 프로세스 신원·정리 규칙을 쓴다. 서버 프로세스는 PDBFixer를 import하지 않고(버전은 `importlib.metadata`만), OpenMM은 기존 M7 `openmm_method.dependencies()`·`preflight()`로만 서버에서 import된다.
- capability `methods.mutation_model`: 고정 OpenMM 8.6.0 포스필드·PDBFixer 1.12.0·프로세스 신원 어댑터가 모두 있을 때만 사용 가능. 아니면 이유와 함께 사용할 수 없음이고 버전·숫자가 없다.

### 읽기
모두 이벤트·작업·도구를 만들지 않고 매번 저장 객체를 `validated_result`(단일 완료 게시, 작업 선택 기록, 후보 집합 행, 구조 종류, 저장 mmCIF 바이트, `validated_model`)로 다시 검증한다. 목록(최신 순, 검증 실패 행은 숫자 없이 `valid: false`), 요약 상세(접촉 행·`final_bonds`·`atom_mapping` 제외), 쪽별 접촉 행 페이지, 쪽별 mmCIF 내려받기(저장 바이트 그대로, 해시 대조), 같은 조건 도킹 짝. handle은 URL 경로다.

### 같은 조건 도킹
- 화면 동작 하나가 같은 조건(같은 SDF 리간드·상자·seed·값, 자유 도킹)의 M18 작업 둘을 `receptor_source.side`만 다르게(야생형 기준 먼저) 기존 작업 API로 제출하고 하나씩 시작한다. 작업마다 1단위, 합쳐서 2단위이며 화면이 먼저 2단위를 확인받는다. 새 쓰기 라우트는 없다. 한쪽이 거절·실패·취소되어도 다른 쪽은 그대로다. 규칙·점수 문구·접촉 표·보고서는 M18 그대로다("리간드 도킹 (M18)"의 `receptor_source`).
- 짝 읽기 `docking_pairs`: 이 run에서 `receptor_source.mutation_model`이 이 모델인 단독 M18 작업을 조건(정규화한 `ligand`·`mode`·`box`·`parameters` 전부와 고정 M18 환경 pin 해시)으로 묶고, 조건 묶음마다 첫 제출 순서로 모두 나열한다(하나를 고르지 않음). 두 쪽 모두 게시·검증된 결과일 때만 쪽마다 결과 handle과 저장된 첫 모드 행 점수(`modes[0]`, 바꾸지 않음)를 보이고, 아니면 쪽마다 작업 상태와 점수 null + 닫힌 이유다(빠진 쪽 점수는 0이 아님). 차이·순위·"개선"이 없다. 야생형 도킹은 후보 간 재사용하지 않는다(후보마다 야생형 구조가 따로).

### 보고서
- `method_report_manifest@1`, `analysis_type: "mutation_model"`, 렌더 `mutation_model_markdown@1`. 입력은 `mutation_model@1` handle 하나. 만들기·다시 열기·다운로드는 모델을 다시 만들거나 최소화하지 않는다.
- 주장은 모두 `computed`이고 statement ID는 `candidate`(위치 7필드, `from`, `to`, 변이 후 이름, 후보 집합, 후보 번호), `openmm_potential`(두 구조 각각 `before`·`after`, kJ/mol), `mutated_residue_sasa`(Å²), `contact_cutoff`, `contact_count`, `contact_residue_count`(상대 잔기 `count_distinct`), `disulfide_pair_count`(두 구조), `protonation_difference_count`, `added_heavy_atom_count`(변이형 PDBFixer 추가 원자)다. 전위·SASA는 `Decimal(str(v))` 0.01 `ROUND_HALF_UP`, 개수는 정확히 일치. 템플릿은 "에너지"가 아니라 "OpenMM 전위"라 쓴다.
- 구조 간 차이·구조 안 변화(차이·변화·증가·감소·delta 등)를 말하는 주장과 도킹 점수 주장(score·docking·qvina·kcal·점수·도킹)은 거부한다. 한계 문장은 결과에 저장된 것을 위 순서 그대로 쓴다.
- 해석 금지어(M20 목록: M15 목록 + 안정성·ΔΔG·순위·추천·최적·개선·활성·예측·유망·좋은·나쁜·안전·점수·에너지·수소결합과 영문)는 값·식별자를 빈 자리로 둔 템플릿 줄마다 검사하고, 고정 한계 문장과 문자 그대로 같은 줄은 건너뛴다.
- 만들고 다시 열 때 저장 모델을 검증하고 manifest·주장·Markdown 바이트를 다시 만든 것과 비교한다. 틀린 값·반올림·섞인 증거·다른 run의 증거는 `report_evidence_invalid`. 보고서 목록 이름은 "변이 구조 모델 보고서".

### 화면 규칙
- 단백질 공학 탭의 M20 변이 후보 화면 아래 별도 영역(구조 분석 탭은 숨긴 채 유지). 후보 행의 "변이 구조 모델링"이 그 후보 집합·번호를 요청 칸에 넣을 뿐이며 seed는 비어 있고 두 확인은 체크되지 않은 채다(cutoff 4.0 Å·시간 120초 기본). 자동 선택·자동 제출·기본 승인이 없다. 비싼 계산 1단위 안내와 명시적 "비싼 계산 승인" 동작은 M7 방식이다.
- 결과: 변이 한 줄 요약(위치 7필드, from → to), 두 구조 저장값 나란히 표(OpenMM 전위 before·after, 변이 위치 SASA, 접촉·상대 잔기 수, PDBFixer 추가 원자, 이황화, 원자·수소 수), 이황화·양성자 상태 목록, 쪽을 고르는 접촉 행 표(페이지), 저장된 한계 문장, mmCIF 내려받기 둘, 보고서 만들기·목록·내려받기. 모델 목록은 아무것도 저절로 열지 않는다.
- 값은 서버 응답만 보이고 브라우저가 계산하지 않는다. 전위·SASA·거리는 소수 둘째 자리 `decimalHalfUp`, 개수는 정수, null·없음은 "—"와 이유. 차이·증감·개선 표시, 구조 간 막대·색 비교, 순위 열이 없다(두 구조 칸은 같은 스타일).
- 같은 조건 도킹 영역은 M18 순수 입력 로직(`lib/docking.ts`)으로 SDF 리간드·상자(리간드 범위 또는 직접 입력, 인스턴스 범위는 이유와 함께 막힘)·값·확인 세 항목을 받고 2단위 확인 뒤 한 번의 동작으로 작업 둘을 보낸다. 짝 표는 서버 `docking_pairs` 그대로이며 점수 이름은 M18 문구다. 짝 동작이 진행 중이면 다른 모델을 열 수 없다(이유 표시).
- 다섯 상태(불러오는 중·준비·빈 결과·실패·사용할 수 없음). capability가 없으면 숫자·컨트롤 없이 이유만. 늦은 응답은 run + 모델 handle + 영역별 요청 번호가 모두 같을 때만 반영한다. 뷰어·저장된 보기·브리지는 건드리지 않는다.

### 의미하지 않는 것
안정성·ΔΔG·결합 친화도·효소 활성·변이 효과, 두 구조 값의 차이나 개선, 순위·추천·점수, 수렴한 구조나 실험 구조, 수소결합·상호작용 판정. OpenMM 전위는 각 구조의 값이며 서열이 다른 두 구조는 서로 비교할 수 없다. 같은 조건 도킹 점수는 M18 qvina 점수이며 짝은 두 값을 나란히 둘 뿐이다.

## 서열 GA 설계 (M23, `sequence_ga_dock_v1`)

같은 run에 게시된 M20 변이 후보 집합 하나가 정한 조합 공간(보호되지 않은 위치 × 허용 아미노산) 안에서, 서로 다른 위치의 변이를 동시에 1~N개 묶은 개체를 유전 알고리즘(GA)이 세대를 거치며 고른다(결정 0031). 개체마다 변이 구조를 모델링(PDBFixer + M7과 같은 OpenMM)하고 사용자가 준 SDF 리간드를 같은 상자·seed·값으로 자유 도킹해 qvina 점수를 낸다. 적합도는 그 점수뿐이다. 개체 도킹은 M18 "리간드 도킹" 규칙 그대로이며(점수 표기·한계 문장·닫힌 이유) 모델링은 M21 규칙(PDBFixer는 변이 잔기에만, 변이 잔기 밖 원자 추가·좌표 변경은 실패, 단백질만, pH 7 수소)을 그대로 쓴다. GA는 "넓은 조합 공간에서 모델링·도킹 상한 안에 어디를 볼지 정하는 탐색 방법"이며 순위 도구가 아니다. 점수가 낮은 개체를 남기는 것은 탐색 규칙이고, 점수·변이를 "좋은·최고·개선·추천·승자"라 부르거나 부모·야생형 대비 차이를 만들지 않는다. 닫힌 집합·범위·상한·문장은 `backend/mw/sequence_ga_constants.py`에 있고(의존성 없는 표준 라이브러리 파일, 작업 모듈이 파일 경로로 공유) 바꾸려면 사용자 결정이 필요하다.

### 입력
- 작업 전용 도구 `sequence_ga_design`, 프로토콜 `sequence_ga_dock_v1`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`·작업 승인 허용 목록·guardian(도킹 인터프리터, 종료 기록 한도 64 KiB)·큐 dispatch, `SUPPORTED_TOOLS` 아님). 시도 1회(재시도 거절).
- 인자(알 수 없는 키는 거부, 수용체 키·`contact_cutoff_A`·`filter`도 알 수 없는 키): `candidate_set`(같은 run의 게시된 `mutation_candidate_set@1`, 구조는 그 집합이 가리키는 이 run의 `prepared_structure@1`), `ligand`(`{source: "sdf", sdf_handle}`만, 후보 출처 거절), `box`(M18 상자, `instance_range`는 `box_invalid`), `parameters`(M18 자유 도킹 값, `seed` = 평가 seed: 모델링과 도킹이 같은 값), `selection_policy: "protein_only"`, `hydrogen_policy: "rebuild_pH7"`(두 리터럴), `acknowledgement`(M18 세 항목), `ga`.
- `ga`(열한 키 모두 필수, 범위·기본 `GA_RANGES`): `seed` 0–2147483647(기본 없음), `population_size` 4–16(8), `generations` 1–8(5), `elite_count` 0–4(2, `population_size − elite_count ≥ 2`), `tournament_size` 2–4(2), `crossover_fraction` 0–1(0.5), `random_fraction` 0–0.5(0.2), `max_mutations` 1–4(3), `patience` 1–8(3), `max_new_evaluations` `population_size`–64(32), `total_s` 600–14400(7200). 정수는 `bool`이 아니고 두 비율은 유한 실수다. `JobSubmit.timeout_s`는 `total_s + 600` 이상 15000 이하이며 기본값이 없다(M22와 같은 세 곳).

### 입장 검사 (작업을 만들기 전, 예산 없음, 이 순서, 첫 실패만)
1. 422 `invalid_job_arguments`(모양·범위·교차 규칙·`timeout_s`·bool·NaN). 2. 422 `confirmation_missing`(두 리터럴), `acknowledgement_missing`. 3. 422 `candidate_set_invalid`, `structure_invalid`. 4. 422 M18 리간드·상자 이유의 **부분집합**: 서버가 RDKit 없이 할 수 있는 것만(`ligand_record_count`·`ligand_unparseable`·`ligand_multiple_fragments`·`ligand_element_not_allowed`·`ligand_too_many_atoms`·`ligand_not_3d`, `box_invalid`·`box_too_large`)이며 작업 모듈이 같은 이유로 거절할 입력만 거절한다. 5. (dry-run은 여기서 계획만) 412 `process_identity_unavailable`·`openmm_unavailable`·`pdbfixer_unavailable`·도킹 환경 이유. 6. 422 `openmm_preflight_failed`(M7, 복구하지 않음), `residue_mismatch`(조합 공간에 든 위치의 7필드가 투영 잔기 하나로 풀리지 않거나 `from` 불일치), `box_no_receptor_atoms`(M7 투영 중원자 기준). 7. 422 `ga_space_too_small`(조합 공간 크기 `N` < `population_size`). 8. 429 `staged_input_bytes`(스테이징 16 MiB 초과). 9. 429 `ga_limit_raise_required`(예산 부족, 과금 없음).
- 서버가 알 수 없어 기준 행에서 드러나는 입력 이유: `ligand_hydrogens_missing`·`ligand_too_many_torsions`·`ligand_prep_failed`, 수용체 준비 `receptor_*`(M18 수용체 한도는 투영 중원자 약 4,890개를 넘으면 `receptor_invalid`로 실패할 수 있고 입장에서 걸러지지 않는다. 시작 전 확인이 `projection_heavy_atoms`와 경고를 보인다).

### 조합 공간과 절차 (작업 모듈 `mw/jobs/sequence_ga_worker.py`, 결정적)
- 위치 = 후보가 하나 이상인 `status == "candidate"` 위치(저장 순서), 개체 = 서로 다른 위치의 후보 1~`M`개(`M = min(max_mutations, P)`), 개체 키 = 후보 번호 오름차순(`12-57-203`, 야생형 기준 행은 `wild_type`). 조합 공간 크기 `N` = Σ e_k(위치별 후보 수)(정확한 정수). 한 실행 안에서 같은 키는 두 번 평가하지 않는다.
- 점수 순서: 점수(저장된 단독 M18 결과 첫 모드)가 낮은 쪽이 앞, 동점은 변이 수가 적은 쪽, 그다음 `pick_index`. 점수 없는 개체는 선택·이어받음·부모에서 늘 제외.
- 난수는 `ga.seed`의 `random.Random`이고 호출은 `randint`·`random`·`sample`·`choice`뿐이며 순서가 고정이다(아래 "세부 규칙"과 커밋된 독립 oracle `backend/tests/fixtures/sequence_ga/independent_sequence_ga_oracle.py`·`expected.json`이 같은 해석이다). 세대 1 = `draw()`(변이 수 1~`M`을 균등하게 먼저, 위치·치환 균등)를 `population_size`번. 세대 g+1 = 이어받음(점수 순서 앞쪽 `elite_count`) + 슬롯(`r = floor(random_fraction × slots + 0.5)`, `c = floor(crossover_fraction × (slots − r) + 0.5)`, 나머지 편집)을 교차 → 편집 → 무작위 순으로. 교차 = 토너먼트 두 부모의 변이 합집합에서(같은 위치 다른 후보는 `choice`, 한 부모만 가진 위치는 `random() < 0.5`, 빈 자식·`M` 초과 보정), 편집 = 추가·교체·이동·삭제 중 가능한 연산 하나. 본 키는 선택 즉시 반영되고 첫 시도에 더한 50·20·3번 재시도 뒤 정식 순서(크기 → 후보 번호 정수 목록 사전식)로 대체한다. 모든 슬롯을 먼저 선택한 뒤 슬롯 순서대로 평가한다.
- 야생형 기준 행을 개체보다 먼저 평가한다(개체가 아니므로 `max_new_evaluations`·선택·`min_score`·`patience`에 쓰지 않는다). 모델링이나 도킹이 실패하면 개체 평가 전에 `reference_failed`로 끝나고 요약은 기준 행 이유와 함께 게시된다(`null_result`는 실패가 아니다).
- 평가: 재사용(아래)이 없으면 새 평가(모델링 → 도킹, 2단위, 상한에 셈). 모델링이나 도킹이 실패하면 평가한 것으로 세고 재시도하지 않는다(`failed`, 점수 없음, 모델링 실패는 도킹 없음). **연속 실패 제동**: 선택 순서로 `failed`면 연속 실패 수 +1, `scored`·`null_result`(재사용 포함)면 0, 이어받은 개체는 건너뜀, 5건에서 `repeated_failure`.
- 세대가 끝나면 종료 우선순위: 마지막 세대 `generations_complete` > 모든 키를 이미 봄 `space_exhausted` > 점수 최솟값이 연속 `patience` 세대 작아지지 않음 `no_change`(세대 2부터 셈, 기준 행 제외).
- 종료 이유와 상태(닫힌 집합): `complete` = `generations_complete`·`no_change`·`space_exhausted`, `partial` = `evaluation_limit`·`time_exhausted`·`cancelled`·`worker_failed`·`resource_exceeded`·`reference_failed`·`repeated_failure`. 멈춤 검사 순서 `cancelled` > `evaluation_limit` > `time_exhausted` > 출력 총량 `resource_exceeded`. 중간에 멈춘 세대는 평가를 끝낸 개체만 담아 `complete: false`로 게시한다.

### 세부 규칙 (작업 모듈, 독립 oracle과 같은 해석)
- 재시도 횟수: `draw()` 50번, 교차·편집 슬롯 20번, 교차 부모 `B` 다시 뽑기 3번은 첫 시도에 **더한** 횟수다(총 51·21·4번). 교차 슬롯은 `B`를 3번 다시 뽑아도 `A`와 같거나 점수 있는 개체가 하나뿐이면 `A`의 편집 슬롯이 된다(토너먼트를 다시 부르지 않음). 점수 있는 개체가 하나도 없으면 교차·편집 슬롯 전부가 무작위 슬롯이다. 교차·편집 자식이 이미 본 키이면 그 슬롯을 **원래 종류로** 처음부터 20번까지 다시 시도하고 그래도 안 되면 무작위 슬롯으로 채운다. 편집 연산은 `add`(크기 < `M`이고 쓰지 않은 위치 있음)·`change`(같은 위치에 다른 후보가 있는 변이 있음)·`move`(쓰지 않은 위치 있음, 부모 크기가 1이어도 가능)·`remove`(크기 > 1) 중 가능한 것을 이 순서로 모아 `choice`한다(가능한 것이 없으면 무작위 슬롯).
- **본 키**는 선택되는 즉시 본 키가 된다(만들고 있는 세대의 앞 슬롯에서 고른 키도). 이어받은 개체를 다시 적은 항목은 새 키가 아니다. 슬롯을 시작할 때 본 키 수가 `N`이면 그 슬롯과 이후 슬롯은 난수를 부르지 않고 비워 두며, 새 슬롯을 하나도 채우지 못한 세대는 기록하지 않고 `space_exhausted`로 끝낸다(`generations_done`은 마지막으로 기록한 세대).
- 교차 자식을 줄일 때 `rng.sample`에 넘기는 목록은 위치 저장 순서의 변이 목록이고, 한 부모만 가진 위치는 자식 크기가 이미 `M`이어도 `rng.random() < 0.5`를 부른 뒤 초과분을 줄인다. 자식이 비면 합집합 후보(위치 순서, 같은 위치에서 `A`가 `B`보다 앞)에서 하나를 `choice`한다.
- `pick_index`는 개체를 처음 선택한 순서(0부터, 한 실행에서 유일, `carried` 항목은 처음 번호를 다시 적음), `eval_index`는 새로 평가한 개체만 평가한 순서(파일 이름 `<k>`, 재사용·이어받은 개체는 null). 세대의 개체 목록은 이어받은 개체(점수 순서)가 앞이고 새 개체가 선택 순서(= 평가 순서)로 뒤따르며, 이어받은 개체는 점수·`model_handle`·`result_handle`·`pick_index`를 처음 평가한 세대의 것과 같게 인용하고 새 평가를 세지 않는다. `evaluation_limit`은 다음 개체가 새 평가를 필요로 하는데 새 평가 수가 `reserved_evaluations`에 이미 닿았을 때 그 시점에 발생한다.
- 최솟값 비교는 값이 없다가 처음 생기면 '작아짐', 없음 → 없음과 x → y(y ≥ x)는 '작아지지 않음'이다. 모든 슬롯을 먼저 선택한 뒤 슬롯 순서대로 평가하므로 선택했지만 평가하지 못한 개체는 기록하지 않는다. 연속 실패 제동은 이어받은 개체를 건너뛴다.
- 작업 모듈이 끝나면 서버가 종료 이유를 정한다: 야생형 기준 행이 실패했으면 어떤 원인이든 `reference_failed`, 그렇지 않고 서버가 보낸 원인(사용자 취소 `cancelled`, 작업 마감 `time_exhausted`, 크래시·강제 종료·한도 `worker_failed`)이 있으면 그것, 아니면 작업 모듈의 종료 기록(`result.json`)을 쓰되 기록이 온전하지 않거나 종료 기록이 없거나 완료 세대 수와 어긋나면 `worker_failed`이고 작업 모듈이 스스로 쓴 `cancelled`(사용자 취소가 아닌 것)·`reference_failed`(기준 행이 실패하지 않은 것)도 `worker_failed`로 다시 해석한다.
- 재사용한 기준 행은 `reference.status.json`(단계 `docking`)만 쓰고 모델·도킹 파일은 쓰지 않는다. 모델링 자식 프로세스의 스트림 출력은 스트림당 1 MiB를 넘으면(자식이 끝난 뒤에도 확인) 자식을 죽이고 그 개체를 모델 단계 `resource_exceeded`로 실패시킨다. 자식 계약을 어기면(예상 밖 종료 코드, 종료 코드 1일 때 `error.json` 외에 남거나 빠진 파일, 잘못된 handle·해시) 그 개체는 `worker_failed`다.
- 서버 `finish`는 작업 모듈의 엔진·방법·상자를 서버 기록과 대조하고 어긋나면 모델·개체 이벤트를 하나도 게시하기 전에 `fatal`로 끝낸다. 요약의 `box`는 서버가 계산한 상자이고 작업 모듈이 상자를 읽지 못해 null일 수 있는 것은 기준 행이 `ligand_*`·`box_*` 이유로 실패한 경우뿐이다.
- 모델 객체 `limitations`: M21 L1·L3는 항상, 다중 변이용 SL5는 `protonation_differences`가 있을 때, M21 L6은 `new_disulfide_in_mutant`일 때다.

### 개체 평가: 모델 + 단독 M18 도킹
- 모델링 프로그램 `mw/jobs/sequence_model_worker.py`(프로젝트 `.venv`, `[<repo>/.venv/bin/python, "-I", 프로그램]`을 GA 작업 모듈이 같은 프로세스 그룹의 자식으로 실행, 경로는 `resolve()`하지 않음): 변이를 구조 순서로 M21 `mutant_projection`을 연속 적용하고 단계 사이에 앞 단계에서 PDBFixer가 놓은 원자 좌표를 소수 넷째 자리로 반올림(M21 PDBx 쓰기 정밀도), 최종 투영을 M21 `_prepare`·`_minimize`(Amber14-all + GBn2, 최대 50회)로 모델링. M21 모듈은 바뀌지 않았고 이 프로그램이 M21 모듈·상수·math·`mutation_candidates.py`·번들 SHA-256과 함께 호출 키에 묶인다. 모델 단계 240초, 도킹 단계 300초(수용체 준비 + 도킹)는 단계 전체 시간이다.
- 개체 도킹 결과는 단독 M18 `docking_result@1`과 같은 바이트·같은 호출 키·같은 handle이다(수용체 출처 `receptor_source = {kind: "mutation_model", mutation_model: <개체 모델 handle>, side: "mutant" | "wild_type_reference"}`, 서버가 저장 스키마로 `mutation_model@1`과 `mutation_set_model@1`을 구분, M18 한계 문장 열두 개). 사이드카는 서버와 같은 `docking_inputs` 함수로 만들며 게시될 mmCIF handle(내용 해시)을 저장 전에 계산해 쓴다. 수용체 PDBQT는 개체마다 준비한다.
- 재사용(무과금): 시작 때(run 실행 잠금 안) 이 run의 `sequence_ga_individual_published` 이벤트에서 같은 `conditions_sha256`을 가진 개체 중 모델과 도킹 결과가 모두 저장·검증된 것(`scored`·`null_result`)만. 실패한 개체·하나만 저장된 개체는 재사용하지 않고 다시 계산한다(결정적이라 같은 handle). 재사용 기록은 작은 사실(`key, state, reason_code, score, model_handle, result_handle`)이다.

### 변이 구조 모델 객체 `mutation_set_model@1`
서버만 만든다. 키: `schema`, `method_version`(`mw.mutation_set_model/v1`), `candidate_set`, `structure{handle, model_number, structure_kind}`, `mutations[{candidate_index, residue(7필드), from, to, mutant_resname}]`(야생형 기준은 빈 목록), `seed`, `method`(M21 method 기록 + `multi_mutation: "sequential_structure_order_round4"`), `structures`(키 하나: 변이 있으면 `mutant`, 없으면 `wild_type_reference` — M18 수용체 출처의 `side` 집합을 그대로 쓰기 위해서다. 항목: `structure_object`, `structure_sha256`, `system_xml_sha256`, `topology_sha256`, `heavy_atoms`, `added_hydrogens`, `added_heavy_atoms[{residue(7필드), atom_name, element}]`, `protonation_variants`, `disulfide_bonds`, `final_bonds`, `atom_mapping`, `energy{before_kJ_mol, after_kJ_mol, …}`), `protonation_differences`, `new_disulfide_in_mutant`, `reference_structure_sha256`, `limitations`(M21 L1·L3, 다중 변이용 SL5, M21 L6). 개체당 상한 16 MiB(넘으면 그 개체 `resource_exceeded`). SASA·접촉은 없다. 구조 mmCIF는 별도 객체 `mutation_set_model_structure@1`이다. 서버 `validated_model`은 mmCIF 해시·handle, 변이 잔기별 추가 원자(변이 모델의 그 잔기 중원자 − 입력 원자, M21 `mutation_model_bundle`과 같은 해석), 양성자 차이·새 이황화를 두 모델의 저장값에서 다시 계산해 대조한다. M18 수용체 읽기 경로는 기준 모델 비교 없이 `validated_model_alone`을 쓰고 요약 읽기가 전체 검증을 한다.

### 요약 객체 `sequence_ga_result@1` (서버만 만든다, 정리 확인 뒤 모든 종료 상태, 개체 게시 다음 마지막, 1 MiB)
- 키: `schema`, `protocol`, `engine`, `candidate_set`, `structure`, `ligand`, `box`(서버가 계산한 상자), `parameters`, `selection_policy`, `hydrogen_policy`, `method`(모델 pin + 도킹 pin), `call_key`, `conditions_sha256`, `selection_sha256`, `ga`(기본값 포함 전체), `space{positions, candidates, effective_max_mutations, size}`, `status`, `stop_reason`, `generations_done`, `new_evaluations_used`, `reused_count`, `reserved_evaluations`, `reserved_units`, `reference{evaluation, state, reason_code, score, model_handle, result_handle}`, `generations[{index, complete, individuals[{key, mutations, origin, parents, edit_op, evaluation, pick_index, eval_index, state, reason_code, score, model_handle, result_handle}], min_score, max_score}]`, `limitations`, 모듈·엔진 pin.
- 서버 검증(읽을 때마다): 후보 집합 안·위치 서로 다름·크기 ≤ 유효 `M`, `carried`가 아닌 개체 키 유일, 세대 개체 수 ≤ `population_size`, `carried` = 직전 세대 점수 순서 앞쪽(동점 `pick_index`), 교차 자식 ⊆ 두 부모 변이 합집합·비어 있지 않음, 편집 자식은 부모와 `edit_op`가 말하는 한 가지 변경만큼만 다름, 부모 키는 직전 세대 점수 있는 개체, 점수 = 저장된 도킹 결과 첫 모드, 모델·결과 객체 검증과 수용체 출처 대조, 모델의 `mutations`·`candidate_set`·`structure`·`seed`·`method`가 요약과 같음, 양성자 차이·이황화 재계산, `failed` 행은 이유가 모델링 전용이면 `model_handle` 없음·도킹 전용이면 있음(단계 전용 집합), 정수 필드는 bool이 아님, `reserved_units = 2 × (reserved_evaluations + 1)`, 종료 이유와 `status` 일치, 차이·순위·best·improved 필드 거부. 서버가 재계산하지 못하는 부모 선택(토너먼트·난수·재시도)은 작업 모듈 기록이다(S1). 기준 행이 기록되기 전에 멈춘 작업은 요약 없이 `failed`/`cancelled`다.

### 예산, 첫 계산 승인, 한도 증액
- 새 평가마다 비싼 계산 2단위(모델링 1 + 도킹 1). 시작 전 `reserved_units = 2 × (reserved_evaluations + 1)`(`reserved_evaluations = min(max_new_evaluations, population_size + (generations − 1) × (population_size − elite_count))`, 야생형 기준 행 2단위는 재사용 가능 여부와 무관하게 늘 예약)을 한 번에 예약하고 환불하지 않는다. 모델링이 실패한 평가도 2단위다. 재사용은 무과금이고 상한에 세지 않는다. 필요 시간 `min(total_s + 600, reserved_units × 270 + 300)`. 기본 run 예산은 대개 모자라 입장에서 429 `ga_limit_raise_required`(과금 없음)이고 사람이 화면에서만 부족분을 증액 승인한다(`RAISE_MARGIN_S` 60, `MAX_RAISE_EXPENSIVE_CALLS` 140, `MAX_RAISE_WALL_CLOCK_S` 15000).
- `Run.raise_limits`를 부르는 코드는 `docking_batch_jobs.limit_approval`(M19)·`ligand_ga_jobs.limit_approval`(M22)·`sequence_ga_jobs.limit_approval`(M23) 셋이고 서로를 부르지 않는다(AST 테스트). 같은 호출 키의 작업이 진행 중이거나 `complete` 요약이 있으면 새 작업 없이 그 작업을 돌려준다(`partial`만 있으면 새 실행).

### 고정 문장 (문자 그대로, 순서 고정, `sequence_ga_constants.STATEMENTS`, 바꾸려면 사용자 결정)
S1 항상: "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 부모–자식 관계만 검증했다." S2 `partial`: "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다." S3 재사용 개체가 있을 때: "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, 저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다." S4 항상: "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 않는다." S5 항상: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 ΔΔG·안정성이 아니다." S6 항상: "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 전에 소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 점수나 선택에 쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 점수를 나란히 두는 것은 같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 다르다) 순위나 '더 잘 결합'을 뜻하지 않는다." 모델 객체: M21 L1·L3 문장 + 다중 변이용 SL5 "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 차이는 지정한 변이만이 아니다." + M21 L6. 점수 문구는 M18·M19와 같다("qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)", 점수 대상 "모드 1(엔진 출력 순서)").

### 보고서
- `method_report_manifest@1`, `analysis_type: "sequence_ga"`, 렌더 `sequence_ga_markdown@1`("서열 GA 설계 보고서"), 입력은 요약 handle 하나. 주장은 모두 `computed`: `candidate_set_input`, `structure_input`, `ligand_input`, `box`, `parameter`, `ga_parameter`, `space_count`, `run_count`, `generation_count`, `generation_score_range`, `individual_score`, `individual_result_score`, `reference_score`, `reference_result_score`. 점수 주장은 `scored` 개체와 `scored` 기준 행에만, 요약 점수와 개체 결과 첫 모드 점수가 같아야 한다(0.1 `ROUND_HALF_UP`). OpenMM 전위·구조 간 비교·야생형 대비·차이 주장은 없다. 해석 금지어(M22 목록 + 순위·최고·개선·야생형 대비·차이·안정성·ΔΔG·전위)는 템플릿 줄마다 검사하고 고정 문장 줄은 건너뛴다. 만들고 다시 열 때 저장 요약을 검증하고 manifest·주장·Markdown 바이트를 다시 만든 것과 비교하며 도킹·모델링을 다시 하지 않는다.

### 화면 규칙
- 단백질 공학 탭에서 M20 변이 후보·M21 변이 구조 모델링 영역 아래 "서열 GA 설계" 영역(구조 분석 탭은 숨긴 채 유지, 선택된 동안에만 렌더링, run마다 `key`로 새로, 탭에 들어올 때 읽기만). 입력(후보 집합·SDF 리간드·상자·도킹 값·평가 seed·확인 항목)은 자동 선택·자동 제출·기본 승인이 없고 M18·M21 입력 로직을 재사용한다. 파라미터 편집은 열한 칸에 범위·기본값·칸별 이유를 보이고 범위를 벗어나면 시작 전 확인·시작을 막으며 "기본값으로"는 GA seed를 그대로 둔다. 조합 공간 크기·유효 `max_mutations`·예약 단위는 서버 시작 전 확인 응답 값만 보이고 브라우저가 계산하지 않는다. 증액은 사람이 단추를 누를 때만 한다.
- 결과: 야생형 기준 행은 값만 보이는 "야생형 기준(참고)"로 개체 표와 따로, 세대 탭, 개체 표(변이 한 줄 표기 + 펼친 7필드·출처 "초기/이어받음/교차/편집(연산)/무작위"·재사용 여부·qvina 점수·상태), 점수 없는 행은 "—"와 이유이며 모든 정렬에서 끝, 세대별 최솟값·최댓값(값만), 종료 이유("점수 최솟값 변화 없음" 등), 서버 저장 문장 S1–S6. 개체 상세는 모델 값만(변이 목록, OpenMM 전위와 S5, HIS·CYS 상태와 기준과 다른 목록, 이황화·추가 원자, mmCIF 내려받기)과 M18 결과 상세(`m18_detail`) 값이다. 차이·증감·순위·막대·색 비교·"최고"·"개선"이 없다. 한 번에 한 GA만 진행하고(진행 중이면 다른 요약 열기를 이유와 함께 막음) 늦은 응답은 run + 요약 handle + 영역별 요청 번호가 모두 같을 때만 반영한다. 다섯 상태, 사용할 수 없을 때는 숫자 없이 이유만.

### 의미하지 않는 것
결합 친화도·ΔΔG·안정성·효소 활성·변이 효과, 점수 정렬·선택 표시의 순위·추천·개선·"더 잘 결합", 야생형 대비 차이, 서열이 다른 구조의 OpenMM 전위 비교, 수렴한 구조나 실험 구조, 수소결합·상호작용 판정. 개체 점수는 개체마다 다른 수용체의 qvina 값이며 같은 수용체 안의 비교가 아니다. 부모–자식 연결의 선택 이유는 서버가 재계산하지 않았다.

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
- 비싼 계산 1단위는 실제 프로세스를 띄우기 직전에 예약하고, 성공·실패·시간 초과·중단 모두 과금한다(환불 없음). 입력 거부, 캐시 적중, dry-run 계획, 승인 거부, 대기 중 취소는 과금하지 않는다. M19 일괄 작업은 시도 하나가 새로 계산하는 행 수만큼(0 가능), M22 GA 작업은 시도 하나가 `reserved_units`만큼(재사용과 무관) 한 번에 예약한다.
- run에서 첫 비싼 계산에는 명시적으로 기록된 승인 이벤트가 필요하다. JSON 필드(`decided_by=human` 등), 재시도, 재시작으로 승인이 생기지 않는다. 승인은 소진된 예산을 채워 주지 않는다. 한도를 바꾸려면 따로 기록된 변경(`budget_limit_updated`)이 필요하다. HTTP로 한도를 올리는 길은 사람 증액 승인 둘뿐이다: M19 일괄(그 일괄의 부족분만)과 M22 GA(그 GA의 부족분만). 각자 자기 라우트 하나에서만 불린다.
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
- 반대로 흐름이 소유한 작업은 소유 실행이 끝나기 전에는 `/jobs`에서 수동으로 시작·재시도할 수 없다(412 `job_owned_by_analysis_execution`). 소유 실행이 종료 상태가 되면 흐름은 그 작업을 다시 움직이지 않으므로 기존 수동 시작·재시도 규칙이 그대로 적용된다(끝난 실행 기록은 바뀌지 않음). 수동 취소는 언제나 허용하며, 흐름은 그 단계를 재시도 불가 `job_cancelled`로 기록한다. 시도·시간 한도 소진이나 `compatibility_changed` 차단을 기록할 때 열린 dispatch의 소유 작업이 대기·실행 중이면 흐름이 먼저 그 작업에 범위 한정 취소를 건다.

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
- M16 `viewer_scene@2`: 참조 주석이 켜진 상태로 저장한 보기다. `viewer_scene@1`의 모든 필드 + `annotation{handle, legend}`. 저장할 때 서버는 주석 handle이 같은 run의 `reference_site_annotation@1`이고 그 `structure.handle`이 보기 소스 handle과 같은지 확인한다(아니면 `input_invalid` 또는 `structure_mismatch`). 주석이 꺼져 있으면 지금처럼 `viewer_scene@1`로 저장하고 바이트·handle이 바뀌지 않는다. 기존 `viewer_scene@1`·`viewer_figure@1`은 그대로 다시 열린다.
- `viewer_scene@2` 복원은 카메라·표현 등 기존 복원에 더해 저장된 주석을 다시 그린다(도구를 다시 실행하지 않음). 일부만 적용되면 적용된 것과 거부된 것을 나눠 보여 주고 롤백을 주장하지 않는다. 포켓 오버레이가 켜져 있거나 M10 비교 중이면 복원을 거절하고 이유를 보여 준다(오버레이·비교를 조용히 끄지 않음). `viewer_scene@1` 복원은 켜진 주석을 끈다.
- M16 그림: `viewer_scene@1` 보기의 그림은 `viewer_figure@1`(바이트 불변). `viewer_scene@2` 보기의 그림은 `viewer_figure@2`: @1 필드 + `annotation{handle, legend, numbering_map, contacts, snapshot_set_hash, display_labels}`(저장된 주석 객체에서 복사), `capture_method`는 범례를 그려 넣었으면 `molstar_image_pass+legend`, 아니면 `molstar_image_pass`. 그림 schema는 보기 schema와 짝이 맞아야 한다.
- PNG 범례: 보기의 `legend`가 참(기본)이고 그린 점선이 하나 이상이면 PNG 한 구석에 고정 문구 "점선: 기하 극성 접촉(원자 거리), 수소결합 판정 아님"을 같은 글자 크기로(필요하면 줄바꿈) 그려 넣는다. 그래도 들어가지 않으면 그림을 저장하지 않는다. 사용자가 패널에서 범례를 끄면 그 값이 보기의 `legend`에 기록된다. `legend`가 거짓인 보기에 범례를 그려 넣었다는 그림은 거부한다. 범례 문구를 바꾸거나 없애지 않는다.
- PNG 크기·개수 한도는 M16에서도 그대로다(위 한도, 결정 0024).
- PNG는 그 시점 렌더링일 뿐이다. GPU마다 픽셀이 다를 수 있으므로 다시 렌더링한 PNG의 바이트가 같다고 주장하지 않는다. 저장한 PNG를 다시 받을 때는 바이트가 같아야 한다.
