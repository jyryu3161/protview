"""Immutable, field-cited reports for one ended JEV design loop (``method_report_manifest@1``,
``analysis_type: "jev_loop"``, render ``jev_loop_markdown@1`` "JEV 루프 보고서"; spec .dryforge/spec.md 8.3, 9.3).

The input is one ``jev_loop_result@1`` summary handle, read through ``jev_loop_store.stored_result`` (an object of
this run whose loop's ``jev_loop_ended`` event names it, equal to the summary its loop's record at that event makes).
Making, reopening and downloading a report read stored objects and run events only: nothing is computed, projected,
sent or chosen again (``generation_mode: "local_rules_no_egress"``) and no read writes an event. Every claim is one
of two evidence kinds that never mix:

- ``computed`` -- ProtView values: from the summary, the pool (``count(pool.candidates)``, the candidate set handle),
  the loop settings (``loop_seed``, ``iteration_cap``, ``effective_cap``, ``setup_sha256``, the docking values in
  ``setup.parameters`` and the protein ``setup.contact_cutoff_A``) and the seven ``counts`` (iterations started and
  done, iterations decided by JEV and by the person, sends dispatched, charged units, reused candidates); and for each
  ``scored`` candidate only, two score claims with ``row_selector {"candidate": i}``: the summary's
  ``candidates[i].score_kcal_mol`` and the first mode ``modes[0].score_kcal_mol`` of that candidate's stored M18
  result (computed: its iteration's docking step result; reused: the stored result of its call key at the loop's
  end), which must hold the same value, rendered to 0.1 with ``ROUND_HALF_UP``. A candidate without a score has no
  claim and an empty cell (never 0).
- ``model_response`` -- the external model's reply, a proposal and not scientific evidence (each claim carries that
  note and the proposal handle; ``row_selector {"iteration": n}``): for each iteration decided by JEV only, the list
  position and list size of the chosen alias (``answer.list_position`` / ``answer.list_size``), the model-reported
  confidence (``answer.confidence``; "보고 없음" and no claim when absent) and the arrival (``arrival.late``). The
  chosen candidate's local notation (``answer.local_display``) is identification data in a template slot (``chosen``),
  not a claim. An iteration the person named has no model-response claim even when a JEV reply exists.

Per-candidate probabilities, ranks, differences and improvement claims never exist. A computed claim that cites a
model-response field, a model-response claim that cites a computed field, a probability field, a wrong value or an
edited manifest or Markdown is ``report_evidence_invalid`` (``EvidenceError`` here). The renderer refuses interpretive
wording (the M24 list plus the loop additions) on every template line with every identifier and value slot left empty,
except a line that is exactly one LJ sentence; on other lines only the exact M18 score-name texts are removed first.

This module never imports the M24 send module or the gate, never sends, submits, starts or retries anything and never
names a limit path. The proposals are the loop's own validated ``jev_loop_choice@1`` objects at the loop's end
(``jev_loop_store.load_proposals``).

M29 T8 (report format ``jev_loop_markdown@2``, ``jev_loop_constants.REPORT_RENDER_V2``; spec .dryforge/spec.md 6.3):
the report of a protein-branch loop whose pool's candidate set is on a repaired structure
(``structure_origin_reports.origin``, the record re-validated with its publication) is @2, and only such a loop's
report is: the @1 manifest keys plus ``structure_origin``, the two computed record-count claims (citing the
``structure_repair@1`` record) after the @1 claims, and a "구조 출처" section (SO1, the handles, the two counts) before
the limitations. Ligand loops and every other protein loop keep @1 (``REPORT_RENDER``) and its bytes.
"""
from __future__ import annotations

import copy
import math
import re
import uuid
from typing import Any

from . import docking_bundle as db
from . import docking_constants as DC
from . import docking_reports as dr
from . import jev_loop_constants as L
from . import jev_loop_result as LR
from . import jev_loop_store as LS
from . import jev_loops as JL
from . import numbering_reports as nr
from . import structure_origin_reports as origin_reports
from .core.handles import canonical_json
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md, _ref

