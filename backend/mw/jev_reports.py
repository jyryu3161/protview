"""Immutable, field-cited reports for one ``jev_choice@1`` proposal (``method_report_manifest@1``,
``analysis_type: "jev_choice"``, render ``jev_choice_markdown@1``; spec .dryforge/spec.md 8).

The input is one proposal handle. Making, reopening and downloading a report read stored objects and run events only:
no request is sent, nothing is projected or chosen again (``generation_mode: "local_rules_no_egress"``). The manifest
carries ``external_response: {kind: "jev_choice", scientific_evidence: false}``. Every claim cites the proposal
(``source_handle`` = the proposal) and is one of two evidence kinds that never mix:

- ``computed`` -- values ProtView holds for the send: the number of sent candidates (``selection[*]``), the body size
  (``projection.body_bytes``) and the reported input / output tokens and cost (``usage.*``, one claim per value the
  reply reported; a missing value is written "알 수 없음" and has no claim).
- ``model_response`` -- the external model's reply, a proposal and not scientific evidence (each claim carries that
  note and the proposal handle): the chosen alias (``answer.choice_alias``), the model-reported confidence
  (``answer.confidence``; "보고 없음" and no claim when absent), the served model (``served_model``) and the arrival
  (``arrival.late``, plus ``arrival.late_reason`` when late).

The chosen candidate's local notation (``answer.local_display``) is identification data in a fixed template slot, not
a claim. Per-candidate probabilities are never in the report (they stay in the stored proposal). A computed claim that
cites a model-response field, a model-response claim that cites a computed field, a probability field, a wrong count
or an edited value is ``report_evidence_invalid``.

The proposal is re-validated on every build and reopen (``jev_sends.load_choice``: its projection and candidate set
again) and bound to its send events (approval, dispatch, the one completed outcome naming it, the late flag derived
from event order up to that outcome). The renderer refuses interpretive wording on the fixed template text with every
identifier and value slot left empty, except the lines that are exactly a fixed sentence J1-J7 or one of the M26
J6 variants J6N / J6C.

M29 T8 (report format ``jev_choice_markdown@2``, spec .dryforge/spec.md 6.3, 6.4): the report of a mutation-kind
proposal whose candidate set's structure is a repaired structure (``structure_origin_reports.origin``, the record
re-validated with its publication) is @2, and only such a proposal's report is: the @1 manifest keys plus
``structure_origin``, the two computed record-count claims (citing the ``structure_repair@1`` record) after the @1
claims, and a "구조 출처" section (SO1, the handles, the two counts) before the limitations. Ligand-kind reports and
every other mutation-kind report are @1 with the @1 bytes; the proposal, its send and the sent body are unchanged.
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Any

from . import jev_constants as J
from . import jev_sends as S
from . import numbering_reports as nr
from . import structure_origin_reports as origin_reports
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _ref

ANALYSIS_TYPE = "jev_choice"
RENDER_VERSION = "jev_choice_markdown@1"
RENDER_VERSION_V2 = "jev_choice_markdown@2"   # M29 T8: a mutation-kind proposal on a repaired structure
GENERATION_MODE = "local_rules_no_egress"
REPORT_BYTES = nr.REPORT_BYTES
EXTERNAL_RESPONSE = {"kind": "jev_choice", "scientific_evidence": False}
MODEL_RESPONSE_NOTE = "외부 모델의 응답, 제안이며 과학 증거가 아니다"
NOT_KNOWN = "알 수 없음"
NOT_REPORTED = "보고 없음"
FIXED_LIMITATIONS = frozenset(J.STATEMENTS.values()) | frozenset(J.J6_BY_CATALYTIC_STATUS.values())  # + J6N, J6C
KIND_FOR_SOURCE_SCHEMA = {schema: kind for kind, schema in J.SOURCE_SCHEMAS.items()}
EVIDENCE_STATEMENT = ("ProtView counted the stored selection and copied the body size and the reported usage of this "
                      "send. The chosen alias, the model-reported confidence, the served model and the arrival are the "
                      "external model's reply kept as a proposal, not scientific evidence. Per-candidate "
                      "probabilities stay in the stored proposal. No request was sent to make this report.")

EVIDENCE_KINDS = ("computed", "model_response")
# statement ID -> (evidence kind, the one field path it cites, quantity, unit, rendering); fixed template.
STATEMENTS = {
    "selection_count": ("computed", "selection[*]", "sent_candidates", "count", "integer"),
    "body_bytes": ("computed", "projection.body_bytes", "body_bytes", "bytes", "integer"),
    "usage_input_tokens": ("computed", "usage.input_tokens", "input_tokens", "tokens", "integer"),
    "usage_output_tokens": ("computed", "usage.output_tokens", "output_tokens", "tokens", "integer"),
    "usage_cost": ("computed", "usage.cost", "cost", "usd", "exact_number"),
    "choice_alias": ("model_response", "answer.choice_alias", "chosen_alias", "identifier", "verbatim"),
    "confidence": ("model_response", "answer.confidence", "model_reported_confidence", "0-1", "exact_number"),
    "served_model": ("model_response", "served_model", "served_model", "identifier", "verbatim"),
    "arrival_late": ("model_response", "arrival.late", "late", "flag", "late_flag"),
    "arrival_late_reason": ("model_response", "arrival.late_reason", "late_reason", "reason", "late_reason"),
}
COMPUTED_FIELDS = frozenset(rule[1] for rule in STATEMENTS.values() if rule[0] == "computed")
MODEL_RESPONSE_FIELDS = frozenset(rule[1] for rule in STATEMENTS.values() if rule[0] == "model_response")
USAGE_STATEMENTS = (("usage_input_tokens", "input_tokens"), ("usage_output_tokens", "output_tokens"),
                    ("usage_cost", "cost"))
CLAIM_KEYS = nr.CLAIM_KEYS
LATE_FLAG = {False: "아니오 (false)", True: "예 (true)"}
LATE_REASON_KO = {"run_cancelled": "run 취소 뒤 도착", "consent_off": "과학 전송 동의 끈 뒤 도착"}
# M15 interpretive wording plus the spec 8 list. Handles are lowercase hex and every identifier / value sits in a slot,
# so none of these can come from data.
INTERPRETIVE = re.compile(
    nr.INTERPRETIVE.pattern + r"|순위|추천|최적|개선|예측|유망|좋은|나쁜|안전|점수|에너지|활성|친화도|안정성|ΔΔG|ddG|"
    r"delta\s*delta|\bwinner|\bbest\b|\brank|recommend|optimal|improv|predict|promising|\bgood\b|\bbad\b|\bsafe|"
    r"\bactiv(e|ity)\b|\bscor(e|ing)\b|energ", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "science_consent", "budget"}
COPIED_FIELDS = ("method_version", "label", "scientific_result", "send", "source", "projection", "question",
                 "requested_model", "served_model", "arrival", "limitations")
PROVENANCE_KEYS = ("send_id", "audit_id", "approved_event_seq", "dispatch_event_seq", "created_event_seq",
                   "outcome_event_seq")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "external_response", "kind", *COPIED_FIELDS, "chosen", "claims", "provenance",
    "evidence_statement", "snapshot", "markdown_handle"})
MANIFEST_KEYS_BY_VERSION = {RENDER_VERSION: MANIFEST_KEYS, RENDER_VERSION_V2: MANIFEST_KEYS | {"structure_origin"}}


# ---------------------------------------------------------------------------------------------------------------
# rendering

def _render(value: Any, rounding: str) -> str:
    if rounding == "integer" and type(value) is int:
        return str(value)
    if rounding == "exact_number" and (type(value) is int or (type(value) is float and math.isfinite(value))):
        return str(value)   # the stored value as written (no rounding)
    if rounding == "verbatim" and type(value) is str:
        return value
    if rounding == "late_flag" and type(value) is bool:
        return LATE_FLAG[value]
    if rounding == "late_reason" and value in LATE_REASON_KO:
        return f"{LATE_REASON_KO[value]} ({value})"
    raise EvidenceError("jev_claim_value_type")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the fixed sentences J1-J7, J6N, J6C or the
    M29 structure origin sentence (SO1)."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS or line in origin_reports.FIXED_LINES:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"jev_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects and events only)

def _one(events: list[dict[str, Any]], kind: str, **fields: Any) -> dict[str, Any] | None:
    return next((event for event in events if event.get("type") == kind and
                 all(event.get(key) == value for key, value in fields.items())), None)


def _send_chain(events: list[dict[str, Any]], handle: str, content: dict[str, Any]) -> dict[str, Any]:
    """The send events that produced this proposal: approval -> dispatch -> object -> the one completed outcome."""
    send_id, audit_id = content["send"]["send_id"], content["send"]["audit_id"]
    outcomes = [event for event in events if event.get("type") == J.EVENT_OUTCOME and
                event.get("choice_handle") == handle]
    if len(outcomes) != 1:
        raise EvidenceError("jev_choice_outcome_missing")
    outcome = outcomes[0]
    approved = _one(events, J.EVENT_APPROVED, send_id=send_id)
    dispatch = _one(events, J.EVENT_DISPATCH, send_id=send_id)
    created = _one(events, "object_created", handle=handle)
    if approved is None or dispatch is None or created is None:
        raise EvidenceError("jev_choice_send_events_missing")
    usage = outcome["usage"]
    if (outcome["send_id"] != send_id or outcome["status"] != "completed" or outcome["reason_code"] is not None or
            outcome["audit_id"] != audit_id or dispatch["audit_id"] != audit_id or
            outcome["requested_model"] != content["requested_model"] or
            outcome["served_model"] != content["served_model"] or
            canonical_json(None if usage is None else {key: usage[key] for key in S.USAGE_KEYS}) !=
            canonical_json(content["usage"]) or
            [outcome["late"], outcome["late_reason"]] != [content["arrival"]["late"],
                                                          content["arrival"]["late_reason"]] or
            approved["projection_handle"] != content["projection"]["handle"] or
            approved["body_sha256"] != content["projection"]["body_sha256"] or
            approved["question_id"] != content["question"]["id"] or
            approved["source_handle"] != content["source"]["handle"] or
            approved["selection_count"] != len(content["selection"]) or
            approved["approved_by"] != J.APPROVED_BY):
        raise EvidenceError("jev_choice_send_events_mismatch")
    if not approved["seq"] < dispatch["seq"] < created["seq"] < outcome["seq"]:
        raise EvidenceError("jev_choice_send_events_order")
    before = [event for event in events if event["seq"] < outcome["seq"]]
    if list(S.late_arrival(before, send_id)) != [content["arrival"]["late"], content["arrival"]["late_reason"]]:
        raise EvidenceError("jev_choice_arrival_mismatch")
    return {"send_id": send_id, "audit_id": audit_id, "approved_event_seq": approved["seq"],
            "dispatch_event_seq": dispatch["seq"], "created_event_seq": created["seq"],
            "outcome_event_seq": outcome["seq"]}


def validated_jev_choice(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(proposal content re-validated against its projection and candidate set, its send provenance)."""
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (J.CHOICE_KIND, J.CHOICE_SCHEMA):
            raise EvidenceError("wrong_result_kind")
        try:
            content = S.load_choice(run, handle)
        except (S.ChoiceInvalid, S.JevSendError) as exc:
            raise EvidenceError("jev_choice_invalid") from exc
        return content, _send_chain(list(run.events.read()), handle, content)
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("jev_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, subject: dict[str, Any], value: Any) -> dict[str, Any]:
    kind, path, quantity, unit, rounding = STATEMENTS[statement_id]
    return {"statement_id": statement_id, "evidence_kind": kind, "source_handle": handle,
            "source_kind": J.CHOICE_KIND, "source_schema": J.CHOICE_SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": None, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": "count(selection[*])" if statement_id == "selection_count" else None,
            "reference": ({"note": MODEL_RESPONSE_NOTE, "proposal_handle": handle} if kind == "model_response"
                          else None)}


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report, in template order; usage values and confidence only when present."""
    subject = {"proposal_handle": handle, "send_id": content["send"]["send_id"]}
    claims = [_claim("selection_count", handle, subject, len(content["selection"])),
              _claim("body_bytes", handle, subject, content["projection"]["body_bytes"])]
    usage = content["usage"] or {}
    claims.extend(_claim(statement, handle, subject, usage[key]) for statement, key in USAGE_STATEMENTS
                  if usage.get(key) is not None)
    answer, arrival = content["answer"], content["arrival"]
    claims.append(_claim("choice_alias", handle, subject, answer["choice_alias"]))
    if answer["confidence"] is not None:
        claims.append(_claim("confidence", handle, subject, answer["confidence"]))
    claims.append(_claim("served_model", handle, subject, content["served_model"]))
    claims.append(_claim("arrival_late", handle, subject, arrival["late"]))
    if arrival["late"]:
        claims.append(_claim("arrival_late_reason", handle, subject, arrival["late_reason"]))
    return claims


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, its one field, its source and every value equal the claim built from it."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("jev_claim_shape")
    statement = proposed["statement_id"]
    if statement in origin_reports.STATEMENT_IDS:   # M29 @2: the record counts of a repaired structure
        return origin_reports.match_claim(expected_claims, proposed, "jev")
    if type(statement) is not str or statement not in STATEMENTS:
        raise EvidenceError("jev_claim_statement_not_allowed")
    kind, path = STATEMENTS[statement][:2]
    evidence, field = proposed["evidence_kind"], proposed["field_path"]
    if evidence not in EVIDENCE_KINDS or evidence != kind:
        raise EvidenceError("jev_claim_evidence_kind_mismatch")
    if evidence == "computed" and field in MODEL_RESPONSE_FIELDS:
        raise EvidenceError("jev_claim_model_response_field_as_computed")
    if evidence == "model_response" and field in COMPUTED_FIELDS:
        raise EvidenceError("jev_claim_computed_field_as_model_response")
    if field != path:
        raise EvidenceError("jev_claim_field_rule")
    reference = proposed["reference"]
    if evidence == "computed" and reference is not None:
        raise EvidenceError("jev_claim_computed_with_model_note")
    if evidence == "model_response" and (type(reference) is not dict or reference.get("note") != MODEL_RESPONSE_NOTE
                                         or reference.get("proposal_handle") != proposed["source_handle"]):
        raise EvidenceError("jev_claim_model_response_note")
    handles = {claim["source_handle"] for claim in expected_claims}
    if ((proposed["source_kind"], proposed["source_schema"]) != (J.CHOICE_KIND, J.CHOICE_SCHEMA) or
            proposed["source_handle"] not in handles or
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]):
        raise EvidenceError("jev_claim_source_mismatch")
    match = next((claim for claim in expected_claims if claim["statement_id"] == statement), None)
    if match is None:
        raise EvidenceError("jev_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("jev_claim_binding_mismatch")
    return proposed


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _origin(run: Any, content: dict[str, Any]) -> dict[str, Any] | None:
    """M29: the validated structure origin of a mutation-kind proposal's candidate set (None for the ligand kind and
    for a set whose structure is not a repaired structure)."""
    if KIND_FOR_SOURCE_SCHEMA[content["source"]["schema"]] != "mutation":
        return None
    return origin_reports.origin(run, run.store.load(content["source"]["handle"])["structure"]["handle"])


def _expected(run: Any, handle: str, version: str | None = None) -> dict[str, Any]:
    """Every manifest field that follows from the validated proposal (not snapshot / markdown handle).

    ``version`` is the render version of a stored report; None picks it for a new report: @2 for a mutation-kind
    proposal whose candidate set's structure is a repaired structure, else @1."""
    content, provenance = validated_jev_choice(run, handle)
    try:
        origin = _origin(run, content)
        if version is None:
            version = RENDER_VERSION if origin is None else RENDER_VERSION_V2
        if version not in MANIFEST_KEYS_BY_VERSION:
            raise EvidenceError("jev_report_schema_invalid")
        if (version == RENDER_VERSION_V2) is (origin is None):
            raise EvidenceError("jev_report_structure_origin_mismatch")   # @2 is a repaired structure's only
        expected = {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                    "render_version": version, "generation_mode": GENERATION_MODE, "result_handle": handle,
                    "result_schema": J.CHOICE_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                    "external_response": dict(EXTERNAL_RESPONSE),
                    "kind": KIND_FOR_SOURCE_SCHEMA[content["source"]["schema"]],
                    **{key: content[key] for key in COPIED_FIELDS},
                    "chosen": {key: content["answer"][key] for key in ("local_ref", "local_display")},
                    "claims": claims_for(handle, content) + ([] if origin is None else origin_reports.claims(origin)),
                    "provenance": {key: provenance[key] for key in PROVENANCE_KEYS},
                    "evidence_statement": EVIDENCE_STATEMENT}
        if origin is not None:
            expected["structure_origin"] = origin_reports.manifest_field(origin)
        return expected
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("jev_report_evidence_unresolved") from exc


