# M28 T1 착수 확인 — 기준선·자료·M7·사례 사슬·시간·간헐 실패·M20 보고서·미해결 문제·설치·훅·감사 어댑터 (2026-10-11)

계획 T1의 (a)–(k)를 코드 전에 잰 기록이다. 기준은 작업 브랜치 `dryforge/m28-final-verification`의 `287a37a8`(= main, M27 병합 `b7d7f49` 포함)이다. 저장소에 더한 것은 이 폴더의 `preflight.md`·`m7_probe.py`·`m7-probe.txt`·`network-ledger.txt`뿐이고 제품 코드(`backend/mw`·`frontend`·`config`·`scripts`·`.codex`)·시험·하네스는 바꾸지 않았다. 측정 산출물은 Git 제외 폴더 `runs/m28-preflight-20261011/`(아래 `<P>`)에 두었고 지우지 않았다. 이 문서에는 실제 kbase 문구가 없고(해시·ID·개수만), 사용자 절대 경로는 `<repo>`(저장소 루트)·`<home>`(사용자 홈)으로 적었다. Python은 모두 `.venv/bin/python`(CPython 3.11.11)이다. 외부 요청은 0건이고 `.env`는 열지 않았다(`os.lstat` 모드만).

조사의 일부((d) 사례 사슬, (e) 시간, (g) M20 보고서, (k) 감사 어댑터)는 읽기 전용 조사 서브에이전트(Opus 5.5, 파일 쓰기·서비스·시험 실행 없음) 넷이 코드·증거를 읽어 정리했고, 이 문서의 결론에 쓰인 핵심 사실은 직접 다시 확인했다(각 절에 "직접 확인" 표시).

## 요약 (항목별 결론)

| 항목 | 결론 | 명세와 다른 점 |
|---|---|---|
| (a) 기준선 | 작업 트리 깨끗함, 호출 키 해시 파일 27개 blob = `BASELINE_BLOBS`(digest 일치), `also_hashed_files` 11·`hashed_files` 6 SHA-256 일치, 골든 `--check` 둘 exit 0, 호출 키 재기록 `cmp` exit 0, 기본 참조 폴더 둘 없음, 8000/3000 비어 있음, `.env` 0600 | 없음 |
| (b) 자료 | 보관 반응 세트 `1a7b131a…` 파일 4개 해시·바이트·행 일치, kbase HEAD `77354f9`·핀 3개 일치, 전례 가져오기 격리 설치 2회(소켓 시도 0, 파일 SHA-256 4개 같음), M15 세트 `aa21ead9…`에 1M17 A·1FIN A·C·1MQ4 A 잔기 대응과 SIFTS 구간·KLIFS·UniProt 행 있음, 입력 fixture 해시·출처 기록 일치 | 없음 |
| (c) M7 사전 검사 | 8구조 × 물 정책 2 = 16회, 1UBQ만 통과(중원자 602, 제외 58), 나머지 이유 코드가 인계 기대와 문자 그대로 같음 | 없음 |
| (d) 사례 사슬 | A1–C7·X1–X6 모두 기존 하네스 단계(복사)·oracle(require)·QA 도우미로 이을 수 있음. 정의 항목이 통과 경로를 잃는 곳 없음. 권고: A2 = 1M17 AQ4(7필드 확정), C1 = 1A30, C2–C6 = 1UBQ tiny 6후보 집합, fixture 서버는 두 목표·M24 전송 모두 받음, A6은 annotation M10 재사용 | **B2 입력 조합**(고정 교체 + 반응 SMARTS를 함께 쓰는 작은 기존 입력 없음), 물 정책 기본값 두 가지(도구 `keep_all` / 화면 `strip_all`) |
| (e) 시간 | fixture 약 25–40분, live 6–12분, 회귀 약 75분. GA 설정 둘 권장값 확정(B5: seed 11 고정·세대 2→3·무작위 0.2→0.5, 예약 6·8; C4: seed 21 고정·개체 4→6·세대 3→2·무작위 0.25→0.5, 예약 22·22). fixture 증액 클릭 5번 | **명세 표 순서대로 한 run에서 돌리면 B7·C6이 `budget_blocked`**(루프는 증액 경로 없음, 증액은 부족분만) → 루프를 GA·일괄보다 먼저 도는 순서 필요. C 분기·live B는 단위 여유 0 |
| (f) 간헐 실패 | 네 가지 모두 원인이 시험 쪽임을 코드로 확인. `backend/mw`에 psutil 명령줄 읽기 0건. 제품 코드 변경 불필요 | 없음 |
| (g) M20 보고서 | `mutation_reports.py` 한 파일로 가능(해시 파일·닫힌 집합·고정 문장·결과 형식 불변). **단 "새 보고서 전부 @2"는 수정 금지 기준선 비교 시험을 깨므로 "인용이 있을 때만 @2"가 필요** | 명세 §10.2 문언("새 보고서에 쓰고")의 해석 결정 필요 |
| (h) 미해결 문제 | 정규식 `(?m)^## ` 128절, 제목에 `(해결됨` 10절(그 밖에 `(일부 해결` 1절) | 없음 |
| (i) 설치 준비 | Python 핵심 의존 7개 범위 지정·잠금 없음(과학 6개만 정확 고정), npm 잠금 항목 288개 중 `resolved` 287개 모두 `registry.npmjs.org`·무결성 해시 있음. **README의 `python3 -m venv`는 이 컴퓨터에서 Python 3.10.9(anaconda)를 가리켜 설치가 실패할 경로** | README 개정(T4) 필요 |
| (j) Stop 훅 | 18그룹 동시 1회: 모두 exit 0, 6,037 passed, 최장 373.6 s(제한 480 s), 나머지 그룹 370.7 s. M28 새 시험(T3 백엔드, T5–T8 `scripts/test_m28_*`)은 나머지 그룹에, T9가 다시 재서 440 s를 넘으면 나눔 | 이번 측정이 M27 게이트보다 5–15% 느림(여유 약 106 s) |
| (k) 감사 어댑터 | 2계열 20종(점검 1 + 방법 19) 모두 어댑터 가능, 만들 수 없는 종류 없음. **단 점검 보고서·interface_sasa는 제품의 다시 열기가 Markdown 재생성(점검은 주장 재검증도)을 하지 않아 §7 1번 전제가 이 두 종류에 성립하지 않음** | 범위 표 기록 또는 감사 보완 결정 필요 |

## (a) 기준선

**작업 트리·HEAD.** `git rev-parse --show-toplevel` = `<repo>`, `git branch --show-current` = `dryforge/m28-final-verification`, HEAD `287a37a8277394cdfa70733b98fb1cf9399379c9`(2026-10-11T06:57:19+09:00), 시작 때 `git status --porcelain` 0줄. (이 문서를 쓰는 동안 바뀐 것은 이 폴더의 새 파일뿐.)

**호출 키 해시 파일 27개.** `backend/tests/test_kinase_precedents_ast.py`의 `HASH_FILE_PATTERN`(`docking_worker\.py|docking_constants\.py|openmm_mutation_worker\.py|mutation_model_constants\.py|mutation_model_math\.py|mutation_candidates\.py|ligand_ga_|sequence_ga_|docking_batch_`)으로 `backend/mw/**/*.py`를 글롭하면 27개이고 `BASELINE_BLOBS` 키 집합과 같다. `git ls-tree HEAD <27>` → 27줄, 모드 모두 100644, HEAD blob·작업 트리 blob(`sha1("blob <n>\0"+bytes)`) 모두 `BASELINE_BLOBS`와 일치(불일치 0), 목록 digest `3a2fc4093bbb61b9…` = `BASELINE_DIGEST`.

**골든 `golden_call_keys.json`이 해시하는 파일.** `also_hashed_files` 11개(`docking_batch_constants.py`, `jobs/docking_batch_worker.py`, `jobs/ligand_ga_worker.py`, `jobs/openmm_worker.py`, `ligand_ga_{bundle,constants,inputs,jobs,reads,reports}.py`, `tools/openmm_method.py`)와 `hashed_files` 6개(`docking_constants.py`, `jobs/docking_worker.py`, `jobs/openmm_mutation_worker.py`, `mutation_candidates.py`, `mutation_model_constants.py`, `mutation_model_math.py`)의 현재 SHA-256이 기록값과 모두 같다(11/11, 6/6).

**골든 셋.**

| 명령 | exit | 결과 | 시간 |
|---|---|---|---|
| `.venv/bin/python backend/tests/fixtures/jev/golden_science_m24.py --check` | 0 | "golden_science_m24.json matches a fresh recording" | 10.1 s |
| `.venv/bin/python backend/tests/fixtures/jev/prototype_golden_egress.py --check` | 0 | "golden_egress_events.json matches a fresh recording" | 1.1 s |
| `.venv/bin/python backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py <P>/golden-keys-runs <P>/golden_call_keys.rerecord.json` (실제 qvina·OpenMM·PDBFixer·M17) | 0 | 재기록 파일 작성 | 65.3 s |
| `cmp <P>/golden_call_keys.rerecord.json backend/tests/fixtures/sequence_ga/golden_call_keys.json` | 0 | 바이트 동일, SHA-256 `7bb3594cf5f023af…` | — |

커밋된 골든 SHA-256: `golden_science_m24.json` `78d4cf12078c443b…`, `golden_egress_events.json` `a662f8ecbb311d5e…`, `golden_call_keys.json` `7bb3594cf5f023af…`. 기록기가 쓰는 `runs/golden-*` 남은 폴더 0. 재기록 출력은 커밋된 파일을 덮지 않도록 `<P>`에 썼다(두 번째 인자). 끝난 뒤 `git status`는 이 폴더 말고 변화 없음.

**참조 폴더.** `ls .deps` → `docking fpocket prolif qvina reaction_qa reference`. `ls -d .deps/precedent_reference .deps/reaction_reference` → 둘 다 "No such file or directory". 이 문서의 모든 측정 뒤에도 같다(아래 (b)의 가져오기 시험은 `--dest <P>/precedent-{1,2}`).

**포트.** `lsof -nP -iTCP:8000 -sTCP:LISTEN`·`-iTCP:3000` → 둘 다 exit 1(리스너 없음). 이 단계에서 서비스는 띄우지 않았다.

**버전·환경.**

| 항목 | 값 |
|---|---|
| OS | macOS 15.6 (24G84), arm64 |
| Python(.venv) | CPython 3.11.11 (`.venv/pyvenv.cfg`: uv 0.8.0으로 만든 venv, `include-system-site-packages = false`, venv 안에 pip 없음) |
| `python3.11` | `<home>/.pyenv/shims/python3.11` → `<home>/.pyenv/versions/3.11.11/bin/python3.11`, 3.11.11 darwin |
| `python3` | `<home>/anaconda3/bin/python3`, **3.10.9** ((i) 참고) |
| 과학 핀(.venv) | psutil 7.2.2, gemmi 0.7.5, numpy 2.4.6, openmm 8.6, pdbfixer 1.12.0 |
| Node / npm | v24.3.0 / 11.4.2 |
| Electron(`frontend/node_modules/electron`) | 44.4.5 (내장 Chrome 152.0.7977.130, Node 24.21.0; `ELECTRON_RUN_AS_NODE=1 … -p process.versions`) |
| Next / Mol* | 15.5.26 / 5.11.0 |
| git | 2.33.0 |
| 디스크 여유 | 688 GiB (`df -k .` 가용 721,022,192 KiB, 사용 63%) |
| `runs/` · `frontend/tests/offscreen/artifacts/` | 20,695,132 KiB(약 19.7 GiB) · 51,401,788 KiB(약 49.0 GiB), 지우지 않음 |
| `.env` | `os.lstat`: 모드 `0o600`, 일반 파일, 심볼릭 링크 아님(내용 읽지 않음) |

**외부 요청 장부.** `network-ledger.txt`를 "새 외부 요청 0" 머리말과 줄 형식(T13 설치 호스트·T16 실호출이 덧붙임)으로 만들었다.

**결론.** 기준선 이상 없음. 멈출 조건 없음.

## (b) 자료

**보관된 M26 실세트 `.deps/reaction_qa/import2`(읽기 전용).** 제품 함수 `mw.reaction_snapshots.pin_active_set(<root>)`(읽기만, 메모리 캐시)로 고정하고, 매니페스트에 적힌 파일을 따로 다시 해시했다.
- `active.json` SHA-256 `358f743328a71ba6…`, 키 `schema`·`set_hash`. 세트 해시 `1a7b131a102684f1f735bb96e6461bd13796c3b13a6d2203d289299cb57acf47` = sha256(매니페스트 2,505 B).
- 파일(바이트·행·SHA-256 앞 16자, 모두 일치): M-CSA `entries.jsonl` 5,310,675 B·1,003행·`c373557bb89315d9`, UniProt 기능 `entries.jsonl` 2,401,807 B·1,622행·`c4e4322de03e665a`, Rhea `reactions.jsonl` 8,297,875 B·18,611행·`80109f69b5d614b9`, 요청 기록 16,846 B·22행 — 4/4 일치, 합계 16,010,357 B. 출처 날짜 셋 모두 2026-10-09, 라이선스 `CC-BY-4.0`.
- `mw.reaction_knowledge.capability(<root>)` → `available: true`, `reason_code: null`.
- A8·C1용 격리 복사는 T6/T8이 만든다(원본은 그대로 둔다).

**로컬 kbase.** 읽기 전용 git(`GIT_OPTIONAL_LOCKS=0 git -C ../kbase_kinase …`): HEAD `77354f94b844a8c64e7cd47691ac20a2e96214b3`, `dist`를 마지막으로 바꾼 커밋 `43a935e4637d986700fa61a4deae8300e405edb7`(2026-09-21T00:05:28+09:00), `status --porcelain` 0줄. `dist/manifest.json` 2,074 B, SHA-256 `d61d9981625a1104…`(M27 착수 확인 값과 같음). `meta`의 `schema_version`·`effect_rules_version`·`vocab_version`(134자)이 `backend/mw/precedent_constants.py`의 `KBASE_PINS`와 셋 다 같다(상수 모듈을 파일 경로로 불러 비교, `mw` import 없음). `kb_version` `kbv1:ae11f41d19e5bef9`.

**전례 가져오기 시험 설치(격리, 네트워크 0).** 명령 `env -u MW_PRECEDENT_REFERENCE_DIR .venv/bin/python <scratch>/nosock_run.py scripts/import_precedent_snapshots.py --from <home>/Projects/kbase_kinase --dest <P>/precedent-<n> --yes`(n = 1, 2; `nosock_run.py`는 `socket.socket`·`socket.create_connection`을 막고 시도를 세는 스크래치패드 래퍼, 커밋하지 않음).

| 설치 | exit | 소켓 시도 | 세트 해시 | `imported_at` | 행(moves·flagged·references·서지) | `records_hash_verified` | `dirty` |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 0 | `95ecda7170eb185e…` | 2026-10-11T06:34:04Z | 891·885·555·252 | 891·885·555, `references_without_hash` 0 | false |
| 2 | 0 | 0 | `ceebb6aade0356e5…` | 2026-10-11T06:34:06Z | 891·885·555·252 | 891·885·555, 0 | false |

두 세트의 파일 4개 SHA-256이 서로 같고 kbase 원본과도 같다: `dist/moves.jsonl` `2ad983addd8ff3fe…`(4,293,797 B), `dist/moves_flagged.jsonl` `0699270358cfb4b2…`(5,544,181 B), `dist/references.jsonl` `70a09223477d77bf…`(4,357,502 B), `pubmed/2026-09-18/documents.jsonl` `8bad29967d065d13…`(76,396 B). 세트 해시만 `imported_at` 때문에 다르다(설계대로). 각 세트에서 `set_hash == sha256(manifest.json)`. 기본 폴더 `.deps/precedent_reference`는 만들어지지 않았다. 가져오기 출력은 숫자·해시·경로만이며 `<P>/precedent-import-{1,2}.txt`에 있다(경로가 들어 있어 커밋하지 않음).

**M15 활성 세트 `.deps/reference`.** `mw.reference_snapshots.pin_active_set(.deps/reference)` → 세트 해시 `aa21ead9930f82ebea3a2acf976449d9b1c6280ed17206d74d8cb9dc3f923317`. 파일: UniProt `entries.jsonl` 542행, SIFTS `residues.jsonl` 658행·`segments.jsonl` 537행, KLIFS `kinases.jsonl` 555행(제품용)·`match_residues.jsonl` 318행(대조용).
- SIFTS `residues.jsonl`: `1M17:A`, `1FIN:A`, `1FIN:C`, `1MQ4:A` 행이 모두 있고 `status: ok`.
- SIFTS `segments.jsonl`: `1M17`(accession P00533), `1FIN`(P24941와 사이클린 P20248, 구간 4개), `1MQ4`(체인 A, O14965).
- KLIFS `kinases.jsonl`·UniProt `entries.jsonl`: P00533·P24941·O14965 각 1행.

