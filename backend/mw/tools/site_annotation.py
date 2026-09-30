"""M16 tool ``annotate_reference_sites``: validated pre-check + ``reference_site_annotation@1`` result.

The registry pre-check hook validates both handles on every call path before the generic argument check (which would
refuse a null ``contacts`` and classify a wrong handle kind as ``precondition``): unknown fields, a wrong kind or a
handle of another run -> ``input_invalid``; contacts of another structure -> ``structure_mismatch``; two mapped rows
for one site -> ``duplicate_site_residue``. The hook returns no bound, so the call key is the plain normalized args.
The tool reads only the two objects and the structure's residue list; never the reference folder or the network.
"""
from __future__ import annotations

from typing import Any

from .. import site_annotation as sa
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolRegistry
from .structural import structure_residues

TOOL = "annotate_reference_sites"
MAP_KIND = ("residue_numbering_map", "residue_numbering_map@1")
CONTACTS_KIND = ("interaction_set", "interaction_set@1")
_ARG_KEYS = frozenset({"numbering_map", "contacts"})


def _invalid(message: str, reason_code: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code})


def _object(store: Any, handle: Any, expected: tuple[str, str], reason_code: str) -> dict[str, Any]:
    if type(handle) is not str:
        raise _invalid(f"expected a {expected[0]} handle of this run", reason_code)
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("unknown handle (not an object of this run)", reason_code) from None
    if (meta["kind"], meta["schema"]) != expected:
        raise _invalid(f"expected a {expected[0]} handle, got '{meta['kind']}'", reason_code)
    return store.load(handle)


def precheck(store: Any, args: dict[str, Any], bound: Any = None) -> tuple[dict[str, Any], None]:
    """Registry pre-check hook: ``(normalized args, None)`` or ``ToolFailure``; never runs the implementation."""
    unknown = set(args) - _ARG_KEYS
    if unknown:
        raise _invalid(f"unknown parameters: {sorted(unknown)}", "unknown_field")
    map_content = _object(store, args.get("numbering_map"), MAP_KIND, "numbering_map_invalid")
    contacts = args.get("contacts")
    if contacts is not None:
        contacts_content = _object(store, contacts, CONTACTS_KIND, "contacts_invalid")
        if contacts_content["structure"] != map_content["structure"]["handle"]:
            raise _invalid("contacts were computed on another structure than the numbering map",
                           "structure_mismatch")
    try:
        sa.site_groups(map_content)
    except sa.AnnotationInvalid as exc:
        raise _invalid(exc.message, exc.reason_code) from exc
    return {"numbering_map": args["numbering_map"], "contacts": contacts}, None


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def annotate_reference_sites(ctx, numbering_map: str, contacts: str | None = None) -> Handle:
        map_content = ctx.store.load(numbering_map)
        contacts_content = ctx.store.load(contacts) if contacts is not None else None
        residues = structure_residues(ctx.store, map_content["structure"]["handle"])["residues"]
        try:
            content = sa.build_annotation(numbering_map, map_content, residues, contacts, contacts_content)
        except sa.AnnotationInvalid as exc:
            raise _invalid(exc.message, exc.reason_code) from exc
        summary = {"numbering_map": numbering_map, "contacts": contacts, "structure": content["structure"]["handle"],
                   "set_hash": content["snapshot_set_hash"], **sa.counts(content)}
        return ctx.store.put(sa.KIND, sa.SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=content["null_result"])
