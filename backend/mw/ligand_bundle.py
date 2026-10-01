"""M17 ligand job lane on the server side: capability, admission, call key, staging, publication, validated reads.

The server never imports RDKit. The capability handshake runs ``ligand_worker.py --handshake`` in the pinned
``.deps/prolif/venv-locked`` interpreter (only a verified handshake is cached). Admission checks request shape,
same-run import handles and, for enumeration, the site against the stored inspection graph
(``mw.ligand_site.check_site``) before any job exists. The worker reads only staged JSON + bytes; publication
re-validates its output against the job's staged selection and stores objects whose content never includes
time, job or attempt identities (same input -> same handle). Every read re-validates the stored object against
its single completed publication and its inputs, so a tampered or uncompleted object never reads.

Objects: ``ligand_inspection@1`` (kind ``ligand_inspection``) and ``ligand_candidate_set@1`` (kind
``ligand_candidate_set``). Both recover from ``events.jsonl`` alone (``object_created`` payloads).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import threading
from pathlib import Path
from typing import Any

from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json
from .ligand_constants import (
    ALLOWED_ELEMENTS,
    BLOCK_IMPORT_KINDS,
    BLOCK_INPUT_FORMATS,
    BLOCK_REJECT_REASONS,
    FIXED_METHOD,
    FIXED_RULE_ID,
    LIMITATIONS,
    MAX_ATTEMPTS,
    MAX_BLOCK_NAME_CHARS,
    MAX_BLOCKS,
    MAX_CANDIDATES,
    MAX_INPUT_BYTES,
    MAX_PARENT_HEAVY_ATOMS,
    MAX_PRODUCT_HEAVY_ATOMS,
    MAX_REPORTED_BLOCK_REJECTIONS,
    MAX_RULE_BYTES,
    MAX_RULES,
    PARENT_REJECT_REASONS,
    PRODUCT_REJECT_REASONS,
    PROPERTY_NAMES,
    RULE_REASONS,
    RULE_VALID,
    SITE_REASONS,
    STEREO_FLAGS,
    STOP_REASONS,
    USER_RULE_METHOD,
    USER_RULE_PREFIX,
)
from .ligand_site import check_site

ROOT = Path(__file__).resolve().parents[2]
# Deployment-fixed paths; a request can never name an interpreter, module, path, env or argv.
WORKER = ROOT / "backend/mw/jobs/ligand_worker.py"
WORKER_PYTHON = ROOT / ".deps/prolif/venv-locked/bin/python"
LOCK = ROOT / "config/chemical/prolif-wheel-hashes-macos-arm64-py311.json"
CONSTANTS = ROOT / "backend/mw/ligand_constants.py"
INSPECT = "rdkit_inspect_v1"
ENUMERATE = "rdkit_enumerate_v1"
PROTOCOLS = frozenset({INSPECT, ENUMERATE})
TOOLS = {INSPECT: "rdkit_inspect_ligand", ENUMERATE: "rdkit_enumerate_ligands"}
IMPLEMENTATIONS = {INSPECT: "rdkit_inspect_v1@1", ENUMERATE: "rdkit_enumerate_v1@1"}
OUTPUT_KINDS = {INSPECT: "ligand_inspection", ENUMERATE: "ligand_candidate_set"}
RDKIT_VERSION = "2026.03.6"
PAINS_CATALOG_ENTRIES = {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 409}
TIMEOUT_S = 120
# Staged structure.json: the parent and both block libraries travel as base64 (each import <= 10 MiB, so
# at most 3 x 10 MiB x 4/3 ~= 40 MiB plus <= 10 rule texts). The generic 4,000,000 B lane bound would refuse
# valid inputs, so this lane has its own bound, equal to the worker's own read bound (ligand_worker.py).
STAGED_LIMIT = 48 * 1024 * 1024
OUTPUT_LIMIT = 32 * 1024 * 1024  # worker MAX_OUTPUT_BYTES; guardian reads at most this much
MAX_INSPECTION_BYTES = 1024 * 1024  # spec 6.2
MAX_SVG_BYTES = 256 * 1024  # spec 6.2
MAX_SET_BYTES = OUTPUT_LIMIT
# Admission bound per rule text. Longer than the 4 KiB rule cap on purpose: the inspection reports
# ``too_large`` per rule (spec 4.3) instead of the request being refused; this only bounds the job record.
MAX_RULE_TEXT_ADMISSION = 64 * 1024
MAX_SMILES_CHARS = 20_000
# Generation caps staged to the worker. Fixed by code (spec defaults); tests may lower them through this
# internal hook, never through a request field. The values are part of the call key and the stored object.
ENUMERATE_LIMITS = {"max_candidates": MAX_CANDIDATES, "max_attempts": MAX_ATTEMPTS}
PAINS_CATALOGS = ("PAINS_A", "PAINS_B", "PAINS_C")
INT_PROPERTIES = frozenset({"hbd", "hba", "rotatable_bonds", "heavy_atoms", "formal_charge"})
REASONS = {
    "worker_missing": "RDKit 작업 환경(.deps/prolif/venv-locked)이나 작업 모듈이 없습니다.",
    "handshake_failed": "RDKit 작업 프로세스 확인(handshake)에 실패했습니다.",
    "rdkit_version_mismatch": f"작업 환경의 RDKit 버전이 고정 버전 {RDKIT_VERSION}과 다릅니다.",
    "pains_catalog_unavailable": "RDKit PAINS A·B·C 카탈로그를 고정 항목 수로 불러오지 못했습니다.",
}
WORKER_ERRORS = {
    "input_invalid": frozenset({*PARENT_REJECT_REASONS, *SITE_REASONS, "rule_invalid", "no_generation_method"}),
    "resource_exceeded": frozenset({"svg_limit", "output_limit"}),
    "fatal": frozenset({"staged_input_invalid", "rdkit_version_mismatch", "worker_internal_error"}),
}
PIN_KEYS = ("engine", "rdkit_version", "worker_sha256", "constants_sha256", "lock_sha256")
INSPECTION_KEYS = frozenset({"schema", "protocol", "method", "parent_handle", "block_handles", "input_sha256",
                             "parent", "property_methods", "block_libraries", "rules"})
INSPECT_OUTPUT_KEYS = frozenset({"schema", "protocol", "rdkit_version", "input_sha256", "parent", "property_methods",
                                 "block_libraries", "rules", "job_id", "attempt_id"})
PARENT_KEYS = frozenset({"sha256", "atoms_in_sdf", "heavy_atom_count", "canonical_smiles", "atoms", "bonds",
                         "hydrogens", "svg", "svg_bytes", "properties"})
LIBRARY_KEYS = frozenset({"kind", "input_format", "sha256", "records_total", "records_read", "block_limit_reached",
                          "accepted", "rejected", "rejected_total", "rejected_counts", "fixed_targets",
                          "rule_targets"})
ENUMERATE_FIELDS = ("input_sha256", "parent_sha256", "parent_canonical_smiles", "parent_properties",
                    "property_methods", "site_atoms", "retained_parent_atoms", "crossing_bond", "use_fixed",
                    "rules_used", "methods", "block_libraries", "candidates", "counts", "limits", "limit_reached",
                    "stop_reason", "limitations")
ENUMERATE_OUTPUT_KEYS = frozenset({"schema", "protocol", "rdkit_version", "job_id", "attempt_id", *ENUMERATE_FIELDS})
SET_KEYS = frozenset({"schema", "protocol", "method", "inspection_handle", "parent_handle", "block_handles",
                      *ENUMERATE_FIELDS})
ROW_KEYS = frozenset({"id", "smiles", "origins", "retained_parent_atoms", "stereo_flag", "properties", "pains"})
COUNT_KEYS = frozenset({"blocks_accepted", "raw_products", "candidates", "duplicate_products", "rejected",
                        "not_applicable"})
SHA_RE = re.compile(r"[0-9a-f]{64}")
CANDIDATE_ID_RE = re.compile(r"c_[0-9a-f]{16}")

_HANDSHAKE_CACHE: dict[tuple, dict[str, Any]] = {}
_HANDSHAKE_LOCK = threading.Lock()


class LigandJobFailure(Exception):
    """A typed attempt failure after reservation (charged); nothing is published."""

    def __init__(self, failure_class: str, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code
        self.message = message

    def to_error(self) -> dict[str, Any]:
        return {"error": self.failure_class, "message": self.message, "reason_code": self.reason_code}


class LigandEvidenceError(ValueError):
    """A stored or produced ligand object does not validate against its inputs and publication."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _invalid(message: str, reason_code: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code, **detail})


