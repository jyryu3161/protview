"""Immutable, field-cited method reports for completed fpocket ``pocket_set@1`` results (``pocket_report@1``).

The report is a ``method_report_manifest@1`` with ``analysis_type: "pocket_detection"``. Every number it
states is a claim bound to one immutable field: source handle, allowed field path, row selector (native
rank), unit, exact stored value and the rendered text. The only derived values are the pocket count
(``count(pockets)``) and the lining-residue count (``count_distinct`` over the 7-field residue identity);
``display_center`` is a ProtView display value (arithmetic mean of stored sphere centers), never an
fpocket value. Creating, reopening and downloading never run fpocket or recompute a scientific quantity:
saved reads re-validate the stored pocket_set and compare every claim and the Markdown byte for byte.
"""
from __future__ import annotations

import math
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .core.handles import canonical_json
from .pocket_bundle import PocketEvidenceError, capability_snapshot, capability_snapshot_valid, validated_pocket_set
from .pocket_input import EXCLUDED_CATEGORIES, RESIDUE_FIELDS
from .pocket_output import DESCRIPTOR_KEYS, DETECTOR_SPECIFIC_NOTE, DISPLAY_CENTER_METHOD
from .reports import EvidenceError, _md, _ref, resume_linked_report
from .runtime.orchestrator import link_fields

ANALYSIS_TYPE = "pocket_detection"
RENDER_VERSION = "pocket_markdown@2"
# Stored reports keep re-opening with the renderer that wrote them: @1 labelled the residue-name mapping
# "Histidine name mapping" (before the four Amber names were admitted); @2 says "Residue name mapping".
MAPPING_LABELS = {"pocket_markdown@1": "Histidine name mapping", RENDER_VERSION: "Residue name mapping"}
REPORT_BYTES = 8 * 1024 * 1024  # same bound the report list/selected routes use
EVIDENCE_STATEMENT = ("fpocket pocket candidates, ranks and scores are not binding-site, affinity or druggability "
                      "evidence (결합 부위·친화도·druggability 증거 아님).")
DRUGGABILITY_WARNING = ("Druggability Score is an fpocket-specific score, not druggability evidence "
                        f"({DETECTOR_SPECIFIC_NOTE}).")
DISPLAY_CENTER_NOTE = ("Display center: arithmetic mean of the stored alpha-sphere centers, computed by ProtView "
                       "for display only; it is not an fpocket value.")
REPORT_LIMITATIONS = [EVIDENCE_STATEMENT, DRUGGABILITY_WARNING, DISPLAY_CENTER_NOTE]
# Fixed template statements; nothing else may carry a number in this report.
STATEMENT_IDS = ("pocket_count", "pocket_descriptor", "lining_residue_count", "display_center_coordinate",
                 "excluded_site_count", "transport_count", "quantization")
CLAIM_KEYS = frozenset({"statement_id", "source_handle", "source_kind", "source_schema", "source_sha256",
                        "field_path", "row_selector", "subject", "quantity", "unit", "exact_value",
                        "rendered_value", "rounding", "operation"})
DESCRIPTOR_LABELS = {"score": "Score", "druggability_score": "Druggability Score",
                     "alpha_sphere_count": "Alpha spheres", "total_sasa_A2": "Total SASA",
                     "volume_A3": "Volume"}
UNIT_TEXT = {"dimensionless": "", "count": "", "A2": " Å²", "A3": " Å³", "angstrom": " Å"}
LEGACY_SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode"}
SNAPSHOT_KEYS = LEGACY_SNAPSHOT_KEYS | {"capability", "budget"}
BUDGET_AXES = {"wall_clock_s", "expensive_calls", "external_tokens", "usd"}
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", "source_handle", "source_kind", "model_number", "preparation_handle", "detector_input_handle",
    "native_output_handle", "transport_pdb_sha256", "selection", "resname_mapping", "quantization", "method",
    "units", "total_count", "null_result", "completeness", "pockets", "raw_file_hashes", "claims", "provenance",
    "evidence_statement", "druggability_warning", "limitations", "snapshot", "markdown_handle"})


def _budget_snapshot_valid(value: Any) -> bool:
    def amount(number: Any) -> bool:
        return type(number) in (int, float) and math.isfinite(number) and number >= 0

    return (type(value) is dict and set(value) == BUDGET_AXES and
            all(type(axis) is dict and set(axis) == {"used", "limit"} and amount(axis["used"]) and
                amount(axis["limit"]) for axis in value.values()))


