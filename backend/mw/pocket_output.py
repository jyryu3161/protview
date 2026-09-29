"""M12 strict reader of fpocket 4.2.3 output, result classification and native output evidence.

Standard library only, so the server and the job worker can both import it; it never runs
fpocket. Formats are pinned to the writers of the pinned 4.2.3 source tag:

- ``protein_info.txt``: ``write_out_fpocket_info_file`` (``src/fpout.c:150-213``), a
  ``Pocket %d :`` line, 19 fixed ``fprintf`` field lines, then a blank line, per pocket.
- ``pocketN_vert.pqr`` / ``protein_pockets.pqr``: ``write_pqr_vert`` → ``write_pqr_atom_line``
  (``src/voronoi.c:1536``, ``src/writepdb.c``), ``%8.3f`` x/y/z Å, ``%6.2f`` charge (always 0)
  and ``%6.2f`` alpha-sphere radius Å (the radius column is not a B-factor).
- ``pocketN_atm.pdb``: ``write_pdb_atom_line`` (``src/writepdb.c``), fixed PDB columns.
- The no-pocket diagnostics are written by ``src/refine.c`` with ``fprintf(stderr, ...)``. In
  ``search_pocket`` (``src/fpocket.c``) the refine sequence is ``reIndexPockets`` →
  ``dropSmallNpolarPockets`` → ``reIndexPockets`` → ``sort_pockets`` → ``reIndexPockets``. When every
  pocket is dropped, ``dropSmallNpolarPockets`` prints ``No Pockets Found while refining`` exactly once
  (the count only reaches 0 on the last node) and the two later ``reIndexPockets`` calls print
  ``No pocket to reindex.`` once each: exactly the three-line stderr observed on the pinned build.
  The other empty path (no pocket before refining: three reindex lines, no refining line) was never
  observed on the pinned build and is rejected until a reviewed parser version admits it.

Lining atoms map to the transport table (``mw.pocket_input`` rows) only by
(synthetic chain, synthetic residue number, atom name, element) and are then checked against
the projected coordinates at output precision. Serial numbers, nearest coordinates and display
strings are never used for mapping. Any deviation is a typed failure; nothing is truncated.
"""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import stat
from collections import Counter
from pathlib import Path
from typing import Any

PARSER_VERSION = "fpocket_4_2_3_output@1"
OUTPUT_DIR = "protein_out"
POCKETS_DIR = "pockets"
INFO_FILE = "protein_info.txt"
ALL_SPHERES_FILE = "protein_pockets.pqr"
# Every top-level file the pinned build writes with ``-w p`` (``src/fpout.c``, ``src/write_visu.c``).
TOP_LEVEL_FILES = frozenset({INFO_FILE, ALL_SPHERES_FILE, "protein_out.pdb", "protein.pml", "protein.tcl",
                             "protein_PYMOL.sh", "protein_VMD.sh"})
POCKET_FILE_RE = re.compile(r"pocket([1-9][0-9]{0,5})_(atm\.pdb|vert\.pqr)")

MAX_OUTPUT_BYTES = 30 * 1024 * 1024
MAX_OUTPUT_FILES = 1000
MAX_STREAM_BYTES = 1024 * 1024
MAX_POCKETS = 200
MAX_SPHERES = 50_000
# Alpha-sphere radius bounds are the fixed argv ``-m 3.4 -M 6.2``; the PQR prints the radius with
# ``%6.2f``, so a stored radius may differ from the full-precision cutoff by half the last digit.
MIN_SPHERE_RADIUS_A = 3.4
MAX_SPHERE_RADIUS_A = 6.2
RADIUS_TOLERANCE_A = 0.005
# Lining atom coordinates are written with ``%8.3f`` from the ``%8.3f`` transport file.
COORDINATE_TOLERANCE_A = 0.0005
ROUNDOFF_A = 1e-9

EMPTY_STDOUT = b"***** POCKET HUNTING BEGINS ***** \n***** POCKET HUNTING ENDS ***** \n"
EMPTY_DIAGNOSTICS = ("! No Pockets Found while refining", "! No pocket to reindex.", "! No pocket to reindex.")
EMPTY_STDERR = "".join(line + "\n" for line in EMPTY_DIAGNOSTICS).encode("ascii")
DETECTOR_SPECIFIC_NOTE = "fpocket 고유 점수이며 약물성 증거가 아님"
DISPLAY_CENTER_METHOD = "arithmetic_mean_of_stored_sphere_centers"

