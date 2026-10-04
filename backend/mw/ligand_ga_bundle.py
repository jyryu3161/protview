"""M22 GA summary ``ligand_ga_result@1``: individuals from the worker's generation records and the server's
per-individual observations, validation and re-validation, call key (spec .dryforge/spec.md 3, 4, 6, 7).

Pure server functions: no RDKit, no Meeko, no store writes, no events. The caller (T4) reads the staging files
(``generations/<g>.json``, ``individuals/<k>.status.json``, ``individuals/<k>.result.json``), publishes every
verifiable new docking with the M18 checks, resolves the stop reason (the worker's ``cancelled`` re-read with the
server's stop cause) and passes here:

- ``records``: the worker generation records ``{index, complete, individuals: [{candidate_id, origin,
  parent_candidate_id, similarity, evaluation, eval_index}]}`` in order;
- ``observations``: ``eval_index -> {"status": {"state", "reason_code"} | None, "result_handle": str | None}`` for
  every non-carried individual (``result_handle`` = the published or reused ``docking_result@1``);
- ``results``: the validated M18 results by handle; ``individual_selections``: candidate id ->
  ``docking_selection@1`` of every non-carried individual (``ligand_ga_inputs.individual_selection``).

Individual rules: a result handle makes the individual ``scored`` (modes >= 1) or ``null_result``; else a status
gives the state (a ``scored``/``null_result`` status whose result could not be published is ``failed``
``engine_output_invalid``, the M18 reason for an output the server refuses); else ``failed`` ``worker_failed``.
Scores and states are never taken from the worker's records. A ``carried`` individual cites the previous
generation's entry with the same id (score, result handle, state).

Checked rules (``check_summary``, on build and on every read): exact keys at every level (so no rank, difference,
best or improved field can exist), every individual an eligible pool candidate, non-carried ids unique in the run,
generation size <= ``population_size`` (a complete generation 1 = ``population_size``), order carried -> similar ->
random (generation 1: initial only), carried = the previous generation's ``elite_count`` lowest-score scored
individuals (ties in pool order; fewer when fewer are scored), ``eval_index`` = 0, 1, ... in listing order,
score = the stored result's first mode, result = the individual's own M18 input under the GA's shared settings,
``min_score``/``max_score``, counts, ``new_dockings_used <= max_new_dockings``, ``reserved_units`` (spec 6), status
= ``STATUS_BY_STOP_REASON`` and its structure (only the last generation of a partial run may be incomplete;
``generations_complete`` = every generation; ``docking_limit`` = cap reached with a generation left; ``no_change``
after at least ``patience`` generations past generation 1), G sentences, pins, hashes, size.
``parent_candidate_id`` and ``similarity`` are worker records the server cannot recompute (no fingerprints here,
G1): only their shape is checked.

Readings of the spec that the summary rules rely on (confirmed against spec 3 and 4 in T2, oracle A1-A3):
A1 generation order = carried (elite order) then new individuals in evaluation order (spec 3: tournament list
"carried first, then evaluation order"); A2 non-carried ids unique in the whole run (spec 4); A3 a stopped
generation lists its carried individuals and the evaluated ones only (spec 3). A4-A7 concern the worker's procedure
and are not encoded here.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import docking_constants as C
from . import docking_inputs, ligand_ga_inputs
from . import ligand_ga_constants as GC
from .core.events import idempotency_key
from .core.handles import canonical_json
from .docking_batch_bundle import PREPARATION, _check_box

SUMMARY_KEYS = frozenset({"schema", "protocol", "engine", "candidate_set_handle", "parent_sdf_handle", "receptor",
                          "pins", "call_key", "selection_sha256", "box", "parameters", "filter", "ga", "pool",
                          "status", "stop_reason", "generations_done", "new_dockings_used", "reused_count",
                          "reserved_units", "generations", "limitations"})
GENERATION_KEYS = frozenset({"index", "complete", "individuals", "min_score", "max_score"})
RECORD_KEYS = frozenset({"candidate_id", "origin", "parent_candidate_id", "similarity", "evaluation", "eval_index"})
INDIVIDUAL_KEYS = RECORD_KEYS | {"state", "reason_code", "score", "result_handle"}
OBSERVATION_KEYS = frozenset({"status", "result_handle"})
STATUS_KEYS = frozenset({"state", "reason_code"})
GA_PIN_KEYS = ("ga_worker_sha256", "ga_constants_sha256")
M18_PIN_KEYS = ("worker_sha256", "constants_sha256", "qvina_sha256", "qvina_package")
REASONS_BY_STATE = {"scored": (None,), "null_result": (None,), "failed": C.REASONS + GC.FAILED_EXTRA_REASONS}
ORIGIN_RANK = {"carried": 0, "similar": 1, "random": 2}
SIMILARITY_RE = re.compile(r"(0\.[0-9]{6}|1\.000000)")
SHA_RE = re.compile(r"[0-9a-f]{64}")


class LigandGaEvidenceError(ValueError):
    """A GA summary or its observations do not validate against the GA selection and per-individual results."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise LigandGaEvidenceError(message)


