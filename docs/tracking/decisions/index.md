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
