"""Fixed, isolated QuickVina 2.1 docking worker for M18 (spec .dryforge/spec.md 3--5). JSON files only.

The guardian launches this script with the pinned ``.deps/docking/venv-locked`` interpreter (Meeko 0.8.0, RDKit
2026.03.6, MDAnalysis 2.10.0, gemmi 0.7.5); Meeko, RDKit and MDAnalysis are imported here and nowhere in the server.
The only ``mw`` code used is ``mw/docking_constants.py``, loaded by file path (no package import). The engine is
the one executable ``.deps/qvina/env/bin/qvina2``; its SHA-256 is computed here and must equal both the pinned
constant and the install record. Python sockets are denied before any chemistry import; nothing is fetched.
Meeko's polymer receptor route (``Polymer.from_pdb_string``) is never used: it downloads unknown residue templates.

Job mode (no arguments, cwd = private attempt directory). ``input.json`` is the control record: ``adapter`` =
``qvina_dock_v1``, ``input_sha256`` (SHA-256 of the ``structure.json`` bytes), ``job_id`` and ``attempt_id`` (echoed);
other control keys are ignored. ``structure.json`` is the canonical staged payload (every byte entry is
``{"b64": base64, "sha256": hex}`` and is checked against its hash):

    {"schema": "docking_worker_input@1",
     "receptor": {"handle": str,                       # receptor import handle (sidecar refs must name it)
                  "format": "pdb" | "cif", "bytes": entry, "model_number": int >= 1,
                  "connectivity": {"kind": "pdb_conect", "sidecar": null} | {"kind": "sidecar", "sidecar": entry},
                  "instance": null | {model_number, chain_auth, chain_label, seq_auth, seq_label, icode, resname}},
     "ligand": {"source": "sdf", "sdf": entry} |
               {"source": "candidate", "parent_sdf": entry,
                "candidate_set_parent_sha256": hex,     # ligand_candidate_set@1 parent_sha256
                "candidate": {"id": str, "smiles": str, "retained_parent_atoms": [int, ...], "stereo_flag": str}},
     "mode": "free" | "core_fixed",
     "box": {"source": "ligand_range" | "instance_range", "margin_A": float} |
            {"source": "manual", "center_A": [x, y, z], "size_A": [x, y, z]},
     "parameters": {"seed": int, "exhaustiveness": int, "num_modes": int, "energy_range": float,
                    "conformers": int | null}}                         # normalized as by mw.docking_inputs

Success writes canonical ``result.json`` (sorted keys, ``,``/``:`` separators, UTF-8, no NaN) and exits 0:

    {"schema": "docking_worker_output@1", "protocol": "qvina_dock_v1", "job_id": str, "attempt_id": str,
     "method": "qvina_free_v1" | "qvina_core_fixed_score_only_v1",
     "inputs": {"receptor": {"sha256", "format", "model_number", "atom_count",   # model atoms, instance included
                             "connectivity": {"kind", "sidecar_sha256" | null},
                             "removed_instance": null | {"residue": 7 fields, "atom_count", "element_counts"}},
                "ligand": {"source", "sdf_sha256" | null, "parent_sdf_sha256" | null, "candidate_id" | null,
                           "generated": {"hydrogens": bool, "coordinates": bool},
                           "stereo_flag": str | null, "unspecified_stereo_centers": int | null},
                "mode": "free" | "core_fixed"},
     "box": {"center_A": [3], "size_A": [3], "source", "margin_A": float | null},
     "parameters": {"seed", "exhaustiveness", "num_modes", "energy_range", "conformers" | null, "cpu": 1},
     "engine": {"name": "qvina", "version": "2.1.0", "binary_sha256", "package": "qvina-2.1.0-<build>"},
     "preparation": {"tool": "Meeko", "version": "0.8.0", "rdkit_version": "2026.03.6", "atom_typing": "ad4",
                     "charges": "gasteiger"},
     "modes": [{"mode": int (1-based), "score_kcal_mol": float,             # engine value, never renamed
                "engine_rmsd_lb_A": float | null, "engine_rmsd_ub_A": float | null,       # free only
                "conformer_index": int | null, "core_max_deviation_A": float | null,      # core_fixed only
                "atoms_outside_box": int, "min_heavy_atom_distance_A": float,
                "pose_sdf": str,          # V2000 record without "$$$$", title "mode_<n>", atom i = ligand_serial i
                "contacts": [{"ligand_serial", "ligand_element", "ligand_parent_serial": int | null,
                              "receptor_atom": {"residue": 7 fields, "atom_name", "altloc", "element", "site_index"},
                              "distance_A", "kind": "polar_contact" | "hydrophobic_contact" | "contact"}]}],
     "counts": {"modes", "contacts_by_mode": [int], "null_result": bool,
                "samples_generated": int | null, "samples_scored": int | null},             # core_fixed only
     "limitations": [str, ...]}                                   # docking_constants.applicable_limitations

Handles, the acknowledgement and ``input_sha256`` of the normalized job arguments are the server's (T5); the worker
reports byte hashes only. Any refusal writes ``error.json`` (``docking_worker_error@1``: ``error_class``
input_invalid | resource_exceeded | fatal, ``reason_code`` from the closed set in ``docking_constants.REASONS``,
``message``, ``detail``) and exits 1 with no result. Results are a pure function of the staged bytes, the echoed
control identity and the engine/Meeko/RDKit/MDAnalysis versions: no clock, and every random choice takes the
staged seed (qvina ``--seed``, RDKit ETKDG ``randomSeed``). Wall-clock time and cancellation are the caller's.

Science rules (spec 3--4), all here:
- Receptor: M11 traversal/connectivity rules (``mw.docking_inputs``), explicit model, the one instance with equal
  seven fields removed (hydrogens included), leftovers refused, no hydrogens refused; PDBQT = M11 MDAnalysis
  inference (``chemical_worker._receptor`` arguments) -> Meeko ``MoleculePreparation`` AD4 types/Gasteiger charges per
  covalent fragment -> ATOM lines in input order, nonpolar H merged by Meeko, input coordinates.
- Free docking: qvina2 search with fixed arguments; modes in engine output order. Core-fixed: core subgraph match,
  coordMap ETKDG samples aligned on the core and the core heavy atoms overwritten with the parent coordinates,
  ``qvina2 --score_only`` per sample (the score does not depend on the box: measured, see tests), listed by score
  then sample index, first ``num_modes`` kept.
- Pose SDF atoms are in input order (SDF order, or the RDKit ``AddHs`` order of the candidate). Merged nonpolar H
  of a docked pose are re-placed by RDKit ``AddHs(addCoords=True)`` from the pose heavy atoms (as Meeko does).
- Geometry (contacts, ``atoms_outside_box``, minimum distance, core deviation) is measured on the stored pose SDF
  coordinates. Contacts: heavy atoms, distance <= 4.0 A, M2 element rule.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path
from typing import Any


def _deny_network() -> None:
    """Deny Python socket egress before importing native chemistry (defense in depth, as chemical_worker)."""
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("external network is disabled for the docking worker")

    def audit(event: str, _args: tuple[object, ...]) -> None:
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            blocked()

    sys.addaudithook(audit)
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.bind = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


_deny_network()
warnings.simplefilter("ignore")

import gemmi
import MDAnalysis as mda
import meeko
from MDAnalysis.converters.RDKitInferring import MDAnalysisInferrer
from meeko import MoleculePreparation, PDBQTWriterLegacy
from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import AllChem, rdMolAlign
from rdkit.Geometry import Point3D

RDLogger.DisableLog("rdApp.*")


def _load_constants() -> Any:
    path = Path(__file__).resolve().parents[1] / "docking_constants.py"
    spec = importlib.util.spec_from_file_location("docking_constants_pinned", path)
    if spec is None or spec.loader is None:
        raise ImportError("pinned docking constants unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _load_constants()

ROOT = Path(__file__).resolve().parents[3]
QVINA_DIR = ROOT / ".deps/qvina"
QVINA = QVINA_DIR / "env/bin/qvina2"
QVINA_RECORD = QVINA_DIR / "install-record.json"
QVINA_SHA256 = "caf5f22a3928be8adf3cb017508eaacbdcecf68ef29c5bca24fceea016c5f79c"   # T1/T2, conda-forge h4a521e9_8
PINNED = {"meeko": "0.8.0", "rdkit": "2026.03.6", "MDAnalysis": "2.10.0", "gemmi": "0.7.5"}
ADAPTER = K.PROTOCOL
MAX_STAGED_BYTES = 48 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
MAX_MATCHES = 10_000
BOX_DECIMALS = 6
COORD_LIMIT = 100_000
SERIAL = "dock_serial"
SHA_RE = re.compile(r"[0-9a-f]{64}")
CONTROL_ID_RE = re.compile(r"[a-z0-9_]{1,100}")
RESIDUE_KEYS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
ATOM_REF_KEYS = {"structure_handle", "residue", "atom_name", "altloc", "element", "site_index"}
AMINO = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO",
         "SER", "THR", "TRP", "TYR", "VAL", "HSD", "HSE", "HSP", "HID", "HIE", "HIP"}   # M11 chemical_inputs.AMINO
RECEPTOR_ELEMENTS = {"H", "C", "N", "O", "S"}
MAX_BONDS = 20_000
POLAR = {"N", "O"}
ALLOWED_ATOMIC_NUMBERS = frozenset(Chem.GetPeriodicTable().GetAtomicNumber(s) for s in K.ALLOWED_LIGAND_ELEMENTS)
SCORE_ONLY_RE = re.compile(r"^Affinity:\s+(\S+)\s+\(kcal/mol\)\s*$", re.MULTILINE)
# Decimal with optional exponent (qvina prints large clash values as e.g. 1.2e+05); nan/inf/hex never match.
SCORE_NUMBER_RE = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")
VINA_RESULT_RE = re.compile(r"^REMARK VINA RESULT:\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
ENGINE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "OMP_NUM_THREADS": "1"}


class DockingWorkerError(Exception):
    def __init__(self, error_class: str, reason_code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        if reason_code not in K.REASONS or error_class not in ("input_invalid", "resource_exceeded", "fatal"):
            raise ValueError("docking worker reason outside the closed set")
        self.error_class = error_class
        self.reason_code = reason_code
        self.detail = detail or {}

    def envelope(self) -> dict[str, Any]:
        envelope = {"schema": "docking_worker_error@1", "error_class": self.error_class,
                    "reason_code": self.reason_code, "message": str(self)[:240], "detail": self.detail}
        if len(canonical_json(envelope)) > MAX_ERROR_BYTES:
            envelope["detail"] = {"truncated": True}
        return envelope


def _refuse(reason: str, message: str, **detail: Any) -> DockingWorkerError:
    return DockingWorkerError("input_invalid", reason, message, detail)


def _fatal(reason: str, message: str) -> DockingWorkerError:
    return DockingWorkerError("fatal", reason, message)


def _malformed(message: str) -> DockingWorkerError:
    # A malformed staging record is a server defect, not a user input; no closer closed reason exists (spec 5.3).
    return _fatal("engine_failed", f"staged input malformed: {message}")


def canonical_json(value: Any) -> bytes:
    """Byte-identical to ``mw.core.handles.canonical_json``."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------ receptor (spec 3.2; mw.docking_inputs rules)