def _render(value: Any, rounding: str) -> str:
    if type(value) is bool or type(value) not in (int, float):
        raise EvidenceError("pocket_claim_value_type")
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("pocket_claim_integer_expected")
        return str(value)
    if rounding == "exact":
        return repr(value)
    if rounding == "native_3dp":
        rounded = Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return f"{abs(rounded) if rounded == 0 else rounded:.3f}"
    raise EvidenceError("pocket_claim_rounding")


def _identity(residue: dict[str, Any]) -> bytes:
    if type(residue) is not dict or set(residue) != set(RESIDUE_FIELDS):
        raise EvidenceError("pocket_residue_identity")
    return canonical_json([residue[field] for field in RESIDUE_FIELDS])


def _claim(statement_id: str, handle: str, kind: str, path: str, rank: int | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None) -> dict[str, Any]:
    return {"statement_id": statement_id, "source_handle": handle, "source_kind": kind,
            "source_schema": f"{kind}@1", "source_sha256": handle.rsplit("/", 1)[-1], "field_path": path,
            "row_selector": None if rank is None else {"rank": rank}, "subject": subject, "quantity": quantity,
            "unit": unit, "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation}


def _claims(handle: str, content: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Every numeric statement of the report, each bound to one exact stored field."""
    base = {"pocket_set_handle": handle}
    pockets = content["pockets"]
    if content["total_count"] != len(pockets):
        raise EvidenceError("pocket_count_mismatch")
    claims = [_claim("pocket_count", handle, "pocket_set", "total_count", None, base, "pocket_count", "count",
                     content["total_count"], "integer", "count(pockets)")]
    for index, pocket in enumerate(pockets):
        rank = pocket["rank"]
        subject = {**base, "rank": rank}
        for key in DESCRIPTOR_KEYS:
            entry = pocket["descriptors"][key]
            claims.append(_claim("pocket_descriptor", handle, "pocket_set",
                                 f"pockets[{index}].descriptors.{key}.value", rank,
                                 {**subject, "native_name": entry["native_name"]}, key, entry["unit"],
                                 entry["value"], "integer" if entry["unit"] == "count" else "native_3dp", None))
        distinct = len({_identity(residue) for residue in pocket["lining_residues"]})
        claims.append(_claim("lining_residue_count", handle, "pocket_set", f"pockets[{index}].lining_residues",
                             rank, subject, "lining_residue_count", "count", distinct, "integer",
                             "count_distinct(residue identity: " + ", ".join(RESIDUE_FIELDS) + ")"))
        center = pocket["display_center"]
        if center.get("method") != DISPLAY_CENTER_METHOD:
            raise EvidenceError("pocket_display_center_method")
        for axis in ("x_A", "y_A", "z_A"):
            claims.append(_claim("display_center_coordinate", handle, "pocket_set",
                                 f"pockets[{index}].display_center.{axis}", rank, subject,
                                 f"display_center_{axis}", "angstrom", center[axis], "native_3dp",
                                 DISPLAY_CENTER_METHOD))
    detector = content["detector_input_handle"]
    for category in EXCLUDED_CATEGORIES:
        claims.append(_claim("excluded_site_count", detector, "pocket_detector_input", f"excluded_counts.{category}",
                             None, base, f"excluded_{category}_sites", "count",
                             manifest["excluded_counts"][category], "integer", None))
    for key in ("heavy_atoms", "residues", "chains"):
        claims.append(_claim("transport_count", detector, "pocket_detector_input", f"counts.{key}", None, base,
                             f"transport_{key}", "count", manifest["counts"][key], "integer", None))
    for key in ("transport_precision_A", "max_axis_discrepancy_A"):
        claims.append(_claim("quantization", detector, "pocket_detector_input", f"quantization.{key}", None, base,
                             key, "angstrom", manifest["quantization"][key], "exact", None))
    return claims


def _validated(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        return validated_pocket_set(run, handle)
    except PocketEvidenceError as exc:
        raise EvidenceError(f"pocket_set_invalid: {exc}") from exc


def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated pocket_set (not snapshot/markdown handle)."""
    content, manifest, source = _validated(run, handle)
    try:
        return {
            "schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
            "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
            "result_schema": "pocket_set@1", "result_sha256": handle.rsplit("/", 1)[-1],
            **{key: content[key] for key in ("source_handle", "source_kind", "model_number", "preparation_handle",
                                             "detector_input_handle", "native_output_handle", "method", "units",
                                             "total_count", "null_result", "completeness", "raw_file_hashes")},
            "transport_pdb_sha256": manifest["transport_pdb_sha256"],
            "selection": {"selected_chains": manifest["selected_chains"], "chain_map": manifest["chain_map"],
                          "excluded_counts": manifest["excluded_counts"], "category_rule": manifest["category_rule"],
                          "counts": manifest["counts"]},
            "resname_mapping": manifest["resname_mapping"], "quantization": manifest["quantization"],
            "pockets": [{"rank": pocket["rank"], "descriptors": pocket["descriptors"],
                         "lining_residues": pocket["lining_residues"], "display_center": pocket["display_center"]}
                        for pocket in content["pockets"]],
            "claims": _claims(handle, content, manifest),
            "provenance": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                           "protocol_id": source["job"]["protocol_id"], "tool_id": source["job"]["tool_id"],
                           "created_event_seq": source["created_seq"], "completed_event_seq": source["published_seq"]},
            "evidence_statement": EVIDENCE_STATEMENT, "druggability_warning": DRUGGABILITY_WARNING,
            "limitations": [*content["limitations"], *REPORT_LIMITATIONS]}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("pocket_report_evidence_unresolved") from exc


def _match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("pocket_claim_shape")
    if proposed["statement_id"] not in STATEMENT_IDS:
        raise EvidenceError("pocket_claim_statement_not_allowed")
    expected = {(claim["statement_id"], claim["field_path"]): claim for claim in expected_claims}
    match = expected.get((proposed["statement_id"], proposed["field_path"]))
    if match is None:
        raise EvidenceError("pocket_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("pocket_claim_binding_mismatch")
    return proposed


def validate_pocket_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    """Accept a claim only if it equals the claim built from that exact field of this pocket_set."""
    return _match_claim(_expected(run, result_handle)["claims"], proposed)


def _residues(residues: list[dict[str, Any]]) -> str:
    return "; ".join(_md(_ref(residue)) for residue in residues)


def render_pocket_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every number is the rendered text of a bound claim."""
    claims = {claim["field_path"]: claim["rendered_value"] for claim in manifest["claims"]}
    method = manifest["method"]
    selection = manifest["selection"]
    quantization = manifest["quantization"]
    provenance = manifest["provenance"]
    lines = ["# Pocket candidates (fpocket)", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             (f"Source: {_md(manifest['source_handle'])} ({_md(manifest['source_kind'])}, "
             f"model {_md(manifest['model_number'])})"),
             f"Preparation manifest: {_md(manifest['preparation_handle'])}",
             f"Detector input: {_md(manifest['detector_input_handle'])}",
             f"Native output evidence: {_md(manifest['native_output_handle'])}",
             f"Job: {_md(provenance['job_id'])}, attempt {_md(provenance['attempt_id'])}", "",
             f"**{_md(EVIDENCE_STATEMENT)}**", "", "## Result", "",
             f"- Pocket candidates: {claims['total_count']} (count of stored pockets)",
             f"- Result completeness: {_md(manifest['completeness'])}"]
    if manifest["null_result"]:
        lines.append("- " + _md("fpocket returned no pocket candidates for this input; this is a valid empty result "
                                "(scientific_null), not a failure."))
    lines.extend(["", "## Input projection", "",
                  f"- Selected chains (chain\\_auth): {_md(', '.join(selection['selected_chains']))}",
                  "- Transport chain map: " + ", ".join(
                      f"{_md(item['chain_auth'])} → {_md(item['synthetic_chain'])}"
                      for item in selection["chain_map"]),
                  "- Excluded sites: " + ", ".join(
                      f"{_md(category)} {claims['excluded_counts.' + category]}"
                      for category in EXCLUDED_CATEGORIES),
                  (f"- Transported heavy atoms: {claims['counts.heavy_atoms']}; residues: "
                  f"{claims['counts.residues']}; chains: {claims['counts.chains']}")])
    for category, rule in selection["category_rule"].items():
        lines.append(f"- Category rule {_md(category)}: {_md(rule)}")
    label = MAPPING_LABELS[manifest["render_version"]]
    if manifest["resname_mapping"]:
        for item in manifest["resname_mapping"]:
            lines.append(f"- {label}: {_md(_ref(item['residue']))} sent as "
                         f"{_md(item['transport_resname'])} (original {_md(item['original_resname'])})")
    else:
        lines.append(f"- {label}: none needed")
    lines.extend([(f"- Quantization: {_md(quantization['coordinate_field'])} coordinates, "
                  f"{_md(quantization['decimals'])} decimals; transport precision "
                  f"{claims['quantization.transport_precision_A']} Å; maximum axis discrepancy "
                  f"{claims['quantization.max_axis_discrepancy_A']} Å"),
                  f"- Transport PDB SHA-256: {_md(manifest['transport_pdb_sha256'])}",
                  "", "## Method", "",
                  (f"- Engine: {_md(method['engine'])} {_md(method['release'])}, build {_md(method['build'])}; "
                  f"observed banner: {_md(method['observed_banner'])}"),
                  f"- Package SHA-256: {_md(method['package_sha256'])}",
                  f"- Executable SHA-256: {_md(method['executable_sha256'])}",
                  f"- Parser: {_md(method['parser_version'])}",
                  f"- Arguments: {_md(' '.join(method['argv']))}",
                  (f"- Seed control: {_md(method['seed_control'])}; fresh execution deterministic: "
                  f"{_md(str(method['fresh_execution_deterministic']).lower())}")])
    for entry in method["effective_parameters"]["effective_parameters"]:
        unit = f" {entry['unit']}" if entry.get("unit") else ""
        lines.append(f"- Parameter {_md(entry['field'])} = {_md(entry['value'])}"
                     f"{_md(unit)} ({_md(entry['source'])})")
    lines.extend([("- Recipe provenance, native raw file hashes and the full effective-parameter record are in the "
                  "JSON download."), "", "## Pocket candidates (native rank order)", ""])
    if manifest["pockets"]:
        header = " | ".join(DESCRIPTOR_LABELS[key] + (f" ({UNIT_TEXT[manifest['units'][key]].strip()})"
                                                      if UNIT_TEXT[manifest["units"][key]] else "")
                            for key in DESCRIPTOR_KEYS)
        lines.extend([f"| Rank | {header} | Lining residues | Display center x, y, z (Å) |",
                      "| ---: |" + " ---: |" * len(DESCRIPTOR_KEYS) + " ---: | --- |"])
        for index, pocket in enumerate(manifest["pockets"]):
            prefix = f"pockets[{index}]"
            values = " | ".join(claims[f"{prefix}.descriptors.{key}.value"] for key in DESCRIPTOR_KEYS)
            center = ", ".join(claims[f"{prefix}.display_center.{axis}"] for axis in ("x_A", "y_A", "z_A"))
            lines.append(f"| {_md(pocket['rank'])} | {values} | {claims[prefix + '.lining_residues']} | "
                         f"{center} |")
        lines.extend(["", f"- {_md(DRUGGABILITY_WARNING)}", f"- {_md(DISPLAY_CENTER_NOTE)}",
                      "- Lining residues: count of distinct 7\\-field residue identities of the mapped lining atoms.",
                      "", "### Lining residues", ""])
        for pocket in manifest["pockets"]:
            lines.append(f"- Rank {_md(pocket['rank'])}: {_residues(pocket['lining_residues'])}")
    else:
        lines.append("- None (valid empty result).")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_md(item)}" for item in manifest["limitations"])
    lines.extend(["", ("Exact values, units, field paths and rank selectors for every number are in the JSON "
                  f"download ({len(manifest['claims'])} claims)."), ""])
    return "\n".join(lines)


def build_pocket_report(run: Any, result_handle: str, *, execution_link: Any = None) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        existing = resume_linked_report(run, execution_link, event_type="method_report_created",
                                        source_field="result_handle", source_handle=result_handle,
                                        saved=saved_pocket_report, builder="pocket")
        if existing is not None:
            return existing
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        # Capability, budget and egress state as of this event sequence (business rules: reports).
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_pocket_report(manifest)
        # A stored report must stay re-openable under the saved-read bound; refuse before storing anything.
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("pocket_report_too_large")
        produced_by = f"pocket_report_{uuid.uuid4().hex}"
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


def saved_pocket_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored pocket report without running fpocket or recomputing anything scientific."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("pocket_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or
            report["analysis_type"] != ANALYSIS_TYPE or type(report["result_handle"]) is not str or
            report["render_version"] not in MAPPING_LABELS):
        raise EvidenceError("pocket_report_schema_invalid")
    expected = {**_expected(run, report["result_handle"]), "render_version": report["render_version"]}
    if type(report["claims"]) is not list:
        raise EvidenceError("pocket_report_claims_invalid")
    for claim in report["claims"]:
        _match_claim(expected["claims"], claim)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"pocket_report_field_mismatch: {key}")
    events = list(run.events.read())
    snapshot = report["snapshot"]
    # Reports stored before the capability/budget snapshot keep exactly the three legacy keys.
    if (type(snapshot) is not dict or set(snapshot) not in (LEGACY_SNAPSHOT_KEYS, SNAPSHOT_KEYS) or
            type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            (set(snapshot) == SNAPSHOT_KEYS and not (capability_snapshot_valid(snapshot["capability"]) and
                                                     _budget_snapshot_valid(snapshot["budget"])))):
        raise EvidenceError("pocket_report_snapshot_invalid")
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("pocket_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("pocket_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("pocket_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_pocket_report(report):
        raise EvidenceError("pocket_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
