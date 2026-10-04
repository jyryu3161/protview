"""M21 contact computation, structure comparison and the pure ``mutation_model@1`` validator (spec 3 (8), 4).

No OpenMM, no PDBFixer, no store: the job module calls ``contacts``, ``topology_sha256``, ``disulfide_bonds`` and
``compare_structures`` to build a result, and every reader (bundle before publishing, reads, reports) calls
``validated_model`` on the stored content, which recomputes those values from the stored atoms and bonds.

* An atom (``atom_mapping`` row) is ``{residue (7 fields), atom_name, element, coordinates_A}`` in final coordinate
  order; residue order is the order of first appearance. Hydrogen means element H or D.
* Contacts: heavy atoms of the mutated residue against heavy atoms of every other residue in every chain, Euclidean
  distance from the stored float64 coordinates ``<= cutoff`` (inclusive), minus pairs within
  ``EXCLUDED_BOND_DISTANCE`` bonds in the stored final bond graph. Rows are ordered by (mutated atom position in the
  structure, partner residue order, partner atom position); distances are stored unrounded. Zero rows is a computed
  result. More than ``MAX_CONTACT_ROWS`` rows raises ``ContactLimitExceeded`` (nothing is truncated).
* Rows of the two structures are paired by the 7 residue fields; the mutated residue (``resname`` = the mutant name
  in the mutant structure) is paired by its original 7 fields.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from . import mutation_model_constants as K
from .core.handles import canonical_json
from .mutation_candidates import identity, seven, standard_name
from .mutation_constants import IDENTITY_FIELDS, STANDARD_ONE_LETTER
from .openmm_bundle import FORCEFIELD_SHA256


class ContactLimitExceeded(ValueError):
    """More contact rows than ``MAX_CONTACT_ROWS`` in one structure (job failure ``resource_exceeded``)."""

    def __init__(self, rows: int) -> None:
        super().__init__(f"{rows} contact rows exceed the limit of {K.MAX_CONTACT_ROWS}")
        self.reason_code = "resource_exceeded"
        self.detail = {"reason_code": "resource_exceeded", "limit": K.TOO_MANY_CONTACTS, "rows": rows,
                       "max_rows": K.MAX_CONTACT_ROWS}


class ModelInvalid(ValueError):
    """Stored ``mutation_model@1`` content that fails the pure validation."""


# --- computation -----------------------------------------------------------------------------------------------------

def _heavy(atom: dict[str, Any]) -> bool:
    return atom["element"] not in K.HYDROGEN_ELEMENTS


def _within_bonds(bonds: Iterable[list[int]], sources: list[int], depth: int) -> dict[int, set[int]]:
    """``{source: atoms at graph distance 1..depth}`` over the undirected bond graph."""
    neighbours: dict[int, set[int]] = {}
    for a, b in bonds:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    out = {}
    for source in sources:
        seen, frontier = {source}, {source}
        for _ in range(depth):
            frontier = {n for atom in frontier for n in neighbours.get(atom, ())} - seen
            seen |= frontier
        out[source] = seen - {source}
    return out


def contacts(atoms: list[dict[str, Any]], bonds: list[list[int]], mutated: dict[str, Any],
             cutoff_A: float) -> dict[str, Any]:
    """The ``contacts`` entry of one structure; ``mutated`` is that structure's 7-field identity of the residue."""
    key = identity(mutated)
    residue_order: dict[tuple[Any, ...], int] = {}
    for atom in atoms:
        residue_order.setdefault(identity(atom["residue"]), len(residue_order))
    mine = [i for i, atom in enumerate(atoms) if _heavy(atom) and identity(atom["residue"]) == key]
    if not mine:
        raise ValueError("the mutated residue has no heavy atom in this structure")
    others = [i for i, atom in enumerate(atoms) if _heavy(atom) and identity(atom["residue"]) != key]
    bonded = _within_bonds(bonds, mine, K.EXCLUDED_BOND_DISTANCE)
    rows: list[dict[str, Any]] = []
    if others:
        coords = np.array([atom["coordinates_A"] for atom in atoms], dtype=np.float64).reshape(-1, 3)
        diff = coords[mine][:, None, :] - coords[others][None, :, :]
        distances = np.sqrt((diff * diff).sum(axis=2))
        for row, i in enumerate(mine):
            hits = [(residue_order[identity(atoms[others[col]]["residue"])], others[col], float(distances[row, col]))
                    for col in np.flatnonzero(distances[row] <= cutoff_A) if others[col] not in bonded[i]]
            for _order, j, distance in sorted(hits):
                rows.append({"atom_name": atoms[i]["atom_name"], "element": atoms[i]["element"],
                             "partner_residue": seven(atoms[j]["residue"]), "partner_atom_name": atoms[j]["atom_name"],
                             "partner_element": atoms[j]["element"], "distance_A": distance})
    if len(rows) > K.MAX_CONTACT_ROWS:
        raise ContactLimitExceeded(len(rows))
    return {"cutoff_A": cutoff_A, "excluded_bond_distance": K.EXCLUDED_BOND_DISTANCE, "rows": rows,
            "count": len(rows), "residue_count": len({identity(row["partner_residue"]) for row in rows})}


