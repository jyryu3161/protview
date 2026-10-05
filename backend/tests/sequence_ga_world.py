"""Shared M23 T6 world for the sequence GA read API and report tests: real product output only.

One run is built through the unmodified product path (``sequence_ga_fixture.real_world``: public 1UBQ, the real tiny
M20 set, the labeled synthetic phenol SDF), then four real GA jobs run through ``JobQueue`` with the real GA worker
(``.deps/docking/venv-locked`` + ``qvina2``) and the real modeling child (project ``.venv``: OpenMM, PDBFixer); a
missing environment FAILS, never skips:

- ``complete``: the T5 GA (seed 21, P 4, G 2, E 1, 7 new evaluations), ``generations_complete`` (S1, S4-S6);
- ``partial``: GA seed 4 with ``max_new_evaluations`` 4 reusing the complete run's rows, ``evaluation_limit``
  (S1-S6; carried, crossover, edit and reused individuals);
- ``faulted``: one generation under other docking values (seed + 1, nothing reusable) where the server refuses one
  individual's docking output and another individual's model files at publication (LABELED FAULTS through internal
  test hooks on ``sequence_ga_jobs._publish_result`` / ``_publish_model``, never a request field): the first is
  ``failed`` (``engine_output_invalid``) with a stored model and no result, the second ``failed`` (``worker_failed``)
  with neither;
- ``reference_failed``: the labeled synthetic implicit-H SDF with a manual box, refused by RDKit in the reference
  row's docking (no generation, a stored reference model, no result).

Paths are checked against the independent T1 oracle (``fixtures/sequence_ga/independent_sequence_ga_oracle.py``) fed
with the T1 real-engine observations, never against product code. The world is built once per test session (both
T6 test modules share it); tests that write copy it first. ``base_root`` keeps the run before any GA (an unused
combination space for preflight cases).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ligand_job_fixture import import_file
from sequence_ga_fixture import real_world
from test_sequence_ga_jobs import (
    DOCK,
    GA,
    IMPLICIT_H,
    evaluated,
    ga_args,
    no_strays,
    oracle_path,
    path,
    raise_limits,
    run_ga,
    summary,
    world,
)

from mw import docking_bundle
from mw import sequence_ga_jobs as SJ
from mw.workspace import new_run

PARTIAL_GA = {"seed": 4, "max_new_evaluations": 4}
FAULTED_GA = {"generations": 1, "max_new_evaluations": 4}
FAULT_RESULT_EVAL = 1   # the server refuses this new evaluation's docking output (labeled fault): a model, no result
FAULT_MODEL_EVAL = 2    # the server refuses this new evaluation's model files (labeled fault): no model, no result
_CACHE: dict[str, Any] = {}


def _faulted(run, args: dict[str, Any]) -> dict[str, Any]:
    """LABELED FAULT: at publication the server refuses individual ``FAULT_RESULT_EVAL``'s docking output and
    individual ``FAULT_MODEL_EVAL``'s model files (internal test hooks; the worker ran as usual)."""
    publish_result, publish_model = SJ._publish_result, SJ._publish_model

    def refused_result(run_, ctx, attempt_id, directory, prefix, model_handle, side):
        if prefix == f"{FAULT_RESULT_EVAL}.":
            return None
        return publish_result(run_, ctx, attempt_id, directory, prefix, model_handle, side)

    def refused_model(run_, ctx, attempt_id, directory, prefix, rows, reference):
        if prefix == f"{FAULT_MODEL_EVAL}.":
            return None
        return publish_model(run_, ctx, attempt_id, directory, prefix, rows, reference)

    SJ._publish_result, SJ._publish_model = refused_result, refused_model
    try:
        return run_ga(run, args)
    finally:
        SJ._publish_result, SJ._publish_model = publish_result, publish_model


