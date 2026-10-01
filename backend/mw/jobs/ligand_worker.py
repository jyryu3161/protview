"""Fixed, isolated RDKit 2026.03.6 worker for M17 ligand candidates. JSON files only (spec 3--6).

The guardian launches this script with the pinned ``.deps/prolif/venv-locked`` interpreter; RDKit is
imported here and nowhere in the server. The only ``mw`` code used is ``mw/ligand_constants.py``, loaded by
file path (standard library only, no package import), so closed reason sets, caps and the fixed limitation
sentences have one copy.

Job mode (no arguments, cwd = private attempt directory): ``input.json`` is the control record
(``adapter`` = ``rdkit_inspect_v1`` | ``rdkit_enumerate_v1``, ``input_sha256`` of ``structure.json``,
``job_id`` and ``attempt_id`` echoed into the output; other control keys are ignored). ``structure.json`` is
the canonical staged payload:

    inspect:   {"schema": "ligand_inspect_worker_input@1",
                "parent": {"sdf_b64": str, "sha256": str},
                "blocks": [{"kind": "building_blocks_sdf" | "building_blocks_smiles", "b64": str, "sha256": str}],
                "rules":  [str, ...]}                                   # request order -> user_<n>
    enumerate: {"schema": "ligand_enumerate_worker_input@1", "parent": ..., "blocks": ...,  # same bytes again
                "site_atoms": [int, ...], "use_fixed": bool,
                "rules": [{"rule_id": "user_<n>", "text": str}, ...],   # only rules inspected as valid
                "limits": {"max_candidates": int, "max_attempts": int}}

Success writes canonical ``result.json`` (``ligand_inspect_worker_output@1`` / ``ligand_enumerate_worker_output@1``)
and exits 0. Any refusal writes a small ``error.json`` (``ligand_worker_error@1``: ``error_class`` input_invalid
| resource_exceeded | fatal, ``reason_code``, ``message``) and exits 1 with no result. Results are a pure
function of the staged bytes, the echoed control identity and the RDKit version (no time, seed or
randomness); a stop on the candidate
or attempt cap is the only partial result. Wall-clock time and cancellation are enforced by the caller.

Handshake mode (``--handshake``): print versions and PAINS catalog sizes; nothing is computed.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any


def _deny_network() -> None:
    """Deny Python socket egress before importing native chemistry (defense in depth, as chemical_worker)."""
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("external network is disabled for the ligand worker")

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

from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import Crippen, Descriptors, rdChemReactions, rdDepictor, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

RDLogger.DisableLog("rdApp.*")  # parse failures are reported as reason codes; keep stderr bounded


def _load_constants() -> Any:
    path = Path(__file__).resolve().parents[1] / "ligand_constants.py"
    spec = importlib.util.spec_from_file_location("ligand_constants_pinned", path)
    if spec is None or spec.loader is None:
        raise ImportError("pinned ligand constants unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _load_constants()

RDKIT_VERSION = "2026.03.6"
INSPECT = "rdkit_inspect_v1"
ENUMERATE = "rdkit_enumerate_v1"
MAX_STAGED_BYTES = 48 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_SVG_BYTES = 256 * 1024
SVG_SIZE = (900, 700)
SERIAL = "sdf_serial"
ALLOWED_ATOMIC_NUMBERS = frozenset(Chem.GetPeriodicTable().GetAtomicNumber(s) for s in K.ALLOWED_ELEMENTS)
BOND_NAMES = {Chem.BondType.SINGLE: "single", Chem.BondType.DOUBLE: "double",
              Chem.BondType.TRIPLE: "triple", Chem.BondType.AROMATIC: "aromatic"}
PAINS_CATALOGS = (("PAINS_A", FilterCatalogParams.FilterCatalogs.PAINS_A),
                  ("PAINS_B", FilterCatalogParams.FilterCatalogs.PAINS_B),
                  ("PAINS_C", FilterCatalogParams.FilterCatalogs.PAINS_C))
PROPERTY_METHODS = {"mol_weight": "rdkit Descriptors.MolWt (average, Da)",
                    "crippen_logp": "rdkit Crippen.MolLogP (Wildman-Crippen estimate)",
                    "hbd": "rdkit CalcNumLipinskiHBD", "hba": "rdkit CalcNumLipinskiHBA",
                    "tpsa": "rdkit CalcTPSA (A^2, includeSandP=False)",
                    "rotatable_bonds": "rdkit CalcNumRotatableBonds (default = Strict)",
                    "heavy_atoms": "rdkit GetNumHeavyAtoms", "formal_charge": "rdkit GetFormalCharge (sum)"}
SHA_RE = re.compile(r"[0-9a-f]{64}")
RULE_ID_RE = re.compile(r"user_([1-9][0-9]*)")
CONTROL_ID_RE = re.compile(r"[a-z0-9_]{1,100}")
CHIRAL_TAGS = (Chem.ChiralType.CHI_TETRAHEDRAL_CW, Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
STEREO_BONDS = (Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOZ,
                Chem.BondStereo.STEREOCIS, Chem.BondStereo.STEREOTRANS)


class LigandWorkerError(Exception):
    def __init__(self, error_class: str, reason_code: str, message: str):
        super().__init__(message)
        self.error_class = error_class
        self.reason_code = reason_code

    def envelope(self) -> dict[str, Any]:
        return {"schema": "ligand_worker_error@1", "error_class": self.error_class,
                "reason_code": self.reason_code, "message": str(self)[:240]}


def _input_invalid(reason: str, message: str) -> LigandWorkerError:
    return LigandWorkerError("input_invalid", reason, message)


def _malformed(message: str) -> LigandWorkerError:
    return LigandWorkerError("fatal", "staged_input_invalid", message)


def canonical_json(value: Any) -> bytes:
    """Byte-identical to ``mw.core.handles.canonical_json``."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------ record splitting (same rules as mw.ligand_inputs)
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


