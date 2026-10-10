"""M27 closed sets, limits, fixed wording, kbase record format checks and shared manifest helpers (spec 3, 5, 9).

Standard library only and no ``mw`` import at all, so the user-run import command
(``scripts/import_precedent_snapshots.py``, which never imports ``backend/mw``) can load this one file by path and
follow exactly the same rules as the server: the canonical JSON formula, the record hash, the JSONL line rule, the
kbase record format (``validate_move`` / ``validate_reference``, spec 3.4), the ``KBASE_PINS`` check, the set hash and
the ``precedent_reference_set@1`` manifest check (``validate_manifest``, spec 3.2).

Changing any closed set, fixed sentence, vocabulary term, pin or cap needs a user decision (spec 9.1-9.2). The page
size defaults are adjustable defaults (spec 9.2 tunables).

Shared helpers (used by the import command, the server and ``backend/tests/precedent_fixture.py``):

* ``canonical_json(obj) -> bytes`` -- ``json.dumps(sort_keys, (",", ":"), ensure_ascii=False, allow_nan=False)``,
  byte-equal to ``mw.core.handles.canonical_json``; ``sha256_hex``; ``set_hash_of(manifest_bytes)``.
* ``content_hash(record)`` = ``"sha256:" + sha256(canonical_json(record without its top-level content_hash))``;
  ``hash_matches(record)``.
* ``parse_jsonl(data)`` (one JSON object per ``"\\n"``-terminated UTF-8 line; the lines need not be canonical),
  ``validate_move``, ``validate_reference``, ``validate_dist_files(moves, moves_flagged, references) -> DistRecords``
  (formats, record hashes, ``move_id`` unique over both move files, ``ref_id`` unique, verification counts),
  ``parse_pubmed``, ``bibliography_entries``.
* ``check_kbase_pins(meta)``, ``validate_kbase_block``, ``validate_file_entry``, ``file_record(name, data)``,
  ``validate_manifest``, ``manifest_bytes``, ``pointer_bytes`` / ``validate_pointer``.
* ``move_number``, ``is_accession``, ``screen_note(key, n)`` (UP2 / UP5 with their integer).

Every check raises ``FormatError`` (a ``ValueError``).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, NamedTuple

# ------------------------------------------------------------------------------------------- names

TOOL = "link_kinase_precedents"
KIND = "kinase_precedents"
SCHEMA = "kinase_precedents@1"
METHOD_VERSION = "mw.kinase_precedents/v1"
STATUS_SCHEMA = "precedent_reference_status@1"
DETAIL_SCHEMA = "kinase_precedents_detail@1"
SET_SCHEMA = "precedent_reference_set@1"
POINTER_SCHEMA = "precedent_active@1"
IMPORTER_VERSION = "precedent_import/1"

# 5.5 stored record copy: the set's record minus exactly these two paths
RECORD_FORMAT = "kbase_record_minus_2_paths@1"
REMOVED_PATHS = (("source", "parser"), ("checks", "cross_parser_numbers", "measurements"))

# 3.1 location (relative values of the variable resolve against the repository root)
ENV_VAR = "MW_PRECEDENT_REFERENCE_DIR"
DEFAULT_DIR_PARTS = (".deps", "precedent_reference")
ACTIVE_NAME = "active.json"
MANIFEST_NAME = "manifest.json"
SETS_DIR = "sets"
FILES_DIR = "files"
MAX_POINTER_BYTES = 4 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024

# 3.3 imported files (bytes copied as they are) and their origins
DIST_FILE_NAMES = ("dist/moves.jsonl", "dist/moves_flagged.jsonl", "dist/references.jsonl")
FILE_SOURCES = ("moves", "moves_flagged")
SOURCE_FILE_NAMES = {"moves": "dist/moves.jsonl", "moves_flagged": "dist/moves_flagged.jsonl"}
REFERENCES_FILE_NAME = "dist/references.jsonl"
KBASE_ORIGIN = "kbase_kinase processed dist"
BIBLIOGRAPHY_ORIGIN = "kbase_kinase processed ref/pubmed"
BIBLIOGRAPHY_FIELDS = ("title", "journal", "year", "doi", "pmc")
# 6 ``methods.kinase_precedents.sources[].source`` and the dist license label (the dist manifest states none)
CAPABILITY_SOURCES = ("kbase_dist", "kbase_pubmed")
DIST_LICENSE = "none-stated"

# 3.4 / 9.2 caps (refused, never truncated)
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILE_ROWS = 100000
MAX_DIST_MANIFEST_BYTES = 1024 * 1024
MAX_REF_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_UNRESOLVED_NAMES = 100
MAX_QUERY_CHARS = 100
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
REPORT_MAX_LINES_PER_TARGET = 300
MAX_QUOTE_WORDS = 25
# adjustable defaults (spec 9.2 tunables)
RECORDS_PAGE_DEFAULT = 25
LIST_PAGE_DEFAULT = 50

# 3.4 kbase version pins (strict; a different value refuses the import and the set)
KBASE_PINS = {
    "schema_version": "1",
    "effect_rules_version": "1",
    "vocab_version": ("contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:"
                      "024a47d5a62eab2a1ad1a52a0bb8f8e2740cbe3f8ad279bc6c62055c778cc11e"),
}

# ------------------------------------------------------------------------------------------- closed sets

# 3.1 snapshot reasons (412 precondition, no numbers, the import command named)
SNAPSHOT_REASON_CODES = ("not_installed", "snapshot_invalid")
SNAPSHOT_REASONS = {
    "not_installed": ("키나아제 전례 참조 스냅샷 세트가 설치되어 있지 않습니다(가져오기 명령 "
                      "scripts/import_precedent_snapshots.py). Kinase precedent reference snapshot set is not "
                      "installed."),
    "snapshot_invalid": ("키나아제 전례 참조 스냅샷 세트의 매니페스트·파일·레코드 해시가 맞지 않거나 형식을 알 수 "
                         "없습니다(가져오기 명령 scripts/import_precedent_snapshots.py로 다시 가져오십시오). Kinase "
                         "precedent reference snapshot set manifest, file or record hashes do not match, or the "
                         "format is unknown."),
}

# 5.2 admission reason codes, in check order (0. pinning is the precondition above)
ADMISSION_REASON_CODES = ("unknown_field", "numbering_map_invalid", "include_flagged_invalid", "chains_invalid",
                          "chain_not_in_map")
RESULT_TOO_LARGE_REASON = "result_too_large"  # resource_exceeded (429): canonical JSON above MAX_RESULT_BYTES
RESULT_INVALID_REASON = "result_invalid"      # input_invalid when validated_result refuses the content

# 5.3 / 5.4 chain and target states
CHAIN_STATUSES = ("linked", "not_linked")
CHAIN_REASONS = ("no_mapped_residues", "multiple_accessions")
TARGET_STATUSES = ("precedents_found", "none_in_included_files", "not_in_kbase_references")

# 6 read filters and sort keys (never an effect, direction or magnitude value)
FILTER_KEYS = ("file", "site", "goal", "tactic", "variant", "q")
SORT_KEYS = ("move_id", "pmid", "year", "variant", "file")
SORT_ORDERS = ("asc", "desc")

# 3.4 closed values of the kbase record format
RESOLUTION_BASES = ("gene", "klifs_gene_name", "klifs_name", "alias", "ambiguous", "unmapped", "absent",
                    "name_token", "pubmed_title", "notation")
TARGET_ROLES = ("on_target", "off_target", "not_applicable")
DIRECTIONS = ("improved", "worsened", "unchanged", "unknown")
DIRECTION_BASES = ("numeric", "text", "none")
MAGNITUDE_BUCKETS = ("small", "moderate", "large", "unknown")
CHECK_STATUSES = ("pass", "fail", "not_applicable", "lookup_failed")
LOCATION_KINDS = ("table", "figure", "text")
STRUCTURE_LINK_BASES = ("pdb_title", "paper_context", "sole_candidate")
CHECK_NAMES = ("qualifier_consistency", "tag_vocab", "schema", "target_in_reference", "quote_in_source",
               "cross_parser_numbers", "chembl_crosscheck", "pmid_exists", "structure_ref_exists", "duplicate")
MOVE_KEYS = ("review_status", "schema_version", "move_id", "source", "target", "structure_ref",
             "structure_link_reason", "structure_ref_from", "structure_links", "interactions", "observation",
             "change", "effects", "tradeoffs", "mutations", "tags", "proposed_tags", "figures", "checks", "extraction",
             "content_hash")
TARGET_KEYS = ("gene", "uniprot", "name_as_written", "resolution_basis", "candidates", "variant")
EFFECT_KEYS = ("metric", "assay", "assay_context", "target_ref", "target_role", "before", "after", "direction",
               "direction_basis", "magnitude_bucket", "comparable", "comparability_reason", "fold_change",
               "chembl_crosscheck", "evidence")
OBSERVATION_KEYS = ("text", "quote", "quote_truncated", "evidence")
TRADEOFF_KEYS = ("text", "quote", "quote_truncated", "evidence")
EXTRACTION_KEYS = ("model", "provider", "prompt_version", "run_at")
REFERENCE_KEYS = ("ref_id", "gene", "klifs_name", "uniprot", "group", "family", "coverage", "content_hash",
                  "review_status", "schema_version")

# 9.2 vocabulary (kbase ``vocab_version``; terms as kbase wrote them, ProtView does not interpret them)
SITE_TERMS = ("bp_I_A", "bp_I_B", "bp_II_in", "bp_II_A_in", "bp_II_B_in", "bp_II_B", "bp_II_out", "bp_III", "bp_IV",
              "bp_V", "fp_I", "fp_II", "front", "back", "gate", "allosteric_non_atp", "myristoyl_pocket",
              "substrate_site", "solvent_exposed", "not_site_specific")
GOAL_TERMS = ("potency", "selectivity", "mutant_coverage", "binding_kinetics", "solubility", "permeability",
              "metabolic_stability", "oral_exposure", "cns_penetration", "safety_offtarget", "chemical_stability",
              "synthetic_accessibility")
TACTIC_TERMS = ("add_hydrophobic_bulk", "truncate_substituent", "vector_extension", "ring_fusion", "scaffold_hop",
                "heteroatom_swap", "bioisostere_replacement", "halogen_substitution", "hbond_engagement",
                "salt_bridge_engagement", "covalent_warhead", "conformational_restriction", "macrocyclization",
                "stereochemistry_change", "polar_group_add", "lipophilicity_reduction", "prodrug_masking",
                "degrader_conversion")
TAG_AXES = {"site": SITE_TERMS, "goal": GOAL_TERMS, "tactic": TACTIC_TERMS}

# ------------------------------------------------------------------------------------------- fixed sentences

# 9.1 verbatim and in order (KP1-KP6 are the result ``limitations``; KT1 goes with every screen and report)
STATEMENTS = {
    "KP1": "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
    "KP2": ("방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, "
            "측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다."),
    "KP3": ("kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. "
            "파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다."),
    "KP4": ("전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 "
            "파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다."),
    "KP5": ("표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 "
            "일치는 판단하지 않았다."),
    "KP6": "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
    "KT1": "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인",
}
LIMITATIONS = tuple(STATEMENTS[key] for key in ("KP1", "KP2", "KP3", "KP4", "KP5", "KP6"))
SCREEN_NOTES = {
    "UP1": ("원문 대조 안 함: ProtView에는 논문 원문이 없어 인용이 원문과 같은지 확인하지 않았다. "
            "'ProtView 무결성 확인'은 가져온 파일과 레코드의 해시, 인용 길이, 논문 쪽 위치 존재만 뜻한다."),
    "UP2": "moves_flagged 파일의 전례 N건은 포함하지 않았다.",
    "UP3": "변이 표기는 kbase 기록 그대로이며 이 구조의 서열과 대조하지 않았다.",
    "UP4": "PDB 언급은 kbase가 기록한 것(근거 수준 포함)이며 이 구조와의 일치를 판단하지 않았다.",
    "UP5": "표적이 해석되지 않은 전례 N건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.",
}
NUMBERED_NOTES = ("UP2", "UP5")  # "N건" is filled with an integer (UP2: excluded_flagged, UP5: unresolved total)

# ------------------------------------------------------------------------------------------- patterns

UNIPROT_ACCESSION_PATTERN = r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
MOVE_ID_PATTERN = r"MOVE-[0-9]{4,}"       # spec ^MOVE-\d{4,}$ with ASCII digits only
PMID_PATTERN = r"[0-9]+"
RECORD_HASH_PATTERN = r"sha256:[0-9a-f]{64}"
HEX64_PATTERN = r"[0-9a-f]{64}"
HEX40_PATTERN = r"[0-9a-f]{40}"
DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
IMPORTED_AT_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"         # UTC, whole seconds
GIT_DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})"  # git %cI
_ACCESSION = re.compile(UNIPROT_ACCESSION_PATTERN + r"\Z")
_MOVE_ID = re.compile(MOVE_ID_PATTERN + r"\Z")
_PMID = re.compile(PMID_PATTERN + r"\Z")
_RECORD_HASH = re.compile(RECORD_HASH_PATTERN + r"\Z")
_HEX64 = re.compile(HEX64_PATTERN + r"\Z")
_HEX40 = re.compile(HEX40_PATTERN + r"\Z")
_DATE = re.compile(DATE_PATTERN + r"\Z")
_IMPORTED_AT = re.compile(IMPORTED_AT_PATTERN + r"\Z")
_GIT_DATE = re.compile(GIT_DATE_PATTERN + r"\Z")


class FormatError(ValueError):
    """A record, JSONL file, pointer or manifest does not have the fixed format."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise FormatError(message)


