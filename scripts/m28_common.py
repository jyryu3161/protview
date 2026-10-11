"""Shared, stable entry points of the M28 end-to-end acceptance (.dryforge/spec.md §3.1, §4, §5, §6.3).

The runner ``scripts/m28_offscreen_acceptance.py`` and the branch modules ``scripts/m28_branch_{a,b,c}.py`` (T6–T8)
use only what is listed here; nothing here imports ``mw`` (the product is reached over the loopback API and through
subprocesses only). Names and signatures below are the contract with the branch modules.

Case catalogue and judgement (pure functions, no I/O)
  FIXTURE_CASES: tuple[str, ...]            the required fixture-phase case IDs (A1–A8, B1–B8, C1–C7, X1-A/B/C, X2–X6)
  LIVE_CASES: tuple[str, ...]               the required live-phase case IDs (L-pre-B2 … L-X6)
  CASE_BRANCH: dict[str, str]               case ID → "a" | "b" | "c" | "x" (common)
  DEFINITION_ITEMS: dict[int, dict]         spec §3.1 table: item → {"name", "parts": {part: [case IDs in chain order]}}
  PREREQUISITES: dict[str, tuple[str, ...]] case ID → the cases whose stored state it needs (cascade)
  ALLOWED_UNOBSERVED: tuple[str, ...]       the closed reasons a not_observed case may carry without blocking acceptance
  NOT_SENT_CAUSES: tuple[str, ...]          the closed causes of a live ``not_sent:<cause>`` reason
  case_record(case_id, status, reason=None, *, evidence_refs=(), covering_tests=(), detail=None) -> dict
      one case of the ledger (``m28_case_ledger@1`` ``cases[]`` entry); raises ValueError when the record breaks a
      rule of spec §3.1 (unknown ID or status, not_observed without a closed reason, an allowed reason without a
      named covering test, a pass with a reason)
  case_problems(record) -> list[str]        the same rules as messages (empty list = valid)
  reason_class(reason) -> str               "allowed" | "prerequisite" | "not_sent" | "invalid"
  cascade(records: dict[str, dict], order: Iterable[str], prerequisites=PREREQUISITES) -> dict[str, dict]
      a case whose prerequisite is not pass becomes not_observed with reason prerequisite_failed:<that prerequisite>
      (the case is not run); returns the completed records in ``order``
  combine_statuses(statuses) -> "pass" | "fail" | "not_observed"
      any fail → fail; else any not_observed → not_observed; else pass (an empty list is not_observed)
  definition_items(statuses: dict[str, str], phase) -> dict[str, dict]
      item "1".."6" → {"status", "cases", "parts": {part: status}}; fixture phase: item 5 is "pending_live" when its
      fixture parts all pass (spec §5); live phase: item 5 is its live part and the other items are null (the fixture
      ledger decides them)
  combine_items(fixture_items, live_items) -> dict[str, dict]
      the final item statuses from both ledgers (only pass / fail / not_observed)

Live results (spec §6.3)
  LIVE_RESULTS = ("completed", "provider_failed", "product_failed", "not_sent")
  live_case_status(result, *, not_sent_cause=None) -> (status, reason)
  live_outcome(results: dict[str, str], not_sent_causes: dict[str, str] | None = None) -> dict
      {"cases": {L-B7, L-C6 → (status, reason)}, "item5Live": status, "verdict": "보류" | None, "waivable": bool,
       "closing": [...]} — verdict None means the live part itself gives no hold reason

Wording (X4, spec §4.4)
  CORE_FORBIDDEN: re.Pattern                the core forbidden words of X4 (Korean list of the spec + English forms)
  FixedText(sentences=(), phrases=())       product fixed lines (exact after normalization) and inline phrases removed
                                            from a line before the check (e.g. the qvina score label)
  normalize_line(line) -> str               bullet / list marker / Markdown escape / HTML entity / whitespace
                                            normal form
  line_sha256(line) -> str                  SHA-256 of the normalized line (the key of an exception)
  forbidden_hits(text, fixed: FixedText, exceptions: dict[str, dict] | None = None)
      -> {"hits": [...], "excepted": [...]}
      exceptions: {line_sha256: {"reason": str (required), "words": [...]}}; an exception without a reason raises

Loopback API and runs
  API = "http://127.0.0.1:8000", WEB = "http://127.0.0.1:3000"
  class Api(base=API, timeout=900)
      .request(method, path, body=None, raw=False) -> (status, data)
      .get(path, raw=False) -> (status, data)
      .post(path, body) -> (status, data)          refuses limit-raising and /jev routes (the harness clicks them)
      .events(rid, after=0) -> list[dict]           every event of a run (pages of 500)
      .report_events(rid) -> list[dict]             report_created and method_report_created events
      .selected_report(rid, handle) -> (status, data)
      .meta(rid, handle) -> (status, data)
      .create_run(goal, *, egress="local_only", dry_run=False) -> str | None
  count_dispatch(runs_dir) -> dict[run_id, {"dispatch", "responseReceived", "scienceResponses"}]
  dispatch_total(counts) -> int
      (the M25 runner's event counter: a half-written last line is left for the next read)
  remaining_short(api, rid, needs) -> list[str]   the budget axes a run is short of before a computation or send

Branch interface (the runner's registry calls ``run(ctx) -> BranchResult``)
  BranchContext: phase, rehearse, branch, code, root, stage, runs, reference, precedent, reaction, artifacts, kbase,
      m15_reference, reaction_set, python, api, flow, record, child_env, fixture, live_calls, send_allowed
      send_allowed: live only; False once an earlier round was dispatched and did not complete (the plan ends: build
      the prerequisite state if useful, never send; the runner also stops a harness at its first new dispatch)
      flow(step, harness_file, mode, extra, limit=None) -> dict | None   a harness step (ledger-row.json of the step)
      record(step, status, **extra) -> None                            a runner-summary line
  BranchResult: cases (list of case_record dicts), runs (run IDs whose reports are audited), reports_created (the
      report POSTs the case code counted, for X1), texts ({name: screen or panel text} for X4), observations
      ({"X5": [(ok, detail)], ...}), live ({"L-B7": result, ...} in the live phase), not_sent_causes, notes
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The event counter of the M25 runner (same loopback rules; this module never imports mw).
import m25_offscreen_acceptance as m25

API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
LEDGER_SCHEMA = "m28_case_ledger@1"
BRANCHES = ("a", "b", "c")
STATUSES = ("pass", "fail", "not_observed")
ITEM_PENDING_LIVE = "pending_live"

# ---------------------------------------------------------------------------------------------------- cases
FIXTURE_CASES = (
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7",
    "X1-A", "X1-B", "X1-C", "X2", "X3", "X4", "X5", "X6",
)
LIVE_CASES = ("L-pre-B2", "L-pre-B3", "L-pre-B4", "L-pre-C2", "L-B7", "L-C6", "L-X3", "L-X4", "L-X6")
# The cases that must be true (pass) for a phase's acceptance (spec §5: X1-A/B/C and X2–X6 true).
MUST_PASS = {"fixture": ("X1-A", "X1-B", "X1-C", "X2", "X3", "X4", "X5", "X6"), "live": LIVE_CASES}


def _branch_of(case_id: str) -> str:
    if case_id.startswith("X1-"):
        return case_id[-1].lower()
    if case_id.startswith("L-pre-"):
        return case_id[len("L-pre-")].lower()
    if case_id in ("L-B7", "L-C6"):
        return case_id[2].lower()
    if case_id.startswith(("X", "L-X")):
        return "x"
    return case_id[0].lower()


CASE_BRANCH = {case: _branch_of(case) for case in (*FIXTURE_CASES, *LIVE_CASES)}

# Spec §3.1 table. Item 6 names the A-branch reports by the cases that make them (A2–A8); X1-A lists them.
DEFINITION_ITEMS: dict[int, dict] = {
    1: {"name": "구조 분석", "parts": {"chain": ["A1", "A2", "A3", "A4", "A6"]}},
    2: {"name": "지식", "parts": {"kinase": ["A5", "A6", "A7"], "enzyme": ["A8"]}},
    3: {"name": "리간드 설계·탐색", "parts": {"chain": ["B2", "B3", "B4"]}},
    4: {"name": "단백질 공학", "parts": {"protection": ["C1"], "modelling": ["C2", "C3"]}},
    5: {"name": "GA·JEV", "parts": {"ligand": ["B5", "B6", "B7"], "protein": ["C4", "C5", "C6"],
                                    "live": ["L-B7", "L-C6"]}},
    6: {"name": "보고서", "parts": {"reports": ["A2", "A3", "A4", "A5", "A6", "A7", "A8", "B8", "C7"],
                                  "lists": ["X1-A", "X1-B", "X1-C"], "audit": ["X2"]}},
}


def _items_of(case_id: str) -> list[int]:
    return [number for number, item in DEFINITION_ITEMS.items()
            if any(case_id in chain for chain in item["parts"].values())]


CASE_ITEMS = {case: _items_of(case) for case in (*FIXTURE_CASES, *LIVE_CASES)}

# The stored state each case needs from an earlier case (the cascade of spec §3.1; T1 (d)): a case is not run, and is
# not_observed prerequisite_failed:<ID>, when one of these is not pass. Branch modules may pass a stricter table.
PREREQUISITES: dict[str, tuple[str, ...]] = {
    "A2": ("A1",), "A3": ("A1",), "A4": ("A1",), "A5": ("A1",), "A6": ("A1", "A2", "A5"), "A7": ("A5",),
    "B3": ("B2",), "B4": ("B2",), "B5": ("B2",), "B6": ("B2",), "B7": ("B2", "B3"),
    "C3": ("C2",), "C4": ("C2",), "C5": ("C2",), "C6": ("C2",),
    "L-pre-B3": ("L-pre-B2",), "L-pre-B4": ("L-pre-B3",), "L-B7": ("L-pre-B2", "L-pre-B3", "L-pre-B4"),
    "L-C6": ("L-pre-C2",),
}

ALLOWED_UNOBSERVED = ("no_public_input", "unreachable_by_ui", "engine_unavailable_by_design")
NOT_SENT_CAUSES = ("earlier_provider_failed", "earlier_product_failed", "ledger_refused")
_PREREQ = re.compile(r"prerequisite_failed:(?P<case>[A-Za-z0-9-]+)")


def reason_class(reason: str | None) -> str:
    """Which closed family a not_observed reason belongs to: allowed (does not block acceptance when a covering test
    is named), prerequisite / not_sent (block acceptance), or invalid (outside every closed list)."""
    if reason in ALLOWED_UNOBSERVED:
        return "allowed"
    if isinstance(reason, str):
        found = _PREREQ.fullmatch(reason)
        if found and found["case"] in CASE_BRANCH:
            return "prerequisite"
        if reason.startswith("not_sent:"):
            cause = reason[len("not_sent:"):]
            found = _PREREQ.fullmatch(cause)
            if cause in NOT_SENT_CAUSES or (found and found["case"] in CASE_BRANCH):
                return "not_sent"
    return "invalid"


def case_problems(record: dict) -> list[str]:
    """The rules of spec §3.1 / §5 a case record breaks (empty = valid)."""
    problems = []
    case_id, status, reason = record.get("id"), record.get("status"), record.get("reason")
    if case_id not in CASE_BRANCH:
        problems.append(f"unknown case ID {case_id!r}")
    if status not in STATUSES:
        problems.append(f"status {status!r} is not one of {STATUSES}")
    if status == "pass" and reason is not None:
        problems.append("a pass carries no reason")
    if status == "not_observed":
        kind = reason_class(reason)
        if kind == "invalid":
            problems.append(f"not_observed reason {reason!r} is outside the closed lists")
        if kind == "allowed" and not [name for name in record.get("covering_tests") or [] if str(name).strip()]:
            problems.append(f"not_observed {reason} names no covering unit test")
    if reason is not None and not isinstance(reason, str):
        problems.append("reason must be a string or null")
    if not isinstance(record.get("evidence_refs", []), list):
        problems.append("evidence_refs must be a list")
    return problems


def case_record(case_id: str, status: str, reason: str | None = None, *, evidence_refs: Iterable[str] = (),
                covering_tests: Iterable[str] = (), detail: dict | None = None) -> dict:
    """One ``cases[]`` entry of ``m28_case_ledger@1`` (spec §5). Raises ValueError when it breaks a rule."""
    record = {"id": case_id, "branch": CASE_BRANCH.get(case_id), "definition_items": list(CASE_ITEMS.get(case_id, [])),
              "status": status, "reason": reason, "evidence_refs": list(evidence_refs),
              "covering_tests": list(covering_tests), "detail": detail}
    problems = case_problems(record)
    if problems:
        raise ValueError(f"{case_id}: " + "; ".join(problems))
    return record


def cascade(records: dict[str, dict], order: Iterable[str],
            prerequisites: dict[str, tuple[str, ...]] = PREREQUISITES) -> dict[str, dict]:
    """Records in ``order``. A reported case keeps its record (it ran: its prerequisite state existed). A case that was
    not reported and whose prerequisite is absent or not pass becomes not_observed with reason
    ``prerequisite_failed:<the first such prerequisite>`` (it was not run for want of that state); other unreported
    cases stay absent (the caller decides)."""
    done: dict[str, dict] = {}
    for case_id in order:
        if case_id in records:
            done[case_id] = records[case_id]
            continue
        blocked = next((need for need in prerequisites.get(case_id, ())
                        if (done.get(need) or records.get(need) or {}).get("status") != "pass"), None)
        if blocked is not None:
            done[case_id] = case_record(case_id, "not_observed", f"prerequisite_failed:{blocked}")
    return done


def combine_statuses(statuses: Iterable[str | None]) -> str:
    """Spec §3.1: any fail → fail; else any not_observed (or absent) → not_observed; else pass."""
    values = list(statuses)
    if not values:
        return "not_observed"
    if "fail" in values:
        return "fail"
    if any(value != "pass" for value in values):
        return "not_observed"
    return "pass"


def definition_items(statuses: dict[str, str], phase: str) -> dict[str, dict]:
    """Item "1".."6" → {"status", "cases", "parts"} from the case statuses of one phase ledger (spec §3.1, §5)."""
    out: dict[str, dict] = {}
    for number, item in DEFINITION_ITEMS.items():
        parts: dict[str, str | None] = {}
        for part, chain in item["parts"].items():
            in_phase = [case for case in chain if (case in LIVE_CASES) == (phase == "live")]
            parts[part] = combine_statuses(statuses.get(case) for case in in_phase) if in_phase else None
        cases = [case for chain in item["parts"].values() for case in chain]
        known = [value for value in parts.values() if value is not None]
        if phase == "live":
            status = parts.get("live") if number == 5 else None
        else:
            status = combine_statuses(known)
            if number == 5 and status == "pass":
                status = ITEM_PENDING_LIVE
        out[str(number)] = {"name": item["name"], "status": status, "cases": cases, "parts": parts}
    return out


def combine_items(fixture_items: dict[str, dict], live_items: dict[str, dict]) -> dict[str, dict]:
    """The final item statuses from both phase ledgers (only pass / fail / not_observed; spec §3.1, §5)."""
    out: dict[str, dict] = {}
    for number in map(str, DEFINITION_ITEMS):
        fixture = fixture_items.get(number) or {}
        parts = dict(fixture.get("parts") or {})
        if number == "5":
            parts["live"] = ((live_items.get(number) or {}).get("parts") or {}).get("live")
        status = combine_statuses(parts.get(part) for part in DEFINITION_ITEMS[int(number)]["parts"])
        out[number] = {"name": DEFINITION_ITEMS[int(number)]["name"], "status": status, "parts": parts,
                       "cases": fixture.get("cases") or [c for p in DEFINITION_ITEMS[int(number)]["parts"].values()
                                                         for c in p]}
    return out


# ---------------------------------------------------------------------------------------------------- live results
LIVE_RESULTS = ("completed", "provider_failed", "product_failed", "not_sent")
LIVE_ROUNDS = ("L-B7", "L-C6")
HOLD = "보류"


def live_case_status(result: str, *, not_sent_cause: str | None = None) -> tuple[str, str | None]:
    """Spec §6.3: completed → pass; provider_failed / product_failed → fail with that reason; not_sent →
    not_observed with not_sent:<cause>. Anything else (or not_sent without a closed cause) raises ValueError."""
    if result == "completed":
        return "pass", None
    if result in ("provider_failed", "product_failed"):
        return "fail", result
    if result == "not_sent":
        reason = f"not_sent:{not_sent_cause}"
        if reason_class(reason) != "not_sent":
            raise ValueError(f"not_sent needs a closed cause (got {not_sent_cause!r})")
        return "not_observed", reason
    raise ValueError(f"live result {result!r} is not one of {LIVE_RESULTS}")


def next_round_cause(earlier_result: str) -> str | None:
    """The not_sent cause of the second round when the first did not complete (spec §6.1: the plan ends)."""
    return {"provider_failed": "earlier_provider_failed", "product_failed": "earlier_product_failed"}.get(
        earlier_result)


def live_outcome(results: dict[str, str], not_sent_causes: dict[str, str] | None = None) -> dict:
    """The §6.3 table: the two rounds' results → their case states, item 5's live part, the hold reason, whether the
    user may waive it and the closing conditions. A round without a result is not_sent; every not_sent round needs
    its closed cause in ``not_sent_causes`` (ValueError otherwise)."""
    causes = not_sent_causes or {}
    values = {round_id: results.get(round_id, "not_sent") for round_id in LIVE_ROUNDS}
    cases = {round_id: live_case_status(value, not_sent_cause=causes.get(round_id) if value == "not_sent" else None)
             for round_id, value in values.items()}
    item = combine_statuses(status for status, _ in cases.values())
    open_rounds = {round_id: value for round_id, value in values.items() if value != "completed"}
    if not open_rounds:
        return {"cases": cases, "item5Live": item, "verdict": None, "waivable": False, "closing": []}
    provider_only = all(value == "provider_failed" or causes.get(round_id) == "earlier_provider_failed"
                        for round_id, value in open_rounds.items())
    closing = []
    if "product_failed" in open_rounds.values() or any(causes.get(r) == "earlier_product_failed" for r in open_rounds):
        closing += ["fix the product defect (product_failed is never waived)",
                    "the user sets a new allocation of real calls"]
    elif provider_only:
        closing += ["the user sets a new allocation of real calls",
                    "or the user waives it and the scope table says 실모델 미관찰(제공자 실패)"]
    if any(_PREREQ.fullmatch(causes.get(round_id, "")) for round_id in open_rounds):
        closing += ["fix the prerequisite defect",
                    "the user sets the allocation again (the calls not sent were not used)"]
    if not closing:
        closing.append("the user decides how to run the live phase again (no call was sent)")
    return {"cases": cases, "item5Live": item, "verdict": HOLD, "waivable": provider_only, "closing": closing}


# ---------------------------------------------------------------------------------------------------- wording (X4)
CORE_FORBIDDEN = re.compile(
    r"순위|최고|개선|승자|추천|친화도|ΔΔG|안정성|좋아짐|수소\s*결합|\brank(?:s|ed|ing)?\b|\bbest\b|\bimprov\w*|"
    r"\bwinners?\b|\brecommend\w*|\baffinit(?:y|ies)\b|\bddg\b|\bstabilit(?:y|ies)\b|hydrogen[\s-]+bonds?",
    re.IGNORECASE)
_BULLET = re.compile(r"^(?:[-*+>]\s+|\d+\.\s+)+")
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|>~-])")


def normalize_line(line: str) -> str:
    """The form fixed sentences and screen / report lines are compared in: Markdown escapes and HTML entities undone,
    list markers removed, whitespace collapsed."""
    text = html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", str(line)))
    text = " ".join(text.split())
    return _BULLET.sub("", text).strip()


def line_sha256(line: str) -> str:
    return hashlib.sha256(normalize_line(line).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixedText:
    """Product fixed lines (exempt when a line equals one after normalization) and inline phrases (removed from a
    line before the check: score labels)."""
    sentences: frozenset = frozenset()
    phrases: tuple = ()

    @classmethod
    def build(cls, sentences: Iterable[str] = (), phrases: Iterable[str] = ()) -> FixedText:
        return cls(frozenset(normalize_line(text) for text in sentences if str(text).strip()),
                   tuple(sorted({str(p) for p in phrases if str(p).strip()}, key=len, reverse=True)))

    @classmethod
    def from_export(cls, exported: dict) -> FixedText:
        """From the JSON of scripts/m28_export_fixed_sentences.py (sentences + inline literals; phrases)."""
        texts = [item["text"] for key in ("sentences", "inline") for item in exported.get(key) or []]
        return cls.build(texts, [item["text"] for item in exported.get("phrases") or []])


def forbidden_hits(text: str, fixed: FixedText, exceptions: dict[str, dict] | None = None) -> dict:
    """X4 core forbidden words in ``text`` line by line. A line equal to a fixed sentence is exempt; inline phrases are
    removed first; a hit whose normalized line SHA-256 is in ``exceptions`` (each with a reason) is listed apart."""
    exceptions = exceptions or {}
    for key, entry in exceptions.items():
        if not (isinstance(entry, dict) and str(entry.get("reason") or "").strip()):
            raise ValueError(f"exception {key} has no reason")
    hits, excepted = [], []
    for raw in str(text).split("\n"):
        line = normalize_line(raw)
        if not line or line in fixed.sentences:
            continue
        checked = line
        for phrase in fixed.phrases:
            checked = checked.replace(normalize_line(phrase), "")
        words = sorted({match.group(0) for match in CORE_FORBIDDEN.finditer(checked)})
        if not words:
            continue
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        entry = {"line_sha256": digest, "words": words, "chars": len(line), "text": line}
        (excepted if digest in exceptions else hits).append(
            {**entry, "reason": exceptions[digest]["reason"]} if digest in exceptions else entry)
    return {"hits": hits, "excepted": excepted}


# ---------------------------------------------------------------------------------------------------- loopback API
FORBIDDEN_POST_PARTS = ("limit_approval", "raise_limits", "/jev")


class Api:
    """Loopback API helper (127.0.0.1 only). POST refuses the limit-raising and JEV routes: approvals, raises and sends
    are the harness's real clicks."""

    def __init__(self, base: str = API, timeout: float = 900) -> None:
        if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError(f"loopback only: {base}")
        self.base, self.timeout = base.rstrip("/"), timeout

    def request(self, method: str, path: str, body: object = None, raw: bool = False) -> tuple[int, Any]:
        if method != "GET" and any(part in path for part in FORBIDDEN_POST_PARTS):
            raise PermissionError(f"the runner never calls {path} (a human click in the harness does)")
        data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                return response.status, (payload if raw else json.loads(payload or b"null"))
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload or b"null")
            except ValueError:
                return exc.code, payload.decode(errors="replace")

    def get(self, path: str, raw: bool = False) -> tuple[int, Any]:
        return self.request("GET", path, raw=raw)

    def post(self, path: str, body: object) -> tuple[int, Any]:
        return self.request("POST", path, body)

    def events(self, rid: str, after: int = 0) -> list[dict]:
        found: list[dict] = []
        while True:
            status, page = self.get(f"/runs/{rid}/events?after={after}&limit=500")
            if status != 200 or not isinstance(page, list):
                raise RuntimeError(f"events of {rid} unreadable (HTTP {status})")
            found += page
            if len(page) < 500:
                return found
            after = page[-1]["seq"]

    def report_events(self, rid: str) -> list[dict]:
        return [event for event in self.events(rid) if event.get("type") in ("report_created", "method_report_created")]

    def selected_report(self, rid: str, handle: str) -> tuple[int, Any]:
        return self.get(f"/runs/{rid}/reports/selected?handle={urllib.parse.quote(handle, safe='')}")

    def meta(self, rid: str, handle: str) -> tuple[int, Any]:
        return self.get(f"/runs/{rid}/objects/meta?handle={urllib.parse.quote(handle, safe='')}")

    def create_run(self, goal: str, *, egress: str = "local_only", dry_run: bool = False) -> str | None:
        status, made = self.post("/runs", {"goal": goal, "context": [], "dry_run": dry_run, "egress": egress})
        return made.get("run_id") if status in (200, 201) and isinstance(made, dict) else None


