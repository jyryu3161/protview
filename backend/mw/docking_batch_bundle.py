"""M19 batch summary ``docking_batch_result@1``: rows from staging observations, status rules, validation, call key
(spec .dryforge/spec.md 4.3, 4.4, 5.2-5.4, 7.2, 12).

Pure server functions: no RDKit, no Meeko, no store writes, no events. The caller reads the staging files
(``rows/<n>.started``, ``rows/<n>.status.json``, ``rows/<n>.result.json``), publishes every verifiable per-row result
with the M18 checks, and passes here, per planned row, one observation
``{"started": bool, "status": {"state", "reason_code"} | None, "result_handle": str | None}``
(``result_handle`` = the published or reused ``docking_result@1``), the validated per-row results by handle, the
job's stop cause (``None`` when the job ran every row, else a ``STOP_REASONS`` value), the batch box the worker
computed once and the engine record.

Row rules (spec 7.2): a result handle makes the row ``scored`` (modes >= 1) or ``null_result``; else a status file
gives the state (a ``scored``/``null_result`` status whose result could not be published is ``failed``
``engine_output_invalid``, the M18 reason for an output the server refuses); else a started row was in progress
(``cancelled`` under a cancel or time stop, ``not_run`` under the output limit, else ``failed`` ``worker_failed``);
else ``not_run``. The stop cause used for in-progress and unstarted rows is the first stop the worker recorded in a
status file, else the job's stop cause; the batch ``stop_reason`` is the reason of the first ``cancelled``/``not_run``
row. Reused rows are filled from their stored result whatever the stop (they are not computed by the job).

Every summary is checked against its batch selection and the per-row results when built and on every read
(``check_summary``): rows, states, reasons, handles, the score copy (``modes[0].score_kcal_mol``), per-row inputs
(``input_sha256``, candidate id, mode, box, values, engine), counts, status, limitations and size.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import docking_batch_constants as BC
from . import docking_batch_inputs, docking_inputs
from . import docking_constants as C
from .core.handles import canonical_json
from .docking_bundle import PINNED_VERSIONS

SUMMARY_KEYS = frozenset({"schema", "protocol", "method", "batch_input_sha256", "inputs", "box", "parameters",
                          "engine", "preparation", "limits", "status", "stop_reason", "rows", "counts",
                          "limitations"})
ROW_KEYS = frozenset({"row_index", "kind", "candidate_id", "state", "reason_code", "result_handle",
                      "score_kcal_mol", "score_row_label"})
OBSERVATION_KEYS = frozenset({"started", "status", "result_handle"})
STATUS_KEYS = frozenset({"state", "reason_code"})
REASONS_BY_STATE = {"scored": (None,), "null_result": (None,), "failed": C.REASONS + BC.FAILED_EXTRA_REASONS,
                    "cancelled": BC.CANCELLED_REASONS, "not_run": BC.NOT_RUN_REASONS}
STOPPED = ("cancelled", "not_run")
PREPARATION = {"tool": "Meeko", "version": PINNED_VERSIONS["meeko"], "rdkit_version": PINNED_VERSIONS["rdkit"],
               "atom_typing": "ad4", "charges": "gasteiger"}
SHA_RE = re.compile(r"[0-9a-f]{64}")


class DockingBatchEvidenceError(ValueError):
    """A batch summary or its observations do not validate against the batch selection and per-row results."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise DockingBatchEvidenceError(message)


# ----------------------------------------------------------------- rows
def _check_status(status: Any) -> None:
    _require(type(status) is dict and set(status) == STATUS_KEYS and status["state"] in BC.ROW_STATES and
             status["reason_code"] in REASONS_BY_STATE[status["state"]], "row status file")


def _result_state(result: dict[str, Any]) -> str:
    return "scored" if len(result["modes"]) >= 1 else "null_result"


def _score(result: dict[str, Any] | None, state: str, mode: str) -> tuple[Any, Any]:
    if state != "scored":
        return None, None
    return result["modes"][0]["score_kcal_mol"], BC.SCORE_ROW_LABELS[mode]