def _res_ref(chain: Any, residue: Any, model_number: int) -> dict[str, Any]:
    """Same seven fields as ``mw.tools.structural._res_ref``."""
    return {"model_number": model_number, "chain_auth": chain.name, "seq_auth": residue.seqid.num,
            "icode": residue.seqid.icode.strip(), "chain_label": residue.subchain or None,
            "seq_label": residue.label_seq, "resname": residue.name}


def _nonstandard(residue: Any) -> bool:
    return not residue.is_water() and (residue.het_flag == "H" or residue.name not in AMINO)


def receptor_rows(raw: bytes, fmt: str, handle: str, model_number: int) -> list[dict[str, Any]]:
    """Atom rows of one model in M11 ``receptor_atoms`` order (``site_index`` = traversal position)."""
    try:
        text = raw.decode("utf-8")
        st = (gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block()) if fmt == "cif"
              else gemmi.read_pdb_string(text))
    except (UnicodeError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        raise _refuse("receptor_invalid", "receptor bytes are not a readable PDB/mmCIF structure") from exc
    selected = [model for model in st if model.num == model_number]
    if len(selected) != 1:
        raise _refuse("receptor_invalid", "exact receptor model unavailable or ambiguous")
    rows: list[dict[str, Any]] = []
    ordinal = 0
    for chain in selected[0]:
        for residue in chain:
            rr = _res_ref(chain, residue, model_number)
            for atom in residue:
                coord = [atom.pos.x, atom.pos.y, atom.pos.z]
                if not all(math.isfinite(x) and abs(x) <= COORD_LIMIT for x in coord):
                    raise _refuse("receptor_invalid", "receptor coordinate nonfinite or out of range", residue=rr)
                rows.append({"ref": {"structure_handle": handle, "residue": rr, "atom_name": atom.name,
                                     "altloc": atom.altloc.strip("\0 "), "element": atom.element.name,
                                     "site_index": len(rows)}, "coordinate_A": coord,
                             "element": atom.element.name, "water": residue.is_water(), "serial": atom.serial,
                             "residue_ordinal": ordinal, "nonstandard": _nonstandard(residue)})
            ordinal += 1
    if not 1 <= len(rows) <= K.MAX_RECEPTOR_ATOMS:
        raise _refuse("receptor_invalid", f"receptor atom count must be 1-{K.MAX_RECEPTOR_ATOMS}")
    return rows


def resolve_instance(rows: list[dict[str, Any]], instance: dict[str, Any]) -> list[int]:
    """Site indices of the one nonstandard residue whose seven fields equal ``instance`` exactly (never the first)."""
    ordinals = sorted({row["residue_ordinal"] for row in rows
                       if row["nonstandard"] and row["ref"]["residue"] == instance})
    if not ordinals:
        raise _refuse("receptor_instance_unknown", "no nonstandard residue instance has these seven fields")
    if len(ordinals) > 1:
        raise _refuse("receptor_instance_ambiguous", "several residue instances share these seven fields",
                      matches=len(ordinals))
    return [row["ref"]["site_index"] for row in rows if row["residue_ordinal"] == ordinals[0]]


def _pdb_conect(rows: list[dict[str, Any]], raw: bytes) -> set[tuple[int, int]]:
    ids = [row["serial"] for row in rows]
    if any(type(x) is not int or x <= 0 for x in ids) or len(set(ids)) != len(ids):
        raise _refuse("receptor_invalid", "PDB serials are ambiguous for CONECT")
    lookup = {x: i for i, x in enumerate(ids)}
    pairs: set[tuple[int, int]] = set()
    for line in raw.decode("utf-8").splitlines():
        if not line.startswith("CONECT"):
            continue
        try:
            values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
        except ValueError as exc:
            raise _refuse("receptor_invalid", "malformed PDB CONECT serial") from exc
        for second in values[1:]:
            if values[0] not in lookup or second not in lookup or values[0] == second:
                raise _refuse("receptor_invalid", "dangling or self PDB CONECT")
            pairs.add(tuple(sorted((lookup[values[0]], lookup[second]))))  # reverse duplicates merge
    return pairs


def _residue_fields_ok(value: Any) -> bool:
    return (type(value) is dict and set(value) == set(RESIDUE_KEYS) and type(value["model_number"]) is int and
            value["model_number"] >= 1 and type(value["chain_auth"]) is str and
            (value["chain_label"] is None or type(value["chain_label"]) is str) and type(value["seq_auth"]) is int and
            (value["seq_label"] is None or type(value["seq_label"]) is int) and type(value["icode"]) is str and
            type(value["resname"]) is str and value["resname"] != "")


def _strict_ref(value: Any, source: str) -> str:
    ok = (type(value) is dict and set(value) == ATOM_REF_KEYS and value["structure_handle"] == source and
          _residue_fields_ok(value["residue"]) and
          all(type(value[k]) is str for k in ("atom_name", "altloc", "element")) and
          type(value["site_index"]) is int and value["site_index"] >= 0)
    if not ok:
        raise _refuse("receptor_invalid", "invalid complete atom reference or another source")
    return json.dumps(value, sort_keys=True)


def _sidecar(rows: list[dict[str, Any]], body: bytes, source: str) -> set[tuple[int, int]]:
    try:
        obj = json.loads(body)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _refuse("receptor_invalid", "bond sidecar is not JSON") from exc
    if (type(obj) is not dict or obj.get("schema") != "receptor_bonds@1" or obj.get("complete") is not True or
            type(obj.get("bonds")) is not list or obj.get("source_handle", obj.get("receptor_input_handle")) != source):
        raise _refuse("receptor_invalid", "incomplete or source-mismatched bond sidecar")
    lookup = {json.dumps(row["ref"], sort_keys=True): i for i, row in enumerate(rows)}
    if len(lookup) != len(rows):
        raise _refuse("receptor_invalid", "ambiguous source atom identities")
    pairs: set[tuple[int, int]] = set()
    for bond in obj["bonds"]:
        if type(bond) is not dict or set(bond) != {"first", "second"}:
            raise _refuse("receptor_invalid", "invalid sidecar bond")
        x, y = lookup.get(_strict_ref(bond["first"], source)), lookup.get(_strict_ref(bond["second"], source))
        if x is None or y is None or x == y:
            raise _refuse("receptor_invalid", "dangling/self sidecar bond")
        pair = tuple(sorted((x, y)))
        if pair in pairs:
            raise _refuse("receptor_invalid", "duplicate sidecar bond")
        pairs.add(pair)
    return pairs


def check_receptor(raw: bytes, fmt: str, handle: str, model_number: int, connectivity: dict[str, Any],
                   instance: dict[str, Any] | None, sidecar_raw: bytes | None) -> dict[str, Any]:
    """Rows, removed instance, bonds and leftovers, in ``mw.docking_inputs.check_receptor`` order, then hydrogens."""
    rows = receptor_rows(raw, fmt, handle, model_number)
    sites = [] if instance is None else resolve_instance(rows, instance)
    if connectivity["kind"] == "pdb_conect":
        if fmt != "pdb":
            raise _refuse("receptor_invalid", "PDB CONECT requires an original receptor PDB")
        pairs = _pdb_conect(rows, raw)
    else:
        pairs = _sidecar(rows, sidecar_raw, handle)
    if not 1 <= len(pairs) <= MAX_BONDS:
        raise _refuse("receptor_invalid", "empty or oversized receptor connectivity")
    bonds = sorted(pairs)
    removed = set(sites)
    crossing = [pair for pair in bonds if (pair[0] in removed) != (pair[1] in removed)]
    if crossing:
        raise _refuse("receptor_instance_covalent", "the selected instance is covalently bonded to the receptor",
                      bonds=[[_public_ref(rows[a]), _public_ref(rows[b])] for a, b in
                             crossing[:K.MAX_LISTED_RECEPTOR_ITEMS]], total=len(crossing))
    kept = [row for row in rows if row["ref"]["site_index"] not in removed]
    unsupported: dict[int, dict[str, Any]] = {}
    for row in kept:
        if row["water"] or row["nonstandard"] or row["element"].upper() not in RECEPTOR_ELEMENTS:
            item = unsupported.setdefault(row["residue_ordinal"], {"residue": row["ref"]["residue"],
                                                                   "atom_names": []})
            item["atom_names"].append(row["ref"]["atom_name"])
    if unsupported:
        items = list(unsupported.values())
        raise _refuse("receptor_unsupported_residue", "receptor keeps water, ions, cofactors, other ligands or "
                      "unsupported residues", items=items[:K.MAX_LISTED_RECEPTOR_ITEMS], total=len(items))
    altloc = [{"residue": row["ref"]["residue"], "atom_name": row["ref"]["atom_name"], "altloc": row["ref"]["altloc"]}
              for row in kept if row["ref"]["altloc"]]
    if altloc:
        raise _refuse("receptor_altloc_present", "receptor has alternate locations",
                      items=altloc[:K.MAX_LISTED_RECEPTOR_ITEMS], total=len(altloc))
    if not any(row["element"].upper() == "H" for row in kept):
        raise _refuse("receptor_hydrogens_missing", "receptor has no explicit hydrogen atoms")
    removed_summary = None
    if sites:
        removed_summary = {"residue": rows[sites[0]]["ref"]["residue"], "atom_count": len(sites),
                           "element_counts": dict(sorted(Counter(rows[s]["element"] for s in sites).items()))}
    local = {row["ref"]["site_index"]: i for i, row in enumerate(kept)}
    kept_bonds = [(local[a], local[b]) for a, b in bonds if a in local and b in local]
    return {"rows": rows, "kept": kept, "kept_bonds": kept_bonds, "instance_sites": sites,
            "removed_instance": removed_summary}


def _public_ref(row: dict[str, Any]) -> dict[str, Any]:
    ref = row["ref"]
    return {"residue": ref["residue"], "atom_name": ref["atom_name"], "altloc": ref["altloc"],
            "element": ref["element"], "site_index": ref["site_index"]}


def _prep_failed(message: str, rows: list[dict[str, Any]] | None = None, sites: list[int] | None = None,
                 code: str | None = None) -> DockingWorkerError:
    atoms = [_public_ref(rows[i]) for i in (sites or [])[:8]] if rows else []
    return _refuse("receptor_prep_failed", message, m11_check=code, atoms=atoms)


def receptor_graph(kept: list[dict[str, Any]], bonds: list[tuple[int, int]]) -> Chem.Mol:
    """RDKit graph by the M11 inference (``chemical_worker._receptor`` arguments and graph checks)."""
    neighbors: list[set[int]] = [set() for _ in kept]
    for first, second in bonds:
        neighbors[first].add(second)
        neighbors[second].add(first)
        if math.dist(kept[first]["coordinate_A"], kept[second]["coordinate_A"]) <= 1e-7:
            raise _prep_failed("zero-length supplied covalent bond", kept, [first, second], "receptor_graph_invalid")
    for index, row in enumerate(kept):
        if row["element"].upper() == "H" and (len(neighbors[index]) != 1 or
                                              kept[next(iter(neighbors[index]))]["element"].upper() == "H"):
            raise _prep_failed("explicit H must have one heavy covalent neighbor", kept, [index],
                               "receptor_graph_invalid")
    residue_keys: dict[str, int] = {}
    residues: list[dict[str, Any]] = []
    resindex: list[int] = []
    for row in kept:
        key = json.dumps(row["ref"]["residue"], sort_keys=True)
        if key not in residue_keys:
            residue_keys[key] = len(residues)
            residues.append(row["ref"]["residue"])
        resindex.append(residue_keys[key])
    try:
        u = mda.Universe.empty(len(kept), n_residues=len(residues), atom_resindex=resindex, trajectory=True)
        u.add_TopologyAttr("names", [r["ref"]["atom_name"] for r in kept])
        u.add_TopologyAttr("elements", [r["element"] for r in kept])
        u.add_TopologyAttr("resnames", [r["resname"] for r in residues])
        u.add_TopologyAttr("resids", list(range(1, len(residues) + 1)))
        u.add_TopologyAttr("chainIDs", ["X"] * len(kept))
        u.add_TopologyAttr("segids", ["X"])
        u.add_TopologyAttr("bonds", sorted(bonds))
        u.atoms.positions = [r["coordinate_A"] for r in kept]
        mol = u.atoms.convert_to.rdkit(implicit_hydrogens=False, force=False,
                                       inferrer=MDAnalysisInferrer(max_iter=200, sanitize=True))
    except Exception as exc:
        raise _prep_failed(f"M11 chemistry inference failed ({type(exc).__name__})") from exc
    if [a.GetIntProp("_MDAnalysis_index") for a in mol.GetAtoms()] != list(range(len(kept))):
        raise _prep_failed("receptor index bijection failed")
    actual = {tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))) for b in mol.GetBonds()}
    if actual != set(bonds):
        raise _prep_failed("inferred graph edge set differs from supplied bonds")
    try:
        Chem.SanitizeMol(mol)
    except (ValueError, RuntimeError) as exc:
        raise _prep_failed("inferred receptor graph cannot be sanitized") from exc
    for atom in mol.GetAtoms():
        if (atom.GetNumRadicalElectrons() or atom.GetNumImplicitHs() or atom.GetNumExplicitHs() or
                atom.GetIsotope() != 0 or atom.GetDegree() == 0):
            raise _prep_failed("unsupported radical, implicit H, isotope or isolated atom", kept, [atom.GetIdx()],
                               "receptor_graph_invalid")
    _protein_chemistry(kept, mol)
    return mol


