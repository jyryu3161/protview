"""M24 JEV science egress: pure projection, body and response functions (spec .dryforge/spec.md 3, 4).

Imports the standard library, numpy and ``.jev_constants`` only. Nothing here reads the object store, an event log, a
file, the network or a credential: callers pass stored object contents (dicts) and, for mutation projections, the
parsed prepared structure (a ``gemmi.Structure`` whose first model is the prepared one, as
``tools.structural._parse`` returns it). The tool (T3), gate (T4) and API (T5) own handles, storage, events and HTTP.

The wire is built field by field from allow lists (never a recursive copy of stored metadata) and every wire is checked
by ``check_wire`` before use. Preview, audit and transport all take their bytes from ``encode_body`` /
``projection_body`` (one encoder: ``json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)``, ASCII).

Public API (T3 / T4 / T5 use these signatures):

    class JevProjectionError(Exception)
        JevProjectionError(reason_code: str, message: str, **detail)
        .reason_code: str, .message: str, .detail: {"reason_code": reason_code, **detail}
        (raised directly with "source_invalid", "selection_invalid", "candidate_unknown", "structure_unavailable")
    class WireFieldInvalid(JevProjectionError)      WireFieldInvalid(message, **detail)   reason "wire_field_invalid"
    class ProjectionInvalid(JevProjectionError)     ProjectionInvalid(message, **detail)  reason "projection_invalid"
    class PayloadTooLarge(JevProjectionError)       PayloadTooLarge(message, body_bytes=int, limit=int)
                                                                                          reason "payload_too_large"

    normalize_selection(kind, content, candidates) -> list[int]
        Stored positions of the requested candidates in stored order (ligand: row positions = generation order;
        mutation: candidate indices ascending). selection_invalid (not a list, 0 or > 20 items, wrong item type or
        id format, duplicates) -> candidate_unknown. ValueError for an unknown kind.
    build_ligand_wire(content, candidates, *, inspection=None) -> (wire, selection)
        content: ligand_candidate_set@1 content; candidates: ids "c_" + 16 hex (any order); inspection: its
        ligand_inspection@1 content (parent SMILES / properties fallback). selection: [{alias, candidate_id}].
    build_mutation_wire(content, candidates, structure) -> (wire, selection)
        content: mutation_candidate_set@1 content; candidates: candidate indices (any order); structure: gemmi
        Structure. selection: [{alias, candidate_index, position_index}]. structure_unavailable before
        wire_field_invalid.
    neighbors_of(structure, residue) -> list[{chain_auth, seq_auth, icode, resname}] | None
        Other protein residues (any chain, structure order) with heavy-atom (not H/D) minimum distance <= 5.0 A;
        None when the target has no heavy atom (not computed). residue: a dict of identity fields (all given fields
        must match one protein residue exactly, types included) else structure_unavailable.
    window_of(structure, residue) -> {chain_auth, first_seq_auth, residues, contiguous} | None
        Same model and chain_auth, structure order, 5 protein residues before and after (target included, cut at the
        chain ends), one-letter codes by the M20 ``one_letter`` rule (the 20 standard names and the ten mapped names,
        HID -> H, CYX -> C, ...), any other name "X"; None when chain_auth is None.
    check_wire(wire, kind) -> None                          WireFieldInvalid on any allow-list / string / number rule
    canonical_ascii(value) -> bytes                         the one encoder
    body_object(wire, question_id, aliases) -> dict         {"model", "state", "questions", "provider"}
    encode_body(wire, question_id, aliases) -> bytes        canonical_ascii(body_object(...)); KeyError: unknown id
    body_sha256(body) -> str                                SHA-256 hex
    build_projection_content(kind, source_handle, wire, selection, *, structure=None, filter_spec=None) -> dict
        jev_projection@1 content (no time, no call id). WireFieldInvalid, then PayloadTooLarge (> 65,536 body bytes,
        nothing truncated), then ProjectionInvalid if the parts are inconsistent. structure: {handle, model_number}
        (mutation only); filter_spec: a normalized M17 filter spec (ligand only) or None.
    validated_projection(content) -> content                ProjectionInvalid unless every spec 3 rule holds
    projection_body(content) -> (body_object, body_bytes)   for an already validated projection
    parse_choice(data, aliases) -> (answer | None, reason_code | None)
        answer = {choice_alias, confidence | None, probabilities | None} (values as received); reason_code None on
        success, else "response_invalid" | "missing_model" | "model_mismatch".
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from itertools import pairwise
from typing import Any

import numpy as np

from .jev_constants import (
    ALIAS_PREFIXES,
    ALLOWED_LIGAND_CANDIDATE,
    ALLOWED_LIGAND_PARENT,
    ALLOWED_LIGAND_TOP,
    ALLOWED_MUTATION_CANDIDATE,
    ALLOWED_MUTATION_POSITION,
    ALLOWED_MUTATION_TOP,
    ALLOWED_NEIGHBOR,
    ALLOWED_PAINS_MATCH,
    ALLOWED_POCKETS,
    ALLOWED_RESIDUE,
    ALLOWED_WINDOW,
    CANDIDATE_ID_RE,
    CRITERION_TEMPLATE,
    FIXED_RULE_ID,
    FORBIDDEN_WIRE_KEYS,
    GENERATION_KINDS,
    HYDROGEN_ELEMENTS,
    IDENT_RE,
    INSTRUCTIONS,
    KINDS,
    LIGAND_VALUES_NOTE,
    MAPPED_RESNAMES,
    MAX_BODY_BYTES,
    MAX_CANDIDATES,
    MAX_OBJECT_BYTES,
    MUTATION_VALUES_NOTE,
    NEIGHBOR_RADIUS_A,
    NON_STANDARD_LETTER,
    ONE_LETTER,
    ONE_LETTER_CODES,
    PAINS_CATALOGS,
    PAINS_NAME_RE,
    POSITION_ALIAS_PREFIX,
    PROJECTION_KEYS,
    PROJECTION_METHOD_VERSION,
    PROJECTION_SCHEMA,
    PROPERTY_METHODS,
    PROPERTY_NAMES,
    PROTECTION_CHECK_KEYS,
    PROTECTION_CHECK_STATUSES,
    PROVIDER,
    QUESTION_FOR_KIND,
    QUESTION_KEY,
    QUESTION_TYPE,
    REQUEST_MODEL,
    SELECTION_KEYS,
    SERVED_SNAPSHOT,
    SMILES_RE,
    SOURCE_NAMES,
    SOURCE_SCHEMAS,
    SOURCE_STORE_KINDS,
    STEREO_FLAGS,
    STRUCTURE_KIND,
    WINDOW_FLANK,
    WIRE_SCHEMAS,
    WIRE_TASK,
    limitations_for,
)

# Strings that look like a location (absolute / home / relative-dot / drive / UNC paths, any URL scheme including
# obj://, a ".." segment, a well-known local root as a path segment, a file name extension). Defense in depth: the
# per-field patterns already keep "/" and "." out of every wire string except SMILES. The generic scan applies it only
# to strings with a path character (``_PATH_TRIGGER``: "/", "\", "~", a drive letter "C:" or ".."), so a legal
# identifier such as "tmp" or "Users" (a chain or residue name) is never refused; SMILES fields always get the whole
# check (``_check_ligand``), file name shapes included.
_PATH_TRIGGER = re.compile(r"[/\\~]|[A-Za-z]:|\.\.")
_PATH_SHAPE = re.compile(
    r"^(?:/|~|\\|\.{1,2}[\\/]|[A-Za-z]:[\\/])"
    r"|://"
    r"|(?:^|[\\/])\.\.(?:[\\/]|$)"
    r"|(?:^|[\\/])(?:Users|home|private|tmp|var|runs|objects|backend|\.deps|\.venv|\.env)(?:[\\/]|$)"
    r"|\.(?:cif|mmcif|pdb|pdbqt|sdf|mol|mol2|smi|json|jsonl|txt|env|py)$")
_WINDOW_RE = re.compile(f"[{ONE_LETTER_CODES}{NON_STANDARD_LETTER}]{{1,{2 * WINDOW_FLANK + 1}}}")
_HANDLE_RE = r"obj://[A-Za-z0-9][A-Za-z0-9_-]{0,79}/%s/[0-9a-f]{64}"
_ANSWER_KEYS = frozenset({"type", "choice", "confidence", "probabilities"})
# Window letters: the M20 position ``one_letter`` rule (``mutation_candidates.standard_name`` then the standard letter).
_WINDOW_LETTER = {**ONE_LETTER, **{name: ONE_LETTER[standard] for name, standard in MAPPED_RESNAMES.items()}}


# --- errors ----------------------------------------------------------------------------------------------------------

class JevProjectionError(Exception):
    """A refusal with a closed ``reason_code`` (spec 3 admission set, or ``projection_invalid``)."""

    def __init__(self, reason_code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.detail = {"reason_code": reason_code, **detail}


class WireFieldInvalid(JevProjectionError):
    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__("wire_field_invalid", message, **detail)


class ProjectionInvalid(JevProjectionError):
    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__("projection_invalid", message, **detail)


class PayloadTooLarge(JevProjectionError):
    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__("payload_too_large", message, **detail)


# --- small predicates ------------------------------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _is_unit(value: Any) -> bool:
    if type(value) is int:
        return 0 <= value <= 1
    return type(value) is float and math.isfinite(value) and 0.0 <= value <= 1.0


def _matches(pattern: re.Pattern[str], value: Any) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _named(source: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: source[name] for name in names}


# --- selection -------------------------------------------------------------------------------------------------------

def normalize_selection(kind: str, content: dict[str, Any], candidates: Any) -> list[int]:
    if kind not in KINDS:
        raise ValueError("kind must be ligand or mutation")
    if type(candidates) is not list or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise JevProjectionError("selection_invalid", f"candidates must be a list of 1-{MAX_CANDIDATES} items")
    if kind == "ligand":
        if not all(_matches(CANDIDATE_ID_RE, item) for item in candidates):
            raise JevProjectionError("selection_invalid", "ligand candidates are ids 'c_' + 16 hex digits")
    elif not all(_is_int(item) for item in candidates):
        raise JevProjectionError("selection_invalid", "mutation candidates are integer candidate indices")
    if len(set(candidates)) != len(candidates):
        raise JevProjectionError("selection_invalid", "candidates must not repeat")
    try:
        rows = content["candidates"]
        key = "id" if kind == "ligand" else "index"
        stored = {row[key]: position for position, row in enumerate(rows)}
    except (KeyError, TypeError) as exc:
        raise JevProjectionError("source_invalid", "the candidate set has no readable candidate rows") from exc
    unknown = [item for item in candidates if item not in stored]
    if unknown:
        raise JevProjectionError("candidate_unknown", "candidates are not in the candidate set", candidates=unknown)
    return sorted(stored[item] for item in candidates)


# --- ligand wire -----------------------------------------------------------------------------------------------------

def build_ligand_wire(content: dict[str, Any], candidates: Any, *,
                      inspection: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    positions = normalize_selection("ligand", content, candidates)
    try:
        rows = content["candidates"]
        smiles, properties = content.get("parent_canonical_smiles"), content.get("parent_properties")
        if (smiles is None or properties is None) and isinstance(inspection, dict):   # spec 3: then the inspection
            stored_parent = inspection.get("parent") or {}
            smiles = stored_parent.get("canonical_smiles") if smiles is None else smiles
            properties = stored_parent.get("properties") if properties is None else properties
        parent = {**({"smiles": smiles} if smiles is not None else {}),
                  "properties": _named(properties, PROPERTY_NAMES)}
        wire_candidates = []
        for number, position in enumerate(positions, 1):
            row = rows[position]
            kinds = {"fixed_replace" if origin["rule_id"] == FIXED_RULE_ID else "user_rule"
                     for origin in row["origins"]}
            wire_candidates.append({
                "alias": f"{ALIAS_PREFIXES['ligand']}{number:02d}", "smiles": row["smiles"],
                "generation_kinds": sorted(kinds), "stereo_flag": row["stereo_flag"],
                "properties": _named(row["properties"], PROPERTY_NAMES),
                "pains_matches": [_named(match, ALLOWED_PAINS_MATCH) for match in row["pains"]["matches"]]})
        wire = {"schema": WIRE_SCHEMAS["ligand"], "task": WIRE_TASK, "parent": parent,
                "property_methods": _named(content["property_methods"], PROPERTY_NAMES),
                "candidates": wire_candidates, "values_note": LIGAND_VALUES_NOTE}
        selection = [{"alias": item["alias"], "candidate_id": rows[position]["id"]}
                     for item, position in zip(wire_candidates, positions, strict=True)]
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise WireFieldInvalid("the candidate set lacks a field the wire needs") from exc
    check_wire(wire, "ligand")
    return wire, selection


# --- structure geometry ----------------------------------------------------------------------------------------------

def _walk(structure: Any) -> list[dict[str, Any]]:
    """Every residue of the first model in file order: 7-field identity, protein flag, heavy-atom coordinates."""
    model = structure[0]
    out = []
    for chain in model:
        for res in chain:
            heavy = [(atom.pos.x, atom.pos.y, atom.pos.z) for atom in res
                     if atom.element.name.upper() not in HYDROGEN_ELEMENTS]
            out.append({
                "residue": {"model_number": model.num, "chain_auth": chain.name, "chain_label": res.subchain or None,
                            "seq_auth": res.seqid.num, "seq_label": res.label_seq,
                            "icode": res.seqid.icode.strip(), "resname": res.name},
                "protein": res.het_flag == "A" and not res.is_water(),
                "heavy": np.array(heavy, dtype=np.float64).reshape(-1, 3)})
    return out


def _min_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = a[:, None, :] - b[None, :, :]
    return float(np.sqrt((diff * diff).sum(axis=2)).min())


def _resolve(walk: list[dict[str, Any]], residue: Any) -> dict[str, Any]:
    def same(entry: dict[str, Any]) -> bool:
        stored = entry["residue"]
        return all(key in stored and type(stored[key]) is type(value) and stored[key] == value
                   for key, value in residue.items())

    found = ([entry for entry in walk if entry["protein"] and same(entry)]
             if isinstance(residue, dict) and residue else [])
    if len(found) != 1:
        raise JevProjectionError("structure_unavailable",
                                 "a position does not resolve to exactly one protein residue of the structure")
    return found[0]


def _neighbors(walk: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]] | None:
    if not len(target["heavy"]):
        return None
    return [_named(entry["residue"], ALLOWED_NEIGHBOR) for entry in walk
            if entry is not target and entry["protein"] and len(entry["heavy"])
            and _min_distance(target["heavy"], entry["heavy"]) <= NEIGHBOR_RADIUS_A]


def _window(walk: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any] | None:
    chain_auth = target["residue"]["chain_auth"]
    if chain_auth is None:
        return None
    chain = [entry for entry in walk if entry["protein"] and entry["residue"]["chain_auth"] == chain_auth]
    at = next(index for index, entry in enumerate(chain) if entry is target)
    span = [entry["residue"] for entry in chain[max(0, at - WINDOW_FLANK):at + WINDOW_FLANK + 1]]
    numbers = [residue["seq_auth"] for residue in span]
    contiguous = (all(residue["icode"] == "" for residue in span)
                  and all(later == earlier + 1 for earlier, later in pairwise(numbers)))
    return {"chain_auth": chain_auth, "first_seq_auth": numbers[0],
            "residues": "".join(_WINDOW_LETTER.get(residue["resname"], NON_STANDARD_LETTER) for residue in span),
            "contiguous": contiguous}


def neighbors_of(structure: Any, residue: dict[str, Any]) -> list[dict[str, Any]] | None:
    walk = _walk(structure)
    return _neighbors(walk, _resolve(walk, residue))


def window_of(structure: Any, residue: dict[str, Any]) -> dict[str, Any] | None:
    walk = _walk(structure)
    return _window(walk, _resolve(walk, residue))


# --- mutation wire ---------------------------------------------------------------------------------------------------

def _source_names(sources: list[dict[str, Any]]) -> list[str]:
    kinds = {source["kind"] for source in sources}
    if not kinds <= set(SOURCE_NAMES):
        raise WireFieldInvalid("a position source is outside the closed source names", field="sources")
    return [name for name in SOURCE_NAMES if name in kinds]


def build_mutation_wire(content: dict[str, Any], candidates: Any,
                        structure: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    indices = normalize_selection("mutation", content, candidates)
    try:
        rows, positions = content["candidates"], content["positions"]
        chosen = [rows[index] for index in indices]
        order = list(dict.fromkeys(row["position_index"] for row in chosen))   # first appearance
        model_number = content["structure"]["model_number"]
        references = [positions[index]["residue"] for index in order]
    except (KeyError, TypeError, IndexError) as exc:
        raise WireFieldInvalid("the candidate set lacks a field the wire needs") from exc
    if structure is None or len(structure) == 0 or structure[0].num != model_number:
        raise JevProjectionError("structure_unavailable", "the structure model is not the candidate set's model")
    walk = _walk(structure)
    targets = [_resolve(walk, reference) for reference in references]   # all positions before any wire field
    try:
        alias = {index: f"{POSITION_ALIAS_PREFIX}{number:02d}" for number, index in enumerate(order, 1)}
        wire_positions = []
        for index, target in zip(order, targets, strict=True):
            position = positions[index]
            wire_positions.append({
                "pos": alias[index], "residue": _named(position["residue"], ALLOWED_RESIDUE),
                "one_letter": position["one_letter"], "sources": _source_names(position["sources"]),
                "ligand_min_distance_A": position["ligand_min_distance_A"],
                "protection_released": position["protection"]["released"],
                "window": _window(walk, target), "neighbors": _neighbors(walk, target)})
        wire_candidates, selection = [], []
        for number, row in enumerate(chosen, 1):
            name = f"{ALIAS_PREFIXES['mutation']}{number:02d}"
            wire_candidates.append({"alias": name, "pos": alias[row["position_index"]], "from": row["from"],
                                    "to": row["to"]})
            selection.append({"alias": name, "candidate_index": row["index"],
                              "position_index": row["position_index"]})
        wire: dict[str, Any] = {
            "schema": WIRE_SCHEMAS["mutation"], "task": WIRE_TASK, "positions": wire_positions,
            "candidates": wire_candidates,
            "protection_checks": {key: content["protection_checks"][key]["status"] for key in PROTECTION_CHECK_KEYS}}
        pockets = content["pockets"]
        if pockets is not None:
            wire["pockets"] = {"ranks": list(pockets["ranks"]), "lining_residue_count": pockets["lining_residue_count"]}
        wire["values_note"] = MUTATION_VALUES_NOTE
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise WireFieldInvalid("the candidate set lacks a field the wire needs") from exc
    check_wire(wire, "mutation")
    return wire, selection


# --- wire rules ------------------------------------------------------------------------------------------------------

def _need(condition: bool, message: str, field: str) -> None:
    if not condition:
        raise WireFieldInvalid(message, field=field)


def _fields(value: Any, allowed: tuple[str, ...], field: str, optional: tuple[str, ...] = ()) -> None:
    _need(type(value) is dict, "must be an object", field)
    _need(not set(value) - set(allowed), "has a field outside the allow list", field)
    _need(not set(allowed) - set(optional) - set(value), "lacks a required field", field)


def _scan(value: Any, field: str) -> None:
    """Generic pass over the whole wire: forbidden key names, location-shaped strings, non-finite or unknown values."""
    if type(value) is dict:
        for key, item in value.items():
            _need(type(key) is str and key not in FORBIDDEN_WIRE_KEYS, "forbidden key name", field)
            _scan(item, f"{field}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _scan(item, f"{field}[{index}]")
    elif type(value) is str:
        _need(_PATH_TRIGGER.search(value) is None or _PATH_SHAPE.search(value) is None,
              "a handle, path or file name is never sent", field)
    elif type(value) is float:
        _need(math.isfinite(value), "numbers must be finite", field)
    else:
        _need(value is None or type(value) in (bool, int), "unsupported value type", field)


def _check_aliases(items: Any, prefix: str, field: str) -> None:
    _need(type(items) is list and 1 <= len(items) <= MAX_CANDIDATES, f"must hold 1-{MAX_CANDIDATES} items", field)
    for number, item in enumerate(items, 1):
        _need(type(item) is dict and item.get("alias") == f"{prefix}{number:02d}", "aliases run in stored order",
              f"{field}[{number - 1}].alias")


def _check_properties(values: Any, field: str) -> None:
    _fields(values, PROPERTY_NAMES, field)
    _need(all(_is_number(values[name]) for name in PROPERTY_NAMES), "properties are finite numbers", field)


def _check_smiles(value: Any, field: str) -> None:
    _need(_matches(SMILES_RE, value), "unsafe SMILES", field)
    _need(_PATH_SHAPE.search(value) is None, "a handle, path or file name is never sent", field)


def _check_ligand(wire: dict[str, Any]) -> None:
    _fields(wire, ALLOWED_LIGAND_TOP, "wire")
    _need(wire["schema"] == WIRE_SCHEMAS["ligand"] and wire["task"] == WIRE_TASK, "schema or task", "wire")
    _need(wire["values_note"] == LIGAND_VALUES_NOTE, "values_note is the fixed note", "values_note")
    parent = wire["parent"]
    _fields(parent, ALLOWED_LIGAND_PARENT, "parent", optional=("smiles",))
    if "smiles" in parent:
        _check_smiles(parent["smiles"], "parent.smiles")
    _check_properties(parent["properties"], "parent.properties")
    methods = wire["property_methods"]
    _fields(methods, PROPERTY_NAMES, "property_methods")
    _need(all(type(methods[name]) is str and methods[name] == PROPERTY_METHODS[name] for name in PROPERTY_NAMES),
          "property methods are the observed stored strings", "property_methods")
    _check_aliases(wire["candidates"], ALIAS_PREFIXES["ligand"], "candidates")
    for index, candidate in enumerate(wire["candidates"]):
        field = f"candidates[{index}]"
        _fields(candidate, ALLOWED_LIGAND_CANDIDATE, field)
        _check_smiles(candidate["smiles"], f"{field}.smiles")
        kinds = candidate["generation_kinds"]
        _need(type(kinds) is list and bool(kinds) and all(kind in GENERATION_KINDS for kind in kinds)
              and kinds == sorted(set(kinds)), "generation kinds", f"{field}.generation_kinds")
        _need(candidate["stereo_flag"] in STEREO_FLAGS, "stereo flag", f"{field}.stereo_flag")
        _check_properties(candidate["properties"], f"{field}.properties")
        matches = candidate["pains_matches"]
        _need(type(matches) is list, "PAINS matches are a list", f"{field}.pains_matches")
        for match in matches:
            _fields(match, ALLOWED_PAINS_MATCH, f"{field}.pains_matches")
            _need(match["catalog"] in PAINS_CATALOGS and _matches(PAINS_NAME_RE, match["name"]),
                  "PAINS catalog or name", f"{field}.pains_matches")


def _check_identifier(value: Any, field: str, *, nullable: bool = False, non_empty: bool = False) -> None:
    _need((nullable and value is None) or (_matches(IDENT_RE, value) and (not non_empty or value != "")),
          "unsafe identifier", field)


def _check_residue(residue: Any, field: str) -> None:
    _fields(residue, ALLOWED_RESIDUE, field)
    _need(_is_int(residue["model_number"]) and _is_int(residue["seq_auth"])
          and (residue["seq_label"] is None or _is_int(residue["seq_label"])), "residue numbers", field)
    for key in ("chain_auth", "chain_label", "icode"):   # spec 3: a null identifier is sent as null
        _check_identifier(residue[key], f"{field}.{key}", nullable=True)
    _check_identifier(residue["resname"], f"{field}.resname", non_empty=True)


def _check_position(position: Any, number: int) -> None:
    field = f"positions[{number - 1}]"
    _fields(position, ALLOWED_MUTATION_POSITION, field)
    _need(position["pos"] == f"{POSITION_ALIAS_PREFIX}{number:02d}", "position aliases in order", f"{field}.pos")
    _check_residue(position["residue"], f"{field}.residue")
    _need(type(position["one_letter"]) is str and len(position["one_letter"]) == 1
          and position["one_letter"] in ONE_LETTER_CODES, "one-letter code", f"{field}.one_letter")
    sources = position["sources"]
    _need(type(sources) is list and bool(sources) and all(type(s) is str and s in SOURCE_NAMES for s in sources)
          and sources == [name for name in SOURCE_NAMES if name in sources], "closed source names",
          f"{field}.sources")
    distance = position["ligand_min_distance_A"]
    _need(distance is None or (_is_number(distance) and distance >= 0), "stored distance", f"{field}.distance")
    _need(type(position["protection_released"]) is bool, "boolean", f"{field}.protection_released")
    window = position["window"]
    _need(window is None or position["residue"]["chain_auth"] is not None, "no window without a chain",
          f"{field}.window")
    if window is not None:
        _fields(window, ALLOWED_WINDOW, f"{field}.window")
        _check_identifier(window["chain_auth"], f"{field}.window.chain_auth")
        _need(window["chain_auth"] == position["residue"]["chain_auth"] and _is_int(window["first_seq_auth"])
              and _matches(_WINDOW_RE, window["residues"]) and type(window["contiguous"]) is bool,
              "window", f"{field}.window")
    neighbors = position["neighbors"]
    _need(neighbors is None or type(neighbors) is list, "neighbors are a list", f"{field}.neighbors")
    for neighbor in neighbors or []:
        _fields(neighbor, ALLOWED_NEIGHBOR, f"{field}.neighbors")
        _need(_is_int(neighbor["seq_auth"]), "neighbor number", f"{field}.neighbors")
        _check_identifier(neighbor["chain_auth"], f"{field}.neighbors.chain_auth", nullable=True)
        _check_identifier(neighbor["icode"], f"{field}.neighbors.icode", nullable=True)
        _check_identifier(neighbor["resname"], f"{field}.neighbors.resname", non_empty=True)


def _check_mutation(wire: dict[str, Any]) -> None:
    _fields(wire, ALLOWED_MUTATION_TOP, "wire", optional=("pockets",))
    _need(wire["schema"] == WIRE_SCHEMAS["mutation"] and wire["task"] == WIRE_TASK, "schema or task", "wire")
    _need(wire["values_note"] == MUTATION_VALUES_NOTE, "values_note is the fixed note", "values_note")
    checks = wire["protection_checks"]
    _fields(checks, PROTECTION_CHECK_KEYS, "protection_checks")
    _need(all(type(checks[key]) is str and checks[key] in PROTECTION_CHECK_STATUSES for key in PROTECTION_CHECK_KEYS),
          "check status strings only", "protection_checks")
    if "pockets" in wire:
        pockets = wire["pockets"]
        _fields(pockets, ALLOWED_POCKETS, "pockets")
        ranks = pockets["ranks"]
        _need(type(ranks) is list and bool(ranks) and all(map(_is_int, ranks)) and ranks == sorted(set(ranks))
              and _is_int(pockets["lining_residue_count"]) and pockets["lining_residue_count"] >= 0,
              "pocket ranks and lining count", "pockets")
    positions = wire["positions"]
    _need(type(positions) is list and 1 <= len(positions) <= MAX_CANDIDATES, "positions", "positions")
    for number, position in enumerate(positions, 1):
        _check_position(position, number)
    letters = {position["pos"]: position["one_letter"] for position in positions}
    _check_aliases(wire["candidates"], ALIAS_PREFIXES["mutation"], "candidates")
    for index, candidate in enumerate(wire["candidates"]):
        field = f"candidates[{index}]"
        _fields(candidate, ALLOWED_MUTATION_CANDIDATE, field)
        _need(candidate["pos"] in letters and candidate["from"] == letters[candidate["pos"]]
              and type(candidate["to"]) is str and len(candidate["to"]) == 1 and candidate["to"] in ONE_LETTER_CODES
              and candidate["to"] != candidate["from"], "position and residue codes", field)
    _need(list(dict.fromkeys(c["pos"] for c in wire["candidates"])) == list(letters),
          "positions appear once each, in first-use order", "positions")


def check_wire(wire: Any, kind: str) -> None:
    if kind not in KINDS:
        raise ValueError("kind must be ligand or mutation")
    _scan(wire, "wire")
    if kind == "ligand":
        _check_ligand(wire)
    else:
        _check_mutation(wire)


# --- body --------------------------------------------------------------------------------------------------------------

def canonical_ascii(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True).encode("ascii")


def body_object(wire: dict[str, Any], question_id: str, aliases: list[str]) -> dict[str, Any]:
    question = {"type": QUESTION_TYPE, "instructions": INSTRUCTIONS[question_id],
                "criteria": {alias: CRITERION_TEMPLATE.format(alias=alias) for alias in aliases}}
    return {"model": REQUEST_MODEL, "state": wire, "questions": {QUESTION_KEY: question}, "provider": dict(PROVIDER)}


def encode_body(wire: dict[str, Any], question_id: str, aliases: list[str]) -> bytes:
    return canonical_ascii(body_object(wire, question_id, aliases))


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def projection_body(content: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    body = body_object(content["wire"], content["question"]["id"], [item["alias"] for item in content["selection"]])
    return body, canonical_ascii(body)


# --- projection object -------------------------------------------------------------------------------------------------

def build_projection_content(kind: str, source_handle: str, wire: dict[str, Any], selection: list[dict[str, Any]],
                             *, structure: dict[str, Any] | None = None,
                             filter_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    check_wire(wire, kind)
    question_id = QUESTION_FOR_KIND[kind]
    if structure is not None and not isinstance(structure, dict):
        raise ProjectionInvalid("structure must be {handle, model_number} or None")
    try:
        aliases = [item["alias"] for item in selection]
        body = encode_body(wire, question_id, aliases)
    except (KeyError, TypeError) as exc:
        raise ProjectionInvalid("selection items need an alias") from exc
    if len(body) > MAX_BODY_BYTES:
        raise PayloadTooLarge(f"the request body is {len(body)} bytes; the limit is {MAX_BODY_BYTES}",
                              body_bytes=len(body), limit=MAX_BODY_BYTES)
    content = {
        "schema": PROJECTION_SCHEMA, "method_version": PROJECTION_METHOD_VERSION, "kind": kind,
        "source": {"handle": source_handle, "schema": SOURCE_SCHEMAS[kind]},
        "structure": structure if structure is None else {"handle": structure.get("handle"),
                                                          "model_number": structure.get("model_number")},
        "question": {"id": question_id, "key": QUESTION_KEY},
        "filter": filter_spec,
        "selection": [dict(item) for item in selection],
        "wire": wire,
        "wire_sha256": hashlib.sha256(canonical_ascii(wire)).hexdigest(),
        "body_sha256": body_sha256(body), "body_bytes": len(body),
        "limitations": limitations_for(kind, False),
    }
    return validated_projection(content)


def _filter_ok(spec: Any) -> bool:
    """The normalized M17 filter form (``ligand_filters.normalize_filter_spec`` output; key order not compared)."""
    if type(spec) is not dict or set(spec) != {"ranges", "pains_exclude"} or type(spec["pains_exclude"]) is not bool:
        return False
    ranges = spec["ranges"]
    if type(ranges) is not dict or not set(ranges) <= set(PROPERTY_NAMES):
        return False
    for bounds in ranges.values():
        if type(bounds) is not dict or set(bounds) != {"min", "max"}:
            return False
        low, high = bounds["min"], bounds["max"]
        if any(value is not None and not _is_number(value) for value in (low, high)) or (low is None and high is None):
            return False
        if low is not None and high is not None and low > high:
            return False
    return True


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionInvalid(message)


def _validate_projection(content: Any) -> None:
    _require(type(content) is dict and set(content) == set(PROJECTION_KEYS), "projection keys")
    _require(content["schema"] == PROJECTION_SCHEMA and content["method_version"] == PROJECTION_METHOD_VERSION,
             "projection schema")
    kind = content["kind"]
    _require(type(kind) is str and kind in KINDS, "kind")
    source = content["source"]
    _require(type(source) is dict and set(source) == {"handle", "schema"} and source["schema"] == SOURCE_SCHEMAS[kind]
             and type(source["handle"]) is str
             and re.fullmatch(_HANDLE_RE % SOURCE_STORE_KINDS[kind], source["handle"]) is not None, "source")
    structure = content["structure"]
    if kind == "mutation":
        _require(type(structure) is dict and set(structure) == {"handle", "model_number"}
                 and type(structure["handle"]) is str
                 and re.fullmatch(_HANDLE_RE % STRUCTURE_KIND, structure["handle"]) is not None
                 and _is_int(structure["model_number"]), "structure")
        _require(content["filter"] is None, "a mutation projection has no filter")
    else:
        _require(structure is None, "a ligand projection has no structure")
        _require(content["filter"] is None or _filter_ok(content["filter"]), "filter")
    question = content["question"]
    _require(type(question) is dict and question == {"id": QUESTION_FOR_KIND[kind], "key": QUESTION_KEY}, "question")
    selection = content["selection"]
    _require(type(selection) is list and 1 <= len(selection) <= MAX_CANDIDATES, "selection count")
    for number, item in enumerate(selection, 1):
        _require(type(item) is dict and set(item) == set(SELECTION_KEYS[kind])
                 and item["alias"] == f"{ALIAS_PREFIXES[kind]}{number:02d}", "selection item")
        if kind == "ligand":
            _require(_matches(CANDIDATE_ID_RE, item["candidate_id"]), "candidate id")
        else:
            _require(_is_int(item["candidate_index"]) and item["candidate_index"] >= 0
                     and _is_int(item["position_index"]) and item["position_index"] >= 0, "candidate index")
    if kind == "ligand":
        _require(len({item["candidate_id"] for item in selection}) == len(selection), "candidate ids repeat")
    else:
        indices = [item["candidate_index"] for item in selection]
        _require(all(later > earlier for earlier, later in pairwise(indices)), "indices ascend")
    wire = content["wire"]
    check_wire(wire, kind)
    aliases = [item["alias"] for item in selection]
    _require([candidate["alias"] for candidate in wire["candidates"]] == aliases, "selection and wire aliases")
    if kind == "mutation":
        pairs = {(item["position_index"], candidate["pos"]) for item, candidate in zip(selection, wire["candidates"])}
        _require(len(pairs) == len({left for left, _ in pairs}) == len({right for _, right in pairs}),
                 "selection positions and wire positions")
    _require(content["wire_sha256"] == hashlib.sha256(canonical_ascii(wire)).hexdigest(), "wire hash")
    body = encode_body(wire, question["id"], aliases)
    _require(content["body_sha256"] == body_sha256(body) and _is_int(content["body_bytes"])
             and content["body_bytes"] == len(body) and len(body) <= MAX_BODY_BYTES, "body hash and length")
    _require(content["limitations"] == limitations_for(kind, False), "limitations")
    stored = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    _require(len(stored.encode("utf-8")) <= MAX_OBJECT_BYTES, "object size")


def validated_projection(content: Any) -> dict[str, Any]:
    try:
        _validate_projection(content)
    except ProjectionInvalid:
        raise
    except WireFieldInvalid as exc:
        raise ProjectionInvalid(f"wire: {exc.message}", field=exc.detail.get("field")) from exc
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise ProjectionInvalid("projection content is malformed") from exc
    return content


# --- response ----------------------------------------------------------------------------------------------------------

def parse_choice(data: Any, aliases: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(data, dict):
        return None, "response_invalid"
    if data.get("model") is None:
        return None, "missing_model"
    if data["model"] != SERVED_SNAPSHOT:
        return None, "model_mismatch"
    choices = set(aliases)
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != {QUESTION_KEY}:
        return None, "response_invalid"
    answer = answers[QUESTION_KEY]
    if (not isinstance(answer, dict) or set(answer) - _ANSWER_KEYS or answer.get("type") != QUESTION_TYPE
            or type(answer.get("choice")) is not str or answer["choice"] not in choices):
        return None, "response_invalid"
    if "confidence" in answer and not _is_unit(answer["confidence"]):
        return None, "response_invalid"
    probabilities = answer.get("probabilities")
    if "probabilities" in answer and not (
            isinstance(probabilities, dict) and len(probabilities) <= len(choices)
            and all(type(key) is str and key in choices and _is_unit(value) for key, value in probabilities.items())):
        return None, "response_invalid"
    return {"choice_alias": answer["choice"], "confidence": answer.get("confidence"),
            "probabilities": dict(probabilities) if "probabilities" in answer else None}, None