**입력 fixture 존재와 출처.**

| 파일 | SHA-256 앞 16자 | 출처 기록 | 기록과 일치 |
|---|---|---|---|
| `public_1m17.cif` | `849bd2548dffb7dd` | `public_1m17.provenance.json`(RCSB 원본, 2026-10-10, M27 장부) | 예 |
| `public_1fin.cif` | `dfe5da37b2e28d3d` | `public_1fin.provenance.json`(2026-10-10) | 예 |
| `public_1mq4.cif` | `0f99d0c2693225ab` | `public_1mq4.provenance.json`(2026-09-30) | 예 |
| `public_1s9i.cif` | `3db038cdfa23f9d2` | `public_1s9i.provenance.json`(2026-10-09, M26 장부) | 예 |
| `public_1a30.cif` | `40ab7868e9b40c19` | `public_1a30.provenance.json`(2026-10-09) | 예 |
| `public_1a4i.cif` | `afa6bd62e3183d1e` | `public_1a4i.provenance.json`(2026-10-09) | 예 |
| `public_1ubq.cif` | `056f98710cb2b36f` | `docs/M7_OPENMM.md` 40행(SHA-256 기록, provenance.json 없음) | 예 |
| `public_1hsg.cif` | `d2ba73b5c4be05c4` | `docs/M7_OPENMM.md` 40행·`docs/METHOD_DEPENDENCY_PROBE.md` 46행 | 예 |
| `chemical/prolif-vina-rec.pdb` | `745bd4726ba956e2` | `chemical/PROVENANCE.json`(ProLIF 2.2.2 wheel 예제 `examples/vina`, 라이선스 `PROLIF-LICENSE.txt`) | 예 |
| `chemical/prolif-vina-output.sdf` | `810b8c714edd3140` | 같음 | 예 |
| `docking/public-derived-parent-record0.sdf` | `34a5c499e612156a` | `docking/SYNTHETIC-PROVENANCE.md` 19행(ProLIF 포즈 0번 기록, 제목 줄만 `PUBLIC-DERIVED-FIXTURE`) | 예 |
| `docking/synthetic-docking-blocks.smi` | `966f7a8607d3011f` | `docking/SYNTHETIC-PROVENANCE.md`(합성 표시) | — |
| `ligand/synthetic-blocks.smi` | `fc603c4b9d2e3cf4` | `ligand/SYNTHETIC-PROVENANCE.md` | — |
| `ligand/synthetic-reaction-rules.json` | `cc27e69029c68d14` | 같음 | — |
| `ligand_ga/synthetic-ga-small-blocks.smi` | `8ae10d0571871f1a` | `ligand_ga/SYNTHETIC-PROVENANCE.md` | — |
| `mutation_model/synthetic-phenol-ligand.sdf` | `997c7d6f0a73142f` | `mutation_model/SYNTHETIC-PROVENANCE.md` | — |

**결론.** 보관 실세트·로컬 kbase·M15 활성 세트 모두 쓸 수 있다. 멈출 조건 없음.

## (c) M7 사전 검사 표

**명령.** `PYTHONPATH=backend .venv/bin/python docs/qa/m28-final-20261011/m7_probe.py <P>/m7-probe-runs` → exit 0. 방식은 이 폴더의 `m7_probe.py`(측정 시제품, `mw` 제품 함수를 바꾸지 않고 부름): 구조·물 정책마다 `new_run` → `load_structure`(모델 0) → `prepare_structure`(altloc highest_occupancy, waters keep_all|strip_all, hydrogens strip, leave_gaps, ignore) → `mw.tools.openmm_method.preflight`. 최소화는 돌리지 않는다. 전체 표는 `m7-probe.txt`.

| 구조 | keep_all | strip_all | 이유 코드 / 메시지 | 실패 잔기 | 인계 기대 |
|---|---|---|---|---|---|
| 1UBQ | 통과 | 통과 | 중원자 602, 제외 58, 체인 1 | — | 통과(602, 58) |
| 1M17 | 실패 | 실패 | `sequence_gap` | A/977/LEU | `sequence_gap` |
| 1S9I | 실패 | 실패 | `sequence_gap` | A/228/VAL | `sequence_gap` |
| 1A4I | 실패 | 실패 | `sequence_gap` | A/251/LYS | `sequence_gap` |
| 1FIN | 실패 | 실패 | (이유 코드 없음) `duplicate author chain identity`, `input_invalid` | — | 같음 |
| 1MQ4 | 실패 | 실패 | `heavy_template_mismatch` | A/126/ARG | `heavy_template_mismatch` |
| 1A30 | 실패 | 실패 | `heavy_template_mismatch` | A/41/ARG | `heavy_template_mismatch` |
| 1HSG | 실패 | 실패 | `missing_terminal_oxt` | A/99/PHE | `missing_terminal_oxt` |

요약 줄: `runs=16 passed_structures=1UBQ same_result_both_water_policies=true`. **결론.** 2026-10-11 기대와 모두 같다(멈출 조건 아님). 변이 모델링(M21·M23·M25 단백질)은 1UBQ에서만, 촉매 보호(M26 → M20 v2)는 M-CSA 효소에서만 돈다는 명세 §3.2 1번 전제가 맞다.

## (d) 사례 사슬 지도

조사: 읽기 전용 서브에이전트가 하네스 31개·QA 도우미·실행기·증거를 읽었다. 하네스 export 목록과 아래 (i)의 AQ4 7필드·잔기/원자 수·화면 기본 정책, (iii)·(v)의 핵심 사실은 직접 확인했다. 행 번호는 HEAD `287a37a8` 기준이고 파일 이름의 `-flow.cjs`는 생략했다.

**결론: 모든 사례를 기존 하네스 단계·QA 도우미로 이을 수 있고, 로컬 공개 자료만으로 정의 항목이 통과 경로를 잃는 곳은 없다.** 다만 실행 순서(아래 막힘 2, (e) 5절)와 B2 입력 조합(막힘 1), GA 설정 둘((e) 4절)은 T7·T8 전에 조율 세션이 정해야 한다.

**하네스가 실제로 내보내는 것.** 명세 §5 "흐름 전체(`main`)와 oracle만 내보낸다"는 대체로 맞지만 예외가 있다: `normal-flow` 592(`parse, runNormalFlow, sha256, sourceDigest, waitForViewer, waitForBoot, assertViewer, validateReportDownload`), `comparison-flow` 2590(`…, createLocalRun, uploadAndLoad, run`), `scenes-flow` 1280(`parse, run, closeCamera, checkPng`), `driver.cjs` 271(`options, launchOffscreen, locator, command, capture, status, waitForPaint, downloadByClick`). 나머지는 `options, main`(chemical·numbering·tabs·workflows) 또는 `options, main` + oracle·상수(annotation `preflightOracle, legendRegion`; docking `oracle, halfUp, expectedLimitations, contactKind, forbiddenWords, refusalOracle, refusalLine`; docking-batch `oracle, neededFor, shortfallFor, sortOracle, NOT_OBSERVED`; ligand `oracle, candidateId`; ligand-ga `oracle, needFor, shortfallFor, sortOracle, tanimoto6, NOT_OBSERVED`; pocket `compareSpheres, validateReport`; mutation `preflightOracle, halfUp2, forbiddenIn, FORBIDDEN, FORBIDDEN_CATALYTIC, reasonCountText, UK2, LIMITATIONS, LIMIT3`; mutation-model `halfUp, expectedLimitations`; sequence-ga `oracle, needFor, shortfallFor, spaceSize, sortOracle, statementIds, projectPath, NOT_OBSERVED, GA1–GA4`; jev `halfUp, expectedLimitations, forbiddenWords, FORBIDDEN, FIXED_LINES, J, U, MODES`; jev-loop `oracleOrder, expectedLimitations, forbiddenWords, checkPlan, fixtureServer, sortExpected, rehearsalScript, FORBIDDEN, FIXED_LINES, LJ, UL, INSTRUCTIONS, MODES, MAX_LIVE_CALLS`; reaction-knowledge `forbiddenIn, identityText, checkChainExpectation, textDigest, FIXED`; kinase-precedents `forbiddenIn, mdEscape, bareZeroOrNone, realSafe, textDigest, countTexts, chainCells, pageText, checkKbaseFields, REAL_TEXT_MIN_CHARS, LIMITATIONS, KT1, UP1–UP5`; openmm 계열 `parse, runX`). **단계 함수(`newRun`·`uploadLoad`·`prepareManual`·`detect`·`fillForm`·`runGa` 등)는 거의 내보내지 않으므로 새 하네스에 복사(출처 주석)**하고, 내보낸 oracle·상수·`validateReportDownload`·`checkPng`·`legendRegion`은 `require`로 써도 된다(기존 하네스끼리 이미 그렇게 쓴다: `normal-flow.waitForViewer` 15곳, docking-flow를 `m18`로 3곳, jev-flow의 J·U, comparison-flow의 oracle).

| ID | 재사용할 단계 로직 (파일 줄) | QA 입력 도우미 | 새로 써야 할 것 | 알려진 장애 |
|---|---|---|---|---|
| A1 | normal W02(229)·I01(245)·I03(255)·I08(264); annotation `uploadLoad`(286)·`prepareManual`(298) | 없음(화면 클릭) | 1M17 독립 계수: 화면 기본 정책 적용 뒤 잔기 313·원자 2,526((i))을 저장 manifest와 대조 | 물 기본값이 두 가지: 도구 명세(`config/tools.yaml` 28행)와 `docs/business-rules.md` 30행은 `keep_all`, 화면(`page.tsx` 128)과 고정 워크플로 인자(`backend/mw/workflows.py` 35)는 `strip_all` → A1 "기본 정책"을 화면 기본값으로 읽을지 T6 전에 정한다(`keep_all`이면 기대 잔기 333·원자 2,546) |
| A2 | normal C01(302)·C02(306–318)·C03(321)·V05(387)·R01(510), `createAndWaitForSavedReport`(145, 비공개)·`validateReportDownload`(113, e); annotation M04(641–663: 옵션 글자로 인스턴스 선택 + 요청 `ligand` 7필드 `sameResidue`) | 없음 | 접촉 행 AtomRef ↔ 입력 mmCIF atom_site 대조(icode `""`↔`?`, seq_label null↔`.`), "수소결합" 문구 검사 | normal은 1HSG 97건 하드코딩. 점검 보고서는 제품 다시 열기가 주장·Markdown 재생성을 안 함((k) 위험 1) |
| A3 | normal S01-input(526)·S01(538)·R03(551–574) | 없음 | 잔기별 SASA 표 ↔ 저장 객체(`/objects` 100행씩) | interface_sasa 보고서도 Markdown 재생성 없음((k) 위험 1) |
| A4 | pocket `uploadLoadPrepare`(254)·`preflightFor`(277)·`detect`(286)·`descriptorCellsMatch`(323)·`assertSummaryTable`(346)·`compareSpheres`(366, e)·`selectAndCompare`(469)·`validateReport`(528, e)·`reportDownloads`(617)·`createReport`(904), P03–P06(652–748) | 없음 | 1M17 입력 지정(체인 A 하나라 P04 분기 생략), 기대값은 저장 `pocket_set`에서 | fpocket 결과는 실행마다 다름(고정 숫자 금지, `engineering-notes.md` 307). A6 전에 포켓 오버레이를 꺼야 함(주석과 배타, annotation 1187–1237) |
| A5 | kinase-precedents `makeMap`(415)·`checkMap`(458)·`pickFromSearch`(404); numbering `chooseStructure`(302)·`runMap`(325)·`chainSummary`(342)·`allScreenRows`(375)·F01(660); annotation M05(668–706, 전처리 구조로 번호 대응) | m27 실행기 `real_plan`(372–391) | 1M17 번호 대응은 A6를 위해 **전처리 구조**에(M27 실행기는 불러온 구조에) | 1FIN B·D를 넣으면 422 `no_usable_method`. M27 관찰 mapped: 1M17 A 311/312, 1FIN A·C 각 298/298, 1MQ4 A 260/261 |
| A6 | annotation M06–M09(712–860: `mapRadios` 358·`contactRadios` 364·`siteTable` 375·`showAnnotation` 391·`annotationDetail` 421), M10(866–892: `saveScene` 452·`exportFigure` 469·`downloadFigure` 482), `legendRegion`(599, e); scenes `checkPng`(228, e) | 없음 | 1M17 독립 oracle(부위별 접촉 수·최소 거리·극성 쌍), **PNG ≤ 8 MiB 단언 추가**(기존은 2048 px·400만 픽셀만, annotation 889) | `preflightOracle`(83)·픽셀 기준(노란 점선 ≥ 30 px, 1MQ4 10쌍)이 1MQ4 전용 |
| A7 | kinase-precedents `openKnowledge`(479)·`linkCase`(782)·`setRequest`(807)·`verifyDetail`(643)·`recordsPart`(1303)·`reportPart`(1553)·`bareZeroOrNone`(533, e)·KT1·UP1–5(e) | m27 실행기 `import_real`(899)·`real_main_plan`(394–427); 설치는 `--from ../kbase_kinase`로 격리 폴더((b)에서 시험) | 설치된 `moves*.jsonl`에서 `target.uniprot`·`target.variant`·`moves_flagged` 수 독립 계수(kbase `77354f9` 기준 P00533 `moves` 76·`moves_flagged` 66, P24941 32·24, O14965 0·0; P00533 변이 not_reported 53·L858R 15·T790M 4·WT 3·L834R 1 — M27 착수 확인과 같음) | 실제 kbase 문구는 커밋 증거에 넣지 않음 |
| A8 | reaction-knowledge `chooseStructure`(704)·`linkCase`(719)·`verifyDetail`(431)·`checkChainExpectation`(644, e)·M12(1105–1115) | m26 실행기 `real_plan` links(384–462: 1S9I·1A30·1A4I 기대) | import2를 격리 폴더로 복사, 기대값은 저장 결과·가져오기 기록에서 | 공개 구조에서는 `unmatched`·`conflict` 행이 나오지 않음(`m26-acceptance.md` 76) → 범위 표 |
| B1 | chemical `openWorkspace`(168)·`startWithApproval`(266)·`focusFirstRow`(311, D···A·각도 독립 계산 351–358)·`downloadReport`(374)·`runCreate`(544) | 입력 `chemical/prolif-vina-rec.pdb`+`prolif-vina-output.sdf`((b)) | — | 시작 30초 초과 시 프록시가 끊어 화면에서 다시 읽음(`engineering-notes.md` 34) |
| B2 | ligand `chooseLigandFile`(329)·I01 반응 규칙 입력(528–529)·`runLigandJob`(345)·`selectInspection`(389)·`selectSet`(395)·`candidateTable`(414)·`fillFilter`(471)·P01(849); ligand-ga `m17CandidateSet`(440: site 22, use_fixed, 규칙 없음) | 부모 `docking/public-derived-parent-record0.sdf`, block `ligand_ga/synthetic-ga-small-blocks.smi`(10) | **고정 교체 + 사용자 반응 SMARTS를 함께 쓰는 입력 조합**(막힘 1) | 규칙 SMARTS 오류는 점검 뒤에야 보임(findings 211) |
| B3 | docking `importDocking`(452)·`fillForm`(505)·`runDockingJob`(569)·`openResult`(612)·`resultView`(618)·`modeTableEquals`(631)·`contactTable`(669)·`contactsEqual`(682)·`downloadPose`(702)·P01(908)·`forbiddenWords`(434, e)·`expectedLimitations`(181, e) | 없음 | **같은 인자 재제출** 단계(기존 M18 하네스에 없음; 같은 `job_id`·`expensive_calls` 불변 확인) | 상자·값을 B7 루프 설정과 같게 해야 활용형 본문에 저장 점수가 실림((iii)). qvina stdout은 실행마다 다름 |
| B4 | docking-batch `chooseReceptor`(462)·`chooseSet`(475)·`tick`(483)·`fillSettings`(499)·`preflight`(536)·`runBatch`(629)·`openSummary`(671)·`resultTable`(679)·`tableEquals`(699)·`sortChecks`(749)·P01(1165), `sortOracle`/`neededFor`/`shortfallFor`(e) | 없음 | 행 → 단독 M18 상세 열기 화면 대조 | 증액은 부족분만 → 막힘 2 |
| B5 | ligand-ga `chooseInputs`(510)·`setParams`(488)·`preflight`(557)·`approveLimits`(640)·`runGa`(708)·`openSummary`(758)·`generationTable`(776)·`resultEquals`(805)·`sortChecks`(924)·P10(1440) | 없음 | 설정 2(기존 GA2는 GA seed 하나만 다름 → 명세 "둘 이상"을 못 채움, (e) 4절) | `claimed` 상태 "작업 시작" 잠재 결함(findings 465). 예약 환불 없음 |
| B6 | jev `openKnowledge`(376)·`setConsent`(384)·`chooseSource`(398)·`checkKeys`(431)·`build`(438)·`previewIdentity`(477)·`confirmAndSend`(508)·`readCard`(530)·`cardMatches`(564)·`preparedMatches`(633)·`makeReport`(663) | M25 fixture 서버((v)); M24 실행기 `setup_runs`(774)는 API 사전 생성이라 패턴만 | B2가 화면으로 만든 같은 run의 집합 사용 | 전송 중 run 잠금(503). 전송 10회·토큰·USD는 run 공유 |
| B7 | jev-loop `openLoopArea`(517)·`setConsent`(532)·`chooseSource`(554)·`checkKeys`(567)·`settings`(608)·`ligandSetupInputs`(614)·`createLoop`(672)·`build`(693)·`previewMatches`(733)·`confirmAndSend`(802)·`serverBytes`(824)·`readCard`(851)·`pressCompute`(978)·`makeLoopReport`(1143)·`ligandBranch`(1186); live용 `modeLive`(2405)·`finishRound`(2376)·`rehearsalScript`(2367, e) | qa_setup.py `ligand_run`(147)은 API 사전 생성이라 패턴만 | 화면으로 만든 B run에서 풀 ≥ 3(미계산 ≥ 2, 계산됨 ≥ 1); 탐색형 본문 점수 없음 검사(jev-loop 1724 패턴) | **막힘 2**. 시작 전 취소한 후보는 그 run에서 다시 계산 불가(`engineering-notes.md` 507) |
| B8 | tabs `expectedLists`(596)·`listsMatch`(610)·`clickDownload`(631); normal `validateReportDownload`; jev-loop `libraryReport`(1116)·`knowledgeRows`(1155) | 없음 | 보고서마다 `/reports/selected` 200·JSON 해시 | 목록 하나 깨지면 전체 422 |
| C1 | mutation `modeCatalytic`(1722–2085)·`linkReaction`(1544)·`setPositions`(1530)·`pickResidueAt`(1518)·`create`(491)·`verifyCatalyticSet`(1589)·`catalyticCellText`(1579)·FORBIDDEN_CATALYTIC·UK2(e) | m26 실행기 `FLOW_OF` real-mutation(72–74)·`real_plan.mutation`(488–515) | `checked` 독립 계산; M20 보고서 단계를 catalytic 흐름에 붙임(main 모드 Q01 1250에만 있음) | 덮인 체인이 없으면 0 저장(findings 599, 수정 안 함 §10.3) |
| C2 | M7: openmm O02–O08(125–241, 별도 run) 또는 annotation N03(1461); mutation-model `uploadLoad`(329)·`prepareManual`(346)·`m20CreateDirect`(372)·`runModelJob`(430)·`openModel`(478)·`sideBySide`(485)·`expectedSideBySide`(498)·`checkContacts`(524)·`panelWording`(551)·Q01(952)·`expectedLimitations`(120, e) | 없음 | M7 뒤 "최신 구조로 돌아가기"로 전처리 구조에서 M20(M21은 M7 사전 검사만 요구, 최소화 결과는 쓰지 않음); 차이·변화량 값 부재 검사 | M7 통과는 1UBQ뿐((c)). OpenMM 보고서는 뷰어 동의를 바꾸면 깨짐((k) 위험 2) |
| C3 | mutation-model `fillPair`(586)·`submitPair`(606)·`drivePair`(633)·`pairView`(563); SDF 가져오기 sequence-ga `importLigandSdf`(583) | `mutation_model/synthetic-phenol-ligand.sdf` | 짝 표 점수 = 해당 M18 첫 모드 값 | 합성 페놀(범위 표 2번) |
| C4 | sequence-ga `m20Create`(546: tiny 집합 = I3 보호, K6·I44·G76 × A·W = 후보 6)·`chooseInputs`(674)·`preflight`(714)·`approveLimits`(825)·`runGa`(900)·`resultEquals`(1028)·`individualMatches`(1253)·Q01(2119), `needFor`/`spaceSize`(e) | 없음 | 설정 2를 둘 이상 다르게((e) 4절) | 기본 8단위로 모자라 화면 증액 → 막힘 2 |
| C5 | B6과 같은 jev 단계(kind = mutation) + `expectedLimitations(kind, late, catalytic)`(139)·`catalyticStatus`(144) | M25 fixture 서버 | v2 집합의 J6n 문구 기대 | — |
| C6 | jev-loop `proteinSetupInputs`(647)·`proteinBranch`(1844–2316; 탐색형 159, 활용형 2182–2229)·`pressCompute`(978), `PROTEIN_SETUP`(154) | qa_setup `protein_run`(166)·`mutation_set`(132)은 API 사전 생성이라 패턴만 | C2–C4와 같은 1UBQ tiny 집합(6후보)에서 풀 ≥ 3 | 막힘 2(바퀴당 2단위·420초). 1MQ4는 루프 불가 |
| C7 | B8과 같음 | — | 같음 | 같음 |
| X1-A/B/C | normal `validateReportDownload`(113), tabs `expectedLists`(596) | — | 이벤트 수와 보고서별 selected 200; **사례 코드가 센 생성 수와도 대조**((k) 위험 3) | 목록 라우트를 열림 판정에 쓰지 않음 |
| X2 | 없음 | — | T5 `m28_trace_audit.py` 전부((k) 표) | — |
| X3 | `main.cjs` `onBeforeRequest` → `blockedRequests`/`loopbackRequestCount`(56–64), driver `launchOffscreen`(201), 하네스 `offscreenProof`, jev-loop `fixtureCalls`(266)·`credentialReads`(270)·`dispatchCounts`(257) | m25 `count_events`(360)·`dispatch_total`(383)·`fixture_proof`(596)·`ledger_path`(664)·`ledger_lock`(739)·`ledger_admission`(770); m27 `browser_hosts`(545) | 세 분기 합산, live 대장 상한 2 | — |
| X4 | `forbiddenWords`(docking 434, jev 148, jev-loop 219, ligand-ga 473, sequence-ga 627), `forbiddenIn`(mutation 600, reaction 414, kinase 522) | m24 `forbidden_in`(367)·`scan_wording`(387); m25 `forbidden_in`(514)·`scan_wording`(542) | 고정 문장 내보내기 하위 프로세스 + 줄 단위 예외 목록 | 옛 6종의 부정문 한계 문장이 인라인 리터럴((k)) |
| X5 | kinase `bareZeroOrNone`(533), mutation `catalyticCellText`(1579)·R-no-zero, reaction X-no-zero, annotation `NO_CONTACT_IN_CUTOFF`(47) | — | 분기 공통 검사 | M20 v2 미덮음은 API 원본에 0(findings 599) |
| X6 | 하네스 `jobProcesses`(docking 240, sequence-ga 315) | m25 `Runner.leftovers`(1417)·`group_alive`(424)·`kill_group`(434)·`fixture_server_started`(612); m13 `listening`(175); m15 `leftovers`(461); m27 기본 폴더 확인(907, 1120) | **`.deps/reaction_reference`도 함께 확인**(m27은 precedent 폴더만 봄) | — |

