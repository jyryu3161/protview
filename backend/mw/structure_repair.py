"""M29 structure repair core: defect analysis, the splice builder, the record and its pure validator (spec 2, 3).

Pure computation over bytes (gemmi, numpy and the installed Amber14 protein template XML, read as a file located with
``importlib.util.find_spec``; OpenMM and PDBFixer are never imported here). Nothing here writes to a run.

Public API (the job, read, report and M20 modules call these):

``load_inputs(store, handle) -> RepairInputs``
    Reads one ``prepared_structure@1`` of the store's run: its coordinates bytes and format, the manifest's waters /
    hydrogens policy and the original ``structure_source`` bytes the manifest names (the gap listing lives only there,
    spec 2.3). Writes nothing. ``ToolFailure(input_invalid, reason_code structure_invalid)`` for any other object.
``analyze(inputs) -> dict``
    The defect analysis (no PDBFixer). Keys: ``model_number``, ``repairable`` (bool), ``reason_code`` (the first refusal
    code of ``REFUSAL_REASONS`` or None when repairable), ``blockers`` (every blocker, refusal order then structure
    order: ``{reason_code, residue?, chain_auth?, detail}``; ``nothing_to_repair`` is one blocker without residue),
    ``classes`` (the repair classes that would apply), ``defects`` {``chain_parts`` [{chain_auth, parts}] (chains with
    more than one part), ``side_chain_residues`` [{residue, missing_atoms}], ``terminal_oxt`` [{residue}], ``gaps``
    [{chain_auth, after_residue, before_residue, length, residues}] (gaps whose residues the file determines),
    ``nonstandard`` [{residue, to_resname}]}, ``chain_ends`` (as in the record), ``expected_added_residues``,
    ``expected_added_heavy_atoms``, ``protein_heavy_atoms_observed``, ``protein_heavy_atoms_after``,
    ``zero_occupancy_input_atoms`` {count, residues} and ``statements`` (the RP sentences whose condition holds).
    Residue references in the analysis are the INPUT identities (an MSE residue is still MSE).
``refusal(analysis) -> dict | None``
    The 422 ``repair_not_possible`` detail: ``{reason_code, blockers[, m7_reason]}``; None when repairable.
``build_repaired(inputs, added_atoms) -> (bytes, dict)``
    Splices the PDBFixer-made atoms into the prepared structure and returns the repaired mmCIF bytes and the
    ``structure_repair@1`` record (spec 3.5, exactly its keys). ``added_atoms`` rows have the shape of the worker
    output / ``8vf6-additions.pdbfixer-measured.json``: ``{residue (7 fields, MET for an MSE residue), atom_name,
    element, coordinates_A (PDBFixer precision), origin}``. Chain parts are merged (author chain order of first
    appearance, parts concatenated in input order), gap residues are inserted after their ``after_residue``, MSE
    becomes MET (SE -> SD, Se -> S, HETATM -> ATOM, coordinates kept), every input ``calc_flag`` becomes ``.``, new
    atoms are appended to their residue with coordinates rounded to ``NEW_ATOM_DECIMALS``, occupancy 1.0, B 0.0 and
    ``calc_flag`` ``c``. gemmi renumbers ``_atom_site.id`` in structure order (not a preserved field, spec 3.2). The
    result passes ``validated_repair`` by construction; same inputs give the same bytes and record.
``validated_repair(inputs, repaired_bytes, record) -> dict``
    The pure validator (spec 3.4 checks 1, 2, 3 and 5): re-derives the record from the inputs and the repaired bytes
    and compares it with ``record`` byte for byte (canonical JSON). Raises ``ToolFailure`` whose
    ``detail.reason_code`` is ``coordinates_changed`` (an observed atom's name, element, altloc, residue or coordinates
    differ by more than 1e-9 A), ``unexpected_atoms_added`` (a new atom outside the allowed residues / names, or a
    ``calc_flag`` ``c`` that is not exactly the new atoms), ``repair_identity_mismatch`` (new residues are not the
    listed gap residues in place, or the residue order is not the planned one) or ``repair_record_mismatch``
    (anything else the record states, incl. ``new_atom_rounding`` outside [0, 0.5e-4] and new coordinates that are
    not at four decimals); ``resource_exceeded`` (limit ``record_bytes``) above ``MAX_RECORD_BYTES``. The M7
    preflight (check 4) is the job module's. ``new_atom_rounding.max_abs_delta_A`` is the one value the stored bytes
    cannot re-derive (it needs the PDBFixer values); it is range-checked.
``template_heavy(resname, terminal) -> dict[str, str]``, ``fixed_method() -> dict``,
``coordinates_handle(run_id, raw) -> str``, ``m7_reason(failure) -> str``.

Record conventions: every residue reference is the REPAIRED structure's identity (an MSE residue appears as MET) except
``replaced[].from``; ``added_atoms`` is in structure order; ``chain_ends`` flags are ``None`` where the file does
not determine them (no sequence for the chain, or a PDB-format chain whose SEQRES / REMARK 465 do not account for
every residue); RP4 applies only when a flag is ``False``. Collisions: for each new heavy atom the nearest heavy atom
of each partner class outside its own residue and the directly adjacent polymer residues of its chain;
``count_lt_*`` count new atoms, ``min_pair`` is the first minimum in structure order (``None`` without a partner).
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import gemmi
import numpy as np

from . import structure_repair_constants as K
from .core.errors import FailureClass, ToolFailure
from .core.handles import HANDLE_PREFIX, canonical_json, object_sha, sha256_hex
from .openmm_bundle import FORCEFIELD_SHA256
from .tools.structural import METALS, _res_ref

# M7 (tools/openmm_method.py) codes, or its messages where it has no code; ``m7_reason`` carries them verbatim.
M7_SEQUENCE_GAP = "sequence_gap"
M7_PEPTIDE_GEOMETRY = "peptide_geometry"
M7_ALTLOC = "unresolved alternate site"
M7_ATOM_IDENTITY = "ambiguous atom identity"
M7_RESIDUE_IDENTITY = "ambiguous residue identity"
M7_COORDINATE = "invalid protein coordinate"
M7_NO_PROTEIN = "protein atom count is empty or exceeds fixed limit"
ATOM_NAME = re.compile(r"[A-Za-z0-9']{1,4}")
STANDARD = frozenset(K.STANDARD_RESIDUES)
CIF_FORMATS = ("cif", "mmcif")


@dataclass(frozen=True)
class RepairInputs:
    run_id: str
    prepared_structure: str
    model_number: int
    prepared_bytes: bytes
    prepared_fmt: str
    source_bytes: bytes
    source_fmt: str
    waters: str
    hydrogens: str


def _fail(code: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": code, **detail})


# ------------------------------------------------------------------------------------------------ inputs, template

def load_inputs(store: Any, handle: str) -> RepairInputs:
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError) as exc:
        raise _fail("structure_invalid", "structure must be a prepared_structure@1 of this run") from exc
    if (meta["kind"], meta["schema"]) != (K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA):
        raise _fail("structure_invalid", "structure must be a prepared_structure@1 of this run")
    prepared = store.load(handle)
    manifest = store.load(prepared["manifest"])
    coordinates = prepared["coordinates"]
    source = manifest["source_handle"]
    return RepairInputs(run_id=store.run_id, prepared_structure=handle, model_number=prepared["model_number"],
                        prepared_bytes=store.load(coordinates), prepared_fmt=store.meta(coordinates)["fmt"],
                        source_bytes=store.load(source), source_fmt=store.meta(source)["fmt"],
                        waters=manifest["waters"], hydrogens=manifest["hydrogens"])


def _unavailable() -> ToolFailure:
    return ToolFailure(FailureClass.precondition, "fixed OpenMM 8.6.0 CPU force field unavailable",
                       detail={"reason_code": "openmm_unavailable"})


@lru_cache(maxsize=1)
def _templates() -> dict[str, dict[str, str]]:
    spec = importlib.util.find_spec("openmm")
    if spec is None or not spec.submodule_search_locations:
        raise _unavailable()
    path = Path(next(iter(spec.submodule_search_locations))) / "app" / "data" / K.TEMPLATE_FILE
    try:
        raw = path.read_bytes()
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        raise _unavailable() from exc
    if hashlib.sha256(raw).hexdigest() != FORCEFIELD_SHA256[K.TEMPLATE_FILE]:
        raise _unavailable()
    elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
    return {node.attrib["name"]: {atom.attrib["name"]: elements[atom.attrib["type"]] for atom in node.findall("Atom")
                                  if elements[atom.attrib["type"]] not in K.HYDROGEN_ELEMENTS}
            for node in root.findall("./Residues/Residue")}


def template_heavy(resname: str, terminal: bool) -> dict[str, str]:
    """Heavy atom name -> element of the installed template M7 compares with (HIS as HID, C-terminal ``C`` form,
    MSE read as MET), in template order."""
    key = {"HIS": "HID", "MSE": "MET"}.get(resname, resname)
    found = _templates().get(("C" if terminal else "") + key)
    if found is None:
        raise ToolFailure(FailureClass.precondition, "fixed force field has no standard residue template")
    return found


def fixed_method() -> dict[str, Any]:
    return {"engine": K.ENGINE, "pdbfixer_version": K.PDBFIXER_VERSION,
            "openmm_distribution_version": K.OPENMM_VERSION, "forcefield_files_sha256": dict(FORCEFIELD_SHA256)}


def coordinates_handle(run_id: str, raw: bytes) -> str:
    return f"{HANDLE_PREFIX}{run_id}/{K.COORDINATES_KIND}/{object_sha(K.COORDINATES_KIND, K.COORDINATES_SCHEMA, raw)}"


def m7_reason(failure: ToolFailure) -> str:
    """The M7 refusal as ``detail.m7_reason``: its ``reason_code`` when it has one, else its message verbatim."""
    return failure.detail.get("reason_code") or failure.message


# ------------------------------------------------------------------------------------------------ reading

def _read(raw: bytes, fmt: str) -> gemmi.Structure:
    text = raw.decode("utf-8")
    if fmt in CIF_FORMATS:
        return gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    return gemmi.read_pdb_string(text)


def _is_polymer(res: Any) -> bool:
    """M7's polymer rule plus residues gemmi places in a polymer entity (a PDB-format HETATM MSE)."""
    return res.het_flag == "A" or res.label_seq is not None or res.entity_type == gemmi.EntityType.Polymer