# (native name, exact line prefix up to the value, value kind, structured descriptor key, unit).
F3, INT, COUNT = "%.3f", "%d", "count"
INFO_FIELDS: tuple[tuple[str, str, str, str | None, str | None], ...] = (
    ("Score", "\tScore : \t", F3, "score", "dimensionless"),
    ("Druggability Score", "\tDruggability Score : \t", F3, "druggability_score", "dimensionless"),
    ("Number of Alpha Spheres", "\tNumber of Alpha Spheres : \t", COUNT, "alpha_sphere_count", "count"),
    ("Total SASA", "\tTotal SASA : \t", F3, "total_sasa_A2", "A2"),
    ("Polar SASA", "\tPolar SASA : \t", F3, None, None),
    ("Apolar SASA", "\tApolar SASA : \t", F3, None, None),
    ("Volume", "\tVolume : \t", F3, "volume_A3", "A3"),
    ("Mean local hydrophobic density", "\tMean local hydrophobic density : \t", F3, None, None),
    ("Mean alpha sphere radius", "\tMean alpha sphere radius :\t", F3, None, None),
    ("Mean alp. sph. solvent access", "\tMean alp. sph. solvent access : \t", F3, None, None),
    ("Apolar alpha sphere proportion", "\tApolar alpha sphere proportion : \t", F3, None, None),
    ("Hydrophobicity score", "\tHydrophobicity score:\t", F3, None, None),
    ("Volume score", "\tVolume score: \t ", F3, None, None),
    ("Polarity score", "\tPolarity score:\t ", INT, None, None),
    ("Charge score", "\tCharge score :\t ", INT, None, None),
    ("Proportion of polar atoms", "\tProportion of polar atoms: \t", F3, None, None),
    ("Alpha sphere density", "\tAlpha sphere density : \t", F3, None, None),
    ("Cent. of mass - Alpha Sphere max dist", "\tCent. of mass - Alpha Sphere max dist: \t", F3, None, None),
    ("Flexibility", "\tFlexibility : \t", F3, None, None),
)
KNOWN_FIELDS = frozenset(field[0] for field in INFO_FIELDS)
DESCRIPTOR_KEYS = tuple(field[3] for field in INFO_FIELDS if field[3])
UNITS = {**{field[3]: field[4] for field in INFO_FIELDS if field[3]},
         "sphere_coordinates": "angstrom", "sphere_radius": "angstrom", "display_center": "angstrom"}
VALUE_RE = {F3: re.compile(r"-?[0-9]+\.[0-9]{3}"), INT: re.compile(r"-?[0-9]+"), COUNT: re.compile(r"[0-9]+")}
# Opaque fields keep their original text; C printf spells non-finite doubles like this.
OPAQUE_NONFINITE = frozenset({"nan", "-nan", "inf", "-inf"})
FIELD_NAME_RE = re.compile(r"\t([^:\t]*?) ?:")
HEADER_RE = re.compile(r"Pocket ([1-9][0-9]*) :")

PQR_RE = re.compile(r"ATOM  (?:[ 0-9]{4}[0-9]|[0-9a-f]{5}) (?P<name>   [CON]) (?P<res>STP|ACC|DON)  "
                    r"(?P<resid>[ 0-9]{3}[0-9])    (?P<x>.{8})(?P<y>.{8})(?P<z>.{8})  (?P<charge>.{6})   "
                    r"(?P<radius>.{6})")
PQR_KINDS = frozenset({("C", "STP"), ("O", "STP"), ("O", "ACC"), ("N", "DON")})  # write_pqr_vert branches
ATM_RE = re.compile(r"ATOM  (?:[ 0-9]{4}[0-9]|[0-9a-f]{5}) (?P<name>[ A-Za-z0-9'*]{4}) (?P<res>[A-Z0-9]{3}) "
                    r"(?P<chain>[A-Za-z0-9])(?P<resseq>[ 0-9-]{3}[0-9])    (?P<x>.{8})(?P<y>.{8})(?P<z>.{8})"
                    r"(?P<occ>[ 0-9.-]{6})(?P<b>[ 0-9.-]{6}) {10}(?P<element>[ A-Z][A-Z])(?P<charge>[ 0-9-]{2})")
