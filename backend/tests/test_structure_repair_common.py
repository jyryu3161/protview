"""Shared helpers of the M29 T4 structure-repair core tests (this module holds no tests).

Prepared structures are made by the product path (``load_structure`` -> ``prepare_structure``, one run per input under
the session's temporary folder) and cached by input bytes, format and water policy. Expected values in the tests come
from the input files and the installed template read independently here (``template_heavy_names``), never from the
product's own output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

import gemmi

from mw import structure_repair as sr
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures"
SR_FIX = FIX / "structure_repair"
PUBLIC = ("8vf6", "1m17", "1mq4", "1a30", "1a4i", "1hsg", "1s9i", "1fin", "1ubq", "1rnh", "4ins", "1ay7", "1cll")
WATERS = ("strip_all", "keep_all")
MEASURED = ("8vf6", "1rnh", "1cll", "1hsg", "1mq4")   # PDBFixer-measured addition fixtures (strip_all, seed 1)
_ROOT: list[Path] = []
_INPUTS: dict[tuple, tuple[sr.RepairInputs, Any]] = {}


def use_root(path: Path) -> None:
    if not _ROOT:
        _ROOT.append(path)


def prepared(raw: bytes, fmt: str, waters: str = "strip_all") -> tuple[sr.RepairInputs, Any]:
    key = (hashlib.sha256(raw).hexdigest(), fmt, waters)
    if key not in _INPUTS:
        run = new_run(_ROOT[0], dry_run=False, run_id=f"run_m29_t4_{len(_INPUTS):03d}")
        source = run.call("load_structure", {"source": f"input.{fmt}", "model_index": 0}, source_bytes=raw,
                          source_format=fmt)
        handle = run.call("prepare_structure", {
            "structure": source.handle, "altloc": "highest_occupancy", "waters": waters, "hydrogens": "strip",
            "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}).handle
        _INPUTS[key] = (sr.load_inputs(run.store, handle), run)
    return _INPUTS[key]


def public(name: str, waters: str = "strip_all") -> sr.RepairInputs:
    return prepared((FIX / f"public_{name}.cif").read_bytes(), "cif", waters)[0]


def synthetic(file: str, waters: str = "strip_all") -> sr.RepairInputs:
    return prepared((SR_FIX / file).read_bytes(), file.rsplit(".", 1)[1], waters)[0]


def additions(name: str) -> list[dict[str, Any]]:
    return json.loads((SR_FIX / f"{name}-additions.pdbfixer-measured.json").read_text())["added_atoms"]


def structure(raw: bytes, fmt: str = "cif") -> gemmi.Structure:
    text = raw.decode()
    if fmt in ("cif", "mmcif"):
        return gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    return gemmi.read_pdb_string(text)


def write(st: gemmi.Structure) -> bytes:
    return st.make_mmcif_document().as_string().encode()


def key(chain: Any, res: Any) -> tuple:
    return (chain.name, res.seqid.num, res.seqid.icode.strip(), res.subchain or None, res.label_seq, res.name)


def ref_key(ref: dict[str, Any]) -> tuple:
    return (ref["chain_auth"], ref["seq_auth"], ref["icode"], ref["chain_label"], ref["seq_label"], ref["resname"])


@lru_cache(maxsize=1)
def _template_xml() -> dict[str, list[str]]:
    spec = importlib.util.find_spec("openmm")
    path = Path(next(iter(spec.submodule_search_locations))) / "app" / "data" / "amber14" / "protein.ff14SB.xml"
    root = ET.parse(path).getroot()
    elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
    return {node.attrib["name"]: [a.attrib["name"] for a in node.findall("Atom")
                                  if elements[a.attrib["type"]] not in ("H", "D")]
            for node in root.findall("./Residues/Residue")}


def template_heavy_names(resname: str, terminal: bool = False) -> list[str]:
    """Independent read of the installed template (HIS as HID, MSE as MET, C-terminal ``C`` form)."""
    name = {"HIS": "HID", "MSE": "MET"}.get(resname, resname)
    return _template_xml()[("C" if terminal else "") + name]
