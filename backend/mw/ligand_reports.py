"""Immutable, field-cited reports for ``ligand_candidate_set@1`` (``method_report_manifest@1``,
``analysis_type: "ligand_candidates"``, render ``ligand_candidates_markdown@1``; spec M17 section 9).

The input is one candidate set handle and an optional filter spec (normalized with ``normalize_filter_spec``; the
normalized spec is stored in the manifest). Every value statement is ``computed`` evidence bound to the candidate set
handle and a field path:

- stored fields: the 8 parent properties (RDKit estimates; ``mol_weight`` Da, ``tpsa`` Å², the others dimensionless
  or counts; floats rendered ``Decimal(str(v))`` to 0.01 with ``ROUND_HALF_UP``, integers exactly), the candidate
  count, accepted blocks, raw and duplicate products, counts per rejection reason and per used rule
  (``not_applicable``), the cap state (``limit_reached``, ``stop_reason``, ``limits``), the site atom serials and the
  user rule texts verbatim;
- ``count_where`` over the stored candidate rows, re-counted at every validation: per active filter the rows passing
  it (the condition is recorded in the claim's ``row_selector``), the rows passing all active filters, the rows with
  any PAINS match, and the rows per ``stereo_flag``. Candidate rows are never cited one by one (the full table is the
  ligand tab). A set without candidates has no row statistics; no filter statement exists without an active filter.

Creating, reopening and downloading never re-run enumeration: the stored set is re-validated with
``ligand_bundle.validated_candidate_set`` (completed job publication, inputs, closed sets), every manifest field and
claim is compared with the one rebuilt from the stored set, and the Markdown is compared byte for byte with a
re-render. The template states no judgement; every line except the five fixed limitation sentences (matched exactly)
is checked for interpretive wording.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import ligand_bundle as lb
from . import numbering_reports as nr
from . import site_annotation_reports as sr
from .core.errors import ToolFailure
from .core.handles import canonical_json
from .ligand_constants import LIMITATIONS as FIXED_LIMITATIONS
from .ligand_constants import PAINS_FILTER, PRODUCT_REJECT_REASONS, PROPERTY_NAMES, STEREO_FLAGS
from .ligand_filters import evaluate_row, normalize_filter_spec
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md

ANALYSIS_TYPE = "ligand_candidates"
RENDER_VERSION = "ligand_candidates_markdown@1"
RESULT_KIND = "ligand_candidate_set"
RESULT_SCHEMA = "ligand_candidate_set@1"
REPORT_BYTES = nr.REPORT_BYTES
LIMITATIONS = list(FIXED_LIMITATIONS)
FLOAT_PROPERTIES = frozenset({"mol_weight", "crippen_logp", "tpsa"})
PROPERTY_UNITS = {"mol_weight": "Da", "crippen_logp": "dimensionless", "hbd": "count", "hba": "count",
                  "tpsa": "A2", "rotatable_bonds": "count", "heavy_atoms": "count", "formal_charge": "dimensionless"}
UNIT_TEXT = {"Da": "Da", "A2": "Å²", "dimensionless": "무차원", "count": "개수"}
REJECT_KO = {"sanitize_failed": "정리(sanitize) 실패", "element_not_allowed": "허용 밖 원소",
             "too_many_atoms": "중원자 수 상한 초과", "equals_parent": "부모와 같음", "outside_site": "부위 밖 매치"}
STEREO_KO = {"none": "표시 없음", "parent_stereo_lost": "부모 입체 미지정됨", "new_unspecified_center": "새 미지정 입체 중심"}
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 RDKit 작업 결과(후보 집합 객체)의 값과, 저장된 후보 행에 보고서 필터 "
                      "조건을 적용해 센 개수이다. 보고서는 후보를 다시 생성하지 않았다.")
NOT_A_JUDGEMENT = ("필터 통과·실패와 PAINS 구조 경고 일치는 저장값에 조건을 적용한 결과일 뿐이며 후보의 특성 판정이 "
                   "아니다.")

_PROPS = "|".join(PROPERTY_NAMES)
# statement ID -> its closed field-path rule (all ``computed``); a claim citing another statement's field is refused
# before any value comparison.
STATEMENTS = {
    "parent_property": re.compile(rf"parent_properties\.({_PROPS})"),
    "candidate_count": re.compile(r"counts\.candidates"),
    "generation_count": re.compile(r"counts\.(blocks_accepted|raw_products|duplicate_products)"),
    "rejected_count": re.compile(r"counts\.rejected\.(" + "|".join(PRODUCT_REJECT_REASONS) + ")"),
    "not_applicable_count": re.compile(r"counts\.not_applicable\.(fixed|user_[1-9][0-9]*)"),
    "limit_state": re.compile(r"limit_reached|stop_reason|limits\.(max_candidates|max_attempts)"),
    "site_atoms": re.compile(r"site_atoms"),
    "rule_text": re.compile(r"rules_used\[\d+\]\.text"),
    "pains_match_count": re.compile(r"candidates\[\*\]\.pains\.matches"),
    "stereo_flag_count": re.compile(r"candidates\[\*\]\.stereo_flag"),
    "filter_pass_count": re.compile(rf"candidates\[\*\]\.(properties\.({_PROPS})|pains\.matches)"),
    "filter_all_pass_count": re.compile(r"candidates\[\*\]"),
}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = frozenset({"statement_id", "evidence_kind", "source_handle", "source_kind", "source_schema",
                        "source_sha256", "field_path", "row_selector", "subject", "quantity", "unit", "exact_value",
                        "rendered_value", "rounding", "operation"})
# M15/M16 interpretive wording plus the M17 list (spec 9); "bad" is left out on purpose (hex handles contain it).
INTERPRETIVE = re.compile(
    sr.INTERPRETIVE.pattern + r"|좋은|나쁜|약물\s*유사|독성|안전|활성|친화|억제|합성\s*가능|최적|중요|핵심|기능|"
    r"drug[\s_-]?like|toxic|\bsafe|synthesi[sz]abl|synthetic\s+accessib|optimal|\bbest\b|\bgood\b|\bactiv(e|ity)\b",
    re.IGNORECASE)
CAPABILITY_KEYS = ("available", "status", "reason_code", "pins", "pains_catalog_entries")
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "capability", "budget"}
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "inspection_handle", "parent_handle", "block_handles", "method", "parent_canonical_smiles",
    "parent_properties", "property_methods", "site_atoms", "retained_parent_atoms", "crossing_bond", "use_fixed",
    "rules_used", "counts", "limits", "limit_reached", "stop_reason", "null_result", "filter_spec", "claims",
    "provenance", "evidence_statement", "limitations", "snapshot", "markdown_handle"})
COPIED_FIELDS = ("inspection_handle", "parent_handle", "block_handles", "method", "parent_canonical_smiles",
                 "parent_properties", "property_methods", "site_atoms", "retained_parent_atoms", "crossing_bond",
                 "use_fixed", "rules_used", "counts", "limits", "limit_reached", "stop_reason")


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_property(value: Any) -> str:
    """Two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68)."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("ligand_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