ANALYSIS_TYPE = L.REPORT_ANALYSIS_TYPE
RENDER_VERSION = L.REPORT_RENDER
RENDER_VERSION_V2 = L.REPORT_RENDER_V2   # M29 T8: a protein loop on a repaired structure
GENERATION_MODE = L.REPORT_GENERATION_MODE
REPORT_BYTES = dr.REPORT_BYTES
EVIDENCE_KINDS = L.REPORT_EVIDENCE_KINDS
EXTERNAL_RESPONSE = {"kind": L.CHOICE_KIND, "scientific_evidence": False}
MODEL_RESPONSE_NOTE = "외부 모델의 응답, 제안이며 과학 증거가 아니다"
NOT_REPORTED = "보고 없음"
SCORE_ROW_LABEL = "모드 1(엔진 출력 순서)"
SCORE_STEP = {"ligand": "ligand_dock", "protein": "dock"}           # the step whose M18 result scores a candidate
RESULT_KIND, RESULT_SCHEMA = db.OUTPUT_KIND, "docking_result@1"
SUMMARY = (L.RESULT_KIND, L.RESULT_SCHEMA)
CHOICE = (L.CHOICE_KIND, L.CHOICE_SCHEMA)
FIXED_LINES = frozenset(L.STATEMENTS.values())
SCORE_TEXTS = (DC.SCORE_LABEL, DC.SCORE_COLUMN_LABEL)              # removed from a line before its check
EVIDENCE_STATEMENT = ("이 보고서의 계산값은 저장된 루프 요약 객체의 값과, 그 요약이 가리키는 후보별 도킹 결과 객체의 "
                      "첫 모드 값이다. JEV 판정은 루프가 저장한 제안 객체에서 읽은 외부 모델의 응답이며 과학 증거가 "
                      "아니다. 이 보고서를 만들려고 계산하거나 보낸 것은 없다.")
SETUP_PARAMETERS = ("seed", "exhaustiveness", "num_modes", "energy_range")
LATE_FLAG = {False: "아니오 (false)", True: "예 (true)"}

_COUNTS = "|".join(JL.COUNT_KEYS)
# statement ID -> (evidence kind, field rule, (source kind, source schema)); fixed template.
STATEMENTS = {
    "pool_size": ("computed", re.compile(r"pool\.candidates"), SUMMARY),
    "pool_source": ("computed", re.compile(r"pool\.source\.handle"), SUMMARY),
    "loop_setting": ("computed", re.compile(r"loop_seed|iteration_cap|effective_cap|setup_sha256"), SUMMARY),
    "setup_value": ("computed", re.compile(r"setup\.(parameters\.(" + "|".join(SETUP_PARAMETERS) + r")|"
                                           r"contact_cutoff_A)"), SUMMARY),
    "count": ("computed", re.compile(rf"counts\.({_COUNTS})"), SUMMARY),
    "candidate_score": ("computed", re.compile(r"candidates\[\d+\]\.score_kcal_mol"), SUMMARY),
    "candidate_result_score": ("computed", re.compile(r"modes\[0\]\.score_kcal_mol"), (RESULT_KIND, RESULT_SCHEMA)),
    "list_position": ("model_response", re.compile(r"answer\.list_position"), CHOICE),
    "list_size": ("model_response", re.compile(r"answer\.list_size"), CHOICE),
    "confidence": ("model_response", re.compile(r"answer\.confidence"), CHOICE),
    "arrival_late": ("model_response", re.compile(r"arrival\.late"), CHOICE),
}
COMPUTED_FIELDS = re.compile("|".join(f"(?:{rule.pattern})" for kind, rule, _ in STATEMENTS.values()
                                      if kind == "computed"))
