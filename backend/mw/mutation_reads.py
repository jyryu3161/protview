"""M20 read-only projections of ``mutation_candidate_set@1`` objects (spec 8). No tool, no job, no event.

* ``list_sets()``: this run's sets, newest first; each page row is re-validated and a row that does not validate shows
  ``valid: false`` with null fields (never stale numbers), as the M18 result list does.
* ``set_detail()``: one validated set without ``positions``/``candidates`` plus ``total_positions``/``total_candidates``.
* M26 spec 8.5: list rows and the detail also carry ``catalytic_status``, the stored
  ``protection_checks.catalytic_residue_database.status`` (``not_available`` for a v1 set, ``not_checked`` /
  ``checked`` for v2). It is only a new key: every other key and value is what it was for v1.
* ``position_page()``: stored position rows filtered by status / source / exclusion reason / ``chain_auth``, in stored
  order or by ``ligand_min_distance_A`` (ascending, null rows always last, ties by order); ``total`` after the filter.
* ``candidate_page()``: stored candidate rows filtered by ``position_index`` / ``to``, each with the residue and
  ``standard_resname`` copied from its position row; ``total`` after the filter.

* M29 (spec 5.3, 5.4), only for a set whose structure is a repaired structure (``mutation_handoff.read_view``): the
  detail and the position page also carry ``repair_handoff`` (``references``: the set's reference results made on the
  original structure; ``statements``: SO2 / SO3 as ``{id, text}``), and every position row of the page also carries
  ``modeled_basis`` (bool) and ``reference_not_checked`` (the stored fields shown as not checked, modeled residue).
  The stored set is never changed; for any other set no key is added (the bytes are what they were).

Every read loads the stored object from the store (content-hash check) and runs ``mutation_candidates.validated_set``;
any failure raises ``MutationEvidenceError``. The caller checks the handle's run, kind and schema first.
"""
from __future__ import annotations

from typing import Any

from . import mutation_candidates as mc
from . import mutation_handoff
from .core.errors import ToolFailure
from .mutation_constants import EXCLUSION_REASONS_V2, KIND, ONE_LETTER_ORDER, POSITION_STATUSES, SCHEMA, SOURCE_KINDS

LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
POSITION_LIMIT_DEFAULT, POSITION_LIMIT_MAX = 50, 100
CANDIDATE_LIMIT_DEFAULT, CANDIDATE_LIMIT_MAX = 100, 200
SORTS = ("order", "ligand_distance")
_LIST_FIELDS = ("structure", "model_number", "ligand", "sources_used", "klifs_status", "numbering_map", "annotation",
                "counts", "null_result", "catalytic_status")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


class MutationEvidenceError(ValueError):
    """The stored object does not load or does not validate (mapped to 422 ``method_evidence_invalid``)."""


def validated(run: Any, handle: str) -> dict[str, Any]:
    try:
        return mc.validated_set(run.store.load(handle))
    except (mc.MutationSetInvalid, ValueError, TypeError, KeyError) as exc:
        raise MutationEvidenceError("invalid mutation candidate set") from exc


def _created(run: Any) -> dict[str, int]:
    """Creating event sequence number of each ``mutation_candidate_set`` handle, in creation order."""
    found: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == KIND and event["handle"] not in found:
            found[event["handle"]] = event["seq"]
    return found


def list_sets(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run)
    newest = list(reversed(created))
    rows = []
    for handle in newest[offset:offset + limit]:
        row: dict[str, Any] = {"handle": handle, "created_seq": created[handle]}
        try:
            if run.store.meta(handle)["schema"] != SCHEMA:
                raise MutationEvidenceError("unexpected schema")
            content = validated(run, handle)
            parameters, sources = content["parameters"], content["parameters"]["sources"]
            row.update(valid=True, structure=content["structure"]["handle"],
                       model_number=content["structure"]["model_number"], ligand=content["ligand"],
                       sources_used={"pocket": sources["pocket"] is not None,
                                     "ligand_shell": sources["ligand_shell"] is not None,
                                     "user": bool(sources["residues"])},
                       klifs_status=content["protection_checks"]["klifs_key_sites"]["status"],
                       numbering_map=parameters["numbering_map"], annotation=parameters["annotation"],
                       counts=content["counts"], null_result=content["null_result"],
                       catalytic_status=catalytic_status(content))
        except MutationEvidenceError:
            row.update(valid=False, **dict.fromkeys(_LIST_FIELDS))
        rows.append(row)
    return {"schema": "mutation_candidate_set_list@1", "total": len(created), "offset": offset, "limit": limit,
            "rows": rows}


