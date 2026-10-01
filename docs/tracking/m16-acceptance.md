# M16 참조 주석 표시와 기하 접촉 강조 완료 기록

- 판정: **완료** (2026-10-01). main 병합 `0fb3426`(2026-10-01, `--no-ff`)
- 브랜치: `dryforge/m16-annotations` (`phase/m16-reference-annotations` = main `70507a5`에서 분기). M15는 시작 전에 main에 병합되어 있었다(`beaffcb`, 기록 `70507a5`).
- 고정 소스: 첫 고정 `b23cb10`(`b23cb10f624d1942666d0f0080e49e449055b53e`, 독립 코드 검토 수정 `cc3da8e`의 병합, 증거 커밋 `a4ca298`), 재고정 `3a2e20c`(`3a2e20c8e65c550a492cb51c7298e07215970231`, 하네스 `annotation-flow.cjs`만 고침, 증거 커밋 `6f14094`). 첫 고정에서 전체 게이트·M16 수락 QA(시도 1, 실패)·M15·M14·M13 회귀를, 재고정에서 바뀐 하네스에 걸린 게이트 명령과 M16 수락 QA(시도 2)를 돌렸다. 재고정 뒤 변경은 테스트 하나를 더한 `71a3fa1`뿐이다(아래 "고정 뒤 변경").
- 수락 증거: `docs/qa/m16-annotations-20261001/`(`preflight.txt` 착수 확인, `gate.txt` 게이트와 재고정 절, `acceptance/` 시도 1, `acceptance-attempt2/` 시도 2, `m15-regression/`, `m14-regression/`, `m13-regression/`). 큰 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다.
- 외부 요청 0건, OpenRouter 호출 0회(모든 흐름 행). 주석 도구는 참조 폴더를 읽지 않는다. 수락 QA의 참조 폴더는 실행마다 격리 루트에 kbase에서 새로 가져왔다(`--kbase <home>/Projects/kbase_kinase`).

## 결과물
- 도구 `annotate_reference_sites`(값싼 동기 도구, `Run.call`): `backend/mw/tools/site_annotation.py`, 순수 로직 `backend/mw/site_annotation.py`, 결과 `reference_site_annotation@1`(`mw.site_annotation/v1`). 부위 목록 `kinase_key_sites@1`(III.17, αC.24, GK.45, hinge.46–48, xDFG.80–83) 고정. 입력은 같은 run의 번호 대응 handle 하나 + 같은 구조의 기하 접촉 결과 handle(선택). 레지스트리 사전 검사 훅이 두 handle을 검증한다. `config/tools.yaml`, `workspace.py`, `SUPPORTED_TOOLS` 등록. `/capabilities`의 `methods.reference_site_annotation`은 항상 사용 가능.
- 읽기 API(이벤트·도구 없음): `GET /runs/{id}/site_annotations`(목록, 소스 handle로 거르기), `GET /runs/{id}/site_annotations/detail`.
- 저장된 보기·그림: `backend/mw/saved_scenes.py`에 `viewer_scene@2`(`annotation{handle, legend}`), `viewer_figure@2`(`capture_method`, `annotation{handle, legend, numbering_map, contacts, snapshot_set_hash, display_labels}`). 주석이 꺼진 저장은 `viewer_scene@1`·`viewer_figure@1` 그대로다.
- 보고서 `backend/mw/site_annotation_reports.py`: `method_report_manifest@1`, `analysis_type: "reference_site_annotation"`, 렌더 `reference_site_annotation_markdown@1`, 증거 종류 `computed`·`reference_value` 분리.
- 화면: 구조 분석 탭 메인 화면의 `frontend/src/components/SiteAnnotationPanel.tsx`(순수 로직 `src/lib/site-annotation.ts`), `MolstarViewer.tsx`의 주석 그리기·native readback·`viewer_scene@2` 복원·PNG 범례 합성, `app/page.tsx` 배타 규칙(포켓 오버레이·M10 비교·M8 자연어 요청), `PocketPanel.tsx`의 `overlayBlockedReason`, `ViewerAgentPanel.tsx`의 `naturalLanguageDisabledReason`, 보고서 목록의 "참조 주석 보고서" 이름. 색 토큰 `site-iii`·`site-ac`·`site-gk`·`site-hinge`·`site-xdfg`·`site-other-contact`·`site-polar-line`(`design/tokens.json`), 스타일 `design/components.css`와 생성물.
- 테스트: 백엔드 `test_reference_site_annotation.py`, `test_site_annotation_reports.py`, `test_saved_scenes.py` 확장. 프런트 `tests/site-annotation.test.cjs`. 스크립트 `test_m16_offscreen_acceptance.py`.
- QA 도구: `frontend/tests/offscreen/annotation-flow.cjs`(`test:offscreen:annotations`, 모드 `main`·`minimized`), `scripts/m16_offscreen_acceptance.py`(단계 `reference-import`·`annotation-main`·`annotation-minimized`).

