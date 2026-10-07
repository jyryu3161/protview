"""M21 read-only projections of ``mutation_model@1`` objects (spec .dryforge/spec.md 6). No tool, no job, no event.

* ``list_models()``: this run's models, newest first; each page row is re-validated and a row that does not validate
  shows ``valid: false`` with null fields (never stale numbers), as the M20 list does.
* ``model_detail()``: one validated model without the contact rows, ``final_bonds`` and ``atom_mapping`` (each side
  keeps its contact ``cutoff_A``, ``excluded_bond_distance``, ``count`` and ``residue_count``).
* ``contact_page()``: one side's stored contact rows in stored order, by page (1-based) and page size.
* ``structure_download()``: one side's stored mmCIF bytes, hash-checked against the model.

Every read goes through ``mutation_model_bundle.validated_result`` / ``structure_bytes`` (single completed
publication, job selection, stored mmCIF bytes, pure ``validated_model``); any failure raises
``MutationEvidenceError``. Nothing is recomputed: values are the stored engine values. The caller checks the handle's
run, kind and schema first.

* ``docking_pairs()`` (spec 7, same-condition docking): this run's single M18 jobs whose ``receptor_source`` is this
  model, grouped by condition, every group listed (never one picked). See its docstring for the key and the rules.
  M25 (spec .dryforge/spec.md 10): a group whose mutant job a JEV loop docking step approved carries ``loop``.
"""
from __future__ import annotations

import hashlib
from typing import Any

from . import docking_bundle, docking_inputs
from . import docking_constants as DC
from . import jev_loop_constants as LOOP
from . import mutation_model_bundle as bundle
from .core.handles import canonical_json
from .jobs.queue import JobQueue
from .mutation_model_bundle import MutationEvidenceError
from .mutation_model_constants import KIND, SCHEMA, STRUCTURE_SIDES

__all__ = ["PAIR_REASONS", "MutationEvidenceError", "ReadInvalid", "contact_page", "docking_pairs", "list_models",
           "model_detail", "structure_download", "structure_summary"]

LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
CONTACT_PAGE_SIZE_DEFAULT, CONTACT_PAGE_SIZE_MAX = 100, 200
_STRUCTURE_ROW_FIELDS = ("final_bonds", "atom_mapping", "contacts")
_LIST_FIELDS = ("candidate", "structure", "parameters")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


def _side(value: Any, name: str) -> str:
    if value not in STRUCTURE_SIDES:
        raise ReadInvalid(f"{name} must be one of {list(STRUCTURE_SIDES)}")
    return value


def structure_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """One structure entry without its rows: no ``final_bonds``, ``atom_mapping`` or contact rows."""
    contacts = entry["contacts"]
    return {**{key: value for key, value in entry.items() if key not in _STRUCTURE_ROW_FIELDS},
            "contacts": {key: contacts[key] for key in ("cutoff_A", "excluded_bond_distance", "count",
                                                        "residue_count")}}


def _created(run: Any) -> dict[str, int]:
    """Creating event sequence number of each ``mutation_model`` handle, in creation order."""
    found: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == KIND and event["handle"] not in found:
            found[event["handle"]] = event["seq"]
    return found


def list_models(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run)
    newest = list(reversed(created))
    rows = []
    for handle in newest[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]}
        try:
            if run.store.meta(handle)["schema"] != SCHEMA:
                raise MutationEvidenceError("unexpected schema")
            content = bundle.validated_result(run, handle)
            candidate = content["candidate"]
            row.update(valid=True,
                       candidate={key: candidate[key] for key in ("candidate_set", "candidate_index", "residue",
                                                                  "from", "to", "mutant_resname")},
                       structure=content["structure"], parameters=content["parameters"])
        except MutationEvidenceError:
            row.update(valid=False, **dict.fromkeys(_LIST_FIELDS))
        rows.append(row)
    return {"schema": "mutation_model_list@1", "total": len(created), "offset": offset, "limit": limit, "rows": rows}


def model_detail(run: Any, handle: str) -> dict[str, Any]:
    content = bundle.validated_result(run, handle)
    result = {key: value for key, value in content.items() if key != "structures"}
    result["structures"] = {side: structure_summary(content["structures"][side]) for side in STRUCTURE_SIDES}
    return {"schema": "mutation_model_detail@1", "handle": handle, "result": result}


