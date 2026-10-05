"""M23 read-only projections for the sequence GA design (spec .dryforge/spec.md 4, 5, 9). No RDKit, no Meeko, no
PDBFixer, no OpenMM engine, no qvina, no tool, no job, no event, no budget record. Mirrors the M22 reads
(``ligand_ga_reads``).

* ``preflight()``: admission steps 1-8 of a GA request (``sequence_ga_jobs.admission_plan`` with the timeout the
  screen always sends: capability, the M7 preflight projection, the reuse index and the staged size), then the space,
  the projected heavy atoms and the 4,890 warning, the reusable individuals and whether the reference row is reusable
  (a notice: its 2 units are reserved anyway), ``reserved_evaluations`` / ``reserved_units`` / the need / the run's
  remaining budget / the shortfall / ``full_run_may_be_partial`` (``sequence_ga_inputs.budget_figures``), the active
  or complete GA job that ``POST /jobs`` would return instead of a new one (``sequence_ga_jobs.complete_job``) and the
  sentences that hold for every run (S1, S4, S5, S6). A refused request (steps 1-8, the environment included) is
  answered with ``admission.admitted: false``, the closed reason and no space, reuse or need numbers. A short budget is
  not a refusal here: it is the shortfall.
* ``list_summaries()``: this run's ``sequence_ga_result`` objects newest first (by first publication), each
  re-validated; a summary that does not validate shows ``valid: false`` with null fields (never stale numbers).
* ``summary_detail()``: one validated summary with its generations and its wild-type reference row; each row carries
  ``detail_available`` (a result handle for the M18 ``/docking/results/*`` reads).
* ``individual()``: one row of a validated summary by key only (``12-57-203`` or ``wild_type``, never a name): its
  stored entry, every generation slot where it appears, its stored model without the atom and bond rows (S5 travels
  with the OpenMM potentials) and the M18 detail read of its result (``docking_reads.result_detail``).
* ``structure_download()``: the stored mmCIF bytes of one row's model (SHA-256 and handle checked).

Every summary read goes through ``sequence_ga_jobs.validated_summary`` on one read view (``sequence_ga_jobs.snapshot``:
the event log is read once per read and handed to every model, result and publication check; spec 9, T1 C1). Failures
raise ``SequenceGaEvidenceError`` (or ``DockingEvidenceError`` from the M18 detail read). Nothing is recomputed: values
are the stored engine values.
"""
from __future__ import annotations

from typing import Any

from . import docking_constants as C
from . import docking_reads
from . import sequence_ga_constants as SC
from . import sequence_ga_inputs as GI
from . import sequence_ga_jobs as SJ
from . import sequence_model_bundle as SM
from .core.errors import ToolFailure
from .jobs.queue import JobQueue
from .sequence_ga_bundle import SequenceGaEvidenceError

SUMMARY = SC.OUTPUT_KIND
SUMMARY_SCHEMA = SC.SUMMARY_SCHEMA
PUBLISHED_EVENT = SC.SUMMARY_EVENT
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
PREFLIGHT_STATEMENTS = ("S1", "S4", "S5", "S6")    # the sentences every run carries (spec 4)
MODEL_STATEMENTS = ("S5",)                          # with the stored OpenMM potentials of one model
PREFLIGHT_NUMBERS = ("selection_sha256", "conditions_sha256", "space", "projection_heavy_atoms", "heavy_atom_warning",
                     "reusable_count", "reference_reusable", "reserved_evaluations", "reserved_units", "needed",
                     "shortfall", "full_run_may_be_partial", "ga", "statements", "existing_job")
LIST_FIELDS = ("job_id", "attempt_id", "status", "stop_reason", "generations_done", "new_evaluations_used",
               "reused_count", "reserved_units", "space", "candidate_set", "selection_sha256", "ga")
ROW_FIELDS = ("evaluation", "state", "reason_code", "score", "model_handle", "result_handle")
MODEL_ROWS = ("final_bonds", "atom_mapping")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


class RowUnknown(LookupError):
    """A well-formed key that is not a row of the summary, or a row without a stored model (404 ``not_found``)."""


