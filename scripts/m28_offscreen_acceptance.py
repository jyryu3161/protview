#!/usr/bin/env python3
"""Run the M28 end-to-end real-data acceptance (.dryforge/spec.md §3–§7).

One command per phase, given a code root (default: this repository; run from the main checkout, where .deps and
frontend/node_modules are). Like the M27 runner it needs free 8000/3000 ports, builds the frontend when needed
(typecheck, then build, never concurrently), starts its own loopback services (``next start`` on 127.0.0.1:3000 and one
backend on 127.0.0.1:8000 for the phase, ``PYTHONPATH=<code root>/backend``, ``MW_RUNS_DIR=<root>/<phase>/runs``,
``MW_REFERENCE_DIR`` = a read-only copy of --m15-reference, ``MW_REACTION_REFERENCE_DIR`` = an isolated copy of
--reaction-set, ``MW_PRECEDENT_REFERENCE_DIR`` = an isolated folder the branch-A module installs into from --kbase),
runs the registered branch modules (``BRANCH_REGISTRY``: ``scripts/m28_branch_{a,b,c}.py``) one after another, each in
its own new run, and writes the case ledger ``m28_case_ledger@1`` of the phase.

Phases (``--phase``):
  fixture  (default) every case of spec §4 (A1–A8, B1–B8, C1–C7, X1-A/B/C, X2–X6). The backend is the M25 fixture
           server (backend/tests/offscreen_jev_loop_fixture/server.py: the product app with only SCIENCE_GATE over a
           scripted httpx.MockTransport and a placeholder credential; it never reads .env). Real calls 0.
  live     a NEW root: the branch modules rebuild the prerequisite state (L-pre-B2/B3/B4, L-pre-C2) with the same case
           code and send ONE exploit round of the ligand loop (L-B7) and ONE explore round of the protein loop (L-C6)
           through the product backend (the real SCIENCE_GATE), runs B and C apart. --live-calls N (1..2) is required
           and the real live phase always runs both branches (T11 R1: the plan is both rounds; --branches with fewer
           is refused, a subset is for the rehearsal only).
           Before anything starts the repository ledger runs/m28-live-ledger.json (main checkout, git-ignored, found
           through the git common dir; the M24 and M25 ledgers are never read) must be readable and its total (every
           recorded root, recounted from the dispatch events) plus this plan must stay within 2, and --live-calls
           within what it leaves; every ledger read-and-write holds the lock file next to it; the ledger is never
           deleted or rewound (a lock file left without its ledger refuses the phase). An unfinished phase reserves
           its planned calls, and the runtime cap of its harnesses is exactly that reservation (min(--live-calls,
           planned)); each branch also passes its own round's limit (the dispatch events already counted + 1). While
           a harness runs the dispatch events are counted and it and the backend are stopped at once past the cap.
           Results per round: completed | provider_failed | product_failed | not_sent (spec §6.3,
           m28_common.live_outcome). The dispatch events counted before and after each branch decide whether its round
           was sent (T11 R2): a dispatch whose round has no completed result (the branch raised, the harness died or
           was stopped, no evidence) is product_failed. No retry, no new run; a round that was dispatched and did not
           complete ends the plan (the next branch gets ``send_allowed`` false and its harness is stopped at a new
           dispatch).
  --rehearse (live only) the same live code path against the fixture server (the product backend is never started),
           the ledger is <root>/rehearsal-live-ledger.json, --live-calls defaults to 2, real calls 0, and the product
           key resolver is never run (the key-present step is skipped; the evidence search looks for the placeholders
           and key patterns only). A rehearsal ledger never says acceptance true (``rehearsalPassed`` says whether it
           passed). A rehearsal may run one branch (T7 / T8 rehearsed one at a time): its plan counts the rounds of the
           selected branches only (b → L-B7, c → L-C6).

``acceptance`` (spec §3.1, §5): every required case of the phase is pass, or not_observed with a closed reason
(no_public_input, unreachable_by_ui, engine_unavailable_by_design) and a named covering unit test; the true cases
(fixture: X1-A/B/C, X2–X6; live: every L case) pass; all of the phase's branches ran (``--branches`` with fewer is
never acceptance); the build was stamped from the current frontend source; nothing is left (workers, fixture server,
Electron, 8000/3000 listeners); browser non-loopback requests 0 and provider calls 0 (fixture) / live calls within the
ledger (live); every ``run_*`` of the phase's runs folder was claimed by a branch (T11: all are audited); and the
searches over the exported evidence found no key string, placeholder, real kbase text or absolute path.

Evidence (--out, text only, decision 0020): README, summary, cases, SHA256SUMS, binary-artifacts.json (git-ignored
files with path, size and SHA-256 only), evidence/ (ledger, rows, plans). Screenshots, paint frames, downloads,
failure panels, text above 256 KiB, the X4 lines as found (x4-lines.json; x4-scan.json keeps hashes, cases, line kinds,
byte lengths and reasons only) and any text with real kbase strings, a key, a placeholder or an absolute path stay in
--artifacts (git-ignored). The root must be new and outside /tmp. This script never imports mw (the fixed
sentences come from the subprocess scripts/m28_export_fixed_sentences.py), never calls a limit-raising route and
never posts to a /jev route (approvals, raises and sends are the harness's clicks).

Usage (main checkout root, 8000/3000 free):
  .venv/bin/python scripts/m28_offscreen_acceptance.py --root runs/m28-fixture-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m28-final/<label> [--phase fixture|live] [--branches a,b,c] \\
      [--live-calls N] [--rehearse] [--kbase <abs>/kbase_kinase] [--m15-reference .deps/reference] \\
      [--reaction-set .deps/reaction_qa/import2] [--out docs/qa/m28-final-<YYYYMMDD>/acceptance-<phase>] \\
      [--build auto|always|never] [--code-root <dir>]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Build stamp, env allowlist, port and hash helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Service URLs of the M15 runner.
import m15_offscreen_acceptance as m15

# Runner protections (fresh root outside /tmp, git-ignored artifacts, build, services, loopback API) through M18.
import m18_offscreen_acceptance as m18

# Event counting, harness watch, process-group cleanup, ledger lock and file write, key scan, .env status and the
# fixture-server record checks of the M25 runner.
import m25_offscreen_acceptance as m25

# Real kbase text matching and the precedent-set strings of the M27 runner (memory only).
import m27_offscreen_acceptance as m27

# The branch modules (standard library and m28_common only; none of them imports mw).
import m28_branch_a as branch_a
import m28_branch_b as branch_b
import m28_branch_c as branch_c
import m28_common as c
import m28_trace_audit as audit

REPO = Path(__file__).resolve().parents[1]
PHASES = ("fixture", "live")
PHASE_BRANCHES = {"fixture": ("a", "b", "c"), "live": ("b", "c")}
MAX_LIVE_CALLS = 2                       # the user's allocation of real JEV calls for M28 (spec §6.1)
LEDGER_NAME = "m28-live-ledger.json"
LEDGER_SCHEMA = "m28_live_ledger@1"
REHEARSAL_LEDGER_NAME = "rehearsal-live-ledger.json"
LIVE_RUNS = Path("live") / "runs"        # a root's live runs folder (the ledger recounts its dispatch events)
LIVE_ROUND_OF = {"b": "L-B7", "c": "L-C6"}
STEP_TIMEOUT_S = 7200
EXPORTER = Path("scripts/m28_export_fixed_sentences.py")
FIXTURE_SERVER = m25.FIXTURE_SERVER
SENTINELS = (m25.SENTINEL, "m24-fixture-sentinel-placeholder-not-a-key")
DEFAULT_FOLDERS = (Path(".deps/precedent_reference"), Path(".deps/reaction_reference"))
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt", ".html"}
MAX_TEXT_BYTES = 256 * 1024
LEDGER_NAMES = {"case-ledger.json", "ledger-row.json"}
WORKERS = (*m25.WORKERS, "docking_batch_worker.py", "ligand_ga_worker.py", "sequence_ga_worker.py",
           "sequence_model_worker.py", "mutation_model_worker.py")
# Key strings (patterns, never a value) and user absolute paths (a home folder; the runner writes <repo> / <home>)
# that committed evidence must not hold.
KEY_PATTERNS = re.compile(r"sk-or-v1-[0-9A-Za-z]{16,}|\bsk-[0-9A-Za-z_-]{24,}|Bearer\s+[0-9A-Za-z._-]{16,}|"
                          r"OPENROUTER_API_KEY\s*=\s*\S+")
ABSOLUTE_PATH = re.compile(r"(?<![\w.:/<-])/(?:Users|home)/[^\s\"'<>`|)/]+")
# Runner-written analysis files the evidence wording scan leaves out (they quote what they found or list fixed text).
X4_LINES = "x4-lines.json"              # the X4 lines as found (raw text): git-ignored artifacts only, never exported
WORDING_SKIP = {"x4-scan.json", X4_LINES, "fixed-sentences.json", "trace-audit.json"}
# X4 line exceptions (spec §4.4 X4; coordinating-session decision of T9). Each entry is ONE line kind the X4 core words
# meet in product text that makes no claim, keyed by the SHA-256 of the normalized line (``line``), of the line with its
# numbers written # (``template``: numbers that differ per run) or of the text before the first ": " (``label``: only
# that label is excepted, the rest of the line is still checked). Every entry names its line kind, the cases it was
# seen in, the code that writes it (found in the source, T9) and its reason. No raw line text here or in committed
# evidence (reference text such as M-CSA roles stays in the git-ignored artifacts). Reviewed by the independent evidence
# review. Not here: product fixed sentences (exported by scripts/m28_export_fixed_sentences.py) and JSON request
# bodies (checked string by string).
_FRONTEND_NEGATION = ("프런트엔드 고정 부정문: 이 화면 값이 그 해석의 근거가 아님을 밝히는 제품 문장이며 핵심어는 부정 "
                      "대상으로만 나온다(제품 문장, 단언 아님)")
_POCKET_LABEL = ("fpocket이 매기는 공동 번호 라벨(엔진 고유 필드 이름)을 제품이 그대로 쓰는 줄: 엔진 출력의 번호이며 "
                 "제품의 평가나 주장이 아니다")
X4_EXCEPTIONS: dict[str, dict] = {
    "4d1d82bfdc9972fde983789777c4ad74f27d41b684fb72d9ba6589d6fe859565": {
        "match": "template", "kind": "fpocket_rank_label", "cases": ["A4"],
        "source": "frontend/app/page.tsx:1690 (뷰어 오버레이 이름표)", "reason": _POCKET_LABEL},
    "a34f61a2588531732fe3e17aaeadcd22de674a23be8274df49e09424ee468025": {
        "match": "template", "kind": "fpocket_rank_label", "cases": ["A4"],
        "source": "frontend/src/components/PocketPanel.tsx:497 (오버레이 표시 확인 줄)", "reason": _POCKET_LABEL},
    "e9796c94fd14a53e8f8df55196dac7f99daa368f8ae73b39716381521587716f": {
        "match": "line", "kind": "fpocket_rank_label", "cases": ["A4", "A6"],
        "source": "frontend/src/components/PocketPanel.tsx:461 (포켓 표 머리글, CSS 대문자)", "reason": _POCKET_LABEL},
    "23e22c71350bb5340191bed6f15f94939caa3521aceff970f9df6d7a5f51ce0e": {
        "match": "line", "kind": "fpocket_rank_label", "cases": ["A4"],
        "source": "backend/mw/pocket_reports.py:264 (포켓 보고서 표 머리글)", "reason": _POCKET_LABEL},
    "f6cce20dc517d4dd0ea5574992d3c0c159bdde9668a4b73738f1efa53d9b2021": {
        "match": "label", "kind": "fpocket_rank_label", "cases": ["A4"],
        "source": "backend/mw/pocket_reports.py:276 (주변 잔기 목록 줄의 공동 번호 머리; 뒤의 잔기 목록은 계속 검사)",
        "reason": _POCKET_LABEL + ". 잔기 목록은 fpocket 실행마다 달라 줄 전체가 아니라 머리 라벨만 예외"},
    "6e31139099f7324f5c65bf328a2df7a593f2f9ef65d76193638203e42c536029": {
        "match": "template", "kind": "fpocket_rank_label", "cases": ["A4"],
        "source": "backend/mw/pocket_reports.py:281 (보고서 끝 JSON 안내, 주장 수는 실행마다 다름)",
        "reason": "포켓 보고서가 JSON의 공동 번호 선택자(fpocket 필드 이름)를 안내하는 제품 문장"},
    "6f978dafb0f0ff00a19b27b0fffb8403d75be8f5ea4a23b1ec0776acaf3ad3d4": {
        "match": "line", "kind": "frontend_fixed_sentence", "cases": ["A2", "A3", "A4", "B1", "C2"],
        "source": "frontend/src/lib/pockets.ts:101 LIMITATION_NOTE + :103 NONDETERMINISM_NOTE (한 줄로 표시)",
        "reason": _FRONTEND_NEGATION},
    "01c5879e8930426a2a3f46e66d77883a319c76e29993975f3f5155817cc1a559": {
        "match": "line", "kind": "frontend_fixed_sentence", "cases": ["A2", "A3", "A4", "A6", "C2"],
        "source": "frontend/src/lib/site-annotation.ts:27 PANEL_LEGEND_TEXT", "reason": _FRONTEND_NEGATION},
    "3d7233ea3db963baca822963b231dc8b2cccfa15e29a115e3ee8b69d9bdb4bec": {
        "match": "line", "kind": "frontend_fixed_sentence", "cases": ["A2", "A4", "A6"],
        "source": "frontend/app/page.tsx:1878", "reason": _FRONTEND_NEGATION},
    "c515bcae36c113886bf0049eff02cc6c10aba08cb1314339b3324980d5e40a66": {
        "match": "template", "kind": "frontend_fixed_sentence", "cases": ["A3"],
        "source": "frontend/app/page.tsx:1919", "reason": _FRONTEND_NEGATION},
    "2b8eefeb282e582da5a0d0c8bb11b9dfbb361bf1e9232c67a962fe64dbfba85a": {
        "match": "template", "kind": "frontend_fixed_sentence", "cases": ["A2", "A3", "A4", "C2"],
        "source": "frontend/app/page.tsx:1961 (OpenMM 방법 안내)", "reason": _FRONTEND_NEGATION},
    "b56ed9a4654dba9c88adc4dfcdfa7d72d00a7166e9f89e88f6aa6ef737715e58": {
        "match": "template", "kind": "frontend_fixed_sentence", "cases": ["B3"],
        "source": "frontend/src/lib/docking.ts:80 CONTACT_NOTE", "reason": _FRONTEND_NEGATION},
    "335d7ddba745a5bbe49c15c5cb9e8048b6468df52349936d1fe84255dbbcd4ad": {
        "match": "template", "kind": "frontend_composed_line", "cases": ["A2", "A3", "A4", "C2"],
        "source": "frontend/app/page.tsx:2060 (방법 id · 알고리즘 · 단위 · backend/mw/tools/sasa.py:61 limitations)",
        "reason": "화면이 SASA 방법 id·조각 수·단위와 제품 한계 문장(내보낸 인라인 고정 문장)을 한 줄로 합친 것: "
                  "핵심어는 그 한계 문장의 부정 대상으로만 나온다"},
    "a1a92b6f0d63cafe9425b3edd4d30d5564a6aa6bf1a75e4891fd4a33093b5b91": {
        "match": "template", "kind": "product_criterion_definition", "cases": ["B1"],
        "source": "backend/mw/chemical_reports.py:152 (ProLIF 범주 판정 기준, 기준값이 들어간 f-string)",
        "reason": "M11 화학 상호작용(ProLIF 고유 판정)의 해당 범주 판정 기준(D···A 거리·D–H···A 각도) 정의 줄: 기하 "
                  "접촉에 대한 말이 아니고 값의 단언도 아니다"},
    "66df641465c349154fc87fe7aa03fb79e82e4ca525f101d6b5bff9177d9101c8": {
        "match": "line", "kind": "reference_text", "cases": ["A8"],
        "source": "backend/mw/reaction_knowledge_reports.py:700-711 (M-CSA 행 표: 1A30 A GLY 27, 항목 175)",
        "reason": "M-CSA 역할 원문(roles_summary·roles, 참조값, 계산 아님): 촉매 잔기의 문헌 역할 어휘이며 기하 접촉에 "
                  "대한 판정이 아니다"},
    "2f43624e7831ccc76770ccae749132af9bfc582f68a4db42e7af2bcd2a089299": {
        "match": "line", "kind": "reference_text", "cases": ["A8"],
        "source": "backend/mw/reaction_knowledge_reports.py:700-711 (M-CSA 행 표: 1A30 B GLY 27, 항목 175)",
        "reason": "M-CSA 역할 원문(참조값, 계산 아님): 촉매 잔기의 문헌 역할 어휘이며 기하 접촉에 대한 판정이 아니다"},
    "506d98fbbf28fa3a5e25f1406224d99da2d5288c0331e7ce3b300e3defdb2bd9": {
        "match": "line", "kind": "reference_text", "cases": ["A8"],
        "source": "backend/mw/reaction_knowledge_reports.py:700-711 (M-CSA 행 표: 1A30 A ASP 25, 항목 175)",
        "reason": "M-CSA 역할 원문(참조값, 계산 아님): 촉매 잔기의 문헌 역할 어휘이며 기하 접촉에 대한 판정이 아니다"},
    "277d395ccd8e804186db3011d540b89ecbb0a614501da2a146166cc81a69fd8b": {
        "match": "line", "kind": "reference_text", "cases": ["A8"],
        "source": "backend/mw/reaction_knowledge_reports.py:700-711 (M-CSA 행 표: 1A30 B ASP 25, 항목 175)",
        "reason": "M-CSA 역할 원문(참조값, 계산 아님): 촉매 잔기의 문헌 역할 어휘이며 기하 접촉에 대한 판정이 아니다"},
    "c6f060a6e54833bbaf0be7bd961279e21936c3adf2ed3b535c0ce1544e9f6edd": {
        "match": "line", "kind": "reference_text", "cases": ["A8"],
        "source": "backend/mw/reaction_knowledge_reports.py:700-711 (M-CSA 행 표: 1S9I A ASP 194, 항목 282)",
        "reason": "M-CSA 역할 원문(참조값, 계산 아님): 촉매 잔기의 문헌 역할 어휘이며 기하 접촉에 대한 판정이 아니다"},
}
# The branch modules: branch → run(ctx) -> m28_common.BranchResult.
BRANCH_REGISTRY: dict[str, Callable[[c.BranchContext], c.BranchResult]] = {
    "a": branch_a.run, "b": branch_b.run, "c": branch_c.run}
# Kinds whose product reopen does not recompute (trace audit partialProductRecheck, handoff decision 5) → the case
# whose independent expectations supplement the audit for that kind.
AUDIT_SUPPLEMENTS = {"inspection": "A2", "interface_sasa": "A3"}

# Live plan (spec §6; T1 (e) §5): run B = L-pre-B2 (M17 inspect + enumerate, 2 units) + L-pre-B3 (M18, 1) + L-pre-B4
# (M19: 3 new rows + the parent row, 4) then L-B7 (1); run C = L-pre-C2 (at most M7 + M21, 2) then L-C6 (model + dock,
# 2). Activity time: the round's own need (ligand 300 s, protein 420 s) plus an upper bound of the setup's activity
# (T1 (e) 1 measurements with margin); external tokens and USD by the widest measured body (the M25 numbers).
LIVE_PLAN = (
    {"id": "L-B7", "run": "B", "branch": "ligand", "goal": "exploit", "sends": 1},
    {"id": "L-C6", "run": "C", "branch": "protein", "goal": "explore", "sends": 1},
)
LIVE_SETUP = {"B": {"expensive_units": 7, "wall_clock_s": 600}, "C": {"expensive_units": 2, "wall_clock_s": 240}}
LIVE_STEP = {"ligand": {"expensive_units": 1, "wall_clock_s": 300},
             "protein": {"expensive_units": 2, "wall_clock_s": 420}}
RUN_BUDGET = dict(m25.RUN_BUDGET)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------------------------------- arguments
def branches_arg(text: str) -> list[str]:
    names = [part.strip().lower() for part in text.split(",") if part.strip()]
    if not names or len(set(names)) != len(names) or any(name not in c.BRANCHES for name in names):
        raise argparse.ArgumentTypeError(f"--branches takes a subset of a,b,c (got {text!r})")
    return [name for name in c.BRANCHES if name in names]


def live_calls_arg(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--live-calls must be an integer 1..{MAX_LIVE_CALLS}") from exc
    if not 1 <= value <= MAX_LIVE_CALLS:
        raise argparse.ArgumentTypeError(f"--live-calls must be 1..{MAX_LIVE_CALLS} (got {value}); the allocation is "
                                         f"{MAX_LIVE_CALLS} real calls in total")
    return value


def under_tmp(path: Path) -> bool:
    text = str(Path(path).resolve())
    return any(text == bad or text.startswith(bad + "/") for bad in ("/tmp", "/private/tmp"))


# ---------------------------------------------------------------------------------------------------- live ledger
class LedgerError(Exception):
    """The real-call ledger cannot be found, read, trusted or counted: the live phase is refused."""


def ledger_path(code: Path = REPO) -> Path:
    """``runs/m28-live-ledger.json`` of the main checkout (git common dir, so a worktree shares it); it must be a
    git-ignored place (the m25 runner's ledger_path, with the M28 name)."""
    done = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=code,
                          capture_output=True, text=True, check=False)
    if done.returncode != 0 or not done.stdout.strip():
        raise LedgerError(f"no git repository at {code}")
    main = Path(done.stdout.strip()).resolve().parent
    path = main / "runs" / LEDGER_NAME
    if subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=main, check=False).returncode != 0:
        raise LedgerError(f"the ledger place is not git-ignored: {path}")
    return path


