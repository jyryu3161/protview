"""M29 M20 hand-off: reference results of the original structure on a repaired structure, and ``modeled_basis``.

Spec ``.dryforge/spec.md`` 5.3 and 5.4. Pure functions over the run's object store (``meta`` / ``load`` only): nothing
is written and no event, job or tool call is made. The stored ``mutation_candidate_set@1`` is never changed:
``mutation_candidates.py`` (a call-key hash file, read and called here, never edited) stores a residue that matches no
row of a reference result as "checked, none" (``numbering.status = not_in_map``, ``protection.klifs_sites = []``,
``protection.catalytic = []``). For a modeled residue of a repaired structure (an internal-gap residue or an MSE residue
replaced by MET, i.e. a residue whose 7-field identity is not one of the original structure) that is not true, so the
read layer shows those fields as not checked (modeled residue) from the repair record.

Public API:

``checked_origin(run, structure) -> dict | None``
    None unless ``structure`` is a repaired structure (``preparation_manifest@1`` key ``repair``). Otherwise the
    ``structure_origin`` dict plus ``"record"`` (the stored ``structure_repair@1``), after the check the downstream
    reports and reads make (M29 T8b, the steps of ``structure_origin_reports.origin``): the link, then
    ``structure_repair_bundle.validated_result`` over ``run`` (a run or a view: ``store`` and ``events.read()``): the
    record's single completed repair-job publication (``structure_repair_published`` and the job's done
    terminal), its four objects and ``structure_repair.validated_repair`` re-deriving the record from the original
    prepared structure (``repair.source``) and the stored repaired bytes; and the published structure must be
    ``structure`` from that source. A repaired structure without publication evidence (e.g. objects left by a partial
    store) therefore fails. ``ToolFailure`` (``repair_record_mismatch``) when the link, the publication or the record
    does not validate, or a ``ToolFailure`` of class ``precondition`` (``openmm_unavailable``) when the installed
    template the check reads is unavailable; callers pass that one through as the environment failure it is (spec 4.6).
``validated_origin(store, structure) -> dict | None``
    ``checked_origin`` over the store and the run's own event log (``store.events``): the M20 admission's and the
    reads' check.
``reference_structures(structure, origin) -> tuple[str, ...]``
    The structures whose pocket set / numbering map / annotation / catalytic annotation an M20 call on ``structure``
    accepts: the structure itself and, for a repaired structure, its original prepared structure (spec 5.3).
``read_view(store, content) -> dict | None``
    None when the set's structure is not a repaired structure (the reads then add nothing, so their bytes are
    unchanged). Otherwise ``{"positions": [{"modeled_basis", "reference_not_checked"} per stored position, in stored
    order], "repair_handoff": {"references", "statements"}}``:

    * ``modeled_basis`` (spec 5.4): true when the position's residue has a modeled atom (``added_atoms`` of the record:
      a new side-chain atom, OXT or a gap residue), or when the ligand-shell, metal-contact or disulfide judgment of
      ``mutation_candidates`` (``_walk`` / ``_min_distance``, same rules and thresholds as the stored parameters) made
      with the observed atoms only differs from the same judgment with every atom.
    * ``reference_not_checked``: the stored fields (``REFERENCE_FIELDS`` order) shown as not checked (modeled residue)
      for a gap or replaced residue: ``numbering`` when the numbering map was handed off and the stored status is
      ``not_in_map``; ``klifs_sites`` when the annotation was handed off and the stored list is empty; ``catalytic``
      when the catalytic annotation was handed off and the stored list is empty (a stored null is already "not
      checked"). Empty for every other position.
    * ``references``: the reference results of the set made on the original structure (``HANDOFF_KEYS`` order).
    * ``statements``: ``[{"id", "text"}]``, the fixed sentences verbatim from ``structure_repair_constants``: SO2 when
      a position's ``modeled_basis`` is true, SO3 when ``references`` is not empty.

    ``ToolFailure`` (link or record), ``KeyError`` / ``TypeError`` / ``ValueError`` (a stored object of another shape)
    when it cannot be computed; the caller maps them to its evidence error, except a ``precondition`` failure (the
    environment, see ``validated_origin``), which it passes through.
``basis_reasons(st, record, content) -> list[tuple[str, ...]]``
    The ``BASIS_REASONS`` behind each position's ``modeled_basis`` (stored order); ``st`` is the parsed repaired
    structure (``tools.structural._parse``). Used by ``read_view``; exposed for tests.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from . import mutation_candidates as mc
from . import structure_repair_bundle as bundle
from . import structure_repair_constants as K
from .core.errors import FailureClass, ToolFailure
from .mutation_constants import CYSTEINE, DISULFIDE_SG_A
from .structure_origin import structure_origin
from .tools.registry import ToolContext
from .tools.structural import _parse, _res_ref

REFERENCE_FIELDS = ("numbering", "klifs_sites", "catalytic")
HANDOFF_KEYS = ("pocket_set", "numbering_map", "annotation", "catalytic_annotation")
BASIS_REASONS = ("modeled_atoms", "ligand_shell", "metal_contact", "disulfide")


def _mismatch(message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": "repair_record_mismatch"})


def checked_origin(run: Any, structure: Any) -> dict[str, Any] | None:
    origin = structure_origin(run.store, structure)
    if origin is None:
        return None
    try:
        repair = bundle.validated_result(run, origin["repair_record"])
    except bundle.RepairEvidenceError as exc:   # the environment's precondition ToolFailure passes through as it is
        raise _mismatch("the repaired structure has no valid published repair record") from exc
    if (repair["prepared_structure"], repair["source_structure"]) != (structure, origin["source_structure"]):
        raise _mismatch("the repair record published another structure")
    return {**origin, "record": repair["record"]}


class _StoreRun:
    """A run view of a store and its own event log (the M20 admission hook gets the store only)."""

    def __init__(self, store: Any) -> None:
        self.store, self.events, self.run_id = store, store.events, store.run_id


def validated_origin(store: Any, structure: Any) -> dict[str, Any] | None:
    return checked_origin(_StoreRun(store), structure)


def reference_structures(structure: str, origin: dict[str, Any] | None) -> tuple[str, ...]:
    return (structure,) if origin is None else (structure, origin["source_structure"])


def _handed_off(store: Any, parameters: dict[str, Any], source: str) -> list[str]:
    pocket = parameters["sources"]["pocket"]
    made_on = {"pocket_set": None if pocket is None else store.load(pocket["pocket_set"])["source_handle"]}
    for key in HANDOFF_KEYS[1:]:
        handle = parameters.get(key)
        made_on[key] = None if handle is None else store.load(handle)["structure"]["handle"]
    return [key for key in HANDOFF_KEYS if made_on[key] is not None and made_on[key] == source]


def _modeled_keys(record: dict[str, Any]) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    """(residues with a modeled atom, residues whose identity the original structure does not have)."""
    with_atoms = {mc.identity(item["residue"]) for item in record["added_atoms"]}
    new = {mc.identity(mc.seven(residue)) for gap in record["gaps"] for residue in gap["residues"]}
    new |= {mc.identity(item["to"]) for item in record["replaced"]}
    return with_atoms, new


def _observed_only(st: Any, record: dict[str, Any]) -> Any:
    """A copy of ``st`` without the record's added atoms (empty gap residues stay, with no atom)."""
    added = {(mc.identity(item["residue"]), item["atom_name"]) for item in record["added_atoms"]}
    observed = st.clone()
    model = observed[0]
    for chain in model:
        for res in chain:
            key = mc.identity(_res_ref(chain, res, model.num))
            for index in range(len(res) - 1, -1, -1):
                if (key, res[index].name) in added:
                    del res[index]
    return observed


