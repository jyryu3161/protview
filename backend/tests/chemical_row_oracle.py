"""Independent per-row oracle for stored M11 chemical interaction rows (test-only).

It re-derives every checked quantity from the stored immutable graph (engine coordinates,
elements, formal charges, bond orders) and the stored result criteria with its own arithmetic.
It shares no code with ``mw.chemical_bundle`` validation, so it is not the product compared with
itself. It checks the pinned ProLIF 2.2.2 default category semantics (role elements, explicit
H bonding, charge patterns), not experimental truth.
"""
from __future__ import annotations

import math

# The fixture probe counts asserted next to this oracle are pinned-engine regression goldens.
# They are valid only for the ProLIF wheel set recorded by this dependency lock-file hash; a
# relock must fail here so the goldens are re-derived and consciously updated, never silently.
PINNED_GOLDEN_LOCK_SHA256 = "be320702daba7ea9922e278c49d6c69efc6f3ce7962a7be47623421b2387999a"

_DONORS = {"N", "O", "S"}
_ACCEPTORS = {"N", "O", "F"}
_HYDROPHOBIC = {"C", "S", "BR", "I"}


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _angle_deg(vertex: list[float], first: list[float], second: list[float]) -> float:
    u = [a - b for a, b in zip(first, vertex, strict=True)]
    v = [a - b for a, b in zip(second, vertex, strict=True)]
    cosine = sum(x * y for x, y in zip(u, v)) / math.sqrt(sum(x * x for x in u) * sum(y * y for y in v))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _neighbors(bonds: list[dict], index: int) -> list[tuple[int, str]]:
    return ([(b["second"], b["order"]) for b in bonds if b["first"] == index] +
            [(b["first"], b["order"]) for b in bonds if b["second"] == index])


def _is_cation(atoms: list[dict], bonds: list[dict], index: int) -> bool:
    """Positive formal charge, or an amidine/guanidine N bonded to C=N+ (ProLIF 2.2.2 default)."""
    if atoms[index]["formal_charge"] > 0:
        return True
    return atoms[index]["element"].upper() == "N" and any(
        atoms[c]["element"].upper() == "C" and any(
            order == "DOUBLE" and atoms[n]["element"].upper() == "N" and atoms[n]["formal_charge"] > 0
            for n, order in _neighbors(bonds, c))
        for c, _ in _neighbors(bonds, index))


def _is_anion(atoms: list[dict], bonds: list[dict], index: int) -> bool:
    """Negative formal charge, or O=[C,S,P]-[O-] (ProLIF 2.2.2 default)."""
    if atoms[index]["formal_charge"] < 0:
        return True
    return atoms[index]["element"].upper() == "O" and any(
        order == "DOUBLE" and atoms[x]["element"].upper() in {"C", "S", "P"} and any(
            o != index and atoms[o]["element"].upper() == "O" and atoms[o]["formal_charge"] < 0
            for o, _ in _neighbors(bonds, x))
        for x, order in _neighbors(bonds, index))


def assert_rows_independently_valid(result: dict, graph: dict) -> None:
    criteria = result["criteria"]
    cutoff = {"HBDonor": criteria["Hbond_distance_A"], "HBAcceptor": criteria["Hbond_distance_A"],
              "Hydrophobic": criteria["Hydrophobic_distance_A"],
              "Cationic": criteria["Cationic_distance_A"], "Anionic": criteria["Anionic_distance_A"]}
    low, high = criteria["Hbond_DHA_angle_deg"]
    ligand, receptor = graph["ligand_atoms"], graph["receptor_atoms"]
    assert result["total"] == len(result["rows"])
    for row in result["rows"]:
        category = row["category"]
        lig_ids = row["native_parent_indices"]["ligand"]
        rec_ids = row["native_parent_indices"]["protein"]
        assert lig_ids and rec_ids
        assert row["ligand_atoms"] == [ligand[i]["ref"] for i in lig_ids]
        assert row["receptor_atoms"] == [receptor[i]["ref"] for i in rec_ids]
        if category == "HBDonor":
            assert (len(lig_ids), len(rec_ids)) == (2, 1)
            donor, hydrogen, acceptor = ligand[lig_ids[0]], ligand[lig_ids[1]], receptor[rec_ids[0]]
            donor_side = ("ligand", lig_ids[0], lig_ids[1])
            ends = (donor, acceptor)
        elif category == "HBAcceptor":
            assert (len(lig_ids), len(rec_ids)) == (1, 2)
            donor, hydrogen, acceptor = receptor[rec_ids[0]], receptor[rec_ids[1]], ligand[lig_ids[0]]
            donor_side = ("receptor", rec_ids[0], rec_ids[1])
            ends = (donor, acceptor)
        else:
            ends = (ligand[lig_ids[0]], receptor[rec_ids[0]])
            if category == "Anionic":
                ends = (receptor[rec_ids[0]], ligand[lig_ids[0]])  # (cation, anion)
        points = [atom["engine_coordinate_A"] for atom in ends]
        assert [row["engine_role_coordinates_A"][role] for role in row["distance_roles"]] == points
        distance = _distance(*points)
        assert abs(distance - row["distance_A"]) <= 1e-6, row["row_id"]
        assert distance <= cutoff[category] + 1e-9, row["row_id"]
        if category in {"HBDonor", "HBAcceptor"}:
            side, donor_index, hydrogen_index = donor_side
            bonds = graph[f"{side}_bonds"]
            assert hydrogen["element"].upper() == "H" and donor["element"].upper() in _DONORS
            assert acceptor["element"].upper() in _ACCEPTORS
            assert [n for n, _ in _neighbors(bonds, hydrogen_index)] == [donor_index], "explicit H on donor"
            angle = _angle_deg(hydrogen["engine_coordinate_A"], donor["engine_coordinate_A"],
                               acceptor["engine_coordinate_A"])
            assert abs(angle - row["DHA_angle_deg"]) <= 1e-6, row["row_id"]
            assert low - 1e-9 <= angle <= high + 1e-9, row["row_id"]
        else:
            assert row["DHA_angle_deg"] is None
            if category == "Hydrophobic":
                assert all(atom["element"].upper() in _HYDROPHOBIC and atom["formal_charge"] == 0
                           for atom in ends), row["row_id"]
            else:
                cation_side = ("ligand", lig_ids[0]) if category == "Cationic" else ("receptor", rec_ids[0])
                anion_side = ("receptor", rec_ids[0]) if category == "Cationic" else ("ligand", lig_ids[0])
                assert _is_cation(graph[f"{cation_side[0]}_atoms"], graph[f"{cation_side[0]}_bonds"],
                                  cation_side[1]), row["row_id"]
                assert _is_anion(graph[f"{anion_side[0]}_atoms"], graph[f"{anion_side[0]}_bonds"],
                                 anion_side[1]), row["row_id"]