def ledger_precheck(path: Path) -> None:
    """Before the lock is taken: a lock file without its ledger means the ledger was removed after a phase was
    recorded (the lock file is made by the first read-and-write and never removed): LedgerError, so a deleted ledger
    never rewinds the allocation (T11). Neither file = the first phase ever (fine)."""
    lock = Path(path).with_name(f"{Path(path).name}.lock")
    if lock.exists() and not Path(path).exists():
        raise LedgerError(f"the ledger's lock file is there but the ledger is not (removed or damaged): {path}")


def read_ledger(path: Path) -> dict:
    """The ledger (absent = nothing recorded yet; ledger_precheck runs before the lock); unreadable or not exactly
    ``m28_live_ledger@1``: LedgerError."""
    if not Path(path).exists():
        return {"schema": LEDGER_SCHEMA, "roots": {}}
    try:
        ledger = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise LedgerError(f"the ledger cannot be read ({exc.__class__.__name__})") from exc
    if not (isinstance(ledger, dict) and set(ledger) == {"schema", "roots"} and ledger["schema"] == LEDGER_SCHEMA
            and isinstance(ledger["roots"], dict)):
        raise LedgerError("the ledger is damaged (not an m28_live_ledger@1 object)")
    for root, entry in ledger["roots"].items():
        ok = (Path(root).is_absolute() and isinstance(entry, dict) and set(entry) == {"phases", "dispatch"}
              and isinstance(entry["phases"], list) and isinstance(entry["dispatch"], dict)
              and all(isinstance(run, str) and m25.RUN_NAME.fullmatch(run) and type(count) is int and count >= 0
                      for run, count in entry["dispatch"].items())
              and all(isinstance(item, dict) and item.get("phase") == "live" and isinstance(item.get("startedAt"), str)
                      and (item.get("finishedAt") is None or isinstance(item.get("finishedAt"), str))
                      and (item.get("finishedAt") is not None
                           or (type(item.get("planned")) is int and 0 <= item["planned"] <= MAX_LIVE_CALLS))
                      for item in entry["phases"]))
        if not ok:
            raise LedgerError(f"the ledger is damaged (root {root!r})")
    return ledger