def _key(ref: dict[str, Any]) -> tuple:
    return tuple(ref[name] for name in K.IDENTITY_FIELDS)


def _out(ref: dict[str, Any], mse: bool) -> dict[str, Any]:
    return {**ref, "resname": K.NONSTANDARD_REPLACEMENT["MSE"]} if mse else ref


def _parts(model: Any) -> tuple[list[str], dict[str, list[Any]]]:
    order: list[str] = []
    parts: dict[str, list[Any]] = {}
    for chain in model:
        if chain.name not in parts:
            order.append(chain.name)
        parts.setdefault(chain.name, []).append(chain)
    return order, parts


@dataclass
class _Listing:
    seq: dict[str, dict[int, list[str]]]
    asym_entity: dict[str, str]
    unobs: dict[tuple[str, int], list[dict[str, Any]]]
    seqres: dict[str, list[str]]
    remark465: dict[str, list[tuple[int, str, str]]] | None


def _cif_int(value: str) -> int | None:
    return None if gemmi.cif.is_null(value) or not re.fullmatch(r"-?\d+", value) else int(value)


def _listing(inputs: RepairInputs) -> _Listing:
    """The sequence and unobserved-residue listing of the ORIGINAL source bytes (spec 2.3)."""
    listing = _Listing({}, {}, {}, {}, {})
    text = inputs.source_bytes.decode("utf-8")
    if inputs.source_fmt in CIF_FORMATS:
        block = gemmi.cif.read_string(text).sole_block()
        for row in block.find("_entity_poly_seq.", ["entity_id", "num", "mon_id"]):
            num = _cif_int(row[1])
            if num is not None:
                listing.seq.setdefault(gemmi.cif.as_string(row[0]), {}).setdefault(num, []).append(
                    gemmi.cif.as_string(row[2]))
        for row in block.find("_struct_asym.", ["id", "entity_id"]):
            listing.asym_entity[gemmi.cif.as_string(row[0])] = gemmi.cif.as_string(row[1])
        table = block.find("_pdbx_unobs_or_zero_occ_residues.",
                           ["polymer_flag", "occupancy_flag", "auth_asym_id", "auth_seq_id", "label_asym_id",
                            "label_seq_id", "label_comp_id", "?PDB_ins_code", "?PDB_model_num", "?auth_comp_id"])
        for row in table:
            model = _cif_int(row[8]) if row.has(8) else None
            label = _cif_int(row[5])
            if row[0] != "Y" or row[1] != "1" or label is None or (row.has(8) and model != inputs.model_number):
                continue
            icode = row[7] if row.has(7) and not gemmi.cif.is_null(row[7]) else ""
            listing.unobs.setdefault((gemmi.cif.as_string(row[4]), label), []).append({
                "chain_auth": gemmi.cif.as_string(row[2]), "seq_auth": _cif_int(row[3]),
                "icode": gemmi.cif.as_string(icode), "resname": gemmi.cif.as_string(row[6]),
                "auth_resname": gemmi.cif.as_string(row[9]) if row.has(9) else None})
        return listing
    header = False
    for line in text.splitlines():
        padded = line.ljust(80)
        if line.startswith("SEQRES"):
            listing.seqres.setdefault(padded[11], []).extend(padded[19:].split())
        elif line.startswith("REMARK 465") and listing.remark465 is not None:
            if padded[10:].split()[:4] == ["M", "RES", "C", "SSSEQI"]:
                header = True
                continue
            if not header or not padded[10:].strip():
                continue
            model, name, chain, num, icode = (padded[10:14].strip(), padded[15:18].strip(), padded[19],
                                              padded[21:26].strip(), padded[26].strip())
            if not re.fullmatch(r"-?\d+", num) or not name or (model and not model.isdigit()):
                listing.remark465 = None   # a malformed listing determines nothing
                continue
            if model and int(model) != inputs.model_number:
                continue
            listing.remark465.setdefault(chain, []).append((int(num), icode, name))
    return listing


