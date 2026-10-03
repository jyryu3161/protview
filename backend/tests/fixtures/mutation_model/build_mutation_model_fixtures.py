"""Rebuild the M21 mutation-model fixtures in this folder (standard library only).

Run: ``python3 backend/tests/fixtures/mutation_model/build_mutation_model_fixtures.py [--check]``. ``--check`` rebuilds
in memory and exits non-zero unless every generated file on disk is byte-identical.

Inputs: the public 1UBQ mmCIF ``backend/tests/fixtures/public_1ubq.cif`` (read as text; ``_atom_site`` rows only).
Nothing here is an experimental structure, a modelled mutant or a measured value.

- ``derived_1ubq_f4c_t66c_disulfide_fixture.cif``: DERIVED SYNTHETIC. 1UBQ polymer ATOM rows (waters dropped) with
  PHE A4 and THR A66 renamed CYS, side chains cut after CB and one hand-placed SG each, so that the SG-SG distance is
  about 2.04 A (OpenMM ``createDisulfideBonds`` threshold 3.0 A; M20 rule 2.5 A). SG placement: N-CA-CB-SG built
  from bond 1.81 A, angle CA-CB-SG 114 deg and a chi1 grid (2 deg steps) choosing the pair closest to 2.04 A,
  ties by the larger closest distance to any other heavy atom. Not a real disulfide variant of ubiquitin.
- ``derived_1ubq_f4c_single_cys_fixture.cif``: the same rows with only PHE A4 replaced by CYS (THR A66 unchanged);
  its SG uses the same bond/angle with chi1 fixed at 66 deg (``SINGLE_CHI1``), chosen in T1 because PDBFixer 1.12.0
  then places the T66C SG about 2.0 A away (a new distance-based disulfide; see the M21 T1 preflight record).
- ``synthetic-phenol-ligand.sdf``: SYNTHETIC hand-built phenol (regular hexagon C-C 1.39 A, C-H 1.09 A, C-O 1.36 A,
  O-H 0.96 A, explicit H) placed next to the 1UBQ I44 side chain; for the M18 same-condition docking flow only.
- ``expected.json``: hand-derived oracles (closed-form values, no engine): (1) contacts of a 12-atom synthetic graph
  with 1-3 bond exclusion at cutoffs 4.0 / 3.0 / 2.5 A; (2) Lee-Richards two-sphere and isolated-sphere SASA.
  The values are written from the formulas below, not from coordinates run through any implementation.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "public_1ubq.cif"
SOURCE_SHA256 = "056f98710cb2b36f633c45e41902a02eb446e82871da21ff2dd44f74a56ca0f6"
PAIR_NAME = "derived_1ubq_f4c_t66c_disulfide_fixture.cif"
SINGLE_NAME = "derived_1ubq_f4c_single_cys_fixture.cif"
LIGAND_NAME = "synthetic-phenol-ligand.sdf"
EXPECTED_NAME = "expected.json"
COLUMNS = ("group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id", "label_asym_id",
           "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z", "occupancy",
           "B_iso_or_equiv", "pdbx_formal_charge", "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id",
           "pdbx_PDB_model_num")
CB_SG, ANGLE_SG, SS_TARGET = 1.81, 114.0, 2.04
SINGLE_CHI1 = 66


def _rows() -> list[list[str]]:
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise SystemExit("public_1ubq.cif changed")
    lines = raw.decode().splitlines()
    start = lines.index("_atom_site.group_PDB ")
    names = [line.strip()[len("_atom_site."):] for line in lines[start:start + len(COLUMNS)]]
    if tuple(names) != COLUMNS:
        raise SystemExit("unexpected _atom_site columns")
    return [line.split() for line in lines[start + len(COLUMNS):] if line.startswith("ATOM ")]


def _xyz(row: list[str]) -> tuple[float, float, float]:
    return float(row[10]), float(row[11]), float(row[12])


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(sum(x * x for x in a))
    return tuple(x / n for x in a)


def _place(a, b, c, bond: float, angle_deg: float, torsion_deg: float):
    """NeRF: atom D bonded to C with angle B-C-D and dihedral A-B-C-D."""
    bc = _unit(_sub(c, b))
    n = _unit(_cross(_sub(b, a), bc))
    m = _cross(n, bc)
    ang, tor = math.radians(angle_deg), math.radians(torsion_deg)
    d2 = (-bond * math.cos(ang), bond * math.sin(ang) * math.cos(tor), bond * math.sin(ang) * math.sin(tor))
    return tuple(c[k] + d2[0] * bc[k] + d2[1] * m[k] + d2[2] * n[k] for k in range(3))


def _atoms(rows, seq):
    return {r[3]: _xyz(r) for r in rows if int(r[16]) == seq}


def _sg_pair(rows):
    a, b = _atoms(rows, 4), _atoms(rows, 66)
    others = [_xyz(r) for r in rows if int(r[16]) not in (4, 66)]
    best = None
    for ta in range(-180, 180, 2):
        sa = _place(a["N"], a["CA"], a["CB"], CB_SG, ANGLE_SG, ta)
        for tb in range(-180, 180, 2):
            sb = _place(b["N"], b["CA"], b["CB"], CB_SG, ANGLE_SG, tb)
            miss = round(abs(math.dist(sa, sb) - SS_TARGET), 6)
            clear = round(min(min(math.dist(sa, o) for o in others), min(math.dist(sb, o) for o in others)), 6)
            key = (miss, -clear, ta, tb)
            if best is None or key < best[0]:
                best = (key, sa, sb)
    return best[1], best[2]


def _single_sg(rows):
    a = _atoms(rows, 4)
    return _place(a["N"], a["CA"], a["CB"], CB_SG, ANGLE_SG, SINGLE_CHI1)


def _cif(title: str, rows: list[list[str]]) -> str:
    out = [f"data_{title}", "#", "loop_"] + [f"_atom_site.{name}" for name in COLUMNS]
    for index, row in enumerate(rows, start=1):
        out.append(" ".join([row[0], str(index)] + row[2:]))
    return "\n".join(out + ["#", ""])


def _derived(rows, sg4, sg66, both: bool) -> list[list[str]]:
    keep = {"N", "CA", "C", "O", "CB"}
    out = []
    for row in rows:
        seq = int(row[16])
        target = seq == 4 or (both and seq == 66)
        if not target:
            out.append(row)
            continue
        if row[3] not in keep:
            continue
        new = list(row)
        new[5] = new[17] = "CYS"
        out.append(new)
        if row[3] == "CB":
            sg = sg4 if seq == 4 else sg66
            sg_row = list(new)
            sg_row[2], sg_row[3], sg_row[19] = "S", "SG", "SG"
            sg_row[10:13] = [f"{x:.3f}" for x in sg]
            out.append(sg_row)
    # residue atom order: N CA C O CB SG (CB row is followed by SG; source order is N CA C O CB ...)
    return out


def _phenol(rows) -> str:
    ile = _atoms(rows, 44)
    direction = _unit(_sub(ile["CB"], ile["CA"]))
    heavy = [_xyz(r) for r in rows]
    ring_r, ch, co, oh = 1.39, 1.09, 1.36, 0.96
    # local frame: ring in the plane spanned by u, v; normal w
    u = _unit(_cross(direction, (0.0, 0.0, 1.0)))
    w = _unit(_cross(direction, u))
    v = _unit(_cross(w, u))
    local = []
    for k in range(6):
        t = math.radians(60 * k)
        local.append(("C", (ring_r * math.cos(t), ring_r * math.sin(t))))
    local.append(("O", ((ring_r + co), 0.0)))
    for k in range(1, 6):
        t = math.radians(60 * k)
        local.append(("H", ((ring_r + ch) * math.cos(t), (ring_r + ch) * math.sin(t))))
    ang = math.radians(109.0)
    ox = ring_r + co
    local.append(("H", (ox - oh * math.cos(ang), oh * math.sin(ang))))
    for distance in [x / 10 for x in range(40, 121, 5)]:
        center = tuple(ile["CB"][k] + distance * direction[k] for k in range(3))
        coords = [(el, tuple(center[k] + p * u[k] + q * v[k] for k in range(3))) for el, (p, q) in local]
        clear = min(math.dist(c, h) for el, c in coords if el != "H" for h in heavy)
        if clear >= 3.2:
            break
    lines = ["SYNTHETIC-FIXTURE phenol next to 1UBQ I44 (hand-built, not experimental)",
             "  build_mutation_model_fixtures.py", "",
             f"{len(coords):3d}{13:3d}  0  0  0  0  0  0  0  0999 V2000"]
    for el, (x, y, z) in coords:
        lines.append(f"{x:10.4f}{y:10.4f}{z:10.4f} {el:<3} 0  0  0  0  0  0  0  0  0  0  0  0")
    bonds = [(1, 2, 2), (2, 3, 1), (3, 4, 2), (4, 5, 1), (5, 6, 2), (6, 1, 1), (1, 7, 1),
             (2, 8, 1), (3, 9, 1), (4, 10, 1), (5, 11, 1), (6, 12, 1), (7, 13, 1)]
    for a, b, order in bonds:
        lines.append(f"{a:3d}{b:3d}{order:3d}  0")
    lines += ["M  END", "$$$$", ""]
    return "\n".join(lines), distance, clear


# ---------------------------------------------------------------- hand oracles (closed form, written before use)
CONTACT_ATOMS = [  # index, residue ordinal (structure order), residue name, atom name, element, xyz (A)
    (0, 1, "ALA", "CA", "C", (1.5, 1.5, 4.0)),
    (1, 1, "ALA", "C", "C", (-1.5, 0.0, 0.0)),
    (2, 2, "MUT", "N", "N", (0.0, 0.0, 0.0)),
    (3, 2, "MUT", "CA", "C", (1.5, 0.0, 0.0)),
    (4, 2, "MUT", "CB", "C", (1.5, 1.5, 0.0)),
    (5, 3, "GLY", "N", "N", (3.0, 0.0, 0.0)),
    (6, 3, "GLY", "CA", "C", (4.5, 0.0, 0.0)),
    (7, 3, "GLY", "CB", "C", (0.0, 0.0, 3.0)),
    (8, 4, "SOL", "O", "O", (1.5, 1.5, -4.25)),
    (9, 4, "SOL", "SD", "S", (0.0, -3.0, 0.0)),
    (10, 4, "SOL", "H1", "H", (0.0, -1.0, 0.0)),
    (11, 2, "MUT", "H", "H", (0.0, 0.0, -1.0)),
]
CONTACT_BONDS = [[0, 1], [1, 2], [2, 3], [3, 4], [3, 5], [5, 6], [6, 7], [2, 11], [9, 10]]


def _expected() -> dict:
    # Graph distance <= 3 bonds is excluded. Rows sorted by (mutated atom order, partner residue order, partner atom
    # order). Distances by hand: N(0,0,0)-CB3(0,0,3) = 3; N-SD(0,-3,0) = 3; CA(1.5,0,0)-SD = sqrt(1.5^2+3^2);
    # CB(1.5,1.5,0)-CA1(1.5,1.5,4) = 4 (4 bonds: CB-CA-N-C-CA1, boundary included);
    # CB-CB3(0,0,3) = sqrt(1.5^2+1.5^2+3^2) (4 bonds: CB-CA-N3-CA3-CB3).
    rows4 = [[2, 7, 3.0], [2, 9, 3.0], [3, 9, math.sqrt(11.25)], [4, 0, 4.0], [4, 7, math.sqrt(13.5)]]
    excluded_close = [  # (mutated, other, bonds, distance) pairs that are within 4.0 A but <= 3 bonds apart
        [2, 1, 1, 1.5], [2, 5, 2, 3.0], [3, 1, 2, 3.0], [3, 5, 1, 1.5], [3, 6, 2, 3.0], [3, 7, 3, math.sqrt(11.25)],
        [4, 1, 3, math.sqrt(11.25)], [4, 5, 2, math.sqrt(4.5)], [4, 6, 3, math.sqrt(11.25)]]
    # Lee-Richards SASA oracle: expanded radii R = vdW + 1.4. gemmi stores vdW radii as float32 (C 1.7, O 1.52 ->
    # nearest float32), and mw/tools/sasa.py passes those values, so the oracle uses the float32 values too.
    rc, ro = (struct.unpack("f", struct.pack("f", v))[0] for v in (1.7, 1.52))
    r1, r2, d = rc + 1.4, ro + 1.4, 4.0
    x = (d * d + r1 * r1 - r2 * r2) / (2 * d)       # centre-1 to intersection plane
    exposed_1 = 2 * math.pi * r1 * (r1 + x)          # sphere area minus the buried cap 2*pi*R1*(R1 - x)
    return {
        "schema": "m21_mutation_model_fixture_oracle@1",
        "provenance": "SYNTHETIC hand-derived values; see SYNTHETIC-PROVENANCE.md",
        "contacts": {
            "atoms": [{"index": i, "residue_ordinal": r, "resname": n, "atom_name": a, "element": e, "xyz_A": list(p)}
                      for i, r, n, a, e, p in CONTACT_ATOMS],
            "bonds": CONTACT_BONDS, "mutated_residue_ordinal": 2, "excluded_bond_distance": 3,
            "expected": {
                "4.0": {"rows": [{"mutated_atom": a, "partner_atom": b, "distance_A": dd} for a, b, dd in rows4],
                        "count": 5, "residue_count": 3},
                "3.0": {"rows": [{"mutated_atom": 2, "partner_atom": 7, "distance_A": 3.0},
                                 {"mutated_atom": 2, "partner_atom": 9, "distance_A": 3.0}],
                        "count": 2, "residue_count": 2},
                "2.5": {"rows": [], "count": 0, "residue_count": 0}},
            "excluded_close_pairs_4A": [{"mutated_atom": a, "partner_atom": b, "bonds": n, "distance_A": dd}
                                        for a, b, n, dd in excluded_close],
            "notes": "H atoms 10 and 11 are never contacts (heavy atoms only); atom 8 is 4.25 A from CB (outside)."},
        "sasa": {
            "radii_A": {"C": rc, "O": ro}, "radii_decimal_A": {"C": 1.7, "O": 1.52}, "probe_A": 1.4, "algorithm": "LeeRichards", "n_slices": 100,
            "isolated_carbon": {"xyz_A": [[0.0, 0.0, 0.0]], "elements": ["C"],
                                "expected_A2": 4 * math.pi * r1 * r1, "tolerance_A2": 1e-6},
            "carbon_with_oxygen_at_4A": {"xyz_A": [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]], "elements": ["C", "O"],
                                         "residue_of_interest": 0, "expected_A2": exposed_1,
                                         "tolerance_relative": 0.005,
                                         "formula": "2*pi*R1*(R1 + (d^2 + R1^2 - R2^2)/(2d))"}},
    }


def build() -> dict[str, str]:
    rows = _rows()
    sg4, sg66 = _sg_pair(rows)
    files = {PAIR_NAME: _cif("DERIVED_SYNTHETIC_1UBQ_F4C_T66C", _derived(rows, sg4, sg66, True)),
             SINGLE_NAME: _cif("DERIVED_SYNTHETIC_1UBQ_F4C", _derived(rows, _single_sg(rows), sg66, False))}
    files[LIGAND_NAME] = _phenol(rows)[0]
    files[EXPECTED_NAME] = json.dumps(_expected(), indent=1, sort_keys=True) + "\n"
    return files


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    bad = 0
    for name, text in build().items():
        raw = text.encode()
        path = HERE / name
        if check:
            same = path.is_file() and path.read_bytes() == raw
            bad += not same
            print(("OK  " if same else "DIFF"), name)
        else:
            path.write_bytes(raw)
            print(hashlib.sha256(raw).hexdigest(), len(raw), name)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
