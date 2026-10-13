# M29 T1 착수 확인 (2026-10-13)

반환 상태: **BLOCKED** — 아래 "멈추고 알릴 상황" S1에 해당한다. 나머지 항목 (a)–(k)는 모두 측정·확인했고 결과는 이 문서에 있다.

- 작업 위치: 메인 체크아웃 `<root>`, 브랜치 `dryforge/m29-structure-repair`, 시작 HEAD `3c5994e4`. 제품 코드·시험·설정·기존 문서는 바꾸지 않았다. 새 파일은 이 폴더(`docs/qa/m29-repair-20261013/`)뿐이다.
- 환경: Apple M3 Ultra(논리 CPU 28), 프로젝트 `.venv`의 gemmi 0.7.5·numpy 2.4.6·OpenMM 8.6.0·PDBFixer 1.12.0. 템플릿 `openmm/app/data/amber14/protein.ff14SB.xml` sha256 `d9f9779c09d67cd5f8bc657692f174ffab14c469dfd06d560ac1899fa7e976b8`.
- 측정하는 동안 같은 기계에서 다른 세션의 작업이 돌아 load average가 9–23이었다. 시간 측정은 모두 단일 스레드(OpenMM CPU `Threads=1`) 프로세스의 벽시계 시간이다. 부하 보정은 하지 않았다.
- 외부 요청 0건. 엔진(OpenMM·PDBFixer)을 띄운 probe는 `probe/netguard.py`로 비-loopback `connect`를 막고 시도 수를 셌으며, 모든 실행에서 0이었다(각 출력 끝의 `non_loopback_connect_attempts=0`). 시작할 때 `lsof`로 8000·3000 리스너가 없음을 확인했고 서버·프런트는 띄우지 않았다. `.env`는 열지 않았다.
- `.deps/precedent_reference`와 `.deps/reaction_reference`는 없다. 8VF6 입력 sha256 `0c2c46cf2b87be1379aaac842ae9a17d6ef373865151e2669e89ae099d1f9b8a`, 888,122 B로 명세와 같다.
- 임시 자료는 Git 제외 폴더 `runs/m29-t1-20261013/*`(probe 전용 throwaway run)와 세션 scratchpad에만 두었다. 기존 run 폴더는 쓰지 않았다. `runs/stk33-8vf6-20261013/probe/raw/`는 읽지 않았다.

---

## 멈추고 알릴 상황

### S1. 8VF6 보완 구조의 M21 작업 하나가 240초 상한을 크게 넘는다 (1,035초)

- **측정:** 보완한 8VF6(strip_all, 단백질 중원자 4,538)에서 후보 하나(A LEU122→ALA)를 돌렸다. 제품 작업 모듈 `backend/mw/jobs/openmm_mutation_worker.py`를 바꾸지 않고 guardian과 같은 방식(`<venv python> -I <worker>`, attempt 폴더, 최소 환경)으로 실행했다. 단독 프로세스 시간은 **1,035.31초**로 상한 240초의 4.3배다. 작업은 정상 종료(exit 0, `result.json`)했다. 결과는 맞게 나오지만 시간 안에 끝나지 않는다.
- **원인:** 크기 때문이다(아래 표). 시간은 단백질 중원자 수의 대략 제곱으로 는다. NoCutoff GBn2 System 두 개(야생형 참조 + 변이형)를 각각 수소화하고 최소화하기 때문이다.
- **상한을 올릴 수 없는 이유:** 상한 `TIMEOUT_MAX_S = 240`은 `backend/mw/mutation_model_constants.py:29`에 있다. 이 파일은 호출 키 해시 파일 27개(`BASELINE_BLOBS`) 중 하나라서 올리려면 해시 파일을 바꿔야 하고, 그것은 사용자 결정 사항이다.

| 구조(보완 뒤) | 단백질 중원자 | M21 작업 하나(초) | 240초 안 | 기본 120초 안 |
|---|---:|---:|---|---|
| 1UBQ(보완 없음, 기준) | 602 | 20.65 | 예 | 예 |
| 1HSG | 1,516 | 118.46 | 예 | 예(여유 1.5초) |
| 1A30 | 1,542 | 123.24 | 예 | **아니오** |
| 1MQ4 | 2,160 | 233.38 | 예(여유 6.6초) | 아니오 |
| 1M17 | 2,594 | 309.81 | **아니오** | 아니오 |
| 1A4I | 4,476 | **992.07** | **아니오** | 아니오 |
| 8VF6 | 4,538 | **1,035.31** | **아니오** | 아니오 |

출처: `probe/out/m21_on_repaired.txt`. 1UBQ·1HSG·1A30·1MQ4·1M17·1A4I는 같은 시각에 병렬로 돌렸다. 8VF6은 처음 약 10분은 혼자, 그 뒤 약 4분은 다른 여섯 프로세스와 겹쳐 돌았다.

**계획에 미치는 영향 (판단은 사용자에게 맡김)**
- 명세 §10.2는 `in_scope`면 "보완 → M7 통과 → M20 → M21 작업 완료"를 반드시 요구한다. 8VF6·1A4I·1M17에서는 이 정의를 지금 상한으로 만족할 수 없다.
- 그래서 R1(8VF6 종단)의 M21 이후 부분, R4(8VF6 M21·M18), R5(로컬 `in_scope` 사슬)를 명세대로 `pass`로 만들 수 없다.
- R2("M21 입장이 `openmm_preflight_failed` 없이 열린다")는 입장만 보므로 가능하다. 보완 구조의 M7 사전 검사는 통과했다(아래 (c)·(f)).
- 선택지(이 문서는 고르지 않는다):
  1. 상한 유지. 큰 구조의 M21 완료를 수락 정의에서 빼고 "시간 초과로 끝남(1단위 청구)"을 알려진 한계로 기록한다. R4·R5를 작은 구조(1HSG·1A30·1MQ4, 그리고 `timeout_s` 240)로 보인다.
  2. 해시 파일 `mutation_model_constants.py`의 상한을 올린다. 사용자 결정이 필요하고, M21·M23 호출 키·골든 `golden_call_keys.json` 재기록과 옛 결과 재사용 끝을 수락해야 한다.
  3. M21에 들어가는 원자 수를 줄이는 다른 설계. 예: 사슬 일부만 모델링. 명세 §1.2의 "사슬 일부만 골라 보완" 금지, 그리고 M21 경로 변경과 충돌한다.

---

## 사용자 결정 또는 명세 해석이 필요한 것

멈춤 목록에는 없지만 명세 문구와 측정이 어긋나는 것들이다.

### D1. 새 원자 좌표는 소수 넷째 자리로 반올림해야 M21·M23이 돈다

명세 §3.5는 "좌표는 반올림하지 않는다"고 쓴다. 그런데 M21 작업 모듈은 변이를 만들 때 단백질 위상을 `app.PDBxFile.writeFile`로 텍스트화한다. 이 함수는 좌표를 `%10.4f`로 쓰고(`openmm/app/pdbxfile.py` writeModel), 이어서 `_graft`가 변이 잔기 밖 좌표를 1e-9 Å로 대조한다(`openmm_mutation_worker.py:78` `GRAFT_TOLERANCE_A`). 해시 파일이라 바꿀 수 없다.

| 보완 구조의 새 원자 좌표 | M7 사전 검사 | M21 작업 |
|---|---|---|
| PDBFixer 전체 정밀도 그대로 | 통과(중원자 4,538) | **0.5초 만에 실패.** `coordinates_changed`, `max_abs_shift_A` 4.566e-05, A/100/LYS, "PDBFixer moved an atom outside the mutated residue" |
| 소수 넷째 자리로 반올림 | 통과 | 정상 종료(1,035초, S1) |