def _protein_chemistry(rows: list[dict[str, Any]], mol: Chem.Mol) -> None:
    """M11 ``chemical_worker._protein_chemistry`` assertions on the inferred graph (refusal only, no output)."""
    residues: dict[str, tuple[dict[str, Any], dict[str, int]]] = {}
    for index, row in enumerate(rows):
        key = json.dumps(row["ref"]["residue"], sort_keys=True)
        names = residues.setdefault(key, (row["ref"]["residue"], {}))[1]
        if row["ref"]["atom_name"] in names:
            raise _prep_failed("duplicate protein atom name in exact residue", rows,
                               [names[row["ref"]["atom_name"]], index], "receptor_graph_invalid")
        names[row["ref"]["atom_name"]] = index

    def order(a: int, b: int) -> Any:
        found = mol.GetBondBetweenAtoms(a, b)
        if found is None:
            raise _prep_failed("required protein bond missing", rows, [a, b], "receptor_graph_invalid")
        return found.GetBondType()

    single, double, aromatic = Chem.BondType.SINGLE, Chem.BondType.DOUBLE, Chem.BondType.AROMATIC
    for residue, names in residues.values():
        if not {"N", "CA", "C", "O"} <= names.keys():
            raise _prep_failed("protein backbone atom inventory incomplete", rows, list(names.values()),
                               "receptor_graph_invalid")
        if (order(names["N"], names["CA"]) != single or order(names["CA"], names["C"]) != single or
                order(names["C"], names["O"]) != double):
            raise _prep_failed("backbone inferred bond order invalid", rows, [names["N"], names["CA"], names["C"]],
                               "receptor_graph_invalid")
        if set(names) & {"CAY", "CY", "OY"}:
            if not {"CAY", "CY", "OY"} <= names.keys():
                raise _prep_failed("merged terminal cap atom inventory incomplete", rows, [], "receptor_graph_invalid")
            if (order(names["CAY"], names["CY"]) != single or order(names["CY"], names["OY"]) != double or
                    order(names["CY"], names["N"]) != single or
                    sum(n.GetSymbol() == "H" for n in mol.GetAtomWithIdx(names["CAY"]).GetNeighbors()) != 3):
                raise _prep_failed("merged terminal cap inferred graph invalid", rows, [names["CAY"]],
                                   "receptor_graph_invalid")
        acid = {"ASP": ("CG", "OD1", "OD2"), "GLU": ("CD", "OE1", "OE2")}.get(residue["resname"])
        if acid and all(x in names for x in acid):
            orders = [order(names[acid[0]], names[x]) for x in acid[1:]]
            if sorted(map(str, orders)) != sorted(map(str, (single, double))):
                raise _prep_failed("acid oxygens lack one inferred single and one double bond", rows,
                                   [names[x] for x in acid], "receptor_graph_invalid")
        amide = {"ASN": ("CG", "OD1", "ND2"), "GLN": ("CD", "OE1", "NE2")}.get(residue["resname"])
        if amide and all(x in names for x in amide) and (
                order(names[amide[0]], names[amide[1]]) != double or order(names[amide[0]], names[amide[2]]) != single
                or mol.GetAtomWithIdx(names[amide[2]]).GetFormalCharge() != 0):
            raise _prep_failed("amide graph contradicts nonacceptor amide nitrogen", rows,
                               [names[x] for x in amide], "receptor_graph_invalid")
        if residue["resname"] in {"HSD", "HID", "HSE", "HIE", "HSP", "HIP", "HIS"}:
            ring = ("CG", "ND1", "CE1", "NE2", "CD2")
            if not {"CB", *ring} <= names.keys():
                raise _prep_failed("histidine ring atom inventory incomplete", rows, [], "histidine_ring_graph")
            expected_heavy = {"CG": {"CB", "ND1", "CD2"}, "ND1": {"CG", "CE1"}, "CE1": {"ND1", "NE2"},
                              "NE2": {"CE1", "CD2"}, "CD2": {"NE2", "CG"}}
            for first, second in zip(ring, ring[1:] + ring[:1], strict=True):
                edge = mol.GetBondBetweenAtoms(names[first], names[second])
                if edge is None or edge.GetBondType() != aromatic or not edge.GetIsAromatic():
                    raise _prep_failed("histidine ring edge is not aromatic", rows, [names[first], names[second]],
                                       "histidine_ring_graph")
            if order(names["CB"], names["CG"]) != single:
                raise _prep_failed("histidine CB-CG attachment is not single", rows, [names["CG"]],
                                   "histidine_ring_graph")
            for name in ring:
                atom = mol.GetAtomWithIdx(names[name])
                heavy = {n.GetIdx() for n in atom.GetNeighbors() if n.GetSymbol() != "H"}
                if not atom.GetIsAromatic() or heavy != {names[other] for other in expected_heavy[name]}:
                    raise _prep_failed("histidine ring connectivity/aromaticity invalid", rows, [names[name]],
                                       "histidine_ring_graph")
            protonated = []
            for atom_name in ("ND1", "NE2"):
                count = sum(n.GetSymbol() == "H" for n in mol.GetAtomWithIdx(names[atom_name]).GetNeighbors())
                if count > 1:
                    raise _prep_failed("multiple histidine ring H on one nitrogen", rows, [names[atom_name]],
                                       "histidine_ring_graph")
                if count:
                    protonated.append(atom_name)
            expected = {"HSD": ["ND1"], "HID": ["ND1"], "HSE": ["NE2"], "HIE": ["NE2"], "HSP": ["ND1", "NE2"],
                        "HIP": ["ND1", "NE2"]}.get(residue["resname"])
            if expected is not None and protonated != expected or protonated not in (["ND1"], ["NE2"],
                                                                                     ["ND1", "NE2"]):
                raise _prep_failed("histidine alias conflicts with supplied ring-H graph", rows,
                                   [names["ND1"], names["NE2"]], "histidine_alias_state")
            charges = {name: mol.GetAtomWithIdx(names[name]).GetFormalCharge() for name in ring}
            n_charges = sorted(charges[name] for name in ("ND1", "NE2"))
            if (any(charges[name] for name in ("CG", "CE1", "CD2")) or
                    (protonated == ["ND1", "NE2"] and n_charges != [0, 1]) or
                    (protonated != ["ND1", "NE2"] and any(n_charges))):
                raise _prep_failed("histidine inferred ring charge contradicts supplied ring-H state", rows,
                                   [names["ND1"], names["NE2"]], "histidine_charge_state")


