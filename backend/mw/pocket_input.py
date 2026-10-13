"""M12 protein-only detector input projection (server side; no engine, no network).

The projection reads only the server's accepted AtomRef traversal of a same-run
source (the M10 atom catalog ``site_index`` order, or the validated M11 chemical
source rows) and writes a private transport PDB ``protein.pdb`` with synthetic
residue/chain identifiers. The full transport ↔ AtomRef bijection, original and
projected coordinates, occupancy/B-factor, excluded sites and quantization are
returned as the ``pocket_detector_input@1`` manifest content. Transport IDs are
never parsed back into source identities.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

import gemmi
import numpy as np

from .core.errors import FailureClass, ToolFailure
from .structure_origin import reject_if_repaired
from .tools.comparison import atom_rows
from .tools.registry import ToolContext
from .tools.structural import _parse, structure_bytes

SCHEMA = "pocket_detector_input@1"
STANDARD_RESIDUES = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"})
# Exactly these ten residue names are written under a standard transport name (six histidine protonation
# names and four Amber names); the original name stays in every identity and in ``resname_mapping``.
TRANSPORT_RESNAMES = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
                      "CYX": "CYS", "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}
WATER_NAMES = frozenset({"HOH", "WAT", "DOD", "H2O", "TIP", "TIP3", "SOL"})
HYDROGEN_ELEMENTS = frozenset({"H", "D"})
CHAIN_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
MAX_HEAVY_ATOMS = 10_000
MAX_RESIDUES = 3_000
MAX_CHAINS = len(CHAIN_ALPHABET)  # 62
MAX_INPUT_BYTES = 10 * 1024 * 1024
MIN_ATOMS = 4
DECIMALS = 3
TOLERANCE_A = 0.0005
ROUNDOFF_A = 1e-9
RANK_ABSOLUTE = 1e-12
RANK_RELATIVE = 1e-8
EXCLUDED_CATEGORIES = ("water", "ligand", "ion", "hydrogen", "unselected_chain")
SOURCE_KINDS = {
    ("prepared_structure", "prepared_structure@1"),
    ("chemical_structure", "chemical_structure@1"),
    ("openmm_minimized_structure", "openmm_minimized_structure@1"),
}
RESIDUE_FIELDS = ("model_number", "chain_auth", "seq_auth", "icode", "chain_label", "seq_label", "resname")
SYNTHETIC_ID_RULE = {
    "residue": "globally unique integer 1..N in source site traversal order, one per source residue",
    "chain": "one character per selected chain_auth, assigned in sorted chain_auth order from alphabet",
    "chain_alphabet": CHAIN_ALPHABET,
    "serial": "transport_index + 1",
    "retained": ("original atom name, element and residue name (six histidine names written as HIS; CYX, ASH, "
                 "GLH, LYN written as CYS, ASP, GLU, LYS)"),
    "note": "synthetic IDs are transport identifiers only; source identities come from this manifest",
}
CATEGORY_RULE = {
    "protein": "20 standard residues plus six histidine and four Amber residue names; heavy atoms only",
    "hydrogen": "H/D atoms of protein residues",
    "water": "water residue names",
    "ion": "single-atom non-water, non-amino-acid residue",
    "ligand": "any other non-protein residue (all its atoms, including H)",
    "unselected_chain": "every site of a chain_auth outside the selection",
    "modified_residue": ("other tabulated amino acid, or polymer-record residue with N/CA/C atoms, "
                         "in a selected chain rejects the input"),
}


def _fail(cls: FailureClass, code: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(cls, message, detail={"reason_code": code, **detail})


def _invalid(code: str, message: str, **detail: Any) -> ToolFailure:
    return _fail(FailureClass.input_invalid, code, message, **detail)


def _residue_key(residue: dict[str, Any]) -> tuple:
    return tuple(residue[field] for field in RESIDUE_FIELDS)


def _load_source(store: Any, handle: str) -> dict[str, Any]:
    """Resolve the accepted server-side traversal of one same-run source."""
    if type(handle) is not str:
        raise _invalid("unknown_source", "source handle must be a string")
    try:
        meta = store.meta(handle)
    except KeyError as exc:
        raise _invalid("unknown_source", "unknown same-run source") from exc
    kind_schema = (meta["kind"], meta["schema"])
    if meta["kind"] == "structure":
        raise _fail(FailureClass.precondition, "raw_structure_requires_preparation",
                    "prepare the structure first (explicit model and altloc policy)")
    if kind_schema not in SOURCE_KINDS:
        raise _invalid("unsupported_source_kind", "unsupported pocket input source kind",
                       source_kind=meta["kind"])
    # M29 spec 5.2: a repaired structure is no pocket source (job submission and re-projection; the preflight route
    # refuses it before this read, so no M12 preflight ``reject`` ever carries this code).
    reject_if_repaired(store, handle)
    if meta["kind"] == "chemical_structure":
        from .chemical_bundle import validated_source

        source = validated_source(store, handle)
        text = source["text"].encode("utf-8")
        if len(text) > MAX_INPUT_BYTES:
            raise _fail(FailureClass.resource_exceeded, "input_size_limit", "source exceeds 10 MiB")
        category = gemmi.cif.read_string(source["text"]).sole_block().get_mmcif_category("_atom_site.")
        rows = []
        for i, row in enumerate(source["atoms"]):
            # Chemical receptor rows are written as ATOM (polymer) records.
            rows.append({"ref": row["ref"], "coordinate_A": list(row["coordinate_A"]),
                         "polymer": row["protein"], "occupancy": float(category["occupancy"][i]),
                         "b_factor": float(category["B_iso_or_equiv"][i])})
        return {"kind": meta["kind"], "model_number": source["model_number"],
                "preparation_handle": source["manifest_handle"], "rows": rows, "input_bytes": len(text)}
    raw, _ = structure_bytes(store, handle)
    if len(raw) > MAX_INPUT_BYTES:
        raise _fail(FailureClass.resource_exceeded, "input_size_limit", "source exceeds 10 MiB")
    catalog = atom_rows(store, handle)
    parsed = _parse(ToolContext(store=store, call_id="pocket_input"), handle)
    atoms = [(residue, atom) for chain in parsed[0] for residue in chain for atom in residue]
    if len(atoms) != len(catalog["rows"]):
        raise _invalid("source_traversal_mismatch", "source traversal differs from atom catalog")
    rows = []
    for row, (residue, atom) in zip(catalog["rows"], atoms, strict=True):
        if (atom.name != row["ref"]["atom_name"] or atom.element.name.upper() != row["ref"]["element"] or
                [atom.pos.x, atom.pos.y, atom.pos.z] != row["coordinate_A"]):
            raise _invalid("source_traversal_mismatch", "source traversal differs from atom catalog")
        rows.append({"ref": row["ref"], "coordinate_A": list(row["coordinate_A"]),
                     "polymer": residue.het_flag == "A",
                     "occupancy": float(atom.occ), "b_factor": float(atom.b_iso)})
    return {"kind": meta["kind"], "model_number": catalog["model_number"],
            "preparation_handle": store.load(handle)["manifest"], "rows": rows, "input_bytes": len(raw)}


def _residue_category(resname: str, atoms: list[dict[str, Any]]) -> str:
    if resname in STANDARD_RESIDUES or resname in TRANSPORT_RESNAMES:
        return "protein"
    info = gemmi.find_tabulated_residue(resname)
    if resname in WATER_NAMES or (info is not None and info.is_water()):
        return "water"
    names = {row["ref"]["atom_name"] for row in atoms}
    polymer = any(row.get("polymer") for row in atoms)
    if (info is not None and info.is_amino_acid()) or (polymer and {"N", "CA", "C"} <= names):
        return "modified_residue"
    if len(atoms) == 1:
        return "ion"
    return "ligand"


def _group(view: dict[str, Any]) -> dict[str, Any]:
    """Group sites into residues in traversal order and list the source chains."""
    rows = view["rows"]
    residues: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for site, row in enumerate(rows):
        if row["ref"]["site_index"] != site:
            raise _invalid("source_traversal_mismatch", "AtomRef site order is not the traversal order")
        key = _residue_key(row["ref"]["residue"])
        if residues and residues[-1]["key"] == key:
            residues[-1]["sites"].append(site)
            continue
        if key in seen:
            raise _invalid("duplicate_residue_identity", "a residue identity occurs in separate site runs",
                           residue=row["ref"]["residue"])
        seen.add(key)
        residues.append({"key": key, "residue": row["ref"]["residue"], "sites": [site]})
    found: dict[str, None] = {}
    for residue in residues:
        residue["category"] = _residue_category(residue["residue"]["resname"],
                                                [rows[i] for i in residue["sites"]])
        if residue["category"] in {"protein", "modified_residue"}:
            found.setdefault(residue["residue"]["chain_auth"])
    protein_chains = list(found)
    chain_rows: dict[str, dict[str, Any]] = {}
    for residue in residues:
        chain = residue["residue"]["chain_auth"]
        entry = chain_rows.setdefault(chain, {"chain_auth": chain, "has_protein": chain in found,
                                              "protein_residues": 0, "protein_heavy_atoms": 0})
        if residue["category"] == "protein":
            entry["protein_residues"] += 1
            entry["protein_heavy_atoms"] += sum(rows[i]["ref"]["element"].upper() not in HYDROGEN_ELEMENTS
                                                for i in residue["sites"])
    all_chains = list(chain_rows)
    available = list(chain_rows.values())
    return {"residues": residues, "protein_chains": protein_chains, "all_chains": all_chains,
            "available_chains": available}


def _analyze(view: dict[str, Any], chains: Any, grouped: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the chain selection, classify sites and count exclusions."""
    rows = view["rows"]
    grouped = grouped or _group(view)
    residues, protein_chains = grouped["residues"], grouped["protein_chains"]
    all_chains = grouped["all_chains"]
    if chains is None:
        chains = []
    if type(chains) is not list or any(type(c) is not str for c in chains):
        raise _invalid("invalid_chain_selection", "chains must be a list of chain_auth strings")
    unknown = sorted(set(chains) - set(all_chains))
    if unknown:
        raise _invalid("unknown_chain", "selected chain is not in the source", chains=unknown)
    selected = sorted(set(chains) if chains else set(protein_chains))
    selected_set = set(selected)
    excluded = {category: 0 for category in EXCLUDED_CATEGORIES}
    excluded_sites: list[dict[str, Any]] = []
    included: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    heavy_by_chain = {chain: 0 for chain in selected}
    for residue in residues:
        chain = residue["residue"]["chain_auth"]
        category = residue["category"] if chain in selected_set else "unselected_chain"
        if category == "modified_residue":
            modified.append(residue["residue"])
            continue
        if category != "protein":
            excluded[category] += len(residue["sites"])
            excluded_sites.extend({"site_index": i, "category": category} for i in residue["sites"])
            continue
        heavy = []
        for i in residue["sites"]:
            if rows[i]["ref"]["element"].upper() in HYDROGEN_ELEMENTS:
                excluded["hydrogen"] += 1
                excluded_sites.append({"site_index": i, "category": "hydrogen"})
            else:
                heavy.append(i)
        if not heavy:
            continue
        heavy_by_chain[chain] += len(heavy)
        included.append({"residue": residue["residue"], "sites": heavy})
    if modified:
        raise _invalid("modified_residue_unsupported", "modified amino-acid residue is not supported",
                       residues=modified[:20], total=len(modified))
    empty = sorted(chain for chain, count in heavy_by_chain.items() if count == 0)
    if empty:
        raise _invalid("chain_without_protein", "selected chain has no standard protein heavy atoms",
                       chains=empty)
    if not included:
        raise _invalid("no_protein_atoms", "source has no standard protein heavy atoms")
    for residue in included:
        resname = residue["residue"]["resname"]
        if resname in TRANSPORT_RESNAMES:
            mapping.append({"residue": residue["residue"], "original_resname": resname,
                            "transport_resname": TRANSPORT_RESNAMES[resname]})
    return {"available_chains": grouped["available_chains"], "selected_chains": selected,
            "excluded_counts": excluded, "excluded_sites": excluded_sites, "included": included,
            "resname_mapping": mapping, "heavy_atom_count": sum(len(r["sites"]) for r in included),
            "residue_count": len(included)}


