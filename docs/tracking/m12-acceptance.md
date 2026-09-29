# M12 로컬 포켓 후보 완료 기록

- 판정: **완료** (2026-09-29)
- 브랜치: `dryforge/m12-pockets` (`phase/m12-pocket-candidates` = main `adb6291`에서 분기). main 병합 `eb73d12`(사용자 결정 2026-09-29).
- 고정 소스: `9e4edcb`. 고정 뒤 변경은 수락 실행기의 남은 프로세스 확인 범위(`1eb88a1`, `scripts/m12_offscreen_acceptance.py`)뿐이며 그 뒤 수락 QA 전체를 다시 돌렸다.
- 증거: `docs/qa/m12-pockets-20260929/` (README, gates/, acceptance-r2/, attempt-1-leftover-check-fail/)
- 옛 단계 폴더 `phases/protview-pockets/`는 index를 만들지 않고 그대로 둔다(결정 0016).

## 결과물
- fpocket 4.2.3(conda-forge `osx-arm64` `hb88c64c_2`) 해시 잠금 설치: `config/pockets/`의 explicit 목록·35개 패키지 해시, `scripts/setup_fpocket.py`(conda 필수, 로컬 archive 폴더, 오프라인). 설치 위치 `.deps/fpocket/env`, 설치 기록 `.deps/fpocket/install-record.json`(결정 0017).
- 입력 투영 `backend/mw/pocket_input.py`: 세 소스(전처리·M11 화학·OpenMM 최소화), 체인 선택, 표준 잔기 중원자, 합성 ID 전송 PDB와 AtomRef 일대일 대응, 한도·퇴화·변형 잔기 거부, 잔기 이름 대응 10개(히스티딘 6개 → HIS, CYX·ASH·GLH·LYN → CYS·ASP·GLU·LYS).
- 출력 파서 `backend/mw/pocket_output.py`: 알려진 파일만, 링크·특수 파일 거부, rank·구 개수·주변 원자 대응 검증, 빈 결과는 stdout 배너와 stderr 진단의 정확한 형태만 scientific_null.
- 작업·객체·API: 도구 `detect_pockets`, 프로토콜 `fpocket_detect_v1`(작업 전용), 작업 프로세스 `backend/mw/jobs/pocket_worker.py`, `backend/mw/pocket_bundle.py`, 객체 `pocket_detector_input@1`·`pocket_native_output@1`·`pocket_set@1`, `/pockets/preflight`·`/pockets`·`/pockets/result`·`/pockets/geometry`, `/capabilities`의 `methods.pocket_detection`.
- 보고서 `backend/mw/pocket_reports.py`: `method_report_manifest@1`, `analysis_type: "pocket_detection"`, 렌더러 `pocket_markdown@2`.
- 화면: `PocketPanel.tsx`(메인 화면과 화학 작업 화면), Mol* 알파 구 오버레이(`MolstarViewer.tsx`), 오버레이 중 M8·M9 비활성, 비교 중 차단, 거리 측정 허용(구 선택 불가).
- QA 도구: `frontend/tests/offscreen/pocket-flow.cjs`, `scripts/m12_offscreen_acceptance.py`, `scripts/m12_qa_inputs.py`, 첫 paint 캡처 수정(`main.cjs`, `driver.cjs`, `m11-ledger.cjs`).

## 진행 중 사용자 결정
- 오버레이 중 M9 저장·PNG와 M8 요청은 비활성(새 보기 형식 만들지 않음).
- 세 소스 모두 지원. 히스티딘 6개 이름 대응, 이어서 Amber 이름 4개 추가.
- 포켓 패널은 메인 화면과 화학 작업 화면 두 곳, 화학 화면에서 주석과 오버레이는 동시에 켜지 않음.
- 취소 뒤 같은 호출은 기존 작업을 돌려주는 대기열 동작 유지(화면이 다른 체인 조합·새 run을 안내).
- 원본 출력은 파서가 읽는 파일만 바이트 보관, run당 64 MiB.
- 빈 결과 진단은 실제 동작대로 stderr(계약 문서의 "stdout"은 시험 기록이 두 출력을 합친 데서 온 표현).
- 개발 중 fpocket 4.2.3 공개 소스 조회 허용(프로젝트 데이터 전송 없음).

## 독립 코드 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 대상: `git diff main...da3aa51`. 판정: **issues** — 막는 지적 5개, 계약 변경 필요 지적 없음(Amber 이름은 사용자에게 올려 결정).
- 막는 지적과 처리(수정 병합 `9e4edcb`):