# ------------------------------------------------------------------------------------------------ analysis

def _pdb_plan(polymer: list[dict[str, Any]], listing: _Listing, chain: str) -> dict[str, Any]:
    """Place a PDB-format chain's REMARK 465 rows between its observed residues by author order; the placement counts
    only when the observed and listed names together are exactly the chain's SEQRES."""
    keys = [(ref["seq_auth"], ref["icode"]) for ref in polymer]
    rows = (listing.remark465 or {}).get(chain, [])
    increasing = listing.remark465 is not None and all(a < b for a, b in pairwise(keys))
    between = {i: [row for row in rows if keys[i - 1] < row[:2] < keys[i]] for i in range(1, len(keys))}
    before = [row for row in rows if row[:2] < keys[0]]
    after = [row for row in rows if row[:2] > keys[-1]]
    names = [row[2] for row in before]
    for i, ref in enumerate(polymer):
        names += ([row[2] for row in between[i]] if i else []) + [ref["resname"]]
    names += [row[2] for row in after]
    placed = len(before) + len(after) + sum(len(v) for v in between.values())
    consistent = (increasing and bool(listing.seqres.get(chain)) and placed == len(rows)
                  and names == listing.seqres[chain])
    return {"increasing": increasing, "between": between, "consistent": consistent,
            "start": not before if consistent else None, "end": not after if consistent else None}


def _cn(prev: Any, cur: Any) -> float | None:
    c = next((a for a in prev if a.name == "C"), None)
    n = next((a for a in cur if a.name == "N"), None)
    return None if c is None or n is None else c.pos.dist(n.pos)


