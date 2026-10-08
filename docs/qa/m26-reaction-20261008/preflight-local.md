# M26 T1-B 착수 확인 — 로컬 영향 측정과 골든 기록기 사전 변경 (2026-10-08)

T1의 (d)–(m)을 로컬에서만 측정한 기록이다(실서버 요청 0건, `.env` 읽지 않음). (a)–(c)는 `preflight-network.md`(T1-A)에 있다. 기준은 작업 브랜치 `dryforge/m26-reaction-knowledge`의 `72f4d1e`이고, 저장소 파일 변경은 (i)의 골든 기록기 둘과 새 fixture·기준선뿐이다(커밋 `5672200`). 제품 코드(`backend/mw`·`config`·`frontend`·`scripts`)는 바꾸지 않았다(`git diff 72f4d1e -- backend/mw config frontend scripts` 0줄). 시제품·실험 스크립트는 저장소 밖 scratchpad(`…/scratchpad/m26_t1/`, 아래 `<S>`)에 두었고 결과만 여기 옮겼다. Python은 모두 `.venv/bin/python`이다.

## (d) M20 변경 영향

**읽는 곳·검증하는 곳(서버).** `mutation_candidate_set@1`을 `mutation_candidates.validated_set`으로 검증하는 곳은 여덟 곳이다: `tools/mutations.py:115`(저장 전), `mutation_reads.py:39`(읽기 라우트 넷, `api/app.py:1906–1959`), `mutation_reports.py:217`(보고서 만들기·다시 열기), `tools/jev.py:83`(M24 투영 입장), `jev_sends.py:506`(M24 제안 소스), `jev_loop_store.py:286`(M25 루프 풀), `mutation_model_inputs.py:96`(M21 입장 `validated_candidate_set`; M23 `sequence_ga_inputs.py:207`·`sequence_ga_jobs.py:313`도 이것을 부름), `mutation_model_bundle.py:411`(M21 결과 읽기 `_check_relations`). 함수만 가져다 쓰는 곳: `mutation_model_math.py:28`(`identity`·`seven`·`standard_name`, **해시 파일**), `mutation_model_reports.py`, `sequence_model_bundle.py`, `sequence_ga_jobs.py`, `jobs/openmm_mutation_worker.py`·`jobs/sequence_model_worker.py`(`identity`·`seven`). 그래서 T6은 `identity`·`seven`·`standard_name`의 동작을 바꾸면 안 된다(M21 계산이 바뀜).

**fixture.** 저장된 v1 집합은 `fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json`·`…-tiny.json`(M23, `sequence_ga_fixture.py`·`test_sequence_ga_worker.py`·`test_sequence_model_worker.py`·`test_jev_loop_projection.py`·`test_jev_loop_choice.py`가 읽음)과 이번 `fixtures/reaction/t1/` 셋, 도구 출처가 있는 v1 run 로그 하나다. 그 밖의 테스트 도우미(`sequence_ga_fixture.py`, `mutation_model_fixture.py`, `jev_send_fixture.py` 등)는 도구를 불러 새 집합을 만들므로 T6 뒤에는 v2(`not_checked`)를 받는다. `fixtures/sequence_ga/build_sequence_ga_fixtures.py --check`는 v2 뒤 설계상 실패한다(도구가 v2를 만든다) — **`--write`로 다시 쓰면 M23 테스트가 쓰는 v1 fixture를 덮어쓰므로 하지 않는다.**

**화면 목록.** 후보 집합을 고르는 곳: `MutationPanel.tsx`(M20 목록), `MutationModelPanel.tsx`(M21), `SequenceGaPanel.tsx`(M23), `JevPanel.tsx`(M24 변이 소스), `JevLoopPanel.tsx`(M25 변이 풀). 순수 로직 `lib/mutations.ts`(44·103·583–585행이 `catalytic_residue_database`를 표시), `lib/jev.ts`(J1–J7 사본 51–60행), `lib/contracts.ts:719`(`catalytic_residue_database: {status: "not_available"; reason: "not_implemented"}` 리터럴 — T7이 넓혀야 함), `lib/sequence-ga.ts`.

**호출 키.** (j) 참조: M20 파일 중 해시 집합에 드는 것은 `mutation_candidates.py` 하나다.

**업그레이드 전 큐 작업.** 큐의 시작 때 고정 확인은 예약보다 앞이다: M23 `queue.py:1361–1368`, M21 `queue.py:1369–1376`이 `worker_version_invalid`(412)로 막고 `reserve_attempt`는 `queue.py:1435`. 실측(`<S>/m21_queued_start.py`): 1UBQ I44W M21 작업을 지금 핀으로 제출한 뒤 `mutation_model_bundle.DEPENDENCIES["mw/mutation_candidates.py"]`를 한 줄 덧붙인 사본으로 바꾸고(기존 R1 테스트와 같은 대역 방식) 시작하면:

    submitted queued 89a4e7fb31a799b1
    resubmitted after change: new job True new call key True
    start refused: precondition {'reason_code': 'worker_version_invalid'}
    budget_reserved events: 0 job_dispatch_intent: 0 expensive used: 0
    job status now: claimed

→ 과금 전 거절이다. 단 작업은 `failed`가 아니라 `claimed`로 남으므로 사용자는 그 작업을 취소하고 다시 제출한다(새 호출 키 = 새 작업). M23도 같은 순서(`test_sequence_ga_jobs.py::test_admission_order_refusals_record_and_charge_nothing` 351–361행이 바뀐 모듈의 시작 거절·예약 0을 확인).

**M25 루프·J6.** (k)·(l) 참조.

결론: 명세 9절의 영향 범위(M21·M23 재사용 종료, 큐 작업 과금 전 실패 후 재제출, 진행 중 단백질 루프 막힘)와 같다. 멈출 조건 없음.

## (e) 도구 비용 (합성 자료만)