**(i) 1M17 AQ4와 A1–A4·A6 입력(직접 확인).** gemmi로 `public_1m17.cif`를 읽으면 모델 1개, AQ4 인스턴스 **정확히 1개**(auth 체인 A, label 체인(subchain) B, auth 번호 999, label 번호 없음, icode 공백, 29원자). ProtView 7필드(`_res_ref`, `structural.py` 88–91, icode는 `strip()` → 빈 문자열): `{"model_number":1,"chain_auth":"A","chain_label":"B","seq_auth":999,"seq_label":null,"icode":"","resname":"AQ4"}`. 화면 옵션은 하나(`AQ4 auth A/999 · label B/unknown · model 1`). 화면 전처리 기본값은 altloc `highest_occupancy`·물 **`strip_all`**·수소 `strip`(`frontend/app/page.tsx` 127–129, 직접 확인); 리간드를 빼는 정책은 없어 AQ4는 남는다. 원본 잔기 333·원자 2,560·물 20·H 0(직접 확인) → 화면 기본 정책 적용 뒤 기대 **잔기 313(= 333 − 물 20)·원자 2,526(= 2,560 − altloc B 14 − 물 O 20)**(제품 `prepare_structure` 요약의 `altlocs: 14`와 일치, 직접 확인). A2·A3 = 전처리 구조 + 위 7필드, A4 = 전처리 구조 체인 A, A6 = 번호 대응과 접촉 결과가 **둘 다 같은 전처리 구조**(결정 0024). 참고(증거 아님): 4 Å 안 중원자 쌍 65개, N/O 쌍 7개(Met769 N–N2 2.699 Å; Met769는 KLIFS hinge.48로 보여 A6 극성 점선이 최소 하나 예상).

**(ii) C1의 효소.** M26 real 기록(`m26-acceptance.md` 67, m26 실행기 `real_plan` 386–392): 1S9I A `covered`(M-CSA 282) matched 2·B `chain_not_listed`; **1A30 A·B 모두 `covered`(175) 각 matched 3**; 1A4I A matched 6·B `chain_not_listed`. **권고: C1은 1A30**(두 체인이 덮여 `checked` 참·거짓(`chains_not_covered`, 체인 A만 연결)을 모두 볼 수 있고 M26 real-mutation이 이미 통과한 입력). 위치 입력 셋: 포켓 순번(rank, mutation `detectPockets` 376), 리간드 껍질 반경(`setPositions` 1531–1534), 직접 선택(`pickResidueAt` 1518). 이미 하는 하네스: `mutation-flow` `modeCatalytic`(1722; m26 실행기가 `--plan`으로 부름, real: 1A30 직접 잔기 ARG A8·ASP A25·THR A26·ASP B25·GLY B27, 반응 결과 체인 A만 / A+B, 해제 ASP A25). 반응 연결은 같은 흐름의 `linkReaction`(1544)이 전처리 구조에 한다.

**(iii) B 분기 선행 상태.** 수용체·포즈·부모·block·규칙 파일과 출처는 (b) 표. 기존 QA 중 화면 클릭으로 만든 것: chemical `runCreate`, ligand 전체, docking 가져오기·M17·M18, docking-batch·ligand-ga `m17CandidateSet`(M22 실행기는 입력을 미리 만들지 않음). API 사전 생성: M24 실행기(`ligand_set` 737·`mutation_set` 757·`setup_runs` 774), M25 `qa_setup.py`(`ligand_run` 147·`protein_run` 166·`job` 103이 첫 비용 승인을 API로). M28은 클릭으로 진행하므로 B6·B7은 B2–B4가 화면으로 만든 같은 run 상태를 쓰고 qa_setup은 패턴 참고만 한다. **B7 재사용 조건**: 루프는 `docking_batch_inputs.published_m18_results`(`jev_loop_store.py` 444)로 단독 M18·M19 행·M22 개체를 "계산됨"으로 보므로, B3·B4·B5의 수용체·뺄 인스턴스(none)·CONECT·manual 상자·도킹 값이 루프 설정(jev-loop `LIGAND_SETUP` 151: 중심 3.41/0.72/11.31, 크기 12, seed 1, exhaustiveness 1, 모드 2, energy_range 3)과 같아야 활용형 본문에 저장 점수가 실린다.

**(iv) C 분기 1UBQ 선행 상태.** M7 최소화(openmm O02–O08 별도 run·물 keep_all, annotation N03 1461, workflows `modeMinimize` 1447) → M20(mutation-model `m20CreateDirect` 372 = I44W 1후보, sequence-ga `m20Create` 546 = tiny 6후보) → M21(`runModelJob` 430) → M18 짝(`fillPair`·`submitPair`·`drivePair`) → M23(sequence-ga `modeMain` 1363) → M25 단백질(jev-loop `proteinBranch` 1844 + `proteinSetupInputs` 647). 합성 페놀 `mutation_model/synthetic-phenol-ligand.sdf`. **권고: C2–C6을 tiny 집합(K6·I44·G76 × A·W = 6후보) 하나로 잇는다**(M21 대상, 풀 ≥ 3, M23 조합 공간 26, M24 ≥ 2를 모두 덮음; I44W 1후보 집합은 풀로 부족). qa_setup이 Gly·Pro·Cys를 풀에서 뺀 것(`NOT_MODELLED_HERE`)은 하네스 선택이지 제품 제한이 아니다.

**(v) fixture JEV 서버(`backend/tests/offscreen_jev_loop_fixture/server.py`).** `main`(177–207)이 `product_api.SCIENCE_GATE`(197)를 스크립트된 `httpx.MockTransport` + placeholder 자격 증명 `SENTINEL`(56, 키 아님)로, `VIEWER_GATE`(199)를 거절 transport로, `EgressGate.__init__.__kwdefaults__`(194)를 거절 기본값으로 바꾸고 `.env`를 읽지 않는다. 폴더 인자가 `/tmp`나 저장소 `runs/`면 거절(186–189); `MW_*_REFERENCE_DIR`은 그대로 넘어간다. 응답은 요청마다 `<control>/script.json`(`Controller.script` 114: `good`·`good_second`·`computed_alias`·`http_500`·`slow`·`no_usage`·`model_mismatch`, `reply` 76)으로 정해지고 `good`은 `criteria[0]`을 고른다. 기록 `calls.jsonl`·`credentials.json`(`productResolverReads` 0이어야 함). **두 목표·두 갈래 모두 받는다**: 서버는 `goal`을 기록만 하고(151) 응답은 `criteria`로만 정하며, M25 fixture 단계가 이 서버로 리간드 활용형·탐색형, 단백질 탐색형·활용형을 모두 통과했다(jev-loop 156–159, 2182–2229). **M24 전송(B6·C5)도 받는다**(M24 본문에도 `questions.candidate_choice.criteria` = 보낸 모든 별칭, `jev_projection.py` 562–565). 차이: `good`이 첫 별칭을 고름(M24 전용 서버는 둘째), `computed_alias`는 M24에서 transport 오류, M24 서버의 `alias_outside`·`good_no_extras`는 없음(성공 경로엔 불필요). `no_usage`·`http_500`은 그 run의 외부 전송을 멈추므로(M25 L19·P13) M28 분기 run에서는 정상 응답 스크립트만 쓴다.

**(vi) A6 그림 내보내기.** annotation M10(866–892)이 이미 보기 저장(`viewer_scene@2`, `annotation{handle, legend: true}`) → PNG 내보내기(`viewer_figure@2`, `capture_method "molstar_image_pass+legend"`, `legend_composited` 참) → PNG·JSON 다운로드 = 백엔드 바이트, `png_sha256` = PNG 해시(494), 2048 px·400만 픽셀(889)을 한다. **1M17에 재사용 가능**하되 1MQ4 전용 oracle(`preflightOracle` 83, ADP 상수 33, 부위 10·극성 쌍 10 단언 93–94, 노란 픽셀 ≥ 30 단언 965)을 1M17 독립 계산으로 바꾸고 PNG ≤ 8 MiB 단언을 더하며 A4 포켓 오버레이를 먼저 끈다(1223 패턴). scenes `checkPng`(228, e)도 쓸 수 있다.