def _judge(walk: list[dict[str, Any]], parameters: dict[str, Any]) -> Any:
    """The ligand-shell, metal and disulfide judgments of ``mutation_candidates.build_candidate_set`` over ``walk``."""
    by_key = {mc.identity(entry["residue"]): entry for entry in walk}
    shell = parameters["sources"]["ligand_shell"]
    ligand = parameters["ligand"]
    ligand_heavy = by_key[mc.identity(ligand)]["heavy"] if ligand is not None else None
    threshold = parameters["metal_contact_A"]
    metals = [entry for entry in walk if entry["metal"]]
    cys = [entry for entry in walk if entry["category"] == "polymer"
           and mc.standard_name(entry["residue"]["resname"]) == CYSTEINE and len(entry["sg"])]

    def judge(residue: dict[str, Any]) -> tuple[bool, Any, Any]:
        key = mc.identity(residue)
        entry = by_key[key]
        heavy = entry["heavy"]
        in_shell = bool(shell is not None and len(heavy)
                        and mc._min_distance(heavy, ligand_heavy) <= shell["radius_A"])
        metal = None
        if metals and len(heavy):
            distances = [mc._min_distance(heavy, item["all"]) for item in metals]
            nearest = int(np.argmin(distances))
            if distances[nearest] <= threshold:
                metal = (distances[nearest], mc.identity(metals[nearest]["residue"]))
        partner = None
        if mc.standard_name(residue["resname"]) == CYSTEINE and len(entry["sg"]):
            others = [item for item in cys if mc.identity(item["residue"]) != key]
            distances = [mc._min_distance(entry["sg"], item["sg"]) for item in others]
            if distances and min(distances) <= DISULFIDE_SG_A:
                partner = mc.identity(others[int(np.argmin(distances))]["residue"])
        return in_shell, metal, partner

    return judge


