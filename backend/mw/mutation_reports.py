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

M28 T3 (report format ``mutation_candidates_markdown@2``): a new report that cites reference values carries the
snapshot source and terms table the M15 / M16 / M26 reports carry. It cites the numbering family when the set names a
numbering map or an annotation (the set of the map; with an annotation alone, the map the annotation names), and the
reaction family when a claim cites an M-CSA entry ID. Each cited set is one manifest entry of
``reference_snapshot_sets``: the M15 ``snapshot_set`` record copied from the numbering map (checked with
``numbering_reports.validated_numbering_map``, which also gives the run's ``reference_snapshot_set@1`` object) with the
KLIFS terms, or the M26 ``snapshot_set`` record copied from the reaction result (validated once with the set). The
Markdown adds one "참조 스냅샷" section before the limitations with the wording and fields of those reports' tables (no
processed-row-count column and no active-set line); every other line is the @1 line. A new report that cites none
keeps the @1 format and bytes, and stored @1 reports reopen with the @1 manifest keys and rendering. Claims, statement
IDs, fixed sentences and the candidate set are the same in both versions.

M29 T8 (report format ``mutation_candidates_markdown@3``, spec .dryforge/spec.md 5.3, 6.3): a new report of a set made
on a repaired structure (``structure_origin_reports.origin``: the manifest ``repair`` key, the record re-validated with
its publication) is @3 and only such a set's report is: the @2 manifest keys (``reference_snapshot_sets`` always
present, the same list as @2, possibly empty, and the "참조 스냅샷" section only when it is not empty) plus
``structure_origin``, the two record-count claims after the @2 claims, and a "구조 출처" section before the limitations
(SO1, plus SO3 when the set uses a pocket set, numbering map, annotation or catalytic annotation made on the original
structure). For @3 only, ``check_sources`` / ``_check_catalytic`` also accept a reference result made on that original
structure (``repair.source``, ``mutation_handoff.reference_structures``); @1 and @2 accept the set's own structure only,
and an @1, @2 manifest for a repaired structure or an @3 one for another structure is refused.

