"""M18 read-only projections for the docking area of the ligand tab (spec 3.1, 7). No RDKit, no Meeko, no qvina,
no tool, no job, no event.

* ``prerequisites()``: this run's ``receptor``/``receptor_bonds``/``ligand_sdf`` imports (kind, size, SHA-256),
  its M17 candidate sets (re-validated: candidate count, parent hash, same-run parent SDF imports with that hash),
  the docking result count and the capability (``methods.ligand_docking``).
* ``receptor_instances()``: the nonstandard residue instances of one same-run receptor import, read by gemmi
  (``docking_inputs.receptor_instances``: seven residue fields as read, atom count, element counts; water only
  counted). A selection aid only: job admission and the worker check the selection again.
* ``list_results()``: this run's ``docking_result`` objects in creation order; each page row is re-validated and a
  row that does not validate shows ``valid: false`` with null fields (never stale numbers).
* ``result_detail()``: one validated result without ``pose_sdf``/``contacts``; each mode row carries its stored
  contact count. ``contact_page()`` pages one mode's stored contact rows (stored order: ``ligand_serial``,
  ``site_index``). ``pose_sdf()``/``all_poses_sdf()``: the stored pose SDF text of one mode (one record, no
  ``$$$$``) or of every mode (records separated by ``$$$$``, titles ``mode_<n>`` as stored).

Every result read goes through ``docking_bundle.validated_result`` (bounded load with the store's content-hash
check, single completed publication, inputs, closed sets); failures raise ``DockingEvidenceError``.
"""
from __future__ import annotations

import re
from typing import Any

from . import docking_bundle, docking_inputs
from . import docking_constants as C
from .ligand_bundle import LigandEvidenceError, validated_candidate_set

RESULT = docking_bundle.OUTPUT_KIND
RESULT_SCHEMA = C.RESULT_SCHEMA
MODE_MAX = C.NUM_MODES_MAX
CANDIDATE_SET = "ligand_candidate_set"
IMPORT_KINDS = ("receptor", "receptor_bonds", "ligand_sdf")
CONTACT_LIMIT_DEFAULT = 100
CONTACT_LIMIT_MAX = C.MAX_CONTACTS_PER_MODE
_HANDLE_SHA = re.compile(r"obj://[^/]+/docking_result/([0-9a-f]{64})\Z")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


class ModeUnknown(LookupError):
    """The validated result has no mode with this number (mapped to 404 ``not_found``)."""


def _created(run: Any, kind: str) -> dict[str, dict[str, Any]]:
    """``object_created`` events of ``kind`` keyed by handle, in creation order."""
    found: dict[str, dict[str, Any]] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == kind and event["handle"] not in found:
            found[event["handle"]] = event
    return found


# ----------------------------------------------------------------- prerequisites and receptor instances
def prerequisites(run: Any) -> dict[str, Any]:
    counts = dict.fromkeys(IMPORT_KINDS, 0)
    imports: list[dict[str, Any]] = []
    sets: list[str] = []
    results = 0
    for event in run.events.read():
        if event["type"] != "object_created":
            continue
        kind = event.get("kind")
        if kind == "chemical_raw_input":
            summary = event.get("summary") or {}
            if summary.get("input_kind") in counts:
                counts[summary["input_kind"]] += 1
                imports.append({"handle": event["handle"], "input_kind": summary["input_kind"],
                                "input_format": summary.get("input_format"),
                                "size": run.store.meta(event["handle"])["size"],
                                "sha256": summary.get("sha256"), "created_seq": event["seq"]})
        elif kind == CANDIDATE_SET and event["handle"] not in sets:
            sets.append(event["handle"])
        results += kind == RESULT
    ligand_sdfs = [row for row in imports if row["input_kind"] == "ligand_sdf"]
    candidate_sets = []
    for handle in sets:
        row: dict[str, Any] = {"handle": handle}
        try:
            content, _ = validated_candidate_set(run, handle)
            row.update(valid=True, candidates=len(content["candidates"]), parent_handle=content["parent_handle"],
                       parent_sha256=content["parent_sha256"],
                       parent_sdf_handles=[item["handle"] for item in ligand_sdfs
                                           if item["sha256"] == content["parent_sha256"]])
        except LigandEvidenceError:
            row.update(valid=False, candidates=None, parent_handle=None, parent_sha256=None, parent_sdf_handles=None)
        candidate_sets.append(row)
    return {"schema": "docking_prerequisites@1", "capability": docking_bundle.capability(), "import_counts": counts,
            "imports": imports, "candidate_sets": candidate_sets, "docking_results": results, "starts_job": False}


