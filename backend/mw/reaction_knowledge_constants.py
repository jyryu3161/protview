"""M26 closed sets, limits, fixed wording, processed-row formats and shared manifest helpers (spec 3, 5, 11).

Standard library only and no ``mw`` import at all, so the user-run import command
(``scripts/import_reaction_references.py``, which never imports ``backend/mw``) can load this one file by path and
follow exactly the same rules as the server: the canonical JSON formula, the JSONL line rule, the processed-row
formats (``SOURCE_FORMATS`` / ``validate_row``, spec 3.3-3.4), the row order, the set hash and the
``reaction_reference_set@1`` manifest check (``validate_manifest``, spec 3.2).

Changing any closed set, fixed sentence, row format or cap needs a user decision (spec 11.2). ``MAX_ACCESSIONS`` and
``MAX_SKIPPED`` are adjustable defaults of the import command; they are not checked when a manifest is read.

Shared helpers (used by the import command, the server and ``backend/tests/reaction_fixture.py``):

* ``canonical_json(obj) -> bytes`` -- ``json.dumps(sort_keys, (",", ":"), ensure_ascii=False, allow_nan=False)``,
  byte-equal to ``mw.core.handles.canonical_json``; ``jsonl_line(obj)`` = canonical JSON + ``b"\\n"``.
* ``sha256_hex``, ``set_hash_of(manifest_bytes)``, ``raw_sha256_digest(body_sha256s)``.
* ``validate_row(source, row)``, ``row_sort_key(source, row)``, ``encode_jsonl(source, rows)``,
  ``decode_jsonl(source, data)`` (canonical lines, row formats, strictly ascending keys), ``file_record``.
* ``validate_request_log_row``, ``pointer_bytes`` / ``validate_pointer``, ``validate_requested_accessions``,
  ``validate_skipped_accessions``, ``validate_manifest``.
* ``is_accession``, ``split_accessions`` (``reference_uniprot_id`` split on ``","`` and trimmed),
  ``entry_accessions`` (spec 4.2 and the 5.4 ``accession_differs_from_mcsa`` set).

Every check raises ``FormatError`` (a ``ValueError``).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from itertools import pairwise
from typing import Any

# ------------------------------------------------------------------------------------------- names

TOOL = "link_reaction_knowledge"
KIND = "reaction_knowledge"
SCHEMA = "reaction_knowledge@1"
METHOD_VERSION = "mw.reaction_knowledge/v1"
STATUS_SCHEMA = "reaction_reference_status@1"
SET_SCHEMA = "reaction_reference_set@1"
POINTER_SCHEMA = "reaction_active@1"
IMPORTER_VERSION = "reaction_import/1"

# 3.1 location (relative values of the variable resolve against the repository root)
ENV_VAR = "MW_REACTION_REFERENCE_DIR"
DEFAULT_DIR_PARTS = (".deps", "reaction_reference")
ACTIVE_NAME = "active.json"
MANIFEST_NAME = "manifest.json"
SETS_DIR = "sets"
FILES_DIR = "files"
MAX_POINTER_BYTES = 4 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024

# 3.2 / 3.3 sources, processed files (``files/<source>/<name>``) and the request log (outside the source folders)
SOURCES = ("mcsa", "uniprot_function", "rhea")
SOURCE_FILES = {"mcsa": ("entries.jsonl",), "uniprot_function": ("entries.jsonl",), "rhea": ("reactions.jsonl",)}
REQUEST_LOG_NAME = "request_log.jsonl"
REQUEST_LOG_PATH = "files/request_log.jsonl"
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ORIGIN = "public server import"
M15_KINASE_LIST = ("present", "absent", "disabled")
SKIP_REASONS = ("obsolete", "merged", "demerged", "not_found", "fetch_failed")
SITE_TYPES = ("Active site", "Binding site", "Site")

# 4.3 import hosts (exact names) and adjustable import defaults
ALLOWED_HOSTS = ("www.ebi.ac.uk", "rest.uniprot.org", "www.rhea-db.org")
MAX_ACCESSIONS = 20000
MAX_SKIPPED = 50

# 3.1 snapshot reasons (412 precondition, no numbers, the import command named)
SNAPSHOT_REASON_CODES = ("not_installed", "snapshot_invalid")
SNAPSHOT_REASONS = {
    "not_installed": ("반응 참조 스냅샷 세트가 설치되어 있지 않습니다(가져오기 명령 "
                      "scripts/import_reaction_references.py). Reaction reference snapshot set is not installed."),
    "snapshot_invalid": ("반응 참조 스냅샷 세트의 매니페스트 또는 파일 해시가 맞지 않거나 형식을 알 수 없습니다(가져오기 "
                         "명령 scripts/import_reaction_references.py로 다시 가져오십시오). Reaction reference snapshot "
                         "set manifest or file hashes do not match, or the format is unknown."),
}

# 5.2 admission reason codes, in check order (0. pinning is the precondition above)
ADMISSION_REASON_CODES = (
    "unknown_field", "structure_invalid", "pdb_id_invalid", "chains_invalid", "chain_not_found",
    "accession_invalid", "numbering_map_invalid", "structure_mismatch", "map_pdb_mismatch",
)
RESULT_INVALID_REASON = "result_invalid"  # input_invalid when validated_result refuses the content before storing
RESULT_TOO_LARGE_REASON = "result_too_large"  # resource_exceeded (429): canonical JSON above MAX_RESULT_BYTES
TOO_MANY_LINKS_REASON = "too_many_links"      # resource_exceeded (429): more than MAX_LINKS link elements

# 5.3-5.6 section states and reasons (closed)
CHECKED = "checked"
NOT_CHECKED = "not_checked"
NOT_AVAILABLE = "not_available"
MCSA_STATUSES = ("checked", "not_checked")
MCSA_NOT_CHECKED_REASON = "pdb_id_not_given"
COVERED = "covered"
COVERAGE = ("covered", "chain_not_listed", "pdb_not_in_snapshot")
ROW_STATUSES = ("matched", "unmatched", "conflict")
UNMATCHED_REASONS = ("non_standard_code", "no_author_number", "residue_not_in_structure",
                     "ambiguous_residue_number", "insertion_code_present")
CONFLICT_REASONS = ("residue_name_differs", "mcsa_rows_disagree")
UNIPROT_STATUSES = ("checked", "not_checked", "not_available")
UNIPROT_REASONS = ("accession_not_given", "accession_not_in_snapshot", "accession_skipped_at_import")
LINKED_VIA = ("numbering_map",)
LINK_STATUSES = ("mapped", "not_in_map")
LINK_REASONS = ("numbering_map_not_given", "chain_not_in_map", "map_accession_differs")
REACTIONS_STATUSES = ("checked", "not_checked")
REACTIONS_NOT_CHECKED_REASON = "no_source"
ACCESSION_SOURCES = ("user", "numbering_map")
CHAIN_FLAGS = ("accession_differs_from_mcsa",)
# 8.3 M20 ``uncovered_chains[].coverage`` values (used by the M20 v2 check)
M20_UNCOVERED_COVERAGE = ("chain_not_listed", "pdb_not_in_snapshot", "not_checked", "not_in_annotation")

# residue identity, the same 7 fields (and order) as M20 ``IDENTITY_FIELDS``
RESIDUE_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")

# 5.6 / 8.3 caps (refused, never truncated)
MAX_RESULT_BYTES = 1024 * 1024
MAX_LINKS = 2000
MAX_M20_CATALYTIC_LIST = 400

# 11.1 fixed sentences, verbatim and in order
STATEMENTS = {
    "RK1": "촉매 잔기·부위·반응은 참조 스냅샷(M-CSA·UniProt·Rhea)에 적힌 값이며 ProtView가 계산하거나 판정한 것이 아니다.",
    "RK2": ("대응됨은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같다는 뜻이며 잔기의 역할이나 활성을 "
            "뜻하지 않는다."),
    "RK3": "대응 없음·충돌·검사하지 않음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이며 촉매 잔기가 없다는 뜻이 아니다.",
    "RK4": ("UniProt 부위는 번호 대응이 있는 체인에서만 구조 잔기에 연결했고 그 밖에는 단백질 서열 위치로만 보여 "
            "준다."),
    "RK5": "반응 정보는 효소 활성·속도·특이성이나 반응 메커니즘이 유지된다는 뜻이 아니다.",
    "RK6": "M-CSA·UniProt·Rhea 자료는 CC BY 4.0이며 출처·스냅샷 날짜는 아래에 있다.",
}
LIMITATIONS = tuple(STATEMENTS[key] for key in ("RK1", "RK2", "RK3", "RK4", "RK5"))
SCREEN_NOTES = {
    "UK1": ("촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 계산한 값이 아니다. 가져온 "
            "스냅샷 날짜 기준이다."),
    "UK2": "촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 검사했다.",
    "UK3": "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.",
    "UK4": "이 체인을 M-CSA가 다루지 않았다는 것은 촉매 잔기가 없다는 뜻이 아니다.",
}

# ------------------------------------------------------------------------------------------- patterns

UNIPROT_ACCESSION_PATTERN = r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
PDB_ID_PATTERN = r"[0-9][A-Za-z0-9]{3}"           # request field (normalized to upper case)
MCSA_PDB_ID_PATTERN = r"[0-9][a-z0-9]{3}"         # M-CSA ``residue_chains[].pdb_id`` (always lower case)
RHEA_ID_PATTERN = r"RHEA:[0-9]+"
CHEBI_ID_PATTERN = r"CHEBI:[0-9]+"
HEX64_PATTERN = r"[0-9a-f]{64}"
DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"                                   # source date, UTC YYYY-MM-DD
IMPORTED_AT_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"  # UTC, whole seconds
_ACCESSION = re.compile(UNIPROT_ACCESSION_PATTERN + r"\Z")
_HEX64 = re.compile(HEX64_PATTERN + r"\Z")
_DATE = re.compile(DATE_PATTERN + r"\Z")
_IMPORTED_AT = re.compile(IMPORTED_AT_PATTERN + r"\Z")


class FormatError(ValueError):
    """A processed row, JSONL file, request log row, pointer or manifest does not have the fixed format."""


# ------------------------------------------------------------------------------------------- canonical bytes

def canonical_json(obj: Any) -> bytes:
    """Same formula as ``mw.core.handles.canonical_json`` (NaN / Infinity refused with ``ValueError``)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def jsonl_line(obj: Any) -> bytes:
    return canonical_json(obj) + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_hash_of(manifest_bytes: bytes) -> str:
    """``set_hash`` = SHA-256 of the exact canonical manifest bytes."""
    return sha256_hex(manifest_bytes)