**막힘과 결정 필요(멈춤 조건 아님: 정의 항목의 통과 경로는 남아 있다).**
1. **B2 입력 조합(T7 전 결정)**: 공개 파생 부모에 고정 교체와 사용자 반응 SMARTS를 함께 쓰면서 후보 수가 작은 기존 입력 묶음이 없다(`ligand_ga/synthetic-ga-small-blocks.smi`에는 브롬화물이 없고, `synthetic-ga-pool2000-rules.json`은 브롬화물 1,000개와 쓰면 2,000개 상한). 기존 합성 표시 파일만으로 가능한 조합(조사 제안, T7이 실제로 확인): SMILES 칸 `small-blocks.smi` + SDF 칸 `ligand/synthetic-blocks.sdf`(bromomethane 기록 포함, 거부 기록 섞임) + 규칙 칸 pool2000의 `user_2`·`user_3`. 새 합성 표시 block 목록을 만드는 길은 명세 R1("이미 있는 … 합성 표시 block·반응 규칙 fixture")의 범위인지 조율 세션이 정해야 한다.
2. **M25 루프 예산 순서(가장 큰 위험, 직접 확인)**: 루프 계산 시작은 바퀴 필요량(리간드 1단위·300초, 단백질 2단위·420초, 모델이 저장돼 있으면 1단위·300초; `jev_loops.py` 723–729 `_candidate_need`)이 남은 예산보다 크면 429 `budget_blocked`(1025)이고 **루프에는 증액 경로가 없다**. 증액이 가능한 M19·M22·M23 `limit_approval`은 **부족분만** 올린다(`ligand_ga_jobs.py` 285–309 등, 직접 확인) → 그 작업이 끝나면 남은 단위는 0. 그래서 명세 표의 순서(B4·B5 뒤 B7, C4 뒤 C6)를 한 run에서 그대로 돌리면 B7·C6이 막힌다. 해법은 (e) 5절의 순서 변경(B: B6·B7을 B4·B5보다 먼저, C: C5·C6을 C4보다 먼저)이고, 명세는 실행 순서를 못 박지 않았으므로(사슬은 선행 상태 관계) 조율 세션의 설계 결정으로 본다. live B에서는 L-pre-B4의 새 행 수를 묶어 L-B7 1단위를 남겨야 한다((e) 5절).
3. **GA 설정 둘**: 기존 M22·M23 하네스의 GA2는 seed 하나만 다르다 → 새 설정값((e) 4절).
4. **새로 써야 하는 단계**: M18 같은 인자 재제출(B3), M20 보고서를 catalytic 흐름에 붙이기(C1), 1M17용 A6 oracle과 PNG 8 MiB 단언, X6의 `.deps/reaction_reference` 확인, X1의 생성 수 대조.
5. **범위 표에 그대로 적을 것**: C1(1A30)과 C2(1UBQ)는 다른 구조, A8 실데이터에 `unmatched`·`conflict` 없음, C3는 합성 페놀, B 분기 block·규칙은 합성 표시.
6. **기본값 두 가지(T6 결정, 문서는 사실대로)**: 물 정책 기본값이 도구 명세·`docs/business-rules.md`(`keep_all`)와 화면·고정 워크플로 인자(`strip_all`)에서 다르다. 둘 다 코드에 있는 사실이므로 문서를 고칠 일은 아니고(T17이 필요하면 "화면 기본값은 `strip_all`"을 덧붙일 수 있음), A1의 "기본 정책"을 어느 쪽으로 볼지만 정하면 된다.

## (e) 시간·예산·GA 설정 둘

조사: 읽기 전용 서브에이전트가 M18–M27 수락 증거와 상수를 읽었다. GA 범위·예약 공식(`ligand_ga_constants.py` 27–38, `sequence_ga_constants.py` 48–60, `ligand_ga_inputs.py` 249–257·269–273, `sequence_ga_inputs.py` 643–650), 기본 한도(`config/default.yaml` 3–7), 루프 바퀴 필요량과 `budget_blocked`(`jev_loops.py` 723–729·1025), 증액 = 부족분(`ligand_ga_jobs.py` 281–309)은 직접 확인했다. **[측정]** = 증거 파일 값, **[추정]** = 그 값으로 계산한 값.

**1. 단계별 시간.**

| 단계 | 조건 | 시간 | 근거 |
|---|---|---|---|
| M18 단독 도킹 | 기본값(exh 8, 모드 9, 리간드 범위 8 Å) | 32.5·40.4 s; 2,000개 풀 6건 35.0–82.9 s | [측정] `docs/qa/m25-jev-loop-20261007/preflight.txt` 206–207, `docs/qa/m22-ga-20261004/preflight.txt` 125–137 |
| M18 작은 설정 | 12 Å 상자, exh 1, 모드 2, seed 1 | 10건 6.9–11.8 s | [측정] m22 preflight 139 |
| M19 일괄 행 | exh 8 자유 / 코어 고정 | 32.41–41.17 s/행 / 5.54–6.15 s | [측정] `m19-acceptance.md` 54 |
| M21 1UBQ I44W | 단독 | 20.0·20.6 s(착수 확인 22.6–23.0) | [측정] m25 preflight 208 |
| 변이 구조 M18(페놀) | — | 2.8 s(M23 개체 안 `dock_row` 0.8–1.6 s) | [측정] m25 preflight 209, `m23-acceptance.md` 47 |
| M22 GA1 / GA2 | seed 11, 개체 4, 세대 2, 이어받음 2, 무작위 0.5, 새 도킹 ≤ 6, exh 1 / seed 12만 바꿈 | 예약 6·새 도킹 6·61.5 s / 재사용 4·새 2·36.7 s·증액 +6 | [측정] M22 수락 G02·U02 |
| M23 GA1 / GA2 | seed 21, 개체 4, 세대 4, 이어받음 1, 교차 0.5, 무작위 0.25, 변이 ≤ 3, 새 평가 ≤ 32 / seed 13, 세대 2, 새 평가 ≤ 4 | 예약 28·새 평가 10 + 기준 행·134.7 s / 새 4 + 재사용 2·61.6 s | [측정] M23 수락 G04·U02 |
| M23 개체 모델링 | 1UBQ | 9.4–10.4 s/개체 | [측정] `m23-acceptance.md` 45 |
| M25 리간드 바퀴 계산 | 12 Å, exh 1 | 9.2–11.3 s | [측정] M25 fixture L10·L13·L14·L19b |
| M25 단백질 바퀴 | 모델링 / 도킹 | 21.5–22.2 s / 2.3 s | [측정] P08·P10 / P09 |
| M25 실호출 | 7회 + 계산 | 2분 48초 | [측정] M25 `acceptance-live/evidence/runner-summary.jsonl` |
| 실행기 전체(2026-10-10 회귀) | M27 fixture+real 1.5분, M26 fixture 0.9분, M25 2.2, M24 0.9, M23 10.8, M22 5.9, M21 1.8, M20 0.7, M19 3.1, M18 1.2, M17 3.0, M16 1.0, M15 0.6, M14 1.9, M13(M8–M12 포함) 36.5분; 사슬 M27→M13 약 73분; typecheck + build 14–15 s | | [측정] `docs/qa/m27-precedents-20261010/regression-chain.txt`·각 `runner-summary.jsonl` |

**2. 제품 상한·기본값.** M22: seed 0–2147483647(기본 없음), 개체 4–24(12), 세대 1–8(5), 이어받음 0–4(2), 토너먼트 2–4(2), 이웃 3–30(10), 무작위 0.0–0.5(0.2), patience 1–8(3), 새 도킹 4–100(60), total_s 600–14400(7200); 개체 − 이어받음 ≥ 2, 새 도킹 상한 ≥ 개체; 예약 단위 = min(새 도킹 상한, P + (G−1)(P−E))(시작 때 한 번, 재사용이 있어도 환불 없음); 필요 시간 = min(total_s + 600, 단위 × 300 + 300). M23: 개체 4–16(8), 세대 1–8(5), 이어받음 0–4(2), 토너먼트 2–4(2), 교차 0–1(0.5), 무작위 0–0.5(0.2), 변이 수 1–4(3), patience 1–8(3), 새 평가 4–64(32), total_s 600–14400(7200); 예약 평가 = min(새 평가 상한, P + (G−1)(P−E)), 예약 단위 = 2 × (예약 평가 + 1); 필요 시간 = min(total_s + 600, 단위 × 270 + 300); 조합 공간 < 개체 수면 `ga_space_too_small`. M19: ≤ 50(+부모 1), 행당 300 s, 새 행마다 1단위. M25: 풀 2–20, 반복 1–8, 바퀴 필요량 리간드 1단위·300 s / 단백질 2단위·420 s(모델 저장 시 1·300), 미계산 후보 ≥ 2여야 전송.

**3. 기본 run 한도와 예약.** 8단위·1800 s·120,000 토큰·USD 2.00(`config/default.yaml` 3–7), run당 전송 10회(`jev_constants.SEND_CAP`), 전송 한 번 예약 = 토큰 min(50000, 4096 + ⌈본문 바이트 × 2/3⌉)·USD 0.10. 단위를 쓰는 것: fpocket 1, M17 점검·생성 각 1, M18 1, M19 새 행마다 1, M22 예약 단위, M23 2 × (예약 평가 + 1), M21 1, M7 1, M11 준비·검출 각 1; 값싼 도구(M15·M16·M20·M24·M25 투영·M26·M27)는 0. 1800 s 활동 시간은 작업도 제한한다(작업 마감 = 시작 + min(run 남은 시간, timeout_s)). **증액(M19·M22·M23 `limit_approval`, 사람 클릭만)은 부족분만 채우므로 그 작업이 끝나면 남은 단위는 0이고, M17·M18·M21·M7·M11·M25는 단위 부족을 올릴 길이 없다**(직접 확인). 기존 하네스의 증액 클릭: "시작 전 확인 보기" → 부족분 > 0이면 `*-limit-approve` 클릭 → 사전 확인 다시 읽기 → 부족 0 → 시작(ligand-ga 640–659, docking-batch 1101–1105, sequence-ga 824–836).

**4. GA 설정 권장안(T7·T8 입력).** 재사용 조건: M22 개체 인자 = M18 인자 그대로(수용체·상자·도킹 `parameters`·자유 방식·후보 id; **GA seed·`ga` 묶음은 들어가지 않음**, `ligand_ga_inputs.py` 88–92·118–120·230–239) → 도킹 값이 같으면 GA seed가 달라도 재사용(M22 GA2 측정); 재사용 원천은 run 안의 모든 저장 M18 결과(단독·M19 행·GA 개체·M25 루프 도킹). M23 재사용 조건 `conditions_sha256` = 후보 집합·구조·리간드 SDF 해시·상자·`parameters`(평가 seed 포함)·정책·pin(`ga` 제외, `sequence_ga_inputs.py` 593–607), 원천은 **같은 run의 이전 서열 GA 개체뿐**(C2의 M21 모델·C3 짝은 재사용되지 않음). 1세대는 GA seed의 `random.Random`으로 뽑으므로 **GA seed를 같게 두면 설정 2가 설정 1의 1세대를 반드시 재사용**하고, "둘 이상 다름"은 세대·무작위 비율(·개체 수)로 채운다(M22는 개체 수를 바꾸면 `sample` 앞부분이 풀 크기에 따라 달라지므로 개체 수 고정 권고).

| B5 (M22) | 설정 1 | 설정 2 |
|---|---|---|
| GA seed / 개체 / 세대 / 이어받음 | 11 / 4 / 2 / 2 | 11 / 4 / **3** / 2 |
| 무작위 비율(→ 무작위 자리) | **0.2**(→ 0) | **0.5**(→ 1) |
| 토너먼트 / 이웃 / patience | 2 / 3 / 3 | 2 / 3 / 3 |
| 새 도킹 상한 / total_s | 6 / 600 | 8 / 600 |
| 예약 단위 / 필요 시간 | 6 / 1200 s | 8 / 1200 s |
| 도킹 값(두 설정·B3·B4·B7 공통) | 중심 (3.41, 0.72, 11.31), 12 Å, seed 1, exh 1, 모드 2, energy_range 3 | 같음 |
| 재사용 | B3·B4·B7과 겹치는 후보 | 1세대 4개 확정 + 그 밖 겹침, 새 도킹 ≤ 3 |
| 시간 [추정] | ≤ 약 70 s(exh 1) | ≤ 약 50 s |

| C4 (M23) | 설정 1 | 설정 2 |
|---|---|---|
| GA seed / 개체 / 세대 / 이어받음 | 21 / 4 / 3 / 1 | 21 / **6** / **2** / 2 |
| 교차 / 무작위 / 변이 수 상한 / patience | 0.5 / **0.25** / 3 / 3 | 0.5 / **0.5** / 3 / 3 |
| 새 평가 상한 / total_s | 10 / 600 | 10 / 600 |
| 예약 단위 / 필요 시간 | 22 / 1200 s | 22 / 1200 s |
| 입력 | C2의 1UBQ tiny 집합(3위치 × 2 → 조합 공간 26), 같은 평가 seed·도킹 값·상자·합성 페놀 SDF | 같음 |
| 재사용 | — | 기준 행 + 1세대 4개 확정, 새 평가 ≤ 6 |
| 시간 | 약 135 s([측정] 같은 모양 G04 134.7 s) | 약 80–90 s [추정] |

두 표 모두 바뀐 값은 명세 §3.1의 넷(개체·세대·seed·무작위) 중 B5는 세대·무작위 둘, C4는 개체·세대·무작위 셋이고 모두 상한 안이다.

**5. 분기별 단위·사람 증액 클릭(가장 큰 위험).** 명세 사례 표 순서를 한 run에서 그대로 돌리면:
- 분기 B: B1 2 + B2 2 + B3 1 = 5 → B4가 새 행 ≥ 4를 요구해 부족분 증액 → 남은 0 → B5 증액 → **B7이 `budget_blocked`로 실패**.
- 분기 C: C2 M7 1 + M21 1 + C3 2 = 4 → **C4가 22단위 증액 → 남은 0 → C6 실패**.

**권장 실행 순서**(사슬의 선행 관계는 그대로):
- **분기 B**: B1, B2, B3(+재제출), B6, B7(탐색형 → 활용형), B4, B5(설정 1 → 2), B8. 증액 불가 작업 합 2 + 2 + 1 + 2 = 7, 남은 1 → B4(후보 4 = B3·B7 계산분 3 + 새 1 + 부모 → 새 행 2) 증액 +1 → B5 설정 1 +6, 설정 2 +8. 합계 23단위, **증액 클릭 3번**. 활용형 바퀴의 저장 점수는 B3와 앞선 탐색형 바퀴 결과에서 온다(§6.1의 "B3·B4로"는 live에서만 B4를 앞에 둔다).
- **분기 C**: C1, C2, C3, C5, C6(탐색형 → 활용형), C4(설정 1 → 2), C7. 증액 불가 합 M7 1 + M21 1 + C3 2 + C6 4 = **정확히 8, 여유 0** → C4 +22, +22(설정 2 새 평가 상한 6이면 +14). **증액 클릭 2번.** 여유 0이므로 하네스가 각 계산 전에 남은 단위를 단언해야 한다(C6이 C2에서 모델링된 후보를 고르면 1바퀴 1단위로 줄어 여유가 생기지만 JEV 선택은 통제할 수 없다).
- **분기 A**: A4 fpocket 1단위, 증액 0.
- **live**(B와 C를 다른 run으로): B = L-pre-B2 2 + L-pre-B3 1 + L-pre-B4 4(후보 4 중 **B3 후보를 넣어** 새 행 3 + 부모) + L-B7 1 = **8, 여유 0, 증액 0**(L-pre-B4 새 행이 하나라도 늘면 L-B7이 막힌다). C = L-pre-C2 0–2 + L-C6 2 ≤ 4, 증액 0. B·C를 한 run에 넣으면 10단위 이상이고 증액 경로가 없다.
- 외부 예산: 전송 10회·120,000 토큰·USD 2.00은 run 공유. fixture 분기 B는 B6 1 + B7 2 = 3전송, C는 C5 1 + C6 2 = 3전송. fixture 서버는 정상 응답 스크립트만 쓴다(`no_usage`·`http_500`은 그 run의 외부 전송을 멈춤).
- **fixture 단계 사람 클릭 합계**: 증액 5번(B 3 + C 2) + run마다 첫 비싼 계산 승인 1번. 활동 시간 쪽 증액은 없을 것으로 본다(B5·C4 필요 1200 s, 그 전 활동 시간 사용은 수 분).

**6. 예상 시간 [추정].** fixture 분기 A 6–10분, B 8–10분(exh 1; exh 8 기본값이면 13–16분), C 7–9분, 감사·내보내기 1–3분 → **fixture 단계 약 25–40분**; `--rehearse` 5–10분; **live(실호출 2회) 6–12분**; 회귀 사슬 약 75분(측정 기준).

**결론.** 시간은 문제 없다. **명세 표의 사례 순서를 한 run에서 그대로 따르면 B7·C6이 예산 때문에 실패하므로 T7·T8은 위 권장 순서(루프를 GA·일괄보다 먼저)로 하네스를 짜야 한다.** 명세는 실행 순서를 정하지 않으므로 설계 결정이며, 분기 안에서 run을 나누는 다른 길은 "분기마다 새 격리 run" 문구와 맞지 않아 권하지 않는다. 도킹 값은 측정이 있는 작은 설정(exh 1)을 권한다.

## (f) 간헐 실패 시험 네 개(명세 §10.1)의 원인

