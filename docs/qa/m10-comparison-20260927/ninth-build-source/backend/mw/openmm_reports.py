"""Evidence-bound immutable report for the fixed OpenMM potential protocol."""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .core.errors import ToolFailure
from .reports import EvidenceError, _md

FIELDS = ("before_kJ_mol", "after_kJ_mol", "potential_change_kJ_mol")


def _typed(store: Any, handle: str, kind: str, schema: str) -> Any:
    meta = store.meta(handle)
    if (meta["kind"], meta["schema"]) != (kind, schema):
        raise EvidenceError("wrong_openmm_evidence_type")
    return store.load(handle)


def validated_openmm(run: Any, handle: str) -> dict[str, Any]:
    """Reopen and validate exactly the same native bundle checked at publication."""
    from .core.handles import canonical_json
    from .jobs.queue import idempotency_key
    from .openmm_bundle import PREPARATION_FIELDS, _integer, _sha, validate_native

    try:
        data = _typed(run.store, handle, "openmm_minimization", "openmm_protein_minimization@1")
        if data["schema"] != "openmm_protein_minimization@1":
            raise EvidenceError("wrong_openmm_method")
        prepared = _typed(run.store, data["structure"], "prepared_structure", "prepared_structure@1")
        source_manifest = _typed(run.store, prepared["manifest"], "preparation_manifest", "preparation_manifest@1")
        _typed(run.store, data["source_handle"], "structure_source", "structure_source@1")
        prep = _typed(run.store, data["preparation_manifest"], "openmm_preparation_manifest", "openmm_preparation_manifest@1")
        system = _typed(run.store, data["system_xml"], "openmm_system_xml", "openmm_system_xml@1")
        initial = _typed(run.store, data["input_coordinates"], "openmm_input_coordinates", "openmm_input_coordinates@1")
        final = _typed(run.store, data["final_coordinates"], "openmm_final_coordinates", "openmm_final_coordinates@1")
        minimized = _typed(run.store, data["minimized_structure"], "openmm_minimized_structure", "openmm_minimized_structure@1")
        selected = prep["selected"]
        if (source_manifest["source_handle"] != data["source_handle"] or
                prep["system_xml"] != data["system_xml"] or prep["system_xml_sha256"] != data["system_xml_sha256"] or
                prep["topology_sha256"] != data["topology_sha256"] or
                prep["input_positions_A"] != data["input_positions_A"] or
                prep["input_coordinates"] != data["input_coordinates"] or
                minimized != {"coordinates": data["final_coordinates"], "manifest": data["preparation_manifest"],
                              "model_number": selected["model_number"], "source_prepared": data["structure"]}):
            raise EvidenceError("openmm_bundle_link_mismatch")
        native = {"schema": "openmm_worker_output@1", "method": data["method"],
                  "selected_sha256": prep["selected_sha256"], "system_xml": system.decode(),
                  "system_xml_sha256": data["system_xml_sha256"], "topology_sha256": data["topology_sha256"],
                  "heavy_atoms": data["heavy_atom_count"], "added_hydrogens": prep["added_hydrogens"],
                  "atom_mapping": prep["atom_mapping"], "residue_mapping": prep["residue_mapping"],
                  "source_bonds": prep["source_bonds"], "final_bonds": prep["final_bonds"],
                  "protonation_variants": prep["protonation_variants"], "disulfide_bonds": prep["disulfide_bonds"],
                  "input_cif": initial.decode(), "final_cif": final.decode(),
                  "input_positions_A": data["input_positions_A"], "final_positions_A": data["final_positions_A"],
                  "before_kJ_mol": data["before_kJ_mol"], "after_kJ_mol": data["after_kJ_mol"],
                  "potential_change_kJ_mol": data["potential_change_kJ_mol"],
                  "convergence": data["convergence"], "iterations": data["iterations"]}
        validate_native(run.store, selected, native, system)
        if (data["structure"] != selected["structure"] or data["source_handle"] != selected["source_handle"] or
                data["method"] != selected["method"] or not _integer(data["seed"]) or
                data["seed"] != selected["seed"] or data["excluded"] != selected["excluded"] or
                data["source_hydrogens_removed"] != selected["source_hydrogens_removed"] or
                not _integer(data["atom_count"], 1) or data["atom_count"] != len(prep["atom_mapping"]) or
                not _integer(data["heavy_atom_count"], 1) or
                not _integer(data["added_hydrogen_count"]) or
                data["added_hydrogen_count"] != len(prep["added_hydrogens"]) or
                _sha(system) != data["system_xml_sha256"]):
            raise EvidenceError("openmm_result_mapping_mismatch")
        events = list(run.events.read())
        jobs = [e["job"] for e in events if e["type"] == "job_submitted" and e["job"]["job_id"] == data["job_id"]]
        if len(jobs) != 1:
            raise EvidenceError("openmm_job_missing")
        job = jobs[0]
        if (job["run_id"] != run.run_id or job["protocol_id"] != "openmm_protein_minimize" or
                job["fixture_only"] is not False or job["selected"] != selected or job["seed"] != selected["seed"] or
                job["input_handles"] != [selected["structure"]] or
                job["parameters"] != {"structure": selected["structure"], "selection_policy": "protein_only",
                                      "hydrogen_policy": "rebuild_pH7"} or
                job["call_key"] != idempotency_key("openmm_protein_minimize", "openmm_protein_minimize_v1",
                                                     {"selected": selected, "parameters": job["parameters"]})):
            raise EvidenceError("openmm_job_mismatch")
        attempt = data["attempt_id"]
        def one(kind: str) -> dict:
            found = [e for e in events if e["type"] == kind and e.get("attempt_id") == attempt]
            if len(found) != 1:
                raise EvidenceError("openmm_attempt_event_missing")
            return found[0]
        reserved, intent, preparation, candidate, clean, terminal = (one(kind) for kind in
            ("budget_reserved", "job_dispatch_intent", "job_preparation_recorded", "job_result_candidate",
             "job_cleanup_verified", "job_terminal"))
        checkpoint = {"schema": "openmm_preparation_checkpoint@1",
                      **{key: native[key] for key in PREPARATION_FIELDS}}
        if (reserved["root_call_id"] != job["root_call_id"] or reserved["tool"] != job["tool_id"] or
                reserved["expensive_calls"] != 1 or
                any(e["type"] == "budget_reserved" and e.get("attempt_id") == attempt and e is not reserved for e in events) or
                any(e["job_id"] != job["job_id"] for e in (intent, preparation, candidate, clean, terminal)) or
                preparation["handles"] != {"manifest": data["preparation_manifest"],
                                           "system_xml": data["system_xml"],
                                           "input_coordinates": data["input_coordinates"]} or
                preparation["checkpoint_sha256"] != _sha(canonical_json(checkpoint)) or
                clean["group_empty"] is not True or candidate["output_handles"] != [handle] or
                terminal["output_handles"] != [handle] or terminal["status"] != "done" or
                not (reserved["seq"] < intent["seq"] < clean["seq"] < preparation["seq"] <
                     candidate["seq"] < terminal["seq"])):
            raise EvidenceError("openmm_attempt_provenance_mismatch")
        return data
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, UnicodeError, OSError,
            RuntimeError, OverflowError, StopIteration, ToolFailure, ET.ParseError) as exc:
        raise EvidenceError("unresolved_openmm_evidence") from exc

