"""M25 JEV design loop: pure send order, loop wire, body and response functions (spec .dryforge/spec.md 4.2-4.5, 5.2).

Imports the standard library, ``.jev_loop_constants`` and the M24 modules ``.jev_constants`` / ``.jev_projection``
only (never the send, gate or loop-record modules). Nothing here reads the object store, an event log, a file, the
network or a credential: callers pass stored object contents (dicts), the loop-record candidate rows and, for
mutation wires, the parsed prepared structure (a ``gemmi.Structure``, as ``tools.structural._parse`` returns it).

The loop wire is the M24 wire re-ordered and extended: the M24 builders (``build_ligand_wire`` /
``build_mutation_wire``, unchanged) make every candidate / parent / position field from the allow lists; this module
only re-orders their output into the send order, renumbers the aliases, adds ``goal`` and ``computed`` and the loop
``schema`` / ``values_note``, and ``check_loop_wire`` runs the M24 ``check_wire`` on the M24-shaped core before the
loop rules. Bodies use the one M24 encoder ``jev_projection.canonical_ascii``; the reply parser is the M24
``parse_choice`` over the not-yet-computed aliases. Refusals are the M24 error classes (``JevProjectionError`` with a
closed ``reason_code``, ``WireFieldInvalid``, ``ProjectionInvalid``, ``PayloadTooLarge``).

Public API (T2-B / T3 / T4 / T5 / T6 use these signatures; all pure):

    order_key(ref, *, loop_seed, iteration, send_ordinal) -> str
        sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{ref}".encode("ascii")).hexdigest(); ref = a ligand candidate
        id ("c_" + 16 hex) or a mutation candidate index (int >= 0, sent through as its decimal string). ValueError
        for a bad ref or order parameter (loop_seed 0-2147483647, iteration 1-8, send_ordinal >= 0; ints, not bool).
    shuffled_refs(refs, *, loop_seed, iteration, send_ordinal) -> list
        ``refs`` in candidate-set (stored) order -> the send order (order_key ascending, ties by that stored order).
    computed_rows(goal, entries) -> list[dict]
        entries: [{alias, state, score_kcal_mol}] in wire order (pending ones are skipped) -> the wire ``computed``:
        explore [{alias}], exploit [{alias, state: scored | no_score, score_kcal_mol: stored value | None}].
    build_loop_ligand_wire(content, rows, *, goal, loop_seed, iteration, send_ordinal, inspection=None)
            -> (wire, selection)
    build_loop_mutation_wire(content, rows, structure, *, goal, loop_seed, iteration, send_ordinal)
            -> (wire, selection)
        content: the stored ligand_candidate_set@1 / mutation_candidate_set@1 content; rows: the pool's loop-record
        candidates, one {ref, state, score_kcal_mol} per pool candidate (other keys ignored; any row order;
        2-20 rows; ``score_kcal_mol`` a finite number exactly when ``state`` is scored); inspection: the M17
        ligand_inspection@1 content (parent fallback, as M24). ``unavailable`` rows are left out of the wire and the
        selection. selection: [{alias, ref, state}] in wire order. Refusals: ProjectionInvalid (malformed rows, goal or
        order parameters), too_few_candidates (< 2 pending), source_invalid (a pool ref not in the set, unreadable
        set), then the M24 structure_unavailable / wire_field_invalid.
    check_loop_wire(wire, kind) -> None                 WireFieldInvalid on any allow-list / value rule
    criteria_aliases(projection) -> list[str]           the pending aliases of projection["selection"], wire order
    list_position(criteria, alias) -> int               1-based place of ``alias`` in ``criteria`` (ValueError if absent);
                                                        list_size is len(criteria)
    loop_body_object(wire, kind, goal, criteria) -> dict   {"model", "state", "questions", "provider"}
    encode_loop_body(wire, kind, goal, criteria) -> bytes  jev_projection.canonical_ascii(loop_body_object(...))
    loop_projection_body(content) -> (body_object, body_bytes)   for a validated loop projection
    build_loop_projection_content(kind, source_handle, wire, selection, *, loop_id, loop_seed, iteration,
                                  send_ordinal, structure=None) -> dict
        jev_loop_projection@1 content (no time, no call id). WireFieldInvalid, then PayloadTooLarge (> 65,536 body
        bytes, nothing truncated), then ProjectionInvalid. structure: {handle, model_number} (mutation only).
    validated_loop_projection(content) -> content       ProjectionInvalid unless every spec 4.2 rule holds
    parse_loop_choice(data, projection) -> (answer | None, reason_code | None)
        The M24 ``parse_choice`` with the projection's criteria (not-yet-computed aliases) as the alias set: a computed
        alias as the choice or as a probability key is response_invalid. answer = {choice_alias, confidence | None,
        probabilities | None} as received; reasons are the M24 PARSE_REASONS. The HTTP status and the response size
        are checked by the gate before the parser, as for M24.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from itertools import pairwise
from typing import Any

from . import jev_constants as J
from . import jev_loop_constants as L
from . import jev_projection as P

_HANDLE_RE = r"obj://[A-Za-z0-9][A-Za-z0-9_-]{0,79}/%s/[0-9a-f]{64}"
_MAPPED_TO_SOURCE = ("selection_invalid", "candidate_unknown")   # M24 selection refusals of a recorded pool


# --- small predicates ------------------------------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _is_ref(value: Any, kind: str | None = None) -> bool:
    """A ligand candidate id (kind ligand), a mutation candidate index (kind mutation), or either (kind None)."""
    is_id = type(value) is str and J.CANDIDATE_ID_RE.fullmatch(value) is not None
    is_index = _is_int(value) and value >= 0
    if kind is None:
        return is_id or is_index
    return is_id if kind == "ligand" else is_index


def _order_params(loop_seed: Any, iteration: Any, send_ordinal: Any) -> None:
    if not (_is_int(loop_seed) and L.MIN_LOOP_SEED <= loop_seed <= L.MAX_LOOP_SEED):
        raise ValueError(f"loop_seed must be an integer {L.MIN_LOOP_SEED}-{L.MAX_LOOP_SEED}")
    if not (_is_int(iteration) and 1 <= iteration <= L.MAX_ITERATION_CAP):
        raise ValueError(f"iteration must be an integer 1-{L.MAX_ITERATION_CAP}")
    if not (_is_int(send_ordinal) and send_ordinal >= 0):
        raise ValueError("send_ordinal must be a non-negative integer")


# --- order (spec 4.3) ------------------------------------------------------------------------------------------------

def order_key(ref: Any, *, loop_seed: int, iteration: int, send_ordinal: int) -> str:
    _order_params(loop_seed, iteration, send_ordinal)
    if not _is_ref(ref):
        raise ValueError("ref must be a ligand candidate id or a non-negative mutation candidate index")
    text = ref if type(ref) is str else str(ref)
    return hashlib.sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{text}".encode("ascii")).hexdigest()


def shuffled_refs(refs: list[Any], *, loop_seed: int, iteration: int, send_ordinal: int) -> list[Any]:
    _order_params(loop_seed, iteration, send_ordinal)
    keyed = [(order_key(ref, loop_seed=loop_seed, iteration=iteration, send_ordinal=send_ordinal), stored, ref)
             for stored, ref in enumerate(refs)]
    return [ref for _, _, ref in sorted(keyed, key=lambda item: (item[0], item[1]))]


def list_position(criteria: list[str], alias: Any) -> int:
    if type(alias) is not str or alias not in criteria:
        raise ValueError("the alias is not one of the criteria (not-yet-computed) aliases")
    return criteria.index(alias) + 1


def criteria_aliases(projection: Any) -> list[str]:
    try:
        selection = projection["selection"]
        if type(selection) is not list:
            raise TypeError("selection")
        criteria = []
        for item in selection:
            if type(item["alias"]) is not str or type(item["state"]) is not str:
                raise TypeError("selection item")
            if item["state"] == "pending":
                criteria.append(item["alias"])
    except (KeyError, TypeError) as exc:
        raise P.ProjectionInvalid("the projection selection is not readable") from exc
    return criteria


def computed_rows(goal: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for entry in entries:
        if entry["state"] == "pending":
            continue
        if goal == "explore":
            rows.append({"alias": entry["alias"]})
        else:
            state = L.COMPUTED_STATE_FOR[entry["state"]]
            rows.append({"alias": entry["alias"], "state": state,
                         "score_kcal_mol": entry["score_kcal_mol"] if state == "scored" else None})
    return rows


# --- loop wires (spec 4.4) -------------------------------------------------------------------------------------------

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise P.ProjectionInvalid(message)


def _pool_rows(kind: str, rows: Any, goal: Any, order: tuple[Any, Any, Any]) -> dict[Any, dict[str, Any]]:
    """Checks the builder inputs; returns ref -> {state, score_kcal_mol} for the pool."""
    _require(type(goal) is str and goal in L.GOALS, "goal must be explore or exploit")
    try:
        _order_params(*order)
    except ValueError as exc:
        raise P.ProjectionInvalid(str(exc)) from exc
    _require(type(rows) is list and L.MIN_POOL <= len(rows) <= L.MAX_POOL,
             f"the pool rows must be a list of {L.MIN_POOL}-{L.MAX_POOL} candidates")
    pool: dict[Any, dict[str, Any]] = {}
    for row in rows:
        _require(type(row) is dict and {"ref", "state", "score_kcal_mol"} <= set(row), "pool row fields")
        ref, state, score = row["ref"], row["state"], row["score_kcal_mol"]
        _require(_is_ref(ref, kind), "pool ref type")
        _require(ref not in pool, "pool refs repeat")
        _require(type(state) is str and state in L.CANDIDATE_STATES, "candidate state")
        _require(_is_number(score) if state == "scored" else score is None,
                 "a scored candidate has its stored finite score; any other candidate has none")
        pool[ref] = {"state": state, "score_kcal_mol": score}
    pending = sum(entry["state"] == "pending" for entry in pool.values())
    if pending < L.MIN_PENDING_TO_SEND:
        raise P.JevProjectionError("too_few_candidates", "fewer than two candidates are not yet computed",
                                   pending=pending)
    return pool


def _m24_wire(builder: Any, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return builder(*args, **kwargs)
    except P.JevProjectionError as exc:
        if exc.reason_code in _MAPPED_TO_SOURCE:   # a recorded pool ref the stored set does not hold
            raise P.JevProjectionError("source_invalid", "the candidate set does not hold the pool candidates") \
                from exc
        raise


def _ordered(kind: str, pool: dict[Any, dict[str, Any]], stored_refs: list[Any], order: tuple[Any, Any, Any],
             ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The selection in send order (aliases renumbered) and its entries with the stored scores."""
    loop_seed, iteration, send_ordinal = order
    refs = shuffled_refs(stored_refs, loop_seed=loop_seed, iteration=iteration, send_ordinal=send_ordinal)
    prefix = J.ALIAS_PREFIXES[kind]
    selection = [{"alias": f"{prefix}{number:02d}", "ref": ref, "state": pool[ref]["state"]}
                 for number, ref in enumerate(refs, 1)]
    entries = [{**item, "score_kcal_mol": pool[item["ref"]]["score_kcal_mol"]} for item in selection]
    return selection, entries


