"""M25 T2 pure loop-record derivation in ``mw.jev_loops`` (spec .dryforge/spec.md 3.2, 3.3, 5.1, 5.3, 6.1, 6.3-6.5,
7, 8.1, 9.3).

Every input here is LABELLED SYNTHETIC: event lists shaped like the real ones measured in M25 T1 (preflight (a):
``job_submitted {job}``, ``budget_reserved {attempt_id, root_call_id = job_id, tool, expensive_calls}``,
``job_terminal {job_id, status, attempt_id, failure, output_handles}``; the M24 send events as ``jev_sends`` writes
them), made-up candidate ids / indexes, call keys (SHA-256 of a label), handles, budgets and score numbers. They stand
in for a run's log; none is a result. The expected values are written by hand from the spec rule quoted next to each
case, never by running the module. ``jev_sends`` is imported here only to compare its M24 event functions with the
loop module's pure copies (the loop module itself never imports it).
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest

from mw import docking_constants as DC
from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loops as JL
from mw import jev_sends as S
from mw import mutation_model_constants as MC
from mw.core.handles import canonical_json

MW = Path(__file__).resolve().parents[1] / "mw"
RUN_ID = "run_m25_t2b"
LOOP = "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b"
OTHER = "0b5e6a7c-1d2e-4f30-9a4b-5c6d7e8f9a0b"
IDS = [f"c_{n:016x}" for n in range(1, 7)]      # SYNTHETIC M17 candidate ids
INDEXES = [3, 7, 11, 19]                         # SYNTHETIC M20 candidate indexes
BUDGET = {"expensive_units": 8, "wall_clock_s": 1800.0, "external_tokens": 120000, "usd": 2.0}
PROTOCOL = {"ligand_dock": DC.PROTOCOL, "dock": DC.PROTOCOL, "model": MC.PROTOCOL}
ZERO_NEEDS = {"expensive_units": 0, "wall_clock_s": 0, "external_tokens": None, "usd": None, "sends": 0}


def label_sha(*parts) -> str:
    return hashlib.sha256(":".join(str(part) for part in ("SYNTHETIC", *parts)).encode()).hexdigest()


def key(ref, step) -> str:
    """SYNTHETIC call key of (candidate, step)."""
    return label_sha("call_key", ref, step)


def handle(kind, *tag) -> str:
    return f"obj://{RUN_ID}/{kind}/{label_sha(kind, *tag)}"


def docked(ref, modes, score, step="ligand_dock"):
    """SYNTHETIC validated M18 result summary keyed by the candidate's call key."""
    return {key(ref, step): {"result_handle": handle("docking_result", ref, step), "mode_count": modes,
                             "score_kcal_mol": score}}


def modelled(ref):
    """SYNTHETIC validated M21 model summary keyed by the candidate's model call key."""
    return {key(ref, "model"): {"result_handle": handle("mutation_model_result", ref)}}


def remaining(units=8, wall=1800, sends=10, tokens=None, usd=None):
    return {"expensive_units": units, "wall_clock_s": wall, "external_tokens": tokens, "usd": usd, "sends": sends}


class Log:
    """A SYNTHETIC event log builder (seq from 1, envelope {seq, ts, type} as ``EventLog.append``)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.proposals: dict[str, dict] = {}
        self.attempts: dict[str, str] = {}
        self.add("run_started", run_id=RUN_ID)

    def add(self, type_, **data) -> dict:
        event = {"seq": len(self.events) + 1, "ts": 1000.0 + len(self.events), "type": type_, **data}
        self.events.append(event)
        return event

    # --- loop events
    def created(self, branch="ligand", pool=None, *, goal="exploit", seed=7, cap=5, loop_id=LOOP, filter_=None):
        pool = list(IDS[:4] if pool is None and branch == "ligand" else INDEXES if pool is None else pool)
        kind = L.KIND_FOR_BRANCH[branch]
        setup = {"synthetic": "M25 T2 test setup, not a real one", "branch": branch, "seed": 20261007}
        structure = None if branch == "ligand" else {"handle": handle("prepared_structure", "s"), "model_number": 1}
        return self.add(L.EVENT_CREATED, loop_id=loop_id, branch=branch,
                        pool={"source": {"handle": handle(J.SOURCE_STORE_KINDS[kind], "set"),
                                         "schema": J.SOURCE_SCHEMAS[kind]},
                              "structure": structure, "candidates": pool, "filter": filter_},
                        goal=goal, loop_seed=seed, iteration_cap=cap, setup=setup,
                        setup_sha256=hashlib.sha256(canonical_json(setup)).hexdigest(), pins={"synthetic": True})

    def approve(self, n, ref, step="ligand_dock", *, by="human", proposal=None, units=1, loop_id=LOOP):
        return self.add(L.EVENT_COMPUTE_APPROVED, loop_id=loop_id, iteration=n, step=step, candidate_ref=ref,
                        decided_by=by, proposal_handle=proposal, call_key=key(ref, step), units=units,
                        approved_by="human")

    def abandon(self, n, ref, loop_id=LOOP):
        return self.add(L.EVENT_DOCKING_ABANDONED, loop_id=loop_id, iteration=n, candidate_ref=ref)

    def ended(self, reason="ended_by_user", loop_id=LOOP):
        result = handle(L.RESULT_KIND, loop_id)
        self.add(L.EVENT_ENDED, loop_id=loop_id, end_reason=reason, result_handle=result)
        return result

    # --- jobs
    def submit(self, ref, step="ligand_dock") -> str:
        job_id = "job_" + label_sha("job", len(self.events))[:32]
        self.add("job_submitted", job={"job_id": job_id, "run_id": RUN_ID, "root_call_id": job_id,
                                       "protocol_id": PROTOCOL[step], "tool_id": PROTOCOL[step],
                                       "call_key": key(ref, step), "timeout_s": L.STEP_TIMEOUT_DEFAULTS_S[step]})
        return job_id

    def claim(self, job_id, blocked=None):
        self.add("job_claimed", job_id=job_id, owner_token="owner_synthetic")
        if blocked:
            self.add("job_blocked", job_id=job_id, reason=blocked)

    def reserve(self, job_id):
        attempt = "att_" + label_sha("attempt", len(self.events))[:24]
        self.attempts[job_id] = attempt
        self.add("budget_reserved", attempt_id=attempt, root_call_id=job_id, tool="synthetic_tool", expensive_calls=1)

    def dispatch(self, job_id):
        self.add("job_dispatch_intent", job_id=job_id, attempt_id=self.attempts[job_id], ordinal=1)

    def terminal(self, job_id, status, failure=None, charged=True):
        attempt = self.attempts.get(job_id) if charged else None
        outputs = [handle("synthetic_output", job_id)] if status == "done" else []
        self.add("job_terminal", job_id=job_id, status=status, attempt_id=attempt, failure=failure,
                 output_handles=outputs)

    def cancel(self, job_id):
        self.add("job_cancel_requested", job_id=job_id)
        self.terminal(job_id, "cancelled", charged=False)

    def retry(self, job_id):
        self.attempts.pop(job_id, None)
        self.add("job_retry_queued", job_id=job_id)

    def run_job(self, ref, step="ligand_dock", end="done", failure=None) -> str:
        """submit -> claim -> reserve -> dispatch -> (terminal ``end`` | still running when ``end`` is None)."""
        job_id = self.submit(ref, step)
        self.start(job_id, end, failure)
        return job_id

    def start(self, job_id, end="done", failure=None):
        self.claim(job_id)
        self.reserve(job_id)
        self.dispatch(job_id)
        if end is not None:
            self.terminal(job_id, end, failure)

    # --- run and science events
    def cancel_run(self):
        self.add("cancel_requested")

    def consent(self, enabled, policy=J.CONSENT_POLICY):
        self.add(J.EVENT_CONSENT, enabled=enabled, policy=policy, send_cap=J.SEND_CAP)

    def projection(self, n, ordinal, loop_id=LOOP) -> str:
        proj = handle(L.PROJECTION_KIND, loop_id, n, ordinal, len(self.events))
        content = {"loop": {"loop_id": loop_id, "iteration": n, "send_ordinal": ordinal},
                   "synthetic": "M25 T2 test projection; only its loop reference is read"}
        self.add("object_created", handle=proj, kind=L.PROJECTION_KIND, schema=L.PROJECTION_SCHEMA, fmt="json",
                 payload_b64=base64.b64encode(json.dumps(content).encode()).decode(), summary={}, produced_by=None,
                 null_result=False)
        return proj

    def send(self, n, ordinal=0, *, ref=None, status="completed", late=False, dispatched=True, position=1, size=3,
             loop_id=LOOP, projection=None):
        """One loop send. ``late`` turns consent off between the dispatch and the outcome (the M24 late order);
        ``status`` None leaves the outcome out (in flight or lost). Returns (send_id, proposal handle | None)."""
        proj = projection or self.projection(n, ordinal, loop_id)
        send_id = str(uuid.UUID(label_sha("send", len(self.events))[:32], version=4))
        self.add(J.EVENT_APPROVED, send_id=send_id, projection_handle=proj, body_sha256=label_sha("body", send_id),
                 question_id=L.LIGAND_QUESTION_ID, source_handle=handle("ligand_candidate_set", "set"),
                 selection_count=4, approved_by="human")
        audit = "eg_" + label_sha("audit", send_id)[:32]
        if dispatched:
            self.add(J.EVENT_DISPATCH, send_id=send_id, audit_id=audit)
        if late:
            self.consent(False)
        choice = None
        if status is not None:
            if status == "completed":
                choice = handle(L.CHOICE_KIND, send_id)
                local = {"candidate_id": ref} if type(ref) is str else {"candidate_index": ref, "position_index": 0}
                self.proposals[choice] = {
                    "schema": L.CHOICE_SCHEMA, "loop": {"loop_id": loop_id, "iteration": n, "send_ordinal": ordinal},
                    "send": {"send_id": send_id, "audit_id": audit},
                    "answer": {"choice_alias": "c01", "list_position": position, "list_size": size, "local_ref": local,
                               "local_display": {"smiles": "C"}, "confidence": None, "probabilities": None},
                    "arrival": {"late": late, "late_reason": "consent_off" if late else None}}
            reason = {"completed": None, "rejected": "consent_off", "failed": "provider_http_error"}[status]
            self.add(J.EVENT_OUTCOME, send_id=send_id, status=status, reason_code=reason,
                     audit_id=audit if dispatched else None, requested_model=J.REQUEST_MODEL,
                     served_model=J.SERVED_SNAPSHOT if status == "completed" else None, choice_handle=choice,
                     usage=None, late=late, late_reason="consent_off" if late else None)
        return send_id, choice


def fold_jobs(events) -> dict[str, dict]:
    """Hand-written stand-in for ``JobQueue._state()`` (only the fields the loop reads)."""
    jobs: dict[str, dict] = {}
    for event in events:
        kind = event["type"]
        if kind == "job_submitted":
            jobs[event["job"]["job_id"]] = {**event["job"], "status": "queued", "blocked_reason": None}
        elif kind == "job_claimed":
            jobs[event["job_id"]]["status"] = "claimed"
        elif kind == "job_blocked":
            jobs[event["job_id"]]["blocked_reason"] = event["reason"]
        elif kind == "job_dispatch_intent":
            jobs[event["job_id"]].update(status="running", blocked_reason=None)
        elif kind == "job_terminal":
            jobs[event["job_id"]]["status"] = event["status"]
        elif kind == "job_retry_queued":
            jobs[event["job_id"]]["status"] = "queued"
    return jobs


def display(branch, number, ref):
    if branch == "ligand":
        return {"smiles": "C" * (number + 1)}
    return {"residue": {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": ref, "seq_label": ref,
                        "icode": "", "resname": "ILE"}, "from": "ILE", "to": "TRP"}


def derive(log, *, results=None, budget=None, reservation=None, send_active=False, approval_pending=False,
           loop_id=LOOP, keys=None):
    created = next(e for e in log.events if e["type"] == L.EVENT_CREATED and e["loop_id"] == loop_id)
    branch, pool = created["branch"], created["pool"]["candidates"]
    results = {} if results is None else results
    if keys is None:
        keys = ({ref: {"ligand_dock": key(ref, "ligand_dock")} for ref in pool} if branch == "ligand" else
                {ref: {"model": key(ref, "model"), "dock": key(ref, "dock") if key(ref, "model") in results else None}
                 for ref in pool})
    return JL.derive_loop(loop_id, log.events, jobs=list(fold_jobs(log.events).values()), keys=keys, results=results,
                          displays={ref: display(branch, n, ref) for n, ref in enumerate(pool)},
                          proposals=log.proposals, budget=BUDGET if budget is None else budget,
                          send_reservation=reservation, send_active=send_active, approval_pending=approval_pending)


def states(state) -> dict:
    return {row["ref"]: row["state"] for row in state.record["candidates"]}


def candidate(state, ref) -> dict:
    return next(row for row in state.record["candidates"] if row["ref"] == ref)


def counts(**values) -> dict:
    return {name: values.get(name, 0) for name in JL.COUNT_KEYS}


# ---------------------------------------------------------------- the record of a fresh loop


def test_fresh_ligand_loop_record():
    log = Log()
    log.created()
    record = derive(log).record
    assert list(record) == list(JL.RECORD_KEYS)
    assert record["schema"] == "jev_loop@1" and record["loop_id"] == LOOP and record["branch"] == "ligand"
    assert (record["status"], record["end_reason"], record["exhausted_reason"]) == ("active", None, None)
    assert (record["goal"], record["loop_seed"], record["iteration_cap"]) == ("exploit", 7, 5)
    assert record["effective_cap"] == 4                       # min(iteration_cap 5, pool size 4)
    assert record["pool"] == {"source": {"handle": handle("ligand_candidate_set", "set"),
                                         "schema": "ligand_candidate_set@1"},
                              "structure": None, "filter": None,
                              "candidates": [{"ref": ref, "display": {"smiles": "C" * (n + 1)}}
                                             for n, ref in enumerate(IDS[:4])]}
    created = log.events[1]
    assert record["setup"] == created["setup"] and record["setup_sha256"] == created["setup_sha256"]
    assert record["pins"] == {"synthetic": True}
    assert record["counts"] == counts()
    assert record["candidates"] == [{"ref": ref, "display": {"smiles": "C" * (n + 1)}, "state": "pending",
                                     "evaluation": None, "score_kcal_mol": None, "iteration": None}
                                    for n, ref in enumerate(IDS[:4])]
    assert record["iterations"] == []
    assert record["current"] == {
        "iteration": 1, "phase": "awaiting_selection", "step": "ligand_dock", "action": "select",
        "needs": {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": None, "usd": None, "sends": 1},
        "remaining": remaining(), "blocked_axes": [], "send_blocked_axes": [], "can_end": True, "job": None}
    assert record["result_handle"] is None
    assert record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ6]   # exploit, ligand, not ended


def test_fresh_protein_loop_record_explore():
    log = Log()
    log.created("protein", goal="explore", cap=8)
    record = derive(log).record
    assert record["effective_cap"] == 4
    assert record["pool"]["structure"] == {"handle": handle("prepared_structure", "s"), "model_number": 1}
    assert record["current"]["step"] == "model"
    # spec 7: protein iteration = model 120 s + dock 300 s, 2 units, when no candidate has a stored model
    assert record["current"]["needs"] == {"expensive_units": 2, "wall_clock_s": 420, "external_tokens": None,
                                          "usd": None, "sends": 1}
    assert record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ5, L.LJ7]


# ---------------------------------------------------------------- candidate state priority (spec 3.2 1-4)


def _outside_job(log, ref, status):
    """A job with the candidate's call key, made outside any loop, left in ``status``."""
    if status == "queued":
        log.submit(ref)
    elif status == "claimed":
        job = log.submit(ref)
        log.claim(job, blocked="approval_or_cancel")
    elif status == "running":
        log.run_job(ref, end=None)
    elif status == "failed":
        log.run_job(ref, end="failed", failure={"error": "fatal", "message": "x", "reason_code": "engine_failed"})
    elif status == "cancelled":
        log.cancel(log.submit(ref))
    elif status == "interrupted":
        job = log.submit(ref)
        log.claim(job, blocked="approval_or_cancel")
        log.terminal(job, "interrupted", failure={"error": "interrupted", "message": "claim owner lost"},
                     charged=False)
    elif status == "done_unvalidated":
        log.run_job(ref)   # done, but its result is not in ``results`` (it does not validate)