def _float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


# ----------------------------------------------------------------- call key and pins (spec 6)
def summary_pins(m18_pins: Mapping[str, Any], ga_pins: Mapping[str, Any]) -> dict[str, Any]:
    """The version pins a summary records: GA worker and constants, M18 row worker and constants, qvina."""
    return {**{key: ga_pins[key] for key in GA_PIN_KEYS}, **{key: m18_pins[key] for key in M18_PIN_KEYS}}


def call_key(selected: dict[str, Any], m18_pins: dict[str, Any], ga_pins: dict[str, Any]) -> str:
    """The GA call key: the selection hash and every pin (same request and environment = same key; the reuse set
    is not part of it, spec 6)."""
    _require(set(ga_pins) == set(GA_PIN_KEYS), "GA pins")
    return idempotency_key(GC.PROTOCOL, GC.IMPLEMENTATION,
                           {"input": ligand_ga_inputs.selection_sha256(selected), "method": dict(m18_pins),
                            "ga_method": dict(ga_pins)})


def complete_duplicate(summaries: Iterable[tuple[str, dict[str, Any]]], key: str) -> str | None:
    """The handle of a validated ``complete`` summary with this call key; a ``partial`` one never deduplicates."""
    return next((handle for handle, content in summaries
                 if content["call_key"] == key and content["status"] == "complete"), None)


# ----------------------------------------------------------------- individuals from observations
def _check_status(status: Any) -> None:
    _require(type(status) is dict and set(status) == STATUS_KEYS and status["state"] in GC.STATES and
             status["reason_code"] in REASONS_BY_STATE[status["state"]], "individual status file")


def _result_state(result: dict[str, Any]) -> str:
    return "scored" if len(result["modes"]) >= 1 else "null_result"


def _first_score(result: dict[str, Any] | None, state: str) -> Any:
    return result["modes"][0]["score_kcal_mol"] if state == "scored" else None


def _observed(obs: Any, results: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(obs) is dict and set(obs) == OBSERVATION_KEYS and
             (obs["result_handle"] is None or type(obs["result_handle"]) is str), "individual observation")
    handle, status = obs["result_handle"], obs["status"]
    if status is not None:
        _check_status(status)
    if handle is not None:
        _require(handle in results, "result of the individual")
        state = _result_state(results[handle])
        _require(status is None or status == {"state": state, "reason_code": None}, "status agrees with result")
        return {"state": state, "reason_code": None, "score": _first_score(results[handle], state),
                "result_handle": handle}
    if status is not None:
        if status["state"] in ("scored", "null_result"):
            return {"state": "failed", "reason_code": "engine_output_invalid", "score": None, "result_handle": None}
        return {"state": "failed", "reason_code": status["reason_code"], "score": None, "result_handle": None}
    return {"state": "failed", "reason_code": "worker_failed", "score": None, "result_handle": None}


def _generations(records: Any, observations: Mapping[int, Any], results: Mapping[str, Any]) -> list[dict[str, Any]]:
    _require(type(records) is list, "generation records")
    out: list[dict[str, Any]] = []
    for record in records:
        _require(type(record) is dict and set(record) == {"index", "complete", "individuals"} and
                 type(record["individuals"]) is list, "generation record")
        previous = {e["candidate_id"]: e for e in out[-1]["individuals"]} if out else {}
        individuals = []
        for entry in record["individuals"]:
            _require(type(entry) is dict and set(entry) == RECORD_KEYS, "generation record entry")
            if entry["origin"] == "carried":
                source = previous.get(entry["candidate_id"])
                _require(source is not None, "a carried individual is in the previous generation")
                derived = {key: source[key] for key in ("state", "reason_code", "score", "result_handle")}
            else:
                _require(type(entry["eval_index"]) is int and entry["eval_index"] in observations,
                         "an observation per evaluated individual")
                derived = _observed(observations[entry["eval_index"]], results)
            individuals.append({**entry, **derived})
        scores = [e["score"] for e in individuals if e["state"] == "scored"]
        out.append({"index": record["index"], "complete": record["complete"], "individuals": individuals,
                    "min_score": min(scores) if scores else None, "max_score": max(scores) if scores else None})
    return out