# ----------------------------------------------------------------- capability (no RDKit in this process)
def _handshake_key() -> tuple:
    interpreter = WORKER_PYTHON.resolve(strict=True)
    info = interpreter.stat()
    return (str(WORKER_PYTHON), str(interpreter), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            _sha(LOCK.read_bytes()), _sha(WORKER.read_bytes()), _sha(CONSTANTS.read_bytes()))


def _handshake() -> dict[str, Any]:
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER), "--handshake"], cwd=ROOT,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=True)
    if len(proc.stdout) > 8192 or len(proc.stderr) > 8192:
        raise ValueError("oversized handshake output")
    data = json.loads(proc.stdout)
    if (type(data) is not dict or data.get("schema") != "ligand_worker_handshake@1" or
            data.get("worker_sha256") != _sha(WORKER.read_bytes()) or
            data.get("protocols") != [INSPECT, ENUMERATE] or
            str(data.get("python", "")).split(".")[:2] != ["3", "11"] or
            type(data.get("rdkit_version")) is not str or type(data.get("pains_catalog_entries")) is not dict):
        raise ValueError("invalid ligand worker handshake")
    return data


def _ready(data: dict[str, Any]) -> dict[str, Any]:
    pins = {"engine": "rdkit", "rdkit_version": data["rdkit_version"], "worker_sha256": data["worker_sha256"],
            "constants_sha256": _sha(CONSTANTS.read_bytes()), "lock_sha256": _sha(LOCK.read_bytes())}
    return {"available": True, "status": "ready", "reason_code": None, "reason": None, "pins": pins,
            "pains_catalog_entries": data["pains_catalog_entries"]}