@pytest.mark.parametrize("status", ["queued", "claimed", "running", "failed", "cancelled", "interrupted",
                                    "done_unvalidated"])
def test_priority_stored_result_then_unusable_job_then_pending(status):
    log = Log()
    log.run_job(IDS[0])                      # outside, done, validated: 3 modes
    log.run_job(IDS[1])                      # outside, done, validated: no mode
    _outside_job(log, IDS[2], status)        # outside, unusable
    log.run_job(IDS[4])                      # outside, done, not validated -> unusable job
    log.created(pool=IDS[:6])
    results = {**docked(IDS[0], 3, -7.25), **docked(IDS[1], 0, None), **docked(IDS[3], 2, -6.5)}  # IDS[3]: a batch
    state = derive(log, results=results, reservation={"external_tokens": 9000, "usd": 0.1})
    # spec 3.2: 2 stored validated result -> reused (scored / null_result by the mode count); 3 no stored result and a
    # same-key job in an unusable state (outside job of any status, a done job whose result does not validate) ->
    # unavailable; 4 pending. A stored result made by another producer (no job with the key) is reused too.
    assert state.record["candidates"] == [
        {"ref": IDS[0], "display": {"smiles": "C"}, "state": "scored", "evaluation": "reused",
         "score_kcal_mol": -7.25, "iteration": None},
        {"ref": IDS[1], "display": {"smiles": "CC"}, "state": "null_result", "evaluation": "reused",
         "score_kcal_mol": None, "iteration": None},
        {"ref": IDS[2], "display": {"smiles": "CCC"}, "state": "unavailable", "evaluation": None,
         "score_kcal_mol": None, "iteration": None},
        {"ref": IDS[3], "display": {"smiles": "CCCC"}, "state": "scored", "evaluation": "reused",
         "score_kcal_mol": -6.5, "iteration": None},
        {"ref": IDS[4], "display": {"smiles": "CCCCC"}, "state": "unavailable", "evaluation": None,
         "score_kcal_mol": None, "iteration": None},
        {"ref": IDS[5], "display": {"smiles": "CCCCCC"}, "state": "pending", "evaluation": None,
         "score_kcal_mol": None, "iteration": None}]
    assert state.record["counts"] == counts(reused_count=3)
    assert state.record["exhausted_reason"] is None           # one pending candidate is left
    current = state.record["current"]
    # spec 3.3: one pending candidate or none -> no send is offered (the send side is not judged)
    assert (current["action"], current["needs"]["sends"], current["send_blocked_axes"]) == ("select", 0, [])
    assert current["needs"]["external_tokens"] is None and current["remaining"]["external_tokens"] is None


def test_unusable_job_turns_into_reused_once_its_result_is_stored():
    log = Log()
    job = log.submit(IDS[1])
    log.claim(job, blocked="approval_or_cancel")
    log.terminal(job, "interrupted", failure={"error": "interrupted", "message": "claim owner lost"}, charged=False)
    log.created()
    assert states(derive(log))[IDS[1]] == "unavailable"
    log.retry(job)                                           # outside the loop
    log.start(job)                                           # -> done
    # spec 3.2 3: "그 작업이 나중에 끝나 결과가 저장되면 다음 읽기에서 2가 되어 다시 reused"
    assert candidate(derive(log, results=docked(IDS[1], 1, -5.0)), IDS[1]) == {
        "ref": IDS[1], "display": {"smiles": "CC"}, "state": "scored", "evaluation": "reused",
        "score_kcal_mol": -5.0, "iteration": None}
    # a stored result that does not validate is left out by the caller and never counts as computed
    assert states(derive(log))[IDS[1]] == "unavailable"


