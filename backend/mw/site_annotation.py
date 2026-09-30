"""M16 reference site annotation: one ``residue_numbering_map@1`` + optional ``interaction_set@1`` -> per-site record.

Pure logic over already loaded objects; the tool wrapper (``mw.tools.site_annotation``) owns validation order,
failure classes and object storage. Nothing here reads the reference folder, a structure file or the network.

* Sites: the fixed ``kinase_key_sites@1`` list (``SITES``), recorded verbatim in every result.
* Groups: one per ``(chain_auth, accession)`` of the map's ``chains[].klifs`` entries; a chain without a mapped
  accession gets one ``accession: null`` group (``klifs_absent_reason: no_mapped_accession``).
* Site status is ``annotated | absent``. ``annotated`` needs exactly one row of the group with ``status == mapped``,
  the group's accession and the site's KLIFS index (two or more -> ``AnnotationInvalid duplicate_site_residue``).
  ``absent`` takes the first matching reason of ``ABSENT_REASONS`` (in that order).
* Contacts: rows are matched to a site residue by all 7 identity fields (null included). Counts are per computed
  contact type; a type the contact result did not compute is ``count: null``; a residue the contact tool does not
  check (not a polymer record, ``category != "polymer"``) is ``assessed: false`` with null counts and distances.
  Every distance is the stored row value, never recomputed.
* Read for the API (no event, no tool): ``list_annotations``.
"""
from __future__ import annotations

from typing import Any

from .klifs_numbering import GAP_CHARS, KLIFS_REGIONS

SCHEMA = "reference_site_annotation@1"
KIND = "reference_site_annotation"
METHOD_VERSION = "mw.site_annotation/v1"
SITE_SET_ID = "kinase_key_sites@1"
SITES: tuple[tuple[int, str], ...] = (
    (17, "III.17"), (24, "αC.24"), (45, "GK.45"), (46, "hinge.46"), (47, "hinge.47"), (48, "hinge.48"),
    (80, "xDFG.80"), (81, "xDFG.81"), (82, "xDFG.82"), (83, "xDFG.83"),
)
SITE_LABELS = dict(SITES)
STATUSES = ("annotated", "absent")
ABSENT_REASONS = ("klifs_not_applied", "pocket_gap", "region_unresolved", "no_mapped_residue")
GROUP_ABSENT_REASONS = ("accession_not_in_klifs", "klifs_pocket_empty", "klifs_multiple_entries",
                        "uniprot_sequence_unavailable", "no_mapped_accession")
CONTACT_TYPES = ("contact", "polar_contact", "hydrophobic_contact")
NOT_ASSESSED_REASON = "residue_not_checked_by_contact_method"
LIMITATIONS = (
    "기하 접촉은 중원자 사이 거리만으로 정한 것이며 수소결합이나 화학 상호작용 판정이 아니다.",
    "KLIFS 번호는 참조 스냅샷 값이며 잔기의 역할을 뜻하지 않는다.",
    "없음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이다.",
    "접촉 도구는 폴리머 레코드 잔기만 검사하므로 HETATM 변형 잔기는 검사하지 않는다.",
)
IDENTITY_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
STANDARD_RESIDUES = frozenset({"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS",
                               "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"})
_REGION_OF = {index: region for region, first, last in KLIFS_REGIONS for index in range(first, last + 1)}


