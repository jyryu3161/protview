# M15 참조 스냅샷과 잔기 번호 대응 완료 기록

- 판정: **완료** (2026-09-30)
- 브랜치: `dryforge/m15-numbering` (`phase/m15-reference-numbering` = main `e866d42`에서 분기). M14는 시작 전에 main에 병합되어 있었다(`da5e4bc`, 기록 `e866d42`). main 병합은 아직 하지 않았다(사용자 결정 대기).
- 고정 소스: `c1d824d`(`c1d824d8bb6400f98790b1196c04cf84c6950264`). 게이트·KLIFS 측정·수락 QA·회귀를 모두 이 고정에서 돌렸고 고정 뒤 소스 변경은 없다. 증거 커밋 `4737847`.
- 수락 증거: `docs/qa/m15-numbering-20260930/`(M15 수락, 게이트 `gate.txt`, KLIFS 측정, PDBe 번호 확인), `m14-regression/`(M14 탭 회귀), `m13-regression/`(M8–M13 회귀). 큰 증거는 결정 0020에 따라 Git 제외 artifacts로 옮겼다.
- 참조 원천: `../kbase_kinase` 커밋 `77354f94b844a8c64e7cd47691ac20a2e96214b3`, 작업 트리 깨끗함(읽기만). 외부 요청 0건, OpenRouter 호출 0회. 개발 중 네트워크 사용은 1MQ4 mmCIF를 RCSB에서 한 번 받은 것뿐이다(사용자 승인, `backend/tests/fixtures/public_1mq4.provenance.json`).

## 결과물
- 참조 스냅샷 가져오기 `scripts/import_reference_snapshots.py --from <kbase_kinase> [--dest .deps/reference]`: kbase `ref/manifest.json`에서 출처별 가장 최근 날짜 스냅샷(UniProt `entries.jsonl` 2026-09-15 `2026_03`, SIFTS `residues.jsonl`·`segments.jsonl` 2026-09-20, KLIFS `kinases.jsonl`·대조용 `match_residues.jsonl` 2026-09-19)만 복사한다. 복사 전 SHA-256·바이트·행 수를 대조하고 다르면 아무것도 바꾸지 않는다. 새 세트 폴더를 다 쓴 뒤 `active.json`을 rename 한 번으로 바꾼다. 세트 매니페스트(canonical JSON)의 SHA-256이 세트 해시다. 네트워크 없음.
- 서버 쪽 세트 읽기 `backend/mw/reference_snapshots.py`(`MW_REFERENCE_DIR`, 기본 `.deps/reference`): 호출마다 `active.json`을 한 번 읽어 그 세트에 고정(`PinnedSet`)하고, 파일 해시는 세트·파일 stat이 바뀔 때만 다시 확인한다. 대조용 파일은 명시적 opt-in 없이는 읽지 않는다.
- 해석기: SIFTS `backend/mw/sifts_mapping.py`(v1 `pdbe-residue-runs-v1`·v0 list, 엔티티별 PDBe 번호, 예외 행의 `uniprot_resnum`, 복원 교차 확인), 정렬기 `backend/mw/sequence_alignment.py`(Gotoh 전역, BLOSUM62, −10/−0.5, 끝 gap 벌점, 동점 M>X>Y, 최적 정렬 모호성 앞·뒤 DP, numpy만), KLIFS `backend/mw/klifs_numbering.py`(구역별 유일 연속 일치 + 두 번째 단계 `gapped_unique`).
- 도구 `map_residue_numbering`(값싼 동기 도구, `Run.call`): `backend/mw/tools/numbering.py`, 계산 `backend/mw/residue_numbering.py`, 결과 `residue_numbering_map@1`, 세트 기록 `reference_snapshot_set@1`. 레지스트리 사전 검사 훅(`ToolRegistry.register(..., precheck=)`, `Run._validated_bound`)이 모든 호출 경로에서 세트 고정 → 입력 검증 → 호출 키(세트 해시 포함) → 같은 세트로 실행 순서를 지킨다. `config/tools.yaml`, `workspace.py`, `SUPPORTED_TOOLS` 등록.
- 읽기 API `backend/mw/numbering_reads.py`: `/reference/snapshots`, `/reference/sifts_chains`, `/reference/uniprot`, `/runs/{id}/reference/pdb_id_hint`, `/runs/{id}/numbering_maps`, `/objects`의 대응 행 페이지, `/capabilities`의 `methods.residue_numbering`. 이벤트를 쓰지 않는다.
- 보고서 `backend/mw/numbering_reports.py`: `method_report_manifest@1`, `analysis_type: "residue_numbering"`, 증거 종류 `computed`·`reference_value` 분리, 렌더 `residue_numbering_markdown@1`.
- 화면: 지식·보고서 탭의 M14 "사용할 수 없음" 안내를 `frontend/src/components/NumberingPanel.tsx`(순수 로직 `src/lib/numbering.ts`)로 바꿨다. 스냅샷 상태, 대응 만들기(구조 → 체인 → PDB ID 제안 확인 → SIFTS accession 미리 채움 또는 UniProt 검색), 대응 목록과 체인 요약, 행 표(상태 필터·페이지), "이전 스냅샷 기준", 보고서 만들기. 만든 보고서는 `ReportLibraryPanel`의 `reloadToken`으로 목록이 다시 읽힌다. 스타일 `design/components.css`(`mw-numbering-*`)와 생성물.
- 테스트 자료: `backend/tests/fixtures/public_1mq4.cif`(RCSB 원본, CC0), 파생 구조 `structures_m15/`(label 없는 PDB, 삽입 코드, MSE mmCIF·PDB, 두 체인, 두 모델, 생성 스크립트와 출처), 참조 부분집합 `fixtures/reference/`(실제 스냅샷 행 발췌와 표시된 fixture, 출처 파일), 표시된 fixture 세트 빌더 `backend/tests/reference_fixture_set.py`.
- 테스트: 백엔드 `test_reference_snapshots`, `test_reference_fixture_set`, `test_sifts_mapping`, `test_sequence_alignment`, `test_klifs_numbering`, `test_residue_numbering`, `test_numbering_api`, `test_numbering_reports`. 프런트 `tests/numbering.test.cjs`. 스크립트 `test_import_reference_snapshots.py`, `test_m15_offscreen_acceptance.py`, `test_measure_klifs_numbering.py`.
- QA 도구: `frontend/tests/offscreen/numbering-flow.cjs`(`test:offscreen:numbering`, 모드 `numbering-empty`·`numbering-main`·`numbering-stale`), `scripts/m15_offscreen_acceptance.py`, KLIFS 측정 `scripts/measure_klifs_numbering.py`.

