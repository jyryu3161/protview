"""M23 GA summary ``sequence_ga_result@1``: the job's selection record, the summary built from the worker's generation
records and the server's per-individual observations, and the pure ``validated_summary`` (spec .dryforge/spec.md 3, 4,
7).

No RDKit, no Meeko, no OpenMM, no store writes, no events. The caller (T5/T6) reads the staging files, publishes and
validates every model (``sequence_model_bundle.validated_model`` with the stored mmCIF) and docking result
(``docking_bundle.validated_result``), resolves the stop reason (a worker ``cancelled`` re-read with the server's stop
cause) and passes here:

- ``records``: the worker generation records ``{index, complete, individuals: [{key, origin, parents, edit_op,
  evaluation, pick_index, eval_index}]}`` in order (no score, no state);
- ``reference``: ``{evaluation, state, reason_code, model_handle, result_handle}`` of the wild-type reference row;
- ``observations``: individual key -> ``{state, reason_code, model_handle, result_handle}`` for every non-carried
  individual (``resolve_observation`` maps a worker status and the published handles to one; a reused individual is
  its reuse index record);
- ``results`` / ``models``: the validated stored objects by handle (the reference model among the models).

Scores and states are never taken from the worker: a published result makes the individual ``scored`` (first mode's
``score_kcal_mol``) or ``null_result`` (no mode). A ``carried`` entry cites the previous generation's entry with the
same key (pick index, state, score, handles).

Checked on build and on every read (``validated_summary``): exact keys at every level (so no rank, difference, best or
improved field can exist), the selection record, pins, call key, ``conditions_sha256``, box, reserved figures
(``reserved_units = 2 x (reserved_evaluations + 1)``), every individual a key of the combination space (distinct
positions, at most the effective ``max_mutations``) with the candidate set's mutation rows, non-carried keys unique in
the run, ``pick_index`` 0, 1, ... and ``eval_index`` 0, 1, ... (computed only) in listing order, generation 1 only
``initial``, carried entries first and equal to the previous generation's ``elite_count`` first scored individuals in
score order (score, then fewer mutations, then ``pick_index``), crossover / edit / random counts within the slot
counts, parents scored individuals of the previous generation, a crossover child non-empty inside its two distinct
parents' union, an edit child one ``add``/``remove``/``change``/``move`` from its parent, scores = the stored results'
first modes, every model's mutations, candidate set, structure, seed and method equal to the summary and its
reference structure, protonation differences and new-disulfide flag recomputed against the reference row's model,
every result the individual's own standalone M18 request on its model, ``min_score``/``max_score``, counts, status =
the stop reason's, the stop structure (below), the S sentences and the 1 MiB bound. Parent choices (tournaments,
random calls, retries) are worker records the server cannot recompute (S1): only the parent-child relations are
checked.

Stop structure: only the last generation can be incomplete (partial runs only); ``generations_complete`` = every
generation; ``space_exhausted`` = every key seen; ``evaluation_limit`` = ``reserved_evaluations`` new evaluations and
an incomplete last generation; ``repeated_failure`` = the fifth consecutive failure (carried entries skipped) is the
last entry of an incomplete generation; ``reference_failed`` = a failed reference row and no generation; ``no_change``
= the patience counter (spec 3 step 5, worker procedure "detail" 7) reaches ``patience`` at the last generation. A
worker that reaches one of its own terminal points (the last generation, every key seen, the patience point, the
fifth failure) stops there; a stop from outside the worker (``time_exhausted``, ``cancelled``, ``worker_failed``,
``resource_exceeded``) is accepted at such a point because it can race the worker's own decision, never after it.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from . import docking_constants as C
from . import docking_inputs
from . import mutation_model_constants as MK
from . import sequence_ga_constants as SC
from . import sequence_ga_inputs as GI
from . import sequence_model_bundle as SM
from .core.handles import canonical_json
from .docking_batch_bundle import PREPARATION

SELECTION_KEYS = frozenset({"schema", "arguments", "structure", "ligand", "space", "selection_sha256"})
SUMMARY_KEYS = frozenset({"schema", "protocol", "engine", "candidate_set", "structure", "ligand", "box", "parameters",
                          "selection_policy", "hydrogen_policy", "method", "pins", "call_key", "conditions_sha256",
                          "selection_sha256", "ga", "space", "status", "stop_reason", "generations_done",
                          "new_evaluations_used", "reused_count", "reserved_evaluations", "reserved_units",
                          "reference", "generations", "limitations"})
GENERATION_KEYS = frozenset({"index", "complete", "individuals", "min_score", "max_score"})
RECORD_KEYS = frozenset({"key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index"})
INDIVIDUAL_KEYS = RECORD_KEYS | {"mutations", "state", "reason_code", "score", "model_handle", "result_handle"}
REFERENCE_KEYS = frozenset({"evaluation", "state", "reason_code", "score", "model_handle", "result_handle"})
OBSERVATION_KEYS = frozenset({"state", "reason_code", "model_handle", "result_handle"})
STATUS_KEYS = frozenset({"state", "reason_code", "stage"})
CITED = ("key", "mutations", "pick_index", "state", "reason_code", "score", "model_handle", "result_handle")
OUTSIDE_STOPS = frozenset({"time_exhausted", "cancelled", "worker_failed", "resource_exceeded"})
REASONS_BY_STATE = {"scored": (None,), "null_result": (None,), "failed": SC.FAILURE_REASONS}


class SequenceGaEvidenceError(ValueError):
    """A GA summary, its selection or its observations do not validate against the stored facts."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise SequenceGaEvidenceError(message)


