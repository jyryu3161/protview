"""M21 server-side admission for ``openmm_mutation_model_v1`` (spec .dryforge/spec.md 2).

Pure functions on the job arguments and on values the caller loads; no OpenMM, no PDBFixer, no events. Every refusal
is ``ToolFailure(input_invalid)`` with ``detail.reason_code`` from ``mutation_model_constants.ADMISSION_REASON_CODES``.

``admit`` runs the checks in the spec order and stops at the first failure:

1. ``unknown_field``: any key outside ``ARG_KEYS``.
2. ``confirmation_missing``: ``selection_policy`` / ``hydrogen_policy`` missing or not exactly the literal.
3. ``argument_invalid``: ``candidate_index`` (int >= 0), ``seed`` (int in ``SEED_RANGE``) and ``contact_cutoff_A``
   (finite int/float in ``CONTACT_CUTOFF_RANGE_A``, default 4.0; null refused). bool, NaN and Infinity are refused.
4. ``candidate_set_invalid``: not a non-empty string, ``meta(handle)`` is None (not a published object of this run;
   the caller's ``meta`` answers None for other runs and unpublished objects) or not ``mutation_candidate_set@1``, or
   the loaded content fails the M20 ``validated_set`` (re-run on every admission).
5. ``candidate_unknown``: no candidate with that ``index`` (a zero-candidate set has none). Selection is by the integer
   index only, never by the ``from``/``to`` letters.
6. ``structure_invalid``: the set's structure is not a ``prepared_structure@1`` of this run (``meta`` again).
7. ``residue_mismatch``: the position's 7 fields (types exact, nulls included) do not resolve to exactly one residue
   of that structure, or the candidate ``from`` is not the standard one-letter code of that residue.

``openmm_preflight_failed`` comes after these, from the M7 preflight the queue/bundle layer runs; ``preflight_failure``
maps its ``ToolFailure`` (412 unavailability stays 412). ``normalize_timeout`` checks the ``JobSubmit.timeout_s``
field the queue applies to this protocol (not a job argument, not in the call key).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from . import mutation_candidates as mc
from . import mutation_model_constants as K
from .core.errors import FailureClass, ToolFailure
from .mutation_constants import STANDARD_ONE_LETTER

PREPARED_TYPE = (K.STRUCTURE_KIND, f"{K.STRUCTURE_KIND}@1")
CANDIDATE_SET_TYPE = (K.CANDIDATE_SET_KIND, K.CANDIDATE_SET_SCHEMA)


def _invalid(reason_code: str, message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code})


def _number(value: Any) -> float | None:
    """Finite int/float (never bool) as a float with -0.0 folded to 0.0, else None."""
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) + 0.0


def normalize_arguments(args: Any) -> dict[str, Any]:
    """Checks 1--3 and the ``candidate_set`` shape; the normalized arguments (the call-key input)."""
    if not isinstance(args, dict):
        raise _invalid("argument_invalid", "arguments must be an object")
    unknown = sorted(set(args) - set(K.ARG_KEYS))
    if unknown:
        raise _invalid("unknown_field", f"unknown parameters: {unknown}")
    if (type(args.get("selection_policy")) is not str or args["selection_policy"] != K.SELECTION_POLICY
            or type(args.get("hydrogen_policy")) is not str or args["hydrogen_policy"] != K.HYDROGEN_POLICY):
        raise _invalid("confirmation_missing", f"selection_policy must be '{K.SELECTION_POLICY}' and "
                                               f"hydrogen_policy must be '{K.HYDROGEN_POLICY}'")
    index = args.get("candidate_index")
    if type(index) is not int or index < 0:
        raise _invalid("argument_invalid", "candidate_index must be an integer >= 0")
    seed = args.get("seed")
    low, high = K.SEED_RANGE
    if type(seed) is not int or not low <= seed <= high:
        raise _invalid("argument_invalid", f"seed must be an integer in [{low}, {high}]")
    cutoff = _number(args.get("contact_cutoff_A", K.CONTACT_CUTOFF_DEFAULT_A))
    low_a, high_a = K.CONTACT_CUTOFF_RANGE_A
    if cutoff is None or not low_a <= cutoff <= high_a:
        raise _invalid("argument_invalid", f"contact_cutoff_A must be a finite number in [{low_a}, {high_a}]")
    candidate_set = args.get("candidate_set")
    if type(candidate_set) is not str or not candidate_set:
        raise _invalid("candidate_set_invalid", "candidate_set must be a mutation_candidate_set handle")
    return {"candidate_set": candidate_set, "candidate_index": index, "seed": seed, "contact_cutoff_A": cutoff,
            "selection_policy": K.SELECTION_POLICY, "hydrogen_policy": K.HYDROGEN_POLICY}


def normalize_timeout(value: Any) -> float:
    """``JobSubmit.timeout_s`` for this protocol: default 120 s, (0, 240] s."""
    if value is None:
        return float(K.TIMEOUT_DEFAULT_S)
    seconds = _number(value)
    if seconds is None or not 0 < seconds <= K.TIMEOUT_MAX_S:
        raise _invalid("argument_invalid", f"timeout_s must be a finite number in (0, {K.TIMEOUT_MAX_S}]")
    return seconds


def validated_candidate_set(handle: str, meta: dict[str, Any] | None, load: Callable[[str], Any]) -> dict[str, Any]:
    """Check 4: the stored M20 set, re-validated with ``validated_set``."""
    if meta is None or (meta.get("kind"), meta.get("schema")) != CANDIDATE_SET_TYPE:
        raise _invalid("candidate_set_invalid", "candidate_set must be a published mutation_candidate_set@1 "
                                                "of this run")
    try:
        return mc.validated_set(load(handle))
    except (mc.MutationSetInvalid, ValueError, TypeError, KeyError) as exc:
        raise _invalid("candidate_set_invalid", "the stored candidate set does not validate") from exc


def select_candidate(content: dict[str, Any], index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check 5: ``(candidate, position)`` for the integer ``index`` of a validated set."""
    found = [candidate for candidate in content["candidates"] if candidate["index"] == index]
    if len(found) != 1:
        raise _invalid("candidate_unknown", f"candidate_index {index} is not a candidate of this set")
    return found[0], content["positions"][found[0]["position_index"]]