# ----------------------------------------------------------------- summary
def _receptor(selected: dict[str, Any]) -> dict[str, Any]:
    """The receptor summary (the key list of ``docking_batch_bundle._inputs``'s receptor)."""
    args = selected["arguments"]
    return {"handle": args["receptor_handle"], "sha256": selected["receptor"]["sha256"],
            "model_number": args["receptor_model_number"], "connectivity": args["connectivity"],
            "removed_instance": selected["receptor"]["removed_instance"],
            "acknowledgement": args["acknowledgement"]}


def _limitations(status: str, reused: int) -> list[str]:
    return ["G1"] + ["G2"] * (status == "partial") + ["G3"] * (reused > 0)


def _counts(generations: list[dict[str, Any]]) -> dict[str, int]:
    evaluated = [e for g in generations for e in g["individuals"] if e["origin"] != "carried"]
    return {"generations_done": sum(g["complete"] is True for g in generations),
            "new_dockings_used": sum(e["evaluation"] == "docked" for e in evaluated),
            "reused_count": sum(e["evaluation"] == "reused" for e in evaluated)}


def build_summary(selected: dict[str, Any], *, records: Any, observations: Mapping[int, Any],
                  results: Mapping[str, Any], individual_selections: Mapping[str, Any], stop_reason: Any,
                  box: dict[str, Any], m18_pins: dict[str, Any], ga_pins: dict[str, Any]) -> dict[str, Any]:
    """The ``ligand_ga_result@1`` content (no time, reuse set or job identity), checked before it is returned."""
    try:
        _require(stop_reason in GC.STOP_REASONS, "stop reason")
        generations = _generations(records, observations, results)
        args = selected["arguments"]
        status = GC.STATUS_BY_STOP_REASON[stop_reason]
        counts = _counts(generations)
        content = {"schema": GC.SUMMARY_SCHEMA, "protocol": GC.PROTOCOL, "engine": GC.ENGINE,
                   "candidate_set_handle": args["candidate_set_handle"],
                   "parent_sdf_handle": args["parent_sdf_handle"], "receptor": _receptor(selected),
                   "pins": summary_pins(m18_pins, ga_pins), "call_key": call_key(selected, m18_pins, ga_pins),
                   "selection_sha256": selected["selection_sha256"], "box": box,
                   "parameters": {**args["parameters"], "cpu": C.CPU}, "filter": args["filter"], "ga": args["ga"],
                   "pool": ligand_ga_inputs.pool_counts(selected["pool"]), "status": status,
                   "stop_reason": stop_reason, **counts,
                   "reserved_units": ligand_ga_inputs.reserved_units(args["ga"]), "generations": generations,
                   "limitations": _limitations(status, counts["reused_count"])}
        _check(content, selected, individual_selections, results, m18_pins, ga_pins)
        return content
    except LigandGaEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise LigandGaEvidenceError("GA observations are invalid") from exc


# ----------------------------------------------------------------- validation
def _check_selection(selected: dict[str, Any], individual_selections: Mapping[str, Any]) -> None:
    args = selected["arguments"]
    _require(selected["schema"] == GC.SELECTION_SCHEMA and
             selected["pool_sha256"] == ligand_ga_inputs.pool_sha256(selected["pool"]) and
             selected["selection_sha256"] == ligand_ga_inputs.selection_sha256(selected) and
             [item["index"] for item in selected["pool"]] == list(range(len(selected["pool"]))) and
             len(selected["pool"]) <= GC.MAX_POOL, "GA selection")
    for cid, sel in individual_selections.items():
        row_args = ligand_ga_inputs.row_arguments(args, cid)
        _require(sel["schema"] == "docking_selection@1" and sel["arguments"] == row_args and
                 sel["input_sha256"] == docking_inputs.input_sha256(row_args) and sel["receptor"] == selected["receptor"] and
                 sel["sidecar"] == selected["sidecar"] and sel["ligand"]["candidate"]["id"] == cid and
                 sel["ligand"]["parent_sdf"] == selected["parent_sdf"], "individual selection")