def _float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _handle(value: Any) -> bool:
    return type(value) is str and value != ""


# ----------------------------------------------------------------- selection record (spec 7, 8)
def selection_record(admitted: dict[str, Any]) -> dict[str, Any]:
    """The job's ``sequence_ga_selection@1`` from ``sequence_ga_inputs.admission``: normalized arguments, structure,
    ligand SDF, the space counts and the selection hash (no candidate rows, no per-individual M18 selection)."""
    selected = {"schema": SC.SELECTION_SCHEMA, "arguments": copy.deepcopy(admitted["arguments"]),
                "structure": dict(admitted["structure"]), "ligand": dict(admitted["ligand"]),
                "space": GI.space_counts(admitted["space"])}
    selected["selection_sha256"] = GI.selection_sha256(selected)
    return selected


def _check_selection(selected: Any, candidate_set: dict[str, Any]) -> dict[str, Any]:
    _require(type(selected) is dict and set(selected) == SELECTION_KEYS and selected["schema"] == SC.SELECTION_SCHEMA,
             "selection keys")
    args = selected["arguments"]
    _require(selected["selection_sha256"] == GI.selection_sha256(selected), "selection hash")
    _require(GI.normalize_ga(args["ga"]) == args["ga"] and GI.request_box(args["box"]) == args["box"],
             "selection arguments")
    _require(selected["structure"] == candidate_set["structure"], "selection structure is the candidate set's")
    space = GI.candidate_space(candidate_set, args["ga"]["max_mutations"])
    _require(selected["space"] == GI.space_counts(space), "selection space")
    return space


# ----------------------------------------------------------------- observations
def _result_state(result: dict[str, Any]) -> str:
    return "scored" if len(result["modes"]) >= 1 else "null_result"


def _first_score(result: dict[str, Any] | None) -> Any:
    return result["modes"][0]["score_kcal_mol"] if result is not None and result["modes"] else None