def test_a_candidate_ended_by_the_loop_keeps_its_result_after_an_outside_retry():
    log = Log()
    log.created()
    log.approve(1, IDS[0])
    job = log.run_job(IDS[0], end="failed",
                      failure={"error": "fatal", "message": "x", "reason_code": "engine_failed"})
    before = derive(log)
    assert candidate(before, IDS[0]) == {"ref": IDS[0], "display": {"smiles": "C"}, "state": "failed",
                                         "evaluation": "computed", "score_kcal_mol": None, "iteration": 1}
    log.retry(job)                                           # outside the loop: queued -> charged -> done
    log.start(job)
    after = derive(log, results=docked(IDS[0], 3, -8.0))
    # spec 3.2 1 / 6.5: a candidate the loop ended keeps that result; an outside retry does not change it
    assert candidate(after, IDS[0]) == candidate(before, IDS[0])
    step = after.record["iterations"][0]["steps"][0]
    assert (step["state"], step["reason_code"], step["job_id"], step["result_handle"]) == (
        "failed", "engine_failed", job, None)
    assert after.record["iterations"][0]["state"] == "failed"
    assert after.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)


# ---------------------------------------------------------------- ligand phases and the six step states


def test_ligand_iteration_walks_selection_compute_running_done():
    log = Log()
    log.created()
    send_id, choice = log.send(1, 0, ref=IDS[2], position=2, size=4)
    state = derive(log)
    # spec 3.3: a first completed, not-late proposal and no live job -> awaiting_compute
    assert state.record["iterations"] == [{
        "index": 1, "phase": "awaiting_compute", "decided_by": None, "candidate_ref": None, "proposal_handle": None,
        "list_position": None, "list_size": None, "approvals": [],
        "sends": [{"send_id": send_id, "status": "completed", "send_ordinal": 0, "proposal_handle": choice,
                   "late": False}],
        "steps": [], "state": "in_progress", "score_kcal_mol": None}]
    assert state.record["current"] == {
        "iteration": 1, "phase": "awaiting_compute", "step": "ligand_dock", "action": "compute",
        "needs": {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": None, "usd": None, "sends": 0},
        "remaining": remaining(sends=9), "blocked_axes": [], "send_blocked_axes": [], "can_end": True, "job": None}
    assert state.record["counts"] == counts(sends_dispatched=1)

    log.approve(1, IDS[2], by="jev", proposal=choice)
    job = log.submit(IDS[2])
    log.claim(job, blocked="approval_or_cancel")
    for pending, blocked in ((True, "approval_required"), (False, None)):
        state = derive(log, approval_pending=pending)
        # spec 3.3 / 6.4: an approved job in the queue -> step waiting_start, phase running; not yet started
        assert state.record["current"] == {
            "iteration": 1, "phase": "running", "step": "ligand_dock", "action": "wait_job", "needs": ZERO_NEEDS,
            "remaining": remaining(sends=9), "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
            "job": {"job_id": job, "step": "ligand_dock", "status": "claimed", "start_blocked": blocked}}
    iteration = state.record["iterations"][0]
    assert (iteration["phase"], iteration["decided_by"], iteration["candidate_ref"], iteration["proposal_handle"],
            iteration["list_position"], iteration["list_size"], iteration["state"]) == (
        "running", "jev", IDS[2], choice, 2, 4, "in_progress")
    assert iteration["approvals"] == [{"step": "ligand_dock", "candidate_ref": IDS[2], "decided_by": "jev",
                                       "proposal_handle": choice, "call_key": key(IDS[2], "ligand_dock")}]
    assert iteration["steps"] == [{"step": "ligand_dock", "candidate_ref": IDS[2], "job_id": job,
                                   "call_key": key(IDS[2], "ligand_dock"), "result_handle": None,
                                   "state": "waiting_start", "reason_code": None, "evaluation": None}]
    assert state.record["counts"] == counts(sends_dispatched=1)              # not started: nothing charged
    assert states(state)[IDS[2]] == "pending"                                # the loop's own live job

    log.reserve(job)
    log.dispatch(job)
    state = derive(log)
    # spec 3.3: the iteration starts when its first step is charged (the reservation)
    assert state.record["iterations"][0]["steps"][0]["state"] == "running"
    assert state.record["iterations"][0]["steps"][0]["evaluation"] == "computed"
    assert state.record["counts"] == counts(started=1, jev_decided=1, sends_dispatched=1, units_charged=1)
    assert state.record["current"]["job"] == {"job_id": job, "step": "ligand_dock", "status": "running",
                                              "start_blocked": None}
    assert candidate(state, IDS[2])["iteration"] is None                    # pending: null (spec 3.2)

    log.terminal(job, "done")
    state = derive(log, results=docked(IDS[2], 2, -9.5))
    assert candidate(state, IDS[2]) == {"ref": IDS[2], "display": {"smiles": "CCC"}, "state": "scored",
                                        "evaluation": "computed", "score_kcal_mol": -9.5, "iteration": 1}
    iteration = state.record["iterations"][0]
    assert (iteration["phase"], iteration["state"], iteration["score_kcal_mol"]) == ("done", "scored", -9.5)
    assert iteration["steps"][0]["state"] == "completed"
    assert iteration["steps"][0]["result_handle"] == handle("docking_result", IDS[2], "ligand_dock")
    assert state.record["counts"] == counts(started=1, done=1, jev_decided=1, sends_dispatched=1, units_charged=1)
    current = state.record["current"]
    assert (current["iteration"], current["phase"], current["action"], current["needs"]["sends"]) == (
        2, "awaiting_selection", "select", 1)


def test_cancel_before_start_makes_the_candidate_unavailable_and_keeps_every_approval():
    log = Log()
    log.created()
    _, choice = log.send(1, 0, ref=IDS[1])
    log.approve(1, IDS[1], by="jev", proposal=choice)
    first_job = log.submit(IDS[1])
    log.cancel(first_job)
    state = derive(log)
    # spec 3.3 / 6.4: cancelled before the process -> unavailable, the iteration does not start; with a proposal the
    # phase goes back to awaiting_compute
    assert states(state)[IDS[1]] == "unavailable"
    assert state.record["counts"]["started"] == 0
    iteration = state.record["iterations"][0]
    assert (iteration["phase"], iteration["state"]) == ("awaiting_compute", "unavailable")
    assert iteration["steps"][0]["state"] == "unavailable" and iteration["steps"][0]["job_id"] == first_job
    assert state.record["current"]["action"] == "compute"
    for request in ({"proposal": choice}, {"candidate": IDS[1]}):
        assert JL.compute_admission(state, iteration=1, capability_available=True,
                                    **request)["reason_code"] == "candidate_unavailable"

    log.approve(1, IDS[3])
    log.run_job(IDS[3])
    state = derive(log, results=docked(IDS[3], 0, None))
    iteration = state.record["iterations"][0]
    # spec 3.2: approvals[] all in time order; candidate_ref / decided_by / proposal_handle of the latest first step
    assert iteration["approvals"] == [
        {"step": "ligand_dock", "candidate_ref": IDS[1], "decided_by": "jev", "proposal_handle": choice,
         "call_key": key(IDS[1], "ligand_dock")},
        {"step": "ligand_dock", "candidate_ref": IDS[3], "decided_by": "human", "proposal_handle": None,
         "call_key": key(IDS[3], "ligand_dock")}]
    assert (iteration["decided_by"], iteration["candidate_ref"], iteration["proposal_handle"],
            iteration["list_position"], iteration["list_size"]) == ("human", IDS[3], None, None, None)
    assert [(step["candidate_ref"], step["state"]) for step in iteration["steps"]] == [
        (IDS[1], "unavailable"), (IDS[3], "completed")]
    assert (iteration["phase"], iteration["state"], iteration["score_kcal_mol"]) == ("done", "null_result", None)
    assert states(state) == {IDS[0]: "pending", IDS[1]: "unavailable", IDS[2]: "pending", IDS[3]: "null_result"}
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, sends_dispatched=1, units_charged=1)


def test_interrupted_before_start_without_a_proposal_goes_back_to_awaiting_selection():
    log = Log()
    log.created()
    log.approve(1, IDS[0])
    job = log.submit(IDS[0])
    log.claim(job, blocked="approval_or_cancel")
    log.terminal(job, "interrupted", failure={"error": "interrupted", "message": "claim owner lost"}, charged=False)
    state = derive(log)
    assert state.record["iterations"][0]["phase"] == "awaiting_selection"
    assert state.record["iterations"][0]["state"] == "unavailable"
    assert state.record["current"]["phase"] == "awaiting_selection"
    assert states(state)[IDS[0]] == "unavailable"


def test_charged_then_cancelled_before_dispatch_is_a_started_failed_step():
    log = Log()
    log.created()
    log.approve(1, IDS[0])
    job = log.submit(IDS[0])
    log.claim(job)
    log.reserve(job)
    log.add("job_cancel_requested", job_id=job)
    log.terminal(job, "cancelled", charged=False)         # attempt None, but the reservation was charged (T1 (a) 5)
    state = derive(log)
    # spec 6.4: after the reservation = after the process start -> failed, started, one unit
    step = state.record["iterations"][0]["steps"][0]
    assert (step["state"], step["reason_code"], step["evaluation"]) == ("failed", None, "computed")
    assert candidate(state, IDS[0])["state"] == "failed"
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)


def test_race_and_crash_orders_resolve_the_step_without_a_new_state():
    """Orders the compute route avoids but a race or a crash can leave (spec 6.1 step_unavailable race, a crash
    between the approval event and the submit): the step still gets one of the six states."""
    log = Log()
    done_unvalidated = log.run_job(IDS[0])                  # outside: done, result does not validate
    log.run_job(IDS[1], end="failed")                       # outside: failed
    log.created()
    log.approve(1, IDS[0])                                  # the queue hands back the ended job
    state = derive(log)
    step = state.record["iterations"][0]["steps"][0]
    # a job that had already ended when approved: no usable result -> unavailable (never reused, never re-run)
    assert (step["state"], step["job_id"], step["evaluation"]) == ("unavailable", done_unvalidated, None)
    assert states(state)[IDS[0]] == "unavailable" and state.record["counts"]["started"] == 0
    log.approve(1, IDS[1])
    state = derive(log)
    assert state.record["iterations"][0]["steps"][1]["state"] == "unavailable"
    assert state.record["iterations"][0]["state"] == "unavailable"

    crash = Log()
    crash.created()
    crash.approve(1, IDS[2])                                # crash before the submit: no job with the key
    state = derive(crash)
    step = state.record["iterations"][0]["steps"][0]
    assert (step["state"], step["job_id"]) == ("unavailable", None)
    assert states(state)[IDS[2]] == "pending"               # no job is left in an unusable state (spec 3.2 4)
    assert state.record["current"]["phase"] == "awaiting_selection"


