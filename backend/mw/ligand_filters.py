"""M17 filter evaluation on stored candidate rows (spec 5). Pure, no RDKit, no events.

Filter spec (normalized form, also what a report records):

    {"ranges": {<property name>: {"min": number | None, "max": number | None}, ...},
     "pains_exclude": bool}

Both keys are optional on input (defaults: no ranges, ``pains_exclude`` false). Property names are the 8 of
``PROPERTY_NAMES``; bounds are finite int/float (not bool), inclusive, and ``min <= max``. A range whose
bounds are both ``None`` is inactive and dropped. Active filters are the ranges left plus ``pains_exclude``
when true. ``passes_all`` is ``None`` when no filter is active.

Rows are stored ``ligand_candidate_set@1`` rows: ``properties`` must hold all 8 names as finite numbers
(never null) and ``pains.matches`` a list. A row breaking this is a corrupt stored object and is refused.
"""
from __future__ import annotations

import math
from typing import Any

from .core.errors import FailureClass, ToolFailure
from .ligand_constants import PAINS_FILTER, PROPERTY_NAMES, SORT_DIRECTIONS, SORT_KEYS

MAX_PAGE_LIMIT = 1_000


def _invalid(message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message)


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def normalize_filter_spec(spec: Any) -> dict[str, Any]:
    if type(spec) is not dict or set(spec) - {"ranges", PAINS_FILTER}:
        raise _invalid("filter spec accepts only ranges and pains_exclude")
    ranges = spec.get("ranges", {})
    pains = spec.get(PAINS_FILTER, False)
    if type(ranges) is not dict or type(pains) is not bool:
        raise _invalid("filter ranges must be an object and pains_exclude a boolean")
    out: dict[str, dict[str, Any]] = {}
    for name, bounds in ranges.items():
        if name not in PROPERTY_NAMES:
            raise _invalid(f"unknown filter property: {name}")
        if type(bounds) is not dict or set(bounds) - {"min", "max"}:
            raise _invalid("filter range accepts only min and max")
        low, high = bounds.get("min"), bounds.get("max")
        if any(x is not None and not _number(x) for x in (low, high)):
            raise _invalid("filter bounds must be finite numbers")
        if low is not None and high is not None and low > high:
            raise _invalid("filter min is greater than max")
        if low is not None or high is not None:
            out[name] = {"min": low, "max": high}
    return {"ranges": {name: out[name] for name in PROPERTY_NAMES if name in out}, PAINS_FILTER: pains}


def _checked_row(row: Any) -> tuple[dict[str, Any], list[Any]]:
    try:
        properties, matches = row["properties"], row["pains"]["matches"]
    except (KeyError, TypeError) as exc:
        raise _invalid("stored candidate row lacks properties or PAINS matches") from exc
    if (type(properties) is not dict or set(properties) != set(PROPERTY_NAMES) or
            not all(_number(properties[name]) for name in PROPERTY_NAMES) or type(matches) is not list):
        raise _invalid("stored candidate row has missing, null or non-numeric properties")
    return properties, matches


def evaluate_row(row: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Per-filter pass/fail for one stored row under a normalized spec."""
    properties, matches = _checked_row(row)
    filters: dict[str, bool] = {}
    for name, bounds in spec["ranges"].items():
        value = properties[name]
        filters[name] = ((bounds["min"] is None or value >= bounds["min"]) and
                         (bounds["max"] is None or value <= bounds["max"]))
    if spec[PAINS_FILTER]:
        filters[PAINS_FILTER] = not matches
    return {"filters": filters, "passes_all": all(filters.values()) if filters else None}


def query_candidates(rows: list[Any], spec: dict[str, Any], *, sort: str = "generation_order",
                     direction: str = "asc", offset: int = 0, limit: int = 100,
                     passes_only: bool = False) -> dict[str, Any]:
    """Evaluate, sort and page stored rows. ``generation_order`` is the stored row index.

    Ties keep generation order in both directions. ``passes_only`` keeps rows with ``passes_all`` true;
    with no active filter it hides nothing. ``hidden_by_filter`` = total - matched.
    """
    if sort not in SORT_KEYS or direction not in SORT_DIRECTIONS:
        raise _invalid("unknown sort key or direction")
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_PAGE_LIMIT or
            type(passes_only) is not bool):
        raise _invalid("invalid candidate page arguments")
    evaluated = [{"generation_order": i, "candidate": row, **evaluate_row(row, spec)} for i, row in enumerate(rows)]
    active = bool(spec["ranges"]) or spec[PAINS_FILTER]
    counts = {name: sum(item["filters"][name] for item in evaluated)
              for name in [*spec["ranges"], *([PAINS_FILTER] if spec[PAINS_FILTER] else [])]}
    passing = sum(item["passes_all"] is True for item in evaluated) if active else None
    shown = [item for item in evaluated if not passes_only or not active or item["passes_all"]]
    sign = -1 if direction == "desc" else 1
    if sort != "generation_order":
        shown.sort(key=lambda item: (sign * item["candidate"]["properties"][sort], item["generation_order"]))
    elif direction == "desc":
        shown.reverse()
    return {"total": len(evaluated), "passing": passing, "filter_pass_counts": counts,
            "matched": len(shown), "hidden_by_filter": len(evaluated) - len(shown), "sort": sort,
            "direction": direction, "offset": offset, "limit": limit, "passes_only": passes_only,
            "filter_spec": spec, "rows": shown[offset:offset + limit]}
