# M18 단일 리간드 도킹(qvina) 완료 기록

- 판정: **완료** (2026-10-02). main 병합 `e0b84ea`(push 없음).
- 브랜치: `dryforge/m18-docking` (`phase/m18-docking` = main `d1f819b`에서 분기). M17은 시작 전에 main에 병합되어 있었다(`45ccad6`, 기록 `d1f819b`).
- 고정 소스: `23e2c03`(`23e2c03d87038092edd1e1ec4c10d5ff398adb11`, 오프스크린 수용체 거부 목록 단계 추가. 그 아래 `5a23462`가 독립 코드 검토 수정 병합). 증거 커밋 `8cb5d31`. 고정 뒤 제품 소스 변경 없음. 고정 뒤 변경은 Stop 훅의 pytest 그룹 분리(`306971b`: `.codex/hooks/stop.py`, `scripts/test_codex_hooks.py`)와 기록 문서뿐이다.
- 수락 증거: `docs/qa/m18-docking-20261002/`(`preflight.txt` 착수 확인, `t2-install.txt` 설치, `lock-inputs.json`, `gate.txt` 게이트, `summary.txt` 요약, `acceptance/` M18 수락, `m17-regression/`, `m16-regression/`, `m15-regression/`, `m14-regression/`, `m13-regression/`). 256 KiB를 넘는 텍스트 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다(m13-regression 52개, m14-regression 1개, m15-regression 1개, 각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 외부 요청 0건, OpenRouter 호출 0회(모든 흐름 행).

## 결과물
- 작업 프로토콜 `qvina_dock_v1`(도구 `qvina_dock_ligand`, 엔진 `qvina`, 기존 `JobQueue` 비싼 작업 경로, 시간 상한 기본 600초·최대 900초) → `docking_result@1`. 방법 `qvina_free_v1`(자유)·`qvina_core_fixed_score_only_v1`(코어 고정). 작업 모듈 `backend/mw/jobs/docking_worker.py`(`.deps/docking/venv-locked`: RDKit 2026.03.6, Meeko 0.8.0, MDAnalysis 2.10.0, gemmi 0.7.5. 엔진 `.deps/qvina/env/bin/qvina2`). `jobs/queue.py`(`DOCKING_PROTOCOL`, 스테이징 한도 48 MiB), `jobs/guardian.py`(고정 진입점·인터프리터, 결과 한도 4 MiB, 감시 대상), `tools/energetic.py`(`JOB_PROTOCOLS`·`JOB_ONLY_TOOLS`), `config/tools.yaml` 등록.
- 서버 모듈(RDKit·Meeko·MDAnalysis import 없음, qvina 실행 없음): `docking_constants.py`(닫힌 이유 집합·값 범위·점수 문구·고정 한계 문장 11개, 의존성 없음), `docking_inputs.py`(작업 인자 입장 검사, 호출 키 입력, gemmi로 수용체 인스턴스 목록·M11 규칙 수용체 검사), `docking_bundle.py`(capability handshake, 입장 검사, 호출 키, 스테이징, 게시 검증, 검증 읽기), `docking_reads.py`(읽기 API), `docking_reports.py`(보고서).
- API: 읽기 7개(`/docking/prerequisites`, `/docking/receptor_instances`, `/docking/results`, `/docking/results/detail`, `/docking/results/contacts`, `/docking/results/pose_sdf`, `/docking/results/poses_sdf`), `/capabilities`의 `methods.ligand_docking`, 방법 보고서 `analysis_type: "ligand_docking"`, 작업 결과 `artifacts.docking_result`, 작업 승인 허용 목록에 `qvina_dock_ligand`. 가져오기 종류는 새로 만들지 않았다(M11 `receptor`·`receptor_bonds`·`ligand_sdf` 그대로).
- 화면: 리간드 설계·탐색 탭에 후보 영역(`LigandPanel`) 다음으로 붙인 `frontend/src/components/DockingPanel.tsx`(순수 로직 `src/lib/docking.ts`), `app/page.tsx`(탭 마운트, 보고서 목록 `reloadToken`), `lib/api.ts`·`contracts.ts`·`report-library.ts`("리간드 도킹 보고서"), 스타일 `design/components.css`와 생성물.
- 설치: `scripts/setup_qvina.py`(conda-forge qvina 2.1.0 osx-arm64 패키지 8개 잠금), `scripts/setup_docking_worker.py`(wheel 26개 잠금), 잠금 `config/docking/` 4개. 실제 설치 기록 `.deps/qvina/install-record.json`, `.deps/docking/install-record.json`(`t2-install.txt`). 기존 `.deps/prolif`·`.deps/fpocket`은 설치 전후 파일 목록 해시가 같았다.
- Fixture: `backend/tests/fixtures/docking/`(공개 준비 예제 파생 3D 부모 SDF, 합성 복합체 3종(인스턴스 1개·같은 7필드 2개·공유 결합), 물·아연 수용체, altloc 수용체, 평면 SDF, 암시 수소 SDF, 실제 M17 작업 출력 후보 집합, 손 계산 접촉 oracle, 기대값 `expected.json`, `SYNTHETIC-PROVENANCE.md`, 재생성 스크립트 `build_docking_fixtures.py --check`).
- 테스트: 백엔드 `test_docking_inputs.py`, `test_docking_worker.py`, `test_docking_jobs.py`, `test_docking_api.py`, `test_docking_reports.py`. 프런트 `tests/docking.test.cjs`. 스크립트 `test_setup_qvina.py`, `test_setup_docking_worker.py`, `test_m18_offscreen_acceptance.py`.
- QA 도구: `frontend/tests/offscreen/docking-flow.cjs`(`test:offscreen:docking`, 모드 `main`·`unavailable`), `scripts/m18_offscreen_acceptance.py`(단계 `docking-main`, 재현 검사, `docking-unavailable`).

## 사용자 결정 (2026-10-02, 명세 확정 때)
근거는 결정 0026. 사용자가 엔진을 직접 골랐고 나머지는 추천안을 골랐다.
- 엔진은 qvina만(일반 Vina·smina·gnina 아님), 점수 문구 "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"와 "모드 n(엔진 출력 순서)".
- 리간드는 3D SDF와 M17 후보 둘 다(후보는 자유/코어 고정), 상자는 리간드 범위+여백·수용체 안 인스턴스 범위+여백·직접 입력(포켓 후보 상자 제외), 상호작용 표는 기하 접촉만, 뷰어 표시 없이 표와 SDF 내려받기.
- 수용체는 M11 입력 규칙 재사용, 복합체는 인스턴스 하나만 지정해 빼고 나머지 비표준 요소는 거부.
- 코어 고정은 부모 코어 좌표를 그대로 둔 구속 샘플에 `--score_only`만, seed 직접·CPU 1, 새 격리 환경 둘, 최소 보고서 포함.
- 조율 세션이 정하고 사용자가 최종 확인에서 바꿀 수 있는 것(확인 세 항목, 한계 문장 10·11, 상자 밖 원자·최소 거리 표시만, 도킹 1회 = 1단위, 한계 문장 11개, 보고서 금지어 예외, 수용체 PDBQT 경로)은 결정 0026에 적었다.

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 착수 확인: 측정, fixture, 손 계산 oracle, 잠금 입력 | `c98e0c1` |
| T2 설치 스크립트·잠금·실제 설치 기록 | `761e9d9` |
| T3 상수, 작업 인자 입장 검사, 수용체 인스턴스 | `cbf6bd4` |
| T4 격리된 qvina 작업 모듈 | `a5a562a` |
| T5 작업 경로, 결과 객체, capability | `e4bc868` |
| T6 읽기 API | `e296fa0` |
| T7 `ligand_docking` 보고서 | `6222a6c` |
| T8 프런트 API·타입·순수 로직 | `c1fce3a` |
| T9 도킹 화면 | `994e1f1` |
| T10 오프스크린 흐름·M18 수락 실행기 | `b6a7c89` |
| T11 독립 코드 검토 수정 | `283cc72`(병합 `5a23462`) |
| T12 오프스크린 수용체 거부 목록 단계 = 고정 소스 | `23e2c03` |
| T12 게이트·수락·회귀 증거 | `8cb5d31` |
| 완료 기록·결정 0026·프로젝트 문서 | 이 기록과 같은 커밋 |

## 착수 확인 (`preflight.txt`, 기준 `d1f819b`)
- qvina 2.1.0 conda 환경(패키지 8개)을 보관 파일로 오프라인 재생성할 수 있었다. `qvina2` SHA-256 `caf5f22a…f79c`, `--version` "QuickVina 2.1 (24 Dec, 2017)". Meeko 0.8.0 + RDKit 2026.3.6 환경에서 리간드 PDBQT를 만들었다.
- 수용체 PDBQT: Meeko 수용체 준비(`Polymer`)는 공개 예제를 받지 못했다(모르는 잔기 템플릿을 files.rcsb.org에서 받으려 함, 말단 캡 잔기 템플릿 불일치). M11 화학 추론 그래프 → Meeko 원자 유형·전하 경로는 됐고, Meeko 자체 수용체 경로와 원자 2,894개에서 유형 불일치 0, 전하 차 ≤ 0.004였다.
- 같은 seed·`--cpu 1` 두 번의 출력 PDBQT가 바이트 동일했다. 공개 예제 재도킹 모드 1 중원자 RMSD 1.300 Å(기준 ≤ 2.5 Å), 기준 포즈 `--score_only` −12.21087. 자유 도킹에서도 상자 밖 중원자가 나왔다(seed 42 모드 6에 1개).
- 이벤트·객체 크기 한도는 코드에 없다. 모드 8개 결과 형태 JSON 239,478 B. 모드당 접촉 상한 500행(`MAX_CONTACTS_PER_MODE`)은 이 실측의 최악 추정으로 정했다.
- 정할 점 7개(작업 환경에 MDAnalysis, 포즈 원자 순서 복원, 코어 좌표 덮어쓰기 여부, Meeko 네트워크 경로, 스테이징 한도, 재현 비교 대상, 점수 자릿수)는 T2–T5에서 정했다(결정 0026, `docs/engineering-notes.md`).

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 독립 코드 검토(고정 전): 막는 지적 1건(수용체 거부 목록 `receptor_unsupported_residue`·`receptor_altloc_present`의 항목이 화면에 나오지 않음)과 권고 여럿. `283cc72`에서 고친 것: 거부 목록을 입장 거절(422)과 작업 실패 두 경로 모두 화면에 표시(잔기 7필드 null 그대로, 원자 이름, altloc), 취소 버튼을 시작 요청과 분리(서버가 시작 요청을 작업 종료까지 붙잡으므로 제출된 job id로 바로 취소), `--score_only` 값의 지수 표기 파싱(nan·inf·넘침·잘못된 값은 계속 `engine_output_invalid`), 후보 출처 선택 때 한계 문장 7·10·11을 제출 전에 안내. 입장 거절(422) 경로의 거부 목록은 T12 오프스크린 단계 `D-reject-receptor`로 실제 화면에서 확인했다. 작업 실패 경로의 목록 표시는 오프스크린에서 관찰하지 않았고 프런트 단위 테스트로만 덮는다. 고치지 않은 권고는 아래 "알려진 한계"와 `docs/tracking/findings.md`에 적었다.
- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 고정 뒤): **approve**. 권고는 이 기록(관찰하지 못한 사례, 재현 범위, 초기 증거 파일의 절대 경로)과 `findings.md`로 처리했다.

