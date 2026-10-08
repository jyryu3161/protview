"""M26 reaction knowledge: link one structure's chains to the M-CSA catalytic residue rows, UniProt sites and
reactions of a pinned reaction reference set (spec .dryforge/spec.md 5.3-5.6), and validate the result.

Pure logic over an already pinned set (``mw.reaction_snapshots``) and already parsed chain residues; the tool wrapper
owns argument normalization, the admission order (spec 5.2), failure classes, the call key and storage. Nothing here
reads the network, the M15 reference folder or the event log.

Interface (consumed by the tool, the read routes, the report and M20 v2; keep it stable):

* ``pin_and_index(root=None) -> (PinnedReactionSet, ReactionIndex)`` and ``reaction_index(pinned)``: decode the three
  processed files of one pinned set (``reaction_knowledge_constants.decode_jsonl``) and index them; one cached set
  (the most recent), keyed by set hash + the files' stat identity, successes only. A format error is
  ``reaction_snapshots.SnapshotUnavailable("snapshot_invalid")``. ``clear_index_cache()``; ``capability(root=None)``
  (the ``methods.*`` shape with content decoded).
* ``pdb_entries(index, pdb_id)``: the M-CSA entries naming a PDB ID ``[{mcsa_id, enzyme_name, reference_uniprot_id,
  chains}]`` (``chains`` = sorted distinct ``chain_name`` values for that PDB).
* ``chain_polymer_residues(st) -> {chain_auth: [7-field residue, ...]}``: the M15 chain residue rule
  (``residue_numbering.chain_residues``) on a gemmi structure holding only the selected model, before
  ``setup_entities()`` (what ``tools.structural._parse`` returns); file order; ``ValueError`` when entity setup changes
  the residue list. The caller parses the structure.
* sections: ``mcsa_section(index, pdb_id, chain_auth, residues)``, ``chain_accession(chain_auth, uniprot_accession,
  numbering_map) -> (accession, accession_source)``, ``map_accession(numbering_map, chain_auth)``,
  ``uniprot_section(index, accession, chain_auth, numbering_map)``, ``reactions_section(index, mcsa, uniprot)``,
  ``chain_flags(index, accession, mcsa)``, ``snapshot_set_record(pinned)``. ``numbering_map`` is the stored
  ``residue_numbering_map@1`` content (a dict) or ``None``.
* ``build_reaction_knowledge(*, pinned, index, structure_handle, structure_kind, model_number, pdb_id, chains,
  chain_residues, numbering_map=None, numbering_map_handle=None) -> dict``: the ``reaction_knowledge@1`` content.
  ``pdb_id`` is the upper-case request value or ``None``; ``chains`` is the normalized request list
  ``[{chain_auth, uniprot_accession}]``. Raises ``TooManyLinks`` (more than ``MAX_LINKS`` link elements) or
  ``ResultTooLarge`` (canonical JSON above ``MAX_RESULT_BYTES``), both ``ResourceExceeded``: nothing is truncated and
  nothing is returned (the tool maps them to 429 ``resource_exceeded``). Same input + same set -> the same dict.
* ``validated_result(obj) -> obj``: pure re-check of a new or stored result (exact key sets, closed sets, null vs [],
  counts, rows against their chain, every reference value against ``reference_rows``, fixed sentences); raises
  ``ResultInvalid`` (a ``ValueError``).

Reference values are copied verbatim from the snapshot rows; the only values computed here are counts. Unmatched,
conflicting and unchecked parts are states with reasons and never become 0 or an empty "none": a part that was not
checked is ``null``. Several M-CSA entries on one chain are all shown; none is chosen.
"""
from __future__ import annotations

import copy
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import reaction_knowledge_constants as K
from . import reaction_snapshots as rs
from .mutation_candidates import standard_name  # the M20 name rule itself (20 names + the ten M12 names)
from .mutation_constants import STANDARD_ONE_LETTER
from .residue_numbering import chain_residues as _m15_chain_residues
from .tools.structural import _res_ref

_HANDLE = re.compile(r"obj://([A-Za-z0-9][A-Za-z0-9_-]{0,79})/([a-z][a-z0-9_]{0,79})/[0-9a-f]{64}\Z")
_RESULT_PDB_ID = re.compile(r"[0-9][A-Z0-9]{3}\Z")
STRUCTURE_KINDS = ("structure", "prepared_structure")
MAP_KIND = "residue_numbering_map"

TOP_KEYS = frozenset({"schema", "method_version", "structure", "pdb_id", "numbering_map", "snapshot_set", "chains",
                      "reference_rows", "counts", "null_result", "limitations"})
CHAIN_KEYS = frozenset({"chain_auth", "polymer_residue_count", "accession", "accession_source", "mcsa", "uniprot",
                        "reactions", "flags"})
MCSA_KEYS = frozenset({"status", "reason", "coverage", "entries", "rows", "counts"})
ROW_KEYS = frozenset({"mcsa_id", "residue_index", "is_reference", "listed", "status", "reason", "residue",
                      "structure_resname", "reference"})
UNIPROT_KEYS = frozenset({"status", "reason", "skipped", "entry", "linked_via", "link_reason", "features"})
FEATURE_KEYS = frozenset({"type", "start", "end", "description", "ligand_name", "ligand_id", "links"})
LINK_KEYS = frozenset({"position", "status", "residue", "uniprot_residue", "residue_match"})
REACTIONS_KEYS = frozenset({"status", "reason", "ecs", "mcsa_compounds", "uniprot_activities"})
COUNTS_KEYS = frozenset({"chains", "covered_chains", "mcsa_rows", "mcsa_entries", "uniprot_features",
                         "linked_positions", "rhea"})

MCSA_NOT_CHECKED = {"status": K.NOT_CHECKED, "reason": K.MCSA_NOT_CHECKED_REASON, "coverage": None, "entries": None,
                    "rows": None, "counts": None}