def claim(handle: str, data: dict[str, Any], field: str) -> dict[str, Any]:
    if field not in FIELDS:
        raise EvidenceError("openmm_field_not_allowed")
    exact = data[field]
    rounded = Decimal(str(exact)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"source_handle": handle, "source_kind": "openmm_minimization", "source_schema": "openmm_protein_minimization@1",
            "source_sha256": handle.rsplit("/", 1)[-1], "field_path": field, "subject": {
                "prepared_handle": data["structure"], "job_id": data["job_id"], "attempt_id": data["attempt_id"]},
            "quantity": field, "unit": "kJ/mol", "exact_value": exact,
            "rendered_value": f"{abs(rounded) if rounded == 0 else rounded:.2f}", "rounding": "half_up_2dp"}


def validate_openmm_claim(run: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proposed, dict) or proposed.get("field_path") not in FIELDS:
        raise EvidenceError("openmm_claim_shape")
    data = validated_openmm(run, proposed["source_handle"])
    if proposed != claim(proposed["source_handle"], data, proposed["field_path"]):
        raise EvidenceError("openmm_claim_binding")
    return proposed


def validated_minimized_structure(run: Any, structure_handle: str) -> dict[str, Any]:
    """Resolve a displayed protein-only model through its completed result bundle."""
    _typed(run.store, structure_handle, "openmm_minimized_structure", "openmm_minimized_structure@1")
    for event in run.events.read():
        if event["type"] != "job_terminal" or event["status"] != "done":
            continue
        for result_handle in event["output_handles"]:
            meta = run.store.meta(result_handle)
            if (meta["kind"], meta["schema"]) != ("openmm_minimization", "openmm_protein_minimization@1"):
                continue
            result = run.store.load(result_handle)
            if result.get("minimized_structure") == structure_handle:
                return validated_openmm(run, result_handle)
    raise EvidenceError("openmm_minimized_result_missing")


