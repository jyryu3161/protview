# M29 T2 — 간헐 실패 시험 고정 (분석)

작업 시작점: `6808d36a`(브랜치 `dryforge/m29-structure-repair`). 고친 커밋: `e1da210b`, `16aa05d8`, `ea608e33`, `0218cfa5`, `0a9a602a`(주석만), `cddc638a`(바꾼 파일은 모두 `backend/tests/`). 제품 코드(`backend/mw`), `scripts/`, `.codex/`, 호출 키 해시 파일 27개, 골든은 바꾸지 않았다. 작업 중 조율 세션이 같은 브랜치에 T3b·T4·T5·T7 커밋을 병합했으므로(`34c6786f`, `ea166565`, `53ca2853`, `100363d6`) `git diff --name-only 6808d36a..HEAD`에는 그 파일도 보인다. T2 커밋의 파일만은 아래 "고친 것" 표와 같다.

실행 증거: `docs/qa/m29-repair-20261013/t2-flaky-tests.txt`(텍스트 요약). 전체 출력·측정 스크립트·원자료는 Git 제외 폴더 `frontend/tests/offscreen/artifacts/m29-repair/t2/`에 있고 텍스트 증거에 경로·크기·SHA-256만 적었다. 측정 스크립트는 모두 제품 코드가 아닌 일회용이며 그 폴더의 `scripts/`에 있다(`load18.py`: Stop 훅의 `PYTEST_GROUPS`와 REST 그룹을 import해 훅 그룹 전부(열여덟, T5 병합 뒤 열아홉)를 같은 명령·480초 제한으로 동시에 돌림).

## 1. 재현 (고치기 전 시험 코드: 소스 `34c6786f` = `6808d36a` + T3b 고정 자료·문서만)

- **R0**: 열여덟 그룹 + 추가 부하(지연 측정기, `test_docking_batch_reports.py` 두 벌, 서열 GA SIGTERM 시험 한 벌)를 동시에 돌렸다. 기존 관찰 두 가지가 그대로 나왔다.
  - group12 `test_sequence_ga_worker.py::test_sigterm_cancels_the_running_step_and_leaves_no_process[qvina-worker]` 1 failed: `AssertionError: individual 0 ended before it was held`.
  - group05 `test_docking_batch_api.py` 13 errors: 모듈 fixture `docking_batch_fixture.build_world`의 148행 `[row["state"] …][2:] == ["cancelled", "not_run"]`에서 `AssertionError`(그 앞의 `jobs["partial"]["status"] == "cancelled"`와 `status == "partial"`은 통과). fixture 모듈은 pytest 단언 재작성 대상이 아니어서 실제 행 상태는 출력에 없었다(고친 뒤에는 메시지에 행 상태와 붙잡은 기록을 싣는다).
  - 추가로 돌린 `test_docking_batch_reports.py` 두 벌과 서열 GA SIGTERM 한 벌은 그 회에 통과했다.
- **R1**(같은 소스, 열여덟 그룹만 + 미세 재현): 열여덟 그룹은 모두 통과했다(간헐).
- 지연 측정(R0 동안 420초, `latency_probe.py`): `time.sleep(0.01)` 깨어남 지연은 최대 13.19 ms(9,250회), 전체 프로세스 훑기 직후에도 최대 3.98 ms였다. 반면 psutil로 시스템의 모든 프로세스를 훑는 측정 단위(`Process.children` 두 번: 자기 자식 재귀 + pid 1의 자식)는 중앙값 365 ms, 99% 7,457 ms, 최대 8,078 ms(185회)였다. 한 번 훑기는 아래 미세 재현의 실패 시행에서 1.15–2.35초였다. 그때 1분 부하 평균은 평균 24.8, 최대 37.9(28코어)였다. **시험 프로세스가 스케줄러에 굶는 것은 아니었고, 느린 것은 전체 프로세스 훑기였다.**

## 2. 원인

### 2.1 서열 GA SIGTERM `[qvina-worker]` (와 같은 붙잡기 기법)

