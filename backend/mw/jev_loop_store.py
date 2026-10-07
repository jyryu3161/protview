"""M25 JEV design loop: the layer that reads a run and writes the loop events (spec .dryforge/spec.md 3.1, 3.2, 9.1,
9.2, 11).

``jev_loops`` derives the ``jev_loop@1`` record purely (no store, log, file or engine). This module is the part that
touches a run: the one-snapshot read view, the inputs ``jev_loops.derive_loop`` takes, the loop creation admission
and its one event ``jev_loop_created``, the requests and call keys of the standalone M18 / M21 jobs a loop step
submits, and the ``methods.jev_loop`` capability. It never imports the M24 send module or the gate, never reads a
credential, never submits, starts, cancels or retries a job, never calls a tool, never changes a budget and never
writes an M24 event. Routes stay thin in ``api/app.py``.

Public API
----------
    LoopReadView(run)                         one event-log snapshot: ``store``, ``run_id``, ``run_dir``,
                                              ``events.read()`` (the shape of the M24 read view in ``api/app.py``)
    LoopRequestError(reason_code, message, http_status, **detail)
                                              a loop route refusal; ``detail`` is the response ``detail`` body
                                              (``reason_code`` = the closed spec name)
    created_payload(events, loop_id)          the parsed ``jev_loop_created`` payload (``jev_loops.LoopNotFound``)
    source_content(view, branch, handle)      the stored candidate set of the pool, validated (KeyError/ValueError)
    candidate_displays(branch, content, refs) {ref: display}: ligand {smiles}, mutation {residue (7 fields), from, to}
    ligand_request / model_request / dock_request
                                              the exact standalone M18 / M21 job requests of one loop step
    ligand_call_key / model_call_key / dock_call_key, candidate_keys(created, models=None)
                                              their call keys under the pins recorded at creation
    remaining_budget(snapshot), approval_pending(events), loop_approvals(events, loop_id)
    model_index(events)                       M21 call key -> output handle of a done M21 job with that key
    load_results(view, created, approvals)    (results, models): validated stored M18 / M21 results by call key
    load_proposals(view, created)             {handle: validated jev_loop_choice@1}: empty until T5 adds the object
    derive_inputs(view, created, *, budget, send_active, send_reservation=None)
                                              the ``jev_loops.derive_loop`` keyword inputs of one loop
    validated_loop_record(record, inputs)     the spec 3.2 record check every read runs (``LoopRecordInvalid``)
    read_loop(view, loop_id, *, budget, send_active=False, send_reservation=None) -> jev_loops.LoopState
    list_loops(view, *, budget, send_active=False) -> the list rows, newest first
    normalize_setup(branch, setup, source)    the pure setup check and its normalized value
    create(run, body, *, send_active)         ``POST /runs/{rid}/jev_loops`` -> ``jev_loop@1``
    engine_unavailable(branch, docking, model), capability(docking, model, *, tool_exposed, pins_match)

Reading (spec 3.2: built and checked on every read, nothing written)
--------------------------------------------------------------------
Every read takes ONE ``LoopReadView`` (one event-log read) and hands that same view to every reader: the job fold
(``JobQueue(view).list()``), ``docking_batch_inputs.published_m18_results`` and ``model_index`` (call key -> handle),
``docking_bundle.validated_result`` / ``mutation_model_bundle.validated_result`` (a stored result that does not
validate, or whose normalized input is not the loop request of that candidate, is left out and never counts as
computed), the candidate set check. ``keys`` come from the created event's setup and pins (events only, no engine);
a protein docking key exists once that candidate's model validates. ``proposals`` come from ``load_proposals``
(empty until T5 stores ``jev_loop_choice@1``). The derived record then passes ``validated_loop_record``. Reads never
take the run lock, never write an event or object and never start, submit or cancel a job.

Creation (spec 3.1)
-------------------
Outside the run lock: ``unknown_field``, ``loop_id_invalid``. Under the run execution owner (``Run._owner``: a held
lock is the route's 503 ``busy`` and nothing is written; no runtime overhead is charged): the same ``loop_id`` answers
the existing record when the normalized request is the same and ``loop_id_conflict`` otherwise; then ``dry_run``,
``branch_invalid``, ``capability_unavailable`` (that branch's engines: the docking environment and qvina; OpenMM /
PDBFixer, then the docking environment), ``loop_active`` (an unended loop of the branch), ``pool_invalid``,
``goal_invalid``, ``seed_invalid``, ``iteration_cap_invalid``, ``setup_invalid``. First failure only; no event.

``setup_invalid`` names in ``detail.setup_reason`` the closed M18 / M21 name the server gives when the first pool
candidate's first step is submitted, and nothing stricter. Ligand: the setup shape (keys outside it or missing:
``invalid_job_arguments``), then ``docking_bundle.submission`` of ``ligand_request`` (= the M19 / M22 row request,
mode free). Protein: the setup shape, the M18 pure argument check of ``dock_request`` on a placeholder model, the
same-run ``ligand_sdf`` import of the SDF (M18 refuses it the same way at the docking step; checked here so no loop
models a candidate it can never dock), M21 ``admission`` 1-7 and ``selection`` (the M7 preflight:
``openmm_preflight_failed``) of ``model_request``. ``pins`` = {"m18": the M18 pins} (ligand) or {"m18", "m21": the
M21 pins} (protein): the values a standalone M18 / M21 job records as its ``method``.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Iterable, Mapping
from typing import Any

from . import (
    docking_batch_inputs,
    docking_bundle,
    docking_inputs,
    jev_loops,
    ligand_bundle,
    ligand_filters,
    mutation_model_bundle,
)
from . import docking_constants as DC
from . import jev_constants as J
from . import jev_loop_constants as L
from . import mutation_candidates as mc
from . import mutation_model_constants as MC
from . import mutation_model_inputs as mi
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .jobs.queue import JobQueue
from .ligand_ga_inputs import M18_KEYS

# --- closed values of this layer ---------------------------------------------------------------------------------------
CREATE_HTTP = {"unknown_field": 422, "loop_id_invalid": 422, "dry_run": 412, "branch_invalid": 422,
               "capability_unavailable": 412, "loop_active": 409, "pool_invalid": 422, "goal_invalid": 422,
               "seed_invalid": 422, "iteration_cap_invalid": 422, "setup_invalid": 422,
               L.LOOP_ID_CONFLICT: 409}
LIGAND_SETUP_KEYS = (*M18_KEYS, "parent_sdf_handle")          # M22 shared fields + the parent SDF
LIGAND_SETUP_REQUIRED = tuple(key for key in LIGAND_SETUP_KEYS if key != "acknowledgement")
PROTEIN_SETUP_KEYS = ("ligand", "box", "parameters", "selection_policy", "hydrogen_policy", "acknowledgement",
                      "contact_cutoff_A")
PROTEIN_SETUP_REQUIRED = ("ligand", "box", "parameters")
SETUP_KEYS = {"ligand": LIGAND_SETUP_KEYS, "protein": PROTEIN_SETUP_KEYS}
SETUP_REQUIRED = {"ligand": LIGAND_SETUP_REQUIRED, "protein": PROTEIN_SETUP_REQUIRED}
SETUP_REASONS = {"ligand": frozenset((*DC.REASONS, *DC.ADMISSION_ONLY_REASONS)),
                 "protein": frozenset((*DC.REASONS, *DC.ADMISSION_ONLY_REASONS, *MC.ADMISSION_REASON_CODES))}
FREE_MODE = DC.MODES[0]                                        # "free": the loop docks freely only
FREE_PARAMETERS = ("seed", "exhaustiveness", "num_modes", "energy_range")
MODEL_SOURCE_KIND = DC.RECEPTOR_SOURCE_KINDS[0]                # "mutation_model"
MUTANT_SIDE = DC.MUTATION_MODEL_SIDES[1]                       # "mutant": the loop never docks the wild type
PLACEHOLDER_CANDIDATE = "jev_loop_pool"    # shape-only stand-in for the pure setup check, never stored or submitted
PLACEHOLDER_MODEL = "jev_loop_model"       # shape-only stand-in model handle, never stored or submitted
CAPABILITY_REASONS = {
    "tool_unavailable": "투영 도구 build_jev_loop_projection이 등록·노출되어 있지 않다.",
    "missing_configuration": "과학 전송의 요청·응답 모델·provider pin이 게이트 값과 다르다.",
}
_FIRST_APPROVAL_GATE = "expensive_first_call"
_APPROVAL_EVENTS = ("approval_requested", "approval_resolved")


class LoopRequestError(Exception):
    """A loop route refusal before anything is written. ``detail`` = {"error", "reason_code", "message", ...}:
    ``error`` is ``input_invalid`` for a 422 and the reason name itself otherwise (the M24 send-route style)."""

    def __init__(self, reason_code: str, message: str, http_status: int, **detail: Any) -> None:
        super().__init__(message)
        self.reason_code, self.message, self.http_status = reason_code, message, http_status
        self.detail = {"error": "input_invalid" if http_status == 422 else reason_code, "reason_code": reason_code,
                       "message": message, **detail}


def _refusal(reason: str, message: str, **detail: Any) -> LoopRequestError:
    return LoopRequestError(reason, message, CREATE_HTTP[reason], **detail)


# --- one read snapshot ---------------------------------------------------------------------------------------------------

class LoopReadView:
    """One event-log read for one loop read or admission: ``events.read()`` returns that one list, so every reader
    that takes a run (the M17 / M18 / M21 validated reads) sees the same snapshot."""

    def __init__(self, run: Any) -> None:
        self.store, self.run_id, self.run_dir = run.store, run.run_id, run.run_dir
        self._events = list(run.events.read())
        self.events = self

    def read(self) -> list[dict[str, Any]]:
        return self._events


def _created_loops(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{loop_id: parsed created payload}, every created event checked (``LoopRecordInvalid`` otherwise)."""
    found: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") == L.EVENT_CREATED:
            payload = jev_loops.parse_created(event)
            if payload["loop_id"] in found:
                raise jev_loops.LoopRecordInvalid("a loop is created twice")
            found[payload["loop_id"]] = payload
    return found


