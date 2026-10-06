#!/usr/bin/env python3
"""Run the M24 JEV science send offscreen acceptance (.dryforge/spec.md sections 9, 11).

One command per phase, given a code root (default: this repository). Every phase checks the locked M17 RDKit
environment, builds the frontend when needed (typecheck, then build, never concurrently), starts its own loopback
services (`next start` on 127.0.0.1:3000 and a backend on 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and
MW_RUNS_DIR=<root>/runs), makes the candidate sets over the loopback API (real M17 jobs rdkit_inspect_v1 →
rdkit_enumerate_v1 on the public-derived parent and the labeled synthetic small block list; real M20
generate_mutation_candidates calls on public 1UBQ and 1MQ4, user positions = the non-Ala residues with the most
neighbors in backend/tests/fixtures/jev/expected.json, substitution to A only), drives the real Electron offscreen flow
frontend/tests/offscreen/jev-flow.cjs and assembles case-ledger.json.

Phases (``--phase``):
  fixture    (default) a fresh --root; the backend is backend/tests/offscreen_jev_fixture/server.py: the real app with
             SCIENCE_GATE over a scripted httpx.MockTransport (sentinel placeholder credential, no provider socket) and
             VIEWER_GATE refusing. Steps: jev-fixture (runs A, B, C: every screen case of the spec with the scripts
             good, good_no_extras, alias_outside, http_500, no_usage, model_mismatch, slow) and jev-rehearsal (the live
             plan below through the same live-mode screen path, against the fixture). Real OpenRouter calls: 0, proven
             by the fixture server record and by every dispatch / response audit matching one scripted transport call.
             The live cases are recorded as not observed (실호출 할당은 T10).
  calibrate  a fresh --root; the product backend (uvicorn mw.api.app:app, the real SCIENCE_GATE) after the key is
             found present (boolean only). Runs L1 (ligand set + 1UBQ set) and L2 (1MQ4 set + 1UBQ set); ONE real send:
             the first plan entry. The usage (input/output tokens, cost) against the body bytes and the reservation is
             recorded; a stop (usage unknown, over the reservation, egress stopped) ends here with no further call.
             Needs --live-calls >= 1. Writes <root>/live-state.json.
  live       the same --root after a passed calibrate (once per root): the plan entries 2..N through the screen.
             Needs --live-calls N >= 2.
In calibrate and live the harness and this runner both guard the count: the harness checks every run's
jev_science_dispatch_started events before each click (plan maxDispatch, at most 3 per run) and this runner counts the
events of every QA run while the harness runs and stops it and the backend at once when the count passes N. Nothing is
retried and no new run is opened to get more calls. The outside-traffic verdict is: browser non-loopback requests 0
and, on the server side, `response_received` audits <= --live-calls (0 real calls in the fixture phase).

Every phase ends with: no worker, fixture server, Electron, 8000/3000 listener left; a search of the evidence, the QA
root and the export for the API key (read by the product resolver in a child process; only booleans and file paths are
printed) and for the fixture's placeholder credential; a wording check of the evidence; the ledger with
``acceptance`` true only when every case of the phase passed, the environment was present, nothing was left and the
build was stamped from the current frontend source. ``--regressions`` (fixture phase only, with --kbase) afterwards runs
the M23, M22, M21, M20, M19, M18, M17, M16, M15, M14 and M13 (all phases) runners, each with its own fresh folders.

The root must be outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted environment
(no OPENROUTER_* or other secrets). This script never imports mw and never posts to a /jev/ route (consent, preview
and every send are the harness's real clicks).

Usage:
  .venv/bin/python scripts/m24_offscreen_acceptance.py --root runs/m24-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<label> \\
      [--out docs/qa/m24-jev-<YYYYMMDD>/acceptance-fixture] [--phase fixture|calibrate|live] [--live-calls N] \\
      [--code-root <dir>] [--build auto|always|never] [--regressions --kbase <abs path>/kbase_kinase]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
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
FLOW = "jev-flow.cjs"
PHASES = ("fixture", "calibrate", "live")
PHASE_STEPS = {"fixture": ["jev-fixture", "jev-rehearsal"], "calibrate": ["jev-calibrate"], "live": ["jev-live"]}
MODE_OF = {"jev-fixture": "fixture", "jev-rehearsal": "live", "jev-calibrate": "live", "jev-live": "live"}
MAX_LIVE_CALLS = 6
MAX_PER_RUN = 3
STEP_TIMEOUT_S = 3600
SETUP_TIMEOUT_S = 600
FIXTURE_SERVER = Path("backend/tests/offscreen_jev_fixture/server.py")
# The fixture server's placeholder credential: searched for in the evidence (it must never be written anywhere).
SENTINEL = "m24-fixture-sentinel-placeholder-not-a-key"
WORKER_PYTHON = Path(".deps/prolif/venv-locked/bin/python")
NEIGHBORS = Path("backend/tests/fixtures/jev/expected.json")
STRUCTURES = {"ubq": (Path("backend/tests/fixtures/public_1ubq.cif"), "1UBQ", 22),
              "mq4": (Path("backend/tests/fixtures/public_1mq4.cif"), "1MQ4", 24)}
PARENT = Path("backend/tests/fixtures/docking/public-derived-parent-record0.sdf")
BLOCKS = Path("backend/tests/fixtures/ligand_ga/synthetic-ga-small-blocks.smi")
SITE_ATOM = 22                     # the parent's N-methyl carbon (M18/M19/M22 fixture site)
LIGAND_CANDIDATES = 10             # the small pool of backend/tests/fixtures/ligand_ga (use_fixed, site 22)
FIXTURE_RUNS = {"A": ("ligand", "ubq", "mq4"), "B": ("ubq",), "C": ("ubq",)}
LIVE_RUNS = {"L1": ("ligand", "ubq"), "L2": ("mq4", "ubq")}
# The live plan (calibrate = the first entry; live = entries 2..N). At most 3 sends per run.
LIVE_PLAN = [
    {"id": "L1-ligand-5", "run": "L1", "kind": "ligand", "set": "ligand", "pick": {"first": 5}, "report": True},
    {"id": "L1-mutation-1ubq-5", "run": "L1", "kind": "mutation", "set": "ubq", "pick": {"first": 5}},
    {"id": "L1-ligand-10", "run": "L1", "kind": "ligand", "set": "ligand", "pick": {"first": 10}},
    {"id": "L2-mutation-1mq4-20", "run": "L2", "kind": "mutation", "set": "mq4", "pick": {"first": 20}},
    {"id": "L2-mutation-1mq4-20-again", "run": "L2", "resend": "L2-mutation-1mq4-20"},
    {"id": "L2-mutation-1ubq-20", "run": "L2", "kind": "mutation", "set": "ubq", "pick": {"first": 20}},
]
FIXTURE_CASES = ["J-tab-entry", "J-source-choice", "J-consent-off-block", "J-consent-toggle", "J-candidate-limit",
                 "J-preview-match", "J-confirm-required", "J-send-good", "J-bytes-equal", "J-resend", "J-report",
                 "J-ligand-filter", "J-failed-alias", "J-failed-model", "J-late", "J-send-cap", "J-other-tabs",
                 "J-no-usage-stop", "J-failed-http", "J-wording", "J-no-egress-browser"]
# Ledger case → the harness row case it reads.
ROW_CASE = {"JL-calibrate-send": "JL-live", "JL-live-sends": "JL-live"}
CASE_TEXT = {
    "J-tab-entry": "지식·보고서 탭 진입: GET 읽기만, 동의 꺼짐, 자동 선택·작성·전송 없음, 고정 안내와 U2·U3, run당 10회 중 0회 사용, "
                   "구조 분석 패널은 숨김·inert로 유지, 전역 표시 없음",
    "J-source-choice": "후보 집합 종류와 집합을 사람이 직접 고름(두 변이 집합이 보이고 아무것도 미리 고르지 않음)",
    "J-consent-off-block": "동의 꺼짐: 미리보기 차단 이유 consent_off, 확인 체크를 해도 전송 단추가 닫힘",
    "J-consent-toggle": "동의 켬: 차단 이유 없음, 전역 줄 run id 바로 뒤에 \"과학 전송 허용\"; 끔: 표시가 사라지고 consent_off가 돌아옴",
    "J-candidate-limit": "20개까지 체크, 21번째 클릭은 체크되지 않고 이유가 보임(20개 유지)",
    "J-preview-match": "보낼 내용 만들기: <pre> 본문 = 서버 미리보기 문자열, 여기서 계산한 SHA-256·바이트 = 표시 = 저장 투영, 별칭 표 = 저장 선택",
    "J-confirm-required": "확인 체크 없이는 전송 단추가 닫히고 이유가 보임; 체크하면 열림",
    "J-send-good": "fixture good: completed, 결과 카드 = 저장된 제안(별칭·로컬 표기·확신도·모델·사용량·접힌 후보별 값은 보낸 "
                   "순서 그대로·J1–J4와 J6), 정렬·막대·색 비교 요소 없음",
    "J-bytes-equal": "transport가 받은 바이트의 SHA-256 = 미리보기 = 감사 prepared 본문(같은 내용)과 payload_sha256",
    "J-resend": "같은 본문 다시 보내기(good_no_extras): 미리보기의 이전 전송 1회, 별도의 두 번째 제안, 기록에 시간순 두 줄과 U1, "
                "합친 줄 없음, 받지 않은 값은 \"보고 없음\"",
    "J-report": "보고서 만들기: 보고서 목록에 \"JEV 판정 보고서\", 클릭하면 저장된 Markdown(고정 문장 포함, 후보별 값 없음)",
    "J-ligand-filter": "리간드 집합: 필터를 통과하지 못한 후보는 체크할 수 없고 \"필터 통과만 보기\"는 통과 행만, 필터가 요청과 투영에 실림",
    "J-failed-alias": "fixture alias_outside: failed response_invalid, 이유만(카드·숫자 없음)",
    "J-failed-model": "fixture model_mismatch: failed model_mismatch, 이유만",
    "J-late": "fixture slow 중 동의 끄기: completed + 늦은 응답(동의 끈 뒤 도착)과 J7, 기록 줄 표시, 전역 표시 사라짐",
    "J-send-cap": "1MQ4 20개 후보로 열 번째 전송까지: 사용 10회·남은 0회, 미리보기 send_cap_exhausted, 전송 단추 닫힘",
    "J-other-tabs": "단백질 공학·리간드 설계·탐색 탭의 영역과 숫자를 가린 글자가 JEV 동작 전후로 같고 JEV 요소·POST 없음, "
                    "구조 분석 뷰어는 같은 세션·소스",
    "J-no-usage-stop": "run B fixture no_usage: completed, 사용량 네 칸 모두 \"알 수 없음\", 외부 전송 멈춤(usage_unknown), "
                       "미리보기 egress_stopped, 전송 단추 닫힘",
    "J-failed-http": "run C fixture HTTP 500: failed provider_http_error, 이유만",
    "J-wording": "금지 표현 검사(고정 문장 J1–J7·U1–U3 제외): 화면 여러 시점, 보고서 Markdown, fixture 응답",
    "J-no-egress-browser": "브라우저의 비-loopback 요청 0건",
    "J-live-rehearsal": "실호출 계획(여섯 전송, run당 셋 이하) 전체를 같은 화면 경로로 fixture 서버에 대고 미리 돌림: 모두 "
                        "completed, 전송 전 계수 확인, 보고서 하나, 다른 탭 불변",
    "JL-calibrate-send": "첫 실호출 한 번(리간드 5개): 실제 JEV 결과 카드·접힌 후보별 값·고정 문장·보고서, 다른 탭 불변",
    "JL-live-sends": "나머지 실호출(변이 소규모·리간드 10개·1MQ4 20개·같은 본문 재전송·1UBQ 20개 중 N−1개): 결과 표시와 "
                     "다른 탭 불변",
}
RUNNER_CASE_TEXT = {
    "S-browser-egress-zero": "모든 흐름 행의 브라우저 비-loopback 요청 0건",
    "S-real-calls-zero": "fixture 단계 실호출 0회: 서버 기록이 MockTransport 게이트이고 dispatch·response_received 감사 수가 "
                         "fixture transport 호출 기록과 같으며 모든 호출의 인증 값이 placeholder였음(불리언)",
    "S-key-absent": "증거 폴더·QA 루트·내보낸 증거에서 API 키 문자열과 fixture placeholder 문자열 0건",
    "S-wording-evidence": "증거 텍스트에 금지 표현 0건(고정 문장 제외)",
    "JL-count": "실호출 계수: 모든 QA run의 dispatch 이벤트와 response_received 감사가 --live-calls 이하, run당 3회 이하",
    "JL-calibration": "첫 실호출: completed, 사용량(입력·출력 토큰·비용)을 알고 예약값 이하, 외부 전송 멈춤 없음",
}
NOT_OBSERVED_LIVE = ("관찰하지 않음 — 실호출 할당은 T10. 이 실행은 가짜 transport fixture 서버만 썼다(OpenRouter 실호출 "
                     "0회). 실호출은 --phase calibrate --live-calls N, 이어서 같은 --root로 --phase live --live-calls N.")
NOT_OBSERVED_COMMON = {
    "J-late-run-cancelled": "run 취소 뒤 도착한 응답: HTTP 취소 경로가 없어 화면에서 만들 수 없다. backend/tests/test_jev_sends.py::"
                            "test_a_valid_reply_after_cancel_or_consent_off_is_kept_and_marked_late 가 덮는다.",
    "J-timeout-transport": "external_timeout·transport_error: backend/tests/test_jev_science_gate.py::"
                           "test_transport_timeout_is_external_timeout_and_usage_unknown, "
                           "test_other_transport_errors_are_transport_error 가 덮는다.",
    "J-missing-credential": "키 없음(missing_credential): backend/tests/test_jev_science_gate.py::"
                            "test_missing_or_unusable_key_is_missing_credential_after_one_read 가 덮는다.",
    "J-restart-derivation": "재시작 뒤 delivery_unknown·outcome_not_recorded 도출: backend/tests/test_jev_sends.py::"
                            "test_restart_without_an_outcome_derives_delivery_unknown_or_outcome_not_recorded 가 덮는다.",
    "J-send-in-progress": "다른 전송 진행 중(send_in_progress): 화면이 한 번에 한 전송만 열어 두 번째 전송을 만들 수 없다. "
                          "backend/tests/test_jev_sends.py::test_a_send_in_flight_blocks_other_sends_and_reads_as_in_progress 가 덮는다.",
    "J-dry-run": "dry-run run: backend/tests/test_jev_sends.py::test_dry_run_cannot_enable_consent_and_rejects_sends 가 덮는다.",
}
WORKERS = (*m13.WORKERS, "ligand_worker.py", "offscreen_jev_fixture/server.py")
REGRESSIONS = [("m23", []), ("m22", []), ("m21", []), ("m20", ["kbase"]), ("m19", []), ("m18", []), ("m17", []),
               ("m16", ["kbase"]), ("m15", ["kbase"]), ("m14", []),
               ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]
# Fixed sentences J1–J7 and screen notes U1–U3 (spec 6, verbatim): exempt from the wording check.
FIXED_SENTENCES = (
    "JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니다.",
    "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다.",
    "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다.",
    "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다.",
    "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 것이다.",
    ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 상호작용을 뜻하지 "
     "않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 했고 촉매 잔기 데이터베이스는 사용하지 "
     "않았으며, 검사하지 않은 항목은 '없음'이 아니다."),
    "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
    "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다.",
    ("과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 사용량을 모르면 이 "
     "run에서 다른 쪽도 멈춘다."),
    "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
)
FORBIDDEN = re.compile(r"순위|추천|최고|최적|개선|점수|친화도|안정성|ΔΔG|\bwinner\b|\bbest\b|\brank(?:s|ed|ing)?\b|"
                       r"\brecommend\w*", re.IGNORECASE)
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
    """--live-calls: an integer 0..6 (the user's allocation of real OpenRouter calls); anything else is refused."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--live-calls must be an integer 0..{MAX_LIVE_CALLS}") from exc
    if not 0 <= value <= MAX_LIVE_CALLS:
        raise argparse.ArgumentTypeError(f"--live-calls must be 0..{MAX_LIVE_CALLS} (got {value}); the allocation is "
                                         f"{MAX_LIVE_CALLS} real calls in total")
    return value


def top_residues(expected: dict, name: str, count: int) -> list[dict]:
    """The ``count`` non-Ala residues of ``name`` with the most neighbors in the T1 oracle file (ties: file order)."""
    rows = expected["structures"][name]["neighbor_counts"]
    ranked = [row for _, row in sorted(enumerate(rows), key=lambda item: (-item[1][4], item[0]))]
    picked = [row for row in ranked if row[3] != "ALA"][:count]
    return [{"model_number": 1, "chain_auth": chain, "seq_auth": seq, "icode": icode, "resname": resname}
            for chain, seq, icode, resname, _ in picked]


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


def live_count_ok(counts: dict[str, dict[str, int]], live_calls: int, per_run: int = MAX_PER_RUN) -> bool:
    """Dispatch events and response audits of every QA run within --live-calls, and at most ``per_run`` per run."""
    return (dispatch_total(counts) <= live_calls
            and sum(item["responseReceived"] for item in counts.values()) <= live_calls
            and all(item["dispatch"] <= per_run for item in counts.values()))


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


def plan_for(phase: str, used: int, live_calls: int, base: int = 0) -> dict:
    """The harness plan of a phase. ``used`` = dispatch events already in the root; ``base`` = the rehearsal offset."""
    if phase == "rehearsal":
        return {"entries": LIVE_PLAN, "maxDispatch": base + len(LIVE_PLAN), "maxPerRun": MAX_PER_RUN}
    if phase == "calibrate":
        return {"entries": LIVE_PLAN[:1], "maxDispatch": 1, "maxPerRun": MAX_PER_RUN}
    return {"entries": LIVE_PLAN[used:live_calls], "maxDispatch": live_calls, "maxPerRun": MAX_PER_RUN}


def forbidden_in(text: str) -> list[str]:
    """Forbidden expressions in ``text``, line by line, after removing every fixed sentence."""
    found: list[str] = []
    for line in str(text).split("\n"):
        for sentence in FIXED_SENTENCES:
            line = line.replace(sentence, " ")
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


def scan_wording(folder: Path) -> dict[str, list[str]]:
    """Forbidden expressions in the text evidence of ``folder`` (JSON strings one by one; other text line by line);
    the browser profile and the service logs are not evidence text."""
    found: dict[str, list[str]] = {}
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder)
        if (not path.is_file() or path.suffix not in TEXT_SUFFIXES or "browser-profile" in rel.parts
                or rel.parts[0] == "services"):
            continue
        text = path.read_text(errors="replace")
        texts: list[str] = []
        if path.suffix in (".json", ".jsonl"):
            for chunk in ([text] if path.suffix == ".json" else text.splitlines()):
                try:
                    texts += json_strings(json.loads(chunk))
                except ValueError:
                    texts.append(chunk)
        else:
            texts.append(text)
        hits = [word for item in texts for word in forbidden_in(item)]
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