MODEL_RESPONSE_FIELDS = re.compile(r"(?:answer|arrival)\..*")
CLAIM_KEYS = nr.CLAIM_KEYS
# The M24 report list (spec 8.3): its M15 base plus its additions, written out here because this module never imports
# the M24 report module (that one imports the send module); a test checks it is the M24 pattern. Then the loop
# additions: lowest / highest, getting better, winner, average, difference and comparison wording.
_M24 = (nr.INTERPRETIVE.pattern + r"|순위|추천|최적|개선|예측|유망|좋은|나쁜|안전|점수|에너지|활성|친화도|안정성|ΔΔG|ddG|"
        r"delta\s*delta|\bwinner|\bbest\b|\brank|recommend|optimal|improv|predict|promising|\bgood\b|\bbad\b|\bsafe|"
        r"\bactiv(e|ity)\b|\bscor(e|ing)\b|energ")
INTERPRETIVE = re.compile(
    _M24 + r"|최저|최고|최솟값|최댓값|좋아짐|좋아진|나아짐|승자|우승|향상|악화|우수|상위|하위|평균|차이|증감|변화량|비교|대비|"
    r"lowest|highest|\bwin\b|better|worse|superior|average|\bmean\b|\bdiff|compar", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget"}
COPIED_FIELDS = ("branch", "loop_id", "goal", "loop_seed", "iteration_cap", "effective_cap", "end_reason", "pool",
                 "setup", "setup_sha256", "pins", "counts", "candidates", "iterations", "unfinished")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "external_response", *COPIED_FIELDS, "score_label", "score_column_label", "chosen", "claims",
    "provenance", "evidence_statement", "limitation_ids", "limitations", "snapshot", "markdown_handle"})
MANIFEST_KEYS_BY_VERSION = {RENDER_VERSION: MANIFEST_KEYS, RENDER_VERSION_V2: MANIFEST_KEYS | {"structure_origin"}}


# ---------------------------------------------------------------------------------------------------------------
# rendering helpers

def _render(value: Any, rounding: str) -> str:
    if rounding == "score_1dp":
        return dr.render_score(value)                       # Decimal(str(v)) to 0.1, ROUND_HALF_UP
    if rounding == "integer" and type(value) is int:
        return str(value)
    if rounding == "identifier" and type(value) is str:
        return value
    if rounding in ("input_decimal", "exact_number") and (
            type(value) is int or (type(value) is float and math.isfinite(value))):
        return str(value)                                   # the stored value as written (no rounding)
    if rounding == "late_flag" and type(value) is bool:
        return LATE_FLAG[value]
    raise EvidenceError("jev_loop_claim_value_type")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one LJ sentence or the M29 structure origin
    sentence (SO1); the exact M18 score-name texts are removed from a line before it is checked."""
    for line in text.split("\n"):
        if line in FIXED_LINES or line in origin_reports.FIXED_LINES:
            continue
        for label in SCORE_TEXTS:
            line = line.replace(label, "")
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"jev_loop_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects and events only)

def _sources(run: Any, handle: str) -> dict[str, Any]:
    """The validated summary and what its claims cite: the loop's end and creation events, the validated stored M18
    results of its candidates' call keys at the end, and its validated proposals at the end."""
    view = LS.LoopReadView(run)
    try:
        content = LS.stored_result(view, handle)
        events = view.read()
        loop_id = content["loop_id"]
        created = next(event for event in events if event.get("type") == L.EVENT_CREATED
                       and event.get("loop_id") == loop_id)
        ended = next(event for event in events if event.get("type") == L.EVENT_ENDED
                     and event.get("loop_id") == loop_id)
        at_end = LS.LoopReadView(view, [event for event in events if event["seq"] <= ended["seq"]])
        payload = LS.created_payload(at_end.read(), loop_id)
        results, models = LS.load_results(at_end, payload, LS.loop_approvals(at_end.read(), loop_id))
        keys = LS.candidate_keys(payload, models)
        proposals = LS.load_proposals(at_end, payload)
    except (LR.LoopResultInvalid, JL.LoopRecordInvalid, LookupError, ValueError, TypeError, StopIteration) as exc:
        raise EvidenceError(f"jev_loop_result_invalid: {exc}") from exc
    return {"content": content, "results": results, "keys": keys, "proposals": proposals,
            "provenance": {"created_event_seq": created["seq"], "ended_event_seq": ended["seq"]}}


