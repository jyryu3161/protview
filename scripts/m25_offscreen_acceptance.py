#!/usr/bin/env python3
"""Run the M25 JEV design loop offscreen acceptance (.dryforge/spec.md section 12).

One command per phase, given a code root (default: this repository). Every phase checks the locked M17 RDKit, docking
and qvina environments, builds the frontend when needed (typecheck, then build, never concurrently), starts its own
loopback services (`next start` on 127.0.0.1:3000 and a backend on 127.0.0.1:8000 with PYTHONPATH=<code
root>/backend and MW_RUNS_DIR=<root>/runs; both live as long as this runner, every harness step is bounded by
STEP_TIMEOUT_S = 2 h), makes the two QA runs over the loopback API with
backend/tests/offscreen_jev_loop_fixture/qa_setup.py (run L: the receptor, the public-derived parent, the labelled
synthetic small blocks and real M17 jobs, 10 candidates; run P: real M20 sets of public 1UBQ (22) and 1MQ4 (3) and the
labelled synthetic phenol SDF), drives the real Electron offscreen flow frontend/tests/offscreen/jev-loop-flow.cjs and
assembles case-ledger.json.

Phases (``--phase``):
  fixture    (default) a fresh --root; the backend is backend/tests/offscreen_jev_loop_fixture/server.py (the real app,
             SCIENCE_GATE over a scripted httpx.MockTransport with a sentinel placeholder credential, the other gates
             refusing and reading no credential). Step jev-loop-fixture: every screen case of the spec (ligand and
             protein branches, scripts good, computed_alias, http_500, slow, no_usage, model_mismatch). Real calls 0,
             proven by the fixture server record: every dispatch event and response audit is one scripted transport
             call that carried the placeholder, and the stand-in product key resolver was never called.
  calibrate  a fresh --root; the product backend (uvicorn mw.api.app:app, the real SCIENCE_GATE) after the key is
             found present (boolean, the product resolver in a child process) and the root .env is private (0600,
             os.lstat only, never read here). The first plan entry: a ligand 탐색형 loop over a pool of 5 with pre-checks
             (no send) and ONE real send up to the iteration's JEV selection; body bytes, used tokens and cost against the
             reservation, and the response shape (answers, confidence, probabilities) are recorded with whether the
             reservation formula was enough. The formula is never changed here (a user decision). A stop (usage unknown,
             over the reservation, a send that did not complete, a failed flow) ends with no further call. Writes
             <root>/live-state.json.
  live       the same --root after a passed calibrate (once per root): the rest of the plan, at most --live-calls in
             total for the root: a ligand 활용형 loop of 3 iterations (one send each, real qvina docking), a protein
             활용형 loop of 3 iterations in the other run (one send each, real PDBFixer/OpenMM model and qvina docking into
             it), then the shuffle check (the calibrate pool and goal with another loop seed, its first iteration, one
             send): both sent orders and chosen list positions are recorded as observed values only.
  calibrate --finalize (--live-calls stays 0)
             rebuilds the evidence of a calibrate root whose real call finished but whose runner stopped before its
             evidence, from the stored files only (no build, service, Electron, POST or call; refused when anything does
             not match; --out absent or empty).
  --rehearse (calibrate, live, calibrate --finalize)
             the same phase code path against the fixture server instead of the product backend: same setup, plan,
             dispatch guard, event counting, ledger shape and evidence, with the ledger at <root>/rehearsal-live-
             ledger.json (never the repository ledger) and the fixture script good for every send. Real calls 0.

Counting and the ledger. The plan sends 8 times in total (calibrate 1 + live 7): run L 5, run P 3. The harness checks
every run's jev_science_dispatch_started events before each click (plan maxDispatch and maxPerRun), this runner counts
them while the harness runs and stops it and the backend at once when the count passes the limit. The repository
ledger runs/m25-live-ledger.json of the main checkout (git-ignored; the M24 ledger is never read) records every
calibrate/live root: before anything starts, a phase is refused when the ledger cannot be read, when its total (every
root, rescanned) plus this phase's planned calls passes 8, or when --live-calls passes what the ledger leaves; the phase
is recorded as started at once and its root's counts (failed sends included) when it ends. Nothing is retried and no new
run is opened to get more calls; a send that does not complete or a stopped egress ends the plan. Before the first
real call the plan's per-run needs (expensive units incl. the M17 setup, activity time by the step time limits,
external tokens and USD by the reservation of the widest measured body, sends) are checked against the run defaults
(8 units, 1800 s, 120,000 tokens, USD 2.00, 10 sends) and, once the runs exist, against their remaining budget.

Every phase ends with: no worker, fixture server, Electron, 8000/3000 listener left; a search of the evidence, the QA
root and the export for the API key and for the fixture placeholder (only booleans and file paths are printed); a
wording check of the evidence; the ledger with ``acceptance`` true only when every case of the phase passed, the
environment was present, nothing was left and the build was stamped from the current frontend source.
``--regressions`` (fixture phase only, with --kbase) afterwards runs the M24 (fixture phase), M23, M22, M21, M20, M19,
M18, M17, M16, M15, M14 and M13 (all phases) runners, each with its own fresh folders; none of them sends to JEV.

The root must be outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted environment
(no OPENROUTER_* or other secrets). This script never imports mw and never posts to a /jev/ or /jev_loops route
(consent, the loop, its sends and computations are the harness's real clicks).

Usage:
  .venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<label> \\
      [--out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-fixture] [--phase fixture|calibrate|live] [--live-calls N] \\
      [--rehearse] [--finalize] [--code-root <dir>] [--build auto|always|never] [--regressions --kbase <abs path>]
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, bookkeeping and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

# Backend start/stop, loopback API helpers and the M17 runner's protections (through the M18 Runner).
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "jev-loop-flow.cjs"
PHASES = ("fixture", "calibrate", "live")
PHASE_STEPS = {"fixture": ["jev-loop-fixture"], "calibrate": ["jev-loop-calibrate"], "live": ["jev-loop-live"]}
MODE_OF = {"jev-loop-fixture": "fixture", "jev-loop-calibrate": "calibrate", "jev-loop-live": "live"}
MAX_LIVE_CALLS = 8                 # the user's allocation of real JEV calls for M25 (2026-10-07)
LEDGER_NAME = "m25-live-ledger.json"
LEDGER_SCHEMA = "m25_live_ledger@1"
REHEARSAL_LEDGER_NAME = "rehearsal-live-ledger.json"
LEDGER_PHASES = ("calibrate", "live")
RUN_NAME = re.compile(r"run_[A-Za-z0-9_-]+")
STEP_TIMEOUT_S = 7200              # one harness step; the services live as long as this runner
FIXTURE_SERVER = Path("backend/tests/offscreen_jev_loop_fixture/server.py")
QA_SETUP = Path("backend/tests/offscreen_jev_loop_fixture/qa_setup.py")
# The fixture server's placeholder credential: searched for in the evidence (it must never be written anywhere).
SENTINEL = "m25-loop-fixture-sentinel-placeholder-not-a-key"
ENVIRONMENTS = {"workerPython": Path(".deps/prolif/venv-locked/bin/python"),
                "dockingPython": Path(".deps/docking/venv-locked/bin/python"),
                "qvina": Path(".deps/qvina/env/bin/qvina2")}
CAPABILITIES = {"ligandAvailable": "ligand_candidates", "mutationAvailable": "mutation_candidates",
                "dockingAvailable": "ligand_docking", "modelAvailable": "mutation_model", "jevAvailable": "jev_choice"}
# The real-call plan (spec 12): 8 sends; calibrate = the first entry, live = the rest. Pools index the setup file:
# run L's ligand set ids (generation order) and run P's 1UBQ candidate indices (L15A, I30A, I44A, I61A, L69A).
LIVE_PLAN = [
    {"id": "L-explore-calibrate", "run": "L", "branch": "ligand", "goal": "explore", "loopSeed": 101, "cap": 1,
     "pool": [0, 1, 2, 3, 4], "rounds": 1, "sends": 1, "compute": False, "report": True},
    {"id": "L-exploit-3", "run": "L", "branch": "ligand", "goal": "exploit", "loopSeed": 202, "cap": 3,
     "pool": [5, 6, 7, 8, 9], "rounds": 3, "sends": 3, "compute": True, "report": True},
    {"id": "P-exploit-3", "run": "P", "branch": "protein", "goal": "exploit", "loopSeed": 303, "cap": 3,
     "pool": [4, 10, 14, 19, 21], "rounds": 3, "sends": 3, "compute": True, "report": True},
    {"id": "L-explore-shuffle", "run": "L", "branch": "ligand", "goal": "explore", "loopSeed": 404, "cap": 1,
     "pool": [0, 1, 2, 3, 4], "rounds": 1, "sends": 1, "compute": False, "report": False,
     "compareWith": "L-explore-calibrate"},
]
# Run defaults (an M25 run never raises a limit) and the plan's cost model per branch (spec 6.1, 7; M24 reservation).
RUN_BUDGET = {"expensive_units": 8, "wall_clock_s": 1800, "external_tokens": 120_000, "usd": 2.0, "sends": 10}
SETUP_COST = {"L": {"expensive_units": 2, "wall_clock_s": 240}, "P": {"expensive_units": 0, "wall_clock_s": 0}}
STEP_COST = {"ligand": {"expensive_units": 1, "wall_clock_s": 300}, "protein": {"expensive_units": 2, "wall_clock_s": 420}}
# Widest bodies measured in T1 (20 candidates): ligand 11,362 B, 1UBQ mutation 27,448 B; rounded up.
RESERVE_BOUND_BYTES = {"ligand": 12_288, "protein": 32_768}
RESERVE_TOKEN_CAP, RESERVE_TOKEN_BASE, RESERVE_USD = 50_000, 4_096, 0.10
RESERVATION_FORMULA = "min(50000, 4096 + ceil(body_bytes × 2 / 3)) external tokens and USD 0.10 per send"
FIXTURE_CASES = [
    "L-tab-entry", "L-create-fields", "L-create", "L-loop-active", "L-consent-off-block", "L-preview-match",
    "L-order-oracle", "L-consent-toggle", "L-confirm-required", "L-failed-model", "L-ordinal-refused", "L-bytes-equal",
    "L-send-good", "L-choice-card", "L-compute-jev", "L-real-engine", "L-failed-computed-alias", "L-late", "L-designate",
    "L-designate-no-send", "L-candidate-table", "L-end-summary", "L-report", "L-reuse", "L-no-usage-stop",
    "L-send-cap-display", "L-knowledge-rows", "L-other-tabs", "P-tab-entry", "P-pool-limit", "P-create-fields",
    "P-create-refused", "P-create", "P-send-good", "P-bytes-equal", "P-order-oracle", "P-first-approval",
    "P-end-refused-job", "P-end-refused-docking", "P-dock", "P-real-engine", "P-abandon", "P-end-summary", "P-report",
    "P-reuse", "P-failed-http", "P-pair-loop", "P-knowledge-rows", "P-other-tabs", "X-fixture-proof", "X-wording",
    "X-no-egress-browser"]
# Ledger case → the harness row case it reads.
ROW_CASE = {"JL-calibrate-send": "JL-calibrate", "JL-live-sends": "JL-live"}
CASE_TEXT = {
    "L-tab-entry": "리간드 탭 진입: GET 읽기만, 동의 꺼짐, UL1·UL3, 루프 없음, 집합·목표 자동 선택 없음, seed 비어 있음, 반복 상한 5",
    "L-create-fields": "만들기 칸별 이유: 풀 1개(pool_invalid)·목표 없음(goal_invalid)·seed 비어 있음(seed_invalid)·반복 상한 "
                       "9(iteration_cap_invalid)·계산 조건, 만들기 단추 닫힘",
    "L-create": "루프 만들기: jev_loop_created 하나, 바퀴 1 선택 대기, 요청 = 화면 입력",
    "L-loop-active": "같은 갈래의 끝나지 않은 루프가 있으면 만들기가 loop_active 이유와 함께 닫힘",
    "L-consent-off-block": "동의 꺼짐: 미리보기 consent_off, 확인 체크를 해도 전송 단추 닫힘",
    "L-preview-match": "미리보기 <pre> = 서버 문자열, 여기서 계산한 SHA-256·바이트 = 표시 = 저장 투영",
    "L-order-oracle": "후보 순서·별칭·criteria·computed 행 = 독립 sha256_order_v1 계산, 질문 = 명세 4.5 문장",
    "L-consent-toggle": "동의 켬: 차단 이유 없음, 전역 줄 run id 바로 뒤 \"과학 전송 허용\"",
    "L-confirm-required": "확인 체크 없이는 전송 단추가 닫히고 이유가 보임; 체크하면 열림",
    "L-failed-model": "fixture model_mismatch: failed model_mismatch, 이유만",
    "L-ordinal-refused": "dispatch 뒤 같은 투영은 ordinal_mismatch로 막히고 다시 만들면 새 순서",
    "L-bytes-equal": "전송마다 transport 수신 바이트 SHA-256 = 미리보기 = 감사 prepared(본문 같음)",
    "L-send-good": "fixture good(첫 criteria 키): completed, 이 바퀴의 선택",
    "L-choice-card": "JEV 판정(모델 선택) 카드 = 저장 제안: 목록 위치 n/m, 확신도, 모델, 사용량, 접힌 후보별 값은 보낸 순서 그대로, "
                     "정렬·막대·색 비교 요소 없음",
    "L-compute-jev": "이 선택으로 계산 시작: decided_by jev 승인 하나, 단독 M18 작업",
    "L-real-engine": "실제 qvina 도킹, 점수 = 저장 결과 첫 모드(소수 첫째 자리 표시)",
    "L-failed-computed-alias": "fixture computed_alias: 게이트에서 response_invalid, 이유만",
    "L-late": "fixture slow 중 동의 끄기: completed + 늦은 응답, 이 바퀴의 선택이 아님, J7",
    "L-designate": "직접 지정(늦은 응답이 고른 후보): decided_by human, 실제 도킹",
    "L-designate-no-send": "전송 없는 바퀴의 직접 지정, 유효 반복 상한 도달(iteration_cap)",
    "L-candidate-table": "후보 표: 점수 = 저장값, 점수 없는 행은 어떤 정렬·방향에서도 끝(풀 순서), aria-sort, 순번 열·강조 없음",
    "L-end-summary": "루프 끝내기: iteration_cap, 요약 jev_loop_result@1 = 기록, LJ8",
    "L-report": "보고서 만들기: 목록의 \"JEV 루프 보고서\"와 저장된 Markdown(고정 문장, 확률 없음)",
    "L-reuse": "저장된 같은 조건 결과는 계산됨(저장된 결과 재사용, 단위 0)",
    "L-no-usage-stop": "fixture no_usage: completed, 사용량 \"알 수 없음\", 외부 전송 멈춤(usage_unknown), 다음 루프 미리보기 "
                       "egress_stopped",
    "L-send-cap-display": "run 전송 상한 줄 = dispatch 수(10회 중 5회)",
    "L-knowledge-rows": "지식·보고서 전송 기록: 루프 전송은 읽기 전용 \"JEV 루프\" 행, 열기·보고서 만들기 단추 없음",
    "L-other-tabs": "다른 영역의 숫자를 가린 글자가 같음(M18 도킹 영역은 루프의 단독 결과를 목록에 보임), 진입 POST 없음, 구조 분석 숨김",
    "P-tab-entry": "단백질 탭 진입: GET 읽기만, UL1·UL3·U3, 두 집합 모두 고르지 않음",
    "P-pool-limit": "20개 체크 뒤 21번째 거절(이유 표시), 1개로 줄이면 최소 2(pool_invalid)",
    "P-create-fields": "단백질 칸별 이유: 목표·seed·반복 상한 0·확인 두 항목(confirmation_missing)·cutoff 7(argument_invalid)",
    "P-create-refused": "1MQ4 풀: 서버 422 setup_invalid(openmm_preflight_failed)가 계산 조건 칸에, 이벤트 없음",
    "P-create": "1UBQ 풀 3개로 루프 만들기, loop_active",
    "P-send-good": "변이 본문(좌표·서열·handle 없음) 전송, 카드의 잔기 표기와 목록 위치",
    "P-bytes-equal": "단백질 전송 바이트 = 미리보기 = 감사 prepared = transport",
    "P-order-oracle": "단백질 순서·별칭·criteria = 독립 계산",
    "P-first-approval": "첫 비싼 계산 승인 안내 → 비싼 계산 승인(POST /jobs/approve) → 작업 시작(새 승인 이벤트 없음)",
    "P-end-refused-job": "작업 대기 중 루프 끝내기 닫힘(job_running)",
    "P-end-refused-docking": "도킹 대기 중 루프 끝내기 닫힘(docking_pending)",
    "P-dock": "변이 구조에 도킹: 점수 = 저장 결과 첫 모드, 수용체 = 그 모델의 변이형",
    "P-real-engine": "실제 PDBFixer·OpenMM 모델링과 qvina 도킹",
    "P-abandon": "도킹 포기: not_run(docking_not_run), 유효 반복 상한 도달",
    "P-end-summary": "루프 끝내기: iteration_cap, 요약, LJ8",
    "P-report": "단백질 루프 보고서 저장과 목록",
    "P-reuse": "모델·변이형 도킹이 저장된 후보는 재사용(단위 0), 활용형 computed 행은 저장 점수 그대로",
    "P-failed-http": "fixture HTTP 500: failed provider_http_error, 이유만, 외부 전송 멈춤",
    "P-pair-loop": "M21 같은 조건 짝 표: \"루프 도킹(야생형 없음) · 바퀴 1\"(loop 키), 야생형 쪽 점수 없음",
    "P-knowledge-rows": "지식·보고서: run P의 루프 전송 두 줄이 읽기 전용 행",
    "P-other-tabs": "run P의 다른 영역 불변(M21 영역·M18 도킹 영역은 루프 결과 목록), 구조 분석 숨김",
    "X-fixture-proof": "흐름 안 확인: fixture transport 호출 = dispatch 이벤트 = 바이트 대조 행, placeholder만, 제품 키 해석기 0회",
    "X-wording": "화면 문구 검사(고정 문장·지시문·본문 줄 제외) 모든 시점 통과",
    "X-no-egress-browser": "브라우저의 비-loopback 요청 0건",
    "JL-calibrate-send": "첫 실호출 전 전송 없는 사전 확인(동의 끔 → consent_off·전송 닫힘 → 켬, 확인 체크 해제 → 닫힘) 뒤 리간드 "
                         "탐색형 루프의 전송 한 번: 결과 카드(또는 이유만)·예약 대비 사용량·응답 모양, 루프 끝내기·보고서, 다른 탭 불변",
    "JL-live-sends": "나머지 계획: 리간드 활용형 3바퀴(바퀴마다 전송 1회와 실제 qvina), 단백질 활용형 3바퀴(다른 run, 실제 모델링·"
                     "도킹), 섞기 확인 1회(같은 풀·목표, 다른 루프 seed): 결과 카드·계산·요약·보고서, 다른 탭 불변",
}
RUNNER_CASE_TEXT = {
    "S-browser-egress-zero": "모든 흐름 행의 브라우저 비-loopback 요청 0건",
    "S-real-calls-zero": "실호출 0회: 서버 기록이 MockTransport 게이트이고 이 단계의 dispatch·response_received 감사 수가 fixture "
                         "transport 호출 기록과 같으며 모든 호출의 인증 값이 placeholder였고 제품 키 해석기 호출 0회",
    "S-key-absent": "증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건",
    "S-wording-evidence": "증거 텍스트에 금지 표현 0건(고정 문장·지시문·보낸 본문 줄 제외)",
    "JL-count": "실호출 계수: 모든 QA run의 dispatch 이벤트와 response_received 감사가 --live-calls 이하, run마다 계획 상한 이하",
    "JL-calibration": "첫 실호출: completed, 사용량(입력·출력 토큰·비용)을 알고 예약값 이하, 외부 전송 멈춤 없음, calibrate 흐름 통과",
    "JL-ledger": "실호출 대장(Git 제외 runs/m25-live-ledger.json, 모든 root의 dispatch 이벤트로 확정, 실패한 전송 포함): 단계 뒤 "
                 "합계 8회 이하. 시작 전 대장 합계 + 이번 계획이 8을 넘거나 --live-calls가 남은 양을 넘거나 대장을 읽을 수 없으면 거절",
    "JL-budget": "계획의 run별 필요량(비싼 계산 단위·활동 시간·외부 토큰·USD·전송 수)이 run 기본 한도와 남은 예산 안",
    "JL-shuffle-observed": "섞기 확인: 같은 풀·목표·다른 루프 seed의 두 첫 전송의 순서와 고른 목록 위치를 관찰값으로만 기록",
}
NOT_OBSERVED_LIVE = ("관찰하지 않음 — 실호출은 T12의 calibrate·live 단계에서만 한다. 이 실행은 가짜 transport fixture 서버만 "
                     "썼다(실호출 0회).")
NOT_OBSERVED_COMMON = {
    "L-late-run-cancelled": "run 취소 뒤 도착한 루프 응답: 화면에 run 취소 경로가 없다. backend/tests/test_jev_loop_sends.py::"
                            "test_a_late_reply_is_kept_but_never_the_selection 이 덮는다.",
    "L-unavailable-before-start": "시작 전 취소된 후보(unavailable): backend/tests/test_jev_loops_compute.py::"
                                  "test_two_presses_make_one_step_and_a_job_cancelled_before_start_is_unavailable 이 덮는다.",
    "L-budget-blocked": "계산 예산 부족(budget_blocked)과 budget_exhausted 끝내기: 화면 run은 한도를 늘리거나 줄이지 않는다. "
                        "test_jev_loops_compute.py::test_budget_blocked_names_each_short_axis_and_charges_nothing, "
                        "test_a_loop_short_of_compute_budget_ends_budget_exhausted_with_its_unfinished_iteration 이 덮는다.",
    "L-end-server-refusal": "끝내기 서버 거절(job_running·docking_pending): 화면은 단추를 닫아 요청을 보내지 않는다. "
                            "test_jev_loops_compute.py::test_end_refusals_follow_the_spec_order_and_write_nothing 이 덮는다.",
    "L-send-cap-ten": "run당 10회 전송 소진: 한 run의 fixture 계획이 5회에서 외부 전송 멈춤으로 끝난다. test_jev_loop_sends.py::"
                      "test_the_ten_send_cap_and_the_budget_are_shared_with_m24_sends 가 덮는다.",
    "L-dry-run": "연습용 run: test_jev_loop_sends.py::"
                 "test_a_loop_projection_in_a_dry_run_run_names_no_loop_and_never_reads_the_key 가 덮는다.",
}
WORKERS = (*m13.WORKERS, "ligand_worker.py", "docking_worker.py", "openmm_mutation_worker.py", "qvina2",
           "offscreen_jev_loop_fixture/server.py")
REGRESSIONS = [("m24", []), ("m23", []), ("m22", []), ("m21", []), ("m20", ["kbase"]), ("m19", []), ("m18", []),
               ("m17", []), ("m16", ["kbase"]), ("m15", ["kbase"]), ("m14", []),
               ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]
# Fixed sentences LJ1-LJ8, UL1-UL3, the M24 U3 and J7 (spec 9.3, verbatim) and the four instructions (spec 4.5):
# exempt from the wording check, as in the harness.
FIXED_SENTENCES = (
    ("JEV 루프는 사람이 바퀴마다 보낼 내용과 계산 시작을 승인하며, JEV 판정은 외부 모델이 계산 대기열에 먼저 둘 후보로 고른 하나일 뿐 "
    "계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니고 고른 이유는 알 수 없다."),
    ("점수는 저장된 qvina 도킹 결과의 첫 모드 값(kcal/mol, Vina 계열 스코어링 함수 값, 친화도가 아님)이며, 점수 없음은 0이 아니다. "
    "바퀴 순서·표 정렬·선택 표시는 순위나 개선이 아니다."),
    ("후보 순서와 별칭은 전송마다 기록된 seed로 섞은 것이며 의미가 없다. 모델 선택은 목록 위치의 영향을 받을 수 있어 고른 위치를 값으로 "
    "기록했고, 이 기록은 효과를 뜻하지 않는다."),
    "활용형은 점수가 낮게 나온 후보와 구조가 비슷한 후보를 고르게 하는 질문이며 점수 예측이 아니고 후보를 줄 세우지 않는다.",
    "탐색형은 이미 계산한 후보와 가장 다른 후보를 고르게 하는 질문이며 점수를 보내지 않았다.",
    ("후보는 2D 그래프이고 점수는 사용자가 정한 수용체·상자에서 자유 도킹한 qvina 값이며 결합·활성·합성 가능성이 아니다. JEV에는 "
    "수용체 정보를 보내지 않았다."),
    ("점수는 후보마다 다른 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 모델)에 "
    "사용자 리간드를 자유 도킹한 값이라 같은 수용체 안의 비교가 아니며 변이의 효과나 친화도가 아니다. 야생형 기준은 계산하지 않았다."),
    "이 루프는 계산하지 않은 후보를 남기고 끝났으며 계산하지 않은 후보는 점수가 없다(0이 아니다).",
    "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다.",
    "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다.",
    ("루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 '사용량 모름' 중지 "
    "상태를 쓴다."),
    "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
    "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
)
_C = ("Choose exactly one candidate from the candidates listed in the criteria to place first in a local computation "
      "queue. This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, "
      "synthesizability, safety or the effect of a substitution. ")
_O = "The order of the candidate list and the alias numbers were shuffled for this request and carry no meaning."
_E = "The computed field lists the aliases of the candidates that have already been computed. "
_S = ("Computed candidates are listed with their stored qvina score (Vina-family scoring function value in kcal/mol, not "
      "an affinity); a candidate without a score is listed without one, which is not zero. ")
_RDK = "Property values are RDKit estimates, not measurements or interactions. "
_GEO = "Distances and neighbor lists are geometry from stored coordinates, not measurements or interactions. "
_NC = "Each score belongs to the modelled structure of its own mutation, so scores are not like-for-like comparisons. "
INSTRUCTIONS = (
    _C + "Prefer the candidate whose structure (SMILES) is most different from all the computed candidates; if no "
    "candidate is computed, choose any one. " + _E + _RDK + _O,
    _C + "Prefer the candidate whose structure (SMILES) is most similar to the one computed candidate with the lowest "
    "listed score; if no candidate has a listed score, choose any one. This is a judgment of structural similarity only, "
    "not a prediction of any score. " + _S + _RDK + _O,
    _C + "Prefer the candidate whose position and substitution (from, to) are most different from all the computed "
    "candidates; if no candidate is computed, choose any one. " + _E + _GEO + _O,
    _C + "Prefer the candidate whose position and substitution (from, to) are most similar to the one computed candidate "
    "with the lowest listed score; if no candidate has a listed score, choose any one. This is a judgment of similarity "
    "of position and substitution only, not a prediction of any score or of the effect of a mutation. " + _S + _NC
    + _GEO + _O,
)
SCORE_NAMES = ("qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)", "qvina 점수(kcal/mol)")
# The harness rule (frontend/tests/offscreen/jev-loop-flow.cjs FORBIDDEN): spec 2 and 8.3, plus effect claims about the
# recorded list positions. re.ASCII gives \b its JavaScript (non-unicode) meaning; the unit test compares the two.
FORBIDDEN = re.compile(r"순위|추천|최고|최저|최적(?!화)|최솟값|최댓값|개선|예측|유망|좋은|나쁜|좋아짐|승자|평균|차이|증감|친화|안정성|ΔΔG|"
                       r"(?<!비)활성|가장\s*높|가장\s*낮|\bbest|\brank|recommend|improv|winner|highest|lowest|효과|편향|"
                       r"\beffects?\b|\bbias(?:es|ed)?\b", re.IGNORECASE | re.ASCII)
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt", ".html"}
# Reads the key with the product resolver in a child process and prints only booleans, a file count and the paths of
# files holding the key or the placeholder (never the key itself).
KEY_SCAN = r"""
import json, sys
from pathlib import Path
from mw.egress.gate import env_or_root_dotenv_key
key = env_or_root_dotenv_key()
needles = {"key": key.encode() if isinstance(key, str) and key else None, "sentinel": sys.argv[1].encode()}
del key
hits = {"key": [], "sentinel": []}
files = 0
for root in sys.argv[2:]:
    base = Path(root)
    if not base.exists():
        continue
    for path in sorted(item for item in base.rglob("*") if item.is_file() and not item.is_symlink()):
        files += 1
        data = path.read_bytes()
        for name, needle in needles.items():
            if needle and needle in data:
                hits[name].append(str(path))