def build_loop_ligand_wire(content: dict[str, Any], rows: Any, *, goal: str, loop_seed: int, iteration: int,
                           send_ordinal: int, inspection: dict[str, Any] | None = None,
                           ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    order = (loop_seed, iteration, send_ordinal)
    pool = _pool_rows("ligand", rows, goal, order)
    kept = [ref for ref, entry in pool.items() if entry["state"] != "unavailable"]
    base, base_selection = _m24_wire(P.build_ligand_wire, content, kept, inspection=inspection)
    by_ref = {item["candidate_id"]: candidate
              for item, candidate in zip(base_selection, base["candidates"], strict=True)}
    selection, entries = _ordered("ligand", pool, [item["candidate_id"] for item in base_selection], order)
    candidates = [{"alias": item["alias"], **{name: by_ref[item["ref"]][name]
                                              for name in J.ALLOWED_LIGAND_CANDIDATE if name != "alias"}}
                  for item in selection]
    wire = {"schema": L.WIRE_SCHEMAS["ligand"], "task": L.WIRE_TASK, "goal": goal, "parent": base["parent"],
            "property_methods": base["property_methods"], "candidates": candidates,
            "computed": computed_rows(goal, entries), "values_note": L.VALUES_NOTES[("ligand", goal)]}
    check_loop_wire(wire, "ligand")
    return wire, selection


def build_loop_mutation_wire(content: dict[str, Any], rows: Any, structure: Any, *, goal: str, loop_seed: int,
                             iteration: int, send_ordinal: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    order = (loop_seed, iteration, send_ordinal)
    pool = _pool_rows("mutation", rows, goal, order)
    kept = [ref for ref, entry in pool.items() if entry["state"] != "unavailable"]
    base, base_selection = _m24_wire(P.build_mutation_wire, content, kept, structure)
    by_ref = {item["candidate_index"]: candidate
              for item, candidate in zip(base_selection, base["candidates"], strict=True)}
    base_positions = {position["pos"]: position for position in base["positions"]}
    selection, entries = _ordered("mutation", pool, [item["candidate_index"] for item in base_selection], order)
    renamed: dict[str, str] = {}   # M24 position alias -> loop position alias, by first use in the send order
    positions, candidates = [], []
    for item in selection:
        base_candidate = by_ref[item["ref"]]
        if base_candidate["pos"] not in renamed:
            renamed[base_candidate["pos"]] = f"{J.POSITION_ALIAS_PREFIX}{len(renamed) + 1:02d}"
            base_position = base_positions[base_candidate["pos"]]
            positions.append({"pos": renamed[base_candidate["pos"]],
                              **{name: base_position[name] for name in J.ALLOWED_MUTATION_POSITION if name != "pos"}})
        candidates.append({"alias": item["alias"], "pos": renamed[base_candidate["pos"]],
                           "from": base_candidate["from"], "to": base_candidate["to"]})
    wire: dict[str, Any] = {"schema": L.WIRE_SCHEMAS["mutation"], "task": L.WIRE_TASK, "goal": goal,
                            "positions": positions, "candidates": candidates,
                            "protection_checks": base["protection_checks"]}
    if "pockets" in base:
        wire["pockets"] = base["pockets"]
    wire["computed"] = computed_rows(goal, entries)
    wire["values_note"] = L.VALUES_NOTES[("mutation", goal)]
    check_loop_wire(wire, "mutation")
    return wire, selection


# --- wire rules ------------------------------------------------------------------------------------------------------

def _need(condition: bool, message: str, field: str) -> None:
    if not condition:
        raise P.WireFieldInvalid(message, field=field)


def _check_computed(computed: Any, goal: str, aliases: list[str]) -> None:
    _need(type(computed) is list, "computed is a list", "computed")
    place = {alias: number for number, alias in enumerate(aliases)}
    seen = []
    for index, row in enumerate(computed):
        field = f"computed[{index}]"
        _need(type(row) is dict and set(row) == set(L.ALLOWED_COMPUTED[goal]), "computed row fields", field)
        _need(type(row["alias"]) is str and row["alias"] in place, "a computed alias is a wire candidate", field)
        if goal == "exploit":
            state, score = row["state"], row["score_kcal_mol"]
            _need(type(state) is str and state in L.COMPUTED_STATES, "computed state", field)
            _need(_is_number(score) if state == "scored" else score is None,
                  "scored rows carry the stored finite score; no_score rows carry null", field)
        seen.append(place[row["alias"]])
    _need(all(earlier < later for earlier, later in pairwise(seen)),
          "computed aliases appear once each, in wire order", "computed")


def check_loop_wire(wire: Any, kind: str) -> None:
    if kind not in L.KINDS:
        raise ValueError("kind must be ligand or mutation")
    _need(type(wire) is dict, "must be an object", "wire")
    allowed, optional = L.ALLOWED_TOP[kind], L.OPTIONAL_TOP[kind]
    _need(not set(wire) - set(allowed), "has a field outside the allow list", "wire")
    _need(not set(allowed) - set(optional) - set(wire), "lacks a required field", "wire")
    _need(wire["schema"] == L.WIRE_SCHEMAS[kind] and wire["task"] == L.WIRE_TASK, "schema or task", "wire")
    goal = wire["goal"]
    _need(type(goal) is str and goal in L.GOALS, "goal is explore or exploit", "goal")
    _need(wire["values_note"] == L.VALUES_NOTES[(kind, goal)], "values_note is the fixed note", "values_note")
    core = {key: value for key, value in wire.items() if key not in ("goal", "computed")}
    core["schema"], core["values_note"] = J.WIRE_SCHEMAS[kind], J.VALUES_NOTES[kind]
    P.check_wire(core, kind)   # the M24 allow lists, string patterns, alias / position order and generic scan
    _check_computed(wire["computed"], goal, [candidate["alias"] for candidate in wire["candidates"]])


# --- body (spec 4.5) -------------------------------------------------------------------------------------------------

def loop_body_object(wire: dict[str, Any], kind: str, goal: str, criteria: list[str]) -> dict[str, Any]:
    question = {"type": L.QUESTION_TYPE, "instructions": L.INSTRUCTIONS[(kind, goal)],
                "criteria": {alias: L.CRITERION_TEMPLATE.format(alias=alias) for alias in criteria}}
    return {"model": J.REQUEST_MODEL, "state": wire, "questions": {L.QUESTION_KEY: question},
            "provider": dict(J.PROVIDER)}


def encode_loop_body(wire: dict[str, Any], kind: str, goal: str, criteria: list[str]) -> bytes:
    return P.canonical_ascii(loop_body_object(wire, kind, goal, criteria))


def loop_projection_body(content: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    body = loop_body_object(content["wire"], content["kind"], content["goal"], criteria_aliases(content))
    return body, P.canonical_ascii(body)


# --- projection object (spec 4.2) ------------------------------------------------------------------------------------

def build_loop_projection_content(kind: str, source_handle: str, wire: dict[str, Any],
                                  selection: list[dict[str, Any]], *, loop_id: str, loop_seed: int, iteration: int,
                                  send_ordinal: int, structure: dict[str, Any] | None = None) -> dict[str, Any]:
    check_loop_wire(wire, kind)
    goal = wire["goal"]
    _require(structure is None or isinstance(structure, dict), "structure must be {handle, model_number} or None")
    try:
        items = [{"alias": item["alias"], "ref": item["ref"], "state": item["state"]} for item in selection]
    except (KeyError, TypeError) as exc:
        raise P.ProjectionInvalid("selection items need alias, ref and state") from exc
    body = encode_loop_body(wire, kind, goal, criteria_aliases({"selection": items}))
    if len(body) > L.MAX_BODY_BYTES:
        raise P.PayloadTooLarge(f"the request body is {len(body)} bytes; the limit is {L.MAX_BODY_BYTES}",
                                body_bytes=len(body), limit=L.MAX_BODY_BYTES)
    content = {
        "schema": L.PROJECTION_SCHEMA, "method_version": L.PROJECTION_METHOD_VERSION, "kind": kind,
        "loop": {"loop_id": loop_id, "iteration": iteration, "send_ordinal": send_ordinal},
        "goal": goal,
        "source": {"handle": source_handle, "schema": J.SOURCE_SCHEMAS[kind]},
        "structure": structure if structure is None else {"handle": structure.get("handle"),
                                                          "model_number": structure.get("model_number")},
        "question": {"id": L.QUESTION_FOR_KIND[kind], "key": L.QUESTION_KEY},
        "order": {"algorithm": L.ORDER_ALGORITHM, "loop_seed": loop_seed, "iteration": iteration,
                  "send_ordinal": send_ordinal},
        "selection": items,
        "wire": wire,
        "wire_sha256": hashlib.sha256(P.canonical_ascii(wire)).hexdigest(),
        "body_sha256": P.body_sha256(body), "body_bytes": len(body),
        "limitations": L.limitations_for(kind, goal, False),
    }
    return validated_loop_projection(content)


def _validate_header(content: Any) -> tuple[str, str]:
    _require(type(content) is dict and set(content) == set(L.PROJECTION_KEYS), "projection keys")
    _require(content["schema"] == L.PROJECTION_SCHEMA and content["method_version"] == L.PROJECTION_METHOD_VERSION,
             "projection schema")
    kind, goal = content["kind"], content["goal"]
    _require(type(kind) is str and kind in L.KINDS, "kind")
    _require(type(goal) is str and goal in L.GOALS, "goal")
    loop = content["loop"]
    _require(type(loop) is dict and set(loop) == set(L.LOOP_REF_KEYS) and L.is_loop_id(loop["loop_id"]), "loop")
    order = content["order"]
    _require(type(order) is dict and set(order) == set(L.ORDER_KEYS) and order["algorithm"] == L.ORDER_ALGORITHM
             and _is_int(order["iteration"]) and order["iteration"] == loop["iteration"]
             and _is_int(order["send_ordinal"]) and order["send_ordinal"] == loop["send_ordinal"], "order")
    _order_params(order["loop_seed"], loop["iteration"], loop["send_ordinal"])   # ValueError -> projection_invalid
    source = content["source"]
    _require(type(source) is dict and set(source) == {"handle", "schema"} and source["schema"] == J.SOURCE_SCHEMAS[kind]
             and type(source["handle"]) is str
             and re.fullmatch(_HANDLE_RE % J.SOURCE_STORE_KINDS[kind], source["handle"]) is not None, "source")
    structure = content["structure"]
    if kind == "mutation":
        _require(type(structure) is dict and set(structure) == {"handle", "model_number"}
                 and type(structure["handle"]) is str
                 and re.fullmatch(_HANDLE_RE % J.STRUCTURE_KIND, structure["handle"]) is not None
                 and _is_int(structure["model_number"]), "structure")
    else:
        _require(structure is None, "a ligand projection has no structure")
    _require(content["question"] == {"id": L.QUESTION_FOR_KIND[kind], "key": L.QUESTION_KEY}, "question")
    return kind, goal


def _validate_loop_projection(content: Any) -> None:
    kind, goal = _validate_header(content)
    selection = content["selection"]
    _require(type(selection) is list and L.MIN_PENDING_TO_SEND <= len(selection) <= L.MAX_POOL, "selection count")
    prefix = J.ALIAS_PREFIXES[kind]
    for number, item in enumerate(selection, 1):
        _require(type(item) is dict and set(item) == set(L.SELECTION_KEYS)
                 and item["alias"] == f"{prefix}{number:02d}" and _is_ref(item["ref"], kind)
                 and type(item["state"]) is str and item["state"] in L.SELECTION_STATES, "selection item")
    refs = [item["ref"] for item in selection]
    _require(len(set(refs)) == len(refs), "selection refs repeat")
    criteria = criteria_aliases(content)
    _require(len(criteria) >= L.MIN_PENDING_TO_SEND, "fewer than two candidates are not yet computed")
    order = content["order"]
    keys = [order_key(ref, loop_seed=order["loop_seed"], iteration=order["iteration"],
                      send_ordinal=order["send_ordinal"]) for ref in refs]
    _require(keys == sorted(keys), "the selection is not in the recorded sha256_order_v1 order")
    wire = content["wire"]
    check_loop_wire(wire, kind)
    _require(wire["goal"] == goal, "the wire goal is the projection goal")
    _require([candidate["alias"] for candidate in wire["candidates"]] == [item["alias"] for item in selection],
             "selection and wire aliases")
    computed = [item for item in selection if item["state"] != "pending"]
    _require([row["alias"] for row in wire["computed"]] == [item["alias"] for item in computed],
             "the wire computed rows are the selection's computed candidates")
    if goal == "exploit":
        _require([row["state"] for row in wire["computed"]] == [L.COMPUTED_STATE_FOR[item["state"]]
                                                                for item in computed], "computed states")
    wire_text = P.canonical_ascii(wire)
    _require(content["loop"]["loop_id"].encode("ascii") not in wire_text, "the loop id is never sent")
    _require(content["wire_sha256"] == hashlib.sha256(wire_text).hexdigest(), "wire hash")
    body = encode_loop_body(wire, kind, goal, criteria)
    _require(content["body_sha256"] == P.body_sha256(body) and _is_int(content["body_bytes"])
             and content["body_bytes"] == len(body) and len(body) <= L.MAX_BODY_BYTES, "body hash and length")
    _require(content["limitations"] == L.limitations_for(kind, goal, False), "limitations")
    stored = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    _require(len(stored.encode("utf-8")) <= L.MAX_OBJECT_BYTES, "object size")


def validated_loop_projection(content: Any) -> dict[str, Any]:
    try:
        _validate_loop_projection(content)
    except P.ProjectionInvalid:
        raise
    except P.WireFieldInvalid as exc:
        raise P.ProjectionInvalid(f"wire: {exc.message}", field=exc.detail.get("field")) from exc
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise P.ProjectionInvalid("loop projection content is malformed") from exc
    return content


# --- response (spec 5.2) ---------------------------------------------------------------------------------------------

def parse_loop_choice(data: Any, projection: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    return P.parse_choice(data, criteria_aliases(projection))
