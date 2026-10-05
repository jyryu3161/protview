"""M23 ``mutation_set_model@1``: construction and the pure ``validated_model`` (spec .dryforge/spec.md 4).

No OpenMM, no PDBFixer, no store: the modeling program (T3) builds a model with ``model_content`` and every reader
(publication, reads, reports, the M18 receptor source) calls ``validated_model`` on the stored content with the stored
mmCIF bytes, the validated M20 candidate set and, for a model with mutations, the validated wild-type reference model
of the same GA run. The M21 ``mutation_model@1`` and its validator are unchanged.

Content (exact keys at every level, so no difference, change, ΔΔG, score or rank field can exist): ``schema``,
``method_version``, ``candidate_set`` (handle), ``structure`` (the set's ``{handle, model_number, structure_kind}``),
``mutations`` (``[{candidate_index, residue (7 fields), from, to, mutant_resname}]`` in candidate index order, which is
the M20 position order; empty for the wild-type reference), ``seed``, ``method`` (the M21 method record plus
``multi_mutation``), ``structures`` (one key: ``mutant`` with mutations, else ``wild_type_reference``; the M21
structure entry without ``sasa`` and ``contacts``), ``protonation_differences``, ``new_disulfide_in_mutant``,
``reference_structure_sha256`` (the reference model's structure SHA-256; null for the reference itself) and
``limitations`` (L1, L3 always; SL5 with protonation differences; L6 with a new disulfide).

Rules checked against the reference (spec 4): residue order and every heavy atom outside the mutated residues equal
the reference's (identity, name, element, order); each mutated residue appears once under its mutant name and never
under its original identity, in the mutations' order; ``added_heavy_atoms`` (``{residue (7 fields, mutant name),
atom_name, element}`` in atom order) is, residue by residue, the mutated residue's heavy atoms minus the heavy atom
names the input residue had (the reference is the unmodified M7 projection, the input of every step: each residue is
mutated once). This is the M21 publication rule (``mutation_model_bundle.model_content``): the worker's graft already
requires the mutated residue's heavy atoms to equal the fixed force-field template, so the server needs no OpenMM.
``protonation_differences`` and ``new_disulfide_in_mutant`` are recomputed from the two models' stored
``protonation_variants`` and ``disulfide_bonds``.
"""
from __future__ import annotations

import copy
import hashlib
import math
from typing import Any

from . import mutation_model_constants as MK
from . import mutation_model_math as mm
from . import sequence_ga_constants as SC
from . import sequence_ga_inputs as GI
from .core.handles import HANDLE_PREFIX, canonical_json, object_sha
from .mutation_candidates import identity, seven

TOP_KEYS = frozenset({"schema", "method_version", "candidate_set", "structure", "mutations", "seed", "method",
                      "structures", "protonation_differences", "new_disulfide_in_mutant",
                      "reference_structure_sha256", "limitations"})
ENTRY_KEYS = frozenset({"structure_object", "structure_sha256", "system_xml_sha256", "topology_sha256",
                        "heavy_atoms", "added_hydrogens", "added_heavy_atoms", "protonation_variants",
                        "disulfide_bonds", "final_bonds", "atom_mapping", "energy"})
MUTATION_KEYS = frozenset({"candidate_index", "residue", "from", "to", "mutant_resname"})
ADDED_KEYS = frozenset({"residue", "atom_name", "element"})
DIFFERENCE_KEYS = frozenset({"residue", "wild_type_reference", "mutant"})
HASH_FIELDS = ("structure_sha256", "system_xml_sha256", "topology_sha256")