def root_count(root: str, entry: dict) -> int:
    """Real calls of one recorded root (the m25 runner's rule): per run the larger of the recorded count and the
    dispatch events now in ``<root>/live/runs``; an unfinished phase counts at least its recorded calls plus its planned
    calls. An unfinished root whose runs folder is gone: LedgerError."""
    runs = Path(root) / LIVE_RUNS
    if runs.is_dir():
        try:
            found = {run: item["dispatch"] for run, item in m25.count_events(runs).items()}
        except (OSError, ValueError) as exc:
            raise LedgerError(f"the events of {root} cannot be counted ({exc.__class__.__name__})") from exc
    elif any(item.get("finishedAt") is None for item in entry["phases"]):
        raise LedgerError(f"an unfinished live phase of {root} has no runs folder left to count")
    else:
        found = {}
    seen = sum(max(entry["dispatch"].get(run, 0), found.get(run, 0)) for run in {*entry["dispatch"], *found})
    reserved = sum(item.get("planned", 0) for item in entry["phases"] if item.get("finishedAt") is None)
    return max(seen, sum(entry["dispatch"].values()) + reserved) if reserved else seen


def ledger_total(ledger: dict, exclude: Path | None = None) -> int:
    skip = str(Path(exclude).resolve()) if exclude is not None else None
    return sum(root_count(root, entry) for root, entry in ledger["roots"].items() if root != skip)


def ledger_admission(before_others: int, mine: int, planned: int, live_calls: int) -> str | None:
    """Why the live phase may not start (None = it may): the ledger total plus this plan passes the allocation, or
    --live-calls passes what the other roots leave."""
    if before_others + mine + planned > MAX_LIVE_CALLS:
        return (f"the ledger counts {before_others + mine} real calls (every root) and this phase plans {planned}; the "
                f"allocation is {MAX_LIVE_CALLS} in total")
    if before_others + live_calls > MAX_LIVE_CALLS:
        return (f"--live-calls {live_calls} passes what the ledger leaves ({MAX_LIVE_CALLS - before_others} after "
                f"{before_others} real calls of other roots)")
    if planned > live_calls:
        return f"this phase plans {planned} calls but --live-calls is {live_calls}"
    return None


def live_plan(branches: Iterable[str] = PHASE_BRANCHES["live"]) -> tuple[dict, ...]:
    """The rounds of the selected live branches (b → L-B7, c → L-C6): a run of one branch plans one call."""
    chosen = {str(name).lower() for name in branches}
    return tuple(entry for entry in LIVE_PLAN if entry["run"].lower() in chosen)


def live_plan_budget(plan: Iterable[dict] | None = None) -> dict:
    """Per run (B, C) the plan's needs against the run defaults (8 units, 1800 s, 120,000 tokens, USD 2.00,
    10 sends). ``None`` = the whole LIVE_PLAN, read when called (never bound at definition time)."""
    plan = LIVE_PLAN if plan is None else tuple(plan)
    runs: dict[str, dict] = {}
    for entry in plan:
        need = runs.setdefault(entry["run"], {**{axis: 0 for axis in RUN_BUDGET}, **LIVE_SETUP[entry["run"]]})
        for axis in ("expensive_units", "wall_clock_s"):
            need[axis] += LIVE_STEP[entry["branch"]][axis]
        need["external_tokens"] += entry["sends"] * m25.reserve_tokens(m25.RESERVE_BOUND_BYTES[entry["branch"]])
        need["usd"] = round(need["usd"] + entry["sends"] * m25.RESERVE_USD, 6)
        need["sends"] += entry["sends"]
    short = {run: [axis for axis, value in need.items() if value > RUN_BUDGET[axis]] for run, need in runs.items()}
    return {"ok": not any(short.values()), "needs": runs, "limits": dict(RUN_BUDGET), "short": short,
            "planned": sum(entry["sends"] for entry in plan)}


# ---------------------------------------------------------------------------------------------------- X cases
def x1_case(branch: str, events: int, opened: int, created_by_cases: int | None, refs: Iterable[str] = ()) -> dict:
    """X1-<branch> (spec §4.4, handoff 5): every report of the branch opens (``/reports/selected`` 200 per report) and
    the count of report_created + method_report_created events equals the reports the case code counted it made (the
    list route is identical to the events, so the event count alone proves nothing)."""
    case_id = f"X1-{branch.upper()}"
    detail = {"events": events, "opened": opened, "createdByCases": created_by_cases}
    ok = isinstance(created_by_cases, int) and events > 0 and events == opened == created_by_cases
    return c.case_record(case_id, "pass" if ok else "fail", None if ok else "report_count_or_open_mismatch",
                         evidence_refs=list(refs), detail=detail)


def audit_supplements(summary: dict | None, records: dict[str, dict]) -> list[dict]:
    """Every kind the audit marks partialProductRecheck with the case that supplements it (AUDIT_SUPPLEMENTS) and that
    case's status; a kind without a supplementing case has ``case`` None."""
    out = []
    for item in (summary or {}).get("partialProductRecheck") or []:
        case = AUDIT_SUPPLEMENTS.get(item.get("kind"))
        out.append({"kind": item.get("kind"), "note": item.get("note"), "supplementedBy": case,
                    "caseStatus": (records.get(case) or {}).get("status") if case else None})
    return out


def x2_case(summary: dict | None, records: dict[str, dict] | None = None, refs: Iterable[str] = (),
            unclaimed: Iterable[str] = ()) -> dict:
    """X2: the trace audit passed over every run of the phase, every run was claimed by a branch (T11: an unclaimed
    run is audited too and fails X2), and every kind the audit could check only partly (the product reopen does not
    recompute: inspection, interface_sasa) is supplemented by a passing case with independent expectations (A2, A3)."""
    supplements = audit_supplements(summary, records or {})
    unsupported = [item["kind"] for item in supplements if item["caseStatus"] != "pass"]
    unclaimed = sorted(unclaimed)
    audited = isinstance(summary, dict) and summary.get("status") == "pass"
    ok = audited and not unsupported and not unclaimed
    reason = None if ok else ("trace_audit_failed" if not audited else "unclaimed_runs" if unclaimed
                              else "partial_recheck_not_supplemented")
    return c.case_record("X2", "pass" if ok else "fail", reason, evidence_refs=list(refs),
                         detail={"status": (summary or {}).get("status"),
                                 "failures": len((summary or {}).get("failures") or []),
                                 "partialProductRecheck": supplements, "notSupplemented": unsupported,
                                 "unclaimedRuns": unclaimed})


def fixture_provider_calls(server: dict | None, calls: list[dict], dispatched: int, reads: dict | None) -> int | None:
    """Real provider calls of a fixture phase: 0 when the backend was the fixture server (MockTransport gates), every
    dispatch event is a scripted transport call that carried the placeholder and the product key resolver was never
    read; None (unknown) otherwise."""
    ok = (isinstance(server, dict) and server.get("fixture") is True
          and all("MockTransport" in str(server.get(gate)) for gate in ("scienceGate", "viewerGate", "defaultGate"))
          and dispatched == len(calls) and all(call.get("authorizationIsSentinel") is True for call in calls)
          and isinstance(reads, dict) and reads.get("productResolverReads") == 0)
    return 0 if ok else None


def x3_case(phase: str, external: dict, ledger_count: int | None = None, live_calls: int = 0,
            refs: Iterable[str] = ()) -> dict:
    """X3 / L-X3: browser non-loopback requests 0; fixture: provider calls 0; live: calls counted = ledger = dispatch
    events, at most 2 and at most --live-calls."""
    browser, provider, counted = (external.get("browser_non_loopback_requests"), external.get("provider_calls"),
                                  external.get("live_calls_counted"))
    if phase == "fixture":
        ok, case_id = browser == 0 and provider == 0, "X3"
    else:
        ok = (browser == 0 and isinstance(counted, int) and counted == ledger_count
              and counted <= min(MAX_LIVE_CALLS, live_calls))
        case_id = "L-X3"
    return c.case_record(case_id, "pass" if ok else "fail", None if ok else "external_requests",
                         evidence_refs=list(refs), detail={**external, "ledgerCount": ledger_count})


def x4_case(phase: str, scans: dict[str, dict], refs: Iterable[str] = (), without_texts: Iterable[str] = ()) -> dict:
    """X4 / L-X4: no core forbidden word outside fixed sentences and reasoned line exceptions in any scanned text,
    and every branch that ran handed over at least one tab-area text (T11: ``without_texts`` names those that did
    not; their screens were never scanned)."""
    hits = {name: scan["hits"] for name, scan in scans.items() if scan["hits"]}
    missing = sorted(without_texts)
    ok = bool(scans) and not hits and not missing
    case_id = "X4" if phase == "fixture" else "L-X4"
    reason = None if ok else ("no_text_scanned" if not scans else "forbidden_words" if hits else "no_tab_text")
    return c.case_record(case_id, "pass" if ok else "fail", reason, evidence_refs=list(refs),
                         detail={"scanned": len(scans), "hitTexts": sorted(hits), "withoutTabText": missing,
                                 "excepted": sum(len(scan["excepted"]) for scan in scans.values())})