def catalytic_status(content: dict[str, Any]) -> str:
    """``not_available`` (v1), ``not_checked`` or ``checked`` (v2), as stored in the validated set."""
    return content["protection_checks"]["catalytic_residue_database"]["status"]


def repair_view(run: Any, content: dict[str, Any]) -> dict[str, Any] | None:
    """``mutation_handoff.read_view`` of a validated set (None unless its structure is a repaired structure)."""
    try:
        return mutation_handoff.read_view(run.store, content)
    except (ToolFailure, KeyError, TypeError, ValueError) as exc:
        raise MutationEvidenceError("the repaired structure of the set does not validate") from exc


def set_detail(run: Any, handle: str) -> dict[str, Any]:
    content = validated(run, handle)
    detail = {"schema": "mutation_candidate_set_detail@1", "handle": handle,
              "result": {key: value for key, value in content.items() if key not in ("positions", "candidates")},
              "total_positions": len(content["positions"]), "total_candidates": len(content["candidates"]),
              "catalytic_status": catalytic_status(content)}
    view = repair_view(run, content)
    if view is not None:
        detail["repair_handoff"] = view["repair_handoff"]
    return detail


def _closed(value: str | None, closed: tuple[str, ...], name: str) -> None:
    if value is not None and value not in closed:
        raise ReadInvalid(f"{name} must be one of {list(closed)}")


def position_order(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Stored order, or ``ligand_min_distance_A`` ascending with null rows always last and ties by ``index``."""
    if sort == "order":
        return sorted(rows, key=lambda row: row["index"])
    return sorted(rows, key=lambda row: (row["ligand_min_distance_A"] is None,
                                         row["ligand_min_distance_A"] or 0.0, row["index"]))


def position_page(run: Any, handle: str, *, status: str | None, source: str | None, exclusion_reason: str | None,
                  chain_auth: str | None, sort: str, offset: int, limit: int) -> dict[str, Any]:
    _closed(status, POSITION_STATUSES, "status")
    _closed(source, SOURCE_KINDS, "source")
    _closed(exclusion_reason, EXCLUSION_REASONS_V2, "exclusion_reason")   # v2 closed set (a superset of v1)
    _closed(sort, SORTS, "sort")
    content = validated(run, handle)
    rows = [row for row in content["positions"]
            if (status is None or row["status"] == status)
            and (source is None or any(item["kind"] == source for item in row["sources"]))
            and (exclusion_reason is None or exclusion_reason in row["exclusion_reasons"])
            and (chain_auth is None or row["residue"]["chain_auth"] == chain_auth)]
    rows = position_order(rows, sort)
    page = {"schema": "mutation_position_page@1", "handle": handle,
            "filters": {"status": status, "source": source, "exclusion_reason": exclusion_reason,
                        "chain_auth": chain_auth},
            "sort": sort, "total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}
    view = repair_view(run, content)
    if view is not None:
        page["rows"] = [{**row, **view["positions"][row["index"]]} for row in page["rows"]]
        page["repair_handoff"] = view["repair_handoff"]
    return page


def candidate_page(run: Any, handle: str, *, position_index: int | None, to: str | None, offset: int,
                   limit: int) -> dict[str, Any]:
    _closed(to, tuple(ONE_LETTER_ORDER), "to")
    content = validated(run, handle)
    positions = content["positions"]
    rows = [{"index": item["index"], "position_index": item["position_index"],
             "residue": positions[item["position_index"]]["residue"],
             "standard_resname": positions[item["position_index"]]["standard_resname"],
             "from": item["from"], "to": item["to"]}
            for item in content["candidates"]
            if (position_index is None or item["position_index"] == position_index) and (to is None or item["to"] == to)]
    return {"schema": "mutation_candidate_page@1", "handle": handle,
            "filters": {"position_index": position_index, "to": to},
            "total": len(rows), "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}