T1 (h)의 가설(qvina2를 찾고도 CPU 0.05초 미만이면 그룹을 재개하는데 그 재개 구간에 qvina2가 끝난다)은 측정과 맞지 않았다. 재개 구간은 `sleep(0.01)`과 깨어남 지연(최대 13 ms)뿐이라 약 12 ms이고, 이 입력의 qvina2는 CPU 약 0.9초가 필요하다(개체 0 입력으로 실측 0.88초).

미세 재현(`micro.py` + `fake_worker.py`): 실제 작업 모듈 대신 개체 0의 실제 qvina2 입력으로 실제 `qvina2`를 `subprocess.run`하는 대역 작업자(표지 `model_work/qvina/ligand.pdbqt`를 쓰고 바로 qvina2 실행, SIGTERM은 도킹 중에만 받음)를 두고, 시험의 붙잡기 알고리즘만 그대로 옮겨 열여덟 그룹 부하 아래에서 돌렸다. 대역 작업자는 시각표(표지 씀, qvina2 호출, qvina2 반환)를 남긴다.

| 알고리즘 | 회 | 통과 | 실패 |
|---|---|---|---|
| 옛 `_held_step`(커밋된 것 그대로) | R1 40 + R2 60 | 89 | 11 ("individual 0 ended before it was held") |
| 처음 보는 즉시 붙잡기 + 옛 전체 훑기 | R1 40 | 35 | 5 (같은 메시지) |
| 처음 보는 즉시 붙잡기 + 자식 한 번 조회(고친 것) | R2 150 | 150 | 0 |

실패 16건의 시각표는 모두 같은 모양이었다(측정으로 확인): 대역 작업자가 qvina2를 호출한 시각이 시험이 표지를 처음 본 시각(곧바로 그룹 SIGSTOP)의 9 ms 전부터 1 ms 뒤 사이였고, qvina2는 그 뒤 1.02–2.00초에 끝까지 돌고 반환했다. 그 시행들에서 "정지 상태의 조회"(그룹 SIGSTOP → psutil 전체 훑기) 한 번이 1.15–2.35초 걸렸다. 1 ms 뒤에 호출한 경우는 psutil이 정지로 보고한 뒤에도 작업자가 잠깐 더 돌았다는 뜻이다(아래 표의 둘째 열과 같은 현상). 곧 **그룹을 멈추는 순간 막 fork/exec 중이던 qvina2가 멈추지 않았고, 이어진 긴 전체 훑기가 그 qvina2가 끝날 시간을 줬다.** M28의 "두 번째 SIGSTOP"은 이 틈을 닫지 못했다.

그룹 정지의 틈은 따로 쟀다(`forkstop.py`, 400 MiB 힙을 가진 파이썬 리더가 `subprocess.run(["/bin/sleep","0.2"])`를 반복, 무작위 시각에 그룹 정지):

| 방식 | 정지 회수 | psutil이 리더를 stopped로 본 직후 리더 스레드가 CPU에 있던 회수 | 50 ms 뒤 실행 중인 그룹 구성원이 있던 회수 |
|---|---|---|---|
| 정지 → psutil stopped 대기 → 다시 정지(M28과 같음) | 300 / 800 / 800 / 800 | 3 / 12 / 3 / 13 | 1 / 2 / 2 / 17 |
| 위 + 리더 스레드가 CPU를 떠날 때까지 대기 | 300 / 800 / 800 | 0 / 6 / 6 | 0 / 2 / 2 |
| 위 + 모든 구성원이 멈춘 것으로 보일 때까지 다시 정지 | 800 / 800 / 800 | 24 / 17 / 19 | 6 / 5 / 10 |

코드로 확인한 것: 옛 `_held_step`은 그룹을 멈춘 뒤 `worker.children(recursive=True)`로 찾고, psutil의 `children()`은 모든 pid의 부모를 하나씩 읽어 지도를 만든다(설치된 psutil 7.2.2 소스). 측정으로 확인한 것: 위 두 표와 훑기 시간. 추정: 커널 안에서 정확히 어떤 경로(fork 마무리 중의 정지, exec 중에 잃는 정지)로 틈이 생기는지는 확인하지 않았다. 어느 쪽이든 정지를 확실하게 만들 수는 없었으므로(셋째 줄), 고침은 "빠져나간 자식이 끝날 시간을 주지 않는 것"이다.

