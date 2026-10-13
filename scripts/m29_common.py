"""Shared, stable pieces of the M29 structure repair acceptance (.dryforge/spec.md 10; plan T11).

Used by the runner ``scripts/m29_offscreen_acceptance.py`` and the API-level case module ``scripts/m29_api_cases.py``.
Nothing here imports ``mw``: the product is reached over the loopback API, through subprocesses and by reading the
run's ``events.jsonl`` (read-only).

Case catalogue and judgement (pure functions)
  CASES                     the required case IDs (R1, R2, R3, R4a, R4b, R5 .. R11); the structure classification
                            table (spec 10.1) is part of R5 and is also written as its own table
  ALLOWED_PART_GAPS         the only parts that may stay not_observed in a passing case, each with its one closed
                            reason (spec 10.3: R4a docking ``receptor_atom_limit``, R4b docking ``no_model_time_limit``)
  NOT_OBSERVED_REASONS      the closed reasons of a not_observed case
  part(name, status, reason=None, **detail) -> dict
  case_record(case_id, parts, *, refs=(), detail=None) -> dict
      the case status from its parts: any fail -> fail; else a not_observed part other than an allowed gap ->
      not_observed (its reason); no part at all -> not_observed ``not_run``; else pass. not_observed and fail never
      count as pass (spec 10.3).
  complete_cases(records, selected) -> dict   every case, in order; a case not reported is not_observed (``not_run``
                                              when the --only subset left it out, else ``case_not_reported``)
  judge(cases, gates, *, rehearsal, subset) -> dict   acceptance only when every case passes, every gate holds, the
                                              whole catalogue ran and this is not a rehearsal

Expectations that are documents, not computations
  EXPECTED_TABLE            spec 10.1 / T1 preflight.md (a) + t3b-classification.tsv: structure -> water policy ->
                            verdict (the oracle must reproduce it; a unit test reads both documents)
  M21_BAND_MEASURED         T1 (g) / spec 10.1 measured M21 time table (2026-10-13): structure -> (band, heavy atoms,
                            seconds); other structures get ``band_for`` of the spec 10.1 rule with source ``rule``
  KLIFS_SEVEN               spec 5.3 / 10.3 R3: the seven 8VF6 key-site exclusions of the original structure
  FIXED                     RP1-RP6, SO1-SO3, JW1 verbatim from the spec (compared with the product's exported
                            constants by the runner)
  M18_MAX_RECEPTOR_ATOMS    the M18 receptor atom cap and (RECEPTOR_ATOM_LIMIT_*) its exact refusal, from the product
                            source read as text by a unit test (R4a docking gap)

Loopback API: ``Api`` (127.0.0.1 only; POST refuses the limit-raising and ``/jev`` / ``/jev_loops`` routes: those are
never the runner's; every request's status is kept for the "no 5xx" gate), ``enc``.
Events: ``read_events(runs, rid)``, ``stored_object(events, handle)`` (bytes of an ``object_created`` payload),
``handle_matches(events, handle)`` (the stored bytes still hash to the handle: never altered since they were stored).
Evidence hygiene: ``leak_kinds(text)`` (key patterns, placeholders, user absolute paths), ``forbidden_hits(text)``
(R11 wording, fixed sentence lines exempt when equal).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path("backend/tests/fixtures")
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
LEDGER_SCHEMA = "m29_case_ledger@1"
STATUSES = ("pass", "fail", "not_observed")
CASES = ("R1", "R2", "R3", "R4a", "R4b", "R5", "R6", "R7", "R8", "R9", "R10", "R11")
UI_CASES = ("R1", "R3", "R4a", "R10")
CASE_TITLES = {
    "R1": "8VF6 종단(UI): 불러오기·전처리·사전 검사·승인·작업·결과·내려받기·보완 보고서",
    "R2": "M7 통과: 보완 8VF6이 두 물 정책에서 게시되고 M21 입장이 openmm_preflight_failed 없이 열림",
    "R3": "M20 인계(UI): 원본 기준 번호 대응·주석·포켓, KLIFS 일곱 자리, 모델링 잔기 표시, SO1–SO3, @3",
    "R4a": "completes 구조(1HSG, UI): M21 작업 완료(240초)·M21 보고서 @2·같은 조건 도킹·M18 보고서 구조 출처",
    "R4b": "시간 상한 관측(8VF6 M21, 240초): 작업 실패·결과 없음·모델 0·1단위 환불 없음·프로세스 정리",
    "R5": "분류 표(13구조 × 물 정책 둘) = 독립 분류, in_scope 사슬(보완 → M20 → M21 입장), out_of_scope 거절",
    "R6": "기본 거절: §5.2 소비자 전부 repaired_structure_not_accepted, 인벤토리 시험, 뷰어 경로 없음",
    "R7": "입장 거절: nothing_to_repair·already_repaired·gap_too_long·합성 표시 다섯, 예산·작업 0",
    "R8": "MSE: 1RNH의 MSE 세 개 → MET, 대응표·RP5·치환 잔기 표시",
    "R9": "재열기: 이벤트만으로 보완 기록·구조·보고서, 저장된 M20 @1·@2·M21 @1 같은 바이트, 비보완 응답 바이트",
    "R10": "JEV 경고(UI): 미리보기·승인 화면 JW1, 전송 0, M23 화면 표시, M23 보고서 바이트 불변",
    "R11": "금지어: 새 화면·보고서·고정 문장에 금지어 0, 비폭로",
}
NOT_OBSERVED_REASONS = ("not_run", "case_not_reported", "prerequisite_failed", "saved_report_fixture_missing",
                        "receptor_atom_limit", "no_model_time_limit")
# spec 10.3 / 15.4: the parts that may be not_observed in a passing case, each with its one reason.
ALLOWED_PART_GAPS = {("R4a", "docking"): "receptor_atom_limit", ("R4b", "docking"): "no_model_time_limit"}

STRUCTURES = ("1m17", "1fin", "1mq4", "1s9i", "1a30", "1a4i", "1ubq", "1hsg", "8vf6", "1rnh", "4ins", "1ay7",
              "1cll")
WATERS = ("strip_all", "keep_all")
IN, OUT = "in_scope", "out_of_scope"
# spec 10.1 classification: T1 preflight.md (a) (nine structures) and t3b-classification.tsv (four).
EXPECTED_TABLE: dict[str, dict[str, str]] = {
    "8vf6": {"strip_all": IN, "keep_all": IN},
    "1m17": {"strip_all": IN, "keep_all": IN},
    "1mq4": {"strip_all": IN, "keep_all": IN},
    "1a30": {"strip_all": IN, "keep_all": IN},
    "1a4i": {"strip_all": IN, "keep_all": IN},
    "1hsg": {"strip_all": IN, "keep_all": IN},
    "1s9i": {"strip_all": f"{OUT}(gap_too_long)", "keep_all": f"{OUT}(gap_too_long)"},
    "1fin": {"strip_all": f"{OUT}(atom_limit_exceeded)", "keep_all": f"{OUT}(atom_limit_exceeded)"},
    "1ubq": {"strip_all": f"{OUT}(nothing_to_repair)", "keep_all": f"{OUT}(nothing_to_repair)"},
    "1rnh": {"strip_all": IN, "keep_all": IN},
    "4ins": {"strip_all": IN, "keep_all": IN},
    "1ay7": {"strip_all": f"{OUT}(nothing_to_repair)", "keep_all": IN},
    "1cll": {"strip_all": IN, "keep_all": IN},
}
# spec 10.1 / T1 preflight.md (g) and S1: measured M21 time of one model job after repair (2026-10-13, one loaded
# machine, one CPU). A documented measurement, never an independent computation of this runner.
M21_BAND_MEASURED: dict[str, tuple[str, int, float]] = {
    "1ubq": ("completes", 602, 20.7), "1hsg": ("completes", 1516, 118.0), "1a30": ("completes", 1542, 123.0),
    "1mq4": ("near_limit", 2160, 233.0), "1m17": ("exceeds", 2594, 310.0), "1a4i": ("exceeds", 4476, 992.0),
    "8vf6": ("exceeds", 4538, 1035.0)}
BAND_SOURCE_MEASURED = "T1 측정 표(docs/qa/m29-repair-20261013/preflight.md (g), 2026-10-13)"
BAND_SOURCE_RULE = "명세 §10.1 구간 규칙(중원자 약 1,600 이하 completes; 측정 없는 구조, 독립 계산이 아님)"


def band_for(name: str, heavy_after: int | None) -> dict:
    """The M21 band of one structure: the measured row when there is one, else the spec 10.1 rule on the protein
    heavy atoms after repair (completes <= 1,600 < near_limit <= 2,200 < exceeds)."""
    if name in M21_BAND_MEASURED:
        band, heavy, seconds = M21_BAND_MEASURED[name]
        return {"band": band, "heavyAtoms": heavy, "seconds": seconds, "source": BAND_SOURCE_MEASURED}
    if heavy_after is None:
        return {"band": None, "heavyAtoms": None, "seconds": None, "source": None}
    band = "completes" if heavy_after <= 1600 else "near_limit" if heavy_after <= 2200 else "exceeds"
    return {"band": band, "heavyAtoms": heavy_after, "seconds": None, "source": BAND_SOURCE_RULE}


KLIFS_SEVEN = ("A/145/LYS", "A/192/MET", "A/193/GLU", "A/194/LEU", "A/195/CYS", "A/264/THR", "A/265/ASP")
# The M18 receptor atom cap and its one refusal (backend/mw/docking_constants.py MAX_RECEPTOR_ATOMS and the
# ``receptor_invalid`` raise of backend/mw/docking_inputs.py; a unit test reads both files as text). Spec 10.3 R4a: only
# this refusal, on a receptor the oracle's lower bound puts above the cap, may leave the docking part not_observed.
M18_MAX_RECEPTOR_ATOMS = 10000
RECEPTOR_ATOM_LIMIT_REASON = "receptor_invalid"
RECEPTOR_ATOM_LIMIT_MESSAGE = f"receptor atom count must be 1-{M18_MAX_RECEPTOR_ATOMS}"
LIGAND_8VF6 = {"model_number": 1, "chain_auth": "A", "seq_auth": 600, "icode": "", "resname": "A1AAY"}
M21_TIMEOUT_S = 240
COORDINATE_TOLERANCE_A = 1e-9
REPAIR_TIMEOUT_S = 240          # API cases (the screen always sends its fixed 120 s)
REPAIR_PROTOCOL = "pdbfixer_repair_v1"
REPAIR_POLICY = "complete_missing_atoms_v1"
MODEL_PROTOCOL = "openmm_mutation_model_v1"
REFUSED = "repaired_structure_not_accepted"
REFUSED_MESSAGE = "보완 구조는 모델링 경로에서만 쓴다"

# spec 3.7 and 6.2 verbatim (the runner also compares the product constants, exported by a subprocess).
FIXED = {
    "RP1": "보완 구조의 추가 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다.",
    "RP2": "실험으로 관측한 원자의 좌표는 입력 그대로이며 추가·치환·원자 순서 변경만 기록했다.",
    "RP3": "메운 틈 구간은 단순한 기하로 놓은 가상 좌표이며 실제 구조가 아니다.",
    "RP4": "사슬의 관측된 끝이 서열의 끝과 다른 곳에도 말단 원자를 두었으므로 그 끝의 화학은 실제와 다를 수 있다.",
    "RP5": "MSE는 MET로 바꾸었고 셀레늄 원자는 황 원자로 대체했다. 원래 이름은 보완 기록에 있다.",
    "RP6": "같은 저자 체인 이름의 조각을 한 체인으로 합쳐 원자 순서가 바뀌었다. 잔기 식별자와 좌표는 그대로이다.",
    "SO1": "이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 "
           "아니다.",
    "SO2": "이 위치·보호 판정에는 모델링 원자 또는 잔기가 들어 있다.",
    "SO3": "번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 이었다. "
           "모델링한 잔기는 검사하지 않았다.",
    "JW1": "이 후보는 보완 구조 기준이며, 전송 본문은 이 사실을 담지 않는다.",
}


def expected_limitations(classes: Iterable[str], chain_end_differs: bool) -> list[str]:
    """Spec 3.7: RP1, RP2 always; RP3 gap; RP4 an observed end that differs; RP5 MSE; RP6 chain parts."""
    classes = set(classes)
    keep = {"RP3": "internal_gap_filled" in classes, "RP4": chain_end_differs,
            "RP5": "nonstandard_replaced" in classes, "RP6": "chain_parts_merged" in classes}
    return [FIXED[key] for key in ("RP1", "RP2", "RP3", "RP4", "RP5", "RP6") if keep.get(key, True)]


# ---------------------------------------------------------------------------------------------------- judgement
def part(name: str, status: str, reason: str | None = None, **detail: Any) -> dict:
    if status not in STATUSES:
        raise ValueError(f"part status {status!r}")
    if status == "pass" and reason is not None:
        raise ValueError("a passing part carries no reason")
    if status != "pass" and not reason:
        raise ValueError(f"part {name}: a {status} part needs a reason")
    if status == "not_observed" and str(reason).split(":", 1)[0] not in NOT_OBSERVED_REASONS:
        raise ValueError(f"part {name}: not_observed reason {reason!r} is outside the closed list")
    return {"name": name, "status": status, "reason": reason, "detail": detail}


def check(name: str, ok: bool, reason: str, **detail: Any) -> dict:
    """A part that passes when ``ok`` is exactly True (anything else is a fail with ``reason``)."""
    return part(name, "pass" if ok is True else "fail", None if ok is True else reason, **detail)


def case_record(case_id: str, parts: Iterable[dict], *, refs: Iterable[str] = (), detail: dict | None = None) -> dict:
    if case_id not in CASES:
        raise ValueError(f"unknown case {case_id!r}")
    parts = list(parts)
    gaps = []
    status, reason = "pass", None
    if not parts:
        status, reason = "not_observed", "not_run"
    elif any(item["status"] == "fail" for item in parts):
        failed = [item for item in parts if item["status"] == "fail"]
        status, reason = "fail", f"{failed[0]['name']}: {failed[0]['reason']}"
    else:
        for item in parts:
            if item["status"] != "not_observed":
                continue
            allowed = ALLOWED_PART_GAPS.get((case_id, item["name"]))
            if allowed is not None and item["reason"] == allowed:
                gaps.append({"part": item["name"], "reason": item["reason"]})
                continue
            status, reason = "not_observed", item["reason"]
            break
    return {"id": case_id, "title": CASE_TITLES[case_id], "status": status, "reason": reason, "parts": parts,
            "allowedGaps": gaps, "evidence_refs": list(refs), "detail": detail}


def complete_cases(records: dict[str, dict], selected: Iterable[str] = CASES) -> dict[str, dict]:
    chosen = set(selected)
    out = {}
    for case_id in CASES:
        if case_id in records:
            out[case_id] = records[case_id]
            continue
        reason = "case_not_reported" if case_id in chosen else "not_run"
        out[case_id] = {**case_record(case_id, []), "reason": reason}
    return out


def judge(cases: dict[str, dict], gates: dict[str, bool], *, rehearsal: bool, subset: bool) -> dict:
    """Acceptance: every case pass (not_observed and fail never count), every gate true, the whole catalogue, not a
    rehearsal. ``passed`` is the same without the rehearsal / subset rule (the rehearsal reports it)."""
    counts = {status: sum(1 for item in cases.values() if item["status"] == status) for status in STATUSES}
    all_pass = set(cases) == set(CASES) and all(item["status"] == "pass" for item in cases.values())
    gates_ok = bool(gates) and all(value is True for value in gates.values())
    passed = all_pass and gates_ok
    return {"acceptance": passed and not rehearsal and not subset, "passed": passed, "counts": counts,
            "gates": dict(gates), "notPassing": sorted(case for case, item in cases.items() if item["status"] != "pass")}


# ---------------------------------------------------------------------------------------------------- wording (R11)
FORBIDDEN = re.compile(
    r"안정성|ΔΔG|ddG|delta\s*delta|순위|추천|최적|개선|활성|예측|유망|좋은|나쁜|안전|점수|에너지|수소\s*결합|친화|"
    r"충돌\s*없음|\brank|\bbest\b|recommend|optimal|improv|predict|promising|\bgood\b|\bsafe|\bactiv(e|ity)\b|"
    r"\bscor(e|ing)\b|energ|hydrogen[\s_-]?bond|\bh-?bond|affinit|stabilit", re.IGNORECASE)
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|>~-])")
_BULLET = re.compile(r"^(?:[-*+>]\s+|\d+\.\s+)+")


def normalize_line(line: str) -> str:
    text = _BULLET.sub("", " ".join(_MARKDOWN_ESCAPE.sub(r"\1", str(line)).split())).strip()
    if len(text) > 4 and text.startswith("**") and text.endswith("**"):
        text = text[2:-2].strip()
    return text


FIXED_LINES = frozenset(normalize_line(text) for text in FIXED.values())


def forbidden_hits(text: str, exempt: Iterable[str] = (), *, skip_fixed: bool = True) -> list[dict]:
    """R11: the forbidden words line by line; a line equal to a fixed sentence (unless ``skip_fixed`` is false) or to
    one of ``exempt`` is skipped. Each hit keeps the words, the line's SHA-256 and length (never the line itself)."""
    skip = (FIXED_LINES if skip_fixed else frozenset()) | {normalize_line(item) for item in exempt}
    hits = []
    for raw in str(text).split("\n"):
        line = normalize_line(raw)
        if not line or line in skip:
            continue
        words = sorted({match.group(0) for match in FORBIDDEN.finditer(line)})
        if words:
            hits.append({"words": words, "line_sha256": hashlib.sha256(line.encode()).hexdigest(),
                         "chars": len(line)})
    return hits