def raw_sha256_digest(body_sha256s: Iterable[str]) -> str:
    """SHA-256 of the raw response body hashes (lower-case hex, request order) joined with ``"\\n"``."""
    values = list(body_sha256s)
    if not all(type(v) is str and _HEX64.fullmatch(v) for v in values):
        raise FormatError("raw response hashes must be lower-case hex SHA-256")
    return sha256_hex("\n".join(values).encode("ascii"))


def file_record(path: str, name: str, data: bytes) -> dict[str, Any]:
    """A manifest ``files[]`` / ``request_log`` record of the given bytes (``rows`` = line count)."""
    rows = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return {"name": name, "path": path, "sha256": sha256_hex(data), "bytes": len(data), "rows": rows}


# ------------------------------------------------------------------------------------------- accessions

def is_accession(value: Any) -> bool:
    return type(value) is str and _ACCESSION.fullmatch(value) is not None


def split_accessions(value: str) -> list[str]:
    """``reference_uniprot_id`` split on ``","`` with surrounding white space removed (response order)."""
    return [part.strip() for part in value.split(",")]


def entry_accessions(row: dict[str, Any]) -> list[str]:
    """Every UniProt accession an M-CSA entry names (sorted): ``reference_uniprot_id`` parts + non-empty
    ``residue_sequences[].uniprot_id`` (an empty string is not an accession)."""
    found = set(split_accessions(row["reference_uniprot_id"]))
    found.update(seq["uniprot_id"] for residue in row["residues"] for seq in residue["residue_sequences"]
                 if seq["uniprot_id"] != "")
    return sorted(found)