def screen_note(key: str, n: int | None = None) -> str:
    """The screen note ``key`` verbatim; UP2 / UP5 with ``N`` replaced by the non-negative integer ``n``."""
    text = SCREEN_NOTES[key]
    if key in NUMBERED_NOTES:
        if type(n) is not int or n < 0:
            raise ValueError(f"{key} needs a non-negative integer")
        return text.replace("N건", f"{n}건", 1)
    if n is not None:
        raise ValueError(f"{key} takes no number")
    return text


# ------------------------------------------------------------------------------------------- canonical bytes

def canonical_json(obj: Any) -> bytes:
    """Same formula as ``mw.core.handles.canonical_json`` (NaN / Infinity refused with ``ValueError``)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_hash_of(manifest_bytes: bytes) -> str:
    """``set_hash`` = SHA-256 of the exact canonical manifest bytes."""
    return sha256_hex(manifest_bytes)


def content_hash(record: dict[str, Any]) -> str:
    """``"sha256:" + sha256(canonical_json(record without its top-level content_hash))`` (spec 3.4)."""
    return "sha256:" + sha256_hex(canonical_json({k: v for k, v in record.items() if k != "content_hash"}))


def hash_matches(record: dict[str, Any]) -> bool:
    return type(record.get("content_hash")) is str and content_hash(record) == record["content_hash"]


def move_number(move_id: str) -> int:
    """The integer part of ``MOVE-<digits>`` (the fixed record order)."""
    return int(move_id.split("-", 1)[1])


def is_accession(value: Any) -> bool:
    return type(value) is str and _ACCESSION.fullmatch(value) is not None


def pubmed_file_name(date: str) -> str:
    return f"pubmed/{date}/documents.jsonl"


def file_path(name: str) -> str:
    """The set-relative path of an imported file name."""
    return f"{FILES_DIR}/{name}"


def file_record(name: str, data: bytes) -> dict[str, Any]:
    """A manifest file record of the given bytes (``rows`` = newline count; the last line must end in one)."""
    _require(not data or data.endswith(b"\n"), f"{name}: the last line has no newline")
    digest = sha256_hex(data)
    return {"name": name, "path": file_path(name), "sha256": digest, "bytes": len(data), "rows": data.count(b"\n"),
            "kbase_sha256": "sha256:" + digest}


# ------------------------------------------------------------------------------------------- JSONL

def _reject_constant(value: str) -> Any:
    raise FormatError(f"non-finite number {value}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise FormatError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def parse_jsonl(data: bytes, what: str = "jsonl") -> list[dict[str, Any]]:
    """One JSON object per UTF-8 line, each line ending in ``"\\n"`` (no blank line, no duplicate key, no NaN)."""
    _require(type(data) is bytes, f"{what}: expected bytes")
    _require(len(data) <= MAX_FILE_BYTES, f"{what}: above the file size cap")
    _require(not data or data.endswith(b"\n"), f"{what}: the last line has no newline")
    lines = data.split(b"\n")[:-1] if data else []
    _require(len(lines) <= MAX_FILE_ROWS, f"{what}: more than {MAX_FILE_ROWS} lines")
    records = []
    for number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                               parse_constant=_reject_constant)
        except (ValueError, RecursionError) as exc:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
            raise FormatError(f"{what} line {number}: not one JSON value ({exc})") from exc
        _require(type(value) is dict, f"{what} line {number}: not a JSON object")
        records.append(value)
    return records


# ------------------------------------------------------------------------------------------- records (3.4)

def _has(obj: Any, keys: tuple[str, ...], where: str) -> dict[str, Any]:
    _require(type(obj) is dict, f"{where}: expected an object")
    missing = [key for key in keys if key not in obj]
    _require(not missing, f"{where}: missing {missing}")
    return obj


def _member(value: Any, values: tuple[str, ...], where: str) -> None:
    _require(type(value) is str and value in values, f"{where}: unknown value {value!r}")


def _page(value: Any) -> bool:
    return type(value) is int and value >= 1


def validate_move(record: Any) -> None:
    """Refuse a move record that leaves the spec 3.4 shape; unlisted nested keys are kept, not refused."""
    _require(type(record) is dict, "move: expected an object")
    _require(set(record) == set(MOVE_KEYS), f"move: top-level keys {sorted(record)} differ from the 21 fixed keys")
    move_id = record["move_id"]
    _require(type(move_id) is str and _MOVE_ID.fullmatch(move_id), f"move: move_id {move_id!r} is not MOVE-<digits>")
    where = f"move {move_id}"
    _require(record["review_status"] == "unreviewed", f"{where}: review_status must stay 'unreviewed'")
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1, f"{where}: schema_version")
    _require(type(record["content_hash"]) is str and _RECORD_HASH.fullmatch(record["content_hash"]),
             f"{where}: content_hash is not sha256:<hex>")
    source = _has(record["source"], ("pmid", "locations"), f"{where}.source")
    _require(type(source["pmid"]) is str and _PMID.fullmatch(source["pmid"]), f"{where}: source.pmid")
    locations = source["locations"]
    _require(type(locations) is list and locations, f"{where}: source.locations must be a non-empty list")
    for i, location in enumerate(locations):
        _has(location, ("kind", "page"), f"{where}.source.locations[{i}]")
        _member(location["kind"], LOCATION_KINDS, f"{where}.source.locations[{i}].kind")
        _require(_page(location["page"]), f"{where}.source.locations[{i}].page must be an integer >= 1")
    target = _has(record["target"], TARGET_KEYS, f"{where}.target")
    _require(target["uniprot"] is None or is_accession(target["uniprot"]), f"{where}: target.uniprot")
    _member(target["resolution_basis"], RESOLUTION_BASES, f"{where}.target.resolution_basis")
    _require(type(target["variant"]) is str, f"{where}: target.variant must be a string")
    _require(target["name_as_written"] is None or type(target["name_as_written"]) is str,
             f"{where}: target.name_as_written must be a string or null")
    tags = record["tags"]
    _require(type(tags) is dict and set(tags) == set(TAG_AXES), f"{where}: tags keys must be site, goal, tactic")
    for axis, terms in TAG_AXES.items():
        _require(type(tags[axis]) is list, f"{where}: tags.{axis} must be a list")
        for term in tags[axis]:
            _member(term, terms, f"{where}.tags.{axis}")
    effects = record["effects"]
    _require(type(effects) is list and effects, f"{where}: effects must be a non-empty list")
    for i, effect in enumerate(effects):
        _has(effect, EFFECT_KEYS, f"{where}.effects[{i}]")
        _member(effect["target_role"], TARGET_ROLES, f"{where}.effects[{i}].target_role")
        _member(effect["direction"], DIRECTIONS, f"{where}.effects[{i}].direction")
        _member(effect["direction_basis"], DIRECTION_BASES, f"{where}.effects[{i}].direction_basis")
        _member(effect["magnitude_bucket"], MAGNITUDE_BUCKETS, f"{where}.effects[{i}].magnitude_bucket")
    observation = _has(record["observation"], OBSERVATION_KEYS, f"{where}.observation")
    _require(type(observation["quote"]) is str, f"{where}: observation.quote must be a string")
    _require(type(record["tradeoffs"]) is list, f"{where}: tradeoffs must be a list")
    for i, tradeoff in enumerate(record["tradeoffs"]):
        _has(tradeoff, TRADEOFF_KEYS, f"{where}.tradeoffs[{i}]")
        _require(tradeoff["quote"] is None or type(tradeoff["quote"]) is str,
                 f"{where}: tradeoffs[{i}].quote must be a string or null")
    checks = _has(record["checks"], CHECK_NAMES, f"{where}.checks")
    for name in CHECK_NAMES:
        _has(checks[name], ("status",), f"{where}.checks.{name}")
        _member(checks[name]["status"], CHECK_STATUSES, f"{where}.checks.{name}.status")
    _require(type(record["structure_links"]) is list, f"{where}: structure_links must be a list")
    for i, link in enumerate(record["structure_links"]):
        _has(link, ("basis",), f"{where}.structure_links[{i}]")
        _member(link["basis"], STRUCTURE_LINK_BASES, f"{where}.structure_links[{i}].basis")
    _has(record["extraction"], EXTRACTION_KEYS, f"{where}.extraction")


def validate_reference(record: Any) -> None:
    """Refuse a reference record that leaves the spec 3.4 shape (``content_hash`` may be null)."""
    _has(record, REFERENCE_KEYS, "reference")
    ref_id = record["ref_id"]
    _require(type(ref_id) is str and ref_id != "", "reference: ref_id must be a non-empty string")
    where = f"reference {ref_id}"
    _require(record["review_status"] == "unreviewed", f"{where}: review_status must stay 'unreviewed'")
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1, f"{where}: schema_version")
    _require(is_accession(record["uniprot"]), f"{where}: uniprot is not an accession")
    _require(record["content_hash"] is None
             or (type(record["content_hash"]) is str and _RECORD_HASH.fullmatch(record["content_hash"])),
             f"{where}: content_hash is not sha256:<hex> or null")


class DistRecords(NamedTuple):
    moves: list[dict[str, Any]]
    moves_flagged: list[dict[str, Any]]
    references: list[dict[str, Any]]
    verification: dict[str, Any]   # the manifest ``verification`` object of these files


def validate_dist_files(moves_data: bytes, moves_flagged_data: bytes, references_data: bytes) -> DistRecords:
    """Parse the three dist files and apply every spec 3.4 rule (formats, record hashes, unique IDs)."""
    files = {}
    seen: set[str] = set()
    for source, data in (("moves", moves_data), ("moves_flagged", moves_flagged_data)):
        name = SOURCE_FILE_NAMES[source]
        records = parse_jsonl(data, name)
        for number, record in enumerate(records, start=1):
            try:
                validate_move(record)
            except FormatError as exc:
                raise FormatError(f"{name} line {number}: {exc}") from exc
            _require(hash_matches(record), f"{name} line {number}: content_hash differs from the record")
            _require(record["move_id"] not in seen, f"{name} line {number}: move_id {record['move_id']} repeats")
            seen.add(record["move_id"])
        files[source] = records
    references = parse_jsonl(references_data, REFERENCES_FILE_NAME)
    ref_ids: set[str] = set()
    without_hash = 0
    for number, record in enumerate(references, start=1):
        try:
            validate_reference(record)
        except FormatError as exc:
            raise FormatError(f"{REFERENCES_FILE_NAME} line {number}: {exc}") from exc
        if record["content_hash"] is None:
            without_hash += 1
        else:
            _require(hash_matches(record), f"{REFERENCES_FILE_NAME} line {number}: content_hash differs")
        _require(record["ref_id"] not in ref_ids, f"{REFERENCES_FILE_NAME} line {number}: ref_id repeats")
        ref_ids.add(record["ref_id"])
    verification = {"records_hash_verified": {"moves": len(files["moves"]),
                                              "moves_flagged": len(files["moves_flagged"]),
                                              "references": len(references) - without_hash},
                    "references_without_hash": without_hash}
    return DistRecords(files["moves"], files["moves_flagged"], references, verification)


def parse_pubmed(data: bytes) -> list[dict[str, Any]]:
    """Bibliography rows: JSON objects whose ``id`` is a PMID string, unique (spec 4.2 step 4)."""
    rows = parse_jsonl(data, "pubmed documents.jsonl")
    ids: set[str] = set()
    for number, row in enumerate(rows, start=1):
        pmid = row.get("id")
        _require(type(pmid) is str and _PMID.fullmatch(pmid), f"pubmed line {number}: id is not a PMID string")
        _require(pmid not in ids, f"pubmed line {number}: id {pmid} repeats")
        ids.add(pmid)
    return rows


def bibliography_entries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """PMID -> ``{title, journal, year, doi, pmc}`` (row values as they are) for rows whose ``status`` is ``"ok"``
    and whose ``data.pmid`` equals ``id``, with the five fields present as strings or null; other rows give no
    bibliography (shown as "no bibliography", never as an error)."""
    out = {}
    for row in rows:
        data = row.get("data")
        if row.get("status") != "ok" or type(data) is not dict or data.get("pmid") != row["id"]:
            continue
        if all(key in data and (data[key] is None or type(data[key]) is str) for key in BIBLIOGRAPHY_FIELDS):
            out[row["id"]] = {key: data[key] for key in BIBLIOGRAPHY_FIELDS}
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------------------------- pins and manifest

def check_kbase_pins(meta: Any) -> None:
    """The dist manifest ``meta`` (or a set's ``kbase`` block) carries exactly the three pinned strings."""
    _require(type(meta) is dict, "kbase meta: expected an object")
    for key, value in KBASE_PINS.items():
        _require(type(meta.get(key)) is str and meta[key] == value, f"kbase {key} differs from the pinned value")


def pointer_bytes(set_hash: str) -> bytes:
    """The ``active.json`` bytes for a set hash."""
    pointer = {"schema": POINTER_SCHEMA, "set_hash": set_hash}
    validate_pointer(pointer)
    return canonical_json(pointer)


def validate_pointer(obj: Any) -> str:
    """The set hash of a valid ``precedent_active@1`` pointer."""
    _require(type(obj) is dict and set(obj) == {"schema", "set_hash"} and obj["schema"] == POINTER_SCHEMA
             and type(obj["set_hash"]) is str and _HEX64.fullmatch(obj["set_hash"]), "unknown active pointer")
    return obj["set_hash"]


def _count(value: Any, cap: int | None = None) -> bool:
    return type(value) is int and value >= 0 and (cap is None or value <= cap)


def _text(value: Any) -> bool:
    return type(value) is str and value != ""


KBASE_KEYS = ("commit", "dist_commit", "dist_commit_date", "dirty", "kb_version", "schema_version",
              "effect_rules_version", "vocab_version", "source_snapshots", "origin")
_FILE_KEYS = frozenset({"name", "path", "sha256", "bytes", "rows"})
_MANIFEST_KEYS = frozenset({"schema", "imported_at", "importer_version", "kbase", "files", "bibliography",
                            "verification"})
_BIBLIOGRAPHY_KEYS = frozenset({"snapshot_id", "date", "license", "origin", "file"})


def validate_kbase_block(obj: Any) -> None:
    """The manifest ``kbase`` object (spec 3.2), pins included."""
    _require(type(obj) is dict and set(obj) == set(KBASE_KEYS), "kbase: unexpected keys")
    _require(type(obj["commit"]) is str and _HEX40.fullmatch(obj["commit"]), "kbase.commit must be 40 hex")
    if obj["dist_commit"] is None:
        _require(obj["dist_commit_date"] is None, "kbase.dist_commit_date must be null without a dist commit")
    else:
        _require(type(obj["dist_commit"]) is str and _HEX40.fullmatch(obj["dist_commit"]),
                 "kbase.dist_commit must be 40 hex or null")
        _require(type(obj["dist_commit_date"]) is str and _GIT_DATE.fullmatch(obj["dist_commit_date"]),
                 "kbase.dist_commit_date must be the commit's ISO date")
    _require(type(obj["dirty"]) is bool, "kbase.dirty must be a boolean")
    _require(type(obj["kb_version"]) is str, "kbase.kb_version must be a string")
    check_kbase_pins(obj)
    _require(type(obj["source_snapshots"]) is list and all(type(s) is str for s in obj["source_snapshots"]),
             "kbase.source_snapshots must be a list of strings")
    _require(obj["origin"] == KBASE_ORIGIN, "kbase.origin")


def validate_file_entry(entry: Any, name: str, kbase_sha256: bool) -> None:
    """One manifest file record (``kbase_sha256`` present and equal to ``"sha256:" + sha256`` when asked)."""
    keys = _FILE_KEYS | {"kbase_sha256"} if kbase_sha256 else _FILE_KEYS
    _require(type(entry) is dict and set(entry) == keys, f"file record {name}: unexpected keys")
    _require(entry["name"] == name and entry["path"] == file_path(name), f"file record {name}: name or path")
    _require(type(entry["sha256"]) is str and _HEX64.fullmatch(entry["sha256"]), f"file record {name}: sha256")
    _require(_count(entry["bytes"], MAX_FILE_BYTES), f"file record {name}: bytes")
    _require(_count(entry["rows"], MAX_FILE_ROWS), f"file record {name}: rows")
    if kbase_sha256:
        _require(entry["kbase_sha256"] == "sha256:" + entry["sha256"], f"file record {name}: kbase_sha256")


def validate_manifest(obj: Any) -> None:
    """A ``precedent_reference_set@1`` manifest with exactly the keys and values of spec 3.2."""
    _require(type(obj) is dict and set(obj) == _MANIFEST_KEYS and obj["schema"] == SET_SCHEMA,
             "unknown set manifest")
    _require(type(obj["imported_at"]) is str and _IMPORTED_AT.fullmatch(obj["imported_at"]),
             "imported_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
    _require(obj["importer_version"] == IMPORTER_VERSION, "unknown importer version")
    validate_kbase_block(obj["kbase"])
    files = obj["files"]
    _require(type(files) is list and len(files) == len(DIST_FILE_NAMES), "files must be the three dist files")
    for entry, name in zip(files, DIST_FILE_NAMES):
        validate_file_entry(entry, name, True)
    bibliography = obj["bibliography"]
    _require(type(bibliography) is dict and set(bibliography) == _BIBLIOGRAPHY_KEYS, "bibliography: unexpected keys")
    _require(_text(bibliography["snapshot_id"]), "bibliography.snapshot_id")
    _require(type(bibliography["date"]) is str and _DATE.fullmatch(bibliography["date"]), "bibliography.date")
    _require(_text(bibliography["license"]), "bibliography.license")
    _require(bibliography["origin"] == BIBLIOGRAPHY_ORIGIN, "bibliography.origin")
    validate_file_entry(bibliography["file"], pubmed_file_name(bibliography["date"]), True)
    verification = obj["verification"]
    _require(type(verification) is dict and set(verification) == {"records_hash_verified", "references_without_hash"},
             "verification: unexpected keys")
    verified = verification["records_hash_verified"]
    _require(type(verified) is dict and set(verified) == {"moves", "moves_flagged", "references"}
             and all(_count(v) for v in verified.values()) and _count(verification["references_without_hash"]),
             "verification: counts must be non-negative integers")
    _require(verified["moves"] == files[0]["rows"] and verified["moves_flagged"] == files[1]["rows"],
             "verification: every move record is hash-verified")
    _require(verified["references"] + verification["references_without_hash"] == files[2]["rows"],
             "verification: reference counts differ from the file's rows")


def manifest_bytes(obj: dict[str, Any]) -> bytes:
    """The canonical bytes of a valid manifest (the set hash is their SHA-256)."""
    validate_manifest(obj)
    return canonical_json(obj)
