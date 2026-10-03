"""M18 qvina docking job lane on the server side: capability, admission, call key, staging, publication, reads.

The server never imports RDKit, Meeko or MDAnalysis and never executes qvina2. The capability checks that both locked
environments exist, hashes the qvina2 file against the install record and the pinned value, and runs
``docking_worker.py --handshake`` in the pinned ``.deps/docking/venv-locked`` interpreter (only the handshake record is
cached; the verdict is recomputed on every call). Admission (``submission``) runs ``docking_inputs.validate_arguments``
and then the checks that need the store: same-run handles of the right import kind, the M17 candidate set and its
candidate, the parent SDF hash, and the M11-rule receptor checks on the import bytes (gemmi only). Any refusal is
``input_invalid`` with a closed reason code before any job exists (no budget).

The worker reads only staged JSON with base64 bytes. Publication re-validates the worker output against the job's
staged selection and the closed sets, cross-checks every contact's receptor atom and distance against the receptor
import, and stores one ``docking_result@1`` object whose content never includes time, job or attempt identities (same
input -> same handle). Every read re-validates the stored object against its single completed publication and its
inputs; the object recovers from ``events.jsonl`` alone (``object_created`` payloads), without any engine. An M19
batch row's publication (``docking_batch_row_published`` after the attempt's verified cleanup, with or without a
later batch summary publication) is accepted as the same evidence, checked against that row's own selection.
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

from . import docking_constants as C
from . import docking_inputs
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json

ROOT = Path(__file__).resolve().parents[2]
# Deployment-fixed paths; a request can never name an interpreter, module, executable, path, env or argv.
WORKER = ROOT / "backend/mw/jobs/docking_worker.py"
WORKER_PYTHON = ROOT / ".deps/docking/venv-locked/bin/python"
WORKER_RECORD = ROOT / ".deps/docking/install-record.json"
WORKER_LOCK = ROOT / "config/docking/docking-wheel-hashes-macos-arm64-py311.json"
QVINA = ROOT / ".deps/qvina/env/bin/qvina2"
QVINA_RECORD = ROOT / ".deps/qvina/install-record.json"
QVINA_LOCK = ROOT / "config/docking/qvina-conda-lock-hashes-osx-arm64.json"
CONSTANTS = ROOT / "backend/mw/docking_constants.py"
QVINA_SHA256 = "caf5f22a3928be8adf3cb017508eaacbdcecf68ef29c5bca24fceea016c5f79c"   # = docking_worker.QVINA_SHA256
PINNED_VERSIONS = {"meeko": "0.8.0", "rdkit": "2026.03.6", "MDAnalysis": "2.10.0", "gemmi": "0.7.5"}
PROTOCOL = C.PROTOCOL
TOOL = C.TOOL
IMPLEMENTATION = "qvina_dock_v1@1"
OUTPUT_KIND = "docking_result"
MAX_INPUT_BYTES = 10 * 1024 * 1024        # M11 chemical import bound (chemical_inputs.MAX_RAW)
# Staged structure.json: receptor + optional sidecar + one SDF as base64 (each import <= 10 MiB, so at most
# 3 x 10 MiB x 4/3 = 40 MiB) plus one candidate row. Equal to the worker's own read bound (MAX_STAGED_BYTES).
STAGED_LIMIT = 48 * 1024 * 1024
# Worker result.json bound (worker refuses to write more; the guardian reads at most this much). The stored object
# has the same 4 MiB bound (spec 5.2); a larger object fails the attempt with resource_exceeded (never truncated).
OUTPUT_LIMIT = C.MAX_RESULT_BYTES
MAX_RESULT_BYTES = C.MAX_RESULT_BYTES
MAX_ERROR_BYTES = 64 * 1024               # worker error.json bound (docking_worker.MAX_ERROR_BYTES)
DISTANCE_TOLERANCE_A = 1e-3               # contact distance re-measured from the stored pose SDF text
REASONS = {
    "worker_missing": "도킹 작업 환경(.deps/docking/venv-locked)·설치 기록·잠금 파일이나 작업 모듈이 없습니다.",
    "engine_missing": "qvina 2.1 엔진 환경(.deps/qvina)의 실행 파일·설치 기록·잠금 파일이 없습니다.",
    "engine_hash_mismatch": "qvina2 실행 파일의 SHA-256이 설치 기록·고정 값과 다릅니다.",
    "handshake_failed": "도킹 작업 프로세스 확인(handshake)에 실패했습니다.",
    "version_mismatch": "작업 환경의 Meeko·RDKit·MDAnalysis·gemmi 버전이 고정 버전과 다릅니다.",
}
WORKER_ERROR_CLASSES = ("input_invalid", "resource_exceeded", "fatal")
OUTPUT_KEYS = frozenset({"schema", "protocol", "job_id", "attempt_id", "method", "inputs", "box", "parameters",
                         "engine", "preparation", "modes", "counts", "limitations"})
RESULT_KEYS = frozenset({"schema", "protocol", "method", "input_sha256", "inputs", "box", "parameters", "engine",
                         "preparation", "modes", "counts", "limitations"})
MODE_KEYS = frozenset({"mode", "score_kcal_mol", "engine_rmsd_lb_A", "engine_rmsd_ub_A", "conformer_index",
                       "core_max_deviation_A", "atoms_outside_box", "min_heavy_atom_distance_A", "pose_sdf",
                       "contacts"})
CONTACT_KEYS = frozenset({"ligand_serial", "ligand_element", "ligand_parent_serial", "receptor_atom", "distance_A",
                          "kind"})
RECEPTOR_ATOM_KEYS = frozenset({"residue", "atom_name", "altloc", "element", "site_index"})
PIN_KEYS = frozenset({"engine", "qvina_sha256", "qvina_package", "versions", "worker_sha256", "constants_sha256",
                      "lock_sha256", "qvina_lock_sha256"})
SHA_RE = re.compile(r"[0-9a-f]{64}")
POLAR = {"N", "O"}

_HANDSHAKE_CACHE: dict[tuple, dict[str, Any]] = {}
_HANDSHAKE_LOCK = threading.Lock()


class DockingJobFailure(Exception):
    """A typed attempt failure after reservation (charged); nothing is published."""

    def __init__(self, failure_class: str, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code
        self.message = message

    def to_error(self) -> dict[str, Any]:
        return {"error": self.failure_class, "message": self.message, "reason_code": self.reason_code}


class DockingEvidenceError(ValueError):
    """A stored or produced docking object does not validate against its inputs and publication."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _invalid(message: str, reason_code: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code, **detail})