# ------------------------------------------------------------------------------------------- row formats (3.3/3.4)
# Field descriptors (pure data, read by ``validate_row``):
#   ("str",) any string, ("text",) non-empty string, ("re", pattern) a string matching the pattern,
#   ("int", minimum) an int (never a bool) >= minimum (None = no minimum), ("bool",),
#   ("enum", values), ("nullable", inner), ("list", inner) a list in response order,
#   ("sorted", inner, distinct) a scalar list in ascending order (distinct: no repeats),
#   ("accession_list",) a reference_uniprot_id string, ("accession_or_empty",),
#   ("object", ((key, descriptor), ...)) a dict with exactly these keys.

_TEXT = ("text",)
_STR = ("str",)
_ROLE = ("object", (("group_function", _STR), ("function_type", _STR), ("function", _STR), ("emo", _STR)))
_RESIDUE_CHAIN = ("object", (
    ("pdb_id", ("re", MCSA_PDB_ID_PATTERN)), ("chain_name", _TEXT), ("assembly_chain_name", _STR),
    ("assembly", ("nullable", ("int", None))), ("code", _TEXT), ("resid", ("nullable", ("int", None))),
    ("auth_resid", ("nullable", ("int", None))), ("is_reference", ("bool",))))
_RESIDUE_SEQUENCE = ("object", (("uniprot_id", ("accession_or_empty",)), ("code", _TEXT), ("is_reference", ("bool",))))
_MCSA_RESIDUE = ("object", (
    ("roles_summary", _STR), ("function_location_abv", _STR), ("ptm", _STR), ("roles", ("list", _ROLE)),
    ("residue_chains", ("list", _RESIDUE_CHAIN)), ("residue_sequences", ("list", _RESIDUE_SEQUENCE))))
