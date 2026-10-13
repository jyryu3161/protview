"""M29 downstream reports: the "## 구조 출처" section of a result made on a repaired structure (spec .dryforge/spec.md
6.2, 6.3).

Shared by the five downstream report modules: M20 ``mutation_reports`` (``mutation_candidates_markdown@3``), M21
``mutation_model_reports`` (``mutation_model_markdown@2``), M24 ``jev_reports`` (mutation kind,
``jev_choice_markdown@2``), M25 ``jev_loop_reports`` (protein branch, ``jev_loop_markdown@2``) and M18
``docking_reports`` (receptor from a mutation model, ``ligand_docking_markdown@2``). Each of them asks ``origin`` about
the structure its result was made on; only for a repaired structure does it take the new format version, add the
manifest field ``structure_origin`` and the two count claims below, and render the section right before
"## Limitations". For any other structure ``origin`` returns None after reading the structure's manifest, and the
report keeps its earlier version and bytes.

Pure reads of the run's stored objects and events (nothing is written, no engine, job, network or process module).

``origin(run, structure) -> dict | None``
    None unless ``structure`` is a repaired structure (``structure_origin``: the manifest ``repair`` key). Otherwise
    the repair record re-validated on every call (``structure_repair_bundle.validated_result``: its single completed
    ``pdbfixer_repair_v1`` publication, the four objects and the record rebuilt from the original prepared structure
    and the stored repaired bytes), which must have published exactly this structure from the manifest's
    ``repair.source``: ``{repair_record, repaired_structure, source_structure, record}``. A malformed link, a record
    that does not validate or one that published another structure is ``EvidenceError``; an environment failure (a
    ``ToolFailure`` of class ``precondition``, e.g. ``openmm_unavailable`` when the installed template cannot be read)
    is raised as it is, never as invalid evidence (spec 3.1, 4.6).
``manifest_field(found, handoff=False) -> dict``
    The manifest field ``structure_origin``: the three handles and the fixed sentences of the section as
    ``[{id, text}]`` (SO1 always; SO3 when ``handoff``, an M20 set using reference results of the original structure).
``claims(found, with_reference=True) -> list[dict]``
    The two ``computed`` claims citing the record (``source_handle`` = the record, ``structure_repair@1``): statement
    ``repair_added_residue_count`` = ``counts.added_residues`` and ``repair_added_atom_count`` = ``counts.added_atoms``,
    each also recounted from the record's rows (``gaps[*].residues``, ``added_atoms``). ``with_reference`` adds the
    ``reference: null`` key of the reports whose claims carry one (M18 claims have no such key).
``match_claim(expected_claims, proposed, prefix) -> dict``
    The claim check of one of those two statements (the caller checked the claim's key set first): computed, the
    statement's one field path, the record's kind and schema, the expected record handle and hash, then every value.
    Refusals are ``EvidenceError`` named with the caller's ``prefix`` (the route answers ``report_evidence_invalid``).
``section_lines(field, bound, md) -> list[str]``
    The section's Markdown lines: the fixed sentences verbatim (template text, so the caller's interpretive-wording
    check sees them; ``FIXED_LINES`` are its exact exemptions), then the handles and the two claimed counts in ``md``
    (the caller's slot or escape function).
"""
from __future__ import annotations

from typing import Any

from . import structure_repair_bundle as bundle
from . import structure_repair_constants as K
from .core.errors import ToolFailure
from .core.handles import canonical_json
from .reports import EvidenceError
from .structure_origin import structure_origin

SECTION = "## 구조 출처"
STATEMENT_IDS = K.ORIGIN_STATEMENT_IDS
COUNT_FIELDS = dict(zip(STATEMENT_IDS, ("added_residues", "added_atoms"), strict=True))
FIXED_LINES = frozenset({K.SO1, K.SO3})