def receptor_instances(run: Any, handle: Any) -> dict[str, Any]:
    """Nonstandard residue instances of one same-run receptor import (gemmi only); a ToolFailure
    (``receptor_invalid``) propagates when the bytes do not read as a structure."""
    if type(handle) is not str:
        raise ReadInvalid("handle must be a string")
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise ReadInvalid("handle is not a same-run receptor import") from exc
    summary = meta["summary"]
    if ((meta["kind"], meta["schema"]) != ("chemical_raw_input", "chemical_raw_input@1") or
            summary.get("input_kind") != "receptor" or meta["fmt"] in ("json", "parquet") or
            not 0 < meta["size"] <= docking_bundle.MAX_INPUT_BYTES):
        raise ReadInvalid("handle is not a receptor import")
    fmt = summary.get("input_format", meta["fmt"])
    fmt = "cif" if fmt == "mmcif" else fmt
    if fmt not in ("pdb", "cif"):
        raise ReadInvalid("receptor import format must be pdb or cif")
    raw = run.store.load_bounded_bytes(handle, docking_bundle.MAX_INPUT_BYTES)
    listed = docking_inputs.receptor_instances(raw, fmt)
    return {"schema": listed["schema"], "handle": handle, "sha256": summary.get("sha256"), "format": fmt,
            "model_numbers": [model["model_number"] for model in listed["models"]], "models": listed["models"],
            "selection_aid_only": True, "starts_job": False}


# ----------------------------------------------------------------- results
def result(run: Any, handle: Any) -> dict[str, Any]:
    return docking_bundle.validated_result(run, handle)


def list_results(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run, RESULT)
    rows = []
    for handle in list(created)[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]["seq"]}
        try:
            content = result(run, handle)
            ligand = content["inputs"]["ligand"]
            receptor = content["inputs"]["receptor"]   # M21 mutation-model source: no import handle (null)
            row.update(valid=True, reason_code=None, job_id=docking_bundle.producer(run, handle)["job_id"],
                       method=content["method"], mode=content["inputs"]["mode"], ligand_source=ligand["source"],
                       candidate_id=ligand["candidate_id"], receptor_handle=receptor.get("handle"),
                       seed=content["parameters"]["seed"], box_source=content["box"]["source"],
                       modes=content["counts"]["modes"], null_result=content["counts"]["null_result"])
        except docking_bundle.DockingEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", job_id=None, method=None, mode=None,
                       ligand_source=None, candidate_id=None, receptor_handle=None, seed=None, box_source=None,
                       modes=None, null_result=None)
        rows.append(row)
    return {"schema": "docking_result_list@1", "total": len(created), "offset": offset, "limit": limit,
            "rows": rows}


def result_detail(run: Any, handle: str) -> dict[str, Any]:
    content = result(run, handle)
    modes = [{**{key: value for key, value in row.items() if key not in ("pose_sdf", "contacts")},
              "contact_count": len(row["contacts"])} for row in content["modes"]]
    return {"schema": "docking_result_detail@1", "handle": handle,
            "job_id": docking_bundle.producer(run, handle)["job_id"], "score_label": C.SCORE_LABEL,
            "result": {**{key: value for key, value in content.items() if key != "modes"}, "modes": modes}}


def _mode(content: dict[str, Any], mode: int) -> dict[str, Any]:
    if not 1 <= mode <= len(content["modes"]):
        raise ModeUnknown(f"result has no mode {mode}")
    return content["modes"][mode - 1]


def contact_page(run: Any, handle: str, mode: int, offset: int, limit: int) -> dict[str, Any]:
    content = result(run, handle)
    contacts = _mode(content, mode)["contacts"]
    return {"schema": "docking_contact_page@1", "handle": handle, "mode": mode, "method": content["method"],
            "cutoff_A": C.CONTACT_CUTOFF_A, "total": len(contacts), "offset": offset, "limit": limit,
            "rows": contacts[offset:offset + limit]}


def _file_stem(handle: str) -> str:
    """A fixed download name from the validated handle hash (never from user input)."""
    match = _HANDLE_SHA.fullmatch(handle)
    if not match:
        raise ReadInvalid("handle is not a docking result")
    return f"protview-docking-{match.group(1)[:12]}"


def pose_sdf(run: Any, handle: str, mode: int) -> tuple[bytes, str]:
    content = result(run, handle)
    text = _mode(content, mode)["pose_sdf"]
    return text.encode("utf-8"), f"{_file_stem(handle)}-mode_{mode}.sdf"


def all_poses_sdf(run: Any, handle: str) -> tuple[bytes, str]:
    content = result(run, handle)
    if not content["modes"]:
        raise ModeUnknown("result has no modes (empty scientific result)")
    records = [row["pose_sdf"] if row["pose_sdf"].endswith("\n") else row["pose_sdf"] + "\n"
               for row in content["modes"]]
    return "".join(f"{record}$$$$\n" for record in records).encode("utf-8"), f"{_file_stem(handle)}-modes.sdf"
