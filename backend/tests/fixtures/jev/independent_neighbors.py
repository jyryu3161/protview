"""Independent oracle for the M24 mutation projection geometry (T1, before any product code exists).

Reads a structure with gemmi only (no ``mw`` import, no numpy) and computes, per the spec 3 wording:

* neighbors: every OTHER protein residue (gemmi ``het_flag == "A"``, the M20 position definition; waters, ligands and
  metals are HETATM and therefore excluded) in any chain of the first model whose heavy-atom (element not H/D) minimum
  distance to the target residue's heavy atoms is <= 5.0 A, in structure (file) order, as
  ``{chain_auth, seq_auth, icode, resname}``. Distances are ``math.dist`` on gemmi float64 positions. A target without
  any heavy atom has neighbors ``None`` (not computed, never ``[]``; RULE N3, fixed in M24 T3).
* window: the protein residues of the same model and chain in structure order, 5 before and 5 after the target
  (the target itself included, ASSUMPTION W1), ``residues`` as a string of one-letter codes by the M20 position
  ``one_letter`` rule: the 20 standard names plus the ten M12/M20 mapped names (HID/HIE/HIP/HSD/HSE/HSP -> H, CYX -> C,
  ASH -> D, GLH -> E, LYN -> K), anything else ``X`` (RULE W2, fixed in M24 T3; written out here, not imported),
  ``first_seq_auth`` of the first window residue and ``contiguous`` = every window residue has an empty insertion code
  and ``seq_auth`` increases by exactly 1 along the window.
* ligand_min_distance_A: heavy-atom minimum distance from the target to a named ligand residue (when given).

``python3 independent_neighbors.py --check`` recomputes every entry of ``expected.json`` and exits 0 only if all are
equal; ``--write`` rewrites it. Labelled ORACLE, not product output; see SYNTHETIC-PROVENANCE.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import gemmi

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent
EXPECTED = HERE / "expected.json"
NEIGHBOR_RADIUS_A = 5.0
WINDOW_FLANK = 5
HYDROGENS = ("H", "D")
ONE_LETTER = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K",
    "LEU": "L", "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S", "THR": "T", "VAL": "V",
    "TRP": "W", "TYR": "Y",
}
MAPPED = {"HID": "H", "HIE": "H", "HIP": "H", "HSD": "H", "HSE": "H", "HSP": "H", "CYX": "C", "ASH": "D", "GLH": "E",
          "LYN": "K"}
STRUCTURES = {"1UBQ": FIXTURES / "public_1ubq.cif", "1MQ4": FIXTURES / "public_1mq4.cif"}
# (structure, chain_auth, seq_auth, icode): chain ends, a gap (1MQ4 285|288), ligand-shell residues, a core residue.
SELECTED = {
    "1UBQ": [("A", 1, ""), ("A", 2, ""), ("A", 44, ""), ("A", 48, ""), ("A", 72, ""), ("A", 76, "")],
    "1MQ4": [("A", 126, ""), ("A", 143, ""), ("A", 162, ""), ("A", 211, ""), ("A", 274, ""), ("A", 283, ""),
             ("A", 285, ""), ("A", 288, ""), ("A", 290, ""), ("A", 388, "")],
}
LIGANDS = {"1MQ4": ("A", 2001, "", "ADP")}


def load_path(path: Path) -> gemmi.Structure:
    return gemmi.read_structure(str(path))


def load_cif_text(text: str) -> gemmi.Structure:
    return gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())


def residues(st: gemmi.Structure) -> list[dict[str, Any]]:
    """First model, file order: identity, protein flag, heavy-atom positions."""
    model = st[0]
    out = []
    for chain in model:
        for res in chain:
            heavy = [(atom.pos.x, atom.pos.y, atom.pos.z) for atom in res
                     if atom.element.name.upper() not in HYDROGENS]
            out.append({"chain_auth": chain.name, "seq_auth": res.seqid.num, "icode": res.seqid.icode.strip(),
                        "resname": res.name, "protein": res.het_flag == "A", "heavy": heavy})
    return out


def min_distance(a: list[tuple[float, float, float]], b: list[tuple[float, float, float]]) -> float | None:
    if not a or not b:
        return None
    return min(math.dist(p, q) for p in a for q in b)


def key(entry: dict[str, Any]) -> tuple[str, int, str]:
    return entry["chain_auth"], entry["seq_auth"], entry["icode"]


def ident(entry: dict[str, Any]) -> dict[str, Any]:
    return {field: entry[field] for field in ("chain_auth", "seq_auth", "icode", "resname")}


def neighbors(all_res: list[dict[str, Any]],
              target: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Neighbors in structure order plus the boundary margins (largest included, smallest excluded distance).

    RULE N3: a target without heavy atoms is not computed -> (None, both margins None).
    """
    if not target["heavy"]:
        return None, {"largest_included_A": None, "smallest_excluded_A": None}
    found, inside, outside = [], [], []
    for other in all_res:
        if not other["protein"] or key(other) == key(target):
            continue
        distance = min_distance(target["heavy"], other["heavy"])
        if distance is None:
            continue
        if distance <= NEIGHBOR_RADIUS_A:
            found.append(ident(other))
            inside.append(distance)
        else:
            outside.append(distance)
    margins = {"largest_included_A": max(inside) if inside else None,
               "smallest_excluded_A": min(outside) if outside else None}
    return found, margins