def _markdown(manifest: dict[str, Any]) -> str:
    claims = {item["field_path"]: item["rendered_value"] for item in manifest["claims"]}
    method = manifest["method"]
    lines = ["# OpenMM protein-only potential minimization", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}", f"Prepared input: {_md(manifest['prepared_handle'])}",
             f"Source: {_md(manifest['source_handle'])}", f"Job: {_md(manifest['job_id'])}", "",
             "## Fixed method", "", "- Selection: protein_only; hydrogen policy: rebuild_pH7",
             "- Force field: amber14-all.xml + implicit/gbn2.xml; NoCutoff; no constraints; CPU Threads=1",
             "- pH: 7.0; tolerance: 10 kJ/mol/nm; maximum iterations: 50; convergence not claimed",
             f"- OpenMM distribution: {_md(method['distribution_version'])}; engine build: {_md(method['engine_build'])}",
             f"- Force-field SHA-256: {_md(method['forcefield_files_sha256'])}", "",
             f"- Construction RNG seed: {_md(manifest['seed'])}", "",
             "## Actual potential (kJ/mol)", "",
             f"- Before: {claims['before_kJ_mol']} kJ/mol", f"- After: {claims['after_kJ_mol']} kJ/mol",
             f"- Change (after − before): {claims['potential_change_kJ_mol']} kJ/mol", "",
             "## Input and provenance", "",
             f"- Heavy atoms: {_md(manifest['heavy_atom_count'])}; added hydrogens: {_md(manifest['added_hydrogen_count'])}",
             f"- Excluded components: {_md(len(manifest['excluded']))}",
             f"- Hydrogenated input coordinates: {_md(manifest['input_coordinates'])}",
             f"- Minimized protein coordinates: {_md(manifest['minimized_structure'])}",
             f"- System XML: {_md(manifest['system_xml'])}",
             f"- System XML SHA-256: {_md(manifest['system_xml_sha256'])}",
             f"- Topology SHA-256: {_md(manifest['topology_sha256'])}"]
    for item in manifest["excluded"]:
        lines.append(f"- Excluded: {_md(item['residue'])} ({_md(item['reason'])})")
    lines.extend(["", "Potential change under this fixed implicit-solvent model is not binding energy, ΔΔG, affinity, or experimental stability.",
                  "GBn2 is an implicit-solvent model. A returned minimization does not establish convergence.",
                  "", "Exact values, full atom mapping, protonation variants, exclusions and method settings are in the JSON manifest.", ""])
    return "\n".join(lines)