def _scored_result(content: dict[str, Any], row: dict[str, Any], results: dict[str, Any],
                   keys: dict[Any, Any]) -> dict[str, Any]:
    """The stored M18 result summary {result_handle, mode_count, score_kcal_mol} that scores a ``scored`` candidate:
    its own iteration's last docking step with a result (computed), or its call key's stored result (reused)."""
    step_name = SCORE_STEP[content["branch"]]
    if row["evaluation"] == "reused":
        summary = results.get(keys[row["ref"]][step_name])
    else:
        iteration = content["iterations"][row["iteration"] - 1]
        steps = [step for step in iteration["steps"] if step["step"] == step_name and step["result_handle"] is not None
                 and canonical_json(step["candidate_ref"]) == canonical_json(row["ref"])]
        summary = results.get(steps[-1]["call_key"]) if steps else None
        if summary is not None and summary["result_handle"] != steps[-1]["result_handle"]:
            raise EvidenceError("jev_loop_report_result_mismatch")
    if summary is None or summary["mode_count"] < 1:
        raise EvidenceError("jev_loop_report_result_missing")
    return summary


def _chosen(content: dict[str, Any], proposals: dict[str, Any]) -> list[dict[str, Any]]:
    """{iteration, proposal_handle, local_ref, local_display} of each iteration decided by JEV, its proposal checked
    against the iteration (this loop and iteration, in time, the same candidate, list place)."""
    chosen = []
    for row in content["iterations"]:
        if row["decided_by"] != "jev":
            continue
        proposal = proposals.get(row["proposal_handle"])
        if proposal is None:
            raise EvidenceError("jev_loop_report_proposal_missing")
        answer, loop = proposal["answer"], proposal["loop"]
        local = answer["local_ref"].get("candidate_id", answer["local_ref"].get("candidate_index"))
        if (loop["loop_id"] != content["loop_id"] or loop["iteration"] != row["index"]
                or proposal["arrival"]["late"] is not False
                or canonical_json(local) != canonical_json(row["candidate_ref"])
                or (answer["list_position"], answer["list_size"]) != (row["list_position"], row["list_size"])):
            raise EvidenceError("jev_loop_report_proposal_mismatch")
        chosen.append({"iteration": row["index"], "proposal_handle": row["proposal_handle"],
                       "local_ref": copy.deepcopy(answer["local_ref"]),
                       "local_display": copy.deepcopy(answer["local_display"])})
    return chosen


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None = None) -> dict[str, Any]:
    kind, _rule, (source_kind, source_schema) = STATEMENTS[statement_id]
    return {"statement_id": statement_id, "evidence_kind": kind, "source_handle": handle,
            "source_kind": source_kind, "source_schema": source_schema, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation,
            "reference": ({"note": MODEL_RESPONSE_NOTE, "proposal_handle": handle} if kind == "model_response"
                          else None)}