def statements(ids: Any) -> list[dict[str, str]]:
    """The fixed S sentences for stored or planned ids, verbatim from the constants."""
    return [{"id": item, "text": SC.STATEMENTS[item]} for item in ids]


# ----------------------------------------------------------------- preflight (spec 2, 7, 9)
def preflight(run: Any, args: Any) -> dict[str, Any]:
    capability = SJ.capability()
    run._refresh()
    snapshot = run.budget_snapshot()
    base = {"schema": "sequence_ga_preflight@1", "starts_job": False, "capability": capability,
            "score_label": SC.SCORE_LABEL, "budget": {axis: dict(snapshot[axis]) for axis in GI.AXES},
            "remaining": GI.remaining(snapshot), **dict.fromkeys(PREFLIGHT_NUMBERS)}
    try:
        plan = SJ.admission_plan(run, args, SJ.admission_timeout(args))
    except ToolFailure as exc:
        return {**base, "admission": {"admitted": False, "error": exc.cls.value,
                                      "reason_code": (exc.detail or {}).get("reason_code"), "message": exc.message,
                                      "detail": exc.detail}}
    ga = plan["arguments"]["ga"]
    figures = GI.budget_figures(ga, snapshot)
    jobs = {job["job_id"]: job for job in JobQueue(run).list()}
    job = SJ.complete_job(run, jobs, plan["call_key"])
    return {**base, "admission": {"admitted": True, "error": None, "reason_code": None, "message": None,
                                  "detail": None},
            "selection_sha256": plan["selected"]["selection_sha256"], "conditions_sha256": plan["conditions_sha256"],
            "space": dict(plan["space"]), "projection_heavy_atoms": plan["projection_heavy_atoms"],
            "heavy_atom_warning": plan["heavy_atom_warning"], "reusable_count": plan["reusable_count"],
            "reference_reusable": plan["reference_reusable"],
            **{key: figures[key] for key in ("reserved_evaluations", "reserved_units", "needed", "remaining",
                                             "shortfall", "full_run_may_be_partial")},
            "ga": ga, "statements": statements(PREFLIGHT_STATEMENTS),
            "existing_job": None if job is None else {"job_id": job["job_id"], "status": job["status"],
                                                      "summary_handle": job.get("sequence_ga_summary_handle")}}


# ----------------------------------------------------------------- summaries (one event-log read per call)
def _published(view: Any) -> dict[str, dict[str, Any]]:
    """First ``sequence_ga_published`` event per summary handle, in publication order."""
    found: dict[str, dict[str, Any]] = {}
    for event in view.events.read():
        if event["type"] == PUBLISHED_EVENT and event.get("summary_handle") not in found:
            found[event["summary_handle"]] = event
    return found


def list_summaries(run: Any, offset: int, limit: int) -> dict[str, Any]:
    view = SJ.snapshot(run)
    published = _published(view)
    newest = list(reversed(published))
    rows = []
    for handle in newest[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "published_seq": published[handle]["seq"]}
        try:
            content = SJ.validated_summary(view, handle)
            source = SJ.summary_producer(view, handle)
            row.update(valid=True, reason_code=None, job_id=source["job_id"], attempt_id=source["attempt_id"],
                       **{key: content[key] for key in LIST_FIELDS[2:]})
        except SequenceGaEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", **dict.fromkeys(LIST_FIELDS))
        rows.append(row)
    return {"schema": "sequence_ga_list@1", "total": len(published), "offset": offset, "limit": limit, "rows": rows}


def _with_link(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry, "detail_available": entry["result_handle"] is not None}