def _is_v3000(record: str) -> bool:
    lines = record.splitlines()
    return len(lines) < 4 or "V3000" in lines[3]


# ------------------------------------------------------------------ shared chemistry
def _canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)


def properties(mol: Chem.Mol) -> dict[str, Any]:
    return {"mol_weight": Descriptors.MolWt(mol), "crippen_logp": Crippen.MolLogP(mol),
            "hbd": rdMolDescriptors.CalcNumLipinskiHBD(mol), "hba": rdMolDescriptors.CalcNumLipinskiHBA(mol),
            "tpsa": rdMolDescriptors.CalcTPSA(mol), "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(mol),
            "heavy_atoms": mol.GetNumHeavyAtoms(), "formal_charge": Chem.GetFormalCharge(mol)}


_PAINS: list[tuple[str, Any]] = []


def pains(mol: Chem.Mol) -> dict[str, Any]:
    if not _PAINS:
        for name, which in PAINS_CATALOGS:
            params = FilterCatalogParams()
            params.AddCatalog(which)
            _PAINS.append((name, FilterCatalog(params)))
    matches = []
    for name, catalog in _PAINS:
        matches += [{"catalog": name, "name": entry}
                    for entry in sorted({match.GetDescription() for match in catalog.GetMatches(mol)})]
    return {"matches": matches}


def _from_smiles_properties(smiles: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Properties and PAINS are a function of the stored SMILES (identical rows for identical SMILES)."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return properties(mol), pains(mol)


def _clear_maps(mol: Chem.Mol) -> None:
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)


# ------------------------------------------------------------------ parent (spec 3.2)
class Parent:
    def __init__(self, full: Chem.Mol, heavy: Chem.Mol):
        self.full = full
        self.heavy = heavy
        self.serial = [atom.GetIntProp(SERIAL) for atom in heavy.GetAtoms()]
        self.index = {serial: idx for idx, serial in enumerate(self.serial)}


