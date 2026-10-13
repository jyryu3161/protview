# PROTOTYPE (M29 T1 (c)(f)(g) measurement only; never product code, never imported by mw).
"""Splice a repaired-structure mmCIF from prepared mmCIF text + a PDBFixer-measured additions list (gemmi only).

    build(prepared_text, additions, decimals=None|int, marker="calc_flag"|"category"|"second_block"|"none")

Steps: merge chain parts per author chain (residues keep their 7 fields; only the atom order changes), append new
side-chain / OXT atoms to their residues, insert gap residues after the residue the record names, mark new atoms,
write with gemmi. gemmi's writer numbers `_atom_site.id` 1..N in structure order (atom.serial is ignored), so the
written ids of observed atoms after an insertion point shift (measured in marker_and_preflight.py).
`decimals=None` writes the additions' full float repr into the coordinate cells (gemmi itself writes at most nine
significant digits); an int rounds new coordinates to that many decimals before writing. Observed atoms are never
touched. MSE renaming is not exercised (no MSE in the local inputs).
"""
from __future__ import annotations

import gemmi

MARKERS = ("calc_flag", "category", "second_block", "none")


def _key(r: dict) -> tuple:
    return (r["chain_auth"], r["seq_auth"], r["icode"], r["chain_label"], r["seq_label"], r["resname"])


def _res_key(chain, res) -> tuple:
    return (chain.name, res.seqid.num, res.seqid.icode.strip(), res.subchain or None, res.label_seq, res.name)


def _atom(name: str, element: str, xyz, serial: int, decimals) -> gemmi.Atom:
    atom = gemmi.Atom()
    atom.name = name
    atom.element = gemmi.Element(element)
    pos = [round(v, decimals) for v in xyz] if decimals is not None else list(xyz)
    atom.pos = gemmi.Position(*pos)
    atom.occ = 1.0
    atom.b_iso = 0.0
    atom.serial = serial
    return atom


def build(prepared_text: str, additions: dict, *, decimals: int | None = None, marker: str = "calc_flag") -> str:
    if marker not in MARKERS:
        raise ValueError(marker)
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(prepared_text).sole_block())
    model = st[0]
    merged: dict[str, gemmi.Chain] = {}
    order: list[str] = []
    for ch in model:
        if ch.name not in merged:
            merged[ch.name] = gemmi.Chain(ch.name)
            order.append(ch.name)
        for res in ch:
            merged[ch.name].add_residue(res)
    for name in order:
        model.remove_chain(name)
    for name in order:
        model.add_chain(merged[name])
    serial = max(a.serial for ch in model for r in ch for a in r)
    new_serials: dict[int, tuple] = {}
    by_res = {}
    for ch in model:
        for i, res in enumerate(ch):
            by_res[_res_key(ch, res)] = (ch.name, i)
    for gap in additions["gaps"]:
        chain = model[gap["chain_auth"]]
        after = _key(gap["after_residue"])
        index = next(i for i, res in enumerate(chain) if _res_key(chain, res) == after)
        neighbour = chain[index]
        for offset, row in enumerate(gap["residues"]):
            res = gemmi.Residue()
            res.name = row["resname"]
            res.seqid = gemmi.SeqId(row["seq_auth"], row["icode"] or " ")
            res.subchain = row["chain_label"]
            res.label_seq = row["seq_label"]
            res.entity_type = gemmi.EntityType.Polymer
            res.entity_id = neighbour.entity_id
            res.het_flag = "A"
            chain.add_residue(res, index + 1 + offset)
    for ch in model:
        lookup = {_res_key(ch, res): res for res in ch}
        for item in additions["added_atoms"]:
            if item["residue"]["chain_auth"] != ch.name:
                continue
            res = lookup[_key(item["residue"])]
            serial += 1
            res.add_atom(_atom(item["atom_name"], item["element"], item["coordinates_A"], serial, decimals))
            new_serials[serial] = (item["origin"], item["coordinates_A"])
    if marker == "calc_flag":
        for ch in model:
            for res in ch:
                for atom in res:
                    if atom.serial in new_serials:
                        atom.calc_flag = gemmi.CalcFlag.Calculated
    # gemmi's writer numbers _atom_site.id 1..N in structure order (atom.serial is ignored), so rows are found by
    # structure order, not by serial.
    order_serials = [atom.serial for ch in model for res in ch for atom in res]
    new_rows = {row: new_serials[s] for row, s in enumerate(order_serials) if s in new_serials}
    doc = st.make_mmcif_document()
    block = doc.sole_block()
    ids = list(block.find_values("_atom_site.id"))
    if decimals is None:
        cols = [block.find_values(f"_atom_site.Cartn_{axis}") for axis in "xyz"]
        for row, (_, xyz) in new_rows.items():
            for axis in range(3):
                cols[axis][row] = repr(float(xyz[axis]))
    text = doc.as_string()
    if marker == "category":
        loop = block.init_loop("_protview_repair_added_atom.", ["atom_site_id", "origin"])
        for row, (origin, _) in sorted(new_rows.items()):
            loop.add_row([ids[row], origin])
        text = doc.as_string()
    elif marker == "second_block":
        lines = ["data_protview_repair", "loop_", "_protview_repair_added_atom.atom_site_id",
                 "_protview_repair_added_atom.origin"]
        lines += [f"{ids[row]} {origin}" for row, (origin, _) in sorted(new_rows.items())]
        text = text + "\n".join(lines) + "\n"
    return text