def derive_rows(selected: dict[str, Any], observations: list[dict[str, Any]], results: Mapping[str, Any],
                stop_cause: str | None) -> list[dict[str, Any]]:
    """Summary rows (spec 4.3, 7.2) from one observation per planned row and the job's stop cause."""
    plan = selected["rows"]
    _require(stop_cause is None or stop_cause in BC.STOP_REASONS, "stop cause")
    _require(type(observations) is list and len(observations) == len(plan), "one observation per row")
    for obs in observations:
        _require(type(obs) is dict and set(obs) == OBSERVATION_KEYS and type(obs["started"]) is bool and
                 (obs["result_handle"] is None or type(obs["result_handle"]) is str), "row observation")
        if obs["status"] is not None:
            _check_status(obs["status"])
    recorded = next((obs["status"]["reason_code"] for obs in observations
                     if obs["status"] is not None and obs["status"]["state"] in STOPPED), None)
    cause = recorded or stop_cause
    mode = selected["arguments"]["mode"]
    rows = []
    for planned, obs in zip(plan, observations, strict=True):
        handle, status = obs["result_handle"], obs["status"]
        if handle is not None:
            _require(handle in results, "result of the row")
            state, reason = _result_state(results[handle]), None
            _require(status is None or status == {"state": state, "reason_code": None}, "status agrees with result")
        elif status is not None:
            state, reason = status["state"], status["reason_code"]
            if state in ("scored", "null_result"):
                state, reason = "failed", "engine_output_invalid"
        else:
            _require(cause is not None, "a row did not finish but the job has no stop cause")
            if not obs["started"]:
                state, reason = "not_run", cause
            elif cause in BC.CANCELLED_REASONS:
                state, reason = "cancelled", cause
            elif cause == "resource_exceeded":
                state, reason = "not_run", cause
            else:
                state, reason = "failed", "worker_failed"
        score, label = _score(results.get(handle) if handle else None, state, mode)
        rows.append({"row_index": planned["row_index"], "kind": planned["kind"],
                     "candidate_id": planned["candidate_id"], "state": state, "reason_code": reason,
                     "result_handle": handle, "score_kcal_mol": score, "score_row_label": label})
    return rows


# ----------------------------------------------------------------- summary
def _limitations(selected: dict[str, Any], rows: list[dict[str, Any]], results: Mapping[str, Any],
                 partial: bool) -> dict[str, list]:
    """B1, B2 (partial), B3 (parent row); M18 sentence numbers whose condition holds for any row (spec 5.4)."""
    args = selected["arguments"]
    removed = selected["receptor"]["removed_instance"] is not None
    numbers: set[int] = set()
    for row in rows:
        parent = row["kind"] == "parent"
        handle = row["result_handle"]
        stereo = (results[handle]["inputs"]["ligand"]["unspecified_stereo_centers"] if handle else
                  None if parent else 0)
        for sentence in C.applicable_limitations(mode=args["mode"], source="sdf" if parent else "candidate",
                                                 removed_instance=removed, unspecified_stereo_centers=stereo):
            numbers.add(C.LIMITATIONS.index(sentence) + 1)
    batch = ["B1"] + ["B2"] * partial + ["B3"] * args["include_parent"]
    return {"batch_statements": batch, "m18_sentences": sorted(numbers)}


def _inputs(selected: dict[str, Any]) -> dict[str, Any]:
    args = selected["arguments"]
    return {"receptor": {"handle": args["receptor_handle"], "sha256": selected["receptor"]["sha256"],
                         "model_number": args["receptor_model_number"], "connectivity": args["connectivity"],
                         "removed_instance": selected["receptor"]["removed_instance"],
                         "acknowledgement": args["acknowledgement"]},
            "candidate_set": {"handle": args["candidate_set_handle"], "parent_sdf_handle": args["parent_sdf_handle"],
                              "parent_sdf_sha256": selected["parent_sdf"]["sha256"]},
            "candidate_ids": args["candidate_ids"], "include_parent": args["include_parent"], "mode": args["mode"]}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {"rows": len(rows), **{state: sum(row["state"] == state for row in rows) for state in BC.ROW_STATES}}