def _render(value: Any, rounding: str) -> str:
    if rounding == "property_2dp":
        return render_property(value)
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("ligand_claim_integer_expected")
        return str(value)
    if rounding == "flag":
        if type(value) is not bool:
            raise EvidenceError("ligand_claim_value_type")
        return "true" if value else "false"
    if rounding == "identifier":
        if value is not None and type(value) is not str:
            raise EvidenceError("ligand_claim_value_type")
        return "none (null)" if value is None else value
    if rounding == "serial_list":
        if type(value) is not list or any(type(item) is not int for item in value):
            raise EvidenceError("ligand_claim_value_type")
        return ", ".join(str(item) for item in value)
    if rounding == "verbatim_text":
        if type(value) is not str:
            raise EvidenceError("ligand_claim_value_type")
        return value
    raise EvidenceError("ligand_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the five fixed limitation sentences."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"ligand_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, quantity: str, unit: str,
           value: Any, rounding: str, operation: str | None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": "computed", "source_handle": handle,
            "source_kind": RESULT_KIND, "source_schema": RESULT_SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": {"candidate_set_handle": handle},
            "quantity": quantity, "unit": unit, "exact_value": value, "rendered_value": _render(value, rounding),
            "rounding": rounding, "operation": operation}


def _active_ranges(spec: dict[str, Any]) -> list[str]:
    """Range filter names in the fixed property order (stored JSON sorts keys; order must not depend on it)."""
    return [name for name in PROPERTY_NAMES if name in spec["ranges"]]


