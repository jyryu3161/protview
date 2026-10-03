"""M19 batch docking admission, per-row M18 arguments, batch input hash, preflight and limit-raise arithmetic
(spec .dryforge/spec.md 3, 4.1, 4.5, 5.2, 5.3, 6.1-6.3, 12).

No RDKit, no Meeko, no events. Every row is an M18 ``qvina_dock_v1`` input: the shared fields go through
``docking_inputs.validate_arguments`` and each row's store checks through ``docking_bundle.submission`` unchanged,
so a row's selection, ``input_sha256`` and call key are exactly those of a standalone M18 request.

Argument shape (fixed, unknown keys ``invalid_job_arguments``): the M18 receptor, box, parameter and acknowledgement
fields with their M18 names and rules, plus ``candidate_set_handle``, ``parent_sdf_handle``, ``candidate_ids``
(1-50 distinct non-empty strings) and ``include_parent`` (bool, default false). There is no ``ligand`` key: the batch
builds each row's ligand (candidate rows ``candidate`` source, the parent row ``sdf`` source on ``parent_sdf_handle``).
Check order: keys, ``candidate_ids`` shape, ``batch_empty``, ``batch_too_large``, duplicates, ``include_parent``,
mode, ``batch_parent_not_allowed``, then the M18 order on the shared fields.

Budget figures use the run budget snapshot shape ``{axis: {"used", "limit"}}`` for ``expensive_calls`` and
``wall_clock_s``; remaining = limit - used (never clamped), shortfall = max(0, needed - remaining).
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from . import docking_batch_constants as BC
from . import docking_bundle, docking_inputs
from . import docking_constants as C
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json

TOP_KEYS = frozenset({"receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                      "candidate_set_handle", "parent_sdf_handle", "candidate_ids", "include_parent", "mode", "box",
                      "parameters", "acknowledgement"})
OPTIONAL_KEYS = frozenset({"include_parent", "acknowledgement"})
SHARED_KEYS = ("receptor_handle", "receptor_model_number", "connectivity", "receptor_instance", "mode", "box",
               "parameters", "acknowledgement")
AXES = ("expensive_calls", "wall_clock_s")


def _fail(reason: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason, **detail})


# ---------------------------------------------------------------- job arguments (pure)
def validate_arguments(args: Any) -> dict[str, Any]:
    """Validate ``qvina_batch_dock_v1`` arguments (shape and values only); ``candidate_ids`` keep request order."""
    if type(args) is not dict:
        raise _fail("invalid_job_arguments", "job arguments must be an object")
    if not set(args) <= TOP_KEYS or not TOP_KEYS - OPTIONAL_KEYS <= set(args):
        raise _fail("invalid_job_arguments", "job arguments have unknown or missing keys")
    ids = args["candidate_ids"]
    if type(ids) is not list or any(type(item) is not str or not item for item in ids):
        raise _fail("invalid_job_arguments", "candidate_ids must be a list of non-empty strings")
    if not ids:
        raise _fail("batch_empty", "a batch needs at least one candidate")
    if len(ids) > BC.MAX_CANDIDATES:
        raise _fail("batch_too_large", f"a batch takes at most {BC.MAX_CANDIDATES} candidates")
    if len(set(ids)) != len(ids):
        raise _fail("invalid_job_arguments", "candidate_ids has duplicates")
    include_parent = args.get("include_parent", False)
    if type(include_parent) is not bool:
        raise _fail("invalid_job_arguments", "include_parent must be true or false")
    if args["mode"] not in C.MODES:
        raise _fail("invalid_job_arguments", "mode must be free or core_fixed")
    if include_parent and args["mode"] == "core_fixed":
        raise _fail("batch_parent_not_allowed", "the parent row exists only in free mode (no core to fix)")
    template = {key: args[key] for key in SHARED_KEYS if key in args}
    template["ligand"] = {"source": "candidate", "candidate_set_handle": args["candidate_set_handle"],
                          "candidate_id": ids[0], "parent_sdf_handle": args["parent_sdf_handle"]}
    row = docking_inputs.validate_arguments(template)
    return {**{key: row[key] for key in SHARED_KEYS},
            "candidate_set_handle": row["ligand"]["candidate_set_handle"],
            "parent_sdf_handle": row["ligand"]["parent_sdf_handle"], "candidate_ids": list(ids),
            "include_parent": include_parent}


def row_request(normalized: dict[str, Any], kind: str, candidate_id: str | None) -> dict[str, Any]:
    """One row as a standalone M18 ``qvina_dock_v1`` request (``conformers`` omitted in free mode, as M18 requires)."""
    if kind == "parent" and candidate_id is None:
        ligand = {"source": "sdf", "sdf_handle": normalized["parent_sdf_handle"]}
    elif kind == "candidate" and type(candidate_id) is str:
        ligand = {"source": "candidate", "candidate_set_handle": normalized["candidate_set_handle"],
                  "candidate_id": candidate_id, "parent_sdf_handle": normalized["parent_sdf_handle"]}
    else:
        raise ValueError("unknown row kind")
    parameters = {key: value for key, value in normalized["parameters"].items()
                  if key != "conformers" or value is not None}
    return {**{key: normalized[key] for key in SHARED_KEYS}, "parameters": parameters, "ligand": ligand}


def row_arguments(normalized: dict[str, Any], kind: str, candidate_id: str | None) -> dict[str, Any]:
    """The M18-normalized arguments of one row (equal to a standalone request's ``selected["arguments"]``)."""
    return docking_inputs.validate_arguments(row_request(normalized, kind, candidate_id))


def planned_rows(selected_ids: list[str], set_ids: list[str], include_parent: bool) -> list[dict[str, Any]]:
    """Rows in batch order: the parent row first (if any), then the selected ids in candidate-set order."""
    known = set(set_ids)
    unknown = [item for item in selected_ids if item not in known]
    if unknown:
        raise _fail("candidate_unknown", "candidate_id is not in the candidate set")
    chosen = set(selected_ids)
    kinds = [("parent", None)] * include_parent + [("candidate", item) for item in set_ids if item in chosen]
    return [{"row_index": index, "kind": kind, "candidate_id": cid} for index, (kind, cid) in enumerate(kinds)]


# ---------------------------------------------------------------- selection and batch input hash
def _parent_entry(row_selected: dict[str, Any]) -> dict[str, str]:
    ligand = row_selected["ligand"]
    return ligand["sdf"] if ligand["source"] == "sdf" else ligand["parent_sdf"]


def batch_selection(normalized: dict[str, Any], row_selections: list[dict[str, Any]]) -> dict[str, Any]:
    """The batch job's selection from its normalized arguments (``candidate_ids`` in set order) and the M18
    ``docking_selection@1`` of every row, in row order. Rows that disagree on shared inputs raise ValueError."""
    plan = planned_rows(normalized["candidate_ids"], normalized["candidate_ids"], normalized["include_parent"])
    if len(plan) != len(row_selections):
        raise ValueError("one row selection per planned row")
    first = row_selections[0]
    candidate = next(sel for sel in row_selections if sel["ligand"]["source"] == "candidate")
    for row, sel in zip(plan, row_selections, strict=True):
        if (sel["arguments"] != row_arguments(normalized, row["kind"], row["candidate_id"]) or
                sel["receptor"] != first["receptor"] or sel["sidecar"] != first["sidecar"] or
                _parent_entry(sel) != _parent_entry(first)):
            raise ValueError("row selection differs from the batch inputs")
    selected = {"schema": BC.SELECTION_SCHEMA, "arguments": normalized,
                "receptor": first["receptor"], "sidecar": first["sidecar"],
                "candidate_set": {"handle": normalized["candidate_set_handle"],
                                  "parent_sha256": candidate["ligand"]["candidate_set_parent_sha256"]},
                "parent_sdf": _parent_entry(first),
                "rows": [{**row, "selected": sel} for row, sel in zip(plan, row_selections, strict=True)]}
    selected["batch_input_sha256"] = batch_input_sha256(selected)
    return selected


def batch_input(selected: dict[str, Any]) -> dict[str, Any]:
    """Spec 5.2: what defines the batch (no acknowledgement, timeout, reuse, time or job identity)."""
    args = selected["arguments"]
    sidecar = selected["sidecar"]
    return {"receptor": {"handle": selected["receptor"]["handle"], "sha256": selected["receptor"]["sha256"],
                         "model_number": args["receptor_model_number"],
                         "connectivity": {"kind": args["connectivity"]["kind"],
                                          "sidecar_handle": None if sidecar is None else sidecar["handle"],
                                          "sidecar_sha256": None if sidecar is None else sidecar["sha256"]},
                         "instance": args["receptor_instance"]},
            "candidate_set_handle": args["candidate_set_handle"],
            "parent_sdf": {"handle": selected["parent_sdf"]["handle"], "sha256": selected["parent_sdf"]["sha256"]},
            "candidate_ids": args["candidate_ids"], "include_parent": args["include_parent"], "mode": args["mode"],
            "box": args["box"], "parameters": args["parameters"]}


def batch_input_sha256(selected: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(batch_input(selected))).hexdigest()


def submission(run: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """(selected, normalized arguments with set-ordered ids, input handles); refusals as in M18, before any job."""
    from .ligand_bundle import LigandEvidenceError, validated_candidate_set

    normalized = validate_arguments(args)
    try:
        candidate_set, _inspection = validated_candidate_set(run, normalized["candidate_set_handle"])
    except LigandEvidenceError as exc:
        raise _fail("invalid_job_arguments",
                    "candidate_set_handle is not a completed same-run ligand candidate set") from exc
    plan = planned_rows(normalized["candidate_ids"], [row["id"] for row in candidate_set["candidates"]],
                        normalized["include_parent"])
    normalized = {**normalized, "candidate_ids": [row["candidate_id"] for row in plan if row["kind"] == "candidate"]}
    rows = [docking_bundle.submission(run, row_request(normalized, row["kind"], row["candidate_id"]))
            for row in plan]
    selected = batch_selection(normalized, [row[0] for row in rows])
    return selected, normalized, rows[-1][2]   # the last row is a candidate: receptor, sidecar?, set, parent


def row_call_keys(selected: dict[str, Any], pins: dict[str, Any]) -> list[str]:
    """The M18 call key of every row (reuse detection, spec 4.5 and 7.3: the full key, pins included)."""
    return [docking_bundle.call_key(row["selected"]["arguments"], pins) for row in selected["rows"]]


def published_m18_results(events: Iterable[dict[str, Any]]) -> dict[str, str]:
    """call key -> handle of every completed standalone ``qvina_dock_v1`` job and every row a batch published (its
    M18 call key under the batch job's M18 pins). The caller still validates the handle with
    ``docking_bundle.validated_result`` before reusing it."""
    events = list(events)
    keys = {event["job"]["job_id"]: event["job"]["call_key"] for event in events
            if event["type"] == "job_submitted" and event["job"].get("protocol_id") == C.PROTOCOL}
    found = {keys[event["job_id"]]: event["output_handles"][0] for event in events
             if event["type"] == "job_terminal" and event.get("status") == "done" and event.get("job_id") in keys
             and type(event.get("output_handles")) is list and len(event["output_handles"]) == 1}
    batches = {event["job"]["job_id"]: event["job"] for event in events
               if event["type"] == "job_submitted" and event["job"].get("protocol_id") == BC.PROTOCOL}
    for event in events:
        job = batches.get(event.get("job_id")) if event["type"] == "docking_batch_row_published" else None
        if job is not None:
            key = docking_bundle.call_key(job["selected"]["rows"][event["row_index"]]["selected"]["arguments"],
                                          job["method"])
            found.setdefault(key, event["handle"])
    return found


# ---------------------------------------------------------------- budget arithmetic (spec 6.1-6.3)
def needed_budget(new_dockings: int) -> dict[str, int]:
    if type(new_dockings) is not int or not 0 <= new_dockings <= BC.MAX_CANDIDATES + 1:
        raise ValueError("new_dockings must be an integer 0-51")
    wall = (BC.EMPTY_BATCH_WALL_S if new_dockings == 0 else
            min(BC.TIMEOUT_MAX_S, new_dockings * BC.PER_CANDIDATE_S + BC.FINISH_MARGIN_S))
    return {"expensive_calls": new_dockings, "wall_clock_s": wall}


def remaining(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {axis: snapshot[axis]["limit"] - snapshot[axis]["used"] for axis in AXES}


def shortfall(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    left = remaining(snapshot)
    return {axis: max(0, needed[axis] - left[axis]) for axis in AXES}


def full_batch_may_be_partial(new_dockings: int) -> bool:
    return new_dockings * BC.PER_CANDIDATE_S > BC.TOTAL_S


def limit_increase(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """How much one approval raises each limit for this batch (spec 6.3, 12); zero when nothing is short (idempotent).

    calls = min(shortfall, need); wall = 0 if the wall shortfall is 0, else min(shortfall, need) + RAISE_MARGIN_S.
    Clamping the shortfall at the need is clamping a negative remaining (usage above the limit) at zero, so an
    approval never raises an axis by more than this batch's need (<= 51 units) plus the wall margin (<= 7860 s). The
    margin is kept even when the need is capped at 7800 s, so the runtime overhead charged right after the raise
    cannot make the batch short again; it also absorbs a wall overrun of up to 60 s (a larger overrun stays short
    until another explicit approval)."""
    short = shortfall(needed, snapshot)
    calls = min(short["expensive_calls"], needed["expensive_calls"], BC.MAX_RAISE_EXPENSIVE_CALLS)
    wall = min(short["wall_clock_s"], needed["wall_clock_s"], BC.MAX_RAISE_WALL_CLOCK_S)
    return {"expensive_calls": calls, "wall_clock_s": wall + BC.RAISE_MARGIN_S if wall > 0 else 0}


def require_budget(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Admission: a short budget refuses the batch (429 ``batch_limit_raise_required``, nothing charged)."""
    short = shortfall(needed, snapshot)
    if any(value > 0 for value in short.values()):
        raise ToolFailure(FailureClass.resource_exceeded, "the run budget is short for this batch; raise the limits "
                          "first", detail={"reason_code": "batch_limit_raise_required", "needed": dict(needed),
                                           "shortfall": short})


def preflight(selected: dict[str, Any], pins: dict[str, Any], existing: Mapping[str, str],
              snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Rows with reuse (``existing``: M18 call key -> stored result handle), N, need, remaining, shortfall."""
    rows = []
    for row, key in zip(selected["rows"], row_call_keys(selected, pins), strict=True):
        handle = existing.get(key)
        rows.append({"row_index": row["row_index"], "kind": row["kind"], "candidate_id": row["candidate_id"],
                     "reuse": handle is not None, "reused_handle": handle})
    new = sum(not row["reuse"] for row in rows)
    needed = needed_budget(new)
    return {"batch_input_sha256": selected["batch_input_sha256"], "rows": rows, "new_dockings": new,
            "needed": needed, "remaining": remaining(snapshot), "shortfall": shortfall(needed, snapshot),
            "full_batch_may_be_partial": full_batch_may_be_partial(new)}