def remaining_short(api: Api, rid: str, needs: dict) -> list[str]:
    """The budget axes a run's remaining budget is short of ``needs`` (``expensive_units``, ``wall_clock_s``,
    ``external_tokens``, ``usd``, ``sends``; GET /runs/{rid}/budget and /jev/status; the M25 runner's rule).
    ``["unreadable"]`` when either read fails."""
    status, budget = api.get(f"/runs/{rid}/budget")
    jev_status, jev = api.get(f"/runs/{rid}/jev/status")
    if status != 200 or jev_status != 200 or not isinstance(budget, dict) or not isinstance(jev, dict):
        return ["unreadable"]
    return m25.remaining_ok(needs, budget, jev)


def count_dispatch(runs_dir: Path) -> dict[str, dict[str, int]]:
    """``jev_science_dispatch_started`` events and egress response audits per run (the M25 runner's counter)."""
    return m25.count_events(Path(runs_dir))


def dispatch_total(counts: dict[str, dict[str, int]]) -> int:
    return m25.dispatch_total(counts)


# ---------------------------------------------------------------------------------------------------- branch interface
@dataclass
class BranchContext:
    """What the runner gives a branch module (spec §5 services and folders; see the module docstring)."""
    phase: str
    rehearse: bool
    branch: str
    code: Path
    root: Path
    stage: Path
    runs: Path
    reference: Path
    precedent: Path
    reaction: Path
    artifacts: Path
    kbase: Path
    m15_reference: Path
    reaction_set: Path
    python: Path
    api: Api
    flow: Callable[..., dict | None]
    record: Callable[..., None]
    child_env: Callable[..., dict]
    fixture: dict | None = None
    live_calls: int = 0
    send_allowed: bool = True        # live: False once a dispatched round did not complete (spec §6.1)


@dataclass
class BranchResult:
    """What a branch module returns (see the module docstring)."""
    cases: list[dict] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    reports_created: int | None = None
    texts: dict[str, str] = field(default_factory=dict)
    observations: dict[str, list] = field(default_factory=dict)
    live: dict[str, str] = field(default_factory=dict)
    not_sent_causes: dict[str, str] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)