def analyze(inputs: RepairInputs) -> dict[str, Any]:
    model = _read(inputs.prepared_bytes, inputs.prepared_fmt)[0]
    listing = _listing(inputs)
    order, parts = _parts(model)
    num = model.num
    blockers: list[dict[str, Any]] = []
    side_chain: list[dict[str, Any]] = []
    oxt: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    nonstandard: list[dict[str, Any]] = []
    chain_ends: list[dict[str, Any]] = []
    zero = {"count": 0, "residues": []}
    observed_heavy = 0
    added_heavy = 0
    seen: set[tuple] = set()

    def block(code: str, residue: dict | None = None, chain: str | None = None, **detail: Any) -> None:
        item: dict[str, Any] = {"reason_code": code}
        if residue is not None:
            item["residue"] = residue
        if chain is not None:
            item["chain_auth"] = chain
        item["detail"] = detail
        blockers.append(item)

    for name in order:
        residues = [(chain, res) for chain in parts[name] for res in chain]
        for chain, res in residues:
            zero_here = sum(1 for atom in res if atom.occ == 0)
            if zero_here:
                zero["count"] += zero_here
                zero["residues"].append(_res_ref(chain, res, num))
        polymer = [(chain, res) for chain, res in residues if _is_polymer(res)]
        if not polymer:
            continue
        labels = sorted({res.subchain or "" for _, res in polymer})
        if len(labels) > 1:
            block("chain_identity_duplicate", chain=name, label_chains=labels)
        refs = [_res_ref(chain, res, num) for chain, res in polymer]
        for index, ((chain, res), ref) in enumerate(zip(polymer, refs)):
            mse = res.name == "MSE"
            out_key = _key(_out(ref, mse))
            if out_key in seen:
                block("m7_condition_unsupported", ref, m7_reason=M7_RESIDUE_IDENTITY)
            seen.add(out_key)
            names: list[str] = []
            heavy: dict[str, str] = {}
            for atom in res:
                atom_name, element = atom.name, atom.element.name
                if mse and atom_name == "SE":
                    atom_name, element = "SD", ("S" if element == "Se" else element)
                names.append(atom_name)
                if atom.altloc not in ("\0", " ", ""):
                    block("m7_condition_unsupported", ref, m7_reason=M7_ALTLOC)
                if not all(math.isfinite(x) and abs(x) <= K.COORDINATE_ABS_MAX_A
                           for x in (atom.pos.x, atom.pos.y, atom.pos.z)):
                    block("m7_condition_unsupported", ref, m7_reason=M7_COORDINATE)
                if element not in K.HYDROGEN_ELEMENTS:
                    heavy[atom_name] = element
                    observed_heavy += 1
            if len(set(names)) != len(names) or any(not ATOM_NAME.fullmatch(n) for n in names):
                block("m7_condition_unsupported", ref, m7_reason=M7_ATOM_IDENTITY)
            if res.name not in STANDARD and not mse:
                # no template check for this residue, but the link to the previous residue (a gap before it) is
                # still checked below so the preflight lists every blocker
                block("unsupported_residue", ref, resname=res.name, in_gap=False)
            else:
                if mse:
                    nonstandard.append({"residue": ref, "to_resname": K.NONSTANDARD_REPLACEMENT["MSE"]})
                last = index == len(polymer) - 1
                template = template_heavy(res.name, last)
                extra = sorted(n for n, el in heavy.items() if n not in template or el not in K.HEAVY_ELEMENTS)
                if extra:
                    block("unexpected_atoms", ref, atoms=extra)
                missing_backbone = [n for n in K.BACKBONE_ATOMS if n not in heavy]
                if missing_backbone:
                    block("backbone_atoms_missing", ref, missing=missing_backbone)
                else:
                    missing = [n for n in template
                               if n not in heavy and n not in K.BACKBONE_ATOMS and n != K.TERMINAL_OXT]
                    if missing:
                        side_chain.append({"residue": ref, "missing_atoms": missing})
                        added_heavy += len(missing)
                    if last and K.TERMINAL_OXT not in heavy:
                        oxt.append({"residue": ref})
                        added_heavy += 1
            if not index:
                continue
            (_, prev), prev_ref = polymer[index - 1], refs[index - 1]
            distance = _cn(prev, res)
            if prev.label_seq is not None and res.label_seq is not None:
                step = res.label_seq - prev.label_seq
                if step < 1:
                    block("m7_condition_unsupported", ref, m7_reason=M7_SEQUENCE_GAP)
                elif step == 1:
                    if distance is not None and not K.PEPTIDE_CN_RANGE_A[0] <= distance <= K.PEPTIDE_CN_RANGE_A[1]:
                        block("m7_condition_unsupported", ref, m7_reason=M7_PEPTIDE_GEOMETRY, distance_A=distance)
                elif prev.subchain == res.subchain:
                    _label_gap(listing, name, num, prev, res, prev_ref, ref, gaps, block)
                continue
            if distance is None or K.PEPTIDE_CN_RANGE_A[0] <= distance <= K.PEPTIDE_CN_RANGE_A[1]:
                continue
            if (prev.subchain or "") != (res.subchain or ""):
                continue
            plan = _pdb_plan(refs, listing, name) if inputs.source_fmt not in CIF_FORMATS else None
            rows = plan["between"][index] if plan and plan["increasing"] else []
            if not rows and res.seqid.num - prev.seqid.num in (0, 1):
                block("m7_condition_unsupported", ref, m7_reason=M7_PEPTIDE_GEOMETRY, distance_A=distance)
            elif not rows or not plan["consistent"]:
                block("gap_listing_missing", ref, name, after_residue=prev_ref, missing_label_positions=None)
            else:
                gaps.append({"chain_auth": name, "after_residue": prev_ref, "before_residue": ref,
                             "length": len(rows),
                             "residues": [{"model_number": num, "chain_auth": name, "chain_label": res.subchain or None,
                                           "seq_auth": row[0], "seq_label": None, "icode": row[1], "resname": row[2]}
                                          for row in rows]})
        chain_ends.append(_chain_end(inputs, listing, name, polymer, refs))
    for gap in gaps:
        if gap["length"] > K.MAX_GAP_RESIDUES:
            block("gap_too_long", gap["before_residue"], gap["chain_auth"], after_residue=gap["after_residue"],
                  length=gap["length"], max_gap_residues=K.MAX_GAP_RESIDUES)
        if any(_key(ref) in seen for ref in gap["residues"]):   # a listed residue that is also observed
            block("gap_listing_missing", gap["before_residue"], gap["chain_auth"], after_residue=gap["after_residue"],
                  missing_label_positions=None)
        for ref in gap["residues"]:
            if ref["resname"] not in STANDARD:
                block("unsupported_residue", ref, resname=ref["resname"], in_gap=True)
            else:
                added_heavy += len(template_heavy(ref["resname"], False))
    if not observed_heavy:
        block("m7_condition_unsupported", m7_reason=M7_NO_PROTEIN)
    after = observed_heavy + added_heavy
    if after > K.M7_ATOM_CAP:
        block("atom_limit_exceeded", protein_heavy_atoms_after=after, limit=K.M7_ATOM_CAP)
    chain_parts = [{"chain_auth": name, "parts": len(parts[name])} for name in order if len(parts[name]) > 1]
    found = {"chain_parts_merged": chain_parts, "side_chain_atoms_added": side_chain, "terminal_oxt_added": oxt,
             "internal_gap_filled": gaps, "nonstandard_replaced": nonstandard}
    classes = [name for name in K.REPAIR_CLASSES if found[name]]
    blockers.sort(key=lambda item: K.REFUSAL_REASONS.index(item["reason_code"]))
    if not blockers and not classes:
        block("nothing_to_repair")
    differs = any(end["first_is_sequence_start"] is False or end["last_is_sequence_end"] is False
                  for end in chain_ends)
    return {"model_number": num, "repairable": not blockers, "reason_code": blockers[0]["reason_code"] if blockers
            else None, "blockers": blockers, "classes": classes,
            "defects": {"chain_parts": chain_parts, "side_chain_residues": side_chain, "terminal_oxt": oxt,
                        "gaps": gaps, "nonstandard": nonstandard},
            "chain_ends": chain_ends, "expected_added_residues": sum(gap["length"] for gap in gaps),
            "expected_added_heavy_atoms": added_heavy, "protein_heavy_atoms_observed": observed_heavy,
            "protein_heavy_atoms_after": after, "zero_occupancy_input_atoms": zero,
            "statements": list(K.applicable_limitations(classes_applied=classes, chain_end_differs=differs))}