@pytest.mark.parametrize(("step", "failure", "reason"), [
    ("ligand_dock", {"error": "fatal", "message": "x", "reason_code": "engine_failed"}, "engine_failed"),
    ("ligand_dock", {"error": "resource_exceeded", "message": "job timeout"}, None),       # T1 (a) 6: no code
    ("ligand_dock", {"error": "fatal", "message": "x", "reason_code": "not_a_closed_reason"}, None),
    ("model", {"error": "fatal", "message": "x", "reason_code": "mutation_modeling_failed"},
     "mutation_modeling_failed"),
    ("model", {"error": "fatal", "message": "x", "reason_code": "box_invalid"}, None),     # an M18 name on M21
])
def test_failed_step_reason_code_is_the_jobs_closed_reason_or_null(step, failure, reason):
    log = Log()
    ref = IDS[0] if step == "ligand_dock" else INDEXES[0]
    log.created("ligand" if step == "ligand_dock" else "protein")
    log.approve(1, ref, step)
    log.run_job(ref, step, end="failed", failure=failure)
    state = derive(log)
    assert state.record["iterations"][0]["steps"][0]["reason_code"] == reason
    assert candidate(state, ref)["state"] == "failed"


# ---------------------------------------------------------------- protein: model, docking, reuse, abandon


def test_protein_loop_model_dock_reuse_abandon_and_not_run():
    log = Log()
    log.run_job(11, "model")                                 # outside: the stored model of candidate 11
    log.created("protein", goal="explore", cap=3)
    results = dict(modelled(11))
    state = derive(log, results=results)
    # spec 3.2: a model result alone is pending; spec 7: the minimum need over pending candidates (11 has a model)
    assert states(state) == {3: "pending", 7: "pending", 11: "pending", 19: "pending"}
    assert state.record["current"]["needs"] == {
        "expensive_units": 1, "wall_clock_s": 300, "external_tokens": None, "usd": None, "sends": 1}
    assert derive(log, results=results, budget={**BUDGET, "expensive_units": 1}).record["current"]["blocked_axes"] == []

    log.approve(1, 7, "model")
    model_job = log.run_job(7, "model")
    results |= modelled(7)
    state = derive(log, results=results)
    # spec 6.3: model done -> awaiting_docking (the iteration has started)
    assert state.record["current"] == {
        "iteration": 1, "phase": "awaiting_docking", "step": "dock", "action": "dock",
        "needs": {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": None, "usd": None, "sends": 0},
        "remaining": remaining(), "blocked_axes": [], "send_blocked_axes": [], "can_end": False, "job": None}
    assert state.record["iterations"][0]["steps"] == [{
        "step": "model", "candidate_ref": 7, "job_id": model_job, "call_key": key(7, "model"),
        "result_handle": handle("mutation_model_result", 7), "state": "completed", "reason_code": None,
        "evaluation": "computed"}]
    assert (state.record["iterations"][0]["phase"], state.record["iterations"][0]["state"]) == (
        "awaiting_docking", "in_progress")
    assert candidate(state, 7) == {"ref": 7, "display": display("protein", 1, 7), "state": "pending",
                                   "evaluation": None, "score_kcal_mol": None, "iteration": None}
    assert state.record["counts"] == counts(started=1, human_decided=1, units_charged=1)
    assert JL.end_refusal(state) == "docking_pending"
    assert JL.compute_admission(state, iteration=1, capability_available=True) == {
        "outcome": "approve", "iteration": 1, "step": "dock", "candidate_ref": 7, "decided_by": "human",
        "proposal_handle": None, "call_key": key(7, "dock"), "units": 1, "reuse": False,
        "needs": {"expensive_units": 1, "wall_clock_s": 300}}
    assert JL.compute_admission(state, iteration=1, candidate=7, capability_available=True) == {
        "outcome": "idempotent", "job_id": model_job, "start": False}
    assert JL.compute_admission(state, iteration=1, candidate=3,
                                capability_available=True)["reason_code"] == "phase_invalid"

    log.approve(1, 7, "dock")
    log.run_job(7, "dock")
    results |= docked(7, 1, -4.2, "dock")
    state = derive(log, results=results)
    assert candidate(state, 7) == {"ref": 7, "display": display("protein", 1, 7), "state": "scored",
                                   "evaluation": "computed", "score_kcal_mol": -4.2, "iteration": 1}
    assert [step["step"] for step in state.record["iterations"][0]["steps"]] == ["model", "dock"]
    assert len(state.record["iterations"][0]["approvals"]) == 2
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=2)
    assert state.record["current"]["needs"]["expensive_units"] == 1           # 11 (stored model) is still pending

    # candidate 11: a stored model is adopted (reused, no job, no unit) and the iteration starts at that moment
    assert JL.compute_admission(state, iteration=2, candidate=11, capability_available=True) == {
        "outcome": "approve", "iteration": 2, "step": "model", "candidate_ref": 11, "decided_by": "human",
        "proposal_handle": None, "call_key": key(11, "model"), "units": 0, "reuse": True,
        "needs": {"expensive_units": 1, "wall_clock_s": 300}}
    log.approve(2, 11, "model", units=0)
    state = derive(log, results=results)
    step = state.record["iterations"][1]["steps"][0]
    assert step == {"step": "model", "candidate_ref": 11, "job_id": None, "call_key": key(11, "model"),
                    "result_handle": handle("mutation_model_result", 11), "state": "reused", "reason_code": None,
                    "evaluation": "reused"}
    assert state.record["current"]["phase"] == "awaiting_docking"
    assert state.record["counts"] == counts(started=2, done=1, human_decided=2, units_charged=2)

    log.abandon(2, 11)
    state = derive(log, results=results)
    # spec 6.3: abandoning -> not_run, the iteration ends
    assert candidate(state, 11) == {"ref": 11, "display": display("protein", 2, 11), "state": "not_run",
                                    "evaluation": "computed", "score_kcal_mol": None, "iteration": 2}
    assert state.record["iterations"][1]["state"] == "not_run"
    assert state.record["current"]["needs"] == {"expensive_units": 2, "wall_clock_s": 420, "external_tokens": None,
                                                "usd": None, "sends": 1}
    tight = derive(log, results=results, budget={**BUDGET, "expensive_units": 1})
    assert tight.record["current"]["blocked_axes"] == ["expensive_units"]
    assert JL.end_reason_for(tight) == "budget_exhausted"

    log.approve(3, 3, "model")
    log.run_job(3, "model")
    results |= modelled(3)
    log.approve(3, 3, "dock")
    dock_job = log.submit(3, "dock")
    log.cancel(dock_job)
    state = derive(log, results=results)
    # spec 6.4: the dock step cancelled before its process -> candidate not_run, the iteration counts as ended
    assert state.record["iterations"][2]["steps"][1] == {
        "step": "dock", "candidate_ref": 3, "job_id": dock_job, "call_key": key(3, "dock"), "result_handle": None,
        "state": "unavailable", "reason_code": "docking_not_run", "evaluation": None}
    assert candidate(state, 3)["state"] == "not_run" and state.record["iterations"][2]["state"] == "not_run"
    assert state.record["counts"] == counts(started=3, done=3, human_decided=3, units_charged=3)
    assert state.record["exhausted_reason"] == "iteration_cap"
    assert state.record["current"] == {"iteration": None, "phase": None, "step": None, "action": "end",
                                       "needs": ZERO_NEEDS, "remaining": remaining(), "blocked_axes": [],
                                       "send_blocked_axes": [], "can_end": True, "job": None}
    assert JL.end_refusal(state) is None and JL.end_reason_for(state) == "iteration_cap"

    result = log.ended("iteration_cap")
    state = derive(log, results=results)
    assert (state.record["status"], state.record["end_reason"], state.record["result_handle"]) == (
        "ended", "iteration_cap", result)
    assert state.record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ5, L.LJ7, L.LJ8]   # 19 is still pending
    assert state.record["current"]["action"] == "none"


def test_a_dock_result_stored_outside_after_the_model_does_not_change_the_started_iteration():
    log = Log()
    log.created("protein")
    log.approve(1, 7, "model")
    log.run_job(7, "model")
    results = modelled(7)
    log.run_job(7, "dock")                                 # someone docks the mutant outside the loop
    results |= docked(7, 2, -3.3, "dock")
    state = derive(log, results=results)
    # spec 6.5: a result made after the candidate's iteration started does not change that iteration
    assert state.record["current"]["phase"] == "awaiting_docking" and states(state)[7] == "pending"
    log.approve(1, 7, "dock")                              # the queue hands back the existing done job
    state = derive(log, results=results)
    step = state.record["iterations"][0]["steps"][1]
    assert (step["state"], step["job_id"], step["evaluation"]) == ("reused", None, "reused")
    assert candidate(state, 7)["state"] == "scored" and candidate(state, 7)["evaluation"] == "computed"
    assert state.record["counts"]["units_charged"] == 1


# ---------------------------------------------------------------- a live approved step holds its candidate


def assert_consistent(state):
    """One snapshot never contradicts itself: exhausted_reason, current, can_end, end_refusal, end_reason_for."""
    record, current = state.record, state.record["current"]
    refusal = JL.end_refusal(state)
    if record["status"] == "ended":
        assert current["action"] == "none" and current["can_end"] is False and refusal in ("cancelled", "loop_ended")
        return
    assert current["can_end"] == (refusal is None)
    if record["exhausted_reason"] is not None:
        assert current["action"] == "end" and current["job"] is None and refusal in (None, "send_in_progress")
    if current["action"] == "wait_job":
        assert current["job"] is not None and refusal in ("job_running", "send_in_progress")
        assert record["exhausted_reason"] is None
    if current["action"] == "dock":
        assert refusal in ("docking_pending", "send_in_progress")
    if refusal is None:
        expected = record["exhausted_reason"] or ("budget_exhausted" if current["blocked_axes"] else "ended_by_user")
        assert JL.end_reason_for(state) == expected
    else:
        with pytest.raises(ValueError):
            JL.end_reason_for(state)
    pending = sum(row["state"] == "pending" for row in record["candidates"])
    assert (record["exhausted_reason"] == "pool_exhausted") == (pending == 0 and record["exhausted_reason"]
                                                                != "iteration_cap")
    assert record["counts"]["done"] <= record["counts"]["started"] <= record["effective_cap"]