def basis_reasons(st: Any, record: dict[str, Any], content: dict[str, Any]) -> list[tuple[str, ...]]:
    parameters = content["parameters"]
    with_atoms, _new = _modeled_keys(record)
    every = _judge(mc._walk(st), parameters)
    observed = _judge(mc._walk(_observed_only(st, record)), parameters)
    out = []
    for position in content["positions"]:
        residue = position["residue"]
        found = {"modeled_atoms"} if mc.identity(residue) in with_atoms else set()
        found |= {name for name, a, b in zip(BASIS_REASONS[1:], every(residue), observed(residue), strict=True)
                  if a != b}
        out.append(tuple(name for name in BASIS_REASONS if name in found))
    return out


def _not_checked(position: dict[str, Any], handed: list[str]) -> list[str]:
    numbering, protection = position["numbering"], position["protection"]
    shown = {"numbering": "numbering_map" in handed and numbering is not None and numbering["status"] == "not_in_map",
             "klifs_sites": "annotation" in handed and protection["klifs_sites"] == [],
             "catalytic": "catalytic_annotation" in handed and protection.get("catalytic") == []}
    return [field for field in REFERENCE_FIELDS if shown[field]]


def read_view(store: Any, content: dict[str, Any]) -> dict[str, Any] | None:
    structure = content["structure"]["handle"]
    origin = validated_origin(store, structure)
    if origin is None:
        return None
    record = origin["record"]
    handed = _handed_off(store, content["parameters"], origin["source_structure"])
    reasons = basis_reasons(_parse(ToolContext(store=store, call_id="metadata"), structure), record, content)
    _with_atoms, new = _modeled_keys(record)
    positions = [{"modeled_basis": bool(found),
                  "reference_not_checked": (_not_checked(position, handed)
                                            if mc.identity(position["residue"]) in new else [])}
                 for position, found in zip(content["positions"], reasons, strict=True)]
    statements = ([{"id": "SO2", "text": K.SO2}] if any(row["modeled_basis"] for row in positions) else [])
    statements += [{"id": "SO3", "text": K.SO3}] if handed else []
    return {"positions": positions, "repair_handoff": {"references": handed, "statements": statements}}