또 하나: 옛 `_blocked`는 CPU 시간이 50 ms 간격 세 번 같으면 막힌 것으로 봤다. 굶은 실행 가능 프로세스나 멈춘 프로세스도 CPU 시간이 같으므로 오판할 수 있다(macOS는 막힌 프로세스의 psutil 상태도 running으로 보인다). libproc 스레드 실행 상태로 재 보니 멈춘 프로세스·막힌 프로세스는 TH_STATE_WAITING, 실행·실행 대기는 TH_STATE_RUNNING이었다. 이 오판이 실제 실패로 나온 적은 없다(예방적 보강).

### 2.2 M19 world fixture의 부분 배치 (`docking_batch_fixture.build_world`)

재현은 위 R0. 원인(코드로 확인): 이 fixture는 `rows/2.started`가 보이면 큐의 취소 경로로 취소를 요청한다. 취소는 큐가 다음 감시 반복에서 guardian에 STOP을 보내고, guardian이 감시 루프의 표본(`MONITORED_ADAPTERS`인 배치 작업은 표본마다 `process.children(recursive=True)`로 모든 프로세스를 훑음)을 마친 뒤 `members()`(모든 pid의 프로세스 그룹 확인) → `cleanup()`(다시 `members()`) 다음에야 작업자에 SIGTERM을 보낸다. 부하에서 이런 훑기는 한 번에 수백 ms에서 2초 넘게 걸리고(위 측정) 이 배치의 한 행(exhaustiveness 1, 12 Å 상자)은 약 1초다. 그래서 취소가 행 3이나 마지막 행 뒤에 닿아 148행이 실패했다. 실제 행 상태 값은 캡처하지 못했다(추정: `[scored, cancelled]` 또는 `[scored, scored]`). 같은 hook 모양(행·개체가 시작될 때 취소)이 `test_docking_batch_jobs.py`(행 1)와 `test_ligand_ga_jobs.py`(개체 1, exhaustiveness 1)에도 있어 같이 고쳤다(그 둘은 이번 실행들에서 실패하지 않았다).

### 2.3 게이트 3회째에서 드러난 신호 순서 경합 (제품 쪽 경합, 고치지 않고 기록)

첫 수정(행 2의 qvina2를 붙잡은 뒤 큐 취소)으로 게이트를 돌리자 1·2회는 통과하고 3회째에 `test_docking_batch_reports.py` 11개가 같은 fixture 단언으로 ERROR였다. 이번에는 메시지에 기록이 실렸다: 붙잡기는 성공(qvina2 pid 469, 조회 29번)했는데 행 상태가 `rows[2:] = [("failed", "engine_failed"), ("cancelled", "cancelled")]`였다.

원인(코드 + 재현으로 확인): guardian은 그룹을 멈출 때 `members()`(psutil `pids()` 오름차순)로 구성원마다 SIGTERM을 보낸다. 이 기계는 pid가 한 바퀴 돌아 qvina2가 469, 작업자가 그보다 큰 pid였다. 그래서 붙잡힌 qvina2가 먼저 SIGTERM을 받아 죽었고(멈춘 프로세스도 기본 동작의 SIGTERM이면 바로 끝남: 직접 확인), 작업자는 자기 SIGTERM보다 먼저 qvina2의 종료(-15)를 처리해 `engine_failed`를 기록했다. 실제 배치 작업자(`docking_batch_worker.py`, 고정 venv, 실제 qvina2)로 따로 재현했다(`sigorder.py`): qvina2를 먼저, 작업자를 5 ms 뒤에 SIGTERM하면 두 번 모두 행 1이 `failed/engine_failed`(다음 행 `cancelled`), 작업자를 먼저 보내면 두 번 모두 `cancelled`였다.

이것은 제품 쪽 경합이다: 실제 사용에서도 취소가 qvina2 실행 중에 닿고 qvina2의 pid가 작업자보다 작으면(pid가 한 바퀴 돈 뒤) 사용자가 취소한 행이 `engine_failed`로 남을 수 있다. 제품 코드는 이 작업의 범위가 아니어서 고치지 않았고 T18이 `findings.md`에 옮기도록 여기와 보고에 적는다. 고친 이전 fixture도 취소가 qvina2 실행 중에 닿을 때는 같은 경합을 탔다(드물었을 뿐이다).

