"""Honest optional energy capability boundary. No production adapter is validated."""
from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolContext, ToolRegistry

PROTOCOLS = {
    "relax": ("relax_structure", "pyrosetta"),
    "cartesian_ddg": ("estimate_stability", "pyrosetta"),
    "interface_analyzer": ("score_interface", "pyrosetta"),
    "residue_energies": ("residue_energies", "pyrosetta"),
}
JOB_PROTOCOLS = {**PROTOCOLS, "openmm_protein_minimize": ("openmm_protein_minimize", "openmm"),
                 "prolif_prepare_v1": ("prepare_chemical_structure", "prolif"),
                 "prolif_detect_v1": ("compute_chemical_interactions", "prolif"),
                 "fpocket_detect_v1": ("detect_pockets", "fpocket"),
                 "rdkit_inspect_v1": ("rdkit_inspect_ligand", "rdkit"),
                 "rdkit_enumerate_v1": ("rdkit_enumerate_ligands", "rdkit"),
                 "qvina_dock_v1": ("qvina_dock_ligand", "qvina"),
                 "qvina_batch_dock_v1": ("qvina_dock_batch", "qvina"),
                 "openmm_mutation_model_v1": ("openmm_mutation_model", "openmm"),
                 "qvina_ga_dock_v1": ("qvina_ga_design", "qvina"),
                 "sequence_ga_dock_v1": ("sequence_ga_design", "qvina")}
JOB_ONLY_TOOLS = frozenset({"openmm_protein_minimize", "prepare_chemical_structure",
                            "compute_chemical_interactions", "detect_pockets",
                            "rdkit_inspect_ligand", "rdkit_enumerate_ligands", "qvina_dock_ligand",
                            "qvina_dock_batch", "openmm_mutation_model", "qvina_ga_design",
                            "sequence_ga_design"})


def protocol_capabilities() -> dict[str, Any]:
    found = importlib.util.find_spec("pyrosetta") is not None
    matrix = {}
    for protocol, (tool, engine) in PROTOCOLS.items():
        matrix[protocol] = {
            "protocol_id": protocol, "tool_id": tool, "engine_id": engine,
            "engine_detected": found, "implementation_status": "unimplemented",
            "validation_status": "not_validated", "available": False,
            "reason_code": "engine_missing" if not found else "protocol_unimplemented",
            "explanation": ("PyRosetta is absent from this backend interpreter" if not found else
                            "No validated production implementation is registered"),
        }
    return {"protocols": matrix, "rosetta_scripts_detected": shutil.which("rosetta_scripts") is not None,
            "real_protocol_tested": False}


def require_protocol(protocol: str) -> None:
    if protocol not in PROTOCOLS:
        raise ToolFailure(FailureClass.input_invalid, "unknown energy protocol")
    capability = protocol_capabilities()["protocols"][protocol]
    raise ToolFailure(FailureClass.precondition, capability["explanation"],
                      detail={"reason_code": capability["reason_code"], "protocol_id": protocol})


def register(reg: ToolRegistry) -> None:
    for protocol, (tool, _) in PROTOCOLS.items():
        reason = "no validated M4 energy backend or production implementation is registered"

        def unavailable(ctx: ToolContext, _protocol: str = protocol, **kwargs: object) -> Handle:
            require_protocol(_protocol)
            raise AssertionError("unreachable")

        reg.register(tool, unavailable_reason=reason)(unavailable)

    @reg.register("openmm_protein_minimize", unavailable_reason="use the durable JobQueue lane")
    def queued_only(ctx: ToolContext, **kwargs: object) -> Handle:
        raise ToolFailure(FailureClass.precondition, "submit through the durable method job lane")

    for name in ("prepare_chemical_structure", "compute_chemical_interactions"):
        reg.register(name, unavailable_reason="use the fixed durable chemical job lane")(queued_only)
    reg.register("detect_pockets", unavailable_reason="use the fixed durable fpocket job lane")(queued_only)
    for name in ("rdkit_inspect_ligand", "rdkit_enumerate_ligands"):
        reg.register(name, unavailable_reason="use the fixed durable RDKit ligand job lane")(queued_only)
    reg.register("qvina_dock_ligand", unavailable_reason="use the fixed durable qvina docking job lane")(queued_only)
    reg.register("qvina_dock_batch", unavailable_reason="use the fixed durable qvina batch docking job lane")(queued_only)
    reg.register("openmm_mutation_model", unavailable_reason="use the fixed durable OpenMM mutation-model job lane")(
        queued_only)
    reg.register("qvina_ga_design", unavailable_reason="use the fixed durable qvina GA design job lane")(queued_only)
    reg.register("sequence_ga_design", unavailable_reason="use the fixed durable sequence GA design job lane")(
        queued_only)

    @reg.register("define_mutations")
    def define_mutations(ctx: ToolContext, structure: str, mutations: list) -> Handle:
        for mutation in mutations:
            if not isinstance(mutation, dict) or not {"chain_auth", "seq_auth", "to"} <= set(mutation):
                raise ToolFailure(FailureClass.input_invalid, "each mutation needs chain_auth, seq_auth, to")
            if not isinstance(mutation["to"], str) or mutation["to"] not in "ACDEFGHIKLMNPQRSTVWY":
                raise ToolFailure(FailureClass.input_invalid, "invalid target residue")
        return ctx.store.put("mutation_set", "mutation_set@1", mutations, produced_by=ctx.call_id,
                             summary={"n": len(mutations), "structure": structure})
