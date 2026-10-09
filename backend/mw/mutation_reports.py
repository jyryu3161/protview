"""Immutable, field-cited reports for ``mutation_candidate_set@1`` (``method_report_manifest@1``,
``analysis_type: "mutation_candidates"``, render ``mutation_candidates_markdown@1``; spec M20 section 9).

The input is one candidate set handle. Every claim cites the stored set (``source_handle`` = the set) and is one of
two evidence kinds, kept apart as in the M15/M16 reports:

- ``computed`` -- counts over the stored position / candidate rows (positions, positions by status, released
  positions, candidates, positions by exclusion reason, positions by source kind, positions by numbering status), the
  minimum of the stored ``ligand_min_distance_A`` over all positions (only when a ligand was given and positions exist;
  cites the first position holding that minimum, rendered ``Decimal(str(v))`` to 0.01 with ``ROUND_HALF_UP``), the
  status of each protection check, and the stored check counts. A check that was not done (``klifs_key_sites``
  ``not_checked``) gets a "검사하지 않음" status claim and no number; the catalytic residue database is "사용할 수
  없음" and has no number.
- ``reference_value`` -- values the set copied from reference objects: the distinct UniProt accessions of the
  positions (from the numbering map rows) and the distinct KLIFS site labels of protected positions (from the
  annotation). Each claim carries the note "참조 스냅샷 값, 계산 아님" and the reference object handle.

The report has no per-position table (the rows are in the stored object). Creating, reopening and downloading never
regenerate candidates: the stored set is re-validated (``mutation_candidates.validated_set``), the numbering map,
annotation and pocket set it names are checked to be the same structure and their copied values / site counts are
compared with the stored objects, every manifest field and claim is compared, and the Markdown is compared byte for
byte with a re-render. The renderer refuses interpretive wording on every line except the fixed limitation sentences
(matched exactly; sentence 2 contains "안정성·결합·활성" and "순위나 추천"; the M26 third-sentence variants are fixed too).

M26 v2 sets (spec 8.5) add a catalytic part, and only v2 sets do: a v1 set's manifest, claims and Markdown are the
v1 bytes. For v2 the catalytic check status is a status claim; when it is ``checked`` the covered chain count and the
``matched`` / ``conflict`` / ``unmatched`` row counts are computed claims, and a ``not_checked`` check has the status
claim only (no number). The ``catalytic_residue`` exclusion count is a claim only when the check covered a chain; with
no covered chain (no annotation, or none covered) the stored 0 counts nothing and its line has no number. The
distinct M-CSA entry IDs of the positions' ``protection.catalytic`` are reference values citing the
``reaction_knowledge@1`` result. Creating and reopening re-validate that result
(``reaction_knowledge.validated_result``) and compare the set's catalytic check and every ``protection.catalytic``
with the ones the result gives (``mutation_catalytic_value_mismatch`` otherwise).
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import mutation_candidates as mc
from . import numbering_reports as nr
from . import reaction_knowledge as rk
from . import reaction_knowledge_constants as rkc
from . import site_annotation as sa
from .core.handles import canonical_json
from .mutation_constants import (
    CHECKED,
    EXCLUSION_REASONS,
    EXCLUSION_REASONS_V2,
    KIND,
    LIMITATIONS,
    LIMITATIONS_V2,
    METHOD_VERSION_V2,
    NOT_AVAILABLE,
    NOT_CHECKED,
    NUMBERING_STATUSES,
    POSITION_STATUSES,
    PROTECTION_CHECK_KEYS,
    SCHEMA,
    SOURCE_KINDS,
    TOOL,
)
from .reports import EvidenceError, _md, _provenance, _ref
from .tools.mutations import catalytic_input

ANALYSIS_TYPE = "mutation_candidates"
RENDER_VERSION = "mutation_candidates_markdown@1"
REPORT_BYTES = nr.REPORT_BYTES
REFERENCE_NOTE = nr.REFERENCE_NOTE
POCKET_KIND = ("pocket_set", "pocket_set@1")
CATALYTIC_KIND = (rkc.KIND, rkc.SCHEMA)
FIXED_LIMITATIONS = frozenset(LIMITATIONS) | frozenset(s for v in LIMITATIONS_V2.values() for s in v)
EVIDENCE_STATEMENT = ("ProtView counted the stored position and candidate rows, took the minimum of the stored "
                      "ligand distances, and copied the protection check states. UniProt accessions and KLIFS site "
                      "labels are reference snapshot values (참조 스냅샷 값, 계산 아님) copied into the set, not "
                      "ProtView calculations. No structure was modelled and no candidate was regenerated.")
EVIDENCE_STATEMENT_V2 = ("ProtView counted the stored position and candidate rows and the catalytic annotation rows, "
                         "took the minimum of the stored ligand distances, and copied the protection check states. "
                         "UniProt accessions, KLIFS site labels and M-CSA entry IDs are reference snapshot values "
                         "(참조 스냅샷 값, 계산 아님) copied into the set, not ProtView calculations. No structure was "
                         "modelled and no candidate was regenerated.")

STATUS_KO = {"candidate": "후보 위치", "excluded": "제외 위치"}
REASON_KO = {"non_standard_residue": "비표준 잔기", "user_protected": "사용자 보호",
             "klifs_key_site": "KLIFS 주요 부위", "metal_contact": "금속 근접", "disulfide_cys": "이황화 Cys",
             "catalytic_residue": "M-CSA 촉매 잔기 주석", "no_allowed_alternative": "허용 목록에 바꿀 잔기 없음"}
SOURCE_KO = {"pocket": "포켓", "ligand_shell": "리간드 껍질", "user": "직접 선택"}
NUMBERING_KO = {"mapped": "대응됨", "unmapped": "대응 안 됨", "conflict": "충돌", "not_in_map": "지도에 없음"}
CHECK_KO = {"user_list": "사용자 보호·해제 목록", "klifs_key_sites": "KLIFS 주요 부위",
            "metal_contact": "금속 근접", "disulfide": "이황화 Cys SG–SG",
            "catalytic_residue_database": "촉매 잔기 데이터베이스"}
CHECK_STATUS_KO = {CHECKED: "검사함", NOT_CHECKED: "검사하지 않음", NOT_AVAILABLE: "사용할 수 없음"}
CHECK_REASON_KO = {"annotation_not_given": "주석을 주지 않음", "not_implemented": "구현하지 않음",
                   "chains_not_covered": "위치가 있는 체인을 M-CSA 주석이 모두 다루지는 않음"}
COVERAGE_KO = {"chain_not_listed": "체인이 M-CSA 행에 없음", "pdb_not_in_snapshot": "PDB가 스냅샷에 없음",
               "not_checked": "M-CSA 절을 검사하지 않음", "not_in_annotation": "결과에 체인이 없음"}
NOT_GIVEN = "주지 않음"
NOT_COMPUTED = "계산하지 않음"

EVIDENCE_KINDS = ("computed", "reference_value")
_COUNT_FIELDS = ("user_list.protected", "user_list.released", "klifs_key_sites.annotated_sites",
                 "klifs_key_sites.absent_sites", "metal_contact.metal_residues", "disulfide.pairs",
                 # v2 only (a v1 catalytic check is not_available and never has these numbers)
                 "catalytic_residue_database.matched_rows", "catalytic_residue_database.conflict_rows",
                 "catalytic_residue_database.unmatched_rows")
# statement ID -> (evidence kind, field path rule); fixed template, nothing else carries a number in this report.
STATEMENTS = {
    "position_count": ("computed", re.compile(r"positions\[\*\]")),
    "position_status_count": ("computed", re.compile(r"positions\[\*\]\.status")),
    "released_position_count": ("computed", re.compile(r"positions\[\*\]\.protection\.released")),
    "candidate_count": ("computed", re.compile(r"candidates\[\*\]")),
    "exclusion_reason_count": ("computed", re.compile(r"positions\[\*\]\.exclusion_reasons")),
    "source_position_count": ("computed", re.compile(r"positions\[\*\]\.sources\.kind")),
    "numbering_status_count": ("computed", re.compile(r"positions\[\*\]\.numbering\.status")),
    "ligand_min_distance_A": ("computed", re.compile(r"positions\[\d+\]\.ligand_min_distance_A")),
    "protection_check_status": ("computed", re.compile(
        r"protection_checks\.(" + "|".join(PROTECTION_CHECK_KEYS) + r")\.status")),
    "protection_check_count": ("computed", re.compile(
        r"protection_checks\.(" + "|".join(re.escape(f) for f in _COUNT_FIELDS) + r")")),
    "reference_uniprot_accession": ("reference_value", re.compile(r"positions\[\d+\]\.numbering\.uniprot_accession")),
    "reference_klifs_site_label": ("reference_value", re.compile(r"positions\[\d+\]\.protection\.klifs_sites\[\d+\]")),
    # M26 v2
    "catalytic_covered_chain_count": ("computed", re.compile(
        r"protection_checks\.catalytic_residue_database\.covered_chains")),
    "reference_mcsa_entry_id": ("reference_value", re.compile(
        r"positions\[\d+\]\.protection\.catalytic\[\d+\]\.mcsa_id")),
}
REFERENCE_FIELDS = re.compile(r"positions\[\d+\]\.(numbering\.(uniprot_accession|uniprot_position|uniprot_residue|"
                              r"klifs_index|klifs_label)|protection\.klifs_sites\[\d+\]|"
                              r"protection\.catalytic\[\d+\]\.(mcsa_id|residue_index|is_reference))")
CLAIM_KEYS = nr.CLAIM_KEYS
# M15 interpretive wording plus the M20 list (spec 9). "촉매" is not listed: the report must state that the catalytic
# residue database is unavailable. Handles are lowercase hex, so none of these words can occur inside one.
INTERPRETIVE = re.compile(
    nr.INTERPRETIVE.pattern + r"|안정성|ΔΔG|ddG|delta\s*delta|순위|추천|최적|개선|활성|예측|유망|좋은|나쁜|안전|"
    r"점수|에너지|수소\s*결합|\brank|\bbest\b|recommend|optimal|improv|predict|promising|\bgood\b|\bsafe|"
    r"\bactiv(e|ity)\b|\bscor(e|ing)\b|energ|hydrogen[\s_-]?bond|\bh-?bond", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget"}
COPIED_FIELDS = ("method_version", "structure", "parameters", "ligand", "pockets", "protection_checks",
                 "released_residues", "counts", "null_result", "limitations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "claims", "provenance", "evidence_statement", "snapshot", "markdown_handle"})


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_distance(value: Any) -> str:
    """Å with two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68)."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("mutation_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