## 사용자 결정 (2026-09-30)
명세 확정 때 정한 것과 구현 중 추가한 것(★). 근거는 결정 0022·0023.
- 데이터: `kbase_kinase/ref` 가공 스냅샷(원본 바이트 아님, kinase 한정: SIFTS 약 658체인, 사람 kinase UniProt 542개)을 가져오기 명령으로 복사해 쓴다. 이 한계를 알고 택했다(결정 0022).
- 방법: SIFTS + 로컬 전역 정렬, 둘 다 가능하면 둘 다. 둘이 같을 때만 대응됨, 한쪽만이면 충돌. 한 방법만 쓸 수 있으면 그 답 + "교차 확인 없음"과 이유.
- PDB ID는 파일에서 제안하고 사용자가 확인한 뒤에만 쓴다. SIFTS 잔기 키는 label + author + 삽입 코드, label이 없으면 author만(기록). SIFTS 체인은 author만(기록).
- SIFTS accession을 정렬에 미리 채우고, 사용자가 다른 accession을 고르면 SIFTS를 뺀다. UniProt accession은 스냅샷 항목에서만 고른다.
- 정렬 기준 일치율 90%, 정렬 범위 50%(조정 가능). 잔기 종류 불일치는 대응됨 유지 + 표시.
- KLIFS 번호는 구역별 정확한 연속 일치가 유일할 때만. 대응됨 행(불일치·교차 확인 없음 포함)에만 붙인다. KLIFS 라이선스 `none-stated`는 항상 표시하되 사용은 막지 않는다(처음 "로컬만" → 이후 외부 전송 허용으로 바꿈).
- 스냅샷 버전은 출처별 최신 하나, 다시 가져오면 사용 중 세트 교체, 이전 세트로 만든 대응은 "이전 스냅샷 기준".
- 대상은 `structure`·`prepared_structure`. 정렬기는 자체 구현(새 의존성 없음, numpy 허용). 화면은 지식 탭 표와 보고서(뷰어 강조는 M16). M13 흐름 템플릿은 추가하지 않는다. 테스트용 RCSB 다운로드는 1MQ4 한 번. 보고서는 참조값과 계산값을 분리한다.
- ★ KLIFS 두 번째 단계: 해결되지 않은 구역 중 앞뒤 구역이 모두 해결된 구역만, 사이 구간에서 순서 유지 배치가 유일할 때 `gapped_unique`로 번호를 준다.
- ★ 정렬 크기 상한 20,000,000칸 → `alignment_too_large`.
- ★ HETATM 변형 잔기(MSE 등)는 번호 대응에서만 사슬 잔기로 넣는다.
- ★ 최적 정렬마다 위치가 달라지는 잔기는 `alignment_ambiguous`(1MQ4 S388이 이 규칙 없이는 UniProt 403에 놓였다).

