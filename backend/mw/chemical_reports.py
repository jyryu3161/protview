"""Immutable, field-cited reports for native ProLIF assignment results."""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from .chemical_bundle import validated_result
from .core.handles import canonical_json
from .jobs.queue import require_completed_chemical_handle
from .reports import EvidenceError

SDF_SCOPE_LIMITATION = "Ligand import supports SDF V2000 only; V3000 input is rejected."


def _claims(handle: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    source_sha = handle.rsplit("/", 1)[-1]
    claims = [{"source_handle": handle, "source_kind": "chemical_interaction_set",
               "source_schema": "chemical_interaction_set@1", "source_sha256": source_sha,
               "field_path": "total", "row_id": None, "subject": None,
               "quantity": "assignment_count", "unit": "count", "exact_value": result["total"]}]
    for index, row in enumerate(result["rows"]):
        subject = {"category": row["category"], "ligand_atoms": row["ligand_atoms"],
                   "receptor_atoms": row["receptor_atoms"], "distance_roles": row["distance_roles"]}
        for field, quantity, unit in (("distance_A", "assigned_distance", "angstrom"),
                                      ("DHA_angle_deg", "DHA_angle", "degree")):
            if row[field] is not None:
                claims.append({"source_handle": handle, "source_kind": "chemical_interaction_set",
                               "source_schema": "chemical_interaction_set@1", "source_sha256": source_sha,
                               "field_path": f"rows.{index}.{field}", "row_id": row["row_id"],
                               "subject": subject, "quantity": quantity, "unit": unit,
                               "exact_value": row[field]})
    return claims


def _coordinate_provenance(store: Any, result: dict[str, Any]) -> dict[str, Any]:
    manifest_handle = result["manifest_handle"]
    manifest = store.load_bounded_json(manifest_handle, 8 * 1024 * 1024)
    entries = manifest["attached_source_sites"]
    return {"source_manifest_handle": manifest_handle,
            "derived_coordinate_policy": manifest["derived_coordinate_policy"],
            "attached_source_sites": entries,
            "field_citations": ([{"source_handle": manifest_handle,
                                  "field_path": "derived_coordinate_policy",
                                  "exact_value": manifest["derived_coordinate_policy"]}] +
                                [{"source_handle": manifest_handle,
                                  "field_path": f"attached_source_sites.{index}", "exact_value": entry}
                                 for index, entry in enumerate(entries)]),
            "maximum_attachment_discrepancy_A":
                max((entry["discrepancy_A"] for entry in entries), default=None)}


def _preparation_graph_states(store: Any, result: dict[str, Any]) -> dict[str, Any]:
    manifest = store.load_bounded_json(result["manifest_handle"], 8 * 1024 * 1024)
    citations = ([{"source_handle": result["manifest_handle"],
                  "field_path": "stereochemistry_policy",
                  "exact_value": manifest["stereochemistry_policy"]}] +
                 [{"source_handle": result["manifest_handle"],
                   "field_path": f"histidine_states.{index}", "exact_value": state}
                  for index, state in enumerate(manifest["histidine_states"])] +
                 [{"source_handle": result["manifest_handle"],
                   "field_path": f"stereochemistry_audit.{index}", "exact_value": audit}
                  for index, audit in enumerate(manifest["stereochemistry_audit"])] +
                 [{"source_handle": result["manifest_handle"],
                   "field_path": f"terminal_extension_inventory.{index}", "exact_value": extension}
                  for index, extension in enumerate(manifest["terminal_extension_inventory"])])
    return {"source_manifest_handle": result["manifest_handle"],
            "histidine_states": manifest["histidine_states"],
            "stereochemistry_audit": manifest["stereochemistry_audit"],
            "terminal_extension_inventory": manifest["terminal_extension_inventory"],
            "stereochemistry_policy": manifest["stereochemistry_policy"],
            "field_citations": citations}


def _provenance(events: list[dict[str, Any]], handle: str,
                publication: dict[str, Any]) -> dict[str, Any]:
    created = [e for e in events if e["type"] == "object_created" and e.get("handle") == handle and
               e.get("kind") == "chemical_interaction_set"]
    if len(created) != 1:
        raise EvidenceError("chemical_result_creation_missing")
    attempt_id = publication["successful_publisher_attempt_id"]
    job_id = publication["successful_publisher_job_id"]
    candidates = [e for e in events if e["type"] == "job_result_candidate" and
                  e.get("job_id") == job_id and e.get("attempt_id") == attempt_id and
                  e.get("output_handles") == [handle]]
    if len(candidates) != 1:
        raise EvidenceError("chemical_result_candidate_missing")
    submitted = [e for e in events if e["type"] == "job_submitted" and
                 e["job"]["job_id"] == job_id and e["job"].get("protocol_id") == "prolif_detect_v1" and
                 e["job"].get("tool_id") == "compute_chemical_interactions"]
    terminal = [e for e in events if e["type"] == "job_terminal" and e.get("job_id") == job_id and
                e.get("attempt_id") == attempt_id and e.get("status") == "done" and
                e.get("output_handles") == [handle]]
    reserved = [e for e in events if e["type"] == "budget_reserved" and
                e.get("attempt_id") == attempt_id and e.get("tool") == "compute_chemical_interactions" and
                e.get("root_call_id") == job_id]
    if len(submitted) != 1 or len(terminal) != 1 or len(reserved) != 1 or not (
            created[0]["seq"] < candidates[0]["seq"] < terminal[0]["seq"] and
            reserved[0]["seq"] < candidates[0]["seq"]):
        raise EvidenceError("chemical_job_provenance_invalid")
    return {"job_id": job_id, "attempt_id": attempt_id, "protocol_id": "prolif_detect_v1",
            "tool_id": "compute_chemical_interactions", "created_event_seq": created[0]["seq"],
            "first_creator_attempt_id": created[0].get("produced_by"),
            "completed_event_seq": terminal[0]["seq"]}


def _markdown(result: dict[str, Any], claims: list[dict[str, Any]],
              coordinate_provenance: dict[str, Any],
              preparation_graph_states: dict[str, Any]) -> str:
    counts = Counter(row["category"] for row in result["rows"])
    lines = ["# Chemical interaction assignments", "",
             f"ProLIF 2.2.2 returned {result['total']} assignments from one supplied explicit-H graph.",
             "These are chemistry-dependent native assignments, not experimental bond validation, affinity or energy.",
             "", "## Categories", ""]
    for category in ("HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"):
        lines.append(f"- {category}: {counts[category]}")
    lines.extend(["", "## Exact assignment evidence", "",
                  ("Every measured distance and D–H···A angle has its immutable handle, row ID, AtomRefs, "
                   "field path, native unit and exact numeric value in the JSON sidecar."), ""])
    for row in result["rows"]:
        label = f"{row['row_id']} {row['category']}: {row['distance_A']:.6f} Å"
        if row["DHA_angle_deg"] is not None:
            label += f", {row['DHA_angle_deg']:.6f}° D–H···A"
        lines.append(f"- {label}")
    if not result["rows"]:
        lines.append("- No native assignments (valid empty result).")
    lines.extend(["", "## Derived source coordinates", "",
                  coordinate_provenance["derived_coordinate_policy"],
                  f"Preparation manifest: `{coordinate_provenance['source_manifest_handle']}`."])
    attached = coordinate_provenance["attached_source_sites"]
    if attached:
        lines.extend(["", "Attached ligand source-site mapping (Å):", "",
                      "| SDF atom | Original source AtomRef | Original coordinate (Å) | Discrepancy (Å) |",
                      "| ---: | --- | --- | ---: |"])
        for entry in attached:
            atom = entry["source_atom"]
            residue = atom["residue"]
            identity = (f"model {residue['model_number']} "
                        f"{residue['chain_auth']}:{residue['seq_auth']}{residue['icode']} "
                        f"{residue['resname']}/{atom['atom_name']} "
                        f"site {atom['site_index']}")
            coordinate = ", ".join(f"{value:.6f}" for value in entry["source_coordinate_A"])
            lines.append(f"| {entry['sdf_atom_index']} | {identity} | {coordinate} | "
                         f"{entry['discrepancy_A']:.6f} |")
        lines.append(f"\nMaximum attachment discrepancy: "
                     f"{coordinate_provenance['maximum_attachment_discrepancy_A']:.6f} Å.")
    else:
        lines.append("\nNo existing source atoms were attached; ligand coordinates came from the selected SDF conformer.")
    criteria = result["criteria"]
    lines.extend(["", "## Native method criteria", "",
                  (f"D···A hydrogen-bond distance ≤{criteria['Hbond_distance_A']} Å; "
                   f"D–H···A angle {criteria['Hbond_DHA_angle_deg'][0]}–"
                   f"{criteria['Hbond_DHA_angle_deg'][1]}°."),
                  (f"Hydrophobic, Cationic and Anionic thresholds: "
                   f"{criteria['Hydrophobic_distance_A']}, {criteria['Cationic_distance_A']} and "
                   f"{criteria['Anionic_distance_A']} Å; vicinity cutoff "
                   f"{criteria['vicinity_cutoff_A']} Å."),
                  (f"Exact native SMARTS pairs are in the JSON sidecar; SHA-256 "
                   f"`{criteria['native_smarts_sha256']}`."),
                  "", "## Supplied protein graph annotations", "",
                  f"Stereochemistry policy: {preparation_graph_states['stereochemistry_policy']}",
                  (f"Saved SDF parity/3D audit: {len(preparation_graph_states['stereochemistry_audit'])} "
                   "declared center(s); exact declaration and observed comparison rows are in the JSON sidecar.")])
    states = preparation_graph_states["histidine_states"]
    if states:
        for state in states:
            residue = state["residue"]
            sites = ", ".join(state["ring_h_sites"]) or "none"
            lines.append(f"- Histidine model {residue['model_number']} "
                         f"{residue['chain_auth']}:{residue['seq_auth']}{residue['icode']} "
                         f"{residue['resname']}: supplied ring-H sites {sites}; "
                         f"represented graph state {state['represented_state']}, "
                         f"ring formal charge {state['ring_formal_charge']}; "
                         f"{state['annotation']}.")
    else:
        lines.append("- No histidine residues in the supplied receptor graph.")
    extensions = preparation_graph_states["terminal_extension_inventory"]
    if extensions:
        for extension in extensions:
            residue = extension["residue"]
            lines.append(f"- Terminal extension model {residue['model_number']} "
                         f"{residue['chain_auth']}:{residue['seq_auth']}{residue['icode']} "
                         f"{residue['resname']}: {len(extension['resolved_atoms'])} resolved atoms, "
                         f"{len(extension['attachment_bonds'])} attachment bond(s); "
                         f"exact AtomRefs and bonds are in the JSON sidecar.")
    else:
        lines.append("- No declared terminal extension in the supplied receptor graph.")
    lines.extend(["", "## Scope and limitations", ""])
    lines.extend(f"- {item}" for item in [*result["limitations"], SDF_SCOPE_LIMITATION])
    lines.extend(["- Receptor orders and formal charges were inferred from the supplied explicit-H graph.",
                  "- Supplied protonation/tautomer completeness is acknowledged by the preparer, not independently proven.",
                  "- JSON claims include full source and engine coordinate provenance; render text is rounded only for display.",
                  "", f"JSON claim count: {len(claims)}.", ""])
    return "\n".join(lines)


def build_chemical_report(run: Any, result_handle: str) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        publication = require_completed_chemical_handle(run, result_handle)
        result = validated_result(run.store, result_handle)
        coordinate_provenance = _coordinate_provenance(run.store, result)
        preparation_graph_states = _preparation_graph_states(run.store, result)
        events = list(run.events.read())
        provenance = _provenance(events, result_handle, publication)
        seq = events[-1]["seq"]
        manifest = {"schema": "method_report_manifest@1", "analysis_type": "chemical_interactions",
                    "status": "complete", "render_version": "chemical_markdown@1",
                    "generation_mode": "local_rules_no_egress", "result_handle": result_handle,
                    "result_schema": "chemical_interaction_set@1",
                    "result_sha256": result_handle.rsplit("/", 1)[-1],
                    "chemical_structure_handle": result["chemical_structure_handle"],
                    "graph_handle": result["graph_handle"], "manifest_handle": result["manifest_handle"],
                    "method": result["method"], "dependency_manifest": result["dependency_manifest"],
                    "criteria": result["criteria"], "total": result["total"],
                    "null_result": result["null_result"], "claims": _claims(result_handle, result),
                    "coordinate_provenance": coordinate_provenance,
                    "preparation_graph_states": preparation_graph_states,
                    "snapshot": {"event_seq": seq, "time_utc": events[-1]["ts"],
                                 "run_egress_mode": run.egress_config["mode"]},
                    "provenance": provenance,
                    "limitations": [*result["limitations"], SDF_SCOPE_LIMITATION]}
        markdown = _markdown(result, manifest["claims"], coordinate_provenance,
                             preparation_graph_states)
        produced_by = f"chemical_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by=produced_by, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=produced_by,
                               summary={"result_handle": result_handle,
                                        "analysis_type": "chemical_interactions", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle,
                          markdown_handle=md.handle, result_handle=result_handle,
                          snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle,
                "manifest": manifest, "markdown": markdown}


def saved_chemical_report(run: Any, report_handle: str) -> dict[str, Any]:
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"]) != ("method_report_manifest", "method_report_manifest@1"):
        raise EvidenceError("chemical_report_type")
    report = run.store.load_bounded_json(report_handle, 8 * 1024 * 1024)
    required = {"schema", "analysis_type", "status", "render_version", "generation_mode",
                "result_handle", "result_schema", "result_sha256", "chemical_structure_handle",
                "graph_handle", "manifest_handle", "method", "dependency_manifest", "criteria",
                "total", "null_result", "claims", "coordinate_provenance", "preparation_graph_states",
                "snapshot", "provenance", "limitations",
                "markdown_handle"}
    if (type(report) is not dict or set(report) != required or
            report["schema"] != "method_report_manifest@1" or
            report["analysis_type"] != "chemical_interactions" or report["status"] != "complete" or
            report["render_version"] != "chemical_markdown@1" or
            report["generation_mode"] != "local_rules_no_egress"):
        raise EvidenceError("chemical_report_schema_invalid")
    publication = require_completed_chemical_handle(run, report["result_handle"])
    result = validated_result(run.store, report["result_handle"])
    coordinate_provenance = _coordinate_provenance(run.store, result)
    preparation_graph_states = _preparation_graph_states(run.store, result)
    expected_fields = {"result_schema": "chemical_interaction_set@1",
                       "result_sha256": report["result_handle"].rsplit("/", 1)[-1],
                       "chemical_structure_handle": result["chemical_structure_handle"],
                       "graph_handle": result["graph_handle"], "manifest_handle": result["manifest_handle"],
                       "method": result["method"], "dependency_manifest": result["dependency_manifest"],
                       "criteria": result["criteria"], "total": result["total"],
                       "null_result": result["null_result"], "claims": _claims(report["result_handle"], result),
                       "coordinate_provenance": coordinate_provenance,
                       "preparation_graph_states": preparation_graph_states,
                       "limitations": [*result["limitations"], SDF_SCOPE_LIMITATION]}
    if any(canonical_json(report[key]) != canonical_json(value) for key, value in expected_fields.items()):
        raise EvidenceError("chemical_report_claim_mismatch")
    events = list(run.events.read())
    provenance = _provenance(events, report["result_handle"], publication)
    if report["provenance"] != provenance:
        raise EvidenceError("chemical_report_provenance_mismatch")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != {"event_seq", "time_utc", "run_egress_mode"} or
            type(snapshot["event_seq"]) is not int or snapshot["event_seq"] < provenance["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"}):
        raise EvidenceError("chemical_report_snapshot_invalid")
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("chemical_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("chemical_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("chemical_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, 8 * 1024 * 1024).decode()
    if markdown != _markdown(result, report["claims"], coordinate_provenance,
                             preparation_graph_states):
        raise EvidenceError("chemical_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle,
            "manifest": report, "markdown": markdown}