COORD_RE = re.compile(r"-?[0-9]+\.[0-9]{3}")
RADIUS_RE = re.compile(r"[0-9]+\.[0-9]{2}")
OCCUPANCY_RE = re.compile(r" *-?[0-9]+\.[0-9]{2}")

LIMITATIONS = [
    ("fpocket pocket candidates, ranks and scores are geometric detector output, "
     "not binding-site, affinity or druggability evidence."),
    ("Score and Druggability Score are fpocket regression scores min-max normalised across the pockets of the "
     "same execution; they are relative within one run and not comparable across runs or structures."),
    ("Volume is fpocket's Monte Carlo estimate with a clock-derived seed (seed control unsupported); fresh "
     "executions can differ, and it is not an analytical union-of-spheres volume."),
    ("Total SASA is fpocket's point-sampled surface of pocket-contacting atoms not covered by the pocket's alpha "
     "spheres; it is not whole-protein SASA or the result of the project's SASA tool."),
    "display_center is the arithmetic mean of stored sphere centers computed by ProtView, not an fpocket value.",
    "Coordinates refer to the projected protein-only transport input (standard-residue heavy atoms).",
]
RESIDUE_FIELDS = ("model_number", "chain_auth", "seq_auth", "icode", "chain_label", "seq_label", "resname")