`<S>/cost_prototype.py`(표준 라이브러리만, mw import 없음, 네트워크 없음): 명세 3.3 필드 이름의 합성 JSONL 세 파일을 쓰고 ① 고정(포인터·매니페스트 읽기 + 파일마다 `O_NOFOLLOW` 읽기·SHA-256) ② JSONL 해석 ③ 색인(PDB 소문자 → `(mcsa_id, residue_index, chain 행)`, accession → UniProt 행, Rhea ID → 행) ④ 결과 하나(체인 하나 조회·묶기·300잔기 합성 체인과 대응·정규 JSON)를 세 번씩 재서 가장 빠른 값을 적었다.

| 시나리오 | 항목 / 잔기·항목 / 체인·잔기 / accession / 부위·accession / Rhea | 파일 MB (mcsa·uniprot·rhea) | 고정 | 해석 | 색인 | 결과 | 캐시 없이 호출당 |
|---|---|---|---|---|---|---|---|
| typical | 1003 / 6 / 2 / 2,000 / 25 / 18,000 | 5.1 · 7.1 · 6.2 | 0.010 s | 0.156 s | 0.005 s | <0.001 s | 0.171 s |
| heavy | 1003 / 12 / 8 / 3,500 / 60 / 18,000 | 19.6 · 27.2 · 6.2 | 0.071 s | 0.478 s | 0.065 s | <0.001 s | 0.614 s |
| heavier | 1003 / 20 / 16 / 5,000 / 100 / 20,000 | 54.3 · 63.0 · 6.9 | 0.338 s | 1.058 s | 0.282 s | <0.001 s | 1.678 s |

해석 직후 최대 RSS: typical 157 MB, heavy 317 MB, heavier 648 MB. 체인 하나 결과의 정규 JSON 9–68 KB(1 MiB 상한보다 작음). 실제 M-CSA는 T1-A 측정으로 잔기 5,248개(항목당 약 5.2), 잔기당 `residue_chains` 0 또는 1개라 typical보다 가볍다(UniProt·Rhea 실제 크기는 T1-A 값을 쓴다).

결론: 호출마다 해석·색인을 다시 하면 0.17–1.7 s가 드는데 그 대부분이 JSONL 해석이다. **고정 세트 단위 캐시가 필요하다**: M15 `residue_numbering.reference_index`(`_INDEXES`, 세트 해시 키, 성공만 저장, 개수 상한)와 같이 `set_hash`(+ `reaction_snapshots`가 이미 확인한 파일 stat 정체) 키로 해석·색인 결과를 성공한 것만 두고, 메모리 때문에 세트 하나(최근 것)만 둔다. 캐시가 있으면 도구·`GET /reaction_reference/pdb/{id}`·status 읽기는 ms 이하다.

## (f) 카디널리티 결합 지도 (grep으로 확정한 실제 위치)

- **도구 집합**: `backend/mw/api/app.py:132–135` `SUPPORTED_TOOLS`; `config/tools.yaml`(새 도구 명세, `generate_mutation_candidates` 202–218행 `params`); `backend/mw/workspace.py:23–34` `build_registry`. 하드코딩 테스트: `backend/tests/test_api.py:279–285`(`/tools` L1–L5 이름 집합), `test_reference_site_annotation.py:692–696`·`test_residue_numbering.py:747–752`(사전 검사 훅 도구 집합 — 새 도구는 훅이 있으므로 둘 다 고침), `test_mutation_tool.py:133–146`(M20 등록 네 곳과 `set(spec["params"]) == set(K.ARG_KEYS) - {"structure"}` — T6이 `catalytic_annotation`을 yaml과 `ARG_KEYS`에 같이 넣어야 통과), `test_jev_api.py:486`(집합에서 빼는 패치, 고칠 필요 없음). 프런트 `frontend/src/lib/api.ts:261`(command 도구 이름 유니언).
- **capability 방법 집합**: `app.py:660–688`(`methods[...]`; `analysis_workflows`가 667행 `residue_numbering`보다 먼저 계산되므로 뒤에 더한 방법은 M13 템플릿에 영향 없음 — `test_numbering_api.py:80–95`가 그것을 확인). 하드코딩: `test_ligand_api.py:23`(`PRIOR_METHODS`)·`420`·`~457`(두 단언). 모양 기준은 `test_numbering_api.py:80–100`.
- **보고서 종류 집합**: `app.py:1309–1311`(`create_method_report` 분기), `1346–1349`(`list_reports`의 bounded-load 분석 종류 집합), `1363–1367`(`_saved_any_report`의 같은 집합)과 `1369–1402`(다시 열기 분기). 프런트 `frontend/src/lib/report-library.ts:94–98`(`reportKindLabel`), `frontend/tests/report-library.test.cjs:51`, `frontend/src/lib/contracts.ts:~1192`(manifest 유니언).
- **입장 이유 튜플·import 제한**: `backend/mw/mutation_constants.py:28–33` `ADMISSION_REASON_CODES`; 단언 `backend/tests/test_mutation_candidates.py:141–145`(튜플), `157–172`(두 M20 파일의 import 허용 집합 `{"__future__", "math", "typing", "numpy", "mutation_constants", "tools.structural"}`, `mutation_constants.py`는 `__future__`만), `135–155`(닫힌 집합·한계 문장·`PROTECTION_CHECK_KEYS`).
- **고정 문장**: `backend/mw/jev_reports.py:48` `FIXED_LIMITATIONS = frozenset(J.STATEMENTS.values())`; `backend/tests/test_jev_constants.py:39`(J6 문장)·`210–225`(`STATEMENTS` J1–J7, `limitations_for`); `test_jev_reports.py:175`(`STATEMENTS` 반복); M20 `mutation_reports.py:59` `FIXED_LIMITATIONS = frozenset(LIMITATIONS)`(v2 셋째 문장 변형 둘을 더해야 함). 프런트 `lib/jev.ts:51–60`, `lib/mutations.ts`(M20 한계 문장 사본).
- **v1 값에 묶인 기대**(T6 뒤 도구가 만든 새 집합은 `not_checked`/J6n이 됨): `test_jev_projection.py:557`·`568`·`585`(와이어 `catalytic_residue_database == "not_available"`), `test_mutation_reports.py:193`(촉매 검사 상태 주장), `frontend/tests/offscreen/mutation-flow.cjs:703–712`(`assert.equal(value.catalytic, "not_available")`), `frontend/tests/offscreen/jev-flow.cjs:52`·`129`(J6 고정 기대), `frontend/tests/mutations.test.cjs`, `frontend/tests/jev.test.cjs`, M20·M24 수락 실행기의 fixture 단계(이 하네스를 그대로 돌림).
- **골든**: `backend/tests/fixtures/jev/golden_science_m24.py`·`golden_science_m24.json`, `fixtures/jev/prototype_golden_egress.py`·`golden_egress_events.json`(`test_jev_science_gate.py:682`가 subprocess로 `--check`), `fixtures/sequence_ga/prototype_golden_call_keys.py`·`golden_call_keys.json`(`test_sequence_ga_jobs.py:842–854`가 다시 만들어 같음을 단언, `test_sequence_model_worker.py:50`·`test_sequence_ga_worker.py:1152`는 JSON만 읽음).
- **AST·문자열 검사(고칠 필요 없음, 지키기만)**: 증액 호출자 셋 `test_docking_batch_budget.py:127–143`·`test_ligand_ga_budget.py`·`test_sequence_ga_budget.py`(모든 `backend/mw` 본문에서 `raise_limits`·`limit_approval` 문자열 검색), `test_jev_ast.py`(httpx는 `egress/` 안만, `NEW_MODULES` 21행은 M24 모듈 목록 — M26 모듈을 넣을 필요 없음).
- **Stop 훅**: `.codex/hooks/stop.py:26–36` `SCRIPT_TESTS`(새 `scripts/test_*.py`는 수동 추가 필수 — `scripts/test_codex_hooks.py`가 모든 `scripts/test_*.py`·`backend/tests/test_*.py`가 정확히 한 그룹에 있는지 검사), `62–99` `PYTEST_GROUPS`(열다섯), `100` `REST_GROUP`(새 백엔드 테스트 파일 자동 포함), `103–105` `CHECKS`(17, `scripts/test_codex_hooks.py:145`가 단언), `114` `CHECK_TIMEOUT = 480`. M25 고정 게이트에서 나머지 그룹 398 s였으므로(엔지니어링 노트) 새 M26 테스트는 엔진 없는 순수 테스트라도 그룹 시간을 T11에서 재고, 넘으면 이름 있는 그룹을 새로 만들고 `CHECKS` 기대(17)를 같이 고친다.
- **문서 게이트 목록**: `docs/standards.md:38–57`(스크립트 테스트 목록 40행, `node --check` 하네스 목록 41–54행), `docs/operations.md`의 Stop 훅 문단(T13).
- **탭·하네스 서명**: `frontend/src/components/WorkspaceTabs.tsx:12–14`·`53`(지식 탭 영역 슬롯), `frontend/app/page.tsx`(슬롯 연결), `frontend/tests/workspace-tabs.test.cjs`, `frontend/tests/offscreen/tabs-flow.cjs`, `jev-flow.cjs:331–343`(`tabSignature`가 지식 탭 글자를 비교), `jev-loop-flow.cjs`.

