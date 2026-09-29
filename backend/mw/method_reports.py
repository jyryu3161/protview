"""Immutable, evidence-bound reports for the fixed interface SASA method."""
from __future__ import annotations

import hashlib
import math
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .core.errors import ToolFailure
from .core.handles import canonical_json
from .core.residue import ResidueRef
from .reports import EvidenceError, _md, _provenance, _ref, resume_linked_report
from .runtime.orchestrator import link_fields
from .tools.energetic import protocol_capabilities
from .tools.registry import ToolContext
from .tools.sasa import AMINO, _preflight, dependencies
from .tools.structural import _parse, _res_ref

SUMMARY_FIELDS = (
    "protein_sasa_isolated_A2", "ligand_sasa_isolated_A2", "complex_sasa_A2",
    "protein_sasa_bound_A2", "ligand_sasa_bound_A2", "protein_burial_A2",
    "ligand_burial_A2", "total_sasa_loss_A2",
)
ROW_FIELDS = ("isolated_A2", "bound_A2", "buried_A2")


def _same(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def _number(value: Any, *, nonnegative: bool = False) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or (nonnegative and value < 0):
        raise EvidenceError("invalid_area")
    return value


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6)


def _render(value: float, rounding: str) -> str:
    _number(value)
    if rounding == "integer" and type(value) is int:
        return str(value)
    if rounding != "area_2dp":
        raise EvidenceError("rounding_mismatch")
    result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(result) if result == 0 else result:.2f}"


def _source_links(store: Any, result: dict[str, Any]) -> dict[str, str]:
    prepared_id = result["structure"]
    prepared_meta = store.meta(prepared_id)
    if (prepared_meta["kind"], prepared_meta["schema"]) != ("prepared_structure", "prepared_structure@1"):
        raise EvidenceError("prepared_link_type")
    prepared = store.load(prepared_id)
    manifest_id = prepared["manifest"]
    if (store.meta(manifest_id)["kind"], store.meta(manifest_id)["schema"]) != ("preparation_manifest", "preparation_manifest@1"):
        raise EvidenceError("preparation_manifest_type")
    manifest = store.load(manifest_id)
    source_id = manifest["source_handle"]
    original_id = manifest["input"]
    if (store.meta(source_id)["kind"], store.meta(source_id)["schema"]) != ("structure_source", "structure_source@1"):
        raise EvidenceError("source_link_type")
    if (store.meta(original_id)["kind"], store.meta(original_id)["schema"]) != ("structure", "structure_selection@2"):
        raise EvidenceError("original_link_type")
    original = store.load(original_id)
    store.load(source_id)
    if (original["source"] != source_id or original["model_index"] != manifest["model_index"] or
            prepared["model_index"] != manifest["model_index"] or
            prepared["model_number"] != manifest["model_number"] or
            result["ligand"]["model_number"] != manifest["model_number"]):
        raise EvidenceError("source_link_mismatch")
    return {"prepared_handle": prepared_id, "preparation_manifest_handle": manifest_id,
            "source_handle": source_id, "original_handle": original_id}


