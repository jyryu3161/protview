"""M29 structure repair: the four objects, the read-only overlay, publication and validated reads (spec 3.1, 3.4,
3.5, 4.5).

No PDBFixer, no OpenMM import, no network, no process module. Nothing here runs an engine; ``validated_result`` reads
only this run's stored objects and events (events-only recovery works without the original input, a network or an
engine; the core's validator reads the installed Amber14 template XML as a file).

Objects of one repair, made in this order (handles are content hashes, so the record never names the structure or
the manifest and there is no cycle):

1. repaired coordinates ``prepared_coordinates@1`` (mmCIF bytes from ``structure_repair.build_repaired``);
2. the record ``structure_repair@1``;
3. the manifest ``preparation_manifest@1``: the source manifest with ``missing_residues`` =
   ``modeled_internal_gaps`` only when gaps were filled, plus ``repair`` = ``{record, source}`` (the only mark);
4. the repaired structure ``prepared_structure@1`` ``{coordinates, manifest, model_index, model_number}``.

``pending()`` computes the four objects and handles without storing anything; ``Overlay`` is the read-only view
(the store plus these pending objects, ``meta``/``load`` only) the M7 preflight runs on before publication;
``store()`` puts the four objects in that order and appends ``structure_repair_published`` (``job_id``,
``attempt_id`` and the four handles). Nothing calls ``store()`` before every check passed.

``validated_result(run, handle)`` re-validates a stored record on every read: its single completed publication (the
published event, the job's done terminal with output handles ``[record, prepared_structure]``, its result candidate,
cleanup and reservation), the job selection, the four objects' kinds and contents (manifest and structure rebuilt
from the source), the coordinates bytes against ``result.coordinates_sha256`` and the core validator
``structure_repair.validated_repair`` (the record rebuilt from the source and the stored bytes). Any failure raises
``RepairEvidenceError``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from . import structure_repair as sr
from . import structure_repair_constants as K
from .core.errors import ToolFailure
from .core.handles import HANDLE_PREFIX, canonical_json, object_sha
from .structure_origin import is_repaired

MAX_STRUCTURE_BYTES = 64_000_000   # stored repaired coordinates read bound (the record itself is MAX_RECORD_BYTES)
SELECTION_SCHEMA = "structure_repair_selection@1"


class RepairEvidenceError(ValueError):
    """A stored repair does not validate against its inputs and publication."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise RepairEvidenceError(message)


def _handle(run_id: str, kind: str, schema: str, raw: bytes) -> str:
    return f"{HANDLE_PREFIX}{run_id}/{kind}/{object_sha(kind, schema, raw)}"


def repaired_manifest(source_manifest: dict[str, Any], record_handle: str, source_handle: str,
                      record: dict[str, Any]) -> dict[str, Any]:
    """The source manifest, ``missing_residues`` set only when gaps were filled, plus the ``repair`` mark."""
    filled = "internal_gap_filled" in record["classes_applied"]
    return {**source_manifest,
            "missing_residues": K.MISSING_RESIDUES_FILLED if filled else source_manifest["missing_residues"],
            K.MANIFEST_REPAIR_KEY: {"record": record_handle, "source": source_handle}}


def repaired_structure(source_prepared: dict[str, Any], coordinates: str, manifest: str) -> dict[str, Any]:
    return {"coordinates": coordinates, "manifest": manifest, "model_index": source_prepared["model_index"],
            "model_number": source_prepared["model_number"]}


@dataclass(frozen=True)
class Pending:
    """The four objects of one repair, not stored: handle -> (kind, schema, fmt, content, summary)."""

    objects: dict[str, tuple[str, str, str, Any, dict[str, Any]]]
    coordinates: str
    record: str
    manifest: str
    structure: str

    def handles(self) -> dict[str, str]:
        return {"record": self.record, "prepared_structure": self.structure, "coordinates": self.coordinates,
                "manifest": self.manifest}


