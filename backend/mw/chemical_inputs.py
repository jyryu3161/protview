"""Bounded M11 immutable prepared-input inventory and exact mapping preflight.

No chemistry inference runs here. The isolated native worker validates the final
graph after approval. Raw staging refs never enter M8--M10 source allowlists.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from itertools import pairwise
from typing import Any

import gemmi

from .core.errors import FailureClass, ToolFailure
from .core.handles import object_sha
from .ligand_constants import BLOCK_IMPORT_KINDS
from .ligand_inputs import import_raw as import_block_raw
from .structure_origin import reject_if_repaired
from .tools.comparison import AtomRefV1, CompleteResidueRef, atom_rows
from .tools.registry import ToolContext
from .tools.structural import _parse, _res_ref

MAX_RAW = 10 * 1024 * 1024
MAX_RECEPTOR = 10_000
MAX_LIGAND = 256
MAX_BONDS = 20_000
AMINO = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
         "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
         "HSD", "HSE", "HSP", "HID", "HIE", "HIP"}
RECEPTOR_ELEMENTS = {"H", "C", "N", "O", "S"}
LIGAND_ELEMENTS = RECEPTOR_ELEMENTS | {"P", "F", "CL", "BR", "I"}
ACK_KEYS = {"schema", "supplied_graph_complete", "supplied_hydrogens_complete",
            "use_supplied_protonation_tautomer", "infer_receptor_orders_charges", "description", "ph_annotation"}
DERIVED_COORDINATE_POLICY = ("new chemical source keeps receptor original coordinates and selected SDF "
                             "conformer coordinates; attach requires <=0.002 A discrepancy and never aligns")


def invalid(message: str, *, detail: dict[str, Any] | None = None) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail=detail or {})


def _bytes(store: Any, handle: str, input_kind: str) -> tuple[bytes, str]:
    try:
        meta = store.meta(handle)
        raw = store.load_bounded_bytes(handle, MAX_RAW)
    except KeyError as exc:
        raise invalid("unknown same-run chemical import") from exc
    if ((meta["kind"], meta["schema"]) != ("chemical_raw_input", "chemical_raw_input@1") or
            meta["summary"].get("input_kind") != input_kind or type(raw) is not bytes or len(raw) > MAX_RAW):
        raise invalid("chemical import kind or size mismatch")
    return raw, meta["summary"].get("input_format", meta["fmt"])


def import_raw(store: Any, kind: str, filename: str, raw: bytes) -> dict[str, Any]:
    if kind in BLOCK_IMPORT_KINDS:  # M17 building blocks: light checks only (ligand_inputs)
        return import_block_raw(store, kind, filename, raw)
    if (kind not in {"receptor", "ligand_sdf", "receptor_bonds"} or type(filename) is not str or
            not filename or len(filename.encode("utf-8")) > 200 or "/" in filename or "\\" in filename or
            type(raw) is not bytes or not 0 < len(raw) <= MAX_RAW):
        raise invalid("unsupported or oversized chemical import")
    ext = filename.rsplit(".", 1)[-1].lower()
    allowed = {"receptor": {"pdb", "cif", "mmcif"}, "ligand_sdf": {"sdf"},
               "receptor_bonds": {"json"}}[kind]
    if ext not in allowed:
        raise invalid("chemical filename extension does not match input kind")
    try:
        text = raw.decode("utf-8")
        if kind == "receptor":
            st = _gemmi(text, ext)
            if not st or not any(model.count_atom_sites() for model in st):
                raise ValueError("empty receptor")
        elif kind == "ligand_sdf":
            _sdf_records(text)
        else:
            obj = json.loads(text)
            if type(obj) is not dict or obj.get("schema") != "receptor_bonds@1":
                raise ValueError("invalid connectivity sidecar")
    except (UnicodeError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        raise invalid("malformed chemical input") from exc
    # An import is content-addressed. The caller's filename is an upload hint,
    # not scientific object identity; a second name for the same bytes must
    # return the existing immutable object without rewriting historical meta.
    canonical_format = "cif" if ext == "mmcif" else ext
    sha = hashlib.sha256(raw).hexdigest()
    handle = f"obj://{store.run_id}/chemical_raw_input/" + object_sha(
        "chemical_raw_input", "chemical_raw_input@1", raw)
    try:
        existing = store.meta(handle)
    except KeyError:
        existing = None
    if existing is not None:
        old_format = existing["summary"].get("input_format", existing["fmt"])
        if (existing["kind"] != "chemical_raw_input" or existing["schema"] != "chemical_raw_input@1" or
                existing["summary"].get("input_kind") != kind or
                ("cif" if old_format == "mmcif" else old_format) != canonical_format or
                existing["summary"].get("sha256") != sha or
                store.load_bounded_bytes(handle, MAX_RAW) != raw):
            raise invalid("identical chemical bytes have incompatible imported kind or format")
        return {"schema": "chemical_raw_input@1", "handle": handle, "kind": kind,
                "format": old_format, "sha256": sha, "size": len(raw)}
    # ObjectStore parses fmt=json on load; preserve uploaded sidecar bytes as
    # immutable raw content so even whitespace/hash provenance is retained.
    result = store.put("chemical_raw_input", "chemical_raw_input@1", raw,
                       fmt="raw" if ext == "json" else canonical_format,
                       summary={"input_kind": kind, "input_format": canonical_format, "sha256": sha})
    return {"schema": "chemical_raw_input@1", "handle": result.handle, "kind": kind,
            "format": canonical_format, "sha256": sha, "size": len(raw)}


def _gemmi(text: str, fmt: str):
    if fmt in {"cif", "mmcif"}:
        return gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    if fmt == "pdb":
        return gemmi.read_pdb_string(text)
    raise ValueError("unsupported receptor format")


def _sdf_records(text: str) -> list[dict[str, Any]]:
    records = [x for x in text.split("$$$$") if x.strip()]
    if not 1 <= len(records) <= 100:
        raise ValueError("SDF must contain 1--100 records")
    out = []
    for ridx, record in enumerate(records):
        lines = record.splitlines()
        # The delimiter contributes one newline to later records. Do not
        # strip a second blank line: it may be the legitimate empty title.
        if ridx and lines and lines[0] == "":
            lines.pop(0)
        if len(lines) < 5 or "V2000" not in lines[3]:
            raise ValueError(f"SDF record {ridx}: only bounded V2000 supported")
        na, nb = int(lines[3][0:3]), int(lines[3][3:6])
        if not 1 <= na <= MAX_LIGAND or not 1 <= nb <= MAX_BONDS or len(lines) < 4 + na + nb:
            raise ValueError(f"SDF record {ridx}: atom/bond cap or truncation")
        atoms, bonds = [], []
        charge_codes = {0: 0, 1: 3, 2: 2, 3: 1, 5: -1, 6: -2, 7: -3}
        for i, line in enumerate(lines[4:4 + na]):
            xyz = [float(line[j:j + 10]) for j in (0, 10, 20)]
            element = line[31:34].strip().upper()
            mass_difference = int(line[34:36])
            charge_code = int(line[36:39])
            parity = int(line[39:42])
            if (not all(math.isfinite(x) and abs(x) <= 100_000 for x in xyz) or
                    element not in LIGAND_ELEMENTS or mass_difference != 0 or charge_code not in charge_codes or
                    parity not in {0, 1, 2}):
                raise ValueError(f"SDF record {ridx}: invalid atom {i}")
            map_value = line[60:63].strip()
            map_tag = map_value if map_value and map_value != "0" else None
            atoms.append({"sdf_atom_index": i, "atom_name": f"L{i + 1}", "name_generated": True,
                          "atom_map_tag": map_tag,
                          "element": element, "hydrogen": element == "H",
                          "formal_charge": charge_codes[charge_code], "declared_parity": parity,
                          "coordinate_A": xyz})
        for line in lines[4 + na:4 + na + nb]:
            a, b, order = int(line[:3]) - 1, int(line[3:6]) - 1, int(line[6:9])
            stereo = int(line[9:12])
            if (a == b or not 0 <= a < na or not 0 <= b < na or order not in {1, 2, 3, 4} or
                    stereo not in {0, 1, 6} or (stereo and order != 1)):
                raise ValueError(f"SDF record {ridx}: invalid bond")
            bonds.append([a, b, order])
        if len({tuple(sorted(x[:2])) for x in bonds}) != len(bonds):
            raise ValueError(f"SDF record {ridx}: repeated bond")
        ended = False
        assigned_charge: set[int] = set()
        cursor = 4 + na + nb
        while cursor < len(lines):
            line = lines[cursor]
            if line.startswith("M  END"):
                ended = True
                break
            if line.startswith("A  "):
                fields = line.split()
                if len(fields) != 2 or cursor + 1 >= len(lines):
                    raise ValueError(f"SDF record {ridx}: malformed atom alias")
                site = int(fields[1]) - 1
                alias = lines[cursor + 1].strip()
                if (not 0 <= site < na or not alias or len(alias) > 32 or
                        atoms[site]["name_generated"] is False):
                    raise ValueError(f"SDF record {ridx}: invalid or repeated atom alias")
                atoms[site]["atom_name"] = alias
                atoms[site]["name_generated"] = False
                cursor += 2
                continue
            if line.startswith(("M  ISO", "M  RAD")):
                raise ValueError(f"SDF record {ridx}: isotope or radical unsupported")
            if line.startswith("M  CHG"):
                parts = line.split()
                count = int(parts[2])
                if not 1 <= count <= na or len(parts) != 3 + 2 * count:
                    raise ValueError(f"SDF record {ridx}: malformed formal-charge record")
                for j in range(count):
                    site, charge = int(parts[3 + 2 * j]) - 1, int(parts[4 + 2 * j])
                    if not 0 <= site < na or not -3 <= charge <= 3 or site in assigned_charge:
                        raise ValueError(f"SDF record {ridx}: invalid formal charge")
                    atoms[site]["formal_charge"] = charge
                    assigned_charge.add(site)
            cursor += 1
        if not ended:
            raise ValueError(f"SDF record {ridx}: missing M  END")
        out.append({"index": ridx, "title": lines[0][:120], "atom_count": na,
                    "heavy_atom_count": sum(x["element"] != "H" for x in atoms),
                    "hydrogen_count": sum(x["element"] == "H" for x in atoms),
                    "has_3d": lines[1][20:22].strip().upper() == "3D",
                    "atoms": atoms, "bonds": bonds})
    return out


def inspect(store: Any, handle: str) -> dict[str, Any]:
    meta = store.meta(handle)
    if (meta["kind"], meta["schema"]) != ("chemical_raw_input", "chemical_raw_input@1"):
        raise invalid("not a chemical raw input")
    kind = meta["summary"]["input_kind"]
    raw, fmt = _bytes(store, handle, kind)
    basic = {"schema": "chemical_raw_inspection@1", "handle": handle, "kind": kind,
             "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if kind == "ligand_sdf":
        return {**basic, "records": [{k: v for k, v in r.items() if k not in {"atoms", "bonds"}}
                                      for r in _sdf_records(raw.decode())]}
    if kind == "receptor":
        st = _gemmi(raw.decode(), fmt)
        return {**basic, "model_numbers": [x.num for x in st],
                "models": [{"model_number": m.num, "atom_count": m.count_atom_sites(),
                            "water_atoms": sum(len(r) for c in m for r in c if r.is_water()),
                            "hydrogen_atoms": sum(a.element.name.upper() == "H" for c in m for r in c for a in r)}
                           for m in st], "connectivity": "pdb_conect" if fmt == "pdb" else "sidecar_required"}
    return basic


def receptor_atoms(store: Any, handle: str, model_number: int) -> list[dict[str, Any]]:
    if type(model_number) is not int or model_number < 1:
        raise invalid("receptor model number must be a positive integer")
    raw, fmt = _bytes(store, handle, "receptor")
    st = _gemmi(raw.decode(), fmt)
    selected = [m for m in st if m.num == model_number]
    if len(selected) != 1:
        raise invalid("exact receptor model unavailable or ambiguous")
    rows = []
    for chain in selected[0]:
        for residue in chain:
            rr = _res_ref(chain, residue, selected[0].num)
            for atom in residue:
                coord = [atom.pos.x, atom.pos.y, atom.pos.z]
                if not all(math.isfinite(x) and abs(x) <= 100_000 for x in coord):
                    raise invalid("receptor coordinate nonfinite or out of range", detail={"residue": rr})
                rows.append({"ref": {"structure_handle": handle, "residue": rr, "atom_name": atom.name,
                                      "altloc": atom.altloc.strip("\0 "), "element": atom.element.name,
                                      "site_index": len(rows)}, "coordinate_A": coord,
                             "element": atom.element.name, "water": residue.is_water(),
                             "serial": atom.serial, "het_flag": residue.het_flag})
    if not 1 <= len(rows) <= MAX_RECEPTOR:
        raise invalid("receptor atom count exceeds supported limit")
    return rows


def receptor_atom_page(store: Any, handle: str, model_number: int, offset: int, limit: int) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise invalid("invalid receptor atom page")
    rows = receptor_atoms(store, handle, model_number)
    return {"schema": "chemical_staging_atom_page@1", "input_handle": handle,
            "model_number": model_number, "total": len(rows), "offset": offset, "limit": limit,
            "rows": [{k: r[k] for k in ("ref", "coordinate_A", "element", "water")}
                     for r in rows[offset:offset + limit]]}


def _strict_ref(value: Any, source: str) -> dict[str, Any]:
    try:
        ref = AtomRefV1.model_validate(value, strict=True).model_dump()
    except ValueError as exc:
        raise invalid("invalid complete chemical atom reference") from exc
    if ref != value or ref["structure_handle"] != source:
        raise invalid("atom reference belongs to another source or is incomplete")
    return ref


def _strict_residue(value: Any) -> dict[str, Any]:
    try:
        residue = CompleteResidueRef.model_validate(value, strict=True).model_dump()
    except ValueError as exc:
        raise invalid("invalid complete chemical residue identity") from exc
    if residue != value:
        raise invalid("chemical residue identity has unsupported fields")
    return residue


def _source_rows(store: Any, req: dict[str, Any]) -> tuple[list[dict[str, Any]], bytes | None, str]:
    if req["mode"] == "create_new":
        handle = req["receptor_input_handle"]
        raw, fmt = _bytes(store, handle, "receptor")
        return receptor_atoms(store, handle, req["receptor_model_number"]), raw if fmt == "pdb" else None, handle
    handle = req["complex_handle"]
    if type(req["complex_model_number"]) is not int or req["complex_model_number"] < 1:
        raise invalid("complex model number must be a positive integer")
    meta = store.meta(handle)
    if (meta["kind"], meta["schema"]) not in {("structure", "structure_selection@2"),
                                               ("prepared_structure", "prepared_structure@1")}:
        raise invalid("attach requires one exact prepared complex source kind/schema")
    # M29 spec 5.2: one place for the preview route, the prolif_prepare_v1 submission and the M13 plan.
    reject_if_repaired(store, handle)
    st = _parse(ToolContext(store=store, call_id="chemical_preview"), handle)
    if st[0].num != req["complex_model_number"]:
        raise invalid("complex model does not match exact selected source")
    rows = []
    for chain in st[0]:
        for residue in chain:
            rr = _res_ref(chain, residue, st[0].num)
            for atom in residue:
                rows.append({"ref": {"structure_handle": handle, "residue": rr, "atom_name": atom.name,
                                      "altloc": atom.altloc.strip("\0 "), "element": atom.element.name,
                                      "site_index": len(rows)}, "coordinate_A": [atom.pos.x, atom.pos.y, atom.pos.z],
                             "element": atom.element.name, "water": residue.is_water(),
                             "serial": atom.serial, "het_flag": residue.het_flag})
    if len(rows) > MAX_RECEPTOR + MAX_LIGAND:
        raise invalid("complex atom count exceeds supported limit")
    # Attach uses the already-reviewed exact selected-source AtomRef catalog.
    # If source bytes cannot be reconciled to native viewer rows, the selected
    # ligand map is unavailable rather than guessed from a second traversal.
    catalog = atom_rows(store, handle)
    if (catalog["total"] != len(rows) or any(item["ref"] != row["ref"] or
                                              item["coordinate_A"] != row["coordinate_A"]
                                              for item, row in zip(catalog["rows"], rows, strict=True))):
        raise invalid("attach source AtomRef catalog reconciliation failed")
    return rows, None, handle


def _bonds(store: Any, req: dict[str, Any], rows: list[dict[str, Any]], raw_pdb: bytes | None,
           source: str) -> list[list[int]]:
    conn = req["connectivity"]
    if type(conn) is not dict or set(conn) != {"kind", "sidecar_handle"}:
        raise invalid("connectivity selection incomplete")
    if conn["kind"] == "pdb_conect":
        if raw_pdb is None or conn["sidecar_handle"] is not None:
            raise invalid("PDB CONECT requires original receptor PDB")
        ids = [r["serial"] for r in rows]
        if any(type(x) is not int or x <= 0 for x in ids) or len(set(ids)) != len(ids):
            raise invalid("PDB serials are ambiguous for CONECT")
        lookup = {x: i for i, x in enumerate(ids)}
        pairs: set[tuple[int, int]] = set()
        for line in raw_pdb.decode().splitlines():
            if not line.startswith("CONECT"):
                continue
            try:
                values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
            except ValueError as exc:
                raise invalid("malformed PDB CONECT serial") from exc
            for second in values[1:]:
                if values[0] not in lookup or second not in lookup or values[0] == second:
                    raise invalid("dangling or self PDB CONECT")
                pairs.add(tuple(sorted((lookup[values[0]], lookup[second]))))
    elif conn["kind"] == "sidecar":
        raw, _ = _bytes(store, conn["sidecar_handle"], "receptor_bonds")
        obj = json.loads(raw)
        if (type(obj) is not dict or obj.get("schema") != "receptor_bonds@1" or
                obj.get("complete") is not True or type(obj.get("bonds")) is not list or
                obj.get("source_handle", obj.get("receptor_input_handle")) != source):
            raise invalid("incomplete or source-mismatched bond sidecar")
        lookup = {json.dumps(r["ref"], sort_keys=True): i for i, r in enumerate(rows)}
        if len(lookup) != len(rows):
            raise invalid("ambiguous source atom identities")
        pairs = set()
        for bond in obj["bonds"]:
            if type(bond) is not dict or set(bond) != {"first", "second"}:
                raise invalid("invalid sidecar bond")
            a, b = _strict_ref(bond["first"], source), _strict_ref(bond["second"], source)
            x, y = lookup.get(json.dumps(a, sort_keys=True)), lookup.get(json.dumps(b, sort_keys=True))
            if x is None or y is None or x == y:
                raise invalid("dangling/self sidecar bond")
            pair = tuple(sorted((x, y)))
            if pair in pairs:
                raise invalid("duplicate sidecar bond")
            pairs.add(pair)
    else:
        raise invalid("unsupported receptor connectivity")
    if not 1 <= len(pairs) <= MAX_BONDS:
        raise invalid("empty or oversized receptor connectivity")
    return [list(x) for x in sorted(pairs)]


def _protein_graph_blockers(rows: list[dict[str, Any]], bonds: list[list[int]],
                            selected_ligand: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Check known backbone and declared merged-cap edges by exact source site.

    These checks do not infer missing chemistry or impose an Amber side-chain
    template. Native conversion still checks valence, H vertices and bond order.
    """
    edges = {tuple(sorted(pair)) for pair in bonds}
    residues: dict[str, tuple[dict[str, Any], dict[str, list[int]]]] = {}
    for site, row in enumerate(rows):
        if row["water"] or row["ref"]["residue"] == selected_ligand:
            continue
        residue = row["ref"]["residue"]
        key = json.dumps(residue, sort_keys=True)
        if key not in residues:
            residues[key] = (residue, {})
        residues[key][1].setdefault(row["ref"]["atom_name"], []).append(site)
    blockers = []
    for residue, names in residues.values():
        def blocked(code: str, message: str, sites: list[int]) -> None:
            blockers.append({"code": code, "message": message,
                             "atoms": [rows[site]["ref"] for site in sites[:5]]})

        duplicated = [site for sites in names.values() if len(sites) > 1 for site in sites]
        if duplicated:
            blocked("duplicate_receptor_atom_name", "Duplicate names prevent exact residue graph checks",
                    duplicated)
            continue
        if not {"N", "CA", "C", "O"} <= names.keys():
            continue  # missing-backbone inventory is reported separately
        for a, b in (("N", "CA"), ("CA", "C"), ("C", "O")):
            if tuple(sorted((names[a][0], names[b][0]))) not in edges:
                blocked("missing_backbone_bond", f"Supplied {a}-{b} backbone bond missing",
                        [names[a][0], names[b][0]])
        if set(names) & {"CAY", "CY", "OY"}:
            cap = {"CAY", "CY", "OY"}
            if not cap <= names.keys():
                blocked("incomplete_terminal_cap", "Merged CAY/CY/OY cap atom inventory incomplete",
                        [i for atom in cap & names.keys() for i in names[atom]])
            else:
                expected = {tuple(sorted((names[a][0], names[b][0])))
                            for a, b in (("CAY", "CY"), ("CY", "OY"), ("CY", "N"))}
                attached_h = [other for pair in edges if names["CAY"][0] in pair
                              for other in pair if other != names["CAY"][0] and
                              rows[other]["element"].upper() == "H"]
                if not expected <= edges or len(attached_h) != 3:
                    blocked("terminal_cap_graph", "Merged terminal cap bonds differ from the declared form",
                            [names[a][0] for a in cap])
        if residue["resname"] in {"HSD", "HID", "HSE", "HIE", "HSP", "HIP", "HIS"}:
            ring = ("CG", "ND1", "CE1", "NE2", "CD2")
            if not {"CB", *ring} <= names.keys():
                blocked("histidine_ring_incomplete", "Histidine ring nitrogens unavailable",
                        [i for atom in ("CB", *ring) if atom in names for i in names[atom]])
                continue
            required_ring = {tuple(sorted((names[a][0], names[b][0])))
                             for a, b in (*zip(ring, ring[1:] + ring[:1]), ("CB", "CG"))}
            if not required_ring <= edges:
                blocked("histidine_ring_graph", "Supplied histidine five-cycle/CB attachment incomplete",
                        [names[a][0] for a in ring])
            attached = {}
            for atom_name in ("ND1", "NE2"):
                site = names[atom_name][0]
                attached[atom_name] = sum(rows[other]["element"].upper() == "H" for pair in edges
                                          if site in pair for other in pair if other != site)
            expected_h = {"HSD": (1, 0), "HID": (1, 0), "HSE": (0, 1), "HIE": (0, 1),
                          "HSP": (1, 1), "HIP": (1, 1)}.get(residue["resname"])
            observed = (attached["ND1"], attached["NE2"])
            if any(count > 1 for count in observed) or expected_h is not None and observed != expected_h:
                blocked("histidine_alias_graph", "Histidine label conflicts with supplied ring-H graph",
                        [names["ND1"][0], names["NE2"][0]])
    return blockers