def x5_case(observations: list, refs: Iterable[str] = ()) -> dict:
    """X5: every observed honest-absence display passed (not 0, not a bare 없음); none observed is a fail of the
    harness (the branches must observe them)."""
    bad = [detail for ok, detail in observations if not ok]
    ok = bool(observations) and not bad
    return c.case_record("X5", "pass" if ok else "fail", None if ok else
                         ("no_observation" if not observations else "absence_shown_as_zero"),
                         evidence_refs=list(refs), detail={"observed": len(observations), "failed": bad})


def x6_case(phase: str, leftover: dict, folders_before: dict, folders_after: dict, refs: Iterable[str] = ()) -> dict:
    """X6 / L-X6: no worker, fixture server, Electron or 8000/3000 listener left, and the default reference folders
    (.deps/precedent_reference, .deps/reaction_reference) were not created."""
    created = [name for name, present in folders_after.items() if present and not folders_before.get(name)]
    present = [name for name, value in folders_after.items() if value]
    ok = not leftover.get("processes") and not leftover.get("ports") and not created and not present
    return c.case_record("X6" if phase == "fixture" else "L-X6", "pass" if ok else "fail",
                         None if ok else "environment_left", evidence_refs=list(refs),
                         detail={"leftover": leftover, "defaultFoldersCreated": created,
                                 "defaultFoldersPresent": present})


# ---------------------------------------------------------------------------------------------------- judgement
def complete_cases(phase: str, records: dict[str, dict]) -> dict[str, dict]:
    """Every required case of the phase, in order: a case the branches did not report becomes not_observed
    prerequisite_failed:<ID> when its prerequisite is not pass, else fail ``case_not_reported``."""
    order = c.FIXTURE_CASES if phase == "fixture" else c.LIVE_CASES
    done = c.cascade(records, order)
    for case_id in order:
        if case_id not in done:
            done[case_id] = c.case_record(case_id, "fail", "case_not_reported")
    return {case_id: done[case_id] for case_id in order}


def judge_phase(phase: str, cases: dict[str, dict], branches: list[str], *, build: dict | None, leftover: dict,
                external: dict, export_ok: bool, rehearsal: bool = False, runs_claimed: bool = False) -> dict:
    """The acceptance of one phase ledger (spec §3.1, §5). A rehearsal is never acceptance (its result is
    ``rehearsalPassed``). ``runs_claimed``: every run of the phase's runs folder belongs to a branch (T11)."""
    required = c.FIXTURE_CASES if phase == "fixture" else c.LIVE_CASES
    problems = {case_id: c.case_problems(cases.get(case_id) or {"id": case_id}) for case_id in required}
    invalid = {case_id: found for case_id, found in problems.items() if found}

    def acceptable(record: dict) -> bool:
        if record.get("status") == "pass":
            return True
        return record.get("status") == "not_observed" and c.reason_class(record.get("reason")) == "allowed"

    parts = {
        "allBranches": list(branches) == list(PHASE_BRANCHES[phase]),
        "casesValid": not invalid,
        "requiredCases": all(acceptable(cases.get(case_id) or {}) for case_id in required),
        "trueCases": all((cases.get(case_id) or {}).get("status") == "pass" for case_id in c.MUST_PASS[phase]),
        "buildStamped": bool((build or {}).get("buildCurrentWithSource")),
        "nothingLeft": not leftover.get("processes") and not leftover.get("ports"),
        "external": (external.get("browser_non_loopback_requests") == 0 and
                     (external.get("provider_calls") == 0 if phase == "fixture" else
                      isinstance(external.get("live_calls_counted"), int)
                      and external["live_calls_counted"] <= MAX_LIVE_CALLS
                      and (not rehearsal or (external.get("provider_calls") == 0
                                             and external.get("product_key_resolver_calls") == 0)))),
        "exportChecks": bool(export_ok),
        "runsClaimed": bool(runs_claimed),
    }
    passed = all(parts.values())
    return {"passed": passed, "acceptance": passed and not rehearsal, "rehearsalPassed": passed if rehearsal else None,
            "parts": parts, "invalidCases": invalid}


def unobserved(cases: dict[str, dict]) -> list[dict]:
    return [{"id": case_id, "reason": record.get("reason"), "class": c.reason_class(record.get("reason")),
             "covering_tests": record.get("covering_tests") or []}
            for case_id, record in cases.items() if record.get("status") == "not_observed"]


def assemble_ledger(phase: str, cases: dict[str, dict], branches: list[str], *, build: dict | None, leftover: dict,
                    external: dict, trace_audit: dict | None, export_ok: bool, rehearsal: bool = False,
                    source_head: str | None = None, dirty_files: Iterable[str] = (), extra: dict | None = None,
                    runs_claimed: bool = False) -> dict:
    """``m28_case_ledger@1`` of one phase (spec §5)."""
    judged = judge_phase(phase, cases, branches, build=build, leftover=leftover, external=external,
                         export_ok=export_ok, rehearsal=rehearsal, runs_claimed=runs_claimed)
    statuses = {case_id: record.get("status") for case_id, record in cases.items()}
    summary = None
    if isinstance(trace_audit, dict):
        summary = {key: trace_audit.get(key) for key in ("status", "reportCount", "byKind", "checks",
                                                          "partialProductRecheck", "noReports")}
        summary["failures"] = len(trace_audit.get("failures") or [])
    return {"schema": c.LEDGER_SCHEMA, "acceptance": judged["acceptance"], "phase": phase, "rehearsal": rehearsal,
            "rehearsalPassed": judged["rehearsalPassed"], "acceptanceParts": judged["parts"],
            "invalidCases": judged["invalidCases"], "branchesRequested": list(branches),
            "source_head": source_head, "dirty_files": list(dirty_files), "build": build,
            "cases": list(cases.values()), "definition_items": c.definition_items(statuses, phase),
            "external": external, "leftover": leftover, "trace_audit": summary, "unobserved": unobserved(cases),
            "generatedAt": now(), **(extra or {})}


def verdict(fixture_ledger: dict, live_ledger: dict, *, review_passed: bool, user_decision_defects: bool) -> dict:
    """Spec §3.3 before the user's confirmation: "검증 통과, 사용자 확인 대기" or "보류" (the third value is written only
    after the user confirms, by the coordinating session). Hold reasons (a)–(d) are listed."""
    items = c.combine_items(fixture_ledger.get("definition_items") or {}, live_ledger.get("definition_items") or {})
    reasons = []
    if any(item["status"] != "pass" for item in items.values()):
        reasons.append("(a) an item did not pass")
    if user_decision_defects:
        reasons.append("(b) a defect needs a hash file, closed set, fixed sentence or limit change")
    if any(record.get("status") == "fail" for ledger in (fixture_ledger, live_ledger)
           for record in ledger.get("cases") or []):
        reasons.append("(c) a failed case remains")
    rounds = {record["id"]: record for record in live_ledger.get("cases") or [] if record.get("id") in c.LIVE_ROUNDS}
    if any((rounds.get(round_id) or {}).get("status") != "pass" for round_id in c.LIVE_ROUNDS):
        reasons.append("(d) a real-call round did not complete")
    if not (fixture_ledger.get("acceptance") is True and live_ledger.get("acceptance") is True):
        reasons.append("a phase ledger is not acceptance")
    if not review_passed:
        reasons.append("the independent review has not passed")
    value = c.HOLD if reasons else "검증 통과, 사용자 확인 대기"
    return {"verdict": value, "reasons": reasons, "items": items}


# ---------------------------------------------------------------------------------------------------- evidence rules
def leak_kinds(text: str, real: m27.RealText | None = None) -> list[str]:
    """What a committed text must not hold: a key-shaped string, a fixture placeholder, an absolute path, real kbase
    text (kinds only; never the matched value)."""
    kinds = []
    if KEY_PATTERNS.search(text):
        kinds.append("key_pattern")
    if any(sentinel in text for sentinel in SENTINELS):
        kinds.append("placeholder")
    if ABSOLUTE_PATH.search(text):
        kinds.append("absolute_path")
    if real is not None and len(real) and m27.contains_any(text, real):
        kinds.append("real_kbase_text")
    return kinds


def hold_reason(artifacts: Path, path: Path, real: m27.RealText | None,
                replacements: Iterable[tuple[str, str]] = ()) -> str | None:
    """Why a text artifact stays out of the committed evidence (hash only), or None to export it. The leak search
    runs on the text as it would be exported (after the ``replacements`` redaction, T11): an absolute path the
    redaction does not cover (another user's /Users/…, a /home/… path) holds the file."""
    rel = path.relative_to(artifacts)
    if "downloads" in rel.parts:
        return "download"
    if path.name == X4_LINES:
        return "raw_lines"
    if path.name.endswith(m27.FAILURE_PANEL_SUFFIX):
        return "failure_panel"
    if path.stat().st_size > MAX_TEXT_BYTES and path.name not in LEDGER_NAMES:
        return "over_256KiB"
    found = leak_kinds(m13.redact(path.read_text(encoding="utf-8", errors="replace"), list(replacements)), real)
    return found[0] if found else None


def scan_evidence(folder: Path, real: m27.RealText | None = None) -> dict[str, list[str]]:
    """Leak kinds per file of an exported folder (paths relative to it)."""
    hits = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file() and not path.is_symlink():
            found = leak_kinds(path.read_text(encoding="utf-8", errors="replace"), real)
            if found:
                hits[str(path.relative_to(folder))] = found
    return hits


# X4 case attribution of a reopened report: the case that makes that report kind in its branch (spec §4).
REPORT_CASES = {
    "fixture": {"a": {"inspection": ["A2"], "interface_sasa": ["A3"], "pocket_detection": ["A4"],
                      "residue_numbering": ["A5"], "reference_site_annotation": ["A6"], "kinase_precedents": ["A7"],
                      "reaction_knowledge": ["A8"]},
                "b": {"chemical_interactions": ["B1"], "ligand_candidates": ["B2"], "ligand_docking": ["B3"],
                      "ligand_docking_batch": ["B4"], "ligand_ga": ["B5"], "jev_choice": ["B6"], "jev_loop": ["B7"]},
                "c": {"mutation_candidates": ["C1", "C2"], "openmm_protein_minimize": ["C2"],
                      "mutation_model": ["C2"], "sequence_ga": ["C4"], "jev_choice": ["C5"], "jev_loop": ["C6"]}},
    "live": {"b": {"ligand_candidates": ["L-pre-B2"], "ligand_docking": ["L-pre-B3"],
                   "ligand_docking_batch": ["L-pre-B4"], "jev_loop": ["L-B7"]},
             "c": {"openmm_protein_minimize": ["L-pre-C2"], "mutation_candidates": ["L-pre-C2"],
                   "mutation_model": ["L-pre-C2"], "jev_loop": ["L-C6"]}},
}