print(json.dumps({"keyAvailable": needles["key"] is not None, "files": files, "hits": hits}))
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def live_calls_arg(text: str) -> int:
    """--live-calls: an integer 0..8 (the user's allocation of real JEV calls); anything else is refused."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--live-calls must be an integer 0..{MAX_LIVE_CALLS}") from exc
    if not 0 <= value <= MAX_LIVE_CALLS:
        raise argparse.ArgumentTypeError(f"--live-calls must be 0..{MAX_LIVE_CALLS} (got {value}); the allocation is "
                                         f"{MAX_LIVE_CALLS} real calls in total")
    return value


def count_events(runs_dir: Path) -> dict[str, dict[str, int]]:
    """Per run of the runs folder: jev_science_dispatch_started events, egress `response_received` audits (all
    scopes) and those of the science scope (read-only file reads)."""
    counts: dict[str, dict[str, int]] = {}
    for log in sorted(Path(runs_dir).glob("run_*/events.jsonl")):
        found = {"dispatch": 0, "responseReceived": 0, "scienceResponses": 0}
        with log.open() as lines:
            for line in lines:
                if "jev_science_dispatch_started" not in line and "response_received" not in line:
                    continue
                event = json.loads(line)
                if event.get("type") == "jev_science_dispatch_started":
                    found["dispatch"] += 1
                elif event.get("type") == "egress" and event.get("stage") == "response_received":
                    found["responseReceived"] += 1
                    found["scienceResponses"] += event.get("scope") == "science"
        counts[log.parent.name] = found
    return counts


def dispatch_total(counts: dict[str, dict[str, int]]) -> int:
    return sum(item["dispatch"] for item in counts.values())


def live_count_ok(counts: dict[str, dict[str, int]], live_calls: int, per_run: dict[str, int] | int) -> bool:
    """Dispatch events and response audits of every QA run within --live-calls, and each run within its plan bound
    (``per_run``: {run id: bound}, an absent run 0; or one bound for every run)."""
    def bound(run: str) -> int:
        return per_run if isinstance(per_run, int) else per_run.get(run, 0)
    return (dispatch_total(counts) <= live_calls
            and sum(item["responseReceived"] for item in counts.values()) <= live_calls
            and all(item["dispatch"] <= bound(run) for run, item in counts.items()))


def watch_process(proc: subprocess.Popen, runs_dir: Path, limit: int | None, timeout_s: float,
                  poll_s: float = 0.5) -> tuple[int, dict | None]:
    """Wait for ``proc``; while it runs, count the dispatch events of every run and, once they pass ``limit``, kill its
    process group at once. Returns (exit code, the counts that passed the limit or None); -9 on timeout."""
    deadline = time.monotonic() + timeout_s
    while proc.poll() is None:
        if limit is not None:
            counts = count_events(runs_dir)
            if dispatch_total(counts) > limit:
                kill_group(proc)
                return -15, counts
        if time.monotonic() > deadline:
            kill_group(proc)
            return -9, None
        time.sleep(poll_s)
    if limit is not None:
        counts = count_events(runs_dir)
        if dispatch_total(counts) > limit:
            return proc.returncode, counts
    return proc.returncode, None


def kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def plan_sends(entries: list[dict]) -> int:
    return sum(entry["sends"] for entry in entries)


def per_run_sends(entries: list[dict] = LIVE_PLAN) -> dict[str, int]:
    """Sends per setup run (L, P) over ``entries`` (the whole plan by default: the bound of each run in both phases)."""
    out: dict[str, int] = {}
    for entry in entries:
        out[entry["run"]] = out.get(entry["run"], 0) + entry["sends"]
    return out


def plan_for(phase: str, used: int, live_calls: int) -> dict:
    """The harness plan of a phase (setup-run keys; the runner maps them to run ids). ``used`` = dispatch events already
    in the root, ``live_calls`` = --live-calls. calibrate = the first entry after the pre-checks; live = the next entries
    in order while ``used`` + their sends stays within ``live_calls`` (an entry is never cut)."""
    if phase == "calibrate":
        entries = LIVE_PLAN[:1]
        return {"entries": entries, "maxDispatch": used + plan_sends(entries), "maxPerRun": per_run_sends(),
                "preChecks": True}
    entries, total = [], used
    for entry in LIVE_PLAN[1:]:
        if total + entry["sends"] > live_calls:
            break
        entries.append(entry)
        total += entry["sends"]
    return {"entries": entries, "maxDispatch": live_calls, "maxPerRun": per_run_sends()}


def reserve_tokens(body_bytes: int) -> int:
    """The M24 external-token reservation of one send (spec 5.1)."""
    return min(RESERVE_TOKEN_CAP, RESERVE_TOKEN_BASE + math.ceil(body_bytes * 2 / 3))


def plan_budget(entries: list[dict] = LIVE_PLAN) -> dict:
    """Per setup run, the needs of ``entries`` (plus the run's setup) against the run defaults: expensive units, activity
    time by the step time limits, external tokens and USD by the reservation of the widest measured body, sends."""
    runs: dict[str, dict] = {}
    for entry in entries:
        need = runs.setdefault(entry["run"], {**{axis: 0 for axis in RUN_BUDGET}, **SETUP_COST[entry["run"]]})
        if entry["compute"]:
            for axis in ("expensive_units", "wall_clock_s"):
                need[axis] += entry["rounds"] * STEP_COST[entry["branch"]][axis]
        need["external_tokens"] += entry["sends"] * reserve_tokens(RESERVE_BOUND_BYTES[entry["branch"]])
        need["usd"] = round(need["usd"] + entry["sends"] * RESERVE_USD, 6)
        need["sends"] += entry["sends"]
    short = {run: [axis for axis, value in need.items() if value > RUN_BUDGET[axis]] for run, need in runs.items()}
    return {"ok": not any(short.values()), "needs": runs, "limits": dict(RUN_BUDGET), "short": short}


def remaining_ok(needs: dict, budget: dict, status: dict) -> list[str]:
    """The axes a run's remaining budget (GET /runs/{id}/budget and /jev/status) is short of ``needs`` (live slice)."""
    left = {"expensive_units": budget["expensive_calls"]["limit"] - budget["expensive_calls"]["used"],
            "wall_clock_s": budget["wall_clock_s"]["limit"] - budget["wall_clock_s"]["used"],
            "external_tokens": budget["external_tokens"]["limit"] - budget["external_tokens"]["used"],
            "usd": budget["usd"]["limit"] - budget["usd"]["used"], "sends": status.get("remaining", 0)}
    return [axis for axis in RUN_BUDGET if needs.get(axis, 0) > left[axis]]


def forbidden_in(text: str) -> list[str]:
    """Forbidden expressions in ``text``, line by line; a line exactly equal to a fixed sentence or an instruction is
    exempt; the exact qvina score names are removed first."""
    found: list[str] = []
    for line in str(text).split("\n"):
        if line in FIXED_SENTENCES or line in INSTRUCTIONS:
            continue
        for name in SCORE_NAMES:
            line = line.replace(name, "")
        found += FORBIDDEN.findall(line)
    return found


def json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in json_strings(item)]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (key, *json_strings(item))]
    return []


