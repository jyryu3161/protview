"""Immutable, field-cited reports for ``residue_numbering_map@1`` (``method_report_manifest@1``,
``analysis_type: "residue_numbering"``).

Two evidence kinds are kept apart (spec M15 section 7):

- ``computed`` -- values ProtView calculated: per-chain alignment ``identity_pct`` / ``coverage_pct`` (rendered with
  ``Decimal(str(v))`` quantized to 0.1, ``ROUND_HALF_UP``), row counts by status (``count_kind``), the count of
  mapped rows whose structure residue differs from the UniProt letter (also by kind = structure residue name and
  UniProt letter, per chain), the count of alignment-ambiguous rows and the
  modified-residue count of the chain residue rule.
- ``reference_value`` -- reference snapshot values, not calculations: accessions, UniProt positions and letters,
  KLIFS pocket numbers and labels. Each claim carries the reference set hash, the source snapshot(s) with version,
  date and license, and the note "참조 스냅샷 값, 계산 아님".

Each statement ID has exactly one evidence kind and its own closed set of field paths; a computed statement citing
a reference field (or the reverse) is rejected before any value comparison. Per-residue reference values are listed
only for mapped rows that carry a KLIFS pocket number (at most 85 per chain and accession); every other row appears
only in the status counts, and the full row table stays in the numbering map object. Creating, reopening and
downloading never re-run the mapping: saved reads re-validate the stored map, compare every manifest field and claim,
and compare the Markdown byte for byte with a re-render. The fixed template makes no interpretive statement; the
renderer also rejects any Markdown containing interpretive wording.
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

from . import residue_numbering as rn
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _provenance, _ref, resume_linked_report
from .runtime.orchestrator import link_fields

ANALYSIS_TYPE = "residue_numbering"
RENDER_VERSION = "residue_numbering_markdown@1"
TOOL = "map_residue_numbering"
REPORT_BYTES = 8 * 1024 * 1024  # same bound the report list/selected routes use
STATUSES = ("mapped", "unmapped", "conflict")
STATUS_KO = {"mapped": "대응됨", "unmapped": "대응 없음", "conflict": "충돌"}
SOURCE_LABELS = {"uniprot": "UniProt", "sifts": "SIFTS", "klifs": "KLIFS"}
REFERENCE_NOTE = "참조 스냅샷 값, 계산 아님"
PROCESSED_LABEL = "kbase_kinase 가공본"
KLIFS_TERMS = "이용 조건 명시 없음(none-stated)"
REFERENCE_STATEMENT = ("Accessions, UniProt positions and residues, and KLIFS pocket numbers and labels in this report "
                       "are reference snapshot values (참조 스냅샷 값, 계산 아님), not ProtView calculations. ProtView "
                       "computed only the alignment identity and coverage and the counts.")
# Limitations of reports created before the snapshot-scope line was added; saved reports carrying them still reopen.
LEGACY_REPORT_LIMITATIONS = [
    "This report states the numbering correspondence only; it makes no statement about function or structure.",
    ("Residue-level reference values are listed only for mapped rows with a KLIFS pocket number; every row (all "
     "statuses, both method answers and absent reasons) is in the numbering map object."),
]
SNAPSHOT_SCOPE = ("참조 스냅샷은 kbase_kinase가 가공한 kinase 한정 자료입니다(원출처 원본 바이트 아님). "
                  "스냅샷에 없는 PDB·단백질은 SIFTS 대응이나 KLIFS 번호가 없습니다.")
REPORT_LIMITATIONS = [*LEGACY_REPORT_LIMITATIONS, SNAPSHOT_SCOPE]
AMBIGUOUS_REASON = "alignment_ambiguous"

EVIDENCE_KINDS = ("computed", "reference_value")
# statement ID -> evidence kind (fixed template; nothing else may carry a number in this report)
STATEMENTS = {
    "status_count": "computed",
    "chain_status_count": "computed",
    "chain_identity_pct": "computed",
    "chain_coverage_pct": "computed",
    "chain_residue_mismatch_count": "computed",
    "chain_residue_mismatch_kind_count": "computed",
    "chain_ambiguous_residue_count": "computed",
    "chain_modified_residue_count": "computed",
    "reference_accession": "reference_value",
    "reference_uniprot_position": "reference_value",
    "reference_uniprot_residue": "reference_value",
    "reference_klifs_index": "reference_value",
    "reference_klifs_label": "reference_value",
}
STATEMENT_IDS = tuple(STATEMENTS)
# Field rules per evidence kind: a claim's field path must belong to its kind before anything else is compared.
COMPUTED_FIELDS = re.compile(
    r"rows\.(status|residue_match|alignment\.absent_reasons)|chains\[\d+\]\.("
    r"alignment\.(identity_pct|coverage_pct)|counts\.(mapped|unmapped|conflict)|residue_rule\.modified_residue_count)")
REFERENCE_FIELDS = re.compile(
    r"chains\[\d+\]\.(sifts\.accessions\[\d+\]|alignment\.accession)|"
    r"rows\[\d+\]\.(uniprot_accession|uniprot_position|uniprot_residue|klifs_index|klifs_label)")
CLAIM_KEYS = frozenset({"statement_id", "evidence_kind", "source_handle", "source_kind", "source_schema",
                        "source_sha256", "field_path", "row_selector", "subject", "quantity", "unit", "exact_value",
                        "rendered_value", "rounding", "operation", "reference"})
# Interpretive wording the template never uses; any rendered Markdown containing it is refused.
INTERPRETIVE = re.compile(
    r"important|critical|essential|key residue|binding|binds|affinity|stabili[sz]|druggab|inhibit|selectiv|"
    r"potency|functional|중요|결합|친화|안정화|억제|선택성|핵심|기능", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget"}
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "method_version", "structure", "pdb_id", "snapshot_set", "reference_set_handle",
    "alignment_params", "chains", "null_result", "labelled_rows", "claims", "provenance", "reference_statement",
    "klifs_terms", "limitations", "snapshot", "markdown_handle"})
ROW_KEYS = {"residue", "status", "uniprot_accession", "uniprot_position", "uniprot_residue", "residue_match",
            "klifs_index", "klifs_label", "klifs_match", "conflict_reason", "sifts", "alignment"}
RESIDUE_KEYS = {"model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"}


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_pct(value: Any) -> str:
    """Percent with one decimal: ``Decimal(str(v))`` quantized to 0.1 with ``ROUND_HALF_UP`` (97.25 -> 97.3)."""
    if value is None:
        return "undefined"
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("numbering_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.1f}"


def _render(value: Any, rounding: str) -> str:
    if rounding == "pct_1dp":
        return render_pct(value)
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("numbering_claim_integer_expected")
        return str(value)
    if rounding == "verbatim":
        if type(value) not in (int, str):
            raise EvidenceError("numbering_claim_value_type")
        return str(value)
    raise EvidenceError("numbering_claim_rounding")


def check_no_interpretation(text: str) -> str:
    match = INTERPRETIVE.search(text)
    if match is not None:
        raise EvidenceError(f"numbering_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation

def _residue_ok(residue: Any) -> bool:
    return type(residue) is dict and set(residue) == RESIDUE_KEYS


def _answer_ok(answer: Any, reasons: tuple[str, ...]) -> bool:
    """A method answer: a position, or absent reasons from that method's closed set (``reasons``)."""
    if answer is None:
        return True
    if type(answer) is not dict:
        return False
    if set(answer) == {"accession", "position"}:
        return type(answer["accession"]) is str and type(answer["position"]) is int
    return (set(answer) == {"absent_reason", "absent_reasons"} and type(answer["absent_reasons"]) is list and
            bool(answer["absent_reasons"]) and answer["absent_reason"] == answer["absent_reasons"][0] and
            all(type(reason) is str and reason in reasons for reason in answer["absent_reasons"]))