def _decode(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        return None


def read_parent(raw: bytes) -> Parent:
    def reject(reason: str) -> LigandWorkerError:
        return _input_invalid(reason, f"parent ligand rejected: {reason}")

    text = _decode(raw)
    if text is None or "\x00" in text:
        raise reject("unparseable")
    records = split_sdf_records(text)
    if len(records) != 1:
        raise reject("record_count")
    if _is_v3000(records[0]):
        raise reject("unparseable")
    try:
        full = Chem.MolFromMolBlock(records[0] + "\n", sanitize=True, removeHs=False, strictParsing=True)
    except (ValueError, RuntimeError):
        full = None
    if full is None or full.GetNumAtoms() == 0:
        raise reject("unparseable")
    for atom in full.GetAtoms():
        atom.SetIntProp(SERIAL, atom.GetIdx() + 1)
    if len(Chem.GetMolFrags(full)) != 1:
        raise reject("multiple_fragments")
    if any(atom.GetAtomicNum() not in ALLOWED_ATOMIC_NUMBERS for atom in full.GetAtoms()):
        raise reject("element_not_allowed")
    for atom in full.GetAtoms():
        if atom.GetAtomicNum() == 1 and (atom.GetDegree() != 1 or atom.GetNeighbors()[0].GetAtomicNum() == 1):
            raise reject("unparseable")
    heavy_count = sum(atom.GetAtomicNum() > 1 for atom in full.GetAtoms())
    if heavy_count == 0:
        raise reject("unparseable")
    if heavy_count > K.MAX_PARENT_HEAVY_ATOMS:
        raise reject("too_many_atoms")
    try:
        heavy = Chem.RemoveAllHs(full)
    except (ValueError, RuntimeError) as exc:
        raise reject("unparseable") from exc
    if (heavy.GetNumAtoms() != heavy_count or any(atom.GetAtomicNum() == 1 for atom in heavy.GetAtoms()) or
            any(bond.GetBondType() not in BOND_NAMES for bond in heavy.GetBonds())):
        raise reject("unparseable")
    _clear_maps(heavy)
    Chem.AssignStereochemistry(heavy, cleanIt=True, force=True)
    return Parent(full, heavy)


def parent_graph(parent: Parent) -> dict[str, Any]:
    """Atom table, bond list and H list in the exact ``mw.ligand_site`` input schema (SDF serials)."""
    atoms = []
    for idx, atom in enumerate(parent.heavy.GetAtoms()):
        atoms.append({"serial": parent.serial[idx], "element": atom.GetSymbol(),
                      "formal_charge": atom.GetFormalCharge(),
                      "neighbors": sorted(parent.serial[n.GetIdx()] for n in atom.GetNeighbors())})
    atoms.sort(key=lambda row: row["serial"])
    bonds = []
    for bond in parent.heavy.GetBonds():
        a, b = sorted((parent.serial[bond.GetBeginAtomIdx()], parent.serial[bond.GetEndAtomIdx()]))
        bonds.append({"a": a, "b": b, "order": BOND_NAMES[bond.GetBondType()]})
    bonds.sort(key=lambda row: (row["a"], row["b"]))
    hydrogens = sorted(({"serial": atom.GetIdx() + 1, "attached_to": atom.GetNeighbors()[0].GetIdx() + 1}
                        for atom in parent.full.GetAtoms() if atom.GetAtomicNum() == 1),
                       key=lambda row: row["serial"])
    return {"atoms": atoms, "bonds": bonds, "hydrogens": hydrogens}


def parent_svg(parent: Parent) -> str:
    mol = Chem.Mol(parent.heavy)
    for idx, atom in enumerate(mol.GetAtoms()):
        atom.SetProp("atomNote", str(parent.serial[idx]))
    rdDepictor.Compute2DCoords(mol)
    # noFreetype: notes and labels are <text> elements, about half the bytes of glyph paths (T1 preflight).
    drawer = rdMolDraw2D.MolDraw2DSVG(SVG_SIZE[0], SVG_SIZE[1], -1, -1, True)
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
        raise LigandWorkerError("resource_exceeded", "svg_limit", "numbered 2D drawing exceeds 256 KiB")
    return svg


# ------------------------------------------------------------------ building blocks (spec 3.3)
class Block:
    def __init__(self, name: str, mol: Chem.Mol, marker: int | None, fixed: bool, markers: int):
        self.name = name
        self.mol = mol
        self.marker = marker
        self.fixed = fixed
        self.markers = markers


def _parse_block(kind: str, record: str) -> tuple[str | None, Chem.Mol | None, str | None]:
    """Return (name or None, mol, reason or None) for one record; checks in the fixed reason order."""
    if kind == "building_blocks_sdf":
        name = record.splitlines()[0].strip() if record.splitlines() else ""
        mol = None
        if not _is_v3000(record):
            try:
                mol = Chem.MolFromMolBlock(record + "\n", sanitize=True, removeHs=True, strictParsing=True)
            except (ValueError, RuntimeError):
                mol = None
    else:
        tokens = record.split()
        name = tokens[1] if len(tokens) > 1 else ""
        try:
            mol = Chem.MolFromSmiles(tokens[0])
        except (ValueError, RuntimeError):
            mol = None
    name = name or None
    if name is not None and len(name) > K.MAX_BLOCK_NAME_CHARS:
        return None, None, "unparseable"  # an over-long name is not a name: the record gets block_<n>
    if mol is None:
        return name, None, "unparseable"
    if not any(atom.GetAtomicNum() > 0 for atom in mol.GetAtoms()):
        return name, mol, "empty"
    if len(Chem.GetMolFrags(mol)) != 1:
        return name, mol, "multiple_fragments"
    if any(atom.GetAtomicNum() != 0 and atom.GetAtomicNum() not in ALLOWED_ATOMIC_NUMBERS
           for atom in mol.GetAtoms()):
        return name, mol, "element_not_allowed"
    if sum(atom.GetAtomicNum() > 1 for atom in mol.GetAtoms()) > K.MAX_BLOCK_HEAVY_ATOMS:
        return name, mol, "too_many_atoms"
    return name, mol, None


def _marker_info(mol: Chem.Mol) -> tuple[int, int | None, bool]:
    """(marker count, marker index, fixed-eligible). Marker = atomic number 0 only (SMILES ``*``, SDF ``*``/``R#``).

    Fixed replacement needs exactly one marker whose only neighbour is one heavy atom through a single bond
    (the replacement makes exactly that single bond, spec 4.2; a non-single marker bond would change the
    block's hydrogen count, so such a block is not applicable rather than silently altered).
    """
    markers = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
    if len(markers) != 1:
        return len(markers), None, False
    marker = markers[0]
    bonds = list(marker.GetBonds())
    fixed = (len(bonds) == 1 and bonds[0].GetBondType() == Chem.BondType.SINGLE and
             bonds[0].GetOtherAtom(marker).GetAtomicNum() > 1)
    return 1, marker.GetIdx(), fixed


def read_libraries(blocks: list[dict[str, Any]], raws: list[bytes]) -> tuple[list[dict[str, Any]], list[Block]]:
    """Summaries per library and the accepted blocks in input order (library order, then record order).

    Names are unique across all libraries of one request (a later record whose name is already held by an
    accepted block is ``duplicate_name``), so ``{rule_id, block_name}`` origins are unambiguous. The block cap
    is shared: records are read in input order across the libraries until ``MAX_BLOCKS`` records were read;
    the rest are not read and their library is marked ``block_limit_reached``.
    """
    used: set[str] = set()
    accepted: list[Block] = []
    summaries = []
    remaining = K.MAX_BLOCKS
    for block, raw in zip(blocks, raws, strict=True):
        kind = block["kind"]
        text = _decode(raw)
        if text is None:
            raise _malformed("building-block bytes are not UTF-8")
        records = split_sdf_records(text) if kind == "building_blocks_sdf" else smiles_record_lines(text)
        considered = records[:remaining]
        remaining -= len(considered)
        counts = dict.fromkeys(K.BLOCK_REJECT_REASONS, 0)
        rejected: list[dict[str, Any]] = []
        n_accepted = fixed_targets = rule_targets = 0
        for ordinal, record in enumerate(considered, start=1):
            name, mol, reason = _parse_block(kind, record)
            name = name or f"block_{ordinal}"
            if reason is None and name in used:
                reason = "duplicate_name"
            if reason is not None:
                counts[reason] += 1
                if len(rejected) < K.MAX_REPORTED_BLOCK_REJECTIONS:
                    rejected.append({"ordinal": ordinal, "name": name, "reason": reason})
                continue
            used.add(name)
            _clear_maps(mol)
            markers, marker, fixed = _marker_info(mol)
            accepted.append(Block(name, mol, marker, fixed, markers))
            n_accepted += 1
            fixed_targets += fixed
            rule_targets += markers == 0
        summaries.append({"kind": kind, "input_format": K.BLOCK_INPUT_FORMATS[kind], "sha256": block["sha256"],
                          "records_total": len(records), "records_read": len(considered),
                          "block_limit_reached": len(records) > len(considered), "accepted": n_accepted,
                          "rejected": rejected, "rejected_total": sum(counts.values()),
                          "rejected_counts": counts, "fixed_targets": fixed_targets, "rule_targets": rule_targets})
    return summaries, accepted


# ------------------------------------------------------------------ rules (spec 4.3)
def check_rule(text: str, earlier: list[str]) -> tuple[str, Any]:
    """Return (``valid`` or reason, initialized reaction or None)."""
    if len(text.encode("utf-8")) > K.MAX_RULE_BYTES:
        return "too_large", None
    if text in earlier:
        return "duplicate_rule", None
    try:
        rxn = rdChemReactions.ReactionFromSmarts(text)
    except (ValueError, RuntimeError):
        rxn = None
    if rxn is None:
        return "reaction_parse_failed", None
    if rxn.GetNumReactantTemplates() != 2:
        return "reactant_count", None
    if rxn.GetNumProductTemplates() != 1:
        return "product_count", None
    if not any(atom.GetAtomMapNum() > 0 for atom in rxn.GetReactantTemplate(0).GetAtoms()):
        return "no_mapped_atom", None
    try:
        _warnings, errors = rxn.Validate()
        rxn.Initialize()
    except (ValueError, RuntimeError):
        return "reaction_parse_failed", None
    if errors:
        return "reaction_parse_failed", None
    return K.RULE_VALID, rxn


# ------------------------------------------------------------------ staged input
def _bytes_entry(entry: Any, key: str) -> bytes:
    if (type(entry) is not dict or type(entry.get(key)) is not str or type(entry.get("sha256")) is not str or
            not SHA_RE.fullmatch(entry["sha256"])):
        raise _malformed("staged byte entry is malformed")
    try:
        raw = base64.b64decode(entry[key], validate=True)
    except ValueError as exc:
        raise _malformed("staged bytes are not base64") from exc
    if not 0 < len(raw) <= K.MAX_INPUT_BYTES or _sha(raw) != entry["sha256"]:
        raise _malformed("staged bytes exceed the cap or do not match their SHA-256")
    return raw


def _common(payload: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]], list[bytes]]:
    parent = payload["parent"]
    if type(parent) is not dict or set(parent) != {"sdf_b64", "sha256"}:
        raise _malformed("parent entry is malformed")
    blocks = payload["blocks"]
    if type(blocks) is not list or len(blocks) > 2:
        raise _malformed("zero to two building-block libraries")
    for block in blocks:
        if type(block) is not dict or set(block) != {"kind", "b64", "sha256"} or block["kind"] not in K.BLOCK_IMPORT_KINDS:
            raise _malformed("building-block entry is malformed")
    return _bytes_entry(parent, "sdf_b64"), blocks, [_bytes_entry(block, "b64") for block in blocks]


