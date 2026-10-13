"""M29 downstream reads: the ``structure_origin`` read field and the JEV warning JW1 (spec .dryforge/spec.md 6.1, 6.2,
6.4).

Read-only helpers over one run's stored objects and events (``meta`` / ``load`` / ``events.read()`` only): nothing is
written and no event, job, tool or engine runs (the record check reads the installed Amber14 template XML as a file).
A result whose structure is a repaired structure (a ``prepared_structure@1`` whose manifest has ``repair``, the only
mark) carries in its READ response, never in a stored object, event or JEV body::

    "structure_origin": {"repair_record": <structure_repair@1 handle>, "repaired_structure": <that structure>,
                         "source_structure": <the original prepared structure>, "counts": <the record's counts>,
                         "statements": [{"id": "SO1", "text": SO1}]}

once the record passed the check the downstream reports make (``structure_origin_reports.origin``, the same steps,
here ``mutation_handoff.checked_origin``, which the M20 admission also uses): the link (``structure_origin``), then
``structure_repair_bundle.validated_result`` (its single completed
``pdbfixer_repair_v1`` publication, the four objects and the record re-derived from the original prepared structure
and the stored repaired bytes), which must have published exactly this structure from the link's source. A read and
a report therefore never disagree about a repaired structure: one that fails either is invalid in both, an
unpublished repaired structure included (which the M20 admission refuses too). A result on any other structure gets
no key, so its response bytes are what they were.

Public API:

``KEY`` / ``WARNING_KEY``
    The response keys ``structure_origin`` and ``repair_warning``.
``field(origin) -> dict``
    The field of a ``structure_origin.structure_origin`` dict (SO1 verbatim from ``structure_repair_constants``).
``Origins(run)``
    One read's resolver over ``run`` (a run or a one-log-read view: ``store`` and ``events.read()``; memo per
    structure, candidate set and model; a structure that does not verify stays invalid for the read). Each method
    returns the field or None:
    ``of_structure(handle)``; ``of_candidate_set(handle)`` (an M20 ``mutation_candidate_set@1``: its
    ``structure.handle``); ``of_model(handle)`` (an M21 ``mutation_model@1`` or an M23 ``mutation_set_model@1``: its
    ``structure.handle``, which the model's own validation keeps equal to its candidate set's, and for a set model
    its sequence GA's candidate set's); ``of_receptor_source(source)`` (an M18 ``inputs.receptor.source``: None for an
    imported receptor, else its model). ``OriginInvalid`` when the link, the record or a stored object on the way does
    not validate (callers map it to their evidence error: a list row ``valid: false`` with null fields, a detail 422
    ``method_evidence_invalid``). A ``ToolFailure`` of class ``precondition`` (``openmm_unavailable``: the installed
    template the check reads) is raised as it is: an environment failure, never invalid evidence (spec 4.6).
``warning(store, structure) -> dict | None``
    ``{"id": "JW1", "text": JW1}`` for a repaired structure by its mark alone (``is_repaired``), else None. Never raises
    (the JEV approval answer, given after the send whatever the record check says).

Imports no network, engine, process, job or send module (the JEV and loop modules keep their import limits: the
response layer calls this module, they do not).
"""
from __future__ import annotations

from typing import Any

from . import mutation_handoff
from . import structure_repair_constants as K
from .core.errors import FailureClass, ToolFailure
from .structure_origin import is_repaired

KEY = "structure_origin"
WARNING_KEY = "repair_warning"
SET_TYPE = ("mutation_candidate_set", "mutation_candidate_set@1")
MODEL_TYPES = (("mutation_model", "mutation_model@1"), ("mutation_set_model", "mutation_set_model@1"))
_BROKEN = (KeyError, TypeError, ValueError, IndexError, AttributeError, OSError)


class OriginInvalid(Exception):
    """A repaired structure's link or record, or a stored object on the way to it, does not validate."""


def field(origin: dict[str, Any]) -> dict[str, Any]:
    return {"repair_record": origin["repair_record"], "repaired_structure": origin["repaired_structure"],
            "source_structure": origin["source_structure"], "counts": dict(origin["counts"]),
            "statements": [{"id": "SO1", "text": K.SO1}]}


def warning(store: Any, structure: Any) -> dict[str, str] | None:
    try:
        return {"id": "JW1", "text": K.JW1} if is_repaired(store, structure) else None
    except _BROKEN:
        return None


def _verified(run: Any, structure: Any) -> dict[str, Any] | None:
    try:
        found = mutation_handoff.checked_origin(run, structure)   # the M20 admission's and the reports' steps
    except ToolFailure as exc:
        if exc.cls is FailureClass.precondition:
            raise
        raise OriginInvalid("the repaired structure does not validate") from exc
    except _BROKEN as exc:
        raise OriginInvalid("the repaired structure does not validate") from exc
    return None if found is None else field({**found, "counts": found["record"]["counts"]})


class Origins:
    """The ``structure_origin`` field of the results of one read (see the module docstring)."""

    def __init__(self, run: Any) -> None:
        self.run, self.store = run, run.store
        self._structures: dict[Any, dict[str, Any] | None | OriginInvalid] = {}
        self._handles: dict[Any, Any] = {}

    def of_structure(self, structure: Any) -> dict[str, Any] | None:
        if structure not in self._structures:
            try:
                self._structures[structure] = _verified(self.run, structure)
            except OriginInvalid as exc:
                self._structures[structure] = exc
        found = self._structures[structure]
        if isinstance(found, OriginInvalid):
            raise OriginInvalid(str(found))
        return found

    def _structure_of(self, handle: Any, types: tuple[tuple[str, str], ...]) -> Any:
        if handle not in self._handles:
            try:
                meta = self.store.meta(handle)
                if (meta["kind"], meta["schema"]) not in types:
                    raise OriginInvalid("unexpected object on the way to the structure")
                self._handles[handle] = self.store.load(handle)["structure"]["handle"]
            except _BROKEN as exc:
                raise OriginInvalid("the object on the way to the structure does not read") from exc
        return self._handles[handle]

    def of_candidate_set(self, handle: Any) -> dict[str, Any] | None:
        return self.of_structure(self._structure_of(handle, (SET_TYPE,)))

    def of_model(self, handle: Any) -> dict[str, Any] | None:
        return self.of_structure(self._structure_of(handle, MODEL_TYPES))

    def of_receptor_source(self, source: Any) -> dict[str, Any] | None:
        if source is None:
            return None
        if not isinstance(source, dict) or source.get("kind") != "mutation_model":
            raise OriginInvalid("unexpected receptor source")
        return self.of_model(source.get("mutation_model"))