def test_a_live_approved_step_keeps_its_candidate_pending_when_a_same_key_result_appears():
    """Review order: pool [A, B], B computed in iteration 1, iteration 2 approves A (claimed, waiting for the first
    expensive-call approval, nothing charged), then an M19 row / M22 individual publishes A's same-key result."""
    a, b = IDS[0], IDS[1]
    log = Log()
    log.created(pool=[a, b])
    log.approve(1, b)
    log.run_job(b)
    log.approve(2, a)
    job = log.submit(a)
    log.claim(job, blocked="approval_or_cancel")
    results = docked(b, 1, -4.0) | docked(a, 2, -5.5)          # A's result published by another producer
    state = derive(log, results=results, approval_pending=True)
    # the iteration holds A: neither 2 (reused) nor 3 (unavailable) applies while its approved job is live
    assert candidate(state, a) == {"ref": a, "display": {"smiles": "C"}, "state": "pending", "evaluation": None,
                                   "score_kcal_mol": None, "iteration": None}
    assert state.record["exhausted_reason"] is None
    assert state.record["current"] == {
        "iteration": 2, "phase": "running", "step": "ligand_dock", "action": "wait_job", "needs": ZERO_NEEDS,
        "remaining": remaining(), "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
        "job": {"job_id": job, "step": "ligand_dock", "status": "claimed", "start_blocked": "approval_required"}}
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)
    assert JL.end_refusal(state) == "job_running"
    assert JL.compute_admission(state, iteration=2, candidate=a, capability_available=True) == {
        "outcome": "idempotent", "job_id": job, "start": True}
    assert_consistent(state)

    charged = Log()
    charged.events = copy.deepcopy(log.events)
    charged.attempts = dict(log.attempts)
    charged.reserve(job)
    charged.dispatch(job)
    state = derive(charged, results=results)
    assert candidate(state, a)["state"] == "pending" and state.record["current"]["action"] == "wait_job"
    assert state.record["counts"] == counts(started=2, done=1, human_decided=2, units_charged=2)
    assert_consistent(state)
    charged.terminal(job, "done")
    state = derive(charged, results=results)
    # charged and done: the iteration's own result (1) -> scored, computed; both iterations used -> iteration_cap
    assert candidate(state, a) == {"ref": a, "display": {"smiles": "C"}, "state": "scored",
                                   "evaluation": "computed", "score_kcal_mol": -5.5, "iteration": 2}
    assert state.record["exhausted_reason"] == "iteration_cap" and JL.end_reason_for(state) == "iteration_cap"
    assert state.record["counts"] == counts(started=2, done=2, human_decided=2, units_charged=2)
    assert_consistent(state)

    log.cancel(job)                                             # cancelled before its process started
    state = derive(log, results=results)
    # the step is unavailable, the iteration does not hold A any more: the stored result applies again (2)
    assert candidate(state, a) == {"ref": a, "display": {"smiles": "C"}, "state": "scored", "evaluation": "reused",
                                   "score_kcal_mol": -5.5, "iteration": None}
    second = state.record["iterations"][1]
    assert (second["phase"], second["state"], second["steps"][0]["state"]) == (
        "awaiting_selection", "unavailable", "unavailable")
    assert state.record["exhausted_reason"] == "pool_exhausted"
    assert state.record["current"]["action"] == "end" and JL.end_refusal(state) is None
    assert JL.end_reason_for(state) == "pool_exhausted"
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1, reused_count=1)
    assert_consistent(state)


def test_protein_live_model_and_dock_steps_hold_their_candidate_too():
    log = Log()
    log.created("protein", pool=[3, 7])
    log.approve(1, 3, "model")
    model_job = log.submit(3, "model")
    log.claim(model_job, blocked="approval_or_cancel")
    results = modelled(3) | docked(3, 1, -2.2, "dock")         # both results appear while the model step waits
    state = derive(log, results=results)
    assert states(state) == {3: "pending", 7: "pending"}
    assert state.record["current"]["phase"] == "running" and state.record["current"]["step"] == "model"
    assert state.record["current"]["job"]["job_id"] == model_job
    assert JL.end_refusal(state) == "job_running" and state.record["exhausted_reason"] is None
    assert_consistent(state)
    log.cancel(model_job)
    state = derive(log, results=results)
    assert states(state) == {3: "scored", 7: "pending"} and candidate(state, 3)["evaluation"] == "reused"
    assert state.record["iterations"][0]["state"] == "unavailable"
    assert_consistent(state)

    log = Log()
    log.created("protein", pool=[3, 7])
    log.approve(1, 7, "model")
    log.run_job(7, "model")
    log.approve(1, 7, "dock")
    dock_job = log.submit(7, "dock")
    log.claim(dock_job)
    results = modelled(7) | docked(7, 1, -3.1, "dock")         # the same-condition docking result appears
    state = derive(log, results=results)
    assert states(state)[7] == "pending" and state.record["current"]["step"] == "dock"
    assert state.record["current"]["job"]["job_id"] == dock_job and JL.end_refusal(state) == "job_running"
    assert_consistent(state)
    log.cancel(dock_job)
    state = derive(log, results=results)
    # the iteration had started (model charged): a dock step lost before its process -> not_run, the result made
    # elsewhere does not change the iteration (spec 6.4, 6.5)
    assert candidate(state, 7)["state"] == "not_run" and candidate(state, 7)["evaluation"] == "computed"
    assert_consistent(state)


def test_snapshots_of_every_scenario_are_self_consistent():
    log = Log()
    log.created(pool=IDS[:3], cap=2)
    snapshots = [derive(log)]
    _, choice = log.send(1, 0, ref=IDS[1])
    snapshots.append(derive(log))
    log.approve(1, IDS[1], by="jev", proposal=choice)
    job = log.submit(IDS[1])
    snapshots += [derive(log), derive(log, send_active=True)]
    log.start(job, end=None)
    snapshots.append(derive(log))
    log.terminal(job, "done")
    results = docked(IDS[1], 1, -1.0)
    snapshots += [derive(log, results=results), derive(log, results=results, budget={**BUDGET, "expensive_units": 0})]
    log.approve(2, IDS[0])
    log.cancel(log.submit(IDS[0]))
    snapshots.append(derive(log, results=results))
    log.approve(2, IDS[2])
    log.run_job(IDS[2])
    snapshots.append(derive(log, results=results | docked(IDS[2], 0, None)))
    log.ended("iteration_cap")
    log.cancel_run()
    snapshots.append(derive(log, results=results | docked(IDS[2], 0, None)))
    for state in snapshots:
        assert_consistent(state)


# ---------------------------------------------------------------- proposals, late replies, sends


def test_late_proposal_is_not_the_selection_and_a_later_one_is():
    log = Log()
    log.created()
    log.consent(True)
    late_send, late_choice = log.send(1, 0, ref=IDS[0], late=True)
    state = derive(log)
    # spec 5.3: a late reply is stored but is not the iteration's choice; the phase stays awaiting_selection
    assert state.record["current"]["phase"] == "awaiting_selection"
    assert state.record["iterations"][0]["sends"] == [{"send_id": late_send, "status": "completed",
                                                       "send_ordinal": 0, "proposal_handle": late_choice,
                                                       "late": True}]
    assert JL.selection_refusal(state, 1) is None                           # sending again is allowed
    assert JL.compute_admission(state, iteration=1, proposal=late_choice,
                                capability_available=True)["reason_code"] == "proposal_late"
    assert JL.send_ordinal(state, 1) == 1
    log.consent(True)
    _, choice = log.send(1, 1, ref=IDS[3])
    state = derive(log)
    assert state.record["current"]["phase"] == "awaiting_compute"
    assert JL.selection_refusal(state, 1) == "selection_done"
    assert JL.compute_admission(state, iteration=1, proposal=late_choice,
                                capability_available=True)["reason_code"] == "proposal_late"
    assert JL.compute_admission(state, iteration=1, proposal=handle(L.CHOICE_KIND, "unknown"),
                                capability_available=True)["reason_code"] == "proposal_invalid"
    approve = JL.compute_admission(state, iteration=1, proposal=choice, capability_available=True)
    assert (approve["outcome"], approve["candidate_ref"], approve["decided_by"], approve["proposal_handle"]) == (
        "approve", IDS[3], "jev", choice)
    # a human may still name another candidate (or the same one) in awaiting_compute
    other = JL.compute_admission(state, iteration=1, candidate=IDS[1], capability_available=True)
    assert (other["outcome"], other["candidate_ref"], other["decided_by"]) == ("approve", IDS[1], "human")
    assert JL.send_ordinal(state, 1) == 2 and state.record["counts"]["sends_dispatched"] == 2


def test_send_status_ordinal_and_dispatch_count():
    log = Log()
    log.created()
    failed, _ = log.send(1, 0, status="failed")              # dispatched, HTTP error
    rejected, _ = log.send(1, 1, status="rejected", dispatched=False)
    lost, _ = log.send(1, 1, status=None)                    # dispatched, no outcome
    state = derive(log)
    assert [(item["send_id"], item["status"], item["send_ordinal"]) for item in
            state.record["iterations"][0]["sends"]] == [(failed, "failed", 0), (rejected, "rejected", 1),
                                                        (lost, "failed", 1)]
    assert JL.send_ordinal(state, 1) == 2 and JL.send_ordinal(state, 2) == 0
    assert state.record["counts"]["sends_dispatched"] == 2
    assert state.record["current"]["phase"] == "awaiting_selection"         # no proposal
    assert derive(log, send_active=True).record["iterations"][0]["sends"][-1]["status"] == J.IN_PROGRESS


