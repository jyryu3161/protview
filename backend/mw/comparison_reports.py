"""Immutable field-cited local reports for M10 geometric results."""
from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np

from .core.errors import ToolFailure
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _provenance, resume_linked_report
from .runtime.orchestrator import link_fields
from .tools.comparison import RANK_ABSOLUTE, RANK_RELATIVE, AtomRefV1, atom_rows

RESULTS = {"atom_distance": ("atom_distance", "atom_distance@1"),
           "rigid_alignment": ("rigid_alignment", "rigid_alignment@1")}


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("comparison_nonfinite_or_non_numeric")
    return float(value)


def _nonnegative(value: Any) -> float:
    checked = _number(value)
    if checked < 0:
        raise EvidenceError("comparison_negative_measurement")
    return checked


def _vector(value: Any, length: int) -> np.ndarray:
    if type(value) is not list or len(value) != length:
        raise EvidenceError("comparison_vector_shape")
    return np.asarray([_number(item) for item in value], dtype=np.float64)


def _close(actual: Any, expected: Any, label: str, tolerance: float = 1e-10) -> None:
    a = float(actual) if isinstance(actual, np.floating) else _number(actual)
    e = float(expected) if isinstance(expected, np.floating) else _number(expected)
    if not math.isclose(a, e, rel_tol=tolerance, abs_tol=tolerance):
        raise EvidenceError(f"comparison_{label}_mismatch")


def _catalog(store: Any, handle: str) -> dict[str, Any]:
    try:
        return atom_rows(store, handle)
    except (ToolFailure, KeyError, ValueError, TypeError) as exc:
        raise EvidenceError("comparison_source_invalid") from exc


def _site(catalog: dict[str, Any], proposed: Any, coordinate: Any,
          *, ca_protein: bool = False) -> dict[str, Any]:
    if type(proposed) is not dict:
        raise EvidenceError("comparison_atom_source_mismatch")
    try:
        normalized = AtomRefV1.model_validate(proposed, strict=True).model_dump()
    except ValueError as exc:
        raise EvidenceError("comparison_atom_identity_invalid") from exc
    if normalized != proposed or proposed["structure_handle"] != catalog["structure_handle"]:
        raise EvidenceError("comparison_atom_source_mismatch")
    index = proposed["site_index"]
    rows = catalog["rows"]
    if index < 0 or index >= len(rows) or rows[index]["ref"] != proposed:
        raise EvidenceError("comparison_atom_identity_mismatch")
    row = rows[index]
    if (type(coordinate) is not list or coordinate != row["coordinate_A"] or
            not np.isfinite(_vector(coordinate, 3)).all()):
        raise EvidenceError("comparison_coordinate_mismatch")
    if ca_protein and (not row["protein"] or row["ref"]["atom_name"] != "CA"):
        raise EvidenceError("comparison_nonprotein_or_non_ca")
    return row


def _check_gram_spectrum(matrix: np.ndarray, values: np.ndarray) -> None:
    """Check every 3×3 Gram eigenvalue invariant; never recalculate a fit."""
    gram = matrix.T @ matrix
    if not np.isfinite(gram).all():
        raise EvidenceError("comparison_nonfinite_gram")
    scale = float(np.max(np.abs(gram)))
    if scale <= 0:
        raise EvidenceError("comparison_zero_gram")
    scaled = gram / scale
    squared = (values / math.sqrt(scale)) ** 2
    for actual, expected in (
            (float(np.sum(squared)), float(np.trace(scaled))),
            (float(np.sum(squared ** 2)), float(np.trace(scaled @ scaled))),
            (float(np.prod(squared)), float(np.linalg.det(scaled)))):
        _close(actual, expected, "singular_spectrum", tolerance=1e-10)