def _check_rows(content: dict[str, Any]) -> None:
    for row in content["rows"]:
        if type(row) is not dict or set(row) != ROW_KEYS or not _residue_ok(row["residue"]):
            raise EvidenceError("numbering_row_shape")
        if (row["status"] not in STATUSES or not _answer_ok(row["sifts"], rn.SIFTS_ABSENT_REASONS) or
                not _answer_ok(row["alignment"], rn.ALIGNMENT_ABSENT_REASONS) or
                (row["conflict_reason"] is not None and row["conflict_reason"] not in rn.CONFLICT_REASONS)):
            raise EvidenceError("numbering_row_shape")
        if row["status"] == "mapped":
            if (type(row["uniprot_accession"]) is not str or type(row["uniprot_position"]) is not int or
                    row["uniprot_position"] < 1 or row["conflict_reason"] is not None):
                raise EvidenceError("numbering_mapped_row_invalid")
            if row["klifs_index"] is not None and (type(row["klifs_index"]) is not int or
                                                   not 1 <= row["klifs_index"] <= 85 or
                                                   type(row["klifs_label"]) is not str):
                raise EvidenceError("numbering_klifs_value_invalid")
        elif any(row[key] is not None for key in ("uniprot_accession", "uniprot_position", "uniprot_residue",
                                                  "residue_match", "klifs_index", "klifs_label", "klifs_match")):
            raise EvidenceError("numbering_unmapped_row_has_value")
        if row["residue_match"] not in (True, False, None):
            raise EvidenceError("numbering_row_shape")