def capability() -> dict[str, Any]:
    """``available`` only when the locked environment exists, RDKit is the pinned version and PAINS A/B/C load."""
    base = {"schema": "ligand_capability@1", "engine": "rdkit", "rdkit_version_expected": RDKIT_VERSION,
            "protocols": [INSPECT, ENUMERATE], "tools": dict(TOOLS), "execution_lane": "durable_job",
            "timeout_s": TIMEOUT_S, "limits": {"input_bytes_per_file": MAX_INPUT_BYTES, "blocks": MAX_BLOCKS,
                                               "rules": MAX_RULES, "rule_bytes": MAX_RULE_BYTES,
                                               "parent_heavy_atoms": MAX_PARENT_HEAVY_ATOMS,
                                               "candidates": MAX_CANDIDATES, "attempts": MAX_ATTEMPTS,
                                               "svg_bytes": MAX_SVG_BYTES, "inspection_bytes": MAX_INSPECTION_BYTES},
            "limitations": list(LIMITATIONS)}

    def unavailable(status: str) -> dict[str, Any]:
        return {**base, "available": False, "status": status, "reason_code": status, "reason": REASONS[status],
                "pins": None, "pains_catalog_entries": None}

    if not (WORKER_PYTHON.is_file() and WORKER.is_file() and LOCK.is_file() and CONSTANTS.is_file()):
        return unavailable("worker_missing")
    with _HANDSHAKE_LOCK:
        try:
            key = _handshake_key()
        except OSError:
            return unavailable("worker_missing")
        cached = _HANDSHAKE_CACHE.get(key)
        if cached is not None:
            return {**base, **copy.deepcopy(cached)}
        try:
            data = _handshake()
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, KeyError):
            return unavailable("handshake_failed")
        if data["rdkit_version"] != RDKIT_VERSION or data.get("rdkit_version_expected") != RDKIT_VERSION:
            return unavailable("rdkit_version_mismatch")
        if data["pains_catalog_entries"] != PAINS_CATALOG_ENTRIES:
            return unavailable("pains_catalog_unavailable")
        ready = _ready(data)
        _HANDSHAKE_CACHE.clear()  # only a verified handshake is reused, while its key is unchanged
        _HANDSHAKE_CACHE[key] = copy.deepcopy(ready)
        return {**base, **ready}


def require_ready() -> dict[str, Any]:
    """The pins a job records at submission (raises a precondition failure when unavailable)."""
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"], detail={"reason_code": value["reason_code"]})
    return value["pins"]


# ----------------------------------------------------------------- admission (no job, no tool, no RDKit)
def _utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _import_meta(run: Any, handle: Any, kinds: tuple[str, ...], reason: str) -> dict[str, Any]:
    if type(handle) is not str:
        raise _invalid("import handle must be a string", reason)
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise _invalid("unknown same-run import handle", reason) from exc
    summary = meta["summary"]
    if ((meta["kind"], meta["schema"]) != ("chemical_raw_input", "chemical_raw_input@1") or
            summary.get("input_kind") not in kinds or type(summary.get("sha256")) is not str or
            not SHA_RE.fullmatch(summary["sha256"]) or meta["fmt"] in ("json", "parquet") or
            not 0 < meta["size"] <= MAX_INPUT_BYTES):
        raise _invalid("handle is not an import of the required kind", reason)
    return meta


def _import_order(run: Any, handles: list[str]) -> list[str]:
    """Import (creation) order of same-run import objects, from the event log."""
    seq = {event["handle"]: event["seq"] for event in run.events.read()
           if event["type"] == "object_created" and event.get("handle") in handles}
    return sorted(handles, key=lambda handle: seq[handle])


def _inspect_submission(run: Any, args: dict[str, Any]) -> tuple[dict, dict, list[str]]:
    if not set(args) <= {"parent_sdf_handle", "block_handles", "rules"} or "parent_sdf_handle" not in args:
        raise _invalid("inspection arguments are {parent_sdf_handle, block_handles, rules}", "invalid_job_arguments")
    blocks, rules = args.get("block_handles", []), args.get("rules", [])
    if type(blocks) is not list or len(blocks) > len(BLOCK_IMPORT_KINDS) or len(set(map(str, blocks))) != len(blocks):
        raise _invalid("zero to two distinct building-block handles", "invalid_job_arguments")
    if (type(rules) is not list or len(rules) > MAX_RULES or
            any(type(text) is not str or not _utf8(text) or len(text.encode("utf-8")) > MAX_RULE_TEXT_ADMISSION
                for text in rules)):
        raise _invalid(f"at most {MAX_RULES} UTF-8 rule texts", "rule_text_invalid")
    parent = _import_meta(run, args["parent_sdf_handle"], ("ligand_sdf",), "parent_import_invalid")
    metas = {handle: _import_meta(run, handle, BLOCK_IMPORT_KINDS, "block_import_invalid") for handle in blocks}
    if len({meta["summary"]["input_kind"] for meta in metas.values()}) != len(metas):
        raise _invalid("at most one building-block import per kind", "block_import_invalid")
    ordered = _import_order(run, blocks)
    selected = {"schema": "ligand_inspect_selection@1",
                "parent": {"handle": parent["handle"], "sha256": parent["summary"]["sha256"]},
                "blocks": [{"kind": metas[h]["summary"]["input_kind"], "handle": h,
                            "sha256": metas[h]["summary"]["sha256"]} for h in ordered],
                "rules": list(rules)}
    normalized = {"parent_sdf_handle": parent["handle"], "block_handles": ordered, "rules": list(rules)}
    return selected, normalized, [parent["handle"], *ordered]