def _fit(text: str, width: int) -> str:
    return text[:width]


def receptor_pdbqt(kept: list[dict[str, Any]], mol: Chem.Mol) -> str:
    """Rigid receptor PDBQT: Meeko AD4 type and Gasteiger charge per atom, input order and input coordinates.

    Label columns are fitted to the fixed PDB widths as Meeko does (qvina reads coordinates and types only);
    atom identity stays in the worker's own row list, never in these labels.
    """
    prep = MoleculePreparation(rigidify_bonds_smarts=["[*]~[*]"], rigidify_bonds_indices=[(0, 1)])
    mapping: list[tuple[int, ...]] = []
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False, fragsMolAtomMapping=mapping)
    typed: dict[int, Any] = {}
    try:
        for frag, indices in zip(frags, mapping, strict=True):
            setups = prep.prepare(frag)
            if len(setups) != 1:
                raise ValueError("one setup per fragment expected")
            for local, atom in enumerate(setups[0].atoms[:frag.GetNumAtoms()]):
                typed[indices[local]] = atom
    except Exception as exc:
        raise _prep_failed(f"Meeko receptor typing failed ({type(exc).__name__})") from exc
    lines = []
    for index, row in enumerate(kept):
        atom = typed.get(index)
        if atom is None:
            raise _prep_failed("Meeko returned no type for a receptor atom", kept, [index])
        if atom.is_ignore:
            continue
        charge = float(atom.charge)
        if atom.atom_type is None or not math.isfinite(charge):
            raise _prep_failed("Meeko receptor type or charge unavailable", kept, [index])
        residue = row["ref"]["residue"]
        seq = residue["seq_auth"] if -999 <= residue["seq_auth"] <= 9999 else residue["seq_auth"] % 10000
        lines.append(PDBQTWriterLegacy._make_pdbqt_line(
            len(lines) + 1, _fit(row["ref"]["atom_name"], 4), _fit(residue["resname"], 3),
            _fit(residue["chain_auth"], 1), seq, row["coordinate_A"], charge, atom.atom_type,
            _fit(residue["icode"], 1)))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ ligand (spec 3.3)
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


def _check_graph(mol: Chem.Mol) -> None:
    """Shared ligand graph checks in the closed reason order: fragments, elements, heavy-atom cap."""
    if len(Chem.GetMolFrags(mol)) != 1:
        raise _refuse("ligand_multiple_fragments", "ligand must be one connected molecule")
    if any(atom.GetAtomicNum() not in ALLOWED_ATOMIC_NUMBERS for atom in mol.GetAtoms()):
        raise _refuse("ligand_element_not_allowed", "ligand element outside H C N O S P F Cl Br I")
    heavy = sum(atom.GetAtomicNum() > 1 for atom in mol.GetAtoms())
    if heavy == 0:
        raise _refuse("ligand_unparseable", "ligand has no heavy atom")
    if heavy > K.MAX_LIGAND_HEAVY_ATOMS:
        raise _refuse("ligand_too_many_atoms", f"ligand has more than {K.MAX_LIGAND_HEAVY_ATOMS} heavy atoms")


def _planar(mol: Chem.Mol) -> bool:
    conf = mol.GetConformer()
    return len({conf.GetAtomPosition(i).z for i in range(mol.GetNumAtoms())}) == 1