_COMPOUND = ("object", (("type", _TEXT), ("chebi_id", _TEXT), ("name", _STR)))
_ACTIVITY = ("object", (
    ("reaction_name", _STR), ("ec_number", ("nullable", _TEXT)),
    ("rhea_ids", ("sorted", ("re", RHEA_ID_PATTERN), False)),
    ("chebi_ids", ("sorted", ("re", CHEBI_ID_PATTERN), False))))
_FEATURE = ("object", (
    ("type", ("enum", SITE_TYPES)), ("start", ("int", 1)), ("end", ("int", 1)), ("description", _STR),
    ("ligand_name", ("nullable", _STR)), ("ligand_id", ("nullable", _STR))))
_PARTICIPANT = ("object", (("chebi_id", ("re", CHEBI_ID_PATTERN)), ("name", _STR)))

SOURCE_FORMATS: dict[str, tuple] = {
    "mcsa": ("object", (
        ("mcsa_id", ("int", 1)), ("enzyme_name", _STR), ("reference_uniprot_id", ("accession_list",)),
        ("all_ecs", ("sorted", _TEXT, False)),
        ("reaction", ("object", (("ec", ("nullable", _TEXT)), ("compounds", ("list", _COMPOUND))))),
        ("residues", ("list", _MCSA_RESIDUE)))),
    "uniprot_function": ("object", (
        ("accession", ("re", UNIPROT_ACCESSION_PATTERN)), ("entry_name", _TEXT),
        ("protein_name", ("nullable", _STR)), ("organism", _TEXT), ("sequence_length", ("int", 1)),
        ("ec_numbers", ("sorted", _TEXT, True)), ("catalytic_activities", ("list", _ACTIVITY)),
        ("features", ("list", _FEATURE)))),
    "rhea": ("object", (
        ("rhea_id", ("re", RHEA_ID_PATTERN)), ("equation", _TEXT),
        ("ec_numbers", ("sorted", ("re", r"(?!EC:)[^\s;]+"), False)),
        ("participants", ("list", _PARTICIPANT)))),
}
REQUEST_LOG_FORMAT = ("object", (
    ("seq", ("int", 1)), ("source", ("enum", SOURCES)), ("method", ("enum", ("GET",))),
    ("url", ("re", r"https://\S+")), ("status", ("int", None)), ("bytes", ("int", 0)),
    ("sha256", ("re", r"[0-9a-f]{64}"))))