def contact_page(run: Any, handle: str, *, structure: Any, page: int, page_size: int) -> dict[str, Any]:
    side = _side(structure, "structure")
    content = bundle.validated_result(run, handle)
    contacts = content["structures"][side]["contacts"]
    start = (page - 1) * page_size
    rows = [{"index": index, **row} for index, row in enumerate(contacts["rows"])][start:start + page_size]
    return {"schema": "mutation_model_contact_page@1", "handle": handle, "structure": side,
            "mutated_residue": content["structures"][side]["sasa"]["residue"], "cutoff_A": contacts["cutoff_A"],
            "excluded_bond_distance": contacts["excluded_bond_distance"], "total": contacts["count"],
            "page": page, "page_size": page_size, "rows": rows}


def structure_download(run: Any, handle: str, side: Any) -> tuple[bytes, str]:
    """``(stored mmCIF bytes, filename)`` of one side; the bytes match the model's recorded SHA-256."""
    side = _side(side, "side")
    raw = bundle.structure_bytes(run, handle, side)
    return raw, f"protview-mutation-model-{handle.rsplit('/', 1)[-1][:12]}-{side}.cif"


# ----------------------------------------------------------------- same-condition docking pairs (spec 7)
# Closed reason set of a side that shows no score (the score is then null, never 0). Fixed sentences, Korean.
PAIR_REASONS = {
    "not_submitted": "이 조건으로 이 구조의 도킹 작업이 제출되지 않았다.",
    "job_not_finished": "도킹 작업이 아직 끝나지 않았다.",
    "job_failed": "도킹 작업이 실패해 결과가 없다.",
    "job_cancelled": "도킹 작업이 취소되어 결과가 없다.",
    "job_interrupted": "도킹 작업이 중단되어 결과가 없다.",
    "result_invalid": "게시된 도킹 결과가 검증을 통과하지 못했다.",
    "other_side_missing": "다른 구조의 도킹 결과가 게시되지 않아 이 결과를 나란히 보이지 않는다.",
    "no_modes": "qvina가 자세를 내지 않은 빈 결과다.",
}
_STATUS_REASON = {"queued": "job_not_finished", "claimed": "job_not_finished", "running": "job_not_finished",
                  "failed": "job_failed", "cancelled": "job_cancelled", "interrupted": "job_interrupted"}
_CONDITION_KEYS = ("ligand", "mode", "box", "parameters")


def _condition(job: dict[str, Any]) -> dict[str, Any]:
    """The docking condition of one M18 job: its normalized ``ligand``, ``mode``, requested ``box`` and every
    ``parameters`` value (seed included), plus the SHA-256 of its pinned M18 environment (``job.method``)."""
    arguments = job["parameters"]
    return {**{key: arguments[key] for key in _CONDITION_KEYS},
            "method_pins_sha256": hashlib.sha256(canonical_json(job["method"])).hexdigest()}


def _published(run: Any, job: dict[str, Any], handle: str, side: str) -> dict[str, Any] | None:
    """The validated M18 result of a done job (or None): re-validated by ``docking_bundle.validated_result``, its
    receptor source is this model and side, and its ``input_sha256`` is the one of this job's arguments."""
    if job["status"] != "done" or len(job["output_handles"]) != 1:
        return None
    try:
        content = docking_bundle.validated_result(run, job["output_handles"][0])
    except docking_bundle.DockingEvidenceError:
        return None
    if (content["inputs"]["receptor"].get("source") != {"kind": "mutation_model", "mutation_model": handle,
                                                        "side": side} or
            content["input_sha256"] != docking_inputs.input_sha256(job["parameters"])):
        return None
    return content


def _side_entry(side: str, job: dict[str, Any] | None, seq: int | None) -> dict[str, Any]:
    return {"side": side, "job_id": None if job is None else job["job_id"],
            "job_status": "not_submitted" if job is None else job["status"], "submitted_seq": seq,
            "result_handle": None, "score_kcal_mol": None, "score_mode": None}


