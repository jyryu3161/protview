"""Immutable, field-cited reports for one ``structure_repair@1`` record (``method_report_manifest@1``,
``analysis_type: "structure_repair"``, render ``structure_repair_markdown@1``; spec .dryforge/spec.md 7, 3.5-3.7).

The input is one repair record handle (``POST /runs/{id}/method_reports``). Every value statement is ``computed``
evidence bound to that handle and one field path of the record (there is no other evidence kind in this report):

- ``repair_scope``: the record's ``classes_applied`` (the repair classes in the spec 2.1 order), also re-derived here
  from the record rows (a class that was not applied can never be listed);
- ``added_residue_count`` (``counts.added_residues``), ``added_atom_count`` (``counts.added_atoms`` and the stored
  ``added_atoms`` rows counted by ``origin``), ``side_chain_residue_count``, ``terminal_oxt_count``, ``gap_count``
  (``counts.gaps`` and each ``gaps[i].length``), ``replaced_count``, ``chain_parts_merged_count``: each count equals
  the one recounted from the record's own rows (``EvidenceError`` otherwise);
- ``unchanged_atom_count``: the observed (input) atom count and the largest observed-atom shift (Å, the stored float
  verbatim; the server's check allows at most 1e-9 Å);
- ``collision_min_distance``: per partner class whose minimum exists, the stored value in Å rendered
  ``Decimal(str(v))`` to 0.01 with ``ROUND_HALF_UP``. A class without a partner has no claim; its line says "—" with
  the reason, and its stored counts are 0 (spec 3.6: never read as an absence of clashes);
- ``zero_occupancy_input_atom_count``: the input atoms with occupancy 0 and their residue count.

The collision table's ``count_lt_*`` values and ``min_pair`` identities, the residue identities of the tables and the
chain-end flags are the record's values copied into the manifest (compared with the record on every reopen), not
separate statements. The limitation sentences are the record's ``limitations`` (RP1-RP6 of spec 3.7, verbatim, in
order, checked against the conditions the record states).

Creating, reopening and downloading never repair again: the stored record is re-validated with
``structure_repair_bundle.validated_result`` (single completed ``pdbfixer_repair_v1`` publication, job selection, the
four objects, the record re-derived from the original prepared structure and the stored repaired bytes), every
manifest field and claim is compared with the one rebuilt from the record, and the Markdown is compared byte for byte
with a re-render. An unavailable environment (``ToolFailure`` of class ``precondition``, e.g. ``openmm_unavailable``
when the installed template cannot be read) is raised as it is (412 at the routes), never as invalid evidence. Any
other mismatch is ``EvidenceError`` (422 ``report_evidence_invalid``). Values and identifiers go into slots; the
interpretive-wording check (the M20 list, ``mutation_reports.INTERPRETIVE``) runs on every template line with the slots
empty, except a line exactly equal to one of the RP sentences.

Pure reads of the run's stored objects and events, plus the two report objects and the ``method_report_created``
event on creation (no engine, job, network or process module).
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import mutation_reports as m20
from . import numbering_reports as nr
from . import structure_repair_bundle as bundle
from . import structure_repair_constants as K
from .core.handles import canonical_json
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md, _ref

ANALYSIS_TYPE = K.REPORT_ANALYSIS_TYPE
RENDER_VERSION = K.REPORT_RENDER
REPORT_BYTES = nr.REPORT_BYTES
LIST_NAME = K.REPORT_LIST_NAME
FIXED_LIMITATIONS = frozenset(K.LIMITATION_ORDER)
INTERPRETIVE = m20.INTERPRETIVE
CLAIM_KEYS = nr.CLAIM_KEYS
EVIDENCE_KINDS = ("computed",)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget"}
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 보완 기록(structure_repair@1)의 필드 값과, 그 기록의 행을 다시 센 "
                      "개수다. 보고서를 만들거나 다시 열 때 보완을 다시 하지 않았고 PDBFixer를 실행하지 않았다. 충돌 "
                      "표의 개수와 최솟값 쌍은 보완 기록 collisions의 값을 그대로 옮겼다.")
# The record keys copied into the manifest (every key but ``schema`` and the ``added_atoms`` rows, which the repair
# record reads page through).
COPIED_FIELDS = ("method_version", "source", "result", "parameters", "method", "classes_applied", "chain_parts",
                 "chain_ends", "side_chain_repairs", "terminal_oxt", "gaps", "replaced", "counts", "unchanged",
                 "new_atom_rounding", "zero_occupancy_input_atoms", "collisions", "limitations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "repaired_structure", "source_structure", "claims", "provenance",
    "evidence_statement", "snapshot", "markdown_handle"})

_CLASSES = "|".join(K.COLLISION_CLASSES)
# statement ID -> its closed field-path rule (all ``computed``); a claim citing another statement's field is refused
# before any value comparison.
STATEMENTS = {
    "repair_scope": re.compile(r"classes_applied"),
    "added_residue_count": re.compile(r"counts\.added_residues"),
    "added_atom_count": re.compile(r"counts\.added_atoms|added_atoms\[\*\]\.origin"),
    "side_chain_residue_count": re.compile(r"counts\.side_chain_residues"),
    "terminal_oxt_count": re.compile(r"counts\.terminal_oxt"),
    "gap_count": re.compile(r"counts\.gaps|gaps\[\d+\]\.length"),
    "replaced_count": re.compile(r"counts\.replaced"),
    "chain_parts_merged_count": re.compile(r"counts\.chain_parts_merged"),
    "unchanged_atom_count": re.compile(r"unchanged\.(atom_count|max_delta_A)"),
    "collision_min_distance": re.compile(rf"collisions\.({_CLASSES})\.min_distance_A"),
    "zero_occupancy_input_atom_count": re.compile(r"zero_occupancy_input_atoms\.(count|residues)"),
}   # keys: exactly ``K.REPORT_STATEMENT_IDS`` in that order (the closed statement set of spec 7; a test checks it)

CLASS_KO = {"chain_parts_merged": "같은 저자 체인 이름의 조각을 한 체인으로 합침",
            "side_chain_atoms_added": "곁사슬 중원자 추가", "terminal_oxt_added": "C 말단 OXT 추가",
            "internal_gap_filled": "내부 틈 메우기", "nonstandard_replaced": "MSE를 MET로 치환"}
ORIGIN_KO = {"side_chain": "곁사슬", "oxt": "C 말단 OXT", "gap_residue": "틈 잔기"}
PARTNER_KO = {"protein": "단백질", "ligand": "리간드", "metal": "금속", "water": "물", "other": "그 밖의 비단백질"}
NO_PARTNER = "— (상대 없음: 이 분류의 비이웃 중원자가 보완 구조에 없다)"
UNDETERMINED = "— (판정 불가)"


class _Unresolved(Exception):
    """Internal: the record lacks a field the report reads (raised as ``EvidenceError``)."""


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_distance(value: Any) -> str:
    """Å with two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68)."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise EvidenceError("structure_repair_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def _render(value: Any, rounding: str) -> str:
    if rounding == "integer":
        if type(value) is not int or value < 0:
            raise EvidenceError("structure_repair_claim_integer_expected")
        return str(value)
    if rounding == "distance_2dp":
        return render_distance(value)
    if rounding == "float_repr":   # the stored float verbatim (Python's shortest round-trip form)
        if type(value) is not float or not math.isfinite(value) or value < 0:
            raise EvidenceError("structure_repair_claim_value_type")
        return repr(value)
    if rounding == "class_list":
        if type(value) is not list or any(item not in K.REPAIR_CLASSES for item in value):
            raise EvidenceError("structure_repair_claim_value_type")
        return ", ".join(value)
    raise EvidenceError("structure_repair_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the RP limitation sentences."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"structure_repair_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# the record's own consistency (each count against its rows; nothing is recomputed from coordinates)

def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise EvidenceError("structure_repair_report_count_invalid")
    return value


def recounted(record: dict[str, Any]) -> dict[str, Any]:
    """The values the report states, each recounted from the record's rows and checked against the stored count,
    class list and limitations; raises ``EvidenceError`` on any disagreement."""
    try:
        counts, gaps, atoms = record["counts"], record["gaps"], record["added_atoms"]
        origins = [row["origin"] for row in atoms]
        if any(origin not in K.ADDED_ATOM_ORIGINS for origin in origins):
            raise EvidenceError("structure_repair_report_origin_invalid")
        by_origin = {origin: origins.count(origin) for origin in K.ADDED_ATOM_ORIGINS}
        lengths = [_count(gap["length"]) for gap in gaps]
        merged = [part["merged"] for part in record["chain_parts"]]
        if any(type(flag) is not bool or flag is not (_count(part["parts"]) > 1)
               for flag, part in zip(merged, record["chain_parts"], strict=True)):
            raise EvidenceError("structure_repair_report_chain_parts_invalid")
        recount = {"added_residues": sum(len(gap["residues"]) for gap in gaps), "added_atoms": len(atoms),
                   "side_chain_residues": len(record["side_chain_repairs"]),
                   "terminal_oxt": len(record["terminal_oxt"]),
                   "gaps": len(gaps), "replaced": len(record["replaced"]), "chain_parts_merged": sum(merged)}
        if any(_count(counts[key]) != value for key, value in recount.items()) or \
                lengths != [len(gap["residues"]) for gap in gaps]:
            raise EvidenceError("structure_repair_report_count_mismatch")
        if (sum(len(row["added_atoms"]) for row in record["side_chain_repairs"]) != by_origin["side_chain"] or
                recount["terminal_oxt"] != by_origin["oxt"]):
            raise EvidenceError("structure_repair_report_count_mismatch")
        applied = {"chain_parts_merged": recount["chain_parts_merged"] > 0,
                   "side_chain_atoms_added": recount["side_chain_residues"] > 0,
                   "terminal_oxt_added": recount["terminal_oxt"] > 0, "internal_gap_filled": recount["gaps"] > 0,
                   "nonstandard_replaced": recount["replaced"] > 0}
        scope = [name for name in K.REPAIR_CLASSES if applied[name]]
        if record["classes_applied"] != scope:
            raise EvidenceError("structure_repair_report_scope_mismatch")
        differs = any(end[flag] is False for end in record["chain_ends"]
                      for flag in ("first_is_sequence_start", "last_is_sequence_end"))
        if record["limitations"] != list(K.applicable_limitations(classes_applied=scope, chain_end_differs=differs)):
            raise EvidenceError("structure_repair_report_limitations_mismatch")
        unchanged = record["unchanged"]
        _count(unchanged["atom_count"])
        _render(unchanged["max_delta_A"], "float_repr")
        if not unchanged["max_delta_A"] <= K.COORDINATE_TOLERANCE_A:
            raise EvidenceError("structure_repair_report_observed_shift")
        zero = record["zero_occupancy_input_atoms"]
        if (_count(zero["count"]) == 0) is not (len(zero["residues"]) == 0) or len(zero["residues"]) > zero["count"]:
            raise EvidenceError("structure_repair_report_zero_occupancy_invalid")
        _check_collisions(record["collisions"], len(atoms))
        return {"scope": scope, "by_origin": by_origin}
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise EvidenceError("structure_repair_report_evidence_unresolved") from exc


def _check_collisions(collisions: dict[str, Any], new_atoms: int) -> None:
    """Each partner class: no minimum <-> no pair <-> both counts 0 (spec 3.6), counts within the new atoms and in
    line with the minimum (a new atom below a threshold exists exactly when the minimum is below it)."""
    if set(collisions) != set(K.COLLISION_CLASSES):   # stored JSON objects keep no key order
        raise EvidenceError("structure_repair_report_collisions_invalid")
    for entry in collisions.values():
        low, below_2, below_15 = entry["min_distance_A"], _count(entry["count_lt_2_0"]), _count(entry["count_lt_1_5"])
        if set(entry) != set(K.COLLISION_KEYS) or below_15 > below_2 or below_2 > new_atoms:
            raise EvidenceError("structure_repair_report_collisions_invalid")
        if low is None:
            if entry["min_pair"] is not None or below_2 or below_15:
                raise EvidenceError("structure_repair_report_collisions_invalid")
            continue
        render_distance(low)
        if entry["min_pair"] is None or (below_2 > 0) is not (low < 2.0) or (below_15 > 0) is not (low < 1.5):
            raise EvidenceError("structure_repair_report_collisions_invalid")


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None = None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": "computed", "source_handle": handle,
            "source_kind": K.KIND, "source_schema": K.SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation, "reference": None}