# ----------------------------------------------------------------- capability (no RDKit/Meeko here, qvina never run)
def _handshake_key() -> tuple:
    interpreter = WORKER_PYTHON.resolve(strict=True)
    info = interpreter.stat()
    engine = QVINA.stat()
    return (str(WORKER_PYTHON), str(interpreter), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            str(QVINA), engine.st_ino, engine.st_size, engine.st_mtime_ns, _sha(QVINA_RECORD.read_bytes()),
            _sha(WORKER_LOCK.read_bytes()), _sha(WORKER.read_bytes()), _sha(CONSTANTS.read_bytes()))


def _handshake() -> dict[str, Any]:
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER), "--handshake"], cwd=ROOT,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=True)
    if len(proc.stdout) > 8192 or len(proc.stderr) > 8192:
        raise ValueError("oversized handshake output")
    data = json.loads(proc.stdout)
    if type(data) is not dict:
        raise ValueError("invalid docking worker handshake")
    return data


def _check_handshake(data: Any) -> None:
    engine = data.get("engine") if type(data) is dict else None
    if (type(data) is not dict or data.get("schema") != "docking_worker_handshake@1" or
            data.get("worker_sha256") != _sha(WORKER.read_bytes()) or data.get("protocols") != [PROTOCOL] or
            str(data.get("python", "")).split(".")[:2] != ["3", "11"] or
            type(data.get("versions")) is not dict or type(data.get("versions_expected")) is not dict or
            type(engine) is not dict or engine.get("name") != C.ENGINE or type(engine.get("package")) is not str):
        raise ValueError("invalid docking worker handshake")


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def capability() -> dict[str, Any]:
    """``available`` only with both locked environments, the qvina2 hash pinned and recorded, and a handshake whose
    Meeko/RDKit/MDAnalysis/gemmi versions are the pinned ones. Otherwise a reason and no pins (spec 5.5)."""
    base = {"schema": "docking_capability@1", "protocol_id": PROTOCOL, "tool_id": TOOL, "engine": C.ENGINE,
            "execution_lane": "durable_job", "methods": dict(C.METHODS),
            "timeout_s": {"default": C.TIMEOUT_DEFAULT_S, "max": C.TIMEOUT_MAX_S},
            "limits": {"input_bytes_per_file": MAX_INPUT_BYTES, "receptor_atoms": C.MAX_RECEPTOR_ATOMS,
                       "ligand_heavy_atoms": C.MAX_LIGAND_HEAVY_ATOMS, "active_torsions": C.MAX_ACTIVE_TORSIONS,
                       "box_side_A": [C.BOX_SIDE_MIN_A, C.BOX_SIDE_MAX_A], "result_bytes": MAX_RESULT_BYTES,
                       "contacts_per_mode": C.MAX_CONTACTS_PER_MODE},
            "score_label": C.SCORE_LABEL, "limitations": list(C.LIMITATIONS)}

    def unavailable(status: str) -> dict[str, Any]:
        return {**base, "available": False, "status": status, "reason_code": status, "reason": REASONS[status],
                "pins": None, "versions": None}

    if not all(path.is_file() for path in (WORKER_PYTHON, WORKER, WORKER_RECORD, WORKER_LOCK, CONSTANTS)):
        return unavailable("worker_missing")
    if not all(path.is_file() for path in (QVINA, QVINA_RECORD, QVINA_LOCK)):
        return unavailable("engine_missing")
    try:
        actual = _file_sha(QVINA)
        record = json.loads(QVINA_RECORD.read_bytes())
        recorded = record["executable"]["sha256"]
    except OSError:
        return unavailable("engine_missing")
    except (ValueError, KeyError, TypeError):
        return unavailable("engine_hash_mismatch")
    if not (actual == recorded == QVINA_SHA256):
        return unavailable("engine_hash_mismatch")
    with _HANDSHAKE_LOCK:
        try:
            key = _handshake_key()
        except OSError:
            return unavailable("worker_missing")
        data = copy.deepcopy(_HANDSHAKE_CACHE.get(key))
        if data is None:
            try:
                data = _handshake()
                _check_handshake(data)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, KeyError,
                    AttributeError):
                return unavailable("handshake_failed")
            _HANDSHAKE_CACHE.clear()  # only a structurally valid handshake is reused, while its key is unchanged
            _HANDSHAKE_CACHE[key] = copy.deepcopy(data)
    try:
        _check_handshake(data)
    except (ValueError, TypeError, OSError):
        return unavailable("handshake_failed")
    engine = data["engine"]
    if engine.get("hash_match") is not True or engine.get("binary_sha256") != actual:
        return unavailable("engine_hash_mismatch")
    if data["versions"] != PINNED_VERSIONS or data["versions_expected"] != PINNED_VERSIONS:
        return unavailable("version_mismatch")
    pins = {"engine": C.ENGINE, "qvina_sha256": actual, "qvina_package": engine["package"],
            "versions": dict(PINNED_VERSIONS), "worker_sha256": data["worker_sha256"],
            "constants_sha256": _sha(CONSTANTS.read_bytes()), "lock_sha256": _sha(WORKER_LOCK.read_bytes()),
            "qvina_lock_sha256": _sha(QVINA_LOCK.read_bytes())}
    return {**base, "available": True, "status": "ready", "reason_code": None, "reason": None, "pins": pins,
            "versions": dict(data["versions"])}


