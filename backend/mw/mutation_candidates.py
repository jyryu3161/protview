"""M20 single-substitution candidate list: pure logic over already loaded inputs (spec .dryforge/spec.md 2--6).

Nothing here reads the object store, a file, the reference folder or the network; the tool wrapper owns handle
checks (kind, run, structure match), failure classes and object storage. Inputs are the parsed prepared structure
(a ``gemmi.Structure`` whose only model is the prepared one, as ``tools.structural._parse`` returns it), the structure
residue list (``tools.structural.structure_residues``) and the loaded pocket_set / numbering map / annotation contents.

* Request (``check_fields`` + ``normalize_request``): the spec 2 checks that need no store, in admission order, and the
  normalized args used as the call key (lists in structure file order with all 7 identity fields, ranks ascending,
  allowed residues as one string in ``ONE_LETTER_ORDER``, defaults filled in).
* Positions: polymer residues of the model (category ``polymer``; chains never merged) from the union of pocket lining
  residues, the ligand shell (heavy-atom minimum distance <= radius) and the user list, in structure file order.
* Protection (closed reasons, in order), release (all reasons at once), exclusion reasons and candidates as spec 4--5.
  Distances are float64 minima over the stored coordinates (hydrogen and deuterium skipped).
* ``validated_set`` checks a stored result's content only (closed sets, counts, candidate/position consistency,
  fixed sentences, identity shape); the caller checks the handle's kind and run.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .mutation_constants import (
    ANNOTATED_SITE_STATUS,
    ARG_KEYS,
    CATALYTIC_NOT_AVAILABLE_REASON,
    CHECKED,
    CYSTEINE,
    DISULFIDE_SG_A,
    EXCLUSION_REASONS,
    HYDROGEN_ELEMENTS,
    IDENTITY_FIELDS,
    KLIFS_NOT_CHECKED_REASON,
    LIGAND_SHELL_KEYS,
    LIGAND_SHELL_RADIUS_DEFAULT_A,
    LIGAND_SHELL_RADIUS_RANGE_A,
    LIMITATIONS,
    MAPPED_RESNAMES,
    MAX_LIST,
    MAX_POSITIONS,
    METAL_CONTACT_DEFAULT_A,
    METAL_CONTACT_RANGE_A,
    METHOD_VERSION,
    NOT_AVAILABLE,
    NOT_CHECKED,
    NUMBERING_FIELDS,
    NUMBERING_STATUSES,
    ONE_LETTER_ORDER,
    POCKET_KEYS,
    POSITION_STATUSES,
    PROTECTION_CHECK_KEYS,
    PROTECTION_REASONS,
    REFERENCE_REQUIRED,
    RELEASE_EFFECTS,
    SCHEMA,
    SG_ATOM,
    SOURCE_KINDS,
    SOURCES_KEYS,
    STANDARD_ONE_LETTER,
    STRUCTURE_KIND,
    TOO_MANY_POSITIONS,
)
from .tools.structural import METALS, _res_ref


class MutationInvalid(Exception):
    """A request the tool must refuse (``reason_code`` from the closed admission set, or ``too_many_positions``)."""

    def __init__(self, reason_code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.detail = {"reason_code": reason_code, **detail}


class MutationSetInvalid(ValueError):
    """Stored ``mutation_candidate_set@1`` content that fails the pure validation."""


# --- identities -----------------------------------------------------------------------------------------------------

def identity(residue: dict[str, Any]) -> tuple[Any, ...]:
    """The 7-field identity with exact types (``1``/``True`` and ``""``/``None`` never compare equal)."""
    return tuple((type(residue[k]), residue[k]) for k in IDENTITY_FIELDS)


def seven(residue: dict[str, Any]) -> dict[str, Any]:
    return {k: residue[k] for k in IDENTITY_FIELDS}


def standard_name(resname: str) -> str | None:
    """The standard name of a standard or one of the ten mapped names; ``None`` for any other name."""
    if resname in STANDARD_ONE_LETTER:
        return resname
    return MAPPED_RESNAMES.get(resname)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _reference_shape_ok(ref: Any) -> bool:
    if not isinstance(ref, dict) or set(ref) - set(IDENTITY_FIELDS) or not set(REFERENCE_REQUIRED) <= set(ref):
        return False
    if not (_is_int(ref["model_number"]) and _is_int(ref["seq_auth"])
            and all(type(ref[k]) is str for k in ("chain_auth", "icode", "resname"))):
        return False
    if "chain_label" in ref and ref["chain_label"] is not None and type(ref["chain_label"]) is not str:
        return False
    return not ("seq_label" in ref and ref["seq_label"] is not None and not _is_int(ref["seq_label"]))


def _matches(ref: dict[str, Any], residue: dict[str, Any]) -> bool:
    return all(type(residue[k]) is type(v) and residue[k] == v for k, v in ref.items())


# --- request ---------------------------------------------------------------------------------------------------------

def check_fields(args: Any) -> None:
    """``unknown_field`` at the top level, in ``sources``, ``pocket`` and ``ligand_shell`` (spec 2, first check)."""
    if not isinstance(args, dict):
        raise MutationInvalid("argument_invalid", "arguments must be an object")
    levels = [(args, ARG_KEYS, "")]
    sources = args.get("sources")
    if isinstance(sources, dict):
        levels.append((sources, SOURCES_KEYS, "sources."))
        for key, allowed in (("pocket", POCKET_KEYS), ("ligand_shell", LIGAND_SHELL_KEYS)):
            if isinstance(sources.get(key), dict):
                levels.append((sources[key], allowed, f"sources.{key}."))
    for value, allowed, prefix in levels:
        unknown = sorted(set(value) - set(allowed))
        if unknown:
            raise MutationInvalid("unknown_field", f"unknown parameters: {[prefix + k for k in unknown]}")


def _distance_arg(value: Any, default: float, bounds: tuple[float, float], name: str) -> float:
    if value is None:
        return default
    if not _is_number(value) or not bounds[0] <= value <= bounds[1]:
        raise MutationInvalid("argument_invalid", f"{name} must be a finite number in [{bounds[0]}, {bounds[1]}]")
    return float(value)


def _reference_list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_LIST or not all(map(_reference_shape_ok, value)):
        raise MutationInvalid("argument_invalid", f"{name} must be a list of at most {MAX_LIST} residue references "
                              "(model_number, chain_auth, seq_auth, icode, resname; optional chain_label, seq_label)")
    return value


def _allowed(value: Any) -> str:
    if isinstance(value, str):
        letters = list(value)
    elif isinstance(value, list) and all(type(item) is str and len(item) == 1 for item in value):
        letters = value
    else:
        raise MutationInvalid("allowed_residues_invalid", "allowed_residues must be one-letter codes")
    if not letters or len(set(letters)) != len(letters) or not set(letters) <= set(ONE_LETTER_ORDER):
        raise MutationInvalid("allowed_residues_invalid",
                              "allowed_residues must be distinct standard one-letter codes and not empty")
    return "".join(code for code in ONE_LETTER_ORDER if code in letters)


def _resolve(ref: dict[str, Any], polymer: list[dict[str, Any]], name: str) -> dict[str, Any]:
    found = [residue for residue in polymer if _matches(ref, residue)]
    if len(found) != 1:
        reason = "not found among protein residues" if not found else "ambiguous"
        raise MutationInvalid("residue_invalid", f"{name}: residue reference {reason}")
    return found[0]


def normalize_request(args: dict[str, Any], residues: list[dict[str, Any]],
                      ligands: list[dict[str, Any]]) -> dict[str, Any]:
    """Spec 2 checks ``no_position_source`` .. ``ligand_invalid`` and the normalized args (the call key).

    ``residues``/``ligands`` are ``structure_residues(...)["residues"|"ligands"]`` of the requested structure; the
    caller has already checked ``unknown_field`` and ``structure_invalid``. Handle values (``pocket_set``,
    ``numbering_map``, ``annotation``) are carried as given; their checks need the store.
    """
    check_fields(args)
    sources = args.get("sources")
    if isinstance(sources, dict) and (sources.get("pocket") is None and sources.get("ligand_shell") is None
                                      and sources.get("residues", []) == []):
        raise MutationInvalid("no_position_source", "pocket, ligand_shell and residues are all empty")
    # argument_invalid: shapes and ranges of every field
    if not isinstance(sources, dict):
        raise MutationInvalid("argument_invalid", "sources must be an object {pocket, ligand_shell, residues}")
    pocket = sources.get("pocket")
    if pocket is not None:
        ranks = pocket.get("ranks") if isinstance(pocket, dict) else None
        if not isinstance(ranks, list) or not ranks or len(ranks) > MAX_LIST or not all(map(_is_int, ranks)):
            raise MutationInvalid("argument_invalid", "pocket must be {pocket_set, ranks: non-empty integer list}")
    shell = sources.get("ligand_shell")
    if shell is not None and not isinstance(shell, dict):
        raise MutationInvalid("argument_invalid", "ligand_shell must be null or {radius_A}")
    radius = (_distance_arg(shell.get("radius_A"), LIGAND_SHELL_RADIUS_DEFAULT_A, LIGAND_SHELL_RADIUS_RANGE_A,
                            "radius_A") if shell is not None else None)
    if "radius_A" in (shell or {}) and shell["radius_A"] is None:
        raise MutationInvalid("argument_invalid", "radius_A must be a number")
    lists = {"residues": _reference_list(sources.get("residues", []), "residues")}
    for key in ("protected_residues", "released_residues"):
        lists[key] = _reference_list(args.get(key, []), key)
    if "metal_contact_A" in args and args["metal_contact_A"] is None:
        raise MutationInvalid("argument_invalid", "metal_contact_A must be a number")
    metal = _distance_arg(args.get("metal_contact_A"), METAL_CONTACT_DEFAULT_A, METAL_CONTACT_RANGE_A,
                          "metal_contact_A")
    ligand = args.get("ligand")
    if ligand is not None and not _reference_shape_ok(ligand):
        raise MutationInvalid("argument_invalid", "ligand selector requires model_number, chain_auth, seq_auth, "
                              "icode and resname; optional chain_label and seq_label")
    allowed_value = args.get("allowed_residues", ONE_LETTER_ORDER)
    if not isinstance(allowed_value, (str, list)):
        raise MutationInvalid("argument_invalid", "allowed_residues must be a string or a list")
    allowed = _allowed(allowed_value)
    # residue_invalid, duplicate_residue, protect_release_conflict
    polymer = [residue for residue in residues if residue["category"] == "polymer"]
    order = {identity(residue): index for index, residue in enumerate(residues)}
    resolved = {key: [_resolve(ref, polymer, key) for ref in refs] for key, refs in lists.items()}
    for key, items in resolved.items():
        if len({identity(item) for item in items}) != len(items):
            raise MutationInvalid("duplicate_residue", f"{key} lists the same residue twice")
    protected = {identity(item) for item in resolved["protected_residues"]}
    if any(identity(item) in protected for item in resolved["released_residues"]):
        raise MutationInvalid("protect_release_conflict", "a residue is both protected and released")
    # ligand_required, ligand_invalid
    if shell is not None and ligand is None:
        raise MutationInvalid("ligand_required", "ligand_shell needs a ligand selector (no automatic choice)")
    ligand_ref = None
    if ligand is not None:
        found = [item for item in ligands if _matches(ligand, item)]
        if len(found) != 1:
            reason = "not found" if not found else "ambiguous; select one ligand instance"
            raise MutationInvalid("ligand_invalid", f"ligand {reason}")
        ligand_ref = seven(found[0])

    def ordered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [seven(item) for item in sorted(items, key=lambda item: order[identity(item)])]

    return {
        "structure": args.get("structure"),
        "sources": {"pocket": (None if pocket is None else {"pocket_set": pocket.get("pocket_set"),
                                                             "ranks": sorted(pocket["ranks"])}),
                    "ligand_shell": None if shell is None else {"radius_A": radius},
                    "residues": ordered(resolved["residues"])},
        "ligand": ligand_ref,
        "allowed_residues": allowed,
        "protected_residues": ordered(resolved["protected_residues"]),
        "released_residues": ordered(resolved["released_residues"]),
        "metal_contact_A": metal,
        "numbering_map": args.get("numbering_map"),
        "annotation": args.get("annotation"),
    }


def pocket_lining(pocket_content: dict[str, Any], ranks: list[int],
                  residues: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """``{rank: lining residues (7 fields)}``; ``pocket_rank_invalid`` / ``pocket_residue_mismatch`` (spec 2)."""
    pockets = {pocket["rank"]: pocket for pocket in pocket_content["pockets"]}
    if len(set(ranks)) != len(ranks) or not set(ranks) <= set(pockets):
        raise MutationInvalid("pocket_rank_invalid", "ranks must be distinct ranks of the pocket set")
    polymer = {identity(residue) for residue in residues if residue["category"] == "polymer"}
    out = {}
    for rank in sorted(ranks):
        lining = pockets[rank]["lining_residues"]
        if not all(isinstance(item, dict) and set(item) == set(IDENTITY_FIELDS) and identity(item) in polymer
                   for item in lining):
            raise MutationInvalid("pocket_residue_mismatch",
                                  f"pocket {rank} lining residues do not match the structure's protein residues")
        out[rank] = [seven(item) for item in lining]
    return out


# --- geometry --------------------------------------------------------------------------------------------------------

def _min_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = a[:, None, :] - b[None, :, :]
    return float(np.sqrt((diff * diff).sum(axis=2)).min())


def _coords(atoms: list[Any]) -> np.ndarray:
    return np.array([(atom.pos.x, atom.pos.y, atom.pos.z) for atom in atoms], dtype=np.float64).reshape(-1, 3)


def _walk(st: Any) -> list[dict[str, Any]]:
    """Every residue of the (only) model in file order with identity, category and atom coordinate arrays."""
    model = st[0]
    out = []
    for chain in model:
        for res in chain:
            ref = _res_ref(chain, res, model.num)
            heavy = [atom for atom in res if atom.element.name.upper() not in HYDROGEN_ELEMENTS]
            water = res.is_water()
            out.append({"residue": ref, "category": ("water" if water else
                                                     "polymer" if res.het_flag == "A" else "nonpolymer"),
                        "metal": res.het_flag == "H" and not water and res.name in METALS,
                        "heavy": _coords(heavy), "all": _coords(list(res)),
                        "sg": _coords([atom for atom in heavy if atom.name == SG_ATOM])})
    return out


def position_sources(walk: list[dict[str, Any]], params: dict[str, Any],
                     lining: dict[int, list[dict[str, Any]]] | None,
                     ligand_heavy: np.ndarray | None) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """``[(residue entry, sources)]`` in file order: union of pocket lining, ligand shell and user residues."""
    pocket_ranks: dict[tuple[Any, ...], list[int]] = {}
    for rank, items in (lining or {}).items():
        for item in items:
            pocket_ranks.setdefault(identity(item), []).append(rank)
    user = {identity(item) for item in params["sources"]["residues"]}
    shell = params["sources"]["ligand_shell"]
    out = []
    for entry in walk:
        if entry["category"] != "polymer":
            continue
        key = identity(entry["residue"])
        sources: list[dict[str, Any]] = [{"kind": "pocket", "pocket_rank": rank}
                                         for rank in sorted(set(pocket_ranks.get(key, [])))]
        if (shell is not None and len(entry["heavy"])
                and _min_distance(entry["heavy"], ligand_heavy) <= shell["radius_A"]):
            sources.append({"kind": "ligand_shell", "radius_A": shell["radius_A"]})
        if key in user:
            sources.append({"kind": "user"})
        if sources:
            out.append((entry, sources))
    return out


def _klifs_sites(annotation: dict[str, Any]) -> tuple[dict[tuple[Any, ...], list[str]], int, int]:
    labels: dict[tuple[Any, ...], dict[str, int]] = {}
    annotated = absent = 0
    for group in annotation["groups"]:
        for site in group["sites"]:
            if site["status"] == ANNOTATED_SITE_STATUS:
                annotated += 1
                labels.setdefault(identity(site["residue"]), {})[site["klifs_label"]] = site["klifs_index"]
            else:
                absent += 1
    ordered = {key: sorted(found, key=lambda label: found[label]) for key, found in labels.items()}
    return ordered, annotated, absent


def _numbering(rows: dict[tuple[Any, ...], dict[str, Any]], residue: dict[str, Any]) -> dict[str, Any]:
    row = rows.get(identity(residue))
    if row is None:
        return {"status": "not_in_map", **{field: None for field in NUMBERING_FIELDS}}
    return {"status": row["status"], **{field: row[field] for field in NUMBERING_FIELDS}}


def _exclusions(reasons: list[str], released: bool, one_letter: str | None, allowed: str) -> list[str]:
    found = set() if released else set(reasons)
    if one_letter is None:
        found.add("non_standard_residue")
    elif not set(allowed) - {one_letter}:
        found.add("no_allowed_alternative")
    return [reason for reason in EXCLUSION_REASONS if reason in found]


def build_candidate_set(structure: str, st: Any, params: dict[str, Any], *,
                        pocket_content: dict[str, Any] | None = None,
                        numbering_content: dict[str, Any] | None = None,
                        annotation_content: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``mutation_candidate_set@1`` content for normalized ``params`` (the output of ``normalize_request``).

    Raises ``MutationInvalid`` for ``pocket_rank_invalid`` / ``pocket_residue_mismatch`` and for more than
    ``MAX_POSITIONS`` positions (``too_many_positions`` with ``positions`` and ``limit``; nothing is truncated).
    """
    walk = _walk(st)
    model_number = st[0].num
    residues = [{**entry["residue"], "category": entry["category"]} for entry in walk]
    sources = params["sources"]
    lining = (pocket_lining(pocket_content, sources["pocket"]["ranks"], residues)
              if sources["pocket"] is not None else None)
    ligand_entry = None
    if params["ligand"] is not None:
        ligand_entry = next(entry for entry in walk if identity(entry["residue"]) == identity(params["ligand"]))
    ligand_heavy = ligand_entry["heavy"] if ligand_entry is not None else None
    gathered = position_sources(walk, params, lining, ligand_heavy)
    if len(gathered) > MAX_POSITIONS:
        raise MutationInvalid(TOO_MANY_POSITIONS, f"{len(gathered)} positions exceed the limit of {MAX_POSITIONS}",
                              positions=len(gathered), limit=MAX_POSITIONS)

    allowed = params["allowed_residues"]
    threshold = params["metal_contact_A"]
    protected = {identity(item) for item in params["protected_residues"]}
    released_set = {identity(item) for item in params["released_residues"]}
    metals = [entry for entry in walk if entry["metal"]]
    cys = [entry for entry in walk if entry["category"] == "polymer"
           and standard_name(entry["residue"]["resname"]) == CYSTEINE and len(entry["sg"])]
    pairs = sum(1 for i in range(len(cys)) for j in range(i + 1, len(cys))
                if _min_distance(cys[i]["sg"], cys[j]["sg"]) <= DISULFIDE_SG_A)
    klifs, annotated_sites, absent_sites = (_klifs_sites(annotation_content) if annotation_content is not None
                                            else ({}, None, None))
    rows = ({identity(row["residue"]): row for row in numbering_content["rows"]}
            if numbering_content is not None else None)

    positions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for index, (entry, position_sources_) in enumerate(gathered):
        residue = seven(entry["residue"])
        key = identity(residue)
        std = standard_name(residue["resname"])
        one_letter = STANDARD_ONE_LETTER[std] if std is not None else None
        reasons = []
        if key in protected:
            reasons.append("user_protected")
        klifs_sites = None if annotation_content is None else klifs.get(key, [])
        if klifs_sites:
            reasons.append("klifs_key_site")
        metal = None
        if metals and len(entry["heavy"]):
            distances = [_min_distance(entry["heavy"], item["all"]) for item in metals]
            nearest = int(np.argmin(distances))
            if distances[nearest] <= threshold:
                metal = {"min_distance_A": distances[nearest], "metal_residue": seven(metals[nearest]["residue"])}
                reasons.append("metal_contact")
        partner = None
        if std == CYSTEINE and len(entry["sg"]):
            others = [item for item in cys if identity(item["residue"]) != key]
            distances = [_min_distance(entry["sg"], item["sg"]) for item in others]
            if distances and min(distances) <= DISULFIDE_SG_A:
                partner = seven(others[int(np.argmin(distances))]["residue"])
                reasons.append("disulfide_cys")
        released = key in released_set and bool(reasons)
        exclusions = _exclusions(reasons, released, one_letter, allowed)
        made = [] if exclusions else [code for code in allowed if code != one_letter]
        for code in made:
            candidates.append({"index": len(candidates), "position_index": index, "from": one_letter, "to": code})
        positions.append({
            "index": index, "residue": residue, "standard_resname": std, "one_letter": one_letter,
            "sources": position_sources_,
            "ligand_min_distance_A": (_min_distance(entry["heavy"], ligand_heavy)
                                      if ligand_heavy is not None and len(entry["heavy"]) else None),
            "numbering": None if rows is None else _numbering(rows, residue),
            "protection": {"reasons": reasons, "released": released, "klifs_sites": klifs_sites, "metal": metal,
                           "disulfide_partner": partner},
            "exclusion_reasons": exclusions, "status": "excluded" if exclusions else "candidate",
            "candidate_count": len(made),
        })

    by_key = {identity(position["residue"]): position for position in positions}
    released_out = [{"residue": seven(item), "effect": ("released" if by_key.get(identity(item), {}).get(
        "protection", {}).get("released") else "none")} for item in params["released_residues"]]
    content = {
        "schema": SCHEMA, "method_version": METHOD_VERSION,
        "structure": {"handle": structure, "model_number": model_number, "structure_kind": STRUCTURE_KIND},
        "parameters": {
            "sources": {"pocket": sources["pocket"], "ligand_shell": sources["ligand_shell"],
                        "residues": sources["residues"]},
            "ligand": params["ligand"], "allowed_residues": allowed,
            "protected_residues": params["protected_residues"], "released_residues": params["released_residues"],
            "metal_contact_A": threshold, "disulfide_sg_A": DISULFIDE_SG_A,
            "numbering_map": params["numbering_map"], "annotation": params["annotation"],
        },
        "ligand": (None if ligand_entry is None else
                   {"residue": seven(ligand_entry["residue"]), "heavy_atom_count": len(ligand_entry["heavy"])}),
        "pockets": (None if lining is None else
                    {"pocket_set": sources["pocket"]["pocket_set"], "ranks": sources["pocket"]["ranks"],
                     "lining_residue_count": len({identity(item) for items in lining.values() for item in items})}),
        "protection_checks": {
            "user_list": {"status": CHECKED, "protected": len(params["protected_residues"]),
                          "released": len(params["released_residues"])},
            "klifs_key_sites": ({"status": NOT_CHECKED, "reason": KLIFS_NOT_CHECKED_REASON, "annotation": None,
                                 "annotated_sites": None, "absent_sites": None} if annotation_content is None else
                                {"status": CHECKED, "reason": None, "annotation": params["annotation"],
                                 "annotated_sites": annotated_sites, "absent_sites": absent_sites}),
            "metal_contact": {"status": CHECKED, "threshold_A": threshold, "metal_residues": len(metals),
                              "metal_names": sorted({entry["residue"]["resname"] for entry in metals})},
            "disulfide": {"status": CHECKED, "threshold_A": DISULFIDE_SG_A, "pairs": pairs},
            "catalytic_residue_database": {"status": NOT_AVAILABLE, "reason": CATALYTIC_NOT_AVAILABLE_REASON},
        },
        "released_residues": released_out,
        "positions": positions,
        "candidates": candidates,
        "counts": counts(positions, candidates),
        "null_result": not candidates,
        "limitations": list(LIMITATIONS),
    }
    return content


