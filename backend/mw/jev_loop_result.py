"""M25 JEV design loop: the summary ``jev_loop_result@1`` (spec .dryforge/spec.md 8.1, 8.2, 9.3).

Pure: the standard library, ``jev_constants`` (the candidate id pattern and source schemas), ``jev_loop_constants``,
``jev_loops`` (the record's row keys) and ``core.handles.canonical_json``. No object store, event log, job index,
file, clock, network, credential or engine; never the M24 send module or the gate.

``build_loop_result(record, end_reason)`` makes the summary from a loop's derived ``jev_loop@1`` record at the moment
it ends (``jev_loop_store`` derives it from one event-log read under the run's transition lock, then stores the
summary and writes ``jev_loop_ended``). ``validated_loop_result(content, record=None, end_reason=None)`` checks a
summary on its own (exact keys at every level, closed sets, the pool, every candidate row against its iteration, the
counts, the charged units, ``unfinished``, the end reason against what the summary itself shows, the LJ ids, the
size) and, given the record derived again from the events up to the loop's ``jev_loop_ended`` event, that the summary
is exactly the one that record makes: so every score is the stored result's first mode (the derivation re-reads and
validates each stored result and its input), a JEV-decided iteration's candidate is its own send's proposal, the
units are the steps whose job reserved its unit, and the pins are the creation pins.

Summary rules that are this module's reading of spec 8.2 (see the T6-B report's spec_gaps):
* ``iterations[]`` holds the record's iterations that have at least one approval (an iteration with sends only, its
  proposal never approved, is not one; its sends are in ``counts.sends_dispatched``). ``send_id`` is the send whose
  proposal decided a ``jev`` iteration, null for a ``human`` one; the steps drop the record's ``evaluation``.
* ``unfinished`` lists every iteration that never started (state ``unavailable``: its latest first-step approval's
  job was lost before any process), with that approval's candidate.
* ``limitations`` are LJ ids: LJ1-LJ3, LJ4 | LJ5, LJ6 | LJ7, then LJ8 when a candidate is ``pending`` or
  ``unavailable`` at the end.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from typing import Any

from . import jev_constants as J
from . import jev_loop_constants as L
from . import jev_loops as JL
from .core.handles import canonical_json

RESULT_KEYS = ("schema", "method_version", "branch", "loop_id", "goal", "loop_seed", "iteration_cap",
               "effective_cap", "end_reason", "pool", "setup", "setup_sha256", "pins", "counts", "candidates",
               "iterations", "unfinished", "limitations")
POOL_KEYS = ("source", "structure", "filter", "candidates")
ITERATION_KEYS = ("index", "decided_by", "candidate_ref", "proposal_handle", "send_id", "list_position", "list_size",
                  "approvals", "steps", "state", "score_kcal_mol")
STEP_KEYS = ("step", "candidate_ref", "job_id", "call_key", "result_handle", "state", "reason_code")
UNFINISHED_KEYS = ("iteration", "candidate_ref")
END_STATES = ("scored", "null_result", "failed", "not_run")       # the outcome of a started, finished iteration
STEP_END_STATES = ("completed", "failed", "unavailable", "reused")  # no step waits or runs once a loop ends
CHARGED_STEP_STATES = ("completed", "failed")                     # the job reserved its unit, a process started
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_HANDLE_RE = re.compile(r"obj://[A-Za-z0-9][A-Za-z0-9_-]{0,79}/[a-z][a-z0-9_]{0,63}/[0-9a-f]{64}")


class LoopResultInvalid(ValueError):
    """A ``jev_loop_result@1`` that is not the summary of its loop (shape, closed sets, consistency or content)."""


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise LoopResultInvalid(message)


def _int(value: Any, low: int | None = None, high: int | None = None) -> bool:
    return type(value) is int and (low is None or value >= low) and (high is None or value <= high)


def _score(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _ref(branch: str, value: Any) -> bool:
    if branch == "ligand":
        return type(value) is str and J.CANDIDATE_ID_RE.fullmatch(value) is not None
    return _int(value, 0)


def _handle(value: Any) -> bool:
    return type(value) is str and _HANDLE_RE.fullmatch(value) is not None


def _keys(value: Any, keys: tuple[str, ...], name: str) -> None:
    """Exactly these keys (a stored summary is canonical JSON, so its key order is not the build order)."""
    _need(type(value) is dict and set(value) == set(keys) and len(value) == len(keys), f"{name} keys")


# --- build ---------------------------------------------------------------------------------------------------------------

def _iteration(row: dict[str, Any]) -> dict[str, Any]:
    send_id = None
    if row["decided_by"] == "jev":
        send_id = next((send["send_id"] for send in row["sends"] if send["proposal_handle"] is not None
                        and send["proposal_handle"] == row["proposal_handle"]), None)
    return {"index": row["index"], "decided_by": row["decided_by"], "candidate_ref": row["candidate_ref"],
            "proposal_handle": row["proposal_handle"], "send_id": send_id, "list_position": row["list_position"],
            "list_size": row["list_size"], "approvals": copy.deepcopy(row["approvals"]),
            "steps": [{name: copy.deepcopy(step[name]) for name in STEP_KEYS} for step in row["steps"]],
            "state": row["state"], "score_kcal_mol": row["score_kcal_mol"]}


def build_loop_result(record: dict[str, Any], end_reason: str) -> dict[str, Any]:
    """The ``jev_loop_result@1`` of a loop that ends now with ``end_reason`` (``jev_loops.end_reason_for``), from its
    derived ``jev_loop@1`` record. No clock, job attempt or call id is added (job ids stay in the steps as read
    evidence), so the same record makes the same bytes and the same handle."""
    kind = L.KIND_FOR_BRANCH[record["branch"]]
    iterations = [_iteration(row) for row in record["iterations"] if row["approvals"]]
    uncomputed = any(row["state"] in ("pending", "unavailable") for row in record["candidates"])
    return {
        "schema": L.RESULT_SCHEMA, "method_version": L.RESULT_METHOD_VERSION, "branch": record["branch"],
        "loop_id": record["loop_id"], "goal": record["goal"], "loop_seed": record["loop_seed"],
        "iteration_cap": record["iteration_cap"], "effective_cap": record["effective_cap"], "end_reason": end_reason,
        "pool": copy.deepcopy(record["pool"]), "setup": copy.deepcopy(record["setup"]),
        "setup_sha256": record["setup_sha256"], "pins": copy.deepcopy(record["pins"]),
        "counts": {name: record["counts"][name] for name in JL.COUNT_KEYS},
        "candidates": [{name: copy.deepcopy(row[name]) for name in JL.CANDIDATE_KEYS} for row in record["candidates"]],
        "iterations": iterations,
        "unfinished": [{"iteration": row["index"], "candidate_ref": row["candidate_ref"]} for row in iterations
                       if row["state"] == "unavailable"],
        "limitations": L.limitation_ids(kind, record["goal"], uncomputed_left=uncomputed),
    }


# --- validate ----------------------------------------------------------------------------------------------------------

def _check_pool(content: dict[str, Any]) -> list[Any]:
    branch, pool = content["branch"], content["pool"]
    kind = L.KIND_FOR_BRANCH[branch]
    _keys(pool, POOL_KEYS, "pool")
    source = pool["source"]
    _need(type(source) is dict and set(source) == {"handle", "schema"} and _handle(source["handle"])
          and source["schema"] == J.SOURCE_SCHEMAS[kind], "pool source")
    if branch == "protein":
        _need(type(pool["structure"]) is dict and set(pool["structure"]) == {"handle", "model_number"}
              and _handle(pool["structure"]["handle"]) and _int(pool["structure"]["model_number"]), "pool structure")
        _need(pool["filter"] is None, "a protein pool has no filter")
    else:
        _need(pool["structure"] is None and (pool["filter"] is None or type(pool["filter"]) is dict), "ligand pool")
    rows = pool["candidates"]
    _need(type(rows) is list and L.MIN_POOL <= len(rows) <= L.MAX_POOL, "pool size")
    for row in rows:
        _keys(row, ("ref", "display"), "pool candidate")
        _need(_ref(branch, row["ref"]) and type(row["display"]) is dict, "pool candidate ref / display")
    refs = [row["ref"] for row in rows]
    _need(len(set(map(canonical_json, refs))) == len(refs), "pool candidates repeat")
    return refs


def _check_candidates(content: dict[str, Any], refs: list[Any]) -> dict[Any, dict[str, Any]]:
    branch, rows = content["branch"], content["candidates"]
    _need(type(rows) is list and len(rows) == len(refs), "candidate rows")
    by_ref = {}
    for row, item in zip(rows, content["pool"]["candidates"], strict=True):
        _keys(row, JL.CANDIDATE_KEYS, "candidate")
        _need(canonical_json(row["ref"]) == canonical_json(item["ref"]) and row["display"] == item["display"],
              "candidate rows follow the pool")
        state, evaluation, score, number = row["state"], row["evaluation"], row["score_kcal_mol"], row["iteration"]
        _need(state in L.CANDIDATE_STATES and evaluation in (*L.EVALUATIONS, None), "candidate state")
        _need(_score(score) if state == "scored" else score is None, "a score only for scored, never a stand-in")
        if state in ("pending", "unavailable"):
            _need(evaluation is None and number is None, "an uncomputed candidate has no evaluation")
        elif evaluation == "reused":
            _need(state in ("scored", "null_result") and number is None, "a reused stored result")
        else:
            _need(evaluation == "computed" and _int(number, 1, L.MAX_ITERATION_CAP), "a computed candidate")
            _need(state != "not_run" or branch == "protein", "not_run is a protein state")
        by_ref[canonical_json(row["ref"])] = row
    return by_ref


def _check_step(branch: str, step: Any, refs_json: set[bytes]) -> None:
    _keys(step, STEP_KEYS, "step")
    state = step["state"]
    _need(step["step"] in L.BRANCH_STEPS[branch] and canonical_json(step["candidate_ref"]) in refs_json
          and state in STEP_END_STATES and type(step["call_key"]) is str and _SHA_RE.fullmatch(step["call_key"]),
          "step values")
    if state == "reused":
        _need(step["job_id"] is None, "an adopted result has no job")
    elif state in CHARGED_STEP_STATES:
        _need(type(step["job_id"]) is str, "a charged step names its job")
    else:
        _need(step["job_id"] is None or type(step["job_id"]) is str, "step job")
    _need((step["result_handle"] is not None) == (state in ("completed", "reused"))
          and (step["result_handle"] is None or _handle(step["result_handle"])), "step result")
    _need(step["reason_code"] is None or type(step["reason_code"]) is str, "step reason")
    _need(state != "reused" or step["step"] in ("model", "dock"), "only a stored model or docking is adopted")


def _check_iteration(branch: str, row: Any, number: int, refs_json: set[bytes]) -> None:
    _keys(row, ITERATION_KEYS, "iteration")
    _need(_int(row["index"]) and row["index"] == number, "iterations are numbered 1, 2, ...")
    _need(row["decided_by"] in L.DECIDED_BY and canonical_json(row["candidate_ref"]) in refs_json, "decision")
    _need(row["state"] in (*END_STATES, "unavailable"), "a finished iteration state")
    _need(_score(row["score_kcal_mol"]) if row["state"] == "scored" else row["score_kcal_mol"] is None,
          "iteration score")
    jev = row["decided_by"] == "jev"
    _need((row["proposal_handle"] is not None) == jev and (row["send_id"] is not None) == jev
          and (row["list_position"] is not None) == jev and (row["list_size"] is not None) == jev,
          "a JEV decision names its proposal, send and list place; a human one none")
    if jev:
        _need(_handle(row["proposal_handle"]) and type(row["send_id"]) is str
              and _int(row["list_size"], 1) and _int(row["list_position"], 1, row["list_size"]), "JEV decision values")
    approvals, steps = row["approvals"], row["steps"]
    _need(type(approvals) is list and approvals and type(steps) is list and len(steps) == len(approvals),
          "one step per approval")
    first = L.BRANCH_STEPS[branch][0]
    for approval, step in zip(approvals, steps, strict=True):
        _keys(approval, JL.APPROVAL_KEYS, "approval")
        _need(approval["decided_by"] in L.DECIDED_BY and (approval["proposal_handle"] is not None)
              == (approval["decided_by"] == "jev"), "approval decision")
        _check_step(branch, step, refs_json)
        _need((approval["step"], canonical_json(approval["candidate_ref"]), approval["call_key"])
              == (step["step"], canonical_json(step["candidate_ref"]), step["call_key"]), "the step of each approval")
    firsts = [(approval, step) for approval, step in zip(approvals, steps, strict=True) if approval["step"] == first]
    _need(firsts and approvals[0]["step"] == first, "an iteration starts with its first step")
    latest, latest_step = firsts[-1]
    _need((canonical_json(latest["candidate_ref"]), latest["decided_by"], latest["proposal_handle"])
          == (canonical_json(row["candidate_ref"]), row["decided_by"], row["proposal_handle"]),
          "the iteration's decision is its latest first-step approval")
    _need(all(step["state"] == "unavailable" for _approval, step in firsts[:-1]), "an earlier approval was lost")
    docks = [step for approval, step in zip(approvals, steps, strict=True) if approval["step"] == "dock"]
    if row["state"] == "unavailable":
        _need(latest_step["state"] == "unavailable" and not docks, "an iteration that never started")
    else:
        _need(latest_step["state"] != "unavailable", "a started iteration")
        _need(all(canonical_json(step["candidate_ref"]) == canonical_json(row["candidate_ref"]) for step in docks)
              and len(docks) <= 1, "the docking of the iteration's candidate")


def _check_iterations(content: dict[str, Any], refs: list[Any], by_ref: dict[bytes, dict[str, Any]]) -> list[Any]:
    branch, rows = content["branch"], content["iterations"]
    refs_json = {canonical_json(ref) for ref in refs}
    _need(type(rows) is list and len(rows) <= L.MAX_ITERATION_CAP, "iterations")
    started = []
    for number, row in enumerate(rows, 1):
        _check_iteration(branch, row, number, refs_json)
        if row["state"] != "unavailable":
            started.append(row)
            candidate = by_ref[canonical_json(row["candidate_ref"])]
            _need(candidate["evaluation"] == "computed" and candidate["iteration"] == row["index"]
                  and candidate["state"] == row["state"] and candidate["score_kcal_mol"] == row["score_kcal_mol"]
                  and type(candidate["score_kcal_mol"]) is type(row["score_kcal_mol"]),
                  "a computed candidate is its iteration's")
    computed = [row for row in content["candidates"] if row["evaluation"] == "computed"]
    _need(len(computed) == len(started), "every computed candidate has its own iteration")
    _need(content["unfinished"] == [{"iteration": row["index"], "candidate_ref": row["candidate_ref"]}
                                    for row in rows if row["state"] == "unavailable"]
          and all(set(item) == set(UNFINISHED_KEYS) for item in content["unfinished"]), "unfinished iterations")
    return started


def _check_counts(content: dict[str, Any], started: list[Any]) -> None:
    counts = content["counts"]
    _keys(counts, JL.COUNT_KEYS, "counts")
    _need(all(_int(value, 0) for value in counts.values()), "counts are non-negative integers")
    steps = [step for row in content["iterations"] for step in row["steps"]]
    _need(counts["started"] == counts["done"] == len(started) <= content["effective_cap"],
          "every started iteration has ended, within the effective cap")
    _need(counts["jev_decided"] == sum(row["decided_by"] == "jev" for row in started)
          and counts["human_decided"] == sum(row["decided_by"] == "human" for row in started), "decision counts")
    _need(counts["units_charged"] == sum(step["state"] in CHARGED_STEP_STATES for step in steps), "charged units")
    _need(counts["reused_count"] == sum(row["evaluation"] == "reused" for row in content["candidates"]), "reused")
    _need(counts["sends_dispatched"] >= counts["jev_decided"], "every JEV decision came from a dispatched send")


def validated_loop_result(content: Any, record: dict[str, Any] | None = None,
                          end_reason: str | None = None) -> dict[str, Any]:
    """Spec 8.2 on every build and read (module docstring). ``record`` (with ``end_reason``, default the summary's):
    the loop's ``jev_loop@1`` derived again from the events up to its ``jev_loop_ended`` event; the summary must be
    the exact one it makes. ``LoopResultInvalid`` otherwise; returns ``content``."""
    _keys(content, RESULT_KEYS, "summary")
    try:
        raw = canonical_json(content)
    except (TypeError, ValueError) as exc:
        raise LoopResultInvalid("the summary is not canonical JSON") from exc
    _need(len(raw) <= L.MAX_OBJECT_BYTES, "the summary exceeds its size limit")
    _need(content["schema"] == L.RESULT_SCHEMA and content["method_version"] == L.RESULT_METHOD_VERSION, "schema")
    branch, goal = content["branch"], content["goal"]
    _need(branch in L.BRANCHES and goal in L.GOALS and L.is_loop_id(content["loop_id"]), "branch / goal / loop_id")
    _need(_int(content["loop_seed"], L.MIN_LOOP_SEED, L.MAX_LOOP_SEED)
          and _int(content["iteration_cap"], L.MIN_ITERATION_CAP, L.MAX_ITERATION_CAP), "seed / cap")
    _need(content["end_reason"] in L.END_REASONS and content["end_reason"] != "run_cancelled", "end reason")
    _need(type(content["setup"]) is dict and type(content["pins"]) is dict
          and content["setup_sha256"] == hashlib.sha256(canonical_json(content["setup"])).hexdigest(), "setup / pins")
    refs = _check_pool(content)
    _need(content["effective_cap"] == min(content["iteration_cap"], len(refs)), "effective_cap")
    by_ref = _check_candidates(content, refs)
    _need(type(content["unfinished"]) is list, "unfinished")
    started = _check_iterations(content, refs, by_ref)
    _check_counts(content, started)
    pending = [row for row in content["candidates"] if row["state"] == "pending"]
    if len(started) == content["effective_cap"]:
        expected = ("iteration_cap",)
    elif not pending:
        expected = ("pool_exhausted",)
    else:
        expected = ("budget_exhausted", "ended_by_user")
    _need(content["end_reason"] in expected, "the end reason is not what the summary shows")
    uncomputed = any(row["state"] in ("pending", "unavailable") for row in content["candidates"])
    _need(content["limitations"] == L.limitation_ids(L.KIND_FOR_BRANCH[branch], goal, uncomputed_left=uncomputed),
          "limitation ids")
    if record is not None:
        expected_content = build_loop_result(record, content["end_reason"] if end_reason is None else end_reason)
        _need(raw == canonical_json(expected_content), "the summary is not its loop's summary at the end")
    return content