**제품 코드에 명령줄 읽기가 없음.** `grep -rn "cmdline\|process_iter" backend/mw` → 0줄. 제품의 psutil 사용은 `psutil.pids()`·`Process(pid)`·`status()`·`children()`·`memory_info()`·비공개 `_proc.create_time(monotonic=True)`(`jobs/queue.py` 342–396, `jobs/guardian.py` 127–160·320–353, `jobs/process_identity.py` 34–75)뿐이고 모두 `psutil.Error`/`ProcessLookupError`/`OSError`를 잡아 "사라짐·확인 불가 = 불일치"로 다룬다. 시험 쪽 명령줄 읽기는 `backend/tests/test_sequence_ga_worker.py` 696(`process_iter(["name", "cmdline"])`)과 1063(`child.cmdline()`) 두 곳뿐이다(다른 시험 파일은 `["name"]`·`["name","exe"]`만).

**재현 시도.** (1) Stop 훅 `CHECKS[1:]` 18그룹을 한꺼번에 1회(아래 (j), 모두 exit 0, 6,037 passed) — 네 시험 모두 이번에는 통과(재현 안 됨). (2) psutil 경쟁 미세 시험(스크래치패드 `cmdline_race.py`, 60 s: 짧게 끝나는 `/bin/sleep` 20개씩을 띄우며 `Process(pid).cmdline()` 반복 + 매 회 시스템 전체 `process_iter(["name","cmdline"])`) → 정상 197,553, `ZombieProcess` 65,304, `AccessDenied` 343, 전체 순회 329회 정상, **`SystemError` 0** — 재현 안 됨. 따라서 원인은 아래의 **코드 근거**로 가린다(실패 출력은 인계·`findings.md` 556–561행 기록).

| # | 시험 | 원인(코드 근거) | 제품/시험 | 결정적으로 묶을 지점(T2 후보) |
|---|---|---|---|---|
| 1 | `test_sequence_ga_worker.py::test_a_failed_reference_row_ends_the_run_before_any_individual[…]`(관찰: `[reference_stream_after_exit-status5-False]` 2026-10-11, `[reference_size_bound-status9-False]` M27) — `SystemError: <built-in function proc_cmdline> returned a result with an exception set` | 이 시험은 989행에서 `_engines_under(out.root) == []`를 단언한다(같은 보조 함수를 1021행 등 다른 시험도 쓴다). `_engines_under`(693–702)는 **시스템 전체** 프로세스를 `psutil.process_iter(["name", "cmdline"])`로 돈다. psutil 7.2.2는 `proc.info = proc.as_dict(attrs)`를 생성기 안(`psutil/__init__.py` 1557–1558)에서, 즉 시험의 `try` **밖**에서 계산하고, `as_dict`는 `AccessDenied`·`ZombieProcess`만, `process_iter`는 `NoSuchProcess`만 잡는다. `_psosx.Process.cmdline` = `cext.proc_cmdline(pid)`이고 `wrap_exceptions`는 `ProcessLookupError`·`PermissionError`·`ZombieProcessError`만 바꾸므로 C 확장이 낸 `SystemError`는 그대로 for 문 밖으로 나가 시험 오류가 된다. 부하 중(다른 그룹이 프로세스를 많이 띄우고 끝냄) 아무 프로세스나 읽는 순간 끝나면 생길 수 있다. 게다가 `_engines_under`는 `cmdline`을 **쓰지 않는다**(`cwd()`·`status()`만). `_wait_for`(1055–1074)의 `child.cmdline()`도 `except psutil.Error`만 잡는다. | **시험 보조 코드**. 제품은 `proc_cmdline`을 부르지 않으므로 이 `SystemError`가 제품 경로에서 날 수 없다 → 제품 코드 변경 불필요 | `_engines_under`의 attrs에서 쓰지 않는 `"cmdline"`을 빼고(또는 `["name"]`), `_wait_for`에서 `SystemError`를 `psutil.Error`와 같이 "이미 없는 프로세스"로 잡는다 |
| 2 | `test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]` — 작업 폴더에 `0.model.cif` 등이 더 있는 채 `== {'0.started': b''}` 실패(M26·M27·2026-10-11 관찰) | `_wait_for`가 qvina2 자식과 `individuals/0.started`를 본 뒤(10 ms 폴링, 자식마다 `name()`·`cmdline()`) `os.kill(worker, SIGTERM)`을 보낸다. 작업 모듈 `_dock`(`sequence_ga_worker.py` 885–916)은 `dock_row`가 돌아오는 즉시 `_quiet()`로 신호를 막고 끝난 도킹을 지키며, `_store`(918–928)가 `model.json`·`model.cif`·`result.json`·`status.json`을 쓰고, 막힌 SIGTERM은 다음 확인의 `cancelled`가 된다 — 시험 `test_a_finished_docking_survives_a_late_sigterm`이 확인하는 **설계된 늦은 신호 동작**이다. 이 개체의 도킹은 합성 페놀(변이 구조 도킹 2.8 s, M23 개체 안 0.8–1.6 s)이라 짧아서, 부하 중 감지 → 신호 사이 시간이 qvina2 남은 시간보다 길면 관찰된 실패가 된다 | **시험 쪽 경쟁**(제품 동작은 명세대로) | qvina2를 감지하면 신호 전에 `psutil.Process(pid).suspend()`(SIGSTOP)로 단계를 붙잡아 "단계가 끝나기 전" 상태를 보장한다. `run_qvina`는 `subprocess.run(capture_output=True)`(`docking_worker.py` 836–841)라 `_Stop` 예외 때 `Popen.kill()`(SIGKILL)로 정리되므로 멈춘 프로세스도 끝난다(T2가 실제로 확인) |
| 3 | `test_jev_reports.py`의 `str(0.1234) not in dumped`(133–134) | 표지 `PROBABILITY_VALUES = (0.4321, 0.1234)`(25)를 **부분 문자열**로 검사하는데 `dumped = canonical_json(manifest)`(131)에는 `snapshot.time_utc` = 마지막 이벤트 `ts` = `time.time()` 부동소수(`core/events.py` 66, `jev_reports.py` 351)와 `snapshot.budget.wall_clock_s.used` 부동소수(`runtime/orchestrator.py` 572–577)가 들어 있다. 정수부가 0으로 끝나고 소수부가 `1234`(또는 `4321`)로 시작하면(예: `…330.1234…`, `10.1234…`) 겹친다(값 하나당 약 10⁻⁵) | **시험 쪽 표지 선택** | 부분 문자열 대신 manifest JSON을 걸어 숫자 값이 표지와 같은 것이 없는지 보거나, 부동소수 표현에 나올 수 없는 표지(예: 확률 키·필드 이름 검사 + 값 구조 검사)로 바꾼다 |
| 4 | `test_pocket_jobs.py::test_running_engine_is_stopped_with_its_process_group[output_files]`(M26 고정 게이트 관찰) | 시험 훅 `act_on_running_engine`(815–832)이 큐의 STARTED 처리 안에서 fpocket 자식을 찾은 뒤 `fpocket_tmp`에 빈 파일 1,001개를 쓴다. 출력 상한은 guardian이 **작업 프로세스가 살아 있는 동안에만**(`while child.poll() is None`, 약 25 ms마다 `pocket_output_exceeded()`, `guardian.py` 320–331, 상한 `POCKET_OUTPUT_FILES = 1000` 79) 보고 끝난 뒤의 최종 확인은 없다. 부하 중 파일 1,001개를 쓰는 사이 또는 다음 표본 전에 fpocket(1HSG 6벌 파생 입력)이 끝나면 정상 완료가 되어 `failed`/`resource_exceeded` 단언이 깨진다 | **시험 쪽 경쟁**(제품 상한 검사는 "실행 중"이 계약) | 파일을 쓰기 전에 fpocket 자식을 `suspend()`해 작업이 살아 있는 동안 guardian이 표본을 뜨게 한다(guardian 정리는 그룹 종료로 끝냄; T2가 확인) |

**결론.** 네 가지 모두 시험 보조 코드·시험 표지·시험 쪽 경쟁이 원인이고, 제품 프로세스 신원 확인 경로에는 `SystemError`를 낼 명령줄 읽기가 없다 → 명세 §10.1의 "제품 코드 변경은 필요하지 않을 것" 전제가 맞다. T2는 시험만 고친다(해시 고정 파일 `sequence_ga_worker.py`·`docking_worker.py`는 읽기만 했다).

## (g) M20 보고서 참조 출처표 (명세 §10.2, T3 준비)

조사: 읽기 전용 서브에이전트가 `mutation_reports.py`·M15/M16/M26/M27 보고서 모듈·시험·하네스·골든을 읽었고, 아래 ★A(기준선 비교 시험)와 상수 위치는 직접 확인했다. 행 번호는 HEAD `287a37a8` 기준.

**1. M20 보고서가 참조값을 인용하는 지점(`backend/mw/mutation_reports.py`).** 주장 생성 `claims_for`(324–420)의 참조 주장 셋은 모두 `reference = {"note": REFERENCE_NOTE, "reference_object": <handle>}`이고 세트 해시·버전·출처·라이선스가 없다: UniProt accession(381–392, `parameters["numbering_map"]`, 주장 `reference_uniprot_accession`), KLIFS 부위 이름표(393–405, `parameters["annotation"]`, `reference_klifs_site_label`), v2 M-CSA 항목 ID(406–419, `parameters["catalytic_annotation"]`, `reference_mcsa_entry_id`). 본문은 handle만 찍는다(540–542, 587, 601–617, 632–664). 파일 안 `set_hash`·`license`·`snapshot_set`·`origin`·`KLIFS_TERMS` 검색 0건 → 출처표 없음 확인. 상수: `ANALYSIS_TYPE` 70, `RENDER_VERSION = "mutation_candidates_markdown@1"` 71(직접 확인), `REFERENCE_NOTE` 73, `FIXED_LIMITATIONS` 76, `STATEMENTS` 111–131, `SNAPSHOT_KEYS` 142, `COPIED_FIELDS` 143–144, `MANIFEST_KEYS` 145(직접 확인). 함수: `_expected` 473–487(`render_version` 고정값, 478), `render_mutation_report` 493–625(슬롯 비운 템플릿 금지어 검사 623–625), `build_mutation_report` 667–691, `saved_mutation_report` 694–734.
- 다시 열기 순서: meta → `set(report) != MANIFEST_KEYS` 또는 `render_version != RENDER_VERSION`이면 거절(700–702, 직접 확인 701) → `_expected` 재구성 → 주장마다 `match_claim` → 기대 키 `canonical_json` 비교 → 스냅숏·이벤트 → Markdown 메타 → `method_report_created` 1건 → Markdown 재렌더 바이트 비교(731–733).
- 호출자: `app.py` `POST /runs/{rid}/method_reports`(1275, `mutation_candidate_set`이면 1317–1319), 다시 열기는 `_saved_any_report`(1376–1427)가 `analysis_type`으로 분기(1414–1415) → **`render_version`으로 고르지 않으므로 `app.py`는 고칠 필요가 없다.**

**2. 스냅샷 출처·이용 조건 표의 선례와 문구 상수.**
- M15 `numbering_reports.py`: `SOURCE_LABELS` 44, `REFERENCE_NOTE` 45, `PROCESSED_LABEL = "kbase_kinase 가공본"` 46, `KLIFS_TERMS = "이용 조건 명시 없음(none-stated)"` 47, `REFERENCE_STATEMENT` 48–50, `SNAPSHOT_SCOPE` 57–58. manifest 키 `snapshot_set`·`reference_set_handle`·`klifs_terms`(95–99). 표 렌더 493–502: "Reference snapshot set: {set_hash} (object {reference_set_handle})", `## 참조 스냅샷`, 머리줄 `| 출처 | 버전 | 날짜 | 스냅샷 ID | 라이선스 | 가공 |`, 행(라벨·`version_hint`(null → "none (null)")·`date`·`snapshot_id`·`_license_text`(KLIFS면 `KLIFS_TERMS`)·`PROCESSED_LABEL`), "- KLIFS: {klifs_terms}…", "- Origin: {origin}".
- M16 `site_annotation_reports.py`: M15 상수 재사용, manifest 키 84–88, 표 561–575(번호 대응의 세트), 활성 세트·stale 줄 563–565(값은 `app.py` 1301–1302가 넘기는 `active_set_hash`).
- M26 `reaction_knowledge_reports.py`: `PROCESSED_LABEL = "공개 서버에서 가져온 가공본"` 63, `LICENSE_LABEL = "CC BY 4.0"` 64, `SOURCE_LABELS` 65, `K.STATEMENTS["RK6"]`(`reaction_knowledge_constants.py` 134), `K.LICENSE` 62, `K.ORIGIN` 64. manifest `snapshot_set`(`COPIED_FIELDS` 155). 표 601–613: RK6, 머리줄 `| 출처 | 날짜 | 세트 해시 | 가공 행 수 | 라이선스 | 가공 |`, 가져온 시각·importer·ORIGIN, 활성 세트 줄.
- M27(비교용, M20이 인용하지 않음): `kinase_precedents_reports.py` 51·55, 표 617–643.

**3. 인용 객체 안의 세트 식별자.** `residue_numbering_map@1`: `snapshot_set = {set_hash, origin, sources[{source, snapshot_id, date, version_hint, license, file_sha256s}]}`(`residue_numbering.py` 345–351). `reference_site_annotation@1`: `snapshot_set_hash`와 `numbering_map` handle만(세트 전체는 그 번호 대응을 거쳐 얻음; 주석만 주고 번호 대응을 주지 않는 M20 입력도 통과하므로 `annotation["numbering_map"]`을 읽어야 한다). `reaction_knowledge@1`: `snapshot_set = {set_hash, imported_at, importer_version, sources[{source, date, license, origin, files[{name, sha256, bytes, rows}]}], requested_accessions, skipped_accessions}`(`reaction_knowledge.py` 191–199). `mutation_candidate_set@1`/v2는 `parameters.numbering_map`·`annotation`·`catalytic_annotation`(v2) handle만 저장(`mutation_candidates.py` 286–288, 568–569)하고 보고서의 `validated_mutation_set`(284–292)이 이미 이 handle들을 저장소에서 읽는다 → **`mutation_candidates.py`를 건드리지 않고 세트를 찾을 수 있다.**

**4. 형식 버전 @2(@1 병존) 방법 — `mutation_reports.py` 한 파일 안.**
1. 렌더 버전 상수를 둘로(@1·@2). `RENDER_VERSION` 이름을 밖에서 쓰는 곳 없음.
2. `MANIFEST_KEYS`를 버전별로: @2 = @1 + 표 데이터 키(예: 번호 대응 세트·반응 세트 사본).
3. `_expected(run, handle, version)`: @2에서만 새 키. 주장 집합은 두 버전 같게(→ `({n} claims)` 줄 불변).
4. `validated_mutation_set`이 이미 읽은 대응·주석·반응 결과를 함께 돌려준다(★C).
5. `render_mutation_report`: `render_version == @2`일 때만 표 절을 끼운다. @1 경로의 기존 줄은 한 글자도 바꾸지 않는다.
6. `build_mutation_report`: 버전을 고른다(★A).
7. `saved_mutation_report` 700–703: 허용 버전 집합, 버전별 키 집합, `_expected(..., report["render_version"])`. 나머지 순서 그대로.
- 선례: `pocket_reports.py`(`pocket_markdown@2`가 @1도 받음, 26–29·233·326–330; 단 두 버전의 키 집합이 같다), `numbering_reports.py` 52–59·638–639(옛 한계 문장 목록 수용), `saved_scenes.py` 39–40(`viewer_scene@2`·`viewer_figure@2`).
- **해시 영향 없음**: `mutation_reports.py`·`mutation_constants.py`는 27개 해시 파일, `golden_call_keys.json`의 `hashed_files`(6)·`also_hashed_files`(11), `mutation_model_bundle.DEPENDENCIES`(49–51), `sequence_ga_inputs.M21_MODULES`(66) 어디에도 없다(뒤 둘은 `mutation_candidates.py`만 포함). M20 고정 문장(`mutation_constants.py` 113–130: `LIMITATIONS` 5문장, `LIMITATIONS_V2`·`LIMITATION_3_CHECKED`·`LIMITATION_3_NOT_CHECKED`)은 결과 객체에서 복사해 쓰므로 고칠 필요가 없다. 골든 셋에 M20 보고서 바이트 없음(`golden_science_m24.json`은 `jev_choice_markdown@1`만).