def validated_sasa(store: Any, result_handle: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve exact source atoms and independently check stored SASA accounting."""
    try:
        meta = store.meta(result_handle)
        if (meta["kind"], meta["schema"]) != ("interface_sasa", "interface_sasa@1"):
            raise EvidenceError("wrong_result_kind")
        data = store.load(result_handle)
        if data["schema"] != "interface_sasa@1" or not _same(data["method"], dependencies()):
            raise EvidenceError("method_mismatch")
        ligand = ResidueRef.model_validate(data["ligand"], strict=True).model_dump()
        if not _same(ligand, data["ligand"]) or not _same(ligand, data["selection"]["ligand"]):
            raise EvidenceError("ligand_mismatch")
        links = _source_links(store, data)
        model = _parse(ToolContext(store=store, call_id="report_validation"), data["structure"])[0]
        expected_atoms = []
        protein_refs = []
        exclusions = []
        ligand_matches = 0
        radius_table = data["method"]["radii_A"]
        for chain in model:
            for residue in chain:
                ref = _res_ref(chain, residue, model.num)
                selected = _same(ref, ligand)
                polymer = residue.het_flag == "A" or residue.label_seq is not None
                if polymer and residue.name not in AMINO:
                    raise EvidenceError("nonstandard_polymer")
                if selected:
                    ligand_matches += 1
                    if polymer or residue.het_flag != "H" or residue.is_water():
                        raise EvidenceError("ligand_category")
                elif polymer:
                    protein_refs.append(ref)
                else:
                    exclusions.append({"residue": ref, "atom_count": len(residue),
                                       "reason": "water" if residue.is_water() else "other_nonprotein"})
                    continue
                for atom in residue:
                    if atom.element.name in {"H", "D"}:
                        continue
                    radius = radius_table.get(atom.element.name)
                    if radius is None:
                        raise EvidenceError("unsupported_element")
                    expected_atoms.append({"partner": "ligand" if selected else "protein", "residue": ref,
                                           "atom_name": atom.name, "atom_serial": atom.serial,
                                           "altloc": atom.altloc.strip("\x00 "), "element": atom.element.name,
                                           "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z], "radius_A": radius})
        if (ligand_matches != 1 or len({canonical_json(item["residue"]) for item in exclusions}) != len(exclusions) or
                not _same(data["selection"]["protein_residues"], protein_refs) or
                not _same(data["selection"]["excluded"], exclusions)):
            raise EvidenceError("selection_mismatch")
        # The calculation orders all protein atoms before the one selected ligand.
        expected_atoms.sort(key=lambda item: item["partner"] == "ligand")
        atoms = data["atoms"]
        counts = data["atom_counts"]
        if set(counts) != {"protein", "ligand", "excluded_residues"} or any(type(value) is not int or value < 0 for value in counts.values()):
            raise EvidenceError("invalid_integer_counts")
        if (len(atoms) != len(expected_atoms) or counts["protein"] != sum(a["partner"] == "protein" for a in atoms) or
                counts["ligand"] != sum(a["partner"] == "ligand" for a in atoms) or
                counts["excluded_residues"] != len(exclusions) or not counts["protein"] or not counts["ligand"]):
            raise EvidenceError("atom_count_mismatch")
        if (data["selection"].get("protein") != "canonical20_polymer_heavy_atoms_all_included_chains" or
                data["selection"].get("hydrogen_policy") != "exclude_H_D" or
                data["selection"].get("environment_scope") !=
                "selected protein and one ligand only; not the full crystal or asymmetric unit" or
                data["selection"].get("max_absolute_coordinate_A") != 1e6 or
                data["selection"].get("max_extent_A") != 1e4 or
                not _same(data["selection"].get("origin_translation_A"),
                          _preflight(atoms[:counts["protein"]], atoms[counts["protein"]:]))):
            raise EvidenceError("analysis_selection_policy_mismatch")
        identities = set()
        for index, (atom, expected) in enumerate(zip(atoms, expected_atoms, strict=True)):
            if type(atom["index"]) is not int or atom["index"] != index or any(
                    not _same(atom[key], value) for key, value in expected.items()):
                raise EvidenceError("atom_mapping_mismatch")
            identity = canonical_json([atom["residue"], atom["atom_name"], atom["altloc"]])
            if identity in identities or atom["altloc"]:
                raise EvidenceError("ambiguous_atom")
            identities.add(identity)
            for field in ROW_FIELDS:
                _number(atom[field], nonnegative=field != "buried_A2")
            if not _close(atom["buried_A2"], atom["isolated_A2"] - atom["bound_A2"]) or atom["buried_A2"] < -1e-6:
                raise EvidenceError("atom_area_mismatch")
        grouped: dict[bytes, list[dict[str, Any]]] = {canonical_json(ref): [] for ref in protein_refs}
        if len(grouped) != len(protein_refs):
            raise EvidenceError("ambiguous_protein_residue")
        for atom in atoms[:counts["protein"]]:
            grouped[canonical_json(atom["residue"])].append(atom)
        rows = data["residues"]
        if len(rows) != len(grouped) or len({canonical_json(row["residue"]) for row in rows}) != len(rows):
            raise EvidenceError("residue_count_mismatch")
        for row in rows:
            group = grouped.get(canonical_json(row["residue"]))
            if group is None or any(type(index) is not int for index in row["atom_indices"]) or row["atom_indices"] != [a["index"] for a in group]:
                raise EvidenceError("residue_mapping_mismatch")
            for field in ROW_FIELDS:
                _number(row[field], nonnegative=field != "buried_A2")
                if not _close(row[field], sum(a[field] for a in group)):
                    raise EvidenceError("residue_area_mismatch")
            if row["buried_A2"] < -1e-6:
                raise EvidenceError("negative_residue_burial")
        summary = data["summary"]
        if set(summary) != set(SUMMARY_FIELDS):
            raise EvidenceError("summary_fields_mismatch")
        p = atoms[:counts["protein"]]
        ligand_atoms = atoms[counts["protein"]:]
        expected_summary = {
            "protein_sasa_isolated_A2": sum(a["isolated_A2"] for a in p),
            "ligand_sasa_isolated_A2": sum(a["isolated_A2"] for a in ligand_atoms),
            "complex_sasa_A2": sum(a["bound_A2"] for a in atoms),
            "protein_sasa_bound_A2": sum(a["bound_A2"] for a in p),
            "ligand_sasa_bound_A2": sum(a["bound_A2"] for a in ligand_atoms),
            "protein_burial_A2": sum(a["buried_A2"] for a in p),
            "ligand_burial_A2": sum(a["buried_A2"] for a in ligand_atoms),
            "total_sasa_loss_A2": sum(a["buried_A2"] for a in atoms),
        }
        for field, expected in expected_summary.items():
            _number(summary[field], nonnegative=False)
            if not _close(summary[field], expected):
                raise EvidenceError("summary_area_mismatch")
        if (summary["protein_burial_A2"] < -1e-6 or summary["ligand_burial_A2"] < -1e-6 or
                summary["total_sasa_loss_A2"] < -1e-6):
            raise EvidenceError("negative_burial")
        return data, links
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, ToolFailure) as exc:
        raise EvidenceError("unresolved_method_evidence") from exc


def _claim(handle: str, data: dict[str, Any], field: str, value: float, *, row_index: int | None = None) -> dict[str, Any]:
    subject = {"prepared_handle": data["structure"], "ligand": data["ligand"]}
    if row_index is None:
        path = f"summary.{field}"
        fingerprint = None
    else:
        row = data["residues"][row_index]
        subject["residue"] = row["residue"]
        path = f"residues[{row_index}].{field}"
        fingerprint = hashlib.sha256(canonical_json({"index": row_index, "row": row})).hexdigest()
    return {"source_handle": handle, "source_kind": "interface_sasa", "source_schema": "interface_sasa@1",
            "source_sha256": handle.rsplit("/", 1)[-1], "field_path": path, "row_index": row_index,
            "row_fingerprint": fingerprint, "subject": subject, "quantity": field, "unit": "A2",
            "exact_value": value, "rendered_value": _render(value, "area_2dp"), "rounding": "area_2dp"}


def validate_method_claim(store: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    try:
        if set(proposed) != {"source_handle", "source_kind", "source_schema", "source_sha256", "field_path",
                             "row_index", "row_fingerprint", "subject", "quantity", "unit", "exact_value",
                             "rendered_value", "rounding"}:
            raise EvidenceError("claim_shape_mismatch")
        handle = proposed["source_handle"]
        data, _ = validated_sasa(store, handle)
        if (proposed["source_kind"], proposed["source_schema"], proposed["source_sha256"],
                proposed["unit"], proposed["rounding"]) != (
                "interface_sasa", "interface_sasa@1", handle.rsplit("/", 1)[-1], "A2", "area_2dp"):
            raise EvidenceError("claim_identity_or_unit_mismatch")
        index = proposed["row_index"]
        field = proposed["quantity"]
        if index is None:
            if field not in SUMMARY_FIELDS:
                raise EvidenceError("field_not_allowed")
            expected = _claim(handle, data, field, data["summary"][field])
        else:
            if type(index) is not int or index < 0 or index >= len(data["residues"]) or field not in ROW_FIELDS:
                raise EvidenceError("row_not_allowed")
            expected = _claim(handle, data, field, data["residues"][index][field], row_index=index)
        if not _same(proposed, expected):
            raise EvidenceError("claim_binding_mismatch")
        return proposed
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("unresolved_method_claim") from exc


def build_method_report(run: Any, result_handle: str, *, execution_link: Any = None) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        existing = resume_linked_report(run, execution_link, event_type="method_report_created",
                                        source_field="result_handle", source_handle=result_handle,
                                        saved=saved_method_report, builder="interface_sasa")
        if existing is not None:
            return existing
        data, links = validated_sasa(run.store, result_handle)
        events = list(run.events.read())
        provenance = {
            "source": _provenance(events, links["source_handle"]),
            "prepared": _provenance(events, links["prepared_handle"], expected_tool="prepare_structure"),
            "preparation_manifest": _provenance(events, links["preparation_manifest_handle"]),
            "result": _provenance(events, result_handle, expected_tool="compute_interface_sasa"),
        }
        claims = [_claim(result_handle, data, field, data["summary"][field]) for field in SUMMARY_FIELDS]
        claims.extend(_claim(result_handle, data, field, row[field], row_index=index)
                      for index, row in enumerate(data["residues"]) for field in ROW_FIELDS)
        # The source was fully validated once; each claim is built from its exact field.
        seq = events[-1]["seq"] if events else 0
        manifest = {"schema": "method_report_manifest@1", "analysis_type": "interface_sasa",
                    "status": "complete", "render_version": "interface_sasa_markdown@1",
                    "generation_mode": "local_rules_no_egress", "result_handle": result_handle,
                    **links, "ligand": data["ligand"], "selection": data["selection"],
                    "method": data["method"], "numeric_tolerance": data["numeric_tolerance"],
                    "atom_counts": data["atom_counts"], "atoms": data["atoms"],
                    "residues": data["residues"], "summary": data["summary"], "claims": claims,
                    "snapshot": {"event_seq": seq, "time_utc": events[-1]["ts"] if events else None,
                                 "run_egress_mode": run.egress_config["mode"]},
                    "provenance": provenance, "capabilities": protocol_capabilities(),
                    "limitations": [data["limitations"],
                        "Other ligands, waters, ions and nonprotein components are excluded; not the full crystal environment."]}
        markdown = render_method_report(manifest)
        report_call = f"method_report_{uuid.uuid4().hex}"
        markdown_obj = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"),
                                     fmt="md", produced_by=report_call, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = markdown_obj.handle
        report_obj = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                                   produced_by=report_call, summary={"result_handle": result_handle,
                                                                     "analysis_type": "interface_sasa", "status": "complete"})
        run.events.append("method_report_created", report_handle=report_obj.handle,
                          markdown_handle=markdown_obj.handle, result_handle=result_handle,
                          snapshot_event_seq=seq, **link_fields(execution_link))
        return {"handle": report_obj.handle, "markdown_handle": markdown_obj.handle,
                "manifest": manifest, "markdown": markdown}


def render_method_report(manifest: dict[str, Any]) -> str:
    claims = {claim["field_path"]: claim["rendered_value"] for claim in manifest["claims"]}
    method = manifest["method"]
    lines = ["# Protein–ligand interface SASA", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             f"Prepared: {_md(manifest['prepared_handle'])}",
             f"Source: {_md(manifest['source_handle'])}",
             f"Ligand: {_md(_ref(manifest['ligand']))}", "", "## Method and selection", "",
             f"- Method: {_md(method['method_id'])} ({_md(method['engine'])} {_md(method['engine_version'])})",
             f"- Algorithm: {_md(method['algorithm'])}, {_md(method['n_slices'])} slices, probe {_md(method['probe_radius_A'])} Å, {_md(method['threads'])} thread",
             f"- Radii: {_md(method['radius_description'])}, policy {_md(method['radius_policy'])}, Gemmi {_md(method['gemmi_version'])}",
             f"- Actual radii (Å): {_md(method['radii_A'])}",
             f"- Selected atoms: protein {_md(manifest['atom_counts']['protein'])}, ligand {_md(manifest['atom_counts']['ligand'])}",
             f"- Excluded residues: {_md(manifest['atom_counts']['excluded_residues'])}",
             f"- Hydrogen policy: {_md(manifest['selection']['hydrogen_policy'])}",
             f"- Analysis translation origin (Å): {_md(manifest['selection']['origin_translation_A'])}",
             "", "## Areas (Å²)", ""]
    for field in SUMMARY_FIELDS:
        lines.append(f"- {_md(field)}: {claims['summary.' + field]} Å²")
    lines.extend(["", "## Protein residues (all rows, Å²)", "",
                  "| Residue (auth and label) | Isolated | Bound | Buried |",
                  "| --- | ---: | ---: | ---: |"])
    for index, row in enumerate(manifest["residues"]):
        lines.append(f"| {_md(_ref(row['residue']))} | " + " | ".join(
            claims[f"residues[{index}].{field}"] for field in ROW_FIELDS) + " |")
    lines.extend(["", "## Excluded components", ""])
    for item in manifest["selection"]["excluded"]:
        lines.append(f"- {_md(_ref(item['residue']))}: {_md(item['reason'])}, {_md(item['atom_count'])} atoms")
    if not manifest["selection"]["excluded"]:
        lines.append("- None in the prepared model")
    lines.extend(["", "## Provenance and limits", "",
                  f"- Evidence snapshot event: {manifest['snapshot']['event_seq']}",
                  f"- Preparation manifest: {_md(manifest['preparation_manifest_handle'])}"])
    for key, value in manifest["provenance"].items():
        lines.append(f"- {_md(key)} call: {_md(value['call_id'] or 'none')} (event {_md(value['completed_event_seq'] or 'none')})")
    for protocol, item in manifest["capabilities"]["protocols"].items():
        lines.append(f"- {_md(protocol)}: unavailable ({_md(item['reason_code'])}; {_md(item['explanation'])})")
    lines.extend(["", *(_md(limit) for limit in manifest["limitations"]),
                  "", "Full exact per-atom values and identities are in the JSON download.", ""])
    return "\n".join(lines)


def saved_method_report(run: Any, report_handle: str) -> dict[str, Any]:
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"]) != ("method_report_manifest", "method_report_manifest@1"):
        raise EvidenceError("wrong_method_report_kind")
    report = run.store.load(report_handle)
    if (report.get("schema"), report.get("analysis_type"), report.get("status")) != (
            "method_report_manifest@1", "interface_sasa", "complete"):
        raise EvidenceError("method_report_status")
    markdown_handle = report["markdown_handle"]
    if (run.store.meta(markdown_handle)["kind"], run.store.meta(markdown_handle)["schema"]) != (
            "report_markdown", "report_markdown@1"):
        raise EvidenceError("method_markdown_link")
    if not any(e["type"] == "method_report_created" and e.get("report_handle") == report_handle and
               e.get("markdown_handle") == markdown_handle and e.get("result_handle") == report["result_handle"]
               for e in run.events.read()):
        raise EvidenceError("method_report_event_missing")
    # ObjectStore checks every content hash; saved reads do not invoke FreeSASA.
    result_handle = report["result_handle"]
    result_meta = run.store.meta(result_handle)
    if (result_meta["kind"], result_meta["schema"]) != ("interface_sasa", "interface_sasa@1"):
        raise EvidenceError("wrong_result_kind")
    result = run.store.load(result_handle)
    if result.get("schema") != "interface_sasa@1":
        raise EvidenceError("result_schema_mismatch")
    links = _source_links(run.store, result)
    if any(report.get(key) != value for key, value in links.items()) or any(
            not _same(report.get(key), result[key]) for key in
            ("ligand", "selection", "method", "numeric_tolerance", "atom_counts", "atoms", "residues", "summary")):
        raise EvidenceError("saved_method_evidence_mismatch")
    expected_claims = [_claim(report["result_handle"], result, field, result["summary"][field])
                       for field in SUMMARY_FIELDS]
    expected_claims.extend(_claim(report["result_handle"], result, field, row[field], row_index=index)
                           for index, row in enumerate(result["residues"]) for field in ROW_FIELDS)
    if not _same(report.get("claims"), expected_claims):
        raise EvidenceError("saved_method_claim_mismatch")
    markdown = run.store.load(markdown_handle).decode("utf-8")
    return {"handle": report_handle, "markdown_handle": markdown_handle,
            "manifest": report, "markdown": markdown}