def created_payload(events: Iterable[dict[str, Any]], loop_id: Any) -> dict[str, Any]:
    payload = _created_loops(events).get(loop_id)
    if payload is None:
        raise jev_loops.LoopNotFound(loop_id)
    return payload


def _unended(events: list[dict[str, Any]], loops: Mapping[str, Mapping[str, Any]], branch: str) -> list[str]:
    """Loops of ``branch`` that are not ended: no ``jev_loop_ended`` and no run cancel (``derive_loop``'s status)."""
    if jev_loops.run_cancel_seen(events):
        return []
    ended = {event.get("loop_id") for event in events if event.get("type") == L.EVENT_ENDED}
    return [loop_id for loop_id, payload in loops.items() if payload["branch"] == branch and loop_id not in ended]


# --- the pool's stored candidate set -------------------------------------------------------------------------------------

def source_content(view: Any, branch: str, handle: Any) -> dict[str, Any]:
    """The pool's candidate set: a published ``ligand_candidate_set@1`` (``ligand_bundle.validated_candidate_set``) or
    a stored ``mutation_candidate_set@1`` (``mutation_candidates.validated_set``) of this run, as the M24 projection
    tool checks its source. KeyError / ValueError / TypeError otherwise."""
    kind = L.KIND_FOR_BRANCH[branch]
    if type(handle) is not str:
        raise TypeError("the pool source must be a handle string")
    meta = view.store.meta(handle)
    if (meta["kind"], meta["schema"]) != (J.SOURCE_STORE_KINDS[kind], J.SOURCE_SCHEMAS[kind]):
        raise ValueError("the pool source is not this branch's candidate set kind")
    if kind == "ligand":
        return ligand_bundle.validated_candidate_set(view, handle)[0]
    return mc.validated_set(view.store.load(handle))