**T3가 지켜야 할 제약.**
- **★A (명세 해석 결정 필요)**: `backend/tests/test_mutation_api.py` 467–512(`test_stored_v1_sets_keep_the_t1_baseline_reads_validation_and_report_bytes`, 직접 확인)는 수정 금지 폴더 `docs/qa/m26-reaction-20261008/v1-baseline/baseline/`의 보고서 manifest·Markdown 바이트와, 그 폴더의 `record_v1_baseline.py`가 **지금 코드로 새로 만든** v1 집합 보고서를 비교한다(대상 v1 집합 다섯 + 고정 집합 둘은 모두 번호 대응·주석·촉매 주석이 없다). 그래서 "새 보고서는 모두 @2"로 하면 이 시험이 깨지고, 기준 바이트는 고칠 수 없다. **권고: 번호 대응·주석·반응 지식(`catalytic_annotation`) 중 하나라도 인용할 때만 @2, 인용이 없으면 지금 @1 바이트 그대로**(명세 §10.2 "인용하지 않는 보고서는 표를 싣지 않고"·계획 T3 "인용 없는 보고서 불변"과 맞음). 이 해석을 조율 세션이 정해야 한다.
- **★B 순환 import**: `reaction_knowledge_reports.py` 41이 `mutation_reports`를 맨 위에서 import하고 49–51에서 `mr.REPORT_BYTES` 등을 모듈 수준으로 읽는다. `mutation_reports`가 맨 위에서 `reaction_knowledge_reports`를 import하면 순환 오류. 문구는 이미 import된 `reaction_knowledge_constants`(`STATEMENTS["RK6"]`, `ORIGIN`, `LICENSE`)에서 가져오고 `LICENSE_LABEL`·`PROCESSED_LABEL`·`SOURCE_LABELS`는 함수 안 지연 import 또는 문자열 복사 + 같은지 확인하는 시험.
- **★C 반응 결과 검증 1회**: `test_mutation_reports.py` 618–630이 다시 열 때 `rk.validated_result` 호출이 정확히 1회인지 본다 → 표 데이터는 `validated_mutation_set`이 이미 읽은 결과에서 꺼낸다.
- **★D 소스 문자열 시험**: `test_mutation_reports.py` 439–443(소스에 `requests`·`structure_residues`·`_parse(`·`gemmi`·`numpy` 없음 → `site_annotation_reports.validated_annotation`을 부르지 않는다), `frontend/tests/reaction-knowledge.test.cjs` 765·`kinase-precedents.test.cjs` 1074(소스의 첫 `INTERPRETIVE = re.compile(` 블록 138–141을 문자열로 읽음 → 건드리지 않는다), `mr.INTERPRETIVE`·`REPORT_BYTES`·`REFERENCE_NOTE`·`CLAIM_KEYS`는 M21·M26이 쓰므로 값 불변.
- **★E** `check_sources` 위치 인자 `(content, map, annotation, pocket[, catalytic])` 유지(시험 404·416·418·576–602가 직접 호출).
- 조율 세션이 정할 것(추가 둘): (1) 반응 세트 표를 싣는 조건 — 명세 문언 "M-CSA 항목 ID를 인용하면"(ID 주장은 다룬 체인이 있을 때만 생김, 406–419) vs `catalytic_annotation` handle이 보고서에 있을 때(542·632·638·661); (2) M26 표의 "가공 행 수" 열 — M26에서는 반응 결과를 근거로 한 주장이지만 M20 `match_claim`은 근거가 M20 집합인 주장만 받으므로(449–454) manifest 사본으로 렌더하고 다시 열 때 저장 객체와 대조하거나, 열을 빼거나(새 주장 종류는 닫힌 `STATEMENTS`를 바꾸므로 불가). (3) 활성 세트 줄(M16 563–565·M26 612–613)은 `app.py`가 `active_set_hash`를 넘겨야 하므로(M20 경로 1319는 넘기지 않음) `app.py`를 고치지 않으려면 뺀다.

**5. M20 보고서 본문을 기대로 쓰는 곳(카디널리티 결합 지도).**

| 파일 | 위치 | 보는 것 | @2 영향 |
|---|---|---|---|
| `backend/tests/test_mutation_reports.py` | 193–194 | 인용 없는 집합의 `render_version == …@1` | ★A 권고면 불변 |
| 〃 | 243–252 | 표 줄 수 상한, 한계 문장, 다시 열기·목록·다운로드 바이트 동일 | 불변(인용 없음) |
| 〃 | 272–292 | 1MQ4(번호 대응 + 주석) 보고서의 참조 주장 집합·REFERENCE_NOTE | @2가 됨 — 기대 갱신 |
| 〃 | 361–383 | 변조 7종, 목록 422 | @2 키 추가 반영 |
| 〃 | 386–396, 399–418, 571–602 | `mc` 차단 다시 열기, `check_sources` 직접 호출(★E) | 시그니처 유지 |
| 〃 | 439–443, 643–648 | 금지 문자열(★D), 금지어 | 유지 |
| 〃 | 446–479, 488–568 | BEST/SAFE, 촉매 `cat`·`cat_partial`·`cat_none`의 Markdown 부분 문자열 정확 비교(513–517) | 촉매 인용이면 @2 — 기대 갱신 |
| 〃 | 618–640 | 반응 결과 검증 1회(★C) | 유지 |
| `backend/tests/test_mutation_api.py` | 48, 467–512 | v1 기준선 바이트(수정 금지 폴더) | ★A |
| `backend/tests/test_jev_reports.py` | 22, 306–320 | M20 보고서 전후 Markdown·다시 열기 동일, 목록 3건 | 견딤 |
| `backend/tests/test_mutation_model_reports.py`·`mutation_model_fixture.py` | 197·225–238·130 | M20 보고서 다시 열기 동일, 목록 200 | 견딤 |
| `backend/tests/test_sequence_ga_reports.py` | 약 600–620 | M20 보고서 다운로드 전후 바이트, 목록 4건 | 견딤 |
| `backend/tests/test_mutation_model_pairs.py` | 33, 51 | `m20.INTERPRETIVE`만 | 유지 |
| `frontend/tests/reaction-knowledge.test.cjs`·`kinase-precedents.test.cjs` | 765·1074 | `INTERPRETIVE` 소스 파싱 | 유지(★D) |
| `frontend/tests/mutations.test.cjs`·`mutation-model.test.cjs` | 474–480·392 | `analysis_type`·라벨 | 견딤 |
| `frontend/tests/offscreen/mutation-flow.cjs` | 1248–1301(M-report) | 1MQ4 + 번호 대응 + 주석(→ @2): `analysis_type`, result handle, 라벨, 화면 = 저장 Markdown 해시, not_checked 한계 5문장, 다운로드 = 백엔드 바이트 | `render_version`·표를 보지 않음 → 고치지 않아도 될 것(T3이 M20 실행기로 확인) |
| `frontend/src/lib/contracts.ts`·`report-library.ts` | 799–801·94 | `render_version` 고정 안 함 | 견딤 |
| 다른 오프스크린 흐름(`jev-flow`·`jev-loop-flow`·`mutation-model-flow`·`sequence-ga-flow`·`reaction-knowledge-flow`) | — | 자기 종류 보고서만 만듦 | 영향 없음 |
| 제품 M24/M25 경로(`jev_projection`·`jev_loop_*`·`jev_sends`·`tools/jev*`) | — | `method_report` 검색 0건 | 영향 없음 |
| 실행기 `m20_offscreen_acceptance.py` 77·114, `scripts/test_m20_offscreen_acceptance.py` | — | 설명·사례 구조만 | 영향 없음 |
| 골든 셋 | — | M20 보고서 바이트 없음 | 영향 없음 |
| 문서 `docs/contracts.md` 406, `docs/business-rules.md` 638, `docs/tracking/findings.md` 399–403 | — | `render_version @1` 서술, 이 문제 항목 | T17·T18 |

- **@1 옛 보고서 fixture**: 인용이 있는 @1 M20 보고서를 담은 커밋된 이벤트 로그는 없다(있는 것은 `docs/qa` 다운로드 증거와 인용 없는 v1 기준선뿐). 이벤트 로그만으로 저장소를 다시 만들 수 있으므로(`core/handles.py` 237–255, 선례 `fixtures/reaction/t1/v1-run-run_m23_golden_keys.events.jsonl` 232,554 B), **T3는 코드를 바꾸기 전에 지금 코드로 인용 있는 @1 보고서(1MQ4 번호 대응 + 주석, 합성 촉매 집합)를 담은 로그를 기록해 두어야 한다**(추정 1–2 MB; 256 KiB 초과면 커밋 위치를 조율 세션이 정한다).

**결론.** 해시 파일·닫힌 집합·고정 문장·결과 객체 형식을 건드리지 않고 `mutation_reports.py` 한 파일로 가능하다(멈출 조건 아님). 다만 ★A 때문에 "새 보고서에 @2"를 "참조값을 인용하는 새 보고서에 @2"로 읽는 결정과, 반응 표의 싣는 조건·행 수 열·활성 세트 줄의 결정이 T3 전에 필요하다.

## (h) 미해결 문제 수 (`docs/tracking/findings.md`)