def _chain_rows(content: dict[str, Any], chain_auth: str) -> list[tuple[int, dict[str, Any]]]:
    return [(index, row) for index, row in enumerate(content["rows"]) if row["residue"]["chain_auth"] == chain_auth]


def _check_chains(content: dict[str, Any]) -> None:
    chains = content["chains"]
    names = [chain["chain_auth"] for chain in chains]
    if type(chains) is not list or not chains or len(set(names)) != len(names):
        raise EvidenceError("numbering_chain_shape")
    if {row["residue"]["chain_auth"] for row in content["rows"]} - set(names):
        raise EvidenceError("numbering_row_chain_unknown")
    mapped_total = 0
    for chain in chains:
        rows = [row for _, row in _chain_rows(content, chain["chain_auth"])]
        counts = chain["counts"]
        if (type(counts) is not dict or set(counts) != set(STATUSES) or
                any(type(counts[s]) is not int or counts[s] != sum(r["status"] == s for r in rows) for s in STATUSES)):
            raise EvidenceError("numbering_counts_mismatch")
        mapped_total += counts["mapped"]
        methods = chain["methods_run"]
        if methods not in (["sifts"], ["local_alignment"], ["sifts", "local_alignment"]):
            raise EvidenceError("numbering_methods_invalid")
        if (chain["cross_check"] is not (len(methods) == 2) or
                (chain["cross_check_absent_reason"] is None) is not chain["cross_check"] or
                (chain["cross_check_absent_reason"] is not None and
                 chain["cross_check_absent_reason"] not in rn.CROSS_CHECK_ABSENT_REASONS)):
            raise EvidenceError("numbering_cross_check_invalid")
        if ((chain["sifts"] is not None) is not ("sifts" in methods) or
                (chain["alignment"] is not None) is not ("local_alignment" in methods) or
                any((row["sifts"] is not None) is not ("sifts" in methods) or
                    (row["alignment"] is not None) is not ("local_alignment" in methods) for row in rows)):
            raise EvidenceError("numbering_method_answers_mismatch")
        if chain["sifts"] is not None and (type(chain["sifts"]["accessions"]) is not list or
                                           any(type(a) is not str for a in chain["sifts"]["accessions"])):
            raise EvidenceError("numbering_sifts_invalid")
        alignment = chain["alignment"]
        if alignment is not None:
            pairs, identical, n = alignment["aligned_pairs"], alignment["identical"], alignment["chain_residue_count"]
            if any(type(v) is not int or v < 0 for v in (pairs, identical, n)) or n != len(rows):
                raise EvidenceError("numbering_alignment_counts_invalid")
            # The stored statistics are the ProtView definitions (sequence_alignment): re-derived exactly.
            if (alignment["identity_pct"] != (identical / pairs * 100 if pairs else None) or
                    alignment["coverage_pct"] != (pairs / n * 100 if n else None) or
                    type(alignment["accession"]) is not str):
                raise EvidenceError("numbering_alignment_statistics_mismatch")
        if type(chain["klifs"]) is not list or any(
                type(item) is not dict or item["applied"] is not (item["absent_reason"] is None) or
                (item["absent_reason"] is not None and item["absent_reason"] not in rn.KLIFS_ABSENT_REASONS)
                for item in chain["klifs"]):
            raise EvidenceError("numbering_klifs_reason_invalid")
        modified = chain["residue_rule"]["modified_residue_count"]
        if type(modified) is not int or modified < 0 or chain["residue_rule"]["rule"] != rn.RESIDUE_RULE:
            raise EvidenceError("numbering_residue_rule_invalid")
    if sum(sum(c["counts"].values()) for c in chains) != len(content["rows"]):
        raise EvidenceError("numbering_counts_mismatch")
    if content["null_result"] is not (mapped_total == 0):
        raise EvidenceError("numbering_null_result_mismatch")