- 출처: `probe/out/m21_on_repaired.txt`, `probe/out/marker_and_preflight.txt`의 `pdbx_writefile_4dp_roundtrip_max_A`가 4.99e-05 대 0.0.
- M23에 같은 원인의 선례가 있다(`docs/engineering-notes.md` "여러 곳 변이를 M21 함수로 이어서 적용하면…": 단계 사이에 새 원자만 소수 넷째 자리로 반올림, `sequential_structure_order_round4`).
- **제안:** 보완 구조에 넣는 새 원자 좌표를 소수 넷째 자리로 반올림하는 것을 방법 고정 정보로 기록한다(축마다 ≤ 5e-5 Å, 측정 최대 3차원 7.5e-5 Å). 보완 기록의 `added_atoms`는 구조에 실제로 들어간 값과 같게 하고(그 이상 반올림하지 않음), PDBFixer 원값과 다르다는 사실은 기록한다.
- 관측 원자는 입력 그대로이며 입력 좌표는 소수 셋째 자리까지다(`probe/out/input_marker_survey.txt`).
- `probe/8vf6_additions.json`은 지시대로 PDBFixer 원정밀도를 그대로 둔다. 반올림은 접합 빌더(T4)가 해야 한다.

### D2. PDB 형식 입력의 `chain_label`은 null이 아니다

명세 §2.3은 PDB 형식이면 `label_seq`와 `chain_label`을 null로 둔다고 쓴다. 측정 결과는 이렇다.
- gemmi로 읽으면 `label_seq`는 항상 None이다(544/544).
- SEQRES가 있는 PDB 파일은 gemmi가 합성 subchain 이름(`Axp`·`Ax1`·`Bxp`·`Bx1`, 물은 `Axw`)을 붙인다. 그래서 제품 `_res_ref`의 `chain_label`이 null이 아니다(`probe/out/info_location.txt`).
- SEQRES가 없는 `backend/tests/fixtures/mini_complex.pdb`는 `''`이고, 제품에서는 null이 된다.
- T4는 PDB 형식 틈 잔기의 `chain_label`을 "gemmi가 다시 읽었을 때 붙는 값"으로 맞출지 null로 둘지 정해야 한다. 보완 구조 바이트를 다시 읽으면 제품은 gemmi 값을 본다.

### D3. 1FIN은 조각을 합쳐도 `atom_limit_exceeded`다

명세 §1과 R5는 1FIN의 저자 체인 중복이 조각 분리 때문이라고 쓴다. 그 자체는 맞다. 그러나 합친 뒤 단백질 중원자가 8,998로 M7 상한 6,000을 넘는다. 제품 M7도 합친 1FIN에 `resource_exceeded`("protein atom count is empty or exceeds fixed limit")를 낸다(`probe/out/crosscheck_m7.txt`). 1FIN은 `out_of_scope(atom_limit_exceeded)`다.

---

## (a) 독립 분류

**방법:** `probe/classify_structures.py`가 gemmi와 템플릿 XML만 쓴다. 템플릿 경로는 `importlib.util.find_spec`으로 찾고 openmm·`mw`는 import하지 않는다.
- 전처리를 독립 재구현했다: 모델 0, 수소 제거, altloc `highest_occupancy`, 물 정책.
- gemmi로 쓰고 다시 읽은 뒤 명세 §2.2 순서로 검사한다.
- 틈 잔기는 원본 파일의 `_entity_poly_seq` + `_pdbx_unobs_or_zero_occ_residues`(occupancy_flag 1)에서만 확정한다.

출력: `probe/out/classification.tsv`(표), `probe/out/classification.json`(전체 걸림돌·결함 목록).

| 구조 | 물 정책 | 분류 | 체인 조각(저자 체인별) | 곁사슬 결손 잔기/원자 | OXT 결손 | 내부 틈(저자, 길이, 식별자 확정) | MSE·비표준 | 뼈대 결손 | 단백질 체인 이름 중복 | 점유율 0 원자 | 보완 뒤 단백질 중원자 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8VF6 | strip_all | `in_scope` | A2·B2 | 23(A10·B13)/91 | A/382·B/383 | A 273–285(13, 확정), B 274–284(11, 확정) | 0 | 0 | 없음 | 0 | 4,538 |
| 8VF6 | keep_all | `in_scope` | A3·B3 | 같음 | 같음 | 같음 | 0 | 0 | 없음 | 0 | 4,538 |
| 1M17 | 둘 다 | `in_scope` | A1 | 0 | A/995 | A 965–976(12, 확정) | 0 | 0 | 없음 | 37(전부 0인 잔기 A/725/GLU) | 2,594 |
| 1MQ4 | 둘 다 | `in_scope` | A1 | 8/36 | A/388 | A 286–287(2, 확정) | 0 | 0 | 없음 | 0 | 2,160 |
| 1A30 | strip_all | `in_scope` | A1·B1·C1 | 1(A/41/ARG)/6 | 없음 | 없음 | 0 | 0 | 없음 | 0 | 1,542 |
| 1A30 | keep_all | `in_scope` | A2·B2·C2 | 같음 | 없음 | 없음 | 0 | 0 | 없음 | 0 | 1,542 |
| 1A4I | strip_all | `in_scope` | A2·B2 | 0 | A/296·B/296 | A 241–250(10, 확정) | 0 | 0 | 없음 | 20 | 4,476 |
| 1A4I | keep_all | `in_scope` | A3·B3 | 0 | 같음 | 같음 | 0 | 0 | 없음 | 20 | 4,476 |
| 1HSG | strip_all | `in_scope` | A1·B1 | 0 | A/99·B/99 | 없음 | 0 | 0 | 없음 | 0 | 1,516 |
| 1HSG | keep_all | `in_scope` | A2·B2 | 0 | 같음 | 없음 | 0 | 0 | 없음 | 0 | 1,516 |
| 1S9I | 둘 다 | `out_of_scope(gap_too_long)` (A/313 앞 27, B/316 앞 34) | A2·B2 | 0 | A/393·B/389 | A 224–227(4)·A 286–312(27)·B 224–229(6)·B 282–315(34), 모두 확정 | 0 | 0 | 없음 | 0 | (5,205) |
| 1FIN | 둘 다 | `out_of_scope(atom_limit_exceeded)` | strip A2·B1·C2·D1 / keep A3·B2·C3·D2 | 0 | 없음 | 없음(미관측 목록 자체가 없음) | 0 | 0 | 없음(A·C와 B·D는 각각 다른 label 체인이고 이름도 다름) | 0 | 8,998 |
| 1UBQ | 둘 다 | `out_of_scope(nothing_to_repair)` | A1 | 0 | 없음 | 없음 | 0 | 0 | 없음 | 0 | 602 |

**보완 종류**
- 8VF6은 두 정책 모두 `chain_parts_merged, side_chain_atoms_added, terminal_oxt_added, internal_gap_filled`이다.
- 1A30·1HSG는 물 정책에 따라 종류가 다르다. strip_all이면 조각 합치기가 없고, keep_all이면 물 조각 때문에 `chain_parts_merged`가 붙는다. 분류 자체는 정책 둘이 모두 같다.

**관측 끝 ≠ 서열 끝 (RP4 대상)**
- 1M17 A, 1MQ4 A, 1S9I A·B, 1A4I A·B, 8VF6 A(양 끝)·B(시작만).
- 8VF6 B의 C 끝은 서열 끝(label 286)과 같다.

**교차 확인 1 (파일의 원자 목록):** 템플릿으로 센 곁사슬 결손이 파일 자체의 `_pdbx_unobs_or_zero_occ_atoms`(occupancy_flag 1)와 같다. 8VF6은 23잔기/91원자, 1MQ4는 8/36이다.

