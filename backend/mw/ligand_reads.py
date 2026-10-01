"""M17 read-only projections for the ligand tab (spec 4.1, 5, 6.3, 6.4, 7). No RDKit, no tool, no job, no event.

* ``prerequisites()``: this run's ligand import counts/handles, inspection and candidate-set counts, capability.
* ``list_inspections()`` / ``list_candidate_sets()``: this run's objects in creation order (oldest first); each
  page row is re-validated, and a row that does not validate shows ``valid: false`` with null fields (never
  stale numbers). The inspection SVG and candidate rows are not in list rows.
* ``inspection_detail()``: one validated inspection with its SVG. ``candidate_set_detail()``: one validated set
  without its candidate rows (those are only paged by ``candidate_page()``).
* ``candidate_page()``: the server evaluates the filter spec on stored values (``ligand_filters``), sorts and pages.
* ``preview()``: the site pre-check (``ligand_site.check_site``) plus rule/method selection, as the enumeration
  admission would judge them; refused with ``inspection_required`` (412) while the run has no inspection.

Every content read goes through ``ligand_bundle.validated_*`` (bounded load with the store's content-hash check,
completed publication, inputs, closed sets); failures raise ``LigandEvidenceError``.
"""
from __future__ import annotations

import math
import re
from typing import Any

from . import ligand_bundle
from .core.errors import FailureClass, ToolFailure
from .ligand_bundle import LigandEvidenceError
from .ligand_constants import BLOCK_IMPORT_KINDS, PAINS_FILTER, PROPERTY_NAMES, RULE_VALID, SORT_DIRECTIONS, SORT_KEYS
from .ligand_filters import normalize_filter_spec, query_candidates
from .ligand_site import check_site

INSPECTION = "ligand_inspection"
CANDIDATE_SET = "ligand_candidate_set"
IMPORT_KINDS = ("ligand_sdf", *BLOCK_IMPORT_KINDS)
PAGE_LIMIT_DEFAULT = 50
PAGE_LIMIT_MAX = 100
MAX_OFFSET = 1_000_000
MAX_SITE_ATOMS = 1_024
PREVIEW_KEYS = frozenset({"inspection_handle", "site_atoms", "use_fixed", "rule_ids"})
RANGE_PARAMS = {f"{name}_{side}": (name, side) for name in PROPERTY_NAMES for side in ("min", "max")}
ROW_PARAMS = frozenset({"handle", "offset", "limit", "sort", "direction", "passes_only", PAINS_FILTER,
                        *RANGE_PARAMS})
_INT_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,15})\Z")
_NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_BOOLS = {"true": True, "false": False}


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


def _created(run: Any, kind: str) -> dict[str, dict[str, Any]]:
    """``object_created`` events of ``kind`` keyed by handle, in creation order."""
    found: dict[str, dict[str, Any]] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == kind and event["handle"] not in found:
            found[event["handle"]] = event
    return found


def inspection(run: Any, handle: Any) -> dict[str, Any]:
    return ligand_bundle.validated_inspection(run, handle)


def candidate_set(run: Any, handle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return ligand_bundle.validated_candidate_set(run, handle)


def _producer_job(run: Any, handle: str, protocol: str) -> str:
    return ligand_bundle.producer(run, handle, protocol)["job_id"]


# ----------------------------------------------------------------- prerequisites and lists
def prerequisites(run: Any) -> dict[str, Any]:
    counts = dict.fromkeys(IMPORT_KINDS, 0)
    imports, inspections, sets = [], 0, 0
    for event in run.events.read():
        if event["type"] != "object_created":
            continue
        if event.get("kind") == "chemical_raw_input":
            summary = event.get("summary") or {}
            if summary.get("input_kind") in counts:
                counts[summary["input_kind"]] += 1
                imports.append({"handle": event["handle"], "input_kind": summary["input_kind"],
                                "sha256": summary.get("sha256"), "created_seq": event["seq"]})
        inspections += event.get("kind") == INSPECTION
        sets += event.get("kind") == CANDIDATE_SET
    return {"schema": "ligand_prerequisites@1", "capability": ligand_bundle.capability(), "import_counts": counts,
            "imports": imports, "inspections": inspections, "candidate_sets": sets,
            "requires": ["ligand_sdf", "inspection"], "starts_job": False}


def list_inspections(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run, INSPECTION)
    rows = []
    for handle in list(created)[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]["seq"]}
        try:
            content = inspection(run, handle)
            parent = content["parent"]
            row.update(valid=True, reason_code=None, job_id=_producer_job(run, handle, ligand_bundle.INSPECT),
                       parent_handle=content["parent_handle"], parent_sha256=parent["sha256"],
                       parent_canonical_smiles=parent["canonical_smiles"],
                       heavy_atom_count=parent["heavy_atom_count"], block_handles=content["block_handles"],
                       blocks_accepted=sum(library["accepted"] for library in content["block_libraries"]),
                       rules_total=len(content["rules"]),
                       rules_valid=sum(rule["status"] == RULE_VALID for rule in content["rules"]))
        except LigandEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", job_id=None, parent_handle=None,
                       parent_sha256=None, parent_canonical_smiles=None, heavy_atom_count=None, block_handles=None,
                       blocks_accepted=None, rules_total=None, rules_valid=None)
        rows.append(row)
    return {"schema": "ligand_inspection_list@1", "total": len(created), "offset": offset, "limit": limit,
            "rows": rows}