def _reference_set(run: Any, events: list[dict[str, Any]], set_hash: str) -> tuple[str, dict[str, Any]]:
    """The run's ``reference_snapshot_set@1`` object whose canonical bytes hash to ``set_hash``."""
    found = [event["handle"] for event in events if event["type"] == "object_created" and
             event.get("kind") == rn.SET_KIND and (event.get("summary") or {}).get("set_hash") == set_hash]
    for handle in dict.fromkeys(found):
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (rn.SET_KIND, "reference_snapshot_set@1"):
            continue
        manifest = run.store.load(handle)
        if hashlib.sha256(canonical_json(manifest)).hexdigest() == set_hash:
            return handle, manifest
    raise EvidenceError("numbering_reference_set_missing")


def validated_numbering_map(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a published numbering map and check its internal accounting; returns (content, context)."""
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (rn.KIND, rn.SCHEMA):
            raise EvidenceError("wrong_result_kind")
        content = run.store.load(handle)
        if type(content) is not dict or content.get("schema") != rn.SCHEMA or \
                content.get("method_version") != rn.METHOD_VERSION:
            raise EvidenceError("numbering_schema_mismatch")
        events = list(run.events.read())
        provenance = _provenance(events, handle, expected_tool=TOOL)
        _check_rows(content)
        _check_chains(content)
        snapshot_set = content["snapshot_set"]
        set_handle, set_manifest = _reference_set(run, events, snapshot_set["set_hash"])
        expected_record = rn.snapshot_set_record(SimpleNamespace(manifest=set_manifest,
                                                                 set_hash=snapshot_set["set_hash"]))
        if canonical_json(expected_record) != canonical_json(snapshot_set):
            raise EvidenceError("numbering_snapshot_record_mismatch")
        structure = content["structure"]
        structure_meta = run.store.meta(structure["handle"])
        if structure_meta["kind"] != structure["structure_kind"] or structure["structure_kind"] not in (
                "structure", "prepared_structure"):
            raise EvidenceError("numbering_structure_link_mismatch")
        return content, {"reference_set_handle": set_handle, "provenance": provenance}
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("numbering_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _reference(content: dict[str, Any], sources: tuple[str, ...]) -> dict[str, Any]:
    by_name = {item["source"]: item for item in content["snapshot_set"]["sources"]}
    return {"note": REFERENCE_NOTE, "set_hash": content["snapshot_set"]["set_hash"],
            "origin": content["snapshot_set"]["origin"],
            "sources": [{key: by_name[name][key] for key in ("source", "snapshot_id", "date", "version_hint",
                                                             "license")} for name in sources]}


def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any], subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None,
           reference: dict[str, Any] | None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": STATEMENTS[statement_id], "source_handle": handle,
            "source_kind": rn.KIND, "source_schema": rn.SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": {"map_handle": handle, **subject},
            "quantity": quantity, "unit": unit, "exact_value": value, "rendered_value": _render(value, rounding),
            "rounding": rounding, "operation": operation, "reference": reference}


def _row_selector(index: int, row: dict[str, Any]) -> dict[str, Any]:
    return {"row_index": index, "row_sha256": hashlib.sha256(canonical_json({"index": index, "row": row})).hexdigest()}


def labelled_rows(content: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    return [(index, row) for index, row in enumerate(content["rows"])
            if row["status"] == "mapped" and row["klifs_index"] is not None]


def _mismatch_kinds(chain_rows: list[dict[str, Any]]) -> list[tuple[tuple[str, Any], int]]:
    """Mismatched rows counted by (structure resname, UniProt letter), in sorted kind order; only kinds that occur."""
    counts: dict[tuple[str, Any], int] = {}
    for row in chain_rows:
        if row["residue_match"] is False:
            key = (row["residue"]["resname"], row["uniprot_residue"])
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (str(item[0][0]), str(item[0][1])))


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report, each bound to one exact stored field or one count over ``rows``."""
    rows = content["rows"]
    claims = [_claim("status_count", handle, "rows.status", {"status": status}, {}, f"{status}_rows", "count",
                     sum(row["status"] == status for row in rows), "integer", "count_kind(rows.status)", None)
              for status in STATUSES]
    for ci, chain in enumerate(content["chains"]):
        name = chain["chain_auth"]
        chain_sel = {"chain_auth": name}
        chain_rows = [row for _, row in _chain_rows(content, name)]
        prefix = f"chains[{ci}]"
        for status in STATUSES:
            claims.append(_claim("chain_status_count", handle, f"{prefix}.counts.{status}", chain_sel, chain_sel,
                                 f"{status}_rows", "count", chain["counts"][status], "integer",
                                 "count_kind(rows.status; residue.chain_auth)", None))
        claims.append(_claim("chain_residue_mismatch_count", handle, "rows.residue_match", chain_sel, chain_sel,
                             "residue_mismatch_rows", "count",
                             sum(row["residue_match"] is False for row in chain_rows), "integer",
                             "count_kind(rows.residue_match == false; residue.chain_auth)", None))
        for (resname, letter), count in _mismatch_kinds(chain_rows):
            kind_sel = {**chain_sel, "structure_resname": resname, "uniprot_residue": letter}
            claims.append(_claim("chain_residue_mismatch_kind_count", handle, "rows.residue_match", kind_sel,
                                 kind_sel, "residue_mismatch_rows_by_kind", "count", count, "integer",
                                 "count_kind(rows.residue_match == false; residue.chain_auth, residue.resname, "
                                 "uniprot_residue)", None))
        claims.append(_claim("chain_modified_residue_count", handle, f"{prefix}.residue_rule.modified_residue_count",
                             chain_sel, chain_sel, "modified_residues", "count",
                             chain["residue_rule"]["modified_residue_count"], "integer", None, None))
        if chain["sifts"] is not None:
            for ai, accession in enumerate(chain["sifts"]["accessions"]):
                claims.append(_claim("reference_accession", handle, f"{prefix}.sifts.accessions[{ai}]", chain_sel,
                                     chain_sel, "sifts_accession", "identifier", accession, "verbatim", None,
                                     _reference(content, ("sifts",))))
        alignment = chain["alignment"]
        if alignment is not None:
            claims.append(_claim("reference_accession", handle, f"{prefix}.alignment.accession", chain_sel,
                                 chain_sel, "alignment_accession", "identifier", alignment["accession"], "verbatim",
                                 None, _reference(content, ("uniprot",))))
            for field in ("identity_pct", "coverage_pct"):
                claims.append(_claim(f"chain_{field}", handle, f"{prefix}.alignment.{field}", chain_sel, chain_sel,
                                     field, "percent", alignment[field], "pct_1dp", None, None))
            claims.append(_claim("chain_ambiguous_residue_count", handle, "rows.alignment.absent_reasons", chain_sel,
                                 chain_sel, "alignment_ambiguous_rows", "count",
                                 sum(AMBIGUOUS_REASON in (row["alignment"] or {}).get("absent_reasons", [])
                                     for row in chain_rows), "integer",
                                 f"count_kind(rows.alignment.absent_reasons contains {AMBIGUOUS_REASON}; "
                                 "residue.chain_auth)", None))
    for index, row in labelled_rows(content):
        selector = _row_selector(index, row)
        subject = {"residue": row["residue"]}
        position_sources = ("sifts", "uniprot") if row["sifts"] is not None else ("uniprot",)
        for statement, field, unit, sources in (
                ("reference_accession", "uniprot_accession", "identifier", position_sources),
                ("reference_uniprot_position", "uniprot_position", "uniprot_sequence_position", position_sources),
                ("reference_uniprot_residue", "uniprot_residue", "identifier", ("uniprot",)),
                ("reference_klifs_index", "klifs_index", "klifs_pocket_index", ("klifs", "uniprot")),
                ("reference_klifs_label", "klifs_label", "identifier", ("klifs", "uniprot"))):
            if row[field] is None:
                continue
            claims.append(_claim(statement, handle, f"rows[{index}].{field}", selector, subject, field, unit,
                                 row[field], "verbatim", None, _reference(content, sources)))
    return claims


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule and every value equal the claim built from that exact field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("numbering_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("numbering_claim_statement_not_allowed")
    kind = proposed["evidence_kind"]
    if kind not in EVIDENCE_KINDS or kind != STATEMENTS[statement]:
        raise EvidenceError("numbering_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str:
        raise EvidenceError("numbering_claim_shape")
    if kind == "computed":
        if REFERENCE_FIELDS.fullmatch(path):
            raise EvidenceError("numbering_claim_reference_field_as_computed")
        if not COMPUTED_FIELDS.fullmatch(path) or proposed["reference"] is not None:
            raise EvidenceError("numbering_claim_computed_field_rule")
    else:
        if COMPUTED_FIELDS.fullmatch(path):
            raise EvidenceError("numbering_claim_computed_field_as_reference")
        reference = proposed["reference"]
        if (not REFERENCE_FIELDS.fullmatch(path) or type(reference) is not dict or
                reference.get("note") != REFERENCE_NOTE):
            raise EvidenceError("numbering_claim_reference_field_rule")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("numbering_claim_shape") from exc
    if match is None:
        raise EvidenceError("numbering_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("numbering_claim_binding_mismatch")
    return proposed


def validate_numbering_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated numbering map (not snapshot / markdown handle)."""
    content, context = validated_numbering_map(run, handle)
    try:
        provenance = context["provenance"]
        return {
            "schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
            "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
            "result_schema": rn.SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
            "method_version": content["method_version"], "structure": content["structure"],
            "pdb_id": content["pdb_id"], "snapshot_set": content["snapshot_set"],
            "reference_set_handle": context["reference_set_handle"], "alignment_params": content["alignment_params"],
            "chains": content["chains"], "null_result": content["null_result"],
            "labelled_rows": [{"row_index": index, "residue": row["residue"], "status": row["status"],
                               **{key: row[key] for key in ("uniprot_accession", "uniprot_position",
                                                            "uniprot_residue", "residue_match", "klifs_index",
                                                            "klifs_label", "klifs_match")}}
                              for index, row in labelled_rows(content)],
            "claims": claims_for(handle, content),
            "provenance": {"call_id": provenance["call_id"], "tool": provenance["tool"],
                           "tool_version": provenance["tool_version"],
                           "created_event_seq": provenance["created_event_seq"],
                           "completed_event_seq": provenance["completed_event_seq"]},
            "reference_statement": REFERENCE_STATEMENT, "klifs_terms": KLIFS_TERMS,
            "limitations": [content["limitations"], *REPORT_LIMITATIONS]}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("numbering_report_evidence_unresolved") from exc


def _license_text(source: dict[str, Any]) -> str:
    return KLIFS_TERMS if source["source"] == "klifs" else source["license"]


def _kind_counts(manifest: dict[str, Any], chain_sel: dict[str, Any]) -> str:
    kinds = [claim for claim in manifest["claims"] if claim["statement_id"] == "chain_residue_mismatch_kind_count"
             and claim["row_selector"]["chain_auth"] == chain_sel["chain_auth"]]
    return "; ".join(f"{claim['row_selector']['structure_resname']}/{claim['row_selector']['uniprot_residue']} "
                     f"{claim['rendered_value']}" for claim in kinds) or "none"


def render_numbering_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim."""
    claims = {_key(claim): claim["rendered_value"] for claim in manifest["claims"]}

    def value(statement: str, path: str, selector: dict[str, Any]) -> str:
        return claims[(statement, path, canonical_json(selector))]

    structure = manifest["structure"]
    snapshot_set = manifest["snapshot_set"]
    params = manifest["alignment_params"]
    lines = ["# 잔기 번호 대응 보고서 (residue numbering)", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             (f"Structure: {_md(structure['handle'])} ({_md(structure['structure_kind'])}, "
              f"model {_md(structure['model_number'])})"),
             f"PDB ID given: {_md(manifest['pdb_id']) if manifest['pdb_id'] is not None else 'none (null)'}",
             f"Reference snapshot set: {_md(snapshot_set['set_hash'])} (object {_md(manifest['reference_set_handle'])})",
             "", f"**{_md(manifest['reference_statement'])}**", "", "## 참조 스냅샷", "",
             "| 출처 | 버전 | 날짜 | 스냅샷 ID | 라이선스 | 가공 |", "| --- | --- | --- | --- | --- | --- |"]
    for source in snapshot_set["sources"]:
        version = source["version_hint"] if source["version_hint"] is not None else "none (null)"
        lines.append(f"| {_md(SOURCE_LABELS.get(source['source'], source['source']))} | {_md(version)} | "
                     f"{_md(source['date'])} | {_md(source['snapshot_id'])} | {_md(_license_text(source))} | "
                     f"{_md(PROCESSED_LABEL)} |")
    lines.extend(["", f"- KLIFS: {_md(manifest['klifs_terms'])}. KLIFS 값에는 이 표시가 함께 붙는다.",
                  f"- Origin: {_md(snapshot_set['origin'])}", "",
                  "## 전체 행 개수 (ProtView 계산: count\\_kind(rows.status))", ""])
    for status in STATUSES:
        lines.append(f"- {STATUS_KO[status]} ({status}): {value('status_count', 'rows.status', {'status': status})}")
    if manifest["null_result"]:
        lines.append("- " + _md("No row is mapped; this is a valid empty result (scientific_null), not a failure."))
    lines.extend(["", "## 정렬 설정", "",
                  (f"- {_md(params['matrix'])}, gap open {_md(params['gap_open'])}, gap extend "
                   f"{_md(params['gap_extend'])} ({_md(params['gap_cost'])}), end gaps {_md(params['end_gaps'])}, "
                   f"tie break {_md(params['tie_break'])}, {_md(params['implementation'])}"),
                  (f"- Chain thresholds: identity at least {_md(params['min_identity_pct'])} %, coverage at least "
                   f"{_md(params['min_coverage_pct'])} %")])
    for ci, chain in enumerate(manifest["chains"]):
        sel = {"chain_auth": chain["chain_auth"]}
        prefix = f"chains[{ci}]"
        cross = ("yes" if chain["cross_check"] else
                 f"no (reason: {_md(chain['cross_check_absent_reason'])})")
        lines.extend(["", f"## Chain {_md(chain['chain_auth'])}", "",
                      f"- Methods run: {_md(', '.join(chain['methods_run']))}",
                      f"- Cross-check (both methods): {cross}",
                      f"- Requested UniProt accession: {_md(chain['requested_uniprot_accession'] or 'none (null)')}"])
        if chain["sifts"] is not None:
            accessions = ", ".join(value("reference_accession", f"{prefix}.sifts.accessions[{ai}]", sel)
                                   for ai in range(len(chain["sifts"]["accessions"])))
            lines.append(f"- SIFTS accessions ({REFERENCE_NOTE}; SIFTS): {accessions}; chain match "
                         f"{_md(chain['sifts']['sifts_chain_match'])}, residue key "
                         f"{_md(chain['sifts']['sifts_residue_key'])}")
        else:
            lines.append("- SIFTS: not run")
        if chain["alignment"] is not None:
            alignment = chain["alignment"]
            reasons = ", ".join(alignment["chain_reason"]) or "none"
            lines.extend([
                (f"- Alignment accession ({REFERENCE_NOTE}; UniProt): "
                 f"{value('reference_accession', f'{prefix}.alignment.accession', sel)}"),
                (f"- Alignment identity (ProtView 계산): "
                 f"{value('chain_identity_pct', f'{prefix}.alignment.identity_pct', sel)} %; coverage (ProtView 계산): "
                 f"{value('chain_coverage_pct', f'{prefix}.alignment.coverage_pct', sel)} %; chain threshold "
                 f"reasons: {_md(reasons)}"),
                (f"- Alignment-ambiguous rows (ProtView 계산): "
                 f"{value('chain_ambiguous_residue_count', 'rows.alignment.absent_reasons', sel)}")])
        else:
            lines.append("- Local alignment: not run")
        counts = "; ".join(f"{STATUS_KO[s]} {value('chain_status_count', f'{prefix}.counts.{s}', sel)}"
                           for s in STATUSES)
        lines.extend([f"- Rows (ProtView 계산): {counts}",
                      (f"- Mapped rows whose structure residue differs from the UniProt residue (ProtView 계산): "
                       f"{value('chain_residue_mismatch_count', 'rows.residue_match', sel)}"),
                      (f"- Mismatch kinds, structure residue/UniProt residue (ProtView 계산): "
                       f"{_md(_kind_counts(manifest, sel))}"),
                      (f"- Residue rule: {_md(chain['residue_rule']['rule'])}; modified residues (ProtView 계산): "
                       f"{value('chain_modified_residue_count', f'{prefix}.residue_rule.modified_residue_count', sel)}")])
        for item in chain["klifs"]:
            state = "applied" if item["applied"] else f"not applied ({_md(item['absent_reason'])})"
            unresolved = ", ".join(item["unresolved_regions"]) or "none"
            gapped = ", ".join(item["gapped_regions"]) or "none"
            lines.append(f"- KLIFS for {_md(item['accession'])}: {state}; unresolved regions {_md(unresolved)}; "
                         f"gapped placement regions {_md(gapped)}")
        if not chain["klifs"]:
            lines.append("- KLIFS: no mapped accession in this chain")
    lines.extend(["", f"## KLIFS 번호가 붙은 대응됨 행 ({REFERENCE_NOTE})", ""])
    klifs = next(s for s in snapshot_set["sources"] if s["source"] == "klifs")
    if manifest["labelled_rows"]:
        lines.extend([(f"UniProt 위치·잔기: UniProt/SIFTS 참조 스냅샷. KLIFS 번호·표지: KLIFS {_md(klifs['date'])}, "
                       f"{_md(KLIFS_TERMS)}."), "",
                      ("| Residue (auth and label) | UniProt accession | UniProt position | UniProt residue | "
                       "Residue differs | KLIFS number | KLIFS label |"),
                      "| --- | --- | ---: | --- | --- | ---: | --- |"])
        for item in manifest["labelled_rows"]:
            index = item["row_index"]
            sel = next(c["row_selector"] for c in manifest["claims"]
                       if c["field_path"] == f"rows[{index}].klifs_index")
            cells = [value("reference_accession", f"rows[{index}].uniprot_accession", sel),
                     value("reference_uniprot_position", f"rows[{index}].uniprot_position", sel),
                     (value("reference_uniprot_residue", f"rows[{index}].uniprot_residue", sel)
                      if item["uniprot_residue"] is not None else "none (null)"),
                     {True: "no", False: "yes", None: "unknown"}[item["residue_match"]],
                     value("reference_klifs_index", f"rows[{index}].klifs_index", sel),
                     value("reference_klifs_label", f"rows[{index}].klifs_label", sel)]
            lines.append(f"| {_md(_ref(item['residue']))} | " + " | ".join(_md(cell) for cell in cells) + " |")
    else:
        lines.append("- None.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_md(item)}" for item in manifest["limitations"])
    lines.extend(["", ("Every row with both method answers and absent reasons is in the numbering map object; exact "
                       f"values, evidence kinds and field paths are in the JSON download ({len(manifest['claims'])} "
                       "claims)."), ""])
    return check_no_interpretation("\n".join(lines))


def build_numbering_report(run: Any, result_handle: str, *, execution_link: Any = None) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        existing = resume_linked_report(run, execution_link, event_type="method_report_created",
                                        source_field="result_handle", source_handle=result_handle,
                                        saved=saved_numbering_report, builder="residue_numbering")
        if existing is not None:
            return existing
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot()}
        markdown = render_numbering_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("numbering_report_too_large")
        produced_by = f"numbering_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by=produced_by, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=produced_by,
                               summary={"result_handle": result_handle, "analysis_type": ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq, **link_fields(execution_link))
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_numbering_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored numbering report without re-running the mapping."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("numbering_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("numbering_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("numbering_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, value in expected.items():
        if key == "limitations" and report[key] == [value[0], *LEGACY_REPORT_LIMITATIONS]:
            continue
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"numbering_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["budget"]) is not dict):
        raise EvidenceError("numbering_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("numbering_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("numbering_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("numbering_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_numbering_report(report):
        raise EvidenceError("numbering_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
