"""Strict measured-row projection and local inspection-view decision.

The optional HTTP operation is wholly owned by :mod:`mw.egress.gate`.
"""
from __future__ import annotations

from typing import Any

from ..core.residue import ResidueRef
from ..egress.gate import EgressGate, EgressInspectionStateV1, _finite_number
from ..runtime.orchestrator import Run

RULE_VERSION = "inspection_view@1"
KINDS = {"polar_contact", "hydrophobic_contact", "contact"}


def _measured_rows(run: Run, interaction_handle: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = run.store.meta(interaction_handle)
    if meta["kind"] != "interaction_set" or meta["schema"] != "interaction_set@1":
        raise ValueError("interaction handle required")
    data = run.store.load(interaction_handle)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise TypeError("invalid interaction set")
    method = data.get("method")
    if not isinstance(method, dict) or method.get("name") != "heavy_atom_distance":
        raise ValueError("unsupported measurement method")
    if meta["null_result"] != (len(data["rows"]) == 0):
        raise ValueError("inconsistent null result")
    n_edges = meta["summary"].get("n_edges")
    if n_edges is not None and (type(n_edges) is not int or n_edges != len(data["rows"])):
        raise ValueError("inconsistent measured row count")
    return data, data["rows"]


def _rule(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "summary"
    if any(isinstance(row, dict) and row.get("type") == "polar_contact" for row in rows):
        return "polar_contacts"
    if any(isinstance(row, dict) and row.get("type") == "hydrophobic_contact" for row in rows):
        return "hydrophobic_contacts"
    return "all_contacts"


def build_inspection_state(run: Run, interaction_handle: str) -> EgressInspectionStateV1:
    """Recompute outbound aggregates from durable measured rows; copy no metadata."""
    data, rows = _measured_rows(run, interaction_handle)
    params = data.get("parameters")
    cutoff = params.get("cutoff_A") if isinstance(params, dict) else None
    if _finite_number(cutoff, maximum=6) is None or cutoff < 2.5:
        raise ValueError("invalid measured cutoff")
    if len(rows) > 10_000_000:
        raise ValueError("state unrepresentable")
    counts = {kind: 0 for kind in KINDS}
    residues: set[tuple[int, str, int, str, str | None, int | None, str]] = set()
    minimum: float | None = None
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in KINDS or row.get("method") != "heavy_atom_distance" or row.get("engine") != "geometric" or row.get("unit") != "angstrom":
            raise ValueError("invalid measured row")
        distance = row.get("distance_A")
        if _finite_number(distance, maximum=6) is None or distance > cutoff:
            raise ValueError("invalid measured distance")
        residue = row.get("residue")
        if not isinstance(residue, dict) or set(residue) != set(ResidueRef.model_fields):
            raise ValueError("invalid measured residue")
        if (type(residue["model_number"]) is not int or type(residue["seq_auth"]) is not int or
                (residue["seq_label"] is not None and type(residue["seq_label"]) is not int) or
                any(type(residue[key]) is not str for key in ("chain_auth", "icode", "resname")) or
                (residue["chain_label"] is not None and type(residue["chain_label"]) is not str)):
            raise ValueError("invalid measured residue")
        residues.add(ResidueRef.model_validate(residue).key)
        counts[row["type"]] += 1
        minimum = distance if minimum is None else min(minimum, distance)
    return EgressInspectionStateV1.model_validate({
        "schema": "inspection_state@1", "measurement_method": "heavy_atom_distance",
        "contact_count": len(rows), "contacting_residue_count": len(residues),
        "polar_contact_count": counts["polar_contact"],
        "hydrophobic_contact_count": counts["hydrophobic_contact"],
        "other_contact_count": counts["contact"], "minimum_distance_A": minimum,
        "cutoff_A": cutoff, "null_result": not rows,
    })


def synthetic_connection_fixture() -> EgressInspectionStateV1:
    """Synthetic aggregate solely for a transport smoke; never a scientific object."""
    return EgressInspectionStateV1.model_validate({
        "schema": "inspection_state@1", "measurement_method": "heavy_atom_distance",
        "contact_count": 0, "contacting_residue_count": 0, "polar_contact_count": 0,
        "hydrophobic_contact_count": 0, "other_contact_count": 0,
        "minimum_distance_A": None, "cutoff_A": 4.0, "null_result": True,
    })


def decide_inspection_view(run: Run, interaction_handle: str, *, gate: EgressGate | None = None) -> dict[str, Any]:
    """Return one advisory view choice, with a complete offline rule fallback."""
    _, rows = _measured_rows(run, interaction_handle)
    fallback = _rule(rows)
    try:
        state = build_inspection_state(run, interaction_handle)
    except (ValueError, TypeError):
        result = {"action": fallback, "source": "rule", "status": "fallback",
                  "reason_code": "state_unrepresentable", "evidence_handle": interaction_handle,
                  "rule_version": RULE_VERSION, "requested_model": None,
                  "served_model": None, "request_id": None, "cache_status": "not_used"}
    else:
        outcome = (gate or EgressGate()).request_jev(run, state)
        accepted = outcome.status == "accepted"
        result = {"action": outcome.action if accepted else fallback,
                  "source": "jev" if accepted else "rule",
                  "status": "accepted" if accepted else
                            "local" if outcome.reason_code in {"local_only", "dry_run"} else "fallback",
                  "reason_code": outcome.reason_code, "evidence_handle": interaction_handle,
                  "rule_version": RULE_VERSION if not accepted else None,
                  "requested_model": outcome.requested_model,
                  "served_model": outcome.served_model, "request_id": outcome.audit_id,
                  "cache_status": "not_implemented"}
    run.decide(result["source"], "inspection_view", result["action"],
               reason_code=result["reason_code"], evidence_handle=interaction_handle,
               requested_model=result["requested_model"], served_model=result["served_model"],
               request_id=result["request_id"])
    return result