def _field(value: float, width: int, decimals: int, name: str) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _invalid("nonfinite_value", f"{name} is not finite")
    text = f"{value:{width}.{decimals}f}"
    if len(text) != width:
        raise _invalid("field_overflow", f"{name} does not fit the PDB {width}.{decimals} field")
    return text


def _atom_name_field(name: str, element: str) -> str:
    if (type(name) is not str or not 1 <= len(name) <= 4 or not name.isascii() or
            any(c.isspace() for c in name)):
        raise _invalid("field_overflow", "atom name is not representable in the PDB name field")
    return f" {name:<3}" if len(name) < 4 and len(element) == 1 else f"{name:<4}"


def _check_limits(analysis: dict[str, Any]) -> None:
    if len(analysis["selected_chains"]) > MAX_CHAINS:
        raise _fail(FailureClass.resource_exceeded, "chain_limit", "more than 62 selected chains")
    if analysis["residue_count"] > MAX_RESIDUES:
        raise _fail(FailureClass.resource_exceeded, "residue_limit", "more than 3000 projected residues")
    if analysis["heavy_atom_count"] > MAX_HEAVY_ATOMS:
        raise _fail(FailureClass.resource_exceeded, "heavy_atom_limit", "more than 10000 projected heavy atoms")


def _parse_transport(pdb: bytes) -> list[dict[str, Any]]:
    records = []
    for line in pdb.decode("ascii").splitlines():
        if not line.startswith("ATOM  "):
            continue
        records.append({"serial": int(line[6:11]), "atom_name": line[12:16].strip(),
                        "resname": line[17:20], "chain": line[21], "resseq": int(line[22:26]),
                        "icode": line[26], "xyz": [float(line[i:i + 8]) for i in (30, 38, 46)],
                        "occupancy": float(line[54:60]), "b_factor": float(line[60:66]),
                        "element": line[76:78].strip()})
    return records