def _result(store: Any, handle: str) -> dict[str, Any]:
    try:
        meta = store.meta(handle)
        result = store.load(handle)
        if (type(result) is not dict or (meta["kind"], meta["schema"]) not in RESULTS.values() or
                result.get("schema") != meta["schema"]):
            raise EvidenceError("comparison_result_type")
        if meta["kind"] == "atom_distance":
            required = {"schema", "structure_handle", "first", "second", "first_coordinate_A",
                        "second_coordinate_A", "distance_A", "unit", "method", "limitations"}
            if (set(result) != required or result["unit"] != "angstrom" or
                    result["method"] != "euclidean_atom_distance@1" or
                    result["limitations"] != "Original-source Euclidean geometry; no bond, affinity or stability inference."):
                raise EvidenceError("comparison_distance_schema")
            catalog = _catalog(store, result["structure_handle"])
            a = _site(catalog, result["first"], result["first_coordinate_A"])
            b = _site(catalog, result["second"], result["second_coordinate_A"])
            _nonnegative(result["distance_A"])
            _close(result["distance_A"], math.dist(a["coordinate_A"], b["coordinate_A"]), "distance")
            if meta["summary"] != {"structure_handle": result["structure_handle"], "distance_A": result["distance_A"]}:
                raise EvidenceError("comparison_summary_mismatch")
            return result
        required = {"schema", "reference_handle", "moving_handle", "reference_model_number",
                    "moving_model_number", "pairs", "pair_count", "method", "numpy_version", "rotation",
                    "translation_A", "transform_convention", "rmsd_A", "unaligned_rmsd_A",
                    "fit_singular_values_A2", "degeneracy", "unit", "limitations"}
        if (set(result) != required or result["unit"] != "angstrom" or
                result["method"] != "unweighted_proper_rotation_kabsch@1" or
                result["transform_convention"] != "column_q=R_p+t; row_Pfit=P_Rtranspose+t" or
                result["limitations"] != "RMSD applies only to the explicit CA pairs; rigid fit is not affinity, stability or structural quality." or
                type(result["numpy_version"]) is not str or not result["numpy_version"]):
            raise EvidenceError("comparison_alignment_schema")
        reference, moving = result["reference_handle"], result["moving_handle"]
        if reference == moving:
            raise EvidenceError("comparison_same_source")
        a_catalog, b_catalog = _catalog(store, reference), _catalog(store, moving)
        if (type(result["reference_model_number"]) is not int or
                type(result["moving_model_number"]) is not int or
                result["reference_model_number"] != a_catalog["model_number"] or
                result["moving_model_number"] != b_catalog["model_number"] or
                type(result["pair_count"]) is not int or type(result["pairs"]) is not list or
                not 3 <= len(result["pairs"]) == result["pair_count"] <= 1000):
            raise EvidenceError("comparison_pair_count_or_model")
        used_a: set[int] = set()
        used_b: set[int] = set()
        p, q = [], []
        for pair in result["pairs"]:
            if type(pair) is not dict or set(pair) != {"reference", "moving", "reference_coordinate_A",
                                                       "moving_coordinate_A", "before_residual_A", "after_residual_A"}:
                raise EvidenceError("comparison_pair_schema")
            a = _site(a_catalog, pair["reference"], pair["reference_coordinate_A"], ca_protein=True)
            b = _site(b_catalog, pair["moving"], pair["moving_coordinate_A"], ca_protein=True)
            ai, bi = a["ref"]["site_index"], b["ref"]["site_index"]
            if ai in used_a or bi in used_b:
                raise EvidenceError("comparison_duplicate_pair")
            used_a.add(ai); used_b.add(bi)
            q.append(a["coordinate_A"]); p.append(b["coordinate_A"])
        p_arr, q_arr = np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64)
        pc, qc = p_arr.mean(axis=0), q_arr.mean(axis=0)
        x, y = p_arr - pc, q_arr - qc
        h = x.T @ y
        if not np.isfinite(h).all():
            raise EvidenceError("comparison_nonfinite_covariance")
        diagnostic = result["degeneracy"]
        if type(diagnostic) is not dict or set(diagnostic) != {"relative", "absolute",
                "moving_singular_values_A", "moving_threshold_A", "reference_singular_values_A",
                "reference_threshold_A", "covariance_threshold_A2"}:
            raise EvidenceError("comparison_degeneracy_schema")
        if (_number(diagnostic["relative"]) != RANK_RELATIVE or
                _number(diagnostic["absolute"]) != RANK_ABSOLUTE):
            raise EvidenceError("comparison_rank_method_mismatch")
        singulars = [_vector(diagnostic["moving_singular_values_A"], 3),
                     _vector(diagnostic["reference_singular_values_A"], 3),
                     _vector(result["fit_singular_values_A2"], 3)]
        thresholds = [diagnostic["moving_threshold_A"], diagnostic["reference_threshold_A"],
                      diagnostic["covariance_threshold_A2"]]
        for matrix, values, threshold in zip((x, y, h), singulars, thresholds):
            if (not np.isfinite(values).all() or np.any(values < 0) or
                    values[0] < values[1] or values[1] < values[2]):
                raise EvidenceError("comparison_singular_diagnostic_order")
            if _number(threshold) != max(RANK_ABSOLUTE, RANK_RELATIVE * float(values[0])):
                raise EvidenceError("comparison_rank_threshold_mismatch")
            if values[1] <= _number(threshold):
                raise EvidenceError("comparison_degenerate_pair_set")
            # Three scale-normalized Gram invariants determine the complete
            # nonnegative squared singular spectrum. No fit/SVD is rerun.
            _check_gram_spectrum(matrix, values)
        if type(result["rotation"]) is not list or len(result["rotation"]) != 3:
            raise EvidenceError("comparison_rotation_shape")
        rotation = np.asarray([_vector(row, 3) for row in result["rotation"]], dtype=np.float64)
        translation = _vector(result["translation_A"], 3)
        if (not np.isfinite(rotation).all() or not np.isfinite(translation).all() or
                abs(float(np.linalg.det(rotation)) - 1.0) > 1e-10 or
                not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=1e-10)):
            raise EvidenceError("comparison_nonproper_transform")
        if not np.allclose(rotation @ pc + translation, qc, rtol=1e-10, atol=1e-10):
            raise EvidenceError("comparison_transform_centroid")
        # Check fit optimality from the singular-value bound, without deriving
        # a new rotation or translation from an SVD.
        objective = float(np.trace(rotation @ h))
        optimum = float(singulars[2][0] + singulars[2][1] +
                        (1 if np.linalg.det(h) >= 0 else -1) * singulars[2][2])
        if not math.isclose(objective, optimum, rel_tol=1e-8, abs_tol=1e-8):
            raise EvidenceError("comparison_transform_not_optimal")
        before = np.linalg.norm(p_arr - q_arr, axis=1)
        after = np.linalg.norm(p_arr @ rotation.T + translation - q_arr, axis=1)
        for pair, old, new in zip(result["pairs"], before, after):
            _nonnegative(pair["before_residual_A"])
            _nonnegative(pair["after_residual_A"])
            _close(pair["before_residual_A"], old, "before_residual")
            _close(pair["after_residual_A"], new, "after_residual")
        _nonnegative(result["unaligned_rmsd_A"])
        _nonnegative(result["rmsd_A"])
        _close(result["unaligned_rmsd_A"], math.sqrt(float(np.mean(before ** 2))), "unaligned_rmsd")
        _close(result["rmsd_A"], math.sqrt(float(np.mean(after ** 2))), "rmsd")
        if meta["summary"] != {"reference_handle": reference, "moving_handle": moving,
                               "pair_count": result["pair_count"], "rmsd_A": result["rmsd_A"]}:
            raise EvidenceError("comparison_summary_mismatch")
        return result
    except EvidenceError:
        raise
    except (KeyError, TypeError, IndexError, ValueError, np.linalg.LinAlgError, OverflowError) as exc:
        raise EvidenceError("comparison_result_malformed") from exc