def topology_sha256(atoms: list[dict[str, Any]], bonds: list[list[int]]) -> str:
    """SHA-256 of canonical JSON ``{atoms: [{residue, atom_name, element}], bonds}`` (coordinates excluded)."""
    topology = {"atoms": [{"residue": atom["residue"], "atom_name": atom["atom_name"], "element": atom["element"]}
                          for atom in atoms], "bonds": bonds}
    return hashlib.sha256(canonical_json(topology)).hexdigest()


def disulfide_bonds(atoms: list[dict[str, Any]], bonds: list[list[int]]) -> list[list[dict[str, Any]]]:
    """Residue pairs of the SG--SG bonds in ``bonds`` (bond order, each pair in bond direction)."""
    return [[seven(atoms[a]["residue"]), seven(atoms[b]["residue"])] for a, b in bonds
            if atoms[a]["atom_name"] == atoms[b]["atom_name"] == K.DISULFIDE_ATOM
            and identity(atoms[a]["residue"]) != identity(atoms[b]["residue"])]


def protonation_variants(atoms: list[dict[str, Any]], variants: dict[tuple[Any, ...], str | None]
                         ) -> list[dict[str, Any]]:
    """One row per HIS/CYS residue in structure order: ``{residue, variant}`` (``variants`` keyed by identity)."""
    rows, seen = [], set()
    for atom in atoms:
        key = identity(atom["residue"])
        if key not in seen and atom["residue"]["resname"] in K.PROTONATION_VARIANTS:
            seen.add(key)
            rows.append({"residue": seven(atom["residue"]), "variant": variants[key]})
    return rows