def test_sends_of_another_loop_or_the_m24_projection_are_not_this_loops():
    log = Log()
    log.created()
    log.created("protein", loop_id=OTHER)
    log.send(1, 0, ref=3, loop_id=OTHER)
    approved = log.add(J.EVENT_APPROVED, send_id=str(uuid.uuid4()), projection_handle=handle("jev_projection", "x"),
                       body_sha256="0" * 64, question_id=J.LIGAND_QUESTION_ID, source_handle="x",
                       selection_count=2, approved_by="human")
    log.add(J.EVENT_DISPATCH, send_id=approved["send_id"], audit_id="eg_" + "0" * 32)
    state = derive(log)
    assert state.record["iterations"] == [] and state.record["counts"]["sends_dispatched"] == 0
    assert state.record["current"]["remaining"]["sends"] == 8                 # the run cap counts every dispatch


# ---------------------------------------------------------------- exhaustion, ending, cancel


def test_pool_exhausted_counts_an_in_progress_candidate_as_pending_and_ignores_unavailable():
    log = Log()
    log.cancel(log.submit(IDS[1]))                            # outside, cancelled -> unavailable
    log.created(pool=IDS[:3])
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    log.approve(2, IDS[2])
    job = log.run_job(IDS[2], end=None)
    results = docked(IDS[0], 1, -6.0)
    state = derive(log, results=results)
    assert state.record["exhausted_reason"] is None and state.record["current"]["action"] == "wait_job"
    log.terminal(job, "done")
    state = derive(log, results=results | docked(IDS[2], 1, -6.1))
    # spec 3.2: no pending candidate -> pool_exhausted (an unavailable one does not keep the loop going)
    assert state.record["exhausted_reason"] == "pool_exhausted"
    assert state.record["counts"]["started"] == 2 and state.record["effective_cap"] == 3
    assert state.record["current"] == {"iteration": None, "phase": None, "step": None, "action": "end",
                                       "needs": ZERO_NEEDS, "remaining": remaining(), "blocked_axes": [],
                                       "send_blocked_axes": [], "can_end": True, "job": None}
    assert derive(log, results=results | docked(IDS[2], 1, -6.1),
                  send_active=True).record["current"]["can_end"] is False
    assert JL.end_reason_for(state) == "pool_exhausted"


def test_iteration_cap_waits_for_the_last_iteration_to_end():
    log = Log()
    log.created(cap=1)
    log.approve(1, IDS[0])
    job = log.run_job(IDS[0], end=None)
    state = derive(log)
    assert state.record["effective_cap"] == 1 and state.record["exhausted_reason"] is None
    log.terminal(job, "failed", failure={"error": "fatal", "message": "x", "reason_code": "engine_failed"})
    assert derive(log).record["exhausted_reason"] == "iteration_cap"


def test_an_unstarted_unavailable_iteration_is_listed_when_the_pool_is_exhausted():
    log = Log()
    log.created(pool=IDS[:2])
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    log.approve(2, IDS[1])
    log.cancel(log.submit(IDS[1]))
    state = derive(log, results=docked(IDS[0], 1, -5.5))
    assert state.record["exhausted_reason"] == "pool_exhausted"
    second = state.record["iterations"][1]
    assert (second["index"], second["phase"], second["state"], second["candidate_ref"]) == (
        2, "awaiting_selection", "unavailable", IDS[1])
    assert state.record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)


def test_run_cancel_derives_run_cancelled_and_ended_events_win():
    log = Log()
    log.created()
    log.cancel_run()
    state = derive(log)
    # spec 3.2: a cancel event of the run ends an unfinished loop as run_cancelled (no event, no summary)
    assert (state.record["status"], state.record["end_reason"], state.record["result_handle"]) == (
        "ended", "run_cancelled", None)
    assert state.record["current"] == {"iteration": None, "phase": None, "step": None, "action": "none",
                                       "needs": ZERO_NEEDS, "remaining": remaining(), "blocked_axes": [],
                                       "send_blocked_axes": [], "can_end": False, "job": None}
    assert state.record["limitations"][-1] == L.LJ8
    assert JL.end_refusal(state) == "cancelled"
    assert JL.selection_refusal(state, 1) == "loop_ended"
    assert JL.compute_admission(state, iteration=1, candidate=IDS[0],
                                capability_available=True)["reason_code"] == "cancelled"

    log = Log()
    log.created(pool=IDS[:2])
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    log.approve(2, IDS[1])
    log.run_job(IDS[1])
    result = log.ended("iteration_cap")
    log.cancel_run()
    state = derive(log, results=docked(IDS[0], 1, -1.0) | docked(IDS[1], 0, None))
    assert (state.record["status"], state.record["end_reason"], state.record["result_handle"]) == (
        "ended", "iteration_cap", result)
    assert state.record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ6]   # nothing left uncomputed: no LJ8
    assert JL.end_refusal(state) == "cancelled"


def test_end_refusal_order_and_end_reason():
    log = Log()
    log.created()
    assert JL.end_refusal(derive(log)) is None
    assert JL.end_reason_for(derive(log)) == "ended_by_user"
    assert JL.end_reason_for(derive(log, budget={**BUDGET, "expensive_units": 0})) == "budget_exhausted"
    assert JL.end_reason_for(derive(log, budget={**BUDGET, "wall_clock_s": 120.0})) == "budget_exhausted"
    # only the send side short (spec 7): the human can still name a candidate -> not budget_exhausted
    assert JL.end_reason_for(derive(log, budget={**BUDGET, "external_tokens": 0, "usd": 0.0},
                                    reservation={"external_tokens": 9000, "usd": 0.1})) == "ended_by_user"
    assert JL.end_refusal(derive(log, send_active=True)) == "send_in_progress"
    log.approve(1, IDS[0])
    job = log.submit(IDS[0])
    assert JL.end_refusal(derive(log)) == "job_running"
    assert JL.end_refusal(derive(log, send_active=True)) == "send_in_progress"
    with pytest.raises(ValueError):
        JL.end_reason_for(derive(log))
    log.start(job, end=None)
    assert JL.end_refusal(derive(log)) == "job_running"
    log.terminal(job, "done")
    log.ended()
    assert JL.end_refusal(derive(log)) == "loop_ended"
    log.cancel_run()
    assert JL.end_refusal(derive(log, send_active=True)) == "cancelled"


# ---------------------------------------------------------------- budget axes (spec 7)


def test_compute_axes_use_the_iteration_need_and_floor_the_remaining_seconds():
    log = Log()
    log.created()
    state = derive(log, budget={**BUDGET, "wall_clock_s": 299.9})
    assert state.record["current"]["remaining"]["wall_clock_s"] == 299
    assert state.record["current"]["blocked_axes"] == ["wall_clock_s"]
    state = derive(log, budget={**BUDGET, "expensive_units": 0, "wall_clock_s": 0.0})
    assert state.record["current"]["blocked_axes"] == ["expensive_units", "wall_clock_s"]
    refused = JL.compute_admission(state, iteration=1, candidate=IDS[0], capability_available=True)
    assert refused == {"outcome": "refused", "reason_code": "budget_blocked", "http_status": 429,
                       "detail": {"blocked_axes": ["expensive_units", "wall_clock_s"],
                                  "needs": {"expensive_units": 1, "wall_clock_s": 300}}}


@pytest.mark.parametrize(("budget", "dispatches", "blocked"), [
    ({}, 0, []),
    ({"external_tokens": 20000}, 0, ["external_tokens"]),
    ({"usd": 0.05}, 0, ["usd"]),
    ({}, 10, ["sends"]),
    ({"external_tokens": 0, "usd": 0.0}, 10, ["external_tokens", "usd", "sends"]),
])
def test_send_axes_are_judged_at_select_with_the_preview_reservation(budget, dispatches, blocked):
    log = Log()
    log.created()
    for _ in range(dispatches):
        log.add(J.EVENT_DISPATCH, send_id=str(uuid.uuid4()), audit_id="eg_" + "1" * 32)   # M24 sends of the run
    state = derive(log, budget={**BUDGET, **budget}, reservation={"external_tokens": 25000, "usd": 0.1})
    current = state.record["current"]
    assert current["send_blocked_axes"] == blocked
    assert current["blocked_axes"] == []
    assert current["needs"] == {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": 25000, "usd": 0.1,
                                "sends": 1}
    assert current["remaining"] == {"expensive_units": 8, "wall_clock_s": 1800,
                                    "external_tokens": {**BUDGET, **budget}["external_tokens"],
                                    "usd": {**BUDGET, **budget}["usd"], "sends": 10 - dispatches}


def test_send_axes_are_not_judged_outside_select():
    log = Log()
    log.created()
    log.send(1, 0, ref=IDS[0])
    state = derive(log, budget={**BUDGET, "external_tokens": 0}, reservation={"external_tokens": 25000, "usd": 0.1})
    current = state.record["current"]
    assert current["action"] == "compute" and current["send_blocked_axes"] == []
    assert current["needs"]["external_tokens"] is None and current["remaining"]["usd"] is None


def test_per_candidate_need_for_compute_and_dock_need():
    log = Log()
    log.run_job(11, "model")
    log.created("protein")
    results = modelled(11)
    tight = {**BUDGET, "expensive_units": 1, "wall_clock_s": 400.0}
    state = derive(log, results=results, budget=tight)
    assert state.record["current"]["blocked_axes"] == []                     # 11 needs 1 unit / 300 s
    assert JL.compute_admission(state, iteration=1, candidate=3, capability_available=True)["detail"] == {
        "blocked_axes": ["expensive_units", "wall_clock_s"], "needs": {"expensive_units": 2, "wall_clock_s": 420}}
    assert JL.compute_admission(state, iteration=1, candidate=11, capability_available=True)["outcome"] == "approve"
    log.approve(1, 11, "model", units=0)
    state = derive(log, results=results, budget={**BUDGET, "wall_clock_s": 250.0})
    assert state.record["current"]["blocked_axes"] == ["wall_clock_s"]       # docking needs 300 s
    assert JL.compute_admission(state, iteration=1, capability_available=True)["reason_code"] == "budget_blocked"


# ---------------------------------------------------------------- compute admission (spec 6.1 order)