def candidate_displays(branch: str, content: Mapping[str, Any], refs: Iterable[Any]) -> dict[Any, dict[str, Any]]:
    """The local notation of each ref, copied from the validated stored set (the M24 proposal ``local_display`` rule):
    ligand {smiles}; mutation {residue (the 7 fields, nulls kept), from, to}."""
    if branch == "ligand":
        rows = {row["id"]: row for row in content["candidates"]}
        return {ref: {"smiles": rows[ref]["smiles"]} for ref in refs}
    rows = {row["index"]: row for row in content["candidates"]}
    positions = {item["index"]: item for item in content["positions"]}
    out = {}
    for ref in refs:
        row = rows[ref]
        residue = positions[row["position_index"]]["residue"]
        out[ref] = {"residue": {key: copy.deepcopy(residue[key]) for key in J.ALLOWED_RESIDUE},
                    "from": row["from"], "to": row["to"]}
    return out


# --- the standalone job requests of a loop step and their call keys ---------------------------------------------------

def ligand_request(setup: Mapping[str, Any], source: str, candidate_id: str) -> dict[str, Any]:
    """The standalone M18 ``qvina_dock_v1`` free request of one ligand candidate: ``docking_batch_inputs.row_request``
    on the normalized setup (the M19 row / M22 individual request)."""
    shared = copy.deepcopy({key: setup[key] for key in M18_KEYS})
    return docking_batch_inputs.row_request({**shared, "mode": FREE_MODE, "candidate_set_handle": source,
                                             "parent_sdf_handle": setup["parent_sdf_handle"]}, "candidate",
                                            candidate_id)


def model_request(setup: Mapping[str, Any], source: str, candidate_index: int) -> dict[str, Any]:
    """The standalone M21 ``openmm_mutation_model_v1`` request of one mutation candidate (seed = the docking seed)."""
    return {"candidate_set": source, "candidate_index": candidate_index, "seed": setup["parameters"]["seed"],
            "contact_cutoff_A": setup["contact_cutoff_A"], "selection_policy": setup["selection_policy"],
            "hydrogen_policy": setup["hydrogen_policy"]}


def dock_request(setup: Mapping[str, Any], model_handle: str) -> dict[str, Any]:
    """The standalone M18 free request docking the setup's SDF ligand into the mutant side of one stored model."""
    return {"receptor_source": {"kind": MODEL_SOURCE_KIND, "mutation_model": model_handle, "side": MUTANT_SIDE},
            "ligand": dict(setup["ligand"]), "mode": FREE_MODE, "box": copy.deepcopy(setup["box"]),
            "parameters": {key: setup["parameters"][key] for key in FREE_PARAMETERS},
            "acknowledgement": dict(setup["acknowledgement"])}


def ligand_call_key(setup: Mapping[str, Any], source: str, candidate_id: str, pins: Mapping[str, Any]) -> str:
    return docking_bundle.call_key(docking_inputs.validate_arguments(ligand_request(setup, source, candidate_id)),
                                   dict(pins))


def model_call_key(setup: Mapping[str, Any], source: str, candidate_index: int, pins: Mapping[str, Any]) -> str:
    return mutation_model_bundle.call_key(mi.normalize_arguments(model_request(setup, source, candidate_index)),
                                          dict(pins))


def dock_call_key(setup: Mapping[str, Any], model_handle: str, pins: Mapping[str, Any]) -> str:
    return docking_bundle.call_key(docking_inputs.validate_arguments(dock_request(setup, model_handle)), dict(pins))


def candidate_keys(created: Mapping[str, Any], models: Mapping[str, str] | None = None) -> dict[Any, dict[str, Any]]:
    """``derive_loop``'s ``keys``: {ref: {"ligand_dock": key}} or {ref: {"model": key, "dock": key | None}} under the
    pins recorded at creation (events only). ``models`` = {M21 call key: validated stored model handle}; a docking
    key exists only for a candidate whose model is in it (the docking request names the model)."""
    setup, source, pins = created["setup"], created["pool"]["source"]["handle"], created["pins"]
    models = models or {}
    keys: dict[Any, dict[str, Any]] = {}
    for ref in created["pool"]["candidates"]:
        if created["branch"] == "ligand":
            keys[ref] = {"ligand_dock": ligand_call_key(setup, source, ref, pins["m18"])}
            continue
        model_key = model_call_key(setup, source, ref, pins["m21"])
        model = models.get(model_key)
        keys[ref] = {"model": model_key, "dock": None if model is None else dock_call_key(setup, model, pins["m18"])}
    return keys


# --- derive inputs and the read --------------------------------------------------------------------------------------------