def counts(positions: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "positions": len(positions),
        "candidate_positions": sum(p["status"] == "candidate" for p in positions),
        "excluded_positions": sum(p["status"] == "excluded" for p in positions),
        "released_positions": sum(p["protection"]["released"] is True for p in positions),
        "candidates": len(candidates),
        "exclusion_reason_counts": {reason: sum(reason in p["exclusion_reasons"] for p in positions)
                                    for reason in EXCLUSION_REASONS},
        "source_counts": {kind: sum(any(s["kind"] == kind for s in p["sources"]) for p in positions)
                          for kind in SOURCE_KINDS},
    }


# --- validation of stored content ------------------------------------------------------------------------------------

_TOP_KEYS = {"schema", "method_version", "structure", "parameters", "ligand", "pockets", "protection_checks",
             "released_residues", "positions", "candidates", "counts", "null_result", "limitations"}
_POSITION_KEYS = {"index", "residue", "standard_resname", "one_letter", "sources", "ligand_min_distance_A",
                  "numbering", "protection", "exclusion_reasons", "status", "candidate_count"}
_PROTECTION_KEYS = {"reasons", "released", "klifs_sites", "metal", "disulfide_partner"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MutationSetInvalid(message)


def _is_seven(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == set(IDENTITY_FIELDS) and _reference_shape_ok(value))


def _seven_list(value: Any) -> bool:
    return (isinstance(value, list) and len(value) <= MAX_LIST and all(map(_is_seven, value))
            and len({identity(item) for item in value}) == len(value))


def _ordered_subset(values: Any, closed: tuple[str, ...]) -> bool:
    return (isinstance(values, list) and all(type(v) is str and v in closed for v in values)
            and values == [v for v in closed if v in values])


def _validate_parameters(parameters: Any) -> None:
    _require(isinstance(parameters, dict) and set(parameters) == {
        "sources", "ligand", "allowed_residues", "protected_residues", "released_residues", "metal_contact_A",
        "disulfide_sg_A", "numbering_map", "annotation"}, "parameters keys")
    sources = parameters["sources"]
    _require(isinstance(sources, dict) and set(sources) == set(SOURCES_KEYS), "sources keys")
    pocket = sources["pocket"]
    _require(pocket is None or (isinstance(pocket, dict) and set(pocket) == set(POCKET_KEYS)
                                and type(pocket["pocket_set"]) is str and isinstance(pocket["ranks"], list)
                                and pocket["ranks"] and all(map(_is_int, pocket["ranks"]))
                                and pocket["ranks"] == sorted(set(pocket["ranks"]))), "sources.pocket")
    shell = sources["ligand_shell"]
    low, high = LIGAND_SHELL_RADIUS_RANGE_A
    _require(shell is None or (isinstance(shell, dict) and set(shell) == set(LIGAND_SHELL_KEYS)
                               and _is_number(shell["radius_A"]) and low <= shell["radius_A"] <= high),
             "sources.ligand_shell")
    _require(_seven_list(sources["residues"]), "sources.residues")
    _require(pocket is not None or shell is not None or sources["residues"] != [], "no position source")
    _require(parameters["ligand"] is None or _is_seven(parameters["ligand"]), "parameters.ligand")
    _require(shell is None or parameters["ligand"] is not None, "ligand_shell without ligand")
    allowed = parameters["allowed_residues"]
    _require(type(allowed) is str and allowed != "" and allowed == "".join(c for c in ONE_LETTER_ORDER
                                                                           if c in allowed)
             and len(set(allowed)) == len(allowed), "allowed_residues")
    for key in ("protected_residues", "released_residues"):
        _require(_seven_list(parameters[key]), key)
    _require(not {identity(i) for i in parameters["protected_residues"]}
             & {identity(i) for i in parameters["released_residues"]}, "protect/release conflict")
    low, high = METAL_CONTACT_RANGE_A
    _require(_is_number(parameters["metal_contact_A"]) and low <= parameters["metal_contact_A"] <= high,
             "metal_contact_A")
    _require(parameters["disulfide_sg_A"] == DISULFIDE_SG_A and type(parameters["disulfide_sg_A"]) is float,
             "disulfide_sg_A")
    for key in ("numbering_map", "annotation"):
        _require(parameters[key] is None or type(parameters[key]) is str, key)


def _validate_checks(checks: Any, parameters: dict[str, Any]) -> None:
    _require(isinstance(checks, dict) and set(checks) == set(PROTECTION_CHECK_KEYS), "protection_checks keys")
    _require(checks["user_list"] == {"status": CHECKED, "protected": len(parameters["protected_residues"]),
                                     "released": len(parameters["released_residues"])}, "user_list")
    klifs = checks["klifs_key_sites"]
    _require(isinstance(klifs, dict) and set(klifs) == {"status", "reason", "annotation", "annotated_sites",
                                                        "absent_sites"}, "klifs_key_sites keys")
    if parameters["annotation"] is None:
        _require(klifs == {"status": NOT_CHECKED, "reason": KLIFS_NOT_CHECKED_REASON, "annotation": None,
                           "annotated_sites": None, "absent_sites": None}, "klifs_key_sites not checked")
    else:
        _require(klifs["status"] == CHECKED and klifs["reason"] is None
                 and klifs["annotation"] == parameters["annotation"]
                 and all(_is_int(klifs[k]) and klifs[k] >= 0 for k in ("annotated_sites", "absent_sites")),
                 "klifs_key_sites checked")
    metal = checks["metal_contact"]
    _require(isinstance(metal, dict) and set(metal) == {"status", "threshold_A", "metal_residues", "metal_names"}
             and metal["status"] == CHECKED and metal["threshold_A"] == parameters["metal_contact_A"]
             and _is_int(metal["metal_residues"]) and metal["metal_residues"] >= 0
             and isinstance(metal["metal_names"], list)
             and all(type(n) is str and n in METALS for n in metal["metal_names"])
             and metal["metal_names"] == sorted(set(metal["metal_names"]))
             and (metal["metal_residues"] == 0) == (metal["metal_names"] == []), "metal_contact check")
    disulfide = checks["disulfide"]
    _require(isinstance(disulfide, dict) and set(disulfide) == {"status", "threshold_A", "pairs"}
             and disulfide["status"] == CHECKED and disulfide["threshold_A"] == DISULFIDE_SG_A
             and _is_int(disulfide["pairs"]) and disulfide["pairs"] >= 0, "disulfide check")
    _require(checks["catalytic_residue_database"] == {"status": NOT_AVAILABLE,
                                                      "reason": CATALYTIC_NOT_AVAILABLE_REASON}, "catalytic")


def _validate_position(position: Any, index: int, parameters: dict[str, Any]) -> None:
    _require(isinstance(position, dict) and set(position) == _POSITION_KEYS, "position keys")
    _require(_is_int(position["index"]) and position["index"] == index, "position index")
    residue = position["residue"]
    _require(_is_seven(residue), "position residue")
    std = standard_name(residue["resname"])
    _require(position["standard_resname"] == std
             and position["one_letter"] == (STANDARD_ONE_LETTER[std] if std else None), "standard name")
    sources = position["sources"]
    pocket, shell = parameters["sources"]["pocket"], parameters["sources"]["ligand_shell"]
    _require(isinstance(sources, list) and sources, "position sources")
    expected_kinds = []
    ranks = []
    for source in sources:
        _require(isinstance(source, dict) and source.get("kind") in SOURCE_KINDS, "source kind")
        expected_kinds.append(source["kind"])
        if source["kind"] == "pocket":
            _require(set(source) == {"kind", "pocket_rank"} and pocket is not None
                     and _is_int(source["pocket_rank"]) and source["pocket_rank"] in pocket["ranks"], "pocket source")
            ranks.append(source["pocket_rank"])
        elif source["kind"] == "ligand_shell":
            _require(source == {"kind": "ligand_shell", "radius_A": shell["radius_A"]} if shell else False,
                     "ligand_shell source")
            _require(position["ligand_min_distance_A"] is not None
                     and position["ligand_min_distance_A"] <= shell["radius_A"], "ligand_shell distance")
        else:
            _require(source == {"kind": "user"}, "user source")
    _require(ranks == sorted(set(ranks)) and expected_kinds == sorted(expected_kinds, key=SOURCE_KINDS.index)
             and expected_kinds.count("ligand_shell") <= 1 and expected_kinds.count("user") <= 1, "source order")
    user = {identity(i) for i in parameters["sources"]["residues"]}
    _require((identity(residue) in user) == ("user" in expected_kinds), "user source membership")
    distance = position["ligand_min_distance_A"]
    if parameters["ligand"] is None:
        _require(distance is None, "ligand distance without ligand")
    else:
        _require(type(distance) is float and math.isfinite(distance) and distance >= 0, "ligand distance")
    numbering = position["numbering"]
    if parameters["numbering_map"] is None:
        _require(numbering is None, "numbering without map")
    else:
        _require(isinstance(numbering, dict) and set(numbering) == {"status", *NUMBERING_FIELDS}
                 and numbering["status"] in NUMBERING_STATUSES, "numbering")
        if numbering["status"] == "not_in_map":
            _require(all(numbering[f] is None for f in NUMBERING_FIELDS), "not_in_map fields")
    protection = position["protection"]
    _require(isinstance(protection, dict) and set(protection) == _PROTECTION_KEYS, "protection keys")
    reasons = protection["reasons"]
    _require(_ordered_subset(reasons, PROTECTION_REASONS), "protection reasons")
    _require(type(protection["released"]) is bool, "released flag")
    released = {identity(i) for i in parameters["released_residues"]}
    _require(protection["released"] == (identity(residue) in released and bool(reasons)), "released")
    protected = {identity(i) for i in parameters["protected_residues"]}
    _require(("user_protected" in reasons) == (identity(residue) in protected), "user_protected")
    sites = protection["klifs_sites"]
    if parameters["annotation"] is None:
        _require(sites is None and "klifs_key_site" not in reasons, "klifs not checked")
    else:
        _require(isinstance(sites, list) and all(type(s) is str for s in sites) and len(set(sites)) == len(sites)
                 and bool(sites) == ("klifs_key_site" in reasons), "klifs_sites")
    metal = protection["metal"]
    if "metal_contact" in reasons:
        _require(isinstance(metal, dict) and set(metal) == {"min_distance_A", "metal_residue"}
                 and _is_number(metal["min_distance_A"]) and type(metal["min_distance_A"]) is float
                 and 0 <= metal["min_distance_A"] <= parameters["metal_contact_A"]
                 and _is_seven(metal["metal_residue"]) and metal["metal_residue"]["resname"] in METALS, "metal")
    else:
        _require(metal is None, "metal without reason")
    partner = protection["disulfide_partner"]
    if "disulfide_cys" in reasons:
        _require(std == CYSTEINE and _is_seven(partner) and identity(partner) != identity(residue)
                 and standard_name(partner["resname"]) == CYSTEINE, "disulfide partner")
    else:
        _require(partner is None, "partner without reason")
    expected = _exclusions(reasons, protection["released"], position["one_letter"],
                           parameters["allowed_residues"])
    _require(position["exclusion_reasons"] == expected, "exclusion reasons")
    _require(position["status"] in POSITION_STATUSES
             and position["status"] == ("excluded" if expected else "candidate"), "status")


def validated_set(content: Any) -> dict[str, Any]:
    """Return ``content`` if it is a well-formed ``mutation_candidate_set@1``; else ``MutationSetInvalid``."""
    _require(isinstance(content, dict) and set(content) == _TOP_KEYS, "top-level keys")
    _require(content["schema"] == SCHEMA and content["method_version"] == METHOD_VERSION, "schema")
    structure = content["structure"]
    _require(isinstance(structure, dict) and set(structure) == {"handle", "model_number", "structure_kind"}
             and type(structure["handle"]) is str and _is_int(structure["model_number"])
             and structure["structure_kind"] == STRUCTURE_KIND, "structure")
    parameters = content["parameters"]
    _validate_parameters(parameters)
    model_number = structure["model_number"]
    ligand = content["ligand"]
    if parameters["ligand"] is None:
        _require(ligand is None, "ligand without selector")
    else:
        _require(isinstance(ligand, dict) and set(ligand) == {"residue", "heavy_atom_count"}
                 and ligand["residue"] == parameters["ligand"] and _is_seven(ligand["residue"])
                 and _is_int(ligand["heavy_atom_count"]) and ligand["heavy_atom_count"] > 0, "ligand")
    pocket = parameters["sources"]["pocket"]
    pockets = content["pockets"]
    if pocket is None:
        _require(pockets is None, "pockets without pocket source")
    else:
        _require(isinstance(pockets, dict) and set(pockets) == {"pocket_set", "ranks", "lining_residue_count"}
                 and pockets["pocket_set"] == pocket["pocket_set"] and pockets["ranks"] == pocket["ranks"]
                 and _is_int(pockets["lining_residue_count"]) and pockets["lining_residue_count"] >= 0, "pockets")
    _validate_checks(content["protection_checks"], parameters)

    positions = content["positions"]
    _require(isinstance(positions, list) and len(positions) <= MAX_POSITIONS, "positions list")
    for index, position in enumerate(positions):
        _validate_position(position, index, parameters)
    every = [parameters["ligand"], *parameters["sources"]["residues"], *parameters["protected_residues"],
             *parameters["released_residues"], *(p["residue"] for p in positions)]
    _require(all(item is None or item["model_number"] == model_number for item in every), "model number")
    keys = [identity(p["residue"]) for p in positions]
    _require(len(set(keys)) == len(keys), "duplicate positions")
    _require({identity(i) for i in parameters["sources"]["residues"]} <= set(keys), "user residues not positions")
    by_key = dict(zip(keys, positions, strict=True))

    released = content["released_residues"]
    _require(isinstance(released, list) and len(released) == len(parameters["released_residues"]), "released list")
    for item, ref in zip(released, parameters["released_residues"], strict=True):
        _require(isinstance(item, dict) and set(item) == {"residue", "effect"} and item["residue"] == ref
                 and item["effect"] in RELEASE_EFFECTS, "released item")
        position = by_key.get(identity(ref))
        hit = position is not None and position["protection"]["released"]
        _require((item["effect"] == "released") == hit, "release effect")

    candidates = content["candidates"]
    _require(isinstance(candidates, list), "candidates list")
    expected = [(p["index"], p["one_letter"], code) for p in positions if p["status"] == "candidate"
                for code in parameters["allowed_residues"] if code != p["one_letter"]]
    _require(len(candidates) == len(expected), "candidate count")
    for index, (candidate, (position_index, origin, code)) in enumerate(zip(candidates, expected, strict=True)):
        _require(candidate == {"index": index, "position_index": position_index, "from": origin, "to": code}
                 and all(_is_int(candidate[k]) for k in ("index", "position_index")), "candidate")
    for position in positions:
        made = sum(c["position_index"] == position["index"] for c in candidates)
        _require(_is_int(position["candidate_count"]) and position["candidate_count"] == made, "candidate_count")
    _require(content["counts"] == counts(positions, candidates), "counts")
    _require(content["null_result"] is (not candidates), "null_result")
    _require(content["limitations"] == list(LIMITATIONS), "limitations")
    return content