def resolve_observation(status: Any, model_handle: Any, result_handle: Any,
                        results: Mapping[str, Any]) -> dict[str, Any]:
    """One individual's (or the reference row's) observation from the worker's ``status.json`` (``{state,
    reason_code, stage}`` or None) and the handles the server published. A published result gives its state (the
    status, when present, must agree); a model without a result is a docking-stage failure; a docked status whose
    result could not be published is ``engine_output_invalid`` (the M18 reason for refused output); a missing status
    or a docking-stage status without a published model is ``worker_failed``."""
    try:
        if status is not None:
            _require(type(status) is dict and set(status) == STATUS_KEYS and status["state"] in SC.STATES and
                     status["stage"] in SC.STAGES and status["reason_code"] in REASONS_BY_STATE[status["state"]],
                     "individual status")
        _require((model_handle is None or _handle(model_handle)) and (result_handle is None or _handle(result_handle)),
                 "observation handles")
        if result_handle is not None:
            _require(model_handle is not None and result_handle in results, "a result needs its published model")
            state = _result_state(results[result_handle])
            _require(status is None or (status["state"], status["reason_code"]) == (state, None),
                     "status agrees with the result")
            return {"state": state, "reason_code": None, "model_handle": model_handle, "result_handle": result_handle}
        if status is None or (model_handle is None and status["stage"] == "docking" and status["state"] == "failed"):
            reason = "worker_failed"
        elif status["state"] != "failed":
            reason = "engine_output_invalid" if model_handle is not None else "worker_failed"
        else:
            _require((model_handle is None) == (status["stage"] == "model"), "a modeling failure has no model")
            reason = status["reason_code"]
        return {"state": "failed", "reason_code": reason, "model_handle": model_handle, "result_handle": None}
    except SequenceGaEvidenceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SequenceGaEvidenceError("individual observation") from exc


def _observed(observation: Any, results: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(observation) is dict and set(observation) == OBSERVATION_KEYS, "observation keys")
    result = results.get(observation["result_handle"]) if observation["result_handle"] is not None else None
    if observation["result_handle"] is not None:
        _require(result is not None and observation["state"] == _result_state(result) and
                 observation["reason_code"] is None, "observation state is the stored result's")
    return {"state": observation["state"], "reason_code": observation["reason_code"], "score": _first_score(result),
            "model_handle": observation["model_handle"], "result_handle": observation["result_handle"]}


def _generations(records: Any, observations: Mapping[str, Any], results: Mapping[str, Any],
                 candidate_set: dict[str, Any], space: dict[str, Any]) -> list[dict[str, Any]]:
    _require(type(records) is list, "generation records")
    out: list[dict[str, Any]] = []
    for record in records:
        _require(type(record) is dict and set(record) == {"index", "complete", "individuals"} and
                 type(record["individuals"]) is list, "generation record")
        previous = {entry["key"]: entry for entry in out[-1]["individuals"]} if out else {}
        individuals = []
        for entry in record["individuals"]:
            _require(type(entry) is dict and set(entry) == RECORD_KEYS, "generation record entry")
            if entry["origin"] == "carried":
                source = previous.get(entry["key"])
                _require(source is not None, "a carried individual is in the previous generation")
                derived = {key: source[key] for key in ("state", "reason_code", "score", "model_handle",
                                                        "result_handle")}
            else:
                _require(entry["key"] in observations, "an observation per evaluated individual")
                derived = _observed(observations[entry["key"]], results)
            individuals.append({**entry, "mutations": GI.key_mutations(candidate_set, space, entry["key"]),
                                **derived})
        scores = [e["score"] for e in individuals if e["state"] == "scored"]
        out.append({"index": record["index"], "complete": record["complete"], "individuals": individuals,
                    "min_score": min(scores) if scores else None, "max_score": max(scores) if scores else None})
    return out


# ----------------------------------------------------------------- summary
def limitations(status: str, reused_count: int) -> list[str]:
    """S1 always, S2 when partial, S3 when an individual was reused, S4-S6 always (ids; the text is
    ``sequence_ga_constants.STATEMENTS``)."""
    return ["S1", *["S2"] * (status == "partial"), *["S3"] * (reused_count > 0), "S4", "S5", "S6"]


def _counts(generations: list[dict[str, Any]]) -> dict[str, int]:
    evaluated = [e for g in generations for e in g["individuals"] if e["origin"] != "carried"]
    return {"generations_done": sum(g["complete"] is True for g in generations),
            "new_evaluations_used": sum(e["evaluation"] == "computed" for e in evaluated),
            "reused_count": sum(e["evaluation"] == "reused" for e in evaluated)}


