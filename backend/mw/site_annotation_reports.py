"""Immutable, field-cited reports for ``reference_site_annotation@1`` (``method_report_manifest@1``,
``analysis_type: "reference_site_annotation"``, render ``reference_site_annotation_markdown@1``).

The input is one annotation handle. Two evidence kinds are kept apart (spec M16 section 7), as in the M15 report:

- ``reference_value`` -- reference snapshot values cited from the numbering map object: per-site accession, KLIFS
  number and label, the structure residue (7 fields) the map row assigns that number to, and the UniProt position;
  plus each group's accession. Each claim carries the snapshot set hash, the source snapshot records and the note
  "참조 스냅샷 값, 계산 아님".
- ``computed`` -- per site and computed contact type, the count of stored contact rows whose residue equals the site
  residue in all 7 fields (``site_contact_count``, citing the contact result's rows); per site, the minimum stored
  ``distance_A`` over those rows (``site_min_distance_A``, citing that row, rendered ``Decimal(str(v))`` to 0.01 with
  ``ROUND_HALF_UP``); and the site counts by status and by absent reason (citing the annotation object).

No number is written for a type the contact result did not compute ("계산하지 않음"), a residue the contact tool
does not check ("접촉 도구가 검사하지 않는 잔기") or an annotation without contacts ("접촉 결과 없음"); 0 appears only
for a computed type without rows. Creating, reopening and downloading never re-run the annotation, the numbering or
the contacts: the stored annotation is checked against the stored map and contact rows it cites (closed status and
reason sets, counts and minima equal to the cited rows), every manifest field and claim is compared, and the Markdown
is compared byte for byte with a re-render. The fixed template makes no interpretive statement; the renderer rejects
interpretive wording on every line except the four fixed limitation sentences (negative notices), matched exactly.
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import numbering_reports as nr
from . import site_annotation as sa
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _provenance, _ref

ANALYSIS_TYPE = "reference_site_annotation"
RENDER_VERSION = "reference_site_annotation_markdown@1"
TOOL = "annotate_reference_sites"
CONTACT_TOOL = "compute_interactions"
REPORT_BYTES = nr.REPORT_BYTES
CONTACTS_KIND = ("interaction_set", "interaction_set@1")
LIMITATIONS = list(sa.LIMITATIONS)
REFERENCE_NOTE = nr.REFERENCE_NOTE
REFERENCE_STATEMENT = ("Accessions, UniProt positions, KLIFS pocket numbers and labels, and the structure residue a "
                       "numbering map row assigns each number to are reference snapshot values (참조 스냅샷 값, 계산 "
                       "아님), not ProtView calculations. ProtView computed only the per-site geometric contact counts "
                       "and minimum distances from the stored contact rows, and the site counts.")
STATUS_KO = {"annotated": "주석됨", "absent": "없음"}
ABSENT_KO = {"klifs_not_applied": "KLIFS 번호 적용 안 됨", "pocket_gap": "KLIFS 포켓 문자열의 gap 자리",
             "region_unresolved": "구역 번호 미확정", "no_mapped_residue": "이 번호의 대응된 잔기 없음"}
GROUP_KO = {"accession_not_in_klifs": "KLIFS 스냅샷에 없는 accession", "klifs_pocket_empty": "KLIFS 포켓 없음",
            "klifs_multiple_entries": "KLIFS 항목이 여럿", "uniprot_sequence_unavailable": "UniProt 서열 없음",
            "no_mapped_accession": "대응된 accession 없음"}
NOT_COMPUTED = "계산하지 않음"
NOT_ASSESSED = "접촉 도구가 검사하지 않는 잔기"
NO_CONTACTS = "접촉 결과 없음"
NOT_APPLICABLE = "해당 없음"
NO_ROW = "없음 (null)"
MIN_MEANING = "최소 거리는 계산한 종류·cutoff 안의 최소입니다(저장된 접촉 행의 distance\\_A)."

EVIDENCE_KINDS = ("computed", "reference_value")
# statement ID -> (evidence kind, source kind); fixed template, nothing else carries a number in this report.
STATEMENTS = {
    "site_status_count": ("computed", sa.KIND),
    "site_absent_reason_count": ("computed", sa.KIND),
    "site_contact_count": ("computed", CONTACTS_KIND[0]),
    "site_min_distance_A": ("computed", CONTACTS_KIND[0]),
    "reference_accession": ("reference_value", nr.rn.KIND),
    "reference_uniprot_position": ("reference_value", nr.rn.KIND),
    "reference_klifs_index": ("reference_value", nr.rn.KIND),
    "reference_klifs_label": ("reference_value", nr.rn.KIND),
    "reference_site_residue": ("reference_value", nr.rn.KIND),
}
SCHEMAS = {sa.KIND: sa.SCHEMA, CONTACTS_KIND[0]: CONTACTS_KIND[1], nr.rn.KIND: nr.rn.SCHEMA}
COMPUTED_FIELDS = re.compile(r"groups\.sites\.(status|absent_reason)|rows\.type|rows\[\d+\]\.distance_A")
REFERENCE_FIELDS = re.compile(
    r"rows\[\d+\]\.(uniprot_accession|uniprot_position|klifs_index|klifs_label|residue)|"
    r"chains\[\d+\]\.klifs\[\d+\]\.accession")
CLAIM_KEYS = nr.CLAIM_KEYS
INTERPRETIVE = re.compile(nr.INTERPRETIVE.pattern + "|촉매", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget", "active_set_hash", "stale_snapshot"}
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "method_version", "site_set", "numbering_map", "structure", "snapshot_set",
    "reference_set_handle", "contacts", "groups", "null_result", "claims", "provenance", "reference_statement",
    "klifs_terms", "limitations", "snapshot", "markdown_handle"})
TOP_KEYS = {"schema", "method_version", "site_set", "numbering_map", "snapshot_set_hash", "structure", "contacts",
            "groups", "other_contact_residues", "null_result", "limitations"}
GROUP_KEYS = {"chain_auth", "accession", "klifs_applied", "klifs_absent_reason", "sites"}
SITE_KEYS = {"klifs_index", "klifs_label", "status", "absent_reason", "residue", "map_row_index", "residue_match",
             "klifs_match", "display_label", "contact"}
CONTACT_KEYS = {"assessed", "not_assessed_reason", "by_type", "min_distance_A", "min_distance_row_index",
                "polar_pairs"}
HEX64 = re.compile(r"[0-9a-f]{64}")


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_distance(value: Any) -> str:
    """Å with two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68)."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("site_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