## 사용자 결정 (2026-09-30, 명세 확정 때)
근거는 결정 0024.
- 부위는 10자리 고정, 기하 접촉만(ProLIF 강조 없음), 같은 구조 handle에만 적용, 극성 접촉은 점선 + 거리, 다른 접촉 잔기는 색만. 사용자 지정 잔기·85개 포켓 전체 표시는 하지 않는다.
- 새 불변 결과·새 보고서. 접촉 결과 없는 주석·보고서도 허용.
- 패널은 구조 분석 탭, 지식 탭은 바꾸지 않는다. 이름표 `Met318 (hinge.47)` 형식. 보기 복원 때 주석을 다시 그린다.
- 주석이 담긴 PNG 저장 허용, 범례 기본 켬(끌 수 있음). 그림 상한은 올리지 않는다(2048 px·400만 픽셀·8 MiB).
- 포켓 오버레이와 배타, 주석 중 M8 자연어 요청 막음, 비교 시작 때 주석 끔.
- 지식 탭 체인 목록 findings 항목은 다시 미룬다.

## 커밋

| 작업 | 커밋 |
|---|---|
| 착수 확인: 부위 표기, 1MQ4 oracle, ATR 손 대조 | `70142f1` |
| 주석 도구·결과 객체·읽기 API | `acebd8b` (병합 `a9f3fe3`) |
| 보고서 | `394ec8f` (병합 `9302959`) |
| `viewer_scene@2`·`viewer_figure@2` | `6bb455d` (병합 `2079fec`) |
| 프런트 API·타입·순수 로직 | `80b7ac7` (병합 `b7b24b4`) |
| 뷰어 브리지 그리기·복원·PNG 범례 | `215bd8b` (병합 `be987b8`) |
| 패널·페이지 연결 | `528e21f` (병합 `16c31da`) |
| 오프스크린 흐름·M16 수락 실행기(패널이 번호 대응 목록을 한 번만 읽던 결함 수정 포함) | `1e94779` (병합 `5cf4a70`) |
| 독립 코드 검토 수정 = 첫 고정 소스 | `cc3da8e` (병합 `b23cb10`) |
| 첫 고정의 게이트·수락 시도 1·회귀 증거 | `a4ca298` |
| 하네스 범례 영역 수정 = 재고정 소스 | `3a2e20c` |
| 재고정 게이트·수락 시도 2 증거 | `6f14094` |
| 커밋된 KLIFS `match_residues` 발췌와 대조하는 테스트(고정 뒤, 테스트만) | `71a3fa1` |
| 완료 기록·결정 0024·프로젝트 문서 | 이 기록과 같은 커밋 |

보고서·저장된 보기 작업을 합친 뒤 통합 게이트(백엔드 879개 통과, skip 0, ruff 통과)와 흐름 작업의 개발 실행(18사례, `acceptance: true`)은 구현 보고이며 커밋 증거는 없다.