M29 T12 (@3 only, spec 5.3: the report shows the modeled residues as not checked; the stored set is unchanged): one
more computed claim, ``repair_modeled_residue_position_count`` (before the two record-count claims), counts the
positions whose residue is a modeled residue of the repair record (a gap residue or an MSE residue replaced by MET) with
the reads' judgment (``mutation_handoff.modeled_residue_view``); it cites the set's ``positions[*].residue`` with the
record named in its subject and operation, and its subject lists the stored fields that judgment shows as "검사 안
함(모델링 잔기)". The "구조 출처" section gives the count; the numbering section (when ``numbering`` is listed) and the
protection-check section (when ``klifs_sites`` / ``catalytic`` is listed) each add one line saying that the stored
counts and states there include those positions and do not mean they were checked. The fixed sentences SO1-SO3 are
unchanged and @1 / @2 manifests and Markdown are the bytes they were.
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import mutation_candidates as mc
from . import mutation_handoff
from . import numbering_reports as nr
from . import reaction_knowledge as rk
from . import reaction_knowledge_constants as rkc
from . import site_annotation as sa
from . import structure_origin_reports as origin_reports
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
RENDER_VERSION = "mutation_candidates_markdown@1"      # stored reports, and new reports citing no reference value
RENDER_VERSION_V2 = "mutation_candidates_markdown@2"   # M28 T3: new reports citing reference values (source table)
RENDER_VERSION_V3 = "mutation_candidates_markdown@3"   # M29 T8: new reports of a set on a repaired structure
NUMBERING_SET_SCHEMA = "reference_snapshot_set@1"
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
# M29 T12 (@3 only): the positions whose residue is a modeled residue of the repair record (a gap residue or an MSE
# residue replaced by MET), judged as the reads judge them (``mutation_handoff.modeled_residue_view``). Kept apart from
# ``STATEMENTS`` (the M20 statements are unchanged); only an @3 report's expected claims hold it.
MODELED_STATEMENT = "repair_modeled_residue_position_count"
V3_STATEMENTS = {MODELED_STATEMENT: ("computed", re.compile(r"positions\[\*\]\.residue"))}
MODELED_NOT_CHECKED = "검사 안 함(모델링 잔기)"   # the reads' and the screen's wording (SO2 / SO3 vocabulary)
NOT_CHECKED_CHECKS = (("klifs_sites", "klifs_key_sites"), ("catalytic", "catalytic_residue_database"))
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
MANIFEST_KEYS_V2 = MANIFEST_KEYS | {"reference_snapshot_sets"}
MANIFEST_KEYS_V3 = MANIFEST_KEYS_V2 | {"structure_origin"}
MANIFEST_KEYS_BY_VERSION = {RENDER_VERSION: MANIFEST_KEYS, RENDER_VERSION_V2: MANIFEST_KEYS_V2,
                            RENDER_VERSION_V3: MANIFEST_KEYS_V3}


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
    """Refuse interpretive wording on any line that is not exactly one of the fixed limitation sentences or one of the
    M29 structure origin sentences (SO1, SO3)."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS or line in origin_reports.FIXED_LINES:
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
                  catalytic_result: dict[str, Any] | None = None, origin: dict[str, Any] | None = None) -> None:
    """The validated set against the stored map, annotation and pocket set it names; raises ``EvidenceError``.

    Same structure for each (M29: or, with the validated ``origin`` of a set on a repaired structure, its original
    structure ``repair.source``); the copied numbering values equal the map row of the same residue (7 fields) or
    ``not_in_map``; the KLIFS site counts and each position's site labels equal the stored annotation's sites. For a
    v2 set with a ``catalytic_annotation``, the stored ``reaction_knowledge@1`` result must pass
    ``reaction_knowledge.validated_result``, be of the same structure, and give exactly the set's catalytic check
    (covered / uncovered chains, row counts, conflict and unmatched lists) and every ``protection.catalytic``.
    """
    try:
        structure = content["structure"]["handle"]
        allowed = mutation_handoff.reference_structures(structure, origin)
        parameters = content["parameters"]
        if (map_content is None) is not (parameters["numbering_map"] is None) or \
                (annotation is None) is not (parameters["annotation"] is None) or \
                (pocket_content is None) is not (parameters["sources"]["pocket"] is None):
            raise EvidenceError("mutation_sources_missing")
        if map_content is not None:
            if map_content["structure"]["handle"] not in allowed:
                raise EvidenceError("mutation_numbering_map_structure_mismatch")
            rows = {mc.identity(row["residue"]): row for row in map_content["rows"]}
            for position in content["positions"]:
                row = rows.get(mc.identity(position["residue"]))
                expected = ({"status": "not_in_map", **dict.fromkeys(mc.NUMBERING_FIELDS)} if row is None else
                            {"status": row["status"], **{field: row[field] for field in mc.NUMBERING_FIELDS}})
                if canonical_json(position["numbering"]) != canonical_json(expected):
                    raise EvidenceError("mutation_numbering_value_mismatch")
        if annotation is not None:
            if annotation["structure"]["handle"] not in allowed:
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
        if pocket_content is not None and pocket_content["source_handle"] not in allowed:
            raise EvidenceError("mutation_pocket_set_structure_mismatch")
        catalytic_handle = parameters.get("catalytic_annotation")   # a v1 set has no such parameter
        if (catalytic_result is None) is not (catalytic_handle is None):
            raise EvidenceError("mutation_sources_missing")
        if catalytic_result is not None:
            _check_catalytic(content, catalytic_result, catalytic_handle, allowed)
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_sources_unresolved") from exc


def _check_catalytic(content: dict[str, Any], result: dict[str, Any], handle: str,
                     allowed: tuple[str, ...] | None = None) -> None:
    try:
        rk.validated_result(result)
    except rk.ResultInvalid as exc:
        raise EvidenceError("mutation_catalytic_annotation_invalid") from exc
    if result["structure"]["handle"] not in (allowed or (content["structure"]["handle"],)):
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


def _validated(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(content, provenance, the stored numbering map / annotation / reaction result / pocket set it names or None and
    the validated M29 ``origin`` of its structure or None)."""
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
        map_content = (None if parameters["numbering_map"] is None else
                       _source(run, parameters["numbering_map"], (nr.rn.KIND, nr.rn.SCHEMA),
                               "mutation_numbering_map_kind"))
        annotation = (None if parameters["annotation"] is None else
                      _source(run, parameters["annotation"], (sa.KIND, sa.SCHEMA), "mutation_annotation_kind"))
        pocket_content = (None if pocket is None else
                          _source(run, pocket["pocket_set"], POCKET_KIND, "mutation_pocket_set_kind"))
        catalytic = (None if parameters.get("catalytic_annotation") is None else
                     _source(run, parameters["catalytic_annotation"], CATALYTIC_KIND,
                             "mutation_catalytic_annotation_kind"))
        origin = origin_reports.origin(run, content["structure"]["handle"])
        check_sources(content, map_content, annotation, pocket_content, catalytic, origin)
        return content, provenance, {"numbering_map": map_content, "annotation": annotation, "catalytic": catalytic,
                                     "pocket": pocket_content, "origin": origin}
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_evidence_unresolved") from exc