시험 쪽 수정(`0218cfa5`): `engine_hold.hold_then_cancel`이 (1) 엔진을 붙잡고 작업자가 그 위에서 막힐 때까지 기다리고, (2) guardian을 멈추고, (3) 큐에 취소를 요청한 뒤 큐가 guardian에 STOP을 보낼 때까지 기다리고(`_send` 감싸기), (4) guardian이 STOP 뒤에 보낼 SIGTERM을 작업자에 먼저 보내고 작업자가 엔진을 끝낼 때까지 기다린 다음, (5) guardian을 재개한다(그 뒤 guardian은 평소처럼 그룹을 정리한다). 작업자가 늘 먼저 신호를 받으므로 pid 순서와 무관하게 작업자 자신의 취소 처리가 행을 `cancelled`로 기록한다. 이 세 시험이 보려는 것(부분 배치·부분 GA 요약, 재사용, 예산)은 그대로이고, guardian이 그룹에 보내는 SIGTERM 자체는 다른 시험(작업자 SIGTERM 시험, 포켓 취소 시험 등)이 본다.

### 2.4 분석 흐름 정지 시험 (조율 세션이 넘긴 추가 사례)

조율 세션의 Stop 훅 실행(다른 작업의 시험과 내 열여덟 그룹이 겹쳐 열여덟 그룹 중 열 개가 480초에 걸린 극한 부하)에서 `test_analysis_workflows.py::test_stop_during_owned_real_job_cancels_only_that_job`이 마지막 확인(옛 1463행 `job["status"] == "cancelled" and job["cleanup_status"] == "verified"`)에서 상태 `'running'`으로 실패했다(그룹 1 failed, 129 passed, 393.9초).

재현(`scratch_stop_probe.py`: 같은 시험의 계측 사본, 시각과 그 run의 이벤트 기록을 남기고 시간으로는 실패하지 않음, 열여덟 그룹을 두 벌 동시에 돌리는 동안 95회씩 두 번): 소유자 스레드의 `advance`는 놓아준 뒤 최대 5.3초에 돌아왔는데(첫 회 69/95, 둘째 회 10/95) 작업은 `running`, 정리는 `pending`이었다. 둘째 회에서 기록한 이유는 모두 `job_cleanup_pending` `guardian_result_missing`이었고 그 10건 모두 run 조정(`reconcile_run`) 한 번(0.075초 안)으로 `cancelled`·정리 확인(`source: orphan_reconciliation`)이 되었다. 원인(코드로 확인): 큐는 STOP 뒤 guardian의 결과를 4초 기다리고(`_stopped_result`), guardian은 신호 전에 모든 프로세스를 훑으므로 부하에서 그보다 늦게 답한다. 그러면 큐는 작업을 `running`으로 두고 정리를 미뤄 두며, 이 미룬 작업은 API가 run을 다시 열 때(`api._run`의 `reconcile_run`) 닫힌다. 곧 시험이 "취소가 그 호출 안에서 끝난다"고 가정한 것이 부하에서 틀렸다. `join(60)`의 시간은 원인이 아니었다(최대 5.3초).

시험 쪽 수정(`cddc638a`): 작업이 아직 `running`이면 큐가 두 미룸 이유(`guardian_result_missing`·`group_not_verified_empty`) 중 하나를 기록했는지 확인한 뒤 API처럼 조정하고, 그다음 원래와 같은 끝 상태(`cancelled`, 그룹 비었음 확인)를 요구한다. 소유자 스레드가 60초 안에 돌아오지 않으면 자기 메시지로 실패한다. 제품 코드(M13 흐름 포함)는 바꾸지 않았다.

### 2.5 그 밖의 검토 대상

