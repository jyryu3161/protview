"""M27 read-only projections (spec 6): the precedent reference set and this run's ``kinase_precedents@1`` results.

No tool call, no job, no event, no external request. Run-scoped reads look at the event log at most once per request
(the list reads it once to find the result objects in creation order; the detail reads the object from the store and
does not need the log). Every result read loads the stored object (content-hash check) and re-checks it with
``kinase_precedents.validated_result``; the result carries its own precedent copies and set record, so it reopens from
events alone, without the reference folder. The current active set is only compared, never used to recompute.

* ``capability()``: ``/capabilities`` ``methods.kinase_precedents`` (set pinned AND its records decoded; five keys).
* ``status()``: ``precedent_reference_status@1``; unavailable -> ``installed: false`` + the reason code, rest null.
* ``list_results(run, offset, limit)``: newest first, ``active`` = the result names the current active set.
* ``parse_detail_query(params)`` -> ``DetailQuery`` (``ReadInvalid`` for an unknown key or value) and
  ``detail(run, handle, query)``: the caller checks the handle's run and kind (``KIND``, ``SCHEMA``) first;
  ``validated(run, handle)`` is the one stored-result read (``ResultEvidenceError``).

The detail filters, searches, sorts and pages one target's stored records on the server so the browser never orders
or narrows precedent values itself. Filters: ``file``, ``site`` / ``goal`` / ``tactic`` (repeatable; OR inside a key,
AND across keys; a record passes a tag key when any of its terms on that axis is asked for), ``variant`` (exact) and
``q`` (case-insensitive substring over exactly ``SEARCH_FIELDS``). Sort keys are exactly ``precedent_constants.
SORT_KEYS``: never an effect, direction or magnitude value. A missing value (``year`` without an integer bibliography
year) is always last; ties keep the record order (``kinase_precedents.move_key`` ascending). Facets count the
selected target's records before any filter (a record counts once per distinct tag term).
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import kinase_precedents as kp
from . import precedent_constants as K
from . import precedent_snapshots as ps

KIND, SCHEMA = K.KIND, K.SCHEMA
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = K.LIST_PAGE_DEFAULT, K.PAGE_LIMIT_MAX
RECORD_LIMIT_DEFAULT, RECORD_LIMIT_MAX = K.RECORDS_PAGE_DEFAULT, K.PAGE_LIMIT_MAX
DETAIL_QUERY_KEYS = ("target", *K.FILTER_KEYS, "sort", "order", "limit", "offset")
SEARCH_FIELDS = ("record.move_id", "record.source.pmid", "record.target.name_as_written", "record.target.variant",
                 "record.observation.text", "record.observation.quote", "record.change.description",
                 "record.change.from_compound", "record.change.to_compound", "record.tradeoffs[].text",
                 "record.tradeoffs[].quote", "bibliography.title")
_STORED_KEYS = ("method_version", "numbering_map", "structure", "pdb_id", "include_flagged", "record_format",
                "precedent_set", "chains", "set_summary", "counts", "null_result", "limitations")
_OVERVIEW_KEYS = ("accession", "chains", "status", "references", "excluded_flagged", "counts")
_DIGITS = re.compile(r"[0-9]+\Z")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


class ResultEvidenceError(ValueError):
    """The stored object does not load or does not validate."""


def capability() -> dict[str, Any]:
    return kp.capability()


def _active_set_hash() -> str | None:
    """The usable active set's hash, or ``None`` (not installed / invalid)."""
    try:
        return kp.pin_and_index()[0].set_hash
    except ps.SnapshotUnavailable:
        return None


def status() -> dict[str, Any]:
    try:
        pinned, index = kp.pin_and_index()
    except ps.SnapshotUnavailable as exc:
        return {"schema": K.STATUS_SCHEMA, "installed": False, "reason": exc.reason_code, "set_hash": None,
                "imported_at": None, "importer_version": None, "kbase": None, "files": None, "bibliography": None,
                "set_summary": None}
    manifest = pinned.manifest
    bibliography = manifest["bibliography"]
    return {"schema": K.STATUS_SCHEMA, "installed": True, "reason": None, "set_hash": pinned.set_hash,
            "imported_at": manifest["imported_at"], "importer_version": manifest["importer_version"],
            "kbase": manifest["kbase"],
            "files": [{"name": entry["name"], "rows": entry["rows"], "bytes": entry["bytes"]}
                      for entry in manifest["files"]],
            "bibliography": {"snapshot_id": bibliography["snapshot_id"], "date": bibliography["date"],
                             "license": bibliography["license"], "rows": bibliography["file"]["rows"]},
            "set_summary": kp.set_summary(index)}