def validated_mutation_set(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a stored candidate set produced by the tool and the stored objects it names; (content, provenance)."""
    content, provenance, _ = _validated(run, handle)
    return content, provenance


def reference_snapshot_sets(run: Any, content: dict[str, Any], claims: list[dict[str, Any]],
                            sources: dict[str, Any]) -> list[dict[str, Any]]:
    """The snapshot set of each reference family the report cites (M28 T3), copied from the cited objects.

    Numbering family: the set names a numbering map or an annotation. The record is the numbering map's
    ``snapshot_set`` (with an annotation alone, the map the annotation names), checked with the M15 report's own
    validation, which also finds the run's ``reference_snapshot_set@1`` object; an annotation must name the same set.
    Reaction family: a claim cites an M-CSA entry ID; the record is the stored reaction result's ``snapshot_set`` (the
    result was validated once with the set). Empty when nothing is cited (the report is then @1)."""
    parameters, annotation = content["parameters"], sources["annotation"]
    sets: list[dict[str, Any]] = []
    map_handle = parameters["numbering_map"]
    if map_handle is None and annotation is not None:
        map_handle = annotation["numbering_map"]
    if map_handle is not None:
        map_content, context = nr.validated_numbering_map(run, map_handle)
        snapshot_set = map_content["snapshot_set"]
        if annotation is not None and annotation["snapshot_set_hash"] != snapshot_set["set_hash"]:
            raise EvidenceError("mutation_reference_set_mismatch")
        sets.append({"set_schema": NUMBERING_SET_SCHEMA, "copied_from": map_handle,
                     "reference_set_handle": context["reference_set_handle"], "snapshot_set": snapshot_set,
                     "klifs_terms": nr.KLIFS_TERMS})
    if any(claim["statement_id"] == "reference_mcsa_entry_id" for claim in claims):
        sets.append({"set_schema": rkc.SET_SCHEMA, "copied_from": parameters["catalytic_annotation"],
                     "snapshot_set": sources["catalytic"]["snapshot_set"]})
    return sets


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None,
           reference: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = (STATEMENTS.get(statement_id) or V3_STATEMENTS[statement_id])[0]
    return {"statement_id": statement_id, "evidence_kind": kind, "source_handle": handle,
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


def modeled_claim(run: Any, handle: str, content: dict[str, Any], origin: dict[str, Any]) -> dict[str, Any]:
    """M29 T12 (@3 only): the count of stored positions whose residue is a modeled residue of the repair record, from
    ``mutation_handoff.modeled_residue_view`` (the reads' judgment). The subject names the record and the stored
    fields that judgment shows as not checked (modeled residue) at one or more of those positions."""
    _references, modeled = mutation_handoff.modeled_residue_view(run.store, content, origin)
    shown = {field for fields in modeled if fields for field in fields}
    subject = {"candidate_set_handle": handle, "repair_record_handle": origin["repair_record"],
               "repaired_structure_handle": origin["repaired_structure"],
               "reference_not_checked": [field for field in mutation_handoff.REFERENCE_FIELDS if field in shown]}
    return _claim(MODELED_STATEMENT, handle, "positions[*].residue", {"repair_modeled_residue": True}, subject,
                  "repair_modeled_residue_positions", "count", sum(fields is not None for fields in modeled),
                  "integer", "count_where(residue in structure_repair@1 gaps[*].residues[*] or replaced[*].to; "
                             "stored rows)")


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim built from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("mutation_claim_shape")
    statement = proposed["statement_id"]
    if statement in origin_reports.STATEMENT_IDS:   # M29 @3: the record counts of a repaired structure
        return origin_reports.match_claim(expected_claims, proposed, "mutation")
    if statement not in STATEMENTS and statement not in V3_STATEMENTS:
        raise EvidenceError("mutation_claim_statement_not_allowed")
    kind, rule = STATEMENTS.get(statement) or V3_STATEMENTS[statement]
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

def _expected(run: Any, handle: str, version: str | None = None) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored set (not snapshot / markdown handle).

    ``version`` is the render version of a stored report; None picks it for a new report: @3 for a set on a repaired
    structure, else @2 when the report cites reference values, else @1. An @1 report is checked with the @1 fields only
    (no source table is looked up); @3 is the report of a repaired structure's set and only of one."""
    content, provenance, sources = _validated(run, handle)
    origin = sources["origin"]
    try:
        claims = claims_for(handle, content)
        sets = [] if version == RENDER_VERSION else reference_snapshot_sets(run, content, claims, sources)
        if version is None:
            version = (RENDER_VERSION_V3 if origin is not None else RENDER_VERSION_V2 if sets else RENDER_VERSION)
        elif version not in MANIFEST_KEYS_BY_VERSION:
            raise EvidenceError("mutation_report_schema_invalid")
        elif version == RENDER_VERSION_V2 and not sets:
            raise EvidenceError("mutation_report_reference_sets_missing")   # an @2 report cites reference values
        if (version == RENDER_VERSION_V3) is (origin is None):
            raise EvidenceError("mutation_report_structure_origin_mismatch")  # @3 is a repaired structure's set only
        if version == RENDER_VERSION_V3:
            claims = claims + [modeled_claim(run, handle, content, origin)] + origin_reports.claims(origin)
        expected = {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                    "render_version": version, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                    "result_schema": SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                    **{key: content[key] for key in COPIED_FIELDS},
                    "claims": claims,
                    "provenance": {key: provenance[key] for key in ("call_id", "tool", "tool_version",
                                                                    "created_event_seq", "completed_event_seq")},
                    "evidence_statement": (EVIDENCE_STATEMENT_V2 if content["method_version"] == METHOD_VERSION_V2
                                           else EVIDENCE_STATEMENT)}
        if version in (RENDER_VERSION_V2, RENDER_VERSION_V3):
            expected["reference_snapshot_sets"] = sets
        if version == RENDER_VERSION_V3:
            expected["structure_origin"] = origin_reports.manifest_field(origin, handoff=_handed_off(sources, origin))
        return expected
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_report_evidence_unresolved") from exc


def _handed_off(sources: dict[str, Any], origin: dict[str, Any]) -> bool:
    """Whether the set uses a reference result (pocket set, numbering map, annotation, catalytic annotation) made on
    the repaired structure's original structure (spec 5.3; the report then carries SO3)."""
    made_on = [None if sources["pocket"] is None else sources["pocket"]["source_handle"],
               *(None if sources[key] is None else sources[key]["structure"]["handle"]
                 for key in ("numbering_map", "annotation", "catalytic"))]
    return origin["source_structure"] in made_on


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
    v3 = manifest["render_version"] == RENDER_VERSION_V3
    modeled = [c for c in claims if c["statement_id"] == MODELED_STATEMENT]
    # M29 T12 (@3): the stored fields the reads show as not checked (modeled residue) at modeled-residue positions
    not_checked = modeled[0]["subject"]["reference_not_checked"] if v3 and len(modeled) == 1 else []
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
    names = [CHECK_KO[key] for field, key in NOT_CHECKED_CHECKS if field in not_checked]
    if names:   # M29 T12 (@3): the table states the stored values, not a check of the modeled-residue positions
        lines.extend(["", (f"- 모델링 잔기 위치의 {'·'.join(names)} 검사: {MODELED_NOT_CHECKED}. 위 표의 상태와 개수는 "
                           "저장값이며 이 위치를 검사했다는 뜻이 아니다.")])
    lines.extend(["", "## 번호 대응 (참조 스냅샷 값, 계산 아님)", ""])
    if parameters["numbering_map"] is None:
        lines.append(f"- 번호 대응: {NOT_GIVEN}. 위치별 UniProt·KLIFS 번호가 없다.")
    else:
        for status in NUMBERING_STATUSES:
            lines.append(f"- {NUMBERING_KO[status]} ({md(status)}) 위치 (ProtView 계산): "
                         f"{value('numbering_status_count', {'numbering_status': status})}")
        if "numbering" in not_checked:   # M29 T12 (@3): the stored not_in_map count holds modeled-residue positions
            lines.append(f"- 모델링 잔기 위치의 번호 대응: {MODELED_NOT_CHECKED}. 위 {NUMBERING_KO['not_in_map']} "
                         f"({md('not_in_map')}) 위치 수는 저장값을 센 것이며 모델링 잔기 위치가 들어 있다.")
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
    if manifest["render_version"] == RENDER_VERSION_V2 or (   # M28 T3: the source table of each cited set
            manifest["render_version"] == RENDER_VERSION_V3 and manifest["reference_snapshot_sets"]):
        lines.extend(["", "## 참조 스냅샷"])
        for entry in manifest["reference_snapshot_sets"]:
            lines.extend(_reference_set_lines(entry, md))
    if v3:   # M29 T8: the structure origin section (T12: and the count of modeled-residue positions)
        lines.extend(origin_reports.section_lines(manifest["structure_origin"], claims, md))
        lines.append(f"- 모델링 잔기 위치 수 (보완 기록 {md('gaps[*].residues')}·{md('replaced[*].to')}와 잔기 식별자가 "
                     f"같은 위치, ProtView 계산): {value(MODELED_STATEMENT)}")
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


def _reference_set_lines(entry: dict[str, Any], md: Any) -> list[str]:
    """One cited set's table in the wording and fields of the M15 / M16 table (numbering family) or the M26 table
    (reaction family, without the processed-row-count column and the active-set lines). Fixed labels are template
    text (checked for forbidden words); values are slots."""
    snapshot_set = entry["snapshot_set"]
    if entry["set_schema"] == NUMBERING_SET_SCHEMA:
        lines = ["", "### 번호 대응·주석의 참조 세트", "", f"Numbering map: {md(entry['copied_from'])}",
                 (f"Reference snapshot set of the numbering map: {md(snapshot_set['set_hash'])} "
                  f"(object {md(entry['reference_set_handle'])})"), "",
                 "| 출처 | 버전 | 날짜 | 스냅샷 ID | 라이선스 | 가공 |", "| --- | --- | --- | --- | --- | --- |"]
        for source in snapshot_set["sources"]:
            label = nr.SOURCE_LABELS.get(source["source"])
            version = source["version_hint"] if source["version_hint"] is not None else "none (null)"
            terms = _md(entry["klifs_terms"]) if source["source"] == "klifs" else md(source["license"])
            lines.append(f"| {_md(label) if label is not None else md(source['source'])} | {md(version)} | "
                         f"{md(source['date'])} | {md(source['snapshot_id'])} | {terms} | {_md(nr.PROCESSED_LABEL)} |")
        lines.extend(["", f"- Origin: {md(snapshot_set['origin'])}"])
        return lines
    if entry["set_schema"] == rkc.SET_SCHEMA:
        # imported here: that module imports this one when it loads
        from . import reaction_knowledge_reports as rkr
        lines = ["", "### 촉매 잔기 주석의 반응 참조 세트", "", rkc.STATEMENTS["RK6"], "",
                 "| 출처 | 날짜 | 세트 해시 | 라이선스 | 가공 |", "| --- | --- | --- | --- | --- |"]
        for source in snapshot_set["sources"]:
            lines.append(f"| {_md(rkr.SOURCE_LABELS[source['source']])} | {md(source['date'])} | "
                         f"{md(snapshot_set['set_hash'])} | {rkr.LICENSE_LABEL} ({md(source['license'])}) | "
                         f"{rkr.PROCESSED_LABEL} |")
        lines.extend(["", (f"- 가져온 시각: {md(snapshot_set['imported_at'])} (importer "
                           f"{md(snapshot_set['importer_version'])}, {_md(rkc.ORIGIN)})")])
        return lines
    raise EvidenceError("mutation_report_reference_set_invalid")


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
    version = report.get("render_version") if type(report) is dict else None
    keys = MANIFEST_KEYS_BY_VERSION.get(version) if type(version) is str else None   # @1, @2 and @3 are read
    if (keys is None or set(report) != keys or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str):
        raise EvidenceError("mutation_report_schema_invalid")
    expected = _expected(run, report["result_handle"], version)
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