def _row_selector(index: int, row: dict[str, Any]) -> dict[str, Any]:
    return {"row_index": index, "row_sha256": hashlib.sha256(canonical_json({"index": index, "row": row})).hexdigest()}


def claims_for(handle: str, record: dict[str, Any], repaired: str) -> list[dict[str, Any]]:
    """Every value statement of the report, in template order; each count is recounted from the record's rows."""
    found = recounted(record)
    subject = {"repair_record_handle": handle, "repaired_structure_handle": repaired,
               "source_structure_handle": record["source"]["prepared_structure"]}
    counts = record["counts"]

    def count(statement: str, field: str, quantity: str, operation: str) -> dict[str, Any]:
        return _claim(statement, handle, f"counts.{field}", None, subject, quantity, "count", counts[field],
                      "integer", operation)

    claims = [_claim("repair_scope", handle, "classes_applied", None, subject, "repair_classes", "class_list",
                     record["classes_applied"], "class_list", "classes with stored rows, in REPAIR_CLASSES order"),
              count("added_residue_count", "added_residues", "added_residues", "count(gaps[*].residues)"),
              count("added_atom_count", "added_atoms", "added_atoms", "count(added_atoms)")]
    claims.extend(_claim("added_atom_count", handle, "added_atoms[*].origin", {"origin": origin}, subject,
                         f"added_atoms_{origin}", "count", found["by_origin"][origin], "integer",
                         f"count_where(origin == {origin}; stored added_atoms rows)")
                  for origin in K.ADDED_ATOM_ORIGINS)
    claims.extend([count("side_chain_residue_count", "side_chain_residues", "side_chain_residues",
                         "count(side_chain_repairs)"),
                   count("terminal_oxt_count", "terminal_oxt", "terminal_oxt_residues", "count(terminal_oxt)"),
                   count("gap_count", "gaps", "gaps", "count(gaps)")])
    for index, gap in enumerate(record["gaps"]):
        claims.append(_claim("gap_count", handle, f"gaps[{index}].length", _row_selector(index, gap),
                             {**subject, "chain_auth": gap["chain_auth"], "after_residue": gap["after_residue"],
                              "before_residue": gap["before_residue"]},
                             "gap_length_residues", "count", gap["length"], "integer", "count(residues of this gap)"))
    claims.extend([count("replaced_count", "replaced", "replaced_residues", "count(replaced)"),
                   count("chain_parts_merged_count", "chain_parts_merged", "chains_with_parts_merged",
                         "count_where(merged; chain_parts)"),
                   _claim("unchanged_atom_count", handle, "unchanged.atom_count", None, subject,
                          "observed_atoms_unchanged", "count", record["unchanged"]["atom_count"], "integer"),
                   _claim("unchanged_atom_count", handle, "unchanged.max_delta_A", None, subject,
                          "observed_atoms_max_shift_A", "angstrom", record["unchanged"]["max_delta_A"],
                          "float_repr")])
    for name in K.COLLISION_CLASSES:
        entry = record["collisions"][name]
        if entry["min_distance_A"] is None:
            continue   # no partner: no number, the line says "—" and why (spec 3.6)
        claims.append(_claim("collision_min_distance", handle, f"collisions.{name}.min_distance_A",
                             {"partner_class": name}, {**subject, "partner_class": name, "min_pair": entry["min_pair"]},
                             f"collision_min_distance_{name}_A", "angstrom", entry["min_distance_A"], "distance_2dp"))
    zero = record["zero_occupancy_input_atoms"]
    claims.extend([
        _claim("zero_occupancy_input_atom_count", handle, "zero_occupancy_input_atoms.count", None, subject,
               "zero_occupancy_input_atoms", "count", zero["count"], "integer"),
        _claim("zero_occupancy_input_atom_count", handle, "zero_occupancy_input_atoms.residues", None, subject,
               "zero_occupancy_input_residues", "count", len(zero["residues"]), "integer",
               "count(zero_occupancy_input_atoms.residues)")])
    return claims


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its statement, field rule, source and every value equal the claim rebuilt from that
    field of the record."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("structure_repair_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("structure_repair_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["reference"] is not None:
        raise EvidenceError("structure_repair_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("structure_repair_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (K.KIND, K.SCHEMA):
        raise EvidenceError("structure_repair_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("structure_repair_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("structure_repair_claim_shape") from exc
    if match is None:
        raise EvidenceError("structure_repair_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("structure_repair_claim_binding_mismatch")
    return proposed


def validate_repair_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored record (not snapshot / markdown handle)."""
    try:
        result = bundle.validated_result(run, handle)   # an unavailable environment is raised as it is (412)
        published = bundle.producer(run, handle)
    except bundle.RepairEvidenceError as exc:
        raise EvidenceError(f"structure_repair_record_invalid: {exc}") from exc
    try:
        record, event = result["record"], published["event"]
        if event["prepared_structure"] != result["prepared_structure"]:
            raise EvidenceError("structure_repair_record_publication_mismatch")
        claims = claims_for(handle, record, result["prepared_structure"])
        return {"schema": K.REPORT_MANIFEST_SCHEMA, "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress",
                "result_handle": handle, "result_schema": K.SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: record[key] for key in COPIED_FIELDS},
                "repaired_structure": result["prepared_structure"], "source_structure": result["source_structure"],
                "claims": claims,
                "provenance": {"structure_repair": {
                    "job_id": published["job"]["job_id"], "attempt_id": event["attempt_id"],
                    "protocol_id": published["job"]["protocol_id"], "tool_id": published["job"]["tool_id"],
                    "published_event_seq": published["published_seq"], "coordinates": result["coordinates"],
                    "manifest": result["manifest"]}},
                "evidence_statement": EVIDENCE_STATEMENT}
    except EvidenceError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError, ValueError) as exc:
        raise EvidenceError("structure_repair_report_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# Markdown

_SLOT = re.compile("\x00(\\d+)\x00")


def render_structure_repair_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every number is the rendered text of a bound claim or a copied record value.

    Values and identifiers go into slots; the forbidden-word check runs on the fixed template text with the slots
    left empty, then the slots are filled. The limitation lines must be the record's RP sentences."""
    claims = manifest["claims"]
    if any(item not in FIXED_LIMITATIONS for item in manifest["limitations"]):
        raise EvidenceError("structure_repair_report_limitations_mismatch")
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def value(statement: str, path: str, selector: dict[str, Any] | None = None) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and c["field_path"] == path and
                 (selector is None or c["row_selector"] == selector)]
        if len(found) != 1:
            raise EvidenceError("structure_repair_report_claim_missing")
        return md(found[0])

    def flag(item: Any) -> str:
        return UNDETERMINED if item is None else ("예 (true)" if item else "아니오 (false)")

    method, parameters, job = manifest["method"], manifest["parameters"], manifest["provenance"]["structure_repair"]
    lines = [f"# {LIST_NAME} (structure repair)", "", "Status: complete", "",
             f"Result: {md(manifest['result_handle'])} ({md(K.SCHEMA)})",
             f"- 보완 구조: {md(manifest['repaired_structure'])}",
             f"- 보완 전 원본 전처리 구조: {md(manifest['source_structure'])}",
             (f"- 보완 작업: {md(job['job_id'])}, attempt {md(job['attempt_id'])} ({md(job['protocol_id'])}), "
              f"게시 이벤트 {md(job['published_event_seq'])}"),
             (f"- 방법: {md(manifest['method_version'])}, {md(method['engine'])} {md(method['pdbfixer_version'])}, "
              f"OpenMM {md(method['openmm_distribution_version'])}"),
             (f"- 보완 정책: {md(parameters['repair_policy'])}, seed {md(parameters['seed'])}, 틈 최대 "
              f"{md(parameters['max_gap_residues'])}잔기, 새 원자 좌표 소수 "
              f"{md(parameters['new_atom_coordinate_decimals'])}자리"),
             f"- 전처리 정책: 물 {md(parameters['waters'])}, 수소 {md(parameters['hydrogens'])}",
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             "## 관측 좌표와 모델링 좌표", "",
             (f"- 실험으로 관측한 입력 원자: {value('unchanged_atom_count', 'unchanged.atom_count')}개, 좌표 그대로 "
              f"(최대 이동 {value('unchanged_atom_count', 'unchanged.max_delta_A')} Å, 검사 기준 "
              f"{md(K.COORDINATE_TOLERANCE_A)} Å 이하)"),
             (f"- 추가 원자 (PDBFixer가 만든 모델링 좌표, mmCIF {md('_atom_site.calc_flag')} = {md(K.CALC_FLAG_NEW)}): "
              f"{value('added_atom_count', 'counts.added_atoms')}개 — " + ", ".join(
                  f"{ORIGIN_KO[origin]} ({md(origin)}) "
                  f"{value('added_atom_count', 'added_atoms[*].origin', {'origin': origin})}"
                  for origin in K.ADDED_ATOM_ORIGINS)),
             f"- 추가 잔기 (메운 틈의 잔기): {value('added_residue_count', 'counts.added_residues')}개",
             "", "## 보완 종류 (repair\\_scope)", ""]
    scope = [c for c in claims if c["statement_id"] == "repair_scope"]
    if len(scope) != 1:
        raise EvidenceError("structure_repair_report_claim_missing")
    for name in scope[0]["exact_value"]:
        lines.append(f"- {CLASS_KO[name]} ({md(name)})")
    lines.extend(["", "## 개수 (ProtView 계산: 보완 기록의 필드와 행)", "",
                  f"- 추가 잔기 수 ({md('counts.added_residues')}): {value('added_residue_count', 'counts.added_residues')}",
                  f"- 추가 원자 수 ({md('counts.added_atoms')}): {value('added_atom_count', 'counts.added_atoms')}",
                  (f"- 곁사슬 원자를 더한 잔기 수 ({md('counts.side_chain_residues')}): "
                   f"{value('side_chain_residue_count', 'counts.side_chain_residues')}"),
                  (f"- C 말단 OXT를 더한 잔기 수 ({md('counts.terminal_oxt')}): "
                   f"{value('terminal_oxt_count', 'counts.terminal_oxt')}"),
                  f"- 메운 틈 수 ({md('counts.gaps')}): {value('gap_count', 'counts.gaps')}",
                  f"- 치환 잔기 수 ({md('counts.replaced')}): {value('replaced_count', 'counts.replaced')}",
                  (f"- 조각을 합친 체인 수 ({md('counts.chain_parts_merged')}): "
                   f"{value('chain_parts_merged_count', 'counts.chain_parts_merged')}"),
                  (f"- 점유율 0인 입력 원자 수 ({md('zero_occupancy_input_atoms.count')}): "
                   f"{value('zero_occupancy_input_atom_count', 'zero_occupancy_input_atoms.count')}, 그 잔기 수 "
                   f"{value('zero_occupancy_input_atom_count', 'zero_occupancy_input_atoms.residues')} "
                   "(좌표는 입력 그대로)")])
    merged = [part["chain_auth"] for part in manifest["chain_parts"] if part["merged"]]
    if merged:
        lines.extend(["", "## 조각을 합친 체인", "", f"- 저자 체인: {md(', '.join(merged))}"])
    if manifest["side_chain_repairs"]:
        lines.extend(["", "## 곁사슬 원자를 더한 잔기", "", "| 잔기 | 더한 원자 |", "| --- | --- |"])
        for row in manifest["side_chain_repairs"]:
            lines.append(f"| {md(_ref(row['residue']))} | {md(', '.join(row['added_atoms']))} |")
    if manifest["terminal_oxt"]:
        lines.extend(["", "## C 말단 OXT를 더한 잔기", ""])
        lines.extend(f"- {md(_ref(row['residue']))}" for row in manifest["terminal_oxt"])
    if manifest["gaps"]:
        lines.extend(["", "## 메운 틈", "", "| 체인 | 앞 잔기 | 뒤 잔기 | 길이 (잔기) | 더한 잔기 |",
                      "| --- | --- | --- | ---: | --- |"])
        for index, gap in enumerate(manifest["gaps"]):
            names = ", ".join(f"{item['seq_auth']}{item['icode']} {item['resname']}" for item in gap["residues"])
            lines.append(f"| {md(gap['chain_auth'])} | {md(_ref(gap['after_residue']))} | "
                         f"{md(_ref(gap['before_residue']))} | "
                         f"{value('gap_count', f'gaps[{index}].length', _row_selector(index, gap))} | {md(names)} |")
    if manifest["replaced"]:
        lines.extend(["", "## 치환 잔기", "", "| 원래 잔기 | 새 잔기 | 원자 이름 | 레코드 종류 |", "| --- | --- | --- | --- |"])
        for row in manifest["replaced"]:
            atom_map = ", ".join(f"{item['from']} → {item['to']}" for item in row["atom_map"]) or "—"
            lines.append(f"| {md(_ref(row['from']))} | {md(_ref(row['to']))} | {md(atom_map)} | "
                         f"{md(row['record_type']['from'])} → {md(row['record_type']['to'])} |")
    lines.extend(["", "## 사슬 끝 (관측 끝과 서열 끝)", "",
                  "| 체인 | 관측 첫 잔기 | 관측 끝 잔기 | 첫 잔기 = 서열 시작 | 끝 잔기 = 서열 끝 |",
                  "| --- | --- | --- | --- | --- |"])
    for end in manifest["chain_ends"]:
        lines.append(f"| {md(end['chain_auth'])} | {md(_ref(end['observed_first']))} | "
                     f"{md(_ref(end['observed_last']))} | {flag(end['first_is_sequence_start'])} | "
                     f"{flag(end['last_is_sequence_end'])} |")
    lines.extend(["", "## 충돌 기록 (새 중원자와 가장 가까운 비이웃 중원자)", "",
                  ("새 중원자마다 같은 잔기와 바로 이웃한 폴리머 잔기를 뺀 가장 가까운 중원자까지의 거리(Å)를 상대 "
                   "분류별로 적었다. 상대가 없는 분류는 개수 0, 최소 거리 —로 적었고, 이는 그 분류의 상대 원자가 보완 "
                   "구조에 없다는 뜻이다. 거리는 기록일 뿐이며 보완을 거절하지 않았다."), "",
                  ("| 상대 분류 | 최소 거리 (Å) | 2.0 Å 미만 새 원자 수 (count\\_lt\\_2\\_0) | "
                   "1.5 Å 미만 새 원자 수 (count\\_lt\\_1\\_5) | 최소 거리 쌍 (새 원자 — 상대 원자) |"),
                  "| --- | ---: | ---: | ---: | --- |"])
    for name in K.COLLISION_CLASSES:
        entry = manifest["collisions"][name]
        pair = entry["min_pair"]
        if entry["min_distance_A"] is None:
            distance, pair_text = NO_PARTNER, "—"
        else:
            distance = value("collision_min_distance", f"collisions.{name}.min_distance_A", {"partner_class": name})
            pair_text = (f"{md(_ref(pair['new_residue']))} {md(pair['new_atom'])} — "
                         f"{md(_ref(pair['partner_residue']))} {md(pair['partner_atom'])}")
        lines.append(f"| {PARTNER_KO[name]} ({md(name)}) | {distance} | {md(entry['count_lt_2_0'])} | "
                     f"{md(entry['count_lt_1_5'])} | {pair_text} |")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units and field paths are in the JSON download "
                   f"({md(len(claims))} claims). The added atom rows and the repaired mmCIF are in the structure "
                   "repair reads."), ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_structure_repair_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object for one stored repair record (nothing is repaired again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot()}
        markdown = render_structure_repair_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("structure_repair_report_too_large")
        produced_by = f"structure_repair_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by=produced_by, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", K.REPORT_MANIFEST_SCHEMA, manifest,
                               produced_by=produced_by,
                               summary={"result_handle": result_handle, "analysis_type": ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_structure_repair_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored repair report from stored objects only (nothing is repaired again)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", K.REPORT_MANIFEST_SCHEMA, "json"):
        raise EvidenceError("structure_repair_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            report["render_version"] != RENDER_VERSION or type(report["result_handle"]) is not str):
        raise EvidenceError("structure_repair_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("structure_repair_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"structure_repair_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["structure_repair"]["published_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("structure_repair_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("structure_repair_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("structure_repair_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("structure_repair_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_structure_repair_report(report):
        raise EvidenceError("structure_repair_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
