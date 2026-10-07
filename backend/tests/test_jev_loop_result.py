"""M25 T6-B: the loop summary ``jev_loop_result@1`` in ``mw.jev_loop_result`` (spec .dryforge/spec.md 8.1, 8.2, 9.3).

Pure tests. The records are derived by ``jev_loops.derive_loop`` from LABELLED SYNTHETIC event logs (the T2 ``Log``
builder: made-up candidate ids / indexes, call keys, handles, budgets and scores standing in for a run's log; none is
a result). The expected summaries are written by hand from spec 8.2 next to each case (keys, ``unfinished``,
``send_id``, LJ ids, counts); the tampering cases change one field each. The engine-backed summaries of real ligand and
protein loops and the read path are in ``test_jev_loops_compute.py``.
"""
from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_jev_loops_derive import IDS, LOOP, Log, docked, handle, key, modelled
from test_jev_loops_derive import derive as derive_state

from mw import jev_loop_constants as L
from mw import jev_loop_result as R
from mw.core.handles import canonical_json

MW = Path(__file__).resolve().parents[1] / "mw"
RESULT_KEYS = ["schema", "method_version", "branch", "loop_id", "goal", "loop_seed", "iteration_cap",
               "effective_cap", "end_reason", "pool", "setup", "setup_sha256", "pins", "counts", "candidates",
               "iterations", "unfinished", "limitations"]                       # spec 8.2, written out
ITERATION_KEYS = ["index", "decided_by", "candidate_ref", "proposal_handle", "send_id", "list_position", "list_size",
                  "approvals", "steps", "state", "score_kcal_mol"]
STEP_KEYS = ["step", "candidate_ref", "job_id", "call_key", "result_handle", "state", "reason_code"]


def ligand_story():
    """Pool A-E (cap 4). Iteration 1: JEV chose B (send at position 2/4), B docked and scored. Iteration 2: A
    approved, its job cancelled before start (A unavailable), then C approved and docked with no mode. Iteration 3: D
    approved, cancelled before start (unfinished). E is never computed."""
    a, b, c, d = IDS[:4]
    log = Log()
    log.created(pool=IDS[:5], cap=4)
    log.consent(True)
    send_id, choice = log.send(1, ref=b, position=2, size=4)
    log.approve(1, b, by="jev", proposal=choice)
    job_b = log.run_job(b)
    log.approve(2, a)
    log.cancel(log.submit(a))
    log.approve(2, c)
    job_c = log.run_job(c)
    log.approve(3, d)
    job_d = log.submit(d)
    log.cancel(job_d)
    results = docked(b, 2, -7.25) | docked(c, 0, None)
    return log, results, {"send_id": send_id, "choice": choice, "jobs": (job_b, job_c, job_d)}


def protein_story():
    """Pool 3, 7, 11, 19 (cap 2). Iteration 1: 7 modelled then docked (scored). Iteration 2: 11's model adopted
    (stored, no unit) and its docking abandoned (not_run). The cap is reached."""
    log = Log()
    log.created("protein", goal="explore", cap=2)
    log.approve(1, 7, "model")
    model_job = log.run_job(7, "model")
    log.approve(1, 7, "dock")
    dock_job = log.run_job(7, "dock")
    log.approve(2, 11, "model", units=0)
    log.abandon(2, 11)
    results = modelled(7) | modelled(11) | docked(7, 3, -4.5, "dock")
    return log, results, {"jobs": (model_job, dock_job)}


def summary(log, results, reason):
    state = derive_state(log, results=results)
    return R.build_loop_result(state.record, reason), state.record