def _label_gap(listing: _Listing, name: str, num: int, prev: Any, res: Any, prev_ref: dict, ref: dict,
               gaps: list, block: Any) -> None:
    """An mmCIF internal gap: residue names from ``_entity_poly_seq``, author number / insertion code / label from
    ``_pdbx_unobs_or_zero_occ_residues``; anything not determined exactly once is ``gap_listing_missing``."""
    entity = listing.asym_entity.get(res.subchain)
    residues, missing = [], []
    for position in range(prev.label_seq + 1, res.label_seq):
        rows = listing.unobs.get((res.subchain, position), [])
        names = listing.seq.get(entity, {}).get(position, []) if entity is not None else []
        row = rows[0] if len(rows) == 1 else None
        if (row is None or len(names) != 1 or row["resname"] != names[0] or row["chain_auth"] != name
                or row["seq_auth"] is None or row["auth_resname"] not in (None, names[0])):
            missing.append(position)
            continue
        residues.append({"model_number": num, "chain_auth": name, "chain_label": res.subchain,
                         "seq_auth": row["seq_auth"], "seq_label": position, "icode": row["icode"],
                         "resname": row["resname"]})
    if missing:
        block("gap_listing_missing", ref, name, after_residue=prev_ref, missing_label_positions=missing)
        return
    gaps.append({"chain_auth": name, "after_residue": prev_ref, "before_residue": ref, "length": len(residues),
                 "residues": residues})


def _chain_end(inputs: RepairInputs, listing: _Listing, name: str, polymer: list, refs: list) -> dict[str, Any]:
    first, last = polymer[0][1], polymer[-1][1]
    start = end = None
    if inputs.source_fmt in CIF_FORMATS:
        entity = listing.asym_entity.get(first.subchain)
        numbers = listing.seq.get(entity) if entity is not None and first.subchain == last.subchain else None
        if numbers and first.label_seq is not None and last.label_seq is not None:
            start, end = first.label_seq == min(numbers), last.label_seq == max(numbers)
    else:
        plan = _pdb_plan(refs, listing, name)
        start, end = plan["start"], plan["end"]
    return {"chain_auth": name, "observed_first": refs[0], "observed_last": refs[-1],
            "first_is_sequence_start": start, "last_is_sequence_end": end}


def refusal(analysis: dict[str, Any]) -> dict[str, Any] | None:
    if analysis["repairable"]:
        return None
    detail = {"reason_code": analysis["reason_code"], "blockers": analysis["blockers"]}
    first = analysis["blockers"][0]
    if first["reason_code"] == "m7_condition_unsupported":
        detail["m7_reason"] = first["detail"]["m7_reason"]
    return detail


# ------------------------------------------------------------------------------------------------ builder

def _new_residue(ref: dict[str, Any], entity_id: str) -> Any:
    res = gemmi.Residue()
    res.name = ref["resname"]
    res.seqid = gemmi.SeqId(ref["seq_auth"], ref["icode"] or " ")
    res.subchain = ref["chain_label"] or ""
    if ref["seq_label"] is not None:
        res.label_seq = ref["seq_label"]
    res.entity_type = gemmi.EntityType.Polymer
    res.entity_id = entity_id
    res.het_flag = "A"
    return res


def _rounded(value: Any) -> float:
    return round(float(value), K.NEW_ATOM_DECIMALS) + 0.0