def _render(value: Any, rounding: str) -> str:
    if rounding == "distance_2dp":
        return render_distance(value)
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("mutation_claim_integer_expected")
        return str(value)
    if rounding == "check_status":
        if value not in CHECK_STATUS_KO:
            raise EvidenceError("mutation_claim_value_type")
        return f"{CHECK_STATUS_KO[value]} ({value})"
    if rounding == "verbatim":
        if type(value) is not str:
            raise EvidenceError("mutation_claim_value_type")
        return value
    raise EvidenceError("mutation_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the five fixed limitation sentences."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"mutation_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects only; nothing is recomputed from coordinates)

def _source(run: Any, handle: str, kind: tuple[str, str], error: str) -> dict[str, Any]:
    meta = run.store.meta(handle)
    if (meta["kind"], meta["schema"]) != kind:
        raise EvidenceError(error)
    return run.store.load(handle)


def check_sources(content: dict[str, Any], map_content: dict[str, Any] | None,
                  annotation: dict[str, Any] | None, pocket_content: dict[str, Any] | None,
                  catalytic_result: dict[str, Any] | None = None) -> None:
    """The validated set against the stored map, annotation and pocket set it names; raises ``EvidenceError``.

    Same structure for each; the copied numbering values equal the map row of the same residue (7 fields) or
    ``not_in_map``; the KLIFS site counts and each position's site labels equal the stored annotation's sites. For a
    v2 set with a ``catalytic_annotation``, the stored ``reaction_knowledge@1`` result must pass
    ``reaction_knowledge.validated_result``, be of the same structure, and give exactly the set's catalytic check
    (covered / uncovered chains, row counts, conflict and unmatched lists) and every ``protection.catalytic``.
    """
    try:
        structure = content["structure"]["handle"]
        parameters = content["parameters"]
        if (map_content is None) is not (parameters["numbering_map"] is None) or \
                (annotation is None) is not (parameters["annotation"] is None) or \
                (pocket_content is None) is not (parameters["sources"]["pocket"] is None):
            raise EvidenceError("mutation_sources_missing")
        if map_content is not None:
            if map_content["structure"]["handle"] != structure:
                raise EvidenceError("mutation_numbering_map_structure_mismatch")
            rows = {mc.identity(row["residue"]): row for row in map_content["rows"]}
            for position in content["positions"]:
                row = rows.get(mc.identity(position["residue"]))
                expected = ({"status": "not_in_map", **dict.fromkeys(mc.NUMBERING_FIELDS)} if row is None else
                            {"status": row["status"], **{field: row[field] for field in mc.NUMBERING_FIELDS}})
                if canonical_json(position["numbering"]) != canonical_json(expected):
                    raise EvidenceError("mutation_numbering_value_mismatch")
        if annotation is not None:
            if annotation["structure"]["handle"] != structure:
                raise EvidenceError("mutation_annotation_structure_mismatch")
            if parameters["numbering_map"] is not None and annotation["numbering_map"] != parameters["numbering_map"]:
                raise EvidenceError("mutation_annotation_map_mismatch")
            labels, annotated, absent = mc._klifs_sites(annotation)
            checks = content["protection_checks"]["klifs_key_sites"]
            if (checks["annotated_sites"], checks["absent_sites"]) != (annotated, absent):
                raise EvidenceError("mutation_klifs_site_count_mismatch")
            for position in content["positions"]:
                if position["protection"]["klifs_sites"] != labels.get(mc.identity(position["residue"]), []):
                    raise EvidenceError("mutation_klifs_site_label_mismatch")
        if pocket_content is not None and pocket_content["source_handle"] != structure:
            raise EvidenceError("mutation_pocket_set_structure_mismatch")
        catalytic_handle = parameters.get("catalytic_annotation")   # a v1 set has no such parameter
        if (catalytic_result is None) is not (catalytic_handle is None):
            raise EvidenceError("mutation_sources_missing")
        if catalytic_result is not None:
            _check_catalytic(content, catalytic_result, catalytic_handle)
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_sources_unresolved") from exc


def _check_catalytic(content: dict[str, Any], result: dict[str, Any], handle: str) -> None:
    try:
        rk.validated_result(result)
    except rk.ResultInvalid as exc:
        raise EvidenceError("mutation_catalytic_annotation_invalid") from exc
    if result["structure"]["handle"] != content["structure"]["handle"]:
        raise EvidenceError("mutation_catalytic_annotation_structure_mismatch")
    positions = content["positions"]
    try:
        lists, check = mc.catalytic_protection([p["residue"] for p in positions], catalytic_input(result), handle)
    except mc.MutationInvalid as exc:
        raise EvidenceError("mutation_catalytic_value_mismatch") from exc
    if canonical_json(check) != canonical_json(content["protection_checks"]["catalytic_residue_database"]) or any(
            canonical_json(found) != canonical_json(p["protection"]["catalytic"])
            for found, p in zip(lists, positions, strict=True)):
        raise EvidenceError("mutation_catalytic_value_mismatch")


def validated_mutation_set(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a stored candidate set produced by the tool and the stored objects it names; (content, provenance)."""
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (KIND, SCHEMA):
            raise EvidenceError("wrong_result_kind")
        try:
            content = mc.validated_set(run.store.load(handle))
        except mc.MutationSetInvalid as exc:
            raise EvidenceError(f"mutation_candidate_set_invalid: {exc}") from exc
        provenance = _provenance(list(run.events.read()), handle, expected_tool=TOOL)
        parameters = content["parameters"]
        pocket = parameters["sources"]["pocket"]
        check_sources(
            content,
            None if parameters["numbering_map"] is None else
            _source(run, parameters["numbering_map"], (nr.rn.KIND, nr.rn.SCHEMA), "mutation_numbering_map_kind"),
            None if parameters["annotation"] is None else
            _source(run, parameters["annotation"], (sa.KIND, sa.SCHEMA), "mutation_annotation_kind"),
            None if pocket is None else _source(run, pocket["pocket_set"], POCKET_KIND, "mutation_pocket_set_kind"),
            None if parameters.get("catalytic_annotation") is None else
            _source(run, parameters["catalytic_annotation"], CATALYTIC_KIND, "mutation_catalytic_annotation_kind"))
        return content, provenance
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None,
           reference: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": STATEMENTS[statement_id][0], "source_handle": handle,
            "source_kind": KIND, "source_schema": SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation, "reference": reference}


def _row_selector(index: int, row: dict[str, Any]) -> dict[str, Any]:
    return {"row_index": index, "row_sha256": hashlib.sha256(canonical_json({"index": index, "row": row})).hexdigest()}


def counted_reason(reason: str, checks: dict[str, Any]) -> bool:
    """Whether the report counts the positions of one exclusion reason. ``catalytic_residue`` (v2 only) is counted only
    where the catalytic check covered a chain: with no covered chain (no annotation, or ``chains_not_covered`` with none
    covered) the stored 0 counts nothing, so there is no claim and the line is "—" with the reason (never 0)."""
    return reason != "catalytic_residue" or bool(checks["catalytic_residue_database"].get("covered_chains"))


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; each count is recounted from the stored rows."""
    positions, candidates = content["positions"], content["candidates"]
    parameters, checks = content["parameters"], content["protection_checks"]
    subject = {"candidate_set_handle": handle}
    v2 = content["method_version"] == METHOD_VERSION_V2

    def count(statement: str, path: str, selector: dict[str, Any] | None, quantity: str, value: int,
              condition: str) -> dict[str, Any]:
        return _claim(statement, handle, path, selector, subject, quantity, "count", value, "integer",
                      f"count_where({condition}; stored rows)" if selector is not None else f"count({path})")

    claims = [count("position_count", "positions[*]", None, "positions", len(positions), "")]
    claims.extend(count("position_status_count", "positions[*].status", {"status": status}, f"{status}_positions",
                        sum(p["status"] == status for p in positions), f"status == {status}")
                  for status in POSITION_STATUSES)
    claims.append(count("released_position_count", "positions[*].protection.released", {"released": True},
                        "released_positions", sum(p["protection"]["released"] is True for p in positions),
                        "protection.released == true"))
    claims.append(count("candidate_count", "candidates[*]", None, "candidates", len(candidates), ""))
    claims.extend(count("exclusion_reason_count", "positions[*].exclusion_reasons", {"exclusion_reason": reason},
                        f"{reason}_positions", sum(reason in p["exclusion_reasons"] for p in positions),
                        f"{reason} in exclusion_reasons") for reason in (EXCLUSION_REASONS_V2 if v2
                                                                         else EXCLUSION_REASONS)
                  if counted_reason(reason, checks))
    claims.extend(count("source_position_count", "positions[*].sources.kind", {"source": kind}, f"{kind}_positions",
                        sum(any(s["kind"] == kind for s in p["sources"]) for p in positions),
                        f"any sources.kind == {kind}") for kind in SOURCE_KINDS)
    if parameters["numbering_map"] is not None:
        claims.extend(count("numbering_status_count", "positions[*].numbering.status", {"numbering_status": status},
                            f"numbering_{status}_positions",
                            sum(p["numbering"]["status"] == status for p in positions), f"numbering.status == {status}")
                      for status in NUMBERING_STATUSES)
    measured = [(p["ligand_min_distance_A"], p["index"]) for p in positions if p["ligand_min_distance_A"] is not None]
    if content["ligand"] is not None and measured:
        low, index = min(measured)
        claims.append(_claim("ligand_min_distance_A", handle, f"positions[{index}].ligand_min_distance_A",
                             _row_selector(index, positions[index]),
                             {**subject, "ligand": content["ligand"]["residue"],
                              "residue": positions[index]["residue"]},
                             "min_ligand_min_distance_A", "angstrom", low, "distance_2dp",
                             "minimum(positions[*].ligand_min_distance_A; first position on ties)"))
    for key in PROTECTION_CHECK_KEYS:
        claims.append(_claim("protection_check_status", handle, f"protection_checks.{key}.status", {"check": key},
                             subject, f"{key}_status", "status", checks[key]["status"], "check_status", None))
    for field in _COUNT_FIELDS:
        key, name = field.split(".")
        if checks[key]["status"] != CHECKED:
            continue   # a check that was not done has no number (never 0)
        claims.append(_claim("protection_check_count", handle, f"protection_checks.{field}", {"check": key},
                             subject, f"{key}_{name}", "count", checks[key][name], "integer", None))
    catalytic = checks["catalytic_residue_database"]
    if v2 and catalytic["status"] == CHECKED:   # a not_checked catalytic check has the status claim only
        path = "protection_checks.catalytic_residue_database.covered_chains"
        claims.append(_claim("catalytic_covered_chain_count", handle, path, {"check": "catalytic_residue_database"},
                             subject, "catalytic_residue_database_covered_chains", "count",
                             len(catalytic["covered_chains"]), "integer", f"count({path})"))
    if parameters["numbering_map"] is not None:
        reference = {"note": REFERENCE_NOTE, "reference_object": parameters["numbering_map"]}
        seen: set[str] = set()
        for position in positions:
            accession = position["numbering"]["uniprot_accession"]
            if accession is None or accession in seen:
                continue
            seen.add(accession)
            i = position["index"]
            claims.append(_claim("reference_uniprot_accession", handle, f"positions[{i}].numbering.uniprot_accession",
                                 _row_selector(i, position), {**subject, "residue": position["residue"]},
                                 "uniprot_accession", "identifier", accession, "verbatim", None, reference))
    if parameters["annotation"] is not None:
        reference = {"note": REFERENCE_NOTE, "reference_object": parameters["annotation"]}
        seen = set()
        for position in positions:
            for j, label in enumerate(position["protection"]["klifs_sites"]):
                if label in seen:
                    continue
                seen.add(label)
                i = position["index"]
                claims.append(_claim("reference_klifs_site_label", handle,
                                     f"positions[{i}].protection.klifs_sites[{j}]", _row_selector(i, position),
                                     {**subject, "residue": position["residue"]}, "klifs_label", "identifier",
                                     label, "verbatim", None, reference))
    if v2 and parameters["catalytic_annotation"] is not None:
        reference = {"note": REFERENCE_NOTE, "reference_object": parameters["catalytic_annotation"]}
        seen_ids: set[tuple[int, bool]] = set()
        for position in positions:
            released = position["protection"]["released"]
            for j, entry in enumerate(position["protection"]["catalytic"] or []):
                if (entry["mcsa_id"], released) in seen_ids:
                    continue
                seen_ids.add((entry["mcsa_id"], released))
                i = position["index"]
                claims.append(_claim("reference_mcsa_entry_id", handle,
                                     f"positions[{i}].protection.catalytic[{j}].mcsa_id", _row_selector(i, position),
                                     {**subject, "residue": position["residue"], "released": released},
                                     "mcsa_entry_id", "identifier", entry["mcsa_id"], "integer", None, reference))
    return claims


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim built from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("mutation_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("mutation_claim_statement_not_allowed")
    kind, rule = STATEMENTS[statement]
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["evidence_kind"] != kind:
        raise EvidenceError("mutation_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str:
        raise EvidenceError("mutation_claim_shape")
    if kind == "computed":
        if REFERENCE_FIELDS.fullmatch(path):
            raise EvidenceError("mutation_claim_reference_field_as_computed")
        if not rule.fullmatch(path) or proposed["reference"] is not None:
            raise EvidenceError("mutation_claim_computed_field_rule")
    else:
        reference = proposed["reference"]
        if not rule.fullmatch(path) or type(reference) is not dict or reference.get("note") != REFERENCE_NOTE:
            raise EvidenceError("mutation_claim_reference_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (KIND, SCHEMA):
        raise EvidenceError("mutation_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("mutation_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("mutation_claim_shape") from exc
    if match is None:
        raise EvidenceError("mutation_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("mutation_claim_binding_mismatch")
    return proposed


def validate_mutation_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored set (not snapshot / markdown handle)."""
    content, provenance = validated_mutation_set(run, handle)
    try:
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS},
                "claims": claims_for(handle, content),
                "provenance": {key: provenance[key] for key in ("call_id", "tool", "tool_version",
                                                                "created_event_seq", "completed_event_seq")},
                "evidence_statement": (EVIDENCE_STATEMENT_V2 if content["method_version"] == METHOD_VERSION_V2
                                       else EVIDENCE_STATEMENT)}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_report_evidence_unresolved") from exc


_SLOT = re.compile("\x00(\\d+)\x00")


def render_mutation_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim.

    Interpolated identifiers and values (handles, chain IDs, CCD codes, accessions, KLIFS labels, numbers) go into
    slots; the forbidden-word check runs on the fixed template text with the slots left empty, then the slots are
    filled. A chain "BEST" or a CCD code therefore cannot fail a report, and the template can never say a forbidden
    word.
    """
    claims = manifest["claims"]
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def rendered(statement: str, selector: dict[str, Any] | None = None, path: str | None = None) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (selector is None or c["row_selector"] == selector) and (path is None or c["field_path"] == path)]
        if len(found) != 1:
            raise EvidenceError("mutation_report_claim_missing")
        return found[0]

    def value(statement: str, selector: dict[str, Any] | None = None, path: str | None = None) -> str:
        return slot(rendered(statement, selector, path))

    structure, parameters = manifest["structure"], manifest["parameters"]
    sources, ligand, checks = parameters["sources"], manifest["ligand"], manifest["protection_checks"]
    pocket, shell = sources["pocket"], sources["ligand_shell"]
    v2 = manifest["method_version"] == METHOD_VERSION_V2
    catalytic_given = parameters.get("catalytic_annotation")   # v2 only
    lines = ["# 변이 후보 보고서 (mutation candidates)", "", "Status: complete", "",
             f"Result: {md(manifest['result_handle'])}",
             (f"Structure: {md(structure['handle'])} ({md(structure['structure_kind'])}, "
              f"model {md(structure['model_number'])})"),
             f"Method: {md(manifest['method_version'])}", "", f"**{_md(manifest['evidence_statement'])}**", "",
             "## 요청 (입력 값, 계산 아님)", "",
             (f"- 포켓 출처: {md(pocket['pocket_set'])}, 순번 {md(', '.join(str(r) for r in pocket['ranks']))}"
              if pocket is not None else f"- 포켓 출처: {NOT_GIVEN}"),
             (f"- 리간드 껍질 반경: {md(shell['radius_A'])} Å" if shell is not None else
              f"- 리간드 껍질 출처: {NOT_GIVEN}"),
             f"- 리간드: {md(_ref(ligand['residue'])) if ligand is not None else NOT_GIVEN}",
             f"- 허용 잔기: {md(parameters['allowed_residues'])}",
             f"- 금속 근접 기준: {md(parameters['metal_contact_A'])} Å",
             f"- 이황화 Cys SG–SG 기준: {md(parameters['disulfide_sg_A'])} Å",
             f"- 번호 대응: {md(parameters['numbering_map']) if parameters['numbering_map'] else NOT_GIVEN}",
             f"- 주석: {md(parameters['annotation']) if parameters['annotation'] else NOT_GIVEN}",
             *([f"- 촉매 잔기 주석: {md(catalytic_given) if catalytic_given else NOT_GIVEN}"] if v2 else []),
             "", "## 위치와 후보 수 (ProtView 계산: 저장된 행의 개수)", "",
             f"- 위치 (positions): {value('position_count')}"]
    for status in POSITION_STATUSES:
        lines.append(f"- {STATUS_KO[status]} ({status}): {value('position_status_count', {'status': status})}")
    lines.append(f"- 보호 해제된 위치 (released): {value('released_position_count')}")
    lines.append(f"- 후보 (candidates): {value('candidate_count')}")
    if manifest["null_result"]:
        lines.append("- 후보가 없다. 유효한 빈 과학 결과(scientific\\_null)이며 실패가 아니다. 제외 사유별 위치 수는 "
                     "아래와 같다.")
    lines.extend(["", "## 제외 사유별 위치 수", ""])
    for reason in (EXCLUSION_REASONS_V2 if v2 else EXCLUSION_REASONS):
        if not counted_reason(reason, checks):   # no chain covered: no number, never 0
            why = checks["catalytic_residue_database"]["reason"]
            lines.append(f"- {REASON_KO[reason]} ({md(reason)}): — (촉매 잔기 검사 안 함: {CHECK_REASON_KO[why]} "
                         f"({md(why)}). M-CSA가 다룬 체인이 없어 이 사유의 위치를 세지 않았다)")
            continue
        note = (" — 촉매 잔기 검사 안 함(검사하지 않은 위치는 세지 않았다)"
                if reason == "catalytic_residue" and checks["catalytic_residue_database"]["status"] != CHECKED else "")
        lines.append(f"- {REASON_KO[reason]} ({md(reason)}): "
                     f"{value('exclusion_reason_count', {'exclusion_reason': reason})}{note}")
    lines.extend(["", "## 출처별 위치 수", ""])
    for kind in SOURCE_KINDS:
        lines.append(f"- {SOURCE_KO[kind]} ({md(kind)}): {value('source_position_count', {'source': kind})}")
    lines.extend(["", "## 리간드까지 최소 거리", ""])
    distance = [c for c in claims if c["statement_id"] == "ligand_min_distance_A"]
    if ligand is None:
        lines.append(f"- {NOT_COMPUTED}: 리간드를 주지 않아 위치별 거리가 없다.")
    elif not distance:
        lines.append(f"- {NOT_COMPUTED}: 거리가 있는 위치가 없다.")
    else:
        claim = distance[0]
        lines.append(f"- 모든 위치의 ligand\\_min\\_distance\\_A 최솟값: {value('ligand_min_distance_A')} Å "
                     f"({md(_ref(claim['subject']['residue']))})")
    lines.extend(["", "## 보호 검사", "", "| 검사 | 상태 | 세부 |", "| --- | --- | --- |"])
    for key in PROTECTION_CHECK_KEYS:
        check = checks[key]
        status = rendered("protection_check_status", {"check": key})

        def number(field: str, key: str = key) -> str:
            return value("protection_check_count", {"check": key}, f"protection_checks.{key}.{field}")

        if key == "user_list":
            detail = f"보호 목록 {number('protected')}, 해제 목록 {number('released')}"
        elif key == "klifs_key_sites":
            detail = (f"주석 {md(check['annotation'])}, 주석된 부위 {number('annotated_sites')}, "
                      f"없는 부위 {number('absent_sites')}" if check["status"] == CHECKED else
                      f"이유: {CHECK_REASON_KO[check['reason']]} ({md(check['reason'])}). 보호 여부를 판정하지 않았다.")
        elif key == "metal_contact":
            names = ", ".join(check["metal_names"]) if check["metal_names"] else "none"
            detail = (f"기준 {md(check['threshold_A'])} Å, 금속 잔기 {number('metal_residues')} "
                      f"({md(names)})")
        elif key == "disulfide":
            detail = f"기준 {md(check['threshold_A'])} Å, SG–SG 쌍 {number('pairs')}"
        elif v2:
            detail = _catalytic_detail(check, md, value, number)
        else:
            detail = f"이유: {CHECK_REASON_KO[check['reason']]} ({md(check['reason'])}). 촉매 잔기를 판정하지 않았다."
        lines.append(f"| {CHECK_KO[key]} ({md(key)}) | {md(status)} | {detail} |")
    lines.extend(["", "## 번호 대응 (참조 스냅샷 값, 계산 아님)", ""])
    if parameters["numbering_map"] is None:
        lines.append(f"- 번호 대응: {NOT_GIVEN}. 위치별 UniProt·KLIFS 번호가 없다.")
    else:
        for status in NUMBERING_STATUSES:
            lines.append(f"- {NUMBERING_KO[status]} ({md(status)}) 위치 (ProtView 계산): "
                         f"{value('numbering_status_count', {'numbering_status': status})}")
        accessions = [c["rendered_value"] for c in claims if c["statement_id"] == "reference_uniprot_accession"]
        lines.append(f"- UniProt accession ({REFERENCE_NOTE}): "
                     f"{md(', '.join(accessions)) if accessions else 'none (null)'}")
    if parameters["annotation"] is not None:
        labels = [c["rendered_value"] for c in claims if c["statement_id"] == "reference_klifs_site_label"]
        lines.append(f"- 보호된 위치의 KLIFS 주요 부위 이름표 ({REFERENCE_NOTE}): "
                     f"{md(', '.join(labels)) if labels else 'none'}")
    if v2:
        lines.extend(["", f"## M-CSA 촉매 잔기 주석 ({REFERENCE_NOTE})", ""])
        lines.extend(_catalytic_reference_lines(parameters, checks["catalytic_residue_database"], claims, md))
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, evidence kinds and field paths are in the JSON download "
                   f"({len(claims)} claims). Position and candidate rows are in the stored result."), ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


def _catalytic_detail(check: dict[str, Any], md: Any, value: Any, number: Any) -> str:
    """The v2 catalytic row of the protection-check table: numbers only when the check is ``checked``."""
    reason = check["reason"]
    if check["annotation"] is None:
        return f"이유: {CHECK_REASON_KO[reason]} ({md(reason)}). 촉매 잔기 보호를 판정하지 않았다."
    if check["status"] == CHECKED:
        return (f"주석 {md(check['annotation'])}, 검사한 체인 {value('catalytic_covered_chain_count')} "
                f"({md(', '.join(check['covered_chains']))}), 대응됨 행 {number('matched_rows')}, 충돌 행 "
                f"{number('conflict_rows')}, 대응 없음 행 {number('unmatched_rows')}. 충돌·대응 없음 행은 보호에 쓰지 "
                "않았고 행 목록은 저장된 결과에 있다.")
    parts = [f"주석 {md(check['annotation'])}. 이유: {CHECK_REASON_KO[reason]} ({md(reason)})."]
    if check["covered_chains"]:
        parts.append(f"M-CSA가 다룬 체인: {md(', '.join(check['covered_chains']))} (이 체인의 대응됨 행은 보호에 씀).")
    if check["uncovered_chains"]:
        parts.append("다루지 않은 체인: " + ", ".join(
            f"{md(item['chain_auth'])} ({COVERAGE_KO[item['coverage']]}, {md(item['coverage'])})"
            for item in check["uncovered_chains"]) + ".")
    else:
        parts.append("위치가 없어 촉매 잔기 보호를 판정하지 않았다.")
    parts.append("모든 체인을 검사하지 않았으므로 이 칸에는 개수를 적지 않는다.")
    return " ".join(parts)


def _catalytic_reference_lines(parameters: dict[str, Any], check: dict[str, Any], claims: list[dict[str, Any]],
                               md: Any) -> list[str]:
    if parameters["catalytic_annotation"] is None:
        return [f"- 촉매 잔기 주석: {NOT_GIVEN}. 위치별 M-CSA 항목 ID를 붙이지 않았다."]
    if not check["covered_chains"]:
        return ["- 보호된 위치의 M-CSA 항목 ID: 검사하지 않음 (위치가 있는 체인을 M-CSA 주석이 다루지 않았다)."]
    found = [c for c in claims if c["statement_id"] == "reference_mcsa_entry_id"]
    kept = [c["rendered_value"] for c in found if c["subject"]["released"] is False]
    released = [c["rendered_value"] for c in found if c["subject"]["released"] is True]
    lines = [(f"- M-CSA가 다룬 체인 위치에서 대응된 M-CSA 항목 ID ({REFERENCE_NOTE}, 결과 "
              f"{md(parameters['catalytic_annotation'])}): {md(', '.join(kept)) if kept else 'none'}")]
    if released:
        lines.append(f"- 보호를 해제한 위치의 M-CSA 항목 ID (해제됨, {REFERENCE_NOTE}): {md(', '.join(released))}")
    return lines


def build_mutation_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object from the stored candidate set (no candidate is generated again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot()}
        markdown = render_mutation_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("mutation_report_too_large")
        produced_by = f"mutation_report_{uuid.uuid4().hex}"
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


def saved_mutation_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored mutation candidate report from stored objects only (nothing is regenerated)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("mutation_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("mutation_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("mutation_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"mutation_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["budget"]) is not dict):
        raise EvidenceError("mutation_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("mutation_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("mutation_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("mutation_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_mutation_report(report):
        raise EvidenceError("mutation_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