def list_candidate_sets(run: Any, inspection_handle: str | None, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run, CANDIDATE_SET)
    handles = [handle for handle, event in created.items() if inspection_handle is None or
               (event.get("summary") or {}).get("inspection_handle") == inspection_handle]
    rows = []
    for handle in handles[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]["seq"]}
        try:
            content, _ = candidate_set(run, handle)
            counts = content["counts"]
            row.update(valid=True, reason_code=None, job_id=_producer_job(run, handle, ligand_bundle.ENUMERATE),
                       inspection_handle=content["inspection_handle"], site_atoms=content["site_atoms"],
                       use_fixed=content["use_fixed"], rule_ids=[rule["rule_id"] for rule in content["rules_used"]],
                       candidates=counts["candidates"], raw_products=counts["raw_products"],
                       null_result=counts["candidates"] == 0, limit_reached=content["limit_reached"],
                       stop_reason=content["stop_reason"])
        except LigandEvidenceError:
            row.update(valid=False, reason_code="evidence_invalid", job_id=None, inspection_handle=None,
                       site_atoms=None, use_fixed=None, rule_ids=None, candidates=None, raw_products=None,
                       null_result=None, limit_reached=None, stop_reason=None)
        rows.append(row)
    return {"schema": "ligand_candidate_set_list@1", "inspection_handle": inspection_handle, "total": len(handles),
            "offset": offset, "limit": limit, "rows": rows}


# ----------------------------------------------------------------- detail reads
def inspection_detail(run: Any, handle: str) -> dict[str, Any]:
    content = inspection(run, handle)
    return {"schema": "ligand_inspection_detail@1", "handle": handle,
            "job_id": _producer_job(run, handle, ligand_bundle.INSPECT), "inspection": content}


def candidate_set_detail(run: Any, handle: str) -> dict[str, Any]:
    content, _ = candidate_set(run, handle)
    return {"schema": "ligand_candidate_set_detail@1", "handle": handle,
            "job_id": _producer_job(run, handle, ligand_bundle.ENUMERATE),
            "candidate_count": len(content["candidates"]),
            "candidate_set": {key: value for key, value in content.items() if key != "candidates"}}


# ----------------------------------------------------------------- candidate rows page
def _number(name: str, text: str) -> int | float:
    if _INT_RE.fullmatch(text):
        return int(text)
    if not _NUMBER_RE.fullmatch(text):
        raise ReadInvalid(f"{name} must be a finite decimal number")
    value = float(text)
    if not math.isfinite(value):
        raise ReadInvalid(f"{name} must be a finite decimal number")
    return value


def _flag(name: str, text: str) -> bool:
    if text not in _BOOLS:
        raise ReadInvalid(f"{name} must be true or false")
    return _BOOLS[text]


