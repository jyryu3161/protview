"""M19 read-only projections for batch docking (spec .dryforge/spec.md 6.2, 8). No RDKit, no Meeko, no qvina, no
tool, no job, no event, no budget record.

* ``preflight()``: the admission checks of a batch request (``docking_batch_jobs.submission`` and the capability, the
  same order as ``JobQueue.submit``), then per planned row whether a validated stored ``docking_result@1`` is reused
  or the row is a new docking (``docking_batch_jobs.reuse_plan``), N, the need, the run's remaining budget, the
  shortfall, ``full_batch_may_be_partial`` (``docking_batch_inputs.preflight``), the active or complete batch job that
  ``POST /jobs`` would return instead of a new one (``docking_batch_jobs.complete_job``), B1 and the M18 sentence
  numbers that follow from the request (mode, each row's ligand source, the removed instance; sentence 11 depends on
  the docked ligand and is decided by the summary). A refused request is answered with ``admission.admitted: false``,
  the closed reason and no row or budget-need numbers.
* ``list_summaries()``: this run's ``docking_batch_result`` objects in first-publication order, each re-validated; a
  summary that does not validate shows ``valid: false`` with null fields (never stale numbers).
* ``summary_detail()``: one validated summary with its rows; each row carries ``reused`` (from the publication
  record, never from the summary) and ``detail_available`` (a per-row result handle for the M18
  ``/docking/results/*`` reads).

Every summary read goes through ``docking_batch_jobs.validated_summary`` (single publication, batch selection, every
per-row result re-validated by ``docking_bundle.validated_result``); failures raise ``DockingBatchEvidenceError``.
"""
from __future__ import annotations

from typing import Any

from . import docking_batch_constants as BC
from . import docking_batch_inputs as BI
from . import docking_batch_jobs as BJ
from . import docking_constants as C
from .core.errors import FailureClass, ToolFailure
from .docking_batch_bundle import DockingBatchEvidenceError, batch_call_key
from .jobs.queue import JobQueue

SUMMARY = BC.OUTPUT_KIND
SUMMARY_SCHEMA = BC.SUMMARY_SCHEMA
PREFLIGHT_NUMBERS = ("batch_input_sha256", "mode", "include_parent", "candidate_ids", "rows", "new_dockings",
                     "reused_rows", "needed", "shortfall", "full_batch_may_be_partial", "statements", "existing_job")


def statements(batch_ids: list[str], m18_numbers: list[int]) -> dict[str, list[dict[str, Any]]]:
    """The fixed sentence texts for stored or planned ids (batch B1-B3, M18 1-11), verbatim from the constants."""
    return {"batch": [{"id": item, "text": BC.BATCH_STATEMENTS[item]} for item in batch_ids],
            "m18": [{"number": number, "text": C.LIMITATIONS[number - 1]} for number in m18_numbers]}


# ----------------------------------------------------------------- preflight (spec 6.2)
def _planned_m18(selected: dict[str, Any]) -> list[int]:
    removed = selected["receptor"]["removed_instance"] is not None
    numbers: set[int] = set()
    for row in selected["rows"]:
        source = "sdf" if row["kind"] == "parent" else "candidate"
        for sentence in C.applicable_limitations(mode=selected["arguments"]["mode"], source=source,
                                                 removed_instance=removed, unspecified_stereo_centers=None):
            numbers.add(C.LIMITATIONS.index(sentence) + 1)
    return sorted(numbers)