def _enumerate_submission(run: Any, args: dict[str, Any]) -> tuple[dict, dict, list[str]]:
    if (not set(args) <= {"inspection_handle", "site_atoms", "use_fixed", "rule_ids"} or
            not {"inspection_handle", "site_atoms", "use_fixed"} <= set(args)):
        raise _invalid("enumeration arguments are {inspection_handle, site_atoms, use_fixed, rule_ids}",
                       "invalid_job_arguments")
    use_fixed, rule_ids = args["use_fixed"], args.get("rule_ids", [])
    if (type(use_fixed) is not bool or type(rule_ids) is not list or len(rule_ids) > MAX_RULES or
            any(type(rule_id) is not str for rule_id in rule_ids) or len(set(rule_ids)) != len(rule_ids)):
        raise _invalid("use_fixed must be a boolean and rule_ids distinct strings", "invalid_job_arguments")
    if not use_fixed and not rule_ids:
        raise _invalid("fixed replacement and all rules are off", "no_generation_method")
    try:
        inspection = validated_inspection(run, args["inspection_handle"])
    except LigandEvidenceError as exc:
        raise _invalid("inspection handle is not a completed same-run ligand inspection",
                       "inspection_invalid") from exc
    graph = {key: inspection["parent"][key] for key in ("atoms", "bonds", "hydrogens")}
    try:
        site = check_site(graph, args["site_atoms"])
    except ToolFailure as exc:
        raise _invalid("site atoms must be a list of distinct integer SDF serials", "site_atoms_invalid") from exc
    if not site["valid"]:
        raise _invalid(f"site rejected: {site['reason']}", site["reason"], site_check=site)
    statuses = {row["rule_id"]: row for row in inspection["rules"]}
    rules = []
    for rule_id in rule_ids:
        row = statuses.get(rule_id)
        if row is None or row["status"] != RULE_VALID:
            raise _invalid(f"rule {rule_id} is not a valid rule of this inspection", "rule_invalid", rule_id=rule_id,
                           status=None if row is None else row["status"])
        rules.append({"rule_id": rule_id, "text": row["text"]})
    parent = {"handle": inspection["parent_handle"], "sha256": inspection["parent"]["sha256"]}
    blocks = [{"kind": library["kind"], "handle": handle, "sha256": library["sha256"]}
              for handle, library in zip(inspection["block_handles"], inspection["block_libraries"], strict=True)]
    selected = {"schema": "ligand_enumerate_selection@1", "inspection_handle": args["inspection_handle"],
                "parent": parent, "blocks": blocks, "site_atoms": site["site_atoms"], "use_fixed": use_fixed,
                "rules": rules, "limits": dict(ENUMERATE_LIMITS)}
    normalized = {"inspection_handle": args["inspection_handle"], "site_atoms": site["site_atoms"],
                  "use_fixed": use_fixed, "rule_ids": list(rule_ids)}
    return selected, normalized, [args["inspection_handle"], parent["handle"], *[b["handle"] for b in blocks]]