- `SystemError` 미처리 넷: `process_iter(["name"…])`의 미리 읽기는 생성기 안, 곧 시험의 `try` 밖에서 돌아, 읽는 순간 끝난 아무 프로세스의 psutil `SystemError`가 새어 나온다(M28이 `_engines_under`에서 확인·수정한 것과 같은 코드 모양). 이번 실행에서 재현되지는 않았다.
- 부분 문자열 검사 둘: manifest(정규 JSON)에 스냅숏 `time_utc`(`time.time()`)와 예산 벽시계가 들어 있어 `0.4321`·`0.1234`가 우연히 그 숫자의 일부가 될 수 있다(M24 `test_jev_reports.py`에서 실제로 실패했고 M28이 그 파일만 고쳤다). Markdown 본문에는 스냅숏 숫자가 없다(`jev_reports.py`·`jev_loop_reports.py` 확인).

## 3. 고친 것

| 파일 | 고친 것 | 이유 |
|---|---|---|
| `backend/tests/engine_hold.py`(새 시험 보조 모듈) | 작업자의 직계 자식을 libproc `proc_listchildpids` 한 번으로 조회, `hold`(멈췄고 CPU에 스레드가 없고 20 ms 동안 CPU 시간이 그대로일 때까지 SIGSTOP 반복), `hold_past_exec`(사용자 CPU 시간이 0보다 커질 때까지 그 엔진만 1 ms씩 진행, 부모는 정지 유지), `wait_blocked`(모든 스레드 WAITING + CPU 시간 세 번 같음), guardian 그룹용 `hold_job_engine`, 순서를 고정한 취소 hook `hold_then_cancel`(2.3) | 2.1–2.3. 한 번 조회는 0.6 ms 안팎(R2 최대 30 ms)이라 빠져나간 엔진이 조회 중에 끝날 수 없다. macOS 밖에서는 psutil로 같은 사실을 읽는다 |
| `test_sequence_ga_worker.py` | `_held_step`: 표지 뒤 매 조회는 그룹 정지 → 직계 자식 조회, qvina2는 처음 본 조회에서 붙잡고 다시 재개하지 않음(CPU 0.05초 조건 삭제), 조회마다 재개 구간·pid·CPU를 남겨 실패 메시지에 싣고 성공 때도 출력. `_blocked` → `EH.wait_blocked` | 2.1. "놓치면 다음 개체로" 같은 우회는 쓰지 않았다(개체 0이 끝났으면 여전히 실패) |
| `test_pocket_jobs.py` | `_held_engine`을 `EH.hold_job_engine`으로. 소유자 죽음 시험(옛 927–957행)은 소유자의 barrier가 fpocket을 붙잡은 뒤에 보고하고, 시험이 소유자를 죽이기 전에 fpocket이 정지 상태임을 단언 | 같은 기법(전체 훑기). 소유자 죽음 시험은 fpocket(약 1.7초)이 스스로 끝나도 "사라졌다"로 통과하던 검증 공백을 닫았다 |
| `test_ligand_ga_worker.py` | SIGTERM 시험이 개체 2의 qvina2를 붙잡은 뒤(작업자만 재개, 막힘 확인) 신호. 실패해도 멈춘 프로세스를 남기지 않음. `_qvina_under` 미리 읽기 제거 + `SystemError` | 보고-후-신호: 전체 훑기(부하에서 수백 ms–2초 이상) 뒤에 신호를 보냈는데 이 도킹(exhaustiveness 1)은 그보다 짧을 수 있다 |
| `test_docking_jobs.py` | qvina2 감시 스레드가 직계 자식 한 번 조회를 씀 | 시간 초과 사례(작업 15초)에서 작업자 준비와 감시 훑기(부하에서 수백 ms–2초 이상, 반복)가 같은 15초 안에 들어간다 |
| `test_docking_batch_worker.py` | `_qvina_under` 미리 읽기 제거 + `SystemError` | 2.5 |
| `docking_batch_fixture.py` | 부분 배치 취소가 `hold_then_cancel`(행 2의 qvina2를 붙잡고, 큐 취소, 작업자에 먼저 SIGTERM). 붙잡은 기록·행 상태(상태와 이유)를 단언 메시지에 싣고, 붙잡지 못했으면 실패 | 2.2·2.3. 시간 여유를 늘린 것이 아니라 "취소가 닿기 전에 행이 끝나는" 경로와 신호 순서 경합을 없앴다 |
| `test_docking_batch_jobs.py` | 취소 시험(행 1)에 같은 hook. `_no_strays` 미리 읽기 제거 + `SystemError` | 2.2·2.3·2.5 |
| `test_ligand_ga_jobs.py` | 취소 시험(개체 1)에 같은 hook | 2.2·2.3 |
| `test_sequence_ga_jobs.py` | `no_strays` 미리 읽기 제거 + `SystemError` | 2.5 |
| `test_jev_api.py`, `test_jev_loop_reports.py` | manifest 검사를 온전한 숫자 일치로(M28 `test_jev_reports.py`와 같은 정규식) + 새는 값을 여전히 잡는지 보는 작은 시험 | 2.5 |
| `test_analysis_workflows.py` | 정지 시험: 소유자 스레드가 돌아온 뒤에도 작업이 `running`이면 미룸 이유를 확인하고 API처럼 run을 조정한 다음 원래 끝 상태를 요구. 스레드가 60초 안에 안 돌아오면 자기 메시지로 실패 | 2.4 |