def _check(value: Any, descriptor: tuple, path: str) -> None:
    kind = descriptor[0]
    if kind == "str":
        ok = type(value) is str
    elif kind == "text":
        ok = type(value) is str and value != ""
    elif kind == "re":
        ok = type(value) is str and re.fullmatch(descriptor[1], value) is not None
    elif kind == "int":
        ok = type(value) is int and (descriptor[1] is None or value >= descriptor[1])
    elif kind == "bool":
        ok = type(value) is bool
    elif kind == "enum":
        ok = type(value) is str and value in descriptor[1]
    elif kind == "accession_or_empty":
        ok = value == "" or is_accession(value)
    elif kind == "accession_list":
        ok = type(value) is str and all(is_accession(part) for part in split_accessions(value))
    elif kind == "nullable":
        if value is not None:
            _check(value, descriptor[1], path)
        return
    elif kind in ("list", "sorted"):
        if type(value) is not list:
            raise FormatError(f"{path}: expected a list")
        for i, item in enumerate(value):
            _check(item, descriptor[1], f"{path}[{i}]")
        if kind == "sorted" and (value != sorted(value) or (descriptor[2] and len(set(value)) != len(value))):
            raise FormatError(f"{path}: not in ascending order" + (" without repeats" if descriptor[2] else ""))
        return
    elif kind == "object":
        if type(value) is not dict:
            raise FormatError(f"{path}: expected an object")
        keys = [key for key, _ in descriptor[1]]
        if set(value) != set(keys):
            raise FormatError(f"{path}: fields {sorted(value)} differ from {sorted(keys)}")
        for key, inner in descriptor[1]:
            _check(value[key], inner, f"{path}.{key}")
        return
    else:  # pragma: no cover - descriptors are constants
        raise FormatError(f"{path}: unknown descriptor {kind!r}")
    if not ok:
        raise FormatError(f"{path}: unexpected value {value!r}")


def validate_row(source: str, row: Any) -> None:
    """Refuse a processed row with an unknown or missing field, a wrong type or value (spec 3.3-3.4)."""
    if source not in SOURCE_FORMATS:
        raise FormatError(f"unknown source {source!r}")
    _check(row, SOURCE_FORMATS[source], source)
    if source == "uniprot_function":
        for i, feature in enumerate(row["features"]):
            if feature["start"] > feature["end"]:
                raise FormatError(f"uniprot_function.features[{i}]: start after end")


def validate_request_log_row(row: Any) -> None:
    _check(row, REQUEST_LOG_FORMAT, "request_log")


def row_sort_key(source: str, row: dict[str, Any]) -> Any:
    """The fixed row order: ``mcsa_id`` (int), accession (string), integer part of ``rhea_id``."""
    if source == "mcsa":
        return row["mcsa_id"]
    if source == "uniprot_function":
        return row["accession"]
    if source == "rhea":
        return int(row["rhea_id"].split(":", 1)[1])
    raise FormatError(f"unknown source {source!r}")


def _check_order(source: str, rows: list[dict[str, Any]]) -> None:
    keys = [row_sort_key(source, row) for row in rows]
    if any(a >= b for a, b in pairwise(keys)):
        raise FormatError(f"{source}: rows are not in strictly ascending order")