KEY_PATTERNS = re.compile(r"sk-or-v1-[0-9A-Za-z]{16,}|\bsk-[0-9A-Za-z_-]{24,}|Bearer\s+[0-9A-Za-z._-]{16,}|"
                          r"OPENROUTER_API_KEY\s*=\s*\S+")
ABSOLUTE_PATH = re.compile(r"(?<![\w.:/<-])/(?:Users|home|private)/[^\s\"'<>`|)/]+")
SENTINELS = ("m25-loop-fixture-sentinel-placeholder-not-a-key", "m24-fixture-sentinel-placeholder-not-a-key")


def leak_kinds(text: str) -> list[str]:
    kinds = []
    if KEY_PATTERNS.search(text):
        kinds.append("key_pattern")
    if any(item in text for item in SENTINELS):
        kinds.append("placeholder")
    if ABSOLUTE_PATH.search(text):
        kinds.append("absolute_path")
    return kinds


# ---------------------------------------------------------------------------------------------------- loopback API
FORBIDDEN_POST_PARTS = ("limit_approval", "raise_limits", "/jev")
# The JEV send route, only ever LOOKED FOR among the page's own requests (R10 "no send"); ``Api`` refuses to send it.
JEV_SEND_ROUTE = "/jev/sends"


BUSY_REASONS = ("global_concurrency_busy", "global_job_cleanup_pending")