def summary_detail(run: Any, handle: str) -> dict[str, Any]:
    view = SJ.snapshot(run)
    content = SJ.validated_summary(view, handle)
    source = SJ.summary_producer(view, handle)
    return {"schema": "sequence_ga_detail@1", "handle": handle, "job_id": source["job_id"],
            "attempt_id": source["attempt_id"], "published_seq": source["published_seq"],
            "score_label": SC.SCORE_LABEL, "score_column_label": C.SCORE_COLUMN_LABEL,
            "score_row_label": SC.SCORE_ROW_LABEL, "statements": statements(content["limitations"]),
            "summary": content,
            "generations": [{**{key: gen[key] for key in ("index", "complete", "min_score", "max_score")},
                             "individuals": [_with_link(entry) for entry in gen["individuals"]]}
                            for gen in content["generations"]],
            "reference": _with_link(content["reference"])}


# ----------------------------------------------------------------- one row by key
def _key(value: Any) -> str:
    """``wild_type`` or an individual key (``12-57-203``: ascending decimal candidate indices, 1-4 of them)."""
    if type(value) is not str:
        raise ReadInvalid("key is required")
    if value != SC.REFERENCE_KEY:
        try:
            GI.parse_key(value)
        except ValueError as exc:
            raise ReadInvalid("key must be wild_type or ascending candidate indices joined by '-'") from exc
    return value


def _row(view: Any, handle: str, key: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """(validated summary, the row of ``key``, its validated model or None). Keys only, never names."""
    content = SJ.validated_summary(view, handle)
    if key == SC.REFERENCE_KEY:
        row = content["reference"]
    else:
        found = [entry for gen in content["generations"] for entry in gen["individuals"]
                 if entry["key"] == key and entry["origin"] != "carried"]
        if len(found) != 1:
            raise RowUnknown("key is not an individual of this GA")
        row = found[0]
    reference = content["reference"]["model_handle"]
    reference_model = None if reference is None else SJ.validated_set_model(view, reference)
    model = None
    if row["model_handle"] is not None:
        model = SJ.validated_set_model(view, row["model_handle"], reference_model)
    return content, row, model


def _model_view(model: dict[str, Any]) -> dict[str, Any]:
    """The stored model without its atom and bond rows (``final_bonds``, ``atom_mapping``)."""
    return {**{key: value for key, value in model.items() if key != "structures"},
            "structures": {side: {key: value for key, value in entry.items() if key not in MODEL_ROWS}
                           for side, entry in model["structures"].items()}}


def individual(run: Any, handle: str, key: Any) -> dict[str, Any]:
    """One individual or the wild-type reference row of a validated summary, found by key only."""
    key = _key(key)
    view = SJ.snapshot(run)
    content, row, model = _row(view, handle, key)
    reference = key == SC.REFERENCE_KEY
    appearances = [] if reference else [
        {"generation": gen["index"], "position": position, "origin": entry["origin"]}
        for gen in content["generations"] for position, entry in enumerate(gen["individuals"]) if entry["key"] == key]
    result = row["result_handle"]
    return {"schema": "sequence_ga_individual@1", "summary_handle": handle, "key": key,
            "mutations": [] if reference else row["mutations"], "is_reference": reference,
            "eval_index": None if reference else row["eval_index"],
            "pick_index": None if reference else row["pick_index"],
            **{field: row[field] for field in ROW_FIELDS}, "appearances": appearances, "model": None if model is None else _model_view(model),
            "statements": statements(MODEL_STATEMENTS), "score_label": SC.SCORE_LABEL,
            "score_row_label": SC.SCORE_ROW_LABEL,
            "m18_detail": None if result is None else docking_reads.result_detail(view, result)}


def structure_download(run: Any, handle: str, key: Any) -> tuple[bytes, str]:
    """``(stored mmCIF bytes, filename)`` of one row's model; the bytes match the model's recorded SHA-256 and
    structure handle."""
    key = _key(key)
    view = SJ.snapshot(run)
    _content, _entry, model = _row(view, handle, key)
    if model is None:
        raise RowUnknown("this row has no stored model structure")
    (entry,) = model["structures"].values()
    raw = SJ._stored_cif(view, entry)
    if SM.structure_handle(view.run_id, raw) != entry["structure_object"]:
        raise SequenceGaEvidenceError("stored mmCIF handle")
    return raw, f"protview-sequence-ga-{handle.rsplit('/', 1)[-1][:12]}-{key}.cif"