def build_summary(selected: dict[str, Any], *, observations: list[dict[str, Any]], results: Mapping[str, Any],
                  stop_cause: str | None, box: dict[str, Any], engine: dict[str, Any]) -> dict[str, Any]:
    """The ``docking_batch_result@1`` content (no time, reuse or job identity), checked before it is returned."""
    try:
        rows = derive_rows(selected, observations, results, stop_cause)
        partial = any(row["state"] in STOPPED for row in rows)
        args = selected["arguments"]
        content = {"schema": BC.SUMMARY_SCHEMA, "protocol": BC.PROTOCOL, "method": C.METHODS[args["mode"]],
                   "batch_input_sha256": selected["batch_input_sha256"], "inputs": _inputs(selected),
                   "box": box, "parameters": {**args["parameters"], "cpu": C.CPU}, "engine": engine,
                   "preparation": dict(PREPARATION), "limits": dict(BC.LIMITS),
                   "status": "partial" if partial else "complete",
                   "stop_reason": next((row["reason_code"] for row in rows if row["state"] in STOPPED), None),
                   "rows": rows, "counts": _counts(rows),
                   "limitations": _limitations(selected, rows, results, partial)}
        _check(content, selected, results)
        return content
    except DockingBatchEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise DockingBatchEvidenceError("batch observations are invalid") from exc


# ----------------------------------------------------------------- validation
def _float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _check_selection(selected: dict[str, Any]) -> None:
    args = selected["arguments"]
    _require(selected["schema"] == BC.SELECTION_SCHEMA and
             selected["batch_input_sha256"] == docking_batch_inputs.batch_input_sha256(selected), "batch selection")
    plan = docking_batch_inputs.planned_rows(args["candidate_ids"], args["candidate_ids"], args["include_parent"])
    _require(len(selected["rows"]) == len(plan), "selection rows")
    for planned, row in zip(plan, selected["rows"], strict=True):
        row_args = row["selected"]["arguments"]
        _require({key: row[key] for key in ("row_index", "kind", "candidate_id")} == planned and
                 row_args == docking_batch_inputs.row_arguments(args, row["kind"], row["candidate_id"]) and
                 row["selected"]["input_sha256"] == docking_inputs.input_sha256(row_args), "selection row")


def _check_box(box: Any, request: dict[str, Any]) -> None:
    _require(type(box) is dict and set(box) == {"center_A", "size_A", "source", "margin_A"} and
             box["source"] == request["source"] and
             all(type(box[key]) is list and len(box[key]) == 3 and all(_float(x) for x in box[key])
                 for key in ("center_A", "size_A")) and
             all(0 < x <= C.BOX_SIDE_MAX_A for x in box["size_A"]), "box")
    if request["source"] == "manual":
        _require(box["center_A"] == request["center_A"] and box["size_A"] == request["size_A"] and
                 box["margin_A"] is None, "manual box is the request")
    else:
        _require(box["margin_A"] == request["margin_A"], "range box margin")


def _check_engine(engine: Any) -> None:
    _require(type(engine) is dict and set(engine) == {"name", "version", "binary_sha256", "package"} and
             engine["name"] == C.ENGINE and type(engine["version"]) is str and type(engine["package"]) is str and
             engine["package"].startswith(f"qvina-{engine['version']}-") and
             type(engine["binary_sha256"]) is str and SHA_RE.fullmatch(engine["binary_sha256"]), "engine")


def _check_row_result(result: Any, planned: dict[str, Any], content: dict[str, Any]) -> None:
    """The per-row result is the row's own M18 input under the batch's shared settings (spec 5.2 last bullet)."""
    ligand = result["inputs"]["ligand"]
    _require(result["schema"] == C.RESULT_SCHEMA and result["method"] == content["method"] and
             result["input_sha256"] == planned["selected"]["input_sha256"] and
             result["inputs"]["mode"] == content["inputs"]["mode"] and
             result["inputs"]["receptor"] == content["inputs"]["receptor"] and
             ligand["source"] == ("sdf" if planned["kind"] == "parent" else "candidate") and
             ligand["candidate_id"] == planned["candidate_id"] and
             result["box"] == content["box"] and result["parameters"] == content["parameters"] and
             result["engine"] == content["engine"] and result["preparation"] == content["preparation"],
             "per-row result inputs")