## 게이트 (고정 `23e2c03`, `gate.txt`, 2026-10-02 02:57:03–03:17:34 UTC)
시작 때 작업 트리 깨끗함, 백엔드 pytest만 `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 끝난 뒤 작업 트리 깨끗함, HEAD 그대로.

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 1404 passed, 0 skipped(1214초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 13개 파일(`test_m18_offscreen_acceptance.py`, `test_setup_qvina.py`, `test_setup_docking_worker.py` 포함) | exit 0, 269 passed |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow`·`ligand-flow`·`docking-flow` | exit 0 ×7 |
| `npm --prefix frontend run test:events` | exit 0, 256 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA (고정 `23e2c03`, `acceptance/`, 시도 1회)
- 명령: `.venv/bin/python scripts/m18_offscreen_acceptance.py --root runs/m18-acceptance-20261002 --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/final --out docs/qa/m18-docking-20261002/acceptance`
- 빌드 `TQn8wObN5_83HO7HbKqrf`(gitHead `23e2c03`, 소스 도장 일치). `verdict: pass`, `acceptance: true`, 판정 사례 24개(흐름 사례 21 + `D-reject-receptor` + `D-reproducible` + `S-no-egress`), 단계 `docking-main`(기록 행 35개 모두 통과)·`docking-unavailable` 통과. 비-loopback 요청 0건, 제공자 호출 0회, 남은 작업 프로세스·guardian·`qvina2`·8000/3000 리스너 없음. 두 환경 있음, 주 백엔드 capability 사용 가능, 환경 없는 layout 백엔드 `worker_missing`.
- 관찰 요약: 구조 분석 탭에서 새 run + 1MQ4 → 리간드 탭 도킹 영역(전역 run, capability 줄, 빈 결과 목록, 시작 비활성) → 파일 선택으로 공개 수용체 `prolif-vina-rec.pdb`와 공개 파생 3D SDF 가져오기(자동 선택 없음) → 확인 두 개만 체크하면 시작 비활성(`acknowledgement_missing`) → SDF 출처에서 코어 고정 비활성(`mode_source_mismatch`), 인스턴스 없이 인스턴스 범위 비활성 → 자유 도킹 시작 → 비싼 계산 승인 → 실제 `qvina_dock_v1`(1단위) → 요약(점수 문구 전체, 엔진, seed 42, 값, 상자 = 손 oracle, 수용체·리간드 SHA-256), 모드 표 = 저장 행("모드 n(엔진 출력 순서)", `ROUND_HALF_UP`), 한계 문장 = 명세 5.4 선택 → 모드 1 접촉 표 = 저장 행(포즈 SDF 번호, 수용체 7필드, `site_index`, 거리, 기하 종류, 4.0 Å, 순서) → 모드 1·전체 SDF 다운로드 = 저장 `pose_sdf`(`events.jsonl` payload) = 백엔드 바이트(`mode_<n>` 제목, `$$$$`) → 보고서 만들기 → 지식 탭 "리간드 도킹 보고서", 다운로드 바이트 동일 → 합성 복합체 수용체의 인스턴스 목록(7필드, 79원자, 원소)에서 고르기 → 인스턴스 범위 상자 = 손 oracle, 뺀 인스턴스 기록, 포즈가 단백질만 수용체의 포즈와 바이트 동일 → 후보 영역에서 실제 M17 점검·생성(부위 22, 고정 교체, 두 번째 승인 없음) → 후보 + 부모 SDF, 코어 고정, conformers 5 → "샘플 n(점수 오름차순 나열)" 행, 코어 최대 이탈, 생성된 수소·좌표 표시, 부모 번호, 한계 문장 1–5·7·8 → 구조 분석 탭 숨긴 채 유지(같은 Mol* 세션·소스·세대), 전역 예산 = 백엔드 → run B에서 붙잡아 둔 run A 결과 목록 응답 버림 → 평면 SDF `ligand_not_3d`, 암시 수소 SDF `ligand_hydrogens_missing`(작업 실패, 결과 없음) → 직접 입력 한 변 41 Å는 시작 비활성(`box_too_large`, 작업 요청 없음), 리간드 범위 + 여백 20은 작업이 `box_too_large`(결과 없음) → 물·아연 수용체(인스턴스 없음)는 제출 422 `receptor_unsupported_residue`, altloc 수용체는 422 `receptor_altloc_present`, 화면 거부 목록이 fixture oracle과 줄마다 같음(작업·예산·결과 없음) → exhaustiveness 32 작업이 `qvina2`를 돌리는 중 작업 취소 → cancelled, 남은 프로세스 없음, 결과 없음 → 고정 한계 문장·점수 이름 밖에 순위·best·최적·개선·결합 강도·친화도 낱말 없음. `docking-unavailable`: run 없음은 이유만, 환경 없는 백엔드는 `worker_missing` 이유만(숫자·컨트롤·도킹 요청 없음).
- 재현 검사(`D-reproducible`): 흐름의 자유 도킹과 같은 수용체·리간드·상자·값·seed를 새 run 두 개에서 API로 다시 도킹해, 점수(−12.9, −10.9, −10.7)와 전체 모드 SDF 바이트가 흐름의 저장 결과와 같았다. 재현 검사는 자유 도킹만 했다. 코어 고정의 같은 seed 재현은 백엔드 테스트가 덮는다.

