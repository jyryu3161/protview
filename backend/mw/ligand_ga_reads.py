"""M22 read-only projections for GA design (spec .dryforge/spec.md 6, 8). No RDKit, no Meeko, no qvina, no tool,
no job, no event, no budget record. Mirrors the M19 reads (``docking_batch_reads``).

* ``preflight()``: admission steps 1-4 of a GA request (``ligand_ga_jobs.submission`` with the timeout the screen
  always sends, the capability, the reuse plan and its staging size), then the pool counts, the eligible candidates
  with a reusable validated stored ``docking_result@1``, ``reserved_units`` (= the expected maximum of new dockings,
  reserved whatever is reused), the need, the run's remaining budget, the shortfall, ``full_run_may_be_partial``
  (``ligand_ga_inputs.preflight``), the active or complete GA job that ``POST /jobs`` would return instead of a new
  one (``ligand_ga_jobs.complete_job``) and G1. A refused request is answered with ``admission.admitted: false``, the
  closed reason and no pool, reuse or budget-need numbers. A short budget is not a refusal here: it is the shortfall.
* ``list_summaries()``: this run's ``ligand_ga_result`` objects newest first (by first publication), each
  re-validated; a summary that does not validate shows ``valid: false`` with null fields (never stale numbers).
* ``summary_detail()``: one validated summary with its generations; each individual carries ``detail_available``
  (a result handle for the M18 ``/docking/results/*`` reads).
* ``individual()``: one candidate of a validated summary: its evaluation (scores and states as stored), every
  generation slot where it appears, and the M18 detail read of its result (``docking_reads.result_detail``).

Every summary read goes through ``ligand_ga_jobs.validated_summary`` (single publication, GA selection, rebuilt
individual selections, every individual's result re-validated); failures raise ``LigandGaEvidenceError``.
"""
from __future__ import annotations

from typing import Any

from . import docking_constants as C
from . import docking_reads, ligand_ga_inputs
from . import ligand_ga_constants as GC
from . import ligand_ga_jobs as LJ
from .core.errors import FailureClass, ToolFailure
from .jobs.queue import JobQueue
from .ligand_ga_bundle import LigandGaEvidenceError, call_key

SUMMARY = GC.OUTPUT_KIND
SUMMARY_SCHEMA = GC.SUMMARY_SCHEMA
PUBLISHED_EVENT = LJ.SUMMARY_EVENT
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
PREFLIGHT_NUMBERS = ("selection_sha256", "pool", "reusable_count", "reserved_units", "max_new_dockings_expected",
                     "needed", "shortfall", "full_run_may_be_partial", "ga", "statements", "existing_job")
LIST_FIELDS = ("job_id", "attempt_id", "status", "stop_reason", "generations_done", "new_dockings_used",
               "reused_count", "reserved_units", "pool", "candidate_set_handle", "selection_sha256", "ga")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


def statements(ids: list[str]) -> list[dict[str, str]]:
    """The fixed G sentences for stored or planned ids, verbatim from the constants."""
    return [{"id": item, "text": GC.STATEMENTS[item]} for item in ids]


# ----------------------------------------------------------------- preflight (spec 6, 8)
def preflight(run: Any, args: Any) -> dict[str, Any]:
    capability = LJ.capability()
    run._refresh()
    snapshot = run.budget_snapshot()
    base = {"schema": "ligand_ga_preflight@1", "starts_job": False, "capability": capability,
            "score_label": C.SCORE_LABEL, "budget": {axis: dict(snapshot[axis]) for axis in ligand_ga_inputs.AXES},
            "remaining": ligand_ga_inputs.remaining(snapshot), **dict.fromkeys(PREFLIGHT_NUMBERS)}
    try:
        selected, normalized, _handles = LJ.submission(run, args, LJ.admission_timeout(args))
        if not capability["available"]:
            raise ToolFailure(FailureClass.precondition, capability["reason"],
                              detail={"reason_code": capability["reason_code"]})
        pins = capability["pins"]
        plan = LJ.reuse_plan(run, selected, pins)
        ligand_ga_inputs.require_reuse_size(sum(run.store.meta(handle)["size"] for handle in plan.values()))
    except ToolFailure as exc:
        return {**base, "admission": {"admitted": False, "error": exc.cls.value,
                                      "reason_code": (exc.detail or {}).get("reason_code"), "message": exc.message,
                                      "detail": exc.detail}}
    keys = ligand_ga_inputs.call_keys(selected, pins)
    computed = ligand_ga_inputs.preflight(selected, pins, {keys[cid]: handle for cid, handle in plan.items()},
                                          snapshot)
    jobs = {job["job_id"]: job for job in JobQueue(run).list()}
    job = LJ.complete_job(run, jobs, call_key(selected, pins, capability["ga_pins"]))
    return {**base, "admission": {"admitted": True, "error": None, "reason_code": None, "message": None,
                                  "detail": None},
            "selection_sha256": computed["selection_sha256"], "pool": computed["pool"],
            "reusable_count": computed["reusable_count"], "reserved_units": computed["reserved_units"],
            "max_new_dockings_expected": computed["max_new_dockings_expected"], "needed": computed["needed"],
            "remaining": computed["remaining"], "shortfall": computed["shortfall"],
            "full_run_may_be_partial": computed["full_run_may_be_partial"], "ga": normalized["ga"],
            "statements": statements(["G1"]),
            "existing_job": None if job is None else {"job_id": job["job_id"], "status": job["status"],
                                                      "summary_handle": job.get("ga_summary_handle")}}