def remaining_budget(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """``derive_loop``'s ``budget`` from a run budget snapshot ({axis: {"used", "limit"}}): limit - used, unclamped."""
    return {"expensive_units": snapshot["expensive_calls"]["limit"] - snapshot["expensive_calls"]["used"],
            **{axis: snapshot[axis]["limit"] - snapshot[axis]["used"]
               for axis in ("wall_clock_s", "external_tokens", "usd")}}


def approval_pending(events: Iterable[dict[str, Any]]) -> bool:
    """The run's first expensive-call approval is requested and not resolved (the last such event is the request)."""
    last = None
    for event in events:
        if event.get("type") in _APPROVAL_EVENTS and event.get("gate") == _FIRST_APPROVAL_GATE:
            last = event["type"]
    return last == _APPROVAL_EVENTS[0]


def loop_approvals(events: Iterable[dict[str, Any]], loop_id: Any) -> list[dict[str, Any]]:
    """This loop's ``jev_loop_compute_approved`` payloads in event order, each checked."""
    return [jev_loops.parse_compute_approved(event) for event in events
            if event.get("type") == L.EVENT_COMPUTE_APPROVED and event.get("loop_id") == loop_id]


def model_index(events: Iterable[dict[str, Any]]) -> dict[str, str]:
    """M21 call key -> the output handle of the earliest done ``openmm_mutation_model_v1`` job with that key (the M21
    counterpart of ``docking_batch_inputs.published_m18_results``; the caller still validates the handle)."""
    events = list(events)
    keys = {event["job"]["job_id"]: event["job"]["call_key"] for event in events
            if event.get("type") == "job_submitted" and event["job"].get("protocol_id") == MC.PROTOCOL}
    found: dict[str, str] = {}
    for event in events:
        if (event.get("type") == "job_terminal" and event.get("status") == "done" and event.get("job_id") in keys
                and type(event.get("output_handles")) is list and len(event["output_handles"]) == 1):
            found.setdefault(keys[event["job_id"]], event["output_handles"][0])
    return found


def _docking_summary(view: Any, handle: str, request: dict[str, Any]) -> dict[str, Any] | None:
    """The derive summary of a stored M18 result that validates now and is the result of exactly ``request``."""
    try:
        content = docking_bundle.validated_result(view, handle)
        expected = docking_inputs.input_sha256(docking_inputs.validate_arguments(request))
    except (docking_bundle.DockingEvidenceError, ToolFailure):
        return None
    if content["input_sha256"] != expected:
        return None
    modes = content["modes"]
    return {"result_handle": handle, "mode_count": len(modes),
            "score_kcal_mol": modes[0]["score_kcal_mol"] if modes else None}


def _model_ok(view: Any, handle: str, created: Mapping[str, Any], ref: Any) -> bool:
    """A stored ``mutation_model@1`` that validates now and models exactly this loop's request for ``ref``."""
    setup, source = created["setup"], created["pool"]["source"]["handle"]
    try:
        content = mutation_model_bundle.validated_result(view, handle)
        expected = mi.normalize_arguments(model_request(setup, source, ref))
    except (mutation_model_bundle.MutationEvidenceError, ToolFailure):
        return False
    return (content["candidate"]["candidate_set"] == source and content["candidate"]["candidate_index"] == ref and
            _same(content["parameters"], {key: expected[key] for key in ("seed", "contact_cutoff_A",
                                                                          "selection_policy", "hydrogen_policy")}))


def load_results(view: Any, created: Mapping[str, Any],
                 approvals: Iterable[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """(``results``, ``models``) for ``derive_loop`` / ``candidate_keys`` from one view: every call key of the pool
    candidates (under the creation pins) and of this loop's approvals whose stored result is published (M18:
    ``published_m18_results``; M21: ``model_index``), validates now and is the loop request of that candidate.
    M18 summary {result_handle, mode_count, score_kcal_mol (first mode, unchanged) | None}; M21 {result_handle}.
    ``models`` = {M21 call key under the creation pins: validated model handle}."""
    events = view.read()
    branch, setup = created["branch"], created["setup"]
    source, pins, refs = created["pool"]["source"]["handle"], created["pins"], created["pool"]["candidates"]
    approvals = list(approvals)
    published = docking_batch_inputs.published_m18_results(events)
    results: dict[str, dict[str, Any]] = {}
    models: dict[str, str] = {}
    if branch == "ligand":
        wanted = [(ligand_call_key(setup, source, ref, pins["m18"]), ref) for ref in refs]
        wanted += [(item["call_key"], item["candidate_ref"]) for item in approvals]
        for key, ref in wanted:
            if key in results or key not in published:
                continue
            summary = _docking_summary(view, published[key], ligand_request(setup, source, ref))
            if summary is not None:
                results[key] = summary
        return results, models
    stored_models = model_index(events)
    model_of: dict[Any, str] = {}
    base = [(model_call_key(setup, source, ref, pins["m21"]), ref) for ref in refs]
    extra = [(item["call_key"], item["candidate_ref"]) for item in approvals if item["step"] == "model"]
    for position, (key, ref) in enumerate(base + extra):
        handle = stored_models.get(key)
        if key in results or handle is None or not _model_ok(view, handle, created, ref):
            continue
        results[key] = {"result_handle": handle}
        model_of.setdefault(ref, handle)
        if position < len(base):
            models[key] = handle
    wanted = [(dock_call_key(setup, model_of[ref], pins["m18"]), ref) for ref in refs if ref in model_of]
    wanted += [(item["call_key"], item["candidate_ref"]) for item in approvals if item["step"] == "dock"]
    for key, ref in wanted:
        if key in results or key not in published or ref not in model_of:
            continue
        summary = _docking_summary(view, published[key], dock_request(setup, model_of[ref]))
        if summary is not None:
            results[key] = summary
    return results, models


def load_proposals(view: Any, created: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """{handle: content} of this loop's stored ``jev_loop_choice@1`` proposals that validate now. T5 adds that object
    (and its ``validated_loop_choice``); until then no such object can exist and this is empty."""
    return {}


def derive_inputs(view: Any, created: Mapping[str, Any], *, budget: Mapping[str, Any], send_active: bool,
                  send_reservation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The keyword inputs of ``jev_loops.derive_loop`` for one loop from one read view (module docstring: reading).
    ``send_active`` is the caller's (``api/app.py``), ``send_reservation`` the previewed loop projection's or None."""
    events = view.read()
    branch, refs = created["branch"], created["pool"]["candidates"]
    content = source_content(view, branch, created["pool"]["source"]["handle"])
    results, models = load_results(view, created, loop_approvals(events, created["loop_id"]))
    return {"jobs": JobQueue(view).list(), "keys": candidate_keys(created, models), "results": results,
            "displays": candidate_displays(branch, content, refs), "proposals": load_proposals(view, created),
            "budget": dict(budget), "send_reservation": None if send_reservation is None else dict(send_reservation),
            "send_active": send_active, "approval_pending": approval_pending(events)}


# --- the record check every read runs (spec 3.2) -----------------------------------------------------------------

_ACTION_FOR_PHASE = {"awaiting_selection": "select", "awaiting_compute": "compute", "running": "wait_job",
                     "awaiting_docking": "dock"}
_ENDED_STATES = ("scored", "null_result", "failed", "not_run")


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise jev_loops.LoopRecordInvalid(message)


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _score_ok(state: Any, score: Any) -> bool:
    if state == "scored":
        return type(score) in (int, float) and math.isfinite(score)
    return score is None


def _check_iterations(record: Mapping[str, Any], branch: str, refs: list[Any]) -> dict[int, dict[str, Any]]:
    steps = L.BRANCH_STEPS[branch]
    rows = record["iterations"]
    _need(type(rows) is list, "iterations")
    by_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        _need(type(row) is dict and set(row) == set(jev_loops.ITERATION_KEYS), "iteration keys")
        index = row["index"]
        _need(type(index) is int and 1 <= index <= L.MAX_ITERATION_CAP and index not in by_index
              and all(index > other for other in by_index), "iteration numbers ascend")
        _need(row["phase"] in L.PHASES and row["state"] in L.ITERATION_STATES, "iteration phase / state")
        _need((row["phase"] == "done") == (row["state"] in _ENDED_STATES), "a finished iteration is done")
        _need(row["decided_by"] in (*L.DECIDED_BY, None) and row["candidate_ref"] in (*refs, None),
              "iteration decision / candidate")
        _need(_score_ok(row["state"], row["score_kcal_mol"]), "iteration score")
        _need(all(value is None or _count(value) for value in (row["list_position"], row["list_size"])),
              "list position")
        _need(all(type(row[name]) is list for name in ("approvals", "sends", "steps")), "iteration lists")
        for item in row["approvals"]:
            _need(type(item) is dict and set(item) == set(jev_loops.APPROVAL_KEYS) and item["step"] in steps
                  and item["candidate_ref"] in refs and item["decided_by"] in L.DECIDED_BY, "approval row")
        for item in row["sends"]:
            _need(type(item) is dict and set(item) == set(jev_loops.SEND_KEYS) and type(item["late"]) is bool,
                  "send row")
        for item in row["steps"]:
            _need(type(item) is dict and set(item) == set(jev_loops.STEP_KEYS) and item["step"] in steps
                  and item["candidate_ref"] in refs and item["state"] in L.STEP_STATES
                  and item["evaluation"] in (*L.EVALUATIONS, None), "step row")
        by_index[index] = row
    return by_index


def _check_candidates(record: Mapping[str, Any], inputs: Mapping[str, Any], branch: str, refs: list[Any],
                      iterations: Mapping[int, Mapping[str, Any]]) -> None:
    results, keys = inputs["results"], inputs["keys"]
    by_handle = {summary["result_handle"]: summary for summary in results.values()}
    rows = record["candidates"]
    _need(type(rows) is list and [row.get("ref") if type(row) is dict else None for row in rows] == refs,
          "candidate rows follow the pool")
    for row, item in zip(rows, record["pool"]["candidates"], strict=True):
        _need(set(row) == set(jev_loops.CANDIDATE_KEYS) and _same(row["display"], item["display"]),
              "candidate row keys / display")
        state, evaluation, score, number = row["state"], row["evaluation"], row["score_kcal_mol"], row["iteration"]
        _need(state in L.CANDIDATE_STATES and evaluation in (*L.EVALUATIONS, None) and _score_ok(state, score),
              "candidate state / score")
        if state in ("pending", "unavailable"):
            _need(evaluation is None and number is None, "an uncomputed candidate has no evaluation")
            continue
        if evaluation == "reused":
            summary = results.get(keys[row["ref"]]["ligand_dock" if branch == "ligand" else "dock"])
            _need(number is None and summary is not None and "mode_count" in summary, "a reused stored result")
        else:
            iteration = iterations.get(number)
            _need(evaluation == "computed" and iteration is not None and iteration["state"] == state
                  and iteration["candidate_ref"] == row["ref"] and iteration["score_kcal_mol"] == score,
                  "a computed candidate follows its iteration")
            if state not in ("scored", "null_result"):
                continue
            handles = [step["result_handle"] for step in iteration["steps"] if step["result_handle"] is not None]
            summary = by_handle.get(handles[-1]) if handles else None
            _need(summary is not None and "mode_count" in summary, "a computed result")
        _need(state == ("scored" if summary["mode_count"] >= 1 else "null_result") and (
            score is None or _same(score, summary["score_kcal_mol"])), "the score is the stored first mode")


def _check_current(record: Mapping[str, Any], branch: str) -> None:
    current = record["current"]
    _need(type(current) is dict and set(current) == set(jev_loops.CURRENT_KEYS), "current keys")
    _need(current["action"] in L.ACTIONS and type(current["can_end"]) is bool, "current action")
    for name in ("needs", "remaining"):
        _need(type(current[name]) is dict and set(current[name]) == set(L.AXES), f"current {name}")
    _need(set(current["blocked_axes"]) <= set(L.COMPUTE_AXES) and set(current["send_blocked_axes"]) <= set(L.SEND_AXES),
          "blocked axes")
    job = current["job"]
    _need(job is None or (type(job) is dict and set(job) == set(jev_loops.JOB_KEYS)
                          and job["step"] in L.BRANCH_STEPS[branch]
                          and job["start_blocked"] in (L.START_BLOCKED, None)), "current job")
    if record["status"] == "ended" or record["exhausted_reason"] is not None:
        _need(current["iteration"] is None and current["phase"] is None and current["step"] is None and job is None
              and current["action"] == ("none" if record["status"] == "ended" else "end"), "current at the end")
        _need(record["status"] == "active" or current["can_end"] is False, "an ended loop cannot end")
        return
    _need(type(current["iteration"]) is int and current["iteration"] >= 1 and current["phase"] in _ACTION_FOR_PHASE
          and current["action"] == _ACTION_FOR_PHASE[current["phase"]]
          and current["step"] in L.BRANCH_STEPS[branch], "current iteration / phase / action")


def validated_loop_record(record: Any, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Spec 3.2, on every read: exact keys, closed sets, the pool's candidates in pool order with the pool notation,
    ``effective_cap``, status / end reason / result handle, the seven counts, every score = the stored result's first
    mode (reused: the candidate's stored result; computed: its iteration's result), the ``current`` shape and the
    limitation sentences. ``inputs`` are the ``derive_inputs`` the record was derived from. ``LoopRecordInvalid``."""
    _need(type(record) is dict and set(record) == set(jev_loops.RECORD_KEYS), "record keys")
    _need(record["schema"] == L.LOOP_SCHEMA and L.is_loop_id(record["loop_id"]), "schema / loop_id")
    branch, goal = record["branch"], record["goal"]
    _need(branch in L.BRANCHES and goal in L.GOALS, "branch / goal")
    _need(type(record["loop_seed"]) is int and L.MIN_LOOP_SEED <= record["loop_seed"] <= L.MAX_LOOP_SEED
          and type(record["iteration_cap"]) is int
          and L.MIN_ITERATION_CAP <= record["iteration_cap"] <= L.MAX_ITERATION_CAP, "seed / cap")
    pool = record["pool"]
    _need(type(pool) is dict and set(pool) == {"source", "structure", "filter", "candidates"}
          and type(pool["candidates"]) is list
          and all(type(item) is dict and set(item) == {"ref", "display"} for item in pool["candidates"]), "pool")
    refs = [item["ref"] for item in pool["candidates"]]
    _need(L.MIN_POOL <= len(refs) <= L.MAX_POOL and len(set(refs)) == len(refs)
          and all(_ref_ok(branch, ref) for ref in refs) and set(inputs["keys"]) == set(refs), "pool candidates")
    _need(record["effective_cap"] == min(record["iteration_cap"], len(refs)), "effective_cap")
    _need(record["setup_sha256"] == hashlib.sha256(canonical_json(record["setup"])).hexdigest(), "setup_sha256")
    status, end_reason = record["status"], record["end_reason"]
    _need(status in L.LOOP_STATUSES and (end_reason is None) == (status == "active")
          and end_reason in (*L.END_REASONS, None), "status / end_reason")
    _need(record["exhausted_reason"] in (*L.EXHAUSTED_REASONS, None), "exhausted_reason")
    _need((record["result_handle"] is not None) == (status == "ended" and end_reason != "run_cancelled")
          and (record["result_handle"] is None or type(record["result_handle"]) is str), "result_handle")
    iterations = _check_iterations(record, branch, refs)
    _check_candidates(record, inputs, branch, refs, iterations)
    counts, rows = record["counts"], record["candidates"]
    _need(type(counts) is dict and set(counts) == set(jev_loops.COUNT_KEYS)
          and all(_count(value) for value in counts.values()), "counts")
    _need(counts["done"] <= counts["started"] <= record["effective_cap"]
          and counts["jev_decided"] + counts["human_decided"] == counts["started"]
          and counts["done"] == sum(row["phase"] == "done" for row in iterations.values())
          and counts["reused_count"] == sum(row["evaluation"] == "reused" for row in rows), "counts agree")
    _check_current(record, branch)
    uncomputed = status == "ended" and any(row["state"] in ("pending", "unavailable") for row in rows)
    _need(record["limitations"] == [L.STATEMENTS[name] for name in L.limitation_ids(
        L.KIND_FOR_BRANCH[branch], goal, uncomputed_left=uncomputed)], "limitation sentences")
    return record


def _read(view: Any, created: Mapping[str, Any], *, budget: Mapping[str, Any], send_active: bool,
          send_reservation: Mapping[str, Any] | None) -> jev_loops.LoopState:
    inputs = derive_inputs(view, created, budget=budget, send_active=send_active, send_reservation=send_reservation)
    state = jev_loops.derive_loop(created["loop_id"], view.read(), **inputs)
    validated_loop_record(state.record, inputs)
    return state


def read_loop(view: Any, loop_id: Any, *, budget: Mapping[str, Any], send_active: bool = False,
              send_reservation: Mapping[str, Any] | None = None) -> jev_loops.LoopState:
    """The derived, checked state of one loop from one snapshot; ``jev_loops.LoopNotFound`` when the run has no such
    loop, ``jev_loops.LoopRecordInvalid`` when its events or the derived record break the closed shapes."""
    return _read(view, created_payload(view.read(), loop_id), budget=budget, send_active=send_active,
                 send_reservation=send_reservation)


def list_loops(view: Any, *, budget: Mapping[str, Any], send_active: bool = False) -> list[dict[str, Any]]:
    """``GET /runs/{rid}/jev_loops``: one row per loop of the run, newest first, each loop read and checked."""
    states = [_read(view, created, budget=budget, send_active=send_active, send_reservation=None)
              for created in _created_loops(view.read()).values()]
    return jev_loops.list_rows(states)


# --- the setup ------------------------------------------------------------------------------------------------------------

def _args_failure(message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": "invalid_job_arguments"})


def normalize_setup(branch: str, setup: Any, source: Any) -> dict[str, Any]:
    """The pure setup check (no store): the closed setup keys, then the M18 value rules (ligand: the M22 shared
    fields of a free candidate request; protein: the docking request on a placeholder model) and, for the protein
    branch, the M21 literals and cutoff. Returns the normalized setup or raises ``ToolFailure(input_invalid)`` with
    the M18 / M21 ``reason_code``."""
    if (type(setup) is not dict or not set(setup) <= set(SETUP_KEYS[branch]) or
            not set(SETUP_REQUIRED[branch]) <= set(setup)):
        raise _args_failure(f"setup takes exactly the keys {list(SETUP_KEYS[branch])}"
                            + (" (acknowledgement, the two literals and contact_cutoff_A may be left out)"
                               if branch == "protein" else " (acknowledgement may be left out)"))
    if branch == "ligand":
        template = {key: setup[key] for key in M18_KEYS if key in setup}
        template.update(mode=FREE_MODE, ligand={"source": "candidate", "candidate_set_handle": source,
                                                "candidate_id": PLACEHOLDER_CANDIDATE,
                                                "parent_sdf_handle": setup["parent_sdf_handle"]})
        row = docking_inputs.validate_arguments(template)
        return {**{key: row[key] for key in M18_KEYS}, "parent_sdf_handle": row["ligand"]["parent_sdf_handle"]}
    request = {"receptor_source": {"kind": MODEL_SOURCE_KIND, "mutation_model": PLACEHOLDER_MODEL,
                                   "side": MUTANT_SIDE},
               "ligand": setup["ligand"], "mode": FREE_MODE, "box": setup["box"], "parameters": setup["parameters"],
               **({"acknowledgement": setup["acknowledgement"]} if "acknowledgement" in setup else {})}
    row = docking_inputs.validate_arguments(request)
    model = mi.normalize_arguments({"candidate_set": source, "candidate_index": 0, "seed": row["parameters"]["seed"],
                                    **{key: setup[key] for key in ("selection_policy", "hydrogen_policy",
                                                                   "contact_cutoff_A") if key in setup}})
    return {"ligand": row["ligand"], "box": row["box"], "parameters": row["parameters"],
            "selection_policy": model["selection_policy"], "hydrogen_policy": model["hydrogen_policy"],
            "acknowledgement": row["acknowledgement"], "contact_cutoff_A": model["contact_cutoff_A"]}


def _admit_setup(view: Any, branch: str, setup: dict[str, Any], source: str, first: Any) -> dict[str, Any]:
    """The store part: what the server refuses when the first pool candidate's first step is submitted. Returns the
    pins (the standalone jobs' ``method`` values)."""
    if branch == "ligand":
        docking_bundle.submission(view, ligand_request(setup, source, first))
        return {"m18": docking_bundle.require_ready()}
    docking_bundle._import_meta(view, setup["ligand"]["sdf_handle"], "ligand_sdf")
    admitted, _timeout = mutation_model_bundle.admission(view, model_request(setup, source, first),
                                                         L.STEP_TIMEOUT_DEFAULTS_S["model"])
    _selected, model_pins = mutation_model_bundle.selection(view, admitted)
    return {"m18": docking_bundle.require_ready(), "m21": model_pins}


def _setup(view: Any, branch: str, raw: Any, pool: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source, first = pool["source"]["handle"], pool["candidates"][0]
    try:
        setup = normalize_setup(branch, raw, source)
        pins = _admit_setup(view, branch, setup, source, first)
    except ToolFailure as exc:
        code = exc.detail.get("reason_code")
        if exc.cls is FailureClass.precondition:
            raise _refusal("capability_unavailable", "an engine of this branch is not available",
                           capability={"reason_code": code, "reason": exc.message}) from exc
        if exc.cls in (FailureClass.input_invalid, FailureClass.resource_exceeded) and code in SETUP_REASONS[branch]:
            raise _refusal("setup_invalid", exc.message, setup_reason=code) from exc
        raise                                    # never a name outside the closed sets
    return setup, pins


# --- the pool ----------------------------------------------------------------------------------------------------------------

def _ref_ok(branch: str, ref: Any) -> bool:
    if branch == "ligand":
        return type(ref) is str and J.CANDIDATE_ID_RE.fullmatch(ref) is not None
    return type(ref) is int and ref >= 0


def _pool(view: Any, branch: str, pool: Any) -> dict[str, Any]:
    """``pool_invalid`` checks; the created payload's normalized pool (candidates in the set's stored order)."""
    if type(pool) is not dict or not set(pool) <= set(L.POOL_KEYS) or not {"source", "candidates"} <= set(pool):
        raise _refusal("pool_invalid", "pool is {source, candidates, filter}")
    handle = pool["source"]
    try:
        content = source_content(view, branch, handle)
    except (KeyError, ValueError, TypeError) as exc:   # LigandEvidenceError / MutationSetInvalid are ValueErrors
        raise _refusal("pool_invalid", "the pool source is not a published, valid candidate set of this run for "
                       "this branch") from exc
    refs = pool["candidates"]
    if (type(refs) is not list or not L.MIN_POOL <= len(refs) <= L.MAX_POOL or
            not all(_ref_ok(branch, ref) for ref in refs)):
        raise _refusal("pool_invalid", f"candidates must be {L.MIN_POOL}-{L.MAX_POOL} candidate ids (ligand) or "
                       "candidate indexes (protein)")
    if len(set(refs)) != len(refs):
        raise _refusal("pool_invalid", "candidates must not repeat")
    key = "id" if branch == "ligand" else "index"
    order = {row[key]: position for position, row in enumerate(content["candidates"])}
    unknown = [ref for ref in refs if ref not in order]
    if unknown:
        raise _refusal("pool_invalid", "candidates are not in the candidate set", candidates=unknown)
    stored = sorted(refs, key=order.__getitem__)
    spec = _pool_filter(branch, pool.get("filter"), content, stored)
    kind = L.KIND_FOR_BRANCH[branch]
    structure = (None if branch == "ligand" else
                 {"handle": content["structure"]["handle"], "model_number": content["structure"]["model_number"]})
    return {"source": {"handle": handle, "schema": J.SOURCE_SCHEMAS[kind]}, "structure": structure,
            "candidates": stored, "filter": spec}


def _pool_filter(branch: str, raw: Any, content: Mapping[str, Any], stored: list[Any]) -> dict[str, Any] | None:
    """Ligand: null or a valid M17 filter spec that no chosen candidate fails (``passes_all`` false; with no active
    criterion every candidate passes, the M17 / M22 / M24 rule). Protein: null only."""
    if raw is None:
        return None
    if branch == "protein":
        raise _refusal("pool_invalid", "a protein pool takes no filter (null)")
    rows = {row["id"]: row for row in content["candidates"]}
    try:
        spec = ligand_filters.normalize_filter_spec(raw)
        failing = [ref for ref in stored if ligand_filters.evaluate_row(rows[ref], spec)["passes_all"] is False]
    except ToolFailure as exc:
        raise _refusal("pool_invalid", "filter is not a valid M17 filter spec") from exc
    if failing:
        raise _refusal("pool_invalid", "chosen candidates do not pass the filter", candidates=failing)
    return spec


# --- creation -----------------------------------------------------------------------------------------------------------

def _same(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def _same_request(existing: Mapping[str, Any], body: Mapping[str, Any]) -> bool:
    """The request would create exactly the existing loop: same branch, source, candidate set (any order), filter,
    goal, seed and cap (types included) and the same normalized setup (key order and number spelling aside)."""
    try:
        branch, pool = body["branch"], body["pool"]
        if branch != existing["branch"] or type(pool) is not dict or not set(pool) <= set(L.POOL_KEYS):
            return False
        source = existing["pool"]["source"]["handle"]
        refs = pool["candidates"]
        raw_filter = pool.get("filter")
        if pool["source"] != source or type(refs) is not list or (branch == "protein" and raw_filter is not None):
            return False
        if sorted(map(canonical_json, refs)) != sorted(map(canonical_json, existing["pool"]["candidates"])):
            return False   # typed: 1 / True / "1" differ; the same refs in any order are the same pool
        spec = None if raw_filter is None else ligand_filters.normalize_filter_spec(raw_filter)
        setup = normalize_setup(branch, body["setup"], source)
        pairs = ((spec, existing["pool"]["filter"]), (body["goal"], existing["goal"]),
                 (body["loop_seed"], existing["loop_seed"]), (body["iteration_cap"], existing["iteration_cap"]),
                 (setup, existing["setup"]))
        return all(_same(left, right) for left, right in pairs)
    except (KeyError, TypeError, ValueError, ToolFailure):
        return False


def _record(run: Any, view: Any, loop_id: str, send_active: bool) -> dict[str, Any]:
    return read_loop(view, loop_id, budget=remaining_budget(run.budget_snapshot()), send_active=send_active).record


def create(run: Any, body: Any, *, send_active: bool) -> dict[str, Any]:
    """``POST /runs/{rid}/jev_loops`` (module docstring: creation). Returns the ``jev_loop@1`` record; raises
    ``LoopRequestError`` (nothing written) or the run owner's busy ``ToolFailure`` (nothing written)."""
    if type(body) is not dict:
        raise _refusal("unknown_field", "the request is one JSON object")
    unknown = sorted(set(body) - set(L.CREATE_KEYS))
    if unknown:
        raise _refusal("unknown_field", f"unknown fields: {unknown}", fields=unknown)
    loop_id = body.get("loop_id")
    if not L.is_loop_id(loop_id):
        raise _refusal("loop_id_invalid", "loop_id must be a canonical version 4 UUID")
    with run._owner():
        run.store.rebuild_from_events()
        view = LoopReadView(run)
        events = view.read()
        loops = _created_loops(events)
        if loop_id in loops:
            if not _same_request(loops[loop_id], body):
                raise _refusal(L.LOOP_ID_CONFLICT, "this loop_id was used for another request")
            return _record(run, view, loop_id, send_active)
        if run.dry_run:
            raise _refusal("dry_run", "a dry-run run cannot hold a JEV loop")
        branch = body.get("branch")
        if type(branch) is not str or branch not in L.BRANCHES:
            raise _refusal("branch_invalid", f"branch must be one of {list(L.BRANCHES)}")
        engine = engine_unavailable(branch, docking_bundle.capability(),
                                    mutation_model_bundle.capability() if branch == "protein" else None)
        if engine is not None:
            raise _refusal("capability_unavailable", "an engine of this branch is not available",
                           capability={"reason_code": engine[0], "reason": engine[1]})
        if _unended(events, loops, branch):
            raise _refusal("loop_active", "this run already has an unended loop of this branch")
        pool = _pool(view, branch, body.get("pool"))
        goal, seed, cap = body.get("goal"), body.get("loop_seed"), body.get("iteration_cap")
        if type(goal) is not str or goal not in L.GOALS:
            raise _refusal("goal_invalid", f"goal must be one of {list(L.GOALS)}")
        if type(seed) is not int or not L.MIN_LOOP_SEED <= seed <= L.MAX_LOOP_SEED:
            raise _refusal("seed_invalid", f"loop_seed must be an integer {L.MIN_LOOP_SEED}-{L.MAX_LOOP_SEED}")
        if type(cap) is not int or not L.MIN_ITERATION_CAP <= cap <= L.MAX_ITERATION_CAP:
            raise _refusal("iteration_cap_invalid",
                           f"iteration_cap must be an integer {L.MIN_ITERATION_CAP}-{L.MAX_ITERATION_CAP}")
        setup, pins = _setup(view, branch, body.get("setup"), pool)
        payload = {"loop_id": loop_id, "branch": branch, "pool": pool, "goal": goal, "loop_seed": seed,
                   "iteration_cap": cap, "setup": setup,
                   "setup_sha256": hashlib.sha256(canonical_json(setup)).hexdigest(), "pins": pins}
        jev_loops.parse_created({"seq": 1, "type": L.EVENT_CREATED, **payload})   # never write what reads fail
        with run._transition():
            run.events.append(L.EVENT_CREATED, **payload)
        return _record(run, LoopReadView(run), loop_id, send_active)


# --- capability ------------------------------------------------------------------------------------------------------------

def engine_unavailable(branch: str, docking: Mapping[str, Any],
                       model: Mapping[str, Any] | None) -> tuple[Any, Any] | None:
    """The first missing engine of a branch, as (reason_code, reason) of that method's own capability (ligand: the
    docking environment and qvina; protein: OpenMM / PDBFixer, then the docking environment), else None."""
    for method in ((docking,) if branch == "ligand" else (model, docking)):
        if method.get("available") is not True:
            return method.get("reason_code"), method.get("reason")
    return None


def capability(docking: Mapping[str, Any], model: Mapping[str, Any], *, tool_exposed: bool,
               pins_match: bool) -> dict[str, dict[str, Any]]:
    """``methods.jev_loop``: per branch ``available`` and the reason (the projection tool not exposed, the science
    pins not the gate's, then that branch's engine reason). No number, pin or version when unavailable."""
    out = {}
    for branch in L.BRANCHES:
        if not tool_exposed:
            reason = ("tool_unavailable", CAPABILITY_REASONS["tool_unavailable"])
        elif not pins_match:
            reason = ("missing_configuration", CAPABILITY_REASONS["missing_configuration"])
        else:
            reason = engine_unavailable(branch, docking, model)
        out[branch] = ({"available": True, "reason_code": None, "reason": None} if reason is None else
                       {"available": False, "reason_code": reason[0], "reason": reason[1]})
    return out