class AnnotationInvalid(Exception):
    """Input the tool must refuse before running (``input_invalid`` with ``reason_code``)."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


def site_set() -> dict[str, Any]:
    return {"id": SITE_SET_ID, "sites": [{"klifs_index": i, "klifs_label": label} for i, label in SITES]}


def identity(residue: dict[str, Any]) -> tuple[Any, ...]:
    """The 7-field residue identity with exact types (``1`` and ``True`` or ``""`` and ``None`` never compare equal)."""
    return tuple((type(residue[k]), residue[k]) for k in IDENTITY_FIELDS)


def display_label(residue: dict[str, Any], klifs_label: str) -> str:
    """``Met318 (hinge.47)``; a non-standard residue name (``MSE``) is kept as is; the insertion code follows."""
    name = residue["resname"]
    shown = name.capitalize() if name in STANDARD_RESIDUES else name
    return f"{shown}{residue['seq_auth']}{residue['icode']} ({klifs_label})"


def _pocket(map_content: dict[str, Any], accession: str) -> str | None:
    for item in map_content["reference_rows"]["klifs"]:
        if item["accession"] == accession:
            entries = item["entries"]
            return entries[0]["pocket"] if len(entries) == 1 else None
    return None


def _absent(index: int, label: str, reason: str) -> dict[str, Any]:
    return {"klifs_index": index, "klifs_label": label, "status": "absent", "absent_reason": reason,
            "residue": None, "map_row_index": None, "residue_match": None, "klifs_match": None,
            "display_label": None, "contact": None}


def site_groups(map_content: dict[str, Any]) -> list[dict[str, Any]]:
    """The groups with site status (``contact`` left null). Raises ``AnnotationInvalid`` on a duplicate site row."""
    groups = []
    for chain in map_content["chains"]:
        chain_auth = chain["chain_auth"]
        rows = [(i, r) for i, r in enumerate(map_content["rows"]) if r["residue"]["chain_auth"] == chain_auth]
        entries = chain["klifs"] or [None]
        for entry in entries:
            if entry is None:
                accession, applied, reason, unresolved, pocket = None, False, "no_mapped_accession", [], None
            else:
                accession, applied = entry["accession"], entry["applied"] is True
                reason = None if applied else entry["absent_reason"]
                unresolved, pocket = entry["unresolved_regions"], _pocket(map_content, accession)
            sites = []
            for index, label in SITES:
                if not applied:
                    sites.append(_absent(index, label, "klifs_not_applied"))
                    continue
                found = [(i, r) for i, r in rows if r["status"] == "mapped" and r["uniprot_accession"] == accession
                         and r["klifs_index"] == index]
                if len(found) > 1:
                    raise AnnotationInvalid("duplicate_site_residue",
                                            f"chain {chain_auth} accession {accession}: {len(found)} mapped rows "
                                            f"carry KLIFS {label}")
                if found:
                    row_index, row = found[0]
                    sites.append({"klifs_index": index, "klifs_label": row["klifs_label"], "status": "annotated",
                                  "absent_reason": None, "residue": dict(row["residue"]),
                                  "map_row_index": row_index, "residue_match": row["residue_match"],
                                  "klifs_match": row["klifs_match"],
                                  "display_label": display_label(row["residue"], row["klifs_label"]),
                                  "contact": None})
                elif pocket is not None and pocket[index - 1] in GAP_CHARS:
                    sites.append(_absent(index, label, "pocket_gap"))
                elif _REGION_OF[index] in unresolved:
                    sites.append(_absent(index, label, "region_unresolved"))
                else:
                    sites.append(_absent(index, label, "no_mapped_residue"))
            groups.append({"chain_auth": chain_auth, "accession": accession, "klifs_applied": applied,
                           "klifs_absent_reason": reason, "sites": sites})
    return groups


def _site_contact(residue: dict[str, Any], assessed: bool, rows: list[dict[str, Any]],
                  types: list[str]) -> dict[str, Any]:
    if not assessed:
        return {"assessed": False, "not_assessed_reason": NOT_ASSESSED_REASON,
                "by_type": {t: {"computed": t in types, "count": None} for t in CONTACT_TYPES},
                "min_distance_A": None, "min_distance_row_index": None, "polar_pairs": None}
    key = identity(residue)
    mine = [(i, r) for i, r in enumerate(rows) if identity(r["residue"]) == key]
    by_type = {t: {"computed": t in types, "count": sum(1 for _, r in mine if r["type"] == t) if t in types else None}
               for t in CONTACT_TYPES}
    minimum = row_index = None
    for i, r in mine:   # rows in stored order: a later equal minimum never replaces the lowest row index
        if minimum is None or r["distance_A"] < minimum:
            minimum, row_index = r["distance_A"], i
    polar = None
    if "polar_contact" in types:
        polar = [{"contact_row_index": i, "protein_atom": r["protein_atom"], "ligand_atom": r["ligand_atom"],
                  "distance_A": r["distance_A"]} for i, r in mine if r["type"] == "polar_contact"]
    return {"assessed": True, "not_assessed_reason": None, "by_type": by_type, "min_distance_A": minimum,
            "min_distance_row_index": row_index, "polar_pairs": polar}


def build_annotation(numbering_map: str, map_content: dict[str, Any], structure_residues: list[dict[str, Any]],
                     contacts: str | None, contacts_content: dict[str, Any] | None) -> dict[str, Any]:
    """The ``reference_site_annotation@1`` content (deterministic for the same inputs)."""
    groups = site_groups(map_content)
    contacts_record = other = None
    if contacts is not None:
        types = list(contacts_content["parameters"]["types"])
        rows = contacts_content["rows"]
        polymer = {identity(r) for r in structure_residues if r["category"] == "polymer"}
        known = {identity(r) for r in structure_residues}
        annotated: set[tuple[Any, ...]] = set()
        for group in groups:
            for site in group["sites"]:
                if site["status"] != "annotated":
                    continue
                key = identity(site["residue"])
                if key not in known:
                    raise ValueError("site residue is not a residue of the mapped structure")
                annotated.add(key)
                site["contact"] = _site_contact(site["residue"], key in polymer, rows, types)
        other_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        for i, row in enumerate(rows):
            key = identity(row["residue"])
            if key not in annotated:
                item = other_by_key.setdefault(key, {"residue": dict(row["residue"]), "row_indexes": []})
                item["row_indexes"].append(i)
        other = list(other_by_key.values())
        contacts_record = {"handle": contacts, "ligand": dict(contacts_content["selection"]["ligand"]),
                           "cutoff_A": contacts_content["parameters"]["cutoff_A"], "types": types}
    return {
        "schema": SCHEMA,
        "method_version": METHOD_VERSION,
        "site_set": site_set(),
        "numbering_map": numbering_map,
        "snapshot_set_hash": map_content["snapshot_set"]["set_hash"],
        "structure": dict(map_content["structure"]),
        "contacts": contacts_record,
        "groups": groups,
        "other_contact_residues": other,
        "null_result": not any(s["status"] == "annotated" for g in groups for s in g["sites"]),
        "limitations": list(LIMITATIONS),
    }


def counts(content: dict[str, Any]) -> dict[str, int]:
    sites = [s for g in content["groups"] for s in g["sites"]]
    return {status: sum(1 for s in sites if s["status"] == status) for status in STATUSES}


# ---------------------------------------------------------------------------------------------------------------
# reads (no event, no tool call)

def list_annotations(run: Any, structure: str | None, offset: int, limit: int,
                     active_set_hash: str | None) -> dict[str, Any]:
    """This run's annotations, newest first, optionally only those of one structure handle."""
    created: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == KIND and event["handle"] not in created:
            created[event["handle"]] = event["seq"]
    rows = []
    for handle in sorted(created, key=created.__getitem__, reverse=True):
        content = run.store.load(handle)
        if type(content) is not dict or content.get("schema") != SCHEMA:
            raise ValueError("reference site annotation payload is invalid")
        if structure is not None and content["structure"]["handle"] != structure:
            continue
        record = content["contacts"]
        rows.append({"handle": handle, "structure": content["structure"]["handle"],
                     "structure_kind": content["structure"]["structure_kind"],
                     "model_number": content["structure"]["model_number"],
                     "numbering_map": content["numbering_map"],
                     "contacts": record["handle"] if record else None,
                     "ligand": record["ligand"] if record else None,
                     "set_hash": content["snapshot_set_hash"],
                     "groups": [{"chain_auth": g["chain_auth"], "accession": g["accession"]}
                                for g in content["groups"]],
                     "counts": counts(content), "null_result": content["null_result"],
                     "created_seq": created[handle],
                     "stale_snapshot": active_set_hash is None or content["snapshot_set_hash"] != active_set_hash})
    return {"schema": "reference_site_annotation_list@1", "active_set_hash": active_set_hash, "total": len(rows),
            "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}