**교차 확인 2 (제품 M7, `probe/crosscheck_m7.py` → `probe/out/crosscheck_m7.txt`):** 제품 결과를 정답으로 쓰지 않고, 분류와 같은지만 봤다.
- 원본 전처리 구조의 첫 거절은 M28 `m7-probe.txt`와 8VF6 점검(`A/100/LYS heavy_template_mismatch`)과 같다. 1M17 `sequence_gap` A/977, 1MQ4 `heavy_template_mismatch` A/126, 1S9I `sequence_gap` A/228, 1A30 A/41, 1A4I `sequence_gap` A/251, 1HSG `missing_terminal_oxt` A/99, 1FIN "duplicate author chain identity", 1UBQ 통과.
- 접합한 보완 구조(아래 (c)의 round4 + `calc_flag`, 저장하지 않은 보기)로 다시 돌린 결과:
  - `in_scope` 여섯은 두 물 정책 모두 통과했다. 중원자 8VF6 4,538, 1M17 2,594, 1MQ4 2,160, 1A30 1,542, 1A4I 4,476, 1HSG 1,516로 분류의 "보완 뒤" 값과 같다.
  - 1FIN 합치기만 한 구조는 `resource_exceeded`.
  - 1UBQ는 그대로 통과.
- 불일치는 0이다.

**계획에 미치는 영향**
- R5 표는 위 표가 기대값이다. `in_scope` 여섯 중 M21까지 상한 안에 끝나는 것은 1HSG·1A30·1MQ4뿐이다(S1).
- R7의 `gap_too_long`은 1S9I(27·34), `nothing_to_repair`는 1UBQ로 확인했다.
- 로컬 9개에는 MSE, 비표준 폴리머 잔기, 뼈대 결손, 템플릿 밖 원자, 단백질 체인 이름 중복, `gap_listing_missing`, `m7_condition_unsupported`가 하나도 없다. 그래서 R7·R8은 합성 표시 자료가 필요하다. 1FIN·1A30·1HSG·1UBQ에는 미관측 목록 자체가 없지만 틈도 없어서 `gap_listing_missing`이 되지 않는다.
- 1A30의 C 사슬은 펩타이드 3잔기(엔티티 2, `polypeptide(L)`)이고 M7이 단백질로 받는다.

---

## (b) `prepared_structure` 소비 지점 인벤토리

**방법:** `probe/consumers_inventory.py`(표준 라이브러리, AST + 문자열)로 찾았다. 출력은 `probe/out/consumers_inventory.txt`(74,441 B)다.
- 백엔드 138개 파일에서 지점 319곳, 함수 126개를 찾았고 미분류는 0이다.
- 함수 단위 분류: 상위에서 막힌 곳 41, 거절할 곳 38, 받는 곳 24, 무관 12, 읽기 전용 6, 판단 필요 5.
- 스크립트 안의 수동 분류표(`CLASSIFICATION`)에 없는 새 소비 지점은 `UNCLASSIFIED`로 드러난다. 같은 입력으로 두 번 돌려 출력 sha256 `6da43a29…`가 같았다.

**엄격한 manifest 검사: 해시 파일 안에는 없다.**
- 해시 파일 중 `preparation_manifest@1`을 읽는 곳은 `tools/openmm_method.py`의 115·117·120·127·213행뿐이다. 읽는 것은 `input`·`waters`·`hydrogens`·`source_handle`이고 키 집합 검사도 `missing_residues` 비교도 없다.
- 해시 파일의 나머지 지점은 `structure_kind == "prepared_structure"`만 본다: `mutation_candidates.py:561·893`, `mutation_model_math.py:313`, `sequence_ga_bundle.py:359`, `jobs/sequence_ga_worker.py:542`, `sequence_ga_jobs.py:543`(preflight 호출). 보완 구조도 같은 종류·스키마라 통과한다.
- 하위 조사에서 `repair` 키와 `modeled_internal_gaps`를 넣은 manifest로 M7·M20·M21 입장·선택이 통과했고, 이 문서의 (c)·(d)·(f) 실험도 같은 결과였다. `set(manifest)`·pydantic `extra=forbid`·재해시 검사는 `preparation_manifest`에 없다.
- **해시 파일 밖에서 깨지는 곳 하나:**
  - `workflows.py:37`이 요청의 `missing_residues`를 `Literal["leave_gaps"]`로 받는다.
  - 443–447행은 입력 handle의 manifest 정책 값이 요청과 다르면 `input_invalid`("prepared handle conflicts with missing_residues policy")를 낸다.
  - 그래서 `modeled_internal_gaps` 보완 구조는 `POST /runs/{rid}/inspect_complex`에서 실패한다. 반면 틈을 메우지 않은(`leave_gaps`) 보완 구조는 그대로 `compute_interactions`까지 간다. 이 라우트는 거절 대상이다(아래).

**분류 요약.** 지점별 전체 목록은 출력 1절에 있다.

| 범주 | 지점(입구 파일:줄) |
|---|---|
| 받는 곳 | M20 `tools/mutations.py:116`(`_admit`)·`:167`. 그 후보 집합을 쓰는 M21 `mutation_model_inputs.py:111`·`mutation_model_bundle.py:170,188,409`, M23 `sequence_ga_jobs.py:543` 등, M24 `tools/jev.py:112`·`jev_projection.py:651`, M25 `jev_loop_projection.py:390`·`jev_loops.py:215`·`jev_loop_store.py:894,1161`, M18 수용체 출처(변이 모델 경유). M7 `preflight`(해시)는 호출자에서 막는다. |
| 거절할 곳 | `compute_interactions`·`compute_interface_sasa`·`measure_distance`·`align_structures`·`compile_state`·`map_residue_numbering`·`link_reaction_knowledge`(`Run.call` 공용 입구 `runtime/orchestrator.py:597` `_validated_bound`, 또는 각 도구); `annotate_reference_sites`(`tools/site_annotation.py:41`, 번호 대응 거절로 실제로는 닿지 않음); M7 `GET /jobs/preflight`(`api/app.py:1472`)·`POST /jobs` `openmm_protein_minimize`(`jobs/queue.py:724`); M11 `chemical_inputs.py:295`(preview·작업·M13 경로를 한곳에서); M12 `pocket_input.py:93`(`_load_source`); 뷰어 세션 `viewer_intents.py:193`; 저장된 보기 `saved_scenes.py:263`; `/reports` `reports.py:333`; M13 계획 라우트 `api/app.py:742`; **명세 목록 밖** `POST /runs/{rid}/inspect_complex`(`api/app.py:1239`, 1256행 호출 앞). |
| 읽기 전용 | `GET /structures/residues`·`/structures/bytes`·`/structures/atoms`, `/reference/pdb_id_hint`(`api/app.py:2861·2906·2879·1646`) |
| 상위에서 막힌 곳 | M13 `analysis_plans.py`·`analysis_executions.py` 전체(계획 라우트), 결과별 보고서·검증 모듈(`reports.py`, `method_reports.py`, `openmm_bundle.py`, `openmm_reports.py`, `numbering_reports.py`, `site_annotation_reports.py`, `pocket_bundle.py`, `pocket_reports.py`, `comparison_reports.py` 등. 결과를 만드는 도구·작업에서 막힘), M27 `tools/kinase_precedents.py:110`(번호 대응만 받음) |
| 판단 필요 | 공용 도우미 `tools/structural.py:24`(`_parse`)·`:94`·`:111`, `tools/comparison.py:50,64`, `core/contracts.py:67`. 받는 곳과 읽기도 쓰므로 여기에 거절을 넣으면 안 된다. `/pockets/preflight`(`pocket_input.py:389–415`)는 거절을 422가 아니라 200 응답 안의 `reject`로 돌려주므로 응답 모양을 정해야 한다. |