def _input_shas(parent_raw: bytes, blocks: list[dict[str, Any]], rules: list[str]) -> dict[str, Any]:
    return {"parent": _sha(parent_raw), "blocks": [block["sha256"] for block in blocks],
            "rules": [_sha(text.encode("utf-8")) for text in rules]}


# ------------------------------------------------------------------ inspect (spec 6.2)
def inspect(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"schema", "parent", "blocks", "rules"}:
        raise _malformed("inspect payload keys")
    parent_raw, blocks, raws = _common(payload)
    rules = payload["rules"]
    if type(rules) is not list or len(rules) > K.MAX_RULES or any(type(text) is not str for text in rules):
        raise _malformed("rules must be at most ten strings")
    parent = read_parent(parent_raw)
    graph = parent_graph(parent)
    svg = parent_svg(parent)
    smiles = _canonical_smiles(parent.heavy)
    computed = _from_smiles_properties(smiles)
    if computed is None:
        raise _input_invalid("unparseable", "parent ligand rejected: unparseable")
    libraries, _accepted = read_libraries(blocks, raws)
    rule_rows = []
    for position, text in enumerate(rules, start=1):
        status, _rxn = check_rule(text, rules[:position - 1])
        rule_rows.append({"rule_id": f"{K.USER_RULE_PREFIX}{position}", "status": status,
                          "text": None if status == "too_large" else text,
                          "text_sha256": _sha(text.encode("utf-8"))})
    return {"schema": "ligand_inspect_worker_output@1", "protocol": INSPECT, "rdkit_version": rdBase.rdkitVersion,
            "input_sha256": _input_shas(parent_raw, blocks, rules),
            "parent": {"sha256": _sha(parent_raw), "atoms_in_sdf": parent.full.GetNumAtoms(),
                       "heavy_atom_count": parent.heavy.GetNumAtoms(), "canonical_smiles": smiles,
                       **graph, "svg": svg, "svg_bytes": len(svg.encode("utf-8")),
                       "properties": computed[0]},
            "property_methods": PROPERTY_METHODS, "block_libraries": libraries, "rules": rule_rows}


