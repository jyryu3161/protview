"""M29 read-only projections of ``structure_repair@1`` records (spec 4.5). No tool, no job, no event.

* ``list_repairs()``: this run's repair records, newest first; each page row is re-validated and a row that does not
  validate shows ``valid: false`` with null fields (never stale numbers), as the M20 and M21 lists do.
* ``repair_detail()``: one validated record without its ``added_atoms`` rows (their count is ``added_atom_count``),
  with the four handles of its publication.
* ``atom_page()``: the stored ``added_atoms`` rows in stored (structure) order, by page (1-based) and page size.
* ``structure_download()``: the stored repaired mmCIF bytes, hash-checked against the record.

Every read goes through ``structure_repair_bundle.validated_result`` / ``structure_bytes`` (single completed
publication, job selection, the four objects, the core validator); any failure raises ``RepairEvidenceError``.
Nothing is recomputed: values are the stored ones. The caller checks the handle's run, kind and schema first.
"""
from __future__ import annotations

from typing import Any

from . import structure_repair_bundle as bundle
from . import structure_repair_constants as K
from .structure_repair_bundle import RepairEvidenceError

__all__ = ["KIND", "SCHEMA", "ReadInvalid", "RepairEvidenceError", "atom_page", "list_repairs", "repair_detail",
           "structure_download"]

KIND, SCHEMA = K.KIND, K.SCHEMA
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
ATOM_PAGE_SIZE_DEFAULT, (ATOM_PAGE_SIZE_MIN, ATOM_PAGE_SIZE_MAX) = K.ATOM_PAGE_DEFAULT, K.ATOM_PAGE_RANGE
_LIST_FIELDS = ("prepared_structure", "source_structure", "classes_applied", "counts")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


def _created(run: Any) -> dict[str, int]:
    """Creating event sequence number of each ``structure_repair`` handle, in creation order."""
    found: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == KIND and event["handle"] not in found:
            found[event["handle"]] = event["seq"]
    return found


def list_repairs(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run)
    newest = list(reversed(created))
    rows = []
    for handle in newest[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]}
        try:
            result = bundle.validated_result(run, handle)
            record = result["record"]
            row.update(valid=True, prepared_structure=result["prepared_structure"],
                       source_structure=result["source_structure"], classes_applied=record["classes_applied"],
                       counts=record["counts"])
        except RepairEvidenceError:
            row.update(valid=False, **dict.fromkeys(_LIST_FIELDS))
        rows.append(row)
    return {"schema": "structure_repair_list@1", "total": len(created), "offset": offset, "limit": limit,
            "rows": rows}


def repair_detail(run: Any, handle: str) -> dict[str, Any]:
    result = bundle.validated_result(run, handle)
    record = result["record"]
    return {"schema": "structure_repair_detail@1", "handle": handle,
            "prepared_structure": result["prepared_structure"], "source_structure": result["source_structure"],
            "coordinates": result["coordinates"], "manifest": result["manifest"],
            "published_seq": result["published_seq"], "added_atom_count": len(record["added_atoms"]),
            "result": {key: value for key, value in record.items() if key != "added_atoms"}}


def atom_page(run: Any, handle: str, *, page: int, page_size: int) -> dict[str, Any]:
    if type(page) is not int or page < 1:
        raise ReadInvalid("page must be an integer >= 1")
    if type(page_size) is not int or not ATOM_PAGE_SIZE_MIN <= page_size <= ATOM_PAGE_SIZE_MAX:
        raise ReadInvalid(f"page_size must be an integer in [{ATOM_PAGE_SIZE_MIN}, {ATOM_PAGE_SIZE_MAX}]")
    atoms = bundle.validated_result(run, handle)["record"]["added_atoms"]
    start = (page - 1) * page_size
    rows = [{"index": index, **row} for index, row in enumerate(atoms)][start:start + page_size]
    return {"schema": "structure_repair_atom_page@1", "handle": handle, "total": len(atoms), "page": page,
            "page_size": page_size, "rows": rows}


def structure_download(run: Any, handle: str) -> tuple[bytes, str]:
    """``(stored repaired mmCIF bytes, filename)``; the bytes match the record's ``result.coordinates_sha256``."""
    raw = bundle.structure_bytes(run, handle)
    return raw, f"protview-structure-repair-{handle.rsplit('/', 1)[-1][:12]}.cif"
