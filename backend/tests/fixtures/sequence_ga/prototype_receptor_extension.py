# PROTOTYPE (M23 T1 measurement only; never product code, never imported by mw).
"""The spec 8 (b) server-side branch, as a measurement-process monkeypatch (``docking_bundle`` itself is unchanged).

``extended_mutation_receptor`` sends a ``receptor_source.mutation_model`` handle whose stored schema is
``mutation_set_model@1`` to a prototype reader (the stored mmCIF of the one ``structures`` key named by ``side``, the
sidecar from its ``final_bonds`` + ``atom_mapping`` with the same ``docking_inputs`` functions) and every other handle
to the ORIGINAL ``docking_bundle._mutation_receptor`` unchanged. It checks no publication evidence (T5 adds that);
it only shows that the M18 call key, staging, worker and publication paths accept the new model kind without any
change to ``docking_worker.py``, ``docking_constants.py`` or ``docking_inputs.py``.
"""
from __future__ import annotations

import hashlib
from typing import Any

from mw import docking_bundle, docking_inputs

SET_MODEL = ("mutation_set_model", "mutation_set_model@1", "json")
SET_STRUCTURE = ("mutation_set_model_structure", "mutation_set_model_structure@1", "cif")
MAX_BYTES = 16 * 1024 * 1024
ORIGINAL = docking_bundle._mutation_receptor


def _set_model_receptor(run: Any, source: dict[str, Any]) -> dict[str, Any]:
    content = run.store.load_bounded_json(source["mutation_model"], MAX_BYTES)
    if set(content["structures"]) != {source["side"]}:
        raise ValueError("side is not the model's one structure")
    entry = content["structures"][source["side"]]
    meta = run.store.meta(entry["structure_object"])
    if (meta["kind"], meta["schema"], meta["fmt"]) != SET_STRUCTURE:
        raise ValueError("structure object kind")
    raw = run.store.load_bounded_bytes(entry["structure_object"], MAX_BYTES)
    if hashlib.sha256(raw).hexdigest() != entry["structure_sha256"]:
        raise ValueError("structure bytes")
    handle, model_number = entry["structure_object"], content["structure"]["model_number"]
    rows = docking_inputs.receptor_rows(raw, "cif", handle, model_number)
    sidecar_raw = docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"], handle)
    return {"handle": handle, "raw": raw, "sha256": entry["structure_sha256"], "model_number": model_number,
            "sidecar_raw": sidecar_raw}


def extended_mutation_receptor(run: Any, source: dict[str, Any]) -> dict[str, Any]:
    try:
        meta = run.store.meta(source["mutation_model"])
    except (KeyError, ValueError, TypeError):
        meta = None
    if meta is None or (meta["kind"], meta["schema"], meta["fmt"]) != SET_MODEL:
        return ORIGINAL(run, source)                       # the M21 path, byte for byte as before
    try:
        return _set_model_receptor(run, source)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise docking_bundle._invalid("receptor_source.mutation_model is not a valid mutation_set_model@1",
                                      "mutation_model_invalid") from exc


def install(setattr_: Any) -> None:
    """``setattr_`` is ``pytest.MonkeyPatch().setattr`` or ``setattr``."""
    setattr_(docking_bundle, "_mutation_receptor", extended_mutation_receptor)