# ------------------------------------------------------------------ enumerate (spec 6.3, 4.2--4.4)
def _site(parent: Parent, site_atoms: Any) -> tuple[list[int], int, int]:
    """Defensive re-check of the server pre-check (spec 4.1). Returns (core serials, core idx, site idx)."""
    if (type(site_atoms) is not list or any(type(x) is not int for x in site_atoms) or
            len(set(site_atoms)) != len(site_atoms)):
        raise _malformed("site atoms must be distinct integers")
    if not site_atoms:
        raise _input_invalid("site_empty", "site rejected: site_empty")
    if any(serial not in parent.index for serial in site_atoms):
        raise _input_invalid("site_atom_unknown", "site rejected: site_atom_unknown")
    site = {parent.index[serial] for serial in site_atoms}
    core = sorted(parent.serial[idx] for idx in range(parent.heavy.GetNumAtoms()) if idx not in site)
    if not core:
        raise _input_invalid("core_empty", "site rejected: core_empty")
    crossing = [bond for bond in parent.heavy.GetBonds()
                if (bond.GetBeginAtomIdx() in site) != (bond.GetEndAtomIdx() in site)]
    if len(crossing) != 1:
        raise _input_invalid("crossing_bond_count", "site rejected: crossing_bond_count")
    if crossing[0].GetBondType() != Chem.BondType.SINGLE:
        raise _input_invalid("crossing_bond_not_single", "site rejected: crossing_bond_not_single")
    a, b = crossing[0].GetBeginAtomIdx(), crossing[0].GetEndAtomIdx()
    return core, (b if a in site else a), (a if a in site else b)