def test_compute_admission_order():
    log = Log()
    log.run_job(IDS[3])                                      # outside, stored -> reused
    log.cancel(log.submit(IDS[2]))                           # outside, cancelled -> unavailable
    log.created()
    results = docked(IDS[3], 1, -2.0)

    def admit(**request):
        base = {"capability_available": True}
        options = {name: request.pop(name) for name in ("results", "send_active") if name in request}
        state = derive(log, results=options.get("results", results), send_active=options.get("send_active", False))
        return JL.compute_admission(state, **{**base, **request})

    assert admit(iteration=1, candidate=IDS[0], send_active=True)["reason_code"] == "send_in_progress"
    assert admit(iteration=2, candidate=IDS[0], send_active=True)["reason_code"] == "send_in_progress"
    assert admit(iteration=2, candidate=IDS[0])["reason_code"] == "iteration_invalid"
    assert admit(iteration=True, candidate=IDS[0])["reason_code"] == "iteration_invalid"
    assert admit(iteration=1)["reason_code"] == "phase_invalid"             # no dock step in a ligand loop
    assert admit(iteration=1, proposal=handle(L.CHOICE_KIND, "x"))["reason_code"] == "proposal_invalid"
    assert admit(iteration=1, candidate=IDS[5])["reason_code"] == "candidate_invalid"
    assert admit(iteration=1, candidate=IDS[2])["reason_code"] == "candidate_unavailable"
    assert admit(iteration=1, candidate=IDS[3])["reason_code"] == "candidate_computed"
    assert admit(iteration=1, candidate=IDS[0], capability_available=False)["reason_code"] == "capability_unavailable"
    assert admit(iteration=1, candidate=IDS[0]) == {
        "outcome": "approve", "iteration": 1, "step": "ligand_dock", "candidate_ref": IDS[0], "decided_by": "human",
        "proposal_handle": None, "call_key": key(IDS[0], "ligand_dock"), "units": 1, "reuse": False,
        "needs": {"expensive_units": 1, "wall_clock_s": 300}}
    assert JL.COMPUTE_HTTP["candidate_invalid"] == 422 and JL.COMPUTE_HTTP["capability_unavailable"] == 412

    log.approve(1, IDS[0])
    job = log.submit(IDS[0])
    # spec 6.1: the same step again with the same arguments -> start the live job, no new event
    assert admit(iteration=1, candidate=IDS[0]) == {"outcome": "idempotent", "job_id": job, "start": True}
    assert admit(iteration=1, candidate=IDS[1])["reason_code"] == "phase_invalid"
    log.claim(job, blocked="approval_or_cancel")
    pending_state = derive(log, results=results, approval_pending=True)
    assert JL.compute_admission(pending_state, iteration=1, candidate=IDS[0], capability_available=True) == {
        "outcome": "idempotent", "job_id": job, "start": True}
    assert admit(iteration=1, candidate=IDS[0]) == {"outcome": "idempotent", "job_id": job, "start": False}
    log.reserve(job)
    log.dispatch(job)
    assert admit(iteration=1, candidate=IDS[0]) == {"outcome": "idempotent", "job_id": job, "start": False}
    assert admit(iteration=1, proposal=handle(L.CHOICE_KIND, "x"))["reason_code"] == "phase_invalid"
    log.terminal(job, "done")
    results = results | docked(IDS[0], 1, -3.0)
    assert admit(iteration=1, candidate=IDS[0])["reason_code"] == "iteration_invalid"
    assert admit(iteration=2, candidate=IDS[0])["reason_code"] == "candidate_computed"


def test_compute_admission_iteration_cap_and_refusals_before_it():
    log = Log()
    log.created(cap=1)
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    state = derive(log, results=docked(IDS[0], 1, -1.5))
    assert state.record["exhausted_reason"] == "iteration_cap"
    assert JL.compute_admission(state, iteration=2, candidate=IDS[5],
                                capability_available=False)["reason_code"] == "iteration_cap_reached"
    assert JL.compute_admission(state, iteration=1, candidate=IDS[1],
                                capability_available=True)["reason_code"] == "iteration_invalid"
    log.ended("iteration_cap")
    assert JL.compute_admission(derive(log, results=docked(IDS[0], 1, -1.5)), iteration=2, candidate=IDS[1],
                                capability_available=True)["reason_code"] == "loop_ended"


# ---------------------------------------------------------------- the shared selection refusal (spec 4.1 / 5.1)


def test_selection_refusal_order():
    log = Log()
    log.created()
    state = derive(log)
    assert JL.selection_refusal(state, 1) is None
    assert JL.selection_refusal(state, 2) == "iteration_mismatch"
    assert JL.selection_refusal(state, True) == "iteration_mismatch"
    log.approve(1, IDS[0])
    job = log.submit(IDS[0])
    assert JL.selection_refusal(derive(log), 1) == "phase_invalid"          # a live approved job
    log.start(job, end=None)
    assert JL.selection_refusal(derive(log), 2) == "phase_invalid"          # iteration 1 is running
    assert JL.selection_refusal(derive(log), 1) == "iteration_mismatch"
    log.terminal(job, "done")
    results = docked(IDS[0], 1, -2.5) | docked(IDS[1], 1, -2.6)            # IDS[1]: stored outside
    state = derive(log, results=results)
    assert JL.selection_refusal(state, 2) is None
    log.send(2, 0, ref=IDS[2])
    assert JL.selection_refusal(derive(log, results=results), 2) == "selection_done"
    capped = Log()
    capped.created(cap=1)
    capped.approve(1, IDS[0])
    capped.run_job(IDS[0])
    assert JL.selection_refusal(derive(capped), 2) == "cap_reached"
    few = Log()
    few.created()
    assert JL.selection_refusal(derive(few, results=docked(IDS[0], 1, -1.0) | docked(IDS[1], 1, -1.0)
                                       | docked(IDS[2], 1, -1.0)), 1) == "too_few_candidates"
    few.ended()
    assert JL.selection_refusal(derive(few), 1) == "loop_ended"


# ---------------------------------------------------------------- list rows


def test_list_rows_newest_first():
    log = Log()
    log.created()
    log.ended()
    log.created("protein", loop_id=OTHER)
    rows = JL.list_rows([derive(log), derive(log, loop_id=OTHER)])
    assert rows == [
        {"loop_id": OTHER, "branch": "protein", "status": "active", "end_reason": None, "goal": "exploit",
         "pool_size": 4, "counts": counts(), "created_seq": 4},
        {"loop_id": LOOP, "branch": "ligand", "status": "ended", "end_reason": "ended_by_user", "goal": "exploit",
         "pool_size": 4, "counts": counts(), "created_seq": 2}]
    assert [list(row) for row in rows] == [list(JL.ROW_KEYS)] * 2
    assert [loop_id for _, loop_id in JL.created_loops(log.events)] == [LOOP, OTHER]


# ---------------------------------------------------------------- M24 parity (the pure copies vs jev_sends)


def _orders():
    sid = [str(uuid.UUID(label_sha("parity", n)[:32], version=4)) for n in range(3)]
    base = [{"seq": 1, "ts": 0.0, "type": "run_started", "run_id": RUN_ID}]

    def build(*items):
        events = list(base)
        for kind, data in items:
            events.append({"seq": len(events) + 1, "ts": float(len(events)), "type": kind, **data})
        return events

    on = (J.EVENT_CONSENT, {"enabled": True, "policy": J.CONSENT_POLICY})
    off = (J.EVENT_CONSENT, {"enabled": False, "policy": J.CONSENT_POLICY})
    wrong = (J.EVENT_CONSENT, {"enabled": True, "policy": "another@1"})

    def dispatch(n):
        return (J.EVENT_DISPATCH, {"send_id": sid[n], "audit_id": "eg_" + str(n) * 32})

    return sid, [
        build(), build(on), build(on, off), build(off, on), build(wrong), build(on, wrong),
        build(on, dispatch(0)), build(on, dispatch(0), off), build(on, off, dispatch(0)),
        build(on, dispatch(0), ("cancel_requested", {})), build(on, dispatch(0), ("run_cancelled", {"reason": "x"})),
        build(("cancel_requested", {}), on, dispatch(0)), build(on, dispatch(0), dispatch(1), off, on, dispatch(2)),
        build(on, dispatch(0), wrong), build(on, dispatch(1), dispatch(1)),
    ]


def test_event_functions_equal_the_m24_ones():
    sid, orders = _orders()
    fake_run = types.SimpleNamespace(_cancel_path=Path("/nonexistent/m25/cancel.request"))
    for events in orders:
        assert JL.consent_enabled(events) == S.consent_enabled(events)
        assert JL.dispatch_count(events) == S.dispatch_count(events)
        assert JL.run_cancel_seen(events) == S.cancel_seen(fake_run, events)
        for send_id in [*sid, "not-a-send"]:
            assert JL.late_arrival(events, send_id) == S.late_arrival(events, send_id)
    assert {JL.late_arrival(events, sid[0]) for events in orders} == {
        (False, None), (True, "consent_off"), (True, "run_cancelled")}


def test_loop_send_status_late_and_proposal_equal_the_m24_record():
    log = Log()
    log.created()
    log.consent(True)
    ids = [log.send(1, 0, status="failed")[0], log.send(1, 1, status="rejected", dispatched=False)[0],
           log.send(1, 1, ref=IDS[0], late=True)[0]]
    log.consent(True)
    ids += [log.send(1, 2, ref=IDS[1])[0], log.send(1, 3, status=None)[0]]
    try:
        S.begin_send(RUN_ID, ids[-1])
        loop_sends = [item for it in derive(log, send_active=True).record["iterations"] for item in it["sends"]]
        m24 = [S.send_record(log.events, send_id) for send_id in ids]
    finally:
        S.end_send(RUN_ID, ids[-1])
    assert [item["send_id"] for item in loop_sends] == ids
    assert [(item["status"], item["late"], item["proposal_handle"]) for item in loop_sends] == [
        (record["status"], record["late"], record["choice_handle"]) for record in m24]
    lost = [item for it in derive(log).record["iterations"] for item in it["sends"]][-1]
    assert (lost["status"], S.send_record(log.events, ids[-1])["status"]) == ("failed", "failed")


# ---------------------------------------------------------------- payload parsers (closed keys and types)


def _created(**override):
    log = Log()
    event = log.created()
    return {**event, **override}