def build_summary(selected: dict[str, Any], *, candidate_set: dict[str, Any], records: Any, reference: Any,
                  observations: Mapping[str, Any], results: Mapping[str, Any], models: Mapping[str, Any],
                  stop_reason: Any, box: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    """The ``sequence_ga_result@1`` content (no time, reuse set or job identity), validated before it is returned."""
    try:
        _require(stop_reason in SC.STOP_REASONS, "stop reason")
        args = selected["arguments"]
        space = GI.candidate_space(candidate_set, args["ga"]["max_mutations"])
        generations = _generations(records, observations, results, candidate_set, space)
        _require(type(reference) is dict and set(reference) == OBSERVATION_KEYS | {"evaluation"},
                 "reference observation")
        row = {"evaluation": reference["evaluation"],
               **_observed({key: reference[key] for key in OBSERVATION_KEYS}, results)}
        status = SC.STATUS_BY_STOP_REASON[stop_reason]
        counts = _counts(generations)
        content = {"schema": SC.SUMMARY_SCHEMA, "protocol": SC.PROTOCOL, "engine": SC.ENGINE,
                   "candidate_set": args["candidate_set"],
                   "structure": {"handle": selected["structure"]["handle"],
                                 "model_number": selected["structure"]["model_number"]},
                   "ligand": dict(selected["ligand"]), "box": copy.deepcopy(box),
                   "parameters": {**args["parameters"], "cpu": C.CPU}, "selection_policy": args["selection_policy"],
                   "hydrogen_policy": args["hydrogen_policy"],
                   "method": {"model": pins["model_method"], "docking": pins["docking"]}, "pins": pins["modules"],
                   "call_key": GI.call_key(selected, pins), "conditions_sha256": GI.conditions_sha256(selected, pins),
                   "selection_sha256": selected["selection_sha256"], "ga": args["ga"], "space": selected["space"],
                   "status": status, "stop_reason": stop_reason, **counts,
                   "reserved_evaluations": GI.reserved_evaluations(args["ga"]),
                   "reserved_units": GI.reserved_units(args["ga"]), "reference": row, "generations": generations,
                   "limitations": limitations(status, counts["reused_count"])}
        validated_summary(content, selected=selected, candidate_set=candidate_set, results=results, models=models,
                          pins=pins)
        return content
    except SequenceGaEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise SequenceGaEvidenceError("GA observations are invalid") from exc


# ----------------------------------------------------------------- relations (pure)
def crossover_relation(first: tuple[int, ...], second: tuple[int, ...], child: tuple[int, ...]) -> bool:
    """A crossover child is non-empty and inside the union of its two distinct parents (spec 4)."""
    return first != second and bool(child) and set(child) <= set(first) | set(second)


def edit_relation(operation: str, parent: tuple[int, ...], child: tuple[int, ...], position: Mapping[int, int]) -> bool:
    """``add``: parent inside child, one more; ``remove``: child inside parent, one fewer; ``change``: one candidate
    differs on the same positions; ``move``: same size, one candidate differs and its position is another (spec 4)."""
    p, c = set(parent), set(child)
    if operation == "add":
        return p < c and len(c) == len(p) + 1
    if operation == "remove":
        return c < p and len(c) == len(p) - 1
    one_differs = len(c) == len(p) and len(c & p) == len(p) - 1
    same_positions = {position[i] for i in c} == {position[i] for i in p}
    if operation == "change":
        return one_differs and same_positions
    if operation == "move":
        return one_differs and not same_positions
    return False


def _order(entry: dict[str, Any]) -> tuple:
    """Spec 3 score order: lower score first, then fewer mutations, then earlier ``pick_index``."""
    return (entry["score"], len(entry["mutations"]), entry["pick_index"])


def _slot_counts(ga: dict[str, Any], carried: int) -> dict[str, int]:
    slots = ga["population_size"] - carried
    r = math.floor(ga["random_fraction"] * slots + 0.5)
    c = math.floor(ga["crossover_fraction"] * (slots - r) + 0.5)
    return {"slots": slots, "crossover": c, "edit": slots - r - c, "random": r}


def _check_box(box: Any, request: dict[str, Any]) -> None:
    _require(type(box) is dict and set(box) == {"center_A", "size_A", "source", "margin_A"} and
             box["source"] == request["source"] and
             all(type(box[key]) is list and len(box[key]) == 3 and all(_float(x) for x in box[key])
                 for key in ("center_A", "size_A")) and
             all(0 < x <= C.BOX_SIDE_MAX_A for x in box["size_A"]), "box")
    if request["source"] == "manual":
        _require(box["center_A"] == request["center_A"] and box["size_A"] == request["size_A"] and
                 box["margin_A"] is None, "box: a manual box is the request")
    else:
        _require(box["margin_A"] == request["margin_A"], "box: range box margin")


def _check_result(result: Any, content: dict[str, Any], args: dict[str, Any], model_handle: str,
                  model: dict[str, Any], side: str) -> None:
    """The stored result is this model side's own standalone M18 free request under the GA's ligand, box, values."""
    individual = GI.individual_arguments(args, model_handle, side)
    receptor = {"source": {"kind": "mutation_model", "mutation_model": model_handle, "side": side},
                "sha256": model["structures"][side]["structure_sha256"],
                "model_number": model["structure"]["model_number"],
                "connectivity": {"kind": C.MUTATION_MODEL_CONNECTIVITY}, "removed_instance": None,
                "acknowledgement": args["acknowledgement"]}
    ligand = result["inputs"]["ligand"]
    engine = result["engine"]
    docking = content["method"]["docking"]
    _require(result["schema"] == C.RESULT_SCHEMA and result["protocol"] == C.PROTOCOL and
             result["method"] == C.METHODS[SC.MODE] and
             result["input_sha256"] == docking_inputs.input_sha256(individual) and
             result["inputs"]["receptor"] == receptor and result["inputs"]["mode"] == SC.MODE and
             ligand["source"] == "sdf" and ligand["sdf_handle"] == content["ligand"]["sdf_handle"] and
             ligand["sdf_sha256"] == content["ligand"]["sdf_sha256"] and result["box"] == content["box"] and
             result["parameters"] == content["parameters"] and result["preparation"] == PREPARATION and
             type(engine) is dict and engine.get("name") == C.ENGINE and
             engine.get("binary_sha256") == docking["qvina_sha256"] and engine.get("package") == docking["qvina_package"]
             and type(result["modes"]) is list, "result: the individual's own M18 request on its model")


def _check_model(model: Any, content: dict[str, Any], rows: list[dict[str, Any]],
                 reference_model: dict[str, Any] | None) -> None:
    """A stored set model of this run conditions whose mutations are ``rows``; a mutant's reference figures are
    recomputed against the reference row's model."""
    side = SM.side(rows)
    _require(type(model) is dict and model.get("schema") == SC.MODEL_SCHEMA and
             type(model.get("structures")) is dict and set(model["structures"]) == {side}, "model side")
    _require(model["candidate_set"] == content["candidate_set"] and
             model["structure"] == {**content["structure"], "structure_kind": MK.STRUCTURE_KIND} and
             model["seed"] == content["parameters"]["seed"] and model["method"] == content["method"]["model"],
             "model: candidate set, structure, seed and method")
    _require(model["mutations"] == [{**row, "mutant_resname": MK.THREE_LETTER[row["to"]]} for row in rows],
             "model mutations")
    if not rows:
        _require(model["reference_structure_sha256"] is None, "model: reference row")
        return
    _require(reference_model is not None, "model: a reference row model")
    entry, reference_entry = model["structures"][side], reference_model["structures"][SC.REFERENCE_SIDE]
    mutations = model["mutations"]
    _require(model["reference_structure_sha256"] == reference_entry["structure_sha256"] and
             canonical_json(model["protonation_differences"]) ==
             canonical_json(SM.protonation_differences(entry, reference_entry, mutations)) and
             model["new_disulfide_in_mutant"] is SM.new_disulfide(entry, reference_entry, mutations),
             "model: reference structure, protonation differences and new disulfide")


def _check_row(entry: dict[str, Any], rows: list[dict[str, Any]], content: dict[str, Any], args: dict[str, Any],
               results: Mapping[str, Any], models: Mapping[str, Any], reference_model: dict[str, Any] | None,
               reasons: dict[str, tuple]) -> None:
    """State, reason, score and handles of one evaluated individual or the reference row."""
    state, model_handle, result_handle = entry["state"], entry["model_handle"], entry["result_handle"]
    _require(state in SC.STATES and entry["reason_code"] in reasons[state], "state and reason")
    _require(model_handle is None or (model_handle in models), "model handle")
    if model_handle is not None:
        _check_model(models[model_handle], content, rows, reference_model)
    if state == "failed":
        _require(result_handle is None and entry["score"] is None, "score: a failed row has no result or score")
        return
    _require(model_handle is not None and result_handle in results, "a scored or null row has a model and a result")
    result = results[result_handle]
    _check_result(result, content, args, model_handle, models[model_handle], SM.side(rows))
    _require(_result_state(result) == state, "state is the stored result's")
    score = _first_score(result)
    _require((state == "null_result" or _float(score)) and entry["score"] == score and
             type(entry["score"]) is type(score), "score is the stored result's first mode")


def _check_reference(content: dict[str, Any], args: dict[str, Any], results: Mapping[str, Any],
                     models: Mapping[str, Any]) -> dict[str, Any] | None:
    row = content["reference"]
    _require(type(row) is dict and set(row) == REFERENCE_KEYS, "reference keys")
    _require(row["evaluation"] in SC.EVALUATIONS and (row["evaluation"] != "reused" or row["state"] != "failed"),
             "reference evaluation")
    _check_row(row, [], content, args, results, models, None, REASONS_BY_STATE)
    return None if row["model_handle"] is None else models[row["model_handle"]]


def _check_generations(content: dict[str, Any], args: dict[str, Any], space: dict[str, Any],
                       candidate_set: dict[str, Any], results: Mapping[str, Any], models: Mapping[str, Any],
                       reference_model: dict[str, Any] | None) -> dict[str, Any]:
    ga = args["ga"]
    position = {index: p for p, alts in zip(space["positions"], space["alts"], strict=True) for index in alts}
    generations = content["generations"]
    _require(type(generations) is list and len(generations) <= ga["generations"], "generations")
    seen: list[str] = []
    next_pick = next_eval = failures = 0
    fifth: tuple[int, int] | None = None
    exhausted_at: int | None = None
    for number, gen in enumerate(generations, start=1):
        _require(type(gen) is dict and set(gen) == GENERATION_KEYS and gen["index"] == number and
                 type(gen["complete"]) is bool and type(gen["individuals"]) is list, "generation keys")
        individuals = gen["individuals"]
        _require(len(individuals) <= ga["population_size"], "generation size")
        for entry in individuals:
            _require(type(entry) is dict and set(entry) == INDIVIDUAL_KEYS, "individual keys")
        previous = generations[number - 2]["individuals"] if number > 1 else []
        pool = [e for e in previous if e["state"] == "scored"]
        pool_keys = {e["key"] for e in pool}
        elite = sorted(pool, key=_order)[:ga["elite_count"]] if number > 1 else []
        carried = [e for e in individuals if e["origin"] == "carried"]
        _require(individuals[:len(carried)] == carried, "carried individuals come first")
        _require(len(carried) == len(elite) and all(c[k] == p[k] for c, p in zip(carried, elite, strict=False)
                                                    for k in CITED) and
                 all(c["parents"] is None and c["edit_op"] is None and c["evaluation"] is None and
                     c["eval_index"] is None for c in carried),
                 "carried = the previous generation's elite_count first scored individuals in score order")
        new = individuals[len(carried):]
        origins = [e["origin"] for e in new]
        if number == 1:
            _require(all(o == "initial" for o in origins), "origin: generation 1 is initial")
        else:
            slots = _slot_counts(ga, len(carried))
            _require(all(o in ("crossover", "edit", "random") for o in origins) and len(new) <= slots["slots"] and
                     origins.count("crossover") <= slots["crossover"] and
                     origins.count("crossover") + origins.count("edit") <= slots["crossover"] + slots["edit"],
                     "origin: crossover, edit and random within their slot counts")
        for slot, entry in enumerate(new):
            _require(entry["pick_index"] == next_pick, "pick_index is the run's selection order")
            next_pick += 1
            rows = GI.key_mutations(candidate_set, space, entry["key"])
            _require(entry["mutations"] == rows, "mutations are the candidate set's rows of the key")
            _require(entry["key"] not in seen, "non-carried keys are unique in the run")
            seen.append(entry["key"])
            child, origin, parents, operation = GI.parse_key(entry["key"]), entry["origin"], entry["parents"], \
                entry["edit_op"]
            if origin in ("crossover", "edit"):
                _require(type(parents) is list and all(type(p) is str for p in parents),
                         f"{origin}: parents are keys")
                _require(all(p in pool_keys for p in parents),
                         "parent keys are scored individuals of the previous generation")
            if origin == "crossover":
                _require(len(parents) == 2 and operation is None and
                         crossover_relation(GI.parse_key(parents[0]), GI.parse_key(parents[1]), child),
                         "crossover: two distinct parents whose union holds the child")
            elif origin == "edit":
                _require(len(parents) == 1 and operation in SC.EDIT_OPERATIONS and
                         edit_relation(operation, GI.parse_key(parents[0]), child, position),
                         "edit: one parent and one edit operation apart")
            else:
                _require(parents is None and operation is None, "initial / random: no parent, no edit operation")
            if entry["evaluation"] == "computed":
                _require(entry["eval_index"] == next_eval, "eval_index is the run's new-evaluation order")
                next_eval += 1
            else:
                _require(entry["evaluation"] == "reused" and entry["eval_index"] is None and
                         entry["state"] != "failed", "evaluation: a reused individual has its stored result")
            _check_row(entry, rows, content, args, results, models, reference_model, REASONS_BY_STATE)
            failures = failures + 1 if entry["state"] == "failed" else 0
            if failures == SC.CONSECUTIVE_FAILURE_LIMIT and fifth is None:
                fifth = (number, slot)
        _require(not gen["complete"] or len(individuals) == ga["population_size"] or
                 (number > 1 and len(seen) == space["size"]),
                 "a complete generation is full unless every key of the space was seen")
        scores = [e["score"] for e in individuals if e["state"] == "scored"]
        _require(gen["min_score"] == (min(scores) if scores else None) and
                 gen["max_score"] == (max(scores) if scores else None), "min_score and max_score")
        if exhausted_at is None and len(seen) == space["size"]:
            exhausted_at = number
    return {"seen": seen, "fifth": fifth, "exhausted_at": exhausted_at}


def _patience_point(generations: list[dict[str, Any]], ga: dict[str, Any]) -> int | None:
    """The generation where spec 3 step 5 ends the run with ``no_change`` (None: never). The running minimum is the
    minimum of the complete generations' ``min_score``; null -> a number is a decrease, null -> null and x -> y with
    y >= x are not; generation 1 is not compared; the last generation ends with ``generations_complete``."""
    best, still = None, 0
    for gen in generations:
        if not gen["complete"]:
            break
        low = gen["min_score"]
        new = best if low is None else (low if best is None else min(best, low))
        if gen["index"] >= 2:
            still = 0 if new is not None and (best is None or new < best) else still + 1
            if gen["index"] < ga["generations"] and still >= ga["patience"]:
                return gen["index"]
        best = new
    return None


def _check_stop(content: dict[str, Any], ga: dict[str, Any], space: dict[str, Any], walk: dict[str, Any]) -> None:
    stop, generations = content["stop_reason"], content["generations"]
    count, complete = len(generations), all(g["complete"] for g in generations)
    _require(all(g["complete"] for g in generations[:-1]), "only the last generation can be incomplete")
    _require(content["status"] == "partial" or (count >= 1 and complete), "a complete run has only complete "
                                                                          "generations")
    _require((content["reference"]["state"] == "failed") == (stop == "reference_failed"),
             "reference_failed is a failed reference row")
    if stop == "reference_failed":
        _require(generations == [], "reference_failed: no generation")
    exhausted = len(walk["seen"]) == space["size"]
    # the worker's own terminal points after a complete generation: the last generation, every key seen, patience
    terminal = None
    if count and complete:
        if count == ga["generations"]:
            terminal = "generations_complete"
        elif exhausted:
            terminal = "space_exhausted"
        elif _patience_point(generations, ga) == count:
            terminal = "no_change"
    _require(_patience_point(generations, ga) in (None, count), "no generation after the no_change point")
    _require(walk["exhausted_at"] in (None, count), "no generation after every key of the space was seen")
    if stop in ("generations_complete", "space_exhausted", "no_change"):
        _require(terminal == stop, f"{stop}: the run ended at that point")
    elif terminal is not None:
        _require(stop in OUTSIDE_STOPS, "a stop after a terminal point of the worker")
    if stop == "evaluation_limit":
        _require(count >= 1 and not generations[-1]["complete"] and
                 content["new_evaluations_used"] == content["reserved_evaluations"],
                 "evaluation_limit: reserved_evaluations reached in an incomplete last generation")
    evaluated = [(number, slot) for number, gen in enumerate(generations, start=1)
                 for slot, _entry in enumerate(e for e in gen["individuals"] if e["origin"] != "carried")]
    fifth = walk["fifth"]
    _require(fifth is None or fifth == evaluated[-1], "five consecutive failures end the run there")
    if stop == "repeated_failure":
        _require(fifth is not None and not generations[-1]["complete"],
                 "repeated_failure: five consecutive failures end an incomplete last generation")
    elif fifth is not None:
        _require(stop in OUTSIDE_STOPS, "five consecutive failures end the run there")


def _check(content: Any, selected: dict[str, Any], candidate_set: dict[str, Any], results: Mapping[str, Any],
           models: Mapping[str, Any], pins: dict[str, Any]) -> None:
    _require(type(content) is dict and set(content) == SUMMARY_KEYS and content["schema"] == SC.SUMMARY_SCHEMA and
             content["protocol"] == SC.PROTOCOL and content["engine"] == SC.ENGINE, "summary keys")
    GI.check_pins(pins)
    space = _check_selection(selected, candidate_set)
    args = selected["arguments"]
    ga = args["ga"]
    _require(content["candidate_set"] == args["candidate_set"] and
             content["structure"] == {"handle": selected["structure"]["handle"],
                                      "model_number": selected["structure"]["model_number"]} and
             content["ligand"] == selected["ligand"] and
             content["parameters"] == {**args["parameters"], "cpu": C.CPU} and
             content["selection_policy"] == args["selection_policy"] == SC.SELECTION_POLICY and
             content["hydrogen_policy"] == args["hydrogen_policy"] == SC.HYDROGEN_POLICY and
             content["ga"] == ga and content["space"] == selected["space"], "summary inputs are the selection's")
    _require(content["method"] == {"model": pins["model_method"], "docking": pins["docking"]} and
             content["pins"] == pins["modules"], "method and pins are the job's")
    _require(content["selection_sha256"] == selected["selection_sha256"] and
             content["call_key"] == GI.call_key(selected, pins) and
             content["conditions_sha256"] == GI.conditions_sha256(selected, pins),
             "selection hash, call key and conditions")
    _check_box(content["box"], args["box"])
    reserved = GI.reserved_evaluations(ga)
    _require(content["reserved_evaluations"] == reserved and
             content["reserved_units"] == GI.reserved_units(ga) == SC.UNITS_PER_EVALUATION * (reserved + 1),
             "reserved figures")
    _require(content["status"] in SC.STATUSES and content["stop_reason"] in SC.STOP_REASONS and
             content["status"] == SC.STATUS_BY_STOP_REASON[content["stop_reason"]], "status and stop reason")
    reference_model = _check_reference(content, args, results, models)
    walk = _check_generations(content, args, space, candidate_set, results, models, reference_model)
    counts = _counts(content["generations"])
    _require(all(type(content[key]) is int and content[key] == value for key, value in counts.items()),
             "counts")
    _require(content["new_evaluations_used"] <= content["reserved_evaluations"],
             "new evaluations within reserved_evaluations")
    _check_stop(content, ga, space, walk)
    _require(content["limitations"] == limitations(content["status"], content["reused_count"]), "limitations")
    _require(len(canonical_json(content)) <= SC.MAX_SUMMARY_BYTES, "summary size")


def validated_summary(content: Any, *, selected: dict[str, Any], candidate_set: dict[str, Any],
                      results: Mapping[str, Any], models: Mapping[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    """Return ``content`` if it validates against the job's selection record and pins, the validated M20 candidate
    set, the validated per-row docking results and set models (by handle, the reference row's model included);
    else ``SequenceGaEvidenceError``."""
    try:
        _check(content, selected, candidate_set, results, models, pins)
        return content
    except SequenceGaEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise SequenceGaEvidenceError("GA summary evidence is invalid") from exc