- 파일: 733줄, 125,527 B. 맨 위 `# 미해결 문제` 한 줄, 그 아래 절은 모두 `## ` 제목이다. `### ` 제목 0, 코드 울타리(```) 0.
- **절을 세는 규칙**: Python `re.findall(r"(?m)^## (.+)$", text)` → **128**(제목 문자열 128개 모두 서로 다름). T18의 "모든 항목이 정확히 하나의 최종 분류" 검사는 이 128절 각각의 본문(다음 `## ` 줄 전까지)에 `^- \*\*최종 분류\(M28\)\*\*: (해결|수용|사용자 결정 필요|범위 밖) — ` 줄이 정확히 하나인지로 센다. 지금 `최종 분류(M28)` 줄은 0개.
- **이미 해결로 표시된 절**: 제목에 `(해결됨`이 있는 절 **10**개(73·100·149·303·313·389·405·439·461·659행 제목). 그 밖에 제목 `(일부 해결, M18) M17 후보에는 3D 좌표·점수가 없다`(217행) 1개는 "(해결됨"이 아니므로 자동 `해결`이 아니다. 제목에 "해결"이 들어간 절은 합계 11.
- 본문 안의 "해결" 기록(예: 절 끝의 "M27 관찰")은 세지 않았다.
- 명령: `.venv/bin/python -c 're.findall(r"(?m)^## (.+)$", text)'`(위 규칙), `grep -c '^## '` = 128, `grep -c '^### '` = 0, ``grep -c '^```'`` = 0.

**결론.** 최종 분류 대상은 128절이고, 그중 제목이 `(해결됨`인 10절은 명세 §11.3에 따라 `해결`, 나머지 118절은 T18이 근거에 따라 분류한다.

## (i) 설치 시험 준비

**Python 핀(`backend/pyproject.toml`).** `requires-python = ">=3.11"`. 정확 고정 6개: gemmi 0.7.5, numpy 2.4.6, freesasa 2.2.1, openmm 8.6.0, pdbfixer 1.12.0, psutil 7.2.2(과학) — 범위 지정 7개: pydantic ≥2.6, pyyaml ≥6, httpx ≥0.27, anyio ≥4, fastapi ≥0.110, uvicorn ≥0.29, pyarrow ≥15. `dev` = pytest ≥8, ruff ≥0.4. **Python 잠금 파일은 없다.** 그래서 설치 시험의 `pip install -e './backend[dev]'`는 그날의 PyPI 최신(범위 안) 버전을 받는다. 지금 `.venv`의 해석 버전(대조용): fastapi 0.141.1, starlette 1.7.0, pydantic 2.13.5, uvicorn 0.53.0, httpx 0.28.1, anyio 4.15.1, PyYAML 6.0.3, pyarrow 25.0.1, pytest 9.1.1, ruff 0.16.8, pdbfixer 1.12.0(배포 31개). pdbfixer 1.12.0은 PyPI에 sdist만 있어 빌드 때 setuptools를 격리 빌드 환경으로 내려받는다(`docs/operations.md` "M21 PDBFixer"). 새로 받은 범위 버전이 깨지면 핀 변경이 필요하므로 명세 §9에 따라 멈추고 묻는다.

**npm 핀(`frontend/package.json` · `package-lock.json`).** `lockfileVersion` 3, 패키지 288개(루트 포함), `resolved` 287개 모두 `registry.npmjs.org`, `integrity` 없는 항목 0. 정확 고정: molstar 5.11.0, next 15.5.26, react·react-dom 19.1.9, electron 44.4.5, playwright 1.63.0. 범위(잠금으로 고정됨): `@fontsource/*` ^5.3.0(잠금 5.3.0), `@types/node` ^22(22.20.4), `@types/react`·`react-dom` ^19(19.3.0), typescript ^5.6(5.9.3). `engines` 없음. electron 설치 스크립트가 실행 파일을 따로 받는다(호스트는 T13이 관찰해 장부에 적는다; 캐시가 있으면 받지 않을 수 있다).

**README vs `docs/operations.md`.**

| 단계 | README.md(현재) | operations.md "처음 설치" | 명세 §9 | 판정 |
|---|---|---|---|---|
| venv | `python3 -m venv .venv` (18행) | `python3.11 -m venv .venv` | `python3.11 -m venv .venv` | **다름.** 이 컴퓨터의 `python3`은 3.10.9(anaconda)라 README대로면 `requires-python >=3.11`에서 설치가 실패한다 → T4가 README를 고친다 |
| 백엔드 설치 | `.venv/bin/python -m pip install -e './backend[dev]'` | 같음 | 같음 | 같음 |
| 프런트 설치·빌드 | `npm --prefix frontend ci` → `run build` | 같음 | 같음 | 같음 |
| 실행 | `uvicorn mw.api.app:app --host 127.0.0.1 --port 8000` / `npm --prefix frontend run start -- -p 3000` | 같음 | 같음 | 같음 |
| 필요 조건 | "Python 3.11 이상, Node.js 22 이상" | "CPython 3.11 이상 … Node.js 22 이상", POSIX, 화학 환경은 macOS arm64 전용 | 지원 환경 문장(§3.2 7번) | README에 지원 환경 문장·외부 요청 정책·공유 제외 폴더 없음(T4) |
| 검증 명령 | `ruff check backend/mw backend/tests`, 스크립트 pytest 2개, `execute.py --dry-run`, "GPT-6 Astra가 설계와 검토를 맡고 GPT-6 Sol이 구현" | `docs/standards.md` 게이트(ruff 다섯 경로, 스크립트 24개, `node --check` 16개) | — | README가 낡았다(M12까지). T4 대상 |

**선택 환경 설치 명령 ↔ 스크립트 인자 ↔ `config/` 잠금 파일(정적 대조, 실제 설치 안 함).**

| 환경 | operations.md 명령 | 스크립트 인자(add_argument) | 잠금 파일(스크립트가 참조) | 잠금 항목 수 | 문서의 수 | 일치 |
|---|---|---|---|---|---|---|
| M11·M17 ProLIF/RDKit | `scripts/setup_prolif_worker.py --wheelhouse <dir>` | `--wheelhouse`, `--destination` | `config/chemical/prolif-wheel-hashes-macos-arm64-py311.json`, `prolif-requirements-macos-arm64-py311.txt` | 33 / 33줄 | 33 | 예(`--destination`은 문서에 없음, 선택 인자) |
| M12 fpocket | `scripts/setup_fpocket.py --pkgs <dir>` | `--pkgs`, `--prefix`, `--conda` | `config/pockets/fpocket-conda-lock-hashes-osx-arm64.json`, `fpocket-conda-explicit-osx-arm64.txt` | 35 / 35줄 | 35 | 예(`--prefix`·`--conda`는 문서 명령에 없음, 선택 인자) |
| M18 qvina | `scripts/setup_qvina.py --pkgs <dir> [--prefix …] [--conda …]` | `--pkgs`, `--prefix`, `--conda` | `config/docking/qvina-conda-lock-hashes-osx-arm64.json`, `qvina-conda-explicit-osx-arm64.txt` | 8 / 8줄 | 8 | 예 |
| M18 도킹 작업 | `scripts/setup_docking_worker.py --wheelhouse <dir> [--destination …]` | `--wheelhouse`, `--destination` | `config/docking/docking-wheel-hashes-macos-arm64-py311.json`, `docking-requirements-macos-arm64-py311.txt` | 26 / 26줄 | 26 | 예 |
| M21 PDBFixer | `pip install -e './backend[dev]'`이 함께 설치(또는 `uv pip install --require-hashes`) | — | `backend/pyproject.toml` `pdbfixer==1.12.0` | — | — | 예 |
| M15 참조 | `scripts/import_reference_snapshots.py --from ../kbase_kinase --dest .deps/reference` | `--from`, `--dest` | — | — | — | 예 |
| M26 반응 참조 | `scripts/import_reaction_references.py [--accession]… [--accessions-file] [--no-kinases] [--reference-dir] [--yes]` | 같은 다섯 | — | — | — | 예 |
| M27 전례 참조 | `scripts/import_precedent_snapshots.py --from <kbase>` | `--from`, `--dest`, `--yes` | — | — | — | 예 |

설치 시험 폴더에는 `.deps`가 없으므로 선택 기능은 모두 "사용할 수 없음 + 이유"여야 한다(ProLIF·RDKit `worker_missing`, fpocket·qvina·도킹 미설치, 참조 셋 `not_installed`). 반대로 OpenMM 최소화와 `methods.mutation_model`은 핵심 설치만으로 사용 가능일 수 있다(`mutation_model_bundle.capability`는 OpenMM 8.6.0 힘장·PDBFixer 1.12.0·프로세스 신원 어댑터만 본다, `backend/mw/mutation_model_bundle.py` 133–149행; 같은 조건 도킹·서열 GA처럼 qvina가 필요한 기능은 사용할 수 없음). T13이 `/capabilities`로 실제 값을 기록하고 이 기대와 대조한다.

**결론.** 핀·잠금 파일을 바꿀 필요는 보이지 않는다(멈출 조건 아님). README의 venv 명령(`python3` → `python3.11`)과 낡은 검증·역할 서술은 T4가 고친다. Python 핵심 의존은 잠금이 없어 설치 시험이 그날의 PyPI 버전을 받으므로, T13은 해석된 버전 목록을 기록하고 지금 `.venv`의 버전과 나란히 적는다.

## (j) Stop 훅 시간 여유와 M28 새 시험의 그룹

**명령.** 스크래치패드 `run_groups.py`가 `.codex/hooks/stop.py`를 파일 경로로 불러 `CHECKS[1:]`(pytest 18그룹)을 Stop 훅과 같은 인자로 **한꺼번에** 띄우고(그룹 제한 없이) 그룹별 시간·exit·요약을 `<P>/stop-groups-run1/`에 남겼다. 다른 QA 서비스는 떠 있지 않았다.

| 그룹 | 첫 인자 | 통과 | 이번(동시) s | M27 게이트(동시) s |
|---|---|---|---|---|
| 1 | `test_chemical_interactions.py` | 24 | 372.4 | 357.5 |
| 2 | `test_m11_job_api.py` | 25 | 324.4 | 305.1 |
| 3 | `test_docking_inputs.py` …(`test_pocket_jobs.py` 포함) | 220 | 371.6 | 342.7 |
| 4 | `test_docking_batch_worker.py` … | 120 | 356.6 | 334.7 |
| 5 | `test_docking_batch_inputs.py` … | 390 | 360.5 | 340.0 |
| 6 | `test_ligand_ga_jobs.py` | 12 | **373.6** | 352.8 |
| 7 | `test_ligand_ga_worker.py` | 15 | 339.2 | 324.2 |
| 8 | `test_sequence_ga_jobs.py`(긴 2개) | 2 | 345.2 | 319.1 |
| 9 | `test_sequence_ga_jobs.py`(나머지 12개) | 12 | 306.8 | 280.3 |
| 10 | `test_sequence_ga_api.py` | 24 | 346.2 | 326.1 |
| 11 | `test_sequence_ga_reports.py` | 20 | 368.6 | 348.1 |
| 12 | `test_sequence_ga_worker.py` … | 418 | 334.5 | 302.1 |
| 13 | `test_mutation_model_worker.py` …(`test_openmm.py` 포함) | 247 | 343.5 | 316.0 |
| 14 | `test_jev_loops_read.py` … | 202 | 214.5 | 195.0 |
| 15 | `test_jev_loops_compute.py` | 43 | 263.1 | 238.9 |
| 16 | M27 백엔드 일곱 파일 | 557 | 47.8 | 42.3 |
| 17 | `test_analysis_workflows.py` + `test_jev_loop_reports.py` | 129 | 257.1 | 231.6 |
| 18 | 나머지(`backend/tests` − 이름 있는 파일 + `SCRIPT_TESTS` 24개) | 3,577 | 370.7 | 323.2 |
| 합 | | **6,037**(모두 exit 0, skip 0, 실패 0) | 전체 벽시계 **373.6** | 357.5 |

이번 측정은 M27 게이트보다 그룹마다 약 5–15% 느렸다(같은 소스, 기계 상태 차이). 제한은 그룹당 480 s(`CHECK_TIMEOUT`)이고 가장 느린 그룹 여유는 약 106 s, 나머지 그룹(18) 여유 약 109 s다.

**M28이 더할 시험과 넣을 그룹.**
- T3: `backend/tests/test_mutation_reports.py`(와 필요하면 `test_mutation_api.py`)에 @2 시험을 더한다 — 이 두 파일은 이름 있는 그룹에 없으므로 **나머지 그룹(18)**. 지금 두 파일 단독 42 passed, 4.77 s.
- T5–T8: `scripts/test_m28_offscreen_acceptance.py`, `scripts/test_m28_branch_{a,b,c}.py`(서비스 없음) → `SCRIPT_TESTS`에 손으로 넣는다(`scripts/test_codex_hooks.py` 177행이 `SCRIPT_TESTS` = `scripts/test_*.py` 글롭을 검사하므로 파일을 만드는 커밋에서 같이 넣어야 함; `len(stop.CHECKS) == 19`(145행)는 그룹을 더하지 않으면 그대로) → **나머지 그룹(18)**. 비슷한 기존 실행기 단위 시험 단독 시간: M25 99개 11.0 s, M24 77개 3.2 s, M27 55개 1.5 s.
- T2: 기존 시험만 고치므로 그룹 변화 없음.
- 예상: 더하는 시험은 단독 합계 수십 초 이하로 보이며 동시 부하에서 1.5–2배를 잡아도 나머지 그룹 여유(약 109 s) 안이다. **T9가 새 시험을 넣은 뒤 18그룹 동시 실행을 다시 재고, 나머지 그룹이 동시 440 s를 넘으면 이름 있는 그룹을 하나 더 나눈다**(예: `test_mutation_*`·`test_jev_*` 나머지 파일). 그룹을 더하면 `test_codex_hooks.py`의 `len(stop.CHECKS) == 19` 기대도 T9가 고친다.

**결론.** 지금 소스의 18그룹은 동시 실행에서 모두 제한 안이고(최장 373.6 s), M28 새 시험은 나머지 그룹에 넣는다. 여유는 이번 측정 기준 약 106 s다.

## (k) 역추적 감사 어댑터 조사 (명세 §7, T5 어댑터 표)

조사: 읽기 전용 서브에이전트가 보고서 모듈 19개·`app.py` 라우트를 읽었고, 다시 열기 분기(`_saved_any_report`)·목록 라우트·`/objects` 페이지 상한·점검 보고서/interface_sasa/OpenMM 다시 열기 동작은 직접 확인했다. 행 번호는 HEAD `287a37a8` 기준. **어댑터를 만들 수 없는 종류는 없다.**

**계열과 종류.** 점검 보고서 1종(`POST /runs/{rid}/reports` → `reports.build_inspection_report`, `report_manifest@1`, `render_version: inspection_markdown@1`, `analysis_type` 없음, 이벤트 `report_created`{`report_handle`,`markdown_handle`,`interaction_handle`,`snapshot_event_seq`}) + 방법 보고서 19종(`POST /runs/{rid}/method_reports` {`result_handle`, `filters`(리간드 후보만)} → 결과 kind로 분기, `method_report_manifest@1`, 이벤트 `method_report_created`{`report_handle`,`markdown_handle`,`result_handle`,`snapshot_event_seq`(+M13 실행이면 `execution_link`)}). 권위 있는 종류 목록은 다시 열기 분기 `app.py` `_saved_any_report`(1376–1427, 모르는 값이면 `unknown_method_report_type`)이다. `analysis_type` 19값: `interface_sasa`, `openmm_protein_minimize`, `atom_distance`, `rigid_alignment`, `chemical_interactions`, `pocket_detection`, `residue_numbering`, `reference_site_annotation`, `ligand_candidates`, `ligand_docking`, `ligand_docking_batch`, `ligand_ga`, `sequence_ga`, `mutation_candidates`, `mutation_model`, `jev_choice`, `jev_loop`, `reaction_knowledge`, `kinase_precedents`(`comparison_reports` 한 모듈이 `atom_distance`·`rigid_alignment` 둘을 만든다).

**공통 주장 필드.** 모든 종류의 주장에 `source_handle`, `source_kind`, `source_schema`, `source_sha256`(handle 끝 64hex), `field_path`(비어 있지 않음), `unit`(비어 있지 않음; null 단위 주장 없음)이 있다. `quantity`는 comparison 2종에만 없다.

**어댑터 표.**

| # | 종류 (render_version) | 주장 만드는 곳 / 다시 열기 | 주장 모양 | 근거 kind | 면제(단일 행·필드가 아닌 주장) | 참조값 인용 | 보고서 자체 출처·세트 ID | 섞임 구분 |
|---|---|---|---|---|---|---|---|---|
| 1 | 점검 (`inspection_markdown@1`) | `reports.py` 237·357–381 / `saved_report` 489 | `statement_id`(7), 행 주장 `contact_distance`만 `row_index`+`row_fingerprint`, `operation`, `contact_type` | `interaction_set`, `preparation_manifest` | `contact_count`·`contacting_residue_count`·`minimum_distance`(행 0이면 null "undefined")·`type_count`(모두 `operation`) | 아니오 | 해당 없음 | 모두 계산값 |
| 2 | interface_sasa (`interface_sasa_markdown@1`) | `method_reports.py` 208·272–274 / 346 | `statement_id`·`operation` 없음; `summary.X`(row_index null), `residues[i].X`(`row_index`+`row_fingerprint`), 단위 `A2` | `interface_sasa` | 없음 | 아니오 | 해당 없음 | 계산값 |
| 3 | openmm_protein_minimize (`openmm_markdown@1`) | `openmm_reports.py` 117·213 / 227 | 최상위 필드 3개, `kJ/mol` | `openmm_minimization` | 없음 | 아니오 | 해당 없음 | 계산값 |
| 4–5 | atom_distance / rigid_alignment (`comparison_markdown@1`) | `comparison_reports.py` 223–252 / 320 | `quantity`·`statement_id` 없음; 원소별 `…[i][j]`, `pairs[i].x` | `atom_distance` / `rigid_alignment` | **quantity 면제**: `field_path` 마지막 이름을 수량 이름으로 | 아니오 | 해당 없음 | 계산값 |
| 6 | chemical_interactions (`chemical_markdown@1`) | `chemical_reports.py` 17–34 / 247 | `field_path` `total` 또는 `rows.{i}.{distance_A|DHA_angle_deg}`, `row_id` | `chemical_interaction_set` | 없음 | 아니오 | 해당 없음 | 계산값 |
| 7 | pocket_detection (`pocket_markdown@2`, @1도 받음) | `pocket_reports.py` 89·98–138 / 320 | `statement_id`(7), `row_selector {"rank"}`/null, `operation` | `pocket_set`, `pocket_detector_input` | `pocket_count`(count), `lining_residue_count`(count_distinct) | 아니오 | 해당 없음 | 계산값 |
| 8 | residue_numbering (`…@1`) | `numbering_reports.py` 298·327–388 / 623 | `nr.CLAIM_KEYS`(87–89): `evidence_kind`, `row_selector`, `operation`, `reference` | `residue_numbering_map` | `status_count`, `chain_residue_mismatch[_kind]_count`, `chain_ambiguous_residue_count` | **예** | **있음**: manifest `snapshot_set`·`reference_set_handle`·`klifs_terms`, Markdown "Reference snapshot set"·`## 참조 스냅샷`(493–502) | `evidence_kind`+`reference`(계산 경로 정규식 81–86) |
| 9 | reference_site_annotation (`…@1`) | `site_annotation_reports.py` 358·374–437 / 663 | 8과 같은 키; selector `{status}`·`{absent_reason}`·`{chain_auth,klifs_item}`·`{row_index,row_sha256}`·`{residue,type,row_indexes}` | `reference_site_annotation`, `interaction_set`, `residue_numbering_map` | `site_status_count`, `site_absent_reason_count`, `site_contact_count` | **예** | **있음**(561–575, 스냅숏 `active_set_hash`·`stale_snapshot`) | 77–80 |
| 10 | ligand_candidates (`…@1`) | `ligand_reports.py` 152·172–239 / 471 | `evidence_kind` 늘 computed, `reference` 키 없음(80–82) | `ligand_candidate_set` | `candidates[*]…` `count_where` 4종 | 아니오 | 해당 없음 | computed만 |
| 11 | ligand_docking (`…@1`) | `docking_reports.py` 162·192–285 / 513 | 10과 같은 키; selector `{mode}`/`{mode,kind}` | `docking_result` | `score_minimum/maximum`(`modes[*].score_kcal_mol`), `contact_count`·`contact_kind_count` | 아니오 | 해당 없음 | computed만 |
| 12 | ligand_docking_batch (`…@1`) | `docking_batch_reports.py` 99·125–194 / 423 | 10과 같은 키; `row_score`·`row_result_score` 짝(`{row_index}`), 매칭 키에 `source_handle` 포함(197) | `docking_batch_result`, 행마다 `docking_result` | `row_count`·상태별 count | 아니오 | 해당 없음 | computed만 |
| 13 | ligand_ga (`…@1`) | `ligand_ga_reports.py` 113·147–239 / 484 | selector `{generation,where}`·`{generation}`·`{generation,position}` | `ligand_ga_result`, `docking_result` | `run_count` 셋, `generation_count` | 아니오 | 해당 없음 | computed만 |
| 14 | sequence_ga (`…@1`) | `sequence_ga_reports.py` 140·174–271 / 580 | 13 + 기준 행 `reference_score`·`reference_result_score`(selector null) | `sequence_ga_result`, `docking_result` | 13과 같음 | 아니오 | 해당 없음 | computed만 |
| 15 | mutation_candidates (`…@1`) | `mutation_reports.py` 303·324–420 / 694 | `nr.CLAIM_KEYS`; 참조 주장 `reference={note, reference_object}` | `mutation_candidate_set` | `positions[*]`·`candidates[*]` count/count_where 7종, `catalytic_covered_chain_count` | **예** | **없음**(→ T3, @2 키를 어댑터에 반영) | `STATEMENTS` 111–131, `REFERENCE_FIELDS` 132 |
| 16 | mutation_model (`…@1`) | `mutation_model_reports.py` 139·148–205 / 411 | `nr.CLAIM_KEYS`, `reference` 늘 None; selector `{structure[,stage]}` | `mutation_model` | `contact_count`, `contact_residue_count`, `disulfide_pair_count`, `protonation_difference_count`, `added_heavy_atom_count` | 아니오 | 해당 없음 | computed만 |
| 17 | jev_choice (`…@1`) | `jev_reports.py` 189·200–216 / 371 | `row_selector` 늘 None; `evidence_kind` computed 또는 `model_response`(`reference={note, proposal_handle}`) | `jev_choice` | `selection_count` | 아니오(모델 응답은 참조값과 별개) | 해당 없음 | 70–71 |
| 18 | jev_loop (`…@1`) | `jev_loop_reports.py` 218·230–285 / 502 | 17과 같음; selector `{candidate}`·`{iteration}` | `jev_loop_result`, `docking_result`, `jev_loop_choice` | `pool_size` | 아니오 | 해당 없음 | 93–95 |
| 19 | reaction_knowledge (`…@1`) | `reaction_knowledge_reports.py` 274–454 / 848 | `mr.CLAIM_KEYS`; `reference={note, set_hash, sources[source,date,license]}`(256–259); selector에 `row_index`·`row_sha256` | `reaction_knowledge` | `chains[*]…` count/count_where/count_distinct, `unlisted_line_count` | **예** | **있음**(manifest `snapshot_set`, Markdown 601–613) | 145–148 |
| 20 | kinase_precedents (`…@1`) | `kinase_precedents_reports.py` 307–456 / 805 | 자체 `CLAIM_KEYS`(nr과 같음); `reference={note:"kbase 가공본 값, 계산 아님", set_hash, kb_version, imported_at, source}`(250–254); selector `{accession, record_index, move_id, record_sha256}` | `kinase_precedents` | `chains[*]`·`targets[*]` count/count_where/sum, `unlisted_record_count`, `record_pass_check_count` | **예** | **있음**(manifest `precedent_set`, Markdown 617–643) | 132–135 |

**근거 존재 확인 경로(모든 종류 공통).** `GET /runs/{rid}/objects/meta?handle=` → 200이면 `{handle, kind, schema, fmt, size, produced_by, summary, null_result}`; handle `obj://<run_id>/<kind>/<64hex>`는 저장소가 run_id까지 대조해 다른 run·없는 handle은 404 `not_found`. 감사 대조: `meta.kind == source_kind`, `meta.schema == source_schema`, handle 끝 해시 == `source_sha256`. 내용 읽기 `GET /runs/{rid}/objects?handle=&columns=&offset=&limit=`(`app.py` 1587–1607, `limit` 1–100 기본 50, 직접 확인)는 행 표 객체(리스트, `interaction_set.rows`, `residue_numbering_map`)만 읽고 dict 결과는 422 `input_invalid` — 감사는 재계산을 하지 않으므로 meta만 쓰면 된다. 보고서 하나 `GET /runs/{rid}/reports/selected?handle=`(1430–1435) → `{handle, markdown_handle, manifest, markdown}` 또는 422 `report_evidence_invalid`. JSON 내려받기 `/reports/download?handle=&format=json`(1438–1454) = `canonical_json(manifest)`(저장소 handle 해시는 `object_sha(kind, schema, raw)`라 바이트 sha256과 다르다). 이벤트 `GET /runs/{rid}/events?after=&limit≤500`(1457). 목록 `GET /runs/{rid}/reports`(1347–1373, 직접 확인)는 이벤트마다 `_saved_any_report`로 전체 다시 열기를 해 **하나만 깨져도 전체 422**다(명세 X1 서술과 같음).

**면제 규칙.** `operation` 키가 있는 종류에서 집계 주장은 늘 `operation`이 null이 아니다(count / count_where / count_distinct / count_kind / minimum / maximum / sum)이고 경로는 `[*]` 또는 색인 없는 모음(`rows.status`, `groups.sites.status`, `modes[i].contacts`, `counts.{state}`)이다 → "operation이 있으면 단일 행 선택자를 요구하지 않음". 단 `operation`이 있어도 한 행을 가리키는 주장(M20 `ligand_min_distance_A`, M16 `site_min_distance_A`)은 selector가 있으므로 면제가 아니다. `operation` 키가 없는 4종(interface_sasa, openmm, comparison, chemical)은 집계 주장이 없다. comparison 2종은 quantity 면제. 명시적 무단위 표지(`unit` 문자열): `count`, `dimensionless`, `identifier`, `flag`, `status`, `text`, `handle`, `sha256`, `residue_field`, `model_number`, `seed`, `index`, `one_letter`, `residue_name`, `position`, `0-1`, `bytes`, `tokens`, `usd`, `percent`, `fraction`, `iterations`, `uniprot_sequence_position`, `klifs_pocket_index`, `residue_identity`, `sdf_atom_serial`, `mcsa_residue_number`, `paper_page` 등(T5가 모듈 상수에서 확정).

**참조값 인용 종류(명세 §7 3번 대상).** 다섯: residue_numbering, reference_site_annotation, mutation_candidates, reaction_knowledge, kinase_precedents. 보고서 자체에 출처·세트 식별자가 **없는 것은 mutation_candidates 하나**(알려진 대로). 섞임 검사 규칙: `evidence_kind == "computed"`이면 `reference`가 None, `reference_value`이면 `reference.note`가 그 종류의 문구(M15·M16·M20·M26 "참조 스냅샷 값, 계산 아님", M27 "kbase 가공본 값, 계산 아님"). 계산/참조 경로를 가르는 정규식은 각 모듈의 `COMPUTED_FIELDS`·`REFERENCE_FIELDS` 상수(내보내기 스크립트로 꺼낼 수 있음).

**고정 문장 상수(하위 프로세스 `m28_export_fixed_sentences.py`가 내보낼 것).** M12 `pocket_reports.EVIDENCE_STATEMENT`·`DRUGGABILITY_WARNING`·`DISPLAY_CENTER_NOTE`(31–37), `pocket_output.LIMITATIONS`(112); M15 `numbering_reports.REFERENCE_NOTE`·`KLIFS_TERMS`·`REFERENCE_STATEMENT`·`LEGACY_REPORT_LIMITATIONS`·`SNAPSHOT_SCOPE`(45–59); M16 `site_annotation.LIMITATIONS`(4, 39); M17 `ligand_constants.LIMITATIONS`(5, 65); M18 `docking_constants.LIMITATIONS`(12, 85)·`SCORE_LABEL`(81)·`SCORE_COLUMN_LABEL`(82); M19 `docking_batch_constants.BATCH_STATEMENTS` B1–B3(53); M20 `mutation_constants.LIMITATIONS`(114)·`LIMITATIONS_V2`·`LIMITATION_3_CHECKED`·`LIMITATION_3_NOT_CHECKED`(122–130); M21 `mutation_model_constants` L1–L7·`LIMITATION_ORDER`(87–95); M22 `ligand_ga_constants.STATEMENTS` G1–G3(95); M23 `sequence_ga_constants.STATEMENTS` S1–S6(174)·`SCORE_LABEL`(159); M24 `jev_constants.STATEMENTS` J1–J7(205)·`J6_BY_CATALYTIC_STATUS`(214)·`SCREEN_NOTES` U1–U3(219); M25 `jev_loop_constants.STATEMENTS` LJ1–LJ8(234)·`SCREEN_NOTES` UL1–UL3(240); M26 `reaction_knowledge_constants.STATEMENTS` RK1–RK6(126)·`LIMITATIONS`(136)·`SCREEN_NOTES` UK1–UK4(137); M27 `precedent_constants.STATEMENTS` KP1–KP6·KT1(170)·`LIMITATIONS`(183)·`SCREEN_NOTES` UP1–UP5(184). (`docking_constants`·`docking_batch_constants`·`ligand_ga_constants`·`sequence_ga_constants`·`mutation_model_constants`는 해시 파일이므로 내보내기 스크립트는 import로 읽기만 한다.)

**제품의 금지어 검사 방식.** `check_no_interpretation`이 렌더 함수 안에서 만들 때와 다시 열 때 모두 불린다. 슬롯을 비운 템플릿 줄 검사(`_SLOT.sub("", template)`) 7종: sequence_ga 545, mutation 624, mutation_model 377, jev 339, jev_loop 471, reaction 571, kinase 574. 채워진 본문 줄 검사(고정 문장과 같은 줄은 건너뜀, M18 계열은 `SCORE_LABEL`을 먼저 지움) 6종: numbering 589, site 629, ligand 436, docking 479, batch 389, ligand_ga 450. **검사 없음 6종**: 점검, interface_sasa, openmm, comparison, chemical, pocket. X4 영향: 옛 6종의 부정문 한계 문장(X4 핵심 금지어를 "…이 아니다"라는 부정문으로 담음)은 상수가 아닌 인라인 리터럴이다(`reports.py` 421, `method_reports.py` 288과 `tools/sasa.py` 245, `openmm_reports.py` 179–180, `tools/comparison.py` 205·284, `chemical_bundle.py` 748·944, `pocket_reports.py` 31). 일부는 `_md` 이스케이프나 "- " 접두로 렌더된다(`reports.py` 485, `method_reports.py` 341, numbering 585, pocket 280, chemical 191). → 내보내기 스크립트가 렌더된 형태로 내보내거나 X4 줄 단위 예외 목록이 이유와 함께 맡아야 한다.

**명세와 다른 점·위험(조율 세션 판단 필요, 멈춤 조건은 아님).**
1. **§7 1번 전제가 두 종류에서 성립하지 않는다(직접 확인).** 점검 보고서의 `saved_report`(`reports.py` 489–505)는 종류·상태·Markdown 연결·생성 이벤트만 보고 **주장 재검증도 Markdown 재생성도 하지 않는다.** interface_sasa의 `saved_method_report`(`method_reports.py` 346–383)는 주장·데이터는 다시 만들어 비교하지만 **Markdown 재생성·스냅숏 검사는 하지 않는다**(Markdown은 저장 바이트를 그대로 돌려줌). 저장소 handle 해시가 바이트 불변은 보장한다. A2(기하 접촉 → 점검 보고서)·A3(SASA → interface_sasa 보고서)이 이 두 종류를 만든다. 선택지: (i) 범위 표에 "이 두 종류는 제품 다시 열기가 주장/Markdown 재생성을 하지 않음"을 적는다, (ii) 감사(또는 A2·A3 사례)가 독립 기대값으로 보완한다. 제품 코드는 고치지 않는다(R3).
2. **OpenMM 보고서 다시 열기는 현재 run 외부 전송 모드에 좌우된다(직접 확인).** `openmm_reports.py` 260이 `snapshot.run_egress_mode == run.egress_config["mode"]`를 요구하고 이 모드는 `viewer_consent_changed`로 바뀐다(`runtime/orchestrator.py` 351–355). 같은 run에서 OpenMM 보고서를 만든 뒤 뷰어 동의를 바꾸면 그 보고서와 목록 전체가 422가 된다. M24/M25 과학 전송 동의는 이 모드를 바꾸지 않으므로 C 분기 하네스가 **뷰어 동의를 건드리지 않으면** 문제없다(C2가 M7 최소화 보고서를 만들 경우).
3. **X1의 개수 비교는 그 자체로 항등이다.** 목록은 두 이벤트마다 한 줄을 돌려주므로 200이면 "목록 개수 = 두 이벤트 수의 합"이 늘 참이다. 의미 있는 대조가 되려면 사례 코드가 직접 센 생성 수(보고서 POST 성공 수)와도 맞춰야 한다(T5/T9 판정 설계에 반영).
4. M20은 §7 3번에서 지금 실패한다(예상대로, T3 뒤 통과 대상). 어댑터는 `render_version`으로 @1(출처 없음 → fail)과 @2를 나눈다.

## T2–T9가 알아야 할 결정 사항과 조율 세션에 올릴 질문

**조율 세션이 정해야 할 것(멈춤 조건은 아니지만 해당 작업 전에 필요).**
1. **실행 순서(T7·T8·T9, (e) 5절·(d) 막힘 2)**: 분기 B는 B1, B2, B3(+재제출), B6, B7(탐색형 → 활용형), B4, B5(설정 1 → 2), B8; 분기 C는 C1, C2, C3, C5, C6(탐색형 → 활용형), C4(설정 1 → 2), C7. live B는 L-pre-B4의 새 행을 3(+부모)으로 묶어 L-B7 1단위를 남긴다. 명세 표 순서 그대로면 B7·C6이 실패한다.
2. **M20 보고서 @2를 언제 쓰는가(T3, (g) ★A)**: "참조값(번호 대응·주석·반응 지식)을 인용하는 새 보고서만 @2, 인용 없는 새 보고서는 지금 @1 바이트 그대로" 권고(수정 금지 기준선 비교 시험 때문에 "새 보고서 전부 @2"는 불가). 함께: 반응 세트 표의 싣는 조건(M-CSA ID 주장이 있을 때 vs `catalytic_annotation` handle이 있을 때), M26 표의 "가공 행 수" 열(manifest 사본 + 다시 열 때 대조 vs 열 제외), 활성 세트 줄(`app.py`를 고치지 않으려면 제외).
3. **B2 입력 조합(T7, (d) 막힘 1)**: 기존 합성 표시 파일 조합(SMILES `ligand_ga/synthetic-ga-small-blocks.smi` + SDF `ligand/synthetic-blocks.sdf` + 규칙 `ligand_ga/synthetic-ga-pool2000-rules.json`의 `user_2`·`user_3`)을 쓸지, 새 합성 표시 목록을 만들지(R1 범위 판단).
4. **A1 "기본 정책"(T6)**: 화면 기본값(`strip_all`; 기대 잔기 313·원자 2,526)으로 볼지 도구 명세 기본값(`keep_all`; 333·2,546)으로 볼지.
5. **§7 1번 전제의 예외 두 종류(T5, (k) 위험 1)**: 점검 보고서(주장·Markdown 재생성 없음)와 interface_sasa(Markdown 재생성 없음)를 범위 표에 적을지, 감사·사례가 독립 기대값으로 보완할지.

**작업별 입력(이 문서의 확정 값).**
- T2: 네 시험 모두 시험 쪽 원인, 제품 변경 불필요((f) 표의 "결정적으로 묶을 지점"). 통과 기준의 동시 부하는 `CHECKS[1:]` 18그룹 동시 실행(이번 측정 373.6 s 벽시계)으로 재현한다.
- T3: `mutation_reports.py` 한 파일 + 시험·fixture. 코드 변경 전에 인용 있는 @1 보고서 이벤트 로그 fixture를 지금 코드로 기록(1MQ4 번호 대응 + 주석, 합성 촉매 집합). ★B 순환 import, ★C 반응 결과 검증 1회, ★D 소스 문자열 시험, ★E `check_sources` 시그니처를 지킨다. 해시 파일·골든 영향 없음((g) 4).
- T5: 어댑터 표 = (k) 표(20종). 존재 확인은 `GET /runs/{rid}/objects/meta`(kind·schema·handle 해시 대조), 면제 = "operation이 있는 집계 주장" + comparison quantity 면제, 섞임 = `evidence_kind`/`reference` 규칙, 참조값 인용 다섯 종류 중 M20 @1은 출처 없음 → fail, @2 키는 T3 결과를 따른다. 고정 문장 내보내기 목록 = (k) "고정 문장 상수", 옛 6종 인라인 한계 문장은 렌더된 형태로 내보내거나 X4 예외 목록으로. X1은 이벤트 수 비교가 항등이므로 사례 코드의 생성 수와도 대조. X6은 `.deps/reaction_reference`도 확인.
- T6: A2 리간드 7필드 `{"model_number":1,"chain_auth":"A","chain_label":"B","seq_auth":999,"seq_label":null,"icode":"","resname":"AQ4"}`, A5 체인 1M17 A(전처리 구조)·1FIN A·C·1MQ4 A, A6은 annotation M10 재사용 + 1M17 oracle + PNG ≤ 8 MiB, A7 세트는 `--dest <격리>`로 설치((b)에서 시험한 명령), A8 세트는 import2의 격리 복사.
- T7: 도킹 값 공통 = 중심 (3.41, 0.72, 11.31)·12 Å·seed 1·exh 1·모드 2·energy_range 3(B3·B4·B5·B7 재사용 조건), B5 설정 둘((e) 4), B3 재제출 단계 새로 작성, 증액 클릭 3번.
- T8: C1 = 1A30(직접 잔기, 반응 결과 체인 A만 / A+B로 `checked` 거짓·참), C2–C6 = 1UBQ tiny 집합(K6·I44·G76 × A·W), C4 설정 둘((e) 4), C2의 M7 OpenMM 보고서가 있으면 뷰어 동의를 바꾸지 않는다((k) 위험 2), 증액 클릭 2번, 단위 여유 0이므로 계산 전 남은 단위 단언.
- T9: fixture 서버 정상 응답 스크립트만, 18그룹 시간 재측정((j)).

## 이 착수 확인이 만든 파일

- 커밋: `docs/qa/m28-final-20261011/preflight.md`(이 문서), `m7_probe.py`(측정 시제품, `mw` 제품 함수를 부르기만 함), `m7-probe.txt`(16행 표), `network-ledger.txt`(머리말).
- Git 제외 `<P>` = `runs/m28-preflight-20261011/`(지우지 않음): `golden-science.txt`·`golden-egress.txt`·`golden-keys.txt`·`golden_call_keys.rerecord.json`·`golden-keys-runs/`, `precedent-1/`·`precedent-2/`(격리 설치 세트)·`precedent-import-{1,2}.txt`, `m7-probe-runs/`·`m7-probe.raw.txt`·`m7-probe.err.txt`, `a1-probe/`(1M17 전처리 요약 확인), `stop-groups-run1/`(그룹 로그 18개·`summary.json`)·`stop-groups-run1.out`.
- 세션 스크래치패드(저장소 밖, 커밋 안 함): `nosock_run.py`(소켓 차단 래퍼), `run_groups.py`(18그룹 동시 실행), `cmdline_race.py`(psutil 경쟁 미세 시험).
- 256 KiB 넘는 텍스트 증거는 만들지 않았다(이 문서가 가장 크다). 제품 코드·시험·하네스·`.codex`·`config`·문서(이 폴더 밖)는 바꾸지 않았다. 측정 뒤에도 `.deps/precedent_reference`·`.deps/reaction_reference`는 없고 8000/3000 리스너는 없다(아래 마지막 확인).

**마지막 확인(문서 작성 뒤).** `ls -d .deps/precedent_reference .deps/reaction_reference` → 둘 다 없음, `lsof -iTCP:8000/3000 -sTCP:LISTEN` → 둘 다 exit 1, `git status --porcelain` → `?? docs/qa/m28-final-20261011/`뿐, 이 폴더의 유출 검사(사용자 절대 경로·키 모양 문자열·판정 금지 정규식 `완성\(범위 명시\)`/`M28[ ]*(완료|완성)`·X4 핵심 금지어) 0건, `ruff check docs/qa/m28-final-20261011/m7_probe.py` 통과.