## 커밋

| 작업 | 커밋 |
|---|---|
| T1 참조 스냅샷 가져오기·서버 세트 읽기 | `e90ad81` (병합 `6b4c6eb`) |
| T2 전역 정렬기 | `71171fd` (병합 `d05c2ee`) |
| T3 KLIFS 포켓 → UniProt 표, 두 번째 단계 | `fc1796a` (병합 `715cb04`), `04d5738` (병합 `686a3cb`) |
| T4 SIFTS 해석기 | `4333d91` (병합 `e819221`) |
| T5 테스트 구조·참조 fixture·PDBe 번호 확인·KLIFS 측정 초안 | `01d3e2c` (병합 `82464dd`) |
| T6 번호 대응 도구·사전 검사 훅, 모호성 규칙, 없음 이유 전부 보존·서열 밖 SIFTS 위치 | `106586f`, `7e94fcd`, `bb9258c` (병합 `6afa2ff`) |
| T7 읽기 API·capability | `7b16e0c` (병합 `5357bae`) |
| T8 보고서 | `c49f331` (병합 `59c9e1a`) |
| T9 프런트 API·순수 로직·목록의 체인 요약 | `7eefc1e` |
| T10 지식 탭 번호 대응 화면 | `1caddba` (병합 `c08e7ad`) |
| T11 오프스크린 흐름·M15 수락 실행기 | `83535f1` (병합 `f378626`) |
| T12 독립 코드 검토 수정 = 고정 소스 | `86397ef` (병합 `c1d824d`) |
| T13 게이트·KLIFS 측정·수락 QA·회귀 증거 | `4737847` |
| T15 완료 기록·결정 0022·0023·프로젝트 문서 | 이 기록과 같은 커밋 |

## 검토 (Opus 5.5, 구현하지 않은 서브에이전트)
- T6 중간 명세 검토: **통과**. 권고는 T6 안에서 반영했다(`bb9258c`: 방법별 없음 이유를 `absent_reasons` 전체로 보존하고 첫 이유를 `absent_reason`에, 스냅샷 서열 길이를 넘는 SIFTS 위치는 `sifts_position_outside_sequence`, 완전히 일치하는 SIFTS 행이 둘 이상이면 `sifts_ambiguous_residue_row`). 같은 시기에 1MQ4 S388로 찾은 모호성 문제는 사용자 결정으로 `7e94fcd`에 반영했다.
- T12 독립 코드 검토: **수정 필요**. 모두 `86397ef`에서 고쳤다.

| 지적 | 처리 (`86397ef`) |
|---|---|
| Stop 훅과 `docs/standards.md` 게이트에 M15 스크립트 테스트와 `numbering-flow.cjs` 검사가 없음 | 추가(`scripts/test_codex_hooks.py` 기대 목록 포함) |
| KLIFS 두 번째 단계가 "가장 가까운 해결 구역" 사이에서도 돌아 명세(바로 앞·뒤 구역)보다 넓음 | 바로 인접한 두 구역이 모두 해결된 경우로 좁힘 |
| 해시는 맞지만 내용 형식을 해석할 수 없는 세트가 사용 가능으로 보임 | `/capabilities`·읽기 API가 해석까지 확인해 `snapshot_invalid` |
| 보고서가 잔기 불일치를 종류별로 주장하지 않음 | 체인별 (구조 잔기 이름, UniProt 글자) 종류별 개수 주장 추가 |
| 화면의 일치율·정렬 범위 표시가 보고서 반올림과 다름 | 소수 한 자리 `ROUND_HALF_UP`(10진 문자열 기준) |
| 융합 SIFTS 체인에 화면이 accession을 보내 `input_invalid`가 남 | 그런 체인은 SIFTS만, accession을 보내지 않음 |
| 대응 목록 응답에 `alignment.aligned_strings`가 들어감, 같은 호출의 재검증이 계획을 다시 만듦 | 목록에서 뺌(객체에는 있음), 인자가 같으면 고정한 계획 재사용 |
| 검증된 세트 캐시가 세트 폴더마다 항목을 쌓음 | 폴더마다 최신 항목 하나만 |