def read_sdf(raw: bytes, *, parent: bool = False) -> Chem.Mol:
    """One V2000 record with explicit hydrogens and 3D coordinates; atom ``i`` keeps SDF serial ``i + 1``."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise _refuse("ligand_unparseable", "ligand SDF is not UTF-8") from exc
    records = split_sdf_records(text)
    if len(records) != 1:
        raise _refuse("ligand_record_count", "ligand SDF must hold exactly one record")
    lines = records[0].splitlines()
    if len(lines) < 4 or "V3000" in lines[3] or "\x00" in text:
        raise _refuse("ligand_unparseable", "ligand SDF must be one V2000 record (V3000 is not accepted)")
    try:
        mol = Chem.MolFromMolBlock(records[0] + "\n", sanitize=True, removeHs=False, strictParsing=True)
    except (ValueError, RuntimeError):
        mol = None
    if mol is None or mol.GetNumAtoms() == 0 or mol.GetNumConformers() != 1:
        raise _refuse("ligand_unparseable", "ligand SDF record cannot be read")
    conf = mol.GetConformer()
    if any(not math.isfinite(c) or abs(c) > COORD_LIMIT for i in range(mol.GetNumAtoms())
           for c in conf.GetAtomPosition(i)):
        raise _refuse("ligand_unparseable", "ligand coordinate nonfinite or out of range")
    for atom in mol.GetAtoms():
        atom.SetIntProp(SERIAL, atom.GetIdx() + 1)
    if parent:
        return mol
    _check_graph(mol)
    if _planar(mol):
        raise _refuse("ligand_not_3d", "every ligand atom has the same z coordinate (planar input)")
    missing = [atom.GetIdx() + 1 for atom in mol.GetAtoms() if atom.GetTotalNumHs(includeNeighbors=False)]
    if missing:
        raise _refuse("ligand_hydrogens_missing", "ligand atoms carry implicit hydrogens; hydrogens are not added",
                      sdf_serials=missing[:20], total=len(missing))
    return mol


def candidate_heavy(smiles: Any) -> Chem.Mol:
    if type(smiles) is not str or not smiles:
        raise _refuse("ligand_unparseable", "candidate SMILES missing")
    try:
        mol = Chem.MolFromSmiles(smiles)
    except (ValueError, RuntimeError):
        mol = None
    if mol is None or mol.GetNumAtoms() == 0:
        raise _refuse("ligand_unparseable", "candidate SMILES cannot be read")
    _check_graph(mol)
    return mol


def unspecified_stereo(mol: Chem.Mol) -> int:
    """Potential stereo elements (atoms and double bonds) left unspecified in the candidate SMILES."""
    return sum(item.specified == Chem.StereoSpecified.Unspecified for item in Chem.FindPotentialStereo(Chem.Mol(mol)))


def _explicit_only(mol: Chem.Mol) -> bool:
    return all(a.GetNumImplicitHs() == 0 and a.GetNumExplicitHs() == 0 for a in mol.GetAtoms())


def ligand_pdbqt(mol: Chem.Mol) -> tuple[str, dict[int, int]]:
    """Meeko 0.8.0 ligand PDBQT (AD4 types, Gasteiger, rings rigid as input) and the input-index -> PDBQT map."""
    try:
        setups = MoleculePreparation(rigid_macrocycles=True).prepare(mol)
        if len(setups) != 1:
            raise ValueError("one ligand setup expected")
        text, ok, error = PDBQTWriterLegacy.write_string(setups[0], add_index_map=True)
    except Exception as exc:
        raise _refuse("ligand_prep_failed", f"Meeko ligand preparation failed ({type(exc).__name__})") from exc
    if not ok:
        raise _refuse("ligand_prep_failed", f"Meeko ligand PDBQT failed: {str(error)[:160]}")
    index_map: dict[int, int] = {}
    for line in text.splitlines():
        if line.startswith("REMARK INDEX MAP"):
            values = [int(x) for x in line[len("REMARK INDEX MAP"):].split()]
            for first, second in zip(values[0::2], values[1::2], strict=True):
                index_map[first - 1] = second
    atom_lines = [line for line in text.splitlines() if line.startswith(("ATOM", "HETATM"))]
    if (sorted(index_map.values()) != list(range(1, len(atom_lines) + 1)) or
            any(not 0 <= i < mol.GetNumAtoms() for i in index_map)):
        raise _refuse("ligand_prep_failed", "Meeko index map does not cover the PDBQT atoms")
    for index in range(mol.GetNumAtoms()):
        if index not in index_map:
            atom = mol.GetAtomWithIdx(index)
            if atom.GetAtomicNum() != 1 or atom.GetDegree() != 1 or atom.GetNeighbors()[0].GetIdx() not in index_map:
                raise _refuse("ligand_prep_failed", "a non-merged ligand atom is missing from the PDBQT")
    torsions = sum(line.startswith("BRANCH") for line in text.splitlines())
    if torsions > K.MAX_ACTIVE_TORSIONS:
        raise _refuse("ligand_too_many_torsions", f"ligand has {torsions} active torsions (qvina limit "
                      f"{K.MAX_ACTIVE_TORSIONS})")
    return text, index_map


# ------------------------------------------------------------------ box (spec 3.4)
def range_box(points: list[list[float]], margin: float) -> dict[str, Any]:
    """Heavy-atom range plus margin: center = (min + max) / 2, side = (max - min) + 2 * margin.

    Values are rounded to 1e-6 A (``BOX_DECIMALS``). Input coordinates carry 3 (PDB) or 4 (SDF) decimals, so this
    only removes binary floating-point noise (0.7175000000000002 -> 0.7175); the recorded box is then exactly the
    number qvina2 parses (the search is sensitive to the last bit of the box).
    """
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    return {"center_A": [round((low[k] + high[k]) / 2, BOX_DECIMALS) + 0.0 for k in range(3)],
            "size_A": [round((high[k] - low[k]) + 2 * margin, BOX_DECIMALS) + 0.0 for k in range(3)]}


def _inside(point: list[float], box: dict[str, Any]) -> bool:
    return all(box["center_A"][k] - box["size_A"][k] / 2 <= point[k] <= box["center_A"][k] + box["size_A"][k] / 2
               for k in range(3))


def check_box(box: dict[str, Any], receptor_heavy: list[list[float]]) -> None:
    if any(side > K.BOX_SIDE_MAX_A for side in box["size_A"]):
        raise _refuse("box_too_large", f"a box side exceeds {K.BOX_SIDE_MAX_A} A (never shrunk)",
                      size_A=box["size_A"])
    if not all(math.isfinite(x) for x in box["center_A"] + box["size_A"]) or any(s <= 0 for s in box["size_A"]):
        raise _refuse("box_invalid", "box must have finite center and positive sides")
    if not any(_inside(point, box) for point in receptor_heavy):
        raise _refuse("box_no_receptor_atoms", "no receptor heavy atom lies inside the box")


def _heavy_points(mol: Chem.Mol) -> list[list[float]]:
    conf = mol.GetConformer()
    return [list(conf.GetAtomPosition(a.GetIdx())) for a in mol.GetAtoms() if a.GetAtomicNum() > 1]


# ------------------------------------------------------------------ geometry (spec 4.4, 4.5)
def contact_kind(ligand_element: str, receptor_element: str) -> str:
    first, second = ligand_element.upper(), receptor_element.upper()
    if first in POLAR and second in POLAR:
        return "polar_contact"
    if first == "C" and second == "C":
        return "hydrophobic_contact"
    return "contact"


def geometry(pose_atoms: list[dict[str, Any]], receptor_heavy: list[dict[str, Any]], box: dict[str, Any]
             ) -> dict[str, Any]:
    """Contacts (<= 4.0 A, heavy atoms), atoms outside the box and the minimum heavy-atom distance.

    ``pose_atoms``: ``{serial, element, xyz, parent_serial}`` for every pose atom (H included, skipped here);
    ``receptor_heavy``: ``{ref (public AtomRef), xyz}``. Distances are ``math.dist`` on float64 coordinates.
    """
    import numpy as np

    heavy = [atom for atom in pose_atoms if atom["element"] != "H"]
    lig = np.array([atom["xyz"] for atom in heavy], dtype=float)
    rec = np.array([atom["xyz"] for atom in receptor_heavy], dtype=float)
    approx = np.sqrt(((lig[:, None, :] - rec[None, :, :]) ** 2).sum(axis=2))
    outside = sum(not _inside(atom["xyz"], box) for atom in heavy)
    li, ri = np.unravel_index(int(np.argmin(approx)), approx.shape)
    minimum = math.dist(heavy[int(li)]["xyz"], receptor_heavy[int(ri)]["xyz"])
    contacts = []
    for li, ri in zip(*np.nonzero(approx <= K.CONTACT_CUTOFF_A + 1e-6), strict=True):
        ligand, receptor = heavy[int(li)], receptor_heavy[int(ri)]
        distance = math.dist(ligand["xyz"], receptor["xyz"])
        minimum = min(minimum, distance)
        if distance <= K.CONTACT_CUTOFF_A:
            contacts.append({"ligand_serial": ligand["serial"], "ligand_element": ligand["element"],
                             "ligand_parent_serial": ligand["parent_serial"], "receptor_atom": receptor["ref"],
                             "distance_A": distance,
                             "kind": contact_kind(ligand["element"], receptor["ref"]["element"])})
    contacts.sort(key=lambda row: (row["ligand_serial"], row["receptor_atom"]["site_index"]))
    if len(contacts) > K.MAX_CONTACTS_PER_MODE:
        raise DockingWorkerError("resource_exceeded", "resource_exceeded",
                                 f"a mode has {len(contacts)} contacts (cap {K.MAX_CONTACTS_PER_MODE}); "
                                 "rows are never truncated")
    return {"atoms_outside_box": outside, "min_heavy_atom_distance_A": minimum, "contacts": contacts}


def pose_record(mol: Chem.Mol, title: str) -> tuple[str, list[dict[str, Any]]]:
    """V2000 pose text (atom order of ``mol``) and the atoms read back from that text (stored coordinates)."""
    copy = Chem.Mol(mol)
    copy.SetProp("_Name", title)
    text = Chem.MolToMolBlock(copy, forceV3000=False)
    back = Chem.MolFromMolBlock(text, sanitize=False, removeHs=False, strictParsing=True)
    if back is None or back.GetNumAtoms() != mol.GetNumAtoms():
        raise _fatal("engine_output_invalid", "pose SDF does not read back")
    conf = back.GetConformer()
    atoms = [{"serial": i + 1, "element": back.GetAtomWithIdx(i).GetSymbol(), "xyz": list(conf.GetAtomPosition(i)),
              "parent_serial": None} for i in range(back.GetNumAtoms())]
    return text, atoms


# ------------------------------------------------------------------ engine (spec 4.1)
def engine_identity() -> dict[str, Any]:
    if not QVINA.is_file() or not QVINA_RECORD.is_file():
        raise _fatal("engine_failed", "pinned qvina2 or its install record is missing")
    record = json.loads(QVINA_RECORD.read_bytes())
    actual = _file_sha(QVINA)
    if actual != QVINA_SHA256 or record.get("executable", {}).get("sha256") != actual:
        raise _fatal("engine_failed", "qvina2 SHA-256 differs from the pinned value or the install record")
    return {"name": K.ENGINE, "version": record["release"], "binary_sha256": actual,
            "package": f"qvina-{record['release']}-{record['build']}"}


def run_qvina(argv_tail: list[str], workdir: Path) -> subprocess.CompletedProcess:
    """The one engine executable, list arguments, no shell, private cwd. Never ``vina``."""
    try:
        return subprocess.run([str(QVINA), *argv_tail], cwd=workdir, env=ENGINE_ENV, stdin=subprocess.DEVNULL,
                              capture_output=True, check=False)
    except OSError as exc:
        raise _fatal("engine_failed", f"qvina2 could not start ({type(exc).__name__})") from exc


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


def _number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite engine value")
    return value


def parse_score_only(text: str) -> float:
    """The one ``Affinity: <value> (kcal/mol)`` line of ``qvina2 --score_only``: a finite decimal (exponent allowed).

    No line, several lines, a malformed number, nan, inf or an overflowing value is ``engine_output_invalid``.
    """
    found = SCORE_ONLY_RE.findall(text)
    if len(found) != 1:
        raise _fatal("engine_output_invalid", "qvina2 --score_only printed no single score line")
    if SCORE_NUMBER_RE.fullmatch(found[0]) is None:
        raise _fatal("engine_output_invalid", "malformed --score_only value")
    try:
        return _number(found[0])
    except ValueError as exc:
        raise _fatal("engine_output_invalid", "nonfinite --score_only value") from exc


def parse_modes(text: str, ligand_text: str) -> list[dict[str, Any]]:
    """qvina ``--out`` models: score, RMSD bounds and coordinates by PDBQT atom number, lines checked against input."""
    template = [line for line in ligand_text.splitlines() if line.startswith(("ATOM", "HETATM"))]
    modes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    try:
        for line in text.splitlines():
            if line.startswith("MODEL"):
                if current is not None or int(line.split()[1]) != len(modes) + 1:
                    raise ValueError("unexpected MODEL record")
                current = {"result": None, "lines": []}
            elif line.startswith("ENDMDL"):
                if current is None or current["result"] is None:
                    raise ValueError("model without VINA RESULT")
                modes.append(current)
                current = None
            elif current is not None and line.startswith("REMARK VINA RESULT:"):
                match = VINA_RESULT_RE.match(line)
                if match is None or current["result"] is not None:
                    raise ValueError("malformed VINA RESULT")
                current["result"] = [_number(x) for x in match.groups()]
            elif current is not None and line.startswith(("ATOM", "HETATM")):
                current["lines"].append(line)
        if current is not None:
            raise ValueError("unterminated MODEL")
        parsed = []
        for mode in modes:
            if len(mode["lines"]) != len(template) or any(
                    a[:30] + a[54:] != b[:30] + b[54:] for a, b in zip(mode["lines"], template, strict=True)):
                raise ValueError("model atoms differ from the input ligand PDBQT")
            coords = {int(line[6:11]): [_number(line[30:38]), _number(line[38:46]), _number(line[46:54])]
                      for line in mode["lines"]}
            score, lower, upper = mode["result"]
            parsed.append({"score": score, "rmsd_lb": lower, "rmsd_ub": upper, "coords": coords})
    except (ValueError, IndexError) as exc:
        raise _fatal("engine_output_invalid", f"qvina output cannot be read: {exc}"[:200]) from exc
    return parsed


def restore_pose(mol: Chem.Mol, index_map: dict[int, int], coords: dict[int, list[float]]) -> Chem.Mol:
    """Pose in input atom order. Atoms written to the PDBQT take the engine coordinates; nonpolar H merged by Meeko
    are re-placed by RDKit ``AddHs(addCoords=True)`` on their parent (Meeko's own restoration), matched by parent."""
    try:
        merged = sorted(i for i in range(mol.GetNumAtoms()) if i not in index_map)
        keep = [i for i in range(mol.GetNumAtoms()) if i in index_map]
        new_of = {old: new for new, old in enumerate(keep)}
        rw = Chem.RWMol(mol)
        for index in reversed(merged):
            rw.RemoveAtom(index)
        by_parent: dict[int, list[int]] = {}
        for index in merged:
            by_parent.setdefault(new_of[mol.GetAtomWithIdx(index).GetNeighbors()[0].GetIdx()], []).append(index)
        for parent, hydrogens in by_parent.items():
            atom = rw.GetAtomWithIdx(parent)
            atom.SetNumExplicitHs(len(hydrogens))
            atom.SetNoImplicit(True)
        stripped = rw.GetMol()
        stripped.RemoveAllConformers()
        conf = Chem.Conformer(stripped.GetNumAtoms())
        for old, new in new_of.items():
            conf.SetAtomPosition(new, Point3D(*coords[index_map[old]]))
        conf.Set3D(True)
        stripped.AddConformer(conf, assignId=True)
        Chem.SanitizeMol(stripped)
        full = Chem.AddHs(stripped, addCoords=True)
        placed = full.GetConformer()
        out = Chem.Conformer(mol.GetNumAtoms())
        for old, new in new_of.items():
            out.SetAtomPosition(old, placed.GetAtomPosition(new))
        for parent, hydrogens in by_parent.items():
            added = sorted(n.GetIdx() for n in full.GetAtomWithIdx(parent).GetNeighbors()
                           if n.GetIdx() >= stripped.GetNumAtoms())
            if len(added) != len(hydrogens):
                raise ValueError("restored hydrogen count differs")
            for original, new in zip(hydrogens, added, strict=True):
                out.SetAtomPosition(original, placed.GetAtomPosition(new))
        if full.GetNumAtoms() != mol.GetNumAtoms():
            raise ValueError("restored atom count differs")
    except (ValueError, RuntimeError, KeyError, IndexError) as exc:
        raise _fatal("engine_output_invalid", f"pose cannot be restored in input atom order ({exc})"[:200]) from exc
    pose = Chem.Mol(mol)
    pose.RemoveAllConformers()
    out.Set3D(True)
    pose.AddConformer(out, assignId=True)
    return pose


# ------------------------------------------------------------------ core-fixed sampling (spec 4.3)
def core_match(parent: Chem.Mol, heavy: Chem.Mol, retained: Any) -> dict[int, int]:
    """Candidate heavy-atom index -> parent atom index for the retained core (refusing failed or ambiguous matches).

    Two matches are the same placement when the sets of (candidate symmetry class, parent serial) pairs are equal,
    i.e. they differ only by a core self-symmetry that the candidate shares (a phenyl flip); then the first is used.
    """
    serial_to_idx = {atom.GetIntProp(SERIAL): atom.GetIdx() for atom in parent.GetAtoms() if atom.GetAtomicNum() > 1}
    if (type(retained) is not list or not retained or any(type(x) is not int for x in retained) or
            len(set(retained)) != len(retained) or any(x not in serial_to_idx for x in retained)):
        raise _refuse("core_match_failed", "retained_parent_atoms are not heavy-atom serials of the parent SDF")
    core = Chem.RWMol(Chem.Mol(parent))
    for index in sorted((a.GetIdx() for a in parent.GetAtoms() if a.GetIntProp(SERIAL) not in set(retained)),
                        reverse=True):
        core.RemoveAtom(index)
    core = core.GetMol()
    matches = heavy.GetSubstructMatches(core, useChirality=False, uniquify=False, maxMatches=MAX_MATCHES)
    if not matches:
        raise _refuse("core_match_failed", "the parent core subgraph does not occur in the candidate")
    if len(matches) >= MAX_MATCHES:
        raise _refuse("core_match_ambiguous", "too many core matches to show they give one placement")
    ranks = list(Chem.CanonicalRankAtoms(heavy, breakTies=False))
    serials = [core.GetAtomWithIdx(i).GetIntProp(SERIAL) for i in range(core.GetNumAtoms())]
    placements = {frozenset((ranks[m[i]], serials[i]) for i in range(len(serials))) for m in matches}
    if len(placements) > 1:
        raise _refuse("core_match_ambiguous", "the core matches the candidate in more than one placement",
                      placements=len(placements))
    return {matches[0][i]: serial_to_idx[serials[i]] for i in range(len(serials))}


def core_samples(heavy: Chem.Mol, parent: Chem.Mol, mapping: dict[int, int], count: int, seed: int
                 ) -> tuple[Chem.Mol, list[int]]:
    """``count`` coordMap ETKDG conformers (seed fixed, no force field), each aligned on the core and with the core
    heavy atoms overwritten by the parent coordinates."""
    mol = Chem.AddHs(heavy)
    pconf = parent.GetConformer()
    cmap = {cand: Point3D(*pconf.GetAtomPosition(par)) for cand, par in mapping.items()}
    try:
        cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=count, randomSeed=seed, coordMap=cmap))
    except (ValueError, RuntimeError):
        cids = []
    if not cids:
        raise _refuse("embed_failed", "no core-restrained conformer could be embedded")
    pairs = sorted(mapping.items())
    for cid in cids:
        rdMolAlign.AlignMol(mol, parent, prbCid=cid, atomMap=pairs)
        conf = mol.GetConformer(cid)
        for cand, par in pairs:
            conf.SetAtomPosition(cand, pconf.GetAtomPosition(par))
    return mol, cids


