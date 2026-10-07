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
    LoopReadView(run, events=None)            one event-log snapshot: ``store``, ``run_id``, ``run_dir``,
                                              ``events.read()`` (the shape of the M24 read view in ``api/app.py``);
                                              ``events`` = a list the caller already read
    LoopRequestError(reason_code, message, http_status, **detail)
                                              a loop route refusal; ``detail`` is the response ``detail`` body
                                              (``reason_code`` = the closed spec name)
    created_payload(events, loop_id)          the parsed ``jev_loop_created`` payload (``jev_loops.LoopNotFound``)
    projection_source(view, branch, handle)   (validated stored candidate set, M17 inspection | None)
    source_content(view, branch, handle)      the stored candidate set of the pool, validated (KeyError/ValueError)
    candidate_displays(branch, content, refs) {ref: display}: ligand {smiles}, mutation {residue (7 fields), from, to}
    ligand_request / model_request / dock_request
                                              the exact standalone M18 / M21 job requests of one loop step
    ligand_call_key / model_call_key / dock_call_key, candidate_keys(created, models=None)
                                              their call keys under the pins recorded at creation
    remaining_budget(snapshot), approval_pending(events), loop_approvals(events, loop_id)
    model_index(events)                       M21 call key -> output handle of a done M21 job with that key
    load_results(view, created, approvals)    (results, models): validated stored M18 / M21 results by call key
    load_proposals(view, created)             {handle: jev_loop_choice@1} of this loop that validate now
    derive_inputs(view, created, *, budget, send_active, send_reservation=None)
                                              the ``jev_loops.derive_loop`` keyword inputs of one loop
    validated_loop_record(record, inputs)     the spec 3.2 record check every read runs (``LoopRecordInvalid``)
    read_loop(view, loop_id, *, budget, send_active=False, send_reservation=None) -> jev_loops.LoopState
    list_loops(view, *, budget, send_active=False) -> the list rows, newest first
    projection_inputs(state, iteration)       the record inputs a loop projection reads (its call-key inputs)
    send_refusal(state, projection) -> str | None
                                              spec 5.1 after loop_not_found: the selection refusals, state_changed,
                                              ordinal_mismatch
    loop_send_check(view, projection, *, budget, send_active, send_reservation=None) -> (state | None, reason | None)
                                              the whole loop send check (loop_not_found first); the preview's loop
                                              blocks and the T5 send approval callback
    normalize_setup(branch, setup, source)    the pure setup check and its normalized value
    create(run, body, *, send_active)         ``POST /runs/{rid}/jev_loops`` -> ``jev_loop@1``
    engine_unavailable(branch, docking, model), capability(docking, model, *, tool_exposed, pins_match)
    action_request(body, keys)                the closed body of ``.../compute`` / ``.../abandon_docking``
    locked_view(run)                          (view, budget) refolded under the caller's run owner
    step_capability(branch, pins)             None, or the ``capability_unavailable`` detail (engines; creation pins)
    compute_decision(view, loop_id, request, *, budget, send_active) -> (state, decision)
                                              spec 6.1 from the loop lookup to ``budget_blocked`` (refusals raise)
    compute_when_busy(run, loop_id, request, *, send_active, busy)
                                              the answer while another request holds the run owner
    step_job(run, state, decision)            the approved step's standalone M18 / M21 job request (job admission
                                              first), None for an adopted stored model
    write_approval(run, state, decision, job) the ``jev_loop_compute_approved`` event (``step_unavailable`` first)
    abandon_docking(run, loop_id, body, *, send_active)
                                              ``POST .../abandon_docking`` -> ``jev_loop@1``
    end_loop(run, loop_id, body, *, send_active)
                                              ``POST .../end`` -> ``jev_loop@1``: the summary, then the end event
    stored_result(view, handle)               a stored ``jev_loop_result@1`` checked against its loop (the report
                                              input; ``jev_loop_result.LoopResultInvalid`` otherwise)