def claims_for(handle: str, sources: dict[str, Any], chosen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every value statement of the report, in template order."""
    content, results, keys, proposals = (sources["content"], sources["results"], sources["keys"],
                                         sources["proposals"])
    subject = {"jev_loop_result_handle": handle}

    def summary(statement: str, path: str, quantity: str, unit: str, value: Any, rounding: str,
                operation: str | None = None) -> dict[str, Any]:
        return _claim(statement, handle, path, None, subject, quantity, unit, value, rounding, operation)

    claims = [summary("pool_size", "pool.candidates", "pool_candidates", "count", len(content["pool"]["candidates"]),
                      "integer", "count(pool.candidates)"),
              summary("pool_source", "pool.source.handle", "candidate_set", "handle",
                      content["pool"]["source"]["handle"], "identifier")]
    for key in ("loop_seed", "iteration_cap", "effective_cap"):
        claims.append(summary("loop_setting", key, key, "seed" if key == "loop_seed" else "iterations", content[key],
                              "integer"))
    claims.append(summary("loop_setting", "setup_sha256", "setup_sha256", "sha256", content["setup_sha256"],
                          "identifier"))
    parameters = content["setup"]["parameters"]
    for key in SETUP_PARAMETERS:
        if parameters.get(key) is not None:
            claims.append(summary("setup_value", f"setup.parameters.{key}", key,
                                  "kcal/mol" if key == "energy_range" else "seed" if key == "seed" else "count",
                                  parameters[key], "input_decimal" if key == "energy_range" else "integer"))
    if content["branch"] == "protein":
        claims.append(summary("setup_value", "setup.contact_cutoff_A", "contact_cutoff_A", "A",
                              content["setup"]["contact_cutoff_A"], "input_decimal"))
    for key in JL.COUNT_KEYS:
        claims.append(summary("count", f"counts.{key}", key, "count", content["counts"][key], "integer"))
    for index, row in enumerate(content["candidates"]):
        if row["state"] != "scored":
            continue
        stored = _scored_result(content, row, results, keys)
        selector = {"candidate": index}
        who = {**subject, **selector, "candidate_ref": row["ref"]}
        claims.append(_claim("candidate_score", handle, f"candidates[{index}].score_kcal_mol", selector, who,
                             "score_kcal_mol", "kcal/mol", row["score_kcal_mol"], "score_1dp"))
        claims.append(_claim("candidate_result_score", stored["result_handle"], "modes[0].score_kcal_mol", selector,
                             {**who, "docking_result_handle": stored["result_handle"]}, "score_kcal_mol", "kcal/mol",
                             stored["score_kcal_mol"], "score_1dp"))
    for item in chosen:
        proposal = item["proposal_handle"]
        answer, arrival = proposals[proposal]["answer"], proposals[proposal]["arrival"]
        selector = {"iteration": item["iteration"]}
        who = {"proposal_handle": proposal, **selector}
        claims.append(_claim("list_position", proposal, "answer.list_position", selector, who, "list_position",
                             "position", answer["list_position"], "integer"))
        claims.append(_claim("list_size", proposal, "answer.list_size", selector, who, "list_size", "count",
                             answer["list_size"], "integer"))
        if answer["confidence"] is not None:
            claims.append(_claim("confidence", proposal, "answer.confidence", selector, who,
                                 "model_reported_confidence", "0-1", answer["confidence"], "exact_number"))
        claims.append(_claim("arrival_late", proposal, "arrival.late", selector, who, "late", "flag",
                             arrival["late"], "late_flag"))
    return claims


def _key(claim: dict[str, Any]) -> tuple[str, str, str, bytes]:
    return claim["statement_id"], claim["source_handle"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, its field rule, its source and every value equal the claim rebuilt from it."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("jev_loop_claim_shape")
    statement = proposed["statement_id"]
    if statement in origin_reports.STATEMENT_IDS:   # M29 @2: the record counts of a repaired structure
        return origin_reports.match_claim(expected_claims, proposed, "jev_loop")
    if type(statement) is not str or statement not in STATEMENTS:
        raise EvidenceError("jev_loop_claim_statement_not_allowed")
    kind, rule, source = STATEMENTS[statement]
    evidence, path = proposed["evidence_kind"], proposed["field_path"]
    if evidence not in EVIDENCE_KINDS or evidence != kind:
        raise EvidenceError("jev_loop_claim_evidence_kind_mismatch")
    if type(path) is not str:
        raise EvidenceError("jev_loop_claim_field_rule")
    if evidence == "computed" and MODEL_RESPONSE_FIELDS.fullmatch(path):
        raise EvidenceError("jev_loop_claim_model_response_field_as_computed")
    if evidence == "model_response" and COMPUTED_FIELDS.fullmatch(path):
        raise EvidenceError("jev_loop_claim_computed_field_as_model_response")
    if not rule.fullmatch(path):
        raise EvidenceError("jev_loop_claim_field_rule")
    reference = proposed["reference"]
    if evidence == "computed" and reference is not None:
        raise EvidenceError("jev_loop_claim_computed_with_model_note")
    if evidence == "model_response" and (type(reference) is not dict or reference.get("note") != MODEL_RESPONSE_NOTE
                                         or reference.get("proposal_handle") != proposed["source_handle"]):
        raise EvidenceError("jev_loop_claim_model_response_note")
    handles = {claim["source_handle"] for claim in expected_claims if claim["statement_id"] == statement}
    if ((proposed["source_kind"], proposed["source_schema"]) != source or proposed["source_handle"] not in handles or
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]):
        raise EvidenceError("jev_loop_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("jev_loop_claim_shape") from exc
    if match is None:
        raise EvidenceError("jev_loop_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("jev_loop_claim_binding_mismatch")
    return proposed


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _origin(run: Any, content: dict[str, Any]) -> dict[str, Any] | None:
    """M29: the validated structure origin of a protein loop's pool candidate set (None for a ligand loop and for a
    set whose structure is not a repaired structure)."""
    if content["branch"] != "protein":
        return None
    return origin_reports.origin(run, run.store.load(content["pool"]["source"]["handle"])["structure"]["handle"])


def _expected(run: Any, handle: str, version: str | None = None) -> dict[str, Any]:
    """Every manifest field that follows from the validated summary (not snapshot / markdown handle).

    ``version`` is the render version of a stored report; None picks it for a new report: @2 for a protein loop whose
    pool's candidate set is on a repaired structure, else @1."""
    sources = _sources(run, handle)
    content = sources["content"]
    try:
        chosen = _chosen(content, sources["proposals"])
        origin = _origin(run, content)
        if version is None:
            version = RENDER_VERSION if origin is None else RENDER_VERSION_V2
        if version not in MANIFEST_KEYS_BY_VERSION:
            raise EvidenceError("jev_loop_report_schema_invalid")
        if (version == RENDER_VERSION_V2) is (origin is None):
            raise EvidenceError("jev_loop_report_structure_origin_mismatch")   # @2 is a repaired structure's only
        expected = {
                "schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": version, "generation_mode": GENERATION_MODE, "result_handle": handle,
                "result_schema": L.RESULT_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                "external_response": dict(EXTERNAL_RESPONSE),
                **{key: copy.deepcopy(content[key]) for key in COPIED_FIELDS},
                "score_label": DC.SCORE_LABEL, "score_column_label": DC.SCORE_COLUMN_LABEL, "chosen": chosen,
                "claims": claims_for(handle, sources, chosen) + ([] if origin is None else
                                                                 origin_reports.claims(origin)),
                "provenance": sources["provenance"],
                "evidence_statement": EVIDENCE_STATEMENT, "limitation_ids": list(content["limitations"]),
                "limitations": [L.STATEMENTS[name] for name in content["limitations"]]}
        if origin is not None:
            expected["structure_origin"] = origin_reports.manifest_field(origin)
        return expected
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("jev_loop_report_evidence_unresolved") from exc


