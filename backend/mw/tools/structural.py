"""Local structure preparation and measured heavy-atom geometry."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolContext, ToolRegistry

POLAR = {"N", "O"}
METALS = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"}


def _gemmi():
    try:
        import gemmi
        return gemmi
    except ImportError:
        raise ToolFailure(FailureClass.fatal, "gemmi is not installed (pip install gemmi)")


def _parse(ctx: ToolContext, handle: str):
    gemmi = _gemmi()
    obj = ctx.store.load(handle)
    if isinstance(obj, dict) and "source" in obj:
        text = ctx.store.load(obj["source"]).decode("utf-8")
        fmt = obj["format"]
        model_index = obj["model_index"]
    elif isinstance(obj, dict) and "coordinates" in obj:
        coordinates = obj["coordinates"]
        text = ctx.store.load(coordinates).decode("utf-8")
        fmt = ctx.store.meta(coordinates)["fmt"]
        model_index = 0
    else:
        text = obj.decode("utf-8")
        fmt = ctx.store.meta(handle)["fmt"]
        model_index = 0
    try:
        if fmt in ("cif", "mmcif"):
            st = gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
        else:
            st = gemmi.read_pdb_string(text)
    except Exception as exc:
        raise ToolFailure(FailureClass.input_invalid, "malformed structure") from exc
    if not st or model_index >= len(st) or st[model_index].count_atom_sites() == 0:
        raise ToolFailure(FailureClass.input_invalid, "selected model is empty or unavailable")
    _validate_coordinates(st[model_index])
    for index in range(len(st) - 1, -1, -1):
        if index != model_index:
            del st[index]
    return st


def validate_upload(raw: bytes, fmt: str) -> dict[str, Any]:
    """Check that uploaded bytes match their declared PDB/mmCIF format."""
    gemmi = _gemmi()
    try:
        text = raw.decode("utf-8")
        if fmt in {"cif", "mmcif"}:
            if not text.lstrip().startswith("data_"):
                raise ValueError("not a CIF data block")
            st = gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
        elif fmt == "pdb":
            if not any(line.startswith(("ATOM  ", "HETATM", "MODEL ")) for line in text.splitlines()):
                raise ValueError("no PDB coordinate records")
            st = gemmi.read_pdb_string(text)
        else:
            raise ValueError("unsupported format")
    except (UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise ToolFailure(FailureClass.input_invalid, "malformed or mismatched structure content") from exc
    if not st or not any(model.count_atom_sites() for model in st):
        raise ToolFailure(FailureClass.input_invalid, "structure has no atoms")
    for model in st:
        _validate_coordinates(model)
    return {"format": fmt, "n_models": len(st), "model_numbers": [model.num for model in st]}


def _validate_coordinates(model) -> None:
    for chain in model:
        for residue in chain:
            for atom in residue:
                if not all(map(math.isfinite, (atom.pos.x, atom.pos.y, atom.pos.z, atom.occ))):
                    raise ToolFailure(FailureClass.input_invalid, "non-finite coordinate or occupancy")


def _res_ref(chain, res, model_number: int) -> dict[str, Any]:
    return {"model_number": model_number, "chain_auth": chain.name,
            "seq_auth": res.seqid.num, "icode": res.seqid.icode.strip(),
            "chain_label": res.subchain or None, "seq_label": res.label_seq, "resname": res.name}


def structure_residues(store, handle: str) -> dict[str, Any]:
    st = _parse(ToolContext(store=store, call_id="metadata"), handle)
    model = st[0]
    residues = []
    ligands = []
    for chain in model:
        for residue in chain:
            ref = _res_ref(chain, residue, model.num)
            item = {**ref, "atom_count": len(residue),
                    "category": ("water" if residue.is_water() else
                                 "polymer" if residue.het_flag == "A" else "nonpolymer")}
            residues.append(item)
            if residue.het_flag == "H" and not residue.is_water() and residue.name not in METALS:
                ligands.append(ref)
    return {"model_number": model.num, "residues": residues, "ligands": ligands}


def structure_bytes(store, handle: str) -> tuple[bytes, str]:
    meta = store.meta(handle)
    if meta["kind"] == "prepared_structure":
        coordinates = store.load(handle)["coordinates"]
        return store.load(coordinates), store.meta(coordinates)["fmt"]
    if meta["kind"] != "structure":
        raise ToolFailure(FailureClass.input_invalid, "handle is not a structure")
    st = _parse(ToolContext(store=store, call_id="viewer"), handle)
    selection = store.load(handle)
    fmt = ("cif" if selection["format"] in {"cif", "mmcif"}
           or selection["model_index"] or st[0].num != 1 else "pdb")
    raw = st.make_mmcif_document().as_string() if fmt == "cif" else st.make_pdb_string()
    return raw.encode(), fmt


def _selected_ligand(model, selector: dict[str, Any] | None):
    ligands = [(ch, res) for ch in model for res in ch
               if res.het_flag == "H" and not res.is_water() and res.name not in METALS]
    if selector is not None:
        required = {"model_number", "chain_auth", "seq_auth", "icode", "resname"}
        allowed = required | {"chain_label", "seq_label"}
        if set(selector) - allowed or not required.issubset(selector):
            raise ToolFailure(FailureClass.input_invalid, "ligand selector requires model_number, chain_auth, "
                              "seq_auth, icode and resname; optional label IDs must match")
        if (type(selector["model_number"]) is not int or type(selector["seq_auth"]) is not int
                or not all(isinstance(selector[key], str) for key in ("chain_auth", "icode", "resname"))):
            raise ToolFailure(FailureClass.input_invalid, "invalid ligand identity types")
        if ("chain_label" in selector and selector["chain_label"] is not None
                and not isinstance(selector["chain_label"], str)) or ("seq_label" in selector
                and selector["seq_label"] is not None and type(selector["seq_label"]) is not int):
            raise ToolFailure(FailureClass.input_invalid, "invalid ligand label identity types")
        ligands = [(ch, res) for ch, res in ligands
                   if all(_res_ref(ch, res, model.num)[key] == value for key, value in selector.items())]
    if len(ligands) != 1:
        reason = "not found" if not ligands else "ambiguous; select one ligand instance"
        raise ToolFailure(FailureClass.input_invalid, f"ligand {reason}")
    return ligands[0]


def _select_altlocs(st, policy: str) -> tuple[int, list[dict[str, Any]]]:
    removed = 0
    choices: list[dict[str, Any]] = []
    for chain in st[0]:
        for res in chain:
            alternates: dict[str, list[float]] = {}
            for atom in res:
                alt = atom.altloc.strip("\x00 ")
                if alt:
                    alternates.setdefault(alt, []).append(atom.occ)
            if not alternates:
                continue
            if policy == "highest_occupancy":
                selected = min(alternates, key=lambda alt: (-sum(alternates[alt]) / len(alternates[alt]), alt))
            else:
                selected = next(iter(alternates))
            choices.append({"chain_auth": chain.name, "seq_auth": res.seqid.num,
                            "icode": res.seqid.icode.strip(), "selected": selected})
            for index in range(len(res) - 1, -1, -1):
                alt = res[index].altloc.strip("\x00 ")
                if alt and alt != selected:
                    del res[index]
                    removed += 1
            for atom in res:
                if atom.altloc.strip("\x00 ") == selected:
                    atom.altloc = "\0"
    return removed, choices


def register(reg: ToolRegistry) -> None:
    @reg.register("load_structure")
    def load_structure(ctx: ToolContext, source: str, model_index: int = 0) -> Handle:
        if ctx.source_bytes is not None:
            raw = ctx.source_bytes
            fmt = ctx.source_format
        else:
            if source.startswith(("pdb:", "afdb:")):
                raise ToolFailure(FailureClass.precondition,
                                  "remote sources go through the fetch adapter + EgressGate (M1)")
            p = Path(source).expanduser()
            if not p.is_file():
                raise ToolFailure(FailureClass.input_invalid, f"file not found: {p.name}")
            fmt = p.suffix.lower().lstrip(".")
            raw = p.read_bytes()
        if fmt not in {"pdb", "cif", "mmcif"}:
            raise ToolFailure(FailureClass.input_invalid, "supported formats are PDB and mmCIF")
        gemmi = _gemmi()
        try:
            text = raw.decode("utf-8")
            st = (gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
                  if fmt in {"cif", "mmcif"} else gemmi.read_pdb_string(text))
        except Exception as exc:
            raise ToolFailure(FailureClass.input_invalid, "malformed structure") from exc
        if not st or model_index >= len(st) or st[model_index].count_atom_sites() == 0:
            raise ToolFailure(FailureClass.input_invalid, f"model_index {model_index} >= {len(st)} models")
        m = st[model_index]
        _validate_coordinates(m)
        source_obj = ctx.store.put("structure_source", "structure_source@1", raw, fmt=fmt,
                                   produced_by=ctx.call_id)
        summary = {"n_models": len(st), "selected_model_index": model_index, "model_number": m.num,
                   "chains_auth": list(dict.fromkeys(c.name for c in m)),
                   "n_residues": sum(len(c) for c in m),
                   "format": fmt, "resolution_A": st.resolution if math.isfinite(st.resolution) and st.resolution > 0 else None,
                   "source_handle": source_obj.handle}
        selection = {"source": source_obj.handle, "model_index": model_index, "format": fmt}
        return ctx.store.put("structure", "structure_selection@2", selection,
                             produced_by=ctx.call_id, summary=summary)

    @reg.register("prepare_structure")
    def prepare_structure(ctx: ToolContext, structure: str, altloc: str, waters: str, hydrogens: str,
                          missing_residues: str, symmetry_mates: str) -> Handle:
        if missing_residues != "leave_gaps" or symmetry_mates != "ignore" or waters not in {"strip_all", "keep_all"}:
            raise ToolFailure(FailureClass.precondition, "requested preparation policy is unavailable")
        st = _parse(ctx, structure)
        selection = ctx.store.load(structure)
        removed = {"waters": 0, "hydrogens": 0, "altlocs": 0}
        if hydrogens == "strip":
            before = st[0].count_atom_sites()
            st.remove_hydrogens()
            removed["hydrogens"] = before - st[0].count_atom_sites()
        removed["altlocs"], choices = _select_altlocs(st, altloc)
        if waters == "strip_all":
            n = sum(1 for c in st[0] for r in c if r.is_water())
            st.remove_waters()
            removed["waters"] = n
        manifest = {"altloc": altloc, "waters": waters, "hydrogens": hydrogens,
                    "protonation": {"policy": "none", "applied": False},
                    "missing_residues": missing_residues, "symmetry_mates": symmetry_mates,
                    "model_index": selection["model_index"], "model_number": st[0].num,
                    "source_handle": selection["source"], "input": structure,
                    "removed": removed, "altloc_choices": choices}
        mh = ctx.store.put("preparation_manifest", "preparation_manifest@1", manifest, produced_by=ctx.call_id)
        # A lone PDB model is emitted without MODEL records by gemmi, which
        # would silently renumber a selected non-first model to 1 on reload.
        fmt = ("cif" if selection["format"] in {"cif", "mmcif"}
               or selection["model_index"] or st[0].num != 1 else "pdb")
        output = (st.make_mmcif_document().as_string() if fmt == "cif" else st.make_pdb_string()).encode()
        coordinates = ctx.store.put("prepared_coordinates", "prepared_coordinates@1", output,
                                    fmt=fmt, produced_by=ctx.call_id)
        prepared = {"coordinates": coordinates.handle, "manifest": mh.handle,
                    "model_index": selection["model_index"], "model_number": st[0].num}
        return ctx.store.put("prepared_structure", "prepared_structure@1", prepared,
                             produced_by=ctx.call_id,
                             summary={"coordinates": coordinates.handle, "manifest": mh.handle,
                                      "model_index": selection["model_index"], **removed})

    @reg.register("compute_interactions")
    def compute_interactions(ctx: ToolContext, structure: str, cutoff_A: float, types: list[str],
                             engine: str, ligand: dict[str, Any] | None = None) -> Handle:
        if engine != "geometric":
            raise ToolFailure(FailureClass.precondition, f"engine '{engine}' adapter not implemented yet (M1)")
        st = _parse(ctx, structure)
        model = st[0]
        if not types:
            raise ToolFailure(FailureClass.input_invalid, "at least one contact type is required")
        lch, lres = _selected_ligand(model, ligand)
        ligand_ref = _res_ref(lch, lres, model.num)
        rows = []
        for ch in model:
            for res in ch:
                if res.het_flag != "A":
                    continue
                for pa in res:
                    if pa.element.name.upper() == "H":
                        continue
                    for la in lres:
                        if la.element.name.upper() == "H":
                            continue
                        distance = pa.pos.dist(la.pos)
                        if distance > cutoff_A:
                            continue
                        pe, le = pa.element.name.upper(), la.element.name.upper()
                        if pe in POLAR and le in POLAR:
                            kind = "polar_contact"
                        elif pe == "C" and le == "C":
                            kind = "hydrophobic_contact"
                        else:
                            kind = "contact"
                        if kind in types:
                            rows.append({"residue": _res_ref(ch, res, model.num),
                                         "ligand": ligand_ref,
                                         "model_number": model.num, "type": kind,
                                         "distance_A": distance, "protein_atom": pa.name,
                                         "ligand_atom": la.name, "engine": "geometric",
                                         "method": "heavy_atom_distance", "unit": "angstrom",
                                         "limitations": "proximity alone does not validate a chemical interaction"})
        rows.sort(key=lambda row: (row["residue"]["chain_auth"], row["residue"]["seq_auth"],
                                   row["residue"]["icode"], row["protein_atom"], row["ligand_atom"]))
        summary = {"n_edges": len(rows), "structure": structure, "ligand": ligand_ref,
                   "cutoff_A": cutoff_A, "types": sorted(set(types)),
                   "method": "heavy_atom_distance", "version": "1", "unit": "angstrom",
                   "limitations": "geometric contacts only; no chemical interaction or energy inference",
                   **{f"n_{t}": sum(row["type"] == t for row in rows) for t in types}}
        content = {"structure": structure, "selection": {"ligand": ligand_ref},
                   "parameters": {"cutoff_A": cutoff_A, "types": sorted(set(types))},
                   "method": {"name": "heavy_atom_distance", "version": "1", "unit": "angstrom",
                              "limitations": summary["limitations"]}, "rows": rows}
        return ctx.store.put("interaction_set", "interaction_set@1", content, produced_by=ctx.call_id,
                             summary=summary, null_result=not rows)   # 0 contacts = result, not error

    @reg.register("compile_state")
    def compile_state(ctx: ToolContext, inputs: list[str], token_budget: int) -> Handle:
        """Compact state = summaries + ≤5 preview rows per handle. Never coordinates or sequence."""
        if not isinstance(inputs, list):
            raise ToolFailure(FailureClass.input_invalid, "inputs must be a list of handles")
        items = []
        for h in inputs:
            m = ctx.store.meta(h)
            data = ctx.store.load(h)
            prev = (data[:5] if isinstance(data, list) else data.get("rows", [])[:5]
                    if m["kind"] == "interaction_set" and isinstance(data, dict) else [])
            items.append({"handle": h, "kind": m["kind"], "schema": m["schema"],
                          "summary": m["summary"], "preview": prev})
        state = {"schema": "compact_state@1", "items": items, "token_budget": token_budget}
        return ctx.store.put("compact_state", "compact_state@1", state, produced_by=ctx.call_id,
                             summary={"n_items": len(items)})
