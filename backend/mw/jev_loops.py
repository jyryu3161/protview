"""M25 JEV design loop: the pure loop-record derivation (spec .dryforge/spec.md 3.2, 3.3, 5.1, 5.3, 6.1, 6.3-6.5, 7,
8.1, 9.3).

The functions in this part of the module are pure: they read no object store, event log, job index, file, clock,
network or credential and write nothing. The read routes (T3), the projection admission (T4), the loop check inside
the send approval callback (T5, from the callback's event list only), the compute and end admission (T6) and the
summary / report (T6, T7) all call the same ``derive_loop``. The record routes, the run reads and the event writers
live in ``jev_loop_store`` (which imports this module, never the reverse).

Imports: the standard library, ``jev_loop_constants``, ``jev_constants`` (the M24 event names only through its
``EVENT_*`` attributes, never spelled out), the dependency-free M18 / M21 constant modules (closed job failure
reasons) and ``core.handles.canonical_json``. Never the M24 send module, the gate or a chemistry engine.

Input shapes (one place; every caller builds exactly these from ONE event-log snapshot)
--------------------------------------------------------------------------------------------
events            The run's events, ascending ``seq`` (the ``EventLog.append`` envelope {seq, ts, type} + payload).
                  Read: the four loop events (payloads below); the M24 science events ``J.EVENT_APPROVED`` (send_id,
                  projection_handle), ``J.EVENT_DISPATCH`` (send_id), ``J.EVENT_OUTCOME`` (send_id, status,
                  choice_handle, late) and ``J.EVENT_CONSENT``; ``object_created`` of kind ``jev_loop_projection`` (its
                  ``loop`` reference is decoded from ``payload_b64``: which loop, iteration and send ordinal a send
                  belongs to); the run cancel events ``cancel_requested`` / ``run_cancelled``; the job events
                  ``job_submitted`` (job.job_id), ``budget_reserved`` (root_call_id = the job id), ``job_retry_queued``
                  and ``job_terminal`` (job_id, status, failure).
jobs              The job records of the same snapshot (``JobQueue(view)._state()`` values or that mapping). Read:
                  job_id, call_key, status, blocked_reason. The earliest submitted job of a call key is "the" job of
                  that key, as ``JobQueue.submit`` hands it back.
keys              {ref: {"ligand_dock": key}} (ligand) or {ref: {"model": key, "dock": key | None}} (protein) for
                  every pool candidate: the call keys the standalone M18 / M21 requests the compute route would submit
                  for that candidate have now (``docking_bundle.call_key`` / ``mutation_model_bundle.call_key``).
                  "dock" is None exactly when "model" has no entry in ``results`` (the mutant docking names the model).
results           {call_key: summary} of the results that are published AND validate now, for every key in ``keys``
                  and every call key in this loop's approvals; absent = no usable result (a stored result that does
                  not validate is left out and never counts as computed). M18 ``docking_result@1``: {"result_handle",
                  "mode_count": int >= 0, "score_kcal_mol": modes[0].score_kcal_mol (finite) if mode_count >= 1 else
                  None}; M21 model: {"result_handle"}.
displays          {ref: display} for every pool candidate, rebuilt from the stored candidate set (ligand {"smiles"},
                  mutation {"residue" (7 fields), "from", "to"}).
proposals         {choice_handle: content} of the ``jev_loop_choice@1`` objects of this run that validate now
                  (``validated_loop_choice``) and belong to their send (``proposal_matches_send``). Read:
                  loop{loop_id, iteration, send_ordinal}, send.send_id, answer{local_ref, list_position, list_size},
                  arrival.late. A completed send whose proposal is absent, or names another send / loop reference /
                  arrival, is no proposal (never a selection; its send row's ``proposal_handle`` is null).
budget            The run's remaining amounts {"expensive_units": int, "wall_clock_s": number, "external_tokens": int,
                  "usd": number} (limit - used of the caller's snapshot).
send_reservation  {"external_tokens": int, "usd": number} of the previewed loop projection, or None (no preview yet).
send_active       ``jev_sends.send_active(run_id)`` (process memory; ``app.py`` passes it, this module never asks).
approval_pending  True while the run's first expensive-call approval is requested and unresolved: tells a job blocked
                  for that approval from one blocked for budget (both are claimed + "approval_or_cancel", T1 (a)).

Loop event payloads (closed keys, checked by ``parse_*`` on every read; the writers in T3 / T6 write exactly these)
---------------------------------------------------------------------------------------------------------------------
L.EVENT_CREATED            loop_id (v4 UUID), branch, pool{source{handle, schema}, structure{handle, model_number}
                           (protein) | None (ligand), candidates[2-20 refs, unique], filter (ligand: dict | None,
                           protein: None)}, goal, loop_seed, iteration_cap, setup (dict), setup_sha256 =
                           sha256(core.handles.canonical_json(setup)), pins (dict). A ref is a ligand candidate id
                           ("c_" + 16 hex) or a mutation candidate index (int >= 0).
L.EVENT_COMPUTE_APPROVED   loop_id, iteration (1-8), step, candidate_ref, decided_by, proposal_handle, call_key (64
                           hex), units, approved_by "human". First steps: decided_by "jev" with the proposal's handle or
                           "human" with None. "dock": decided_by "human", proposal_handle None (the candidate is fixed
                           by the model step). units: 0 only for a model step that adopts a stored model, else 1.
L.EVENT_DOCKING_ABANDONED  loop_id, iteration, candidate_ref.
L.EVENT_ENDED              loop_id, end_reason (END_REASONS without "run_cancelled", which is derived, never written),
                           result_handle (the jev_loop_result@1 handle).

Derivation rules that are this module's reading of the spec (see the T2 report's spec_gaps)
-------------------------------------------------------------------------------------------
* Step result (spec 6.4) = the first change of that call key's job after the approval: a terminal with a reservation
  after its (re)queue mark is charged (completed when done and the result validates, else failed with the job's
  closed failure reason or null); a terminal without one is unavailable; a job already ended before the approval is
  reused (done + validated result, job_id null) or unavailable; an approval whose key has no job is reused when the
  result is stored, else unavailable (only a crash between the approval event and the submit leaves that).
* A candidate whose iteration started and has not ended is ``pending`` with ``iteration`` null (spec 3.2 literal rule
  for pending); it still counts as pending (so ``pool_exhausted`` never fires while it runs) but cannot be selected.
* A candidate held by a live step of this loop (the job of a step's latest approval is queued, claimed or running)
  is ``pending`` before priority 2 and 3 apply: a same-key result published elsewhere meanwhile does not make it
  ``reused`` and the job does not make it ``unavailable`` (coordinator ruling). Once that step is ``unavailable`` the
  candidate is read by 2-4 again; once charged it follows the iteration (1).
* An iteration's ``state`` is ``unavailable`` when the step of its latest first-step approval is ``unavailable`` and
  no newer approval exists; the record keeps it even if the candidate later reads ``reused``. Until then a
  not-started iteration is ``in_progress``.
* ``counts.jev_decided`` / ``human_decided`` count started iterations by their deciding approval; ``reused_count``
  counts pool candidates whose evaluation is "reused"; ``units_charged`` counts charged steps.
* ``current.needs`` for wait_job / end / none is zero; the send axes are judged only at "select" with at least two
  pending candidates (a send is possible); ``needs.sends`` is then 1, else 0. A dock step left unavailable carries
  ``reason_code`` "docking_not_run". The record's ``limitations`` are the summary's sentences (LJ8 once ended with a
  pending or unavailable candidate).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from . import docking_constants as DC
from . import jev_constants as J
from . import jev_loop_constants as L
from . import mutation_model_constants as MC
from .core.handles import canonical_json

# --- record shapes (spec 3.2) ----------------------------------------------------------------------------------------
RECORD_KEYS = ("schema", "loop_id", "branch", "status", "end_reason", "exhausted_reason", "goal", "loop_seed",
               "iteration_cap", "effective_cap", "pool", "setup", "setup_sha256", "pins", "counts", "candidates",
               "iterations", "current", "result_handle", "limitations")
COUNT_KEYS = ("started", "done", "jev_decided", "human_decided", "sends_dispatched", "units_charged", "reused_count")
CANDIDATE_KEYS = ("ref", "display", "state", "evaluation", "score_kcal_mol", "iteration")
ITERATION_KEYS = ("index", "phase", "decided_by", "candidate_ref", "proposal_handle", "list_position", "list_size",
                  "approvals", "sends", "steps", "state", "score_kcal_mol")
APPROVAL_KEYS = ("step", "candidate_ref", "decided_by", "proposal_handle", "call_key")
SEND_KEYS = ("send_id", "status", "send_ordinal", "proposal_handle", "late")
STEP_KEYS = ("step", "candidate_ref", "job_id", "call_key", "result_handle", "state", "reason_code", "evaluation")
CURRENT_KEYS = ("iteration", "phase", "step", "action", "needs", "remaining", "blocked_axes", "send_blocked_axes",
                "can_end", "job")
JOB_KEYS = ("job_id", "step", "status", "start_blocked")
ROW_KEYS = ("loop_id", "branch", "status", "end_reason", "goal", "pool_size", "counts", "created_seq")

# --- loop event payloads ---------------------------------------------------------------------------------------------
CREATED_KEYS = ("loop_id", "branch", "pool", "goal", "loop_seed", "iteration_cap", "setup", "setup_sha256", "pins")
CREATED_POOL_KEYS = ("source", "structure", "candidates", "filter")
APPROVED_KEYS = ("loop_id", "iteration", "step", "candidate_ref", "decided_by", "proposal_handle", "call_key", "units",
                 "approved_by")
ABANDONED_KEYS = ("loop_id", "iteration", "candidate_ref")
ENDED_KEYS = ("loop_id", "end_reason", "result_handle")
BUDGET_KEYS = ("expensive_units", "wall_clock_s", "external_tokens", "usd")

# --- HTTP status of each refusal (spec 6.1, 8.1) ----------------------------------------------------------------------
COMPUTE_HTTP = {"unknown_field": 422, "loop_not_found": 404, "cancelled": 409, "loop_ended": 409,
                "send_in_progress": 409, "iteration_invalid": 409, "phase_invalid": 409, "iteration_cap_reached": 409,
                "proposal_invalid": 409, "proposal_late": 409, "candidate_invalid": 422, "candidate_unavailable": 409,
                "candidate_computed": 409, "capability_unavailable": 412, "budget_blocked": 429}
END_HTTP = {"loop_not_found": 404, "cancelled": 409, "loop_ended": 409, "send_in_progress": 409, "job_running": 409,
            "docking_pending": 409}

_ENVELOPE = ("seq", "ts", "type")
_CANCEL_EVENTS = ("cancel_requested", "run_cancelled")
_FIRST_STEP = {"ligand": "ligand_dock", "protein": "model"}
_STARTED = ("running", "completed", "failed", "reused")      # a charged first step or an adopted model
_LIVE = ("waiting_start", "running")
_FAILURE_REASONS = {"ligand_dock": DC.REASONS, "dock": DC.REASONS, "model": MC.FAILURE_REASON_CODES}
_ACTION = {"awaiting_selection": "select", "awaiting_compute": "compute", "running": "wait_job",
           "awaiting_docking": "dock"}
_COMPLETED = "completed"                                      # the M24 send status of an answered send
_APPROVAL_BLOCK = "approval_or_cancel"
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_HANDLE = r"obj://[A-Za-z0-9][A-Za-z0-9_-]{0,79}/%s/[0-9a-f]{64}"


class LoopRecordInvalid(ValueError):
    """The run's events do not form a valid loop record: a payload outside its closed shape, or an event order the
    loop routes never write."""


class LoopNotFound(LookupError):
    """No ``jev_loop_created`` event with this loop_id in the run."""


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise LoopRecordInvalid(message)


def _is_int(value: Any, low: int | None = None, high: int | None = None) -> bool:
    return type(value) is int and (low is None or value >= low) and (high is None or value <= high)


def _is_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _is_ref(value: Any, branch: str | None = None) -> bool:
    is_id = type(value) is str and J.CANDIDATE_ID_RE.fullmatch(value) is not None
    is_index = _is_int(value, 0)
    return (is_id or is_index) if branch is None else is_id if branch == "ligand" else is_index


def _is_handle(value: Any, kind: str) -> bool:
    return type(value) is str and re.fullmatch(_HANDLE % kind, value) is not None


def _payload(event: Any, keys: tuple[str, ...], name: str) -> dict[str, Any]:
    _need(type(event) is dict and event.get("type") == name and _is_int(event.get("seq"), 1), f"{name} event")
    data = {key: value for key, value in event.items() if key not in _ENVELOPE}
    _need(set(data) == set(keys), f"{name} payload keys")
    return data


# --- loop event parsers ----------------------------------------------------------------------------------------------

def parse_created(event: Any) -> dict[str, Any]:
    data = _payload(event, CREATED_KEYS, L.EVENT_CREATED)
    _need(L.is_loop_id(data["loop_id"]), "loop_id")
    branch = data["branch"]
    _need(type(branch) is str and branch in L.BRANCHES, "branch")
    kind = L.KIND_FOR_BRANCH[branch]
    pool = data["pool"]
    _need(type(pool) is dict and set(pool) == set(CREATED_POOL_KEYS), "pool keys")
    source = pool["source"]
    _need(type(source) is dict and set(source) == {"handle", "schema"} and source["schema"] == J.SOURCE_SCHEMAS[kind]
          and _is_handle(source["handle"], J.SOURCE_STORE_KINDS[kind]), "pool source")
    structure = pool["structure"]
    if branch == "protein":
        _need(type(structure) is dict and set(structure) == {"handle", "model_number"}
              and _is_handle(structure["handle"], J.STRUCTURE_KIND) and _is_int(structure["model_number"]),
              "pool structure")
        _need(pool["filter"] is None, "a protein pool has no filter")
    else:
        _need(structure is None, "a ligand pool has no structure")
        _need(pool["filter"] is None or type(pool["filter"]) is dict, "pool filter")
    refs = pool["candidates"]
    _need(type(refs) is list and L.MIN_POOL <= len(refs) <= L.MAX_POOL and all(_is_ref(ref, branch) for ref in refs)
          and len(set(refs)) == len(refs), "pool candidates")
    _need(type(data["goal"]) is str and data["goal"] in L.GOALS, "goal")
    _need(_is_int(data["loop_seed"], L.MIN_LOOP_SEED, L.MAX_LOOP_SEED), "loop_seed")
    _need(_is_int(data["iteration_cap"], L.MIN_ITERATION_CAP, L.MAX_ITERATION_CAP), "iteration_cap")
    _need(type(data["setup"]) is dict and type(data["pins"]) is dict, "setup and pins")
    _need(data["setup_sha256"] == hashlib.sha256(canonical_json(data["setup"])).hexdigest(), "setup_sha256")
    return data


def parse_compute_approved(event: Any) -> dict[str, Any]:
    data = _payload(event, APPROVED_KEYS, L.EVENT_COMPUTE_APPROVED)
    _need(L.is_loop_id(data["loop_id"]), "loop_id")
    _need(_is_int(data["iteration"], 1, L.MAX_ITERATION_CAP), "iteration")
    step = data["step"]
    _need(type(step) is str and step in L.STEPS, "step")
    _need(_is_ref(data["candidate_ref"]), "candidate_ref")
    decided_by, proposal = data["decided_by"], data["proposal_handle"]
    _need(type(decided_by) is str and decided_by in L.DECIDED_BY, "decided_by")
    _need((decided_by == "jev") == (proposal is not None), "a JEV decision names its proposal, a human one none")
    _need(proposal is None or _is_handle(proposal, L.CHOICE_KIND), "proposal_handle")
    _need(step != "dock" or decided_by == "human", "the docking step is decided by the human")
    _need(type(data["call_key"]) is str and _SHA_RE.fullmatch(data["call_key"]) is not None, "call_key")
    _need(_is_int(data["units"], 0, 1) and (data["units"] == 1 or step == "model"), "units")
    _need(data["approved_by"] == L.APPROVED_BY, "approved_by")
    return data


def parse_docking_abandoned(event: Any) -> dict[str, Any]:
    data = _payload(event, ABANDONED_KEYS, L.EVENT_DOCKING_ABANDONED)
    _need(L.is_loop_id(data["loop_id"]), "loop_id")
    _need(_is_int(data["iteration"], 1, L.MAX_ITERATION_CAP), "iteration")
    _need(_is_ref(data["candidate_ref"]), "candidate_ref")
    return data


def parse_ended(event: Any) -> dict[str, Any]:
    data = _payload(event, ENDED_KEYS, L.EVENT_ENDED)
    _need(L.is_loop_id(data["loop_id"]), "loop_id")
    _need(type(data["end_reason"]) is str and data["end_reason"] in L.END_REASONS
          and data["end_reason"] != "run_cancelled", "end_reason")
    _need(_is_handle(data["result_handle"], L.RESULT_KIND), "result_handle")
    return data


def created_loops(events: Iterable[dict[str, Any]]) -> list[tuple[int, str]]:
    """(created seq, loop_id) of every loop of the run, in creation order (each created event parsed)."""
    found: list[tuple[int, str]] = []
    for event in events:
        if event.get("type") == L.EVENT_CREATED:
            loop_id = parse_created(event)["loop_id"]
            _need(all(loop_id != other for _, other in found), "a loop is created twice")
            found.append((event["seq"], loop_id))
    return found


# --- pure copies of the M24 event functions (jev_sends is never imported; a test compares the two) ---------------

def consent_enabled(events: Iterable[dict[str, Any]]) -> bool:
    """The last science consent event decides; none (a new run) is off."""
    last = None
    for event in events:
        if event.get("type") == J.EVENT_CONSENT:
            last = event
    return bool(last is not None and last.get("policy") == J.CONSENT_POLICY and last.get("enabled") is True)


def dispatch_count(events: Iterable[dict[str, Any]]) -> int:
    """The run's dispatched science sends (the run's send cap counts these)."""
    return sum(event.get("type") == J.EVENT_DISPATCH for event in events)


def run_cancel_seen(events: Iterable[dict[str, Any]]) -> bool:
    """A run cancel event (the M24 check also looks at the cancel marker file; this one reads events only)."""
    return any(event.get("type") in _CANCEL_EVENTS for event in events)


def late_arrival(events: list[dict[str, Any]], send_id: Any) -> tuple[bool, str | None]:
    """Late = a cancel event or a consent-off event after this send's dispatch (event order only, no clock)."""
    dispatch = next((event for event in events if event.get("type") == J.EVENT_DISPATCH
                     and event.get("send_id") == send_id), None)
    if dispatch is None:
        return False, None
    later = [event for event in events if event["seq"] > dispatch["seq"]]
    if any(event.get("type") in _CANCEL_EVENTS for event in later):
        return True, "run_cancelled"
    if any(event.get("type") == J.EVENT_CONSENT and not consent_enabled([event]) for event in later):
        return True, "consent_off"
    return False, None