UNIPROT_NOT_CHECKED = {"status": K.NOT_CHECKED, "reason": "accession_not_given", "skipped": None, "entry": None,
                       "linked_via": None, "link_reason": None, "features": None}
REACTIONS_NOT_CHECKED = {"status": K.NOT_CHECKED, "reason": K.REACTIONS_NOT_CHECKED_REASON, "ecs": None,
                         "mcsa_compounds": None, "uniprot_activities": None}
_STRUCTURE_STEPS = {("unmatched", "residue_not_in_structure"), ("unmatched", "ambiguous_residue_number"),
                    ("unmatched", "insertion_code_present"), ("matched", None), ("conflict", "residue_name_differs")}


class ResultInvalid(ValueError):
    """A result that does not have the fixed ``reaction_knowledge@1`` shape and values."""


class ResourceExceeded(Exception):
    """A result above a cap (refused, never truncated)."""

    def __init__(self, message: str, *, limit: int, actual: int | None = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.actual = actual


class ResultTooLarge(ResourceExceeded):
    """The canonical JSON of the result is larger than ``MAX_RESULT_BYTES``."""


class TooManyLinks(ResourceExceeded):
    """More than ``MAX_LINKS`` UniProt site link elements (``links`` entries) in one result."""


# ------------------------------------------------------------------------------------------- set index

@dataclass(frozen=True)
class ReactionIndex:
    set_hash: str
    key: tuple
    mcsa: Mapping[int, dict[str, Any]]                 # mcsa_id -> processed row (file order = ascending id)
    mcsa_by_pdb: Mapping[str, tuple[int, ...]]         # lower-case PDB ID -> mcsa_ids naming it (ascending)
    uniprot: Mapping[str, dict[str, Any]]              # accession -> processed row
    rhea: Mapping[str, dict[str, Any]]                 # rhea_id -> processed row (integer order)
    skipped: Mapping[str, dict[str, Any]] = field(default_factory=dict)  # accession -> {reason, target_accessions}


_INDEX_CACHE: dict[tuple, ReactionIndex] = {}
_INDEX_LOCK = threading.Lock()


def clear_index_cache() -> None:
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


def _decode(pinned: rs.PinnedReactionSet, source: str) -> list[dict[str, Any]]:
    (name,) = K.SOURCE_FILES[source]
    return K.decode_jsonl(source, pinned.read_bytes(source, name))


def reaction_index(pinned: rs.PinnedReactionSet) -> ReactionIndex:
    """The decoded, indexed content of one pinned set (built once per set + file identity; one set kept)."""
    key = (pinned.set_hash, pinned.files_identity)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        mcsa_rows = _decode(pinned, "mcsa")
        uniprot_rows = _decode(pinned, "uniprot_function")
        rhea_rows = _decode(pinned, "rhea")
    except ValueError as exc:
        raise rs.SnapshotUnavailable("snapshot_invalid") from exc
    by_pdb: dict[str, list[int]] = {}
    for row in mcsa_rows:
        for pdb in sorted({member["pdb_id"] for residue in row["residues"] for member in residue["residue_chains"]}):
            by_pdb.setdefault(pdb, []).append(row["mcsa_id"])
    skipped = {item["accession"]: {"reason": item["reason"], "target_accessions": list(item["target_accessions"])}
               for item in pinned.manifest["skipped_accessions"]}
    index = ReactionIndex(pinned.set_hash, key, {row["mcsa_id"]: row for row in mcsa_rows},
                          {pdb: tuple(ids) for pdb, ids in by_pdb.items()},
                          {row["accession"]: row for row in uniprot_rows},
                          {row["rhea_id"]: row for row in rhea_rows}, skipped)
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()
        _INDEX_CACHE[key] = index
    return index


def pin_and_index(root: Path | None = None) -> tuple[rs.PinnedReactionSet, ReactionIndex]:
    pinned = rs.pin_active_set(root)
    return pinned, reaction_index(pinned)


def capability(root: Path | None = None) -> dict[str, Any]:
    """``methods.*`` shape with the content decoded: available, reason_code, reason, set_hash, sources."""
    try:
        pinned, _index = pin_and_index(root)
    except rs.SnapshotUnavailable as exc:
        return {"available": False, "reason_code": exc.reason_code, "reason": exc.reason, "set_hash": None,
                "sources": []}
    return {"available": True, "reason_code": None, "reason": None, "set_hash": pinned.set_hash,
            "sources": pinned.summary()}


def pdb_entries(index: ReactionIndex, pdb_id: str) -> list[dict[str, Any]]:
    wanted = pdb_id.lower()
    out = []
    for mcsa_id in index.mcsa_by_pdb.get(wanted, ()):
        row = index.mcsa[mcsa_id]
        chains = sorted({member["chain_name"] for residue in row["residues"] for member in residue["residue_chains"]
                         if member["pdb_id"] == wanted})
        out.append({"mcsa_id": mcsa_id, "enzyme_name": row["enzyme_name"],
                    "reference_uniprot_id": row["reference_uniprot_id"], "chains": chains})
    return out


def snapshot_set_record(pinned: rs.PinnedReactionSet) -> dict[str, Any]:
    manifest = pinned.manifest
    return {"set_hash": pinned.set_hash, "imported_at": manifest["imported_at"],
            "importer_version": manifest["importer_version"],
            "sources": [{"source": s["source"], "date": s["date"], "license": s["license"], "origin": s["origin"],
                         "files": [{k: f[k] for k in ("name", "sha256", "bytes", "rows")} for f in s["files"]]}
                        for s in manifest["sources"]],
            "requested_accessions": manifest["requested_accessions"],
            "skipped_accessions": manifest["skipped_accessions"]}


# ------------------------------------------------------------------------------------------- chain residues

def chain_polymer_residues(st: Any) -> dict[str, list[dict[str, Any]]]:
    found = _m15_chain_residues(st, _res_ref)
    return {chain: [{k: residue[k] for k in K.RESIDUE_FIELDS} for residue in value["residues"]]
            for chain, value in found.items()}


def _seven(residue: Mapping[str, Any]) -> dict[str, Any]:
    return {k: residue[k] for k in K.RESIDUE_FIELDS}


# ------------------------------------------------------------------------------------------- M-CSA (5.3)

@dataclass
class _Group:
    mcsa_id: int
    residue_index: int
    chain_name: str
    auth_resid: int | None
    residue: dict[str, Any]
    members: list[dict[str, Any]]


def _groups(entry_rows: Iterable[dict[str, Any]], pdb_lower: str, chain_auth: str) -> list[_Group]:
    """Candidates of (PDB ignoring case, chain) grouped by (mcsa_id, residue_index, chain_name, auth_resid)."""
    groups: dict[tuple, _Group] = {}
    for entry in entry_rows:
        for index, residue in enumerate(entry["residues"]):
            for member in residue["residue_chains"]:
                if member["pdb_id"].lower() != pdb_lower or member["chain_name"] != chain_auth:
                    continue
                key = (entry["mcsa_id"], index, member["chain_name"], member["auth_resid"])
                if key not in groups:
                    groups[key] = _Group(entry["mcsa_id"], index, member["chain_name"], member["auth_resid"],
                                         residue, [])
                groups[key].members.append(member)
    return list(groups.values())


def _listed(group: _Group) -> dict[str, Any]:
    first = group.members[0]
    return {"pdb_id": first["pdb_id"], "chain_name": group.chain_name, "resid": first["resid"],
            "auth_resid": group.auth_resid, "code": "/".join(sorted({m["code"] for m in group.members})),
            "assemblies": sorted({m["assembly"] for m in group.members if m["assembly"] is not None})}


def _reference(residue: Mapping[str, Any]) -> dict[str, Any]:
    return {"roles_summary": residue["roles_summary"], "function_location_abv": residue["function_location_abv"],
            "ptm": residue["ptm"], "roles": [dict(role) for role in residue["roles"]] if residue["roles"] else None}


def _fixed_part(group: _Group) -> dict[str, Any]:
    return {"mcsa_id": group.mcsa_id, "residue_index": group.residue_index,
            "is_reference": any(m["is_reference"] for m in group.members), "listed": _listed(group),
            "reference": _reference(group.residue)}


def _pre_status(group: _Group) -> tuple[str, str] | None:
    """Spec 5.3 steps 1-3 (no structure lookup); ``None`` when the structure decides."""
    codes = {m["code"] for m in group.members}
    if len(codes) > 1:
        return "conflict", "mcsa_rows_disagree"
    if group.auth_resid is None:
        return "unmatched", "no_author_number"
    (code,) = codes
    if code.upper() not in STANDARD_ONE_LETTER:
        return "unmatched", "non_standard_code"
    return None


def _structure_status(code: str, auth_resid: int, by_number: Mapping[int, Sequence[Mapping[str, Any]]]):
    """Spec 5.3 steps 4-5: (status, reason, residue | None, structure_resname | None)."""
    found = by_number.get(auth_resid, ())
    if not found:
        return "unmatched", "residue_not_in_structure", None, None
    if len(found) > 1:
        return "unmatched", "ambiguous_residue_number", None, None
    residue = found[0]
    if residue["icode"] != "":
        return "unmatched", "insertion_code_present", _seven(residue), residue["resname"]
    if standard_name(residue["resname"]) == code.upper():
        return "matched", None, _seven(residue), residue["resname"]
    return "conflict", "residue_name_differs", _seven(residue), residue["resname"]


def _row_key(row: Mapping[str, Any]) -> tuple:
    auth = row["listed"]["auth_resid"]
    return (row["mcsa_id"], row["residue_index"], auth is None, auth if auth is not None else 0,
            row["listed"]["code"])


def _entry_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"mcsa_id": row["mcsa_id"], "enzyme_name": row["enzyme_name"],
            "reference_uniprot_id": row["reference_uniprot_id"], "all_ecs": list(row["all_ecs"])}


