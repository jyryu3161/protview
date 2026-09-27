"""Fixed protein-only Amber14/GBn2 protocol and identity-preserving preflight."""
from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import canonical_json
from ..jobs.process_identity import IdentityUnavailable, supported
from ..openmm_bundle import FORCEFIELD_SHA256
from .registry import ToolContext
from .sasa import AMINO
from .structural import _parse, _res_ref

PROTOCOL = "openmm_protein_minimize"
SCHEMA = "openmm_protein_minimization@1"
ATOM_CAP = 6000


def dependencies() -> dict[str, Any]:
    try:
        import openmm
        from openmm.app import forcefield
        if version("openmm") != "8.6.0":
            raise ValueError("OpenMM distribution version differs from pinned 8.6.0")
        platform = openmm.Platform.getPlatformByName("CPU")
        root = (Path(forcefield.__file__).parent / "data").resolve()
        files: dict[str, str] = {}

        def fingerprint(relative: str) -> None:
            if relative in files:
                return
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("force-field include escapes built-in data")
            raw = path.read_bytes()
            files[relative] = hashlib.sha256(raw).hexdigest()
            for node in ET.fromstring(raw).findall("Include"):
                included = node.attrib["file"]
                candidate = (path.parent / included).resolve()
                if not candidate.is_file():
                    candidate = (root / included).resolve()
                fingerprint(str(candidate.relative_to(root)))

        for name in ("amber14-all.xml", "implicit/gbn2.xml"):
            fingerprint(name)
        if files != FORCEFIELD_SHA256:
            raise ValueError("installed built-in force-field bytes differ from fixed v1")
        return {"method_id": "openmm_protein_minimize_v1", "schema": SCHEMA,
                "distribution_version": version("openmm"), "engine_build": openmm.version.full_version,
                "platform": platform.getName(), "platform_properties": {"Threads": "1"},
                "hydrogen_platform": "CPU", "hydrogen_platform_properties": {"Threads": "1"},
                "forcefield_files_sha256": files, "forcefield_files": ["amber14-all.xml", "implicit/gbn2.xml"],
                "nonbonded_method": "NoCutoff", "constraints": None, "pH": 7.0,
                "tolerance_kJ_mol_nm": 10.0, "max_iterations": 50,
                "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    except (ImportError, ValueError, OSError, ET.ParseError) as exc:
        raise ToolFailure(FailureClass.precondition, "fixed OpenMM 8.6.0 CPU force field unavailable",
                          detail={"reason_code": "openmm_unavailable"}) from exc


def capability() -> dict[str, Any]:
    try:
        require_process_identity()
        dep = dependencies()
    except ToolFailure as exc:
        return {"available": False, "reason_code": exc.detail.get("reason_code", "openmm_unavailable"),
                "explanation": exc.message}
    return {"available": True, "execution_lane": "durable_job", "protocol_id": PROTOCOL,
            "method_id": dep["method_id"], "distribution_version": dep["distribution_version"],
            "engine_build": dep["engine_build"], "unit": "kJ/mol",
            "limitations": "protein-only implicit-solvent potential; complete standard protein required; no affinity or stability claim"}


def require_process_identity() -> None:
    try:
        supported()
    except IdentityUnavailable as exc:
        raise ToolFailure(FailureClass.precondition, str(exc),
                          detail={"reason_code": "process_identity_unavailable"}) from exc


def _template_heavy(resname: str, *, terminal: bool) -> set[str]:
    """Read the installed, fingerprinted Amber template, including terminal OXT."""
    try:
        from openmm.app import forcefield
    except (ImportError, OSError) as exc:
        raise ToolFailure(FailureClass.precondition, "fixed OpenMM 8.6.0 CPU force field unavailable",
                          detail={"reason_code": "openmm_unavailable"}) from exc

    path = Path(forcefield.__file__).parent / "data" / "amber14" / "protein.ff14SB.xml"
    root = ET.parse(path).getroot()
    elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
    key = {"HIS": "HID", "CYS": "CYS"}.get(resname, resname)
    if terminal:
        key = "C" + key
    template = next((node for node in root.findall("./Residues/Residue") if node.attrib["name"] == key), None)
    if template is None:
        raise ToolFailure(FailureClass.precondition, "fixed force field has no standard residue template")
    return {node.attrib["name"] for node in template.findall("Atom")
            if elements[node.attrib["type"]] not in {"H", "D"}}


def preflight(store: Any, structure: str, *, seed: int) -> dict[str, Any]:
    require_process_identity()
    method = dependencies()
    if (store.meta(structure)["kind"], store.meta(structure)["schema"]) != ("prepared_structure", "prepared_structure@1"):
        raise ToolFailure(FailureClass.input_invalid, "OpenMM requires prepared_structure@1")
    prepared = store.load(structure)
    manifest = store.load(prepared["manifest"])
    model = _parse(ToolContext(store=store, call_id="openmm_preflight"), structure)[0]
    original_model = _parse(ToolContext(store=store, call_id="openmm_source_hydrogens"), manifest["input"])[0]
    protein: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    if manifest["waters"] == "strip_all":
        for chain in original_model:
            for residue in chain:
                if residue.is_water():
                    exclusions.append({"residue": _res_ref(chain, residue, original_model.num),
                                       "atom_count": len(residue), "reason": "water_removed_during_preparation"})
    removed_h: list[dict[str, Any]] = []
    if manifest["hydrogens"] == "strip":
        for chain in original_model:
            for residue in chain:
                ref = _res_ref(chain, residue, original_model.num)
                if residue.het_flag != "A" and residue.label_seq is None:
                    continue
                for atom in residue:
                    if atom.element.name in {"H", "D"}:
                        removed_h.append({"residue": ref, "atom_name": atom.name,
                                          "element": atom.element.name, "source_serial": atom.serial,
                                          "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z]})
    chain_names: set[str] = set()
    atom_count = 0
    for chain in model:
        if chain.name in chain_names:
            raise ToolFailure(FailureClass.input_invalid, "duplicate author chain identity")
        chain_names.add(chain.name)
        chain_protein: list[dict[str, Any]] = []
        for residue in chain:
            ref = _res_ref(chain, residue, model.num)
            polymer = residue.het_flag == "A" or residue.label_seq is not None
            if not polymer:
                exclusions.append({"residue": ref, "atom_count": len(residue),
                                   "reason": "water" if residue.is_water() else "nonprotein"})
                continue
            if residue.name not in AMINO:
                raise ToolFailure(FailureClass.precondition, "modified or unsupported polymer residue",
                                  detail={"residue": ref})
            atoms = []
            names: set[str] = set()
            for atom in residue:
                name = atom.name.strip()
                altloc = atom.altloc.strip("\x00 ")
                if altloc:
                    raise ToolFailure(FailureClass.input_invalid, "unresolved alternate site", detail={"residue": ref})
                if name in names or not re.fullmatch(r"[A-Za-z0-9']{1,4}", name):
                    raise ToolFailure(FailureClass.input_invalid, "ambiguous atom identity", detail={"residue": ref})
                names.add(name)
                entry = {"residue": ref, "atom_name": name, "element": atom.element.name,
                         "source_serial": atom.serial, "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z]}
                if atom.element.name in {"H", "D"}:
                    removed_h.append(entry)
                else:
                    if atom.element.name not in {"C", "N", "O", "S"}:
                        raise ToolFailure(FailureClass.precondition, "unsupported protein heavy element", detail={"atom": entry})
                    atoms.append(entry)
            if not {"N", "CA", "C", "O"} <= names:
                raise ToolFailure(FailureClass.precondition, "missing protein backbone heavy atom", detail={"residue": ref})
            chain_protein.append({"residue": ref, "atoms": atoms})
            atom_count += len(atoms)
        if chain_protein:
            for index, item in enumerate(chain_protein):
                if index:
                    previous = chain_protein[index - 1]["residue"]
                    current = item["residue"]
                    # Label sequence is polymer order; author numbering may be arbitrary.
                    # Without labels, geometry still detects unsupported discontinuities.
                    if (previous["seq_label"] is not None and current["seq_label"] is not None and
                            current["seq_label"] - previous["seq_label"] != 1):
                        raise ToolFailure(FailureClass.precondition, "protein chain has a sequence gap",
                                          detail={"residue": current, "reason_code": "sequence_gap"})
                    prev_c = next(a["coordinates_A"] for a in chain_protein[index - 1]["atoms"] if a["atom_name"] == "C")
                    next_n = next(a["coordinates_A"] for a in item["atoms"] if a["atom_name"] == "N")
                    distance = math.dist(prev_c, next_n)
                    if not 1.1 <= distance <= 1.7:
                        raise ToolFailure(FailureClass.precondition, "unsupported peptide C-N distance",
                                          detail={"residue": current, "distance_A": distance,
                                                  "reason_code": "peptide_geometry"})
                observed = {a["atom_name"] for a in item["atoms"]}
                expected = _template_heavy(item["residue"]["resname"], terminal=index == len(chain_protein) - 1)
                if observed != expected:
                    missing = sorted(expected - observed)
                    extra = sorted(observed - expected)
                    reason = "missing terminal OXT" if "OXT" in missing else "protein heavy atoms do not match Amber template"
                    raise ToolFailure(FailureClass.precondition, reason + "; heavy-atom repair is unsupported",
                                      detail={"residue": item["residue"], "missing": missing, "extra": extra,
                                              "reason_code": "missing_terminal_oxt" if "OXT" in missing else "heavy_template_mismatch"})
            protein.append({"chain_auth": chain.name, "residues": chain_protein})
    if not protein or atom_count > ATOM_CAP:
        raise ToolFailure(FailureClass.resource_exceeded if atom_count > ATOM_CAP else FailureClass.input_invalid,
                          "protein atom count is empty or exceeds fixed limit")
    if len({canonical_json(r["residue"]) for c in protein for r in c["residues"]}) != sum(len(c["residues"]) for c in protein):
        raise ToolFailure(FailureClass.input_invalid, "ambiguous residue identity")
    if any(not math.isfinite(x) or abs(x) > 1e6 for c in protein for r in c["residues"] for a in r["atoms"] for x in a["coordinates_A"]):
        raise ToolFailure(FailureClass.input_invalid, "invalid protein coordinate")
    return {"schema": "openmm_preparation_input@1", "structure": structure,
            "source_handle": manifest["source_handle"], "preparation_manifest": prepared["manifest"],
            "model_number": model.num, "protein": protein, "excluded": exclusions,
            "source_hydrogens_removed": removed_h, "heavy_atom_count": atom_count, "seed": seed,
            "method": method}