def report_cases(phase: str, branch: str | None, kind: str | None) -> list[str]:
    found = REPORT_CASES.get(phase, {}).get(branch or "", {}).get(kind or "")
    if found:
        return list(found)
    return [f"branch-{branch}"] if branch else []


def screen_cases(name: str) -> list[str]:
    """The case of a tab-area text named ``<tab>@<case>`` by the harness."""
    case = str(name).rpartition("@")[2]
    return [case] if case in c.CASE_BRANCH else []


def x4_committed(scans: dict[str, dict], origin: dict[str, tuple[str, list[str]]],
                 exceptions: dict[str, dict] | None = None) -> dict:
    """The committed form of the X4 scan (coordinating-session decision, T9): per line found, its line SHA-256,
    template SHA-256, cases, line kind, byte length and reason only, never the line or its words (reference text such
    as M-CSA roles and real kbase strings stay in the git-ignored ``x4-lines.json``); with how often each exception
    matched and which were not met in this run."""
    exceptions = X4_EXCEPTIONS if exceptions is None else exceptions
    used: dict[str, int] = {}
    out: dict[str, dict] = {}
    for name, scan in scans.items():
        source, cases = origin.get(name, ("unknown", []))

        def row(entry: dict, excepted: bool, cases: list[str] = cases) -> dict:
            item = {"line_sha256": entry.get("line_sha256"), "template_sha256": entry.get("template_sha256"),
                    "bytes": entry.get("bytes"), "part": entry.get("part"), "cases": list(cases)}
            if excepted:
                key = entry.get("exception")
                used[key] = used.get(key, 0) + 1
                item.update({"exception": key, "match": entry.get("match"),
                             "kind": (exceptions.get(key) or {}).get("kind"), "reason": entry.get("reason")})
            else:
                item.update({"kind": "not_excepted", "reason": None,
                             "labelException": entry.get("labelException")})
            return item
        out[name] = {"source": source, "cases": list(cases), "hits": [row(hit, False) for hit in scan["hits"]],
                     "excepted": [row(hit, True) for hit in scan["excepted"]]}
    return {"schema": "m28_x4_scan@1", "scans": out, "exceptionsUsed": dict(sorted(used.items())),
            "exceptionsNotMet": sorted(set(exceptions) - set(used)),
            "note": "줄 SHA·템플릿 SHA·사례·줄 종류·바이트 길이·이유만. 원문 줄은 Git 제외 x4-lines.json에만 있다."}


def text_items(path: Path) -> list[str]:
    """The texts of one evidence file for the X4 scan: JSON strings one by one, other text as written."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix not in (".json", ".jsonl"):
        return [raw]
    out = []
    for chunk in ([raw] if path.suffix == ".json" else raw.splitlines()):
        try:
            out += m25.json_strings(json.loads(chunk))
        except ValueError:
            out.append(chunk)
    return out


def evidence_wording(artifacts: Path, fixed: c.FixedText, exceptions: dict[str, dict]) -> dict[str, dict]:
    """X4 over the evidence text (spec §4.4 "증거 문구"): every text file of the artifacts folder except the service
    logs, the browser profile, whole-tab ``*.dom.txt`` dumps (the branches hand their tab-area texts over), downloads
    (report Markdown is scanned from the reopened reports) and the runner's own analysis files (``WORDING_SKIP``)."""
    scans = {}
    for path in sorted(Path(artifacts).rglob("*")):
        rel = path.relative_to(artifacts)
        if (not path.is_file() or path.suffix not in TEXT_SUFFIXES or rel.parts[0] == "services"
                or "browser-profile" in rel.parts or "downloads" in rel.parts or path.name.endswith(".dom.txt")
                or path.name in WORDING_SKIP):
            continue
        found = {"hits": [], "excepted": []}
        for text in text_items(path):
            scan = c.forbidden_hits(text, fixed, exceptions)
            found["hits"] += scan["hits"]
            found["excepted"] += scan["excepted"]
        scans[f"evidence:{rel}"] = found
    return scans