def _approved(**override):
    event = {"seq": 3, "ts": 0.0, "type": L.EVENT_COMPUTE_APPROVED, "loop_id": LOOP, "iteration": 1,
             "step": "ligand_dock", "candidate_ref": IDS[0], "decided_by": "human", "proposal_handle": None,
             "call_key": key(IDS[0], "ligand_dock"), "units": 1, "approved_by": "human"}
    return {**event, **override}


def test_parsers_accept_the_spec_shapes():
    parsed = JL.parse_created(_created())
    assert set(parsed) == set(JL.CREATED_KEYS) and parsed["pool"]["candidates"] == IDS[:4]
    assert JL.parse_compute_approved(_approved())["call_key"] == key(IDS[0], "ligand_dock")
    assert JL.parse_compute_approved(_approved(decided_by="jev", proposal_handle=handle(L.CHOICE_KIND, "p")))
    assert JL.parse_compute_approved(_approved(step="model", candidate_ref=3, units=0))["units"] == 0
    assert JL.parse_docking_abandoned({"seq": 4, "ts": 0.0, "type": L.EVENT_DOCKING_ABANDONED, "loop_id": LOOP,
                                       "iteration": 2, "candidate_ref": 7})["candidate_ref"] == 7
    ended = {"seq": 5, "ts": 0.0, "type": L.EVENT_ENDED, "loop_id": LOOP, "end_reason": "budget_exhausted",
             "result_handle": handle(L.RESULT_KIND, "r")}
    assert JL.parse_ended(ended)["end_reason"] == "budget_exhausted"


def _pool(**override):
    pool = _created()["pool"]
    return {**pool, **override}


@pytest.mark.parametrize("event", [
    _created(extra=1), {k: v for k, v in _created().items() if k != "pins"},
    _created(loop_id="not-a-uuid"), _created(loop_id=str(uuid.uuid1())), _created(branch="dna"),
    _created(goal="neutral"), _created(loop_seed=-1), _created(loop_seed=2_147_483_648), _created(loop_seed=True),
    _created(iteration_cap=0), _created(iteration_cap=9), _created(iteration_cap=5.0), _created(setup_sha256="0" * 64),
    _created(setup=[]), _created(pins=None),
    _created(pool=_pool(candidates=IDS[:1])), _created(pool=_pool(candidates=[f"c_{n:016x}" for n in range(21)])),
    _created(pool=_pool(candidates=[IDS[0], IDS[0]])), _created(pool=_pool(candidates=[1, 2])),
    _created(pool=_pool(extra=None)), _created(pool=_pool(structure={"handle": "x", "model_number": 1})),
    _created(pool=_pool(source={"handle": handle("mutation_candidate_set", "s"), "schema": "ligand_candidate_set@1"})),
    _created(pool=_pool(source={"handle": handle("ligand_candidate_set", "s"), "schema": "mutation_candidate_set@1"})),
    _created(pool=_pool(filter=[])),
])
def test_created_parser_refuses_shapes_outside_the_spec(event):
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_created(event)


def test_created_parser_refuses_protein_shapes():
    log = Log()
    event = log.created("protein")
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_created({**event, "pool": {**event["pool"], "structure": None}})
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_created({**event, "pool": {**event["pool"], "filter": {"rules": []}}})
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_created({**event, "pool": {**event["pool"], "candidates": IDS[:2]}})


@pytest.mark.parametrize("event", [
    _approved(extra=1), {k: v for k, v in _approved().items() if k != "units"}, _approved(iteration=0),
    _approved(iteration=9), _approved(iteration=True), _approved(step="relax"), _approved(decided_by="model"),
    _approved(decided_by="jev"), _approved(proposal_handle=handle(L.CHOICE_KIND, "p")),
    _approved(decided_by="jev", proposal_handle=handle("jev_choice", "p")), _approved(call_key="A" * 64),
    _approved(units=2), _approved(units=0), _approved(approved_by="jev"), _approved(candidate_ref=-1),
    _approved(candidate_ref="c_123"), _approved(step="dock", candidate_ref=3, decided_by="jev",
                                                 proposal_handle=handle(L.CHOICE_KIND, "p")),
])
def test_approved_parser_refuses_shapes_outside_the_spec(event):
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_compute_approved(event)


@pytest.mark.parametrize("override", [{"end_reason": "run_cancelled"}, {"end_reason": "done"},
                                      {"result_handle": None}, {"result_handle": handle("jev_choice", "r")},
                                      {"extra": 1}])
def test_ended_parser_refuses_shapes_outside_the_spec(override):
    event = {"seq": 5, "ts": 0.0, "type": L.EVENT_ENDED, "loop_id": LOOP, "end_reason": "ended_by_user",
             "result_handle": handle(L.RESULT_KIND, "r"), **override}
    with pytest.raises(JL.LoopRecordInvalid):
        JL.parse_ended(event)


# ---------------------------------------------------------------- event orders the routes never write


def _invalid(log, **kwargs):
    with pytest.raises(JL.LoopRecordInvalid):
        derive(log, **kwargs)


def test_event_orders_the_routes_never_write_are_refused():
    log = Log()
    log.created()
    log.approve(2, IDS[0])                                      # iteration 1 never ran
    _invalid(log)

    log = Log()
    log.created()
    log.approve(1, IDS[0])
    log.submit(IDS[0])
    log.approve(1, IDS[1])                                      # the first approval's job is still live
    _invalid(log)

    log = Log()
    log.created("protein")
    log.approve(1, 7, "model")
    log.run_job(7, "model", end=None)
    log.approve(1, 7, "dock")                                   # docking before the model ended
    _invalid(log)

    log = Log()
    log.created()
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    log.abandon(1, IDS[0])                                      # no docking step in a ligand loop
    _invalid(log, results=docked(IDS[0], 1, -1.0))

    log = Log()
    log.created()
    _, late = log.send(1, 0, ref=IDS[0], late=True)
    log.approve(1, IDS[0], by="jev", proposal=late)            # a late proposal is never the decision
    _invalid(log)

    log = Log()
    log.created()
    log.approve(1, IDS[4])                                      # the pool is IDS[:4]
    _invalid(log)

    log = Log()
    log.created(cap=1)
    log.approve(1, IDS[0])
    log.run_job(IDS[0])
    log.approve(2, IDS[1])                                      # beyond effective_cap
    _invalid(log, results=docked(IDS[0], 1, -1.0))

    log = Log()
    log.created()
    log.approve(1, IDS[0])
    log.submit(IDS[0])
    log.ended()                                                 # ended while a job waits
    _invalid(log)

    log = Log()
    log.created()
    log.ended()
    log.approve(1, IDS[0])                                      # after the end
    _invalid(log)

    log = Log()
    log.created()
    log.created()                                               # created twice
    _invalid(log)

    log = Log()
    log.created()
    log.send(3, 0, ref=IDS[0])                                  # a send for an iteration that is not current
    _invalid(log)

    log = Log()
    log.created()
    with pytest.raises(JL.LoopNotFound):
        JL.derive_loop(OTHER, log.events, jobs=[], keys={}, results={}, displays={}, proposals={}, budget=BUDGET)


def test_inputs_must_cover_the_pool():
    log = Log()
    log.created()
    with pytest.raises(ValueError):
        derive(log, keys={ref: {"ligand_dock": key(ref, "ligand_dock")} for ref in IDS[:3]})
    with pytest.raises(ValueError):
        derive(log, budget={**BUDGET, "usd": None})
    protein = Log()
    protein.created("protein")
    with pytest.raises(ValueError):   # a dock key without a stored model
        derive(protein, keys={ref: {"model": key(ref, "model"), "dock": key(ref, "dock")} for ref in INDEXES})


# ---------------------------------------------------------------- purity and module hygiene


def test_derivation_is_pure_and_its_output_is_not_aliased():
    log = Log()
    log.created()
    _, choice = log.send(1, 0, ref=IDS[2])
    log.approve(1, IDS[2], by="jev", proposal=choice)
    log.run_job(IDS[2])
    results = docked(IDS[2], 2, -9.5)
    events, proposals, saved = copy.deepcopy(log.events), copy.deepcopy(log.proposals), copy.deepcopy(results)
    first = derive(log, results=results).record
    second = derive(log, results=results).record
    assert first == second and log.events == events and log.proposals == proposals and results == saved
    first["setup"]["synthetic"] = "changed"
    first["pins"]["synthetic"] = False
    assert log.events == events


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is None:
            found |= {"." * node.level + alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + node.module)
    return found


def test_loop_module_imports_only_stdlib_constants_and_canonical_json():
    allowed = {"__future__", "base64", "collections", "copy", "dataclasses", "hashlib", "itertools", "json", "math",
               "re", "typing", "collections.abc", ".docking_constants", ".jev_constants", ".jev_loop_constants",
               ".mutation_model_constants", ".core.handles"}
    assert _imports(MW / "jev_loops.py") <= allowed


def test_loop_module_names_no_send_path_limit_raise_or_m24_event_string():
    text = (MW / "jev_loops.py").read_text()
    assert "raise_limits" not in text and "limit_approval" not in text
    for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
        assert event not in text, event
    tree = ast.parse(text)
    names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
             if isinstance(node, (ast.Name, ast.Attribute))}
    assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send", "jev_sends", "egress",
                        "raise_limits", "limit_approval"}
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    for module in modules:
        assert module.split(".")[0] not in {"httpx", "rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "urllib",
                                            "http", "requests", "socket", "aiohttp"}, module
        assert "jev_sends" not in module and "egress" not in module, module


def test_importing_the_loop_module_loads_no_send_network_or_chemistry_module():
    code = ("import sys, mw.jev_loops\n"
            "bad = [m for m in ('httpx', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm', 'mw.jev_sends',"
            " 'mw.egress', 'mw.egress.gate', 'mw.egress.science', 'fastapi', 'mw.jobs.queue') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_record_closed_values_are_the_spec_sets():
    assert set(JL.COMPUTE_HTTP) == set(L.COMPUTE_REASONS)
    assert set(JL.END_HTTP) == set(L.END_REFUSAL_REASONS)
    assert JL.COUNT_KEYS == ("started", "done", "jev_decided", "human_decided", "sends_dispatched", "units_charged",
                             "reused_count")