def proposal_matches_send(content: Any, handle: Any, events: list[dict[str, Any]], send_id: Any = None) -> bool:
    """A stored ``jev_loop_choice@1`` counts only for its own send (T5 review ruling): the first outcome of
    ``send.send_id`` is completed and names ``handle`` (with the proposal's audit id), the first approval of that
    send names the proposal's ``projection.handle`` and ``projection.body_sha256``, and ``arrival`` {late,
    late_reason} equals that outcome's and the event-order judgment before it (``late_arrival``). ``send_id``, when
    given, must be the proposal's send. Never raises: anything unreadable is no match."""
    try:
        own, audit_id = content["send"]["send_id"], content["send"]["audit_id"]
        projection, arrival = content["projection"], (content["arrival"]["late"], content["arrival"]["late_reason"])
        if send_id is not None and own != send_id:
            return False
        approval = next((event for event in events if event.get("type") == J.EVENT_APPROVED
                         and event.get("send_id") == own), None)
        outcome = next((event for event in events if event.get("type") == J.EVENT_OUTCOME
                        and event.get("send_id") == own), None)
        if approval is None or outcome is None or type(arrival[0]) is not bool:
            return False
        before = [event for event in events if event["seq"] < outcome["seq"]]
        return (outcome.get("status") == _COMPLETED and outcome.get("choice_handle") == handle
                and outcome.get("audit_id") == audit_id
                and approval.get("projection_handle") == projection["handle"]
                and approval.get("body_sha256") == projection["body_sha256"]
                and arrival == (outcome.get("late"), outcome.get("late_reason")) == late_arrival(before, own))
    except (KeyError, TypeError, AttributeError):
        return False


