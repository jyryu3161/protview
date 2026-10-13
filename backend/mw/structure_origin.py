"""M29 structure origin: is a structure handle a repaired structure, and the default refusal (spec 3.1, 5.2, 6.1).

Pure helpers over the run's object store (``meta`` / ``load`` only; nothing is written). The manifest key ``repair``
of ``preparation_manifest@1`` is the only mark of a repaired structure, so every consumer decides with these.
Imports only the M29 constants and ``core`` (no gemmi, numpy, engine, network, process, job or send module), so read
and report modules with import limits may use it.

Public API:

``is_repaired(store, handle) -> bool``
    True when ``handle`` is a ``prepared_structure@1`` of this store whose manifest has the ``repair`` key (any
    value). False for any other object, an unknown handle or another run's handle.
``structure_origin(store, handle) -> dict | None``
    None unless ``is_repaired``; else ``{"repair_record", "repaired_structure", "source_structure", "counts"}``: the
    ``structure_repair@1`` handle, ``handle`` itself, the original prepared structure (``repair.source``) and the
    record's ``counts`` dict. Checks the link's shape (``repair`` = {record, source} handles of the right kinds, and
    the record's ``source.prepared_structure`` = ``repair.source``), else ``ToolFailure(input_invalid,
    reason_code repair_record_mismatch)``. It does not re-validate the record against the structures (the job /
    read modules' ``validated_result`` does that).
``reject_if_repaired(store, handle) -> None``
    Raises ``ToolFailure(input_invalid, "보완 구조는 모델링 경로에서만 쓴다", detail={"reason_code":
    "repaired_structure_not_accepted"})`` for a repaired structure; returns None otherwise (the consumer keeps its
    own checks for anything else).
"""
from __future__ import annotations

from typing import Any

from . import structure_repair_constants as K
from .core.errors import FailureClass, ToolFailure


def _manifest(store: Any, handle: Any) -> dict[str, Any] | None:
    if not isinstance(handle, str):
        return None
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError):
        return None
    if (meta["kind"], meta["schema"]) != (K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA):
        return None
    prepared = store.load(handle)
    manifest = store.load(prepared["manifest"]) if isinstance(prepared, dict) and "manifest" in prepared else None
    return manifest if isinstance(manifest, dict) else None


def is_repaired(store: Any, handle: Any) -> bool:
    manifest = _manifest(store, handle)
    return manifest is not None and K.MANIFEST_REPAIR_KEY in manifest


def _kind(store: Any, handle: Any, kind: str, schema: str) -> bool:
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError):
        return False
    return (meta["kind"], meta["schema"]) == (kind, schema)


def structure_origin(store: Any, handle: Any) -> dict[str, Any] | None:
    manifest = _manifest(store, handle)
    if manifest is None or K.MANIFEST_REPAIR_KEY not in manifest:
        return None
    link = manifest[K.MANIFEST_REPAIR_KEY]
    ok = (isinstance(link, dict) and tuple(sorted(link)) == tuple(sorted(K.MANIFEST_REPAIR_KEYS))
          and all(isinstance(link[key], str) for key in K.MANIFEST_REPAIR_KEYS)
          and _kind(store, link["record"], K.KIND, K.SCHEMA)
          and _kind(store, link["source"], K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA) and link["source"] != handle)
    record = store.load(link["record"]) if ok else None
    if (not isinstance(record, dict) or not isinstance(record.get("source"), dict)
            or record["source"].get("prepared_structure") != link["source"] or not isinstance(record.get("counts"), dict)):
        raise ToolFailure(FailureClass.input_invalid, "repaired structure link is malformed",
                          detail={"reason_code": "repair_record_mismatch"})
    return {"repair_record": link["record"], "repaired_structure": handle, "source_structure": link["source"],
            "counts": record["counts"]}


def reject_if_repaired(store: Any, handle: Any) -> None:
    if is_repaired(store, handle):
        raise ToolFailure(FailureClass.input_invalid, K.REPAIRED_NOT_ACCEPTED_MESSAGE,
                          detail={"reason_code": K.REPAIRED_NOT_ACCEPTED})