def build_world(directory: Path) -> dict[str, Any]:
    for item in (docking_bundle.WORKER_PYTHON, docking_bundle.QVINA, SJ.PROJECT_PYTHON):
        assert item.is_file(), f"pinned environment missing at {item} (no skip)"
    base_root = directory / "base"
    base = {**real_world(base_root), "root": base_root}
    run, root = world(base, directory, "runs")
    raise_limits(run)
    args = {"complete": ga_args(base), "partial": ga_args(base, **PARTIAL_GA),
            "faulted": {**ga_args(base, **FAULTED_GA), "parameters": {**DOCK, "seed": DOCK["seed"] + 1}}}
    jobs: dict[str, dict[str, Any]] = {}
    handles: dict[str, str] = {}
    stored: dict[str, dict[str, Any]] = {}

    def finished(name: str, job: dict[str, Any]) -> None:
        assert job["status"] == "done", job
        jobs[name] = job
        handles[name], stored[name] = summary(run, job)

    finished("complete", run_ga(run, args["complete"]))
    expected = oracle_path(GA)
    assert path(stored["complete"]) == path(expected)
    assert (stored["complete"]["stop_reason"], stored["complete"]["limitations"]) == (
        "generations_complete", ["S1", "S4", "S5", "S6"])
    seen = [entry["key"] for entry in evaluated(stored["complete"])]
    finished("partial", run_ga(run, args["partial"]))
    expected = oracle_path({**GA, **PARTIAL_GA}, reusable=[*seen, "wild_type"])
    assert path(stored["partial"]) == path(expected)
    assert (stored["partial"]["status"], stored["partial"]["stop_reason"], stored["partial"]["limitations"]) == (
        "partial", "evaluation_limit", ["S1", "S2", "S3", "S4", "S5", "S6"])
    finished("faulted", _faulted(run, args["faulted"]))
    failed = [entry for entry in evaluated(stored["faulted"]) if entry["state"] == "failed"]
    assert [(entry["eval_index"], entry["reason_code"], entry["result_handle"]) for entry in failed] == [
        (FAULT_RESULT_EVAL, "engine_output_invalid", None), (FAULT_MODEL_EVAL, "worker_failed", None)]
    assert failed[0]["model_handle"] is not None and failed[1]["model_handle"] is None
    assert [entry["key"] for entry in evaluated(stored["faulted"])] == [
        entry["key"] for gen in oracle_path({**GA, **FAULTED_GA})["generations"] for entry in gen["individuals"]]
    sdf = import_file(run, "ligand_sdf", "implicit-h.sdf", IMPLICIT_H)
    box = SJ._admitted(run, SJ.submission(run, args["complete"], 1200)[0])["box"]
    args["reference_failed"] = {**ga_args(base), "ligand": {"source": "sdf", "sdf_handle": sdf},
                                "box": {"source": "manual", "center_A": box["center_A"],
                                        "size_A": [20.0, 20.0, 20.0]}}
    finished("reference_failed", run_ga(run, args["reference_failed"]))
    reference = stored["reference_failed"]["reference"]
    assert (stored["reference_failed"]["stop_reason"], stored["reference_failed"]["generations"]) == (
        "reference_failed", [])
    assert reference["state"] == "failed" and reference["model_handle"] is not None
    assert reference["result_handle"] is None and reference["score"] is None
    no_strays(run)
    return {"root": root, "base_root": base_root, "rid": base["rid"],
            "base": {key: value for key, value in base.items() if key not in ("run", "root")},
            "args": args, "jobs": jobs, "handles": handles, "stored": stored}


def shared_world(tmp_path_factory) -> dict[str, Any]:
    """The session's world, built on first use (the GA runs take minutes)."""
    if "world" not in _CACHE:
        _CACHE["world"] = build_world(tmp_path_factory.mktemp("m23_t6_world"))
    return _CACHE["world"]


def copy_run(world_: dict[str, Any], root: Path, *, events_only: bool = False) -> Path:
    """A copy of the world's run under ``root`` (whole directory, or the event log only and an events-only reopen)."""
    rid = world_["rid"]
    if events_only:
        (root / rid).mkdir(parents=True)
        shutil.copyfile(world_["root"] / rid / "events.jsonl", root / rid / "events.jsonl")
        run = new_run(root, run_id=rid, dry_run=False)
        with run._owner():
            run.store.rebuild_from_events()
    else:
        shutil.copytree(world_["root"] / rid, root / rid)
    return root