**명세 §5.2와 다른 점**
1. `POST /runs/{rid}/inspect_complex`(`workflows.py`)는 M13이 아니고 계획 라우트로 막히지 않는다. 새 거절 대상이다.
2. `/pockets/preflight`의 응답 모양(200 + `reject`)을 정해야 한다.
3. PyRosetta `relax`·`interface_analyzer` 작업은 `POST /jobs`로 prepared_structure를 받는다. 지금은 `queue.py:722`의 `require_protocol`이 늘 412를 내서 실제 소비는 없다.
4. 뷰어: Mol*는 세션 없이 `/structures/bytes`(읽기)로 그린다. `frontend/app/page.tsx:431`의 `sourceOptions`가 모든 prepared_structure를 목록에 올리므로 프런트에서 보완 구조를 걸러야 R6("뷰어에 올리는 경로 없음")이 성립한다.
5. M20 화면의 구조 선택(`frontend/src/lib/mutations.ts:267`)은 `prepare_structure` 도구 출력만 고르므로 보완 구조를 더해야 한다(§8).
6. 뷰어 의도·그림은 각각 세션·저장된 보기 거절로 막히고, `/method_reports`의 해당 종류는 결과 handle만 받으므로 상위에서 막힌다.

---

## (c) 새 원자 표지 — 권고: `_atom_site.calc_flag = c`

**방법:** `probe/marker_and_preflight.py`(출력 `probe/out/marker_and_preflight.txt`)를 썼다.
- 8VF6을 제품 도구로 불러와 전처리한 throwaway run을 만들었다(두 물 정책).
- 저장된 전처리 좌표와 `probe/8vf6_additions.json`으로 보완 mmCIF 변형을 접합했다(`probe/splice_prototype.py`).
- 보완 객체는 run에 저장하지 않고 읽기 전용 보기(아래 (f) F1)로만 각 소비자에 넣었다.

| 변형 | 제품 `_parse`(gemmi; M7·M20·M24 경로) | OpenMM `PDBxFile` | PDBFixer 읽기 | 제품 M7 `preflight` | gemmi 읽기+쓰기 뒤 표지 | 판정 |
|---|---|---|---|---|---|---|
| `calc_flag`(새 원자 `c`, 나머지 `.`) | 통과, 266개 `Calculated` | 통과(원자 4,604/4,646, 사슬 4/6) | 통과(빠진 원자 0, 말단 꼬리 3묶음 4잔기만 보고) | 통과(4,538) | **남음** | **권고** |
| 별도 범주 `_protview_repair_added_atom` | 통과(표지 안 보임) | 통과 | 통과 | 통과 | **사라짐** | 비권고(비표준, gemmi로 다시 쓰면 잃음) |
| 둘째 data block(사이드카) | **실패: `input_invalid` "malformed structure"**(`sole_block()`) | 통과 | 통과 | 실패 | 실패 | 소비자를 깸, 불가 |
| 표지 없음(기록만) | 통과 | 통과 | 통과 | 통과 | — | 내려받은 파일에 기계 표지가 없음 |
| 점유율 0 | 시험 안 함 | | | | | 명세가 배제. 입력 1M17 37·1A4I 20개가 이미 0이라 구별 불가 |
| B-인자 표지 | 시험 안 함 | | | | | 물리 값을 덮어씀. 입력 값과 구별할 규칙이 없음 |

- `_atom_site.calc_flag`는 mmCIF 사전의 표준 항목이다(값 `d`·`calc`·`c`·`dum`).
- gemmi 0.7.5는 원자에 `CalcFlag.Calculated`가 하나라도 있으면 이 열을 쓰고(`c`/`.`) 다시 읽는다. 하나도 없으면 열을 쓰지 않는다.
- 로컬 입력 9개에는 이 열이 없다(`probe/out/input_marker_survey.txt`).
- M21 모델링은 M7 투영(원자 이름·원소·좌표)만 받으므로 표지와 무관하다. round4 + `calc_flag` 보완 구조로 M21 작업이 정상 종료했다(S1).
- **남은 결정 (T4):** 입력 mmCIF에 이미 `calc_flag` 값이 있는 원자가 있으면 표지가 모호해진다. 전처리가 gemmi로 다시 쓰면서 그 값을 옮기기 때문이다. 이때 거절할지, 값을 정규화할지, 기록만 정본으로 둘지 정해야 한다. 어느 쪽이든 정본은 보완 기록 `added_atoms`이고, 검증기는 "`c`인 원자 = `added_atoms`"를 양방향으로 확인하면 된다.

**함께 측정한 사실**
- gemmi mmCIF 쓰기는 `atom.serial`을 무시하고 `_atom_site.id`를 구조 순서대로 1..N으로 다시 매긴다. 그래서 조각 합치기와 원자 삽입 뒤 관측 원자의 id가 바뀐다(8VF6 strip_all 4,338개 중 4,333개). 원본 전처리도 gemmi로 쓰므로 id는 원래 원본 파일 id가 아니다. 명세 §3.2의 보존 항목에 id는 없지만 문서화가 필요하다.
- gemmi는 좌표를 유효숫자 9자리까지만 쓴다(`45.123456789012` → `45.1234568`). 전체 정밀도를 넣으려면 문서 셀을 직접 써야 한다. D1의 소수 넷째 자리 반올림을 쓰면 이 문제는 없다(|x| < 1e5 Å).
- round4 보완 구조에서 관측 원자 4,338개(strip)·4,380개(keep)의 좌표 차이는 0.0 Å였다. 잔기 7필드와 원자 이름이 모두 있다.

---

## (d) M20 인계 — `mutation_candidates.py` 변경 없이 가능

멈춤 조건이 아니다.

**구조 일치 검사는 해시 파일 밖에 있다.**
- 포켓·번호 대응·주석·촉매의 `structure_mismatch` 검사는 `backend/mw/tools/mutations.py:129–136`(`_admit`)에만 있다.
- 해시 파일 `mutation_candidates.py`의 `build_candidate_set`은 handle을 비교하지 않는다. `validated_set`은 저장 내용만 검사한다(모듈 docstring "The caller checks the handle's kind and run"; 880행 이후).
- M21·M23·M24·M25 입장 쪽(`mutation_model_inputs.py`, `sequence_ga_inputs.py`, `jev_projection.py`, `jev_loop_*`)은 번호 대응·주석의 구조를 다시 대조하지 않는다(grep).
- 다시 대조하는 곳은 M20 보고서 `mutation_reports.py`의 `check_sources`(235·245·257행)와 `_check_catalytic`(274행)이다. 둘 다 해시 파일 밖이고 T8 `@3`에서 고친다((e) 참고).

**실험 (`probe/m20_handoff.py` → `probe/out/m20_handoff.txt`):** 8VF6 throwaway run에서 원본 전처리 구조로 `compute_interactions`(A1AAY A), `map_residue_numbering`(8VF6, A·B=Q9BYT3, 로컬 `.deps/reference`), `annotate_reference_sites`를 만들고, 보완 구조(round4 + `calc_flag`)를 같은 throwaway run에 저장했다.
- **제품 도구 그대로:** 보완 구조 + 원본 기준 결과 → `input_invalid structure_mismatch`("the numbering map was made for another structure"). 거절 위치가 `tools/mutations.py`임을 확인했다.
- **해시 파일의 순수 함수를 직접 호출**(`normalize_request` → `build_candidate_set` → `validated_set`). `tools/mutations.py`의 구조 검사만 풀었을 때와 같다.
  - S1(리간드 껍질 5 Å, 8VF6 점검 요청과 같음): `validated_set` 통과. 위치 20·후보 247로 원본과 같다. `klifs_key_site` 제외 일곱(A145/LYS·A192/MET·A193/GLU·A194/LEU·A195/CYS·A264/THR·A265/ASP)이 원본과 같다. 관측 잔기에서 잃은 보호 이유 0.
  - S2(껍질 12 Å + 사용자 위치: 곁사슬 보완 잔기·OXT 잔기·틈 잔기 A280/LEU): 통과. 위치 86(원본 83). 보완 구조에만 있는 위치는 A280/LEU(사용자 지정)와 B283/THR·B284/CYS다. 뒤의 둘은 틈 잔기이고 모델링 원자 때문에 껍질에 들어왔다. `klifs_key_site` 열(원본과 같음), 잃은 보호 0.
