"""Offline, location-bound geometric inspection reports."""
from __future__ import annotations

import hashlib
import html
import math
import re
import uuid
from collections import Counter
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .core.handles import canonical_json
from .core.residue import ResidueRef
from .runtime.orchestrator import checked_link, link_fields
from .tools.energetic import protocol_capabilities


class EvidenceError(ValueError):
    """A claimed scientific statement does not follow from its named object."""


StatementId = Literal["contact_distance", "contact_count", "contacting_residue_count",
                      "minimum_distance", "type_count", "cutoff", "selected_model"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statement_id: StatementId
    source_handle: str
    source_kind: str
    source_schema: str
    source_sha256: str
    field_path: str
    row_index: int | None = None
    row_fingerprint: str | None = None
    subject: dict[str, Any]
    quantity: str
    unit: str
    exact_value: float | int | None
    rendered_value: str
    rounding: str
    operation: str | None = None
    contact_type: str | None = None


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def render_number(value: float | None, rounding: str) -> str:
    if value is None:
        return "undefined"
    if not _finite(value):
        raise EvidenceError("non_finite")
    if rounding == "integer" and type(value) is int:
        return str(value)
    if rounding == "distance_2dp":
        rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded == 0:
            rounded = abs(rounded)
        return f"{rounded:.2f}"
    raise EvidenceError("rounding_mismatch")


def _same(a: Any, b: Any) -> bool:
    return canonical_json(a) == canonical_json(b)


def _residue_key(value: dict[str, Any]) -> tuple[Any, ...]:
    return ResidueRef.model_validate(value).key


def _science_links(store: Any, prepared_handle: str, interaction_handle: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Require typed evidence and a single selected input/model across every link."""
    prepared_meta = store.meta(prepared_handle)
    interaction_meta = store.meta(interaction_handle)
    if ((prepared_meta["kind"], prepared_meta["schema"]) != ("prepared_structure", "prepared_structure@1") or
            (interaction_meta["kind"], interaction_meta["schema"]) != ("interaction_set", "interaction_set@1")):
        raise EvidenceError("science_link_type_mismatch")
    prepared = store.load(prepared_handle)
    interaction = store.load(interaction_handle)
    manifest_handle = prepared["manifest"]
    manifest_meta = store.meta(manifest_handle)
    if (manifest_meta["kind"], manifest_meta["schema"]) != ("preparation_manifest", "preparation_manifest@1"):
        raise EvidenceError("manifest_link_type_mismatch")
    manifest = store.load(manifest_handle)
    original_handle = manifest["input"]
    original_meta = store.meta(original_handle)
    original = store.load(original_handle)
    source_handle = manifest["source_handle"]
    source_meta = store.meta(source_handle)
    store.load(source_handle)
    if ((original_meta["kind"], original_meta["schema"]) != ("structure", "structure_selection@2") or
            (source_meta["kind"], source_meta["schema"]) != ("structure_source", "structure_source@1") or
            original["source"] != source_handle or original["model_index"] != manifest["model_index"] or
            prepared["model_index"] != manifest["model_index"] or
            prepared["model_number"] != manifest["model_number"] or
            interaction["structure"] != prepared_handle or
            interaction["selection"]["ligand"]["model_number"] != manifest["model_number"]):
        raise EvidenceError("science_link_mismatch")
    return prepared, interaction, manifest


def validate_claim(store: Any, proposed: Claim | dict[str, Any]) -> Claim:
    """Resolve only approved fields and operations from the immutable store."""
    try:
        claim = proposed if isinstance(proposed, Claim) else Claim.model_validate(proposed)
        meta = store.meta(claim.source_handle)
        content = store.load(claim.source_handle)
        if (meta["kind"], meta["schema"], claim.source_handle.rsplit("/", 1)[-1]) != (
                claim.source_kind, claim.source_schema, claim.source_sha256):
            raise EvidenceError("source_identity_mismatch")
        sid = claim.statement_id
        if sid == "selected_model":
            if (meta["kind"], meta["schema"], claim.field_path, claim.quantity, claim.unit,
                    claim.rounding, claim.operation, claim.row_index) != (
                    "preparation_manifest", "preparation_manifest@1", "model_number",
                    "model_identifier", "identifier", "integer", None, None):
                raise EvidenceError("field_binding_mismatch")
            if set(claim.subject) != {"prepared_handle", "interaction_handle"}:
                raise EvidenceError("subject_mismatch")
            prepared, interaction, manifest = _science_links(
                store, claim.subject["prepared_handle"], claim.subject["interaction_handle"])
            if (set(claim.subject) != {"prepared_handle", "interaction_handle"} or
                    interaction["structure"] != claim.subject["prepared_handle"] or
                    prepared["manifest"] != claim.source_handle or
                    content != manifest or content["model_number"] != prepared["model_number"]):
                raise EvidenceError("subject_mismatch")
            expected = content["model_number"]
        else:
            if meta["kind"] != "interaction_set" or meta["schema"] != "interaction_set@1":
                raise EvidenceError("source_kind_mismatch")
            if not isinstance(content, dict) or not isinstance(content.get("rows"), list):
                raise EvidenceError("malformed_interaction")
            prepared_handle = content["structure"]
            prepared, _, manifest = _science_links(store, prepared_handle, claim.source_handle)
            ligand = content["selection"]["ligand"]
            if (claim.subject.get("prepared_handle") != prepared_handle or
                    claim.subject.get("interaction_handle") != claim.source_handle or
                    not _same(claim.subject.get("ligand"), ligand)):
                raise EvidenceError("subject_mismatch")
            if (manifest["model_number"] != ligand["model_number"] or
                    content["method"].get("name") != "heavy_atom_distance" or
                    content["method"].get("version") != "1" or
                    content["method"].get("unit") != "angstrom" or
                    not _finite(content["parameters"].get("cutoff_A"))):
                raise EvidenceError("method_link_mismatch")
            rows = content["rows"]
            for row in rows:
                if (not isinstance(row, dict) or not _finite(row.get("distance_A")) or row["distance_A"] < 0 or
                        row.get("unit") != "angstrom" or row.get("engine") != "geometric" or
                        row.get("method") != "heavy_atom_distance" or
                        row.get("type") not in content["parameters"]["types"] or
                        row["distance_A"] > content["parameters"]["cutoff_A"] or
                        row.get("model_number") != ligand["model_number"] or
                        not _same(row.get("ligand"), ligand)):
                    raise EvidenceError("malformed_row")
                _residue_key(row["residue"])
                if row["residue"]["model_number"] != ligand["model_number"]:
                    raise EvidenceError("row_model_mismatch")
            expected_spec = {
                "contact_distance": ("distance_A", "angstrom", "distance_2dp", "row_distance"),
                "contact_count": ("atom_pairs", "count", "integer", "count_rows"),
                "contacting_residue_count": ("residues", "count", "integer", "count_distinct_residues"),
                "minimum_distance": ("distance_A", "angstrom", "distance_2dp", "minimum_distance"),
                "type_count": ("atom_pairs", "count", "integer", "count_type"),
                "cutoff": ("distance_A", "angstrom", "distance_2dp", None),
            }[sid]
            if (claim.quantity, claim.unit, claim.rounding, claim.operation) != expected_spec:
                raise EvidenceError("quantity_unit_operation_mismatch")
            if sid == "contact_distance":
                i = claim.row_index
                if type(i) is not int or i < 0 or i >= len(rows) or claim.field_path != f"rows[{i}].distance_A":
                    raise EvidenceError("row_field_mismatch")
                row = rows[i]
                fingerprint = hashlib.sha256(canonical_json({"index": i, "row": row})).hexdigest()
                if claim.row_fingerprint != fingerprint:
                    raise EvidenceError("row_fingerprint_mismatch")
                if (not _same(claim.subject.get("residue"), row["residue"]) or
                        claim.subject.get("protein_atom") != row["protein_atom"] or
                        claim.subject.get("ligand_atom") != row["ligand_atom"] or
                        claim.subject.get("type") != row["type"] or claim.contact_type is not None):
                    raise EvidenceError("row_subject_mismatch")
                if set(claim.subject) != {"prepared_handle", "interaction_handle", "ligand", "residue", "protein_atom", "ligand_atom", "type"}:
                    raise EvidenceError("row_subject_mismatch")
                expected = row["distance_A"]
            else:
                if claim.row_index is not None or claim.row_fingerprint is not None or any(key in claim.subject for key in
                                                      ("residue", "protein_atom", "ligand_atom")):
                    raise EvidenceError("unexpected_row_subject")
                if set(claim.subject) != {"prepared_handle", "interaction_handle", "ligand"}:
                    raise EvidenceError("unexpected_subject_field")
                if sid == "contact_count":
                    expected, path = len(rows), "rows"
                elif sid == "contacting_residue_count":
                    expected, path = len({_residue_key(r["residue"]) for r in rows}), "rows.residue"
                elif sid == "minimum_distance":
                    expected, path = min((r["distance_A"] for r in rows), default=None), "rows.distance_A"
                elif sid == "type_count":
                    if claim.contact_type not in {"contact", "polar_contact", "hydrophobic_contact"}:
                        raise EvidenceError("unsupported_contact_type")
                    expected, path = sum(r["type"] == claim.contact_type for r in rows), "rows.type"
                else:
                    if claim.contact_type is not None:
                        raise EvidenceError("unexpected_contact_type")
                    expected, path = content["parameters"]["cutoff_A"], "parameters.cutoff_A"
                if claim.field_path != path or (sid != "type_count" and claim.contact_type is not None):
                    raise EvidenceError("field_binding_mismatch")
        if expected is None:
            if claim.exact_value is not None:
                raise EvidenceError("exact_value_mismatch")
        elif type(expected) != type(claim.exact_value) or not _finite(expected) or expected != claim.exact_value:
            raise EvidenceError("exact_value_mismatch")
        if claim.rendered_value != render_number(expected, claim.rounding):
            raise EvidenceError("rendered_value_mismatch")
        return claim
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise EvidenceError("unresolved_evidence") from exc


def validate_statement(store: Any, statement_id: str, claim: Claim | dict[str, Any]) -> str:
    """Closed predicate set; free text never becomes scientific authority."""
    if statement_id not in Claim.model_fields["statement_id"].annotation.__args__:
        raise EvidenceError("unsupported_predicate")
    valid = validate_claim(store, claim)
    if valid.statement_id != statement_id:
        raise EvidenceError("statement_mismatch")
    return valid.rendered_value


def _claim(handle: str, meta: dict[str, Any], sid: StatementId, path: str,
           subject: dict[str, Any], quantity: str, unit: str, value: Any,
           rounding: str, operation: str | None = None, row_index: int | None = None,
           contact_type: str | None = None, row_fingerprint: str | None = None) -> dict[str, Any]:
    return Claim(statement_id=sid, source_handle=handle, source_kind=meta["kind"],
                 source_schema=meta["schema"], source_sha256=handle.rsplit("/", 1)[-1],
                 field_path=path, subject=subject, quantity=quantity, unit=unit,
                 exact_value=value, rendered_value=render_number(value, rounding),
                 rounding=rounding, operation=operation, row_index=row_index,
                 contact_type=contact_type, row_fingerprint=row_fingerprint).model_dump()


def _md(value: Any) -> str:
    """Text for a Markdown cell; no raw HTML, links or image syntax survive."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(str(value), quote=True)).replace("\n", " ").replace("\r", " ")


def _ref(ref: dict[str, Any]) -> str:
    label = "unknown" if ref.get("chain_label") is None else f"{ref['chain_label']}/{ref.get('seq_label') if ref.get('seq_label') is not None else 'unknown'}"
    return (f"{ref['resname']} auth {ref['chain_auth']}/{ref['seq_auth']}{ref['icode']} "
            f"label {label} model {ref['model_number']}")


def _provenance(events: list[dict[str, Any]], handle: str,
                *, expected_tool: str | None = None) -> dict[str, Any]:
    created = next((e for e in events if e["type"] == "object_created" and e.get("handle") == handle), None)
    if created is None:
        raise EvidenceError("missing_object_event")
    call_id = created.get("produced_by")
    call = next((e for e in events if e["type"] == "tool_called" and e.get("call_id") == call_id), None)
    success = next((e for e in events if e["type"] == "tool_succeeded" and e.get("call_id") == call_id), None)
    if expected_tool is not None and (call is None or call.get("tool") != expected_tool or
                                      success is None or success["output"]["handle"] != handle):
        raise EvidenceError("missing_successful_tool_provenance")
    return {"handle": handle, "created_event_seq": created["seq"], "call_id": call_id,
            "tool": call.get("tool") if call else None,
            "tool_version": call.get("version") if call else None,
            "completed_event_seq": success.get("seq") if success else None}


def resume_linked_report(run: Any, execution_link: Any, *, event_type: str, source_field: str,
                         source_handle: str, saved: Callable[[Any, str], dict[str, Any]],
                         builder: str) -> dict[str, Any] | None:
    """Operation idempotency for linked report publication; the caller holds the run owner.

    Returns the report this exact link already published (re-validated, never rewritten), or None
    after admitting a new publication. Reuse of a link for another source fails closed.
    """
    link = checked_link(execution_link)
    if link is None:
        return None
    published = [event for event in run.events.read()
                 if event["type"] in {"report_created", "method_report_created"} and
                 event.get("execution_link") == link.record()]
    if published:
        if (len(published) != 1 or published[0]["type"] != event_type or
                published[0].get(source_field) != source_handle):
            raise EvidenceError("execution_link_report_conflict")
        return saved(run, published[0]["report_handle"])
    if link.admit is not None:
        with run._transition():
            link.admit({"lane": "report", "builder": builder, "source_handle": source_handle})
    return None


def build_inspection_report(run: Any, interaction_handle: str, *, prepared_handle: str | None = None,
                            execution_link: Any = None) -> dict[str, Any]:
    """Serialize report creation with run execution; never nests Run.call."""
    try:
        with run._owner():
            run.store.rebuild_from_events()
            run._refresh()
            existing = resume_linked_report(run, execution_link, event_type="report_created",
                                            source_field="interaction_handle", source_handle=interaction_handle,
                                            saved=saved_report, builder="inspection")
            if existing is not None:
                if prepared_handle is not None and existing["manifest"]["prepared_handle"] != prepared_handle:
                    raise EvidenceError("prepared_handle_mismatch")
                return existing
            return _build_inspection_report(run, interaction_handle, prepared_handle=prepared_handle,
                                            execution_link=execution_link)
    except ValueError as exc:
        raise EvidenceError("unresolved_report_source") from exc


def _build_inspection_report(run: Any, interaction_handle: str, *, prepared_handle: str | None = None,
                             execution_link: Any = None) -> dict[str, Any]:
    """Create immutable Markdown + JSON manifest from one selected successful result."""
    try:
        interaction_meta = run.store.meta(interaction_handle)
        if interaction_meta["kind"] != "interaction_set" or interaction_meta["schema"] != "interaction_set@1":
            raise EvidenceError("wrong_result_kind")
        data = run.store.load(interaction_handle)
        prepared_id = data["structure"]
        if prepared_handle is not None and prepared_handle != prepared_id:
            raise EvidenceError("prepared_handle_mismatch")
        prep_meta = run.store.meta(prepared_id)
        if prep_meta["kind"] != "prepared_structure":
            raise EvidenceError("prepared_link_mismatch")
        prepared = run.store.load(prepared_id)
        manifest_id = prepared["manifest"]
        if run.store.meta(manifest_id)["kind"] != "preparation_manifest":
            raise EvidenceError("manifest_link_mismatch")
        prep = run.store.load(manifest_id)
        source_id = prep["source_handle"]
        source_meta = run.store.meta(source_id)
        if source_meta["kind"] != "structure_source":
            raise EvidenceError("source_link_mismatch")
        # Each link is resolved and hash verified. The source and rows are never substituted.
        run.store.load(source_id)
        loaded = run.store.load(prep["input"])
        if (run.store.meta(prep["input"])["kind"] != "structure" or
                loaded["source"] != source_id or loaded["model_index"] != prep["model_index"]):
            raise EvidenceError("source_preparation_link_mismatch")
        rows = data["rows"]
        if interaction_meta["null_result"] != (len(rows) == 0):
            raise EvidenceError("null_result_mismatch")
        ligand = data["selection"]["ligand"]
        subject = {"prepared_handle": prepared_id, "interaction_handle": interaction_handle,
                   "ligand": ligand}
        claims = [
            _claim(interaction_handle, interaction_meta, "contact_count", "rows", subject,
                   "atom_pairs", "count", len(rows), "integer", "count_rows"),
            _claim(interaction_handle, interaction_meta, "contacting_residue_count", "rows.residue", subject,
                   "residues", "count", len({_residue_key(r["residue"]) for r in rows}), "integer", "count_distinct_residues"),
            _claim(interaction_handle, interaction_meta, "minimum_distance", "rows.distance_A", subject,
                   "distance_A", "angstrom", min((r["distance_A"] for r in rows), default=None),
                   "distance_2dp", "minimum_distance"),
            _claim(interaction_handle, interaction_meta, "cutoff", "parameters.cutoff_A", subject,
                   "distance_A", "angstrom", data["parameters"]["cutoff_A"], "distance_2dp"),
            _claim(manifest_id, run.store.meta(manifest_id), "selected_model", "model_number",
                   {"prepared_handle": prepared_id, "interaction_handle": interaction_handle},
                   "model_identifier", "identifier", prep["model_number"], "integer"),
        ]
        counts = Counter(row["type"] for row in rows)
        for kind in ("contact", "polar_contact", "hydrophobic_contact"):
            claims.append(_claim(interaction_handle, interaction_meta, "type_count", "rows.type", subject,
                                 "atom_pairs", "count", counts[kind], "integer", "count_type", contact_type=kind))
        for i, row in enumerate(rows):
            claims.append(_claim(interaction_handle, interaction_meta, "contact_distance",
                                 f"rows[{i}].distance_A", {**subject, "residue": row["residue"],
                                 "protein_atom": row["protein_atom"], "ligand_atom": row["ligand_atom"],
                                 "type": row["type"]}, "distance_A", "angstrom", row["distance_A"],
                                 "distance_2dp", "row_distance", row_index=i,
                                 row_fingerprint=hashlib.sha256(canonical_json({"index": i, "row": row})).hexdigest()))
        for claim in claims:
            validate_claim(run.store, claim)
        events = list(run.events.read())
        seq = events[-1]["seq"] if events else 0
        source_provenance = _provenance(events, source_id)
        prepared_provenance = _provenance(events, prepared_id, expected_tool="prepare_structure")
        manifest_provenance = _provenance(events, manifest_id)
        interaction_provenance = _provenance(events, interaction_handle, expected_tool="compute_interactions")
        capabilities = protocol_capabilities()
        report = {
            "schema": "report_manifest@1", "render_version": "inspection_markdown@1", "status": "complete",
            "generation_mode": "local_rules_no_egress",
            "snapshot": {"event_seq": seq, "time_utc": events[-1]["ts"] if events else None,
                         "run_egress_mode": run.egress_config["mode"],
                         "budget": run.budget_snapshot(),
                         "decisions": [{"seq": e["seq"],
                                        "source": e.get("source") if e.get("source") in
                                        {"human", "rule", "jev", "frontier"} else "unknown",
                                        "question": e.get("question") if e.get("question") in
                                        {"prerequisite_evidence"} else "other"}
                                       for e in events if e["type"] == "decision"],
                         "jobs": [{"seq": e["seq"], "event": e["type"],
                                   "protocol_id": e.get("protocol_id") if e.get("protocol_id") in
                                   {"relax", "cartesian_ddg", "interface_analyzer", "residue_energies"} else None}
                                  for e in events if e["type"] in {"job_submitted", "job_terminal"}]},
            "source_handle": source_id, "prepared_handle": prepared_id,
            "preparation_manifest_handle": manifest_id, "interaction_handle": interaction_handle,
            "model_index": prep["model_index"], "model_number": prep["model_number"],
            "preparation": {key: prep[key] for key in ("altloc", "waters", "hydrogens", "missing_residues",
                                                       "symmetry_mates", "protonation", "removed")},
            "ligand": ligand, "parameters": data["parameters"], "method": data["method"],
            "scientific_null": len(rows) == 0, "counts": {"atom_pairs": len(rows),
                "contacting_residues": len({_residue_key(r["residue"]) for r in rows}),
                "by_type": {kind: counts[kind] for kind in ("contact", "polar_contact", "hydrophobic_contact")}},
            "minimum_distance_A": min((r["distance_A"] for r in rows), default=None),
            "rows": rows, "claims": claims, "capabilities": capabilities,
            "provenance": {"source": source_provenance, "prepared": prepared_provenance,
                           "preparation_manifest": manifest_provenance,
                           "interaction": interaction_provenance},
            "limitations": ["Geometric proximity does not establish a hydrogen bond, affinity, stability, or energy.",
                            "Optional energy protocols are unavailable without a validated production engine."],
        }
        markdown = render_report(report)
        markdown_obj = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                                     produced_by=f"report_{uuid.uuid4().hex}",
                                     summary={"interaction_handle": interaction_handle})
        report["markdown_handle"] = markdown_obj.handle
        manifest_obj = run.store.put("report_manifest", "report_manifest@1", report,
                                     produced_by=markdown_obj.produced_by,
                                     summary={"interaction_handle": interaction_handle, "status": "complete"})
        run.events.append("report_created", report_handle=manifest_obj.handle,
                          markdown_handle=markdown_obj.handle, interaction_handle=interaction_handle,
                          snapshot_event_seq=seq, **link_fields(execution_link))
        return {"handle": manifest_obj.handle, "markdown_handle": markdown_obj.handle, "manifest": report,
                "markdown": markdown}
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise EvidenceError("unresolved_report_source") from exc


def render_report(manifest: dict[str, Any]) -> str:
    """Render only known fields and locally validated claims; no raw Markdown injection."""
    claims = manifest["claims"]
    lookup = {claim["statement_id"]: claim for claim in claims if claim["row_index"] is None}
    lines = ["# Geometric complex inspection", "", "Status: complete", "",
             f"Source: {_md(manifest['source_handle'])}",
             f"Prepared: {_md(manifest['prepared_handle'])}",
             f"Interaction: {_md(manifest['interaction_handle'])}",
             f"Model: {lookup['selected_model']['rendered_value']} (index {manifest['model_index']})", 
             f"Ligand: {_md(_ref(manifest['ligand']))}", "", "## Preparation and method", ""]
    for key, value in manifest["preparation"].items():
        if key == "removed":
            lines.append("- Removed atom and residue counts: see the linked preparation manifest")
            continue
        lines.append(f"- {_md(key)}: {_md(value)}")
    lines.extend([f"- Method: {_md(manifest['method']['name'])} v{_md(manifest['method']['version'])}",
                  f"- Cutoff: {lookup['cutoff']['rendered_value']} Å",
                  f"- Requested contact classes: {_md(', '.join(manifest['parameters']['types']))}", "",
                  "## Measurements", "",
                  f"- Atom pairs: {lookup['contact_count']['rendered_value']}",
                  f"- Distinct contacting residues: {lookup['contacting_residue_count']['rendered_value']}",
                  f"- Minimum distance: {lookup['minimum_distance']['rendered_value']}" +
                  ("" if manifest["minimum_distance_A"] is None else " Å"),
                  f"- Scientific null: {'yes' if manifest['scientific_null'] else 'no'}", "",
                  "## All measured atom pairs", "",
                  "| # | Protein residue (auth and label) | Protein atom | Ligand atom | Class | Distance (Å) |",
                  "| ---: | --- | --- | --- | --- | ---: |"])
    type_lines = [f"- {_md(claim['contact_type'])} atom pairs: {claim['rendered_value']}"
                  for claim in claims if claim["statement_id"] == "type_count"]
    insert_at = lines.index("## All measured atom pairs")
    lines[insert_at:insert_at] = [*type_lines, ""]
    distances = {c["row_index"]: c["rendered_value"] for c in claims if c["statement_id"] == "contact_distance"}
    for index, row in enumerate(manifest["rows"]):
        lines.append(f"| {index + 1} | {_md(_ref(row['residue']))} | {_md(row['protein_atom'])} | "
                     f"{_md(row['ligand_atom'])} | {_md(row['type'])} | {distances[index]} |")
    lines.extend(["", "## Provenance and limits", "",
                  f"- Evidence snapshot event: {manifest['snapshot']['event_seq']}",
                  f"- Preparation manifest: {_md(manifest['preparation_manifest_handle'])}"])
    for key, value in manifest["provenance"].items():
        lines.append(f"- {_md(key)} call: {_md(value['call_id'] or 'none')} (event {_md(value['completed_event_seq'] or 'none')})")
    for protocol, item in manifest["capabilities"]["protocols"].items():
        lines.append(f"- {_md(protocol)}: unavailable ({_md(item['reason_code'])}; {_md(item['explanation'])})")
    lines.extend(["", *(_md(limit) for limit in manifest["limitations"]), ""])
    return "\n".join(lines)


def saved_report(run: Any, report_handle: str) -> dict[str, Any]:
    meta = run.store.meta(report_handle)
    if meta["kind"] != "report_manifest" or meta["schema"] != "report_manifest@1":
        raise EvidenceError("wrong_report_kind")
    report = run.store.load(report_handle)
    if report.get("schema") != "report_manifest@1" or report.get("status") != "complete":
        raise EvidenceError("invalid_report_status")
    markdown_handle = report["markdown_handle"]
    if run.store.meta(markdown_handle)["kind"] != "report_markdown":
        raise EvidenceError("markdown_link_mismatch")
    if not any(e["type"] == "report_created" and e.get("report_handle") == report_handle and
               e.get("markdown_handle") == markdown_handle and
               e.get("interaction_handle") == report["interaction_handle"] for e in run.events.read()):
        raise EvidenceError("report_completion_event_missing")
    markdown = run.store.load(markdown_handle).decode("utf-8")
    return {"handle": report_handle, "markdown_handle": markdown_handle,
            "manifest": report, "markdown": markdown}