def submission(run: Any, protocol: str, args: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """(selected, normalized parameters, input handles); every refusal is input_invalid with a reason code."""
    if type(args) is not dict:
        raise _invalid("job arguments must be an object", "invalid_job_arguments")
    return _inspect_submission(run, args) if protocol == INSPECT else _enumerate_submission(run, args)


def call_key(protocol: str, selected: dict[str, Any], pins: dict[str, Any]) -> str:
    """Spec 6.1: handles (blocks keyed by kind), rules in request order, ascending site, booleans, caps, pins."""
    if protocol == INSPECT:
        fields = {"parent": selected["parent"]["handle"],
                  "blocks": {block["kind"]: block["handle"] for block in selected["blocks"]},
                  "rules": selected["rules"]}
    else:
        fields = {"inspection": selected["inspection_handle"], "site_atoms": selected["site_atoms"],
                  "use_fixed": selected["use_fixed"], "rule_ids": [rule["rule_id"] for rule in selected["rules"]],
                  "limits": selected["limits"]}
    return idempotency_key(protocol, IMPLEMENTATIONS[protocol], {"parameters": fields, "method": pins})


# ----------------------------------------------------------------- staging
def _import_bytes(run: Any, entry: dict[str, Any], kinds: tuple[str, ...]) -> bytes:
    meta = _import_meta(run, entry["handle"], kinds, "staged_input_invalid")
    raw = run.store.load_bounded_bytes(entry["handle"], MAX_INPUT_BYTES)
    if _sha(raw) != entry["sha256"] or meta["summary"]["sha256"] != entry["sha256"]:
        raise ValueError("import bytes changed since submission")
    return raw


def stage(run: Any, job: dict[str, Any], attempt_id: str) -> bytes:
    """The worker payload, re-read from the immutable import objects (never stored in the job record)."""
    selected = job["selected"]
    parent_raw = _import_bytes(run, selected["parent"], ("ligand_sdf",))
    blocks = [{"kind": block["kind"], "b64": base64.b64encode(_import_bytes(run, block, (block["kind"],))).decode(),
               "sha256": block["sha256"]} for block in selected["blocks"]]
    payload: dict[str, Any] = {"parent": {"sdf_b64": base64.b64encode(parent_raw).decode(),
                                          "sha256": selected["parent"]["sha256"]}, "blocks": blocks}
    if job["protocol_id"] == INSPECT:
        payload.update(schema="ligand_inspect_worker_input@1", rules=selected["rules"])
    else:
        payload.update(schema="ligand_enumerate_worker_input@1", site_atoms=selected["site_atoms"],
                       use_fixed=selected["use_fixed"], rules=selected["rules"], limits=selected["limits"])
    return canonical_json(payload)


def worker_error(attempt_dir: Path) -> dict[str, Any]:
    """Accept only the worker's small typed envelope with a closed reason; anything else is fatal."""
    fatal = {"error": "fatal", "message": "worker exit or invalid ligand error envelope"}
    try:
        descriptor = os.open(attempt_dir / "error.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4096:
                return fatal
            raw = stream.read(4097)
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (type(data) is not dict or canonical_json(data) != raw or
                set(data) != {"schema", "error_class", "reason_code", "message"} or
                data["schema"] != "ligand_worker_error@1" or data["error_class"] not in WORKER_ERRORS or
                data["reason_code"] not in WORKER_ERRORS[data["error_class"]] or
                type(data["message"]) is not str or not 0 < len(data["message"]) <= 240):
            return fatal
        return {"error": data["error_class"], "reason_code": data["reason_code"], "message": data["message"]}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return fatal


# ----------------------------------------------------------------- validation helpers
def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LigandEvidenceError(message)


def _int(value: Any, low: int = 0, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _pins(value: Any) -> None:
    _require(type(value) is dict and set(value) == set(PIN_KEYS) and value["engine"] == "rdkit" and
             value["rdkit_version"] == RDKIT_VERSION and
             all(type(value[key]) is str and SHA_RE.fullmatch(value[key])
                 for key in ("worker_sha256", "constants_sha256", "lock_sha256")), "method pins")


def _properties(values: Any) -> None:
    _require(type(values) is dict and set(values) == set(PROPERTY_NAMES), "property names")
    for name in PROPERTY_NAMES:
        value = values[name]
        if name in INT_PROPERTIES:
            _require(type(value) is int and (name == "formal_charge" or value >= 0), f"property {name}")
        else:
            _require(_finite(value) and type(value) is not bool, f"property {name}")


def _property_methods(values: Any) -> None:
    _require(type(values) is dict and set(values) == set(PROPERTY_NAMES) and
             all(type(text) is str and 0 < len(text) <= 200 for text in values.values()), "property methods")


def _check_imports(run: Any, selected: dict[str, Any]) -> None:
    try:
        parent = _import_meta(run, selected["parent"]["handle"], ("ligand_sdf",), "parent_import_invalid")
        _require(parent["summary"]["sha256"] == selected["parent"]["sha256"], "parent import hash")
        for block in selected["blocks"]:
            meta = _import_meta(run, block["handle"], (block["kind"],), "block_import_invalid")
            _require(meta["summary"]["sha256"] == block["sha256"], "block import hash")
    except ToolFailure as exc:
        raise LigandEvidenceError("import evidence") from exc
    _require(len({block["kind"] for block in selected["blocks"]}) == len(selected["blocks"]) <= 2, "block kinds")


def _check_graph(parent: dict[str, Any]) -> None:
    atoms, bonds, hydrogens = parent["atoms"], parent["bonds"], parent["hydrogens"]
    graph = {"atoms": atoms, "bonds": bonds, "hydrogens": hydrogens}
    try:
        check_site(graph, [])  # structural validation of the graph (raises on a malformed table)
    except ToolFailure as exc:
        raise LigandEvidenceError("parent graph") from exc
    heavy = [atom["serial"] for atom in atoms]
    _require(_int(parent["heavy_atom_count"], 1, MAX_PARENT_HEAVY_ATOMS) and len(atoms) == parent["heavy_atom_count"],
             "heavy atom count")
    _require(heavy == sorted(heavy) and [row["serial"] for row in hydrogens] == sorted(row["serial"]
                                                                                     for row in hydrogens), "order")
    _require(_int(parent["atoms_in_sdf"], 1) and
             sorted(heavy + [row["serial"] for row in hydrogens]) == list(range(1, parent["atoms_in_sdf"] + 1)),
             "serials cover the SDF atom block")
    for atom in atoms:
        _require(set(atom) == {"serial", "element", "formal_charge", "neighbors"} and
                 atom["element"] in ALLOWED_ELEMENTS and atom["element"] != "H" and
                 type(atom["formal_charge"]) is int and atom["neighbors"] == sorted(atom["neighbors"]), "atom row")
    _require(all(bond["a"] < bond["b"] for bond in bonds) and
             [(b["a"], b["b"]) for b in bonds] == sorted((b["a"], b["b"]) for b in bonds), "bond order")
    seen, frontier = {heavy[0]}, [heavy[0]]
    adjacency = {atom["serial"]: atom["neighbors"] for atom in atoms}
    while frontier:
        for other in adjacency[frontier.pop()]:
            if other not in seen:
                seen.add(other)
                frontier.append(other)
    _require(len(seen) == len(heavy), "parent heavy atoms are one connected fragment")


def _check_libraries(libraries: Any, selected_blocks: list[dict[str, Any]]) -> None:
    _require(type(libraries) is list and len(libraries) == len(selected_blocks), "block library count")
    read_total, cut = 0, False
    for library, block in zip(libraries, selected_blocks, strict=True):
        _require(type(library) is dict and set(library) == LIBRARY_KEYS, "block library keys")
        _require(library["kind"] == block["kind"] and library["sha256"] == block["sha256"] and
                 library["input_format"] == BLOCK_INPUT_FORMATS[block["kind"]], "block library identity")
        counts = library["rejected_counts"]
        _require(all(_int(library[key]) for key in ("records_total", "records_read", "accepted", "rejected_total",
                                                    "fixed_targets", "rule_targets")) and
                 type(counts) is dict and set(counts) == set(BLOCK_REJECT_REASONS) and
                 all(_int(value) for value in counts.values()), "block library numbers")
        _require(library["rejected_total"] == sum(counts.values()) and
                 library["accepted"] + library["rejected_total"] == library["records_read"] <= library["records_total"]
                 and library["fixed_targets"] + library["rule_targets"] <= library["accepted"], "block counts")
        _require(library["block_limit_reached"] is (library["records_read"] < library["records_total"]),
                 "block limit flag")
        _require(not cut or library["records_read"] == 0, "shared block cap reads libraries in input order")
        read_total += library["records_read"]
        if library["block_limit_reached"]:
            _require(read_total == MAX_BLOCKS, "block cap reached at the shared limit")
            cut = True
        rejected = library["rejected"]
        _require(type(rejected) is list and
                 len(rejected) == min(library["rejected_total"], MAX_REPORTED_BLOCK_REJECTIONS), "rejected rows")
        previous = 0
        tally = dict.fromkeys(BLOCK_REJECT_REASONS, 0)
        for row in rejected:
            _require(type(row) is dict and set(row) == {"ordinal", "name", "reason"} and
                     _int(row["ordinal"], previous + 1, library["records_read"]) and
                     type(row["name"]) is str and 0 < len(row["name"]) <= MAX_BLOCK_NAME_CHARS and
                     row["reason"] in BLOCK_REJECT_REASONS, "rejected row")
            previous = row["ordinal"]
            tally[row["reason"]] += 1
        _require(all(tally[reason] <= counts[reason] for reason in BLOCK_REJECT_REASONS), "rejected tally")
    _require(read_total <= MAX_BLOCKS, "block cap")


def _check_rules(rows: Any, texts: list[str]) -> None:
    _require(type(rows) is list and len(rows) == len(texts), "rule rows")
    for position, (row, text) in enumerate(zip(rows, texts, strict=True), start=1):
        _require(type(row) is dict and set(row) == {"rule_id", "status", "text", "text_sha256"} and
                 row["rule_id"] == f"{USER_RULE_PREFIX}{position}" and
                 row["status"] in (RULE_VALID, *RULE_REASONS) and
                 row["text_sha256"] == _sha(text.encode("utf-8")), "rule row")
        too_large = len(text.encode("utf-8")) > MAX_RULE_BYTES
        _require((row["status"] == "too_large") is too_large, "too_large status")
        _require(row["text"] == (None if too_large else text), "rule text")
        _require((row["status"] == "duplicate_rule") is (not too_large and text in texts[:position - 1]),
                 "duplicate_rule status")


def check_inspection(run: Any, content: Any, job: dict[str, Any]) -> None:
    """Validate a ``ligand_inspection@1`` content against its producing job (submission selection + pins)."""
    selected = job["selected"]
    _require(type(content) is dict and set(content) == INSPECTION_KEYS and
             content["schema"] == "ligand_inspection@1" and content["protocol"] == INSPECT, "inspection keys")
    _pins(content["method"])
    _require(content["method"] == job["method"], "inspection method differs from the job pins")
    _require(selected.get("schema") == "ligand_inspect_selection@1" and
             content["parent_handle"] == selected["parent"]["handle"] and
             content["block_handles"] == [block["handle"] for block in selected["blocks"]], "inspection inputs")
    _check_imports(run, selected)
    rules = selected["rules"]
    _require(type(rules) is list and len(rules) <= MAX_RULES and
             all(type(text) is str and _utf8(text) for text in rules), "rules")
    _require(content["input_sha256"] == {"parent": selected["parent"]["sha256"],
                                         "blocks": [block["sha256"] for block in selected["blocks"]],
                                         "rules": [_sha(text.encode("utf-8")) for text in rules]},
             "inspection input hashes")
    parent = content["parent"]
    _require(type(parent) is dict and set(parent) == PARENT_KEYS and parent["sha256"] == selected["parent"]["sha256"],
             "parent keys")
    _check_graph(parent)
    svg = parent["svg"]
    _require(type(svg) is str and _int(parent["svg_bytes"], 1, MAX_SVG_BYTES) and
             len(svg.encode("utf-8")) == parent["svg_bytes"] and "<svg" in svg and
             "<script" not in svg.lower() and "javascript:" not in svg.lower(), "parent drawing")
    _require(type(parent["canonical_smiles"]) is str and 0 < len(parent["canonical_smiles"]) <= MAX_SMILES_CHARS,
             "parent SMILES")
    _properties(parent["properties"])
    _require(parent["properties"]["heavy_atoms"] == parent["heavy_atom_count"], "parent heavy atoms property")
    _property_methods(content["property_methods"])
    _check_libraries(content["block_libraries"], selected["blocks"])
    _check_rules(content["rules"], rules)
    _require(len(canonical_json(content)) <= MAX_INSPECTION_BYTES, "inspection size")


def _check_row(row: Any, core: list[int], rule_ids: set[str], parent_smiles: str) -> int:
    _require(type(row) is dict and set(row) == ROW_KEYS, "candidate keys")
    smiles = row["smiles"]
    _require(type(smiles) is str and 0 < len(smiles) <= MAX_SMILES_CHARS and smiles != parent_smiles,
             "candidate SMILES")
    _require(type(row["id"]) is str and CANDIDATE_ID_RE.fullmatch(row["id"]) and
             row["id"] == "c_" + _sha(smiles.encode("utf-8"))[:16], "candidate id")
    origins = row["origins"]
    _require(type(origins) is list and origins and
             all(type(o) is dict and set(o) == {"rule_id", "block_name"} and o["rule_id"] in rule_ids and
                 type(o["block_name"]) is str and 0 < len(o["block_name"]) <= MAX_BLOCK_NAME_CHARS for o in origins) and
             len({(o["rule_id"], o["block_name"]) for o in origins}) == len(origins), "candidate origins")
    _require(row["retained_parent_atoms"] == core and row["stereo_flag"] in STEREO_FLAGS, "candidate core/stereo")
    _properties(row["properties"])
    _require(row["properties"]["heavy_atoms"] <= MAX_PRODUCT_HEAVY_ATOMS, "candidate heavy atoms")
    pains = row["pains"]
    _require(type(pains) is dict and set(pains) == {"matches"} and type(pains["matches"]) is list, "pains")
    keys = []
    for match in pains["matches"]:
        _require(type(match) is dict and set(match) == {"catalog", "name"} and match["catalog"] in PAINS_CATALOGS and
                 type(match["name"]) is str and 0 < len(match["name"]) <= 200, "pains match")
        keys.append((PAINS_CATALOGS.index(match["catalog"]), match["name"]))
    _require(keys == sorted(set(keys)), "pains matches are unique and ordered")
    return len(origins) - 1


def check_candidate_set(content: Any, job: dict[str, Any], inspection: dict[str, Any]) -> None:
    """Validate a ``ligand_candidate_set@1`` content against its job and its (validated) inspection."""
    selected = job["selected"]
    _require(type(content) is dict and set(content) == SET_KEYS and
             content["schema"] == "ligand_candidate_set@1" and content["protocol"] == ENUMERATE, "candidate set keys")
    _pins(content["method"])
    _require(content["method"] == job["method"], "candidate set method differs from the job pins")
    _require(selected.get("schema") == "ligand_enumerate_selection@1" and
             content["inspection_handle"] == selected["inspection_handle"] and
             content["parent_handle"] == inspection["parent_handle"] == selected["parent"]["handle"] and
             content["block_handles"] == inspection["block_handles"] ==
             [block["handle"] for block in selected["blocks"]], "candidate set inputs")
    parent = inspection["parent"]
    _require(content["parent_sha256"] == parent["sha256"] == selected["parent"]["sha256"] and
             content["parent_canonical_smiles"] == parent["canonical_smiles"] and
             content["parent_properties"] == parent["properties"] and
             content["property_methods"] == inspection["property_methods"], "candidate set parent")
    rules = selected["rules"]
    _require(content["input_sha256"] == {"parent": parent["sha256"],
                                         "blocks": [block["sha256"] for block in selected["blocks"]],
                                         "rules": [_sha(rule["text"].encode("utf-8")) for rule in rules]},
             "candidate set input hashes")
    statuses = {row["rule_id"]: row for row in inspection["rules"]}
    _require(all(statuses.get(rule["rule_id"], {}).get("status") == RULE_VALID and
                 statuses[rule["rule_id"]]["text"] == rule["text"] for rule in rules), "rules are inspected valid")
    site = check_site({key: parent[key] for key in ("atoms", "bonds", "hydrogens")}, selected["site_atoms"])
    _require(site["valid"] and content["site_atoms"] == site["site_atoms"] == selected["site_atoms"] and
             content["retained_parent_atoms"] == site["core_atoms"] and
             content["crossing_bond"] == site["crossing_bonds"][0], "site")
    use_fixed = selected["use_fixed"]
    _require(content["use_fixed"] is use_fixed and (use_fixed or bool(rules)), "generation methods")
    used = ([{"rule_id": FIXED_RULE_ID, "method": FIXED_METHOD, "text": None}] if use_fixed else []) + [
        {"rule_id": rule["rule_id"], "method": USER_RULE_METHOD, "text": rule["text"]} for rule in rules]
    _require(content["rules_used"] == used and content["methods"] == [row["method"] for row in used], "rules used")
    _require(content["block_libraries"] == inspection["block_libraries"], "block libraries")
    limits = content["limits"]
    _require(limits == selected["limits"] and type(limits) is dict and
             set(limits) == {"max_candidates", "max_attempts"} and
             _int(limits["max_candidates"], 1, MAX_CANDIDATES) and _int(limits["max_attempts"], 1, MAX_ATTEMPTS),
             "limits")
    _require(content["limitations"] == list(LIMITATIONS), "limitations")
    counts, rows = content["counts"], content["candidates"]
    ids = [row["rule_id"] for row in used]
    _require(type(counts) is dict and set(counts) == COUNT_KEYS and type(rows) is list, "counts keys")
    rejected, not_applicable = counts["rejected"], counts["not_applicable"]
    _require(all(_int(counts[key]) for key in ("blocks_accepted", "raw_products", "candidates", "duplicate_products"))
             and type(rejected) is dict and set(rejected) == set(PRODUCT_REJECT_REASONS) and
             all(_int(value) for value in rejected.values()) and type(not_applicable) is dict and
             set(not_applicable) == set(ids) and all(_int(value) for value in not_applicable.values()), "count values")
    libraries = content["block_libraries"]
    accepted = sum(library["accepted"] for library in libraries)
    _require(counts["blocks_accepted"] == accepted, "blocks accepted")
    _require(all(not_applicable[rule_id] == accepted - sum(library["fixed_targets" if rule_id == FIXED_RULE_ID
                                                                   else "rule_targets"] for library in libraries)
                 for rule_id in ids), "not applicable counts")
    _require(counts["candidates"] == len(rows) <= limits["max_candidates"] and
             counts["raw_products"] == counts["candidates"] + counts["duplicate_products"] + sum(rejected.values())
             <= limits["max_attempts"], "count invariant")
    stop = content["stop_reason"]
    _require(stop in (None, *STOP_REASONS) and content["limit_reached"] is (stop is not None), "stop reason")
    _require(stop != "candidate_limit" or len(rows) == limits["max_candidates"], "candidate limit stop")
    _require(stop != "attempt_limit" or counts["raw_products"] == limits["max_attempts"], "attempt limit stop")
    merged = 0
    for row in rows:
        merged += _check_row(row, content["retained_parent_atoms"], set(ids), content["parent_canonical_smiles"])
    _require(len({row["id"] for row in rows}) == len(rows) and len({row["smiles"] for row in rows}) == len(rows),
             "candidate ids are unique")
    _require(merged <= counts["duplicate_products"], "merged origins exceed duplicate products")


# ----------------------------------------------------------------- publication
def _read_result(attempt_dir: Path, descriptor: Any) -> dict[str, Any]:
    if (type(descriptor) is not dict or set(descriptor) != {"output_sha256", "output_bytes"} or
            type(descriptor["output_bytes"]) is not int or not 0 < descriptor["output_bytes"] <= OUTPUT_LIMIT or
            type(descriptor["output_sha256"]) is not str or not SHA_RE.fullmatch(descriptor["output_sha256"])):
        raise ValueError("invalid ligand output descriptor")
    fd = os.open(attempt_dir / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["output_bytes"]:
            raise ValueError("ligand output size mismatch")
        raw = stream.read(descriptor["output_bytes"] + 1)
    if len(raw) != descriptor["output_bytes"] or _sha(raw) != descriptor["output_sha256"]:
        raise ValueError("ligand output hash mismatch")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if type(data) is not dict or canonical_json(data) != raw:
        raise ValueError("ligand output is not canonical JSON")
    return data


def publish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path, descriptor: Any) -> list[str]:
    """Validate the worker output of this attempt and store exactly one object (or raise, storing nothing)."""
    data = _read_result(attempt_dir, descriptor)
    protocol = job["protocol_id"]
    expected_keys, schema = ((INSPECT_OUTPUT_KEYS, "ligand_inspect_worker_output@1") if protocol == INSPECT else
                             (ENUMERATE_OUTPUT_KEYS, "ligand_enumerate_worker_output@1"))
    if (set(data) != expected_keys or data["schema"] != schema or data["protocol"] != protocol or
            data["job_id"] != job["job_id"] or data["attempt_id"] != attempt_id or
            data["rdkit_version"] != job["method"]["rdkit_version"]):
        raise ValueError("ligand output identity mismatch")
    selected = job["selected"]
    if protocol == INSPECT:
        content = {"schema": "ligand_inspection@1", "protocol": INSPECT, "method": job["method"],
                   "parent_handle": selected["parent"]["handle"],
                   "block_handles": [block["handle"] for block in selected["blocks"]],
                   **{key: data[key] for key in ("input_sha256", "parent", "property_methods", "block_libraries",
                                                 "rules")}}
        if len(canonical_json(content)) > MAX_INSPECTION_BYTES:
            raise LigandJobFailure("resource_exceeded", "inspection_size_limit", "inspection object exceeds 1 MiB")
        check_inspection(run, content, job)
        parent = content["parent"]
        out = run.store.put("ligand_inspection", "ligand_inspection@1", content, produced_by=attempt_id,
                            summary={"parent_handle": content["parent_handle"], "parent_sha256": parent["sha256"],
                                     "heavy_atom_count": parent["heavy_atom_count"],
                                     "blocks_accepted": sum(lib["accepted"] for lib in content["block_libraries"]),
                                     "rules_total": len(content["rules"]),
                                     "rules_valid": sum(row["status"] == RULE_VALID for row in content["rules"])})
        return [out.handle]
    inspection = validated_inspection(run, selected["inspection_handle"])
    content = {"schema": "ligand_candidate_set@1", "protocol": ENUMERATE, "method": job["method"],
               "inspection_handle": selected["inspection_handle"], "parent_handle": inspection["parent_handle"],
               "block_handles": inspection["block_handles"], **{key: data[key] for key in ENUMERATE_FIELDS}}
    check_candidate_set(content, job, inspection)
    counts = content["counts"]
    out = run.store.put("ligand_candidate_set", "ligand_candidate_set@1", content, produced_by=attempt_id,
                        null_result=counts["candidates"] == 0,
                        summary={"inspection_handle": content["inspection_handle"],
                                 "site_atoms": content["site_atoms"], "candidates": counts["candidates"],
                                 "raw_products": counts["raw_products"], "limit_reached": content["limit_reached"],
                                 "stop_reason": content["stop_reason"]})
    return [out.handle]


# ----------------------------------------------------------------- validated reads (never run anything)
def producer(run: Any, handle: str, protocol: str) -> dict[str, Any]:
    """The single completed fixed-protocol publication of ``handle`` (else an evidence error)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for terminal in events:
        if (terminal["type"] != "job_terminal" or terminal.get("status") != "done" or
                terminal.get("output_handles") != [handle]):
            continue
        job = jobs.get(terminal.get("job_id"))
        attempt = terminal.get("attempt_id")
        if job is None or job.get("protocol_id") != protocol or job.get("tool_id") != TOOLS[protocol]:
            continue
        candidates = [event for event in events if event["type"] == "job_result_candidate" and
                      event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                      event.get("output_handles") == [handle] and event["seq"] < terminal["seq"]]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("attempt_id") == attempt and event.get("group_empty") is True]
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == TOOLS[protocol]]
        if (len(candidates) == 1 and len(cleaned) == 1 and len(reserved) == 1 and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < candidates[0]["seq"] and
                created[0]["seq"] < candidates[0]["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": job,
                    "created_seq": created[0]["seq"], "published_seq": terminal["seq"]}
    raise LigandEvidenceError(f"object has no completed {protocol} publication")


def _typed(run: Any, handle: Any, kind: str, limit: int) -> Any:
    if type(handle) is not str:
        raise LigandEvidenceError("handle must be a string")
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise LigandEvidenceError("unknown same-run handle") from exc
    if (meta["kind"], meta["schema"], meta["fmt"]) != (kind, f"{kind}@1", "json"):
        raise LigandEvidenceError(f"expected {kind}")
    return run.store.load_bounded_json(handle, limit)


def validated_inspection(run: Any, handle: Any) -> dict[str, Any]:
    try:
        content = _typed(run, handle, "ligand_inspection", MAX_INSPECTION_BYTES)
        check_inspection(run, content, producer(run, handle, INSPECT)["job"])
        return content
    except LigandEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise LigandEvidenceError("ligand inspection evidence is invalid") from exc


def validated_candidate_set(run: Any, handle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """(candidate set, its validated inspection)."""
    try:
        content = _typed(run, handle, "ligand_candidate_set", MAX_SET_BYTES)
        job = producer(run, handle, ENUMERATE)["job"]
        inspection = validated_inspection(run, job["selected"]["inspection_handle"])
        check_candidate_set(content, job, inspection)
        return content, inspection
    except LigandEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise LigandEvidenceError("ligand candidate set evidence is invalid") from exc