def origin(run: Any, structure: Any) -> dict[str, Any] | None:
    try:
        found = structure_origin(run.store, structure)
    except ToolFailure as exc:
        raise EvidenceError("structure_origin_link_invalid") from exc
    if found is None:
        return None
    try:
        repair = bundle.validated_result(run, found["repair_record"])
    except bundle.RepairEvidenceError as exc:
        raise EvidenceError(f"structure_origin_record_invalid: {exc}") from exc
    if (repair["prepared_structure"], repair["source_structure"]) != (structure, found["source_structure"]):
        raise EvidenceError("structure_origin_record_mismatch")
    return {"repair_record": found["repair_record"], "repaired_structure": structure,
            "source_structure": found["source_structure"], "record": repair["record"]}


def manifest_field(found: dict[str, Any], *, handoff: bool = False) -> dict[str, Any]:
    statements = [{"id": "SO1", "text": K.SO1}, *([{"id": "SO3", "text": K.SO3}] if handoff else [])]
    return {"repair_record": found["repair_record"], "repaired_structure": found["repaired_structure"],
            "source_structure": found["source_structure"], "statements": statements}


def claims(found: dict[str, Any], *, with_reference: bool = True) -> list[dict[str, Any]]:
    record, handle = found["record"], found["repair_record"]
    try:
        recount = {"added_residues": sum(len(gap["residues"]) for gap in record["gaps"]),
                   "added_atoms": len(record["added_atoms"])}
        stored = {field: record["counts"][field] for field in COUNT_FIELDS.values()}
    except (KeyError, TypeError) as exc:
        raise EvidenceError("structure_origin_count_unresolved") from exc
    if any(type(value) is not int for value in stored.values()) or stored != recount:
        raise EvidenceError("structure_origin_count_mismatch")
    out = []
    for statement, field in COUNT_FIELDS.items():
        claim = {"statement_id": statement, "evidence_kind": "computed", "source_handle": handle,
                 "source_kind": K.KIND, "source_schema": K.SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
                 "field_path": f"counts.{field}", "row_selector": None,
                 "subject": {"repair_record_handle": handle, "repaired_structure_handle": found["repaired_structure"]},
                 "quantity": f"repair_{field}", "unit": "count", "exact_value": stored[field],
                 "rendered_value": str(stored[field]), "rounding": "integer", "operation": None}
        if with_reference:
            claim["reference"] = None
        out.append(claim)
    return out


def match_claim(expected_claims: list[dict[str, Any]], proposed: dict[str, Any], prefix: str) -> dict[str, Any]:
    statement = proposed["statement_id"]
    if proposed["evidence_kind"] != "computed":
        raise EvidenceError(f"{prefix}_claim_evidence_kind_mismatch")
    if proposed["field_path"] != f"counts.{COUNT_FIELDS[statement]}" or proposed.get("reference") is not None:
        raise EvidenceError(f"{prefix}_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (K.KIND, K.SCHEMA):
        raise EvidenceError(f"{prefix}_claim_source_kind_mismatch")
    match = next((claim for claim in expected_claims if claim["statement_id"] == statement), None)
    if match is None:
        raise EvidenceError(f"{prefix}_claim_field_not_allowed")
    if (proposed["source_handle"] != match["source_handle"] or
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]):
        raise EvidenceError(f"{prefix}_claim_source_mismatch")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError(f"{prefix}_claim_binding_mismatch")
    return proposed


def section_lines(field: dict[str, Any], bound: list[dict[str, Any]], md: Any) -> list[str]:
    values = {}
    for statement in STATEMENT_IDS:
        found = [claim["rendered_value"] for claim in bound if claim["statement_id"] == statement]
        if len(found) != 1:
            raise EvidenceError("structure_origin_claim_missing")
        values[statement] = found[0]
    lines = ["", SECTION, ""]
    for item in field["statements"]:
        lines.extend([item["text"], ""])
    residues, atoms = STATEMENT_IDS
    lines.extend([f"- 보완 기록: {md(field['repair_record'])} ({md(K.SCHEMA)})",
                  f"- 보완 구조: {md(field['repaired_structure'])}",
                  f"- 보완 전 원본 구조: {md(field['source_structure'])}",
                  f"- 추가 잔기 수 (보완 기록 {md('counts.added_residues')}): {md(values[residues])}",
                  f"- 추가 원자 수 (보완 기록 {md('counts.added_atoms')}): {md(values[atoms])}"])
    return lines
