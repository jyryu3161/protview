# 결정 기록

| 번호 | 결정 | 상태 |
|---|---|---|
| [0001](0001-opus-subagent-roles.md) | Opus 5.5 서브에이전트로 조율·구현·검토 분리 | 채택 |
| [0002](0002-new-work-flow-legacy-runner.md) | 새 작업은 ready→go, 기존 단계 실행기는 과거 검증 전용 | 채택 |
| [0003](0003-system-architecture-filename.md) | 새 시스템 구성 문서를 `system-architecture.md`로 (대소문자 충돌 회피) | 채택 |
| [0004](0004-events-carry-full-payloads.md) | 이벤트가 객체 전체 payload를 담는다 | 채택 |
| [0005](0005-local-only-single-egress.md) | 기본 로컬 전용, 단일 외부 게이트, 동의 시 뷰어 프롬프트만 | 채택 |
| [0006](0006-no-pyrosetta-alternative-methods.md) | PyRosetta는 사용 불가, FreeSASA·OpenMM을 별도 이름으로 | 채택 |
| [0007](0007-freesasa-lee-richards.md) | FreeSASA Lee–Richards 100 slices 고정 | 채택 |
| [0008](0008-isolated-prolif-worker.md) | ProLIF를 해시 잠금된 별도 인터프리터로 | 채택 |
| [0009](0009-electron-offscreen-qa.md) | UI 수락 검증은 Electron 오프스크린 렌더러로 | 채택 |
| [0010](0010-honest-git-history.md) | Git 기록을 소급해서 만들지 않는다 | 채택 |
| [0011](0011-single-user-no-auth.md) | 인스턴스당 한 사람, 인증 없음, loopback | 채택 |
| [0012](0012-live-model-calls-need-cap.md) | 실제 모델 호출은 매번 사용자가 횟수를 정한다 | 채택 |
| [0013](0013-host-allowlist.md) | Host 허용 목록을 백엔드·프런트엔드 두 곳에, 중복 Host는 알려진 한계 | 채택 |
| [0014](0014-m11-acceptance-record.md) | M11 완료는 새 흐름 문서에 기록, 옛 단계 기록은 pending | 채택 |
| [0015](0015-scientific-data-egress-allowed.md) | 구조·좌표·서열·리간드의 외부 모델(JEV 등) 전송 허용, 단일 게이트·키 보호 유지 | 채택 (0005 일부 대체) |
| [0016](0016-m12-acceptance-record.md) | M12 완료는 새 흐름 문서에 기록, `phases/protview-pockets`는 그대로 | 채택 |
| [0017](0017-fpocket-locked-conda-install.md) | fpocket을 해시 잠금 conda 환경(`.deps/fpocket/env`)으로 격리 설치 | 채택 |
| [0018](0018-m13-acceptance-record.md) | M13 완료는 새 흐름 문서에 기록, `phases/protview-workflows`는 그대로 | 채택 |
| [0019](0019-analysis-plan-size-1mib.md) | 분석 계획 크기 한도 1 MiB(계약의 64 KiB 대체), 입력은 한 번만 저장 | 채택 |
| [0020](0020-compact-committed-qa-evidence.md) | 커밋 QA 증거는 작은 텍스트만, 큰 증거는 해시와 함께 Git 제외 폴더로 | 채택 |
| [0021](0021-m14-minimal-shared-components.md) | M14는 현재 run·예산·보고서 목록만 공용화, 소스·보기·작업 공용화는 필요한 탭 단계로 | 채택 |
| [0022](0022-kbase-ref-processed-snapshots.md) | `kbase_kinase/ref` 가공 스냅샷은 가져오기 명령으로 로컬 참조 폴더에 복사해 서버가 읽는다(코드 import·`dist/`는 여전히 금지, "kbase_kinase 가공본" 표시) | 채택 (`docs/standards.md` kbase 문장 좁힘) |
| [0023](0023-m15-residue-numbering-rules.md) | M15 번호 대응: SIFTS + 로컬 정렬이 같을 때만 대응됨, 한쪽만이면 충돌, 90%·50% 기준, 모호한 정렬 위치는 대응 없음, KLIFS 구역별 유일 배치, KLIFS none-stated 표시하되 사용 제한 없음 | 채택 |
| [0024](0024-m16-reference-site-annotations.md) | M16 참조 주석: KLIFS 주요 부위 10개 고정, 같은 구조 handle에만, 기하 접촉만(극성 점선 + 저장 거리), 새 불변 결과 `reference_site_annotation@1`, `viewer_scene@2`·범례 기본 켬, 포켓 오버레이·M8 자연어와 배타, 그림 상한 유지, 사용자 지정 잔기 제외 | 채택 |
| [0025](0025-m17-ligand-candidate-generation.md) | M17 리간드 후보: 고정 교체 `replace_single_bond_v1` + 사용자 반응 SMARTS(반응물 2개, 부위 안에서만), 단일 결합 하나로 이어진 부위(링커 제외), V2000 부모 1레코드·허용 원소 H C N O S P F Cl Br I·수소 그대로, block SDF·SMILES, 후보 모두 보관·필터는 저장값에 화면·보고서에서 적용, 점검·생성 두 작업(각 승인·예산 1단위), 코어 입체 유지·새 중심 미지정, 상한 block 1,000·후보 2,000·시도 20,000·입력 10 MiB, 후보 2D 전용, 보고서 `ligand_candidates` | 채택 |
| [0026](0026-m18-single-ligand-docking.md) | M18 단일 리간드 도킹: 엔진은 격리된 qvina 2.1(conda-forge 2.1.0)만(Vina·smina·gnina 제외), 점수는 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"·"모드 n(엔진 출력 순서)"·"샘플 n(점수 오름차순 나열)", 리간드는 3D SDF와 M17 후보, 상자는 리간드 범위·수용체 안 인스턴스 범위·직접 입력, 접촉은 기하 접촉만, 뷰어 표시 없음, 수용체는 M11 규칙·인스턴스 하나만 빼고 나머지 비표준 요소 거부, 코어 고정은 구속 샘플 + `--score_only`만(코어 좌표 덮어쓰기), seed 직접·CPU 1, 새 격리 환경 둘(qvina conda, RDKit·Meeko·MDAnalysis), 보고서 `ligand_docking` | 채택 |
| [0027](0027-m19-batch-docking.md) | M19 후보 일괄 도킹: 작업 하나(`qvina_batch_dock_v1`)가 새로 계산하는 행마다 1단위, 방식은 일괄마다 하나, 부모 기준 행은 자유 방식에서만 선택, 후보는 M17 필터 결과 + 체크박스, 행 결과 = 단독 M18 `docking_result@1`(같은 handle) + 서버가 만드는 요약 `docking_batch_result@1`, 상한 50(+1)·행당 300초·전체 7200초·작업 한도 7800초·출력 128 MiB, 부분 완료는 끝낸 행 보관, 표는 점수 + 열 정렬만(첫 행 점수, 순위·차이 없음), 사람이 승인하는 부족분 한도 증액(되돌리지 않음), 저장된 결과 자동 재사용(과금 없음), 행별 스테이징 + 종료 때 서버 게시, 일괄 보고서 `ligand_docking_batch` | 채택 |
| [0028](0028-m20-mutation-candidates.md) | M20 변이 후보: 값싼 도구 `generate_mutation_candidates` → `mutation_candidate_set@1`, 전처리 구조만, 위치 출처 셋(포켓·리간드 껍질·직접 선택)의 요청별 합집합, 단일 변이(원래를 뺀 표준 19종, 허용 목록으로 줄임), 기본 보호 = 사용자 목록 + KLIFS 주요 부위(주석이 있을 때) + 금속 근접(3.0 Å, 1.0–5.0) + 이황화 Cys(SG–SG 2.5 Å 고정), 촉매 잔기 데이터베이스 사용할 수 없음(M26), 잔기 단위 전부 해제, 주석 없으면 `not_checked`로 진행, 변형 이름 10개, 상한 위치 400·목록 400(자르지 않고 거절), 표 + 보고서 `mutation_candidates`만, 점수·순위·효과 없음, 화면은 리간드를 자동으로 고르지 않음 | 채택 |
| [0029](0029-m21-mutation-model.md) | M21 변이 구조 모델링: 작업 `openmm_mutation_model_v1`(후보 하나, 야생형 기준 + 변이형을 같은 작업·같은 절차, 1단위) → `mutation_model@1`, PDBFixer 1.12.0(프로젝트 `.venv`, sdist SHA-256 고정) 곁사슬 + M7과 같은 OpenMM 최소화, FoldX·ProteinMPNN·ESM 불허, 각 구조의 OpenMM 전위만(차이·구조 안 변화량 없음), HIS·CYS 상태는 구조마다 pH 7 자동 지정·기록(다르면 L5), PDBFixer는 변이 잔기에만(M7 사전 검사 먼저), 새 이황화 허용·기록(L6), 같은 이름 원자 유지·입력 좌표 이식, 비교는 변이 잔기 SASA·1–3결합 제외 중원자 접촉·전위·같은 조건 도킹, 뷰어 표시 없음, M18 단독만 `receptor_source`(열두째 한계 문장·입장 전용 `mutation_model_invalid`·SDF 리간드만·이 출처에서만 말단 카르복실 O/OXT 완화), M18·M19 호출 키 해시 변경으로 옛 결과 자동 재사용 끝(수용), 보고서 `mutation_model`(도킹 점수 없음) | 채택 |
