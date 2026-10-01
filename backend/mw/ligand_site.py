"""M17 site pre-check as a pure graph test on a stored inspection (spec 4.1). No RDKit.

Input graph (the fields T3 writes into ``ligand_inspection@1``; every number is the 1-based SDF atom-block
serial, H lines included, so heavy serials may have gaps):

    {"atoms":     [{"serial": int, "element": str, "formal_charge": int, "neighbors": [int, ...]}, ...],
                  # heavy atoms only; neighbors = heavy-atom serials, equal to the bond list
     "bonds":     [{"a": int, "b": int, "order": "single" | "double" | "triple" | "aromatic"}, ...],
                  # heavy-heavy bonds only, RDKit-sanitized bond types, each pair once
     "hydrogens": [{"serial": int, "attached_to": int}, ...]}
                  # explicit H atoms of the SDF and their heavy neighbour; [] when the SDF has none

``check_site(graph, site_atoms)`` returns ``ligand_site_check@1``. ``site_atoms`` are heavy serials. On
success ``retained_parent_atoms`` is every parent atom outside the site in ascending serial order: the core
heavy atoms plus the explicit H attached to them; H attached to site atoms leave with the site
(``site_hydrogens``). Fields not evaluated for a failing reason are ``None`` (never an empty or zero value).
Reason precedence: site_empty, site_atom_unknown, core_empty, crossing_bond_count, crossing_bond_not_single.
A stored parent is one connected heavy-atom fragment (checked by the worker), so exactly one crossing bond
implies a connected site and a connected core.
"""
from __future__ import annotations

from typing import Any

from .core.errors import FailureClass, ToolFailure
from .ligand_constants import BOND_ORDERS


def _invalid(message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message)


def _serial(value: Any) -> bool:
    return type(value) is int and value >= 1


def _graph(graph: Any) -> tuple[dict[int, list[int]], dict[frozenset[int], str], dict[int, int]]:
    if type(graph) is not dict or not {"atoms", "bonds", "hydrogens"} <= set(graph):
        raise _invalid("inspection graph is missing atoms, bonds or hydrogens")
    atoms, bonds, hydrogens = graph["atoms"], graph["bonds"], graph["hydrogens"]
    if type(atoms) is not list or type(bonds) is not list or type(hydrogens) is not list or not atoms:
        raise _invalid("inspection graph fields must be lists")
    neighbors: dict[int, list[int]] = {}
    for atom in atoms:
        if (type(atom) is not dict or not _serial(atom.get("serial")) or atom["serial"] in neighbors or
                type(atom.get("neighbors")) is not list or not all(_serial(n) for n in atom["neighbors"])):
            raise _invalid("inspection atom row is malformed or repeated")
        neighbors[atom["serial"]] = atom["neighbors"]
    orders: dict[frozenset[int], str] = {}
    for bond in bonds:
        if (type(bond) is not dict or set(bond) != {"a", "b", "order"} or bond["order"] not in BOND_ORDERS or
                not _serial(bond["a"]) or not _serial(bond["b"])):
            raise _invalid("inspection bond row is malformed")
        pair = frozenset((bond["a"], bond["b"]))
        if len(pair) != 2 or not pair <= neighbors.keys() or pair in orders:
            raise _invalid("inspection bond is dangling, a self bond or repeated")
        orders[pair] = bond["order"]
    for serial, listed in neighbors.items():
        bonded = sorted(other for pair in orders if serial in pair for other in pair if other != serial)
        if sorted(listed) != bonded:
            raise _invalid("inspection neighbors disagree with the bond list")
    attached: dict[int, int] = {}
    for row in hydrogens:
        if (type(row) is not dict or set(row) != {"serial", "attached_to"} or not _serial(row["serial"]) or
                row["serial"] in neighbors or row["serial"] in attached or row["attached_to"] not in neighbors):
            raise _invalid("inspection hydrogen row is malformed")
        attached[row["serial"]] = row["attached_to"]
    return neighbors, orders, attached


def check_site(graph: Any, site_atoms: Any) -> dict[str, Any]:
    neighbors, orders, attached = _graph(graph)
    # Any integer is a well-formed request; integers not in the heavy-atom table are site_atom_unknown.
    if (type(site_atoms) is not list or not all(type(x) is int for x in site_atoms) or
            len(set(site_atoms)) != len(site_atoms)):
        raise _invalid("site atoms must be a list of distinct integer SDF serials")
    site = sorted(site_atoms)
    result: dict[str, Any] = {"schema": "ligand_site_check@1", "valid": False, "reason": None,
                              "site_atoms": site, "unknown_atoms": None, "core_atoms": None,
                              "crossing_bonds": None, "site_hydrogens": None, "retained_parent_atoms": None}
    if not site:
        return {**result, "reason": "site_empty"}
    unknown = [x for x in site if x not in neighbors]
    if unknown:
        return {**result, "reason": "site_atom_unknown", "unknown_atoms": unknown}
    chosen = set(site)
    core = sorted(set(neighbors) - chosen)
    result["unknown_atoms"] = []
    result["core_atoms"] = core
    if not core:
        return {**result, "reason": "core_empty"}
    crossing = []
    for pair, order in orders.items():
        inside = pair & chosen
        if len(inside) == 1:
            (site_atom,), (core_atom,) = inside, pair - chosen
            crossing.append({"core_atom": core_atom, "site_atom": site_atom, "order": order})
    crossing.sort(key=lambda bond: (bond["core_atom"], bond["site_atom"]))
    result["crossing_bonds"] = crossing
    if len(crossing) != 1:
        return {**result, "reason": "crossing_bond_count"}
    if crossing[0]["order"] != "single":
        return {**result, "reason": "crossing_bond_not_single"}
    site_h = sorted(h for h, heavy in attached.items() if heavy in chosen)
    core_h = [h for h, heavy in attached.items() if heavy not in chosen]
    return {**result, "valid": True, "site_hydrogens": site_h, "retained_parent_atoms": sorted(core + core_h)}