def _count_where(statement: str, handle: str, path: str, selector: dict[str, Any], quantity: str, value: int,
                 condition: str) -> dict[str, Any]:
    return _claim(statement, handle, path, selector, quantity, "count", value, "integer",
                  f"count_where({condition}; stored candidate rows)")


def claims_for(handle: str, content: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; ``count_where`` values are recounted from ``content['candidates']``."""
    try:
        claims = []
        for name in PROPERTY_NAMES:
            claims.append(_claim("parent_property", handle, f"parent_properties.{name}", None, name,
                                 PROPERTY_UNITS[name], content["parent_properties"][name],
                                 "property_2dp" if name in FLOAT_PROPERTIES else "integer", None))
        counts, rows = content["counts"], content["candidates"]
        claims.append(_claim("candidate_count", handle, "counts.candidates", None, "candidates", "count",
                             counts["candidates"], "integer", None))
        for key in ("blocks_accepted", "raw_products", "duplicate_products"):
            claims.append(_claim("generation_count", handle, f"counts.{key}", None, key, "count", counts[key],
                                 "integer", None))
        for reason in PRODUCT_REJECT_REASONS:
            claims.append(_claim("rejected_count", handle, f"counts.rejected.{reason}", {"reason": reason},
                                 f"rejected_{reason}", "count", counts["rejected"][reason], "integer", None))
        for rule in content["rules_used"]:
            rule_id = rule["rule_id"]
            claims.append(_claim("not_applicable_count", handle, f"counts.not_applicable.{rule_id}",
                                 {"rule_id": rule_id}, "not_applicable_blocks", "count",
                                 counts["not_applicable"][rule_id], "integer", None))
        claims.append(_claim("limit_state", handle, "limit_reached", None, "limit_reached", "flag",
                             content["limit_reached"], "flag", None))
        claims.append(_claim("limit_state", handle, "stop_reason", None, "stop_reason", "identifier",
                             content["stop_reason"], "identifier", None))
        for key in ("max_candidates", "max_attempts"):
            claims.append(_claim("limit_state", handle, f"limits.{key}", None, key, "count", content["limits"][key],
                                 "integer", None))
        claims.append(_claim("site_atoms", handle, "site_atoms", None, "site_atoms", "sdf_atom_serial",
                             content["site_atoms"], "serial_list", None))
        for index, rule in enumerate(content["rules_used"]):
            if rule["text"] is not None:
                claims.append(_claim("rule_text", handle, f"rules_used[{index}].text", {"rule_id": rule["rule_id"]},
                                     "reaction_smarts", "text", rule["text"], "verbatim_text", None))
        if not rows:
            return claims   # no candidate rows: counts only, no row statistics (and no filter statement)
        claims.append(_count_where("pains_match_count", handle, "candidates[*].pains.matches", {"pains_match": True},
                                   "pains_match_candidates", sum(1 for row in rows if row["pains"]["matches"]),
                                   "len(pains.matches) > 0"))
        for flag in STEREO_FLAGS:
            claims.append(_count_where("stereo_flag_count", handle, "candidates[*].stereo_flag",
                                       {"stereo_flag": flag}, f"stereo_flag_{flag}_candidates",
                                       sum(1 for row in rows if row["stereo_flag"] == flag),
                                       f"stereo_flag == {flag}"))
        evaluated = [evaluate_row(row, spec) for row in rows]
        for name in _active_ranges(spec):
            bounds = spec["ranges"][name]
            claims.append(_count_where("filter_pass_count", handle, f"candidates[*].properties.{name}",
                                       {"filter": name, "min": bounds["min"], "max": bounds["max"]},
                                       f"filter_{name}_pass_candidates",
                                       sum(1 for item in evaluated if item["filters"][name]),
                                       f"min <= properties.{name} <= max, inclusive, null bound = no bound"))
        if spec[PAINS_FILTER]:
            claims.append(_count_where("filter_pass_count", handle, "candidates[*].pains.matches",
                                       {"filter": PAINS_FILTER}, "filter_pains_exclude_pass_candidates",
                                       sum(1 for item in evaluated if item["filters"][PAINS_FILTER]),
                                       "len(pains.matches) == 0"))
        if spec["ranges"] or spec[PAINS_FILTER]:
            claims.append(_count_where("filter_all_pass_count", handle, "candidates[*]", {"filter_spec": spec},
                                       "filter_all_pass_candidates",
                                       sum(1 for item in evaluated if item["passes_all"] is True),
                                       "every active filter passes"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, ToolFailure) as exc:
        raise EvidenceError("ligand_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("ligand_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("ligand_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS:
        raise EvidenceError("ligand_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("ligand_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (RESULT_KIND, RESULT_SCHEMA):
        raise EvidenceError("ligand_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("ligand_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("ligand_claim_shape") from exc
    if match is None:
        raise EvidenceError("ligand_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("ligand_claim_binding_mismatch")
    return proposed


def validate_ligand_claim(run: Any, result_handle: str, filter_spec: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle, _normalized(filter_spec))["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _normalized(filters: Any) -> dict[str, Any]:
    """Normalized filter spec; ``None`` is no filter. Raises ``ToolFailure`` (input_invalid) on a bad request."""
    return normalize_filter_spec({} if filters is None else filters)


def _job(source: dict[str, Any]) -> dict[str, Any]:
    return {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
            "protocol_id": source["job"]["protocol_id"], "tool_id": source["job"]["tool_id"],
            "created_event_seq": source["created_seq"], "completed_event_seq": source["published_seq"]}


def _expected(run: Any, handle: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored set and the spec (not snapshot/markdown)."""
    try:
        content, _inspection = lb.validated_candidate_set(run, handle)
        source = lb.producer(run, handle, lb.ENUMERATE)
        inspected = lb.producer(run, content["inspection_handle"], lb.INSPECT)
    except lb.LigandEvidenceError as exc:
        raise EvidenceError(f"ligand_candidate_set_invalid: {exc}") from exc
    try:
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": RESULT_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS},
                "null_result": content["counts"]["candidates"] == 0, "filter_spec": spec,
                "claims": claims_for(handle, content, spec),
                "provenance": {"candidate_set": _job(source), "inspection": _job(inspected)},
                "evidence_statement": EVIDENCE_STATEMENT, "limitations": list(content["limitations"])}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("ligand_report_evidence_unresolved") from exc