def test_the_ligand_summary_has_the_spec_keys_and_values():
    log, results, story = ligand_story()
    content, record = summary(log, results, "ended_by_user")
    a, b, c, d = IDS[:4]
    job_b, job_c, job_d = story["jobs"]
    assert list(content) == RESULT_KEYS
    assert (content["schema"], content["method_version"]) == ("jev_loop_result@1", "mw.jev_loop_result/v1")
    assert (content["branch"], content["loop_id"], content["goal"], content["loop_seed"], content["iteration_cap"],
            content["effective_cap"], content["end_reason"]) == ("ligand", LOOP, "exploit", 7, 4, 4, "ended_by_user")
    e = IDS[4]
    assert content["pool"] == record["pool"] and set(content["pool"]) == {"source", "structure", "filter",
                                                                          "candidates"}
    assert (content["setup"], content["setup_sha256"], content["pins"]) == (record["setup"], record["setup_sha256"],
                                                                            record["pins"])
    assert content["counts"] == {"started": 2, "done": 2, "jev_decided": 1, "human_decided": 1, "sends_dispatched": 1,
                                 "units_charged": 2, "reused_count": 0}
    assert [(row["ref"], row["state"], row["evaluation"], row["score_kcal_mol"], row["iteration"])
            for row in content["candidates"]] == [(a, "unavailable", None, None, None), (b, "scored", "computed",
                                                                                        -7.25, 1),
                                                  (c, "null_result", "computed", None, 2),
                                                  (d, "unavailable", None, None, None), (e, "pending", None, None, None)]
    first, second, third = content["iterations"]
    assert [list(row) for row in content["iterations"]] == [ITERATION_KEYS] * 3
    assert (first["decided_by"], first["candidate_ref"], first["proposal_handle"], first["send_id"],
            first["list_position"], first["list_size"], first["state"], first["score_kcal_mol"]) == (
        "jev", b, story["choice"], story["send_id"], 2, 4, "scored", -7.25)
    assert first["steps"] == [{"step": "ligand_dock", "candidate_ref": b, "job_id": job_b,
                               "call_key": key(b, "ligand_dock"), "result_handle": handle("docking_result", b,
                                                                                          "ligand_dock"),
                               "state": "completed", "reason_code": None}]
    assert [list(step) for step in first["steps"]] == [STEP_KEYS]
    # iteration 2: A approved first and lost before start (approvals only), C the latest first-step approval
    assert [item["candidate_ref"] for item in second["approvals"]] == [a, c]
    assert (second["decided_by"], second["candidate_ref"], second["send_id"], second["state"]) == (
        "human", c, None, "null_result")
    assert [(step["candidate_ref"], step["state"]) for step in second["steps"]] == [(a, "unavailable"),
                                                                                  (c, "completed")]
    assert second["steps"][1]["job_id"] == job_c
    assert (third["candidate_ref"], third["state"], third["steps"][0]["job_id"]) == (d, "unavailable", job_d)
    assert content["unfinished"] == [{"iteration": 3, "candidate_ref": d}]
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ6", "LJ8"]      # unavailable candidates left
    assert R.validated_loop_result(content, record, "ended_by_user") == content
    assert R.validated_loop_result(content) == content


def test_the_protein_summary_counts_an_adopted_model_as_no_unit_and_ends_at_the_cap():
    log, results, story = protein_story()
    content, record = summary(log, results, "iteration_cap")
    model_job, dock_job = story["jobs"]
    assert content["counts"] == {"started": 2, "done": 2, "jev_decided": 0, "human_decided": 2, "sends_dispatched": 0,
                                 "units_charged": 2, "reused_count": 0}
    first, second = content["iterations"]
    assert [(step["step"], step["job_id"], step["state"]) for step in first["steps"]] == [
        ("model", model_job, "completed"), ("dock", dock_job, "completed")]
    assert [(step["step"], step["job_id"], step["state"], step["result_handle"]) for step in second["steps"]] == [
        ("model", None, "reused", handle("mutation_model_result", 11))]
    assert (second["state"], second["score_kcal_mol"]) == ("not_run", None)
    assert content["unfinished"] == [] and content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ5", "LJ7", "LJ8"]
    assert content["pool"]["structure"] == record["pool"]["structure"] is not None
    assert R.validated_loop_result(content, record, "iteration_cap") == content
    for reason in ("pool_exhausted", "ended_by_user", "budget_exhausted"):   # the cap was reached: only iteration_cap
        with pytest.raises(R.LoopResultInvalid):
            R.validated_loop_result({**content, "end_reason": reason})


def test_the_end_reason_follows_the_summary_and_lj8_only_with_an_uncomputed_candidate():
    a, b = IDS[:2]
    log = Log()
    log.created(pool=[a, b])
    log.approve(1, a)
    log.run_job(a)
    log.approve(2, b)
    log.run_job(b)
    content, record = summary(log, docked(a, 1, -3.0) | docked(b, 1, -2.0), "iteration_cap")
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ6"]               # nothing left uncomputed
    assert R.validated_loop_result(content, record) == content
    log = Log()
    log.created(pool=[a, b])
    content, _record = summary(log, {}, "ended_by_user")
    assert content["limitations"][-1] == "LJ8" and content["iterations"] == [] and content["unfinished"] == []
    for reason in ("ended_by_user", "budget_exhausted"):
        assert R.validated_loop_result({**content, "end_reason": reason})["end_reason"] == reason
    for reason in ("iteration_cap", "pool_exhausted", "run_cancelled", "best"):
        with pytest.raises(R.LoopResultInvalid):
            R.validated_loop_result({**content, "end_reason": reason})