def sent_body(text: str) -> bool:
    """A line that is a JEV request body (the exact outgoing string, checked byte for byte by the harness)."""
    return text.startswith('{"model":')


def scan_wording(folder: Path) -> dict[str, list[str]]:
    """Forbidden expressions in the text evidence of ``folder`` (JSON strings one by one; other text line by line). Not
    scanned: the browser profile, the service logs and the *.dom.txt screen texts (a whole tab as shown: its other
    areas follow their own milestone's rule and the loop area's text is checked by the harness at every step)."""
    found: dict[str, list[str]] = {}
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder)
        if (not path.is_file() or path.suffix not in TEXT_SUFFIXES or "browser-profile" in rel.parts
                or rel.parts[0] == "services" or path.name.endswith(".dom.txt")):
            continue
        text = path.read_text(errors="replace")
        if path.suffix == ".html":         # a panel dump: one line per element, as the screen shows it
            text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
        texts: list[str] = []
        if path.suffix in (".json", ".jsonl"):
            for chunk in ([text] if path.suffix == ".json" else text.splitlines()):
                try:
                    texts += json_strings(json.loads(chunk))
                except ValueError:
                    texts.append(chunk)
        else:
            texts.append(text)
        hits = [word for item in texts for line in item.split("\n") if not sent_body(line)
                for word in forbidden_in(line)]
        if hits:
            found[str(rel)] = sorted(set(hits))
    return found