def require_ready() -> dict[str, Any]:
    """The pins a job records at submission (raises a precondition failure when unavailable)."""
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"], detail={"reason_code": value["reason_code"]})
    return value["pins"]


# ----------------------------------------------------------------- admission (no job, no tool, no RDKit)
def _import_meta(run: Any, handle: str, kind: str) -> dict[str, Any]:
    """A same-run ``chemical_raw_input@1`` of exactly ``kind``; anything else is ``invalid_job_arguments``."""
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise _invalid(f"{kind} handle is not a same-run import", "invalid_job_arguments") from exc
    summary = meta["summary"]
    if ((meta["kind"], meta["schema"]) != ("chemical_raw_input", "chemical_raw_input@1") or
            summary.get("input_kind") != kind or type(summary.get("sha256")) is not str or
            not SHA_RE.fullmatch(summary["sha256"]) or meta["fmt"] in ("json", "parquet") or
            not 0 < meta["size"] <= MAX_INPUT_BYTES):
        raise _invalid(f"handle is not a {kind} import", "invalid_job_arguments")
    return meta


def _import_bytes(run: Any, handle: str, kind: str, sha256: str) -> bytes:
    meta = _import_meta(run, handle, kind)
    raw = run.store.load_bounded_bytes(handle, MAX_INPUT_BYTES)
    if _sha(raw) != sha256 or meta["summary"]["sha256"] != sha256:
        raise ValueError("import bytes changed since submission")
    return raw


def _entry(meta: dict[str, Any]) -> dict[str, str]:
    return {"handle": meta["handle"], "sha256": meta["summary"]["sha256"]}


def _receptor_format(meta: dict[str, Any]) -> str:
    fmt = meta["summary"].get("input_format", meta["fmt"])
    fmt = "cif" if fmt == "mmcif" else fmt
    if fmt not in ("pdb", "cif"):
        raise _invalid("receptor import format must be pdb or cif", "invalid_job_arguments")
    return fmt