def capability_snapshot() -> dict[str, Any]:
    """Capability status and pins at report creation (the cached handshake; nothing is generated)."""
    value = lb.capability()
    return {key: value[key] for key in CAPABILITY_KEYS}


def capability_snapshot_valid(value: Any) -> bool:
    if type(value) is not dict or set(value) != set(CAPABILITY_KEYS):
        return False
    ready = value["status"] == "ready"
    if not (ready or value["status"] in lb.REASONS) or value["available"] is not ready:
        return False
    if not ready:
        return value["reason_code"] == value["status"] and value["pins"] is None and \
            value["pains_catalog_entries"] is None
    try:
        lb._pins(value["pins"])
    except lb.LigandEvidenceError:
        return False
    return value["reason_code"] is None and value["pains_catalog_entries"] == lb.PAINS_CATALOG_ENTRIES


# ---------------------------------------------------------------------------------------------------------------
# Markdown

def _bound(value: Any) -> str:
    return "없음" if value is None else _md(json.dumps(value))


def render_ligand_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every number is the rendered text of a bound claim."""
    claims = manifest["claims"]

    def value(statement: str, path: str, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and c["field_path"] == path
                 and all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("ligand_report_claim_missing")
        return found[0]

    provenance = manifest["provenance"]
    method = manifest["method"]
    lines = ["# 리간드 부분 교체 후보 보고서 (ligand candidates)", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             f"Inspection: {_md(manifest['inspection_handle'])}",
             f"Parent import: {_md(manifest['parent_handle'])}",
             "Block imports: " + (", ".join(_md(h) for h in manifest["block_handles"]) or "없음"),
             (f"Enumeration job: {_md(provenance['candidate_set']['job_id'])}, attempt "
              f"{_md(provenance['candidate_set']['attempt_id'])}"),
             (f"Inspection job: {_md(provenance['inspection']['job_id'])}, attempt "
              f"{_md(provenance['inspection']['attempt_id'])}"),
             (f"Method: {_md(method['engine'])} {_md(method['rdkit_version'])} (worker "
              f"{_md(method['worker_sha256'])})"),
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             "## 부모 리간드 속성 (RDKit 추정값)", "",
             f"- Canonical SMILES: {_md(manifest['parent_canonical_smiles'])}", "",
             "| 속성 | 값 | 단위 | RDKit 방법 |", "| --- | ---: | --- | --- |"]
    for name in PROPERTY_NAMES:
        lines.append(f"| {_md(name)} | {value('parent_property', f'parent_properties.{name}')} | "
                     f"{UNIT_TEXT[PROPERTY_UNITS[name]]} | {_md(manifest['property_methods'][name])} |")
    crossing = manifest["crossing_bond"]
    lines.extend(["", "## 부위와 생성 규칙", "",
                  f"- 부위 원자 (SDF 번호): {value('site_atoms', 'site_atoms')}",
                  (f"- 부위와 코어를 잇는 단일 연결: 코어 원자 {_md(crossing['core_atom'])} – 부위 원자 "
                   f"{_md(crossing['site_atom'])} ({_md(crossing['order'])})"),
                  f"- 고정 교체 사용: {'예' if manifest['use_fixed'] else '아니오'}"])
    for index, rule in enumerate(manifest["rules_used"]):
        if rule["text"] is None:
            lines.append(f"- {_md(rule['rule_id'])} ({_md(rule['method'])})")
        else:
            lines.append(f"- {_md(rule['rule_id'])} ({_md(rule['method'])}): "
                         f"{_md(value('rule_text', f'rules_used[{index}].text'))}")
    lines.extend(["", "## 생성 개수 (저장값)", "",
                  f"- 수락된 block: {value('generation_count', 'counts.blocks_accepted')}",
                  f"- 원시 생성물: {value('generation_count', 'counts.raw_products')}",
                  f"- 후보 (고유 SMILES 행): {value('candidate_count', 'counts.candidates')}",
                  f"- 중복 생성물 (행 없음, origins에 합침): {value('generation_count', 'counts.duplicate_products')}"])
    for reason in PRODUCT_REJECT_REASONS:
        lines.append(f"- 거부 {REJECT_KO[reason]} ({_md(reason)}): "
                     f"{value('rejected_count', f'counts.rejected.{reason}')}")
    for rule in manifest["rules_used"]:
        rule_id = rule["rule_id"]
        lines.append(f"- 규칙에 쓸 수 없는 block {_md(rule_id)} (not\\_applicable): "
                     f"{value('not_applicable_count', f'counts.not_applicable.{rule_id}')}")
    lines.extend([(f"- 상한 도달: {value('limit_state', 'limit_reached')} (stop\\_reason "
                   f"{_md(value('limit_state', 'stop_reason'))}); 상한 후보 "
                   f"{value('limit_state', 'limits.max_candidates')}, 원시 생성물 시도 "
                   f"{value('limit_state', 'limits.max_attempts')}")])
    if manifest["null_result"]:
        lines.append("- " + _md("후보 0개: 유효한 빈 결과(scientific_null)이며 실패가 아니다."))
    lines.extend(["", "## 후보 행 개수 (저장된 후보 행에서 센 값)", ""])
    if manifest["null_result"]:
        lines.append("- 후보 0개: 후보 행 통계와 필터 적용 개수가 없다.")
    else:
        lines.append(f"- PAINS 구조 경고 일치가 하나 이상인 후보: "
                     f"{value('pains_match_count', 'candidates[*].pains.matches')}")
        for flag in STEREO_FLAGS:
            lines.append(f"- stereo\\_flag {STEREO_KO[flag]} ({_md(flag)}): "
                         f"{value('stereo_flag_count', 'candidates[*].stereo_flag', stereo_flag=flag)}")
    spec = manifest["filter_spec"]
    lines.extend(["", "## 필터 (보고서 시점에 저장값으로 적용)", ""])
    if not spec["ranges"] and not spec[PAINS_FILTER]:
        lines.append("- 적용한 필터 없음.")
    else:
        for name in _active_ranges(spec):
            bounds = spec["ranges"][name]
            unit = UNIT_TEXT[PROPERTY_UNITS[name]]
            lines.append(f"- {_md(name)} 최소 {_bound(bounds['min'])}, 최대 {_bound(bounds['max'])} ({unit}, 경계 포함)"
                         + ("" if manifest["null_result"] else
                            f": 통과 {value('filter_pass_count', f'candidates[*].properties.{name}', filter=name)}"))
        if spec[PAINS_FILTER]:
            lines.append("- PAINS 구조 경고 일치 제외 (pains\\_exclude)" + (
                "" if manifest["null_result"] else
                f": 통과 {value('filter_pass_count', 'candidates[*].pains.matches', filter=PAINS_FILTER)}"))
        if not manifest["null_result"]:
            lines.append(f"- 적용한 필터 모두 통과: {value('filter_all_pass_count', 'candidates[*]')}")
        lines.append(f"- {_md(NOT_A_JUDGEMENT)}")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units, field paths and filter conditions are in the JSON download "
                   f"({len(claims)} claims). The candidate rows are in the ligand tab table."), ""])
    return check_no_interpretation("\n".join(lines))


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_ligand_report(run: Any, result_handle: str, *, filters: Any = None) -> dict[str, Any]:
    """New report object for one stored candidate set; ``filters`` is the optional filter spec."""
    spec = _normalized(filters)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle, spec)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_ligand_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("ligand_report_too_large")
        produced_by = f"ligand_report_{uuid.uuid4().hex}"
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


def saved_ligand_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored ligand report without re-running inspection or enumeration."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("ligand_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("ligand_report_schema_invalid")
    try:
        spec = _normalized(report["filter_spec"])
    except ToolFailure as exc:
        raise EvidenceError("ligand_report_filter_spec_invalid") from exc
    if canonical_json(spec) != canonical_json(report["filter_spec"]):
        raise EvidenceError("ligand_report_filter_spec_not_normalized")
    expected = _expected(run, report["result_handle"], spec)
    if type(report["claims"]) is not list:
        raise EvidenceError("ligand_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"ligand_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["candidate_set"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not capability_snapshot_valid(snapshot["capability"]) or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("ligand_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("ligand_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("ligand_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("ligand_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_ligand_report(report):
        raise EvidenceError("ligand_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