def fixture_proof(server: dict | None, calls: list[dict], counts: dict[str, dict[str, int]]) -> dict:
    """Real calls 0: the backend was the fixture server (MockTransport gates) and every dispatch event and every
    response audit of the QA runs is one scripted transport call that carried the placeholder credential."""
    answered = sum(1 for call in calls if call.get("status") is not None)
    dispatch = dispatch_total(counts)
    responses = sum(item["responseReceived"] for item in counts.values())
    ok = (isinstance(server, dict) and server.get("fixture") is True
          and "MockTransport" in str(server.get("scienceGate")) and "MockTransport" in str(server.get("viewerGate"))
          and dispatch == len(calls) and responses == answered and len(calls) > 0
          and all(call.get("authorizationIsSentinel") is True for call in calls))
    return {"ok": ok, "dispatchEvents": dispatch, "fixtureTransportCalls": len(calls), "responseAudits": responses,
            "answeredCalls": answered, "realProviderCalls": 0 if ok else None}


def calibration(row: dict | None) -> dict:
    """The first real send: completed, usage known and within the reservation, no egress stop."""
    sends = [item for item in ((row or {}).get("sends") or []) if item.get("sendId")]
    if not sends:
        return {"ok": False, "reason": "no send recorded"}
    send = sends[0]
    usage = send.get("usage") or {}
    reservation = send.get("reservation") or {}
    known = all(isinstance(usage.get(key), (int, float)) for key in ("input_tokens", "output_tokens",
                                                                     "external_tokens", "cost"))
    ok = (send.get("status") == "completed" and known and send.get("egressStop") is None
          and usage["external_tokens"] <= reservation.get("external_tokens", -1)
          and usage["cost"] <= reservation.get("usd", -1))
    out = {"ok": ok, "entry": send.get("entry"), "status": send.get("status"), "reasonCode": send.get("reasonCode"),
           "servedModel": send.get("servedModel"), "bodyBytes": send.get("bodyBytes"), "usage": usage or None,
           "reservation": reservation or None, "egressStop": send.get("egressStop"),
           "responseShape": send.get("responseShape")}
    if known and usage["input_tokens"]:
        out["bodyBytesPerInputToken"] = send.get("bodyBytes", 0) / usage["input_tokens"]
    if known and usage["external_tokens"]:
        out["reservedTokensOverUsed"] = reservation.get("external_tokens", 0) / usage["external_tokens"]
    return out


