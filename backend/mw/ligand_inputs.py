"""M17 building-block imports: light, chemistry-free server checks (spec 3.1, 3.3).

Kinds ``building_blocks_sdf`` (format ``sdf_multi``, ``.sdf``) and ``building_blocks_smiles`` (format
``smiles_list``, ``.smi``/``.txt``) are stored as ``chemical_raw_input@1`` exactly like the M11 kinds
(content-addressed, same run, an identical byte string under another kind is refused). The M11
``_sdf_records`` parser is deliberately not used: marker atoms ``*``/``R#`` would fail its element check
and its record cap differs. Chemical validation of each record happens in the isolated worker.

Record ordinals (used by the worker for ``block_<n>`` names) are defined here:
- SDF: records are the texts between lines equal to ``$$$$`` (trailing whitespace ignored); a segment
  with only whitespace is not a record (as in M11), a last record without ``$$$$`` is.
- SMILES: every line that is not blank and does not start with ``#`` (after stripping) is one record.
No RDKit here.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .core.errors import FailureClass, ToolFailure
from .core.handles import object_sha
from .ligand_constants import (
    BLOCK_EXTENSIONS,
    BLOCK_IMPORT_KINDS,
    BLOCK_INPUT_FORMATS,
    MAX_BLOCK_SDF_RECORDS,
    MAX_INPUT_BYTES,
)

STORE_FMT = {"building_blocks_sdf": "sdf", "building_blocks_smiles": "smi"}


def _invalid(message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message)


def split_sdf_records(text: str) -> list[str]:
    segments, current = [], []
    for line in text.splitlines():
        if line.rstrip() == "$$$$":
            segments.append(current)
            current = []
        else:
            current.append(line)
    segments.append(current)
    return ["\n".join(lines) for lines in segments if any(line.strip() for line in lines)]


def smiles_record_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def check_block_bytes(kind: str, filename: str, raw: bytes) -> str:
    """Return the ``input_format`` for valid block bytes, else raise a typed input error."""
    if kind not in BLOCK_IMPORT_KINDS:
        raise _invalid("unsupported building-block import kind")
    if (type(filename) is not str or not filename or len(filename.encode("utf-8")) > 200 or
            "/" in filename or "\\" in filename or "." not in filename):
        raise _invalid("invalid building-block filename")
    if filename.rsplit(".", 1)[-1].lower() not in BLOCK_EXTENSIONS[kind]:
        raise _invalid("building-block filename extension does not match input kind")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise _invalid("building-block file is empty or larger than 10 MiB")
    if b"\x00" in raw:
        raise _invalid("building-block file contains NUL bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise _invalid("building-block file is not UTF-8") from exc
    if kind == "building_blocks_sdf":
        count = len(split_sdf_records(text))
        if not 1 <= count <= MAX_BLOCK_SDF_RECORDS:
            raise _invalid(f"building-block SDF must contain 1--{MAX_BLOCK_SDF_RECORDS:,} records")
    elif not smiles_record_lines(text):
        raise _invalid("building-block SMILES list has no record lines")
    return BLOCK_INPUT_FORMATS[kind]


def import_raw(store: Any, kind: str, filename: str, raw: bytes) -> dict[str, Any]:
    input_format = check_block_bytes(kind, filename, raw)
    sha = hashlib.sha256(raw).hexdigest()
    handle = f"obj://{store.run_id}/chemical_raw_input/" + object_sha(
        "chemical_raw_input", "chemical_raw_input@1", raw)
    try:
        existing = store.meta(handle)
    except KeyError:
        existing = None
    if existing is not None:
        # Same rule as M11 import_raw: identical bytes keep one immutable object of one kind/format.
        if (existing["kind"] != "chemical_raw_input" or existing["schema"] != "chemical_raw_input@1" or
                existing["summary"].get("input_kind") != kind or
                existing["summary"].get("input_format") != input_format or
                existing["summary"].get("sha256") != sha or
                store.load_bounded_bytes(handle, MAX_INPUT_BYTES) != raw):
            raise _invalid("identical chemical bytes have incompatible imported kind or format")
        return {"schema": "chemical_raw_input@1", "handle": handle, "kind": kind,
                "format": input_format, "sha256": sha, "size": len(raw)}
    result = store.put("chemical_raw_input", "chemical_raw_input@1", raw, fmt=STORE_FMT[kind],
                       summary={"input_kind": kind, "input_format": input_format, "sha256": sha})
    return {"schema": "chemical_raw_input@1", "handle": result.handle, "kind": kind,
            "format": input_format, "sha256": sha, "size": len(raw)}