def parse_page_query(items: list[tuple[str, str]]) -> dict[str, Any]:
    """Strict query: known names only, each at most once; returns handle, filter spec and page arguments."""
    names = [name for name, _ in items]
    unknown = sorted(set(names) - ROW_PARAMS)
    if unknown:
        raise ReadInvalid(f"unknown parameters: {unknown}")
    if len(set(names)) != len(names):
        raise ReadInvalid("a parameter is repeated")
    query = dict(items)
    if "handle" not in query:
        raise ReadInvalid("handle is required")
    ranges: dict[str, dict[str, Any]] = {}
    for name, (prop, side) in RANGE_PARAMS.items():
        if name in query:
            ranges.setdefault(prop, {})[side] = _number(name, query[name])
    try:
        spec = normalize_filter_spec({"ranges": ranges, PAINS_FILTER: _flag(PAINS_FILTER, query.get(PAINS_FILTER,
                                                                                                    "false"))})
    except ToolFailure as exc:
        raise ReadInvalid(exc.message) from exc
    sort, direction = query.get("sort", "generation_order"), query.get("direction", "asc")
    if sort not in SORT_KEYS or direction not in SORT_DIRECTIONS:
        raise ReadInvalid(f"sort must be one of {list(SORT_KEYS)} and direction one of {list(SORT_DIRECTIONS)}")
    offset_text, limit_text = query.get("offset", "0"), query.get("limit", str(PAGE_LIMIT_DEFAULT))
    if not _INT_RE.fullmatch(offset_text) or not 0 <= int(offset_text) <= MAX_OFFSET:
        raise ReadInvalid(f"offset must be an integer 0--{MAX_OFFSET}")
    if not _INT_RE.fullmatch(limit_text) or not 1 <= int(limit_text) <= PAGE_LIMIT_MAX:
        raise ReadInvalid(f"limit must be an integer 1--{PAGE_LIMIT_MAX}")
    return {"handle": query["handle"], "spec": spec, "sort": sort, "direction": direction,
            "offset": int(offset_text), "limit": int(limit_text),
            "passes_only": _flag("passes_only", query.get("passes_only", "false"))}


def candidate_page(run: Any, query: dict[str, Any]) -> dict[str, Any]:
    handle = query["handle"]
    content, _ = candidate_set(run, handle)
    page = query_candidates(content["candidates"], query["spec"], sort=query["sort"], direction=query["direction"],
                            offset=query["offset"], limit=query["limit"], passes_only=query["passes_only"])
    passing = page["passing"]
    return {"schema": "ligand_candidate_page@1", "handle": handle,
            **{key: content[key] for key in ("inspection_handle", "parent_handle", "parent_canonical_smiles",
                                             "parent_properties", "property_methods", "site_atoms",
                                             "retained_parent_atoms", "crossing_bond", "use_fixed", "rules_used",
                                             "counts", "limits", "limit_reached", "stop_reason", "limitations")},
            "failing": None if passing is None else page["total"] - passing, **page}


# ----------------------------------------------------------------- site preview
def _preview_refused(message: str, reason_code: str, cls: FailureClass = FailureClass.input_invalid) -> ToolFailure:
    return ToolFailure(cls, message, detail={"reason_code": reason_code})


def preview(run: Any, body: dict[str, Any]) -> dict[str, Any]:
    """What enumeration admission would decide about this site and selection; starts nothing."""
    if not _created(run, INSPECTION):
        raise _preview_refused("site check needs a completed ligand inspection in this run", "inspection_required",
                               FailureClass.precondition)
    if not set(body) <= PREVIEW_KEYS or not {"inspection_handle", "site_atoms", "use_fixed"} <= set(body):
        raise _preview_refused("preview fields are {inspection_handle, site_atoms, use_fixed, rule_ids}",
                               "invalid_preview_request")
    use_fixed, rule_ids, site_atoms = body["use_fixed"], body.get("rule_ids", []), body["site_atoms"]
    if (type(use_fixed) is not bool or type(rule_ids) is not list or
            any(type(rule_id) is not str for rule_id in rule_ids) or len(set(rule_ids)) != len(rule_ids) or
            type(site_atoms) is not list or len(site_atoms) > MAX_SITE_ATOMS):
        raise _preview_refused("use_fixed must be a boolean, rule_ids distinct strings, site_atoms a list",
                               "invalid_preview_request")
    try:
        inspected = inspection(run, body["inspection_handle"])
    except LigandEvidenceError as exc:
        raise _preview_refused("inspection handle is not a completed same-run ligand inspection",
                               "inspection_invalid") from exc
    try:
        site = check_site({key: inspected["parent"][key] for key in ("atoms", "bonds", "hydrogens")}, site_atoms)
    except ToolFailure as exc:
        raise _preview_refused("site atoms must be a list of distinct integer SDF serials",
                               "site_atoms_invalid") from exc
    statuses = {row["rule_id"]: row["status"] for row in inspected["rules"]}
    rules = [{"rule_id": rule_id, "status": statuses.get(rule_id), "usable": statuses.get(rule_id) == RULE_VALID}
             for rule_id in rule_ids]
    selected = use_fixed or bool(rule_ids)
    blocking = ([] if selected else ["no_generation_method"]) + ([] if site["valid"] else [site["reason"]])
    if not all(rule["usable"] for rule in rules):
        blocking.append("rule_invalid")
    return {"schema": "ligand_site_preview@1", "inspection_handle": body["inspection_handle"], "site_check": site,
            "use_fixed": use_fixed, "rules": rules, "generation_method_selected": selected,
            "ready": not blocking, "blocking_reasons": blocking, "starts_job": False}