def _transport(view: dict[str, Any], analysis: dict[str, Any], source_handle: str) -> dict[str, Any]:
    _check_limits(analysis)
    rows = view["rows"]
    chain_map = {chain: CHAIN_ALPHABET[i] for i, chain in enumerate(analysis["selected_chains"])}
    atoms: list[dict[str, Any]] = []
    residues: list[dict[str, Any]] = []
    lines: list[str] = []
    for number, residue in enumerate(analysis["included"], start=1):
        identity = residue["residue"]
        resname = identity["resname"]
        transport_resname = TRANSPORT_RESNAMES.get(resname, resname)
        synthetic_chain = chain_map[identity["chain_auth"]]
        residues.append({"synthetic_chain": synthetic_chain, "synthetic_resseq": number,
                         "transport_resname": transport_resname, "residue": identity})
        names: set[str] = set()
        for site in residue["sites"]:
            row = rows[site]
            ref = row["ref"]
            if ref["atom_name"] in names:
                raise _invalid("duplicate_atom_name", "duplicate atom name within one residue",
                               residue=identity, atom_name=ref["atom_name"])
            names.add(ref["atom_name"])
            element = ref["element"].upper()
            if not 1 <= len(element) <= 2 or not element.isalpha() or not element.isascii():
                raise _invalid("field_overflow", "element does not fit the PDB element field")
            index = len(atoms)
            coords = [_field(value, 8, DECIMALS, "coordinate") for value in row["coordinate_A"]]
            occupancy = _field(row["occupancy"], 6, 2, "occupancy")
            b_factor = _field(row["b_factor"], 6, 2, "B-factor")
            lines.append(f"ATOM  {index + 1:5d} {_atom_name_field(ref['atom_name'], element)} "
                         f"{transport_resname:>3} {synthetic_chain}{number:4d}    "
                         f"{''.join(coords)}{occupancy}{b_factor}          {element:>2}  ")
            atoms.append({"transport_index": index, "serial": index + 1, "synthetic_chain": synthetic_chain,
                          "synthetic_resseq": number, "atom_name": ref["atom_name"],
                          "transport_resname": transport_resname, "element": element, "ref": ref,
                          "original_coordinate_A": list(row["coordinate_A"]),
                          "occupancy": row["occupancy"], "b_factor": row["b_factor"]})
    pdb = ("\n".join(lines) + "\nEND\n").encode("ascii")
    if len(pdb) > MAX_INPUT_BYTES:
        raise _fail(FailureClass.resource_exceeded, "input_size_limit", "transport file exceeds 10 MiB")
    records = _parse_transport(pdb)
    if len(records) != len(atoms):
        raise _fail(FailureClass.fatal, "transport_roundtrip_mismatch", "transport atom count changed")
    worst = 0.0
    for atom, record in zip(atoms, records, strict=True):
        if ((record["serial"], record["atom_name"], record["resname"], record["chain"], record["resseq"],
             record["icode"], record["element"]) !=
                (atom["serial"], atom["atom_name"], atom["transport_resname"], atom["synthetic_chain"],
                 atom["synthetic_resseq"], " ", atom["element"])):
            raise _fail(FailureClass.fatal, "transport_roundtrip_mismatch", "transport identity changed")
        for original, projected in zip(atom["original_coordinate_A"], record["xyz"], strict=True):
            difference = abs(original - projected)
            if difference > TOLERANCE_A + ROUNDOFF_A:
                raise _fail(FailureClass.fatal, "transport_roundtrip_mismatch",
                            "transport coordinate exceeds quantization tolerance")
            worst = max(worst, difference)
        atom["projected_coordinate_A"] = record["xyz"]
    positions: dict[tuple[float, float, float], int] = {}
    for atom in atoms:
        key = tuple(atom["projected_coordinate_A"])
        if key in positions:
            raise _invalid("coincident_atoms", "projected heavy atoms coincide",
                           atoms=[atoms[positions[key]]["ref"], atom["ref"]])
        positions[key] = atom["transport_index"]
    if len(atoms) < MIN_ATOMS:
        raise _invalid("too_few_atoms", "at least 4 projected heavy atoms are required", count=len(atoms))
    xyz = np.asarray([atom["projected_coordinate_A"] for atom in atoms], dtype=np.float64)
    singular = np.linalg.svd(xyz - xyz.mean(axis=0), compute_uv=False)
    if len(singular) < 3 or singular[2] <= max(RANK_ABSOLUTE, RANK_RELATIVE * float(singular[0])):
        raise _invalid("degenerate_geometry", "projected coordinates do not have rank 3")
    sha = hashlib.sha256(pdb).hexdigest()
    manifest = {
        "schema": SCHEMA, "source_handle": source_handle, "source_kind": view["kind"],
        "model_number": view["model_number"], "preparation_handle": view["preparation_handle"],
        "selected_chains": analysis["selected_chains"],
        "chain_map": [{"chain_auth": chain, "synthetic_chain": code} for chain, code in chain_map.items()],
        "excluded_counts": analysis["excluded_counts"], "excluded_sites": analysis["excluded_sites"],
        "category_rule": CATEGORY_RULE, "resname_mapping": analysis["resname_mapping"],
        "synthetic_id_rule": SYNTHETIC_ID_RULE,
        "quantization": {"decimals": DECIMALS, "coordinate_field": "PDB 8.3", "transport_precision_A": 0.001,
                         "tolerance_A": TOLERANCE_A, "max_axis_discrepancy_A": worst},
        "limits": {"heavy_atoms": MAX_HEAVY_ATOMS, "residues": MAX_RESIDUES, "chains": MAX_CHAINS,
                   "input_bytes": MAX_INPUT_BYTES, "min_atoms": MIN_ATOMS, "coordinate_rank": 3},
        "counts": {"heavy_atoms": len(atoms), "residues": len(residues), "chains": len(chain_map),
                   "source_sites": len(rows), "source_input_bytes": view["input_bytes"]},
        "residues": residues, "atoms": atoms,
        "transport_file": "protein.pdb", "transport_pdb_sha256": sha, "transport_pdb_bytes": len(pdb),
    }
    return {"manifest": manifest, "atoms": atoms, "pdb_bytes": pdb, "pdb_sha256": sha,
            "selected_chains": analysis["selected_chains"]}