def files_containing(roots: list[Path], needles: list[bytes]) -> list[str]:
    """Files under ``roots`` holding any of ``needles`` (the pure core of the evidence search)."""
    hits = []
    for root in roots:
        if not Path(root).exists():
            continue
        for path in sorted(item for item in Path(root).rglob("*") if item.is_file() and not item.is_symlink()):
            data = path.read_bytes()
            if any(needle and needle in data for needle in needles):
                hits.append(str(path))
    return hits


def dotenv_status(code: Path) -> dict:
    """The root .env of ``code``: present and private (no group/other permission bits) from os.lstat only; its content
    is never opened or read here."""
    path = Path(code) / ".env"
    try:
        info = path.lstat()
    except OSError:
        return {"present": False, "private": False, "mode": None}
    regular = stat.S_ISREG(info.st_mode)
    return {"present": regular, "private": regular and not info.st_mode & 0o077, "mode": oct(info.st_mode & 0o777)}


def fixture_proof(server: dict | None, calls: list[dict], dispatched: int, responses: int, reads: dict | None) -> dict:
    """Real calls 0 in this phase: the backend was the fixture server (MockTransport gates), every dispatch event and
    every response audit of the phase is one scripted transport call that carried the placeholder, the science gate
    read only the placeholder (as often as it dispatched) and the stand-in product key resolver was never called."""
    answered = sum(1 for call in calls if call.get("status") is not None)
    ok = (isinstance(server, dict) and server.get("fixture") is True and server.get("schema") ==
          "m25_jev_loop_fixture_server@1" and all("MockTransport" in str(server.get(gate))
                                                  for gate in ("scienceGate", "viewerGate", "defaultGate"))
          and dispatched == len(calls) and responses == answered and len(calls) > 0
          and all(call.get("authorizationIsSentinel") is True for call in calls)
          and isinstance(reads, dict) and reads.get("productResolverReads") == 0
          and reads.get("sentinelReads") == dispatched)
    return {"ok": ok, "dispatchEvents": dispatched, "fixtureTransportCalls": len(calls), "responseAudits": responses,
            "answeredCalls": answered, "credentialReads": reads, "realProviderCalls": 0 if ok else None}


def calibration(row: dict | None) -> dict:
    """The first real send: completed, usage known and within the reservation, no egress stop, and the calibrate flow
    around it passed. Also recorded: the body bytes per input token, the reserved/used ratio, the response shape and
    whether the reservation formula was enough (an adjustment is the user's decision; never made here)."""
    sends = [item for item in ((row or {}).get("sends") or []) if item.get("sendId")]
    if not sends:
        return {"ok": False, "reason": "no send recorded"}
    send = sends[0]
    usage = send.get("usage") or {}
    reservation = send.get("reservation") or {}
    known = all(isinstance(usage.get(key), (int, float)) for key in ("input_tokens", "output_tokens",
                                                                     "external_tokens", "cost"))
    within = (known and usage["external_tokens"] <= reservation.get("external_tokens", -1)
              and usage["cost"] <= reservation.get("usd", -1))
    flow = (row or {}).get("status") == "pass"
    ok = flow and send.get("status") == "completed" and within and send.get("egressStop") is None
    out = {"ok": ok, "flowPassed": flow, "entry": send.get("entry"), "status": send.get("status"),
           "reasonCode": send.get("reasonCode"), "servedModel": send.get("servedModel"),
           "bodyBytes": send.get("bodyBytes"), "aliases": send.get("aliases"), "usage": usage or None,
           "reservation": reservation or None, "egressStop": send.get("egressStop"),
           "responseShape": send.get("responseShape"), "reservationFormula": RESERVATION_FORMULA,
           "withinReservation": within if known else None, "adjustmentSuggested": (not within) if known else None,
           "adjustmentNote": "예약식 조정은 사용자 결정이며 실행기는 자동으로 바꾸지 않는다"}
    if known and usage["input_tokens"]:
        out["bodyBytesPerInputToken"] = send.get("bodyBytes", 0) / usage["input_tokens"]
    if known and usage["external_tokens"]:
        out["reservedTokensOverUsed"] = reservation.get("external_tokens", 0) / usage["external_tokens"]
    return out


def shuffle_observed(row: dict | None) -> bool:
    """The live row recorded the shuffle observation: two first sends of loops with the same pool and goal and other
    loop seeds, both orders over the same candidates (values only)."""
    found = (row or {}).get("shuffle") or {}
    first, second = found.get("first") or {}, found.get("second") or {}
    return (bool(first.get("order")) and bool(second.get("order")) and first.get("loopSeed") != second.get("loopSeed")
            and sorted(map(str, first["order"])) == sorted(map(str, second["order"])))


class LedgerError(Exception):
    """The real-call ledger cannot be found, read, trusted or counted: every real-call phase is refused."""


def ledger_path(code: Path = REPO) -> Path:
    """``runs/m25-live-ledger.json`` of the main checkout (found through the common git directory, so a worktree
    shares it); it must be a git-ignored place. Raises LedgerError otherwise. The M24 ledger is never read."""
    done = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=code,
                          capture_output=True, text=True, check=False)
    if done.returncode != 0 or not done.stdout.strip():
        raise LedgerError(f"no git repository at {code}")
    main = Path(done.stdout.strip()).resolve().parent
    path = main / "runs" / LEDGER_NAME
    if subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=main, check=False).returncode != 0:
        raise LedgerError(f"the ledger place is not git-ignored: {path}")
    return path


def read_ledger(path: Path) -> dict:
    """The ledger (absent = nothing recorded yet). Unreadable, not JSON or not exactly the ledger shape: LedgerError."""
    if not Path(path).exists():
        return {"schema": LEDGER_SCHEMA, "roots": {}}
    try:
        ledger = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise LedgerError(f"the ledger cannot be read ({exc.__class__.__name__})") from exc
    if not (isinstance(ledger, dict) and set(ledger) == {"schema", "roots"} and ledger["schema"] == LEDGER_SCHEMA
            and isinstance(ledger["roots"], dict)):
        raise LedgerError("the ledger is damaged (not an m25_live_ledger@1 object)")
    for root, entry in ledger["roots"].items():
        ok = (Path(root).is_absolute() and isinstance(entry, dict) and set(entry) == {"phases", "dispatch"}
              and isinstance(entry["phases"], list) and isinstance(entry["dispatch"], dict)
              and all(isinstance(run, str) and RUN_NAME.fullmatch(run) and type(count) is int and count >= 0
                      for run, count in entry["dispatch"].items())
              and all(isinstance(item, dict) and item.get("phase") in LEDGER_PHASES
                      and isinstance(item.get("startedAt"), str)
                      and (item.get("finishedAt") is None or isinstance(item.get("finishedAt"), str))
                      for item in entry["phases"]))
        if not ok:
            raise LedgerError(f"the ledger is damaged (root {root!r})")
    return ledger


def root_count(root: str, entry: dict) -> int:
    """Real calls of one recorded root: per run, the larger of the recorded count and the jev_science_dispatch_started
    events now in the root's runs folder (events only grow). An unfinished root whose runs folder is gone: LedgerError."""
    runs = Path(root) / "runs"
    if runs.is_dir():
        try:
            found = {run: item["dispatch"] for run, item in count_events(runs).items()}
        except (OSError, ValueError) as exc:
            raise LedgerError(f"the events of {root} cannot be counted ({exc.__class__.__name__})") from exc
    elif any(item.get("finishedAt") is None for item in entry["phases"]):
        raise LedgerError(f"an unfinished real-call phase of {root} has no runs folder left to count")
    else:
        found = {}
    return sum(max(entry["dispatch"].get(run, 0), found.get(run, 0)) for run in {*entry["dispatch"], *found})


def ledger_total(ledger: dict, extra_roots: tuple[Path, ...] = (), exclude: Path | None = None) -> int:
    """Real calls of every recorded root and of ``extra_roots`` (counted from their events), without ``exclude``."""
    roots = {root: entry for root, entry in ledger["roots"].items()}
    for root in extra_roots:
        roots.setdefault(str(Path(root).resolve()), {"phases": [], "dispatch": {}})
    skip = str(Path(exclude).resolve()) if exclude is not None else None
    return sum(root_count(root, entry) for root, entry in roots.items() if root != skip)