### 관찰하지 못한 사례
- `D-zero-modes`(qvina가 모드 0개를 냄): 이번 유효 입력에서 실제 엔진이 모드 0개를 낸 적이 없다. 입력을 위조해 만들지 않았다. 빈 과학 결과 경로는 `frontend/tests/docking.test.cjs`(`dockingPanelState`)와 백엔드 도킹 테스트로만 덮는다.

### 회귀 (고정 `23e2c03`, 같은 빌드 `TQn8wObN5_83HO7HbKqrf`)
- M17: `scripts/m17_offscreen_acceptance.py --root runs/m18-m17-regression-20261002 --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/m18-regression --out docs/qa/m18-docking-20261002/m17-regression` → `acceptance: true`, 21/21.
- M16: `scripts/m16_offscreen_acceptance.py --root runs/m18-m16-regression-20261002 --kbase <home>/Projects/kbase_kinase --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/m18-regression --out docs/qa/m18-docking-20261002/m16-regression` → `acceptance: true`, 19/19.
- M15: `scripts/m15_offscreen_acceptance.py --root runs/m18-m15-regression-20261002 --kbase <home>/Projects/kbase_kinase --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m18-regression --out docs/qa/m18-docking-20261002/m15-regression` → `acceptance: true`, 14/14.
- M14: `scripts/m14_offscreen_acceptance.py --root runs/m18-m14-regression-20261002 --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/m18-regression --out docs/qa/m18-docking-20261002/m14-regression` → `acceptance: true`, 15/15.
- M8–M13: `scripts/m13_offscreen_acceptance.py --root runs/m18-m13-regression-20261002 --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/m18-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m18-docking-20261002/m13-regression` → `acceptance: true`, 필수 단계 17개·사례 28개, M11·M12 하위 실행기 통과.
- 모두 외부 요청 0건, 남은 프로세스·리스너 없음. 순서대로 하나씩, 실행 전후 포트 비어 있음.