def pending(run: Any, inputs: sr.RepairInputs, raw: bytes, record: dict[str, Any]) -> Pending:
    """The four objects and their handles, in the order they will be stored; nothing is written."""
    source = inputs.prepared_structure
    prepared = run.store.load(source)
    manifest = run.store.load(prepared["manifest"])
    coordinates = _handle(run.run_id, K.COORDINATES_KIND, K.COORDINATES_SCHEMA, raw)
    if coordinates != record["result"]["coordinates"]:
        raise ValueError("repaired coordinates handle differs from the record")
    record_handle = _handle(run.run_id, K.KIND, K.SCHEMA, canonical_json(record))
    manifest_content = repaired_manifest(manifest, record_handle, source, record)
    manifest_handle = _handle(run.run_id, K.MANIFEST_KIND, K.MANIFEST_SCHEMA, canonical_json(manifest_content))
    structure_content = repaired_structure(prepared, coordinates, manifest_handle)
    structure_handle = _handle(run.run_id, K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, canonical_json(structure_content))
    counts = record["counts"]
    objects = {
        coordinates: (K.COORDINATES_KIND, K.COORDINATES_SCHEMA, K.COORDINATES_FMT, raw, {}),
        record_handle: (K.KIND, K.SCHEMA, "json", record,
                        {"prepared_structure": source, "added_residues": counts["added_residues"],
                         "added_atoms": counts["added_atoms"]}),
        manifest_handle: (K.MANIFEST_KIND, K.MANIFEST_SCHEMA, "json", manifest_content, {}),
        # the prepare_structure summary shape (coordinates, manifest, model_index and the source removal counts)
        structure_handle: (K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, "json", structure_content,
                           {"coordinates": coordinates, "manifest": manifest_handle,
                            "model_index": prepared["model_index"], **manifest["removed"]}),
    }
    return Pending(objects=objects, coordinates=coordinates, record=record_handle, manifest=manifest_handle,
                   structure=structure_handle)


class Overlay:
    """Read-only view: the run's store plus the pending objects (``meta`` and ``load`` only, no write method)."""

    def __init__(self, store: Any, objects: Pending) -> None:
        self._store = store
        self._pending = objects.objects
        self.run_id = store.run_id
        self.events = store.events

    def meta(self, handle: str) -> dict[str, Any]:
        found = self._pending.get(handle)
        if found is None:
            return self._store.meta(handle)
        kind, schema, fmt, content, summary = found
        raw = content if isinstance(content, bytes) else canonical_json(content)
        return {"handle": handle, "kind": kind, "schema": schema, "path": None, "fmt": fmt, "size": len(raw),
                "produced_by": None, "summary": summary, "null_result": False}

    def load(self, handle: str) -> Any:
        found = self._pending.get(handle)
        if found is None:
            return self._store.load(handle)
        content = found[3]
        return content if isinstance(content, bytes) else json.loads(canonical_json(content))


def store(run: Any, objects: Pending, job_id: str, attempt_id: str) -> list[str]:
    """Put the four objects in order (coordinates, record, manifest, structure), then the published event."""
    for handle in (objects.coordinates, objects.record, objects.manifest, objects.structure):
        kind, schema, fmt, content, summary = objects.objects[handle]
        stored = run.store.put(kind, schema, content, fmt=fmt, produced_by=attempt_id, summary=summary)
        if stored.handle != handle:
            raise ValueError("stored repair object handle differs from the pending one")
    run.events.append(K.EVENT_PUBLISHED, job_id=job_id, attempt_id=attempt_id, **objects.handles())
    return [objects.record, objects.structure]


# ----------------------------------------------------------------- validated reads (never run anything)
def _meta(run: Any, handle: Any) -> dict[str, Any] | None:
    try:
        return run.store.meta(handle)
    except (KeyError, ValueError, TypeError):
        return None