## 착수 확인 (`preflight.txt`, 기준 `70507a5`)
- 부위 표기 10개가 1MQ4 전처리 구조 대응의 `klifs_label`과 문자 그대로 같다(`αC`는 U+03B1). 10개 모두 커밋된 1MQ4:A `match_residues` 발췌와 (Xray_position, KLIFS_position) 일치. 10개 부위 잔기 모두 ATOM 레코드(HETATM 부위 없음).
- PDB ID 제안은 전처리 구조 handle에서 원본 업로드로 따라가 "1MQ4". 대응: 대응됨 260, 충돌 1, KLIFS `O14965` 적용(unresolved I·a.l).
- 독립 oracle: 전처리 구조 좌표를 gemmi.cif로 `_atom_site`만 읽어 numpy로 계산(ADP 인스턴스 `chain_label E`, `seq_auth 2001`, cutoff 4.0). 극성 쌍 10개(III.17 3, hinge.46 1, hinge.48 2, xDFG.81 4), hinge.47·αC.24·xDFG.80/82/83은 접촉 0. 제품 `compute_interactions`와 쌍·개수는 같고 거리는 두 곳에서 마지막 자리만 다르다(gemmi와 numpy 부동소수 차이) → 이후 독립 비교는 abs ≤ 1e-9.
- ATR(Q13535) 5YZ0:A: GK.45 2377, hinge.46–48 2378–2380이 손 대조·제품 규칙·KLIFS 구조별 표 셋 다 같다. 어긋남은 `linker.49`(KLIFS 표 2381, 제품 2382, 둘 다 N)뿐이고 부위 목록 밖이라 규칙을 바꾸지 않았다(`docs/tracking/findings.md`).

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- 중간 명세 검토: 주석 도구 작업(`acebd8b`)과 뷰어 브리지 작업(`215bd8b`) 각각 **통과**.
- 독립 코드 검토(첫 고정 전): 막는 지적·고쳐야 할 지적 없음, 권고 6개. 5개는 `cc3da8e`에서 고쳤고 1개는 이 기록 커밋에서 처리했다.

| 권고 | 처리 |
|---|---|
| 보고서 다시 열기가 저장된 없음 이유를 그대로 믿음 | `cc3da8e`: 대응 객체에서 첫 해당 이유를 다시 정해 비교하고, `assessed`를 저장된 구조 잔기 목록의 polymer 분류와 대조(저장 객체만 읽고 접촉·대응·주석을 다시 계산하지 않음) |
| 거부된 `viewer_scene@2` 복원 뒤 일반 그리기가 같은 주석을 다시 그릴 수 있음 | `cc3da8e`: 페이지가 요청을 거두고, 뷰어는 복원에서 거부된 의도 revision을 다시 그리지 않음 |
| 쓰지 않는 export | `cc3da8e`: 제거 |
| 범례가 그림 폭을 넘을 수 있음 | `cc3da8e`: 같은 글자 크기로 줄바꿈(`wrapLegendText`), 그래도 안 들어가면 그림 저장 거절(`FIGURE_LEGEND_NO_FIT`) |
| 영어 해석·혼동 표현이 금지어 검사에 없음 | `cc3da8e`: `hydrogen bond`, `H-bond`/`hbond`, `catalytic` 추가 |
| 게이트 목록에 M16 검사가 없음 | 이 기록 커밋: `docs/standards.md`·`docs/operations.md`·`scripts/AGENTS.md`(Stop 훅과 `scripts/test_codex_hooks.py`에는 흐름 작업에서 이미 추가) |

- 독립 증거 검토(코드 검토자와 다른 새 인스턴스, 재고정 뒤): **approve**. 권고는 아래처럼 처리했다.

