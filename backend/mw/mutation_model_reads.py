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
run, kind and schema first. Docking pairs (``docking_pairs``) are a separate read (spec 7).
"""
from __future__ import annotations

from typing import Any

from . import mutation_model_bundle as bundle
from .mutation_model_bundle import MutationEvidenceError
from .mutation_model_constants import KIND, SCHEMA, STRUCTURE_SIDES

__all__ = ["MutationEvidenceError", "ReadInvalid", "contact_page", "list_models", "model_detail",
           "structure_download", "structure_summary"]

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