붙잡기 뒤 시험의 단언(결과 파일, 개체·행 상태, 남은 엔진 없음, `0.status.json` 없음)은 그대로다. 시험 입력(도킹 인자 등)은 바꾸지 않았다. exhaustiveness를 올려 qvina2를 길게 만드는 방법(T1 후보 2)은 미세 재현에서 25/25였지만 여유만 늘리는 것이라 쓰지 않았다.

## 4. 고치지 않은 것과 이유

- `test_docking_batch_worker.py` 307–345(`_start` 뒤 SIGTERM, SIGKILL): 행이 exhaustiveness 8이라 30초를 넘는다(파일의 T1 (b) 측정 주석). 전체 훑기 뒤 신호여도 행이 먼저 끝날 수 없고, 신호는 시험이 작업자에게 직접 보내므로 2.3의 순서 경합도 없다. 그대로 둠.
- `test_openmm.py` 653–672(준비 체크포인트를 본 뒤 검증하고 SIGSTOP): 1UBQ M7 작업자는 `preparation.json` 뒤 7.93초 더 돈다(부하 평균 약 6에서 실측, `m7_timing.py`). 시험이 신호 전까지 하는 일(JSON·XML 검증, 신원 확인)은 그보다 훨씬 짧다. 그대로 둠.
- 강제 종료(SIGKILL) 변형(`test_docking_batch_jobs`·`test_ligand_ga_jobs`·`test_sequence_ga_jobs`의 hard kill): 표지를 본 스레드가 곧바로 `os.kill(SIGKILL)`을 보내므로 큐·guardian 지연이 없다. 그대로 둠.
- `test_sequence_ga_jobs.py`의 개체 1 취소: 개체 1의 모델링 단계(1UBQ M21 약 20초)가 취소 창이라 여유가 크다. 그대로 둠.
- M17 `test_ligand_jobs.py`의 STARTED 때 취소: 작업 상태를 큐의 취소 이유가 정하고 결과가 작업자의 진행 위치에 달려 있지 않다. 그대로 둠.
- Markdown 본문의 부분 문자열 검사: 본문에는 스냅숏 숫자가 없어 그대로 둠(M28과 같은 판단).

## 5. 남은 위험