| 권고 | 처리 |
|---|---|
| 1MQ4 부위를 커밋된 `match_residues` 발췌와 직접 대조하는 테스트가 없음 | `71a3fa1`(아래 "고정 뒤 변경") |
| 하네스 범례 영역이 제품의 기하 계산을 함께 씀 | 기록(아래 "재고정") |
| "범례 픽셀은 왼쪽 아래 상자 안에만"이라는 사례 설명은 실제 판정과 다름 | 기록: 실제 판정은 밀도 비율이다(아래). 실행기의 사례 설명 문자열은 고정 소스라 그대로 둔다 |
| 시도 1 실패 진단 위치를 완료 기록에서 가리킬 것 | 아래 "수락 QA" |
| `gate.txt`의 "tree status after gate" 줄이 비어 있음 | 기록: 빈 줄은 증거 폴더를 뺀 작업 트리에 변경이 없었다는 뜻(깨끗함) |
| 완료 기록 미작성 | 이 기록 |

## 게이트 (첫 고정 `b23cb10`, `gate.txt`, 2026-10-01 00:31:41–00:48:13 UTC)
시작 때 작업 트리 깨끗함, `MW_KBASE_REF=<home>/Projects/kbase_kinase/ref`. 끝난 뒤 "tree status after gate" 줄이 비어 있다 = 증거 폴더 밖 변경 없음.

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 886 passed, 0 skipped(969초) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 9개 파일(`test_m16_offscreen_acceptance.py` 포함) | exit 0, 145 passed |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow`·`annotation-flow` | exit 0 ×5 |
| `npm --prefix frontend run test:events` | exit 0, 200 pass, 0 fail, 0 skipped |
| `typecheck` → `build` | exit 0 → exit 0 |

## 수락 QA

### 시도 1 (첫 고정 `b23cb10`, `acceptance/`, 2026-10-01 00:49 UTC) — 실패
- 명령: `.venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-20261001 --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/final --kbase <home>/Projects/kbase_kinase --out docs/qa/m16-annotations-20261001/acceptance`
- 빌드 `q6eypdtQJ4Qgom9x2qBFB`(소스 도장 일치). `verdict: fail`, `acceptance: false`, 사례 15/19. 하네스의 PNG 픽셀 검사(`M13-pixels`)가 실패해 그림 부분이 중단되었고, 그 부분의 4사례(A-figure-legend, A-figure-no-legend, A-figure-pixels, A-scene-v1-unchanged)가 실패로 기록되었다. 나머지 사례, 외부 요청 0건, 남은 프로세스 없음은 통과.
- 진단(`acceptance-attempt2/README.md`의 "시도 2" 절, 실패 화면 `acceptance/evidence/annotation-main/M13-pixels-failure.panel.html`): 하네스 `legendRegion()`이 코드 검토 수정(`cc3da8e`)의 범례 줄바꿈 전 상자 높이(47 px, y0=734)를 가정해 실제 상자(54 px, 729–782행)의 윗부분을 상자 밖으로 셌다(legendInside 0.0831 < 20 × legendOutside 0.00466). 제품의 범례는 올바르게 그려졌다. 시도 1 증거는 지우지 않았다.

### 재고정 (`3a2e20c`, `gate.txt`의 "re-freeze" 절, 01:38:28–01:38:34 UTC)
- `b23cb10` 대비 `docs/qa` 밖 변경은 `frontend/tests/offscreen/annotation-flow.cjs`뿐이다. 하네스의 범례 영역은 이제 제품의 `wrapLegendText`와 같은 글자 크기·여백·줄 간격 상수로 계산한다. **주의**: 그래서 이 검사는 제품과 같은 기하 계산을 공유하며, 제품의 줄바꿈 계산 자체가 틀린 경우는 이 검사로 잡히지 않는다(범례 문자열·그려졌는지는 별도 확인).
- 백엔드·프런트 빌드 소스가 같아 백엔드 pytest·ruff·`test:events`·`typecheck`·`build`는 다시 돌리지 않았다. 다시 돌린 것: `node --check frontend/tests/offscreen/annotation-flow.cjs`(exit 0), 스크립트 pytest 9개 파일(exit 0, 145 passed).

### 시도 2 (재고정 `3a2e20c`, `acceptance-attempt2/`, 01:39 UTC) — 채택
- 명령: `.venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-20261001-attempt2 --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/attempt2 --kbase <home>/Projects/kbase_kinase --out docs/qa/m16-annotations-20261001/acceptance-attempt2`
- 같은 빌드 `q6eypdtQJ4Qgom9x2qBFB`(gitHead `3a2e20c`, 소스 도장 일치). Electron 44.4.5, `isOffscreen()===true`, WebGL, paint. `verdict: pass`, `acceptance: true`, 사례 19/19, 단계 3개 모두 첫 시도. 비-loopback 요청 0건, 제공자 호출 0회, 남은 프로세스·리스너 없음. 참조 세트(격리 가져오기) `96abf6e4…7d3c`(시도 1은 `67e062ad…b9e5`: 가져올 때마다 세트 해시가 다르다).
- 관찰 요약: 1MQ4 → 전처리 → ADP 기하 접촉(인스턴스를 명시 선택, PO4도 후보로 표시) → 지식 탭에서 전처리 구조 대응(PDB ID 1MQ4 확인) → 패널에서 같은 구조의 대응·접촉 결과만 나열하고 자동 선택 없음 → 주석 만들기. 부위 표의 이름표·상태·개수·최소 거리가 저장 객체와 착수 확인 oracle(`preflight.txt`)과 같고, 계산했으나 0인 개수는 0, cutoff 안 접촉 없음은 문장으로 표시. Mol* readback: 부위 10개, 이름표 = `display_label`(예: `Glu211 (hinge.46)`), 점선 = 착수 확인의 극성 쌍 10개(정확한 카탈로그 원자 사이), 거리 이름표 `ROUND_HALF_UP`, 그리지 못한 쌍 0.
- 그림: `viewer_scene@2`(범례 켬) + `viewer_figure@2` `molstar_image_pass+legend`, 범례 끈 보기 → `molstar_image_pass`, 주석 끈 저장은 `annotation` 키 없는 `viewer_scene@1`·`viewer_figure@1`. PNG·출처 JSON 다시 받기 바이트가 백엔드와 같다. 같은 카메라의 세 PNG 비교: 범례 그림과 범례 없는 그림의 차이 픽셀 **밀도**가 범례 상자 안 0.1872, 상자 밖 0.00393(판정: 안 ≥ 20 × 밖, 밖 ≤ 0.01). 즉 "범례 픽셀이 상자 안에만 있다"가 아니라 상자 안에 몰려 있다는 판정이며, 증거 검토자 계산으로 차이 픽셀의 약 39%는 상자 밖(다시 렌더링한 두 그림 사이의 안티앨리어싱 차이)이다. 점선 색 픽셀은 범례 그림 139, 범례 없는 그림 87, 주석 끈 그림 0 → Mol* 이미지 패스에 점선이 담긴다.
- 그 밖: 주석 끈 뒤 `viewer_scene@2` 복원으로 저장된 주석 다시 그림(도구 호출 없음), 주석 중 M8 자연어 요청 막힘·`/zoom in`은 동작, 보고서 만들기 → 지식 탭 목록 "참조 주석 보고서", 다운로드 바이트 동일, 접촉 결과 없이 주석(셀 "접촉 결과 없음", 점선 0), 포켓 오버레이 배타(양방향, `@2` 복원 거절 시 오버레이 유지), 비교 시작 때 주석 꺼짐·켤 수 없음·`@2` 복원 거절, run 전환 때 주석 꺼짐·이전 run의 늦은 목록 응답 버림, 표시된 읽기 실패 3종 → 다시 읽기로 회복, OpenMM 최소화 1UBQ 소스에서는 이유만 보이고 숫자·컨트롤 없음.

### 회귀 (첫 고정 `b23cb10`, 같은 빌드)
- M15: `scripts/m15_offscreen_acceptance.py --root runs/m16-m15-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m16-regression --kbase <home>/Projects/kbase_kinase --out docs/qa/m16-annotations-20261001/m15-regression` → `acceptance: true`, 14/14, 단계 5개.
- M14: `scripts/m14_offscreen_acceptance.py --root runs/m16-m14-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/m16-regression --out docs/qa/m16-annotations-20261001/m14-regression` → `acceptance: true`, 15/15.
- M8–M13: `scripts/m13_offscreen_acceptance.py --root runs/m16-m13-regression-20261001 --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/m16-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m16-annotations-20261001/m13-regression` → `acceptance: true`, 필수 단계 17개·사례 28개, M11 수락 실행기 17/17, M12 수락 실행기 31/31. 하위 실행기 행의 `providerCallsZero`는 null(M15 회귀와 같은 형식, 외부 요청 0건).
- 셋 다 외부 요청 0건, 남은 프로세스 없음. 큰 텍스트 증거는 결정 0020대로 옮겼다(각 폴더의 `ARCHIVED-EVIDENCE.sha256`).
- 재고정 뒤 다시 돌리지 않았다: 세 실행기 모두 `annotation-flow.cjs`를 불러오지 않고, 제품 소스와 빌드 입력이 `b23cb10`과 같다(시도 2도 같은 빌드 ID).

### 기존 검사 스크립트
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다.
- `backend/tests/test_api.py`: 노출 도구 집합에 `annotate_reference_sites` 추가.
- `backend/tests/test_residue_numbering.py`: 사전 검사 훅이 있는 도구 집합 기대값에 `annotate_reference_sites` 추가(이 훅은 `bound`를 돌려주지 않아 호출 키 필드가 없다).
- `frontend/tests/report-library.test.cjs`: 보고서 종류 이름 1줄.
- `.codex/hooks/stop.py` 세 번째 pytest 그룹과 `scripts/test_codex_hooks.py` 기대 목록에 `scripts/test_m16_offscreen_acceptance.py`.
- M13·M14·M15 수락 실행기와 기존 흐름 스크립트는 고치지 않고 통과했다. 과거 검토 파일·해시는 건드리지 않았다.

## 고정 뒤 변경
- `71a3fa1`: `backend/tests/test_reference_site_annotation.py`에 테스트 1개 추가(증거 검토 권고). 1MQ4 전처리 구조 주석의 부위 표기·author 번호가 커밋된 1MQ4:A `match_residues` 발췌(제품 코드가 아닌 테스트 안 파싱)와 같고, 발췌에 잔기 이름이 없어 잔기 이름은 1MQ4 mmCIF를 gemmi로 따로 읽어 비교한다. 제품 코드 변경 없음. 실행 보고: 그 파일과 보고서 테스트 68개 통과, skip 0, ruff 통과(이 실행 출력은 커밋하지 않았다). 수락·회귀는 테스트 전용 변경이라 다시 돌리지 않았다.

## 대체한 과거 검증 범위
- M16은 공유 소스를 바꿨다: 백엔드 `api/app.py`(도구 허용 목록, capability, 방법 보고서 분기·목록, 읽기 라우트, 보기·그림 본문 파싱), `saved_scenes.py`, `workspace.py`, `config/tools.yaml`. 프런트 `app/page.tsx`, `MolstarViewer.tsx`, `PocketPanel.tsx`, `ViewerAgentPanel.tsx`, `lib/api.ts`, `lib/contracts.ts`, `lib/report-library.ts`, 디자인 토큰·스타일.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(886개, skip 0)와 M15·M14 수락 실행기, M13 수락 실행기 전체(M8–M12 포함)로 대체한다(모두 첫 고정 `b23cb10`). M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.

## 남은 일
- main 병합 완료(`0fb3426`). push하지 않았다.
- 새 미해결 문제(`docs/tracking/findings.md`): 뷰어가 `viewer_scene@2` 복원을 거부하는 경로는 실제 화면에서 지나가지 않음, 부위 이름표가 선택 가능한 Mol* 도형으로 남음, 다른 접촉 잔기는 회색 막대 모형으로 겹쳐 그림, 비교를 끝내면 패널의 주석 선택이 지워짐, 가져오기마다 세트 해시가 다름, 없음 이유의 한국어 이름이 화면과 보고서에서 다름. 지식 탭 체인 목록 항목은 다시 미뤘다.