def _check(content: Any, selected: dict[str, Any], results: Mapping[str, Any]) -> None:
    _require(type(content) is dict and set(content) == SUMMARY_KEYS and content["schema"] == BC.SUMMARY_SCHEMA and
             content["protocol"] == BC.PROTOCOL, "summary keys")
    _check_selection(selected)
    args = selected["arguments"]
    _require(content["method"] == C.METHODS[args["mode"]], "method")
    _require(content["batch_input_sha256"] == selected["batch_input_sha256"], "batch_input_sha256")
    _require(content["inputs"] == _inputs(selected), "inputs")
    _require(content["parameters"] == {**args["parameters"], "cpu": C.CPU}, "parameters")
    _check_box(content["box"], args["box"])
    _check_engine(content["engine"])
    _require(content["preparation"] == PREPARATION and content["limits"] == BC.LIMITS, "preparation and limits")
    rows = content["rows"]
    _require(type(rows) is list and len(rows) == len(selected["rows"]), "rows")
    for planned, row in zip(selected["rows"], rows, strict=True):
        _require(type(row) is dict and set(row) == ROW_KEYS and
                 [row["row_index"], row["kind"], row["candidate_id"]] ==
                 [planned["row_index"], planned["kind"], planned["candidate_id"]], "row identity")
        state = row["state"]
        _require(state in BC.ROW_STATES and row["reason_code"] in REASONS_BY_STATE[state], "row state and reason")
        if state in ("scored", "null_result"):
            handle = row["result_handle"]
            _require(type(handle) is str and handle in results, "row result handle")
            result = results[handle]
            _check_row_result(result, planned, content)
            _require(_result_state(result) == state, "row state is the result's")
            score, label = _score(result, state, args["mode"])
            _require((state == "null_result" or _float(score)) and row["score_kcal_mol"] == score and
                     type(row["score_kcal_mol"]) is type(score) and row["score_row_label"] == label,
                     "score is the first result row, copied")
        else:
            _require(row["result_handle"] is None and row["score_kcal_mol"] is None and
                     row["score_row_label"] is None, "a row without a result has no score")
    partial = any(row["state"] in STOPPED for row in rows)
    _require(content["counts"] == _counts(rows), "counts")
    _require(content["status"] == ("partial" if partial else "complete") and
             content["stop_reason"] == next((row["reason_code"] for row in rows if row["state"] in STOPPED), None),
             "status and stop_reason")
    _require(content["limitations"] == _limitations(selected, rows, results, partial), "limitations")
    _require(len(canonical_json(content)) <= BC.MAX_SUMMARY_BYTES, "summary size")


def check_summary(content: Any, selected: dict[str, Any], results: Mapping[str, Any], pins: dict[str, Any]) -> None:
    """Validate a stored or new summary against its batch selection, the validated per-row results (by handle,
    from ``docking_bundle.validated_result``) and the batch job's pins; raise DockingBatchEvidenceError."""
    try:
        _check(content, selected, results)
        _require(content["engine"]["binary_sha256"] == pins["qvina_sha256"] and
                 content["engine"]["package"] == pins["qvina_package"], "engine pins")
    except DockingBatchEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise DockingBatchEvidenceError("batch summary evidence is invalid") from exc


# ----------------------------------------------------------------- call key (spec 5.3)
def batch_call_key(selected: dict[str, Any]) -> str:
    """The batch call key is ``batch_input_sha256`` (handles are run-scoped, so other runs never collide)."""
    return docking_batch_inputs.batch_input_sha256(selected)


def complete_duplicate(summaries: Iterable[tuple[str, dict[str, Any]]], key: str) -> str | None:
    """The handle of a validated ``complete`` summary with this key; a ``partial`` one never deduplicates."""
    return next((handle for handle, content in summaries
                 if content["batch_input_sha256"] == key and content["status"] == "complete"), None)