def _check_rows(added_atoms: Any) -> None:
    fields = {"residue", "atom_name", "element", "coordinates_A", "origin"}
    if not isinstance(added_atoms, list):
        raise _fail("unexpected_atoms_added", "added atoms must be a list")
    for row in added_atoms:
        ok = (isinstance(row, dict) and set(row) == fields and isinstance(row["residue"], dict)
              and set(row["residue"]) == set(K.IDENTITY_FIELDS) and isinstance(row["atom_name"], str)
              and isinstance(row["element"], str) and row["origin"] in K.ADDED_ATOM_ORIGINS
              and isinstance(row["coordinates_A"], list) and len(row["coordinates_A"]) == 3
              and all(type(x) in (int, float) and math.isfinite(x) for x in row["coordinates_A"]))
        if not ok:
            raise _fail("unexpected_atoms_added", "malformed added atom row")


def build_repaired(inputs: RepairInputs, added_atoms: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
    analysis = analyze(inputs)
    if not analysis["repairable"]:
        raise ToolFailure(FailureClass.input_invalid, "structure repair is not possible", detail=refusal(analysis))
    _check_rows(added_atoms)
    st = _read(inputs.prepared_bytes, inputs.prepared_fmt)
    model = st[0]
    order, parts = _parts(model)
    after = {(gap["chain_auth"], _key(gap["after_residue"])): gap["residues"]
             for gap in analysis["defects"]["gaps"]}
    merged = []
    for name in order:
        chain = gemmi.Chain(name)
        for part in parts[name]:
            for res in part:
                chain.add_residue(res)
                for ref in after.get((name, _key(_res_ref(part, res, model.num))), []):
                    chain.add_residue(_new_residue(ref, res.entity_id))
        merged.append(chain)
    while len(model):
        del model[0]
    for chain in merged:
        model.add_chain(chain)
    lookup: dict[tuple, Any] = {}
    for chain in model:
        for res in chain:
            if res.name == "MSE" and _is_polymer(res):
                res.name = K.NONSTANDARD_REPLACEMENT["MSE"]
                res.het_flag = "A"
                for atom in res:
                    if atom.name == "SE":
                        atom.name = K.REPLACED_ATOM_NAMES["MSE"]["SE"]
                        if atom.element.name == "Se":
                            atom.element = gemmi.Element("S")
            for atom in res:
                atom.calc_flag = gemmi.CalcFlag.NotSet
            lookup[_key(_res_ref(chain, res, model.num))] = res
    delta = 0.0
    for row in added_atoms:
        res = lookup.get(_key(row["residue"]))
        if res is None:
            raise _fail("unexpected_atoms_added", "an added atom names a residue outside the repaired structure")
        atom = gemmi.Atom()
        atom.name = row["atom_name"]
        atom.element = gemmi.Element(row["element"])
        position = [_rounded(x) for x in row["coordinates_A"]]
        delta = max([delta, *(abs(float(x) - y) for x, y in zip(row["coordinates_A"], position))])
        atom.pos = gemmi.Position(*position)
        atom.occ = K.NEW_ATOM_OCCUPANCY
        atom.b_iso = K.NEW_ATOM_B_ISO
        atom.calc_flag = gemmi.CalcFlag.Calculated
        res.add_atom(atom)
    raw = st.make_mmcif_document().as_string().encode("utf-8")
    return raw, _derive(inputs, analysis, raw, delta)


# ------------------------------------------------------------------------------------------------ record, validator

def validated_repair(inputs: RepairInputs, repaired_bytes: bytes, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != set(K.RECORD_KEYS):
        raise _fail("repair_record_mismatch", "repair record keys differ")
    rounding = record.get("new_atom_rounding")
    value = rounding.get("max_abs_delta_A") if isinstance(rounding, dict) else None
    if type(value) is not float or not 0.0 <= value <= 0.5 * 10 ** -K.NEW_ATOM_DECIMALS + 1e-12:
        raise _fail("repair_record_mismatch", "new-atom rounding is outside its range")
    analysis = analyze(inputs)
    if not analysis["repairable"]:
        raise _fail("repair_identity_mismatch", "the input structure is not repairable")
    derived = _derive(inputs, analysis, repaired_bytes, value)
    if canonical_json(derived) != canonical_json(record):
        raise _fail("repair_record_mismatch", "repair record differs from the one rebuilt from the structures")
    return record


def _derive(inputs: RepairInputs, analysis: dict[str, Any], raw: bytes, delta: float) -> dict[str, Any]:
    try:
        out_st = _read(raw, K.COORDINATES_FMT)
    except Exception as exc:   # any unreadable output is a changed structure
        raise _fail("coordinates_changed", "repaired structure cannot be read") from exc
    if len(out_st) != 1 or out_st[0].num != inputs.model_number:
        raise _fail("repair_identity_mismatch", "repaired structure model differs")
    out_model = out_st[0]
    if len({chain.name for chain in out_model}) != len(out_model):
        raise _fail("repair_identity_mismatch", "repaired structure keeps chain parts")
    in_model = _read(inputs.prepared_bytes, inputs.prepared_fmt)[0]
    num = in_model.num
    order, parts = _parts(in_model)
    after = {(gap["chain_auth"], _key(gap["after_residue"])): gap["residues"] for gap in analysis["defects"]["gaps"]}
    plan: list[tuple[str, Any, dict, dict, bool]] = []   # (kind, input residue, input ref, output ref, mse)
    for name in order:
        for part in parts[name]:
            for res in part:
                ref = _res_ref(part, res, num)
                mse = res.name == "MSE" and _is_polymer(res)
                plan.append(("observed", res, ref, _out(ref, mse), mse))
                plan.extend(("gap", None, gap_ref, gap_ref, False) for gap_ref in after.get((name, _key(ref)), []))
    out = [(chain, res, _res_ref(chain, res, out_model.num)) for chain in out_model for res in chain]
    if [_key(item[3]) for item in plan] != [_key(item[2]) for item in out]:
        observed = {_key(item[3]) for item in plan if item[0] == "observed"}
        if observed - {_key(item[2]) for item in out}:
            raise _fail("coordinates_changed", "an observed residue is missing or renamed")
        raise _fail("repair_identity_mismatch", "residues differ from the planned observed and gap residues")
    last = {}
    for index, (_, res, _ref, ref_out, _mse) in enumerate(plan):
        if res is None or _is_polymer(res):
            last[ref_out["chain_auth"]] = index
    terminal = set(last.values())
    added, side_chain, oxt, replaced, zero_residues = [], [], [], [], []
    heavy_rows: list[tuple[int, Any, dict, bool]] = []   # (plan index, atom, output ref, new)
    max_delta = 0.0
    cleared = zero_count = atom_count = protein_heavy = 0
    for index, ((kind, res_in, ref_in, ref_out, mse), (_chain, res_out, _)) in enumerate(zip(plan, out)):
        atoms = list(res_out)
        known = list(res_in) if res_in is not None else []
        polymer = _is_polymer(res_out)
        if kind == "observed" and (polymer != _is_polymer(res_in) or (mse and res_out.het_flag != "A")):
            raise _fail("repair_record_mismatch", "a replaced residue is not an ATOM polymer residue")
        if len(atoms) < len(known):
            raise _fail("coordinates_changed", "an observed atom is missing")
        for atom_in, atom_out in zip(known, atoms):
            name_in, element_in = atom_in.name, atom_in.element.name
            if mse and name_in == "SE":
                name_in, element_in = "SD", ("S" if element_in == "Se" else element_in)
            distance = atom_in.pos.dist(atom_out.pos)
            if (atom_out.name != name_in or atom_out.element.name != element_in or atom_out.altloc != atom_in.altloc
                    or not distance <= K.COORDINATE_TOLERANCE_A):
                raise _fail("coordinates_changed", "an observed atom changed", residue=ref_out, atom_name=name_in)
            if atom_out.calc_flag != gemmi.CalcFlag.NotSet:
                raise _fail("unexpected_atoms_added", "an observed atom carries the new-atom mark", residue=ref_out)
            max_delta = max(max_delta, distance)
            cleared += atom_in.calc_flag != gemmi.CalcFlag.NotSet
            atom_count += 1
            if atom_in.occ == 0:
                zero_count += 1
                if not zero_residues or zero_residues[-1] is not ref_out:
                    zero_residues.append(ref_out)
        new = atoms[len(known):]
        template = template_heavy(ref_out["resname"], index in terminal) if polymer and new else {}
        present = {atom.name for atom in known}
        names_new: list[str] = []
        for atom in new:
            origin = ("gap_residue" if kind == "gap" else "oxt" if atom.name == K.TERMINAL_OXT else "side_chain")
            allowed = (atom.calc_flag == gemmi.CalcFlag.Calculated and polymer
                       and template.get(atom.name) == atom.element.name and atom.name not in present
                       and atom.name not in names_new and atom.altloc == "\0"
                       and (kind == "gap" or atom.name not in K.BACKBONE_ATOMS))
            if not allowed:
                raise _fail("unexpected_atoms_added", "a new atom is outside the allowed residues and names",
                            residue=ref_out, atom_name=atom.name)
            position = [atom.pos.x, atom.pos.y, atom.pos.z]
            if any(_rounded(x) != x for x in position):
                raise _fail("repair_record_mismatch", "a new atom coordinate is not at the fixed decimals",
                            residue=ref_out, atom_name=atom.name)
            names_new.append(atom.name)
            added.append({"residue": ref_out, "atom_name": atom.name, "element": atom.element.name,
                          "coordinates_A": position, "origin": origin})
        side = [n for n in names_new if n != K.TERMINAL_OXT]
        if kind == "observed" and side:
            side_chain.append({"residue": ref_out, "added_atoms": side})
        if kind == "observed" and K.TERMINAL_OXT in names_new:
            oxt.append({"residue": ref_out})
        if mse:
            atom_map = [{"from": "SE", "to": "SD"}] if any(atom.name == "SE" for atom in known) else []
            replaced.append({"from": ref_in, "to": ref_out, "atom_map": atom_map,
                             "record_type": {"from": "HETATM" if res_in.het_flag == "H" else "ATOM", "to": "ATOM"}})
        for position_in_residue, atom in enumerate(atoms):
            if atom.element.name not in K.HYDROGEN_ELEMENTS:
                heavy_rows.append((index, atom, ref_out, position_in_residue >= len(known)))
                protein_heavy += polymer
    return _record(inputs, analysis, raw, plan, out, heavy_rows, {
        "added": added, "side_chain": side_chain, "oxt": oxt, "replaced": replaced, "max_delta": max_delta,
        "cleared": cleared, "atom_count": atom_count, "protein_heavy": protein_heavy, "delta": delta,
        "zero": {"count": zero_count, "residues": zero_residues}, "parts": [(name, len(parts[name])) for name in order]})


def _collisions(plan: list, out: list, heavy_rows: list) -> dict[str, Any]:
    chain_of = {}
    polymer_index: dict[int, int] = {}
    counters: dict[str, int] = {}
    for index, (_chain, res, ref) in enumerate(out):
        chain_of[index] = ref["chain_auth"]
        if _is_polymer(res):
            polymer_index[index] = counters.get(ref["chain_auth"], 0)
            counters[ref["chain_auth"]] = polymer_index[index] + 1

    def kind(index: int) -> str:
        res = out[index][1]
        if _is_polymer(res):
            return "protein"
        if res.is_water():
            return "water"
        if res.name in METALS:
            return "metal"
        return "ligand" if res.het_flag == "H" else "other"

    positions = np.array([[a.pos.x, a.pos.y, a.pos.z] for _, a, _, _ in heavy_rows], dtype=float).reshape(-1, 3)
    residue = np.array([row[0] for row in heavy_rows], dtype=int)
    classes = np.array([kind(row[0]) for row in heavy_rows], dtype=object)
    chains = np.array([chain_of[row[0]] for row in heavy_rows], dtype=object)
    poly = np.array([polymer_index.get(row[0], -10) for row in heavy_rows], dtype=int)
    result = {}
    for name in K.COLLISION_CLASSES:
        best: tuple[float, int, int] | None = None
        below = {threshold: 0 for threshold in K.COLLISION_THRESHOLDS_A}
        for i, (index, _atom, _ref, new) in enumerate(heavy_rows):
            if not new:
                continue
            excluded = (residue == index) | ((chains == chains[i]) & (np.abs(poly - poly[i]) == 1)
                                             & (poly >= 0) & (poly[i] >= 0))
            mask = (classes == name) & ~excluded
            if not mask.any():
                continue
            candidates = np.flatnonzero(mask)
            distances = np.sqrt(((positions[candidates] - positions[i]) ** 2).sum(axis=1))
            j = int(np.argmin(distances))
            nearest = float(distances[j])
            for threshold in below:
                below[threshold] += nearest < threshold
            if best is None or nearest < best[0]:
                best = (nearest, i, int(candidates[j]))
        pair = None
        if best is not None:
            _, i, j = best
            pair = {"new_residue": heavy_rows[i][2], "new_atom": heavy_rows[i][1].name,
                    "partner_residue": heavy_rows[j][2], "partner_atom": heavy_rows[j][1].name}
        result[name] = {"min_distance_A": best[0] if best else None, "count_lt_2_0": below[2.0],
                        "count_lt_1_5": below[1.5], "min_pair": pair}
    return result


def _record(inputs: RepairInputs, analysis: dict[str, Any], raw: bytes, plan: list, out: list, heavy_rows: list,
            got: dict[str, Any]) -> dict[str, Any]:
    renamed = {_key(item[2]): item[3] for item in plan if item[0] == "observed"}

    def output(ref: dict[str, Any]) -> dict[str, Any]:
        return renamed.get(_key(ref), ref)

    gaps = [{"chain_auth": gap["chain_auth"], "after_residue": output(gap["after_residue"]),
             "before_residue": output(gap["before_residue"]), "length": gap["length"], "residues": gap["residues"]}
            for gap in analysis["defects"]["gaps"]]
    chain_parts = [{"chain_auth": name, "parts": count, "merged": count > 1} for name, count in got["parts"]]
    chain_ends = [{**end, "observed_first": output(end["observed_first"]), "observed_last": output(end["observed_last"])}
                  for end in analysis["chain_ends"]]
    found = {"chain_parts_merged": any(item["merged"] for item in chain_parts), "side_chain_atoms_added":
             bool(got["side_chain"]), "terminal_oxt_added": bool(got["oxt"]), "internal_gap_filled": bool(gaps),
             "nonstandard_replaced": bool(got["replaced"])}
    classes = [name for name in K.REPAIR_CLASSES if found[name]]
    differs = any(end["first_is_sequence_start"] is False or end["last_is_sequence_end"] is False
                  for end in chain_ends)
    record = {
        "schema": K.SCHEMA, "method_version": K.METHOD_VERSION,
        "source": {"prepared_structure": inputs.prepared_structure, "model_number": inputs.model_number},
        "result": {"coordinates": coordinates_handle(inputs.run_id, raw), "coordinates_sha256": sha256_hex(raw)},
        "parameters": {"repair_policy": K.REPAIR_POLICY, "seed": K.REPAIR_SEED, "max_gap_residues": K.MAX_GAP_RESIDUES,
                       "waters": inputs.waters, "hydrogens": inputs.hydrogens,
                       "new_atom_coordinate_decimals": K.NEW_ATOM_DECIMALS},
        "method": fixed_method(), "classes_applied": classes, "chain_parts": chain_parts, "chain_ends": chain_ends,
        "side_chain_repairs": got["side_chain"], "terminal_oxt": got["oxt"], "gaps": gaps,
        "replaced": got["replaced"], "added_atoms": got["added"],
        "counts": {"added_residues": sum(gap["length"] for gap in gaps), "added_atoms": len(got["added"]),
                   "side_chain_residues": len(got["side_chain"]), "terminal_oxt": len(got["oxt"]), "gaps": len(gaps),
                   "replaced": len(got["replaced"]), "chain_parts_merged": sum(item["merged"] for item in chain_parts),
                   "protein_heavy_atoms": got["protein_heavy"]},
        "unchanged": {"atom_count": got["atom_count"], "max_delta_A": got["max_delta"],
                      "input_calc_flag_cleared": got["cleared"]},
        "new_atom_rounding": {"decimals": K.NEW_ATOM_DECIMALS, "max_abs_delta_A": float(got["delta"])},
        "zero_occupancy_input_atoms": got["zero"],
        "collisions": _collisions(plan, out, heavy_rows),
        "limitations": list(K.applicable_limitations(classes_applied=classes, chain_end_differs=differs)),
    }
    size = len(canonical_json(record))
    if size > K.MAX_RECORD_BYTES:
        raise ToolFailure(FailureClass.resource_exceeded, f"repair record exceeds {K.MAX_RECORD_BYTES} bytes; never "
                          "truncated", detail={"reason_code": "resource_exceeded", "limit": "record_bytes",
                                               "bytes": size, "max_bytes": K.MAX_RECORD_BYTES})
    return record