### 바뀐 기존 기대와 이유
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다.
- `backend/tests/test_ligand_api.py` 2줄: `/capabilities`의 방법 집합 기대에 `ligand_docking`을 더했다(M18이 새 방법을 노출하므로). M17 capability 값 검사는 그대로다.
- `frontend/tests/report-library.test.cjs` 1줄: 새 보고서 종류 이름(`ligand_docking` → "리간드 도킹 보고서") 사례를 더했다.
- 수락 실행기(M13–M17)와 그 흐름 스크립트의 기대는 바뀌지 않았다. M17 리간드 흐름과 M14 탭 흐름은 리간드 탭에 도킹 영역이 붙은 상태로 그대로 통과했다. 과거 검토 파일·해시는 건드리지 않았다.

## 알려진 한계
- 좌표계 일치는 도구가 검증하지 못한다. 상자 안 수용체 중원자가 0개면 거부하는 것(`box_no_receptor_atoms`)이 전부다.
- 포즈는 Mol*로 보여 주지 않는다(표와 SDF 내려받기만).
- 수용체에 물·금속·보조인자·다른 리간드·변형 잔기·altloc이 남으면 거부하므로 실제 결정구조는 사용자가 파일을 손질해 다시 가져와야 한다.
- `core_max_deviation_A`는 코어 중원자 좌표를 부모 좌표로 덮어쓴 뒤 재므로 사실상 0이다. 덮어쓰기 전 구속 임베딩 잔차는 기록하지 않는다. 코어 수소는 고정 대상이 아니다(RDKit이 만든 위치).
- 수용체 수소 검사는 "명시적 수소가 하나도 없음"만 거부한다. 일부만 없는 수용체는 M11과 같은 MDAnalysis 추론으로 하전 종이 되어 통과할 수 있다(M11과 같은 규칙).
- 서버는 작업 시작 요청을 작업이 끝날 때까지 붙잡는다. 30초를 넘는 도킹은 프런트 프록시 제한에 걸릴 수 있고, 화면은 저장된 작업을 다시 읽어 실제 상태를 보여 준다. 취소는 제출 직후의 job id로 시작 요청과 무관하게 할 수 있다.
- 결과 목록 읽기는 행마다 결과 객체 전체를 다시 검증한다(이벤트 로그를 여러 번 읽음).
- 비싼 계산 승인(`/jobs/approve`)은 요청 본문에 작업을 지정하지 않고 run의 가장 최근 승인 요청 하나를 승인한다. 리간드 후보 작업과 도킹 작업이 함께 승인을 기다리면 어느 쪽 요청이 승인되는지는 요청 순서로 정해진다(M17과 공용 경로).
- 플랫폼은 macOS arm64·CPython 3.11뿐이다(qvina는 macOS ≥ 11.0).
- 커밋한 초기 증거 `preflight.txt`·`t2-install.txt`에는 사용자 절대 경로가 그대로 남아 있다(이후 증거는 `<repo>`·`<home>`). 증거 불변 규칙 때문에 고치지 않았다.

## 대체한 과거 검증 범위
- M18은 공유 소스를 바꿨다: 백엔드 `api/app.py`(capability, 작업 결과 artifacts, 작업 승인 허용 목록, 보고서 분기·목록, 도킹 읽기 라우트), `jobs/queue.py`, `jobs/guardian.py`, `tools/energetic.py`, `config/tools.yaml`. 프런트 `app/page.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, 스타일.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(1404개, skip 0)와 M17·M16·M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 고정 `23e2c03`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합(방법은 사용자에게 묻는다). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): 좌표계 일치 미검증, 포즈 뷰어 표시 없음, 수용체 비표준 요소 거부, 코어 수소 미고정·`core_max_deviation_A`의 뜻, 수용체 수소 일부 누락, 시작 요청 붙잡힘, 모드 0개·코어 고정 재현 미관찰, 목록 읽기 비용, 공용 승인 경로, 초기 증거 절대 경로. 플랫폼 잠금 항목은 기존 항목에 합쳤다.