def _tampered(content, path, value):
    out = copy.deepcopy(content)
    target = out
    for part in path[:-1]:
        target = target[part]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return out


@pytest.mark.parametrize("path, value", [
    (("candidates", 1, "score_kcal_mol"), -9.0),                 # a score that is not the stored first mode
    (("candidates", 1, "score_kcal_mol"), 0),                    # no score is never zero
    (("candidates", 1, "state"), "pending"),
    (("candidates", 0, "ref"), "c_00000000000000ff"),             # a candidate outside the pool
    (("candidates", 3, "score_kcal_mol"), -1.0),
    (("end_reason",), "pool_exhausted"),
    (("counts", "units_charged"), 3),
    (("counts", "started"), 3),
    (("counts", "jev_decided"), 0),
    (("iterations", 0, "decided_by"), "human"),
    (("iterations", 0, "list_position"), 1),
    (("iterations", 0, "send_id"), None),
    (("iterations", 0, "steps", 0, "state"), "reused"),
    (("iterations", 1, "candidate_ref"), IDS[0]),
    (("unfinished",), []),
    (("limitations",), ["LJ1", "LJ2", "LJ3", "LJ4", "LJ6"]),
    (("loop_seed",), 8),
    (("effective_cap",), 3),
    (("pins",), {"other": True}),
    (("rank",), [IDS[1]]),                                       # ranking / difference / best fields cannot exist
    (("best_candidate",), IDS[1]),
    (("candidates", 1, "rank"), 1),
    (("iterations", 0, "improved"), True),
    (("counts", "best"), 1),
    (("unfinished",), ...),
])
def test_a_tampered_summary_is_refused(path, value):
    log, results, _story = ligand_story()
    content, record = summary(log, results, "ended_by_user")
    tampered = _tampered(content, path, value)
    with pytest.raises(R.LoopResultInvalid):
        R.validated_loop_result(tampered, record, "ended_by_user")


def test_the_structural_check_alone_refuses_inconsistent_summaries():
    log, results, _story = ligand_story()
    content, _record = summary(log, results, "ended_by_user")
    for path, value in ((("counts", "units_charged"), 3), (("candidates", 1, "score_kcal_mol"), -9.0),
                        (("candidates", 1, "score_kcal_mol"), 0), (("iterations", 0, "list_position"), 9),
                        (("rank",), 1), (("unfinished",), []), (("limitations",), ["LJ1"]),
                        (("candidates", 2, "iteration"), 1), (("iterations", 1, "steps", 1, "job_id"), None)):
        with pytest.raises(R.LoopResultInvalid):
            R.validated_loop_result(_tampered(content, path, value))
    with pytest.raises(R.LoopResultInvalid):
        R.validated_loop_result({**content, "padding": "x" * L.MAX_OBJECT_BYTES})
    with pytest.raises(R.LoopResultInvalid):
        R.validated_loop_result([content])


def test_the_summary_is_canonical_json_and_carries_no_clock_or_attempt():
    log, results, _story = ligand_story()
    content, _record = summary(log, results, "ended_by_user")
    raw = canonical_json(content).decode()
    for word in ("attempt", "ts", "created", "timestamp", "seq"):
        assert f'"{word}"' not in raw, word
    assert summary(log, results, "ended_by_user")[0] == content                  # same record, same summary
    stored = json.loads(raw)                    # a stored summary reads back with canonical (sorted) key order
    assert list(stored) != list(content) and R.validated_loop_result(stored, _record) == stored


def test_the_result_module_is_pure_and_names_no_send_or_limit_path():
    text = (MW / "jev_loop_result.py").read_text()
    assert "raise_limits" not in text and "limit_approval" not in text
    tree = ast.parse(text)
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {module for module in modules if "jev_sends" in module or "egress" in module or "jobs" in module}
    names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
             if isinstance(node, (ast.Name, ast.Attribute))}
    assert not names & {"open", "store", "events", "run", "run_send", "request_science", "JobQueue", "time"}
    code = ("import sys, mw.jev_loop_result\n"
            "bad = [m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'mw.jobs.queue', 'fastapi', 'gemmi', 'numpy')"
            " if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