def _check_result(result: Any, sel: dict[str, Any], content: dict[str, Any]) -> None:
    """The stored result is this individual's own M18 free input under the GA's shared settings."""
    ligand = result["inputs"]["ligand"]
    engine = result["engine"]
    pins = content["pins"]
    _require(result["schema"] == C.RESULT_SCHEMA and result["method"] == C.METHODS[GC.MODE] and
             result["input_sha256"] == sel["input_sha256"] and result["inputs"]["mode"] == GC.MODE and
             result["inputs"]["receptor"] == content["receptor"] and ligand["source"] == "candidate" and
             ligand["candidate_id"] == sel["ligand"]["candidate"]["id"] and result["box"] == content["box"] and
             result["parameters"] == content["parameters"] and result["preparation"] == PREPARATION and
             type(engine) is dict and engine.get("name") == C.ENGINE and
             engine.get("binary_sha256") == pins["qvina_sha256"] and engine.get("package") == pins["qvina_package"],
             "per-individual result inputs")


def _check_individual(entry: Any, generation: int, results: Mapping[str, Any],
                      individual_selections: Mapping[str, Any], content: dict[str, Any]) -> None:
    _require(type(entry) is dict and set(entry) == INDIVIDUAL_KEYS and type(entry["candidate_id"]) is str,
             "individual keys")
    origin = entry["origin"]
    _require(origin == "initial" if generation == 1 else origin in ORIGIN_RANK, "origin")
    if origin == "similar":
        _require(type(entry["parent_candidate_id"]) is str and entry["parent_candidate_id"] and
                 type(entry["similarity"]) is str and SIMILARITY_RE.fullmatch(entry["similarity"]),
                 "similar slot records a parent and a 6-decimal similarity")
    else:
        _require(entry["parent_candidate_id"] is None and entry["similarity"] is None, "no parent outside similar")
    state = entry["state"]
    _require(state in GC.STATES and entry["reason_code"] in REASONS_BY_STATE[state], "state and reason")
    if origin == "carried":
        _require(entry["evaluation"] is None and entry["eval_index"] is None and state == "scored",
                 "a carried individual is a scored earlier evaluation")
    else:
        _require(entry["evaluation"] in GC.EVALUATIONS and type(entry["eval_index"]) is int, "evaluation")
        _require(entry["evaluation"] != "reused" or state != "failed", "a reused individual has a stored result")
    handle = entry["result_handle"]
    if state == "failed":
        _require(handle is None and entry["score"] is None, "a failed individual has no result or score")
        return
    _require(type(handle) is str and handle in results, "individual result handle")
    result = results[handle]
    _require(entry["candidate_id"] in individual_selections, "individual selection")
    _check_result(result, individual_selections[entry["candidate_id"]], content)
    _require(_result_state(result) == state, "state is the result's")
    score = _first_score(result, state)
    _require((state == "null_result" or _float(score)) and entry["score"] == score and
             type(entry["score"]) is type(score), "score is the stored first mode, copied")


def _check_generations(content: dict[str, Any], selected: dict[str, Any], results: Mapping[str, Any],
                       individual_selections: Mapping[str, Any]) -> None:
    ga = selected["arguments"]["ga"]
    order = {item["candidate_id"]: item["index"] for item in selected["pool"]}
    eligible = set(ligand_ga_inputs.eligible_ids(selected))
    generations = content["generations"]
    _require(type(generations) is list and len(generations) <= ga["generations"], "generations")
    seen: list[str] = []
    next_eval = 0
    for number, gen in enumerate(generations, start=1):
        _require(type(gen) is dict and set(gen) == GENERATION_KEYS and gen["index"] == number and
                 type(gen["complete"]) is bool and type(gen["individuals"]) is list, "generation keys")
        last = number == len(generations)
        _require(gen["complete"] or (last and content["status"] == "partial"),
                 "only the last generation of a partial run can be incomplete")
        individuals = gen["individuals"]
        _require(len(individuals) <= ga["population_size"] and
                 (number > 1 or not gen["complete"] or len(individuals) == ga["population_size"]),
                 "generation size")
        ids = [e["candidate_id"] if type(e) is dict else None for e in individuals]
        _require(len(set(ids)) == len(ids), "an individual appears once in a generation")
        ranks = []
        for entry in individuals:
            _check_individual(entry, number, results, individual_selections, content)
            _require(entry["candidate_id"] in eligible, "every individual is an eligible pool candidate")
            ranks.append(ORIGIN_RANK.get(entry["origin"], 0))
            if entry["origin"] != "carried":
                _require(entry["eval_index"] == next_eval, "eval_index is the run's evaluation order")
                next_eval += 1
                seen.append(entry["candidate_id"])
        _require(ranks == sorted(ranks), "carried, then similar, then random")
        _require(not gen["complete"] or len(individuals) == ga["population_size"] or set(seen) == eligible,
                 "a complete generation is full unless every eligible candidate was picked (spec 3e)")
        if number > 1:
            prior = [e for e in generations[number - 2]["individuals"] if e["state"] == "scored"]
            elite = sorted(prior, key=lambda e: (e["score"], order[e["candidate_id"]]))[:ga["elite_count"]]
            carried = [e for e in individuals if e["origin"] == "carried"]
            _require([e["candidate_id"] for e in carried] == [e["candidate_id"] for e in elite] and
                     all(c["score"] == p["score"] and c["result_handle"] == p["result_handle"]
                         for c, p in zip(carried, elite, strict=True)),
                     "carried = the previous generation's lowest-score elites, ties in pool order")
        scores = [e["score"] for e in individuals if e["state"] == "scored"]
        _require(gen["min_score"] == (min(scores) if scores else None) and
                 gen["max_score"] == (max(scores) if scores else None), "min_score and max_score")
    _require(len(set(seen)) == len(seen), "non-carried candidate ids are unique in the run")
    _require(set(individual_selections) == set(seen), "one selection per evaluated individual")