def _row_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    return {status: sum(1 for r in rows if r["status"] == status) for status in K.ROW_STATUSES}


def mcsa_section(index: ReactionIndex, pdb_id: str | None, chain_auth: str,
                 residues: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if pdb_id is None:
        return dict(MCSA_NOT_CHECKED)
    pdb_lower = pdb_id.lower()
    ids = index.mcsa_by_pdb.get(pdb_lower, ())
    groups = _groups((index.mcsa[i] for i in ids), pdb_lower, chain_auth)
    if not groups:
        coverage = "chain_not_listed" if ids else "pdb_not_in_snapshot"
        return {"status": K.CHECKED, "reason": None, "coverage": coverage, "entries": None, "rows": None,
                "counts": None}
    by_number: dict[int, list[Mapping[str, Any]]] = {}
    for residue in residues:
        by_number.setdefault(residue["seq_auth"], []).append(residue)
    rows = []
    for group in groups:
        pre = _pre_status(group)
        if pre is not None:
            status, reason, found, resname = pre[0], pre[1], None, None
        else:
            status, reason, found, resname = _structure_status(group.members[0]["code"], group.auth_resid, by_number)
        fixed = _fixed_part(group)
        rows.append({"mcsa_id": fixed["mcsa_id"], "residue_index": fixed["residue_index"],
                     "is_reference": fixed["is_reference"], "listed": fixed["listed"], "status": status,
                     "reason": reason, "residue": found, "structure_resname": resname,
                     "reference": fixed["reference"]})
    rows.sort(key=_row_key)
    used = sorted({row["mcsa_id"] for row in rows})
    return {"status": K.CHECKED, "reason": None, "coverage": K.COVERED,
            "entries": [_entry_summary(index.mcsa[i]) for i in used], "rows": rows, "counts": _row_counts(rows)}


# ------------------------------------------------------------------------------------------- UniProt (5.4)

def map_accession(numbering_map: Mapping[str, Any], chain_auth: str) -> str | None:
    """The map chain's requested accession, else the single accession of its ``mapped`` rows, else ``None``."""
    for chain in numbering_map["chains"]:
        if chain["chain_auth"] == chain_auth and chain["requested_uniprot_accession"] is not None:
            return chain["requested_uniprot_accession"]
    found = {row["uniprot_accession"] for row in numbering_map["rows"]
             if row["residue"]["chain_auth"] == chain_auth and row["status"] == "mapped"}
    return next(iter(found)) if len(found) == 1 else None


def chain_accession(chain_auth: str, uniprot_accession: str | None,
                    numbering_map: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    if uniprot_accession is not None:
        return uniprot_accession, "user"
    if numbering_map is not None:
        derived = map_accession(numbering_map, chain_auth)
        if derived is not None:
            return derived, "numbering_map"
    return None, None


class _LinkCounter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total = 0

    def add(self, n: int) -> None:
        self.total += n
        if self.total > self.limit:
            raise TooManyLinks(f"more than {self.limit} linked site positions", limit=self.limit)


def _feature_base(feature: Mapping[str, Any]) -> dict[str, Any]:
    return {k: feature[k] for k in ("type", "start", "end", "description", "ligand_name", "ligand_id")}


def _link_state(numbering_map: Mapping[str, Any] | None, chain_auth: str, accession: str) -> tuple:
    if numbering_map is None:
        return None, "numbering_map_not_given"
    if not any(chain["chain_auth"] == chain_auth for chain in numbering_map["chains"]):
        return None, "chain_not_in_map"
    if map_accession(numbering_map, chain_auth) != accession:
        return None, "map_accession_differs"
    return "numbering_map", None


def uniprot_section(index: ReactionIndex, accession: str | None, chain_auth: str,
                    numbering_map: Mapping[str, Any] | None, *, counter: _LinkCounter | None = None) -> dict:
    if accession is None:
        return dict(UNIPROT_NOT_CHECKED)
    row = index.uniprot.get(accession)
    if row is None:
        skipped = index.skipped.get(accession)
        return {"status": K.NOT_AVAILABLE,
                "reason": "accession_skipped_at_import" if skipped is not None else "accession_not_in_snapshot",
                "skipped": copy.deepcopy(skipped), "entry": None, "linked_via": None, "link_reason": None,
                "features": None}
    counter = counter if counter is not None else _LinkCounter(K.MAX_LINKS)
    linked_via, link_reason = _link_state(numbering_map, chain_auth, accession)
    by_position: dict[int, list[Mapping[str, Any]]] = {}
    if linked_via is not None:
        for map_row in numbering_map["rows"]:
            if (map_row["residue"]["chain_auth"] == chain_auth and map_row["status"] == "mapped"
                    and map_row["uniprot_accession"] == accession):
                by_position.setdefault(map_row["uniprot_position"], []).append(map_row)
    features = []
    for feature in row["features"]:
        links = None
        if linked_via is not None:
            links = []
            for q in range(feature["start"], feature["end"] + 1):
                found = by_position.get(q)
                if found:
                    counter.add(len(found))
                    links.extend({"position": q, "status": "mapped", "residue": _seven(m["residue"]),
                                  "uniprot_residue": m["uniprot_residue"], "residue_match": m["residue_match"]}
                                 for m in found)
                else:
                    counter.add(1)
                    links.append({"position": q, "status": "not_in_map", "residue": None, "uniprot_residue": None,
                                  "residue_match": None})
        features.append({**_feature_base(feature), "links": links})
    return {"status": K.CHECKED, "reason": None, "skipped": None,
            "entry": {k: row[k] for k in ("accession", "entry_name", "protein_name", "organism", "sequence_length")},
            "linked_via": linked_via, "link_reason": link_reason, "features": features}


def _flags(accession: str | None, mcsa: Mapping[str, Any], mcsa_rows: Mapping[int, Mapping[str, Any]]) -> list:
    if accession is None or mcsa["coverage"] != K.COVERED:
        return []
    named = {acc for entry in mcsa["entries"] for acc in K.entry_accessions(mcsa_rows[entry["mcsa_id"]])}
    return [] if accession in named else ["accession_differs_from_mcsa"]


def chain_flags(index: ReactionIndex, accession: str | None, mcsa: Mapping[str, Any]) -> list[str]:
    return _flags(accession, mcsa, index.mcsa)


# ------------------------------------------------------------------------------------------- reactions (5.5)

def _reactions(mcsa_rows: Sequence[Mapping[str, Any]] | None, uniprot_row: Mapping[str, Any] | None,
               in_snapshot: Callable[[str], bool]) -> dict[str, Any]:
    if mcsa_rows is None and uniprot_row is None:
        return dict(REACTIONS_NOT_CHECKED)
    ecs = {"mcsa": None, "uniprot": None}
    compounds = activities = None
    if mcsa_rows is not None:
        found = {ec for row in mcsa_rows for ec in row["all_ecs"]}
        found.update(row["reaction"]["ec"] for row in mcsa_rows if row["reaction"]["ec"] is not None)
        ecs["mcsa"] = sorted(found)
        compounds = [{"mcsa_id": row["mcsa_id"], "ec": row["reaction"]["ec"],
                      "compounds": [{"type": c["type"], "chebi_id": c["chebi_id"], "name": c["name"]}
                                    for c in row["reaction"]["compounds"]]} for row in mcsa_rows]
    if uniprot_row is not None:
        found = set(uniprot_row["ec_numbers"])
        found.update(a["ec_number"] for a in uniprot_row["catalytic_activities"] if a["ec_number"] is not None)
        ecs["uniprot"] = sorted(found)
        activities = [{"reaction_name": a["reaction_name"], "ec_number": a["ec_number"],
                       "rhea": [{"rhea_id": rid, "in_snapshot": in_snapshot(rid)} for rid in a["rhea_ids"]]}
                      for a in uniprot_row["catalytic_activities"]]
    return {"status": K.CHECKED, "reason": None, "ecs": ecs, "mcsa_compounds": compounds,
            "uniprot_activities": activities}


def reactions_section(index: ReactionIndex, mcsa: Mapping[str, Any], uniprot: Mapping[str, Any]) -> dict[str, Any]:
    """M-CSA contributes when the chain is covered, UniProt when its section is checked (Rhea only through UniProt
    catalytic activities, never widened from EC numbers)."""
    mcsa_rows = ([index.mcsa[e["mcsa_id"]] for e in mcsa["entries"]] if mcsa["coverage"] == K.COVERED else None)
    uniprot_row = index.uniprot[uniprot["entry"]["accession"]] if uniprot["status"] == K.CHECKED else None
    return _reactions(mcsa_rows, uniprot_row, lambda rid: rid in index.rhea)


# ------------------------------------------------------------------------------------------- result (5.6)

def _rhea_order(rhea_id: str) -> int:
    return int(rhea_id.split(":", 1)[1])


def _reference_rows(chains: Sequence[Mapping[str, Any]], mcsa: Mapping[int, Any], uniprot: Mapping[str, Any],
                    rhea: Mapping[str, Any]) -> dict[str, list]:
    mcsa_ids = sorted({e["mcsa_id"] for c in chains if c["mcsa"]["coverage"] == K.COVERED
                       for e in c["mcsa"]["entries"]})
    accessions = sorted({c["uniprot"]["entry"]["accession"] for c in chains if c["uniprot"]["status"] == K.CHECKED})
    rhea_ids = sorted({link["rhea_id"] for c in chains for a in (c["reactions"]["uniprot_activities"] or [])
                       for link in a["rhea"] if link["in_snapshot"]}, key=_rhea_order)
    return {"mcsa": [mcsa[i] for i in mcsa_ids], "uniprot": [uniprot[a] for a in accessions],
            "rhea": [rhea[r] for r in rhea_ids]}


def _counts(chains: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    covered = [c for c in chains if c["mcsa"]["coverage"] == K.COVERED]
    checked = [c for c in chains if c["uniprot"]["status"] == K.CHECKED]
    linked = [f for c in checked for f in c["uniprot"]["features"] if f["links"] is not None]
    with_activities = [c for c in chains if c["reactions"]["uniprot_activities"] is not None]
    rhea = {link["rhea_id"]: link["in_snapshot"] for c in with_activities
            for a in c["reactions"]["uniprot_activities"] for link in a["rhea"]}
    return {
        "chains": len(chains),
        "covered_chains": len(covered),
        "mcsa_rows": ({s: sum(c["mcsa"]["counts"][s] for c in covered) for s in K.ROW_STATUSES}
                      if covered else None),
        "mcsa_entries": len({e["mcsa_id"] for c in covered for e in c["mcsa"]["entries"]}) if covered else None,
        "uniprot_features": ({t: sum(1 for c in checked for f in c["uniprot"]["features"] if f["type"] == t)
                              for t in K.SITE_TYPES} if checked else None),
        "linked_positions": ({s: sum(1 for f in linked for link in f["links"] if link["status"] == s)
                              for s in K.LINK_STATUSES} if linked else None),
        "rhea": ({"in_snapshot": sum(1 for v in rhea.values() if v),
                  "not_in_snapshot": sum(1 for v in rhea.values() if not v)} if with_activities else None),
    }


def _empty(value: Any) -> bool:
    return value is None or value == []


def _null_result(chains: Sequence[Mapping[str, Any]]) -> bool:
    for c in chains:
        reactions = c["reactions"]
        if c["mcsa"]["rows"] is not None or not _empty(c["uniprot"]["features"]):
            return False
        if reactions["ecs"] is not None and not all(_empty(v) for v in reactions["ecs"].values()):
            return False
        if not _empty(reactions["mcsa_compounds"]) or not _empty(reactions["uniprot_activities"]):
            return False
    return True


def build_reaction_knowledge(*, pinned: rs.PinnedReactionSet, index: ReactionIndex, structure_handle: str,
                             structure_kind: str, model_number: int, pdb_id: str | None,
                             chains: Sequence[Mapping[str, Any]],
                             chain_residues: Mapping[str, Sequence[Mapping[str, Any]]],
                             numbering_map: Mapping[str, Any] | None = None,
                             numbering_map_handle: str | None = None) -> dict[str, Any]:
    """The ``reaction_knowledge@1`` content (deterministic for the same inputs and set; no time or call ID)."""
    if index.set_hash != pinned.set_hash:
        raise ValueError("the index belongs to another pinned set")
    if (numbering_map is None) != (numbering_map_handle is None):
        raise ValueError("numbering_map and numbering_map_handle go together")
    counter = _LinkCounter(K.MAX_LINKS)
    chains_out = []
    for item in chains:
        chain_auth = item["chain_auth"]
        residues = chain_residues.get(chain_auth)
        if not residues:
            raise ValueError(f"chain {chain_auth!r} has no polymer residues (the tool refuses chain_not_found)")
        accession, source = chain_accession(chain_auth, item["uniprot_accession"], numbering_map)
        mcsa = mcsa_section(index, pdb_id, chain_auth, residues)
        uniprot = uniprot_section(index, accession, chain_auth, numbering_map, counter=counter)
        chains_out.append({"chain_auth": chain_auth, "polymer_residue_count": len(residues), "accession": accession,
                           "accession_source": source, "mcsa": mcsa, "uniprot": uniprot,
                           "reactions": reactions_section(index, mcsa, uniprot),
                           "flags": chain_flags(index, accession, mcsa)})
    result = {
        "schema": K.SCHEMA,
        "method_version": K.METHOD_VERSION,
        "structure": {"handle": structure_handle, "structure_kind": structure_kind, "model_number": model_number},
        "pdb_id": pdb_id,
        "numbering_map": (None if numbering_map is None
                          else {"handle": numbering_map_handle, "pdb_id": numbering_map["pdb_id"]}),
        "snapshot_set": snapshot_set_record(pinned),
        "chains": chains_out,
        "reference_rows": _reference_rows(chains_out, index.mcsa, index.uniprot, index.rhea),
        "counts": _counts(chains_out),
        "null_result": _null_result(chains_out),
        "limitations": list(K.LIMITATIONS),
    }
    size = len(K.canonical_json(result))
    if size > K.MAX_RESULT_BYTES:
        raise ResultTooLarge(f"result is {size} bytes, above {K.MAX_RESULT_BYTES}", limit=K.MAX_RESULT_BYTES,
                             actual=size)
    return copy.deepcopy(result)  # never share rows with the cached index


# ------------------------------------------------------------------------------------------- validation

def _fail(message: str) -> None:
    raise ResultInvalid(message)


def _same(a: Any, b: Any) -> bool:
    """Equal with exact JSON types (``2`` vs ``2.0``, ``1`` vs ``true`` differ)."""
    return K.canonical_json(a) == K.canonical_json(b)


def _keys(obj: Any, keys: frozenset, where: str) -> None:
    if type(obj) is not dict or set(obj) != keys:
        _fail(f"{where}: keys differ")


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _check_residue(residue: Any, chain_auth: str, model_number: int, where: str) -> None:
    if type(residue) is not dict or set(residue) != set(K.RESIDUE_FIELDS):
        _fail(f"{where}: residue must have the 7 identity fields")
    if (type(residue["model_number"]) is not int or residue["model_number"] != model_number
            or residue["chain_auth"] != chain_auth
            or not (residue["chain_label"] is None or type(residue["chain_label"]) is str)
            or type(residue["seq_auth"]) is not int
            or not (residue["seq_label"] is None or type(residue["seq_label"]) is int)
            or type(residue["icode"]) is not str or type(residue["resname"]) is not str or not residue["resname"]):
        _fail(f"{where}: residue identity of another chain/model or with wrong types")


@dataclass(frozen=True)
class _Refs:
    mcsa_rows: list
    mcsa: dict
    uniprot: dict
    rhea: dict


def _validate_reference_rows(value: Any) -> _Refs:
    _keys(value, frozenset({"mcsa", "uniprot", "rhea"}), "reference_rows")
    for source, key in (("mcsa", "mcsa"), ("uniprot_function", "uniprot"), ("rhea", "rhea")):
        if type(value[key]) is not list:
            _fail(f"reference_rows.{key}: expected a list")
        K.encode_jsonl(source, value[key])  # every row in its processed format and the fixed order
    return _Refs(value["mcsa"], {r["mcsa_id"]: r for r in value["mcsa"]},
                 {r["accession"]: r for r in value["uniprot"]}, {r["rhea_id"]: r for r in value["rhea"]})


def _validate_snapshot_set(value: Any) -> None:
    _keys(value, frozenset({"set_hash", "imported_at", "importer_version", "sources", "requested_accessions",
                            "skipped_accessions"}), "snapshot_set")
    if (type(value["set_hash"]) is not str or not re.fullmatch(K.HEX64_PATTERN, value["set_hash"])
            or type(value["imported_at"]) is not str
            or not re.fullmatch(K.IMPORTED_AT_PATTERN, value["imported_at"])
            or value["importer_version"] != K.IMPORTER_VERSION):
        _fail("snapshot_set: header")
    sources = value["sources"]
    if type(sources) is not list or [s.get("source") if type(s) is dict else None for s in sources] != list(K.SOURCES):
        _fail("snapshot_set.sources: expected mcsa, uniprot_function, rhea")
    for record in sources:
        _keys(record, frozenset({"source", "date", "license", "origin", "files"}), "snapshot_set.sources[]")
        if (type(record["date"]) is not str or not re.fullmatch(K.DATE_PATTERN, record["date"])
                or record["license"] != K.LICENSE or record["origin"] != K.ORIGIN
                or type(record["files"]) is not list
                or [f.get("name") if type(f) is dict else None for f in record["files"]]
                != list(K.SOURCE_FILES[record["source"]])):
            _fail("snapshot_set.sources[]: values")
        for entry in record["files"]:
            _keys(entry, frozenset({"name", "sha256", "bytes", "rows"}), "snapshot_set.sources[].files[]")
            if (type(entry["sha256"]) is not str or not re.fullmatch(K.HEX64_PATTERN, entry["sha256"])
                    or not _count(entry["bytes"]) or not _count(entry["rows"])):
                _fail("snapshot_set.sources[].files[]: values")
    K.validate_requested_accessions(value["requested_accessions"])
    K.validate_skipped_accessions(value["skipped_accessions"])
    if ({s["accession"] for s in value["skipped_accessions"]}
            & set(value["requested_accessions"]["user_named"])):
        _fail("snapshot_set: a user-named accession is listed as skipped")


def _check_structure_row(row: Mapping[str, Any], group: _Group, chain_auth: str, model_number: int) -> None:
    pair = (row["status"], row["reason"])
    if pair not in _STRUCTURE_STEPS:
        _fail("mcsa row: status/reason not reachable for this group")
    residue, resname = row["residue"], row["structure_resname"]
    if pair in {("unmatched", "residue_not_in_structure"), ("unmatched", "ambiguous_residue_number")}:
        if residue is not None or resname is not None:
            _fail("mcsa row: no residue for this reason")
        return
    _check_residue(residue, chain_auth, model_number, "mcsa row")
    if residue["seq_auth"] != group.auth_resid or resname != residue["resname"]:
        _fail("mcsa row: residue number or name differs from the row")
    if pair == ("unmatched", "insertion_code_present"):
        if residue["icode"] == "":
            _fail("mcsa row: insertion_code_present without an insertion code")
        return
    if residue["icode"] != "":
        _fail("mcsa row: a residue with an insertion code is never compared by name")
    same = standard_name(residue["resname"]) == group.members[0]["code"].upper()
    if same != (pair == ("matched", None)):
        _fail("mcsa row: matched/residue_name_differs disagrees with the names")


def _validate_mcsa(section: Any, chain_auth: str, pdb_id: str | None, model_number: int, refs: _Refs) -> None:
    _keys(section, MCSA_KEYS, "mcsa")
    if pdb_id is None:
        if not _same(section, MCSA_NOT_CHECKED):
            _fail("mcsa: a request without a PDB ID is not checked")
        return
    if section["status"] != K.CHECKED or section["reason"] is not None or section["coverage"] not in K.COVERAGE:
        _fail("mcsa: status/reason/coverage")
    groups = _groups(refs.mcsa_rows, pdb_id.lower(), chain_auth)
    if section["coverage"] != K.COVERED:
        if any(section[k] is not None for k in ("entries", "rows", "counts")) or groups:
            _fail("mcsa: an uncovered chain has null entries/rows/counts and no listed rows")
        return
    rows = section["rows"]
    if type(rows) is not list or not rows or len(rows) != len(groups):
        _fail("mcsa: rows differ from the reference rows of this chain")
    ordered = sorted(groups, key=lambda g: _row_key(_fixed_part(g)))
    for row, group in zip(rows, ordered):
        _keys(row, ROW_KEYS, "mcsa row")
        expected = _fixed_part(group)
        if not _same({k: row[k] for k in expected}, expected):
            _fail("mcsa row: identity, listed or reference values differ from the reference rows")
        pre = _pre_status(group)
        if pre is not None:
            if ((row["status"], row["reason"]) != pre or row["residue"] is not None
                    or row["structure_resname"] is not None):
                _fail("mcsa row: status/reason differs from the rule for this group")
        else:
            _check_structure_row(row, group, chain_auth, model_number)
    used = sorted({row["mcsa_id"] for row in rows})
    if not _same(section["entries"], [_entry_summary(refs.mcsa[i]) for i in used]):
        _fail("mcsa: entries differ from the rows")
    if not _same(section["counts"], _row_counts(rows)):
        _fail("mcsa: counts differ from the rows")


def _check_links(links: Any, start: int, end: int, chain_auth: str, model_number: int) -> None:
    if type(links) is not list or not links:
        _fail("links: expected a non-empty list")
    by_position: dict[int, list] = {}
    previous = None
    for link in links:
        _keys(link, LINK_KEYS, "link")
        q = link["position"]
        if type(q) is not int or (previous is not None and q < previous):
            _fail("links: positions must ascend")
        previous = q
        by_position.setdefault(q, []).append(link)
    if list(by_position) != list(range(start, end + 1)):
        _fail("links: every site position appears once in order")
    for items in by_position.values():
        statuses = {link["status"] for link in items}
        if statuses == {"not_in_map"}:
            if len(items) != 1 or any(items[0][k] is not None for k in ("residue", "uniprot_residue",
                                                                         "residue_match")):
                _fail("links: not_in_map is one element without values")
        elif statuses == {"mapped"}:
            for link in items:
                _check_residue(link["residue"], chain_auth, model_number, "link")
                if not (link["uniprot_residue"] is None or type(link["uniprot_residue"]) is str):
                    _fail("links: uniprot_residue")
                if not (link["residue_match"] is None or type(link["residue_match"]) is bool):
                    _fail("links: residue_match")
        else:
            _fail("links: closed status set, one kind per position")


def _validate_uniprot(section: Any, chain: Mapping[str, Any], numbering_map: Any, model_number: int, refs: _Refs,
                      skipped: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
    _keys(section, UNIPROT_KEYS, "uniprot")
    accession = chain["accession"]
    if accession is None:
        if not _same(section, UNIPROT_NOT_CHECKED):
            _fail("uniprot: a chain without an accession is not checked")
        return None
    if section["status"] == K.NOT_AVAILABLE:
        item = skipped.get(accession)
        expected = {"status": K.NOT_AVAILABLE,
                    "reason": "accession_skipped_at_import" if item is not None else "accession_not_in_snapshot",
                    "skipped": None if item is None else {"reason": item["reason"],
                                                          "target_accessions": item["target_accessions"]},
                    "entry": None, "linked_via": None, "link_reason": None, "features": None}
        if accession in refs.uniprot or not _same(section, expected):
            _fail("uniprot: not_available differs from the snapshot record")
        return None
    if section["status"] != K.CHECKED or section["reason"] is not None or section["skipped"] is not None:
        _fail("uniprot: status/reason/skipped")
    row = refs.uniprot.get(accession)
    if row is None:
        _fail("uniprot: a checked accession has its reference row")
    entry = {k: row[k] for k in ("accession", "entry_name", "protein_name", "organism", "sequence_length")}
    if not _same(section["entry"], entry):
        _fail("uniprot: entry differs from the reference row")
    linked = section["linked_via"] == "numbering_map"
    if linked:
        if section["link_reason"] is not None or numbering_map is None:
            _fail("uniprot: a link needs the numbering map")
    elif section["linked_via"] is None:
        if section["link_reason"] not in K.LINK_REASONS:
            _fail("uniprot: link_reason")
        if (section["link_reason"] == "numbering_map_not_given") != (numbering_map is None):
            _fail("uniprot: link_reason disagrees with the numbering map")
        if chain["accession_source"] == "numbering_map":
            _fail("uniprot: an accession taken from the map always links")
    else:
        _fail("uniprot: linked_via")
    features = section["features"]
    if type(features) is not list or len(features) != len(row["features"]):
        _fail("uniprot: features differ from the reference row")
    for stored, base in zip(features, row["features"]):
        _keys(stored, FEATURE_KEYS, "feature")
        if not _same({k: stored[k] for k in base}, _feature_base(base)):
            _fail("uniprot: feature values differ from the reference row")
        if not linked:
            if stored["links"] is not None:
                _fail("uniprot: no links without a numbering map link")
        else:
            _check_links(stored["links"], base["start"], base["end"], chain["chain_auth"], model_number)
    return row


def _validate_chain(chain: Any, obj: Mapping[str, Any], refs: _Refs, skipped: Mapping[str, Any]) -> None:
    _keys(chain, CHAIN_KEYS, "chain")
    chain_auth = chain["chain_auth"]
    model_number = obj["structure"]["model_number"]
    if type(chain_auth) is not str or not chain_auth:
        _fail("chain_auth")
    if type(chain["polymer_residue_count"]) is not int or chain["polymer_residue_count"] < 1:
        _fail("polymer_residue_count")
    accession, source = chain["accession"], chain["accession_source"]
    if accession is None:
        if source is not None:
            _fail("accession_source without an accession")
    elif not K.is_accession(accession) or source not in K.ACCESSION_SOURCES:
        _fail("accession / accession_source")
    if source == "numbering_map" and obj["numbering_map"] is None:
        _fail("accession_source numbering_map without a numbering map")
    _validate_mcsa(chain["mcsa"], chain_auth, obj["pdb_id"], model_number, refs)
    uniprot_row = _validate_uniprot(chain["uniprot"], chain, obj["numbering_map"], model_number, refs, skipped)
    mcsa = chain["mcsa"]
    mcsa_rows = [refs.mcsa[e["mcsa_id"]] for e in mcsa["entries"]] if mcsa["coverage"] == K.COVERED else None
    _keys(chain["reactions"], REACTIONS_KEYS, "reactions")
    if not _same(chain["reactions"], _reactions(mcsa_rows, uniprot_row, lambda rid: rid in refs.rhea)):
        _fail("reactions differ from the reference rows")
    if not _same(chain["flags"], _flags(accession, mcsa, refs.mcsa)):
        _fail("flags")


def _validate(obj: Any) -> None:
    _keys(obj, TOP_KEYS, "result")
    if obj["schema"] != K.SCHEMA or obj["method_version"] != K.METHOD_VERSION:
        _fail("schema / method_version")
    structure = obj["structure"]
    _keys(structure, frozenset({"handle", "structure_kind", "model_number"}), "structure")
    match = _HANDLE.fullmatch(structure["handle"]) if type(structure["handle"]) is str else None
    if (match is None or structure["structure_kind"] not in STRUCTURE_KINDS
            or match.group(2) != structure["structure_kind"] or type(structure["model_number"]) is not int):
        _fail("structure")
    pdb_id = obj["pdb_id"]
    if pdb_id is not None and (type(pdb_id) is not str or not _RESULT_PDB_ID.fullmatch(pdb_id)):
        _fail("pdb_id")
    nmap = obj["numbering_map"]
    if nmap is not None:
        _keys(nmap, frozenset({"handle", "pdb_id"}), "numbering_map")
        found = _HANDLE.fullmatch(nmap["handle"]) if type(nmap["handle"]) is str else None
        if (found is None or found.group(2) != MAP_KIND or found.group(1) != match.group(1)
                or not (nmap["pdb_id"] is None or (type(nmap["pdb_id"]) is str
                                                    and _RESULT_PDB_ID.fullmatch(nmap["pdb_id"])))
                or (nmap["pdb_id"] is not None and pdb_id is not None and nmap["pdb_id"] != pdb_id)):
            _fail("numbering_map")
    _validate_snapshot_set(obj["snapshot_set"])
    refs = _validate_reference_rows(obj["reference_rows"])
    chains = obj["chains"]
    if type(chains) is not list or not chains:
        _fail("chains: expected a non-empty list")
    names = [c.get("chain_auth") if type(c) is dict else None for c in chains]
    if len(set(names)) != len(names):
        _fail("chains: duplicate chain_auth")
    skipped = {item["accession"]: item for item in obj["snapshot_set"]["skipped_accessions"]}
    for chain in chains:
        _validate_chain(chain, obj, refs, skipped)
    coverages = {c["mcsa"]["coverage"] for c in chains if c["mcsa"]["status"] == K.CHECKED}
    if "pdb_not_in_snapshot" in coverages and len(coverages) > 1:
        _fail("mcsa: a PDB is either in the snapshot for every chain or for none")
    if not _same(obj["reference_rows"], _reference_rows(chains, refs.mcsa, refs.uniprot, refs.rhea)):
        _fail("reference_rows are exactly the rows the result uses")
    _keys(obj["counts"], COUNTS_KEYS, "counts")
    if not _same(obj["counts"], _counts(chains)):
        _fail("counts differ from the chains")
    if obj["null_result"] is not _null_result(chains):
        _fail("null_result")
    if not _same(obj["limitations"], list(K.LIMITATIONS)):
        _fail("limitations must be RK1-RK5 verbatim and in order")


def validated_result(obj: Any) -> Any:
    """``obj`` when it is a valid ``reaction_knowledge@1`` content; ``ResultInvalid`` otherwise (pure)."""
    try:
        _validate(obj)
    except ResultInvalid:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise ResultInvalid(f"malformed result: {exc}") from exc
    return obj