def case_plan(phase: str) -> dict[str, list[str]]:
    if phase == "fixture":
        return {**{case: ["jev-fixture"] for case in FIXTURE_CASES}, "J-live-rehearsal": ["jev-rehearsal"]}
    if phase == "calibrate":
        return {"JL-calibrate-send": ["jev-calibrate"]}
    return {"JL-live-sends": ["jev-live"]}


def not_observed(phase: str) -> dict[str, str]:
    if phase == "fixture":
        return {"JL-calibrate-send": NOT_OBSERVED_LIVE, "JL-live-sends": NOT_OBSERVED_LIVE, **NOT_OBSERVED_COMMON}
    return dict(NOT_OBSERVED_COMMON)


def environment_ok(environment: dict, phase: str) -> bool:
    base = (environment.get("workerPython") is True and environment.get("ligandAvailable") is True
            and environment.get("mutationAvailable") is True and environment.get("jevAvailable") is True)
    if phase == "fixture":
        return base and environment.get("fixtureServer") is True and environment.get("setup") is True
    if phase == "calibrate":
        return base and environment.get("keyAvailable") is True and environment.get("setup") is True
    return base and environment.get("keyAvailable") is True and environment.get("liveState") is True


def assemble(rows: list[dict], leftovers: list[str], environment: dict, phase: str, checks: dict) -> dict:
    """Judge the latest row of every step of ``phase``, the cases of its plan and the runner checks.

    A step passes when its latest row passed and measured 0 non-loopback requests. A case passes only when every
    covering step's latest row reports it as pass (absent = fail). ``checks``: keyScan {ok}, wordingScan {path:
    words}, and fixtureProof {ok} (fixture) or liveCount {ok} and calibration {ok} (calibrate, live)."""
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
    if phase == "fixture":
        runner_case("S-real-calls-zero", (checks.get("fixtureProof") or {}).get("ok") is True)
    else:
        runner_case("JL-count", (checks.get("liveCount") or {}).get("ok") is True)
        runner_case("JL-calibration", (checks.get("calibration") or {}).get("ok") is True)
    parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
             "cases": all(v["status"] == "pass" for v in cases.values()),
             "environment": environment_ok(environment, phase), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "notObserved": not_observed(phase), "verdictParts": parts,
            "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


