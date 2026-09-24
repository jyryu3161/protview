"""L3 energetic tools. Real implementations go through the JobQueue (M4).

Each tool also registers a deterministic STUB used in dry_run so loop logic can be
debugged without running Rosetta (plan §4.5). Stub outputs are marked summary.stub=True
and the UI must show them as such.
"""
from __future__ import annotations

import hashlib

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolContext, ToolRegistry


def _pseudo(seed_text: str, lo: float, hi: float) -> float:
    h = int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(lo + (hi - lo) * h, 2)


def register(reg: ToolRegistry) -> None:
    def relax_stub(ctx: ToolContext, structure: str, scorefxn: str, nstruct: int, constrain_to_start: bool) -> Handle:
        raw = ctx.store.load(structure)
        return ctx.store.put("relaxed_structure", "structure@1", raw, fmt="pdb", produced_by=ctx.call_id,
                             summary={"stub": True, "scorefxn": scorefxn, "total_REU": _pseudo(structure, -900, -700)})

    @reg.register("relax_structure", stub=relax_stub)
    def relax_structure(ctx: ToolContext, **kw) -> Handle:
        raise ToolFailure(FailureClass.fatal, "relax_structure via JobQueue not implemented yet (M4)")

    def ddg_stub(ctx: ToolContext, structure: str, mutations: str, protocol: str, iterations: int) -> Handle:
        muts = ctx.store.load(mutations)
        rows = []
        for m in muts:
            label = f"{m.get('from', 'X')}{m['seq_auth']}{m.get('icode', '')}{m['to']}"
            rounds = [_pseudo(f"{label}:{i}", -2.5, 3.0) for i in range(iterations)]
            mean = round(sum(rounds) / len(rounds), 2)
            sd = round((sum((r - mean) ** 2 for r in rounds) / len(rounds)) ** 0.5, 2)
            rows.append({"mutation": label, "chain_auth": m["chain_auth"], "ddg_REU": mean, "sd_REU": sd,
                         "rounds_REU": rounds, "iterations": iterations})
        return ctx.store.put("energy_table", "energy_table@1", rows, produced_by=ctx.call_id,
                             summary={"stub": True, "n": len(rows), "unit": "REU", "protocol": protocol})

    @reg.register("estimate_stability", stub=ddg_stub)
    def estimate_stability(ctx: ToolContext, **kw) -> Handle:
        raise ToolFailure(FailureClass.fatal, "estimate_stability via JobQueue not implemented yet (M4)")

    @reg.register("define_mutations")
    def define_mutations(ctx: ToolContext, structure: str, mutations: list) -> Handle:
        for m in mutations:
            if not {"chain_auth", "seq_auth", "to"} <= set(m):
                raise ToolFailure(FailureClass.input_invalid, "each mutation needs chain_auth, seq_auth, to")
            if m["to"] not in "ACDEFGHIKLMNPQRSTVWY" or len(m["to"]) != 1:
                raise ToolFailure(FailureClass.input_invalid, f"invalid target residue {m['to']!r}")
        return ctx.store.put("mutation_set", "mutation_set@1", mutations, produced_by=ctx.call_id,
                             summary={"n": len(mutations), "structure": structure})