def _loop_docking(events: list[dict[str, Any]], job: dict[str, Any] | None,
                  submitted_seq: int | None) -> dict[str, Any] | None:
    """M25: ``{loop_id, iteration}`` when ``job`` is the job of a JEV loop docking step of this run: the latest
    ``jev_loop_compute_approved`` with ``step: "dock"`` and this job's call key before the job was submitted (the loop
    compute route writes its approval, then submits; a same-key job submitted before an approval is not the loop's)."""
    if job is None:
        return None
    found = None
    for event in events:
        if event["seq"] >= submitted_seq:
            break
        if (event["type"] == LOOP.EVENT_COMPUTE_APPROVED and event["step"] == "dock"
                and event["call_key"] == job["call_key"]):
            found = {"loop_id": event["loop_id"], "iteration": event["iteration"]}
    return found


def docking_pairs(run: Any, handle: str) -> dict[str, Any]:
    """Spec 7 ``docking_pairs``: same-condition M18 docking on the two structures of one model.

    Members: this run's ``qvina_dock_v1`` jobs whose ``parameters.receptor_source.mutation_model`` is ``handle``
    (M19 never takes this source). Group key: ``_condition`` (ligand, mode, box, parameters, pinned environment);
    a published result of a member is checked to carry these same values (its ``input_sha256`` equals the job's).
    One call key per side and condition means at most one job per side in a group (two would raise, never pick).
    A side shows its result handle and the stored first mode row score (``modes[0].score_kcal_mol``, unchanged)
    only when BOTH sides are published, validated results; otherwise every side shows its job status, null score
    and a ``PAIR_REASONS`` code. Groups are ordered by the earliest submission event of their jobs. Nothing is
    subtracted, ranked or chosen. M25: a group whose mutant job is a JEV loop docking step's (``_loop_docking``) also
    has ``loop: {loop_id, iteration}`` (no new reason; every other group is unchanged, without the key)."""
    bundle.validated_result(run, handle)
    jobs = [job for job in JobQueue(run).list()
            if job["protocol_id"] == DC.PROTOCOL and job["tool_id"] == DC.TOOL and
            type(job["parameters"]) is dict and type(job["parameters"].get("receptor_source")) is dict and
            job["parameters"]["receptor_source"].get("mutation_model") == handle]
    events = list(run.events.read())
    submitted = {event["job"]["job_id"]: event["seq"] for event in events if event["type"] == "job_submitted"}
    groups: dict[bytes, dict[str, Any]] = {}
    for job in sorted(jobs, key=lambda item: submitted[item["job_id"]]):
        side = job["parameters"]["receptor_source"]["side"]
        if side not in STRUCTURE_SIDES:
            raise ValueError("docking job with an unknown receptor side")
        condition = _condition(job)
        group = groups.setdefault(canonical_json(condition), {"condition": condition, "jobs": {}})
        if side in group["jobs"]:
            raise ValueError("two docking jobs for one side and one condition")
        group["jobs"][side] = job
    pairs = []
    for index, group in enumerate(groups.values()):
        found = {side: group["jobs"].get(side) for side in STRUCTURE_SIDES}
        results = {side: None if job is None else _published(run, job, handle, side) for side, job in found.items()}
        both = all(content is not None for content in results.values())
        sides = {}
        for side, job in found.items():
            entry = _side_entry(side, job, None if job is None else submitted[job["job_id"]])
            content = results[side]
            if both and content["modes"]:
                entry.update(result_handle=job["output_handles"][0], score_mode=content["modes"][0]["mode"],
                             score_kcal_mol=content["modes"][0]["score_kcal_mol"], reason_code=None)
            elif both:
                entry.update(result_handle=job["output_handles"][0], reason_code="no_modes")
            else:
                entry["reason_code"] = ("not_submitted" if job is None else
                                        "other_side_missing" if content is not None else
                                        "result_invalid" if job["status"] == "done" else _STATUS_REASON[job["status"]])
            entry["reason"] = None if entry["reason_code"] is None else PAIR_REASONS[entry["reason_code"]]
            sides[side] = entry
        pair = {"index": index,
                "first_submitted_seq": min(submitted[job["job_id"]] for job in group["jobs"].values()),
                "condition": group["condition"], "both_published": both, "sides": sides}
        mutant = found["mutant"]
        loop = _loop_docking(events, mutant, None if mutant is None else submitted[mutant["job_id"]])
        if loop is not None:
            pair["loop"] = loop
        pairs.append(pair)
    return {"schema": "mutation_model_docking_pairs@1", "handle": handle, "score_label": DC.SCORE_LABEL,
            "total": len(pairs), "pairs": pairs, "starts_job": False}