class Runner(m18.Runner):
    """The M18/M17/M15 runner protections (outside /tmp, git-ignored artifacts, free ports, build stamp, mw path check,
    allowlisted env, redacted export, loopback API helpers) with the M24 setup, fixture server, guarded live phases,
    evidence searches and ledger."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        phase = getattr(args, "phase", "fixture")
        out = args.out or str(code / "docs/qa" / f"m24-jev-{stamp}" / f"acceptance-{phase}")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.phase = phase
        self.live_calls = int(getattr(args, "live_calls", 0))
        if self.phase not in PHASES:
            raise SystemExit(f"--phase must be one of {PHASES}")
        if self.phase == "calibrate" and self.live_calls < 1:
            raise SystemExit("--phase calibrate makes one real call: it needs --live-calls >= 1")
        if self.phase == "live" and self.live_calls < 2:
            raise SystemExit("--phase live sends the plan entries 2..N: it needs --live-calls N >= 2")
        self.regressions = bool(getattr(args, "regressions", False))
        kbase = getattr(args, "kbase", None)
        self.kbase = Path(kbase).resolve() if kbase else None
        if self.regressions and self.phase != "fixture":
            raise SystemExit("--regressions runs after the fixture phase only (live phases spend real calls)")
        if self.regressions and (self.kbase is None or not (self.kbase / "ref/manifest.json").is_file()):
            raise SystemExit("--regressions needs --kbase <kbase_kinase checkout with ref/manifest.json> "
                             "(the M20, M16 and M15 regressions import reference snapshots)")
        self.control = self.root / "fixture-control"
        self.state_path = self.root / "live-state.json"
        self.checks: dict = {}

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m24_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- services ----------------------------------------------------------------------------
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
                                                                               "scripts")}
        self.state.setdefault("services", []).append({"name": "fixture-backend", "runs": str(self.runs),
                                                      "control": str(self.control), "startedAt": now()})
        self.save()

    def capabilities_ready(self) -> bool:
        methods = {name: self.capability(name) for name in ("ligand_candidates", "mutation_candidates", "jev_choice")}
        for key, name in (("ligandAvailable", "ligand_candidates"), ("mutationAvailable", "mutation_candidates"),
                          ("jevAvailable", "jev_choice")):
            self.environment[key] = methods[name].get("available") is True
        self.record("environment-capability", "pass" if all(
            self.environment[key] for key in ("ligandAvailable", "mutationAvailable", "jevAvailable")) else "fail",
            capability={name: {k: value.get(k) for k in ("available", "status", "reason_code")}
                        for name, value in methods.items()})
        return all(self.environment[key] for key in ("ligandAvailable", "mutationAvailable", "jevAvailable"))

    # ----- candidate sets over the loopback API (real M17 jobs, real M20 tool) -----------------
    def checked(self, label: str, status: int, body: object, want: tuple[int, ...] = (200, 201)) -> dict:
        if status not in want or not isinstance(body, dict):
            raise RuntimeError(f"{label}: HTTP {status} {json.dumps(body)[:600]}")
        return body

    def command(self, run: str, tool: str, args: dict) -> dict:
        status, body = self.api("POST", f"/runs/{run}/commands", {"tool": tool, "args": args})
        body = self.checked(f"{tool}", status, body)
        if body.get("ok") is not True:
            raise RuntimeError(f"{tool}: {json.dumps(body)[:600]}")
        return body["handle"]

    def job(self, run: str, protocol: str, args: dict) -> dict:
        status, job = self.api("POST", f"/runs/{run}/jobs", {"protocol_id": protocol, "args": args, "timeout_s": 120})
        job_id = self.checked(f"{protocol} submit", status, job)["job_id"]
        status, started = self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        if status == 409 and isinstance(started, dict) and "approval" in started:
            self.checked(f"{protocol} approve", *self.api("POST", f"/runs/{run}/jobs/approve"))
            self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        deadline = time.monotonic() + SETUP_TIMEOUT_S
        while time.monotonic() < deadline:
            _, job = self.api("GET", f"/runs/{run}/jobs/{job_id}")
            if job.get("status") not in ("queued", "claimed", "running"):
                break
            time.sleep(1)
        if job.get("status") != "done":
            raise RuntimeError(f"{protocol}: job {job_id} ended {job.get('status')} {job.get('failure')}")
        return job

    def ligand_set(self, run: str) -> dict:
        handles = {}
        for kind, rel, name in (("ligand_sdf", PARENT, "parent.sdf"), ("building_blocks_smiles", BLOCKS, "blocks.smi")):
            status, body = self.api("POST", f"/runs/{run}/chemical/imports?kind={kind}&filename={name}",
                                    (self.code / rel).read_bytes(), "application/octet-stream")
            handles[kind] = self.checked(f"import {kind}", status, body)["handle"]
        inspected = self.job(run, "rdkit_inspect_v1", {"parent_sdf_handle": handles["ligand_sdf"],
                                                       "block_handles": [handles["building_blocks_smiles"]]})
        inspection = inspected["artifacts"]["ligand_inspection"]
        enumerated = self.job(run, "rdkit_enumerate_v1", {"inspection_handle": inspection, "site_atoms": [SITE_ATOM],
                                                          "use_fixed": True})
        handle = enumerated["artifacts"]["ligand_candidate_set"]
        status, rows = self.api("GET", f"/runs/{run}/ligand/candidate_sets/rows?handle="
                                f"{urllib.parse.quote(handle, safe='')}&offset=0&limit=100")
        count = self.checked("ligand rows", status, rows)["total"]
        if count != LIGAND_CANDIDATES:
            raise RuntimeError(f"ligand set has {count} candidates, expected {LIGAND_CANDIDATES}")
        return {"handle": handle, "candidates": count, "inspection": inspection,
                "inputs": {"parent": str(PARENT), "blocks": str(BLOCKS), "site_atoms": [SITE_ATOM], "use_fixed": True}}

    def mutation_set(self, run: str, key: str, expected: dict) -> dict:
        rel, name, count = STRUCTURES[key]
        status, upload = self.api("POST", f"/runs/{run}/uploads?filename={rel.name}", (self.code / rel).read_bytes(),
                                  "application/octet-stream")
        upload = self.checked(f"upload {name}", status, upload)
        loaded = self.command(run, "load_structure", {"source": upload["upload_id"], "model_index": 0})
        prepared = self.command(run, "prepare_structure", {"structure": loaded["handle"]})
        residues = top_residues(expected, name, count)
        made = self.command(run, "generate_mutation_candidates", {
            "structure": prepared["handle"], "sources": {"pocket": None, "ligand_shell": None, "residues": residues},
            "allowed_residues": ["A"]})
        candidates = made["summary"]["candidates"]
        if candidates < 21:
            raise RuntimeError(f"{name} set has {candidates} candidates (< 21)")
        return {"handle": made["handle"], "candidates": candidates, "structure": prepared["handle"],
                "inputs": {"structure": str(rel), "positions": len(residues), "allowed_residues": ["A"]}}

    def setup_runs(self, shapes: dict[str, tuple[str, ...]], label: str, keys: dict[str, str] | None = None) -> Path:
        """Fresh runs with their candidate sets; returns the setup file the harness reads."""
        expected = json.loads((self.code / NEIGHBORS).read_text())
        runs = {}
        for key, sets in shapes.items():
            _, made = self.api("POST", "/runs", {"goal": f"M24 JEV QA {label} {key}", "context": [], "dry_run": False,
                                                 "egress": "local_only"})
            run = self.checked("new run", 201, made)["run_id"]
            found = {}
            for item in sets:
                found[item] = self.ligand_set(run) if item == "ligand" else self.mutation_set(run, item, expected)
            runs[(keys or {}).get(key, key)] = {"run": run, "sets": found}
        setup = {"schema": "m24_jev_setup@1", "label": label, "runs": runs, "madeAt": now()}
        target = self.artifacts / f"setup-{label}.json"
        target.write_text(json.dumps(setup, indent=2) + "\n")
        self.record(f"setup-{label}", "pass", runs={key: {"run": value["run"], "sets": {
            name: item["candidates"] for name, item in value["sets"].items()}} for key, value in runs.items()})
        return target

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

    def write_plan(self, name: str, plan: dict) -> Path:
        target = self.artifacts / f"plan-{name}.json"
        target.write_text(json.dumps(plan, indent=2) + "\n")
        return target

    def fixture_calls(self) -> list[dict]:
        file = self.control / "calls.jsonl"
        return [json.loads(line) for line in file.read_text().splitlines() if line] if file.exists() else []

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
        scan = self.key_scan([])
        self.environment["keyAvailable"] = scan.get("keyAvailable") is True
        self.record("key-present", "pass" if self.environment["keyAvailable"] else "fail",
                    keyAvailable=self.environment["keyAvailable"])
        return self.environment["keyAvailable"]

    # ----- phases ------------------------------------------------------------------------------
    def run_fixture(self) -> None:
        self.start_fixture_backend()
        if not self.capabilities_ready():
            for step in PHASE_STEPS["fixture"]:
                self.missing_prerequisite(step, "backend reports a needed method unavailable")
            return
        setup = self.setup_runs(FIXTURE_RUNS, "fixture")
        rehearsal = self.setup_runs({"R1": LIVE_RUNS["L1"], "R2": LIVE_RUNS["L2"]}, "rehearsal",
                                    keys={"R1": "L1", "R2": "L2"})
        self.environment["setup"] = True
        self.flow("jev-fixture", "fixture", ["--control", str(self.control), "--setup", str(setup)])
        base = dispatch_total(count_events(self.runs))
        plan = self.write_plan("rehearsal", plan_for("rehearsal", base, 0, base=base))
        self.flow("jev-rehearsal", "live", ["--control", str(self.control), "--setup", str(rehearsal), "--plan", str(plan)],
                  limit=base + len(LIVE_PLAN))
        counts = count_events(self.runs)
        self.checks["events"] = counts
        server = json.loads((self.control / "server.json").read_text()) if (self.control / "server.json").exists() else None
        self.checks["fixtureProof"] = fixture_proof(server, self.fixture_calls(), counts)
        self.record("fixture-proof", "pass" if self.checks["fixtureProof"]["ok"] else "fail", **self.checks["fixtureProof"])

    def run_calibrate(self) -> None:
        self.start_backend_at("backend", self.code, self.runs)
        if not (self.capabilities_ready() and self.key_available()):
            self.missing_prerequisite("jev-calibrate", "a needed method is unavailable or the key is absent (no call made)")
            return
        made = self.setup_runs(LIVE_RUNS, "live")
        setup = self.root / "live-setup.json"          # kept with the root: the live phase reads it from there
        setup.write_text(made.read_text())
        self.environment["setup"] = True
        plan = self.write_plan("calibrate", plan_for("calibrate", 0, self.live_calls))
        row = self.flow("jev-calibrate", "live", ["--setup", str(setup), "--plan", str(plan)], limit=1)
        counts = count_events(self.runs)
        self.checks["events"] = counts
        self.checks["liveCount"] = {"ok": live_count_ok(counts, 1), "limit": 1, "counts": counts}
        self.checks["calibration"] = calibration(row)
        self.state_path.write_text(json.dumps({"schema": "m24_jev_live_state@1", "setup": str(setup),
                                               "calibration": self.checks["calibration"], "counts": counts,
                                               "liveCalls": self.live_calls, "livePhaseRan": False,
                                               "writtenAt": now()}, indent=2) + "\n")
        self.record("calibration", "pass" if self.checks["calibration"]["ok"] else "fail", **self.checks["calibration"])

    def run_live(self) -> None:
        state = json.loads(self.state_path.read_text())
        self.checks["calibration"] = state.get("calibration") or {"ok": False}
        self.start_backend_at("backend", self.code, self.runs)
        if not (self.capabilities_ready() and self.key_available()):
            self.missing_prerequisite("jev-live", "a needed method is unavailable or the key is absent (no call made)")
            return
        used = dispatch_total(count_events(self.runs))
        plan = plan_for("live", used, self.live_calls)
        state["livePhaseRan"] = True
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")
        if not plan["entries"]:
            self.missing_prerequisite("jev-live", f"no plan entry left: {used} dispatch events already, --live-calls "
                                                  f"{self.live_calls}")
        else:
            self.flow("jev-live", "live", ["--setup", state["setup"], "--plan", str(self.write_plan("live", plan))],
                      limit=self.live_calls)
        counts = count_events(self.runs)
        self.checks["events"] = counts
        self.checks["liveCount"] = {"ok": live_count_ok(counts, self.live_calls), "limit": self.live_calls,
                                    "counts": counts}

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
                         "dispatchCounts": row.get("dispatchCounts"), "evidenceKind": row.get("evidenceKind"),
                         "fixtureLabels": row.get("fixtureLabels", []), "controls": sorted(row.get("controls") or {}),
                         "wording": row.get("wording", []), "externalRequestCount": row.get("externalRequestCount"),
                         "partFailures": row.get("partFailures", []), "error": row.get("error"),
                         "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.phase, self.checks)
        passed = judged["passed"]
        ledger = {"schema": "m24_case_ledger@1", "phase": self.phase, "acceptanceScope": self.phase,
                  "liveCalls": self.live_calls, "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail", "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "environment": self.environment,
                  "checks": self.checks, "dispatchCapExceeded": self.state.get("dispatchCapExceeded"),
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
        proof = (ledger.get("checks") or {}).get("fixtureProof") or {}
        calib = (ledger.get("checks") or {}).get("calibration") or {}
        count = (ledger.get("checks") or {}).get("liveCount") or {}
        lines = [f"# M24 JEV 과학 전송 오프스크린 수락 QA 증거 ({ledger['phase']} 단계)", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}** (범위: {ledger['acceptanceScope']}, --live-calls "
                  f"{ledger['liveCalls']})"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 환경: M17 venv-locked {'있음' if env.get('workerPython') else '없음'} · ligand_candidates "
                  f"{env.get('ligandAvailable')} · mutation_candidates {env.get('mutationAvailable')} · jev_choice "
                  f"{env.get('jevAvailable')} · fixture 서버 {env.get('fixtureServer')} · 키 존재(불리언) "
                  f"{env.get('keyAvailable')}"),
                 ("- 입력: 공개 1UBQ·1MQ4(`backend/tests/fixtures/public_*.cif`, 이웃 수가 많은 Ala 아닌 잔기 22·24곳, A로만 치환한 "
                  "실제 M20 후보 집합), 공개 파생 부모 + 합성 표시 작은 block 목록의 실제 M17 후보 10개(부위 22, 고정 교체)."),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 브라우저 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", ""]
        if ledger["phase"] == "fixture":
            lines += [(f"- 실호출: 0회. fixture 서버(SCIENCE_GATE = 스크립트된 httpx.MockTransport)만 썼고, dispatch 이벤트 "
                       f"{proof.get('dispatchEvents')}개 = fixture transport 호출 {proof.get('fixtureTransportCalls')}개, "
                       f"response_received 감사 {proof.get('responseAudits')}개 = 응답한 호출 {proof.get('answeredCalls')}개."), ""]
        else:
            lines += [(f"- 실호출 계수(모든 QA run): {json.dumps(count.get('counts'), ensure_ascii=False)} · 한도 "
                       f"{count.get('limit')} · 판정 {count.get('ok')}"),
                      (f"- 첫 실호출 보정: {json.dumps(calib, ensure_ascii=False)}"), ""]
        lines += [("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                   "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다. "
                   "키·헤더·원시 오류는 기록하지 않는다."), "",
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
                  ".venv/bin/python scripts/m24_offscreen_acceptance.py --root runs/m24-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m24-acceptance/<label> \\",
                  "    --out docs/qa/m24-jev-<YYYYMMDD>/acceptance-fixture   # --phase fixture (실호출 0)",
                  "# 실호출(사용자 할당 안에서만): 새 --root로 --phase calibrate --live-calls N, 이어서 같은 --root로",
                  "# --phase live --live-calls N (N <= 6, run당 3회 이하)",
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
        if self.phase == "live":
            if not self.state_path.is_file():
                raise SystemExit(f"--phase live needs the calibrate root (no {self.state_path})")
            state = json.loads(self.state_path.read_text())
            if state.get("livePhaseRan"):
                raise SystemExit("the live phase already ran on this root (no second attempt, no new calls)")
            if (state.get("calibration") or {}).get("ok") is not True:
                raise SystemExit("the calibrate phase did not pass on this root: no further real call")
            self.environment["liveState"] = True
        else:
            for folder in (self.runs, self.control):
                if folder.exists() and any(folder.iterdir()):
                    raise SystemExit(f"{folder} is not fresh; choose a new --root")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        worker = self.code / WORKER_PYTHON
        self.environment["workerPython"] = worker.is_file()
        self.record("environment", "pass" if worker.is_file() else "fail", workerPython=str(WORKER_PYTHON),
                    present=worker.is_file())
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
                                   FLOW, "driver.cjs", "main.cjs")},
                               "fixtureServerSha256": m13.sha_file(self.code / FIXTURE_SERVER),
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        self.runs.mkdir(parents=True, exist_ok=True)
        self.reference.mkdir(parents=True, exist_ok=True)
        try:
            self.start_frontend()
            {"fixture": self.run_fixture, "calibrate": self.run_calibrate, "live": self.run_live}[self.phase]()
        finally:
            self.stop_all()
            self.state["environment"] = self.environment
            self.save()
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
                        "frontend/tests/offscreen/artifacts/m24-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m24-jev-<YYYYMMDD>/acceptance-<phase>)")
    parser.add_argument("--phase", choices=PHASES, default="fixture", help="fixture (0 real calls), calibrate (the "
                        "first real call), live (the rest of the allocation)")
    parser.add_argument("--live-calls", type=live_calls_arg, default=0, help=f"real OpenRouter calls allowed in total "
                        f"(0..{MAX_LIVE_CALLS}, default 0); calibrate needs >= 1, live >= 2")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="fixture phase only: afterwards run the M23, M22, "
                        "M21, M20, M19, M18, M17, M16, M15, M14 and M13 (all phases) runners, each with its own fresh "
                        "root, artifacts and out folder")
    parser.add_argument("--kbase", help="local kbase_kinase checkout (read only, absolute path); required with "
                        "--regressions (passed to the M20, M16 and M15 regressions)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