def check_structure(content: dict[str, Any], meta: dict[str, Any] | None) -> str:
    """Check 6: the set's structure handle, a ``prepared_structure@1`` of this run."""
    if meta is None or (meta.get("kind"), meta.get("schema")) != PREPARED_TYPE:
        raise _invalid("structure_invalid", "the candidate set's structure is not a prepared_structure of this run")
    return content["structure"]["handle"]


def check_residue(candidate: dict[str, Any], position: dict[str, Any],
                  residues: list[dict[str, Any]]) -> dict[str, Any]:
    """Check 7 against ``structure_residues(...)["residues"]``; the resolved residue's 7 fields."""
    key = mc.identity(position["residue"])
    found = [residue for residue in residues if mc.identity(residue) == key]
    if len(found) != 1:
        reason = "not found in" if not found else "ambiguous in"
        raise _invalid("residue_mismatch", f"the candidate position residue is {reason} the structure")
    standard = mc.standard_name(found[0]["resname"])
    if standard is None or STANDARD_ONE_LETTER[standard] != candidate["from"]:
        raise _invalid("residue_mismatch", "the candidate 'from' residue differs from the structure residue")
    return mc.seven(found[0])


def admit(args: Any, *, meta: Callable[[str], dict[str, Any] | None], load: Callable[[str], Any],
          residues: Callable[[str], list[dict[str, Any]]]) -> dict[str, Any]:
    """Checks 1--7 in order. ``meta(handle)`` is the store metadata of a published object of this run or None;
    ``load(handle)`` the stored content; ``residues(structure)`` the ``structure_residues`` residue list."""
    arguments = normalize_arguments(args)
    handle = arguments["candidate_set"]
    content = validated_candidate_set(handle, meta(handle), load)
    candidate, position = select_candidate(content, arguments["candidate_index"])
    structure = check_structure(content, meta(content["structure"]["handle"]))
    residue = check_residue(candidate, position, residues(structure))
    return {"arguments": arguments, "candidate_set_content": content, "candidate": candidate, "position": position,
            "structure": structure, "model_number": content["structure"]["model_number"], "residue": residue,
            "mutant_resname": K.THREE_LETTER[candidate["to"]]}


def preflight_failure(exc: ToolFailure) -> ToolFailure:
    """The admission failure for an M7 ``preflight`` failure: unavailability (412) unchanged, everything else
    (input_invalid, precondition, resource_exceeded incl. the 6,000-atom limit) as 422 ``openmm_preflight_failed``."""
    code = exc.detail.get("reason_code") if isinstance(exc.detail, dict) else None
    if exc.cls is FailureClass.precondition and code in ("openmm_unavailable", "process_identity_unavailable"):
        return exc
    return ToolFailure(FailureClass.input_invalid, "the structure does not pass the M7 OpenMM preflight",
                       detail={"reason_code": "openmm_preflight_failed",
                               "m7_reason": code if type(code) is str else None, "m7_message": exc.message})


def excluded_components(excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``excluded_components`` from the M7 preflight ``excluded`` list: every category, fixed order, counts."""
    if any(item["reason"] not in K.EXCLUDED_CATEGORIES for item in excluded):
        raise ValueError("unknown M7 exclusion category")
    return [{"reason": reason, "residue_count": sum(item["reason"] == reason for item in excluded),
             "atom_count": sum(item["atom_count"] for item in excluded if item["reason"] == reason)}
            for reason in K.EXCLUDED_CATEGORIES]