class _Stop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Generator:
    def __init__(self, parent: Parent, core_serials: list[int], max_candidates: int, max_attempts: int):
        self.parent = parent
        self.core_serials = core_serials
        self.core = set(core_serials)
        self.parent_smiles = _canonical_smiles(parent.heavy)
        self.max_candidates = max_candidates
        self.max_attempts = max_attempts
        self.rows: list[dict[str, Any]] = []
        self.by_smiles: dict[str, dict[str, Any]] = {}
        self.raw = 0
        self.duplicates = 0
        self.rejected = dict.fromkeys(K.PRODUCT_REJECT_REASONS, 0)
        heavy = parent.heavy
        self.specified_centers = {parent.serial[a.GetIdx()] for a in heavy.GetAtoms()
                                  if a.GetChiralTag() in CHIRAL_TAGS and parent.serial[a.GetIdx()] in self.core}
        self.specified_bonds = {frozenset((parent.serial[b.GetBeginAtomIdx()], parent.serial[b.GetEndAtomIdx()]))
                                for b in heavy.GetBonds() if b.GetStereo() in STEREO_BONDS}
        self.specified_bonds = {pair for pair in self.specified_bonds if pair <= self.core}
        self.parent_centers = {parent.serial[idx] for idx, _label in
                               Chem.FindMolChiralCenters(heavy, includeUnassigned=True, useLegacyImplementation=False)}

    def _stereo_flag(self, product: Chem.Mol, origin: dict[int, int]) -> str:
        """``origin`` maps product atom index -> parent core serial (core atoms only)."""
        present = {origin[a.GetIdx()] for a in product.GetAtoms()
                   if a.GetIdx() in origin and a.GetChiralTag() in CHIRAL_TAGS}
        bonds = {frozenset((origin[b.GetBeginAtomIdx()], origin[b.GetEndAtomIdx()])) for b in product.GetBonds()
                 if b.GetBeginAtomIdx() in origin and b.GetEndAtomIdx() in origin and b.GetStereo() in STEREO_BONDS}
        if not self.specified_centers <= present or not self.specified_bonds <= bonds:
            return "parent_stereo_lost"
        for idx, label in Chem.FindMolChiralCenters(product, includeUnassigned=True, useLegacyImplementation=False):
            if label == "?" and not (idx in origin and origin[idx] in self.parent_centers):
                return "new_unspecified_center"
        return "none"

    def attempt(self, origin_ref: dict[str, str], build: Any) -> None:
        if self.raw == self.max_attempts:
            raise _Stop("attempt_limit")
        outcome = build()
        reason, smiles, flag = outcome if type(outcome) is tuple else (outcome, None, None)
        if reason is None and smiles not in self.by_smiles and len(self.rows) == self.max_candidates:
            raise _Stop("candidate_limit")
        computed = _from_smiles_properties(smiles) if reason is None and smiles not in self.by_smiles else None
        if reason is None and smiles not in self.by_smiles and computed is None:
            reason = "sanitize_failed"
        self.raw += 1
        if reason is not None:
            self.rejected[reason] += 1
            return
        if smiles in self.by_smiles:
            self.duplicates += 1
            row = self.by_smiles[smiles]
            if origin_ref not in row["origins"]:
                row["origins"].append(origin_ref)
            return
        row = {"id": "c_" + _sha(smiles.encode("utf-8"))[:16], "smiles": smiles, "origins": [origin_ref],
               "retained_parent_atoms": list(self.core_serials), "stereo_flag": flag,
               "properties": computed[0], "pains": computed[1]}
        self.rows.append(row)
        self.by_smiles[smiles] = row

    def finish(self, product: Chem.Mol | None, origin: dict[int, int]) -> str | tuple[None, str, str]:
        """Shared product checks in the fixed order; returns a reason or (None, smiles, stereo flag)."""
        if product is None:
            return "sanitize_failed"
        try:
            Chem.SanitizeMol(product)
            for atom in product.GetAtoms():
                atom.SetIntProp("_m17_index", atom.GetIdx())
            product = Chem.RemoveHs(product)
        except (ValueError, RuntimeError):
            return "sanitize_failed"
        origin = {a.GetIdx(): origin[a.GetIntProp("_m17_index")] for a in product.GetAtoms()
                  if a.GetIntProp("_m17_index") in origin}
        if any(atom.GetAtomicNum() not in ALLOWED_ATOMIC_NUMBERS for atom in product.GetAtoms()):
            return "element_not_allowed"
        if product.GetNumHeavyAtoms() > K.MAX_PRODUCT_HEAVY_ATOMS:
            return "too_many_atoms"
        _clear_maps(product)
        Chem.AssignStereochemistry(product, cleanIt=True, force=True)
        smiles = _canonical_smiles(product)
        if smiles == self.parent_smiles:
            return "equals_parent"
        return None, smiles, self._stereo_flag(product, origin)


def _fixed_core(parent: Parent, site: set[int], site_attach: int) -> Chem.Mol:
    """Parent with the site's crossing atom turned into a mapped dummy and the rest of the site removed.

    Core atoms keep their indices' bond order, so molzip keeps their chiral tags; the dummy sits exactly
    where the site was attached.
    """
    rw = Chem.RWMol(parent.heavy)
    dummy = Chem.Atom(0)
    dummy.SetAtomMapNum(1)
    rw.ReplaceAtom(site_attach, dummy)
    for idx in sorted(site - {site_attach}, reverse=True):
        rw.RemoveAtom(idx)
    return rw.GetMol()