# ----------------------------------------------------------------- summaries
def _published(run: Any) -> dict[str, dict[str, Any]]:
    """First ``ligand_ga_published`` event per summary handle, in publication order."""
    found: dict[str, dict[str, Any]] = {}
    for event in run.events.read():
        if event["type"] == PUBLISHED_EVENT and event.get("summary_handle") not in found:
            found[event["summary_handle"]] = event
    return found


def list_summaries(run: Any, offset: int, limit: int) -> dict[str, Any]:
    published = _published(run)
    newest = list(reversed(published))
    rows = []
    for handle in newest[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "published_seq": published[handle]["seq"]}
        try:
            content = LJ.validated_summary(run, handle)
            source = LJ.summary_producer(run, handle)
            row.update(valid=True, reason_code=None, job_id=source["job_id"], attempt_id=source["attempt_id"],
                       **{key: content[key] for key in LIST_FIELDS[2:]})
        except LigandGaEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", **dict.fromkeys(LIST_FIELDS))
        rows.append(row)
    return {"schema": "ligand_ga_list@1", "total": len(published), "offset": offset, "limit": limit, "rows": rows}


def summary_detail(run: Any, handle: str) -> dict[str, Any]:
    content = LJ.validated_summary(run, handle)
    source = LJ.summary_producer(run, handle)
    return {"schema": "ligand_ga_detail@1", "handle": handle, "job_id": source["job_id"],
            "attempt_id": source["attempt_id"], "published_seq": source["published_seq"],
            "score_label": C.SCORE_LABEL, "score_column_label": C.SCORE_COLUMN_LABEL,
            "score_row_label": GC.SCORE_ROW_LABEL, "statements": statements(content["limitations"]),
            "summary": content,
            "generations": [{**{key: gen[key] for key in ("index", "complete", "min_score", "max_score")},
                             "individuals": [{**entry, "detail_available": entry["result_handle"] is not None}
                                             for entry in gen["individuals"]]}
                            for gen in content["generations"]]}


def individual(run: Any, handle: str, candidate_id: Any) -> dict[str, Any]:
    """One individual of a validated summary, found by candidate id only (never by name)."""
    if type(candidate_id) is not str:
        raise ReadInvalid("candidate_id is required")
    content = LJ.validated_summary(run, handle)
    slots = [(gen["index"], position, entry) for gen in content["generations"]
             for position, entry in enumerate(gen["individuals"]) if entry["candidate_id"] == candidate_id]
    evaluated = [entry for _g, _p, entry in slots if entry["origin"] != "carried"]
    if len(evaluated) != 1:
        raise ReadInvalid("candidate_id is not an individual of this GA")
    entry = evaluated[0]
    result = entry["result_handle"]
    return {"schema": "ligand_ga_individual@1", "summary_handle": handle,
            **{key: entry[key] for key in ("candidate_id", "evaluation", "eval_index", "state", "reason_code",
                                           "score", "result_handle")},
            "appearances": [{"generation": g, "position": p, "origin": e["origin"]} for g, p, e in slots],
            "score_label": C.SCORE_LABEL, "score_row_label": GC.SCORE_ROW_LABEL,
            "m18_detail": None if result is None else docking_reads.result_detail(run, result)}