def busy_answer(status: int, body: Any) -> bool:
    """The product's designed 503 "busy, try again" (a held run or worker lock: ``ToolFailure`` transient with
    ``detail.busy``, or the JEV routes' ``{"detail": {"error": "busy"}}``): not a crash, so never a spec 10.2 5xx."""
    if status != 503 or not isinstance(body, dict):
        return False
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
    return detail.get("busy") is True or detail.get("error") == "busy" or detail.get("reason_code") in BUSY_REASONS


def enc(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


class Api:
    """Loopback API (127.0.0.1 only). Any request other than GET to a limit-raising route or a ``/jev`` /
    ``/jev_loops`` route raises before it is sent: approvals of limits and JEV sends are never the runner's. Every
    request sent is kept in ``sent`` with its answer's status (None when no HTTP answer came) for the spec 10.2 "no
    5xx" gate (``server_errors``)."""

    def __init__(self, base: str = API, timeout: float = 900) -> None:
        if not base.startswith("http://127.0.0.1:"):
            raise ValueError(f"loopback only: {base}")
        self.base, self.timeout = base.rstrip("/"), timeout
        self.sent: list[dict] = []

    def server_errors(self) -> list[dict]:
        """Every 5xx answer except the product's "busy, try again" 503 (``busy_answer``, kept in ``sent``)."""
        return [item for item in self.sent if isinstance(item.get("status"), int) and item["status"] >= 500
                and not item.get("busy")]

    def request(self, method: str, path: str, body: Any = None, *, raw: bool = False,
                ctype: str = "application/json") -> tuple[int, Any]:
        if method != "GET" and any(item in path for item in FORBIDDEN_POST_PARTS):
            raise PermissionError(f"the runner never sends {method} {path}")
        data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        sent = {"method": method, "path": path.split("?", 1)[0], "status": None}
        self.sent.append(sent)
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"content-type": ctype})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                sent["status"] = response.status
                return response.status, (payload if raw else json.loads(payload or b"null"))
        except urllib.error.HTTPError as exc:
            sent["status"] = exc.code
            payload = exc.read()
            try:
                answer: Any = json.loads(payload or b"null")
            except ValueError:
                answer = payload.decode(errors="replace")
            sent["busy"] = busy_answer(exc.code, answer)
            return exc.code, (payload if raw else answer)

    def get(self, path: str, raw: bool = False) -> tuple[int, Any]:
        return self.request("GET", path, raw=raw)

    def post(self, path: str, body: Any = None, ctype: str = "application/json") -> tuple[int, Any]:
        return self.request("POST", path, body, ctype=ctype)