def encode_jsonl(source: str, rows: Iterable[dict[str, Any]]) -> bytes:
    """Validated rows in the fixed order -> the processed file bytes (same rows, same bytes)."""
    rows = list(rows)
    for row in rows:
        validate_row(source, row)
    _check_order(source, rows)
    return b"".join(jsonl_line(row) for row in rows)


def _reject_constant(value: str) -> Any:
    raise FormatError(f"non-finite number {value}")


def decode_jsonl(source: str, data: bytes) -> list[dict[str, Any]]:
    """Processed file bytes -> rows; every line must be the canonical JSON of a valid row, in the fixed order."""
    if data and not data.endswith(b"\n"):
        raise FormatError(f"{source}: the last line has no newline")
    rows = []
    for number, line in enumerate(data.split(b"\n")[:-1], start=1):
        try:
            row = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:
            raise FormatError(f"{source} line {number}: not JSON") from exc
        validate_row(source, row)
        if canonical_json(row) != line:
            raise FormatError(f"{source} line {number}: not canonical JSON")
        rows.append(row)
    _check_order(source, rows)
    return rows


# ------------------------------------------------------------------------------------------- pointer and manifest

def pointer_bytes(set_hash: str) -> bytes:
    """The ``active.json`` bytes for a set hash."""
    pointer = {"schema": POINTER_SCHEMA, "set_hash": set_hash}
    validate_pointer(pointer)
    return canonical_json(pointer)


def validate_pointer(obj: Any) -> str:
    """The set hash of a valid ``reaction_active@1`` pointer."""
    if (type(obj) is not dict or set(obj) != {"schema", "set_hash"} or obj["schema"] != POINTER_SCHEMA
            or type(obj["set_hash"]) is not str or not _HEX64.fullmatch(obj["set_hash"])):
        raise FormatError("unknown active pointer")
    return obj["set_hash"]


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _accession_list(value: Any, path: str) -> list[str]:
    if (type(value) is not list or not all(is_accession(v) for v in value)
            or any(a >= b for a, b in pairwise(value))):
        raise FormatError(f"{path}: expected accessions in strictly ascending order")
    return value


def validate_requested_accessions(obj: Any) -> None:
    """``requested_accessions`` keys and values exactly (spec 3.2)."""
    keys = {"from_mcsa", "from_m15_kinase_set", "m15_kinase_list", "user_named", "dropped_previous_user_named",
            "union_count"}
    if type(obj) is not dict or set(obj) != keys:
        raise FormatError("requested_accessions: unexpected keys")
    kinase = obj["from_m15_kinase_set"]
    if not _count(obj["from_mcsa"]) or not _count(obj["union_count"]):
        raise FormatError("requested_accessions: counts must be non-negative integers")
    if type(kinase) is not dict or set(kinase) != {"set_hash", "count"} or not _count(kinase["count"]):
        raise FormatError("requested_accessions.from_m15_kinase_set: unexpected shape")
    if obj["m15_kinase_list"] not in M15_KINASE_LIST:
        raise FormatError("requested_accessions.m15_kinase_list: unknown value")
    if obj["m15_kinase_list"] == "present":
        if type(kinase["set_hash"]) is not str or not _HEX64.fullmatch(kinase["set_hash"]):
            raise FormatError("requested_accessions: a present kinase list names its M15 set hash")
    elif kinase != {"set_hash": None, "count": 0}:
        raise FormatError("requested_accessions: an absent or disabled kinase list is {set_hash: null, count: 0}")
    user = _accession_list(obj["user_named"], "requested_accessions.user_named")
    dropped = _accession_list(obj["dropped_previous_user_named"], "requested_accessions.dropped_previous_user_named")
    if set(user) & set(dropped):
        raise FormatError("requested_accessions: a dropped accession is named again")
    parts = (obj["from_mcsa"], kinase["count"], len(user))
    if not max(parts) <= obj["union_count"] <= sum(parts):
        raise FormatError("requested_accessions.union_count is not the size of a union of the parts")