def producer(run: Any, handle: str) -> dict[str, Any]:
    """The earliest ``structure_repair_published`` event of ``handle`` whose job attempt completed (else an evidence
    error): ``{job, event, published_seq}``."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    for published in events:
        if published["type"] != K.EVENT_PUBLISHED or published.get("record") != handle:
            continue
        job = jobs.get(published.get("job_id"))
        attempt = published.get("attempt_id")
        if job is None or job.get("protocol_id") != K.PROTOCOL or job.get("tool_id") != K.TOOL:
            continue
        outputs = [handle, published.get("prepared_structure")]
        terminal = [event for event in events if event["type"] == "job_terminal" and
                    event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                    event.get("status") == "done" and event.get("output_handles") == outputs]
        candidates = [event for event in events if event["type"] == "job_result_candidate" and
                      event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                      event.get("output_handles") == outputs]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("attempt_id") == attempt and event.get("group_empty") is True]
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == K.TOOL]
        created = {event.get("handle"): event["seq"] for event in events if event["type"] == "object_created"}
        if (len(terminal) == 1 and len(candidates) == 1 and len(cleaned) == 1 and len(reserved) == 1 and
                all(published.get(key) in created and created[published[key]] < published["seq"]
                    for key in K.EVENT_HANDLE_KEYS) and
                reserved[0]["seq"] < cleaned[0]["seq"] < published["seq"] < candidates[0]["seq"] <
                terminal[0]["seq"]):
            return {"job": job, "event": published, "published_seq": published["seq"]}
    raise RepairEvidenceError("record has no completed pdbfixer_repair_v1 publication")


def _object(run: Any, handle: Any, kind: str, schema: str, fmt: str) -> None:
    meta = _meta(run, handle)
    _require(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) == (kind, schema, fmt),
             f"expected a {schema} of this run")


def validated_result(run: Any, handle: Any) -> dict[str, Any]:
    """The stored ``structure_repair@1`` of this run, re-validated on every read (no engine, no event):
    ``{record, handle, prepared_structure, coordinates, manifest, source_structure, published_seq, job_id}``."""
    try:
        _require(type(handle) is str, "handle must be a string")
        _object(run, handle, K.KIND, K.SCHEMA, "json")
        record = run.store.load_bounded_json(handle, K.MAX_RECORD_BYTES)
        _require(isinstance(record, dict) and set(record) == set(K.RECORD_KEYS), "record keys")
        published = producer(run, handle)
        job, event = published["job"], published["event"]
        selected = job["selected"]
        source = record["source"]["prepared_structure"]
        _require(selected.get("schema") == SELECTION_SCHEMA and
                 selected["arguments"] == {"structure": source, "repair_policy": K.REPAIR_POLICY} and
                 job["parameters"] == selected["arguments"] and
                 selected["structure"] == {"handle": source, "model_number": record["source"]["model_number"]},
                 "record differs from its job")
        coordinates, manifest, structure = event["coordinates"], event["manifest"], event["prepared_structure"]
        _object(run, coordinates, K.COORDINATES_KIND, K.COORDINATES_SCHEMA, K.COORDINATES_FMT)
        _object(run, manifest, K.MANIFEST_KIND, K.MANIFEST_SCHEMA, "json")
        _object(run, structure, K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, "json")
        _object(run, source, K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, "json")
        _require(not is_repaired(run.store, source), "the source is a repaired structure")
        raw = run.store.load_bounded_bytes(coordinates, MAX_STRUCTURE_BYTES)
        _require(record["result"] == {"coordinates": coordinates,
                                      "coordinates_sha256": hashlib.sha256(raw).hexdigest()}, "coordinates bytes")
        source_prepared = run.store.load(source)
        expected_manifest = repaired_manifest(run.store.load(source_prepared["manifest"]), handle, source, record)
        _require(canonical_json(run.store.load(manifest)) == canonical_json(expected_manifest), "manifest content")
        _require(canonical_json(run.store.load(structure)) ==
                 canonical_json(repaired_structure(source_prepared, coordinates, manifest)), "structure content")
        sr.validated_repair(sr.load_inputs(run.store, source), raw, record)
        return {"record": record, "handle": handle, "prepared_structure": structure, "coordinates": coordinates,
                "manifest": manifest, "source_structure": source, "published_seq": published["published_seq"],
                "job_id": job["job_id"]}
    except RepairEvidenceError:
        raise
    except (ToolFailure, KeyError, TypeError, ValueError, IndexError, AttributeError, OSError, RecursionError) as exc:
        raise RepairEvidenceError("structure repair evidence is invalid") from exc


def structure_bytes(run: Any, handle: Any) -> bytes:
    """The stored repaired mmCIF bytes of a validated record (hash-checked against the record)."""
    result = validated_result(run, handle)
    try:
        raw = run.store.load_bounded_bytes(result["coordinates"], MAX_STRUCTURE_BYTES)
    except (KeyError, ValueError, OSError) as exc:
        raise RepairEvidenceError("repaired coordinates do not load") from exc
    _require(hashlib.sha256(raw).hexdigest() == result["record"]["result"]["coordinates_sha256"], "coordinates bytes")
    return raw