class ModelInvalid(ValueError):
    """Stored ``mutation_set_model@1`` content that fails the pure validation."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ModelInvalid(message)


def _hex(value: Any) -> bool:
    return type(value) is str and bool(GI.SHA_RE.fullmatch(value))


def _float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _heavy(atom: dict[str, Any]) -> bool:
    return atom["element"] not in MK.HYDROGEN_ELEMENTS


# ---------------------------------------------------------------- construction
def structure_handle(run_id: str, raw: bytes) -> str:
    """The handle ``ObjectStore.put(STRUCTURE_OBJECT_KIND, STRUCTURE_OBJECT_SCHEMA, raw, fmt="cif")`` gives these
    mmCIF bytes in run ``run_id`` (``core/handles.py``), computable before anything is stored."""
    sha = object_sha(SC.STRUCTURE_OBJECT_KIND, SC.STRUCTURE_OBJECT_SCHEMA, raw)
    return f"{HANDLE_PREFIX}{run_id}/{SC.STRUCTURE_OBJECT_KIND}/{sha}"


def side(mutations: list[Any]) -> str:
    return SC.MUTANT_SIDE if mutations else SC.REFERENCE_SIDE


def model_mutations(candidate_set: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """The model ``mutations`` of an individual key (``sequence_ga_inputs.key_mutations`` with the mutant residue
    name; the space cap is the largest ``max_mutations``)."""
    space = GI.candidate_space(candidate_set, SC.MAX_MUTATIONS)
    return [{**row, "mutant_resname": MK.THREE_LETTER[row["to"]]}
            for row in GI.key_mutations(candidate_set, space, key)]


def _renamed(mutations: list[dict[str, Any]]) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    """mutant-structure identity -> original identity of every mutated residue."""
    return {identity({**m["residue"], "resname": m["mutant_resname"]}): identity(m["residue"]) for m in mutations}


def protonation_differences(entry: dict[str, Any], reference_entry: dict[str, Any],
                            mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HIS/CYS residues outside the mutated ones whose variant differs from the reference structure's, in the
    reference's structure order (rows as M21: ``{residue, wild_type_reference, mutant}``)."""
    mutated = {identity(m["residue"]) for m in mutations}
    renamed = _renamed(mutations)
    variants = {identity(row["residue"]): row["variant"] for row in entry["protonation_variants"]
                if identity(row["residue"]) not in renamed}
    return [{"residue": seven(row["residue"]), "wild_type_reference": row["variant"],
             "mutant": variants[identity(row["residue"])]}
            for row in reference_entry["protonation_variants"]
            if identity(row["residue"]) not in mutated and identity(row["residue"]) in variants
            and variants[identity(row["residue"])] != row["variant"]]


def new_disulfide(entry: dict[str, Any], reference_entry: dict[str, Any], mutations: list[dict[str, Any]]) -> bool:
    """A disulfide bond of the mutant that the reference lacks (mutated residues matched by original identity)."""
    back = _renamed(mutations)

    def pairs(item: dict[str, Any]) -> set[frozenset[tuple[Any, ...]]]:
        return {frozenset(back.get(identity(r), identity(r)) for r in bond) for bond in item["disulfide_bonds"]}

    return bool(pairs(entry) - pairs(reference_entry))