def window(all_res: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any] | None:
    if target["chain_auth"] is None:
        return None
    chain = [entry for entry in all_res if entry["protein"] and entry["chain_auth"] == target["chain_auth"]]
    index = [key(entry) for entry in chain].index(key(target))
    span = chain[max(0, index - WINDOW_FLANK):index + WINDOW_FLANK + 1]
    contiguous = all(entry["icode"] == "" for entry in span) and all(
        later["seq_auth"] == earlier["seq_auth"] + 1 for earlier, later in pairwise(span))
    return {"chain_auth": target["chain_auth"], "first_seq_auth": span[0]["seq_auth"],
            "residues": "".join(ONE_LETTER.get(entry["resname"], MAPPED.get(entry["resname"], "X"))
                                for entry in span),
            "contiguous": contiguous, "members": [[entry["seq_auth"], entry["icode"]] for entry in span]}


def compute(name: str, st: gemmi.Structure) -> dict[str, Any]:
    all_res = residues(st)
    by_key = {key(entry): entry for entry in all_res}
    ligand = None
    if name in LIGANDS:
        chain, seq, icode, resname = LIGANDS[name]
        ligand = by_key[(chain, seq, icode)]
        assert ligand["resname"] == resname and not ligand["protein"]
    positions = []
    for chain, seq, icode in SELECTED[name]:
        target = by_key[(chain, seq, icode)]
        assert target["protein"]
        found, margins = neighbors(all_res, target)
        positions.append({"residue": ident(target), "neighbors": found,
                          "neighbor_count": None if found is None else len(found),
                          "margins": margins, "window": window(all_res, target),
                          "ligand_min_distance_A": (min_distance(target["heavy"], ligand["heavy"])
                                                    if ligand is not None else None)})
    counts = []
    for entry in all_res:
        if entry["protein"]:
            found = neighbors(all_res, entry)[0]
            counts.append([entry["chain_auth"], entry["seq_auth"], entry["icode"], entry["resname"],
                           None if found is None else len(found)])
    return {"protein_residues": sum(entry["protein"] for entry in all_res),
            "ligand": None if ligand is None else ident(ligand),
            "positions": positions, "neighbor_counts": counts}


def build() -> dict[str, Any]:
    return {
        "_fixture": ("ORACLE (independent, gemmi only, no mw import): M24 T1 expected neighbors / windows / ligand "
                     "distances for public 1UBQ and 1MQ4. Not product output."),
        "constants": {"neighbor_radius_A": NEIGHBOR_RADIUS_A, "window_flank": WINDOW_FLANK,
                      "hydrogen_elements": list(HYDROGENS)},
        "assumptions": {
            "W1": "the window includes the target residue (5 before + target + 5 after, cut at chain ends)",
            "W2": ("one-letter codes by the M20 one_letter rule: the 20 standard names plus the ten mapped names "
                   "(HID/HIE/HIP/HSD/HSE/HSP H, CYX C, ASH D, GLH E, LYN K); any other name (incl. MSE) is X"),
            "N1": "protein residue = gemmi het_flag 'A' (ATOM record), as M20 positions; first model only",
            "N2": "a protein residue without heavy atoms is never a neighbor (no distance)",
            "N3": "a target residue without heavy atoms has neighbors null (not computed), never []",
            "D1": "distances are math.dist on gemmi float64 positions; <= 5.0 inclusive",
        },
        "structures": {name: compute(name, load_path(path)) for name, path in STRUCTURES.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    fresh = build()
    if args.write:
        EXPECTED.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {EXPECTED.name}")
        return 0
    stored = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if stored != fresh:
        print("expected.json differs from a fresh oracle run", file=sys.stderr)
        return 1
    print("expected.json matches a fresh oracle run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