- **틈 잔기 위치의 저장값:** `numbering.status = "not_in_map"`, `protection.klifs_sites = []`(검사함·해당 없음으로 저장), `catalytic = None`(이 실험에는 촉매 주석을 주지 않음. 덮인 체인이면 `[]`). 명세 §5.3이 말한 대로 저장값으로는 "검사 안 함"이 보이지 않는다. 읽기 계층(`mutation_reads.py`, 해시 파일 아님)이 보완 기록의 틈·치환 잔기 목록으로 덮어 보이는 것은 구조상 가능하다(위치 행에 잔기 7필드가 있음).
- **`modeled_basis`는 저장 데이터만으로 재현된다.** 보완 구조 바이트에서 `calc_flag = c` 원자(= `added_atoms`)를 뺀 관측 원자만으로 `mutation_candidates._walk`·`_min_distance`(읽기만)를 다시 돌려 껍질·금속·이황화 판정을 비교했다.
  - S1: 참 0.
  - S2: 참 5. A100/LYS·A280/LEU·A382/THR은 잔기에 모델링 원자가 있음. B283/THR은 그것 + 껍질 판정이 모델링 원자에 의존. B284/CYS는 그것 + 껍질 + SG 자체가 모델링 원자.
  - 8VF6에는 금속이 없어 금속 3.0 Å 재판정은 실제 사례로 확인하지 못했다. 규칙은 같은 함수(`_min_distance(entry["heavy"], metal["all"]) <= threshold`)라 재현 가능하다고 판단한다(추정).

**측정하지 못한 것**
- 포켓 출처: fpocket 작업이 필요하다. 코드상 `pocket_lining`이 7필드로 대조하므로 관측 잔기는 통과하고, MSE→MET 치환 잔기가 lining에 있으면 `pocket_residue_mismatch`다.
- 촉매(M26): `.deps/reaction_reference`가 없다. 코드상 `_admit` 135행과 `catalytic_protection`의 7필드 대조로 같은 방식이다.
- MSE: 로컬에 없다.

---

## (e) 보고서

출처: 하위 조사(file:line 대조, 일부를 다시 확인함).

| 종류 | 파일 | 현재 렌더 버전 | `## Limitations` 줄 | 버전 분기 | 해시 파일 | 새 버전 이름(제안) |
|---|---|---|---|---|---|---|
| M20 변이 후보 | `mutation_reports.py` | `mutation_candidates_markdown@1`·`@2`(83–84) | 688 | 있음(`MANIFEST_KEYS_BY_VERSION` 159–163, `_expected` 525–539, 다시 열기 803–808) | 아님 | `mutation_candidates_markdown@3` |
| M21 변이 모델 | `mutation_model_reports.py` | `mutation_model_markdown@1`(50) | 370 | 없음(262 고정, 417–419) | 아님 | `mutation_model_markdown@2` |
| M24 JEV 판정 | `jev_reports.py` | `jev_choice_markdown@1`(42) | 333 | 없음. `kind`로 렌더가 갈리므로 변이 종류만 올릴 수 있음 | 아님 | `jev_choice_markdown@2`(변이만) |
| M25 루프 | `jev_loop_reports.py` | `jev_loop_markdown@1`(`jev_loop_constants.py:68` `REPORT_RENDER`) | 465 | 없음. `branch`로 단백질만 가능 | 아님 | `jev_loop_markdown@2`(단백질만). 기존 상수는 시험이 `@1`로 고정하므로 새 상수를 더함 |
| M18 도킹 | `docking_reports.py` | `ligand_docking_markdown@1`(52) | 473 | 없음(337, 519–521) | 아님(단 `docking_constants.py`는 해시) | `ligand_docking_markdown@2` |

- `sequence_ga_reports.py`·`sequence_ga_reads.py`는 `BASELINE_BLOBS`에 있다(`backend/tests/test_kinase_precedents_ast.py:282–283`). 확인했다.
- M23 읽기 함수는 dict를 돌려주고 `app.py`가 `{**…, "meta": meta}`로 감싼다(상세 2419–2429, 목록 2353–2363, 개체 2383–2397). 응답 계층에서 `structure_origin`을 더할 수 있다.
- **골든:** `golden_science_m24.py`는 보완하지 않은 1UBQ v1 후보 집합으로 투영·`/jev/*` 응답·`jev_choice` 보고서·이벤트를 고정한다. `prototype_golden_egress.py`는 게이트 이벤트 모양, `prototype_golden_call_keys.py`는 호출 키와 해시만 고정한다. 후보 집합·변이 모델·서열 GA·M18·루프 읽기 응답을 바이트로 고정한 골든은 없다. 그래서 "보완 구조일 때만 필드 추가"는 골든을 바꾸지 않는다고 판단한다(골든은 실행하지 않음. 실행하면 저장소 안 `_work_golden`에 쓰거나 기본값이 골든 파일 덮어쓰기라서).
- 응답 키 집합을 정확히 비교하는 기존 시험도 보완 구조가 아니면 그대로다: `test_mutation_api.py:178·498·508`, `test_mutation_model_api.py:107·139`, `test_sequence_ga_api.py:275–278·297·369`, `test_jev_api.py:132·143·325`, `test_jev_loop_sends.py:266…`, `test_jev_loops_read.py:335·417·510` 등.

**T8에 미치는 영향**
1. M20 `@3`의 `check_sources`·`_check_catalytic`이 같은 구조를 요구하므로 `@3`에서만 `repair.source`를 허용해야 한다(`@1`·`@2`는 그대로).
2. `@3`의 키 집합 규칙(`reference_snapshot_sets` 필수 여부, 538·684행)을 정해야 한다.
3. M21 보고서의 `DIFFERENCE` 정규식(80·219행)이 주장 이름·경로에 걸린다. `change`가 "unchanged"에도 걸리므로 보완 기록 필드 경로(예: `unchanged.atom_count`)를 인용하면 거절된다.
4. `docking_reports`의 공용 상수는 해시 파일 셋(`sequence_ga_reports.py` 등)이 쓰므로 하나도 바꾸면 안 된다.
5. M18 수용체 출처 `kind: "mutation_model"`은 M23 서열 모델일 수도 있다(`docking_bundle.py:274–293`). 명세는 M21만 말하므로 정해야 한다.
6. `test_mutation_reports.py:893`은 `@3`으로 위조한 보고서를 422로 기대한다. 그래서 `@3`은 보완 구조가 아니면 거절해야 한다.
7. `test_ligand_api.py:420`이 `/capabilities`의 `methods` 키 집합을 고정하므로 `methods.structure_repair` 추가 때 함께 고친다.
8. 새 `structure_origin` 모듈은 순수 함수만 둔다. `jev_sends` 임포터 셋 고정(`test_jev_ast.py:94–97`), 루프·읽기 모듈의 import 제약(`test_jev_loop_reports.py:693–697`) 때문이다.
9. 명세 §6.3의 "M23 보고서가 인용하는 M20 `@3` 보고서"는 정확하지 않다. M23 보고서는 후보 집합 handle과 구조 handle을 인용한다(`sequence_ga_reports.py:185–190`).

---

## (f) 게시 전 M7 사전 검사 — 권고: F1 읽기 전용 겹침 보기

**방법:** `probe/marker_and_preflight.py`의 (f) 절. handle은 내용 해시(`obj://<run>/<kind>/<sha256(kind\0schema\0raw)>`)라 저장하지 않고도 미리 계산할 수 있다.