def _terminal_extension_inventory(rows: list[dict[str, Any]], bonds: list[list[int]],
                                  selected_ligand: dict[str, Any] | None,
                                  declarations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve named terminal extensions into exact source sites and graph edges."""
    by_residue: dict[str, tuple[dict[str, Any], dict[str, list[int]]]] = {}
    chains: dict[str, list[str]] = {}
    for site, row in enumerate(rows):
        residue = row["ref"]["residue"]
        if row["water"] or residue == selected_ligand:
            continue
        key = json.dumps(residue, sort_keys=True)
        if key not in by_residue:
            by_residue[key] = (residue, {})
            chain = json.dumps([residue["model_number"], residue["chain_auth"],
                                residue["chain_label"]])
            chains.setdefault(chain, []).append(key)
        by_residue[key][1].setdefault(row["ref"]["atom_name"], []).append(site)
    terminal: dict[str, set[str]] = {}
    edges = {tuple(sorted(pair)) for pair in bonds}
    blockers: list[dict[str, Any]] = []
    for members in chains.values():
        terminal.setdefault(members[0], set()).add("N")
        terminal.setdefault(members[-1], set()).add("C")
        for former, latter in pairwise(members):
            former_c = by_residue[former][1].get("C", [])
            latter_n = by_residue[latter][1].get("N", [])
            if (len(former_c) != 1 or len(latter_n) != 1 or
                    tuple(sorted((former_c[0], latter_n[0]))) not in edges):
                blockers.append({"code": "missing_peptide_bond",
                                 "message": "Consecutive protein residues lack supplied C-N connectivity",
                                 "atoms": [rows[i]["ref"] for i in former_c[:1] + latter_n[:1]]})
    declared: dict[str, dict[str, Any]] = {}
    for item in declarations:
        if (type(item) is not dict or set(item) != {"residue", "atom_names", "approve_supplied_graph"} or
                type(item["atom_names"]) is not list or not item["atom_names"] or
                any(type(name) is not str or not name for name in item["atom_names"]) or
                len(set(item["atom_names"])) != len(item["atom_names"]) or
                type(item["approve_supplied_graph"]) is not bool):
            raise invalid("invalid terminal extension declaration")
        residue = _strict_residue(item["residue"])
        key = json.dumps(residue, sort_keys=True)
        if (key in declared or key not in by_residue or key not in terminal or
                residue["resname"] not in AMINO):
            raise invalid("terminal extension residue is missing, repeated, or not a supported chain terminus")
        declared[key] = item
    known_names = {key: sorted(set(names) & {"CAY", "CY", "OY"})
                   for key, (_, names) in by_residue.items() if set(names) & {"CAY", "CY", "OY"}}
    inventory = []
    for key in dict.fromkeys([*known_names, *declared]):
        residue, names = by_residue[key]
        item = declared.get(key)
        selected_names = sorted(item["atom_names"] if item else known_names[key])
        known = set(known_names.get(key, []))
        if not known <= set(selected_names) or set(selected_names) & {"N", "CA", "C", "O"}:
            raise invalid("terminal extension omits known cap sites or includes backbone anchors")
        if any(name not in names or len(names[name]) != 1 for name in selected_names):
            raise invalid("terminal extension names do not resolve uniquely to supplied AtomRefs")
        declared_sites = {names[name][0] for name in selected_names}
        if not any(rows[site]["element"].upper() != "H" for site in declared_sites):
            raise invalid("terminal extension requires at least one named heavy atom")
        # Attached H vertices are part of the extension inventory regardless
        # of source naming (HY1/HY2/HY3 are not a required template).
        sites = set(declared_sites)
        for a, b in edges:
            if a in declared_sites and rows[b]["element"].upper() == "H" and rows[b]["ref"]["residue"] == residue:
                sites.add(b)
            if b in declared_sites and rows[a]["element"].upper() == "H" and rows[a]["ref"]["residue"] == residue:
                sites.add(a)
        extension_edges = sorted(pair for pair in edges if pair[0] in sites and pair[1] in sites)
        attachment_edges = sorted(pair for pair in edges if (pair[0] in sites) != (pair[1] in sites))
        reached = {min(sites)}
        while True:
            enlarged = reached | {other for a, b in extension_edges for source, other in ((a, b), (b, a))
                                  if source in reached}
            if enlarged == reached:
                break
            reached = enlarged
        anchor = None
        if len(attachment_edges) == 1:
            a, b = attachment_edges[0]
            outside = b if a in sites else a
            candidate = rows[outside]["ref"]["atom_name"]
            if (rows[outside]["ref"]["residue"] == residue and candidate in terminal.get(key, set()) and
                    names.get(candidate) == [outside]):
                anchor = candidate
        bonds_as_refs = lambda pairs: [{"first": rows[a]["ref"], "second": rows[b]["ref"]} for a, b in pairs]
        inventory.append({"residue": residue, "atom_names": selected_names, "declared": item is not None,
                          "resolved_atoms": [rows[site]["ref"] for site in sorted(sites)],
                          "terminal_anchor": anchor,
                          "attachment_bonds": bonds_as_refs(attachment_edges),
                          "extension_bonds": bonds_as_refs(extension_edges)})
        if item is None:
            blockers.append({"code": "terminal_extension_undeclared",
                             "message": "Declare the exact supplied terminal cap atom names",
                             "atoms": [rows[site]["ref"] for site in sorted(declared_sites)]})
        elif not item["approve_supplied_graph"]:
            blockers.append({"code": "terminal_extension_unapproved",
                             "message": "Approve this exact supplied terminal graph",
                             "atoms": [rows[site]["ref"] for site in sorted(declared_sites)]})
        if anchor is None or reached != sites:
            blockers.append({"code": "terminal_extension_graph",
                             "message": "Terminal extension must be connected and have one supplied bond to terminal N or C",
                             "atoms": [rows[site]["ref"] for site in sorted(sites)][:20]})
    return inventory, blockers


def preview(store: Any, req: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    if type(req) is not dict or req.get("schema") != "chemical_prepare_request@1" or req.get("mode") not in {"create_new", "attach_existing"}:
        raise invalid("invalid chemical preparation request mode/schema")
    mode = req["mode"]
    required = ({"schema", "mode", "receptor_input_handle", "receptor_model_number", "connectivity",
                 "ligand_sdf_handle", "sdf_record_index", "ligand_instance", "terminal_extensions", "acknowledgement"}
                if mode == "create_new" else
                {"schema", "mode", "complex_handle", "complex_model_number", "selected_ligand",
                 "connectivity", "ligand_sdf_handle", "sdf_record_index", "hydrogen_policy", "mapping",
                 "terminal_extensions", "acknowledgement"})
    if strict and set(req) != required or not strict and set(req) - required:
        raise invalid("chemical preparation fields incomplete or unsupported")
    if mode == "attach_existing" and not strict:
        req = {**req, "mapping": req.get("mapping", [])}
    rows, raw_pdb, source = _source_rows(store, req)
    sdf_raw, _ = _bytes(store, req["ligand_sdf_handle"], "ligand_sdf")
    records = _sdf_records(sdf_raw.decode())
    index = req["sdf_record_index"]
    if type(index) is not int or not 0 <= index < len(records):
        raise invalid("SDF record index unavailable")
    ligand = records[index]
    if not ligand["has_3d"]:
        raise invalid("selected SDF record declares no 3D coordinates")
    bonds = _bonds(store, req, rows, raw_pdb, source)
    blockers = []
    ack = req.get("acknowledgement")
    if type(ack) is not dict or set(ack) != ACK_KEYS or ack.get("schema") != "chemical_preparation_ack@1":
        raise invalid("preparation acknowledgement fields incomplete")
    if (type(ack["description"]) is not str or len(ack["description"].encode()) > 500 or
            ack["ph_annotation"] is not None and (type(ack["ph_annotation"]) not in (int, float) or
                                                  not math.isfinite(ack["ph_annotation"]) or
                                                  not 0 <= ack["ph_annotation"] <= 14)):
        raise invalid("invalid preparation annotation")
    for key in ACK_KEYS - {"schema", "description", "ph_annotation"}:
        if type(ack[key]) is not bool:
            raise invalid("preparation acknowledgement must be explicit boolean")
        if not ack[key]:
            blockers.append({"code": key, "message": "Explicit prepared-graph acknowledgement required", "atoms": []})
    if type(req.get("terminal_extensions")) is not list:
        raise invalid("terminal extension declarations must be a list")
    selected_ligand = req.get("selected_ligand") if mode == "attach_existing" else None
    if selected_ligand is not None:
        _strict_residue(selected_ligand)
    receptor = [r for r in rows if not r["water"] and r["ref"]["residue"] != selected_ligand]
    blockers.extend(_protein_graph_blockers(rows, bonds, selected_ligand))
    by_residue: dict[str, tuple[dict[str, Any], set[str]]] = {}
    for row in receptor:
        residue = row["ref"]["residue"]
        key = json.dumps(residue, sort_keys=True)
        if key not in by_residue:
            by_residue[key] = (residue, set())
        by_residue[key][1].add(row["ref"]["atom_name"])
    for residue, names in by_residue.values():
        absent = {"N", "CA", "C", "O"} - names
        if absent:
            blockers.append({"code": "missing_backbone", "message": f"Missing backbone atoms: {sorted(absent)}",
                             "atoms": [r["ref"] for r in receptor if r["ref"]["residue"] == residue][:5]})
    terminal_extensions, extension_blockers = _terminal_extension_inventory(
        rows, bonds, selected_ligand, req["terminal_extensions"])
    blockers.extend(extension_blockers)
    mapped = []
    excluded_original_ligand_hydrogens: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    if mode == "attach_existing":
        if req.get("hydrogen_policy") not in {"map_existing", "replace_from_sdf"}:
            raise invalid("unsupported ligand hydrogen policy")
        choices = req["mapping"]
        if type(choices) is not list:
            raise invalid("ligand mapping must be an array")
        used_sdf: set[int] = set(); used_sites: set[int] = set()
        for choice in choices:
            if type(choice) is not dict or set(choice) != {"sdf_atom_index", "source_atom"}:
                raise invalid("invalid ligand mapping row")
            i = choice["sdf_atom_index"]
            if type(i) is not int or not 0 <= i < len(ligand["atoms"]) or i in used_sdf:
                raise invalid("duplicate or out-of-range SDF mapping")
            ref = _strict_ref(choice["source_atom"], source)
            site = ref["site_index"]
            if (site < 0 or site >= len(rows) or rows[site]["ref"] != ref or
                    ref["residue"] != selected_ligand or site in used_sites or
                    ref["element"].upper() != ligand["atoms"][i]["element"].upper()):
                raise invalid("source atom mapping identity/element mismatch")
            discrepancy = math.dist(rows[site]["coordinate_A"], ligand["atoms"][i]["coordinate_A"])
            if discrepancy > .002:
                blockers.append({"code": "coordinate_discrepancy", "message": "SDF/source atom discrepancy exceeds 0.002 Å", "atoms": [ref]})
            mapped.append({**choice, "discrepancy_A": discrepancy})
            used_sdf.add(i); used_sites.add(site)
        required_indices = {a["sdf_atom_index"] for a in ligand["atoms"]
                            if a["element"] != "H" or req["hydrogen_policy"] == "map_existing"}
        if required_indices - used_sdf or used_sdf - required_indices:
            blockers.append({"code": "ligand_mapping_incomplete", "message": "Map every required selected SDF atom", "atoms": []})
        source_ligand = [r for r in rows if r["ref"]["residue"] == selected_ligand]
        required_source_sites = {r["ref"]["site_index"] for r in source_ligand
                                 if r["element"].upper() != "H" or req["hydrogen_policy"] == "map_existing"}
        if req["hydrogen_policy"] == "replace_from_sdf":
            excluded_original_ligand_hydrogens = [r["ref"] for r in source_ligand
                                                  if r["element"].upper() == "H"]
        if used_sites != required_source_sites:
            missing_sites = required_source_sites - used_sites
            blockers.append({"code": "ligand_source_inventory_mismatch",
                             "message": "Every required existing ligand site must map exactly once; only explicitly replaced H may be excluded",
                             "atoms": [r["ref"] for r in source_ligand
                                       if r["ref"]["site_index"] in missing_sites][:20]})
        name_counts = Counter(r["ref"]["atom_name"] for r in source_ligand)
        for atom in ligand["atoms"]:
            i = atom["sdf_atom_index"]
            if i in used_sdf:
                continue
            supplied_name = None if atom["name_generated"] else atom["atom_name"]
            tag = atom["atom_map_tag"]
            matches = [r for r in source_ligand if r["element"].upper() == atom["element"].upper()
                       and ((supplied_name is not None and r["ref"]["atom_name"] == supplied_name)
                            or (tag is not None and r["ref"]["atom_name"] == tag))]
            if len(matches) == 1 and name_counts[matches[0]["ref"]["atom_name"]] == 1:
                proposed = matches[0]
                check_discrepancy = math.dist(proposed["coordinate_A"], atom["coordinate_A"])
                if check_discrepancy <= .002:
                    proposals.append({"sdf_atom_index": i, "candidates": [{"source_atom": proposed["ref"],
                                                                             "discrepancy_A": check_discrepancy}],
                                      "reason": "exact_unique_supplied_name_or_map_tag"})
    else:
        _strict_residue(req.get("ligand_instance"))
        if req["ligand_instance"]["model_number"] != req["receptor_model_number"] or any(r["ref"]["residue"] == req["ligand_instance"] for r in rows):
            raise invalid("new ligand instance model or identity collides")
    if any(r["ref"]["altloc"] for r in receptor):
        blockers.append({"code": "alternate_location", "message": "Unresolved receptor alternate atom state", "atoms": [r["ref"] for r in receptor if r["ref"]["altloc"]][:5]})
    bad = [r for r in receptor if (r["ref"]["residue"]["resname"] not in AMINO or
                                  r["element"].upper() not in RECEPTOR_ELEMENTS)]
    if bad:
        blockers.append({"code": "unsupported_receptor_chemistry", "message": "Only explicit-H standard protein atoms are supported", "atoms": [r["ref"] for r in bad[:5]]})
    included = {r["ref"]["site_index"] for r in receptor}
    graph = Counter(i for a, b in bonds for i in (a, b))
    missing = [r for r in receptor if graph[r["ref"]["site_index"]] == 0]
    if missing:
        blockers.append({"code": "disconnected_receptor_atom", "message": "Supplied receptor connectivity is incomplete", "atoms": [r["ref"] for r in missing[:5]]})
    crossing = [(a, b) for a, b in bonds if (a in included) != (b in included)]
    if crossing:
        # Report the exact bonded endpoints (first five bonds) instead of an anonymous rejection.
        blockers.append({"code": "cross_excluded_bond", "message": "Water or selected ligand is covalently bonded to receptor",
                         "atoms": [rows[site]["ref"] for pair in crossing[:5] for site in pair]})
    if len(bonds) + len(ligand["bonds"]) > MAX_BONDS:
        raise invalid("combined bond count exceeds supported limit")
    result = {"schema": "chemical_preparation_preview@1", "ready": not blockers, "blockers": blockers,
              "included_receptor_atoms": len(receptor), "excluded_water_atoms": sum(r["water"] for r in rows),
              "selected_ligand_atoms": ligand["atom_count"], "ligand_atoms": ligand["atoms"],
              "ligand_mapping": mapped, "mapping_proposals": proposals,
              "excluded_original_ligand_hydrogens": excluded_original_ligand_hydrogens,
              "terminal_extensions": terminal_extensions,
              "derived_coordinate_policy": DERIVED_COORDINATE_POLICY,
              "limitations": ["Orders/charges inferred from supplied receptor connectivity; supplied protonation is unverified.",
                              "V2000 tetrahedral atom parity must agree with 3D; 3D geometry supersedes wedge/dash depiction.",
                              "Unfamiliar undeclared terminal extensions cannot be exhaustively detected; completeness is user-declared."]}
    if strict and blockers:
        raise ToolFailure(FailureClass.precondition, "chemical preparation prerequisites incomplete",
                          detail={"blockers": blockers[:20]})
    return result