def compare_structures(candidate: dict[str, Any], wild: dict[str, Any],
                       mutant: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(comparison, protonation_differences)`` from the two structure entries' disulfide and variant rows."""
    original = candidate["residue"]
    renamed = identity({**original, "resname": candidate["mutant_resname"]})

    def paired(residue: dict[str, Any]) -> tuple[Any, ...]:
        key = identity(residue)
        return identity(original) if key == renamed else key

    def pairs(entry: dict[str, Any]) -> set[frozenset[tuple[Any, ...]]]:
        return {frozenset((paired(a), paired(b))) for a, b in entry["disulfide_bonds"]}

    mutant_variants = {paired(row["residue"]): row["variant"] for row in mutant["protonation_variants"]}
    differences = [{"residue": seven(row["residue"]), "wild_type_reference": row["variant"],
                    "mutant": mutant_variants[identity(row["residue"])]}
                   for row in wild["protonation_variants"]
                   if identity(row["residue"]) != identity(original) and identity(row["residue"]) in mutant_variants
                   and mutant_variants[identity(row["residue"])] != row["variant"]]
    comparison = {"mutated_residue": seven(original),
                  "resnames": {"wild_type_reference": original["resname"], "mutant": candidate["mutant_resname"]},
                  "new_disulfide_in_mutant": bool(pairs(mutant) - pairs(wild)),
                  "protonation_difference_count": len(differences)}
    return comparison, differences


# --- validation of stored content ------------------------------------------------------------------------------------

_TOP_KEYS = {"schema", "method_version", "candidate", "structure", "parameters", "method", "excluded_components",
             "structures", "comparison", "protonation_differences", "limitations"}
_STRUCTURE_KEYS = {"structure_object", "structure_sha256", "system_xml_sha256", "topology_sha256", "heavy_atoms",
                   "added_hydrogens", "added_heavy_atoms", "protonation_variants", "disulfide_bonds", "final_bonds",
                   "atom_mapping", "energy", "sasa", "contacts"}
_ATOM_KEYS = {"residue", "atom_name", "element", "coordinates_A"}
_HASH_FIELDS = ("structure_sha256", "system_xml_sha256", "topology_sha256")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelInvalid(message)


def _is_int(value: Any, low: int = 0) -> bool:
    return type(value) is int and value >= low


def _is_float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _is_hex(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _is_seven(value: Any, model_number: int) -> bool:
    return (isinstance(value, dict) and set(value) == set(IDENTITY_FIELDS) and type(value["model_number"]) is int
            and value["model_number"] == model_number and type(value["chain_auth"]) is str
            and (value["chain_label"] is None or type(value["chain_label"]) is str)
            and type(value["seq_auth"]) is int and (value["seq_label"] is None or type(value["seq_label"]) is int)
            and type(value["icode"]) is str and type(value["resname"]) is str and value["resname"] != "")


def _validate_candidate(candidate: Any, model_number: int) -> None:
    _require(isinstance(candidate, dict) and set(candidate) == {"candidate_set", "candidate_index", "position_index",
                                                                "from", "to", "residue", "mutant_resname"},
             "candidate keys")
    _require(type(candidate["candidate_set"]) is str and candidate["candidate_set"] != ""
             and _is_int(candidate["candidate_index"]) and _is_int(candidate["position_index"]), "candidate refs")
    _require(candidate["from"] in K.THREE_LETTER and candidate["to"] in K.THREE_LETTER
             and candidate["from"] != candidate["to"]
             and candidate["mutant_resname"] == K.THREE_LETTER[candidate["to"]], "candidate letters")
    _require(_is_seven(candidate["residue"], model_number), "candidate residue")
    standard = standard_name(candidate["residue"]["resname"])
    _require(standard is not None and STANDARD_ONE_LETTER[standard] == candidate["from"], "candidate from residue")


def _validate_method(method: Any) -> None:
    _require(isinstance(method, dict) and set(method) == set(K.METHOD_KEYS), "method keys")
    fixed = {**K.M7_METHOD_FIXED, **K.MUTATION_METHOD_FIXED}
    _require(all(canonical_json(method[k]) == canonical_json(v) for k, v in fixed.items()), "fixed method")
    _require(type(method["engine_build"]) is str and method["engine_build"].startswith(K.OPENMM_VERSION),
             "engine build")
    _require(method["forcefield_files_sha256"] == FORCEFIELD_SHA256, "force-field fingerprint")


def _validate_atoms(atoms: Any, bonds: Any, model_number: int) -> list[tuple[Any, ...]]:
    """Shape of ``atom_mapping`` and ``final_bonds``; the residue identities in structure order."""
    _require(isinstance(atoms, list) and atoms, "atom_mapping")
    order: list[tuple[Any, ...]] = []
    names: set[tuple[Any, ...]] = set()
    for atom in atoms:
        _require(isinstance(atom, dict) and set(atom) == _ATOM_KEYS and _is_seven(atom["residue"], model_number)
                 and type(atom["atom_name"]) is str and atom["atom_name"] != ""
                 and atom["element"] in K.MODEL_ELEMENTS and isinstance(atom["coordinates_A"], list)
                 and len(atom["coordinates_A"]) == 3 and all(map(_is_float, atom["coordinates_A"])), "atom row")
        key = identity(atom["residue"])
        if not order or order[-1] != key:
            _require(key not in order, "residue atoms are not contiguous")
            order.append(key)
        _require((key, atom["atom_name"]) not in names, "duplicate atom identity")
        names.add((key, atom["atom_name"]))
    _require(isinstance(bonds, list) and bonds, "final_bonds")
    edges = set()
    for bond in bonds:
        _require(isinstance(bond, list) and len(bond) == 2 and all(_is_int(v) and v < len(atoms) for v in bond)
                 and bond[0] != bond[1], "bond endpoints")
        edge = frozenset(bond)
        _require(edge not in edges, "duplicate bond")
        edges.add(edge)
    return order


def _validate_structure(entry: Any, side: str, mutated: dict[str, Any], cutoff: float, model_number: int) -> None:
    _require(isinstance(entry, dict) and set(entry) == _STRUCTURE_KEYS, f"{side} keys")
    _require(type(entry["structure_object"]) is str and entry["structure_object"] != ""
             and all(_is_hex(entry[k]) for k in _HASH_FIELDS), f"{side} handles/hashes")
    atoms, bonds = entry["atom_mapping"], entry["final_bonds"]
    order = _validate_atoms(atoms, bonds, model_number)
    _require(entry["topology_sha256"] == topology_sha256(atoms, bonds), f"{side} topology hash")
    heavy = [atom for atom in atoms if _heavy(atom)]
    _require(_is_int(entry["heavy_atoms"], 1) and entry["heavy_atoms"] == len(heavy)
             and _is_int(entry["added_hydrogens"]) and entry["added_hydrogens"] == len(atoms) - len(heavy),
             f"{side} atom counts")
    key = identity(mutated)
    _require(key in order, f"{side} mutated residue missing")
    mine = {(atom["atom_name"], atom["element"]) for atom in heavy if identity(atom["residue"]) == key}
    added = entry["added_heavy_atoms"]
    _require(isinstance(added, list) and all(isinstance(a, dict) and set(a) == {"atom_name", "element"}
                                             for a in added), f"{side} added_heavy_atoms")
    added_keys = [(a["atom_name"], a["element"]) for a in added]
    _require(len(set(added_keys)) == len(added_keys) and set(added_keys) <= mine
             and (side == "mutant" or not added), f"{side} added_heavy_atoms")
    variants = entry["protonation_variants"]
    _require(isinstance(variants, list) and all(isinstance(v, dict) and set(v) == {"residue", "variant"}
                                                for v in variants), f"{side} protonation_variants")
    expected_residues = [seven(atom["residue"]) for i, atom in enumerate(atoms)
                         if atom["residue"]["resname"] in K.PROTONATION_VARIANTS
                         and (i == 0 or identity(atoms[i - 1]["residue"]) != identity(atom["residue"]))]
    _require([v["residue"] for v in variants] == expected_residues
             and all(v["variant"] in K.PROTONATION_VARIANTS[v["residue"]["resname"]] for v in variants),
             f"{side} protonation_variants")
    _require(entry["disulfide_bonds"] == disulfide_bonds(atoms, bonds), f"{side} disulfide_bonds")
    energy = entry["energy"]
    _require(isinstance(energy, dict) and set(energy) == {"before_kJ_mol", "after_kJ_mol", *K.ENERGY_FIXED}
             and all(energy[k] == v for k, v in K.ENERGY_FIXED.items())
             and _is_float(energy["before_kJ_mol"]) and _is_float(energy["after_kJ_mol"])
             and energy["after_kJ_mol"] <= energy["before_kJ_mol"] + K.ENERGY_INCREASE_TOLERANCE_KJ_MOL,
             f"{side} energy")
    sasa = entry["sasa"]
    _require(isinstance(sasa, dict) and set(sasa) == {"residue", "engine", "value_A2", "parameters"}
             and sasa["residue"] == mutated and sasa["engine"] == K.SASA_ENGINE and _is_float(sasa["value_A2"])
             and sasa["value_A2"] >= 0 and canonical_json(sasa["parameters"]) == canonical_json(K.SASA_PARAMETERS),
             f"{side} sasa")
    try:
        expected = contacts(atoms, bonds, mutated, cutoff)
    except (ContactLimitExceeded, ValueError) as exc:
        raise ModelInvalid(f"{side} contacts: {exc}") from exc
    _require(canonical_json(entry["contacts"]) == canonical_json(expected), f"{side} contacts")


def _without_mutated(atoms: list[dict[str, Any]], key: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    """Heavy atoms outside the mutated residue as (identity, name, element), in order."""
    return [(identity(a["residue"]), a["atom_name"], a["element"]) for a in atoms
            if _heavy(a) and identity(a["residue"]) != key]


def validated_model(content: Any) -> dict[str, Any]:
    """Return ``content`` if it is a well-formed ``mutation_model@1``; else ``ModelInvalid``.

    Checks shape and closed sets, recomputes contacts, topology hashes, disulfide pairs, the comparison, protonation
    differences and the limitation sentences from the stored rows, and requires the two structures to share every
    residue and heavy atom outside the mutated residue (in the same order). Handle kinds/runs and stored bytes are the
    caller's checks.
    """
    try:
        return _validated(content)
    except ModelInvalid:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:   # e.g. NaN inside a recomputed row
        raise ModelInvalid(f"malformed mutation model: {type(exc).__name__}") from exc


def _validated(content: Any) -> dict[str, Any]:
    _require(isinstance(content, dict) and set(content) == _TOP_KEYS, "top-level keys")
    _require(content["schema"] == K.SCHEMA and content["method_version"] == K.METHOD_VERSION, "schema")
    structure = content["structure"]
    _require(isinstance(structure, dict) and set(structure) == {"handle", "model_number", "structure_kind"}
             and type(structure["handle"]) is str and structure["handle"] != ""
             and _is_int(structure["model_number"]) and structure["structure_kind"] == K.STRUCTURE_KIND, "structure")
    model_number = structure["model_number"]
    candidate = content["candidate"]
    _validate_candidate(candidate, model_number)
    parameters = content["parameters"]
    low, high = K.SEED_RANGE
    low_a, high_a = K.CONTACT_CUTOFF_RANGE_A
    _require(isinstance(parameters, dict)
             and set(parameters) == {"seed", "contact_cutoff_A", "selection_policy", "hydrogen_policy"}
             and type(parameters["seed"]) is int and low <= parameters["seed"] <= high
             and _is_float(parameters["contact_cutoff_A"]) and low_a <= parameters["contact_cutoff_A"] <= high_a
             and parameters["selection_policy"] == K.SELECTION_POLICY
             and parameters["hydrogen_policy"] == K.HYDROGEN_POLICY, "parameters")
    _validate_method(content["method"])
    excluded = content["excluded_components"]
    _require(isinstance(excluded, list) and len(excluded) == len(K.EXCLUDED_CATEGORIES)
             and all(isinstance(item, dict) and set(item) == {"reason", "residue_count", "atom_count"}
                     and item["reason"] == reason and _is_int(item["residue_count"]) and _is_int(item["atom_count"])
                     and (item["residue_count"] == 0) == (item["atom_count"] == 0)
                     for item, reason in zip(excluded, K.EXCLUDED_CATEGORIES, strict=False)), "excluded_components")

    structures = content["structures"]
    _require(isinstance(structures, dict) and set(structures) == set(K.STRUCTURE_SIDES), "structures keys")
    original = candidate["residue"]
    renamed = {**original, "resname": candidate["mutant_resname"]}
    cutoff = parameters["contact_cutoff_A"]
    wild, mutant = structures["wild_type_reference"], structures["mutant"]
    _validate_structure(wild, "wild_type_reference", original, cutoff, model_number)
    _validate_structure(mutant, "mutant", renamed, cutoff, model_number)
    _require(all(wild[k] != mutant[k] for k in ("structure_object", *_HASH_FIELDS)), "the two structures share bytes")
    wild_order = [identity(a["residue"]) for a in wild["atom_mapping"]]
    mutant_order = [identity(original) if identity(a["residue"]) == identity(renamed) else identity(a["residue"])
                    for a in mutant["atom_mapping"]]
    _require(list(dict.fromkeys(wild_order)) == list(dict.fromkeys(mutant_order)), "residue order differs")
    _require(_without_mutated(wild["atom_mapping"], identity(original))
             == _without_mutated(mutant["atom_mapping"], identity(renamed)), "heavy atoms outside the mutated residue")

    comparison, differences = compare_structures(candidate, wild, mutant)
    _require(canonical_json(content["comparison"]) == canonical_json(comparison), "comparison")
    _require(canonical_json(content["protonation_differences"]) == canonical_json(differences),
             "protonation_differences")
    expected = K.applicable_limitations(protonation_difference_count=len(differences),
                                        new_disulfide_in_mutant=comparison["new_disulfide_in_mutant"])
    _require(content["limitations"] == list(expected), "limitations")
    return content