def _single(mol: Chem.Mol, cid: int) -> Chem.Mol:
    out = Chem.Mol(mol)
    out.RemoveAllConformers()
    conf = Chem.Conformer(mol.GetConformer(cid))
    conf.Set3D(True)
    out.AddConformer(conf, assignId=True)
    return out


# ------------------------------------------------------------------ staged input
def _entry(entry: Any) -> bytes:
    if (type(entry) is not dict or set(entry) != {"b64", "sha256"} or type(entry["b64"]) is not str or
            type(entry["sha256"]) is not str or not SHA_RE.fullmatch(entry["sha256"])):
        raise _malformed("byte entry")
    try:
        raw = base64.b64decode(entry["b64"], validate=True)
    except ValueError as exc:
        raise _malformed("bytes are not base64") from exc
    if not 0 < len(raw) <= MAX_ENTRY_BYTES or _sha(raw) != entry["sha256"]:
        raise _malformed("bytes exceed the cap or do not match their SHA-256")
    return raw


def _validate_payload(p: Any) -> None:
    ok = (type(p) is dict and set(p) == {"schema", "receptor", "ligand", "mode", "box", "parameters"} and
          p["schema"] == "docking_worker_input@1" and p["mode"] in K.MODES)
    receptor = p.get("receptor") if ok else None
    ok = ok and type(receptor) is dict and set(receptor) == {"handle", "format", "bytes", "model_number",
                                                             "connectivity", "instance"}
    ok = ok and type(receptor["handle"]) is str and receptor["format"] in ("pdb", "cif") and \
        type(receptor["model_number"]) is int and receptor["model_number"] >= 1 and \
        (receptor["instance"] is None or _residue_fields_ok(receptor["instance"]))
    connectivity = receptor.get("connectivity") if ok else None
    ok = ok and type(connectivity) is dict and set(connectivity) == {"kind", "sidecar"} and \
        connectivity["kind"] in K.CONNECTIVITY_KINDS and \
        (connectivity["sidecar"] is None) == (connectivity["kind"] == "pdb_conect")
    ligand = p.get("ligand") if ok else None
    ok = ok and type(ligand) is dict and (
        (ligand.get("source") == "sdf" and set(ligand) == {"source", "sdf"}) or
        (ligand.get("source") == "candidate" and
         set(ligand) == {"source", "parent_sdf", "candidate_set_parent_sha256", "candidate"} and
         type(ligand["candidate_set_parent_sha256"]) is str and type(ligand["candidate"]) is dict and
         set(ligand["candidate"]) == {"id", "smiles", "retained_parent_atoms", "stereo_flag"} and
         type(ligand["candidate"]["id"]) is str and type(ligand["candidate"]["stereo_flag"]) is str))
    ok = ok and not (p["mode"] == "core_fixed" and ligand["source"] != "candidate")
    box = p.get("box") if ok else None
    ok = ok and type(box) is dict and (
        (box.get("source") in ("ligand_range", "instance_range") and set(box) == {"source", "margin_A"} and
         type(box["margin_A"]) in (int, float) and K.MARGIN_MIN_A <= box["margin_A"] <= K.MARGIN_MAX_A) or
        (box.get("source") == "manual" and set(box) == {"source", "center_A", "size_A"} and
         all(type(v) is list and len(v) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in v)
             for v in (box["center_A"], box["size_A"]))))
    params = p.get("parameters") if ok else None

    def bounded(value: Any, low: int, high: int) -> bool:
        return type(value) is int and low <= value <= high

    ok = ok and type(params) is dict and \
        set(params) == {"seed", "exhaustiveness", "num_modes", "energy_range", "conformers"} and \
        bounded(params["seed"], K.SEED_MIN, K.SEED_MAX) and \
        bounded(params["exhaustiveness"], K.EXHAUSTIVENESS_MIN, K.EXHAUSTIVENESS_MAX) and \
        bounded(params["num_modes"], K.NUM_MODES_MIN, K.NUM_MODES_MAX) and \
        type(params["energy_range"]) in (int, float) and \
        K.ENERGY_RANGE_MIN <= params["energy_range"] <= K.ENERGY_RANGE_MAX and \
        ((p["mode"] == "free" and params["conformers"] is None) or
         (p["mode"] == "core_fixed" and bounded(params["conformers"], K.CONFORMERS_MIN, K.CONFORMERS_MAX)))
    if not ok:
        raise _malformed("payload shape")