작업별로 바꿀 파일 목록은 맨 끝 "명세와 다른 점" 아래 표에 모았다.

## (g) 원자적 설치·검증 패턴 이식과 M15 kinase 목록 읽기

**서버(`reaction_snapshots.py`)가 `reference_snapshots.py`에서 옮겨 쓸 것(복사해 별도 구현, import하지 않음):** `_read_limited`(`O_RDONLY|O_NOFOLLOW`, `fstat` 일반 파일, 크기 상한, 읽는 중 커짐 거부), 포인터 읽기(키 집합 정확히 `{schema, set_hash}`, 64자 hex), 매니페스트 바이트의 SHA-256 = 포인터 해시 + `canonical_json(manifest) == raw` 확인, 각 파일 경로가 `resolve(strict=True)`로 세트 폴더 안인지, `_stat_identity`(dev·ino·size·mtime_ns·ctime_ns)와 "성공한 검증만, 세트 폴더당 하나" 캐시(`_VERIFIED`·`_LOCK`, 검증 전후 stat 비교), 한 세트 폴더에 묶인 `PinnedSet`(접근자는 그 폴더만), `SnapshotUnavailable(reason_code)`의 `not_installed`(포인터 없음)·`snapshot_invalid`(그 밖 OSError/ValueError), `reference_dir()`의 환경변수·상대 경로(저장소 루트 기준) 규칙. **공유하면 안 되는 것:** 모듈 전역 캐시(`_VERIFIED`·`_LOCK`)와 `ENV_VAR`·`DEFAULT_DIR`·`SOURCES`·`ORIGIN`·`REASONS`(문구가 M15 가져오기 명령을 가리킴)·`_validate_manifest`(스키마 `reference_snapshot_set@1`, `kbase_repo`, `use`/`comparison_only`, 파일 경로 `source/date/name` — M26은 `files/<source>/<name>`과 출처 밖 `files/request_log.jsonl`). M15 모듈은 건드리지 않는다.