def submission(run: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """(selected, normalized arguments, input handles); every refusal is input_invalid with a closed reason code."""
    from .ligand_bundle import LigandEvidenceError, validated_candidate_set

    normalized = docking_inputs.validate_arguments(args)
    receptor = _import_meta(run, normalized["receptor_handle"], "receptor")
    connectivity = normalized["connectivity"]
    sidecar = (None if connectivity["kind"] == "pdb_conect" else
               _import_meta(run, connectivity["sidecar_handle"], "receptor_bonds"))
    ligand = normalized["ligand"]
    if ligand["source"] == "sdf":
        sdf = _import_meta(run, ligand["sdf_handle"], "ligand_sdf")
        selected_ligand = {"source": "sdf", "sdf": _entry(sdf)}
        input_handles = [receptor["handle"], *([sidecar["handle"]] if sidecar else []), sdf["handle"]]
    else:
        parent = _import_meta(run, ligand["parent_sdf_handle"], "ligand_sdf")
        try:
            candidate_set, _inspection = validated_candidate_set(run, ligand["candidate_set_handle"])
        except LigandEvidenceError as exc:
            raise _invalid("candidate_set_handle is not a completed same-run ligand candidate set",
                           "invalid_job_arguments") from exc
        row = next((item for item in candidate_set["candidates"] if item["id"] == ligand["candidate_id"]), None)
        if row is None:
            raise _invalid("candidate_id is not in the candidate set", "candidate_unknown")
        if parent["summary"]["sha256"] != candidate_set["parent_sha256"]:
            raise _invalid("parent SDF SHA-256 differs from the candidate set's parent_sha256", "parent_mismatch")
        selected_ligand = {"source": "candidate", "candidate_set_handle": ligand["candidate_set_handle"],
                           "candidate_set_parent_sha256": candidate_set["parent_sha256"],
                           "parent_sdf": _entry(parent),
                           "candidate": {key: copy.deepcopy(row[key]) for key in
                                         ("id", "smiles", "retained_parent_atoms", "stereo_flag")}}
        input_handles = [receptor["handle"], *([sidecar["handle"]] if sidecar else []),
                         ligand["candidate_set_handle"], parent["handle"]]
    fmt = _receptor_format(receptor)
    raw = run.store.load_bounded_bytes(receptor["handle"], MAX_INPUT_BYTES)
    sidecar_raw = None if sidecar is None else run.store.load_bounded_bytes(sidecar["handle"], MAX_INPUT_BYTES)
    checked = docking_inputs.check_receptor(raw, fmt, receptor["handle"], normalized["receptor_model_number"],
                                            connectivity, normalized["receptor_instance"], sidecar_raw)
    removed = set(checked["instance_sites"])
    if not any(row["element"].upper() == "H" for row in checked["rows"] if row["ref"]["site_index"] not in removed):
        raise _invalid("receptor has no explicit hydrogen atoms", "receptor_hydrogens_missing")
    selected = {"schema": "docking_selection@1", "arguments": normalized,
                "input_sha256": docking_inputs.input_sha256(normalized),
                "receptor": {**_entry(receptor), "format": fmt, "atom_count": len(checked["rows"]),
                             "instance_sites": checked["instance_sites"],
                             "removed_instance": checked["removed_instance"]},
                "sidecar": None if sidecar is None else _entry(sidecar), "ligand": selected_ligand}
    return selected, normalized, input_handles


def call_key(normalized: dict[str, Any], pins: dict[str, Any]) -> str:
    """Spec 5.1: the normalized arguments without the acknowledgement, and the pinned environment."""
    return idempotency_key(PROTOCOL, IMPLEMENTATION,
                           {"input": docking_inputs.call_key_input(normalized), "method": pins})


# ----------------------------------------------------------------- staging
def _b64(raw: bytes) -> dict[str, str]:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def stage(run: Any, job: dict[str, Any], attempt_id: str) -> bytes:
    """The worker payload, re-read from the immutable import objects (never stored in the job record)."""
    selected = job["selected"]
    args = selected["arguments"]
    receptor = selected["receptor"]
    sidecar = selected["sidecar"]
    payload_receptor = {
        "handle": receptor["handle"], "format": receptor["format"],
        "bytes": _b64(_import_bytes(run, receptor["handle"], "receptor", receptor["sha256"])),
        "model_number": args["receptor_model_number"],
        "connectivity": {"kind": args["connectivity"]["kind"],
                         "sidecar": None if sidecar is None else
                         _b64(_import_bytes(run, sidecar["handle"], "receptor_bonds", sidecar["sha256"]))},
        "instance": args["receptor_instance"]}
    ligand = selected["ligand"]
    if ligand["source"] == "sdf":
        payload_ligand = {"source": "sdf", "sdf": _b64(_import_bytes(run, ligand["sdf"]["handle"], "ligand_sdf",
                                                                      ligand["sdf"]["sha256"]))}
    else:
        payload_ligand = {"source": "candidate",
                          "parent_sdf": _b64(_import_bytes(run, ligand["parent_sdf"]["handle"], "ligand_sdf",
                                                           ligand["parent_sdf"]["sha256"])),
                          "candidate_set_parent_sha256": ligand["candidate_set_parent_sha256"],
                          "candidate": ligand["candidate"]}
    return canonical_json({"schema": "docking_worker_input@1", "receptor": payload_receptor,
                           "ligand": payload_ligand, "mode": args["mode"], "box": args["box"],
                           "parameters": args["parameters"]})


def worker_error(attempt_dir: Path) -> dict[str, Any]:
    """Accept only the worker's typed envelope with a closed reason; anything else is fatal."""
    fatal = {"error": "fatal", "message": "worker exit or invalid docking error envelope"}
    try:
        descriptor = os.open(attempt_dir / "error.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_ERROR_BYTES:
                return fatal
            raw = stream.read(MAX_ERROR_BYTES + 1)
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (type(data) is not dict or canonical_json(data) != raw or
                set(data) != {"schema", "error_class", "reason_code", "message", "detail"} or
                data["schema"] != "docking_worker_error@1" or data["error_class"] not in WORKER_ERROR_CLASSES or
                data["reason_code"] not in C.REASONS or type(data["detail"]) is not dict or
                type(data["message"]) is not str or not 0 < len(data["message"]) <= 240):
            return fatal
        return {"error": data["error_class"], "reason_code": data["reason_code"], "message": data["message"],
                "detail": data["detail"]}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return fatal


# ----------------------------------------------------------------- validation
def _require(condition: Any, message: str) -> None:
    if not condition:
        raise DockingEvidenceError(message)


def _int(value: Any, low: int = 0, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _float(value: Any) -> bool:
    return type(value) is float and math.isfinite(value)


def _residue_ok(value: Any) -> bool:
    try:
        docking_inputs._residue(value)
    except ToolFailure:
        return False
    return True


def _pins(value: Any) -> None:
    _require(type(value) is dict and set(value) == PIN_KEYS and value["engine"] == C.ENGINE and
             value["versions"] == PINNED_VERSIONS and value["qvina_sha256"] == QVINA_SHA256 and
             type(value["qvina_package"]) is str and
             all(type(value[key]) is str and SHA_RE.fullmatch(value[key])
                 for key in ("worker_sha256", "constants_sha256", "lock_sha256", "qvina_lock_sha256")),
             "method pins")


def _sdf_atoms(text: str) -> list[tuple[str, tuple[float, float, float]]]:
    """(element, coordinates) per V2000 atom line, read from the fixed text columns."""
    lines = text.splitlines()
    _require(len(lines) >= 4 and lines[3].rstrip().endswith("V2000"), "pose SDF is V2000")
    count = int(lines[3][0:3])
    _require(0 < count and len(lines) >= 4 + count, "pose SDF atom block")
    atoms = []
    for line in lines[4:4 + count]:
        xyz = (float(line[0:10]), float(line[10:20]), float(line[20:30]))
        _require(all(math.isfinite(x) for x in xyz), "pose SDF coordinates")
        atoms.append((line[31:34].strip(), xyz))
    return atoms


def _kind(ligand_element: str, receptor_element: str) -> str:
    a, b = ligand_element.upper(), receptor_element.upper()
    return "polar_contact" if a in POLAR and b in POLAR else "hydrophobic_contact" if a == b == "C" else "contact"


def _check_mode(row: Any, number: int, mode: str, retained: set[int] | None,
                selected: dict[str, Any], samples_generated: int | None) -> list[tuple]:
    _require(type(row) is dict and set(row) == MODE_KEYS and row["mode"] == number, "mode row keys and number")
    _require(_float(row["score_kcal_mol"]), "score is a finite engine value")
    if mode == "free":
        _require(_float(row["engine_rmsd_lb_A"]) and _float(row["engine_rmsd_ub_A"]) and
                 row["engine_rmsd_lb_A"] >= 0 and row["engine_rmsd_ub_A"] >= 0 and
                 row["conformer_index"] is None and row["core_max_deviation_A"] is None, "free mode fields")
    else:
        _require(row["engine_rmsd_lb_A"] is None and row["engine_rmsd_ub_A"] is None and
                 _int(row["conformer_index"], 0, (samples_generated or 0) - 1) and
                 _float(row["core_max_deviation_A"]) and row["core_max_deviation_A"] >= 0, "core-fixed mode fields")
    _require(_int(row["atoms_outside_box"]) and _float(row["min_heavy_atom_distance_A"]) and
             row["min_heavy_atom_distance_A"] >= 0, "geometry fields")
    text = row["pose_sdf"]
    _require(type(text) is str and 0 < len(text) and "$$$$" not in text and
             text.splitlines()[0] == f"mode_{number}", "pose SDF record and title")
    atoms = _sdf_atoms(text)
    heavy = sum(element != "H" for element, _ in atoms)
    _require(row["atoms_outside_box"] <= heavy, "atoms outside the box are pose heavy atoms")
    contacts = row["contacts"]
    _require(type(contacts) is list and len(contacts) <= C.MAX_CONTACTS_PER_MODE, "contact rows")
    keys, measured = [], []
    for contact in contacts:
        _require(type(contact) is dict and set(contact) == CONTACT_KEYS, "contact keys")
        serial, atom = contact["ligand_serial"], contact["receptor_atom"]
        _require(_int(serial, 1, len(atoms)) and atoms[serial - 1][0] != "H" and
                 contact["ligand_element"] == atoms[serial - 1][0], "contact ligand atom")
        parent_serial = contact["ligand_parent_serial"]
        if mode == "core_fixed":
            _require(parent_serial is None or (_int(parent_serial, 1) and parent_serial in retained),
                     "core parent serial")
        else:
            _require(parent_serial is None, "parent serial only for core-fixed")
        _require(type(atom) is dict and set(atom) == RECEPTOR_ATOM_KEYS and _residue_ok(atom["residue"]) and
                 all(type(atom[key]) is str for key in ("atom_name", "altloc", "element")) and
                 atom["element"].upper() != "H" and
                 _int(atom["site_index"], 0, selected["receptor"]["atom_count"] - 1) and
                 atom["site_index"] not in selected["receptor"]["instance_sites"], "contact receptor atom")
        _require(_float(contact["distance_A"]) and 0 <= contact["distance_A"] <= C.CONTACT_CUTOFF_A and
                 contact["distance_A"] >= row["min_heavy_atom_distance_A"] - DISTANCE_TOLERANCE_A, "contact distance")
        _require(contact["kind"] in C.CONTACT_KINDS and
                 contact["kind"] == _kind(contact["ligand_element"], atom["element"]), "contact kind")
        keys.append((serial, atom["site_index"]))
        measured.append((serial, atom, contact["distance_A"], atoms[serial - 1][1]))
    _require(keys == sorted(set(keys)), "contacts are unique and sorted by ligand_serial, site_index")
    return measured


def check_result(run: Any, content: Any, job: dict[str, Any]) -> list[tuple]:
    """Validate a ``docking_result@1`` against its producing job (selection + pins) and its import metadata.

    Returns (ligand_serial, receptor_atom, distance, pose xyz) per contact for the publication-time receptor check.
    """
    selected = job["selected"]
    _require(selected.get("schema") == "docking_selection@1", "selection schema")
    _pins(job.get("method"))
    args = selected["arguments"]
    mode, source = args["mode"], args["ligand"]["source"]
    _require(type(content) is dict and set(content) == RESULT_KEYS and content["schema"] == C.RESULT_SCHEMA and
             content["protocol"] == PROTOCOL and content["method"] == C.METHODS[mode], "result keys")
    _require(content["input_sha256"] == selected["input_sha256"] == docking_inputs.input_sha256(args),
             "input_sha256 of the normalized arguments")
    try:
        _import_meta(run, selected["receptor"]["handle"], "receptor")
        if selected["sidecar"] is not None:
            _import_meta(run, selected["sidecar"]["handle"], "receptor_bonds")
        for entry in ([selected["ligand"]["sdf"]] if source == "sdf" else [selected["ligand"]["parent_sdf"]]):
            _require(_import_meta(run, entry["handle"], "ligand_sdf")["summary"]["sha256"] == entry["sha256"],
                     "ligand import hash")
    except ToolFailure as exc:
        raise DockingEvidenceError("import evidence") from exc
    _require(run.store.meta(selected["receptor"]["handle"])["summary"]["sha256"] == selected["receptor"]["sha256"],
             "receptor import hash")
    removed = selected["receptor"]["removed_instance"]
    _require(content["inputs"] == {"receptor": {
        "handle": args["receptor_handle"], "sha256": selected["receptor"]["sha256"],
        "model_number": args["receptor_model_number"], "connectivity": args["connectivity"],
        "removed_instance": removed, "acknowledgement": args["acknowledgement"]},
        "ligand": content["inputs"]["ligand"], "mode": mode} and
        args["acknowledgement"] == {key: True for key in C.ACKNOWLEDGEMENT_KEYS}, "receptor inputs")
    ligand = content["inputs"]["ligand"]
    candidate = source == "candidate"
    sel_ligand = selected["ligand"]
    unspecified = ligand.get("unspecified_stereo_centers") if type(ligand) is dict else None
    _require(type(ligand) is dict and ligand == {
        "source": source,
        "sdf_handle": None if candidate else sel_ligand["sdf"]["handle"],
        "sdf_sha256": None if candidate else sel_ligand["sdf"]["sha256"],
        "candidate_set_handle": sel_ligand["candidate_set_handle"] if candidate else None,
        "candidate_id": sel_ligand["candidate"]["id"] if candidate else None,
        "parent_sdf_handle": sel_ligand["parent_sdf"]["handle"] if candidate else None,
        "parent_sdf_sha256": sel_ligand["parent_sdf"]["sha256"] if candidate else None,
        "generated": {"hydrogens": candidate, "coordinates": candidate},
        "stereo_flag": sel_ligand["candidate"]["stereo_flag"] if candidate else None,
        "unspecified_stereo_centers": unspecified} and
        ((unspecified is None) if not candidate else _int(unspecified)), "ligand inputs")
    box = content["box"]
    request = args["box"]
    _require(type(box) is dict and set(box) == {"center_A", "size_A", "source", "margin_A"} and
             box["source"] == request["source"] and
             all(type(box[key]) is list and len(box[key]) == 3 and all(_float(x) for x in box[key])
                 for key in ("center_A", "size_A")) and
             all(0 < x <= C.BOX_SIDE_MAX_A for x in box["size_A"]), "box")
    if request["source"] == "manual":
        _require(box["center_A"] == request["center_A"] and box["size_A"] == request["size_A"] and
                 box["margin_A"] is None, "manual box is the request")
    else:
        _require(box["margin_A"] == request["margin_A"], "range box margin")
    _require(content["parameters"] == {**args["parameters"], "cpu": C.CPU}, "parameters")
    method = job["method"]
    engine, preparation = content["engine"], content["preparation"]
    _require(type(engine) is dict and set(engine) == {"name", "version", "binary_sha256", "package"} and
             engine["name"] == C.ENGINE and engine["binary_sha256"] == method["qvina_sha256"] and
             engine["package"] == method["qvina_package"] and type(engine["version"]) is str and
             engine["package"].startswith(f"qvina-{engine['version']}-"), "engine")
    _require(preparation == {"tool": "Meeko", "version": PINNED_VERSIONS["meeko"],
                             "rdkit_version": PINNED_VERSIONS["rdkit"], "atom_typing": "ad4",
                             "charges": "gasteiger"}, "preparation")
    counts, modes = content["counts"], content["modes"]
    params = args["parameters"]
    _require(type(counts) is dict and set(counts) == {"modes", "contacts_by_mode", "null_result", "samples_generated",
                                                      "samples_scored"} and type(modes) is list and
             len(modes) <= params["num_modes"] and counts["modes"] == len(modes) and
             counts["null_result"] is (len(modes) == 0), "counts")
    if mode == "free":
        _require(counts["samples_generated"] is None and counts["samples_scored"] is None, "free sample counts")
        retained = None
    else:
        _require(_int(counts["samples_generated"], 1, params["conformers"]) and
                 _int(counts["samples_scored"], 0, counts["samples_generated"]) and
                 len(modes) == min(params["num_modes"], counts["samples_scored"]), "core-fixed sample counts")
        retained = set(sel_ligand["candidate"]["retained_parent_atoms"])
    contacts = []
    for number, row in enumerate(modes, start=1):
        contacts.extend(_check_mode(row, number, mode, retained, selected, counts["samples_generated"]))
    _require(counts["contacts_by_mode"] == [len(row["contacts"]) for row in modes], "contacts by mode")
    if mode == "core_fixed":
        order = [(row["score_kcal_mol"], row["conformer_index"]) for row in modes]
        _require(order == sorted(order) and len({row["conformer_index"] for row in modes}) == len(modes),
                 "core-fixed samples listed by score then sample index")
    _require(content["limitations"] == list(C.applicable_limitations(
        mode=mode, source=source, removed_instance=removed is not None, unspecified_stereo_centers=unspecified)),
        "limitations")
    _require(len(canonical_json(content)) <= MAX_RESULT_BYTES, "result size")
    return contacts


def _check_receptor_atoms(run: Any, job: dict[str, Any], contacts: list[tuple]) -> None:
    """Publication only: every contact names the receptor import's own atom at its site index (M11 traversal),
    and its distance re-measures from the stored pose coordinates and that atom's coordinates."""
    selected = job["selected"]
    receptor = selected["receptor"]
    raw = _import_bytes(run, receptor["handle"], "receptor", receptor["sha256"])
    try:
        rows = docking_inputs.receptor_rows(raw, receptor["format"], receptor["handle"],
                                            selected["arguments"]["receptor_model_number"])
    except ToolFailure as exc:
        raise DockingEvidenceError("receptor import no longer reads") from exc
    _require(len(rows) == receptor["atom_count"], "receptor atom count")
    for _serial, atom, distance, xyz in contacts:
        row = rows[atom["site_index"]]
        ref = {key: value for key, value in row["ref"].items() if key != "structure_handle"}
        _require(atom == ref, "contact receptor atom identity")
        _require(abs(math.dist(xyz, row["coordinate_A"]) - distance) <= DISTANCE_TOLERANCE_A,
                 "contact distance re-measured")


# ----------------------------------------------------------------- publication
def _read_result(attempt_dir: Path, descriptor: Any) -> dict[str, Any]:
    if (type(descriptor) is not dict or set(descriptor) != {"output_sha256", "output_bytes"} or
            type(descriptor["output_bytes"]) is not int or not 0 < descriptor["output_bytes"] <= OUTPUT_LIMIT or
            type(descriptor["output_sha256"]) is not str or not SHA_RE.fullmatch(descriptor["output_sha256"])):
        raise ValueError("invalid docking output descriptor")
    fd = os.open(attempt_dir / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["output_bytes"]:
            raise ValueError("docking output size mismatch")
        raw = stream.read(descriptor["output_bytes"] + 1)
    if len(raw) != descriptor["output_bytes"] or _sha(raw) != descriptor["output_sha256"]:
        raise ValueError("docking output hash mismatch")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if type(data) is not dict or canonical_json(data) != raw:
        raise ValueError("docking output is not canonical JSON")
    return data


def result_content(job: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """The ``docking_result@1`` content from one worker output: the server's handles, ``input_sha256`` and
    acknowledgement are added; the worker's control identities and byte-hash echoes are checked and dropped."""
    selected = job["selected"]
    args = selected["arguments"]
    _require(type(data) is dict and set(data) == OUTPUT_KEYS and data["schema"] == "docking_worker_output@1" and
             data["protocol"] == PROTOCOL, "worker output keys")
    inputs = data["inputs"]
    _require(type(inputs) is dict and set(inputs) == {"receptor", "ligand", "mode"} and inputs["mode"] == args["mode"],
             "worker inputs")
    receptor = inputs["receptor"]
    sidecar = selected["sidecar"]
    _require(type(receptor) is dict and receptor == {
        "sha256": selected["receptor"]["sha256"], "format": selected["receptor"]["format"],
        "model_number": args["receptor_model_number"], "atom_count": selected["receptor"]["atom_count"],
        "connectivity": {"kind": args["connectivity"]["kind"],
                         "sidecar_sha256": None if sidecar is None else sidecar["sha256"]},
        "removed_instance": selected["receptor"]["removed_instance"]}, "worker receptor echo")
    ligand = inputs["ligand"]
    sel_ligand = selected["ligand"]
    candidate = sel_ligand["source"] == "candidate"
    _require(type(ligand) is dict and set(ligand) == {"source", "sdf_sha256", "parent_sdf_sha256", "candidate_id",
                                                      "generated", "stereo_flag", "unspecified_stereo_centers"} and
             ligand["source"] == sel_ligand["source"] and
             ligand["sdf_sha256"] == (None if candidate else sel_ligand["sdf"]["sha256"]) and
             ligand["parent_sdf_sha256"] == (sel_ligand["parent_sdf"]["sha256"] if candidate else None) and
             ligand["candidate_id"] == (sel_ligand["candidate"]["id"] if candidate else None), "worker ligand echo")
    return {"schema": C.RESULT_SCHEMA, "protocol": PROTOCOL, "method": data["method"],
            "input_sha256": selected["input_sha256"],
            "inputs": {"receptor": {"handle": args["receptor_handle"], "sha256": receptor["sha256"],
                                    "model_number": args["receptor_model_number"],
                                    "connectivity": args["connectivity"],
                                    "removed_instance": receptor["removed_instance"],
                                    "acknowledgement": args["acknowledgement"]},
                       "ligand": {"source": ligand["source"],
                                  "sdf_handle": None if candidate else sel_ligand["sdf"]["handle"],
                                  "sdf_sha256": ligand["sdf_sha256"],
                                  "candidate_set_handle": sel_ligand["candidate_set_handle"] if candidate else None,
                                  "candidate_id": ligand["candidate_id"],
                                  "parent_sdf_handle": sel_ligand["parent_sdf"]["handle"] if candidate else None,
                                  "parent_sdf_sha256": ligand["parent_sdf_sha256"],
                                  "generated": ligand["generated"], "stereo_flag": ligand["stereo_flag"],
                                  "unspecified_stereo_centers": ligand["unspecified_stereo_centers"]},
                       "mode": inputs["mode"]},
            **{key: data[key] for key in ("box", "parameters", "engine", "preparation", "modes", "counts",
                                          "limitations")}}


def publish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path, descriptor: Any) -> list[str]:
    """Validate the worker output of this attempt and store exactly one object (or raise, storing nothing)."""
    data = _read_result(attempt_dir, descriptor)
    if type(data) is not dict or data.get("job_id") != job["job_id"] or data.get("attempt_id") != attempt_id:
        raise ValueError("docking output identity mismatch")
    return [store_result(run, job, attempt_id, result_content(job, data))]


def store_result(run: Any, job: dict[str, Any], attempt_id: str, content: dict[str, Any]) -> str:
    """Check one ``docking_result@1`` content against ``job`` (an M18 job, or an M19 batch row's view) and the
    receptor import, then store it; the handle (or raise, storing nothing)."""
    if len(canonical_json(content)) > MAX_RESULT_BYTES:
        raise DockingJobFailure("resource_exceeded", "resource_exceeded",
                                f"docking result exceeds {MAX_RESULT_BYTES} bytes; never truncated")
    contacts = check_result(run, content, job)
    _check_receptor_atoms(run, job, contacts)
    counts = content["counts"]
    out = run.store.put(OUTPUT_KIND, C.RESULT_SCHEMA, content, produced_by=attempt_id,
                        null_result=counts["null_result"],
                        summary={"method": content["method"], "mode": content["inputs"]["mode"],
                                 "ligand_source": content["inputs"]["ligand"]["source"],
                                 "receptor_handle": content["inputs"]["receptor"]["handle"],
                                 "input_sha256": content["input_sha256"], "modes": counts["modes"],
                                 "null_result": counts["null_result"]})
    return out.handle


# ----------------------------------------------------------------- validated reads (never run anything)
def producer(run: Any, handle: str) -> dict[str, Any]:
    """The earliest completed publication of ``handle``: a ``qvina_dock_v1`` job or an M19 batch row (else an
    evidence error)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    m18 = None
    for terminal in events:
        if (terminal["type"] != "job_terminal" or terminal.get("status") != "done" or
                terminal.get("output_handles") != [handle]):
            continue
        job = jobs.get(terminal.get("job_id"))
        attempt = terminal.get("attempt_id")
        if job is None or job.get("protocol_id") != PROTOCOL or job.get("tool_id") != TOOL:
            continue
        candidates = [event for event in events if event["type"] == "job_result_candidate" and
                      event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                      event.get("output_handles") == [handle] and event["seq"] < terminal["seq"]]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("attempt_id") == attempt and event.get("group_empty") is True]
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == TOOL]
        if (len(candidates) == 1 and len(cleaned) == 1 and len(reserved) == 1 and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < candidates[0]["seq"] and
                created[0]["seq"] < candidates[0]["seq"]):
            m18 = {"job_id": job["job_id"], "attempt_id": attempt, "job": job,
                   "created_seq": created[0]["seq"], "published_seq": terminal["seq"]}
            break
    # The earliest completed publication is the producer, so later ones (an M18 job and an M19 batch row can
    # publish the same handle) never change what an existing read or report was checked against.
    found = [item for item in (m18, _batch_row_producer(events, jobs, created, handle)) if item is not None]
    if found:
        return min(found, key=lambda item: item["published_seq"])
    raise DockingEvidenceError("object has no completed qvina_dock_v1 publication")


def _batch_row_producer(events: list[dict[str, Any]], jobs: dict[str, Any], created: list[dict[str, Any]],
                        handle: str) -> dict[str, Any] | None:
    """M19: a row of a ``qvina_batch_dock_v1`` attempt published this M18 result (reservation < verified cleanup <
    row publication). ``job`` is the row's view: the batch job with that row's own ``docking_selection@1`` and the
    batch's M18 pins, so the M18 checks apply unchanged. The batch summary publication is not required: a summary
    that could not be built (the job then fails with its reason) never hides a verified row (spec 7.2). The
    completion point is the summary publication when there is one, else the row publication."""
    from . import docking_batch_constants as BC

    for row in events:
        if row["type"] != "docking_batch_row_published" or row.get("handle") != handle:
            continue
        job = jobs.get(row.get("job_id"))
        attempt = row.get("attempt_id")
        if job is None or job.get("protocol_id") != BC.PROTOCOL or job.get("tool_id") != BC.TOOL:
            continue
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == BC.TOOL]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event.get("group_empty") is True]
        summary = [event for event in events if event["type"] == "docking_batch_published" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event["seq"] > row["seq"]]
        rows = job.get("selected", {}).get("rows", [])
        index = row.get("row_index")
        if (len(reserved) == 1 and cleaned and created and type(index) is int and
                0 <= index < len(rows) and reserved[0]["seq"] < cleaned[0]["seq"] < row["seq"] and
                created[0]["seq"] < row["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": {**job, "selected": rows[index]["selected"]},
                    "created_seq": created[0]["seq"], "published_seq": (summary[0] if summary else row)["seq"],
                    "row_index": index}
    return None


def validated_result(run: Any, handle: Any) -> dict[str, Any]:
    try:
        if type(handle) is not str:
            raise DockingEvidenceError("handle must be a string")
        try:
            meta = run.store.meta(handle)
        except (KeyError, ValueError) as exc:
            raise DockingEvidenceError("unknown same-run handle") from exc
        if (meta["kind"], meta["schema"], meta["fmt"]) != (OUTPUT_KIND, C.RESULT_SCHEMA, "json"):
            raise DockingEvidenceError("expected docking_result")
        content = run.store.load_bounded_json(handle, MAX_RESULT_BYTES)
        check_result(run, content, producer(run, handle)["job"])
        return content
    except DockingEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise DockingEvidenceError("docking result evidence is invalid") from exc