# ------------------------------------------------------------------ job
def dock(p: dict[str, Any], workdir: Path) -> dict[str, Any]:
    _validate_payload(p)
    rec, lig, mode, box_req, params = p["receptor"], p["ligand"], p["mode"], p["box"], p["parameters"]
    rec_raw = _entry(rec["bytes"])
    sidecar_raw = None if rec["connectivity"]["sidecar"] is None else _entry(rec["connectivity"]["sidecar"])
    receptor = check_receptor(rec_raw, rec["format"], rec["handle"], rec["model_number"], rec["connectivity"],
                              rec["instance"], sidecar_raw)
    rows, kept = receptor["rows"], receptor["kept"]
    receptor_heavy = [{"ref": _public_ref(row), "xyz": row["coordinate_A"]} for row in kept
                      if row["element"].upper() != "H"]

    # ligand inputs and the box reference points (cheap checks before any chemistry inference)
    parent = mol = heavy = None
    sdf_raw = parent_raw = None
    candidate = lig.get("candidate")
    if lig["source"] == "sdf":
        sdf_raw = _entry(lig["sdf"])
        mol = read_sdf(sdf_raw)
        unspecified = None
    else:
        parent_raw = _entry(lig["parent_sdf"])
        if _sha(parent_raw) != lig["candidate_set_parent_sha256"]:
            raise _refuse("parent_mismatch", "parent SDF SHA-256 differs from the candidate set's parent_sha256")
        heavy = candidate_heavy(candidate["smiles"])
        unspecified = unspecified_stereo(heavy)
        if mode == "core_fixed" or box_req["source"] == "ligand_range":
            parent = read_sdf(parent_raw, parent=True)
            if _planar(parent):
                raise _refuse("parent_not_3d", "every parent atom has the same z coordinate (planar input)")
    if box_req["source"] == "manual":
        box = {"center_A": [float(x) + 0.0 for x in box_req["center_A"]],
               "size_A": [float(x) + 0.0 for x in box_req["size_A"]]}
    elif box_req["source"] == "instance_range":
        if not receptor["instance_sites"]:
            raise _refuse("box_invalid", "instance_range needs a receptor_instance")
        box = range_box([rows[s]["coordinate_A"] for s in receptor["instance_sites"]
                         if rows[s]["element"].upper() != "H"] or
                        [rows[s]["coordinate_A"] for s in receptor["instance_sites"]], float(box_req["margin_A"]))
    else:
        box = range_box(_heavy_points(mol if lig["source"] == "sdf" else parent), float(box_req["margin_A"]))
    check_box(box, [atom["xyz"] for atom in receptor_heavy])
    mapping = core_match(parent, heavy, candidate["retained_parent_atoms"]) if mode == "core_fixed" else None

    receptor_text = receptor_pdbqt(kept, receptor_graph(kept, receptor["kept_bonds"]))
    engine = engine_identity()
    _write_private(workdir / "receptor.pdbqt", receptor_text)

    if mode == "free":
        if lig["source"] == "candidate":
            mol = Chem.AddHs(heavy)
            if AllChem.EmbedMolecule(mol, randomSeed=params["seed"]) != 0:
                raise _refuse("embed_failed", "RDKit could not embed a starting conformer for the candidate")
        if not _explicit_only(mol):
            raise _refuse("ligand_hydrogens_missing", "ligand atoms carry implicit hydrogens")
        ligand_text, index_map = ligand_pdbqt(mol)
        _write_private(workdir / "ligand.pdbqt", ligand_text)
        argv = ["--receptor", "receptor.pdbqt", "--ligand", "ligand.pdbqt",
                "--center_x", repr(box["center_A"][0]), "--center_y", repr(box["center_A"][1]),
                "--center_z", repr(box["center_A"][2]), "--size_x", repr(box["size_A"][0]),
                "--size_y", repr(box["size_A"][1]), "--size_z", repr(box["size_A"][2]),
                "--out", "out.pdbqt", "--cpu", str(K.CPU), "--seed", str(params["seed"]),
                "--exhaustiveness", str(params["exhaustiveness"]), "--num_modes", str(params["num_modes"]),
                "--energy_range", repr(float(params["energy_range"]))]
        proc = run_qvina(argv, workdir)
        if proc.returncode != 0:
            raise _fatal("engine_failed", f"qvina2 exited {proc.returncode}")
        out_path = workdir / "out.pdbqt"
        if out_path.is_symlink() or not out_path.is_file():
            raise _fatal("engine_output_invalid", "qvina2 wrote no output file")
        parsed = parse_modes(out_path.read_text(encoding="utf-8"), ligand_text)
        if len(parsed) > params["num_modes"]:
            raise _fatal("engine_output_invalid", "qvina2 returned more modes than requested")
        modes = []
        for number, item in enumerate(parsed, start=1):
            text, atoms = pose_record(restore_pose(mol, index_map, item["coords"]), f"mode_{number}")
            modes.append({"mode": number, "score_kcal_mol": item["score"], "engine_rmsd_lb_A": item["rmsd_lb"],
                          "engine_rmsd_ub_A": item["rmsd_ub"], "conformer_index": None,
                          "core_max_deviation_A": None, "pose_sdf": text,
                          **geometry(atoms, receptor_heavy, box)})
        samples = (None, None)
    else:
        mol, cids = core_samples(heavy, parent, mapping, params["conformers"], params["seed"])
        if not _explicit_only(mol):
            raise _refuse("ligand_hydrogens_missing", "candidate atoms carry implicit hydrogens")
        scored = []
        for position, cid in enumerate(cids):
            sample = _single(mol, cid)
            ligand_text, _index_map = ligand_pdbqt(sample)
            name = f"sample_{position}.pdbqt"
            _write_private(workdir / name, ligand_text)
            proc = run_qvina(["--receptor", "receptor.pdbqt", "--ligand", name, "--score_only",
                              "--cpu", str(K.CPU)], workdir)
            if proc.returncode != 0:
                raise _fatal("engine_failed", f"qvina2 --score_only exited {proc.returncode}")
            scored.append((parse_score_only(proc.stdout.decode("utf-8", "replace")), position, sample))
        scored.sort(key=lambda item: (item[0], item[1]))
        pconf = parent.GetConformer()
        modes = []
        for number, (score, position, sample) in enumerate(scored[:params["num_modes"]], start=1):
            text, atoms = pose_record(sample, f"mode_{number}")
            for cand, par in mapping.items():
                atoms[cand]["parent_serial"] = parent.GetAtomWithIdx(par).GetIntProp(SERIAL)
            deviation = max(math.dist(atoms[cand]["xyz"], list(pconf.GetAtomPosition(par)))
                            for cand, par in mapping.items())
            modes.append({"mode": number, "score_kcal_mol": score, "engine_rmsd_lb_A": None,
                          "engine_rmsd_ub_A": None, "conformer_index": position,
                          "core_max_deviation_A": deviation, "pose_sdf": text,
                          **geometry(atoms, receptor_heavy, box)})
        samples = (len(cids), len(scored))

    removed = receptor["removed_instance"]
    candidate_source = lig["source"] == "candidate"
    return {
        "schema": "docking_worker_output@1", "protocol": K.PROTOCOL, "method": K.METHODS[mode],
        "inputs": {
            "receptor": {"sha256": _sha(rec_raw), "format": rec["format"], "model_number": rec["model_number"],
                         "atom_count": len(rows),
                         "connectivity": {"kind": rec["connectivity"]["kind"],
                                          "sidecar_sha256": None if sidecar_raw is None else _sha(sidecar_raw)},
                         "removed_instance": removed},
            "ligand": {"source": lig["source"], "sdf_sha256": None if sdf_raw is None else _sha(sdf_raw),
                       "parent_sdf_sha256": _sha(parent_raw) if candidate_source else None,
                       "candidate_id": candidate["id"] if candidate_source else None,
                       "generated": {"hydrogens": candidate_source, "coordinates": candidate_source},
                       "stereo_flag": candidate["stereo_flag"] if candidate_source else None,
                       "unspecified_stereo_centers": unspecified},
            "mode": mode},
        "box": {"center_A": box["center_A"], "size_A": box["size_A"], "source": box_req["source"],
                "margin_A": None if box_req["source"] == "manual" else float(box_req["margin_A"]) + 0.0},
        "parameters": {"seed": params["seed"], "exhaustiveness": params["exhaustiveness"],
                       "num_modes": params["num_modes"], "energy_range": float(params["energy_range"]) + 0.0,
                       "conformers": params["conformers"], "cpu": K.CPU},
        "engine": engine,
        "preparation": {"tool": "Meeko", "version": meeko.__version__, "rdkit_version": rdBase.rdkitVersion,
                        "atom_typing": "ad4", "charges": "gasteiger"},
        "modes": modes,
        "counts": {"modes": len(modes), "contacts_by_mode": [len(m["contacts"]) for m in modes],
                   "null_result": not modes, "samples_generated": samples[0], "samples_scored": samples[1]},
        "limitations": list(K.applicable_limitations(mode=mode, source=lig["source"],
                                                     removed_instance=removed is not None,
                                                     unspecified_stereo_centers=unspecified)),
    }