| 방법 | 내용 | 결과(보완 8VF6 round4) | 결과(일부러 깬 변형: A100 NZ 뺌) | 원래 run 이벤트/객체 | 시간 |
|---|---|---|---|---|---|
| F1 겹침 보기 | 기존 store + 메모리의 보완 좌표·manifest·구조(`meta`·`load`만 제공) | pass, 다이제스트 `9c90cc19…` | `heavy_template_mismatch` A/100/LYS | 21/8 → 21/8 (변화 없음) | 2.43초 |
| F2 임시 ObjectStore | 같은 run id의 임시 store에 입력 둘(구조 선택·원본 바이트)을 복사하고 보완 객체를 넣은 뒤 지움 | pass, `9c90cc19…` | 같은 실패 | 변화 없음 | 2.67초 |
| F3 실제 저장(참조) | 같은 run id로 다른 root에 실제로 저장 | pass, `9c90cc19…` | 같은 실패 | — | — |
| F4 저장 후 검사 | F3에서 `put` 셋 | — | — | **이벤트 3·객체 3이 즉시 생김**(실패해도 남음 = 고아) | — |

- F1·F2·F3의 결과가 바이트로 같다(성공은 정규 JSON 다이제스트, 실패는 같은 분류·이유·잔기). F4는 `ObjectStore.put`이 `object_created` 이벤트를 바로 추가하므로 "실패 시 새 객체 0"을 지킬 수 없다.
- **권고: F1.** 쓰기가 전혀 없고, 해시 파일 `openmm_method.preflight`를 그대로 부른다. `preflight`가 store에 쓰는 것은 `meta(handle)["kind"|"schema"|"fmt"]`와 `load(handle)`뿐이고 `_parse`도 같다.
- 시험에서는 F1 결과가 F3(실제 저장 뒤)와 같음을 대조하면 된다.
- F2는 임시 폴더 정리와 원본 바이트 복사(8VF6 0.9 MB)가 필요해 더 무겁다.

---

## (g) PDBFixer 측정과 M21·M18

**방법:** `probe/pdbfixer_measure.py`. 제품 코드 없이 PDBFixer를 직접 쓴다.
- 단백질만, 저자 체인별로 조각을 합친 M21식 PDBx 텍스트를 쓰고 `platform=CPU Threads=1`로 돌린다.
- `missingResidues`는 미관측 목록에서 직접 설정한다. PDBFixer `findMissingResidues`는 저자 번호와 label 체인 id로 서열을 맞추므로 쓰지 않는다.
- 그다음 `findMissingAtoms` → `addMissingAtoms(seed)` 순서다.

출력: `probe/out/pdbfixer_measure.txt`.

**결정성과 관측 원자**
- **시드 재현성:** 같은 입력·시드 1로 프로세스를 나눠 두 번 돌리면 결과가 바이트로 같았다. 8VF6은 측정 전체(시간 제외) 정규 JSON이 같았다. 다섯 구조는 `added_atoms` sha256이 같았다(1M17 `0da65de5…`, 1MQ4 `32641b83…`, 1A30 `4dd732d3…`, 1A4I `28d2fa86…`, 1HSG `969d19e4…`, 8VF6 `8767389f…`).
- **시드 2:** 8VF6의 새 원자 266개가 **모두** 바뀌었다(최대 9.875 Å, 곁사슬 최대 6.52 Å, OXT 2.50 Å). 새 원자 전체를 함께 최소화하고 충돌 시 Langevin 단계를 돌리기 때문이다. 곁사슬 좌표도 틈 메우기와 함께 정해진다. `REPAIR_SEED = 1` 고정이 필요하다는 근거다.
- **물 정책 무관:** PDBFixer에 단백질만 넣으므로 8VF6 strip_all과 keep_all의 결과가 같다(`water_policy_independent: true`).
- **관측 원자 이식:** PDBFixer 출력의 관측 원자 이동은 최대 1.07e-14 Å(8VF6), 1.74e-14 Å(1MQ4)로 nm 왕복 오차다. 틈 양옆 잔기도 포함한다. 1e-9 Å 이식이 가능하다.
- **추가 원자 내용:** 모든 구조에서 추가 원자 = 템플릿 기대(곁사슬·OXT)였고, 틈 잔기 원자 = 템플릿 중원자였다. 수소는 0개 추가됐다.
- **펩티드 결합:** 틈을 메운 뒤 C–N이 모두 M7 범위 1.1–1.7 Å 안이었다(8VF6 1.290–1.431 Å). 이 구조들에서는 `repair_incomplete`(peptide_geometry)가 나지 않았다.

**PDBFixer 시간 (`addMissingAtoms`, 시드 1)**

| 구조 | 시간(초) | 추가 원자 | 추가 잔기 | 단백질 충돌 최소(Å, < 2.0 / < 1.5 개수) |
|---|---:|---:|---:|---|
| 8VF6 | 22.9–23.1 | 266 | 24 | 1.580 (2 / 0) |
| 1M17 | 4.93–4.96 | 97 | 12 | 1.484 (6 / 2) |
| 1MQ4 | 2.69–2.70 | 55 | 2 | 1.404 (5 / 2) |
| 1A30 | 0.07 | 6 | 0 | 3.912 (0 / 0) |
| 1A4I | 7.78–7.81 | 80 | 10 | 1.310 (5 / 2) |
| 1HSG | 0.07 | 2 | 0 | 4.237 (0 / 0) |

- 8VF6 새 원자와 리간드·물의 최소 거리(keep_all 상대)는 리간드 9.60 Å, 물 3.29 Å이고 금속은 없다.
- 점검용 spike(기본 플랫폼, `findMissingResidues` 방식)의 1.36 Å와는 다르다. 플랫폼과 틈 지정 방식이 다르기 때문이다.

**M21 작업 하나의 단독 시간**
- S1 표 그대로다. 8VF6 1,035초 > 240초.
- 1HSG는 기본 120초 안(118초), 1A30(123초)·1MQ4(233초)는 `timeout_s`를 240으로 줘야 한다. 1M17·1A4I·8VF6은 240초를 넘는다.

**M18 수용체 원자 수 (수소 포함, 상한 10,000)**

| 구조 | 변이형 | 야생형 참조 |
|---|---:|---:|
| 8VF6 | 9,143(수소 4,608) | 9,152 |
| 1MQ4 | 4,319 | 4,328 |
| 1M17 | 5,204 | 5,213 |
| 1A4I | 9,049(수소 4,576) | 9,058 |
| 1HSG | 3,119 | 3,128 |
| 1A30 | 3,178 | 3,187 |

- 8VF6은 상한 안이고 여유는 857이다. 멈춤 사유가 아닌 보고 항목이다.
- M18 상자 출처 호환은 측정하지 않았다.

---

## (h) 간헐 실패 시험의 원인

하위 조사(코드 읽기, 재현 실행 없음). `--collect-only`로 Stop 훅 12번째 그룹 419개를 확인했다.

**실패 경로**
- `backend/tests/test_sequence_ga_worker.py:1103–1131` `_held_step`은 표지(`model_work/qvina/ligand.pdbqt`)를 본 뒤 그룹에 SIGSTOP을 두 번 보내고 qvina2를 찾는다. 찾은 qvina2의 CPU 시간이 0.05초 미만이면 **그룹 전체에 SIGCONT를 보내고**(1129) 10 ms를 잔 뒤 다시 반복한다.
- 그 재개 구간마다 qvina2가 자유롭게 돈다. 재개 구간 길이에는 상한이 없다. 부하가 크면 0.05초에 닿기까지 재개 횟수가 늘고, 한 구간이라도 qvina2가 남은 시간을 넘기면 개체 0의 도킹이 붙잡히기 전에 끝난다.
- 그러면 다음 반복이 개체 1의 qvina2를 잡고, 1127행 검사가 `0.status.json`을 보고 "individual 0 ended before it was held"를 낸다.
- 구조는 코드로 확인했다. 구간 길이와 횟수는 추정이다.
- 작업 모듈 쪽 순서(`docking_worker.py:1168` 표지 → 1176 `run_qvina`, `sequence_ga_worker.py:912·928`)도 코드로 확인했다.
- fork 중 SIGSTOP 놓침과 신호 전달 지연은 원인이 아니다(코드로 확인).