# ---------------------------------------------------------------------------------------------------- events
def read_events(runs: Path, rid: str) -> list[dict]:
    path = Path(runs) / rid / "events.jsonl"
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            break          # a half-written last line is left for the next read
    return out


def stored_object(events: list[dict], handle: str) -> bytes:
    for event in events:
        if event.get("type") == "object_created" and event.get("handle") == handle:
            return base64.b64decode(event["payload_b64"])
    raise KeyError(handle)


def object_sha(kind: str, schema: str, raw: bytes) -> str:
    """The content hash of a stored object as the run's handles name it (kind NUL schema NUL bytes)."""
    return hashlib.sha256(kind.encode() + b"\0" + schema.encode() + b"\0" + raw).hexdigest()


def handle_matches(events: list[dict], handle: str) -> bool:
    for event in events:
        if event.get("type") == "object_created" and event.get("handle") == handle:
            raw = base64.b64decode(event["payload_b64"])
            return handle.rsplit("/", 1)[-1] == object_sha(event["kind"], event["schema"], raw)
    return False


def kind_count(events: list[dict], kind: str) -> int:
    return sum(1 for event in events if event.get("type") == "object_created" and event.get("kind") == kind)


def short_ref(item: dict) -> str:
    return f"{item['chain_auth']}/{item['seq_auth']}{item.get('icode') or ''}/{item['resname']}"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