def _check_stop(content: dict[str, Any], ga: dict[str, Any]) -> None:
    stop = content["stop_reason"]
    _require(stop in GC.STOP_REASONS and content["status"] == GC.STATUS_BY_STOP_REASON[stop], "status and stop")
    done, generations = content["generations_done"], content["generations"]
    _require(content["status"] == "partial" or (generations and all(g["complete"] for g in generations)),
             "a complete run has only complete generations")
    if stop == "generations_complete":
        _require(done == ga["generations"], "generations_complete ran every generation")
    if stop == "docking_limit":
        _require(content["new_dockings_used"] == ga["max_new_dockings"] and done < ga["generations"],
                 "docking_limit: the cap was reached with a generation left")
    if stop == "no_change":
        _require(done >= ga["patience"] + 1, "no_change needs patience generations after generation 1")


def _check(content: Any, selected: dict[str, Any], individual_selections: Mapping[str, Any],
           results: Mapping[str, Any], m18_pins: dict[str, Any], ga_pins: dict[str, Any]) -> None:
    _require(type(content) is dict and set(content) == SUMMARY_KEYS and content["schema"] == GC.SUMMARY_SCHEMA and
             content["protocol"] == GC.PROTOCOL and content["engine"] == GC.ENGINE, "summary keys")
    _check_selection(selected, individual_selections)
    args = selected["arguments"]
    ga = args["ga"]
    _require(content["candidate_set_handle"] == args["candidate_set_handle"] and
             content["parent_sdf_handle"] == args["parent_sdf_handle"], "input handles")
    _require(content["receptor"] == _receptor(selected), "receptor")
    _require(content["pins"] == summary_pins(m18_pins, ga_pins) and
             all(type(content["pins"][key]) is str and SHA_RE.fullmatch(content["pins"][key])
                 for key in (*GA_PIN_KEYS, "worker_sha256", "constants_sha256", "qvina_sha256")), "pins")
    _require(content["selection_sha256"] == selected["selection_sha256"] and
             content["call_key"] == call_key(selected, m18_pins, ga_pins), "selection hash and call key")
    _check_box(content["box"], args["box"])
    _require(content["parameters"] == {**args["parameters"], "cpu": C.CPU} and content["filter"] == args["filter"]
             and content["ga"] == ga, "parameters, filter and ga")
    _require(content["pool"] == ligand_ga_inputs.pool_counts(selected["pool"]), "pool counts")
    _require(content["reserved_units"] == ligand_ga_inputs.reserved_units(ga), "reserved_units")
    _require(content["status"] in GC.STATUSES, "status")
    _check_generations(content, selected, results, individual_selections)
    counts = _counts(content["generations"])
    _require(all(content[key] == value and type(content[key]) is int for key, value in counts.items()), "counts")
    _require(content["new_dockings_used"] <= ga["max_new_dockings"], "new dockings within max_new_dockings")
    _check_stop(content, ga)
    _require(content["limitations"] == _limitations(content["status"], content["reused_count"]), "limitations")
    _require(len(canonical_json(content)) <= GC.MAX_SUMMARY_BYTES, "summary size")


def check_summary(content: Any, selected: dict[str, Any], individual_selections: Mapping[str, Any],
                  results: Mapping[str, Any], m18_pins: dict[str, Any], ga_pins: dict[str, Any]) -> None:
    """Validate a stored or new summary against its GA selection, the evaluated individuals' M18 selections, the
    validated per-individual results (by handle, from ``docking_bundle.validated_result``) and the GA job's pins;
    raise LigandGaEvidenceError."""
    try:
        _check(content, selected, individual_selections, results, m18_pins, ga_pins)
    except LigandGaEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise LigandGaEvidenceError("GA summary evidence is invalid") from exc