def validated(run: Any, handle: str) -> dict[str, Any]:
    try:
        return kp.validated_result(run.store.load(handle))
    except (kp.ResultInvalid, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ResultEvidenceError("invalid kinase precedents result") from exc


def _created(run: Any) -> dict[str, int]:
    """Creating event sequence number of each ``kinase_precedents`` handle, in creation order (one log read)."""
    found: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == K.KIND and event["handle"] not in found:
            found[event["handle"]] = event["seq"]
    return found


def list_results(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run)
    active = _active_set_hash()
    items = []
    for handle in list(reversed(created))[offset:offset + limit]:   # newest first
        content = validated(run, handle)
        counts, set_hash = content["counts"], content["precedent_set"]["set_hash"]
        items.append({"handle": handle, "numbering_map_handle": content["numbering_map"]["handle"],
                      "pdb_id": content["pdb_id"], "include_flagged": content["include_flagged"],
                      "chain_count": counts["chains"], "linked_chain_count": counts["linked_chains"],
                      "target_count": counts["targets"], "records": dict(counts["records"]),
                      "null_result": content["null_result"], "set_hash": set_hash,
                      "active": active is not None and set_hash == active})
    return {"items": items, "total": len(created)}


# ------------------------------------------------------------------------------------------- detail query

@dataclass(frozen=True)
class DetailQuery:
    target: str | None
    file: str | None
    tags: dict[str, tuple[str, ...]]     # site / goal / tactic -> asked terms (empty: no filter on that axis)
    variant: str | None
    q: str | None                        # stripped search text
    sort: str
    order: str
    limit: int
    offset: int


def _single(params: Mapping[str, Sequence[str]], key: str) -> str | None:
    values = list(params.get(key, ()))
    if len(values) > 1:
        raise ReadInvalid(f"{key} may be given once")
    return values[0] if values else None


def _integer(text: str | None, key: str, default: int, low: int, high: int | None) -> int:
    if text is None:
        return default
    if not _DIGITS.fullmatch(text):
        raise ReadInvalid(f"{key} must be an integer")
    try:
        value = int(text)
    except ValueError as exc:   # beyond the interpreter's digit limit: not readable as an integer
        raise ReadInvalid(f"{key} must be an integer") from exc
    if value < low or (high is not None and value > high):
        raise ReadInvalid(f"{key} must be between {low} and {high}" if high is not None else f"{key} must be >= {low}")
    return value


def parse_detail_query(params: Mapping[str, Sequence[str]]) -> DetailQuery:
    """The detail's query parameters (each key -> its values); unknown keys or values -> ``ReadInvalid``."""
    unknown = set(params) - set(DETAIL_QUERY_KEYS)
    if unknown:
        raise ReadInvalid(f"unknown parameters: {sorted(unknown)}")
    file = _single(params, "file")
    if file is not None and file not in K.FILE_SOURCES:
        raise ReadInvalid(f"file must be one of {list(K.FILE_SOURCES)}")
    tags: dict[str, tuple[str, ...]] = {}
    for axis, terms in K.TAG_AXES.items():
        asked = tuple(params.get(axis, ()))
        unknown_terms = sorted(set(asked) - set(terms))
        if unknown_terms:
            raise ReadInvalid(f"{axis} terms not in the vocabulary: {unknown_terms}")
        tags[axis] = asked
    q = _single(params, "q")
    if q is not None:
        if len(q) > K.MAX_QUERY_CHARS:
            raise ReadInvalid(f"q is at most {K.MAX_QUERY_CHARS} characters")
        q = q.strip()
        if not q:
            raise ReadInvalid("q is empty")
    sort = _single(params, "sort")
    sort = "move_id" if sort is None else sort
    if sort not in K.SORT_KEYS:
        raise ReadInvalid(f"sort must be one of {list(K.SORT_KEYS)}")
    order = _single(params, "order")
    order = "asc" if order is None else order
    if order not in K.SORT_ORDERS:
        raise ReadInvalid(f"order must be one of {list(K.SORT_ORDERS)}")
    return DetailQuery(target=_single(params, "target"), file=file, tags=tags, variant=_single(params, "variant"),
                       q=q, sort=sort, order=order,
                       limit=_integer(_single(params, "limit"), "limit", RECORD_LIMIT_DEFAULT, K.PAGE_LIMIT_MIN,
                                      RECORD_LIMIT_MAX),
                       offset=_integer(_single(params, "offset"), "offset", 0, 0, None))


# ------------------------------------------------------------------------------------------- filter, sort, facets

def _bibliography_entry(books: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any] | None:
    entry = books.get(record["source"]["pmid"])
    return entry if isinstance(entry, dict) else None


def search_texts(record: Mapping[str, Any], books: Mapping[str, Any]) -> list[str]:
    """The string values of exactly ``SEARCH_FIELDS`` for one record copy (null or non-string values are skipped)."""
    observation, target = record["observation"], record["target"]
    change = record.get("change")
    change = change if isinstance(change, dict) else {}
    tradeoffs = [t for t in record["tradeoffs"] if isinstance(t, dict)]
    entry = _bibliography_entry(books, record)
    values = [record["move_id"], record["source"]["pmid"], target["name_as_written"], target["variant"],
              observation["text"], observation["quote"], change.get("description"), change.get("from_compound"),
              change.get("to_compound"), *(t.get("text") for t in tradeoffs), *(t.get("quote") for t in tradeoffs),
              entry.get("title") if entry is not None else None]
    return [value for value in values if type(value) is str]


def _matches(item: Mapping[str, Any], query: DetailQuery, books: Mapping[str, Any]) -> bool:
    record = item["record"]
    if query.file is not None and item["file"] != query.file:
        return False
    for axis, asked in query.tags.items():
        if asked and not set(asked) & set(record["tags"][axis]):
            return False
    if query.variant is not None and record["target"]["variant"] != query.variant:
        return False
    if query.q is not None:
        needle = query.q.casefold()
        return any(needle in text.casefold() for text in search_texts(record, books))
    return True


def _as_int(text: Any) -> int | None:
    if type(text) is not str or not _DIGITS.fullmatch(text):
        return None
    try:
        return int(text)
    except ValueError:   # beyond the interpreter's digit limit: not readable as an integer
        return None


def _sort_value(item: Mapping[str, Any], sort: str, books: Mapping[str, Any]) -> Any:
    record = item["record"]
    if sort == "move_id":
        return kp.move_key(record["move_id"])
    if sort == "pmid":
        return _as_int(record["source"]["pmid"])
    if sort == "year":
        entry = _bibliography_entry(books, record)
        return _as_int(entry.get("year")) if entry is not None else None
    if sort == "variant":
        return record["target"]["variant"]
    return item["file"]


def ordered(items: Sequence[Mapping[str, Any]], sort: str, order: str,
            books: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Sorted by ``sort``; ties keep the record order (``move_key`` ascending); a missing value is always last."""
    base = sorted(items, key=lambda item: kp.move_key(item["record"]["move_id"]))
    valued = [(item, _sort_value(item, sort, books)) for item in base]
    present = [pair for pair in valued if pair[1] is not None]
    present.sort(key=lambda pair: pair[1], reverse=order == "desc")   # stable: ties stay in record order
    return [item for item, _value in present] + [item for item, value in valued if value is None]


def _tally(values: Sequence[str]) -> list[dict[str, Any]]:
    counter = Counter(values)
    return [{"value": value, "count": counter[value]} for value in sorted(counter)]


def facets(items: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """``{file, site, goal, tactic, variant}`` value counts over ``items`` (a record counts once per distinct term)."""
    records = [item["record"] for item in items]
    return {"file": _tally([item["file"] for item in items]),
            **{axis: _tally([term for record in records for term in set(record["tags"][axis])])
               for axis in K.TAG_AXES},
            "variant": _tally([record["target"]["variant"] for record in records])}


def detail(run: Any, handle: str, query: DetailQuery) -> dict[str, Any]:
    content = validated(run, handle)
    targets = content["targets"]
    if query.target is None:
        chosen = targets[0] if targets else None
    else:
        chosen = next((target for target in targets if target["accession"] == query.target), None)
        if chosen is None:
            raise ReadInvalid("target must be one of this result's target accessions")
    books = content["bibliography"]
    if chosen is None:
        page = {"target": None, "total": None, "filtered_total": None, "offset": query.offset, "limit": query.limit}
        found_facets, records = None, []
    else:
        items = chosen["records"]
        kept = ordered([item for item in items if _matches(item, query, books)], query.sort, query.order, books)
        records = kept[query.offset:query.offset + query.limit]
        page = {"target": chosen["accession"], "total": len(items), "filtered_total": len(kept),
                "offset": query.offset, "limit": query.limit}
        found_facets = facets(items)
    pmids = sorted({item["record"]["source"]["pmid"] for item in records})
    active = _active_set_hash()
    return {"schema": K.DETAIL_SCHEMA, "handle": handle, **{key: content[key] for key in _STORED_KEYS},
            "targets_overview": [{key: target[key] for key in _OVERVIEW_KEYS} for target in targets],
            "page": page, "facets": found_facets, "records": records,
            "bibliography": {pmid: books[pmid] for pmid in pmids},
            "active_set": {"set_hash": active,
                           "same": active is not None and active == content["precedent_set"]["set_hash"]}}