def _render(value: Any, rounding: str) -> str:
    if rounding == "distance_2dp":
        return render_distance(value)
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("site_claim_integer_expected")
        return str(value)
    if rounding == "verbatim":
        if type(value) not in (int, str):
            raise EvidenceError("site_claim_value_type")
        return str(value)
    if rounding == "residue_ref":
        return _ref(value)
    raise EvidenceError("site_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the four fixed limitation sentences."""
    for line in text.split("\n"):
        if line in sa.LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"site_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects only; nothing is recomputed from coordinates or the reference folder)

def _residue_ok(residue: Any) -> bool:
    return type(residue) is dict and set(residue) == set(sa.IDENTITY_FIELDS)


def _check_contacts(annotation: dict[str, Any], contacts: dict[str, Any]) -> list[dict[str, Any]]:
    record = annotation["contacts"]
    parameters, ligand = contacts["parameters"], contacts["selection"]["ligand"]
    types, cutoff = parameters["types"], parameters["cutoff_A"]
    if (type(record) is not dict or contacts["structure"] != annotation["structure"]["handle"] or
            canonical_json(record) != canonical_json({"handle": record.get("handle"), "ligand": ligand,
                                                      "cutoff_A": cutoff, "types": types})):
        raise EvidenceError("site_contacts_record_mismatch")
    if (type(types) is not list or not types or any(t not in sa.CONTACT_TYPES for t in types) or
            len(set(types)) != len(types) or type(cutoff) not in (int, float) or not math.isfinite(cutoff) or
            not _residue_ok(ligand)):
        raise EvidenceError("site_contacts_parameters_invalid")
    rows = contacts["rows"]
    for row in rows:
        distance = row["distance_A"]
        if (not _residue_ok(row["residue"]) or row["type"] not in types or type(distance) not in (int, float) or
                not math.isfinite(distance) or distance < 0 or distance > cutoff or
                canonical_json(row["ligand"]) != canonical_json(ligand)):
            raise EvidenceError("site_contact_row_invalid")
    return rows


def _expected_groups(map_content: dict[str, Any]) -> list[tuple[Any, ...]]:
    out = []
    for chain in map_content["chains"]:
        for entry in chain["klifs"] or [None]:
            if entry is None:
                out.append((chain["chain_auth"], None, False, "no_mapped_accession"))
            else:
                applied = entry["applied"] is True
                out.append((chain["chain_auth"], entry["accession"], applied,
                            None if applied else entry["absent_reason"]))
    return out


def _site_rows(map_content: dict[str, Any], chain_auth: str, accession: Any, index: int) -> list[int]:
    return [i for i, r in enumerate(map_content["rows"]) if r["residue"]["chain_auth"] == chain_auth and
            r["status"] == "mapped" and r["uniprot_accession"] == accession and r["klifs_index"] == index]


def _check_site_contact(site: dict[str, Any], rows: list[dict[str, Any]], types: list[str]) -> None:
    contact = site["contact"]
    if type(contact) is not dict or set(contact) != CONTACT_KEYS or contact["assessed"] not in (True, False):
        raise EvidenceError("site_contact_shape")
    key = sa.identity(site["residue"])
    mine = [(i, r) for i, r in enumerate(rows) if sa.identity(r["residue"]) == key]
    by_type = contact["by_type"]
    if type(by_type) is not dict or set(by_type) != set(sa.CONTACT_TYPES) or any(
            by_type[t] != {"computed": t in types, "count": by_type[t].get("count")} for t in sa.CONTACT_TYPES):
        raise EvidenceError("site_contact_types_mismatch")
    if contact["assessed"] is False:
        # The contact tool checks polymer records only; such a residue cannot have a row, and has no number.
        if (contact["not_assessed_reason"] != sa.NOT_ASSESSED_REASON or mine or
                any(by_type[t]["count"] is not None for t in sa.CONTACT_TYPES) or
                any(contact[k] is not None for k in ("min_distance_A", "min_distance_row_index", "polar_pairs"))):
            raise EvidenceError("site_contact_not_assessed_invalid")
        return
    if contact["not_assessed_reason"] is not None:
        raise EvidenceError("site_contact_reason_invalid")
    for t in sa.CONTACT_TYPES:
        expected = sum(1 for _, r in mine if r["type"] == t) if t in types else None
        if by_type[t]["count"] != expected or type(by_type[t]["count"]) is not type(expected):
            raise EvidenceError("site_contact_count_mismatch")
    low = min((r["distance_A"] for _, r in mine), default=None)
    low_index = None if low is None else min(i for i, r in mine if r["distance_A"] == low)
    if (contact["min_distance_A"] != low or type(contact["min_distance_A"]) is not type(low) or
            contact["min_distance_row_index"] != low_index):
        raise EvidenceError("site_contact_minimum_mismatch")
    polar = None if "polar_contact" not in types else [
        {"contact_row_index": i, "protein_atom": r["protein_atom"], "ligand_atom": r["ligand_atom"],
         "distance_A": r["distance_A"]} for i, r in mine if r["type"] == "polar_contact"]
    if canonical_json(contact["polar_pairs"]) != canonical_json(polar):
        raise EvidenceError("site_contact_polar_pairs_mismatch")


def check_annotation(content: dict[str, Any], map_content: dict[str, Any],
                     contacts: dict[str, Any] | None) -> None:
    """The stored annotation against the stored map and contact rows it cites; raises ``EvidenceError``."""
    try:
        if (type(content) is not dict or set(content) != TOP_KEYS or content["schema"] != sa.SCHEMA or
                content["method_version"] != sa.METHOD_VERSION or content["site_set"] != sa.site_set() or
                content["limitations"] != LIMITATIONS):
            raise EvidenceError("site_annotation_schema_invalid")
        if (content["snapshot_set_hash"] != map_content["snapshot_set"]["set_hash"] or
                canonical_json(content["structure"]) != canonical_json(map_content["structure"])):
            raise EvidenceError("site_annotation_map_link_mismatch")
        if (contacts is None) is not (content["contacts"] is None) or \
                (contacts is None) is not (content["other_contact_residues"] is None):
            raise EvidenceError("site_annotation_contacts_mismatch")
        rows = _check_contacts(content, contacts) if contacts is not None else None
        types = content["contacts"]["types"] if contacts is not None else None
        groups = content["groups"]
        if type(groups) is not list or any(type(g) is not dict or set(g) != GROUP_KEYS for g in groups):
            raise EvidenceError("site_group_shape")
        for group in groups:
            reason = group["klifs_absent_reason"]
            if (group["klifs_applied"] not in (True, False) or (reason is None) is not group["klifs_applied"] or
                    (reason is not None and reason not in sa.GROUP_ABSENT_REASONS)):
                raise EvidenceError("site_group_reason_invalid")
        if [(g["chain_auth"], g["accession"], g["klifs_applied"], g["klifs_absent_reason"]) for g in groups] != \
                _expected_groups(map_content):
            raise EvidenceError("site_groups_mismatch")
        annotated: set[tuple[Any, ...]] = set()
        for group in groups:
            sites = group["sites"]
            if type(sites) is not list or [(s.get("klifs_index"), s.get("klifs_label")) for s in sites] != \
                    list(sa.SITES) or any(set(s) != SITE_KEYS for s in sites):
                raise EvidenceError("site_list_mismatch")
            for site in sites:
                status, reason = site["status"], site["absent_reason"]
                if status not in sa.STATUSES:
                    raise EvidenceError("site_status_invalid")
                found = _site_rows(map_content, group["chain_auth"], group["accession"], site["klifs_index"]) \
                    if group["klifs_applied"] else []
                if status == "absent":
                    if (reason not in sa.ABSENT_REASONS or found or
                            (reason == "klifs_not_applied") is not (not group["klifs_applied"]) or
                            any(site[k] is not None for k in ("residue", "map_row_index", "residue_match",
                                                              "klifs_match", "display_label", "contact"))):
                        raise EvidenceError("site_absent_invalid")
                    continue
                if reason is not None or found != [site["map_row_index"]]:
                    raise EvidenceError("site_annotated_row_mismatch")
                row = map_content["rows"][site["map_row_index"]]
                if (canonical_json(site["residue"]) != canonical_json(row["residue"]) or
                        site["klifs_label"] != row["klifs_label"] or site["residue_match"] != row["residue_match"] or
                        site["klifs_match"] != row["klifs_match"] or
                        site["display_label"] != sa.display_label(row["residue"], row["klifs_label"])):
                    raise EvidenceError("site_annotated_row_mismatch")
                annotated.add(sa.identity(site["residue"]))
                if contacts is None:
                    if site["contact"] is not None:
                        raise EvidenceError("site_contact_without_contacts")
                else:
                    _check_site_contact(site, rows, types)
        if content["null_result"] is not (not annotated):
            raise EvidenceError("site_null_result_mismatch")
        if rows is not None:
            other: dict[tuple[Any, ...], dict[str, Any]] = {}
            for i, row in enumerate(rows):
                if sa.identity(row["residue"]) not in annotated:
                    other.setdefault(sa.identity(row["residue"]), {"residue": row["residue"],
                                                                    "row_indexes": []})["row_indexes"].append(i)
            if canonical_json(content["other_contact_residues"]) != canonical_json(list(other.values())):
                raise EvidenceError("site_other_contact_residues_mismatch")
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("site_annotation_evidence_unresolved") from exc


def validated_annotation(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a published annotation, its numbering map and contact result; returns (content, context)."""
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (sa.KIND, sa.SCHEMA):
            raise EvidenceError("wrong_result_kind")
        content = run.store.load(handle)
        events = list(run.events.read())
        provenance = {"annotation": _provenance(events, handle, expected_tool=TOOL)}
        map_handle = content["numbering_map"]
        map_content, map_context = nr.validated_numbering_map(run, map_handle)
        provenance["numbering_map"] = map_context["provenance"]
        contacts = None
        record = content["contacts"]
        if record is not None:
            contacts_meta = run.store.meta(record["handle"])
            if (contacts_meta["kind"], contacts_meta["schema"]) != CONTACTS_KIND:
                raise EvidenceError("site_contacts_kind_mismatch")
            contacts = run.store.load(record["handle"])
            provenance["contacts"] = _provenance(events, record["handle"], expected_tool=CONTACT_TOOL)
        else:
            provenance["contacts"] = None
        check_annotation(content, map_content, contacts)
        return content, {"map": map_content, "reference_set_handle": map_context["reference_set_handle"],
                         "contacts": contacts, "provenance": provenance}
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("site_annotation_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any], subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None,
           reference: dict[str, Any] | None) -> dict[str, Any]:
    kind, source_kind = STATEMENTS[statement_id]
    return {"statement_id": statement_id, "evidence_kind": kind, "source_handle": handle,
            "source_kind": source_kind, "source_schema": SCHEMAS[source_kind],
            "source_sha256": handle.rsplit("/", 1)[-1], "field_path": path, "row_selector": selector,
            "subject": subject, "quantity": quantity, "unit": unit, "exact_value": value,
            "rendered_value": _render(value, rounding), "rounding": rounding, "operation": operation,
            "reference": reference}


def _row_selector(index: int, row: dict[str, Any]) -> dict[str, Any]:
    return {"row_index": index, "row_sha256": hashlib.sha256(canonical_json({"index": index, "row": row})).hexdigest()}


def claims_for(handle: str, content: dict[str, Any], map_content: dict[str, Any],
               contacts: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every value statement of the report, each bound to one stored field or one count over stored rows."""
    map_handle = content["numbering_map"]
    sites = [s for g in content["groups"] for s in g["sites"]]
    claims = [_claim("site_status_count", handle, "groups.sites.status", {"status": status},
                     {"annotation_handle": handle}, f"{status}_sites", "count",
                     sum(s["status"] == status for s in sites), "integer", "count_kind(groups.sites.status)", None)
              for status in sa.STATUSES]
    claims.extend(_claim("site_absent_reason_count", handle, "groups.sites.absent_reason", {"absent_reason": reason},
                         {"annotation_handle": handle}, f"{reason}_sites", "count",
                         sum(s["absent_reason"] == reason for s in sites), "integer",
                         "count_kind(groups.sites.absent_reason)", None) for reason in sa.ABSENT_REASONS)
    record = content["contacts"]
    rows = contacts["rows"] if contacts is not None else None
    chain_index = {chain["chain_auth"]: ci for ci, chain in enumerate(map_content["chains"])}
    for group in content["groups"]:
        chain_auth, accession = group["chain_auth"], group["accession"]
        ci = chain_index[chain_auth]
        group_subject = {"map_handle": map_handle, "annotation_handle": handle, "chain_auth": chain_auth}
        if accession is not None:
            ki = next(k for k, item in enumerate(map_content["chains"][ci]["klifs"]) if item["accession"] == accession)
            claims.append(_claim("reference_accession", map_handle, f"chains[{ci}].klifs[{ki}].accession",
                                 {"chain_auth": chain_auth, "klifs_item": ki}, group_subject, "group_accession",
                                 "identifier", accession, "verbatim", None, nr._reference(map_content, ("uniprot",))))
        for site in group["sites"]:
            if site["status"] != "annotated":
                continue
            index = site["map_row_index"]
            row = map_content["rows"][index]
            selector = _row_selector(index, row)
            subject = {**group_subject, "accession": accession, "klifs_index": site["klifs_index"],
                       "klifs_label": site["klifs_label"], "residue": site["residue"]}
            position_sources = ("sifts", "uniprot") if row["sifts"] is not None else ("uniprot",)
            for statement, field, unit, rounding, sources in (
                    ("reference_accession", "uniprot_accession", "identifier", "verbatim", position_sources),
                    ("reference_uniprot_position", "uniprot_position", "uniprot_sequence_position", "verbatim",
                     position_sources),
                    ("reference_klifs_index", "klifs_index", "klifs_pocket_index", "verbatim", ("klifs", "uniprot")),
                    ("reference_klifs_label", "klifs_label", "identifier", "verbatim", ("klifs", "uniprot")),
                    ("reference_site_residue", "residue", "residue_identity", "residue_ref", ("klifs", "uniprot"))):
                claims.append(_claim(statement, map_handle, f"rows[{index}].{field}", selector, subject, field, unit,
                                     row[field], rounding, None, nr._reference(map_content, sources)))
            contact = site["contact"]
            if contact is None or contact["assessed"] is not True:
                continue
            contact_subject = {**subject, "ligand": record["ligand"]}
            key = sa.identity(site["residue"])
            mine = [i for i, r in enumerate(rows) if sa.identity(r["residue"]) == key]
            for t in record["types"]:
                indexes = [i for i in mine if rows[i]["type"] == t]
                claims.append(_claim("site_contact_count", record["handle"], "rows.type",
                                     {"residue": site["residue"], "type": t, "row_indexes": indexes},
                                     contact_subject, f"{t}_rows", "count", len(indexes), "integer",
                                     f"count_kind(rows.type == {t}; rows.residue == site residue, 7 fields)", None))
            if mine:
                low = min(rows[i]["distance_A"] for i in mine)
                j = min(i for i in mine if rows[i]["distance_A"] == low)
                claims.append(_claim("site_min_distance_A", record["handle"], f"rows[{j}].distance_A",
                                     _row_selector(j, rows[j]), contact_subject, "min_distance_A", "angstrom",
                                     rows[j]["distance_A"], "distance_2dp",
                                     "minimum(rows.distance_A; rows.residue == site residue, 7 fields; computed types "
                                     "within cutoff)", None))
    return claims


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source kind and every value equal the claim built from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("site_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("site_claim_statement_not_allowed")
    kind, source_kind = STATEMENTS[statement]
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["evidence_kind"] != kind:
        raise EvidenceError("site_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str:
        raise EvidenceError("site_claim_shape")
    if kind == "computed":
        if REFERENCE_FIELDS.fullmatch(path):
            raise EvidenceError("site_claim_reference_field_as_computed")
        if not COMPUTED_FIELDS.fullmatch(path) or proposed["reference"] is not None:
            raise EvidenceError("site_claim_computed_field_rule")
    else:
        if COMPUTED_FIELDS.fullmatch(path):
            raise EvidenceError("site_claim_computed_field_as_reference")
        reference = proposed["reference"]
        if not REFERENCE_FIELDS.fullmatch(path) or type(reference) is not dict or \
                reference.get("note") != REFERENCE_NOTE:
            raise EvidenceError("site_claim_reference_field_rule")
    if proposed["source_kind"] != source_kind or proposed["source_schema"] != SCHEMAS[source_kind]:
        raise EvidenceError("site_claim_source_kind_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("site_claim_shape") from exc
    if match is None:
        raise EvidenceError("site_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("site_claim_binding_mismatch")
    return proposed


def validate_site_annotation_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _call(provenance: dict[str, Any] | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return {key: provenance[key] for key in ("call_id", "tool", "tool_version", "created_event_seq",
                                             "completed_event_seq")}


def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated annotation (not snapshot / markdown handle)."""
    content, context = validated_annotation(run, handle)
    try:
        map_content = context["map"]
        return {
            "schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
            "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
            "result_schema": sa.SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
            "method_version": content["method_version"], "site_set": content["site_set"],
            "numbering_map": content["numbering_map"], "structure": content["structure"],
            "snapshot_set": map_content["snapshot_set"], "reference_set_handle": context["reference_set_handle"],
            "contacts": content["contacts"], "groups": content["groups"], "null_result": content["null_result"],
            "claims": claims_for(handle, content, map_content, context["contacts"]),
            "provenance": {name: _call(item) for name, item in context["provenance"].items()},
            "reference_statement": REFERENCE_STATEMENT, "klifs_terms": nr.KLIFS_TERMS,
            "limitations": content["limitations"]}
    except (KeyError, TypeError, IndexError, AttributeError, StopIteration) as exc:
        raise EvidenceError("site_report_evidence_unresolved") from exc


def _contact_cells(manifest: dict[str, Any], site: dict[str, Any], value) -> list[str]:
    """Three per-type count cells and the minimum-distance cell; words instead of numbers where none exists."""
    if site["status"] != "annotated":
        return [NOT_APPLICABLE] * 4
    contact = site["contact"]
    if contact is None:
        return [NO_CONTACTS] * 4
    if contact["assessed"] is not True:
        return [NOT_ASSESSED] * 4
    residue = site["residue"]
    cells = []
    for t in sa.CONTACT_TYPES:
        if t not in manifest["contacts"]["types"]:
            cells.append(NOT_COMPUTED)
        else:
            cells.append(value("site_contact_count", lambda c, t=t: c["field_path"] == "rows.type" and
                               c["row_selector"]["type"] == t and c["row_selector"]["residue"] == residue))
    minimum = value("site_min_distance_A", lambda c: c["subject"]["residue"] == residue, default=NO_ROW)
    return [*cells, minimum]


def render_site_annotation_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim."""
    claims = manifest["claims"]

    def value(statement: str, where, default: str | None = None) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and where(c)]
        if len(found) > 1 or (not found and default is None):
            raise EvidenceError("site_report_claim_missing")
        return found[0] if found else default

    def at(statement: str, path: str) -> str:
        return value(statement, lambda c: c["field_path"] == path)

    structure = manifest["structure"]
    snapshot_set = manifest["snapshot_set"]
    snapshot = manifest["snapshot"]
    active = snapshot["active_set_hash"]
    lines = ["# 참조 부위 주석 보고서 (reference site annotation)", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             (f"Structure: {_md(structure['handle'])} ({_md(structure['structure_kind'])}, "
              f"model {_md(structure['model_number'])})"),
             f"Numbering map: {_md(manifest['numbering_map'])}",
             f"Site set: {_md(manifest['site_set']['id'])}",
             (f"Reference snapshot set of the numbering map: {_md(snapshot_set['set_hash'])} "
              f"(object {_md(manifest['reference_set_handle'])})"),
             f"Active reference set at report creation: {_md(active) if active is not None else 'none (null)'}",
             ("Earlier snapshot basis (the map's set is not the active set at report creation): "
              f"{'yes' if snapshot['stale_snapshot'] else 'no'}"),
             "", f"**{_md(manifest['reference_statement'])}**", "", "## 참조 스냅샷", "",
             "| 출처 | 버전 | 날짜 | 스냅샷 ID | 라이선스 | 가공 |", "| --- | --- | --- | --- | --- | --- |"]
    for source in snapshot_set["sources"]:
        version = source["version_hint"] if source["version_hint"] is not None else "none (null)"
        license_text = manifest["klifs_terms"] if source["source"] == "klifs" else source["license"]
        lines.append(f"| {_md(nr.SOURCE_LABELS.get(source['source'], source['source']))} | {_md(version)} | "
                     f"{_md(source['date'])} | {_md(source['snapshot_id'])} | {_md(license_text)} | "
                     f"{_md(nr.PROCESSED_LABEL)} |")
    lines.extend(["", f"- KLIFS: {_md(manifest['klifs_terms'])}. KLIFS 값에는 이 표시가 함께 붙는다.",
                  f"- Origin: {_md(snapshot_set['origin'])}", "", "## 기하 접촉 결과", ""])
    record = manifest["contacts"]
    if record is None:
        lines.append(f"- {NO_CONTACTS}: 이 주석은 기하 접촉 결과 없이 만들었다. 부위별 접촉 개수와 거리는 없다.")
    else:
        lines.extend([f"- Contact result: {_md(record['handle'])}",
                      f"- Ligand instance: {_md(_ref(record['ligand']))}",
                      f"- Cutoff: {_md(record['cutoff_A'])} Å",
                      f"- Computed contact types: {_md(', '.join(record['types']))}"])
        lines.extend(f"- {_md(t)}: {'계산함' if t in record['types'] else NOT_COMPUTED}" for t in sa.CONTACT_TYPES)
        lines.append(f"- {MIN_MEANING}")
    lines.extend(["", "## 부위 수 (ProtView 계산: count\\_kind(groups.sites.status))", ""])
    for status in sa.STATUSES:
        lines.append(f"- {STATUS_KO[status]} ({status}): "
                     f"{value('site_status_count', lambda c, s=status: c['row_selector'] == {'status': s})}")
    for reason in sa.ABSENT_REASONS:
        lines.append(f"- {ABSENT_KO[reason]} ({_md(reason)}): "
                     f"{value('site_absent_reason_count', lambda c, r=reason: c['row_selector'] == {'absent_reason': r})}")
    if manifest["null_result"]:
        lines.append("- " + _md("No site is annotated in any group; this is a valid empty result (scientific_null), "
                                "not a failure."))
    for group in manifest["groups"]:
        accession = group["accession"]
        heading = (value("reference_accession", lambda c, g=group: c["subject"].get("klifs_index") is None and
                         c["row_selector"].get("chain_auth") == g["chain_auth"] and c["exact_value"] == g["accession"])
                   if accession is not None else "none (null)")
        state = ("applied" if group["klifs_applied"] else
                 f"not applied ({GROUP_KO[group['klifs_absent_reason']]} ({_md(group['klifs_absent_reason'])}))")
        lines.extend(["", f"## Chain {_md(group['chain_auth'])} · accession {_md(heading)}", "",
                      f"- KLIFS: {state}",
                      f"- Accession, KLIFS numbers, residues and UniProt positions: {REFERENCE_NOTE}", "",
                      ("| KLIFS | 상태 | 없음 이유 | 이름표 | 잔기 (auth and label) | UniProt accession | "
                       "UniProt position | contact | polar\\_contact | hydrophobic\\_contact | 최소 거리 (Å) |"),
                      "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"])
        for site in group["sites"]:
            if site["status"] == "annotated":
                index = site["map_row_index"]
                label = at("reference_klifs_label", f"rows[{index}].klifs_label")
                reference = [_md(site["display_label"]), _md(at("reference_site_residue", f"rows[{index}].residue")),
                             _md(at("reference_accession", f"rows[{index}].uniprot_accession")),
                             at("reference_uniprot_position", f"rows[{index}].uniprot_position")]
                reason = NOT_APPLICABLE
            else:
                label = site["klifs_label"]
                reference = [NOT_APPLICABLE] * 4
                reason = f"{ABSENT_KO[site['absent_reason']]} ({_md(site['absent_reason'])})"
            cells = [_md(label), f"{STATUS_KO[site['status']]} ({site['status']})", reason, *reference,
                     *_contact_cells(manifest, site, value)]
            lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, evidence kinds and field paths are in the JSON download "
                   f"({len(claims)} claims)."), ""])
    return check_no_interpretation("\n".join(lines))


def build_site_annotation_report(run: Any, result_handle: str, *, active_set_hash: str | None) -> dict[str, Any]:
    """New report object; ``active_set_hash`` is the active reference set at creation (None when unusable)."""
    if active_set_hash is not None and (type(active_set_hash) is not str or not HEX64.fullmatch(active_set_hash)):
        raise EvidenceError("site_report_active_set_invalid")
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot(),
                                "active_set_hash": active_set_hash,
                                "stale_snapshot": active_set_hash != manifest["snapshot_set"]["set_hash"]}
        markdown = render_site_annotation_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("site_report_too_large")
        produced_by = f"site_annotation_report_{uuid.uuid4().hex}"
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


def saved_site_annotation_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored site annotation report without re-running the annotation, mapping or contacts."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("site_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("site_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("site_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"site_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["annotation"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["budget"]) is not dict or
            (snapshot["active_set_hash"] is not None and (type(snapshot["active_set_hash"]) is not str or
                                                          not HEX64.fullmatch(snapshot["active_set_hash"]))) or
            snapshot["stale_snapshot"] is not (snapshot["active_set_hash"] != expected["snapshot_set"]["set_hash"])):
        raise EvidenceError("site_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("site_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("site_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("site_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_site_annotation_report(report):
        raise EvidenceError("site_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