_SLOT = re.compile("\x00(\\d+)\x00")


def render_jev_loop_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every claimed value is the rendered text of a bound claim.

    Identifiers and values (handles, refs, SMILES, residue fields, names, numbers) go into slots; the forbidden-word
    check runs on the fixed template text with the slots left empty, then the slots are filled.
    """
    claims = manifest["claims"]
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def found(statement: str, path: str | None = None, **selector: Any) -> list[dict[str, Any]]:
        return [c for c in claims if c["statement_id"] == statement and (path is None or c["field_path"] == path)
                and all((c["row_selector"] or {}).get(key) == value for key, value in selector.items())]

    def value(statement: str, path: str | None = None, missing: str | None = None, **selector: Any) -> str:
        rows = found(statement, path, **selector)
        if not rows and missing is not None:
            return missing
        if len(rows) != 1:
            raise EvidenceError("jev_loop_report_claim_missing")
        return md(rows[0]["rendered_value"])

    def display(item: dict[str, Any]) -> str:
        if manifest["branch"] == "ligand":
            return f"SMILES {md(item['smiles'])}"
        return f"{md(_ref(item['residue']))}, {md(item['from'])} → {md(item['to'])}"

    def count(name: str) -> str:
        return value("count", f"counts.{name}")

    lines = ["# JEV 루프 보고서 (jev_loop)", "", "Status: complete", "",
             f"Loop summary: {md(manifest['result_handle'])}",
             f"Loop: {md(manifest['loop_id'])}, branch {md(manifest['branch'])}, goal {md(manifest['goal'])}",
             f"End reason: {md(manifest['end_reason'])}", "",
             f"**{_md(manifest['evidence_statement'])}**", "",
             "## 계산값 (ProtView 값: 저장된 루프 요약과 후보별 도킹 결과 객체)", "",
             f"- 후보 집합: {value('pool_source')}; 풀 후보 수: {value('pool_size')}",
             (f"- 루프 seed: {value('loop_setting', 'loop_seed')}; 반복 상한: {value('loop_setting', 'iteration_cap')}"
              f"; 유효 상한: {value('loop_setting', 'effective_cap')}"),
             f"- 설정 SHA-256: {value('loop_setting', 'setup_sha256')}",
             f"- 설정 (정규 JSON, 식별 데이터): {md(canonical_json(manifest['setup']).decode('utf-8'))}"]
    for key in SETUP_PARAMETERS:
        if found("setup_value", f"setup.parameters.{key}"):
            unit = " kcal/mol" if key == "energy_range" else ""
            lines.append(f"- 도킹 값 {md(key)}: {value('setup_value', f'setup.parameters.{key}')}{unit}")
    if manifest["branch"] == "protein":
        lines.append(f"- 접촉 cutoff: {value('setup_value', 'setup.contact_cutoff_A')} Å")
    lines.extend([f"- 시작한 바퀴: {count('started')}; 끝난 바퀴: {count('done')}",
                  f"- JEV 판정으로 정한 바퀴: {count('jev_decided')}; 사람이 지정한 바퀴: {count('human_decided')}",
                  f"- 보낸 전송 (dispatch): {count('sends_dispatched')}",
                  f"- 과금된 비싼 계산 단위: {count('units_charged')}",
                  f"- 저장된 같은 조건 결과를 가져온 후보: {count('reused_count')}",
                  f"- {manifest['score_label']}: 후보마다 그 후보 도킹 결과 객체의 {SCORE_ROW_LABEL}",
                  "", "### 후보 (풀 순서, 표시 순서일 뿐)", "",
                  f"| 후보 | 표기 | 상태 | 평가 | 바퀴 | {manifest['score_column_label']} | 도킹 결과 객체 |",
                  "| --- | --- | --- | --- | ---: | ---: | --- |"])
    for index, row in enumerate(manifest["candidates"]):
        cells = [md(row["ref"]), display(row["display"]), md(row["state"]),
                 "" if row["evaluation"] is None else md(row["evaluation"]),
                 "" if row["iteration"] is None else md(row["iteration"]), "", ""]   # no score: an empty cell
        if row["state"] == "scored":
            score = found("candidate_score", f"candidates[{index}].score_kcal_mol", candidate=index)
            result = found("candidate_result_score", "modes[0].score_kcal_mol", candidate=index)
            if len(score) != 1 or len(result) != 1 or score[0]["rendered_value"] != result[0]["rendered_value"]:
                raise EvidenceError("jev_loop_report_score_trace_mismatch")
            cells[5], cells[6] = md(score[0]["rendered_value"]), md(result[0]["source_handle"])
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "### 바퀴", ""])
    if manifest["iterations"]:
        lines.extend(["| 바퀴 | 결정 주체 | 후보 | 상태 | 단계 |", "| ---: | --- | --- | --- | --- |"])
    else:
        lines.append("- 승인된 바퀴가 없다.")
    for row in manifest["iterations"]:
        steps = "; ".join(f"{md(step['step'])} {md(step['state'])}" +
                          ("" if step["reason_code"] is None else f" ({md(step['reason_code'])})")
                          for step in row["steps"])
        lines.append(f"| {md(row['index'])} | {md(row['decided_by'])} | {md(row['candidate_ref'])} | "
                     f"{md(row['state'])} | {steps} |")
    lines.append("")
    if manifest["unfinished"]:
        for item in manifest["unfinished"]:
            lines.append(f"- 시작하지 못한 바퀴 {md(item['iteration'])}: 후보 {md(item['candidate_ref'])}")
    else:
        lines.append("- 시작하지 못한 바퀴: 없음")
    lines.extend(["", f"## {L.CHOICE_LABEL}: {MODEL_RESPONSE_NOTE}", "",
                  "- JEV 판정으로 정한 바퀴만 적는다. 사람이 지정한 바퀴에는 모델 응답이 없다.",
                  "- 고른 이유: 알 수 없음 (응답에 이유가 없다)",
                  "- 후보별 확률은 저장된 제안 객체에만 있고 이 보고서에는 넣지 않는다."])
    if not manifest["chosen"]:
        lines.append("- 이 루프에는 JEV 판정으로 정한 바퀴가 없다.")
    for item in manifest["chosen"]:
        number = item["iteration"]
        lines.extend(["", f"### 바퀴 {md(number)}", "",
                      f"- 제안 객체: {md(item['proposal_handle'])}",
                      f"- 고른 후보의 로컬 표기 (식별 데이터, 주장 아님): {display(item['local_display'])}",
                      (f"- 목록 위치: {value('list_position', iteration=number)}/"
                       f"{value('list_size', iteration=number)}"),
                      ("- 모델 보고 확신도 (0–1, 과학 값 아님): "
                       f"{value('confidence', iteration=number, missing=NOT_REPORTED)}"),
                      f"- 늦은 응답: {value('arrival_late', iteration=number)}"])
    if manifest["render_version"] == RENDER_VERSION_V2:   # M29 T8: the structure origin section
        lines.extend(origin_reports.section_lines(manifest["structure_origin"], claims, md))
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([(f"Exact values, evidence kinds and field paths are in the JSON download ({len(claims)} claims). "
                   "The candidate table follows the pool order, a display order only."), ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


def build_jev_loop_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object from the stored loop summary (nothing is computed, projected, sent or chosen again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot()}
        markdown = render_jev_loop_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("jev_loop_report_too_large")
        produced_by = f"jev_loop_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by=produced_by, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=produced_by,
                               summary={"result_handle": result_handle, "analysis_type": ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_jev_loop_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored JEV loop report from stored objects and events only (nothing is computed or sent)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("jev_loop_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    version = report.get("render_version") if type(report) is dict else None
    keys = MANIFEST_KEYS_BY_VERSION.get(version) if type(version) is str else None   # @1 and @2 are read
    if (keys is None or set(report) != keys or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str):
        raise EvidenceError("jev_loop_report_schema_invalid")
    expected = _expected(run, report["result_handle"], version)
    if type(report["claims"]) is not list:
        raise EvidenceError("jev_loop_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"jev_loop_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["ended_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("jev_loop_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("jev_loop_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("jev_loop_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("jev_loop_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_jev_loop_report(report):
        raise EvidenceError("jev_loop_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