- T14 독립 증거 검토(코드 검토자와 다른 인스턴스): **approve**, 막는 지적 없음. 권고는 아래처럼 기록했다.

| 권고 | 처리 |
|---|---|
| "이전 스냅샷 기준" 사례의 두 번째 세트는 가져오기 명령이 아니라 테스트 도우미(`backend/tests/reference_fixture_set.py`)가 표시된 fixture 행으로 직접 만든 세트다 | 기록(아래 수락 QA 해석). 가져오기 명령의 교체는 `scripts/test_import_reference_snapshots.py`가 다룬다 |
| 세트 해시에 `imported_at`이 들어가 같은 파일을 다시 가져와도 해시가 달라진다(측정 세트 `aa21ead9…`와 수락 세트 `1ad8413f…`는 파일 바이트가 같음) | 기록(설계대로, `docs/engineering-notes.md`) |
| 측정 텍스트 머리글에 "draft"가 남음 | 기록. 스크립트에 고정된 문자열이며 수치는 고정 소스로 다시 잰 최종값(초안과 바이트 동일). `docs/tracking/findings.md` |
| M13 회귀 행 중 하위 실행기·회귀 행 7개에 `providerCallsZero`가 없음(null) | 기록. M14 회귀 증거와 같은 형식이고 그 행들의 외부 요청은 0건 |

## 게이트 (고정 소스 `c1d824d`, `docs/qa/m15-numbering-20260930/gate.txt`, 2026-09-30 04:19–04:35 UTC)

