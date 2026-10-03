"""Rebuild the M20 synthetic mutation-candidate fixtures in this folder (standard library only).

Run: ``python3 backend/tests/fixtures/mutation/build_mutation_fixtures.py [--check]``. ``--check`` rebuilds in memory
and exits non-zero unless every file on disk (the two structures and ``expected.json``) is byte-identical.

Everything here is a hand-placed SYNTHETIC geometry (labelled in the file names and in the structure titles). It is not
an experimental structure and not a chemically valid protein: each residue is a short straight line of atoms (1.5 A
apart) whose first-listed "probe" atom sits at a chosen distance from one feature (metal ion, ligand atom, partner SG).

``expected.json`` is an independent oracle: after writing the structure text, this script parses the written bytes
back by column / whitespace (no gemmi, no ``mw`` code) and computes every distance by brute force with ``math.dist``
over all heavy-atom pairs. The preparation step is simulated explicitly (H/D removed, one altloc kept per residue by
the documented ``highest_occupancy`` rule; the ``first`` rule is recorded separately where it changes a value).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CIF_NAME = "synthetic-mutation-fixture.cif"
PDB_NAME = "synthetic-mutation-fixture-nolabel.pdb"
TITLE = "SYNTHETIC-FIXTURE M20 mutation candidates (hand-placed geometry, not experimental, not a valid protein)"

# Spec constants the oracle needs (copied from .dryforge/spec.md 2-4, not imported from product code).
METALS = ("ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K")
WATERS = ("HOH",)
STANDARD = {"ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I",
            "LYS": "K", "LEU": "L", "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S",
            "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y"}
VARIANTS = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS", "CYX": "CYS",
            "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}
DISULFIDE_SG_A = 2.5
SIDE = {"CYS": ("CB", "SG"), "CYX": ("CB", "SG"), "LYS": ("CB", "NZ"), "MSE": ("CB", "SE"), "SEP": ("CB", "P")}
ELEMENT = {"N": "N", "CA": "C", "C": "C", "O": "O", "CB": "C", "SG": "S", "NZ": "N", "SE": "SE", "P": "P"}
STEP = 1.5

# Sequence of chains A and B (identical; auth numbering identical, 10A has insertion code A).
SEQ_AB = [(1, "", "GLY"), (2, "", "ALA"), (3, "", "SER"), (4, "", "THR"), (5, "", "CYS"), (6, "", "HID"),
          (7, "", "VAL"), (8, "", "CYX"), (9, "", "MSE"), (10, "", "LEU"), (10, "A", "ILE"), (11, "", "LYS"),
          (12, "", "GLU"), (13, "", "ASN"), (14, "", "GLN"), (15, "", "PHE"), (16, "", "THR"), (17, "", "TRP"),
          (18, "", "TYR"), (19, "", "PRO"), (20, "", "CYS"), (21, "", "CYS"), (22, "", "CYS"), (23, "", "CYS"),
          (24, "", "ARG"), (25, "", "MET"), (26, "", "ASP"), (27, "", "HIS")]
# Chain CC (multi-letter auth chain): the eight other variant names, an in-chain HETATM MSE, a non-standard ATOM SEP
# and one ATOM residue whose label_seq_id is "." (null label).
SEQ_CC = [(1, "", "HIE"), (2, "", "HIP"), (3, "", "HSD"), (4, "", "HSE"), (5, "", "HSP"), (6, "", "ASH"),
          (7, "", "GLH"), (8, "", "LYN"), (9, "", "MSE"), (10, "", "SEP"), (11, "", "ALA")]

ZN, NA, CD, HOH_O = (10.0, 10.0, 10.0), (10.0, 10.0, 60.0), (10.0, 10.0, 110.0), (10.0, 10.0, 160.0)
LIG_A = {"C1": (110.0, 10.0, 10.0), "C2": (111.5, 10.0, 10.0), "O3": (113.0, 10.0, 10.0), "H4": (110.0, 8.9, 10.0)}
LIG_B = {name: (x, y, z + 50.0) for name, (x, y, z) in LIG_A.items()}


def _add(p, q, s=1.0):
    return tuple(round(a + s * b, 3) for a, b in zip(p, q))


X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
NX, NY, NZ_ = (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)

# (chain, seq, icode) -> (probe atom name, probe xyz, direction away from the feature, note)
PLACED = {
    ("A", 2, ""): ("N", _add(ZN, X, 2.9), X, "ZN at 2.9 A (inside 3.0)"),
    ("A", 3, ""): ("N", _add(ZN, Y, 3.0), Y, "ZN at exactly 3.0 A (boundary, inclusive)"),
    ("A", 4, ""): ("N", _add(ZN, Z, 3.1), Z, "ZN at 3.1 A (just outside 3.0)"),
    ("A", 11, ""): ("N", _add(ZN, NX, 6.0), NX, "LYS NZ altloc A 2.5 A (occ 0.30) / B 3.5 A (occ 0.70) from ZN"),
    ("A", 12, ""): ("N", _add(NA, X, 4.0), X, "NA at 4.0 A (outside 3.0, inside 5.0)"),
    ("B", 1, ""): ("N", _add(NA, Y, 2.2), Y, "NA at 2.2 A (other chain near a metal)"),
    ("A", 13, ""): ("N", _add(CD, X, 2.0), X, "CD at 2.0 A (CD is not in the metal list)"),
    ("A", 14, ""): ("N", _add(HOH_O, X, 2.5), X, "water O at 2.5 A (water is neither metal nor ligand)"),
    ("A", 5, ""): ("SG", (60.0, 10.0, 10.0), NX, "SG-SG 2.05 A with CYX A8 (intra-chain)"),
    ("A", 8, ""): ("SG", (62.05, 10.0, 10.0), X, "SG-SG 2.05 A with CYS A5 (variant name CYX)"),
    ("A", 20, ""): ("SG", (60.0, 10.0, 60.0), NX, "SG-SG exactly 2.5 A with CYS B20 (inter-chain boundary)"),
    ("B", 20, ""): ("SG", (62.5, 10.0, 60.0), X, "SG-SG exactly 2.5 A with CYS A20"),
    ("A", 21, ""): ("SG", (60.0, 10.0, 110.0), NX, "SG-SG 2.6 A with CYS B21 (just over 2.5)"),
    ("B", 21, ""): ("SG", (62.6, 10.0, 110.0), X, "SG-SG 2.6 A with CYS A21"),
    ("B", 22, ""): ("SG", (60.0, 10.0, 160.0), Y, "SG-SG 2.4 A tie with CYS A22 and CYS B23"),
    ("A", 22, ""): ("SG", (57.6, 10.0, 160.0), NX, "SG-SG 2.4 A with CYS B22"),
    ("B", 23, ""): ("SG", (62.4, 10.0, 160.0), X, "SG-SG 2.4 A with CYS B22"),
    ("A", 6, ""): ("N", _add(LIG_A["C1"], Z, 5.0), Z, "LIG A101 C1 at exactly 5.0 A (shell boundary, inclusive)"),
    ("A", 7, ""): ("N", _add(LIG_A["C1"], NZ_, 5.001), NZ_, "LIG A101 C1 at 5.001 A (just outside 5.0)"),
    ("A", 9, ""): ("N", _add(LIG_A["O3"], X, 3.5), X, "LIG A101 O3 at 3.5 A (MSE as ATOM, non-standard)"),
    ("A", 10, ""): ("N", _add(LIG_A["C2"], Y, 4.0), Y, "LIG A101 C2 at 4.0 A"),
    ("A", 10, "A"): ("N", _add(LIG_A["C1"], NX, 6.0), NX, "LIG A101 C1 at 6.0 A (insertion code A)"),
    ("A", 15, ""): ("N", (113.0, 5.5, 10.0), NY, "LIG A101 O3 at 4.5 A heavy; its H atom HX at 2.0 A from O3"),
    ("A", 16, ""): ("N", (110.0, 4.5, 10.0), NY, "LIG A101 C1 at 5.5 A heavy; LIG H4 at 4.4 A (H not counted)"),
    ("CC", 10, ""): ("N", _add(LIG_A["C2"], Z, 4.2), Z, "LIG A101 C2 at 4.2 A (SEP, ATOM, non-standard)"),
    ("CC", 9, ""): ("N", _add(LIG_A["C2"], NZ_, 3.0), NZ_, "LIG A101 C2 at 3.0 A (MSE as HETATM: not a polymer)"),
    ("B", 10, ""): ("N", _add(LIG_B["C2"], Y, 3.0), Y, "LIG B101 C2 at 3.0 A"),
    ("B", 13, ""): ("N", _add(LIG_B["C1"], NZ_, 4.9), NZ_, "LIG B101 C1 at 4.9 A"),
}


def _atom_names(resname: str) -> list[str]:
    names = ["N", "CA", "C", "O"]
    if resname == "GLY":
        return names
    return names + list(SIDE.get(resname, ("CB",)))


def _residue_atoms(chain, seq, icode, resname, park):
    """[(name, element, xyz, altloc, occupancy)] in file order (N CA C O CB side...)."""
    names = _atom_names(resname)
    placed = PLACED.get((chain, seq, icode))
    if placed is None:
        probe, anchor, direction = names[0], park, X
    else:
        probe, anchor, direction, _ = placed
    order = [probe] + [n for n in names if n != probe]
    xyz = {name: _add(anchor, direction, STEP * k) for k, name in enumerate(order)}
    atoms = [(name, ELEMENT[name], xyz[name], "", 1.0) for name in names]
    if (chain, seq, icode) == ("A", 11, ""):
        atoms = [a for a in atoms if a[0] != "NZ"]
        atoms += [("NZ", "N", _add(ZN, NX, 2.5), "A", 0.3), ("NZ", "N", _add(ZN, NX, 3.5), "B", 0.7)]
    if (chain, seq, icode) == ("A", 15, ""):
        atoms.append(("HX", "H", (113.0, 8.0, 10.0), "", 1.0))
    return atoms


def _records():
    """Every atom as a dict in file order (mmCIF variant)."""
    rows = []
    park = [0]

    def parked():
        park[0] += 1
        return (200.0 + 10.0 * park[0], 200.0, 200.0)

    def poly(chain, label, seq_list, null_label_seq=(), hetatm=()):
        for index, (seq, icode, resname) in enumerate(seq_list, start=1):
            label_seq = None if seq in null_label_seq else index
            group = "HETATM" if seq in hetatm else "ATOM"
            for name, element, xyz, alt, occ in _residue_atoms(chain, seq, icode, resname, parked()):
                rows.append({"group": group, "element": element, "name": name, "alt": alt, "resname": resname,
                             "label_asym": label, "label_seq": label_seq, "chain": chain, "seq": seq, "icode": icode,
                             "xyz": xyz, "occ": occ})

    def het(chain, label, seq, resname, atoms):
        for name, element, xyz in atoms:
            rows.append({"group": "HETATM", "element": element, "name": name, "alt": "", "resname": resname,
                         "label_asym": label, "label_seq": None, "chain": chain, "seq": seq, "icode": "",
                         "xyz": xyz, "occ": 1.0})

    lig = [("C1", "C"), ("C2", "C"), ("O3", "O"), ("H4", "H")]
    poly("A", "A", SEQ_AB)
    het("A", "D", 101, "LIG", [(n, e, LIG_A[n]) for n, e in lig])
    het("A", "F", 201, "ZN", [("ZN", "ZN", ZN)])
    het("A", "G", 202, "NA", [("NA", "NA", NA)])
    het("A", "H", 203, "CD", [("CD", "CD", CD)])
    het("A", "I", 301, "HOH", [("O", "O", HOH_O)])
    poly("B", "B", SEQ_AB)
    het("B", "E", 101, "LIG", [(n, e, LIG_B[n]) for n, e in lig])
    poly("CC", "C", SEQ_CC, null_label_seq=(11,), hetatm=(9,))
    for serial, row in enumerate(rows, start=1):
        row["serial"] = serial
    return rows


def _fmt(v: float) -> str:
    return f"{v:.3f}"


def write_cif(rows) -> str:
    cols = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id", "label_asym_id",
            "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv",
            "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id", "pdbx_PDB_model_num"]
    out = ["data_SYNTHETIC_M20", "#", f"_struct.title '{TITLE}'", "#", "loop_"]
    out += [f"_atom_site.{c}" for c in cols]
    for r in rows:
        out.append(" ".join([
            r["group"], str(r["serial"]), r["element"], r["name"], r["alt"] or ".", r["resname"], r["label_asym"],
            "." if r["label_seq"] is None else str(r["label_seq"]), r["icode"] or "?",
            _fmt(r["xyz"][0]), _fmt(r["xyz"][1]), _fmt(r["xyz"][2]), f"{r['occ']:.2f}", "20.00",
            str(r["seq"]), r["resname"], r["chain"], r["name"], "1"]))
    return "\n".join(out + ["#"]) + "\n"


def write_pdb(rows) -> str:
    """Chains A and B (+ their HETATM residues) only; PDB has no label IDs (chain_label/seq_label null)."""
    out = [f"REMARK   1 {TITLE}", "REMARK   2 PDB variant: chains A and B only, no label IDs"]
    serial = 0
    for r in rows:
        if r["chain"] not in ("A", "B"):
            continue
        serial += 1
        name = r["name"]
        name_field = f" {name:<3}" if len(name) < 4 and len(r["element"]) == 1 else f"{name:<4}"
        out.append(f"{r['group']:<6}{serial:>5} {name_field}{r['alt'] or ' '}{r['resname']:>3} {r['chain']}"
                   f"{r['seq']:>4}{r['icode'] or ' '}   {r['xyz'][0]:>8.3f}{r['xyz'][1]:>8.3f}{r['xyz'][2]:>8.3f}"
                   f"{r['occ']:>6.2f}{20.0:>6.2f}          {r['element']:>2}")
    return "\n".join(out + ["END"]) + "\n"


# ----------------------------------------------------------------------------------------------- independent oracle
def parse_cif(text: str):
    lines = text.splitlines()
    cols = [ln.split(".", 1)[1] for ln in lines if ln.startswith("_atom_site.")]
    atoms = []
    for ln in lines:
        if ln.startswith(("ATOM ", "HETATM ")):
            v = dict(zip(cols, ln.split()))
            atoms.append({"group": v["group_PDB"], "element": v["type_symbol"].upper(), "name": v["label_atom_id"],
                          "alt": "" if v["label_alt_id"] == "." else v["label_alt_id"], "occ": float(v["occupancy"]),
                          "resname": v["auth_comp_id"], "chain": v["auth_asym_id"], "seq": int(v["auth_seq_id"]),
                          "icode": "" if v["pdbx_PDB_ins_code"] in ("?", ".") else v["pdbx_PDB_ins_code"],
                          "chain_label": v["label_asym_id"],
                          "seq_label": None if v["label_seq_id"] == "." else int(v["label_seq_id"]),
                          "model": int(v["pdbx_PDB_model_num"]),
                          "xyz": (float(v["Cartn_x"]), float(v["Cartn_y"]), float(v["Cartn_z"]))})
    return atoms


def parse_pdb(text: str):
    atoms = []
    for ln in text.splitlines():
        if ln.startswith(("ATOM  ", "HETATM")):
            atoms.append({"group": ln[0:6].strip(), "element": ln[76:78].strip().upper(), "name": ln[12:16].strip(),
                          "alt": ln[16].strip(), "occ": float(ln[54:60]), "resname": ln[17:20].strip(),
                          "chain": ln[21].strip(), "seq": int(ln[22:26]), "icode": ln[26].strip(),
                          "chain_label": None, "seq_label": None, "model": 1,
                          "xyz": (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))})
    return atoms


def prepare(atoms, altloc_rule: str):
    """Simulated preparation: drop H/D; keep one altloc per residue (highest mean occupancy, tie by letter; or the
    first letter met in file order); waters kept."""
    by_res: dict = {}
    for a in atoms:
        by_res.setdefault((a["chain"], a["seq"], a["icode"], a["resname"]), []).append(a)
    keep = []
    for a in atoms:
        if a["element"] in ("H", "D"):
            continue
        if a["alt"]:
            group = by_res[(a["chain"], a["seq"], a["icode"], a["resname"])]
            occ: dict = {}
            for b in group:
                if b["alt"]:
                    occ.setdefault(b["alt"], []).append(b["occ"])
            if altloc_rule == "highest_occupancy":
                chosen = min(occ, key=lambda k: (-sum(occ[k]) / len(occ[k]), k))
            else:
                chosen = next(iter(occ))
            if a["alt"] != chosen:
                continue
        keep.append(a)
    return keep


IDENT = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")


def ident(a) -> dict:
    return dict(zip(IDENT, (a["model"], a["chain"], a["chain_label"], a["seq"], a["seq_label"], a["icode"],
                            a["resname"])))


def residues_of(atoms):
    order, by = [], {}
    for a in atoms:
        key = tuple(ident(a).values())
        if key not in by:
            by[key] = []
            order.append(key)
        by[key].append(a)
    return [(dict(zip(IDENT, k)), by[k]) for k in order]


def name(res) -> str:
    return f"{res['resname']} {res['chain_auth']}{res['seq_auth']}{res['icode']}"


def min_dist(xs, ys):
    return min(math.dist(p["xyz"], q["xyz"]) for p in xs for q in ys)


def oracle(atoms, altloc_rule="highest_occupancy"):
    prepared = prepare(atoms, altloc_rule)
    res = residues_of(prepared)
    raw_res = residues_of(atoms)
    groups = {name(r): {a["group"] for a in xs} for r, xs in raw_res}
    polymer = [(r, xs) for r, xs in res if groups[name(r)] == {"ATOM"}]
    metals = [(r, xs) for r, xs in res if groups[name(r)] == {"HETATM"} and r["resname"] in METALS]
    ligands = [(r, xs) for r, xs in res if groups[name(r)] == {"HETATM"} and r["resname"] not in METALS
               and r["resname"] not in WATERS]
    out = {"residues": [], "ligand_candidates": [r for r, _ in ligands], "metal_residues": [r for r, _ in metals]}
    for r, xs in res:
        g = groups[name(r)]
        category = ("water" if r["resname"] in WATERS else "polymer" if g == {"ATOM"} else "nonpolymer")
        out["residues"].append({"residue": r, "record": "/".join(sorted(g)), "category": category,
                                "heavy_atoms_after_prepare": len(xs)})
    positions = []
    sg = [(r, a) for r, xs in polymer if r["resname"] in ("CYS", "CYX") for a in xs if a["name"] == "SG"]
    pairs = []
    for i in range(len(sg)):
        for j in range(i + 1, len(sg)):
            d = math.dist(sg[i][1]["xyz"], sg[j][1]["xyz"])
            if d <= DISULFIDE_SG_A:
                pairs.append({"a": sg[i][0], "b": sg[j][0], "sg_sg_A": d})
    for index, (r, xs) in enumerate(polymer):
        std = STANDARD.get(r["resname"]) and r["resname"] or VARIANTS.get(r["resname"])
        lig = {name(lr): min_dist(xs, [a for a in lxs]) for lr, lxs in ligands}
        metal = None
        for mr, mxs in metals:
            d = min_dist(xs, mxs)
            if metal is None or d < metal["min_distance_A"]:
                metal = {"min_distance_A": d, "metal_residue": mr}
        partner = None
        if r["resname"] in ("CYS", "CYX"):
            mine = [a for a in xs if a["name"] == "SG"]
            best = None
            for other, a in sg:
                if other == r:
                    continue
                d = math.dist(mine[0]["xyz"], a["xyz"])
                if d <= DISULFIDE_SG_A and (best is None or d < best[0]):   # strict <: file order wins ties
                    best = (d, other)
            partner = None if best is None else {"residue": best[1], "sg_sg_A": best[0]}
        positions.append({"file_index": index, "residue": r, "standard_resname": std,
                          "one_letter": STANDARD.get(std) if std else None,
                          "ligand_min_distance_A": lig, "nearest_metal": metal, "disulfide_partner": partner})
    out["polymer_residues"] = positions
    out["disulfide_pairs_le_2.5A"] = pairs
    return out


def shells(o, ligand: str, radius: float):
    return [name(p["residue"]) for p in o["polymer_residues"] if p["ligand_min_distance_A"][ligand] <= radius]


def metal_contacts(o, threshold: float):
    return [name(p["residue"]) for p in o["polymer_residues"]
            if p["nearest_metal"] is not None and p["nearest_metal"]["min_distance_A"] <= threshold]


def expected(cif: str, pdb: str) -> dict:
    exp = {"schema": "m20_mutation_fixture_expectations@1",
           "label": "SYNTHETIC FIXTURE EXPECTATIONS. Independent brute-force oracle (this script: parse the written "
                    "bytes by column/whitespace, math.dist over all heavy-atom pairs, simulated preparation). "
                    "No gemmi, no mw code. Not experimental.",
           "how": {"distances": "float64 math.dist over every heavy-atom pair (element not H/D) of the prepared "
                                "residue and the other residue; minimum",
                   "prepare": "H/D removed; altloc highest_occupancy = highest mean occupancy, tie by letter; "
                              "first = first letter met; waters kept (prepare_structure config defaults)",
                   "polymer": "residue whose every record is ATOM (spec 2: category polymer)",
                   "metal": "HETATM residue named in Zn Mg Ca Mn Fe Cu Co Ni Na K (CD is not; HOH is water)",
                   "ligand_candidates": "HETATM, not water, not in the metal list (spec 2 ligand selector)",
                   "disulfide": "SG of CYS/CYX polymer residues, SG-SG <= 2.5 A; partner = nearest, tie -> first "
                                "in file order",
                   "standard": "20 standard names + 10 mapped names (HID HIE HIP HSD HSE HSP CYX ASH GLH LYN)"},
           "files": {}}
    for fname, text, parser in ((CIF_NAME, cif, parse_cif), (PDB_NAME, pdb, parse_pdb)):
        atoms = parser(text)
        o = oracle(atoms)
        first = oracle(atoms, "first")
        diff = [{"residue": p["residue"],
                 "first_rule": {"ligand_min_distance_A": q["ligand_min_distance_A"],
                                "nearest_metal": q["nearest_metal"]},
                 "highest_occupancy": {"ligand_min_distance_A": p["ligand_min_distance_A"],
                                       "nearest_metal": p["nearest_metal"]}}
                for p, q in zip(o["polymer_residues"], first["polymer_residues"], strict=True)
                if p != q]
        ligs = [name(r) for r in o["ligand_candidates"] if r["resname"] == "LIG"]
        exp["files"][fname] = {
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "atom_records": len(atoms),
            "altloc_records": sum(1 for a in atoms if a["alt"]),
            "hydrogen_records": sum(1 for a in atoms if a["element"] in ("H", "D")),
            **o,
            "derived": {
                "polymer_count": len(o["polymer_residues"]),
                "shell": {lig: {str(r): shells(o, lig, r) for r in (1.0, 4.0, 5.0, 12.0)} for lig in ligs},
                "metal_contact": {str(t): metal_contacts(o, t) for t in (1.0, 2.0, 3.0, 5.0)},
                "altloc_first_rule_changes": diff,
                "metal_contact_first_rule_3.0": metal_contacts(first, 3.0),
                "disulfide_cys_residues": sorted({name(p["residue"]) for p in o["polymer_residues"]
                                                  if p["disulfide_partner"] is not None}),
                "non_standard_polymer": [name(p["residue"]) for p in o["polymer_residues"]
                                         if p["one_letter"] is None]},
        }
    return exp


def build() -> dict[str, str]:
    rows = _records()
    cif, pdb = write_cif(rows), write_pdb(rows)
    notes = {f"{c}{s}{i}": n for (c, s, i), (_, _, _, n) in PLACED.items()}
    exp = expected(cif, pdb)
    exp["placement_notes"] = notes
    return {CIF_NAME: cif, PDB_NAME: pdb,
            "expected.json": json.dumps(exp, ensure_ascii=False, indent=1, sort_keys=False) + "\n"}


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    bad = 0
    for fname, text in build().items():
        raw = text.encode()
        path = HERE / fname
        if check:
            same = path.is_file() and path.read_bytes() == raw
            bad += not same
            print(("OK  " if same else "DIFF"), fname)
        else:
            path.write_bytes(raw)
            print(hashlib.sha256(raw).hexdigest(), len(raw), fname)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