def expected_added_atoms(entry: dict[str, Any], reference_entry: dict[str, Any],
                         mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per mutated residue: its heavy atoms in the mutant minus the heavy atom names of the input residue (the
    reference), in atom order."""
    back = _renamed(mutations)
    inputs: dict[tuple[Any, ...], set[str]] = {original: set() for original in back.values()}
    for atom in reference_entry["atom_mapping"]:
        if _heavy(atom) and identity(atom["residue"]) in inputs:
            inputs[identity(atom["residue"])].add(atom["atom_name"])
    return [{"residue": seven(atom["residue"]), "atom_name": atom["atom_name"], "element": atom["element"]}
            for atom in entry["atom_mapping"] if _heavy(atom) and identity(atom["residue"]) in back
            and atom["atom_name"] not in inputs[back[identity(atom["residue"])]]]


def limitations(differences: list[Any], disulfide: bool) -> list[str]:
    applies = {SC.SL5: bool(differences), SC.L6: disulfide}
    return [sentence for sentence in SC.MODEL_LIMITATION_ORDER if applies.get(sentence, True)]


def model_content(*, run_id: str, candidate_set_handle: str, structure: dict[str, Any],
                  mutations: list[dict[str, Any]], seed: int, method: dict[str, Any], entry: dict[str, Any],
                  cif_raw: bytes, reference: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``mutation_set_model@1`` content for one structure entry (the M21 entry keys without ``sasa``,
    ``contacts`` and ``structure_object``) and its mmCIF bytes; the reference model is required with mutations.
    Nothing is checked here beyond what is computed; publication and reads run ``validated_model``."""
    if "structure_object" in entry:
        raise ValueError("the structure object handle is computed from the mmCIF bytes")
    full = {"structure_object": structure_handle(run_id, cif_raw), **copy.deepcopy(entry)}
    if mutations:
        if reference is None:
            raise ValueError("a mutant model is built with its wild-type reference model")
        reference_entry = reference["structures"][SC.REFERENCE_SIDE]
        differences = protonation_differences(full, reference_entry, mutations)
        disulfide = new_disulfide(full, reference_entry, mutations)
        reference_sha = reference_entry["structure_sha256"]
    else:
        differences, disulfide, reference_sha = [], False, None
    return {"schema": SC.MODEL_SCHEMA, "method_version": SC.MODEL_METHOD_VERSION,
            "candidate_set": candidate_set_handle, "structure": dict(structure), "mutations": copy.deepcopy(mutations),
            "seed": seed, "method": dict(method), "structures": {side(mutations): full},
            "protonation_differences": differences, "new_disulfide_in_mutant": disulfide,
            "reference_structure_sha256": reference_sha, "limitations": limitations(differences, disulfide)}


# ---------------------------------------------------------------- validation
def _validate_entry(entry: Any, model_number: int) -> list[tuple[Any, ...]]:
    """Shape and self-consistency of one structure entry (M21 rules without SASA/contacts); residue order."""
    _require(type(entry) is dict and set(entry) == ENTRY_KEYS, "structure entry keys")
    _require(type(entry["structure_object"]) is str and all(_hex(entry[key]) for key in HASH_FIELDS),
             "structure entry handle and hashes")
    atoms, bonds = entry["atom_mapping"], entry["final_bonds"]
    try:
        order = mm._validate_atoms(atoms, bonds, model_number)
    except mm.ModelInvalid as exc:
        raise ModelInvalid(f"atom rows: {exc}") from exc
    _require(entry["topology_sha256"] == mm.topology_sha256(atoms, bonds), "topology hash")
    heavy = sum(_heavy(atom) for atom in atoms)
    _require(type(entry["heavy_atoms"]) is int and entry["heavy_atoms"] == heavy and
             type(entry["added_hydrogens"]) is int and entry["added_hydrogens"] == len(atoms) - heavy,
             "atom counts")
    added = entry["added_heavy_atoms"]
    _require(type(added) is list and all(type(row) is dict and set(row) == ADDED_KEYS for row in added),
             "added_heavy_atoms rows")
    variants = entry["protonation_variants"]
    expected = [seven(atom["residue"]) for i, atom in enumerate(atoms)
                if atom["residue"]["resname"] in MK.PROTONATION_VARIANTS
                and (i == 0 or identity(atoms[i - 1]["residue"]) != identity(atom["residue"]))]
    _require(type(variants) is list and all(type(v) is dict and set(v) == {"residue", "variant"} for v in variants)
             and [v["residue"] for v in variants] == expected
             and all(v["variant"] in MK.PROTONATION_VARIANTS[v["residue"]["resname"]] for v in variants),
             "protonation_variants")
    _require(entry["disulfide_bonds"] == mm.disulfide_bonds(atoms, bonds), "disulfide_bonds")
    energy = entry["energy"]
    _require(type(energy) is dict and set(energy) == {"before_kJ_mol", "after_kJ_mol", *MK.ENERGY_FIXED}
             and all(energy[key] == value for key, value in MK.ENERGY_FIXED.items())
             and _float(energy["before_kJ_mol"]) and _float(energy["after_kJ_mol"])
             and energy["after_kJ_mol"] <= energy["before_kJ_mol"] + MK.ENERGY_INCREASE_TOLERANCE_KJ_MOL,
             "energy")
    return order


def _outside(atoms: list[dict[str, Any]], skip: set[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [(identity(a["residue"]), a["atom_name"], a["element"]) for a in atoms
            if _heavy(a) and identity(a["residue"]) not in skip]


def _check_reference(content: dict[str, Any], reference: Any) -> dict[str, Any]:
    _require(type(reference) is dict and set(reference) == TOP_KEYS and reference["schema"] == SC.MODEL_SCHEMA and
             reference["mutations"] == [] and type(reference["structures"]) is dict and
             set(reference["structures"]) == {SC.REFERENCE_SIDE}, "the reference is a wild-type set model")
    _require(all(reference[key] == content[key] for key in ("candidate_set", "structure", "seed", "method")),
             "the reference has the same candidate set, structure, seed and method")
    entry = reference["structures"][SC.REFERENCE_SIDE]
    _require(type(entry) is dict and content["reference_structure_sha256"] == entry.get("structure_sha256"),
             "reference_structure_sha256")
    return entry


def validated_model(content: Any, *, run_id: str, candidate_set_handle: str, candidate_set: dict[str, Any],
                    structure_cif: bytes, reference: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``content`` if it is a well-formed ``mutation_set_model@1`` of run ``run_id`` over the validated M20
    ``candidate_set`` (handle ``candidate_set_handle``) whose stored mmCIF bytes are ``structure_cif``; else
    ``ModelInvalid``. A model with mutations needs ``reference``: the (separately validated) wild-type reference
    model of the same run conditions; the reference itself takes none."""
    try:
        return _validated(content, run_id, candidate_set_handle, candidate_set, structure_cif, reference)
    except ModelInvalid:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        raise ModelInvalid(f"malformed sequence model: {type(exc).__name__}") from exc


def _validated(content: Any, run_id: str, candidate_set_handle: str, candidate_set: dict[str, Any],
               structure_cif: bytes, reference: dict[str, Any] | None) -> dict[str, Any]:
    _require(type(content) is dict and set(content) == TOP_KEYS, "top-level keys")
    _require(content["schema"] == SC.MODEL_SCHEMA and content["method_version"] == SC.MODEL_METHOD_VERSION,
             "schema")
    _require(type(content["candidate_set"]) is str and content["candidate_set"] == candidate_set_handle,
             "candidate set handle")
    _require(content["structure"] == candidate_set["structure"], "structure is the candidate set's")
    low, high, _default = SC.GA_RANGES["seed"]
    _require(type(content["seed"]) is int and low <= content["seed"] <= high, "seed")
    try:
        GI.check_model_method(content["method"])
    except (ValueError, mm.ModelInvalid) as exc:
        raise ModelInvalid("method") from exc
    mutations = content["mutations"]
    _require(type(mutations) is list and all(type(m) is dict and set(m) == MUTATION_KEYS for m in mutations),
             "mutation rows")
    if mutations:
        key = GI.key_text(m["candidate_index"] for m in mutations)
        _require(mutations == model_mutations(candidate_set, key), "mutations are the candidate set's rows")
    structures = content["structures"]
    _require(type(structures) is dict and set(structures) == {side(mutations)}, "one structure, the model's side")
    entry = structures[side(mutations)]
    order = _validate_entry(entry, content["structure"]["model_number"])
    _require(hashlib.sha256(structure_cif).hexdigest() == entry["structure_sha256"] and
             entry["structure_object"] == structure_handle(run_id, structure_cif), "stored mmCIF bytes and handle")
    back = _renamed(mutations)
    _require([key for key in order if key in back] == list(back) and
             not set(back.values()) & set(order), "each mutated residue once, renamed, in mutation order")
    differences, disulfide = content["protonation_differences"], content["new_disulfide_in_mutant"]
    _require(type(differences) is list and all(type(d) is dict and set(d) == DIFFERENCE_KEYS for d in differences)
             and type(disulfide) is bool, "difference rows")
    if not mutations:
        _require(reference is None, "the wild-type reference model takes no reference")
        _require(entry["added_heavy_atoms"] == [] and differences == [] and disulfide is False and
                 content["reference_structure_sha256"] is None, "a wild-type model has no mutation records")
    else:
        _require(reference is not None, "a mutant model is validated with its wild-type reference model")
        reference_entry = _check_reference(content, reference)
        reference_order = [identity(a["residue"]) for a in reference_entry["atom_mapping"]]
        _require(list(dict.fromkeys(reference_order)) == [back.get(key, key) for key in order],
                 "residue order differs from the reference")
        _require(_outside(entry["atom_mapping"], set(back)) ==
                 _outside(reference_entry["atom_mapping"], set(back.values())),
                 "heavy atoms outside the mutated residues differ from the reference")
        _require(entry["added_heavy_atoms"] == expected_added_atoms(entry, reference_entry, mutations),
                 "added_heavy_atoms is not the template minus the input atoms per residue")
        _require(canonical_json(differences) == canonical_json(
            protonation_differences(entry, reference_entry, mutations)), "protonation_differences")
        _require(disulfide is new_disulfide(entry, reference_entry, mutations), "new_disulfide_in_mutant")
    _require(content["limitations"] == limitations(differences, disulfide), "limitations")
    _require(len(canonical_json(content)) <= SC.MAX_MODEL_OBJECT_BYTES, "model object size")
    return content