def enumerate_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"schema", "parent", "blocks", "site_atoms", "use_fixed", "rules", "limits"}:
        raise _malformed("enumerate payload keys")
    parent_raw, blocks, raws = _common(payload)
    use_fixed, rules, limits = payload["use_fixed"], payload["rules"], payload["limits"]
    if (type(use_fixed) is not bool or type(rules) is not list or len(rules) > K.MAX_RULES or
            type(limits) is not dict or set(limits) != {"max_candidates", "max_attempts"} or
            type(limits["max_candidates"]) is not int or not 1 <= limits["max_candidates"] <= K.MAX_CANDIDATES or
            type(limits["max_attempts"]) is not int or not 1 <= limits["max_attempts"] <= K.MAX_ATTEMPTS):
        raise _malformed("enumerate options are malformed")
    seen_ids: set[str] = set()
    for rule in rules:
        if (type(rule) is not dict or set(rule) != {"rule_id", "text"} or type(rule["text"]) is not str or
                type(rule["rule_id"]) is not str or not RULE_ID_RE.fullmatch(rule["rule_id"]) or
                int(rule["rule_id"][len(K.USER_RULE_PREFIX):]) > K.MAX_RULES or rule["rule_id"] in seen_ids):
            raise _malformed("rule entry is malformed")
        seen_ids.add(rule["rule_id"])
    if not use_fixed and not rules:
        raise _input_invalid("no_generation_method", "fixed replacement and all rules are off")
    parent = read_parent(parent_raw)
    core_serials, core_attach, site_attach = _site(parent, payload["site_atoms"])
    site = {parent.index[serial] for serial in payload["site_atoms"]}
    reactions = []
    for position, rule in enumerate(rules):
        status, rxn = check_rule(rule["text"], [earlier["text"] for earlier in rules[:position]])
        if status != K.RULE_VALID:
            raise _input_invalid("rule_invalid", f"rule {rule['rule_id']} is not valid: {status}")
        reactions.append((rule, rxn))
    libraries, accepted = read_libraries(blocks, raws)
    gen = Generator(parent, core_serials, limits["max_candidates"], limits["max_attempts"])
    not_applicable: dict[str, int] = {}
    if use_fixed:
        not_applicable[K.FIXED_RULE_ID] = sum(not block.fixed for block in accepted)
    for rule, _rxn in reactions:
        not_applicable[rule["rule_id"]] = sum(block.markers != 0 for block in accepted)
    stop_reason = None
    try:
        if use_fixed:
            core_mol = _fixed_core(parent, site, site_attach)
            for block in (b for b in accepted if b.fixed):
                gen.attempt({"rule_id": K.FIXED_RULE_ID, "block_name": block.name},
                            lambda block=block: _fixed_product(gen, core_mol, block))
        all_parent = set(range(parent.heavy.GetNumAtoms()))
        for rule, rxn in reactions:
            for block in (b for b in accepted if b.markers == 0):
                remaining = gen.max_attempts - gen.raw
                outputs = rxn.RunReactants((parent.heavy, block.mol), remaining + 1)
                for products in outputs:
                    gen.attempt({"rule_id": rule["rule_id"], "block_name": block.name},
                                lambda products=products: _rule_product(gen, products[0], site, all_parent))
    except _Stop as stop:
        stop_reason = stop.reason
    computed = _from_smiles_properties(gen.parent_smiles)
    if computed is None:
        raise _input_invalid("unparseable", "parent ligand rejected: unparseable")
    used = ([{"rule_id": K.FIXED_RULE_ID, "method": K.FIXED_METHOD, "text": None}] if use_fixed else []) + \
        [{"rule_id": rule["rule_id"], "method": K.USER_RULE_METHOD, "text": rule["text"]} for rule, _ in reactions]
    return {"schema": "ligand_enumerate_worker_output@1", "protocol": ENUMERATE,
            "rdkit_version": rdBase.rdkitVersion,
            "input_sha256": _input_shas(parent_raw, blocks, [rule["text"] for rule in rules]),
            "parent_sha256": _sha(parent_raw), "parent_canonical_smiles": gen.parent_smiles,
            "parent_properties": computed[0], "property_methods": PROPERTY_METHODS,
            "site_atoms": sorted(payload["site_atoms"]), "retained_parent_atoms": core_serials,
            "crossing_bond": {"core_atom": parent.serial[core_attach], "site_atom": parent.serial[site_attach],
                              "order": "single"},
            "use_fixed": use_fixed, "rules_used": used, "methods": [row["method"] for row in used],
            "block_libraries": libraries, "candidates": gen.rows,
            "counts": {"blocks_accepted": len(accepted), "raw_products": gen.raw, "candidates": len(gen.rows),
                       "duplicate_products": gen.duplicates, "rejected": gen.rejected,
                       "not_applicable": not_applicable},
            "limits": dict(limits), "limit_reached": stop_reason is not None, "stop_reason": stop_reason,
            "limitations": list(K.LIMITATIONS)}