def build_openmm_report(run: Any, result_handle: str) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        data = validated_openmm(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest = {"schema": "method_report_manifest@1", "analysis_type": "openmm_protein_minimize",
                    "status": "complete", "render_version": "openmm_markdown@1",
                    "generation_mode": "local_rules_no_egress", "result_handle": result_handle,
                    "prepared_handle": data["structure"], "source_handle": data["source_handle"],
                    "method": data["method"], "job_id": data["job_id"], "attempt_id": data["attempt_id"],
                    "seed": data["seed"],
                    "preparation_manifest": data["preparation_manifest"],
                    "system_xml": data["system_xml"],
                    "input_coordinates": data["input_coordinates"], "minimized_structure": data["minimized_structure"],
                    "system_xml_sha256": data["system_xml_sha256"], "topology_sha256": data["topology_sha256"],
                    "heavy_atom_count": data["heavy_atom_count"], "added_hydrogen_count": data["added_hydrogen_count"],
                    "excluded": data["excluded"], "source_hydrogens_removed": data["source_hydrogens_removed"],
                    "atom_mapping": run.store.load(data["preparation_manifest"])["atom_mapping"],
                    "residue_mapping": run.store.load(data["preparation_manifest"])["residue_mapping"],
                    "protonation_variants": run.store.load(data["preparation_manifest"])["protonation_variants"],
                    "input_positions_A": data["input_positions_A"], "final_positions_A": data["final_positions_A"],
                    "claims": [claim(result_handle, data, field) for field in FIELDS],
                    "snapshot": {"event_seq": seq, "time_utc": events[-1]["ts"],
                                 "run_egress_mode": run.egress_config["mode"]}}
        markdown = _markdown(manifest)
        call_id = "method_report_" + uuid.uuid4().hex
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md", produced_by=call_id)
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=call_id, summary={"result_handle": result_handle, "analysis_type": "openmm_protein_minimize"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_openmm_report(run: Any, report_handle: str) -> dict[str, Any]:
    report = _typed(run.store, report_handle, "method_report_manifest", "method_report_manifest@1")
    if report.get("schema") != "method_report_manifest@1" or report.get("analysis_type") != "openmm_protein_minimize":
        raise EvidenceError("wrong_openmm_report")
    md = _typed(run.store, report["markdown_handle"], "report_markdown", "report_markdown@1")
    created = [e for e in run.events.read() if e["type"] == "method_report_created" and
               e["report_handle"] == report_handle]
    if (len(created) != 1 or created[0]["markdown_handle"] != report["markdown_handle"] or
            created[0]["result_handle"] != report["result_handle"] or
            created[0]["snapshot_event_seq"] != report["snapshot"]["event_seq"]):
        raise EvidenceError("openmm_report_event_missing")
    data = validated_openmm(run, report["result_handle"])
    if report["claims"] != [claim(report["result_handle"], data, field) for field in FIELDS]:
        raise EvidenceError("openmm_report_claim_mismatch")
    prep = _typed(run.store, data["preparation_manifest"], "openmm_preparation_manifest", "openmm_preparation_manifest@1")
    expected = {"schema": "method_report_manifest@1", "analysis_type": "openmm_protein_minimize",
                "status": "complete", "render_version": "openmm_markdown@1",
                "generation_mode": "local_rules_no_egress", "result_handle": report["result_handle"],
                "prepared_handle": data["structure"], "source_handle": data["source_handle"],
                "method": data["method"], "job_id": data["job_id"], "attempt_id": data["attempt_id"],
                "seed": data["seed"],
                "preparation_manifest": data["preparation_manifest"], "system_xml": data["system_xml"],
                "input_coordinates": data["input_coordinates"], "minimized_structure": data["minimized_structure"],
                "system_xml_sha256": data["system_xml_sha256"], "topology_sha256": data["topology_sha256"],
                "heavy_atom_count": data["heavy_atom_count"], "added_hydrogen_count": data["added_hydrogen_count"],
                "excluded": data["excluded"], "source_hydrogens_removed": data["source_hydrogens_removed"],
                "atom_mapping": prep["atom_mapping"], "residue_mapping": prep["residue_mapping"],
                "protonation_variants": prep["protonation_variants"],
                "input_positions_A": data["input_positions_A"], "final_positions_A": data["final_positions_A"],
                "claims": [claim(report["result_handle"], data, field) for field in FIELDS],
                "snapshot": report["snapshot"], "markdown_handle": report["markdown_handle"]}
    events = list(run.events.read())
    snapshot = report["snapshot"]
    if (report != expected or snapshot["run_egress_mode"] != run.egress_config["mode"] or
            not any(e["seq"] == snapshot["event_seq"] and e["ts"] == snapshot["time_utc"] and
                    e["seq"] < created[0]["seq"] for e in events)):
        raise EvidenceError("openmm_report_source_mismatch")
    markdown = md.decode()
    if markdown != _markdown({key: value for key, value in report.items() if key != "markdown_handle"}):
        raise EvidenceError("openmm_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": report["markdown_handle"], "manifest": report, "markdown": markdown}