**가져오기 명령이 `scripts/import_reference_snapshots.py`에서 옮겨 쓸 것:** `canonical_json`(같은 식, 줄바꿈 없음), `_write_file`(`O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, 끝까지 쓰고 fsync), `_fsync_dir`, 설치 순서(모든 검사 통과 뒤에만 쓰기 → `sets/.staging-<uuid>`에 파일·매니페스트 → 디렉터리 fsync → `os.rename(staging, sets/<hash>)` → `sets` fsync → `.active.json.<uuid>.tmp` 쓰기 → `os.replace` → 상위 fsync, 실패하면 staging·임시 포인터만 지움, 최종 폴더가 이미 있으면 거절), `_rows`. **옮기면 안 되는 것:** `_now()`(M15는 `%Y-%m-%dT%H:%M:%S.%fZ` 마이크로초 — 명세 3.2는 `YYYY-MM-DDTHH:MM:SSZ`), kbase 전용 `read_git_info`·`_load_kbase_manifest`·`_latest`·`_collect`, `--from`·`--dest` CLI(명세는 `--reference-dir`, 기본 `MW_REACTION_REFERENCE_DIR` 또는 `.deps/reaction_reference`; M15 명령은 환경변수를 보지 않는다).

**M15 활성 세트의 kinase accession 목록(읽기만, `backend/mw` import 없이):**

```python
def m15_kinase_accessions(root):           # root = MW_REFERENCE_DIR(상대면 저장소 루트 기준) 또는 <repo>/.deps/reference
    try:
        pointer = json.loads(read_limited(root / "active.json", 4096))
        if set(pointer) != {"schema", "set_hash"} or pointer["schema"] != "reference_active@1":
            raise ValueError("pointer")
        set_dir = root / "sets" / pointer["set_hash"]
        raw = read_limited(set_dir / "manifest.json", 1 << 20)
        if hashlib.sha256(raw).hexdigest() != pointer["set_hash"]:
            raise ValueError("manifest hash")
        [entry] = [f for s in json.loads(raw)["sources"] if s["source"] == "uniprot"
                   for f in s["files"] if f["name"] == "entries.jsonl"]
        data = read_limited(set_dir / "files" / entry["path"], 512 << 20)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("file hash")
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
        return pointer["set_hash"], sorted({r["data"]["accession"] for r in rows if r.get("status") == "ok"})
    except (OSError, ValueError, KeyError, TypeError):
        return None, []                    # m15_kinase_list "absent" (차단하지 않음)
```

실측(로컬 `.deps/reference`, 세트 `aa21ead9930f…3317`): 매니페스트 해시·파일 해시 일치, `uniprot/2026-09-15/entries.jsonl` 542행 = `ok` **541** + `lookup_failed` 1(`O43930`). `ok` 행은 모두 `id == data.accession`이고 541개 모두 명세 4.1 accession 정규식에 맞고 중복 없음. 행 키는 `{data, id, reason, status}`.

## (h) 오프스크린 격리 방식

하네스(`numbering-flow.cjs`·`annotation-flow.cjs`·`mutation-flow.cjs`)는 환경변수를 다루지 않고 수락 실행기가 백엔드를 띄울 때 정한다. `scripts/m15_offscreen_acceptance.py:154`가 `self.reference = <root>/reference`를 두고 `245`행 `start_backend`가 `m13.child_env({"PYTHONPATH": <code>/backend, "MW_RUNS_DIR": <root>/runs, "MW_REFERENCE_DIR": <root>/reference})`로 띄운다. `run()`(485–507행)은 runs·reference 폴더가 비어 있지 않으면 시작을 거절하고(새 `--root` 요구) 8000·3000 포트가 비어야 한다. 순서는 빈 참조 폴더로 `empty` 모드(하네스가 `api.available == false` 확인, numbering-flow.cjs 425행) → 그 폴더에 가져오기(`--dest <root>/reference`) → `main`(하네스가 `--set-hash`와 활성 세트 일치 확인, 466행) → 다시 가져오기 → `stale`("이전 스냅샷 기준")이다. M16–M25 실행기는 모두 `m15.Runner`를 상속한다(M16·M17 직접, M20은 M16, M18은 M17, M19·M21–M25는 M18). 백엔드 env는 `m15.Runner.start_backend`(243–245), `m17.Runner.start_backend_at`(216–218, M18–M23이 씀), M24 `start_backend`(674–675), M25(945–946)가 같은 방식으로 준다. M13(`start_backend` 308–309)·M14(259–260) 실행기는 `MW_REFERENCE_DIR`도 주지 않는다. `m13.child_env`(`m13_offscreen_acceptance.py:107–108, 165–167`)는 허용 목록 `PATH·HOME·USER·LOGNAME·SHELL·LANG·TMPDIR·TERM·TZ·__CF_USER_TEXT_ENCODING`과 `LC_*`만 넘긴다.

새 변수 격리 방법: M26 실행기는 같은 방식으로 `self.reaction_reference = <root>/reaction_reference`(새 폴더, 비어 있지 않으면 거절)를 두고 `child_env`에 `"MW_REACTION_REFERENCE_DIR": str(self.reaction_reference)`를 명시한다. 실서버 요청 없이 `empty` → (실제 가져오기 세트 `sets/<hash>/` + `active.json`을 이 폴더로 복사) → `main` → (두 번째 유효 세트를 복사하고 포인터 교체 — T11 둘째 가져오기 세트나 T2 도우미로 만든 표시된 합성 세트) → `stale` 순서로 M15 선례를 따른다. **주의:** `child_env`가 부모 셸의 `MW_*`를 버리므로, M26 env를 주지 않는 기존 회귀 실행기(M13–M25)의 백엔드는 코드 루트 기본값 `.deps/reaction_reference`를 읽는다(격리 안 됨). 실세트를 기본 위치에 설치하면 회귀 중 지식 탭의 새 영역 글자가 기계마다 달라질 수 있다. T9/T11은 (1) 회귀 동안 `.deps/reaction_reference`를 비워 두거나 (2) 위 env를 만드는 여섯 곳(`m13:308`, `m14:259`, `m15:243`, `m17:216`, `m24:674`, `m25:945`)에 빈 격리 폴더의 `MW_REACTION_REFERENCE_DIR`를 더하는 최소 변경(이유 기록) 중 하나를 고른다. git worktree에는 `.deps`가 없어 기본값이 `not_installed`가 된다.

## (i) v1 기준선과 골든 기록기 변경

1. **바꾸기 전(수정하지 않은 코드)** — `v1-baseline/checks/before-*.txt`:
   - `golden_science_m24.py --check --work <S>/gs_before` → `golden_science_m24.json matches a fresh recording`, **exit 0**.
   - `prototype_golden_egress.py --check` → **exit 0**.
   - `prototype_golden_call_keys.py <S>/gck_before/runs <S>/gck_before/golden_call_keys.json` → exit 0, `cmp`로 커밋된 `golden_call_keys.json`과 **바이트 동일**(이 골든은 재기록하지 않음; 같은 비교를 `test_sequence_ga_jobs.py`가 한다).
   - 골든 파일 SHA-256은 `v1-baseline/README.md` 1절.
2. **fixture 생성**(`v1-baseline/make_v1_fixtures.py`, 수정하지 않은 v1 도구, 1UBQ만): `fixtures/reaction/t1/`에 `m20-v1-candidate-set-golden_m24_mutation.json`(handle `…/f7f7b292…a00d`)·`…golden_m24_dry.json`(`…/fd21366f…32d8`)·`…run_m23_golden_keys-8pos.json`(`…/47a93045…19b8`, M23 8pos fixture와 바이트 동일) — 셋 다 골든에 적힌 handle과 같다. 출처는 `SYNTHETIC-PROVENANCE-t1.md`.
3. **기록기 변경.** 먼저 맨 `store.put`을 시험했다(`<S>/golden_variants.py bare`): 템플릿에서 M20 `Run.call`이 이벤트 5개(15–19: `tool_called`·`object_created`·`wall_charged`·`tool_succeeded`·`wall_charged`)를 쓰던 것이 1개가 되어 **골든과 정확히 네 곳이 다르다**(모두 `mutation_completed_and_conflicts`의 `jev_choice` 보고서, 리듀서가 줄이지 않는 절대 순번):

       /events/20/snapshot_event_seq: golden=37 fresh=33
       /exchanges/8/response/manifest/provenance/created_event_seq: golden=36 fresh=32
       /exchanges/8/response/manifest/provenance/dispatch_event_seq: golden=30 fresh=26
       /exchanges/8/response/manifest/snapshot/event_seq: golden=37 fresh=33

   그래서 `golden_science_m24.py`는 템플릿의 `generate_mutation_candidates` `Run.call`(같은 인자)을 그대로 두고 **그 run의 레지스트리에서 구현만** fixture 내용을 `ctx.store.put`하는 함수로 바꿨다(`stored_v1_set`; 인자 → fixture `parameters`·구조 handle 대조와 결과 handle = fixture handle 단언 포함). 이벤트 수·종류가 같아 차이 0(`variant-runcall-store-put.txt`). `prototype_golden_call_keys.py`는 HTTP 업로드·전처리 뒤 run을 다시 열고 8pos 내용을 `store.put`한다(`stored_v1_candidates`; 위치·허용 잔기·구조 handle 대조, handle 단언; 이 골든에는 순번이 없음). 쓰지 않게 된 `M20_ARGS_EXTRA`는 지웠다.
4. **바꾼 뒤** — `checks/after-*.txt`: `golden_science_m24.py --check` **exit 0**, `prototype_golden_egress.py --check` **exit 0**, `prototype_golden_call_keys.py` 재구성 exit 0·`cmp` **0**, M20 구현을 부르면 예외가 나게 한 상태에서도 `golden_science_m24.py --check` exit 0(구현 호출 0회), 재구성한 run 로그에 `generate_mutation_candidates` 0회(전 2회). `git diff -- …golden_science_m24.json …golden_egress_events.json …golden_call_keys.json` **0줄**.
5. **직접 영향받는 테스트**: `pytest -q "backend/tests/test_sequence_ga_jobs.py::test_golden_m18_m19_m21_call_keys_results_and_hashed_files_are_unchanged" backend/tests/test_jev_science_gate.py -k golden` → **2 passed, exit 0**(45 s). `ruff check` 두 기록기 → All checks passed.
6. **v1 읽기·보고서·`validated_set` 기준선**: `v1-baseline/record_v1_baseline.py --write`(두 번 기록이 같을 때만 씀) → `--check` exit 0, 파일 11개(`baseline/SHA256SUMS`). 저장된 v1 집합 다섯 모두 handle 일치·`validated_set` 통과(돌려준 값 = 입력)·읽기 넷 200. **M20 보고서는 도구 출처가 필요하다**: `store.put`만 한 집합은 v1에서도 `POST /method_reports`가 422 `missing_successful_tool_provenance`라(기록됨), 보고서 바이트 기준선은 v1 도구로 만든 run 로그 전체(`fixtures/reaction/t1/v1-run-run_m23_golden_keys.events.jsonl`)를 events-only로 열어 만든다(8pos·tiny 각 201, `GET /reports` 200). 보고서 snapshot이 앞 보고서 생성 시각을 담지 않도록 집합마다 로그의 새 사본에서 만든다.
7. 커밋 `5672200`(두 기록기, `fixtures/reaction/t1/`, `v1-baseline/`).

결론: 같은 handle·같은 골든 바이트, 옛 `--check` 전후 모두 exit 0. 멈출 조건 없음(기제 차이는 끝 절 1번).

## (j) 해시 집합 확인

- M21: `mutation_model_bundle.py:44–51` `WORKER = backend/mw/jobs/openmm_mutation_worker.py`, `DEPENDENCIES = {mw/mutation_model_math.py, mw/mutation_model_constants.py, mw/jobs/openmm_worker.py, mw/tools/openmm_method.py, mw/mutation_candidates.py}`; `require_ready()`(152–157)이 이 SHA-256과 고정 방법 기록을 호출 키·시작 때 재확인에 쓴다. `test_mutation_model_jobs.py:477–479`가 이 집합을 단언한다.
- M23: `sequence_ga_inputs.py:58–66` `GA_MODULES`(sequence_ga_worker·sequence_ga_constants·sequence_model_worker·sequence_model_bundle) + `M21_MODULES = {"mw/jobs/openmm_mutation_worker.py": mmb.WORKER, **mmb.DEPENDENCIES}`.
- M25 단백질 루프 pin = `{"m18": docking_bundle.require_ready(), "m21": mutation_model_bundle.require_ready()}`(`jev_loop_store.py:890–895`), 리간드 루프는 M18만.
- `grep 'mutation_candidates\.py\|mutation_constants\.py\|mutation_reads\.py\|mutation_reports\.py\|tools/mutations\.py' backend/mw scripts .codex` → 해시에 쓰는 곳은 `mutation_model_bundle.py:51` 하나(나머지는 주석·설명문). M18·M19·M22 pin(`docking_bundle.py:134–135, 224–225`, `docking_batch_jobs`, `ligand_ga_*`)에는 M20 파일이 없다.

결론: 호출 키에 드는 M20 파일은 `mutation_candidates.py` 하나이고 `mutation_constants.py`·`tools/mutations.py`·`mutation_reads.py`·`mutation_reports.py`는 들지 않는다(명세와 같음). 단 M21 작업 모듈이 `mutation_candidates`를 통해 `mutation_constants`를 간접 import하므로(엔지니어링 노트 "호출 키의 의존 파일 해시와 그 밖의 파일") T6은 v1 경로에서 쓰는 상수 값을 바꾸지 않는다. 덧붙여 `/capabilities`의 `methods.sequence_ga_design.pins.modules.m21_sha256`은 지금 파일 해시를 보여 주므로 T6 뒤 값이 바뀐다(저장 기록이 아니라 현재 값). T6의 `golden_call_keys.json` 재기록 기대 차이: `hashed_files["backend/mw/mutation_candidates.py"]`, `pins.m21.dependency_sha256["mw/mutation_candidates.py"]`, `requests.m21_mutation_model.call_key` — M21 모델 객체의 `method`는 고정 방법 기록뿐(파일 해시 없음)이라 모델·M18 도킹 handle은 그대로일 것으로 예상한다(T6에서 확인).

## (k) 진행 중·끝난 M25 루프

`jev_loop_store.step_capability(branch, pins)`(1099–1113행)는 엔진 확인 뒤 지금 pin(`m18`, 단백질이면 `m21`)과 만들 때 pin을 비교해 다르면 `{"reason_code": "missing_configuration", "reason": PINS_CHANGED_REASON}`을 준다. 이 함수를 부르는 곳은 쓰기 경로 `compute_decision`(1123행)뿐이고, 루프 읽기는 만들 때 pin(이벤트)으로 호출 키를 다시 만든다(`jev_loop_store.py:355–364, 442–469`). `mutation_model_bundle.validated_result`·`_check_relations`(396–439행)는 지금 파일 해시를 보지 않는다.

실측(`<S>/m25_loops_hash.py`, `<S>/m25_compute_refusal.py`; 저장된 M25 수락 run `runs/m25-acceptance-20261008/runs/run_568ef869…7480`의 events-only 사본, 해시 변경 대역은 (d)와 같은 사본 바꾸기):

    == ended (133 events)                    # 끝난 단백질 루프 둘
      GET list / 18ffe552… / 80820070…: status 200->200 bytes_equal=True (셋 다)
      step_capability 둘 다: current_files=None changed_hash={'reason_code': 'missing_configuration', ...}
    == in_progress_prefix (109 events)       # 첫 루프의 jev_loop_ended 직전까지
      GET list / 80820070…: bytes_equal=True
    model_step_next (61 events, current.action=compute phase=awaiting_compute step=model):
      POST .../compute {"iteration":1,"proposal":<그 바퀴 제안>} -> HTTP 412 capability_unavailable,
      capability.reason_code missing_configuration, events 61->61
    dock_step_next (80 events, current.action=dock phase=awaiting_docking):
      POST .../compute {"iteration":1} -> HTTP 412 capability_unavailable (같은 detail), events 80->80
    리간드 루프 셋(run_ec871737…): step_capability current=None, changed_hash=None

(계산 단추는 해시를 바꾼 상태에서만 눌렀다 — 지금 pin으로는 실제 작업이 시작되므로.) 결론: 해시가 바뀌면 **진행 중 단백질 루프의 계산 단계(모델 단계와, 이미 만든 모델의 도킹 단계 모두)**가 412 `capability_unavailable`(`capability.reason_code: "missing_configuration"`)로 막히고 아무것도 쓰지 않는다. **끝난 루프의 보이는 값(목록·상세 읽기 바이트)은 그대로**이고, 진행 중 루프의 읽기도 단추를 누르기 전에는 같다(막힘은 누를 때 응답으로만 보임). 리간드 루프는 영향이 없다. 멈출 조건 없음.

## (l) J6 도출 지점과 v1 바이트 불변 시제품

호출 지점(실제 행): `jev_projection.py:608`(투영 만들기, 지역 `wire`), `jev_projection.py:685`(`_validate_projection`, `check_wire` 뒤 `content["wire"]`), `jev_sends.py:552`(`build_choice`, `projection["wire"]`), `jev_sends.py:617`(`_check_choice`, `projection["wire"]`). 네 곳 모두 와이어가 범위 안에 있어 `wire["protection_checks"]["catalytic_residue_database"]`(변이만; 리간드는 `not_available`)로 고를 수 있다. 와이어 허용 값 `PROTECTION_CHECK_STATUSES = ("checked", "not_checked", "not_available")`(`jev_constants.py:171`)라 와이어 모양은 그대로다. M25 루프 와이어는 M24 와이어의 `protection_checks`를 복사하고(`jev_loop_projection.py:264`) 한계 문장은 `jev_loop_constants.limitations_for`(LJ1–LJ8, J6 없음)라 `jev_loop_projection.py`는 바꿀 필요가 없다.

시제품: `backend/`를 `<S>/proto/backend`로 복사(`config`·`.deps`는 저장소로 심볼릭 링크)하고 사본에만 아래 최소 분기를 넣었다(4파일, ± 33줄). 저장소 소스는 바꾸지 않았다.

```diff
# jev_constants.py — STATEMENTS(J1–J7)는 그대로, 그 뒤에 추가
+J6N = (… 명세 9절 J6n 문구 …)
+J6C = (… 명세 9절 J6c 문구 …)
+J6_BY_CATALYTIC_STATUS = {"not_available": J6, "not_checked": J6N, "checked": J6C}
-def limitations_for(kind: str, late: bool) -> list[str]:
+def limitations_for(kind: str, late: bool, catalytic: str = "not_available") -> list[str]:
-    if kind not in KINDS or type(late) is not bool:
+    if kind not in KINDS or type(late) is not bool or catalytic not in J6_BY_CATALYTIC_STATUS:
-    return [J1, J2, J3, J4, J5 if kind == "ligand" else J6, *([J7] if late else [])]
+    return [J1, J2, J3, J4, J5 if kind == "ligand" else J6_BY_CATALYTIC_STATUS[catalytic], *([J7] if late else [])]
+def catalytic_status(kind: str, wire: dict) -> str:
+    return wire["protection_checks"]["catalytic_residue_database"] if kind == "mutation" else "not_available"
# jev_projection.py 608·685
-        "limitations": limitations_for(kind, False),
+        "limitations": limitations_for(kind, False, catalytic_status(kind, wire)),
# jev_sends.py 552·617
-        "limitations": J.limitations_for(kind, late),
+        "limitations": J.limitations_for(kind, late, J.catalytic_status(kind, projection["wire"])),
# jev_reports.py 48
-FIXED_LIMITATIONS = frozenset(J.STATEMENTS.values())
+FIXED_LIMITATIONS = frozenset(J.STATEMENTS.values()) | frozenset(J.J6_BY_CATALYTIC_STATUS.values())
```

사본 기준 결과(`mw imported from: <S>/proto/backend/mw/__init__.py` 확인):

- `golden_science_m24.py --check`(사본) → `matches a fresh recording`, **exit 0**.
- `prototype_golden_egress.py --check`(사본) → **exit 0**.
- 사본에서 `pytest -q test_jev_constants.py test_jev_projection.py test_jev_reports.py test_jev_sends.py test_jev_tool.py` → **372 passed, exit 0**(기존 테스트 무수정).
- 골든에 저장된 v1 투영(와이어 `not_available`)이 분기 뒤에도 `validated_projection`을 통과하고 `limitations`가 같음; 와이어 상태를 `not_checked`/`checked`로 바꾸면 `check_wire` 통과, 다섯째 문장이 J6N/J6C, 두 문장은 `STATEMENTS`에 없고 `jev_reports.FIXED_LIMITATIONS`에 있음; 리간드 불변; 모르는 상태는 `ValueError`.

결론: J6 분기는 v1(`not_available`) 바이트를 바꾸지 않는다. J6n·J6c는 `STATEMENTS` 밖 별도 상수(`J6_BY_CATALYTIC_STATUS`)에 두고 `FIXED_LIMITATIONS`에만 더하면 `test_jev_constants.py:210–225`가 그대로 통과한다. 멈출 조건 없음.

## (m) M20 입장 순서와 capability 모양

- **실제 실행 순서**(`tools/mutations._admit`, 58–83행): `check_fields`(`unknown_field`) → `structure_invalid` → `structure_residues` → `normalize_request`(`argument_invalid`·`allowed_residues_invalid`·`residue_invalid`·`no_position_source`·`duplicate_residue`·`protect_release_conflict`·`ligand_required`·`ligand_invalid`) → 리간드 중원자(`ligand_invalid`) → `pocket_set_invalid`(66–67) → `numbering_map_invalid`(68–69) → `annotation_invalid`(70–71) → `structure_mismatch`(포켓 72–73 → 번호 대응 74–75 → 주석 76–77) → `pocket_rank_invalid`·`pocket_residue_mismatch`(`pocket_lining`, 78–79) → `annotation_map_mismatch`(80–82). `catalytic_annotation_invalid`는 71행 다음·72행 앞에 들어가고 `structure_mismatch`는 77행 뒤에 결과의 `structure.handle` 비교를 더한다.
- **튜플 순서**(`mutation_constants.py:28–33`, 명세 표 순서 = 실행 순서와 다름): `unknown_field, structure_invalid, no_position_source, argument_invalid, allowed_residues_invalid, residue_invalid, duplicate_residue, protect_release_conflict, ligand_required, ligand_invalid, pocket_set_invalid, structure_mismatch, pocket_rank_invalid, pocket_residue_mismatch, numbering_map_invalid, annotation_invalid, annotation_map_mismatch`(17개). v2는 `annotation_invalid` 바로 뒤에 `catalytic_annotation_invalid`(18개).
- **단언 위치**: `test_mutation_candidates.py:141–145`(튜플), `157–172`(import 제한), `test_mutation_tool.py:158–`(입장 이유마다 구현 호출 0회).
- **`/capabilities` `methods.residue_numbering` 실제 모양**(TestClient, `<S>/logs/m_capabilities.txt`): 정상 `{"available": true, "reason_code": null, "reason": null, "set_hash": "aa21ead9…3317", "sources": [{"source", "snapshot_id", "date", "version_hint", "license", "origin"} × 3]}`, 빈 참조 폴더 `{"available": false, "reason_code": "not_installed", "reason": "참조 스냅샷 세트가 설치되어 있지 않습니다(가져오기 명령 scripts/import_reference_snapshots.py). Reference snapshot set is not installed.", "set_hash": null, "sources": []}`. 새 `methods.reaction_knowledge`는 같은 다섯 키, 사용할 수 없으면 `set_hash: null`·`sources: []`(명세 6절 status 라우트의 `null`과 다름에 주의), 이유 문구는 `scripts/import_reaction_references.py`를 가리키게 한다. `test_numbering_api.py:80–100`이 모양·세 상태 시험 선례다.

## 명세와 다른 점

1. **골든 기록기의 넣는 방식(`golden_science_m24.py`).** 계획 (i)의 "저장된 v1 내용을 `store.put`으로 넣는다"를 문자 그대로(맨 `store.put`) 하면 골든 바이트가 네 곳(절대 이벤트 순번 −4) 달라진다. 그래서 M20 `Run.call` 봉투는 그대로 두고 그 run의 레지스트리 구현만 fixture 내용을 `store.put`하는 함수로 바꿨다(M20 구현은 실행되지 않음, handle·골든 바이트 동일). `prototype_golden_call_keys.py`는 맨 `store.put`이다.
2. **추가 fixture.** M20 보고서는 도구 출처가 있어야 만들어지므로(`missing_successful_tool_provenance`) v1 보고서 기준선을 위해 v1 도구로 만든 run 로그(`v1-run-run_m23_golden_keys.events.jsonl`, 232,554 B)를 fixture로 더했다. `fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json`과 같은 바이트의 t1 사본을 둔 것은 `build_sequence_ga_fixtures.py`를 v2 뒤에 다시 써도 골든 입력이 바뀌지 않게 하기 위해서다.
3. **M15 kinase 수.** 인계 문서의 "kinase 542개"는 행 수이고 명세 4.2의 `status: ok`는 **541개**다(`O43930`은 `lookup_failed`).
4. **진행 중 루프 막힘의 범위.** 단백질 루프만 막히고(모델 단계와 도킹 단계 모두, M18·M21 pin을 함께 비교하기 때문), 리간드 루프는 막히지 않는다. 막힘은 계산 단추 응답(412, `capability.reason_code: "missing_configuration"`)으로만 보이고 읽기 바이트는 같다.
5. **업그레이드 전 큐 작업**은 과금 전 412 `worker_version_invalid`로 거절되지만 `claimed`로 남는다(자동 실패 아님) — 취소 후 재제출 안내가 필요하다(T13 기록).
6. **T6 뒤 새로 만드는 집합은 v2 `not_checked`(주석 없음)이다.** 도구로 집합을 만드는 기존 테스트·하네스·실행기의 v1 기대(`not_available`, J6, M20 셋째 문장)는 바뀐다(위 (f) "v1 값에 묶인 기대"). `build_sequence_ga_fixtures.py --check`는 설계상 실패하며 `--write`하지 않는다.
7. **기존 회귀 실행기는 `MW_REACTION_REFERENCE_DIR`를 넘기지 않는다**(`child_env` 허용 목록) — (h)의 두 선택지 중 하나를 T9/T11이 고른다.
8. `fixtures/jev/SYNTHETIC-PROVENANCE.md`와 `fixtures/sequence_ga/SYNTHETIC-PROVENANCE.md`의 기록기 설명은 옛 방식(M20 도구 호출)을 적고 있다. T1의 커밋 범위 밖이라 고치지 않았고, 두 기록기 docstring과 `fixtures/reaction/t1/SYNTHETIC-PROVENANCE-t1.md`에 새 방식을 적었다(T13에서 변경 기록 한 줄씩 권함).

그 밖에 명세 8·9·11.3·12절과 다른 점은 없다.

### 작업별로 바꿀 기존 파일 (카디널리티 결합 지도)

| 작업 | 바꿀 기존 파일(새 파일 제외) |
|---|---|
| T2 | 없음(새 모듈·테스트만). 지킬 것: 증액 문자열 AST 셋, `test_jev_ast.py` httpx 위치 |
| T3 | `.codex/hooks/stop.py` `SCRIPT_TESTS`(+`scripts/test_import_reaction_references.py`) |
| T4 | `config/tools.yaml`(새 도구), `backend/mw/workspace.py`(`build_registry`), `backend/mw/api/app.py`(`SUPPORTED_TOOLS` 132–135, `methods["reaction_knowledge"]` 660–688, 읽기 라우트 넷), `backend/tests/test_api.py:279–285`, `test_reference_site_annotation.py:692–696`, `test_residue_numbering.py:747–752`, `test_ligand_api.py:23·420·~457` |
| T5 | `backend/mw/api/app.py`(1309–1311 분기, 1346–1349·1363–1367 집합, 1369–1402 다시 열기 분기) |
| T6 | `backend/mw/mutation_constants.py`(`ARG_KEYS` 16, `ADMISSION_REASON_CODES` 28–33, v2 상수), `mutation_candidates.py`(해시 파일), `tools/mutations.py`(`_admit` 71/72·77행), `mutation_reads.py`(`_LIST_FIELDS` 25, 목록·상세 `catalytic_status`), `mutation_reports.py`(`FIXED_LIMITATIONS` 59, v2 촉매 절), `config/tools.yaml`(202–218 `catalytic_annotation`), `jev_constants.py`, `jev_projection.py`(608·685·import), `jev_sends.py`(552·617), `jev_reports.py`(48), `backend/tests/fixtures/sequence_ga/golden_call_keys.json`(재기록), `backend/tests/test_mutation_candidates.py`(135–172), `test_mutation_tool.py`(133–146·158–), `test_mutation_api.py`, `test_mutation_reports.py`(193 근처), `test_jev_projection.py`(557·568·585), `test_jev_tool.py`, `test_jev_constants.py`(J6N·J6C 단언 추가), `test_jev_reports.py`(175 근처) |
| T7 | `frontend/src/lib/mutations.ts`(44·103·583–585, `CATALYTIC_NOTE`), `lib/jev.ts`(51–60), `lib/contracts.ts`(719, ~1192, 새 응답형), `lib/api.ts`(261, 새 읽기), `lib/report-library.ts`(94–98), `frontend/tests/mutations.test.cjs`, `jev.test.cjs`, `report-library.test.cjs`(51 근처) |
| T8 | `frontend/src/components/MutationPanel.tsx`, `MutationModelPanel.tsx`, `SequenceGaPanel.tsx`, `JevPanel.tsx`, `JevLoopPanel.tsx`, `WorkspaceTabs.tsx`(12–14·53), `frontend/app/page.tsx`, `frontend/src/components/index.ts`, `design/components.css`, `frontend/tests/workspace-tabs.test.cjs`, 토큰 생성물 |
| T9 | `frontend/tests/offscreen/mutation-flow.cjs`(703–712), `.codex/hooks/stop.py` `SCRIPT_TESTS`(+`scripts/test_m26_offscreen_acceptance.py`), 필요하면 `jev-flow.cjs`(52·129)·`tabs-flow.cjs`·`jev-loop-flow.cjs`와 M20·M24 실행기 기대, (h)의 실행기 env(선택지 (2)면 `scripts/m13`·`m14`·`m15`·`m17`·`m24`·`m25_offscreen_acceptance.py`) |
| T11·T13 | `docs/standards.md`(40·41–54행 게이트 목록), `docs/operations.md`(Stop 훅 문단), 필요하면 `.codex/hooks/stop.py` 그룹·`scripts/test_codex_hooks.py:145`(그룹을 새로 만들 때만), 기록 문서 |