def project(store: Any, source_handle: str, chains: list[str] | None = None) -> dict[str, Any]:
    """Project one same-run source to the detector transport input or raise ToolFailure."""
    view = _load_source(store, source_handle)
    return _transport(view, _analyze(view, chains), source_handle)


def preflight(store: Any, source_handle: str, chains: list[str] | None = None) -> dict[str, Any]:
    """Pure projection summary for the preflight route; runs no tool, job or engine."""
    summary: dict[str, Any] = {
        "schema": "pocket_input_preflight@1", "source_handle": source_handle, "source_kind": None,
        "model_number": None, "preparation_handle": None, "available_chains": [], "selected_chains": [],
        "excluded_counts": None, "projected_atom_count": None,
        "projected_residue_count": None, "resname_mapping": [], "ready": False, "reject": None}
    stage = "source"
    try:
        view = _load_source(store, source_handle)
        summary.update(source_kind=view["kind"], model_number=view["model_number"],
                       preparation_handle=view["preparation_handle"])
        stage = "analysis"
        grouped = _group(view)
        summary["available_chains"] = grouped["available_chains"]
        analysis = _analyze(view, chains, grouped)
        summary.update(selected_chains=analysis["selected_chains"],
                       excluded_counts=analysis["excluded_counts"],
                       projected_atom_count=analysis["heavy_atom_count"],
                       projected_residue_count=analysis["residue_count"],
                       resname_mapping=analysis["resname_mapping"])
        stage = "transport"
        _transport(view, analysis, source_handle)
    except ToolFailure as failure:
        summary["reject"] = {"failure_class": failure.cls.value,
                             "reason_code": failure.detail.get("reason_code", "source_invalid"),
                             "message": failure.message, "stage": stage,
                             "detail": {k: v for k, v in failure.detail.items() if k != "reason_code"}}
        return summary
    summary["ready"] = True
    return summary