def write_ledger(path: Path, ledger: dict) -> None:
    """Replace the ledger file at once (a temporary file next to it, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def ledger_admission(before_others: int, mine: int, planned: int, live_calls: int) -> str | None:
    """Why a real-call phase may not start (None = it may): the ledger total plus this phase's plan passes the
    allocation, or --live-calls (this root's calls in total) passes what the other roots leave."""
    if before_others + mine + planned > MAX_LIVE_CALLS:
        return (f"the ledger counts {before_others + mine} real calls (every root) and this phase plans {planned}; the "
                f"allocation is {MAX_LIVE_CALLS} in total")
    if before_others + live_calls > MAX_LIVE_CALLS:
        return (f"--live-calls {live_calls} passes what the ledger leaves ({MAX_LIVE_CALLS - before_others} after "
                f"{before_others} real calls of other roots)")
    return None


def case_plan(phase: str) -> dict[str, list[str]]:
    if phase == "fixture":
        return {case: ["jev-loop-fixture"] for case in FIXTURE_CASES}
    if phase == "calibrate":
        return {"JL-calibrate-send": ["jev-loop-calibrate"]}
    return {"JL-live-sends": ["jev-loop-live"]}


def not_observed(phase: str) -> dict[str, str]:
    if phase == "fixture":
        return {"JL-calibrate-send": NOT_OBSERVED_LIVE, "JL-live-sends": NOT_OBSERVED_LIVE, **NOT_OBSERVED_COMMON}
    return dict(NOT_OBSERVED_COMMON)


def environment_ok(environment: dict, phase: str, rehearsal: bool = False) -> bool:
    base = all(environment.get(key) is True for key in (*ENVIRONMENTS, *CAPABILITIES, "loopLigand", "loopProtein"))
    if phase == "fixture" or rehearsal:
        gate = environment.get("fixtureServer") is True
    else:
        gate = environment.get("keyAvailable") is True and environment.get("dotenvPrivate") is True
    state = environment.get("liveState") is True if phase == "live" else environment.get("setup") is True
    return base and gate and state


def assemble(rows: list[dict], leftovers: list[str], environment: dict, phase: str, checks: dict,
             rehearsal: bool = False) -> dict:
    """Judge the latest row of every step of ``phase``, the cases of its plan and the runner checks.

    A step passes when its latest row passed and measured 0 non-loopback requests. A case passes only when every
    covering step's latest row reports it as pass (absent = fail). ``checks``: keyScan {ok}, wordingScan {path:
    words}, fixtureProof {ok} (fixture and rehearsals), liveCount, calibration, liveLedger, budget {ok} (calibrate,
    live) and shuffle {ok, planned} (live)."""
    attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
    for row in rows:
        base, order = m13.step_base(row["step"])
        attempts.setdefault(base, []).append((order, row))
    latest = {step: max(found, key=lambda item: item[0])[1] for step, found in attempts.items()}
    steps: dict[str, dict] = {}
    for step in PHASE_STEPS[phase]:
        row = latest.get(step)
        if row is None:
            steps[step] = {"status": "missing", "problems": ["no row"]}
            continue
        problems = []
        if row.get("status") != "pass":
            problems.append(f"status {row.get('status')}")
        if row.get("externalRequestCount") != 0:
            problems.append(f"externalRequestCount {row.get('externalRequestCount')!r}")
        steps[step] = {"status": "fail" if problems else "pass", "latest": row["step"], "problems": problems,
                       "attempts": len(attempts[step])}
    cases: dict[str, dict] = {}
    for case, modes in case_plan(phase).items():
        seen = {mode: ((latest.get(mode) or {}).get("cases") or {}).get(ROW_CASE.get(case, case)) for mode in modes}
        cases[case] = {"text": CASE_TEXT[case], "modes": seen,
                       "status": "pass" if all(value == "pass" for value in seen.values()) else "fail"}
    judged = [latest[step] for step in PHASE_STEPS[phase] if step in latest]

    def runner_case(name: str, ok: bool) -> None:
        cases[name] = {"text": RUNNER_CASE_TEXT[name], "modes": {"runner": "pass" if ok else "fail"},
                       "status": "pass" if ok else "fail"}

    runner_case("S-browser-egress-zero", len(judged) == len(PHASE_STEPS[phase])
                and all(row.get("externalRequestCount") == 0 for row in judged))
    runner_case("S-key-absent", (checks.get("keyScan") or {}).get("ok") is True)
    runner_case("S-wording-evidence", checks.get("wordingScan") == {})
    if phase == "fixture" or rehearsal:
        runner_case("S-real-calls-zero", (checks.get("fixtureProof") or {}).get("ok") is True)
    if phase != "fixture":
        runner_case("JL-count", (checks.get("liveCount") or {}).get("ok") is True)
        runner_case("JL-ledger", (checks.get("liveLedger") or {}).get("ok") is True)
        runner_case("JL-budget", (checks.get("budget") or {}).get("ok") is True)
        runner_case("JL-calibration", (checks.get("calibration") or {}).get("ok") is True)
    if phase == "live" and (checks.get("shuffle") or {}).get("planned") is True:
        runner_case("JL-shuffle-observed", (checks.get("shuffle") or {}).get("ok") is True)
    parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
             "cases": all(v["status"] == "pass" for v in cases.values()),
             "environment": environment_ok(environment, phase, rehearsal), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "notObserved": not_observed(phase), "verdictParts": parts,
            "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


class Runner(m18.Runner):
    """The M18/M17/M15 runner protections (outside /tmp, git-ignored artifacts, free ports, build stamp, mw path check,
    allowlisted env, redacted export, loopback API helpers) with the M25 setup, fixture server, guarded calibrate and
    live phases, their rehearsal against the fixture server, evidence searches and ledger."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        phase = getattr(args, "phase", "fixture")
        rehearse = bool(getattr(args, "rehearse", False))
        finalize = bool(getattr(args, "finalize", False))
        if args.out:
            out = args.out
        elif rehearse:
            out = str(Path(args.root).resolve() / f"out-{phase}{'-finalize' if finalize else ''}")
        else:
            out = str(code / "docs/qa" / f"m25-jev-loop-{stamp}" / f"acceptance-{phase}")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.phase = phase
        self.rehearse = rehearse
        self.live_calls = int(getattr(args, "live_calls", 0))
        if self.phase not in PHASES:
            raise SystemExit(f"--phase must be one of {PHASES}")
        self.finalize = finalize
        self.finalized: dict | None = None
        if self.rehearse and self.phase == "fixture":
            raise SystemExit("--rehearse rehearses the calibrate and live phases (the fixture phase sends to no one)")
        if self.finalize and (self.phase != "calibrate" or self.live_calls != 0):
            raise SystemExit("--finalize rebuilds the evidence of a finished calibrate root from its stored files and "
                             "makes no call: use it with --phase calibrate and leave --live-calls at 0")
        if self.phase == "calibrate" and self.live_calls < 1 and not self.finalize:
            raise SystemExit("--phase calibrate makes one real call: it needs --live-calls >= 1")
        if self.phase == "live" and self.live_calls < 2:
            raise SystemExit("--phase live sends the rest of the plan: it needs --live-calls N >= 2")
        self.regressions = bool(getattr(args, "regressions", False))
        kbase = getattr(args, "kbase", None)
        self.kbase = Path(kbase).resolve() if kbase else None
        if self.regressions and self.phase != "fixture":
            raise SystemExit("--regressions runs after the fixture phase only (the other phases spend real calls)")
        if self.regressions and (self.kbase is None or not (self.kbase / "ref/manifest.json").is_file()):
            raise SystemExit("--regressions needs --kbase <kbase_kinase checkout with ref/manifest.json> "
                             "(the M20, M16 and M15 regressions import reference snapshots)")
        self.control = self.root / "fixture-control"
        self.state_path = self.root / "live-state.json"
        self.checks: dict = {}
        self.ledger_file: Path | None = None
        self.ledger_open = False
        self.setup_file: Path | None = None
        self.dispatch_before = 0
        self.calls_before = 0

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m25_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- services ----------------------------------------------------------------------------
    def uses_fixture(self) -> bool:
        return self.phase == "fixture" or self.rehearse

    def start_fixture_backend(self) -> None:
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(self.runs),
                             "MW_REFERENCE_DIR": str(self.reference)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        log = self.artifacts / "services" / "fixture-backend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), str(self.code / FIXTURE_SERVER), "--port", "8000", "--runs-dir", str(self.runs),
             "--control", str(self.control)],
            cwd=self.code, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{m15.API}/capabilities")
        server = json.loads((self.control / "server.json").read_text())
        self.environment["fixtureServer"] = (server.get("fixture") is True and server.get("runsDir") == str(self.runs)
                                             and "MockTransport" in server.get("scienceGate", ""))
        self.environment["fixtureServerRecord"] = {k: server.get(k) for k in ("schema", "scienceGate", "viewerGate",
                                                                               "defaultGate", "scripts")}
        self.state.setdefault("services", []).append({"name": "fixture-backend", "runs": str(self.runs),
                                                      "control": str(self.control), "startedAt": now()})
        self.save()

    def start_phase_backend(self) -> None:
        """The fixture server (fixture phase and rehearsals) or the product backend (the real-call phases)."""
        if self.uses_fixture():
            self.start_fixture_backend()
        else:
            self.start_backend_at("backend", self.code, self.runs)
        self.dispatch_before = dispatch_total(count_events(self.runs)) if self.runs.is_dir() else 0
        self.calls_before = len(self.fixture_calls())

    def capabilities_ready(self) -> bool:
        methods = self.get_json("/capabilities").get("methods") or {}
        for key, name in CAPABILITIES.items():
            self.environment[key] = (methods.get(name) or {}).get("available") is True
        loop = methods.get("jev_loop") or {}
        self.environment["loopLigand"] = (loop.get("ligand") or {}).get("available") is True
        self.environment["loopProtein"] = (loop.get("protein") or {}).get("available") is True
        ready = all(self.environment[key] for key in (*CAPABILITIES, "loopLigand", "loopProtein"))
        self.record("environment-capability", "pass" if ready else "fail", detail={
            "capability": {name: (methods.get(name) or {}).get("available") for name in CAPABILITIES.values()},
            "jevLoop": {branch: (loop.get(branch) or {}).get("available") for branch in ("ligand", "protein")}})
        return ready

    # ----- QA runs over the loopback API (qa_setup.py; real M17 jobs and cheap tools) ----------
    def setup_runs(self, label: str) -> Path | None:
        target = self.artifacts / f"setup-{label}.json"
        log = self.artifacts / "services" / f"setup-{label}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            rc = subprocess.run([str(self.python), str(self.code / QA_SETUP), "--api", m15.API, "--out", str(target)],
                                cwd=self.code, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                timeout=STEP_TIMEOUT_S, check=False).returncode
        ok = rc == 0 and target.is_file()
        self.record(f"setup-{label}", "pass" if ok else "fail", exitCode=rc, log=str(log))
        if not ok:
            return None
        setup = json.loads(target.read_text())
        self.environment["setup"] = True
        self.state["setupRuns"] = {key: value["run"] for key, value in setup["runs"].items()}
        self.save()
        return target

    def run_ids(self, setup_file: Path) -> dict[str, str]:
        return {key: value["run"] for key, value in json.loads(Path(setup_file).read_text())["runs"].items()}

    # ----- harness steps -----------------------------------------------------------------------
    def flow(self, step: str, mode: str, extra: list[str], limit: int | None = None) -> dict | None:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / FLOW), "--url", m15.WEB, "--mode", mode, "--artifacts", str(step_dir),
                "--runs-dir", str(self.runs), *extra]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            proc = subprocess.Popen(argv, cwd=self.frontend, env=m13.child_env(), stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            rc, exceeded = watch_process(proc, self.runs, limit, STEP_TIMEOUT_S)
        if exceeded is not None:
            self.stop_backend()
            self.state["dispatchCapExceeded"] = {"limit": limit, "counts": exceeded}
            self.save()
            self.record("dispatch-cap", "fail", limit=limit, counts=exceeded)
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        if row is None:
            self.write_row(step_dir, {"mode": mode, "evidenceKind": "real_electron_offscreen", "status": "fail",
                                      "cases": {}, "externalRequestCount": None,
                                      "error": f"harness exited {rc} without a ledger row"})
        passed = rc == 0 and row is not None and row.get("status") == "pass" and exceeded is None
        self.record(step, "pass" if passed else "fail", exitCode=rc, artifacts=str(step_dir),
                    cases=(row or {}).get("cases"))
        return row

    def write_plan(self, name: str, plan: dict, ids: dict[str, str]) -> Path:
        """The harness plan with the setup-run keys of maxPerRun mapped to this root's run ids."""
        target = self.artifacts / f"plan-{name}.json"
        mapped = {**plan, "maxPerRun": {ids[key]: value for key, value in plan["maxPerRun"].items()}}
        target.write_text(json.dumps(mapped, indent=2) + "\n")
        return target

    def fixture_calls(self) -> list[dict]:
        file = self.control / "calls.jsonl"
        return [json.loads(line) for line in file.read_text().splitlines() if line] if file.exists() else []

    def check_fixture_proof(self) -> None:
        """S-real-calls-zero for this phase only (a rehearsed live phase restarts the server on the same folders)."""
        server_file = self.control / "server.json"
        server = json.loads(server_file.read_text()) if server_file.exists() else None
        reads_file = self.control / "credentials.json"
        reads = json.loads(reads_file.read_text()) if reads_file.exists() else None
        counts = count_events(self.runs)
        calls = self.fixture_calls()[self.calls_before:]
        responses = sum(item["responseReceived"] for item in counts.values())
        self.checks["fixtureProof"] = fixture_proof(server, calls, dispatch_total(counts) - self.dispatch_before,
                                                    responses - self.state.get("responsesBefore", 0), reads)
        self.record("fixture-proof", "pass" if self.checks["fixtureProof"]["ok"] else "fail",
                    detail=self.checks["fixtureProof"])

    def check_remaining(self, ids: dict[str, str], entries: list[dict]) -> bool:
        """JL-budget: the plan within the run defaults (pure) and, once the runs exist, within their remaining budget."""
        planned = plan_budget(LIVE_PLAN)
        needs = plan_budget(entries)["needs"]
        short: dict[str, list[str]] = {}
        for key, need in needs.items():
            _, budget = self.api("GET", f"/runs/{ids[key]}/budget")
            _, status = self.api("GET", f"/runs/{ids[key]}/jev/status")
            live_need = {**need, **{axis: need[axis] - SETUP_COST[key][axis] for axis in SETUP_COST[key]}}
            short[key] = remaining_ok(live_need, budget, status) if isinstance(budget, dict) else ["unreadable"]
        ok = planned["ok"] and not any(short.values())
        self.checks["budget"] = {"ok": ok, "plan": planned, "phaseNeeds": needs, "remainingShort": short}
        self.record("plan-budget", "pass" if ok else "fail", detail=self.checks["budget"])
        return ok

    # ----- searches ----------------------------------------------------------------------------
    def key_scan(self, roots: list[Path]) -> dict:
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend")})
        done = subprocess.run([str(self.python), "-c", KEY_SCAN, SENTINEL, *map(str, roots)], cwd=self.code, env=env,
                              capture_output=True, text=True, check=False)
        try:
            found = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"ok": False, "error": f"key scan exited {done.returncode}"}
        hits = found.get("hits") or {}
        return {"ok": done.returncode == 0 and not hits.get("key") and not hits.get("sentinel"),
                "keyAvailable": found.get("keyAvailable"), "files": found.get("files"),
                "keyHits": hits.get("key", []), "sentinelHits": hits.get("sentinel", []),
                "roots": [str(root) for root in roots]}

    def key_available(self) -> bool:
        """The key found by the product resolver (boolean, child process) and the root .env private (os.lstat only).
        Required before a real call; a rehearsal records it (its gate holds the placeholder)."""
        scan = self.key_scan([])
        dotenv = dotenv_status(self.code)
        self.environment["keyAvailable"] = scan.get("keyAvailable") is True
        self.environment["dotenvPrivate"] = dotenv["private"]
        ok = self.environment["keyAvailable"] and dotenv["private"]
        self.record("key-present", "pass" if ok or self.rehearse else "fail", detail={
            "keyAvailable": self.environment["keyAvailable"], "dotenv": dotenv, "rehearsal": self.rehearse})
        return ok or self.rehearse

    # ----- phases ------------------------------------------------------------------------------
    def run_fixture(self) -> None:
        self.start_phase_backend()
        if not self.capabilities_ready():
            self.missing_prerequisite("jev-loop-fixture", "backend reports a needed method unavailable")
            return
        setup = self.setup_runs("fixture")
        if setup is None:
            self.missing_prerequisite("jev-loop-fixture", "the QA runs could not be made")
            return
        self.flow("jev-loop-fixture", "fixture", ["--control", str(self.control), "--setup", str(setup)])
        self.checks["events"] = count_events(self.runs)
        self.check_fixture_proof()

    def phase_extra(self, setup: Path, plan: Path) -> list[str]:
        extra = ["--setup", str(setup), "--plan", str(plan)]
        return [*extra, "--control", str(self.control)] if self.rehearse else extra

    def run_calibrate(self) -> None:
        self.start_phase_backend()
        if not (self.capabilities_ready() and self.key_available()):
            self.missing_prerequisite("jev-loop-calibrate", "a needed method is unavailable or the key is absent (no call "
                                                            "made)")
            return
        made = self.setup_runs("live")
        if made is None:
            self.missing_prerequisite("jev-loop-calibrate", "the QA runs could not be made (no call made)")
            return
        setup = self.root / "live-setup.json"          # kept with the root: the live phase reads it from there
        setup.write_text(made.read_text())
        ids = self.run_ids(setup)
        plan = plan_for("calibrate", 0, self.live_calls)
        if not self.check_remaining(ids, LIVE_PLAN):
            self.missing_prerequisite("jev-loop-calibrate", "the plan does not fit the runs' budget (no call made)")
            return
        per_run = {ids[key]: value for key, value in plan["maxPerRun"].items()}
        row = self.flow("jev-loop-calibrate", "calibrate", self.phase_extra(setup, self.write_plan("calibrate", plan, ids)),
                        limit=plan["maxDispatch"])
        counts = count_events(self.runs)
        self.checks["events"] = counts
        self.checks["liveCount"] = {"ok": live_count_ok(counts, 1, per_run), "limit": 1, "counts": counts}
        self.checks["calibration"] = calibration(row)
        self.state_path.write_text(json.dumps({"schema": "m25_jev_loop_live_state@1", "setup": str(setup),
                                               "rehearsal": self.rehearse, "calibration": self.checks["calibration"],
                                               "counts": counts, "maxPerRun": per_run, "liveCalls": self.live_calls,
                                               "livePhaseRan": False, "writtenAt": now()}, indent=2) + "\n")
        # One ``detail`` keyword: the calibration holds the send's own ``status`` (M24 lesson).
        self.record("calibration", "pass" if self.checks["calibration"]["ok"] else "fail",
                    detail=self.checks["calibration"])
        if self.rehearse:
            self.check_fixture_proof()

    def run_live(self) -> None:
        state = json.loads(self.state_path.read_text())
        self.checks["calibration"] = state.get("calibration") or {"ok": False}
        self.start_phase_backend()
        if not (self.capabilities_ready() and self.key_available()):
            self.missing_prerequisite("jev-loop-live", "a needed method is unavailable or the key is absent (no call made)")
            return
        setup = Path(state["setup"])
        ids = self.run_ids(setup)
        used = dispatch_total(count_events(self.runs))
        plan = plan_for("live", used, self.live_calls)
        state["livePhaseRan"] = True
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")
        self.checks["shuffle"] = {"planned": any(entry.get("compareWith") for entry in plan["entries"]), "ok": False}
        if not plan["entries"]:
            self.missing_prerequisite("jev-loop-live", f"no plan entry left: {used} dispatch events already, --live-calls "
                                                       f"{self.live_calls}")
        elif not self.check_remaining(ids, plan["entries"]):
            self.missing_prerequisite("jev-loop-live", "the plan does not fit the runs' remaining budget (no call made)")
        else:
            row = self.flow("jev-loop-live", "live", self.phase_extra(setup, self.write_plan("live", plan, ids)),
                            limit=self.live_calls)
            self.checks["shuffle"]["ok"] = shuffle_observed(row)
            self.record("shuffle-observed", "pass" if self.checks["shuffle"]["ok"] or not self.checks["shuffle"]["planned"]
                        else "fail", detail={"planned": self.checks["shuffle"]["planned"],
                                             "shuffle": (row or {}).get("shuffle")})
        counts = count_events(self.runs)
        self.checks["events"] = counts
        self.checks["liveCount"] = {"ok": live_count_ok(counts, self.live_calls, state.get("maxPerRun") or {}),
                                    "limit": self.live_calls, "counts": counts}
        if self.rehearse:
            self.check_fixture_proof()

    # ----- the real-call ledger (calibrate and live; the rehearsal's own file) -----------------
    def ledger_location(self) -> Path:
        return self.root / REHEARSAL_LEDGER_NAME if self.rehearse else ledger_path(self.code)

    def planned_calls(self) -> int:
        """Calls this phase may make: the calibrate send, or the live plan entries left in this root."""
        if self.phase == "calibrate":
            return plan_sends(plan_for("calibrate", 0, self.live_calls)["entries"])
        used = dispatch_total(count_events(self.runs)) if self.runs.is_dir() else 0
        return plan_sends(plan_for("live", used, self.live_calls)["entries"])

    def ledger_guard(self) -> None:
        """Before anything starts: refuse (SystemExit) when the ledger cannot be found, read or counted, when its total
        (every root, rescanned) plus this phase's planned calls passes MAX_LIVE_CALLS or when --live-calls passes what
        it leaves; otherwise record this phase as started (unfinished until ledger_close)."""
        planned = self.planned_calls()
        try:
            self.ledger_file = self.ledger_location()
            ledger = read_ledger(self.ledger_file)
            others = ledger_total(ledger, exclude=self.root)
            mine = root_count(str(self.root), ledger["roots"].get(str(self.root)) or {"phases": [], "dispatch": {}})
        except LedgerError as exc:
            raise SystemExit(f"real calls refused, nothing started: {exc}") from exc
        refusal = ledger_admission(others, mine, planned, self.live_calls)
        if refusal is not None:
            raise SystemExit(f"real calls refused, nothing started: {refusal}")
        entry = ledger["roots"].setdefault(str(self.root), {"phases": [], "dispatch": {}})
        entry["phases"].append({"phase": self.phase, "startedAt": now(), "finishedAt": None, "planned": planned,
                                "liveCalls": self.live_calls})
        try:
            write_ledger(self.ledger_file, ledger)
        except OSError as exc:
            raise SystemExit(f"real calls refused, nothing started: the ledger cannot be written ({exc})") from exc
        self.ledger_open = True
        self.checks["liveLedger"] = {"ok": False, "path": str(self.ledger_file), "rehearsal": self.rehearse,
                                     "before": others + mine, "planned": planned}

    def ledger_close(self) -> None:
        """Record this root's jev_science_dispatch_started counts (failed sends included) and close its phase."""
        if not self.ledger_open:
            return
        self.ledger_open = False
        ledger = read_ledger(self.ledger_file)
        entry = ledger["roots"].setdefault(str(self.root), {"phases": [], "dispatch": {}})
        found = count_events(self.runs) if self.runs.is_dir() else {}
        for run, item in found.items():
            entry["dispatch"][run] = max(entry["dispatch"].get(run, 0), item["dispatch"])
        for item in entry["phases"]:
            if item["finishedAt"] is None:
                item["finishedAt"] = now()
        write_ledger(self.ledger_file, ledger)
        after = ledger_total(ledger)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.checks["liveLedger"] = {**self.checks.get("liveLedger", {}), "ok": after <= MAX_LIVE_CALLS, "after": after,
                                     "rootDispatch": sum(entry["dispatch"].values())}
        self.record("live-ledger", "pass" if after <= MAX_LIVE_CALLS else "fail", detail=self.checks["liveLedger"])

    # ----- --finalize: the calibrate evidence of a finished root, from its stored files only -----
    def latest_row(self, step: str) -> dict | None:
        found = []
        for row_file in self.artifacts.glob("*/ledger-row.json"):
            base, order = m13.step_base(row_file.parent.name)
            if base == step:
                found.append((order, row_file))
        return json.loads(max(found)[1].read_text()) if found else None

    def recorded(self, step: str, key: str) -> object:
        """A field of the last ``step`` record of runner-summary.jsonl (its ``detail``), or None."""
        value = None
        summary = self.artifacts / "runner-summary.jsonl"
        for line in summary.read_text().splitlines() if summary.is_file() else []:
            entry = json.loads(line)
            if entry.get("step") == step:
                value = (entry.get("detail") or entry).get(key)
        return value

    def finalize_inputs(self) -> dict:
        """The stored files --finalize reads, each checked against the others; any doubt is a refusal (SystemExit)
        before anything is written."""
        def refuse(reason: str) -> None:
            raise SystemExit(f"--finalize refused, nothing written: {reason}")

        if self.out.exists() and (not self.out.is_dir() or any(self.out.iterdir())):
            refuse(f"{self.out} already holds files and committed evidence is never overwritten or removed: choose a "
                   "new --out")
        try:
            self.ledger_file = self.ledger_location()
            if not self.ledger_file.exists():
                refuse(f"the real-call ledger has no record of {self.root}")
            book = read_ledger(self.ledger_file)
            after = ledger_total(book)
        except LedgerError as exc:
            refuse(f"the real-call ledger: {exc}")
        entry = book["roots"].get(str(self.root))
        if entry is None:
            refuse(f"the real-call ledger has no record of {self.root}")
        phases = entry["phases"]
        if (not any(item["phase"] == "calibrate" for item in phases)
                or any(item.get("finishedAt") is None for item in phases)):
            refuse("the real-call ledger does not record this root's calibrate phase as finished")
        if not self.state_path.is_file():
            refuse(f"no {self.state_path} (not a calibrate root)")
        try:
            state = json.loads(self.state_path.read_text())
        except ValueError:
            state = None
        if not (isinstance(state, dict) and state.get("schema") == "m25_jev_loop_live_state@1"
                and isinstance(state.get("calibration"), dict) and type(state.get("liveCalls")) is int
                and 1 <= state["liveCalls"] <= MAX_LIVE_CALLS and state.get("rehearsal") is self.rehearse):
            refuse(f"{self.state_path} is not a stored calibrate state of this kind (rehearsal {self.rehearse})")
        if state.get("livePhaseRan") is not False:
            refuse("the live phase already ran on this root: the calibrate evidence cannot be rebuilt alone")
        counts = count_events(self.runs) if self.runs.is_dir() else {}
        if {run: item["dispatch"] for run, item in counts.items()} != entry["dispatch"] or counts != state.get("counts"):
            refuse("the real-call ledger, live-state.json and the root's events do not hold the same dispatch counts")
        saved_file = self.artifacts / "runner-state.json"
        try:
            saved = json.loads(saved_file.read_text())
        except (OSError, ValueError):
            saved = None
        if not (isinstance(saved, dict) and isinstance(saved.get("build"), dict)
                and isinstance(saved.get("environment"), dict)):
            refuse(f"{saved_file} (this run's build and environment) is missing or unreadable")
        row = self.latest_row("jev-loop-calibrate")
        if row is None:
            refuse(f"no jev-loop-calibrate ledger row in {self.artifacts}")
        if calibration(row) != state["calibration"]:
            refuse("the calibration in live-state.json is not the one the stored jev-loop-calibrate row gives")
        setup, stored = self.artifacts / "setup-live.json", self.root / "live-setup.json"
        if not (setup.is_file() and stored.is_file() and setup.read_bytes() == stored.read_bytes()):
            refuse(f"{self.artifacts} is not this root's calibrate run (setup-live.json differs from live-setup.json)")
        planned = [item for item in phases if item["phase"] == "calibrate"][-1].get("planned")
        return {"state": state, "saved": saved, "entry": entry, "after": after, "planned": planned, "counts": counts}

    def finalize_calibrate(self) -> int:
        """--finalize: the end of run_calibrate and of execute, rebuilt from the stored files of a calibrate root whose
        call finished (no build, service, Electron, POST or call; the ledger and the root are only read and
        runner-state.json is not rewritten)."""
        found = self.finalize_inputs()
        self.state = found["saved"]                      # that run's build and environment, in memory only
        self.environment = dict(self.state["environment"])
        self.live_calls = found["state"]["liveCalls"]
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        self.finalized = {"at": now(), "realCalls": 0, "gitHead": head, "runnerSha256": m13.sha_file(Path(__file__)),
                          "ledgerSha256": m13.sha_file(self.ledger_file),
                          "liveStateSha256": m13.sha_file(self.state_path), "rehearsal": self.rehearse,
                          "note": "rebuilt from the stored files of a finished calibrate root; no call"}
        self.record("finalize", "pass", detail=self.finalized)
        counts = found["counts"]
        self.checks["events"] = counts
        self.checks["liveCount"] = {"ok": live_count_ok(counts, 1, found["state"].get("maxPerRun") or {}), "limit": 1,
                                    "counts": counts}
        self.checks["calibration"] = found["state"]["calibration"]
        self.record("calibration", "pass" if self.checks["calibration"].get("ok") is True else "fail",
                    detail=self.checks["calibration"])
        for name in ("budget", "fixtureProof"):
            stored = self.recorded({"budget": "plan-budget", "fixtureProof": "fixture-proof"}[name], "ok")
            if stored is not None:
                self.checks[name] = {"ok": stored is True, "fromSummary": True}
        entry, after = found["entry"], found["after"]
        self.checks["liveLedger"] = {"ok": after <= MAX_LIVE_CALLS, "path": str(self.ledger_file),
                                     "before": self.recorded("live-ledger", "before"), "planned": found["planned"],
                                     "after": after, "rootDispatch": sum(entry["dispatch"].values()), "readOnly": True}
        self.record("live-ledger", "pass" if after <= MAX_LIVE_CALLS else "fail", detail=self.checks["liveLedger"])
        return self.finish()

    # ----- optional regression chain (separate runners; their own ledgers decide) -----------------
    def regression_commands(self) -> list[tuple[str, list[str]]]:
        commands = []
        for name, extra in REGRESSIONS:
            argv = [str(self.python), str(self.code / "scripts" / f"{name}_offscreen_acceptance.py"),
                    "--root", str(self.root.parent / f"{self.root.name}-{name}-regression"),
                    "--artifacts", str(self.artifacts / "regressions" / name),
                    "--out", str(self.out.parent / f"{name}-regression"), "--code-root", str(self.code)]
            for item in extra:
                if item == "kbase":
                    argv += ["--kbase", str(self.kbase)]
                else:
                    argv.append(item)
            commands.append((name, argv))
        return commands

    def run_regressions(self) -> None:
        results = {}
        for name, argv in self.regression_commands():
            log = self.artifacts / "services" / f"regression-{name}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("w") as out:
                rc = subprocess.run(argv, cwd=self.code, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    check=False).returncode
            results[name] = {"exitCode": rc, "argv": argv, "log": str(log)}
            self.record(f"regression-{name}", "pass" if rc == 0 else "fail", exitCode=rc, log=str(log))
        self.state["regressions"] = results
        self.save()

    # ----- leftovers, ledger, evidence ---------------------------------------------------------
    def leftovers(self) -> list[str]:
        left = []
        root = self.root.resolve()
        for _ in range(10):
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
            left = []
            for line in ps.splitlines():
                pid, _, command = line.strip().partition(" ")
                if str(self.offscreen / "main.cjs") in command:
                    left.append(line.strip())
                    continue
                if not any(worker in command for worker in WORKERS):
                    continue
                cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True,
                                     check=False).stdout
                paths = [Path(item[1:]) for item in cwd.splitlines() if item.startswith("n")]
                if not paths or str(root) in command or any(path == root or root in path.parents for path in paths):
                    left.append(line.strip())
            if not left:
                break
            time.sleep(0.5)
        for port in (8000, 3000):
            left += [f"port {port} still listening: pid {pid}" for pid in m13.listening(port)]
        return left

    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "rehearsal": row.get("rehearsal"),
                         "status": row.get("status"), "cases": row.get("cases") or {}, "runs": row.get("runs"),
                         "sends": row.get("sends") or [], "plan": row.get("plan"), "fixture": row.get("fixture"),
                         "loops": row.get("loops"), "shuffle": row.get("shuffle"), "preChecks": row.get("preChecks"),
                         "dispatchCounts": row.get("dispatchCounts"), "evidenceKind": row.get("evidenceKind"),
                         "fixtureLabels": row.get("fixtureLabels", []), "controls": sorted(row.get("controls") or {}),
                         "wording": row.get("wording", []), "externalRequestCount": row.get("externalRequestCount"),
                         "partFailures": row.get("partFailures", []), "error": row.get("error"),
                         "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.phase, self.checks, self.rehearse)
        passed = judged["passed"]
        scope = f"{self.phase}-rehearsal" if self.rehearse else self.phase
        ledger = {"schema": "m25_case_ledger@1", "phase": self.phase, "rehearsal": self.rehearse,
                  "acceptanceScope": scope, "liveCalls": self.live_calls, "generatedAt": now(),
                  "build": self.state.get("build"), "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "environment": self.environment,
                  "checks": self.checks, "finalize": self.finalized,
                  "dispatchCapExceeded": self.state.get("dispatchCapExceeded"),
                  "leftoverProcesses": leftovers,
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows),
                  "rowsWithUnknownExternalCount": [r["step"] for r in rows if r["externalRequestCount"] is None],
                  "rows": rows}
        (self.artifacts / "case-ledger.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
        self.record("case-ledger", "pass" if passed else "fail", verdict=ledger["verdict"],
                    acceptance=ledger["acceptance"],
                    cases={case: value["status"] for case, value in judged["cases"].items()},
                    output=str(self.artifacts / "case-ledger.json"))
        return ledger

    def readme(self, ledger: dict) -> str:
        env = ledger["environment"]
        checks = ledger.get("checks") or {}
        proof = checks.get("fixtureProof") or {}
        calib = checks.get("calibration") or {}
        count = checks.get("liveCount") or {}
        kind = "연습(fixture 서버, 실호출 0)" if ledger.get("rehearsal") else ""
        lines = [f"# M25 JEV 루프 오프스크린 수락 QA 증거 ({ledger['phase']} 단계{' · ' + kind if kind else ''})", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}** (범위: {ledger['acceptanceScope']}, --live-calls "
                  f"{ledger['liveCalls']})"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 환경: M17 {env.get('workerPython')} · 도킹 {env.get('dockingPython')} · qvina {env.get('qvina')} · "
                  f"jev_loop ligand {env.get('loopLigand')} / protein {env.get('loopProtein')} · fixture 서버 "
                  f"{env.get('fixtureServer')} · 키 존재(불리언) {env.get('keyAvailable')} · .env 비공개 "
                  f"{env.get('dotenvPrivate')}"),
                 ("- 입력: run L = 공개 준비 수용체 예제·공개 파생 부모·합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 "
                  "교체), run P = 공개 1UBQ(22곳)·1MQ4(3곳) A 치환 실제 M20 후보 집합과 합성 표시 페놀 SDF."),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 브라우저 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", ""]
        if ledger["phase"] == "fixture" or ledger.get("rehearsal"):
            lines += [(f"- 실호출: 0회. fixture 서버(SCIENCE_GATE = 스크립트된 httpx.MockTransport)만 썼고, 이 단계의 dispatch "
                       f"이벤트 {proof.get('dispatchEvents')}개 = fixture transport 호출 {proof.get('fixtureTransportCalls')}개, "
                       f"response_received 감사 {proof.get('responseAudits')}개 = 응답한 호출 {proof.get('answeredCalls')}개, "
                       f"자격 증명 해석 {json.dumps(proof.get('credentialReads'), ensure_ascii=False)}.")]
        if ledger["phase"] != "fixture":
            book = checks.get("liveLedger") or {}
            place = (f"연습 대장 {REHEARSAL_LEDGER_NAME}(root 안)" if ledger.get("rehearsal")
                     else f"저장소 대장 Git 제외 runs/{LEDGER_NAME}")
            lines += [(f"- 실호출 계수(모든 QA run): {json.dumps(count.get('counts'), ensure_ascii=False)} · 한도 "
                       f"{count.get('limit')} · 판정 {count.get('ok')}"),
                      (f"- {place}: 단계 전 {book.get('before')}회 + 이번 계획 {book.get('planned')}회, 단계 뒤 합계 "
                       f"{book.get('after')}회 / {MAX_LIVE_CALLS} · 판정 {book.get('ok')}"),
                      f"- 계획 예산: {json.dumps(checks.get('budget'), ensure_ascii=False)}",
                      f"- 첫 전송 보정: {json.dumps(calib, ensure_ascii=False)}"]
            if ledger["phase"] == "live":
                lines.append(f"- 섞기 확인(관찰값만 기록): {json.dumps(checks.get('shuffle'), ensure_ascii=False)}")
            fin = ledger.get("finalize")
            if fin:
                lines.append(f"- 마무리 모드(--finalize, {fin.get('at')}): 저장 파일(live-state.json·jev-loop-calibrate "
                             "행·runner-state.json·root의 이벤트·대장)만 읽어 이 증거를 다시 만들었다. 새 호출·빌드·서버·"
                             f"Electron·POST 없음(대장 SHA-256 {fin.get('ledgerSha256')}, 실행기 SHA-256 "
                             f"{fin.get('runnerSha256')}, git {fin.get('gitHead')}).")
        lines += ["", ("스크린숏·paint 프레임 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 SHA-256만 "
                       "기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. 키·헤더·원시 "
                       "오류는 기록하지 않는다. 고른 목록 위치는 관찰값으로만 기록했다."), "",
                  "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items())
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 관찰하지 않은 사례", ""]
        lines += [f"- {case}: {reason}" for case, reason in ledger["notObserved"].items()]
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m25_offscreen_acceptance.py --root runs/m25-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m25-acceptance/<label> \\",
                  "    --out docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-fixture   # --phase fixture (실호출 0)",
                  "# 연습(실호출 0): --phase calibrate --rehearse --live-calls 8, 같은 --root로 --phase live --rehearse",
                  "# 실호출(사용자 할당 8회 안에서만): 새 --root로 --phase calibrate --live-calls 8, 이어서 같은 --root로",
                  "# --phase live --live-calls 8 (저장소 대장 합계 + 계획이 8을 넘으면 거절)",
                  "# calibrate 실호출 뒤 증거를 쓰기 전에 멈췄으면: 같은 --root·--artifacts로 --phase calibrate --finalize",
                  "```"]
        return "\n".join(lines) + "\n"

    def export(self, ledger: dict) -> None:
        super().export(ledger)
        post = {"keyScan": self.key_scan([self.out]), "wordingScan": scan_wording(self.out), "checkedAt": now()}
        ok = post["keyScan"]["ok"] and post["wordingScan"] == {}
        target = self.out / "post-export-checks.json"
        target.write_text(json.dumps({**post, "keyScan": {k: v for k, v in post["keyScan"].items() if k != "roots"}},
                                     indent=2, ensure_ascii=False) + "\n")
        with (self.out / "SHA256SUMS").open("a") as sums:
            sums.write(f"{m13.sha_file(target)}  post-export-checks.json\n")
        self.record("post-export-checks", "pass" if ok else "fail", keyHits=len(post["keyScan"].get("keyHits", [])),
                    sentinelHits=len(post["keyScan"].get("sentinelHits", [])), wording=post["wordingScan"])

    def run(self) -> int:
        busy = {port: m13.listening(port) for port in (8000, 3000)}
        if any(busy.values()):
            raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        if self.phase != "fixture" and not plan_budget(LIVE_PLAN)["ok"]:
            raise SystemExit(f"the real-call plan does not fit the run defaults: {plan_budget(LIVE_PLAN)['short']}")
        if self.finalize:
            return self.finalize_calibrate()     # stored files only: no ledger guard, build, service or call
        if self.phase == "live":
            if not self.state_path.is_file():
                raise SystemExit(f"--phase live needs the calibrate root (no {self.state_path})")
            state = json.loads(self.state_path.read_text())
            if state.get("rehearsal") is not self.rehearse:
                raise SystemExit("this root's calibrate phase was "
                                 f"{'a rehearsal' if state.get('rehearsal') else 'real'}: run live the same way")
            if state.get("livePhaseRan"):
                raise SystemExit("the live phase already ran on this root (no second attempt, no new calls)")
            if (state.get("calibration") or {}).get("ok") is not True:
                raise SystemExit("the calibrate phase did not pass on this root: no further call")
            self.environment["liveState"] = True
        else:
            for folder in (self.runs, self.control):
                if folder.exists() and any(folder.iterdir()):
                    raise SystemExit(f"{folder} is not fresh; choose a new --root")
        real = self.phase != "fixture"
        if real:
            self.ledger_guard()          # nothing has started yet; refused when the ledger total + this plan > 8
        try:
            return self.execute()
        finally:
            if real:
                self.ledger_close()      # once (execute closes it before the ledger and export when it gets there)

    def execute(self) -> int:
        """The phase after its admission checks: build, services, flows, searches, ledger, export."""
        self.artifacts.mkdir(parents=True, exist_ok=True)
        for key, rel in ENVIRONMENTS.items():
            self.environment[key] = (self.code / rel).is_file()
        self.record("environment", "pass" if all(self.environment[key] for key in ENVIRONMENTS) else "fail",
                    detail={key: str(rel) for key, rel in ENVIRONMENTS.items()},
                    present={key: self.environment[key] for key in ENVIRONMENTS})
        self.build()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=self.code, capture_output=True, text=True,
                                   check=False).stdout
        build_id = self.frontend / ".next/BUILD_ID"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None, "gitHead": head,
                               "buildCurrentWithSource": m13.build_is_current(self.frontend),
                               "gitStatusPorcelainSha256": m13.sha_bytes(porcelain.encode()),
                               "dirtyFiles": porcelain.splitlines(), "recordedAt": now(), "codeRoot": str(self.code),
                               "harnessSha256": {name: m13.sha_file(self.offscreen / name) for name in (
                                   FLOW, "jev-flow.cjs", "driver.cjs", "main.cjs")},
                               "fixtureServerSha256": m13.sha_file(self.code / FIXTURE_SERVER),
                               "qaSetupSha256": m13.sha_file(self.code / QA_SETUP),
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        self.runs.mkdir(parents=True, exist_ok=True)
        self.reference.mkdir(parents=True, exist_ok=True)
        self.state["responsesBefore"] = sum(item["responseReceived"] for item in count_events(self.runs).values())
        try:
            self.start_frontend()
            {"fixture": self.run_fixture, "calibrate": self.run_calibrate, "live": self.run_live}[self.phase]()
        finally:
            self.stop_all()
            self.state["environment"] = self.environment
            self.save()
            self.ledger_close()          # calibrate and live: this root's dispatch events into the ledger
        return self.finish()

    def finish(self) -> int:
        """Leftovers, evidence searches, case ledger, export (and the opt-in regressions); the exit code."""
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        self.checks["keyScan"] = self.key_scan([self.artifacts, self.root])
        self.checks["wordingScan"] = scan_wording(self.artifacts)
        self.record("evidence-searches", "pass" if self.checks["keyScan"]["ok"] and not self.checks["wordingScan"]
                    else "fail", keyHits=len(self.checks["keyScan"].get("keyHits", [])),
                    sentinelHits=len(self.checks["keyScan"].get("sentinelHits", [])),
                    wording=self.checks["wordingScan"])
        ledger = self.ledger(left)
        self.export(ledger)
        if self.regressions:
            self.run_regressions()
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"], "artifacts": str(self.artifacts)}),
              flush=True)
        return 1 if failed or not ledger["acceptance"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="QA root (runs/, fixture-control/ and live-state.json inside); "
                        "fresh for fixture and calibrate, the calibrate root for live; not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m25-acceptance/<label>")
    parser.add_argument("--out", help="text evidence folder (default docs/qa/m25-jev-loop-<YYYYMMDD>/acceptance-<phase>; "
                        "with --rehearse <root>/out-<phase>)")
    parser.add_argument("--phase", choices=PHASES, default="fixture", help="fixture (0 real calls), calibrate (the "
                        "first real call), live (the rest of the allocation)")
    parser.add_argument("--live-calls", type=live_calls_arg, default=0, help=f"real JEV calls this root may make in "
                        f"total (0..{MAX_LIVE_CALLS}, default 0); calibrate needs >= 1, live >= 2")
    parser.add_argument("--rehearse", action="store_true", help="calibrate, live and calibrate --finalize against the "
                        "fixture server (no call): the same code path, a ledger inside the root")
    parser.add_argument("--finalize", action="store_true", help="with --phase calibrate and --live-calls 0: rebuild the "
                        "evidence of a calibrate root whose call finished but whose runner stopped before its evidence, "
                        "from the stored files only (no build, service, call or ledger write; --out absent or empty)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="fixture phase only: afterwards run the M24 "
                        "(fixture), M23, M22, M21, M20, M19, M18, M17, M16, M15, M14 and M13 (all phases) runners, each "
                        "with its own fresh root, artifacts and out folder")
    parser.add_argument("--kbase", help="local kbase_kinase checkout (read only, absolute path); required with "
                        "--regressions (passed to the M20, M16 and M15 regressions)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