**같은 기법의 다른 시험**
- `test_pocket_jobs.py:802–830` `_held_engine`: 같은 기법이고 CPU 조건이 없다. 첫 발견 전 재개 구간만 남는다.
- "보고 나서 신호" 방식(M28 이전): `test_docking_batch_worker.py:307–345`, `test_ligand_ga_worker.py:563–590`, `test_docking_jobs.py:647–720`, `test_openmm.py:653–672`.
- `test_pocket_jobs.py:927–957`은 fpocket이 먼저 끝나면 그냥 통과한다. 실패가 아니라 검증 공백이다.
- `SystemError` 미처리(M28이 `_engines_under`만 고침): `test_docking_batch_worker.py:155–159`, `test_ligand_ga_worker.py:240–244`, `test_sequence_ga_jobs.py:173–177`, `test_docking_batch_jobs.py:168–172`.
- 부분 문자열 검사 잔존: `test_jev_api.py:160–161`, `test_jev_loop_reports.py:384`.

**수정 후보 (시험만)**
1. qvina2를 처음 찾으면 바로 붙잡고 작업 프로세스만 재개한다. 원인을 직접 제거하므로 권고한다. `_blocked`의 굶주림 오판을 막는 보강이 필요하다.
2. 범위 안의 시험 입력으로 qvina2를 길게 만든다. 여유만 늘리므로 1번과 함께, 측정값을 기록할 때만 쓴다.
3. 놓치면 다음 개체로 넘어간다. 숨기기가 되므로 비권고.

진단 출력(재개 구간 길이, 각 반복의 qvina2 pid·CPU 시간, `0.status.json` 내용)을 함께 더할 것을 권한다.

**재현 비용**
- 실제 시험을 18그룹 배경 부하에서 반복하면 1회 약 145초 이상이다. 실패율 10%를 가정하면(추정) 90% 확률로 한 번 보는 데 약 22회, 약 2.2시간이 든다.
- 그래서 개체 0의 qvina 입력으로 붙잡기 알고리즘만 흉내 내는 미세 재현(시도당 1–3초)을 먼저 할 것을 권한다.
- 게이트(18그룹 연속 3회)는 약 16–20분이다.

---

## (i) RCSB 구조 ID 후보 (외부 조회 없음, 사용자 승인 전용)

S1 때문에 기준을 하나 더 둔다: **보완 뒤 단백질 중원자 약 2,100 이하**(M21 240초 안, 측정 1MQ4 2,160이 233초), 가능하면 약 1,500 이하(기본 120초 안). 아래 성질은 모두 기억에 따른 것이고, "미확인"은 받기 전에 확인하지 못했다는 뜻이다.

| ID | 고른 이유 | 확인 상태 |
|---|---|---|
| 1RNH | 대장균 RNase HI의 셀레노메티오닌 MAD 구조(1990)로 알려짐. MSE→MET 규칙 시험용. 단일 사슬 약 155잔기(추정 중원자 약 1,250), 비키나아제 | MSE 표기·틈·곁사슬 결손 모두 미확인 |
| 4INS | 돼지 인슐린 2-Zn 결정. 두 엔티티(A 21·B 30잔기)가 다른 체인 이름으로 둘씩 있는 다량체. Zn(금속 보호), 이황화 셋/분자(이황화 보호). 비키나아제, 작음(추정 약 800) | 결손·altloc·틈 미확인 |
| 1AY7 | RNase Sa–barstar 이종 복합체로 기억함. 서로 다른 두 단백질, 비키나아제, 약 185잔기(추정 약 1,450) | 복합체 정체·결손·틈 미확인 |
| 1CLL | Ca²⁺ 결합 칼모듈린(148잔기, 금속 넷). 비키나아제, 작음(추정 약 1,150) | 곁사슬 결손·틈 미확인. 긴 틈 기준을 만족하는지 모름 |

- "긴 틈(10–20잔기) + 작은 크기"를 함께 만족하는 구조는 알려진 정보로 확정하지 못했다.
- 로컬에서는 긴 틈이 8VF6(13·11)·1M17(12)·1A4I(10)에 있지만 모두 M21 240초를 넘는다(S1).
- MSE 구조를 얻지 못하면 명세대로 1UBQ MET→MSE 합성 표시 자료를 쓴다. MSE는 PDBFixer의 `replaceNonstandardResidues`에 맡기면 SD를 템플릿 위치에 새로 놓으므로(SE 좌표 보존 불가) T4·T5가 PDBFixer 전에 이름을 직접 바꿔야 한다.

---

## (j) 8VF6 추가 원자 목록 고정 자료

`probe/8vf6_additions.json` — **PDBFixer 측정 고정 자료(제품 값 아님)**. 메타 `label`에 이 문구가 있고 `schema` 값은 `m29_t1_pdbfixer_measured_additions@1`이다.
- 크기 105,818 B(256 KiB·4 MB 이하), sha256 `9f1234b897cfac9ef05537dad3fcd8d188dd2254f6384ac75719be4cd33721dd`.
- 만든 명령: `.venv/bin/python docs/qa/m29-repair-20261013/probe/pdbfixer_measure.py additions runs/stk33-8vf6-20261013/8VF6.cif --out docs/qa/m29-repair-20261013/probe/8vf6_additions.json`
- 내용: `added_atoms` 266(곁사슬 91, OXT 2, 틈 잔기 173; 잔기 7필드·원자 이름·원소·좌표 Å·origin, 구조 순서, PDBFixer 원정밀도), `gaps` 2(`after_residue`·`before_residue`·`length`·`residues[7필드]`), `side_chain_repairs` 23, `terminal_oxt` 2, `counts`, `observed_max_delta_A` 1.07e-14, 충돌, 펩티드 결합, 입력 sha256·크기, 절차, `water_policy_independent: true`.
- **틈 잔기 식별자는 원본 `structure_source` 바이트(= 8VF6.cif)의 `_pdbx_unobs_or_zero_occ_residues`에서 왔다. 서열 이름은 `_entity_poly_seq`와 대조했다.** 결과: A 273–285(label 176–188, chain_label A, `GSASGAMLGATCG`), B 274–284(label 177–187, chain_label B, `SASGAMLGATC`). 삽입 코드는 모두 빈 문자열이다.
- 좌표는 원정밀도이고, 보완 구조에 넣을 때는 D1대로 소수 넷째 자리로 반올림해야 M21이 돈다.

---

## (k) 정보 위치

`probe/info_location.py` → `probe/out/info_location.txt`. 제품 도구로 load·prepare했다.

**mmCIF 입력(8VF6·1M17, 두 물 정책)**
- 원본 `structure_source`는 입력 바이트와 같고 `_entity_poly_seq`(286/333행)·`_pdbx_unobs_or_zero_occ_residues`(28/22)·`_pdbx_unobs_or_zero_occ_atoms`·`_pdbx_poly_seq_scheme`이 있다.
- 전처리 mmCIF(`prepared_coordinates`)에는 `_entity_poly_seq`만 남는다. `_pdbx_unobs_or_zero_occ_residues`·`_atoms`·`_pdbx_poly_seq_scheme`은 0행이다.
- 전처리 manifest의 `source_handle`은 `structure_source` 종류다. 틈 잔기 목록은 그 원본 바이트에서 읽어야 한다(명세 §2.3과 같음).
- manifest 키는 `altloc, altloc_choices, hydrogens, input, missing_residues, model_index, model_number, protonation, removed, source_handle, symmetry_mates, waters` 12개다.