Reading (spec 3.2: built and checked on every read, nothing written)
--------------------------------------------------------------------
Every read takes ONE ``LoopReadView`` (one event-log read) and hands that same view to every reader: the job fold
(``JobQueue(view).list()``), ``docking_batch_inputs.published_m18_results`` and ``model_index`` (call key -> handle),
``docking_bundle.validated_result`` / ``mutation_model_bundle.validated_result`` (a stored result that does not
validate, or whose normalized input is not the loop request of that candidate, is left out and never counts as
computed), the candidate set check. ``keys`` come from the created event's setup and pins (events only, no engine);
a protein docking key exists once that candidate's model validates. ``proposals`` come from ``load_proposals`` (this
loop's stored ``jev_loop_choice@1`` objects, each re-validated with ``jev_loop_projection.validated_loop_choice``
against its stored projection and the pool's candidate set). The derived record then passes
``validated_loop_record``. Reads never take the run lock, never write an event or object and never start, submit or
cancel a job.

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

Compute and docking abandon (spec 6.1, 6.3; the routes in ``api/app.py``)
-------------------------------------------------------------------------
The request shape is checked first (``unknown_field``, 422). Under the run owner the log is refolded
(``locked_view``), the loop read and ``jev_loops.compute_admission`` / ``abandon_refusal`` decide; a refusal raises
``LoopRequestError`` and writes nothing. While another request holds the owner (a running job of this run holds it
for the job's whole run, a send for its HTTP exchange) the same decision is read without the lock: a refusal, or for
compute the idempotent answer that starts nothing, is still given; anything that would write or start is the owner's
busy failure (503 ``busy``, nothing written). ``capability_unavailable`` names in ``detail.capability`` the branch's
engine reason, or ``missing_configuration`` (the existing pin-mismatch capability name, no new name) when the engine
pins now differ from the pins recorded at creation (every loop call key was made under those). An approved step runs
the job admission the queue runs at submission on the same request (``step_job``: an M18 / M21 refusal is passed on
with its closed ``detail.reason_code``, nothing written), then ``write_approval`` writes ``jev_loop_compute_approved``
under the transition lock unless a same-key job appeared since the read (``step_unavailable``). The job itself is
submitted by the route under the same run owner and started after the owner is released (``JobQueue.start``, as the
job start route): this module never submits, starts, cancels or retries a job.

Ending and the summary (spec 8.1, 8.2)
--------------------------------------
``end_loop`` checks the body (no key), then under the run owner and, for the last read and the two writes, the
transition lock (so no submission, cancel or result lands between them): ``loop_not_found``, then
``jev_loops.end_refusal``; ``end_reason_for`` decides the reason; ``jev_loop_result.build_loop_result`` makes the
summary from that read, which is validated, stored (same content, same handle) and then named by
``jev_loop_ended``. A stop between the two leaves a stored summary and no end: the loop is not ended and the next
``end`` stores nothing new and writes the event. Every read of an ended loop checks its summary: the record is
derived again from the events up to the loop's ``jev_loop_ended`` event (no engine, job or network) and the stored
object must be exactly the summary that record makes (``jev_loop_result.validated_loop_result``); anything else is
``LoopResultInvalid`` (409 ``run_corrupt`` on the routes). The record of an ended loop IS that derivation (frozen at its
end: a job or result made outside the loop afterwards changes no candidate, count or LJ sentence); only
``current.remaining`` (the run's remaining budget and sends now) and the refusal inputs ``cancelled`` (a run cancel
event, also after the end) and ``send_active`` come from the live log, so a write route still answers ``cancelled``
before ``loop_ended``. ``run_cancelled`` is derived only for a loop without its own end event.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import math
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
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
from . import jev_loop_projection as LP
from . import jev_loop_result as LR
from . import jev_projection as P
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
# Spec 6.1 / 6.3: the messages of the closed compute / abandon refusals (the names and statuses are the spec's).
ACTION_MESSAGES = {
    "unknown_field": "the request takes iteration (an integer) and at most one of proposal or candidate",
    "loop_not_found": "no such loop in this run",
    "cancelled": "the run is cancelled; its loops take no new step",
    "loop_ended": "the loop has ended",
    "send_in_progress": "a science send of this run is in progress",
    "iteration_invalid": "iteration is not the loop's current iteration",
    "phase_invalid": "the current iteration does not take this step now",
    "iteration_cap_reached": "the loop has started as many iterations as its effective cap",
    "proposal_invalid": "proposal is not this iteration's first completed JEV proposal that arrived in time",
    "proposal_late": "this JEV proposal arrived late; it is not the iteration's selection",
    "candidate_invalid": "candidate is not a candidate of the loop's pool",
    "candidate_unavailable": "a same-key job of this candidate cannot be used in this run",
    "candidate_computed": "this candidate is already computed (by this loop or a stored same-condition result)",
    "capability_unavailable": "the branch's engines are not available as they were when the loop was created",
    "budget_blocked": "the run's remaining budget is short of this candidate's need",
    L.STEP_UNAVAILABLE: "a same-key job of this step appeared outside the loop",
    "job_running": "a job this loop approved is queued or running",
    "docking_pending": "the modelled candidate of the iteration awaits its docking or its abandon",
}
_SNAPSHOT_BUDGET = {"expensive_units": 0, "wall_clock_s": 0, "external_tokens": 0, "usd": 0}   # no summary field
PINS_CHANGED_CODE = "missing_configuration"   # the existing pin-mismatch capability name (M24 gate), no new name
PINS_CHANGED_REASON = ("이 루프를 만들 때 기록한 M18·M21 작업 모듈·엔진 pin이 지금 값과 달라, 루프가 기록한 호출 키의 "
                       "작업을 만들 수 없다.")


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
    that takes a run (the M17 / M18 / M21 validated reads) sees the same snapshot. ``events``: a list the caller
    already read (the preview's one read; the send approval callback's list) instead of reading the log again."""

    def __init__(self, run: Any, events: Iterable[dict[str, Any]] | None = None) -> None:
        self.store, self.run_id, self.run_dir = run.store, run.run_id, run.run_dir
        self._events = list(run.events.read() if events is None else events)
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

def projection_source(view: Any, branch: str, handle: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The pool's candidate set: a published ``ligand_candidate_set@1`` (``ligand_bundle.validated_candidate_set``,
    with its validated M17 inspection: the M24 wire's parent fallback) or a stored ``mutation_candidate_set@1``
    (``mutation_candidates.validated_set``, no inspection) of this run, as the M24 projection tool checks its source.
    KeyError / ValueError / TypeError otherwise."""
    kind = L.KIND_FOR_BRANCH[branch]
    if type(handle) is not str:
        raise TypeError("the pool source must be a handle string")
    meta = view.store.meta(handle)
    if (meta["kind"], meta["schema"]) != (J.SOURCE_STORE_KINDS[kind], J.SOURCE_SCHEMAS[kind]):
        raise ValueError("the pool source is not this branch's candidate set kind")
    if kind == "ligand":
        content, inspection = ligand_bundle.validated_candidate_set(view, handle)
        return content, inspection
    return mc.validated_set(view.store.load(handle)), None


def source_content(view: Any, branch: str, handle: Any) -> dict[str, Any]:
    """``projection_source`` without the inspection."""
    return projection_source(view, branch, handle)[0]


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


def _stored_loop_projection(view: Any, handle: Any) -> dict[str, Any]:
    """This run's stored ``jev_loop_projection@1`` at ``handle``, validated (``ValueError`` / ``KeyError`` /
    ``TypeError`` / ``JevProjectionError`` otherwise)."""
    if type(handle) is not str or not handle.startswith(f"obj://{view.run_id}/"):
        raise ValueError("the proposal's projection is not of this run")
    meta = view.store.meta(handle)
    if (meta["kind"], meta["schema"]) != (L.PROJECTION_KIND, L.PROJECTION_SCHEMA):
        raise ValueError("the proposal's projection is not a jev_loop_projection@1")
    return LP.validated_loop_projection(view.store.load_bounded_json(handle, L.MAX_OBJECT_BYTES))


def load_proposals(view: Any, created: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """{handle: content} of this loop's stored ``jev_loop_choice@1`` proposals that validate now: every object of that
    kind and schema in the view's one event list whose ``loop.loop_id`` is this loop's, read back (bounded), checked by
    ``jev_loop_projection.validated_loop_choice`` against its stored projection (this run's validated
    ``jev_loop_projection@1`` of this loop's pool) and the pool's candidate set (validated once, only when such an
    object exists). Anything else (an M24 ``jev_choice@1``, another loop's proposal, an object that does not read back
    or validate, or that does not belong to its own send: ``jev_loops.proposal_matches_send``) is left out, so a
    completed send without a validating proposal of its own has no selection. A late proposal that validates is kept
    (the derivation never takes it as a selection). Writes nothing."""
    loop_id, branch, pool = created["loop_id"], created["branch"], created["pool"]
    handles = dict.fromkeys(event["handle"] for event in view.read() if event.get("type") == "object_created"
                            and event.get("kind") == L.CHOICE_KIND and event.get("schema") == L.CHOICE_SCHEMA)
    source: dict[str, Any] | None = None
    found: dict[str, dict[str, Any]] = {}
    for handle in handles:
        try:
            if type(handle) is not str or not handle.startswith(f"obj://{view.run_id}/"):
                continue
            content = view.store.load_bounded_json(handle, L.MAX_OBJECT_BYTES)
            if type(content) is not dict or type(content.get("loop")) is not dict \
                    or content["loop"].get("loop_id") != loop_id:
                continue
            projection = _stored_loop_projection(view, content["projection"]["handle"])
            if not (projection["kind"] == L.KIND_FOR_BRANCH[branch] and projection["goal"] == created["goal"]
                    and _same(projection["order"]["loop_seed"], created["loop_seed"])
                    and _same(projection["source"], pool["source"]) and _same(projection["structure"], pool["structure"])):
                continue
            if not jev_loops.proposal_matches_send(content, handle, view.read()):
                continue                         # a proposal counts only for its own send (T5 review ruling)
            if source is None:
                source = source_content(view, branch, pool["source"]["handle"])
            found[handle] = LP.validated_loop_choice(content, projection, source)
        except (KeyError, TypeError, ValueError, P.JevProjectionError):   # LoopChoiceInvalid is a ValueError
            continue
    return found


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
    events = view.read()
    if any(event.get("type") == L.EVENT_ENDED and event.get("loop_id") == created["loop_id"] for event in events):
        at_end, _content = _at_end(view, created, budget=budget)          # the record frozen at the loop's end
        record = copy.deepcopy(at_end.record)
        record["current"]["remaining"] = {
            "expensive_units": max(0, budget["expensive_units"]),
            "wall_clock_s": math.floor(max(0, budget["wall_clock_s"])), "external_tokens": None, "usd": None,
            "sends": max(0, J.SEND_CAP - jev_loops.dispatch_count(events))}
        return dataclasses.replace(at_end, record=record, cancelled=jev_loops.run_cancel_seen(events),
                                   send_active=send_active)
    inputs = derive_inputs(view, created, budget=budget, send_active=send_active, send_reservation=send_reservation)
    state = jev_loops.derive_loop(created["loop_id"], events, **inputs)
    validated_loop_record(state.record, inputs)
    return state


# --- the stored summary of an ended loop (spec 8.2) -------------------------------------------------------------------

def _ended(events: list[dict[str, Any]], loop_id: Any) -> tuple[int, dict[str, Any]]:
    for position, event in enumerate(events):
        if event.get("type") == L.EVENT_ENDED and event.get("loop_id") == loop_id:
            return position, jev_loops.parse_ended(event)
    raise LR.LoopResultInvalid("the loop has no end event")


def _load_result(view: Any, handle: Any) -> Any:
    if type(handle) is not str or not handle.startswith(f"obj://{view.run_id}/"):
        raise LR.LoopResultInvalid("the summary is not an object of this run")
    try:
        meta = view.store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise LR.LoopResultInvalid("the summary is not stored") from exc
    if (meta["kind"], meta["schema"]) != (L.RESULT_KIND, L.RESULT_SCHEMA):
        raise LR.LoopResultInvalid("the end event names another kind of object")
    return view.store.load_bounded_json(handle, L.MAX_OBJECT_BYTES)


def _at_end(view: Any, created: Mapping[str, Any], *,
            budget: Mapping[str, Any]) -> tuple[jev_loops.LoopState, dict[str, Any]]:
    """An ended loop as it was when it ended: the state derived from the events up to and including its
    ``jev_loop_ended`` event (one prefix of the view's one read: job records, proposals and stored results as they
    were then; no send was in flight, the end refuses one), the record checked, and the stored summary that event
    names checked to be exactly the one that record makes. A loop event of this loop after its end is
    ``LoopRecordInvalid`` (no route writes one)."""
    events = view.read()
    position, ended = _ended(events, created["loop_id"])
    if any(event.get("type") in L.EVENT_TYPES and event.get("loop_id") == created["loop_id"]
           for event in events[position + 1:]):
        raise jev_loops.LoopRecordInvalid("a loop event after the loop ended")
    snapshot = LoopReadView(view, events[:position + 1])
    inputs = derive_inputs(snapshot, created, budget=budget, send_active=False)
    state = jev_loops.derive_loop(created["loop_id"], snapshot.read(), **inputs)
    validated_loop_record(state.record, inputs)
    content = LR.validated_loop_result(_load_result(view, ended["result_handle"]), state.record, ended["end_reason"])
    return state, content


def stored_result(view: Any, handle: Any) -> dict[str, Any]:
    """The validated ``jev_loop_result@1`` at ``handle`` (the ``jev_loop`` report input): an object of this run of
    that kind and schema whose loop's ``jev_loop_ended`` event names exactly it, equal to the summary the loop's
    record at its end makes. ``jev_loop_result.LoopResultInvalid`` otherwise. Writes nothing."""
    content = _load_result(view, handle)
    loop_id = content.get("loop_id") if type(content) is dict else None
    events = view.read()
    try:
        created = created_payload(events, loop_id)
    except jev_loops.LoopNotFound as exc:
        raise LR.LoopResultInvalid("the summary's loop is not in this run") from exc
    if _ended(events, loop_id)[1]["result_handle"] != handle:
        raise LR.LoopResultInvalid("the loop's end event names another summary")
    return _at_end(view, created, budget=_SNAPSHOT_BUDGET)[1]


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


# --- the loop projection's record inputs and the loop send check (spec 4.1, 5.1) ---------------------------------------

def projection_inputs(state: jev_loops.LoopState, iteration: int) -> dict[str, Any]:
    """What a loop projection of ``iteration`` reads from the record (its call key hashes these with the normalized
    arguments, spec 4.1): the pool in stored order, the goal, the loop seed, the send ordinal and every pool
    candidate's state and stored score (``unavailable`` ones included: they are left out of the wire)."""
    record = state.record
    return {"pool": [row["ref"] for row in record["candidates"]], "goal": record["goal"],
            "loop_seed": record["loop_seed"], "send_ordinal": jev_loops.send_ordinal(state, iteration),
            "candidates": [{"ref": row["ref"], "state": row["state"], "score_kcal_mol": row["score_kcal_mol"]}
                           for row in record["candidates"]]}


def _projection_differs(state: jev_loops.LoopState, projection: Mapping[str, Any]) -> bool:
    """The projection is not what this loop's record derives now: another kind, goal, loop seed, source or
    structure; another set of sendable candidates (the record's minus ``unavailable``) or another state of one; or,
    for exploit, a sent score that is not the candidate's stored first-mode value."""
    record = state.record
    pool = record["pool"]
    if (projection["kind"] != L.KIND_FOR_BRANCH[state.branch] or projection["goal"] != record["goal"]
            or projection["order"]["loop_seed"] != record["loop_seed"]
            or not _same(projection["source"], pool["source"]) or not _same(projection["structure"], pool["structure"])):
        return True
    now = {row["ref"]: row for row in record["candidates"] if row["state"] != "unavailable"}
    sent = {item["ref"]: item for item in projection["selection"]}
    if set(sent) != set(now) or any(sent[ref]["state"] != now[ref]["state"] for ref in sent):
        return True
    if projection["goal"] == "exploit":
        refs = {item["alias"]: item["ref"] for item in projection["selection"]}
        return any(row["state"] == "scored" and not _same(row["score_kcal_mol"], now[refs[row["alias"]]][
            "score_kcal_mol"]) for row in projection["wire"]["computed"])
    return False


def send_refusal(state: jev_loops.LoopState, projection: Mapping[str, Any]) -> str | None:
    """Spec 5.1 after ``loop_not_found``, for a validated ``jev_loop_projection@1`` of this loop: the selection
    refusals of the projection's iteration (``jev_loops.selection_refusal``: loop_ended ... too_few_candidates), then
    ``state_changed`` (the projection is not what the record derives now), then ``ordinal_mismatch`` (its send
    ordinal is not the iteration's dispatched send count). None when the loop may send this projection now."""
    loop = projection["loop"]
    refusal = jev_loops.selection_refusal(state, loop["iteration"])
    if refusal is not None:
        return refusal
    if _projection_differs(state, projection):
        return "state_changed"
    if loop["send_ordinal"] != jev_loops.send_ordinal(state, loop["iteration"]):
        return "ordinal_mismatch"
    return None


def loop_send_check(view: Any, projection: Mapping[str, Any], *, budget: Mapping[str, Any], send_active: bool,
                    send_reservation: Mapping[str, Any] | None = None,
                    ) -> tuple[jev_loops.LoopState | None, str | None]:
    """The loop send check of spec 5.1 (``LOOP_SEND_REASONS`` in order) from one view: ``(None, "loop_not_found")``
    when the projection's loop is not in this run, else ``(state, send_refusal(state, projection))`` with the state
    derived with ``send_reservation`` (the preview's M24 reservation of this projection body). The preview shows the
    result as its loop blocks; the send approval callback (T5) runs the same check on its own event list."""
    try:
        state = read_loop(view, projection["loop"]["loop_id"], budget=budget, send_active=send_active,
                          send_reservation=send_reservation)
    except jev_loops.LoopNotFound:
        return None, "loop_not_found"
    return state, send_refusal(state, projection)


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


# --- compute and docking abandon (spec 6.1, 6.3; module docstring) --------------------------------------------------

def _action_refusal(reason: str, message: str | None = None, **detail: Any) -> LoopRequestError:
    status = {**jev_loops.END_HTTP, **jev_loops.COMPUTE_HTTP}.get(reason, 409)
    return LoopRequestError(reason, message or ACTION_MESSAGES[reason], status, **detail)


def action_request(body: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """The closed body of ``.../compute`` (``L.COMPUTE_KEYS``: ``iteration`` and, for a first step, exactly one
    non-null ``proposal`` or ``candidate``) or ``.../abandon_docking`` (``L.ABANDON_KEYS``). Anything else is the
    request shape refusal ``unknown_field`` (422), before the loop is looked up."""
    if type(body) is not dict:
        raise _action_refusal("unknown_field", "the request is one JSON object")
    unknown = sorted(set(body) - set(keys))
    if unknown:
        raise _action_refusal("unknown_field", f"unknown fields: {unknown}", fields=unknown)
    if type(body.get("iteration")) is not int:
        raise _action_refusal("unknown_field", "iteration is a required integer")
    chosen = [key for key in ("proposal", "candidate") if key in body]
    if len(chosen) > 1 or any(body[key] is None for key in chosen):
        raise _action_refusal("unknown_field", "name at most one of proposal and candidate, never null")
    return dict(body)


def locked_view(run: Any) -> tuple[LoopReadView, dict[str, Any]]:
    """Under the caller's run owner: the store index and the run's budget refolded from the log, then ONE read view
    and the remaining budget of that fold."""
    run.store.rebuild_from_events()
    run._refresh()
    return LoopReadView(run), remaining_budget(run.budget_snapshot())


def _loop_state(view: Any, loop_id: Any, *, budget: Mapping[str, Any], send_active: bool) -> jev_loops.LoopState:
    try:
        return read_loop(view, loop_id, budget=budget, send_active=send_active)
    except jev_loops.LoopNotFound as exc:
        raise _action_refusal("loop_not_found") from exc


def step_capability(branch: str, pins: Mapping[str, Any]) -> dict[str, Any] | None:
    """None when the branch's engines are available and their pins are the loop's creation pins; else the
    ``capability_unavailable`` detail {reason_code, reason}: the engine's own reason (ligand: the docking environment
    and qvina; protein: OpenMM / PDBFixer, then the docking environment), or ``missing_configuration`` when the pins
    changed since creation (the step's job would get another call key than the loop's)."""
    engine = engine_unavailable(branch, docking_bundle.capability(),
                                mutation_model_bundle.capability() if branch == "protein" else None)
    if engine is not None:
        return {"reason_code": engine[0], "reason": engine[1]}
    current = {"m18": docking_bundle.require_ready()}
    if branch == "protein":
        current["m21"] = mutation_model_bundle.require_ready()
    if not _same(current, pins):
        return {"reason_code": PINS_CHANGED_CODE, "reason": PINS_CHANGED_REASON}
    return None


def compute_decision(view: Any, loop_id: Any, request: Mapping[str, Any], *, budget: Mapping[str, Any],
                     send_active: bool) -> tuple[jev_loops.LoopState, dict[str, Any]]:
    """Spec 6.1 after the request shape: ``loop_not_found`` (404), then ``jev_loops.compute_admission`` (cancelled ...
    budget_blocked, the idempotent path included) on one read. A refusal raises ``LoopRequestError`` with the
    admission's detail (``blocked_axes`` and ``needs``; ``capability`` for capability_unavailable). Returns (state,
    decision) for ``idempotent`` and ``approve``."""
    state = _loop_state(view, loop_id, budget=budget, send_active=send_active)
    capability = step_capability(state.branch, state.record["pins"])
    decision = jev_loops.compute_admission(state, iteration=request["iteration"], proposal=request.get("proposal"),
                                           candidate=request.get("candidate"),
                                           capability_available=capability is None)
    if decision["outcome"] == "refused":
        reason = decision["reason_code"]
        extra = {"capability": capability} if reason == "capability_unavailable" else {}
        raise _action_refusal(reason, **decision["detail"], **extra)
    return state, decision


def compute_when_busy(run: Any, loop_id: Any, request: Mapping[str, Any], *, send_active: bool,
                      busy: ToolFailure) -> dict[str, Any]:
    """A compute press while another request holds the run owner (this run's job is running, a send is in flight):
    the same decision read without the lock. A refusal is given; the idempotent answer that starts nothing (the job
    runs or has ended) is {"job_id", "start": False}; anything that would write or start raises ``busy``."""
    _state, decision = compute_decision(LoopReadView(run), loop_id, request,
                                        budget=remaining_budget(run.budget_snapshot()), send_active=send_active)
    if decision["outcome"] == "idempotent" and not decision["start"]:
        return {"job_id": decision["job_id"], "start": False}
    raise busy


def step_job(run: Any, state: jev_loops.LoopState, decision: Mapping[str, Any]) -> dict[str, Any] | None:
    """The standalone job of an approved step: {"protocol", "args", "timeout_s", "call_key"} (M18 ``qvina_dock_v1``
    free docking or M21 ``openmm_mutation_model_v1``, the request builders above), or None when a stored model is
    adopted (no job). Runs the job admission the queue runs at submission on that request first: a refusal is the
    M18 / M21 ``ToolFailure`` with its closed ``detail.reason_code`` and nothing is written. The call key the queue
    gives that request under the current pins must be the approved one."""
    if decision["reuse"]:
        return None
    record = state.record
    setup, source = record["setup"], record["pool"]["source"]["handle"]
    step, ref = decision["step"], decision["candidate_ref"]
    timeout = L.STEP_TIMEOUT_DEFAULTS_S[step]
    if step == "model":
        args = model_request(setup, source, ref)
        admitted, timeout = mutation_model_bundle.admission(run, args, timeout)
        _selected, pins = mutation_model_bundle.selection(run, admitted)
        key, protocol = mutation_model_bundle.call_key(admitted["arguments"], pins), MC.PROTOCOL
    else:
        args = (ligand_request(setup, source, ref) if step == "ligand_dock" else
                dock_request(setup, state.results[state.keys[ref]["model"]]["result_handle"]))
        _selected, normalized, _handles = docking_bundle.submission(run, args)
        key, protocol = docking_bundle.call_key(normalized, docking_bundle.require_ready()), DC.PROTOCOL
    if key != decision["call_key"]:
        raise jev_loops.LoopRecordInvalid("the standalone job of this step would get another call key")
    return {"protocol": protocol, "args": args, "timeout_s": timeout, "call_key": key}


def write_approval(run: Any, state: jev_loops.LoopState, decision: Mapping[str, Any],
                   job: Mapping[str, Any] | None) -> dict[str, Any]:
    """The step's ``jev_loop_compute_approved`` event (spec 6.1, ``approved_by: "human"``), under the transition lock
    after one last look at the queue: a same-key job that appeared since the read (another request's submission) is
    ``step_unavailable`` (409, ``detail.job`` {id, status}, nothing written; the loop never starts, retries or
    cancels another job). Returns the payload."""
    payload = {"loop_id": state.record["loop_id"], "iteration": decision["iteration"], "step": decision["step"],
               "candidate_ref": decision["candidate_ref"], "decided_by": decision["decided_by"],
               "proposal_handle": decision["proposal_handle"], "call_key": decision["call_key"],
               "units": decision["units"], "approved_by": L.APPROVED_BY}
    jev_loops.parse_compute_approved({"seq": 1, "type": L.EVENT_COMPUTE_APPROVED, **payload})   # write what reads
    with run._transition():
        if job is not None:
            same = sorted((item for item in JobQueue(run).list() if item["call_key"] == job["call_key"]),
                          key=lambda item: item["created"])
            if same:
                raise _action_refusal(L.STEP_UNAVAILABLE, job={"id": same[0]["job_id"], "status": same[0]["status"]})
        run.events.append(L.EVENT_COMPUTE_APPROVED, **payload)
    return payload


def _abandon_payload(view: Any, loop_id: Any, request: Mapping[str, Any], *, budget: Mapping[str, Any],
                     send_active: bool) -> dict[str, Any]:
    state = _loop_state(view, loop_id, budget=budget, send_active=send_active)
    reason = jev_loops.abandon_refusal(state, request["iteration"])
    if reason is not None:
        raise _action_refusal(reason)
    model = [step for step in state.steps if step["iteration"] == request["iteration"] and step["step"] == "model"]
    return {"loop_id": state.record["loop_id"], "iteration": request["iteration"],
            "candidate_ref": model[-1]["candidate_ref"]}


def abandon_docking(run: Any, loop_id: Any, body: Any, *, send_active: bool) -> dict[str, Any]:
    """``POST /runs/{rid}/jev_loops/{loop_id}/abandon_docking`` (spec 6.3): only while the iteration awaits its
    docking decision. One ``jev_loop_docking_abandoned`` event; the candidate becomes ``not_run`` (the model step was
    charged or adopted and is never undone) and the iteration ends. Returns the ``jev_loop@1`` record; raises
    ``LoopRequestError`` or the owner's busy ``ToolFailure`` (nothing written)."""
    request = action_request(body, L.ABANDON_KEYS)
    with ExitStack() as stack:
        try:
            stack.enter_context(run._owner())
        except ToolFailure as busy:
            if busy.detail.get("busy") is not True:
                raise
            _abandon_payload(LoopReadView(run), loop_id, request, budget=remaining_budget(run.budget_snapshot()),
                             send_active=send_active)     # a refusal is still given; the write is busy
            raise
        view, budget = locked_view(run)
        payload = _abandon_payload(view, loop_id, request, budget=budget, send_active=send_active)
        jev_loops.parse_docking_abandoned({"seq": 1, "type": L.EVENT_DOCKING_ABANDONED, **payload})
        with run._transition():
            run.events.append(L.EVENT_DOCKING_ABANDONED, **payload)
        return _record(run, LoopReadView(run), payload["loop_id"], send_active)


def _end_state(view: Any, loop_id: Any, *, budget: Mapping[str, Any], send_active: bool) -> jev_loops.LoopState:
    state = _loop_state(view, loop_id, budget=budget, send_active=send_active)
    reason = jev_loops.end_refusal(state)
    if reason is not None:
        raise _action_refusal(reason)
    return state


def end_loop(run: Any, loop_id: Any, body: Any, *, send_active: bool) -> dict[str, Any]:
    """``POST /runs/{rid}/jev_loops/{loop_id}/end`` (spec 8.1; module docstring: ending and the summary). Returns the
    ended ``jev_loop@1`` record; raises ``LoopRequestError`` or the owner's busy ``ToolFailure`` (nothing written)."""
    if type(body) is not dict or body:
        raise _action_refusal("unknown_field", "the request is an empty JSON object",
                              fields=sorted(body) if type(body) is dict else [])
    with ExitStack() as stack:
        try:
            stack.enter_context(run._owner())
        except ToolFailure as busy:
            if busy.detail.get("busy") is not True:
                raise
            _end_state(LoopReadView(run), loop_id, budget=remaining_budget(run.budget_snapshot()),
                       send_active=send_active)                    # a refusal is still given; the end is busy
            raise
        _view, budget = locked_view(run)
        with run._transition():
            state = _end_state(LoopReadView(run), loop_id, budget=budget, send_active=send_active)
            reason = jev_loops.end_reason_for(state)
            content = LR.validated_loop_result(LR.build_loop_result(state.record, reason), state.record, reason)
            handle = run.store.put(L.RESULT_KIND, L.RESULT_SCHEMA, content, summary={
                "loop_id": state.record["loop_id"], "branch": state.branch, "end_reason": reason}).handle
            payload = {"loop_id": state.record["loop_id"], "end_reason": reason, "result_handle": handle}
            jev_loops.parse_ended({"seq": 1, "type": L.EVENT_ENDED, **payload})   # never write what reads refuse
            run.events.append(L.EVENT_ENDED, **payload)
        return _record(run, LoopReadView(run), payload["loop_id"], send_active)


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