class PocketOutputFailure(Exception):
    """Typed failure; ``failure_class`` is a ``FailureClass`` value (``fatal`` or ``resource_exceeded``)."""

    def __init__(self, failure_class: str, reason_code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code
        self.message = message
        self.detail = {"reason_code": reason_code, **detail}


def _fatal(code: str, message: str, **detail: Any) -> PocketOutputFailure:
    return PocketOutputFailure("fatal", code, message, **detail)


def _exceeded(code: str, message: str, **detail: Any) -> PocketOutputFailure:
    return PocketOutputFailure("resource_exceeded", code, message, **detail)


# ----------------------------------------------------------------- output tree
def _dir_fd(path: str | Path, dir_fd: int | None = None) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        raise _fatal("unexpected_output_type", "output directory could not be opened safely") from exc


def _scan(fd: int, prefix: str, state: dict[str, Any]) -> None:
    """Enumerate one directory by fd; caps are enforced per entry before anything is parsed."""
    with os.scandir(fd) as entries:
        for entry in entries:
            rel = prefix + entry.name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise _fatal("link_rejected", "symbolic link in fpocket output", path=rel)
            if stat.S_ISDIR(info.st_mode):
                if prefix or entry.name != POCKETS_DIR:
                    raise _fatal("unexpected_directory", "unexpected directory in fpocket output", path=rel)
                state["dirs"][rel] = info
                continue
            if not stat.S_ISREG(info.st_mode):
                raise _fatal("special_file", "special file in fpocket output", path=rel)
            state["count"] += 1
            if state["count"] > MAX_OUTPUT_FILES:
                raise _exceeded("output_file_limit", "fpocket output has more than 1000 files")
            state["bytes"] += info.st_size
            if state["bytes"] > MAX_OUTPUT_BYTES:
                raise _exceeded("output_bytes_limit", "fpocket output exceeds 30 MiB")
            if info.st_nlink != 1:
                raise _fatal("hardlink_rejected", "hard-linked file in fpocket output", path=rel)
            known = POCKET_FILE_RE.fullmatch(entry.name) if prefix else entry.name in TOP_LEVEL_FILES
            if not known:
                raise _fatal("unexpected_output_file", "unexpected file in fpocket output", path=rel)
            state["files"][rel] = info


def _read(dir_fd: int, name: str, expected: os.stat_result, rel: str) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError as exc:
        raise _fatal("link_rejected", "output file could not be opened without following links", path=rel) from exc
    try:
        info = os.fstat(fd)
        if ((info.st_dev, info.st_ino, info.st_size) != (expected.st_dev, expected.st_ino, expected.st_size) or
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise _fatal("output_changed", "output file changed while reading", path=rel)
        chunks, remaining = [], info.st_size + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != info.st_size:
            raise _fatal("output_changed", "output file changed while reading", path=rel)
        return data
    finally:
        os.close(fd)


def read_output(job_root: str | Path) -> dict[str, Any]:
    """Strictly enumerate and read ``<job_root>/protein_out``.

    Returns ``{"files": {relative path: {"size", "sha256", "data"}}}`` in sorted path order;
    ``data`` holds bytes only for the files the parser reads, other files are hashed only.
    """
    root = Path(job_root)
    outdir = root / OUTPUT_DIR
    try:
        top = os.lstat(outdir)
    except FileNotFoundError as exc:
        raise _fatal("missing_output_directory", "fpocket output directory is missing") from exc
    if stat.S_ISLNK(top.st_mode):
        raise _fatal("link_rejected", "fpocket output directory is a symbolic link")
    if not stat.S_ISDIR(top.st_mode):
        raise _fatal("special_file", "fpocket output path is not a directory")
    if os.path.realpath(outdir) != os.path.join(os.path.realpath(root), OUTPUT_DIR):
        raise _fatal("link_rejected", "fpocket output directory resolves outside the job root")
    state: dict[str, Any] = {"count": 0, "bytes": 0, "files": {}, "dirs": {}}
    out_fd = _dir_fd(outdir)
    fds = {"": out_fd}
    try:
        _scan(out_fd, "", state)
        if POCKETS_DIR in state["dirs"]:
            fds[POCKETS_DIR + "/"] = _dir_fd(POCKETS_DIR, dir_fd=out_fd)
            _scan(fds[POCKETS_DIR + "/"], POCKETS_DIR + "/", state)
        files: dict[str, dict[str, Any]] = {}
        for rel in sorted(state["files"]):
            prefix, _, name = rel.rpartition("/")
            data = _read(fds[prefix + "/" if prefix else ""], name, state["files"][rel], rel)
            parsed = rel in (INFO_FILE, ALL_SPHERES_FILE) or bool(prefix)
            files[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "data": data if parsed else None}
    finally:
        for fd in fds.values():
            os.close(fd)
    return {"files": files, "has_pockets_dir": POCKETS_DIR in state["dirs"]}


# ----------------------------------------------------------------- record parsers
def _text(data: bytes, rel: str) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _fatal("malformed_file", "fpocket output file is not ASCII", path=rel) from exc
    if not text.endswith("\n") or "\r" in text:
        raise _fatal("malformed_file", "fpocket output file does not end with a newline", path=rel)
    return text[:-1]


def _coordinate(field: str, rel: str, line: int) -> float:
    value = field.strip()
    if value.lower().lstrip("+-") in {"nan", "inf", "infinity"}:
        raise _fatal("nonfinite_coordinate", "non-finite coordinate in fpocket output", path=rel, line=line)
    if not COORD_RE.fullmatch(value):
        raise _fatal("malformed_record", "coordinate is not in the %8.3f format", path=rel, line=line)
    return float(value)


def _records(text: str, rel: str) -> list[tuple[int, str]]:
    """HEADER lines, ATOM lines, then exactly ``TER`` and ``END``; returns the ATOM lines."""
    lines = text.split("\n")
    if len(lines) < 2 or lines[-2:] != ["TER", "END"]:
        raise _fatal("malformed_record", "record file does not end with TER/END", path=rel)
    body = lines[:-2]
    index = 0
    while index < len(body) and body[index].startswith("HEADER"):
        index += 1
    atoms = [(number + 1, line) for number, line in enumerate(body) if number >= index]
    for number, line in atoms:
        if not line.startswith("ATOM  "):
            raise _fatal("malformed_record", "unexpected record in fpocket output", path=rel, line=number)
    return atoms


def _parse_pqr(data: bytes, rel: str) -> list[dict[str, Any]]:
    spheres = []
    for number, line in _records(_text(data, rel), rel):
        match = PQR_RE.fullmatch(line)
        if not match or (match["name"].strip(), match["res"]) not in PQR_KINDS or match["charge"] != "  0.00":
            if match:
                for axis in ("x", "y", "z"):
                    _coordinate(match[axis], rel, number)
            raise _fatal("malformed_record", "PQR record is not in the supported format", path=rel, line=number)
        xyz = [_coordinate(match[axis], rel, number) for axis in ("x", "y", "z")]
        radius_text = match["radius"].strip()
        if radius_text.lower().lstrip("+-") in {"nan", "inf"}:
            raise _fatal("nonfinite_coordinate", "non-finite sphere radius", path=rel, line=number)
        if not RADIUS_RE.fullmatch(radius_text):
            raise _fatal("malformed_record", "radius is not in the %6.2f format", path=rel, line=number)
        radius = float(radius_text)
        if not (MIN_SPHERE_RADIUS_A - RADIUS_TOLERANCE_A - ROUNDOFF_A <= radius <=
                MAX_SPHERE_RADIUS_A + RADIUS_TOLERANCE_A + ROUNDOFF_A):
            raise _fatal("sphere_radius_out_of_range", "alpha-sphere radius outside the -m/-M bounds",
                         path=rel, line=number)
        spheres.append({"resid": int(match["resid"]), "x_A": xyz[0], "y_A": xyz[1], "z_A": xyz[2],
                        "radius_A": radius, "key": (match["x"], match["y"], match["z"], match["radius"])})
    return spheres


def _parse_atm(data: bytes, rel: str) -> list[dict[str, Any]]:
    records = []
    for number, line in _records(_text(data, rel), rel):
        match = ATM_RE.fullmatch(line)
        if not match:
            if len(line) == 80 and line.startswith("ATOM  "):
                for start in (30, 38, 46):
                    _coordinate(line[start:start + 8], rel, number)
            raise _fatal("malformed_record", "lining atom record is not in the supported format",
                         path=rel, line=number)
        name = match["name"].strip()
        if not name or " " in name or not OCCUPANCY_RE.fullmatch(match["occ"]) or \
                not OCCUPANCY_RE.fullmatch(match["b"]):
            raise _fatal("malformed_record", "lining atom record is not in the supported format",
                         path=rel, line=number)
        try:
            resseq = int(match["resseq"])
        except ValueError as exc:
            raise _fatal("malformed_record", "lining atom residue number is malformed", path=rel, line=number) from exc
        records.append({"key": (match["chain"], resseq, name, match["element"].strip()),
                        "resname": match["res"],
                        "xyz": [_coordinate(match[axis], rel, number) for axis in ("x", "y", "z")],
                        "line": number})
    return records


def _field_name(line: str) -> str | None:
    match = FIELD_NAME_RE.match(line)
    return match[1] if match else None


def _parse_info(data: bytes) -> list[dict[str, Any]]:
    """Parse every ``Pocket N :`` block; field names, order and separators are fixed."""
    lines = _text(data, INFO_FILE).split("\n")
    blocks: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        header = HEADER_RE.fullmatch(lines[index])
        if not header:
            raise _fatal("malformed_field", "expected a 'Pocket N :' line", path=INFO_FILE, line=index + 1)
        index += 1
        seen: set[str] = set()
        fields: list[tuple[str, str, str, str | None, str | None]] = []
        for name, prefix, kind, key, unit in INFO_FIELDS:
            line = lines[index] if index < len(lines) else ""
            if line.startswith(prefix):
                fields.append((name, line[len(prefix):], kind, key, unit))
                seen.add(name)
                index += 1
                continue
            found = _field_name(line)
            if not line or found is None:
                raise _fatal("missing_field", f"missing field {name!r}", path=INFO_FILE, line=index + 1)
            if found not in KNOWN_FIELDS:
                raise _fatal("unknown_field", "unknown field in protein_info.txt", path=INFO_FILE, line=index + 1)
            if found in seen:
                raise _fatal("duplicate_field", "duplicate field in protein_info.txt", path=INFO_FILE, line=index + 1)
            raise _fatal("malformed_field", "field is out of order or has an unsupported separator",
                         path=INFO_FILE, line=index + 1)
        if index >= len(lines) or lines[index] != "":
            line = lines[index] if index < len(lines) else ""
            found = _field_name(line)
            if found is not None and found in KNOWN_FIELDS:
                raise _fatal("duplicate_field", "duplicate field in protein_info.txt", path=INFO_FILE, line=index + 1)
            if found is not None:
                raise _fatal("unknown_field", "unknown field in protein_info.txt", path=INFO_FILE, line=index + 1)
            raise _fatal("malformed_field", "pocket block does not end with a blank line",
                         path=INFO_FILE, line=index + 1)
        index += 1
        blocks.append({"rank": int(header[1]), "fields": fields})
        if len(blocks) > MAX_POCKETS:
            raise _exceeded("pocket_count_limit", "fpocket reported more than 200 pockets")
    return blocks


def _descriptors(block: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    descriptors: dict[str, Any] = {}
    native: dict[str, str] = {}
    for name, text, kind, key, unit in block["fields"]:
        if key is None:
            if not (VALUE_RE[kind].fullmatch(text) or (kind == F3 and text in OPAQUE_NONFINITE)):
                raise _fatal("malformed_field", f"field {name!r} is not in its native format",
                             path=INFO_FILE, rank=block["rank"])
            native[name] = text
            continue
        if text.lower() in OPAQUE_NONFINITE:
            raise _fatal("nonfinite_descriptor", f"descriptor {name!r} is not finite",
                         path=INFO_FILE, rank=block["rank"])
        if not VALUE_RE[kind].fullmatch(text):
            raise _fatal("malformed_field", f"descriptor {name!r} is not in its native format",
                         path=INFO_FILE, rank=block["rank"])
        value: int | float = int(text) if kind == COUNT else float(text)
        entry: dict[str, Any] = {"native_name": name, "native_text": text, "value": value, "unit": unit}
        if key == "druggability_score":
            entry["detector_specific_note"] = DETECTOR_SPECIFIC_NOTE
        descriptors[key] = entry
    return descriptors, native


def display_center(spheres: list[dict[str, Any]]) -> dict[str, Any]:
    """Arithmetic mean of stored sphere centers (a ProtView display value, not an fpocket value)."""
    if not spheres:
        raise ValueError("display center needs at least one sphere")
    center = {axis: math.fsum(sphere[axis] for sphere in spheres) / len(spheres) for axis in ("x_A", "y_A", "z_A")}
    return {**center, "method": DISPLAY_CENTER_METHOD}


def _transport_index(atoms: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    table: dict[tuple, dict[str, Any]] = {}
    for atom in atoms:
        key = (atom["synthetic_chain"], atom["synthetic_resseq"], atom["atom_name"], atom["element"])
        if key in table:
            raise _fatal("transport_key_not_unique", "transport atom key is not unique")
        table[key] = atom
    return table


def _lining(records: list[dict[str, Any]], table: dict[tuple, dict[str, Any]], rel: str) -> dict[str, Any]:
    """Map native records to transport atoms; dedup per transport atom, keep the native record count."""
    order: list[int] = []
    refs: list[dict[str, Any]] = []
    residues: list[dict[str, Any]] = []
    residue_keys: set[tuple] = set()
    for record in records:
        atom = table.get(record["key"])
        if atom is None:
            raise _fatal("unmapped_lining_atom", "lining atom does not map to a projected transport atom",
                         path=rel, line=record["line"])
        if record["resname"] != atom["transport_resname"]:
            raise _fatal("lining_atom_mismatch", "lining atom residue name differs from the transport atom",
                         path=rel, line=record["line"])
        if any(abs(a - b) > COORDINATE_TOLERANCE_A + ROUNDOFF_A
               for a, b in zip(record["xyz"], atom["projected_coordinate_A"], strict=True)):
            raise _fatal("lining_atom_coordinate_mismatch", "lining atom coordinates differ from the transport atom",
                         path=rel, line=record["line"])
        if atom["transport_index"] in order:
            continue
        order.append(atom["transport_index"])
        refs.append(atom["ref"])
        residue = atom["ref"]["residue"]
        key = tuple(residue.get(field) for field in RESIDUE_FIELDS)
        if key not in residue_keys:
            residue_keys.add(key)
            residues.append(residue)
    return {"atoms": {"transport_indices": order, "atoms": refs, "native_record_count": len(records),
                      "dedup_policy": "unique per transport atom in first native record order; "
                                      "native_record_count keeps every native record"},
            "residues": residues}


# ----------------------------------------------------------------- classification
def _check_streams(stdout: bytes, stderr: bytes) -> None:
    if type(stdout) is not bytes or type(stderr) is not bytes:
        raise TypeError("stdout and stderr must be bytes")
    if len(stdout) > MAX_STREAM_BYTES:
        raise _exceeded("stdout_limit", "fpocket stdout exceeds 1 MiB")
    if len(stderr) > MAX_STREAM_BYTES:
        raise _exceeded("stderr_limit", "fpocket stderr exceeds 1 MiB")


def _require_known(native: dict[str, Any]) -> None:
    missing = sorted(TOP_LEVEL_FILES - set(native["files"]))
    if missing:
        raise _fatal("missing_output_file", "fpocket output file is missing", paths=missing)
    if not native["has_pockets_dir"]:
        raise _fatal("missing_output_file", "fpocket pockets directory is missing", paths=[POCKETS_DIR])


def _pocket_files(native: dict[str, Any]) -> set[str]:
    return {rel for rel in native["files"] if rel.startswith(POCKETS_DIR + "/")}


def _base(native: dict[str, Any], classification: str) -> dict[str, Any]:
    return {"parser_version": PARSER_VERSION, "classification": classification,
            "null_result": classification == "scientific_null", "completeness": "complete",
            "units": dict(UNITS), "limitations": list(LIMITATIONS),
            "raw_file_hashes": {rel: entry["sha256"] for rel, entry in native["files"].items()
                                if entry["data"] is not None}}


def _empty(native: dict[str, Any], stdout: bytes, stderr: bytes) -> dict[str, Any]:
    """The single supported empty convention of the pinned build (see module docstring)."""
    if _pocket_files(native):
        raise _fatal("unsupported_empty_format", "empty pocket summary with per-pocket files")
    if _records(_text(native["files"][ALL_SPHERES_FILE]["data"], ALL_SPHERES_FILE), ALL_SPHERES_FILE):
        raise _fatal("unsupported_empty_format", "empty pocket summary with sphere records")
    if stdout != EMPTY_STDOUT:
        raise _fatal("unsupported_empty_format", "empty result without the supported stdout banner")
    if stderr != EMPTY_STDERR:
        raise _fatal("unsupported_empty_format", "empty result without exactly the supported diagnostics")
    result = _base(native, "scientific_null")
    result.update(total_count=0, total_sphere_count=0, pockets=[], empty_diagnostics=list(EMPTY_DIAGNOSTICS))
    return result


def _pockets(native: dict[str, Any], atoms: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = _parse_info(native["files"][INFO_FILE]["data"])
    parsed = [(block, *_descriptors(block)) for block in blocks]
    if sum(descriptors["alpha_sphere_count"]["value"] for _, descriptors, _ in parsed) > MAX_SPHERES:
        raise _exceeded("sphere_count_limit", "fpocket reported more than 50000 alpha spheres")
    ranks = [block["rank"] for block in blocks]
    if len(set(ranks)) != len(ranks):
        raise _fatal("duplicate_rank", "duplicate pocket rank in protein_info.txt")
    if ranks != list(range(1, len(ranks) + 1)):
        raise _fatal("rank_sequence", "pocket ranks are not 1..N in order")
    expected = {f"{POCKETS_DIR}/pocket{rank}_{suffix}" for rank in ranks for suffix in ("vert.pqr", "atm.pdb")}
    present = _pocket_files(native)
    if expected - present:
        raise _fatal("missing_pocket_file", "per-pocket file is missing", paths=sorted(expected - present))
    if present - expected:
        raise _fatal("unexpected_pocket_file", "per-pocket file without a pocket block",
                     paths=sorted(present - expected))
    table = _transport_index(atoms)
    all_spheres = _parse_pqr(native["files"][ALL_SPHERES_FILE]["data"], ALL_SPHERES_FILE)
    by_rank: dict[int, Counter] = {}
    for sphere in all_spheres:
        by_rank.setdefault(sphere["resid"], Counter())[sphere["key"]] += 1
    if set(by_rank) - set(ranks):
        raise _fatal("pocket_sphere_mismatch", "protein_pockets.pqr lists spheres of an unknown pocket")
    pockets = []
    for block, descriptors, native_fields in parsed:
        rank = block["rank"]
        vert_rel = f"{POCKETS_DIR}/pocket{rank}_vert.pqr"
        atm_rel = f"{POCKETS_DIR}/pocket{rank}_atm.pdb"
        spheres = _parse_pqr(native["files"][vert_rel]["data"], vert_rel)
        records = _parse_atm(native["files"][atm_rel]["data"], atm_rel)
        reported = descriptors["alpha_sphere_count"]["value"]
        if reported == 0 or not spheres or not records:
            raise _fatal("empty_pocket", "pocket without alpha spheres or lining atoms", rank=rank)
        if reported != len(spheres):
            raise _fatal("sphere_count_mismatch", "reported alpha-sphere count differs from PQR records",
                         rank=rank, reported=reported, records=len(spheres))
        if any(sphere["resid"] != rank for sphere in spheres):
            raise _fatal("pocket_sphere_mismatch", "sphere residue number differs from the pocket rank", rank=rank)
        if Counter(sphere["key"] for sphere in spheres) != by_rank.get(rank, Counter()):
            raise _fatal("pocket_sphere_mismatch", "pocket spheres differ from protein_pockets.pqr", rank=rank)
        stored = [{axis: sphere[axis] for axis in ("x_A", "y_A", "z_A", "radius_A")} for sphere in spheres]
        lining = _lining(records, table, atm_rel)
        pockets.append({"rank": rank, "descriptors": descriptors, "native_fields": native_fields,
                        "spheres": stored, "lining_atoms": lining["atoms"], "lining_residues": lining["residues"],
                        "display_center": display_center(stored)})
    result = _base(native, "success")
    result.update(total_count=len(pockets), total_sphere_count=len(all_spheres), pockets=pockets)
    return result


def classify(job_root: str | Path, atoms: list[dict[str, Any]], *, exit_code: int | None, stdout: bytes,
             stderr: bytes, killed: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify one finished fpocket execution.

    ``atoms`` are the transport rows of ``mw.pocket_input.project``. Returns ``(result, native)``
    where ``result["classification"]`` is ``success`` or ``scientific_null`` and ``native`` is the
    read output tree for :func:`native_output_evidence`. Every other outcome raises
    :class:`PocketOutputFailure` (``fatal`` with a reason code, or ``resource_exceeded``).
    """
    _check_streams(stdout, stderr)
    if killed or exit_code is None or exit_code < 0:
        raise _fatal("engine_killed", "fpocket was terminated by a signal", exit_code=exit_code)
    if exit_code != 0:
        raise _fatal("nonzero_exit", "fpocket exited with a nonzero status", exit_code=exit_code)
    native = read_output(job_root)
    _require_known(native)
    if native["files"][INFO_FILE]["size"] == 0:
        return _empty(native, stdout, stderr), native
    return _pockets(native, atoms), native


def classify_evidence(evidence: dict[str, Any], atoms: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-parse stored ``pocket_native_output@1`` bytes with the same pinned rules as :func:`classify`.

    Used on validated reads so a stored ``pocket_set`` is checked against its retained native bytes,
    not only against its own structure. Raises :class:`PocketOutputFailure` on any deviation.
    """
    files: dict[str, dict[str, Any]] = {}
    for item in evidence["files"]:
        data = base64.b64decode(item["content_b64"], validate=True) if item["retained"] else None
        if item["path"] in files or (data is not None and (len(data) != item["size"] or
                                                          hashlib.sha256(data).hexdigest() != item["sha256"])):
            raise _fatal("native_evidence_invalid", "stored native evidence is inconsistent", path=item["path"])
        files[item["path"]] = {"size": item["size"], "sha256": item["sha256"], "data": data}
    missing = sorted(TOP_LEVEL_FILES - set(files))
    if missing:
        raise _fatal("missing_output_file", "fpocket output file is missing", paths=missing)
    parsed = {INFO_FILE, ALL_SPHERES_FILE} | {rel for rel in files if rel.startswith(POCKETS_DIR + "/")}
    if {rel for rel, entry in files.items() if entry["data"] is not None} != parsed:
        raise _fatal("native_evidence_invalid", "stored native evidence retains the wrong files")
    streams = [base64.b64decode(evidence[name]["content_b64"], validate=True) for name in ("stdout", "stderr")]
    _check_streams(*streams)
    native = {"files": files, "has_pockets_dir": True}
    if files[INFO_FILE]["size"] == 0:
        return _empty(native, *streams)
    return _pockets(native, atoms)


def native_output_evidence(native: dict[str, Any], stdout: bytes, stderr: bytes) -> dict[str, Any]:
    """``pocket_native_output@1`` content: bytes only for parsed files and streams, hashes for the rest.

    ``retained_bytes`` is the decoded byte total the caller charges against the per-run cap.
    """
    _check_streams(stdout, stderr)
    files = []
    retained = len(stdout) + len(stderr)
    for rel, entry in native["files"].items():
        item: dict[str, Any] = {"path": rel, "size": entry["size"], "sha256": entry["sha256"],
                                "retained": entry["data"] is not None}
        if entry["data"] is not None:
            item["content_b64"] = base64.b64encode(entry["data"]).decode("ascii")
            retained += entry["size"]
        files.append(item)

    def stream(raw: bytes) -> dict[str, Any]:
        return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "content_b64": base64.b64encode(raw).decode("ascii")}

    return {"parser_version": PARSER_VERSION, "encoding": "base64", "files": files,
            "stdout": stream(stdout), "stderr": stream(stderr), "retained_bytes": retained,
            "total_output_bytes": sum(entry["size"] for entry in native["files"].values())}