- `engine_hold`의 정확한 정지 판정은 macOS libproc(스레드 실행 상태, 직계 자식 조회)에 기대고, 다른 플랫폼에서는 psutil로 같은 사실을 읽는 대체 경로가 있으나 이 기계 밖에서는 돌려 보지 않았다.
- 표지를 본 뒤 qvina2를 찾기 전의 재개 구간(서열·리간드 GA 10 ms, 포켓 5 ms, 배치 2 ms)에는 엔진이 잠깐 돈다. 측정한 깨어남 지연은 최대 13 ms이고 조회는 30 ms 안이라 0.9초짜리 qvina2가 그 사이에 끝날 수는 없다. 다만 표지 자체를 놓칠 만큼(약 1초) 시험 프로세스가 멈추는 일이 생기면 시험은 실패한다(숨기지 않음). 이번 측정에서 표지 확인(`stat`)은 최대 1 ms였다.
- `hold_past_exec`는 아직 자기 코드를 돌리지 않은 엔진만 1 ms씩 진행시킨다(부모는 정지). 그 사이 엔진이 끝나면 시험은 실패로 드러난다.
- `hold_then_cancel`은 큐의 내부 함수 `_send`를 감싸 STOP 전송을 안다(기존 `_record_control` 감싸기와 같은 종류의 시험 hook). 큐가 STOP 뒤 guardian 결과를 4초 기다리는 기존 동작(`_stopped_result`)은 그대로이며, guardian을 멈춰 두는 시간은 작업자가 SIGTERM을 처리하는 동안(ms 단위)뿐이다.
- 2.3의 신호 순서 경합은 제품에 그대로 남는다(사용자가 취소한 행이 드물게 `engine_failed`로 기록될 수 있음). T18이 `findings.md`에 옮길 새 발견이다.
- 2.4의 "guardian이 4초 안에 답하지 못하면 정리를 미룸"은 guardian으로 취소하는 다른 작업 시험에도 같은 코드 경로로 있다. Stop 훅 한 벌 부하(이 작업의 게이트 조건)에서는 실패를 보지 못했고 열여덟 그룹을 두 벌 이상 겹치면 나올 수 있다. 실패가 확인된 분석 흐름 시험만 고쳤다(근거가 있는 곳만). 더 무거운 부하를 게이트 조건으로 삼을지는 T14·조율 세션이 정한다.
- 이 기계에서는 다른 작업(T4·T5 worktree)의 열여덟 그룹과 조율 세션의 Stop 훅이 수시로 겹쳤다. 그런 겹침이 분명한 회는 결과로 세지 않고 새로 돌렸다(판정 기준은 텍스트 증거).
- 그룹 시간: 깨끗한 계열 C(열아홉 그룹)에서 가장 긴 그룹은 REST 385.6–390.0초였고 제한은 480초다. 다른 작업의 전체 실행과 겹친 B1에서는 REST가 478.5초까지 갔다. M29 시험이 더 늘면 그룹 시간을 다시 봐야 한다(§11.2: 넘으면 그룹 추가).

## 6. 검증

`t2-flaky-tests.txt`에 각 회의 명령, 그룹별 passed/failed/errors/skipped/시간, 실패 시험 id, 부하 표본, 전체 출력 파일의 크기·SHA-256을 적었다. Stop 훅 그룹은 T5 병합(`2da787e9`) 전 열여덟, 뒤 열아홉이며 각 회는 그 소스의 훅 그룹 전부를 돌렸다.

- 계열 A(`ea608e33`): 1·2회 통과, 3회 실패(2.3의 신호 순서 경합) → `0218cfa5`로 고치고 세기를 새로 시작.
- 계열 B: 첫 시도는 주석 정정(`0a9a602a`) 커밋을 위해 3분 만에 멈춤(세지 않음). B1 통과·B2 실패 모두 다른 작업(T5 worktree)의 전체 그룹 실행과 조율 세션 Stop 훅이 겹친 회라 조율 세션 지시대로 세지 않았다(B2는 부하 평균 62–91, 그룹 18개 중 16개가 480초 제한). 그 사이 조율 세션이 2.4 사례를 넘겨 `cddc638a`로 고쳤다.
- 계열 C(`cddc638a`, 열아홉 그룹): 표본기가 30초마다 부하와 이 회 밖의 pytest 그룹 프로세스 수를 남기고, 그 수가 9 이상인 표본이 있으면 오염으로 보고 세지 않는다. 결과: C1·C2·C3 모두 통과(다시 돌리기 없음), 각 회 열아홉 그룹 모두 exit 0·제한 안·skip 0, 6,531개 통과, 가장 긴 그룹 385.6·388.0·390.0초, 1분 부하 평균 최대 29.8·33.6·33.0, 이 회 밖의 pytest 그룹 프로세스 최대 0·2·3(오염 없음). 고친 시험 셋(위 표의 파일 전부)은 이 열아홉 그룹 안에 모두 들어 있다. 판정 줄은 텍스트 증거의 "VERDICT" 절이다.
