"""L2 structural tools — geometric baseline implemented with gemmi.

This is a correct-but-simple baseline so the whole loop runs end to end on day one.
ProLIF / PLIP adapters (M1) must emit the SAME interaction_set@1 schema and pass
tests/test_residue_roundtrip.py (to be written in M1).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolContext, ToolRegistry

POLAR = {"N", "O"}
METALS = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"}
POS = {("LYS", "NZ"), ("ARG", "NH1"), ("ARG", "NH2"), ("ARG", "NE"), ("HIS", "NE2"), ("HIS", "ND1")}
NEG = {("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2")}


def _gemmi():
    try:
        import gemmi
        return gemmi
    except ImportError:
        raise ToolFailure(FailureClass.fatal, "gemmi is not installed (pip install gemmi)")


def _parse(ctx: ToolContext, handle: str):
    gemmi = _gemmi()
    text = ctx.store.load(handle).decode()
    fmt = ctx.store.meta(handle)["fmt"]
    if fmt in ("cif", "mmcif"):
        st = gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    else:
        st = gemmi.read_pdb_string(text)
    st.setup_entities()
    return st


def _res_ref(chain, res) -> dict[str, Any]:
    return {"chain_auth": chain.name, "seq_auth": res.seqid.num, "icode": res.seqid.icode.strip(),
            "chain_label": res.subchain or chain.name, "seq_label": res.label_seq, "resname": res.name}


def register(reg: ToolRegistry) -> None:
    @reg.register("load_structure")
    def load_structure(ctx: ToolContext, source: str, model_index: int = 0) -> Handle:
        if source.startswith(("pdb:", "afdb:")):
            raise ToolFailure(FailureClass.precondition,
                              "remote sources go through the fetch adapter + EgressGate (M1)")
        p = Path(source).expanduser()
        if not p.exists():
            raise ToolFailure(FailureClass.input_invalid, f"file not found: {p.name}")
        gemmi = _gemmi()
        raw = p.read_bytes()
        st = gemmi.read_structure(str(p))
        if model_index >= len(st):
            raise ToolFailure(FailureClass.input_invalid, f"model_index {model_index} >= {len(st)} models")
        m = st[model_index]
        summary = {"n_models": len(st), "chains": [c.name for c in m],
                   "n_residues": sum(len(c) for c in m), "format": p.suffix.lstrip("."),
                   "resolution_A": st.resolution or None}
        # Stored as raw bytes (not JSON). The file NAME is not stored: it may be sensitive.
        return ctx.store.put("structure", "structure@1", raw, fmt=p.suffix.lstrip(".") or "pdb",
                             produced_by=ctx.call_id, summary=summary)

    @reg.register("prepare_structure")
    def prepare_structure(ctx: ToolContext, structure: str, altloc: str, waters: str, hydrogens: str,
                          protonation_ph: float, missing_residues: str, symmetry_mates: str) -> Handle:
        gemmi = _gemmi()
        st = _parse(ctx, structure)
        removed = {"waters": 0, "hydrogens": 0, "altlocs": 0}
        if hydrogens == "strip":
            before = st[0].count_atom_sites()
            st.remove_hydrogens()
            removed["hydrogens"] = before - st[0].count_atom_sites()
        before = st[0].count_atom_sites()
        st.remove_alternative_conformations()      # keeps first; highest_occupancy handled below (TODO M0)
        removed["altlocs"] = before - st[0].count_atom_sites()
        if waters == "strip_all":
            n = sum(1 for c in st[0] for r in c if r.is_water())
            st.remove_waters()
            removed["waters"] = n
        manifest = {"altloc": altloc, "waters": waters, "hydrogens": hydrogens,
                    "protonation": {"ph": protonation_ph, "engine": None, "applied": False},
                    "missing_residues": missing_residues, "symmetry_mates": symmetry_mates,
                    "model_index": 0, "removed": removed, "input": structure,
                    "notes": ["protonation not applied in baseline (M0: reduce/PropKa adapter)"]}
        mh = ctx.store.put("preparation_manifest", "preparation_manifest@1", manifest, produced_by=ctx.call_id)
        pdb = st.make_pdb_string().encode()
        return ctx.store.put("prepared_structure", "structure@1", pdb, fmt="pdb", produced_by=ctx.call_id,
                             summary={"manifest": mh.handle, **removed})

    @reg.register("compute_interactions")
    def compute_interactions(ctx: ToolContext, structure: str, cutoff_A: float, types: list[str],
                             engine: str, ligand: str | None = None) -> Handle:
        if engine != "geometric":
            raise ToolFailure(FailureClass.precondition, f"engine '{engine}' adapter not implemented yet (M1)")
        gemmi = _gemmi()
        st = _parse(ctx, structure)
        model = st[0]
        lig_atoms = []
        for ch in model:
            for r in ch:
                if r.het_flag == "H" and not r.is_water() and r.name not in METALS and (ligand is None or r.name == ligand):
                    lig_atoms += [(ch, r, a) for a in r]
            if lig_atoms and ligand is None:
                break
        if not lig_atoms:
            raise ToolFailure(FailureClass.input_invalid, f"ligand '{ligand or 'any'}' not found")
        ns = gemmi.NeighborSearch(model, st.cell, 6).populate()
        rows, seen = [], set()
        for lch, lres, la in lig_atoms:
            for mark in ns.find_atoms(la.pos, "\0", radius=cutoff_A):
                cra = mark.to_cra(model)
                if cra.residue.het_flag == "H" and cra.residue.name not in METALS:
                    continue
                d = la.pos.dist(cra.atom.pos)
                pe, le = cra.atom.element.name.upper(), la.element.name.upper()
                kind = None
                if cra.residue.name in METALS and "metal" in types and le in {"N", "O", "S"} and d <= 2.8:
                    kind = "metal"
                elif "salt_bridge" in types and ((cra.residue.name, cra.atom.name) in POS | NEG) and le in POLAR and d <= 4.0:
                    kind = "salt_bridge"
                elif "hbond" in types and pe in POLAR and le in POLAR and d <= 3.5:
                    kind = "hbond"
                elif "hydrophobic" in types and pe == "C" and le == "C" and d <= 4.0:
                    kind = "hydrophobic"
                if not kind:
                    continue
                res = _res_ref(cra.chain, cra.residue)
                k = (res["chain_auth"], res["seq_auth"], res["icode"], kind)
                if k in seen:
                    continue
                seen.add(k)
                rows.append({"residue": res, "type": kind, "distance_A": round(d, 2),
                             "protein_atom": cra.atom.name, "ligand_atom": la.name, "engine": "geometric"})
        rows.sort(key=lambda r: (r["residue"]["chain_auth"], r["residue"]["seq_auth"], r["type"]))
        summary = {"n_edges": len(rows), **{f"n_{t}": sum(r["type"] == t for r in rows) for t in types}}
        return ctx.store.put("interaction_set", "interaction_set@1", rows, produced_by=ctx.call_id,
                             summary=summary, null_result=not rows)   # 0 contacts = result, not error

    @reg.register("compile_state")
    def compile_state(ctx: ToolContext, inputs: list[str], token_budget: int) -> Handle:
        """Compact state = summaries + ≤5 preview rows per handle. Never coordinates or sequence."""
        items = []
        for h in inputs:
            m = ctx.store.meta(h)
            data = ctx.store.load(h)
            prev = data[:5] if isinstance(data, list) else []
            items.append({"handle": h, "kind": m["kind"], "schema": m["schema"],
                          "summary": m["summary"], "preview": prev})
        state = {"schema": "compact_state@1", "items": items, "token_budget": token_budget}
        return ctx.store.put("compact_state", "compact_state@1", state, produced_by=ctx.call_id,
                             summary={"n_items": len(items)})