| 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest backend/tests -q -rs` | exit 0, 806 passed, 0 skipped(963초). 실제 kbase 스냅샷을 고정 절대 경로로 읽는 KLIFS 테스트 2개가 포함된다(경로가 없으면 skip, `docs/tracking/findings.md`) |
| `ruff check backend/mw backend/tests scripts .codex/hooks design/build_tokens.py` | exit 0 |
| 스크립트 pytest 8개 파일(`docs/standards.md` 줄) | exit 0, 131 passed |
| `node --check` `pocket-flow`·`workflows-flow`·`tabs-flow`·`numbering-flow` | exit 0 ×4 |
| `npm --prefix frontend run test:events` | exit 0, 180 pass, 0 fail, 0 skipped |
| `npm --prefix frontend run typecheck` → `build` | exit 0 → exit 0 |

## KLIFS 번호 측정 (`klifs_measurement.txt`·`.json`)
- 명령: `.venv/bin/python scripts/measure_klifs_numbering.py --reference-dir .deps/reference --out docs/qa/m15-numbering-20260930/klifs_measurement.txt`, 고정 소스, 네트워크 없음. 세트 `aa21ead9…3317`. 결과는 T5 초안과 바이트 동일해 초안 폴더는 지웠다. 이것은 대조용 측정이며 제품 결과가 아니다.
- 방법: KLIFS 구조별 표(`match_residues`, 대조 전용)의 author 번호를 SIFTS로 UniProt 위치로 옮겨, 우리 KLIFS 표가 같은 KLIFS 번호에 준 UniProt 위치와 비교한다.
- 비교 구조 279개(표 318행 중 39개 건너뜀: SIFTS segment 없음 18, KLIFS 항목 여러 개 14, SIFTS 체인 accession 아님 4, SIFTS 조회 실패 3), 비교 위치 22,618개: **일치 22,211(98.2%)**, 불일치 407, 우리 번호 없음(ours_missing) 852, 우리만 번호 있음(ours_extra, KLIFS가 그 구조에 잔기를 두지 않은 자리) 104, 숫자 아닌 `Xray_position` 제외 244. label 불일치 0.
- 불일치 407개 중 394개가 5개 구조에 몰려 있다: 7TYM:A 84, 6TLJ:S 81, 8E06:A 81, 6CD6:D 76, 8U7L:A 72. 불일치 전체에서 우리 UniProt 글자는 항상 KLIFS 포켓 글자와 같고(0/407 다름), KLIFS `Xray_position` 자리의 잔기가 포켓 글자와 다른 경우가 318/407이다. 증거 검토자는 이 5개 구조를 KLIFS 쪽 산물로 판단했다. 예외로 ATR 5YZ0:A의 `linker.49` 1개는 포켓 앞뒤에 N이 겹쳐 생긴 한 칸 차이로 보이며, 어느 쪽이 맞는지 정하지 않았다(`docs/tracking/findings.md`).
- 번호 없음 852개는 주로 b.l 337, a.l 306, VIII 118, I 60 구역이다. KLIFS가 번호를 둔 위치 기준 적용률은 약 96.4%(22,618 ÷ (22,618 + 852))다. 두 번째 단계(`gapped_unique`)는 1,613 일치·17 불일치를 더했다.
- 정렬 시간(구현 중 로컬 측정, 로그는 커밋하지 않음): 1MQ4 체인 A 크기(261 × 403) 약 0.01초, 상한 근처 4,000 × 5,000 약 1.3초(모호성 앞·뒤 계산 포함). 값싼 동기 도구로 둘 수 있는 범위다. 테스트(`test_sequence_alignment.py`의 `test_near_cap_runs_within_cheap_budget`)는 상한 근처가 10초 안에 끝나는지만 검사한다.

## PDBe 번호 확인 (`pdbe_label_check.txt`)
1MQ4 체인 A 사슬 잔기 261개 모두 kbase SIFTS의 PDBe 번호 = mmCIF `label_seq_id`, 잔기 이름 같음(관측 261, 미관측 11, `_entity_poly_seq` 272행과도 일치). 명세의 착수 전 확인 조건을 만족해 SIFTS 키를 설계대로 썼다. T5 초안을 내용 그대로 옮겼고, 이를 만든 스크립트는 저장소에 없다.

## 수락 QA

### M15 수락 (`scripts/m15_offscreen_acceptance.py`, 2026-09-30 04:36 UTC)
- 명령: `.venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/final --out docs/qa/m15-numbering-20260930 --kbase <home>/Projects/kbase_kinase`
- 빌드 `mc98KdfOBAIUwmBLTIM0q`(소스 도장 일치, gitHead `c1d824d`). Electron 44.4.5, Chrome 152, `isOffscreen()===true`, WebGL.
- 결과: `verdict: pass`, `acceptance: true`, 사례 14/14(N-no-snapshot, N-confirmed-sifts, N-klifs-oracle, N-status-filter, N-conflict-row, N-alignment-only, N-below-identity, N-prepared, N-report, N-read-retry, N-run-switch, N-late-response, N-stale, S-no-egress), 단계 5개(numbering-empty, reference-import, numbering-main, reference-reimport, numbering-stale), 첫 시도. 외부 요청 0건, 제공자 호출 0회, 남은 프로세스 없음.
- 참조 폴더: 빈 폴더(`not_installed`)로 시작 → 실제 kbase 가져오기 세트 `1ad8413f…7c0` → 표시된 fixture 세트 `8e2307d4…9e`.
- 관찰 값 요약(run A `run_dafef30c2161495094340349f1f80395`, run B `run_6fb6e5503e374f9c8929abe564d049e0`): PDB ID 확인 대응은 1MQ4 체인 A 261행 중 대응됨 260, 충돌 1(S388, `one_method_only`, 양쪽 답 표시). PDB ID 없이 accession만 고른 대응은 교차 확인 없음 표시, 대응됨 260, 대응 없음 1(S388 `alignment_ambiguous`). 다른 kinase accession은 261행 모두 대응 없음(scientific_null). 화면의 KLIFS 번호는 커밋된 1MQ4:A `match_residues` 발췌(85행)와 같다(GK.45·hinge·xDFG 포함). 보고서 다운로드 바이트 SHA-256이 백엔드와 같다.
- 해석:
  - N-stale의 두 번째 세트는 가져오기 명령이 아니라 `backend/tests/reference_fixture_set.py`가 커밋된 fixture 행으로 수락 참조 폴더에 직접 쓰고 활성화한 표시된 세트다(`imported_at`에 표시 태그). 목적은 세트 해시가 바뀐 뒤 기존 대응의 "이전 스냅샷 기준" 표시를 보는 것이다. 가져오기 명령의 원자적 교체·실패 시 무변경은 `scripts/test_import_reference_snapshots.py`가 다룬다.
  - `--kbase`를 절대 경로로 준 것은 실행기 기본값(`<repo>/../kbase_kinase`)이 git worktree에서 틀린 경로가 되기 때문이다(주 체크아웃에서는 기본값과 같은 곳이다).

### M14 탭 회귀 (`scripts/m14_offscreen_acceptance.py`)
- 명령: `.venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m15-m14-regression-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m14-regression --out docs/qa/m15-numbering-20260930/m14-regression`
- 결과: `acceptance: true`, 15/15, 같은 빌드, 외부 요청 0건, 남은 프로세스 없음.

### M8–M13 회귀 (`scripts/m13_offscreen_acceptance.py` 전체)
- 명령: `.venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m15-m13-regression-20260930 --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/m13-regression --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m15-numbering-20260930/m13-regression`
- 결과: `acceptance: true`, 필수 단계 17개·사례 28개 통과, M11 수락 실행기 17/17, M12 수락 실행기 31/31. 같은 빌드, 외부 요청 0건, 남은 프로세스 없음. 하위 실행기·회귀 행 7개의 `providerCallsZero`는 null(M14 회귀와 같은 형식, 외부 요청 0건).
- 큰 텍스트 증거는 결정 0020대로 옮겼다(각 폴더의 `ARCHIVED-EVIDENCE.sha256`). M15 수락 폴더에서는 보고서 JSON 다운로드 1개(589,907 bytes).

### 기존 검사 스크립트
이번 변경으로 기대가 바뀐 기존 검사만 최소로 고쳤다.
- `frontend/tests/offscreen/tabs-flow.cjs`: M14의 지식·보고서 탭 "사용할 수 없음" 사례를 "번호 대응 화면(`section.mw-numbering`)과 보고서 목록이 있고 `section.mw-unavailable`이 없음"으로 바꿨다(`knowledgeScreen`). 단백질 공학·리간드 설계·탐색의 안내·무요청 확인은 그대로이며, 탭 패널 컨트롤 0개 검사는 이제 두 탭 모두에 적용된다.
- `scripts/m14_offscreen_acceptance.py`: 문서 문자열과 T-unavailable 사례 설명만 바꿨다(판정 로직 불변).
- `.codex/hooks/stop.py` 세 번째 pytest 그룹과 `scripts/test_codex_hooks.py` 기대 목록에 M15 스크립트 테스트 3개, `docs/standards.md` 게이트에 스크립트 테스트 3개와 `node --check numbering-flow.cjs`를 추가했다.
- M11·M12·M13 수락 실행기와 나머지 흐름 스크립트는 고치지 않고 통과했다. 과거 검토 파일·해시는 건드리지 않았다.

## 대체한 과거 검증 범위
- M15는 공유 소스를 바꿨다: 백엔드 `runtime/orchestrator.py`(사전 검사 훅, 호출 키에 고정 상태 추가 — 훅이 없는 도구는 기존 키·이벤트 그대로), `tools/registry.py`, `workspace.py`, `api/app.py`(capability, 방법 보고서 분기, `/objects` 페이지), `config/tools.yaml`. 프런트 `app/page.tsx`, `WorkspaceTabs.tsx`, `ReportLibraryPanel.tsx`, `workspace-tabs.ts`, `report-library.ts`.
- 이 소스 기준의 현재 검증은 전체 백엔드 pytest(806개, skip 0)와 위 M14 회귀·M8–M13 회귀(고정 `c1d824d`)로 대체한다. M14 수락의 지식 탭 "안내 문구·이유·여는 단계·컨트롤 없음" 확인은 안내가 없어졌으므로 위 `knowledgeScreen` 확인으로 대체한다. M13 수락 실행기가 돌리지 않는 과거 범위는 M13 완료 기록의 "대체한 과거 검증 범위"와 같다.