_SLOT = re.compile("\x00(\\d+)\x00")


def render_jev_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim.

    Identifiers and values (handles, aliases, SMILES, residue fields, numbers) go into slots; the forbidden-word check
    runs on the fixed template text with the slots left empty, then the slots are filled.
    """
    claims = manifest["claims"]
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def value(statement: str, missing: str | None = None) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement]
        if not found and missing is not None:
            return missing
        if len(found) != 1:
            raise EvidenceError("jev_report_claim_missing")
        return md(found[0])

    send, source, projection, question = (manifest["send"], manifest["source"], manifest["projection"],
                                          manifest["question"])
    display = manifest["chosen"]["local_display"]
    chosen = (f"SMILES {md(display['smiles'])}" if manifest["kind"] == "ligand" else
              f"{md(_ref(display['residue']))}, {md(display['from'])} → {md(display['to'])}")
    late = value("arrival_late")
    if manifest["arrival"]["late"]:
        late = f"{late}, {value('arrival_late_reason')}"
    lines = ["# JEV 판정 보고서 (jev_choice)", "", "Status: complete", "",
             f"Proposal: {md(manifest['result_handle'])}",
             f"Projection: {md(projection['handle'])}",
             f"Source: {md(source['handle'])} ({md(source['schema'])})",
             f"Question: {md(question['id'])}",
             f"Send: {md(send['send_id'])}, audit {md(send['audit_id'])}", "",
             f"**{_md(manifest['evidence_statement'])}**", "",
             "## 보낸 내용 (ProtView 값: 저장된 제안 객체)", "",
             f"- 보낸 후보 수: {value('selection_count')}",
             f"- 본문 바이트: {value('body_bytes')} bytes",
             f"- 본문 SHA-256: {md(projection['body_sha256'])}",
             f"- 입력 토큰: {value('usage_input_tokens', NOT_KNOWN)}",
             f"- 출력 토큰: {value('usage_output_tokens', NOT_KNOWN)}",
             f"- 비용 (USD): {value('usage_cost', NOT_KNOWN)}", "",
             f"## {_md(manifest['label'])}: {MODEL_RESPONSE_NOTE}", "",
             f"- 고른 별칭: {value('choice_alias')}",
             f"- 고른 후보의 로컬 표기 (식별 데이터, 주장 아님): {chosen}",
             f"- 모델 보고 확신도 (0–1, 과학 값 아님): {value('confidence', NOT_REPORTED)}",
             f"- 응답 모델: {value('served_model')}",
             f"- 늦은 응답: {late}",
             "- 고른 이유: 알 수 없음 (응답에 이유가 없다)",
             "- 후보별 확률은 저장된 제안 객체에만 있고 이 보고서에는 넣지 않는다."]
    if manifest["render_version"] == RENDER_VERSION_V2:   # M29 T8: the structure origin section
        lines.extend(origin_reports.section_lines(manifest["structure_origin"], claims, md))
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([f"Exact values, evidence kinds and field paths are in the JSON download ({len(claims)} claims).",
                  ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


def build_jev_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object from the stored proposal (nothing is sent, projected or chosen again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"],
                                "science_consent": S.consent_enabled(events), "budget": run.budget_snapshot()}
        markdown = render_jev_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("jev_report_too_large")
        produced_by = f"jev_report_{uuid.uuid4().hex}"
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


def saved_jev_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored JEV choice report from stored objects and events only (nothing is sent)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("jev_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    version = report.get("render_version") if type(report) is dict else None
    keys = MANIFEST_KEYS_BY_VERSION.get(version) if type(version) is str else None   # @1 and @2 are read
    if (keys is None or set(report) != keys or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str):
        raise EvidenceError("jev_report_schema_invalid")
    expected = _expected(run, report["result_handle"], version)
    if type(report["claims"]) is not list:
        raise EvidenceError("jev_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"jev_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["outcome_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["science_consent"]) is not bool or type(snapshot["budget"]) is not dict):
        raise EvidenceError("jev_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if (at is None or at["ts"] != snapshot["time_utc"] or snapshot["science_consent"] is not
            S.consent_enabled([event for event in events if event["seq"] <= snapshot["event_seq"]])):
        raise EvidenceError("jev_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("jev_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("jev_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_jev_report(report):
        raise EvidenceError("jev_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