def loop_projection_refs(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{projection handle: {loop_id, iteration, send_ordinal}} decoded from each stored loop projection's event."""
    refs: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "object_created" or event.get("kind") != L.PROJECTION_KIND:
            continue
        handle = event.get("handle")
        if handle in refs:
            continue
        try:
            loop = json.loads(base64.b64decode(event["payload_b64"], validate=True))["loop"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LoopRecordInvalid("a loop projection event is not readable") from exc
        _need(type(loop) is dict and set(loop) == set(L.LOOP_REF_KEYS) and L.is_loop_id(loop["loop_id"])
              and _is_int(loop["iteration"], 1) and _is_int(loop["send_ordinal"], 0), "a loop projection reference")
        refs[handle] = dict(loop)
    return refs


# --- the derived state ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopState:
    """``record`` is the ``jev_loop@1`` read (spec 3.2). The other fields are what the refusal helpers below need;
    they are not part of the record and are never returned by a route."""

    record: dict[str, Any]
    created_seq: int
    branch: str
    cancelled: bool                      # a run cancel event exists
    ended_event: bool                    # a jev_loop_ended event exists
    current_number: int                  # the iteration a request must name: in progress, else started + 1
    current_phase: str                   # that iteration's phase (also while exhausted)
    started: int
    effective_cap: int
    pending: tuple[Any, ...]             # pending candidates (incl. the one of an iteration in progress), pool order
    send_active: bool
    approval_pending: bool
    selections: dict[int, str] = field(repr=False)              # iteration -> first completed, not-late proposal
    late_proposals: dict[int, frozenset[str]] = field(repr=False)
    proposal_refs: dict[str, Any] = field(repr=False)           # proposal handle -> chosen candidate ref
    dispatched: dict[int, int] = field(repr=False)              # iteration -> dispatched loop sends
    candidate_needs: dict[Any, dict[str, int]] = field(repr=False)
    steps: tuple[dict[str, Any], ...] = field(repr=False)       # internal step entries, approval order
    keys: Mapping[Any, Mapping[str, Any]] = field(repr=False)
    results: Mapping[str, Mapping[str, Any]] = field(repr=False)
    remaining: dict[str, Any] = field(repr=False)


def _loop_events(events: list[dict[str, Any]], loop_id: Any) -> tuple[Any, ...]:
    created, approvals, abandons, ended = None, [], [], None
    for event in events:
        kind = event.get("type")
        if kind not in L.EVENT_TYPES or event.get("loop_id") != loop_id:
            continue
        if kind == L.EVENT_CREATED:
            _need(created is None, "a loop is created twice")
            created = (event["seq"], parse_created(event))
            continue
        _need(created is not None, "a loop event before the loop was created")
        _need(ended is None, "a loop event after the loop ended")
        if kind == L.EVENT_COMPUTE_APPROVED:
            approvals.append((event["seq"], parse_compute_approved(event)))
        elif kind == L.EVENT_DOCKING_ABANDONED:
            abandons.append((event["seq"], parse_docking_abandoned(event)))
        else:
            ended = (event["seq"], parse_ended(event))
    if created is None:
        raise LoopNotFound(loop_id)
    return created, approvals, abandons, ended


def _check_inputs(branch: str, pool: list[Any], keys: Any, results: Any, displays: Any, budget: Any,
                  reservation: Any) -> None:
    def require(condition: Any, message: str) -> None:
        if not condition:
            raise ValueError(message)

    names = set(L.BRANCH_STEPS[branch])
    require(isinstance(keys, Mapping) and set(keys) == set(pool), "keys must cover exactly the pool candidates")
    require(isinstance(results, Mapping) and isinstance(displays, Mapping) and set(pool) <= set(displays),
            "results must be a mapping and displays must cover the pool")
    for ref in pool:
        entry = keys[ref]
        require(isinstance(entry, Mapping) and set(entry) == names, "keys entry names the branch's steps")
        for step in names:
            value = entry[step]
            require((value is None and step == "dock") or (type(value) is str and _SHA_RE.fullmatch(value)),
                    "call keys are 64 hex digits")
        if branch == "protein":
            require((entry["dock"] is None) == (entry["model"] not in results),
                    "the docking key is known exactly when the model result is stored")
    require(isinstance(budget, Mapping) and set(budget) == set(BUDGET_KEYS) and _is_int(budget["expensive_units"])
            and _is_number(budget["wall_clock_s"]) and _is_int(budget["external_tokens"])
            and _is_number(budget["usd"]), "budget must hold the four remaining amounts")
    require(reservation is None or (isinstance(reservation, Mapping)
                                    and set(reservation) == {"external_tokens", "usd"}
                                    and _is_int(reservation["external_tokens"], 0)
                                    and _is_number(reservation["usd"])), "send_reservation")


def _job_index(events: list[dict[str, Any]], jobs: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    timelines: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event.get("type")
        if kind == "job_submitted":
            job_id = event["job"]["job_id"]
            timelines[job_id] = {"submitted": event["seq"], "marks": [event["seq"]], "reserved": [], "terminals": []}
        elif kind == "job_retry_queued" and event.get("job_id") in timelines:
            timelines[event["job_id"]]["marks"].append(event["seq"])
        elif kind == "budget_reserved" and event.get("root_call_id") in timelines:
            timelines[event["root_call_id"]]["reserved"].append(event["seq"])
        elif kind == "job_terminal" and event.get("job_id") in timelines:
            timelines[event["job_id"]]["terminals"].append((event["seq"], event.get("status"), event.get("failure")))
    by_key: dict[str, dict[str, Any]] = {}
    for record in (jobs.values() if isinstance(jobs, Mapping) else jobs):
        timeline = timelines.get(record["job_id"])
        _need(timeline is not None, "a job record without its submission event")
        held = by_key.get(record["call_key"])
        if held is None or timeline["submitted"] < timelines[held["job_id"]]["submitted"]:
            by_key[record["call_key"]] = record
    return by_key, timelines


def _result_state(summary: Any) -> tuple[str, Any]:
    if not (isinstance(summary, Mapping) and type(summary.get("result_handle")) is str
            and _is_int(summary.get("mode_count"), 0)):
        raise ValueError("a docking result summary needs result_handle and mode_count")
    score = summary.get("score_kcal_mol")
    if summary["mode_count"] >= 1:
        if not _is_number(score):
            raise ValueError("a docking result with modes carries its first-mode score")
        return "scored", score
    if score is not None:
        raise ValueError("a docking result without modes has no score")
    return "null_result", None


def _failure_reason(step: str, status: Any, failure: Any) -> str | None:
    if status != "failed" or not isinstance(failure, Mapping):
        return None
    code = failure.get("reason_code")
    return code if type(code) is str and code in _FAILURE_REASONS[step] else None


def _step(seq: int, approval: dict[str, Any], by_key: dict[str, Any], timelines: dict[str, Any],
          results: Mapping[str, Any]) -> dict[str, Any]:
    """Spec 6.4: the step's result is the first change of its call key's job after the approval event."""
    call_key, step = approval["call_key"], approval["step"]
    entry = {"seq": seq, "iteration": approval["iteration"], "step": step, "candidate_ref": approval["candidate_ref"],
             "decided_by": approval["decided_by"], "proposal_handle": approval["proposal_handle"],
             "call_key": call_key, "job": None, "state": None, "reason_code": None, "result": None,
             "start_seq": None, "resolve_seq": None}
    result = results.get(call_key)
    job = by_key.get(call_key)

    def reused() -> dict[str, Any]:
        entry.update(state="reused", result=result, start_seq=seq, resolve_seq=seq, job=None)
        return entry

    if job is None:
        if result is not None:
            return reused()
        entry.update(state="unavailable", resolve_seq=seq)
        return entry
    entry["job"] = job
    timeline = timelines[job["job_id"]]
    marks, terminals = timeline["marks"], timeline["terminals"]
    before = max([(mark, False) for mark in marks if mark < seq]
                 + [(end, True) for end, _, _ in terminals if end < seq], default=None)
    if before is not None and before[1]:       # the job had already ended when the step was approved
        status = next(status for end, status, _ in terminals if end == before[0])
        if status == "done" and result is not None:
            return reused()
        entry.update(state="unavailable", resolve_seq=seq)
        return entry
    after = next(((end, status, failure) for end, status, failure in terminals if end > seq), None)
    if after is None:
        mark = max(marks)
        reserved = [at for at in timeline["reserved"] if at > mark]
        _need(reserved or job["status"] != "running", "a running job without its reservation")
        if reserved:
            entry.update(state="running", start_seq=reserved[0])
        else:
            entry["state"] = "waiting_start"
        return entry
    end, status, failure = after
    mark = max(at for at in marks if at < end)
    reserved = [at for at in timeline["reserved"] if mark < at < end]
    entry["resolve_seq"] = end
    if not reserved:
        entry["state"] = "unavailable"
    elif status == "done" and result is not None:
        entry.update(state="completed", result=result, start_seq=reserved[0])
    else:
        entry.update(state="failed", reason_code=_failure_reason(step, status, failure), start_seq=reserved[0])
    return entry


def _sends(events: list[dict[str, Any]], loop_id: str, send_active: bool) -> list[dict[str, Any]]:
    refs = loop_projection_refs(events)
    approved: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    dispatched: set[str] = set()
    last_approved = None
    for event in events:
        kind = event.get("type")
        if kind == J.EVENT_APPROVED:
            approved.setdefault(event["send_id"], event)
            last_approved = event["send_id"]
        elif kind == J.EVENT_OUTCOME:
            outcomes.setdefault(event["send_id"], event)
        elif kind == J.EVENT_DISPATCH:
            dispatched.add(event["send_id"])
    sends = []
    for send_id, event in approved.items():
        ref = refs.get(event.get("projection_handle"))
        if ref is None or ref["loop_id"] != loop_id:
            continue
        outcome = outcomes.get(send_id)
        if outcome is not None:
            status, late, proposal = outcome["status"], outcome["late"] is True, outcome.get("choice_handle")
        else:   # the M24 record: in progress while this run's send is active, else failed (lost)
            status = J.IN_PROGRESS if send_active and send_id == last_approved else "failed"
            late, proposal = False, None
        sends.append({"send_id": send_id, "iteration": ref["iteration"], "send_ordinal": ref["send_ordinal"],
                      "outcome": outcome, "dispatched": send_id in dispatched, "status": status, "late": late,
                      "proposal_handle": proposal})
    return sends


def _proposal_ref(content: Any, kind: str, send: dict[str, Any], loop_id: str) -> tuple[Any, int, int, bool] | None:
    """The proposal's chosen candidate, list place and lateness, or None when it is not readable or does not belong
    to this send (another loop reference, send or arrival): such a proposal is dropped, never an error."""
    try:
        loop, answer, late = content["loop"], content["answer"], content["arrival"]["late"]
        local = answer["local_ref"]
        ref = local["candidate_id"] if kind == "ligand" else local["candidate_index"]
        position, size, send_id = answer["list_position"], answer["list_size"], content["send"]["send_id"]
    except (KeyError, TypeError):
        return None
    if not (loop == {"loop_id": loop_id, "iteration": send["iteration"], "send_ordinal": send["send_ordinal"]}
            and send_id == send["send_id"] and late is send["late"]):
        return None
    if not (_is_ref(ref, "ligand" if kind == "ligand" else "protein") and _is_int(size, 1)
            and _is_int(position, 1, size)):
        return None
    return ref, position, size, late


def _proposals(sends: list[dict[str, Any]], proposals: Mapping[str, Any], kind: str, loop_id: str) -> tuple[Any, ...]:
    """Selections, late proposals and proposal info from the completed sends whose proposal is present and belongs
    to them; every other send row's ``proposal_handle`` becomes null (T5 review ruling)."""
    selections: dict[int, str] = {}
    late: dict[int, set[str]] = {}
    info: dict[str, dict[str, Any]] = {}
    matched: set[str] = set()
    answered = [send for send in sends if send["outcome"] is not None and send["status"] == _COMPLETED]
    for send in sorted(answered, key=lambda item: item["outcome"]["seq"]):
        handle = send["proposal_handle"]
        found = None if handle is None or handle not in proposals else _proposal_ref(proposals[handle], kind, send,
                                                                                     loop_id)
        if found is None:
            continue
        matched.add(send["send_id"])
        ref, position, size, is_late = found
        number = send["iteration"]
        info[handle] = {"ref": ref, "list_position": position, "list_size": size, "iteration": number,
                        "seq": send["outcome"]["seq"]}
        if is_late:
            late.setdefault(number, set()).add(handle)
        elif number not in selections:
            selections[number] = handle
    for send in sends:
        if send["send_id"] not in matched:
            send["proposal_handle"] = None
    return selections, {number: frozenset(handles) for number, handles in late.items()}, info


def _iterations(branch: str, pool: list[Any], effective_cap: int, steps: list[dict[str, Any]],
                abandons: list[tuple[int, dict[str, Any]]], selections: dict[int, str],
                info: dict[str, dict[str, Any]], ended: Any) -> dict[int, dict[str, Any]]:
    first_step = _FIRST_STEP[branch]
    by_number: dict[int, list[dict[str, Any]]] = {}
    for step in steps:
        _need(step["step"] in L.BRANCH_STEPS[branch], "a step of the other branch")
        _need(step["candidate_ref"] in pool, "an approval for a candidate outside the pool")
        by_number.setdefault(step["iteration"], []).append(step)
    abandon_by: dict[int, tuple[int, dict[str, Any]]] = {}
    for seq, abandon in abandons:
        _need(branch == "protein" and abandon["iteration"] not in abandon_by,
              "a docking abandon the routes never write")
        abandon_by[abandon["iteration"]] = (seq, abandon)
    numbers = sorted(set(by_number) | set(abandon_by))
    _need(numbers == list(range(1, len(numbers) + 1)) and len(numbers) <= effective_cap,
          "iterations are numbered 1, 2, ... up to effective_cap")
    iterations: dict[int, dict[str, Any]] = {}
    for number in numbers:
        own = by_number.get(number, [])
        firsts = [step for step in own if step["step"] == first_step]
        docks = [step for step in own if step["step"] == "dock"]
        _need(firsts and (not docks or docks[0]["seq"] > firsts[0]["seq"]), "an iteration starts with its first step")
        for earlier, later in pairwise(firsts):
            _need(earlier["state"] == "unavailable" and earlier["resolve_seq"] < later["seq"],
                  "a new first-step approval while the previous one could still start")
        for step in firsts:
            if step["decided_by"] == "jev":
                chosen = info.get(step["proposal_handle"])
                _need(step["proposal_handle"] == selections.get(number) and chosen is not None
                      and chosen["seq"] < step["seq"] and chosen["ref"] == step["candidate_ref"],
                      "a JEV decision that is not the iteration's first completed, not-late proposal")
        latest = firsts[-1]
        it = {"index": number, "firsts": firsts, "docks": docks, "abandon": abandon_by.get(number), "latest": latest,
              "started": latest["state"] in _STARTED, "done": False, "done_seq": None, "outcome": None,
              "result": None, "live": None}
        it["start_seq"] = latest["start_seq"] if it["started"] else None
        abandon = it["abandon"]
        if not it["started"]:
            _need(not docks and abandon is None, "docking in an iteration that has not started")
            it["live"] = latest if latest["state"] == "waiting_start" else None
        elif latest["state"] == "running":
            _need(not docks and abandon is None, "docking before the model ended")
            it["live"] = latest
        elif latest["state"] == "failed" or branch == "ligand":
            _need(not docks and abandon is None, "docking after a failed model")
            _done(it, latest, latest["resolve_seq"])
        else:   # protein, model completed or reused
            model_seq = latest["resolve_seq"]
            _need(len(docks) <= 1 and not (docks and abandon), "one docking decision per iteration")
            for item in docks:
                _need(item["seq"] > model_seq and item["candidate_ref"] == latest["candidate_ref"],
                      "docking of the iteration's candidate after its model")
            if abandon is not None:
                _need(abandon[0] > model_seq and abandon[1]["candidate_ref"] == latest["candidate_ref"],
                      "abandoning the iteration's candidate after its model")
                it.update(done=True, done_seq=abandon[0], outcome="not_run")
            elif docks:
                dock = docks[0]
                if dock["state"] in _LIVE:
                    it["live"] = dock
                elif dock["state"] == "unavailable":
                    dock["reason_code"] = L.NOT_RUN_REASON
                    it.update(done=True, done_seq=dock["resolve_seq"], outcome="not_run")
                else:
                    _done(it, dock, dock["resolve_seq"])
        iterations[number] = it
    for earlier, later in pairwise(numbers):
        _need(iterations[earlier]["done"] and iterations[earlier]["done_seq"] < iterations[later]["firsts"][0]["seq"],
              "an iteration approved before the previous one ended")
    if ended is not None:
        _need(all(step["resolve_seq"] is not None and step["resolve_seq"] < ended[0] for step in steps),
              "the loop ended while an approved job could still run")
        _need(all(it["done"] or not it["started"] for it in iterations.values()),
              "the loop ended while a modelled candidate waited for docking")
    return iterations


def _done(it: dict[str, Any], step: dict[str, Any], seq: int) -> None:
    if step["state"] == "failed":
        it.update(done=True, done_seq=seq, outcome="failed")
        return
    outcome, score = _result_state(step["result"])
    it.update(done=True, done_seq=seq, outcome=outcome, result=step["result"], score=score)


def _candidate_need(branch: str, ref: Any, keys: Mapping[Any, Any], results: Mapping[str, Any]) -> dict[str, int]:
    """Spec 7: the whole iteration's need (ligand 1 unit / 300 s; protein 2 / 420, or 1 / 300 with a stored model)."""
    steps = (("ligand_dock",) if branch == "ligand" else ("dock",) if keys[ref]["model"] in results
             else ("model", "dock"))
    return {"expensive_units": L.UNITS_PER_STEP * len(steps),
            "wall_clock_s": sum(L.STEP_TIMEOUT_DEFAULTS_S[step] for step in steps)}


def _dock_need() -> dict[str, int]:
    return {"expensive_units": L.UNITS_PER_STEP, "wall_clock_s": L.STEP_TIMEOUT_DEFAULTS_S["dock"]}


def _blocked(need: Mapping[str, int], remaining: Mapping[str, Any]) -> list[str]:
    return [axis for axis in L.COMPUTE_AXES if need[axis] > remaining[axis]]


def derive_loop(loop_id: Any, events: Iterable[dict[str, Any]], *, jobs: Any, keys: Mapping[Any, Any],
                results: Mapping[str, Any], displays: Mapping[Any, Any], proposals: Mapping[str, Any],
                budget: Mapping[str, Any], send_reservation: Mapping[str, Any] | None = None,
                send_active: bool = False, approval_pending: bool = False) -> LoopState:
    """The ``jev_loop@1`` record of one loop from one snapshot (inputs: the module docstring). ``LoopNotFound`` when
    the run has no such loop, ``LoopRecordInvalid`` when its events break the closed shapes or orders, ``ValueError``
    when the caller's tables do not cover the pool."""
    events = events if isinstance(events, list) else list(events)
    (created_seq, created), approvals, abandons, ended = _loop_events(events, loop_id)
    branch, goal = created["branch"], created["goal"]
    kind = L.KIND_FOR_BRANCH[branch]
    pool = created["pool"]["candidates"]
    effective_cap = min(created["iteration_cap"], len(pool))
    _check_inputs(branch, pool, keys, results, displays, budget, send_reservation)
    by_key, timelines = _job_index(events, jobs)
    steps = [_step(seq, approval, by_key, timelines, results) for seq, approval in approvals]
    sends = _sends(events, loop_id, send_active)
    selections, late, info = _proposals(sends, proposals, kind, loop_id)
    iterations = _iterations(branch, pool, effective_cap, steps, abandons, selections, info, ended)
    started = sum(it["started"] for it in iterations.values())
    done = sum(it["done"] for it in iterations.values())
    in_progress = [it for it in iterations.values() if it["started"] and not it["done"]]
    if in_progress:
        current = in_progress[0]
        number = current["index"]
        phase = "running" if current["live"] is not None else "awaiting_docking"
    else:
        number = started + 1
        current = iterations.get(number)
        phase = ("running" if current is not None and current["live"] is not None else
                 "awaiting_compute" if number in selections else "awaiting_selection")
    for send in sends:
        _need(send["iteration"] <= number, "a send for an iteration that was never current")

    # candidates (spec 3.2 priority 1-4)
    held = {step["candidate_ref"] for step in steps if step["state"] in _LIVE}   # this loop's live steps
    ended_by = {it["latest"]["candidate_ref"]: it for it in iterations.values() if it["done"]}
    running_ref = in_progress[0]["latest"]["candidate_ref"] if in_progress else None
    rows, pending, needs, evaluation_reused = [], [], {}, 0
    for ref in pool:
        row = {"ref": ref, "display": copy.deepcopy(displays[ref]), "state": "pending", "evaluation": None,
               "score_kcal_mol": None, "iteration": None}
        stored = _stored(branch, keys[ref], results)
        if ref in ended_by:
            it = ended_by[ref]
            row.update(state=it["outcome"], evaluation="computed", score_kcal_mol=it.get("score"),
                       iteration=it["index"])
        elif ref == running_ref or ref in held:
            pass
        elif stored is not None:
            row.update(state=stored[0], evaluation="reused", score_kcal_mol=stored[1])
            evaluation_reused += 1
        elif _unusable(branch, keys[ref], results, by_key):
            row["state"] = "unavailable"
        if row["state"] == "pending":
            pending.append(ref)
            needs[ref] = _candidate_need(branch, ref, keys, results)
        rows.append(row)

    if started == effective_cap and done == started:
        exhausted = "iteration_cap"
    elif not pending:
        exhausted = "pool_exhausted"
    else:
        exhausted = None
    cancelled = run_cancel_seen(events)
    status = "ended" if ended is not None or cancelled else "active"
    end_reason = ended[1]["end_reason"] if ended is not None else "run_cancelled" if cancelled else None

    rest = {"expensive_units": max(0, budget["expensive_units"]),
            "wall_clock_s": math.floor(max(0, budget["wall_clock_s"])), "external_tokens": None, "usd": None,
            "sends": max(0, J.SEND_CAP - dispatch_count(events))}
    need = {"expensive_units": 0, "wall_clock_s": 0, "external_tokens": None, "usd": None, "sends": 0}
    out = {"iteration": None, "phase": None, "step": None, "action": "none", "needs": need, "remaining": rest,
           "blocked_axes": [], "send_blocked_axes": [], "can_end": False, "job": None}
    if status == "active" and exhausted is not None:
        out.update(action="end", can_end=not send_active)
    elif status == "active":
        action = _ACTION[phase]
        live = current["live"] if phase == "running" else None
        out.update(iteration=number, phase=phase, action=action, can_end=action in ("select", "compute")
                   and not send_active,
                   step=live["step"] if live else "dock" if phase == "awaiting_docking" else _FIRST_STEP[branch])
        if action in ("select", "compute"):
            least = min(needs.values(), key=lambda item: (item["expensive_units"], item["wall_clock_s"]))
            need.update(least)
        elif action == "dock":
            need.update(_dock_need())
        out["blocked_axes"] = _blocked(need, rest)
        if action == "select" and len(pending) >= L.MIN_PENDING_TO_SEND:
            need["sends"] = 1
            blocked = []
            if send_reservation is not None:
                need.update(external_tokens=send_reservation["external_tokens"], usd=send_reservation["usd"])
                rest.update(external_tokens=max(0, budget["external_tokens"]), usd=max(0, budget["usd"]))
                blocked = [axis for axis in ("external_tokens", "usd") if need[axis] > rest[axis]]
            out["send_blocked_axes"] = blocked + (["sends"] if rest["sends"] < 1 else [])
        if live is not None:
            job = live["job"]
            blocked_start = (job["status"] == "claimed" and job.get("blocked_reason") == _APPROVAL_BLOCK
                             and approval_pending)
            out["job"] = {"job_id": job["job_id"], "step": live["step"], "status": job["status"],
                          "start_blocked": L.START_BLOCKED if blocked_start else None}

    listed = sorted(set(iterations) | {send["iteration"] for send in sends})
    iteration_rows = [_iteration_row(n, iterations.get(n), [s for s in sends if s["iteration"] == n], info,
                                     number, phase) for n in listed]
    started_its = [it for it in iterations.values() if it["started"]]
    record = {
        "schema": L.LOOP_SCHEMA, "loop_id": loop_id, "branch": branch, "status": status, "end_reason": end_reason,
        "exhausted_reason": exhausted, "goal": goal, "loop_seed": created["loop_seed"],
        "iteration_cap": created["iteration_cap"], "effective_cap": effective_cap,
        "pool": {"source": dict(created["pool"]["source"]), "structure": copy.deepcopy(created["pool"]["structure"]),
                 "filter": copy.deepcopy(created["pool"]["filter"]),
                 "candidates": [{"ref": row["ref"], "display": copy.deepcopy(row["display"])} for row in rows]},
        "setup": copy.deepcopy(created["setup"]), "setup_sha256": created["setup_sha256"],
        "pins": copy.deepcopy(created["pins"]),
        "counts": {"started": started, "done": done,
                   "jev_decided": sum(it["latest"]["decided_by"] == "jev" for it in started_its),
                   "human_decided": sum(it["latest"]["decided_by"] == "human" for it in started_its),
                   "sends_dispatched": sum(send["dispatched"] for send in sends),
                   "units_charged": sum(step["state"] in ("running", "completed", "failed") for step in steps),
                   "reused_count": evaluation_reused},
        "candidates": rows, "iterations": iteration_rows, "current": out,
        "result_handle": ended[1]["result_handle"] if ended is not None else None,
        "limitations": [L.STATEMENTS[name] for name in L.limitation_ids(
            kind, goal, uncomputed_left=status == "ended" and any(row["state"] in ("pending", "unavailable")
                                                                  for row in rows))],
    }
    dispatched: dict[int, int] = {}
    for send in sends:
        dispatched[send["iteration"]] = dispatched.get(send["iteration"], 0) + send["dispatched"]
    return LoopState(record=record, created_seq=created_seq, branch=branch, cancelled=cancelled,
                     ended_event=ended is not None, current_number=number, current_phase=phase, started=started,
                     effective_cap=effective_cap, pending=tuple(pending), send_active=send_active,
                     approval_pending=approval_pending, selections=selections, late_proposals=late,
                     proposal_refs={handle: item["ref"] for handle, item in info.items()}, dispatched=dispatched,
                     candidate_needs=needs, steps=tuple(steps), keys=keys, results=results, remaining=dict(rest))


def _stored(branch: str, entry: Mapping[str, Any], results: Mapping[str, Any]) -> tuple[str, Any] | None:
    """Spec 3.2 2: ligand = its M18 result; protein = its model AND its mutant docking result."""
    if branch == "ligand":
        summary = results.get(entry["ligand_dock"])
    else:
        summary = results.get(entry["dock"]) if entry["model"] in results and entry["dock"] is not None else None
    return None if summary is None else _result_state(summary)


def _unusable(branch: str, entry: Mapping[str, Any], results: Mapping[str, Any], by_key: Mapping[str, Any]) -> bool:
    """Spec 3.2 3: a same-key job (of the next step to run) exists; a candidate this loop's live step holds never
    gets here."""
    key = entry["ligand_dock"] if branch == "ligand" else entry["model"] if entry["model"] not in results \
        else entry["dock"]
    job = by_key.get(key)
    return job is not None


def _iteration_row(number: int, it: dict[str, Any] | None, sends: list[dict[str, Any]],
                   info: Mapping[str, Any], current_number: int, current_phase: str) -> dict[str, Any]:
    if it is not None and it["done"]:
        phase = "done"
    else:
        _need(number == current_number, "an unfinished iteration that is not the current one")
        phase = current_phase
    latest = it["latest"] if it is not None else None
    chosen = info.get(latest["proposal_handle"]) if latest is not None and latest["decided_by"] == "jev" else None
    if it is None or not it["started"]:
        state = "unavailable" if latest is not None and latest["state"] == "unavailable" else "in_progress"
    else:
        state = it["outcome"] if it["done"] else "in_progress"
    steps = [] if it is None else sorted(it["firsts"] + it["docks"], key=lambda item: item["seq"])
    return {
        "index": number, "phase": phase,
        "decided_by": latest["decided_by"] if latest else None,
        "candidate_ref": latest["candidate_ref"] if latest else None,
        "proposal_handle": latest["proposal_handle"] if latest else None,
        "list_position": chosen["list_position"] if chosen else None,
        "list_size": chosen["list_size"] if chosen else None,
        "approvals": [{name: step[name] for name in APPROVAL_KEYS} for step in steps],
        "sends": [{name: send[name] for name in SEND_KEYS} for send in sends],
        "steps": [_step_row(step) for step in steps],
        "state": state, "score_kcal_mol": it.get("score") if it is not None and state == "scored" else None,
    }


def _step_row(step: dict[str, Any]) -> dict[str, Any]:
    state = step["state"]
    return {"step": step["step"], "candidate_ref": step["candidate_ref"],
            "job_id": step["job"]["job_id"] if step["job"] is not None and state != "reused" else None,
            "call_key": step["call_key"],
            "result_handle": step["result"]["result_handle"] if state in ("completed", "reused") else None,
            "state": state, "reason_code": step["reason_code"],
            "evaluation": "reused" if state == "reused" else "computed" if state in ("running", "completed",
                                                                                     "failed") else None}


# --- refusal helpers shared by the projection tool, the send check, compute and end -------------------------------

def selection_refusal(state: LoopState, iteration: Any) -> str | None:
    """The loop-state refusals spec 4.1 (projection tool) and 5.1 (loop send check) share, in their common order
    (``loop_not_found`` is the caller's lookup): loop_ended, iteration_mismatch, selection_done, phase_invalid,
    cap_reached, too_few_candidates; None when a send may be prepared for ``iteration``."""
    if state.record["status"] == "ended":
        return "loop_ended"
    if type(iteration) is not int or iteration != state.started + 1:
        return "iteration_mismatch"
    if iteration in state.selections:
        return "selection_done"
    if state.current_number != iteration or state.current_phase != "awaiting_selection":
        return "phase_invalid"
    if state.started >= state.effective_cap:
        return "cap_reached"
    if len(state.pending) < L.MIN_PENDING_TO_SEND:
        return "too_few_candidates"
    return None


def send_ordinal(state: LoopState, iteration: int) -> int:
    """Spec 4.2: the dispatched sends of this loop's ``iteration`` (from 0)."""
    return state.dispatched.get(iteration, 0)


def _refused(reason: str, **detail: Any) -> dict[str, Any]:
    return {"outcome": "refused", "reason_code": reason, "http_status": COMPUTE_HTTP[reason], "detail": detail}


def compute_admission(state: LoopState, *, iteration: Any, proposal: Any = None, candidate: Any = None,
                      capability_available: bool) -> dict[str, Any]:
    """Spec 6.1 from ``cancelled`` to ``budget_blocked`` (the request shape / unknown_field, the loop lookup and the
    M18 / M21 job admission are the route's). ``proposal`` / ``candidate``: at most one, both None for the docking
    step. Returns {"outcome": "refused", reason_code, http_status, detail}, {"outcome": "idempotent", job_id, start}
    (no new event or job; ``start`` = call ``JobQueue.start``) or {"outcome": "approve", iteration, step,
    candidate_ref, decided_by, proposal_handle, call_key, units, reuse, needs} (the approval event to write; ``reuse``
    = adopt the stored model, no job)."""
    if proposal is not None and candidate is not None:
        raise ValueError("a compute request names a proposal or a candidate, not both")
    if state.cancelled:
        return _refused("cancelled")
    if state.ended_event:
        return _refused("loop_ended")
    if state.send_active:
        return _refused("send_in_progress")
    if type(iteration) is not int or iteration != state.current_number:
        return _refused("iteration_invalid")
    first = proposal is not None or candidate is not None
    step_name = _FIRST_STEP[state.branch] if first else "dock"
    idempotent = _idempotent(state, iteration, step_name, proposal, candidate)
    if idempotent is not None:
        return idempotent
    if first:
        if state.current_phase not in ("awaiting_selection", "awaiting_compute"):
            return _refused("phase_invalid")
        if state.started >= state.effective_cap:
            return _refused("iteration_cap_reached")
        if proposal is not None:
            if proposal == state.selections.get(iteration):
                ref, decided_by = state.proposal_refs[proposal], "jev"
            elif proposal in state.late_proposals.get(iteration, frozenset()):
                return _refused("proposal_late")
            else:
                return _refused("proposal_invalid")
        else:
            ref, decided_by = candidate, "human"
        rows = {row["ref"]: row for row in state.record["candidates"]}
        if not _is_ref(ref, state.branch) or ref not in rows:
            return _refused("candidate_invalid")
        if rows[ref]["state"] == "unavailable":
            return _refused("candidate_unavailable")
        if rows[ref]["state"] != "pending":
            return _refused("candidate_computed")
        need = dict(state.candidate_needs[ref])
    else:
        if state.branch != "protein" or state.current_phase != "awaiting_docking":
            return _refused("phase_invalid")
        latest = [step for step in state.steps if step["iteration"] == iteration and step["step"] == "model"][-1]
        ref, decided_by, need = latest["candidate_ref"], "human", _dock_need()
    if not capability_available:
        return _refused("capability_unavailable")
    blocked = _blocked(need, state.remaining)
    if blocked:
        return _refused("budget_blocked", blocked_axes=blocked, needs=need)
    call_key = state.keys[ref][step_name]
    if call_key is None:
        raise ValueError("the docking key of a modelled candidate is missing")
    reuse = step_name == "model" and call_key in state.results
    return {"outcome": "approve", "iteration": iteration, "step": step_name, "candidate_ref": ref,
            "decided_by": decided_by, "proposal_handle": proposal if decided_by == "jev" else None,
            "call_key": call_key, "units": 0 if reuse else L.UNITS_PER_STEP, "reuse": reuse, "needs": need}


def _idempotent(state: LoopState, iteration: int, step_name: str, proposal: Any,
                candidate: Any) -> dict[str, Any] | None:
    """Spec 6.1: the same step again with the arguments of its latest approval, whose job is not lost before start."""
    own = [step for step in state.steps if step["iteration"] == iteration and step["step"] == step_name]
    if not own:
        return None
    latest = own[-1]
    if proposal is not None:
        same = latest["decided_by"] == "jev" and latest["proposal_handle"] == proposal
    elif candidate is not None:
        same = (latest["decided_by"] == "human" and latest["candidate_ref"] == candidate
                and type(latest["candidate_ref"]) is type(candidate))
    else:
        same = True
    if not same or latest["state"] == "unavailable":
        return None
    job = latest["job"]
    start = latest["state"] == "waiting_start" and job is not None and (
        job["status"] == "queued" or (job["status"] == "claimed" and job.get("blocked_reason") == _APPROVAL_BLOCK
                                      and state.approval_pending))
    return {"outcome": "idempotent", "job_id": None if job is None or latest["state"] == "reused" else job["job_id"],
            "start": start}


def end_refusal(state: LoopState) -> str | None:
    """Spec 8.1 after ``loop_not_found``: cancelled, loop_ended, send_in_progress, job_running, docking_pending."""
    if state.cancelled:
        return "cancelled"
    if state.ended_event:
        return "loop_ended"
    if state.send_active:
        return "send_in_progress"
    if state.current_phase == "running":
        return "job_running"
    if state.current_phase == "awaiting_docking":
        return "docking_pending"
    return None


def end_reason_for(state: LoopState) -> str:
    """Spec 8.1: exhausted_reason, else budget_exhausted when the compute side is blocked, else ended_by_user. Only
    for a loop that may end now (``end_refusal`` None); ValueError otherwise."""
    if end_refusal(state) is not None:
        raise ValueError("this loop cannot end now")
    record = state.record
    if record["exhausted_reason"] is not None:
        return record["exhausted_reason"]
    return "budget_exhausted" if record["current"]["blocked_axes"] else "ended_by_user"


def list_row(state: LoopState) -> dict[str, Any]:
    record = state.record
    return {"loop_id": record["loop_id"], "branch": record["branch"], "status": record["status"],
            "end_reason": record["end_reason"], "goal": record["goal"], "pool_size": len(record["candidates"]),
            "counts": dict(record["counts"]), "created_seq": state.created_seq}


def list_rows(states: Iterable[LoopState]) -> list[dict[str, Any]]:
    """``GET /runs/{rid}/jev_loops`` rows, newest first (by the created event's seq)."""
    return [list_row(state) for state in sorted(states, key=lambda item: item.created_seq, reverse=True)]