| # | 지적 | 처리 |
|---|---|---|
| 1 | 최소화 구조의 포켓을 고르면 최소화 표시 규칙(원래 복합체 접촉 행 숨김, 범례)이 깨짐 | 수정: 최소화 구조 포켓은 OpenMM 최소화 보기와 같은 상태로 전환, "원래 소스로 돌아가기"는 직전 보기로 |
| 2 | 체인을 모두 해제하면 전체 체인으로 실행 | 수정: 실행 막고 "체인을 하나 이상 고르세요" |
| 3 | QA의 빠른 rank 전환 단계가 실제 경쟁을 시험하지 않음 | 수정: 동시 읽기 차단을 확인하고 실제 늦은 응답을 만들어 반영되지 않음을 확인 |
| 4 | 거리 측정 단계가 오버레이 유지를 확인하지 않음 | 수정: 같은 소스면 오버레이 유지를 확인 |
| 5 | 사례 대장이 빠지거나 실패한 필수 단계를 통과로 셀 수 있음 | 수정: 단계 이름별 필수, 빠지면 실패, 남은 프로세스·외부 요청 수 포함 |

- 권고 처리: 보관량을 게시된 결과만·최종 크기로 계산, 게시 전 현재 시도 확인, 빈 결과 형태를 소스 기준 정확한 바이트로, 읽을 때 원본 출력과 재대조, 보고서에 capability·예산 스냅숏, 작업 프로세스가 해시 확인한 복사본을 실행, 화면의 로딩·기록 페이지·실행 중 작업 복원·초점 상태, QA 검사 강화·환경 허용 목록·경로 가림. 수락 QA 중 찾은 결함(다른 run으로 바꾼 뒤 늦은 포켓 결과가 새 화면에 적용됨)도 수정했다(`da3aa51` 이전 병합).
- 검토 파일 SHA-256 전체 목록(`da3aa51` 기준)은 검토 보고에 있으며, 고정 소스의 증거 파일 해시는 `docs/qa/m12-pockets-20260929/acceptance-r2/SHA256SUMS`와 사례 대장에 있다.

## 전체 게이트 (고정 소스 `9e4edcb`)

| 명령 | 결과 |
|---|---|
| `pytest backend/tests -q -rs` | 497 passed, skip 0 (fpocket·ProLIF 작업 환경 설치) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | 통과 |
| `pytest scripts/test_execute.py scripts/test_codex_hooks.py scripts/test_setup_fpocket.py -q` | 85 passed |
| `test:events`, `typecheck`, `build` | 106 passed, 통과, 통과 |
| `node --check frontend/tests/offscreen/pocket-flow.cjs` | 통과 |

## 수락 QA
- 첫 실행(`attempt-1`): 기능 31단계 통과, 남은 프로세스 확인 실패. 잡힌 프로세스는 이 실행의 이벤트 기록에 없는 PID였고(같은 시각의 Stop 훅 pytest로 추정), 이 실행의 작업 16개는 모두 종료·정리되었다. 확인 범위를 수락 루트로 좁혔다.
- 재실행(`acceptance-r2`): **pass**. 포켓 13개 흐름, M8 normal·M9 OpenMM·M9 scenes·M10 measure·alignment·M11 7개 모드와 m11-create 회귀, events-only 복구(포켓 결과·보고서 바이트 동일, 엔진 없이), 엔진 없음·해시 불일치 표시, 남은 프로세스 없음, 외부 요청 0건.

## 독립 증거 검토 (Opus 5.5, 코드 검토자와 다른 서브에이전트)
- 판정: **approved** (막는 지적 없음).
- 직접 확인: SHA256SUMS 전체와 이진 산출물 4,792개 해시, 모든 행의 offscreen·GPU·paint·첫 paint·외부 요청 0건, 8개 rank 전체의 구 중심·반지름 대조(최대 1.8e-6 Å, 반지름 0), 보고서 근거 83개, 실제 엔진 빈 결과, 복원 바이트 동일, 첫 실행 남은 프로세스 설명, 커밋 증거에 로컬 경로 없음.
- 권고(기록으로 처리): 최소화 구조에서 접촉 행 숨김은 리간드 있는 최소화 가능 fixture가 없어 실제 화면에서 확인하지 못함, M11 회귀는 일부 모드만, M8–M10 행에 렌더러 문자열 없음, 화면 취소는 승인 대기 작업으로만 확인, 보고서 Markdown의 작은따옴표 이중 이스케이프(`findings.md`).

## 대체한 과거 검증 범위
- 바뀐 공유 소스: `backend/mw/api/app.py`, `jobs/queue.py`, `jobs/guardian.py`, `tools/energetic.py`, `config/tools.yaml`, `frontend/app/page.tsx`, `MolstarViewer.tsx`, `ChemicalWorkspace.tsx`, `ViewerAgentPanel.tsx`, `src/lib/api.ts`, `comparison.ts`, `design/components.css`, 오프스크린 `main.cjs`·`driver.cjs`·`m11-ledger.cjs`, `.codex/hooks/stop.py`. 위 회귀(M8 normal, M9 OpenMM·scenes, M10 measure·alignment, M11 일부 모드)와 전체 게이트가 현재 기준 검증이다. 과거 검토 해시는 고치지 않는다.