def preflight(run: Any, args: Any) -> dict[str, Any]:
    capability = BJ.capability()
    run._refresh()
    snapshot = run.budget_snapshot()
    base = {"schema": "docking_batch_preflight@1", "starts_job": False, "capability": capability,
            "score_label": C.SCORE_LABEL, "budget": {axis: dict(snapshot[axis]) for axis in BI.AXES},
            "remaining": BI.remaining(snapshot), **dict.fromkeys(PREFLIGHT_NUMBERS)}
    try:
        selected, normalized, _handles = BJ.submission(run, args)
        if not capability["available"]:
            raise ToolFailure(FailureClass.precondition, capability["reason"],
                              detail={"reason_code": capability["reason_code"]})
    except ToolFailure as exc:
        return {**base, "admission": {"admitted": False, "error": exc.cls.value,
                                      "reason_code": (exc.detail or {}).get("reason_code"), "message": exc.message,
                                      "detail": exc.detail}}
    pins = capability["pins"]
    plan = BJ.reuse_plan(run, selected, pins)
    existing = {key: handle for key, handle in zip(BI.row_call_keys(selected, pins), plan, strict=True)
                if handle is not None}
    computed = BI.preflight(selected, pins, existing, snapshot)
    jobs = {job["job_id"]: job for job in JobQueue(run).list()}
    job = BJ.complete_job(run, jobs, batch_call_key(selected))
    return {**base, "admission": {"admitted": True, "error": None, "reason_code": None, "message": None,
                                  "detail": None},
            "batch_input_sha256": computed["batch_input_sha256"], "mode": normalized["mode"],
            "include_parent": normalized["include_parent"], "candidate_ids": normalized["candidate_ids"],
            "rows": [{**row, "new_docking": not row["reuse"]} for row in computed["rows"]],
            "new_dockings": computed["new_dockings"],
            "reused_rows": len(computed["rows"]) - computed["new_dockings"], "needed": computed["needed"],
            "remaining": computed["remaining"], "shortfall": computed["shortfall"],
            "full_batch_may_be_partial": computed["full_batch_may_be_partial"],
            "statements": statements(["B1"], _planned_m18(selected)),
            "existing_job": None if job is None else {"job_id": job["job_id"], "status": job["status"],
                                                      "summary_handle": job.get("batch_summary_handle")}}


# ----------------------------------------------------------------- summaries
def _published(run: Any) -> dict[str, dict[str, Any]]:
    """First ``docking_batch_published`` event per summary handle, in publication order."""
    found: dict[str, dict[str, Any]] = {}
    for event in run.events.read():
        if event["type"] == "docking_batch_published" and event.get("summary_handle") not in found:
            found[event["summary_handle"]] = event
    return found


def list_summaries(run: Any, offset: int, limit: int) -> dict[str, Any]:
    published = _published(run)
    rows = []
    for handle in list(published)[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "published_seq": published[handle]["seq"]}
        try:
            content = BJ.validated_summary(run, handle)
            source = BJ.summary_producer(run, handle)
            row.update(valid=True, reason_code=None, job_id=source["job_id"], attempt_id=source["attempt_id"],
                       reused_rows=source["reused_rows"], method=content["method"],
                       mode=content["inputs"]["mode"], status=content["status"],
                       stop_reason=content["stop_reason"], batch_input_sha256=content["batch_input_sha256"],
                       include_parent=content["inputs"]["include_parent"],
                       candidate_set_handle=content["inputs"]["candidate_set"]["handle"],
                       counts=content["counts"])
        except DockingBatchEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", job_id=None, attempt_id=None, reused_rows=None,
                       method=None, mode=None, status=None, stop_reason=None, batch_input_sha256=None,
                       include_parent=None, candidate_set_handle=None, counts=None)
        rows.append(row)
    return {"schema": "docking_batch_list@1", "total": len(published), "offset": offset, "limit": limit,
            "rows": rows}


def summary_detail(run: Any, handle: str) -> dict[str, Any]:
    content = BJ.validated_summary(run, handle)
    source = BJ.summary_producer(run, handle)
    reused = list(source["reused_rows"] or [])
    limitations = content["limitations"]
    return {"schema": "docking_batch_detail@1", "handle": handle, "job_id": source["job_id"],
            "attempt_id": source["attempt_id"], "published_seq": source["published_seq"], "reused_rows": reused,
            "score_label": C.SCORE_LABEL, "score_column_label": C.SCORE_COLUMN_LABEL,
            "statements": statements(limitations["batch_statements"], limitations["m18_sentences"]),
            "summary": content,
            "rows": [{**row, "reused": row["row_index"] in reused,
                      "detail_available": row["result_handle"] is not None} for row in content["rows"]]}