# ------------------------------------------------------------------ entry points
def versions() -> dict[str, str]:
    return {"meeko": meeko.__version__, "rdkit": rdBase.rdkitVersion, "MDAnalysis": mda.__version__,
            "gemmi": gemmi.__version__}


def handshake() -> dict[str, Any]:
    """Versions and the engine file check; nothing is computed and qvina2 is not executed."""
    present = QVINA.is_file()
    actual = _file_sha(QVINA) if present else None
    try:
        record = json.loads(QVINA_RECORD.read_bytes())
        recorded = record["executable"]["sha256"]
        package = f"qvina-{record['release']}-{record['build']}"
    except (OSError, ValueError, KeyError, TypeError):
        recorded = package = None
    return {"schema": "docking_worker_handshake@1", "protocols": [ADAPTER], "versions": versions(),
            "versions_expected": dict(PINNED),
            "engine": {"name": K.ENGINE, "present": present, "binary_sha256": actual, "record_sha256": recorded,
                       "pinned_sha256": QVINA_SHA256, "package": package,
                       "hash_match": present and actual == recorded == QVINA_SHA256},
            "worker_sha256": _sha(Path(__file__).read_bytes()), "python": sys.version.split()[0]}


def _read_bounded(name: str, limit: int) -> bytes:
    path = Path(name)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise _malformed(f"{name} missing or over its bound")
    return path.read_bytes()


def run_job() -> dict[str, Any]:
    if versions() != PINNED:
        raise _fatal("engine_failed", "pinned Meeko/RDKit/MDAnalysis/gemmi versions unavailable")
    try:
        control = json.loads(_read_bounded("input.json", 4096))
        raw = _read_bounded("structure.json", MAX_STAGED_BYTES)
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _malformed("staged JSON unreadable") from exc
    if (type(control) is not dict or control.get("adapter") != ADAPTER or
            type(control.get("input_sha256")) is not str or _sha(raw) != control["input_sha256"] or
            any(type(control.get(key)) is not str or not CONTROL_ID_RE.fullmatch(control[key])
                for key in ("job_id", "attempt_id"))):
        raise _malformed("control record or staged hash mismatch")
    workdir = Path("qvina_work")
    os.mkdir(workdir, 0o700)
    try:
        output = dock(payload, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {**output, "job_id": control["job_id"], "attempt_id": control["attempt_id"]}


def main(argv: list[str]) -> int:
    if argv == ["--handshake"]:
        sys.stdout.write(json.dumps(handshake(), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    if argv:
        return 2
    output = canonical_json(run_job())
    if not 0 < len(output) <= K.MAX_RESULT_BYTES:
        raise DockingWorkerError("resource_exceeded", "resource_exceeded",
                                 f"result is {len(output)} bytes (limit {K.MAX_RESULT_BYTES}); never truncated")
    fd = os.open("result.tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(output)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace("result.tmp", "result.json")
    return 0


def _write_error(envelope: dict[str, Any]) -> None:
    Path("error.json").write_bytes(canonical_json(envelope))


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except DockingWorkerError as exc:
        _write_error(exc.envelope())
        raise SystemExit(1) from None
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError,
            MemoryError, RecursionError) as exc:
        _write_error({"schema": "docking_worker_error@1", "error_class": "fatal", "reason_code": "engine_failed",
                      "message": f"docking worker internal error ({type(exc).__name__})"[:240], "detail": {}})
        raise SystemExit(1) from None