def _fixed_product(gen: Generator, core_mol: Chem.Mol, block: Block) -> Any:
    piece = Chem.Mol(block.mol)
    piece.GetAtomWithIdx(block.marker).SetAtomMapNum(1)
    try:
        product = Chem.RWMol(Chem.molzip(core_mol, piece))
    except (ValueError, RuntimeError):
        return gen.finish(None, {})
    origin = {atom.GetIdx(): atom.GetIntProp(SERIAL) for atom in product.GetAtoms()
              if atom.HasProp(SERIAL) and atom.GetIntProp(SERIAL) in gen.core}
    return gen.finish(product, origin)


def _rule_product(gen: Generator, product: Chem.Mol, site: set[int], all_parent: set[int]) -> Any:
    """Skip as ``outside_site`` unless every parent atom the first template matched is a site atom.

    Matched parent atoms = mapped atoms carried into the product plus parent atoms missing from it (unmapped
    template atoms are deleted). Requiring both inside the site also guarantees every core atom survives.
    """
    carried, mapped = set(), set()
    origin = {}
    for atom in product.GetAtoms():
        if atom.HasProp("react_idx") and atom.GetIntProp("react_idx") == 0:
            parent_idx = atom.GetIntProp("react_atom_idx")
            carried.add(parent_idx)
            if atom.HasProp("old_mapno"):
                mapped.add(parent_idx)
            serial = gen.parent.serial[parent_idx]
            if serial in gen.core:
                origin[atom.GetIdx()] = serial
    if not ((all_parent - carried) | mapped) <= site:
        return "outside_site"
    return gen.finish(Chem.RWMol(product), origin)


# ------------------------------------------------------------------ entry points
def handshake() -> dict[str, Any]:
    pains_sizes = {}
    for name, which in PAINS_CATALOGS:
        params = FilterCatalogParams()
        params.AddCatalog(which)
        pains_sizes[name] = FilterCatalog(params).GetNumEntries()
    return {"schema": "ligand_worker_handshake@1", "rdkit_version": rdBase.rdkitVersion,
            "rdkit_version_expected": RDKIT_VERSION, "pains_catalog_entries": pains_sizes,
            "protocols": [INSPECT, ENUMERATE], "worker_sha256": _sha(Path(__file__).read_bytes()),
            "python": sys.version.split()[0]}


def _read_bounded(name: str, limit: int) -> bytes:
    path = Path(name)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise _malformed(f"{name} missing or over its bound")
    return path.read_bytes()


def run_job() -> dict[str, Any]:
    if rdBase.rdkitVersion != RDKIT_VERSION:
        raise LigandWorkerError("fatal", "rdkit_version_mismatch", "pinned RDKit version unavailable")
    try:
        control = json.loads(_read_bounded("input.json", 4096))
        raw = _read_bounded("structure.json", MAX_STAGED_BYTES)
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _malformed("staged JSON unreadable") from exc
    if (type(control) is not dict or control.get("adapter") not in (INSPECT, ENUMERATE) or
            type(control.get("input_sha256")) is not str or _sha(raw) != control["input_sha256"] or
            type(payload) is not dict or
            any(type(control.get(key)) is not str or not CONTROL_ID_RE.fullmatch(control[key])
                for key in ("job_id", "attempt_id"))):
        raise _malformed("control record or staged hash mismatch")
    expected = {INSPECT: "ligand_inspect_worker_input@1", ENUMERATE: "ligand_enumerate_worker_input@1"}
    if payload.get("schema") != expected[control["adapter"]]:
        raise _malformed("staged schema does not match the adapter")
    output = inspect(payload) if control["adapter"] == INSPECT else enumerate_candidates(payload)
    # Echo the attempt identity so the server binds this result to the attempt it launched.
    return {**output, "job_id": control["job_id"], "attempt_id": control["attempt_id"]}


def main(argv: list[str]) -> int:
    if argv == ["--handshake"]:
        sys.stdout.write(json.dumps(handshake(), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    if argv:
        return 2
    output = canonical_json(run_job())
    if not 0 < len(output) <= MAX_OUTPUT_BYTES:
        raise LigandWorkerError("resource_exceeded", "output_limit", "bounded worker output exceeded")
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
    except LigandWorkerError as exc:
        _write_error(exc.envelope())
        raise SystemExit(1) from None
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError,
            MemoryError, RecursionError) as exc:
        _write_error({"schema": "ligand_worker_error@1", "error_class": "fatal",
                      "reason_code": "worker_internal_error", "message": type(exc).__name__[:80]})
        raise SystemExit(1) from None