**PDB 형식 입력(8VF6을 gemmi로 PDB 텍스트로 쓴 것)**
- 제품 `_parse`의 `label_seq`는 544/544 None이다.
- gemmi PDB 쓰기는 SEQRES 44줄을 쓰고 REMARK 465는 쓰지 않는다. 전처리 PDB에도 REMARK 465가 없다. 실제 PDB 파일의 REMARK 465도 원본 바이트에서 읽어야 한다(gemmi는 `raw_remarks`로만 보존. 로컬에 REMARK 465가 있는 PDB fixture가 없어 실제 파일로는 시험하지 못함).
- `chain_label`은 D2 참고.

**틈의 정의**
- mmCIF: 연속한 폴리머 잔기의 label 번호가 1보다 크게 건너뛰는 곳(M7 `sequence_gap` 기준).
- PDB 형식: label이 없어 M7은 틈을 C–N 거리로만 본다. 8VF6을 PDB로 쓰면 `A/272→286 C–N 19.33 Å`, `B/273→285 C–N 12.75 Å`이고, M7은 `peptide_geometry`로 거절한다.
- 그래서 PDB 형식의 틈은 "C–N 거리가 1.1–1.7 Å 밖인 연속 폴리머 잔기 쌍 + 그 사이를 채우는 REMARK 465 행(저자 번호·삽입 코드 순서)과 SEQRES 이름 일치"로 정의해야 한다. 목록이 없거나 맞지 않으면 `gap_listing_missing`이다.
- 거리만 어긋나고 저자 번호가 이어진 쌍(진짜 사슬 끊김)은 `m7_condition_unsupported(peptide_geometry)`다.

---

## 계획(T2–T11)에 미치는 영향

- **T2:** (h)의 후보 1(즉시 붙잡기 + 작업 프로세스만 재개)과 진단 출력을 권한다. 같은 기법 시험 `test_pocket_jobs.py:802–830`, 보고-후-신호 시험 넷, `SystemError` 미처리 넷, 부분 문자열 검사 둘을 같은 방식으로 검토한다.
- **T3a:** `probe/8vf6_additions.json`을 `backend/tests/fixtures/structure_repair/8vf6-additions.pdbfixer-measured.json`으로 복사한다. 좌표는 원정밀도이므로 접합 빌더가 D1의 반올림을 한다.
- **T3b:** (i)의 크기 기준을 더한다.
- **T4:**
  - 접합 빌더는 새 원자 좌표를 소수 넷째 자리로 반올림한다(D1).
  - gemmi 쓰기가 `_atom_site.id`를 다시 매기고 유효숫자 9자리로 쓰는 점을 반영한다.
  - 표지는 `calc_flag = c`이고, 입력에 이미 `calc_flag`가 있을 때의 규칙을 정한다.
  - PDBFixer `missingResidues`는 직접 설정한다.
  - MSE는 PDBFixer 전에 직접 바꾼다.
  - PDB 형식 `chain_label`(D2)과 틈 정의((k))를 정한다.
  - 분류 결과는 (a) 표와 맞아야 한다.
- **T5:**
  - 게시 전 M7은 F1(겹침 보기)로 한다.
  - 작업 모듈은 `platform=CPU Threads=1`, 시드 1로 돈다. 8VF6 PDBFixer는 약 23초라 기본 120초 안에 든다.
  - `findMissingResidues` 대신 분석 결과로 `missingResidues`를 넣는다.
  - `test_ligand_api.py:420`을 함께 고친다.
- **T6:** 거절 입구는 (b) 표를 따른다. `inspect_complex` 라우트를 추가하고 `/pockets/preflight` 응답 모양을 정한다. 프런트 `page.tsx:431`에서 보완 구조를 거른다.
- **T7:** `tools/mutations.py:129–136`만 고친다(해시 파일 불변). 읽기 덮어쓰기 대상의 저장값은 `numbering.status = not_in_map`, `klifs_sites = []`, `catalytic = []|None`이다. `modeled_basis`는 `calc_flag`/`added_atoms`를 뺀 관측 원자로 `_walk`·`_min_distance`를 다시 돌려 계산한다.
- **T8:** (e)의 아홉 항목.
- **T11·T15:** S1의 결정에 따라 R1·R4·R5의 통과 정의를 바꿔야 한다. 8VF6 M18 수용체 9,143원자는 상한 안이지만 M21 자체가 240초를 넘으므로 R4 도킹까지 가지 못한다.

## 새로 알게 된 위험 (명세·계획에 없던 것)

1. M21 시간은 단백질 중원자 수의 대략 제곱으로 늘어나 2,100 근처에서 240초에 닿는다(S1). 8VF6 같은 이량체 키나아제는 보완해도 M21·M23·M25 단백질 루프·수용체 출처 도킹을 상한 안에 마칠 수 없다.
2. 새 원자 좌표의 정밀도가 M21 `_graft`를 깬다(D1). 명세 문구 "반올림하지 않는다"와 충돌한다.
3. gemmi가 `_atom_site.id`를 다시 매기고 유효숫자 9자리로 쓴다((c)).
4. PDBFixer 시드를 바꾸면 곁사슬·OXT를 포함한 새 원자가 전부 바뀐다(최대 9.9 Å). 곁사슬 좌표가 틈 메우기와 결합되어 있다((g)).
5. 1FIN은 조각을 합쳐도 원자 상한에 걸린다(D3).
6. PDB 형식 입력의 `chain_label`은 gemmi 합성 이름일 수 있다(D2). 전처리 PDB에는 REMARK 465가 없다((k)).
7. `POST /inspect_complex`는 명세 거절 목록 밖이고, `modeled_internal_gaps`가 아니면 보완 구조를 받아 계산한다((b)).
8. M20 틈 잔기가 모델링 원자만으로 리간드 껍질에 들어올 수 있다(8VF6 12 Å에서 B283·B284). 저장값은 `not_in_map`·`[]`다((d)).
9. M18 수용체 출처가 M23 서열 모델일 수 있다((e) 5).
10. 1HSG M21은 기본 120초에 겨우 들어간다(118초). 부하가 크면 기본 시간 초과 위험이 있다(추정).
11. MSE를 PDBFixer 표준 치환에 맡기면 SE 좌표가 보존되지 않는다((i)).

## 산출물

모두 이 폴더 아래에 있고 텍스트만이며 256 KiB 이하다. 사용자 절대 경로·키·kbase 문구는 없다.

| 파일 | 내용 |
|---|---|
| `preflight.md` | 이 문서 |
| `probe/classify_structures.py` | (a) 독립 분류(gemmi + 템플릿 XML만) |
| `probe/consumers_inventory.py` | (b) 소비 지점 인벤토리(표준 라이브러리) |
| `probe/netguard.py` | 비-loopback 연결 차단·계수 도우미 |
| `probe/splice_prototype.py` | 보완 mmCIF 접합 프로토타입(gemmi) |
| `probe/marker_and_preflight.py` | (c) 표지 후보 × 소비자, (f) 게시 전 M7 방법 |
| `probe/input_marker_survey.py` | (c) 입력의 `calc_flag`·점유율 0·B 0·소수 자릿수 |
| `probe/pdbfixer_measure.py` | (g)(j) PDBFixer 측정과 고정 자료 생성 |
| `probe/m21_on_repaired.py` | (g) 보완 구조 M21 작업 시간·M18 원자 수 |
| `probe/m20_handoff.py` | (d) M20 인계 실험 |
| `probe/crosscheck_m7.py` | (a) 제품 M7 교차 확인 |
| `probe/info_location.py` | (k) 정보 위치 |
| `probe/8vf6_additions.json` | (j) PDBFixer 측정 고정 자료(제품 값 아님) |
| `probe/out/*.txt`, `probe/out/classification.json` | 위 스크립트의 출력 |