_TARGETS = {"merged": (1, 1), "demerged": (1, 3)}


def validate_skipped_accessions(obj: Any) -> None:
    """``skipped_accessions`` entries exactly, accession order (spec 3.2)."""
    if type(obj) is not list:
        raise FormatError("skipped_accessions: expected a list")
    for i, item in enumerate(obj):
        if (type(item) is not dict or set(item) != {"accession", "reason", "target_accessions"}
                or not is_accession(item["accession"]) or item["reason"] not in SKIP_REASONS):
            raise FormatError(f"skipped_accessions[{i}]: unexpected shape")
        targets = _accession_list(item["target_accessions"], f"skipped_accessions[{i}].target_accessions")
        low, high = _TARGETS.get(item["reason"], (0, 0))
        if not low <= len(targets) <= high:
            raise FormatError(f"skipped_accessions[{i}]: wrong number of target accessions")
    accessions = [item["accession"] for item in obj]
    if any(a >= b for a, b in pairwise(accessions)):
        raise FormatError("skipped_accessions: not in strictly ascending accession order")


def _validate_file_record(entry: Any, name: str, path: str) -> None:
    if (type(entry) is not dict or set(entry) != {"name", "path", "sha256", "bytes", "rows"}
            or entry["name"] != name or entry["path"] != path or type(entry["sha256"]) is not str
            or not _HEX64.fullmatch(entry["sha256"]) or not _count(entry["bytes"])
            or entry["bytes"] > MAX_FILE_BYTES or not _count(entry["rows"])):
        raise FormatError(f"file record {path}: unexpected shape")


_MANIFEST_KEYS = frozenset({"schema", "imported_at", "importer_version", "sources", "requested_accessions",
                            "skipped_accessions", "request_log"})
_SOURCE_KEYS = frozenset({"source", "date", "license", "license_url", "origin", "files", "raw_response_count",
                          "raw_sha256_digest"})


def validate_manifest(obj: Any) -> None:
    """A ``reaction_reference_set@1`` manifest with exactly the keys and values of spec 3.2."""
    if type(obj) is not dict or set(obj) != _MANIFEST_KEYS or obj["schema"] != SET_SCHEMA:
        raise FormatError("unknown set manifest")
    if type(obj["imported_at"]) is not str or not _IMPORTED_AT.fullmatch(obj["imported_at"]):
        raise FormatError("imported_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
    if obj["importer_version"] != IMPORTER_VERSION:
        raise FormatError("unknown importer version")
    sources = obj["sources"]
    if type(sources) is not list or [s.get("source") if type(s) is dict else None for s in sources] != list(SOURCES):
        raise FormatError("sources must be exactly mcsa, uniprot_function, rhea in this order")
    for record in sources:
        if (set(record) != _SOURCE_KEYS or type(record["date"]) is not str or not _DATE.fullmatch(record["date"])
                or record["license"] != LICENSE or record["license_url"] != LICENSE_URL
                or record["origin"] != ORIGIN or not _count(record["raw_response_count"])
                or type(record["raw_sha256_digest"]) is not str or not _HEX64.fullmatch(record["raw_sha256_digest"])
                or type(record["files"]) is not list
                or len(record["files"]) != len(SOURCE_FILES[record["source"]])):
            raise FormatError(f"source record {record.get('source')!r}: unexpected shape")
        for entry, name in zip(record["files"], SOURCE_FILES[record["source"]]):
            _validate_file_record(entry, name, f"{FILES_DIR}/{record['source']}/{name}")
    validate_requested_accessions(obj["requested_accessions"])
    validate_skipped_accessions(obj["skipped_accessions"])
    if {item["accession"] for item in obj["skipped_accessions"]} & set(obj["requested_accessions"]["user_named"]):
        raise FormatError("a user-named accession is never skipped (the import is refused instead)")
    _validate_file_record(obj["request_log"], REQUEST_LOG_NAME, REQUEST_LOG_PATH)