# ---------------------------------------------------------------------------------------------------- runner
class Runner(m18.Runner):
    """The M18/M17/M15 runner protections (new root outside /tmp, git-ignored artifacts, free ports, build stamp, mw
    path check, allowlisted env, loopback API) with the M28 phase folders, backend choice, branch registry, live
    ledger, X cases, case ledger and evidence rules."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        phase = getattr(args, "phase", "fixture")
        rehearse = bool(getattr(args, "rehearse", False))
        if phase not in PHASES:
            raise SystemExit(f"--phase must be one of {PHASES}")
        root = Path(args.root)
        if args.out:
            out = args.out
        elif rehearse:
            out = str(root.resolve() / f"out-{phase}-rehearsal")
        else:
            out = str(code / "docs/qa" / f"m28-final-{stamp}" / f"acceptance-{phase}")
        for path in (args.root, args.artifacts, out):
            if under_tmp(Path(path)):
                raise SystemExit("QA roots and evidence folders must not be under /tmp")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        if self.root.exists() and (not self.root.is_dir() or any(self.root.iterdir())):
            raise SystemExit(f"{self.root} is not new; choose a new --root")
        self.phase, self.rehearse = phase, rehearse
        if self.rehearse and self.phase != "live":
            raise SystemExit("--rehearse rehearses the live phase (the fixture phase sends to no one)")
        live_calls = getattr(args, "live_calls", None)
        if self.phase == "live" and live_calls is None and not self.rehearse:
            raise SystemExit("--phase live makes real calls: it needs --live-calls N (1..2)")
        if self.phase == "fixture" and live_calls is not None:
            raise SystemExit("--live-calls belongs to the live phase (the fixture phase makes no real call)")
        self.live_calls = MAX_LIVE_CALLS if live_calls is None else int(live_calls)
        requested = getattr(args, "branches", None)
        self.branches = list(PHASE_BRANCHES[self.phase]) if requested is None else list(requested)
        stray = [name for name in self.branches if name not in PHASE_BRANCHES[self.phase]]
        if stray:
            raise SystemExit(f"the {self.phase} phase has no branch {stray} (its branches: "
                             f"{','.join(PHASE_BRANCHES[self.phase])})")
        if self.phase == "live" and not self.rehearse and self.branches != list(PHASE_BRANCHES["live"]):
            raise SystemExit("a real live phase plans both rounds (spec §6.1: L-B7 then L-C6, the plan ends at a round "
                             "that does not complete): --branches with fewer is for the rehearsal only")
        # The calls this phase reserves in the ledger and the runtime cap of its harnesses: the same number (T11 R1).
        self.live_cap = (min(self.live_calls, live_plan_budget(live_plan(self.branches))["planned"])
                         if self.phase == "live" else 0)
        self.kbase = Path(args.kbase).resolve()
        self.m15_source = self.resolve_input(args.m15_reference)
        self.reaction_source = self.resolve_input(args.reaction_set)
        for source, name in ((self.m15_source, "--m15-reference"), (self.reaction_source, "--reaction-set")):
            if self.root == source or self.root in source.parents:
                raise SystemExit(f"{name} must not be inside --root (it is copied, never written)")
        if not (self.m15_source / "active.json").is_file() or not (self.m15_source / "sets").is_dir():
            raise SystemExit(f"--m15-reference has no active.json and sets/: {self.m15_source}")
        if self.phase == "fixture" and "a" in self.branches and not (self.kbase / "dist/manifest.json").is_file():
            raise SystemExit(f"branch A (A7) needs --kbase with dist/manifest.json: {self.kbase}")
        if self.needs_reaction_set() and not ((self.reaction_source / "active.json").is_file()
                                              and (self.reaction_source / "sets").is_dir()):
            raise SystemExit(f"--reaction-set has no active.json and sets/: {self.reaction_source}")
        base = self.root / self.phase
        self.runs, self.reference = base / "runs", base / "reference"
        self.precedent, self.reaction = base / "precedent_reference", base / "reaction_reference"
        self.control = base / "fixture-control"
        self.api_client = c.Api()
        self.flow_rows: list[dict] = []
        self.results: dict[str, c.BranchResult] = {}
        self.checks: dict = {}
        self.fixed: dict | None = None
        self.ledger_file: Path | None = None
        self.ledger_open = False
        self.send_allowed = True
        self.resolver_calls = 0                  # runs of the product key resolver (a rehearsal must have none)
        self.markdowns: dict[str, str] = {}
        self.report_cases: dict[str, list[str]] = {}
        self.x4_record: dict | None = None
        self.round_dispatch: dict[str, int | None] = {}     # live: dispatch events each branch's flow added
        self.unclaimed: list[str] = []
        self.without_texts: list[str] = []
        self.audited = False                                 # the trace audit ran over the phase's runs

    # ----- inputs and folders ------------------------------------------------------------------
    def resolve_input(self, value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else self.code / path).resolve()

    def needs_reaction_set(self) -> bool:
        return self.phase == "fixture" and bool({"a", "c"} & set(self.branches))

    def default_folders(self) -> dict[str, bool]:
        return {str(rel): (self.code / rel).exists() for rel in DEFAULT_FOLDERS}

    def prepare_folders(self) -> None:
        """The phase folders: runs, a read-only M15 copy, an isolated reaction copy (A8 / C1) or an empty folder, an
        empty precedent folder (the branch-A module installs into it) and the fixture control folder."""
        for folder in (self.runs, self.precedent, self.control):
            folder.mkdir(parents=True, exist_ok=True)
        self.checks["m15"] = self.copy_read_only(self.m15_source, self.reference)
        if self.needs_reaction_set():
            self.checks["reaction"] = self.copy_read_only(self.reaction_source, self.reaction)
        else:
            self.reaction.mkdir(parents=True, exist_ok=True)

    def copy_read_only(self, source: Path, target: Path) -> dict:
        """A read-only copy (the source never written; its tree digest equal before, after and in the copy)."""
        before = m13.tree_digest(source)
        if target.exists():
            raise RuntimeError(f"{target} exists")
        shutil.copytree(source, target, symlinks=False)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        after, copied = m13.tree_digest(source), m13.tree_digest(target)
        active = json.loads((target / "active.json").read_text())["set_hash"]
        return {"status": "pass" if before == after == copied else "fail", "source": str(source), "setHash": active,
                "files": len(copied), "treeSha256": m13.sha_bytes(json.dumps(copied, sort_keys=True).encode())}

    def backend_env(self) -> dict[str, str]:
        return m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(self.runs),
                              "MW_REFERENCE_DIR": str(self.reference),
                              "MW_PRECEDENT_REFERENCE_DIR": str(self.precedent),
                              "MW_REACTION_REFERENCE_DIR": str(self.reaction)})

    # ----- services ----------------------------------------------------------------------------
    def uses_fixture_server(self) -> bool:
        return self.phase == "fixture" or self.rehearse

    def start_phase_backend(self) -> bool:
        """The fixture server (fixture phase, rehearsal: never the product backend) or the product backend (live).
        False when the fixture server record does not name the server just started (no branch runs then)."""
        env = self.backend_env()
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        log = self.artifacts / "services" / f"backend-{self.phase}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        if self.uses_fixture_server():
            argv = [str(self.python), str(self.code / FIXTURE_SERVER), "--port", "8000", "--runs-dir", str(self.runs),
                    "--control", str(self.control)]
        else:
            argv = [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"]
        proc = subprocess.Popen(argv, cwd=self.code, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT,
                                start_new_session=True)
        self.services["backend"] = proc
        self.wait_http(f"{m15.API}/capabilities")
        started = True
        if self.uses_fixture_server():
            try:
                server = json.loads((self.control / "server.json").read_text())
            except (OSError, ValueError):
                server = {}
            started = m25.fixture_server_started(server, proc.pid, m13.listening(8000), self.runs)
            self.checks["fixtureServer"] = {"started": started, "pid": proc.pid, "serverJsonPid": server.get("pid")}
        self.state.setdefault("services", []).append({
            "name": "fixture-backend" if self.uses_fixture_server() else "backend", "pid": proc.pid,
            "runs": str(self.runs), "reference": str(self.reference), "precedentReference": str(self.precedent),
            "reactionReference": str(self.reaction), "mw": probe.stdout.strip(), "startedAt": now()})
        self.save()
        self.record("backend", "pass" if started else "fail", fixtureServer=self.uses_fixture_server(), pid=proc.pid)
        if not started:
            self.stop_backend()
        return started

    def flow(self, step: str, harness_file: str, mode: str, extra: list[str], limit: int | None = None) -> dict | None:
        """One harness step (``node frontend/tests/offscreen/<harness_file> --mode <mode>``) with its ledger row; in the
        live phase the dispatch events are counted while it runs and it and the backend stop past ``limit``."""
        if self.phase == "live":                       # the runner's own cap; none at all once the plan ended
            cap = self.live_cap if self.send_allowed else m25.dispatch_total(m25.count_events(self.runs))
            limit = cap if limit is None else min(limit, cap)
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / harness_file), "--url", m15.WEB, "--mode", mode, "--artifacts",
                str(step_dir), "--runs-dir", str(self.runs), *extra]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            proc = subprocess.Popen(argv, cwd=self.frontend, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            rc, exceeded = m25.watch_process(proc, self.runs, limit, STEP_TIMEOUT_S)
        if exceeded is not None:
            self.stop_backend()
            self.state["dispatchCapExceeded"] = {"limit": limit, "counts": exceeded}
            self.save()
            self.record("dispatch-cap", "fail", limit=limit, counts=exceeded)
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        if row is None:
            row = {"mode": mode, "status": "fail", "externalRequestCount": None,
                   "error": f"harness exited {rc} without a ledger row"}
            self.write_row(step_dir, row)
        self.flow_rows.append({"step": step_dir.name, "harness": harness_file, "status": row.get("status"),
                               "externalRequestCount": row.get("externalRequestCount"), "exitCode": rc,
                               "dispatchCapExceeded": exceeded is not None})
        self.record(step, "pass" if rc == 0 and row.get("status") == "pass" and exceeded is None else "fail",
                    exitCode=rc, artifacts=str(step_dir))
        return row

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m28_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(),
                "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    def leftovers(self) -> list[str]:
        """Workers (incl. the fixture server and Electron of this root's harness) whose command or working directory is
        inside the root, and 8000/3000 listeners (the m25 runner's rule with the M28 worker names)."""
        root = self.root.resolve()
        left: list[str] = []
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

    # ----- fixed sentences (subprocess; this runner never imports mw) ---------------------------
    def export_fixed_sentences(self) -> dict | None:
        target = self.artifacts / "fixed-sentences.json"
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend")})
        done = subprocess.run([str(self.python), str(self.code / EXPORTER), "--out", str(target)], cwd=self.code,
                              env=env, capture_output=True, text=True, timeout=300, check=False)
        ok = done.returncode == 0 and target.is_file()
        self.record("fixed-sentences", "pass" if ok else "fail", exitCode=done.returncode)
        self.fixed = json.loads(target.read_text()) if ok else None
        return self.fixed

    # ----- live ledger -------------------------------------------------------------------------
    def ledger_location(self) -> Path:
        return self.root / REHEARSAL_LEDGER_NAME if self.rehearse else ledger_path(self.code)

    def ledger_guard(self) -> None:
        """Before anything starts: refuse (SystemExit) when the ledger cannot be found, read or counted, or the plan
        does not fit; otherwise record this phase as started (unfinished until ledger_close)."""
        planned = live_plan_budget(live_plan(self.branches))["planned"]
        try:
            self.ledger_file = self.ledger_location()
            if self.rehearse:
                self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            ledger_precheck(self.ledger_file)
            with m25.ledger_lock(self.ledger_file):
                ledger = read_ledger(self.ledger_file)
                others = ledger_total(ledger, exclude=self.root)
                mine = root_count(str(self.root), ledger["roots"].get(str(self.root)) or {"phases": [], "dispatch": {}})
                refusal = ledger_admission(others, mine, planned, self.live_calls)
                if refusal is not None:
                    raise SystemExit(f"real calls refused, nothing started: {refusal}")
                entry = ledger["roots"].setdefault(str(self.root), {"phases": [], "dispatch": {}})
                entry["phases"].append({"phase": "live", "startedAt": now(), "finishedAt": None, "planned": planned,
                                        "liveCalls": self.live_calls, "runtimeCap": self.live_cap})
                m25.write_ledger(self.ledger_file, ledger)
        except (LedgerError, m25.LedgerError) as exc:
            raise SystemExit(f"real calls refused, nothing started: {exc}") from exc
        except OSError as exc:
            raise SystemExit(f"real calls refused, nothing started: the ledger cannot be written ({exc})") from exc
        self.ledger_open = True
        self.checks["liveLedger"] = {"ok": False, "path": str(self.ledger_file), "rehearsal": self.rehearse,
                                     "before": others + mine, "planned": planned, "runtimeCap": self.live_cap}

    def ledger_close(self) -> int | None:
        """Record this root's dispatch counts (failed sends included), close its phase; returns this root's count."""
        if not self.ledger_open:
            return None
        self.ledger_open = False
        try:
            ledger_precheck(self.ledger_file)
        except LedgerError as exc:                     # removed while the phase ran: never written back from here
            self.checks["liveLedger"] = {**self.checks.get("liveLedger", {}), "ok": False, "error": str(exc)}
            self.record("live-ledger", "fail", detail=self.checks["liveLedger"])
            return None
        with m25.ledger_lock(self.ledger_file):
            ledger = read_ledger(self.ledger_file)
            entry = ledger["roots"].setdefault(str(self.root), {"phases": [], "dispatch": {}})
            found = m25.count_events(self.runs) if self.runs.is_dir() else {}
            for run, item in found.items():
                entry["dispatch"][run] = max(entry["dispatch"].get(run, 0), item["dispatch"])
            for item in entry["phases"]:
                if item["finishedAt"] is None:
                    item["finishedAt"] = now()
            m25.write_ledger(self.ledger_file, ledger)
            after = ledger_total(ledger)
            mine = root_count(str(self.root), entry)
        self.checks["liveLedger"] = {**self.checks.get("liveLedger", {}), "ok": after <= MAX_LIVE_CALLS,
                                     "after": after, "root": mine}
        self.record("live-ledger", "pass" if after <= MAX_LIVE_CALLS else "fail", detail=self.checks["liveLedger"])
        return mine

    def key_present(self) -> bool:
        """Real live phase only: key presence as a boolean only (the product resolver in a child) and the root .env
        private (os.lstat only). A rehearsal needs no key (the fixture server has a placeholder): the step is skipped
        and the product key resolver is never run (T8 / T9)."""
        if self.rehearse:
            self.checks["key"] = {"skipped": "rehearsal", "rehearsal": True}
            self.record("key-present", "pass", skipped="rehearsal")
            return True
        scan = self.key_scan([])
        dotenv = m25.dotenv_status(self.code)
        ok = scan.get("keyAvailable") is True and dotenv["private"]
        self.checks["key"] = {"keyAvailable": scan.get("keyAvailable") is True, "dotenv": dotenv,
                              "rehearsal": self.rehearse}
        self.record("key-present", "pass" if ok else "fail", detail=self.checks["key"])
        return ok

    def key_scan(self, roots: list[Path]) -> dict:
        """The files under ``roots`` holding the key (the product resolver in a child prints booleans and paths only)
        or a fixture placeholder. In a rehearsal the resolver is never run: the placeholders are searched here and the
        key search is recorded as skipped (a rehearsal touches no key)."""
        if self.rehearse:
            hits = m25.files_containing(roots, [sentinel.encode() for sentinel in SENTINELS])
            return {"ok": not hits, "keyAvailable": None, "keySearch": "skipped: rehearsal", "keyHits": [],
                    "sentinelHits": hits}
        self.resolver_calls += 1
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend")})
        done = subprocess.run([str(self.python), "-c", m25.KEY_SCAN, m25.SENTINEL, *map(str, roots)], cwd=self.code,
                              env=env, capture_output=True, text=True, check=False)
        try:
            found = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"ok": False, "error": f"key scan exited {done.returncode}"}
        hits = found.get("hits") or {}
        return {"ok": done.returncode == 0 and not hits.get("key") and not hits.get("sentinel"),
                "keyAvailable": found.get("keyAvailable"), "files": found.get("files"),
                "keyHits": hits.get("key", []), "sentinelHits": hits.get("sentinel", [])}

    # ----- branches ----------------------------------------------------------------------------
    def context(self, branch: str) -> c.BranchContext:
        server = self.services.get("backend")
        fixture = ({"control": self.control, "pid": server.pid} if self.uses_fixture_server() and server else None)
        return c.BranchContext(
            phase=self.phase, rehearse=self.rehearse, branch=branch, code=self.code, root=self.root,
            stage=self.root / self.phase, runs=self.runs, reference=self.reference, precedent=self.precedent,
            reaction=self.reaction, artifacts=self.artifacts / branch, kbase=self.kbase, m15_reference=self.m15_source,
            reaction_set=self.reaction_source, python=self.python, api=self.api_client, flow=self.flow,
            record=self.record, child_env=m13.child_env, fixture=fixture,
            live_calls=self.live_cap if self.phase == "live" else 0, send_allowed=self.send_allowed)

    def run_branch(self, branch: str) -> c.BranchResult:
        module = BRANCH_REGISTRY.get(branch)
        if module is None:
            self.record(f"branch-{branch}", "fail", reason="branch module not registered")
            return c.BranchResult(notes={"error": "branch_module_not_registered"})
        try:
            result = module(self.context(branch))
        except Exception as exc:  # noqa: BLE001 - any branch failure is recorded (its round judged by the events)
            self.record(f"branch-{branch}", "fail", error=f"{type(exc).__name__}: {exc}")
            return c.BranchResult(notes={"error": f"{type(exc).__name__}: {exc}"})
        self.record(f"branch-{branch}", "pass", cases={item["id"]: item["status"] for item in result.cases})
        return result

    def dispatch_count(self) -> int | None:
        """The dispatch events of every run of the phase now (None when they cannot be counted)."""
        try:
            return m25.dispatch_total(m25.count_events(self.runs)) if self.runs.is_dir() else 0
        except (OSError, ValueError):
            return None

    def run_branches(self) -> None:
        """Every requested branch in turn. Live (T11 R2): the dispatch events are counted before and after each
        branch; a branch whose flow added a dispatch (or whose count is unknown) and whose round has no completed
        result (the branch raised, the harness died or was stopped, no evidence) ends the plan, as a round that was
        dispatched and failed does (spec §6.1)."""
        for branch in self.branches:
            before = self.dispatch_count() if self.phase == "live" else 0
            self.results[branch] = self.run_branch(branch)
            if self.phase != "live":
                continue
            after = self.dispatch_count()
            added = None if before is None or after is None else after - before
            round_id = LIVE_ROUND_OF.get(branch)
            if round_id is not None:
                self.round_dispatch[round_id] = added
            result = self.results[branch].live.get(round_id or "", "")
            if (added != 0 and result != "completed") or c.next_round_cause(result) is not None:
                self.send_allowed = False          # spec §6.1: a dispatched round did not complete

    def branch_records(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        for branch, result in self.results.items():
            for record in result.cases:
                if c.CASE_BRANCH.get(record.get("id")) == branch:      # X cases are the runner's
                    records[record["id"]] = record
        if self.phase == "live":
            results = {key: value for result in self.results.values() for key, value in result.live.items()}
            causes = {key: value for result in self.results.values() for key, value in result.not_sent_causes.items()}
            for round_id, added in self.round_dispatch.items():   # T11 R2: the events decide whether it was sent
                if added != 0 and results.get(round_id) not in ("completed", "provider_failed", "product_failed"):
                    results[round_id] = "product_failed"
                    causes.pop(round_id, None)
            for index, round_id in enumerate(c.LIVE_ROUNDS):
                if round_id not in results and round_id not in causes:
                    earlier = c.next_round_cause(results.get(c.LIVE_ROUNDS[index - 1], "")) if index else None
                    need = next((p for p in c.PREREQUISITES.get(round_id, ()) if (records.get(p) or {}).get(
                        "status") != "pass"), None)
                    causes[round_id] = earlier or (f"prerequisite_failed:{need}" if need else "ledger_refused")
            outcome = c.live_outcome(results, causes)
            self.checks["liveOutcome"] = {**outcome, "results": results, "causes": causes,
                                          "dispatched": {round_id: self.round_dispatch.get(round_id, 0)
                                                         for round_id in c.LIVE_ROUNDS}}
            for round_id, (status, reason) in outcome["cases"].items():
                refs = (records.get(round_id) or {}).get("evidence_refs") or []
                records[round_id] = c.case_record(round_id, status, reason, evidence_refs=refs,
                                                  detail={"result": results.get(round_id, "not_sent")})
        return records

    # ----- X cases -----------------------------------------------------------------------------
    def audit_targets(self) -> tuple[list[str], list[str]]:
        """Every ``run_*`` folder of the phase's runs folder (the branches' runs first, in branch order, then the
        others) and the runs no branch claimed (T11: all are audited and X4-scanned; an unclaimed run fails X2 and
        acceptance)."""
        claimed = [rid for result in self.results.values() for rid in result.runs]
        present = sorted(path.name for path in self.runs.glob("run_*") if path.is_dir()) if self.runs.is_dir() else []
        unclaimed = [rid for rid in present if rid not in claimed]
        return list(dict.fromkeys(claimed + unclaimed)), unclaimed

    def x1_and_audit(self, records: dict[str, dict]) -> None:
        """X1-<branch> per branch and the trace audit (X2) over every run of the phase, while the backend still
        runs."""
        fetch = audit.http_fetch(m15.API)
        rules = (self.fixed or {}).get("reportRules")
        runs, self.unclaimed = self.audit_targets()
        summary = audit.audit_runs(fetch, runs, rules)
        summary["unclaimedRuns"] = list(self.unclaimed)
        self.audited = True
        self.markdowns = summary.pop("_markdown", {})
        branch_of = {rid: branch for branch, result in self.results.items() for rid in result.runs}
        self.report_cases = {report["handle"]: report_cases(self.phase, branch_of.get(report["run"]), report["kind"])
                             for report in summary["reports"]}
        (self.artifacts / "trace-audit.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        self.checks["traceAudit"] = summary
        if self.phase != "fixture":
            return
        records["X2"] = x2_case(summary, records, ["trace-audit.json"], unclaimed=self.unclaimed)
        for branch in self.branches:
            result = self.results.get(branch) or c.BranchResult()
            events = sum(1 for report in summary["reports"] if report["run"] in result.runs)
            opened = sum(1 for report in summary["reports"] if report["run"] in result.runs
                         and report["checks"]["reopen"] == "pass")
            records[f"X1-{branch.upper()}"] = x1_case(branch, events, opened, result.reports_created,
                                                       ["trace-audit.json"])

    def x4_scans(self) -> dict[str, dict]:
        """X4 over the tab-area texts, the reopened report Markdown and the evidence text. The lines as found go to
        ``x4-lines.json`` (git-ignored artifacts only, held from the export); ``x4-scan.json`` keeps hashes, cases,
        line kinds, byte lengths and reasons only (x4_committed)."""
        fixed = c.FixedText.from_export(self.fixed or {})
        scans: dict[str, dict] = {}
        origin: dict[str, tuple[str, list[str]]] = {}
        self.without_texts = sorted(branch for branch, result in self.results.items() if not result.texts)
        for branch, result in self.results.items():
            for name, text in result.texts.items():
                key = f"{branch}:screen:{name}"
                scans[key] = c.forbidden_hits(text, fixed, X4_EXCEPTIONS)
                origin[key] = ("screen", screen_cases(name))
        for handle, text in self.markdowns.items():
            key = f"report:{handle}"
            scans[key] = c.forbidden_hits(text, fixed, X4_EXCEPTIONS)
            origin[key] = ("report", self.report_cases.get(handle) or [])
        for key, scan in evidence_wording(self.artifacts, fixed, X4_EXCEPTIONS).items():
            scans[key] = scan
            origin[key] = ("evidence", ["L-X4" if self.phase == "live" else "X4"])
        (self.artifacts / X4_LINES).write_text(json.dumps(scans, indent=2, ensure_ascii=False) + "\n")
        self.x4_record = x4_committed(scans, origin)
        (self.artifacts / "x4-scan.json").write_text(json.dumps(self.x4_record, indent=2, ensure_ascii=False) + "\n")
        return scans

    def external(self) -> dict:
        rows = self.flow_rows
        browser = (sum(row["externalRequestCount"] for row in rows)
                   if rows and all(isinstance(row["externalRequestCount"], int) for row in rows) else None)
        counts = m25.count_events(self.runs) if self.runs.is_dir() else {}
        if self.uses_fixture_server():
            server = json.loads((self.control / "server.json").read_text()) if (
                self.control / "server.json").is_file() else None
            calls_file = self.control / "calls.jsonl"
            calls = [json.loads(line) for line in calls_file.read_text().splitlines() if line] if (
                calls_file.is_file()) else []
            reads_file = self.control / "credentials.json"
            reads = json.loads(reads_file.read_text()) if reads_file.is_file() else None
            provider = fixture_provider_calls(server, calls, m25.dispatch_total(counts), reads)
        else:
            provider = None
        live = m25.dispatch_total(counts) if self.phase == "live" else None
        return {"browser_non_loopback_requests": browser, "provider_calls": provider if self.phase == "fixture"
                else (0 if self.rehearse and provider == 0 else None), "live_calls_counted": live,
                "dispatchEvents": m25.dispatch_total(counts), "product_key_resolver_calls": self.resolver_calls}

    # ----- phase -------------------------------------------------------------------------------
    def run(self) -> int:
        busy = {port: m13.listening(port) for port in (8000, 3000)}
        if any(busy.values()):
            raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        if self.phase == "live":
            budget = live_plan_budget(live_plan(self.branches))
            if not budget["ok"]:
                raise SystemExit(f"the live plan does not fit the run defaults: {budget['short']}")
            self.ledger_guard()          # nothing has started yet; refused past the allocation
        try:
            return self.execute()
        finally:
            if self.phase == "live":
                self.ledger_close()

    def execute(self) -> int:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        folders_before = self.default_folders()
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
                               "runnerSha256": m13.sha_file(Path(__file__)),
                               "commonSha256": m13.sha_file(Path(c.__file__)),
                               "auditSha256": m13.sha_file(Path(audit.__file__))}
        self.save()
        self.prepare_folders()
        self.export_fixed_sentences()
        records: dict[str, dict] = {}
        ready = self.phase == "fixture" or self.key_present()
        try:
            self.start_frontend()
            if ready and self.start_phase_backend():
                self.run_branches()
                records = self.branch_records()
                self.x1_and_audit(records)
            else:
                records = self.branch_records()
        finally:
            self.stop_all()
            self.save()
        root_calls = self.ledger_close() if self.phase == "live" else None
        left = self.leftovers()
        leftover = {"processes": [item for item in left if not item.startswith("port ")],
                    "ports": [item for item in left if item.startswith("port ")]}
        folders_after = self.default_folders()
        external = self.external()
        scans = self.x4_scans()
        observations = [item for result in self.results.values() for item in result.observations.get("X5", [])]
        prefix = "" if self.phase == "fixture" else "L-"
        records[f"{prefix}X3"] = x3_case(self.phase, external, root_calls, self.live_calls)
        records[f"{prefix}X4"] = x4_case(self.phase, scans, ["x4-scan.json"], without_texts=self.without_texts)
        if self.phase == "fixture":
            records["X5"] = x5_case(observations)
        records[f"{prefix}X6"] = x6_case(self.phase, leftover, folders_before, folders_after)
        cases = complete_cases(self.phase, records)
        ledger = self.finish(cases, external, leftover)
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"],
                          "rehearsalPassed": ledger["rehearsalPassed"], "artifacts": str(self.artifacts)}), flush=True)
        passed = ledger["acceptance"] or (self.rehearse and ledger["rehearsalPassed"])
        return 0 if passed else 1

    def finish(self, cases: dict[str, dict], external: dict, leftover: dict) -> dict:
        """The case ledger and the export (T11): the first ``case-ledger.json`` is written with the export not yet
        passed (an export that raises leaves a ledger that is not acceptance); only after the searches passed is it
        written again with them, and that final export is searched again."""
        ledger = self.write_ledger(cases, external, leftover, export_ok=False, provisional=True)
        if not self.export(ledger):
            return ledger
        ledger = self.write_ledger(cases, external, leftover, export_ok=True)
        if not self.export(ledger):
            ledger = self.write_ledger(cases, external, leftover, export_ok=False)
            self.export(ledger)
        return ledger

    def write_ledger(self, cases: dict[str, dict], external: dict, leftover: dict, export_ok: bool,
                     provisional: bool = False) -> dict:
        build = self.state.get("build") or {}
        audit_summary = self.checks.get("traceAudit")
        x4 = self.x4_record or {}
        matched = x4.get("exceptionsUsed") or {}
        extra = {"x4": {"exceptions": [{"sha256": key, **value, "matched": matched.get(key, 0)}
                                       for key, value in X4_EXCEPTIONS.items()],
                        "notMetInThisRun": x4.get("exceptionsNotMet"), "committedScan": "x4-scan.json",
                        "rawLines": f"{X4_LINES} (git-ignored artifacts only)"},
                 "auditSupplements": audit_supplements(self.checks.get("traceAudit"), {
                     record["id"]: record for record in cases.values()}),
                 "checks": {key: value for key, value in self.checks.items() if key != "traceAudit"},
                 "flowRows": self.flow_rows, "fixedSentencesSha256": (self.fixed or {}).get("sha256"),
                 "liveCalls": self.live_calls if self.phase == "live" else None,
                 "liveCap": self.live_cap if self.phase == "live" else None,
                 "unclaimedRuns": list(self.unclaimed), "branchesWithoutTabText": list(self.without_texts),
                 "registry": sorted(BRANCH_REGISTRY),
                 "branchNotes": {branch: result.notes for branch, result in self.results.items()}}
        ledger = assemble_ledger(self.phase, cases, self.branches, build=build, leftover=leftover, external=external,
                                 trace_audit=audit_summary, export_ok=export_ok, rehearsal=self.rehearse,
                                 source_head=build.get("gitHead"), dirty_files=build.get("dirtyFiles") or [],
                                 extra=extra, runs_claimed=self.audited and not self.unclaimed)
        (self.artifacts / "case-ledger.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False,
                                                                    default=str) + "\n")
        # the pessimistic first write (export not yet searched) is recorded as provisional, never as a failed step
        passed = ledger["acceptance"] or ledger["rehearsalPassed"]
        status = "provisional" if provisional else "pass" if passed else "fail"
        self.record("case-ledger", status, acceptance=ledger["acceptance"], rehearsalPassed=ledger["rehearsalPassed"])
        return ledger

    # ----- evidence ----------------------------------------------------------------------------
    def real_text(self) -> m27.RealText | None:
        """Real kbase strings of the precedent set the branch-A module installed in this phase (memory only)."""
        active = self.precedent / "active.json"
        if not active.is_file():
            return None
        set_hash = json.loads(active.read_text())["set_hash"]
        return m27.RealText(m27.real_text_strings(self.precedent / "sets" / set_hash))

    def export(self, ledger: dict) -> bool:
        """Text evidence (redacted) to --out; held files listed by path, size and SHA-256 (a file still holding a leak
        after the redaction is held, T11); then the searches over the exported folder (key patterns, placeholders,
        absolute paths, real kbase text and, in a child, the key itself). A file of --out the searches still find
        (the summary, cases, README or listing the runner writes there itself) is moved back to the git-ignored
        ``<artifacts>/held-from-out/`` and dropped from SHA256SUMS, so a failed export leaves no leak in the committed
        folder. Returns whether the searches found nothing."""
        replacements = [(str(self.code), "<repo>"), (str(REPO), "<repo>"), (str(Path.home()), "<home>")]
        real = self.real_text()
        self.out.mkdir(parents=True, exist_ok=True)
        sums, files, held = [], [], []
        for path in sorted(self.artifacts.rglob("*")):
            rel = path.relative_to(self.artifacts)
            if not path.is_file() or rel.parts[0] == "services" or "browser-profile" in rel.parts:
                continue
            record = {"path": str(rel), "bytes": path.stat().st_size, "sha256": m13.sha_file(path)}
            reason = hold_reason(self.artifacts, path, real, replacements) if path.suffix in TEXT_SUFFIXES else None
            if path.suffix in TEXT_SUFFIXES and reason is None:
                target = self.out / "evidence" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(m13.redact(path.read_text(errors="replace"), replacements))
                sums.append(f"{m13.sha_file(target)}  evidence/{rel}")
            elif path.suffix in TEXT_SUFFIXES:
                held.append({**record, "held": reason})
            else:
                files.append(record)
        (self.out / "binary-artifacts.json").write_text(m13.redact(json.dumps({
            "note": "screenshots, paint frames, downloads, failure panels, text above 256 KiB and text holding a key "
                    "pattern, a placeholder or real kbase strings stay in the git-ignored artifacts folder; path, size "
                    "and sha256 only", "artifacts": str(self.artifacts), "files": files, "heldText": held},
            indent=2), replacements) + "\n")
        summary = {"schema": "m28_acceptance_summary@1", "phase": self.phase, "rehearsal": self.rehearse,
                   "acceptance": ledger["acceptance"], "rehearsalPassed": ledger["rehearsalPassed"],
                   "acceptanceParts": ledger["acceptanceParts"], "branches": ledger["branchesRequested"],
                   "definitionItems": {key: value["status"] for key, value in ledger["definition_items"].items()},
                   "external": ledger["external"], "leftover": ledger["leftover"], "traceAudit": ledger["trace_audit"],
                   "unobserved": ledger["unobserved"], "sourceHead": ledger["source_head"]}
        (self.out / "summary.json").write_text(m13.redact(json.dumps(summary, indent=2, ensure_ascii=False),
                                                          replacements) + "\n")
        (self.out / "cases.json").write_text(m13.redact(json.dumps(
            {"schema": "m28_acceptance_cases@1", "acceptance": ledger["acceptance"], "cases": ledger["cases"]},
            indent=2, ensure_ascii=False), replacements) + "\n")
        (self.out / "README.md").write_text(m13.redact(self.readme(ledger, held), replacements))
        for name in ("binary-artifacts.json", "summary.json", "cases.json", "README.md"):
            sums.append(f"{m13.sha_file(self.out / name)}  {name}")
        (self.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        found = scan_evidence(self.out, real)
        moved = self.move_back(found, sums)
        key = self.key_scan([self.out, self.artifacts, self.root])     # spec §6.2: evidence, QA root, export
        ok = not found and key.get("ok") is True and not (self.rehearse and self.resolver_calls)
        self.checks["exportScan"] = {"ok": ok, "files": found, "movedToArtifacts": moved, "keyScanOk": key.get("ok"),
                                     "keySearch": key.get("keySearch", "product resolver in a child"),
                                     "keyHits": key.get("keyHits", []), "sentinelHits": key.get("sentinelHits", []),
                                     "productKeyResolverCalls": self.resolver_calls}
        self.record("export-evidence", "pass" if ok else "fail", output=str(self.out), leaks=found,
                    keyScanOk=key.get("ok"), keySearch=self.checks["exportScan"]["keySearch"],
                    keyHits=len(key.get("keyHits", [])), sentinelHits=len(key.get("sentinelHits", [])),
                    productKeyResolverCalls=self.resolver_calls)
        return ok

    def move_back(self, found: dict[str, list[str]], sums: list[str]) -> list[str]:
        """Move every --out file the leak search found back to ``<artifacts>/held-from-out/`` (git-ignored) and write
        SHA256SUMS without them (T11); returns the moved paths (relative to --out)."""
        moved = []
        for rel in sorted(found):
            source = self.out / rel
            if not source.is_file() or rel == "SHA256SUMS":
                continue
            target = self.artifacts / "held-from-out" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append(rel)
        if moved:
            kept = [line for line in sums if line.split("  ", 1)[-1] not in moved]
            (self.out / "SHA256SUMS").write_text("\n".join(kept) + "\n")
        return moved

    def readme(self, ledger: dict, held: list[dict]) -> str:
        scope = "연습(fixture 서버, 실호출 0)" if ledger["rehearsal"] else ledger["phase"]
        lines = [f"# M28 종단 실데이터 수락 증거 ({scope})", "",
                 (f"- 생성: {ledger['generatedAt']} · acceptance **{str(ledger['acceptance']).lower()}**"
                  + (f" · 연습 통과 {ledger['rehearsalPassed']}" if ledger["rehearsal"] else "")),
                 f"- 요청한 분기: {', '.join(ledger['branchesRequested'])} (분기 일부만 돌리면 acceptance는 늘 false)",
                 f"- 소스: {ledger['source_head']} · 작업 트리 변경 {len(ledger['dirty_files'])}개",
                 f"- 외부 요청: {json.dumps(ledger['external'], ensure_ascii=False)}",
                 f"- 남은 프로세스·포트: {json.dumps(ledger['leftover'], ensure_ascii=False)}",
                 f"- 역추적 감사: {json.dumps(ledger['trace_audit'], ensure_ascii=False)}", "",
                 "## 정의 항목", "", "| 항목 | 이름 | 상태 | 사례 |", "|---|---|---|---|"]
        for number, item in ledger["definition_items"].items():
            lines.append(f"| {number} | {item['name']} | {item['status']} | {', '.join(item['cases'])} |")
        lines += ["", "## 사례", "", "| 사례 | 분기 | 상태 | 이유 |", "|---|---|---|---|"]
        for record in ledger["cases"]:
            lines.append(f"| {record['id']} | {record['branch']} | {record['status']} | {record['reason'] or ''} |")
        lines += ["", "## 관찰하지 못한 사례", ""]
        lines += [f"- {item['id']}: {item['reason']} ({item['class']}; 덮는 시험: "
                  f"{', '.join(item['covering_tests']) or '없음'})" for item in ledger["unobserved"]] or ["- 해당 없음"]
        lines += ["", (f"Git 제외로 둔 텍스트 {len(held)}개(경로·크기·SHA-256은 binary-artifacts.json). 절대 경로는 "
                       "`<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), ""]
        return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="a NEW QA root (<phase>/runs, reference, precedent_reference, "
                        "reaction_reference and fixture-control are made inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m28-final/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m28-final-<YYYYMMDD>/"
                        "acceptance-<phase>; with --rehearse <root>/out-live-rehearsal)")
    parser.add_argument("--phase", choices=PHASES, default="fixture")
    parser.add_argument("--branches", type=branches_arg, default=None, help="a subset of a,b,c (fixture default a,b,c; "
                        "live default b,c); fewer than all is never acceptance")
    parser.add_argument("--live-calls", type=live_calls_arg, default=None, help=f"real JEV calls this root may make "
                        f"(1..{MAX_LIVE_CALLS}); required by --phase live, default {MAX_LIVE_CALLS} with --rehearse")
    parser.add_argument("--rehearse", action="store_true", help="the live phase against the fixture server (no call)")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"), help="local kbase_kinase checkout (read "
                        "only; give an absolute path in a git worktree)")
    parser.add_argument("--m15-reference", default=".deps/reference", help="active M15 reference folder, copied "
                        "read-only (relative paths are taken from the code root)")
    parser.add_argument("--reaction-set", default=".deps/reaction_qa/import2",
                        help="installed M26 reaction set, copied into the phase folder (never written)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner from "
                        "the current frontend source")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