def validated_comparison_result(store: Any, handle: str) -> dict[str, Any]:
    """Validate one immutable result against the original source bytes."""
    return _result(store, handle)


def _claims(handle: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[tuple[str, str, Any]] = []
    if result["schema"] == "atom_distance@1":
        fields.extend((field, "angstrom", result[field]) for field in
                      ("first_coordinate_A", "second_coordinate_A", "distance_A"))
    else:
        fields.extend((field, unit, result[field]) for field, unit in (
            ("pair_count", "count"), ("reference_model_number", "identifier"),
            ("moving_model_number", "identifier"), ("rotation", "dimensionless"),
            ("translation_A", "angstrom"), ("rmsd_A", "angstrom"),
            ("unaligned_rmsd_A", "angstrom"), ("fit_singular_values_A2", "angstrom_squared")))
        for index, pair in enumerate(result["pairs"]):
            fields.extend((f"pairs[{index}].{key}", "angstrom", pair[key]) for key in (
                "reference_coordinate_A", "moving_coordinate_A", "before_residual_A", "after_residual_A"))

    claims = []
    def append(path: str, unit: str, value: Any) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                append(f"{path}[{index}]", unit, item)
            return
        if type(value) not in (int, float) or not math.isfinite(value):
            raise EvidenceError("nonfinite_comparison_claim")
        claims.append({"source_handle": handle, "source_kind": result["schema"].split("@")[0],
                       "source_schema": result["schema"], "source_sha256": handle.rsplit("/", 1)[-1],
                       "field_path": path, "unit": unit, "exact_value": value,
                       "rendered_value": str(value), "rounding": "exact_decimal"})
    for path, unit, value in fields:
        append(path, unit, value)
    return claims


def _render(result: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    values = {row["field_path"]: row["rendered_value"] for row in claims}
    lines = ["# Atom distance" if result["schema"] == "atom_distance@1" else "# Explicit CA rigid alignment",
             "", "Status: complete", "", f"Method: {_md(result['method'])}"]
    if result["schema"] == "atom_distance@1":
        lines.extend([f"Source: {_md(result['structure_handle'])}",
                      f"First atom: {_md(result['first'])}", f"Second atom: {_md(result['second'])}",
                      f"Distance: {values['distance_A']} Å (result field distance_A)"])
    else:
        lines.extend([f"Reference: {_md(result['reference_handle'])}, model {values['reference_model_number']}",
                      f"Moving: {_md(result['moving_handle'])}, model {values['moving_model_number']}",
                      f"Explicit pairs: {values['pair_count']} (result field pair_count)",
                      f"Aligned RMSD: {values['rmsd_A']} Å (result field rmsd_A)",
                      f"Unaligned RMSD: {values['unaligned_rmsd_A']} Å (result field unaligned_rmsd_A)",
                      f"Transform: {_md(result['transform_convention'])}",
                      f"NumPy: {_md(result['numpy_version'])}", "", "## Exact pair residuals", ""])
        for index, pair in enumerate(result["pairs"]):
            lines.append(f"- Pair {index + 1}: {_md(pair['reference'])} ↔ {_md(pair['moving'])}; "
                         f"before {values[f'pairs[{index}].before_residual_A']} Å, "
                         f"after {values[f'pairs[{index}].after_residual_A']} Å")
        lines.extend(["", "Rotation entries are dimensionless; translation and coordinates are Å.",
                      "Every transform entry and coordinate is field-cited in the JSON claims.",
                      "All declared pairs were fitted; no missing pair was silently omitted."])
    lines.extend(["", "## Scope and limitations", "", _md(result["limitations"]),
                  "The exact values, field paths, units and immutable source handle are in the JSON download.", ""])
    return "\n".join(lines)


def build_comparison_report(run: Any, result_handle: str, *, execution_link: Any = None) -> dict[str, Any]:
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        existing = resume_linked_report(run, execution_link, event_type="method_report_created",
                                        source_field="result_handle", source_handle=result_handle,
                                        saved=saved_comparison_report, builder="comparison")
        if existing is not None:
            return existing
        result = _result(run.store, result_handle)
        claims = _claims(result_handle, result)
        events = list(run.events.read())
        expected_tool = "measure_distance" if result["schema"] == "atom_distance@1" else "align_structures"
        provenance = _provenance(events, result_handle, expected_tool=expected_tool)
        seq = events[-1]["seq"] if events else 0
        manifest = {"schema": "method_report_manifest@1", "analysis_type": result["schema"].split("@")[0],
                    "status": "complete", "render_version": "comparison_markdown@1",
                    "generation_mode": "local_rules_no_egress", "result_handle": result_handle,
                    "result_schema": result["schema"], "result_sha256": result_handle.rsplit("/", 1)[-1],
                    "claims": claims, "snapshot": {"event_seq": seq, "time_utc": events[-1]["ts"] if events else None,
                                                "run_egress_mode": run.egress_config["mode"]},
                    "provenance": provenance,
                    "limitations": [result["limitations"], "No pairs or atoms were inferred or silently omitted."]}
        markdown = _render(result, claims)
        call_id = f"comparison_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by=call_id, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        saved = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                              produced_by=call_id, summary={"result_handle": result_handle,
                                                            "analysis_type": manifest["analysis_type"],
                                                            "status": "complete"})
        run.events.append("method_report_created", report_handle=saved.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq, **link_fields(execution_link))
        return {"handle": saved.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_comparison_report(run: Any, report_handle: str) -> dict[str, Any]:
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"]) != ("method_report_manifest", "method_report_manifest@1"):
        raise EvidenceError("comparison_report_type")
    report = run.store.load(report_handle)
    if (type(report) is not dict or set(report) != {"schema", "analysis_type", "status", "render_version",
            "generation_mode", "result_handle", "result_schema", "result_sha256", "claims", "snapshot",
            "provenance", "limitations", "markdown_handle"} or
            report.get("analysis_type") not in RESULTS or report.get("status") != "complete" or
            report.get("schema") != "method_report_manifest@1" or
            report.get("render_version") != "comparison_markdown@1" or
            report.get("generation_mode") != "local_rules_no_egress"):
        raise EvidenceError("comparison_report_status")
    result = _result(run.store, report["result_handle"])
    if (report["analysis_type"] != result["schema"].split("@")[0] or
            report["limitations"] != [result["limitations"], "No pairs or atoms were inferred or silently omitted."] or
            report["result_schema"] != result["schema"] or report["result_sha256"] !=
            report["result_handle"].rsplit("/", 1)[-1] or
            canonical_json(report["claims"]) != canonical_json(_claims(report["result_handle"], result))):
        raise EvidenceError("comparison_claim_mismatch")
    events = list(run.events.read())
    expected_tool = "measure_distance" if result["schema"] == "atom_distance@1" else "align_structures"
    expected_provenance = _provenance(events, report["result_handle"], expected_tool=expected_tool)
    if report["provenance"] != expected_provenance:
        raise EvidenceError("comparison_provenance_mismatch")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != {"event_seq", "time_utc", "run_egress_mode"} or
            type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected_provenance["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"}):
        raise EvidenceError("comparison_snapshot_invalid")
    source_event = next((e for e in events if e["seq"] == snapshot["event_seq"]), None)
    if source_event is None or snapshot["time_utc"] != source_event["ts"]:
        raise EvidenceError("comparison_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    if (run.store.meta(markdown_handle)["kind"], run.store.meta(markdown_handle)["schema"]) != (
            "report_markdown", "report_markdown@1"):
        raise EvidenceError("comparison_markdown_type")
    if not any(e["type"] == "method_report_created" and e.get("report_handle") == report_handle and
               e.get("result_handle") == report["result_handle"] and e.get("markdown_handle") == markdown_handle
               and e.get("snapshot_event_seq") == snapshot["event_seq"] for e in events):
        raise EvidenceError("comparison_report_event_missing")
    markdown = run.store.load(markdown_handle).decode()
    if markdown != _render(result, report["claims"]):
        raise EvidenceError("comparison_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle,
            "manifest": report, "markdown": markdown}
