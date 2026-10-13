"""Independent expectations of the M29 structure repair acceptance (.dryforge/spec.md 10.1-10.3).

Computed from the INPUT FILES and the installed Amber14 protein template XML only: gemmi, numpy-free standard library
math and ``xml.etree``. The template is located with ``importlib.util.find_spec("openmm")`` (the package is found, never
imported) and read as a file. Nothing here imports ``mw`` or PDBFixer, and nothing here reads a product answer: the
runner compares these values with what the product stored. Ported from the T1 prototype
``docs/qa/m29-repair-20261013/probe/classify_structures.py`` (the classification) with the record-level checks added.

``Templates`` / ``templates()``
    The heavy-atom names of every residue template (``HIS`` read as ``HID``, ``MSE`` as ``MET``, ``C``-prefixed for a
    chain's last residue) and the template file's SHA-256.
``classify(raw, waters, tpl) -> dict``
    One structure file (mmCIF bytes) under one water policy (``strip_all`` | ``keep_all``): the preparation the product
    applies before M7 re-implemented (model 0, hydrogens stripped, altloc ``highest_occupancy``, waters per policy,
    written and read back), then the spec 2.2 refusal checks in order. ``verdict`` is ``in_scope`` or
    ``out_of_scope(<code>)``; the defect lists carry each residue's 7-field identity (``ref``) and the gap residues
    come from the file's ``_entity_poly_seq`` + ``_pdbx_unobs_or_zero_occ_residues`` (occupancy_flag 1) only.
``receptor_atoms_lower_bound(row, tpl) -> int``
    A lower bound of the M18 receptor atoms (hydrogens included) of a one-point M21 model on the repaired structure:
    the fewest-atom template form of every residue after repair (R4a: the receptor atom cap may only explain a refused
    docking when this bound is above the cap).
``shell_residues(raw, waters, ligand, radius_A) -> list[dict]``
    The M20 ligand shell recomputed from the input file: the polymer residues of the prepared view with a heavy atom
    within ``radius_A`` of a heavy atom of the ligand residue (R3: what may explain a key-site exclusion).
``mutable_residue(row, skip=()) -> dict | None``
    A residue to put a mutation on (the third standard residue of the first chain that is not GLY / PRO / CYS / MSE and
    has a complete side chain): a deterministic choice of the runner, not a design suggestion.
``repair_problems(row, prepared, repaired) -> dict``
    The spec 3.2 / 3.4 checks of one stored repair made from the input (``prepared`` = the bytes the repair read,
    ``repaired`` = the stored repaired mmCIF): every input atom is in the output with its name (SE -> SD of MSE only),
    element (Se -> S), altloc, residue 7 fields (MSE -> MET only) and coordinates within 1e-9 A; the other output atoms
    carry ``calc_flag`` c and are exactly the side-chain / OXT / gap-residue heavy atoms this module expects, at four
    decimals; the new residues are the listed gap residues. Returns the counts found and the problems (empty = pass).
``modeled_basis_expected(repaired, positions, parameters) -> list[bool]``
    Spec 5.4 per stored M20 position: the residue has a modeled atom (``calc_flag`` c), or the ligand-shell,
    metal-contact or disulfide judgment made with observed atoms only differs from the judgment with every atom.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

import gemmi

WATERS = ("strip_all", "keep_all")
STANDARD = frozenset({"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET",
                      "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"})
BACKBONE = frozenset({"N", "CA", "C", "O"})
HEAVY_ELEMENTS = frozenset({"C", "N", "O", "S"})
HYDROGENS = frozenset({"H", "D"})
METALS = frozenset({"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"})
MAX_GAP_RESIDUES = 20
ATOM_CAP = 6000
PEPTIDE_CN = (1.1, 1.7)
COORDINATE_TOLERANCE_A = 1e-9
DISULFIDE_A = 2.5
# Spec 2.2 order (nothing_to_repair is the verdict when no blocker and no class applies).
ORDER = ("chain_identity_duplicate", "unsupported_residue", "unexpected_atoms", "backbone_atoms_missing",
         "gap_listing_missing", "gap_too_long", "m7_condition_unsupported", "atom_limit_exceeded")
CLASSES = ("chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added", "internal_gap_filled",
           "nonstandard_replaced")
FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
ATOM_NAME = re.compile(r"[A-Za-z0-9']{1,4}")
# The Amber14 template names a residue can take once hydrogens are added at a pH (MSE is MET after the repair).
VARIANTS = {"HIS": ("HID", "HIE", "HIP"), "CYS": ("CYS", "CYX", "CYM"), "ASP": ("ASP", "ASH"), "GLU": ("GLU", "GLH"),
            "LYS": ("LYS", "LYN"), "MSE": ("MET",)}


# ---------------------------------------------------------------------------------------------------- template
def template_path() -> Path:
    spec = importlib.util.find_spec("openmm")
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError("the openmm package (the template XML is inside it) is not installed")
    return Path(next(iter(spec.submodule_search_locations))) / "app" / "data" / "amber14" / "protein.ff14SB.xml"


class Templates:
    def __init__(self, raw: bytes) -> None:
        self.sha256 = hashlib.sha256(raw).hexdigest()
        root = ET.fromstring(raw)
        elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
        self.heavy: dict[str, set[str]] = {}
        self.atoms: dict[str, int] = {}          # every atom of the template, hydrogens included
        for node in root.findall("./Residues/Residue"):
            self.heavy[node.attrib["name"]] = {atom.attrib["name"] for atom in node.findall("Atom")
                                               if elements[atom.attrib["type"]] not in HYDROGENS}
            self.atoms[node.attrib["name"]] = len(node.findall("Atom"))

    def expected(self, resname: str, terminal: bool) -> set[str]:
        key = {"HIS": "HID", "MSE": "MET"}.get(resname, resname)
        return set(self.heavy[("C" if terminal else "") + key])

    def fewest_atoms(self, resname: str) -> int:
        """The fewest atoms (hydrogens included) of any template form ``resname`` can take in a protonated model: its
        protonation variants, each plain, N-terminal and C-terminal (0 for a name without a template)."""
        forms = [prefix + base for base in VARIANTS.get(resname, (resname,)) for prefix in ("", "N", "C")]
        return min((self.atoms[form] for form in forms if form in self.atoms), default=0)


def templates(path: Path | None = None) -> Templates:
    return Templates(Path(path or template_path()).read_bytes())


# ---------------------------------------------------------------------------------------------------- reading
def ref(chain: Any, res: Any, model_num: int) -> dict:
    return {"model_number": model_num, "chain_auth": chain.name, "chain_label": res.subchain or None,
            "seq_auth": res.seqid.num, "seq_label": res.label_seq, "icode": res.seqid.icode.strip(),
            "resname": res.name}


def short(item: dict) -> str:
    return f"{item['chain_auth']}/{item['seq_auth']}{item['icode']}/{item['resname']}"


def key7(item: dict) -> tuple:
    return tuple(item[field] for field in FIELDS)


def _select_altlocs(st: Any) -> None:
    """altloc ``highest_occupancy`` (mean occupancy, ties to the first letter), as the product's preparation."""
    for chain in st[0]:
        for res in chain:
            alts: dict[str, list[float]] = {}
            for atom in res:
                letter = atom.altloc.strip("\x00 ")
                if letter:
                    alts.setdefault(letter, []).append(atom.occ)
            if not alts:
                continue
            chosen = min(alts, key=lambda a: (-sum(alts[a]) / len(alts[a]), a))
            for index in range(len(res) - 1, -1, -1):
                letter = res[index].altloc.strip("\x00 ")
                if letter and letter != chosen:
                    del res[index]
            for atom in res:
                if atom.altloc.strip("\x00 ") == chosen:
                    atom.altloc = "\0"


def prepared_view(raw: bytes, waters: str) -> tuple[Any, str]:
    if waters not in WATERS:
        raise ValueError(f"unknown water policy {waters!r}")
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())
    for index in range(len(st) - 1, 0, -1):
        del st[index]
    st.remove_hydrogens()
    _select_altlocs(st)
    if waters == "strip_all":
        st.remove_waters()
    text = st.make_mmcif_document().as_string()
    return gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block()), text


def source_listing(raw: bytes) -> tuple[dict, dict, dict, bool]:
    block = gemmi.cif.read_string(raw.decode()).sole_block()
    seq: dict[str, dict[int, list[str]]] = {}
    for row in block.find("_entity_poly_seq.", ["entity_id", "num", "mon_id"]):
        seq.setdefault(row[0], {}).setdefault(int(row[1]), []).append(row[2])
    unobs: dict[tuple[str, int], list[dict]] = {}
    table = block.find("_pdbx_unobs_or_zero_occ_residues.",
                       ["polymer_flag", "occupancy_flag", "auth_asym_id", "auth_seq_id", "PDB_ins_code",
                        "label_asym_id", "label_seq_id", "label_comp_id"])
    for row in table:
        if row[0] != "Y" or row[1] != "1" or row[6] in {"?", "."}:
            continue
        unobs.setdefault((row[5], int(row[6])), []).append(
            {"chain_auth": row[2], "seq_auth": int(row[3]), "icode": "" if row[4] in {"?", "."} else row[4],
             "chain_label": row[5], "seq_label": int(row[6]), "resname": row[7]})
    asym_entity = {row[0]: row[1] for row in block.find("_struct_asym.", ["id", "entity_id"])}
    return seq, unobs, asym_entity, len(table) > 0


# ---------------------------------------------------------------------------------------------------- classify
def classify(raw: bytes, waters: str, tpl: Templates) -> dict:
    st, prepared_text = prepared_view(raw, waters)
    model = st[0]
    num = model.num
    seq, unobs, asym_entity, has_unobs = source_listing(raw)
    parts = [chain.name for chain in model]
    merged: OrderedDict[str, list] = OrderedDict()
    for chain in model:
        merged.setdefault(chain.name, []).extend((chain, res) for res in chain)
    blockers: list[dict] = []
    side_chain: list[dict] = []
    oxt: list[dict] = []
    gaps: list[dict] = []
    nonstandard: list[dict] = []
    chain_ends: list[dict] = []
    polymer_refs: list[dict] = []
    zero_atoms = 0
    observed_heavy = 0
    added_heavy = 0
    seen: set[tuple] = set()

    def block(code: str, residue: dict | None, chain: str | None, detail: str) -> None:
        blockers.append({"reason_code": code, "residue": residue, "chain_auth": chain, "detail": detail})

    for name, items in merged.items():
        polymer = [(chain, res) for chain, res in items if res.het_flag == "A" or res.label_seq is not None]
        labels = sorted({res.subchain or "" for _, res in polymer})
        if len(labels) > 1:
            block("chain_identity_duplicate", None, name, f"author chain {name} holds polymer label chains {labels}")
        for _chain, res in items:
            zero_atoms += sum(1 for atom in res if atom.occ == 0)
        if not polymer:
            continue
        for index, (chain, res) in enumerate(polymer):
            item = ref(chain, res, num)
            polymer_refs.append(item)
            out = dict(item, resname="MET") if res.name == "MSE" else item
            if key7(out) in seen:
                block("m7_condition_unsupported", item, name, "ambiguous residue identity")
            seen.add(key7(out))
            last = index == len(polymer) - 1
            names: list[str] = []
            observed: dict[str, str] = {}
            for atom in res:
                atom_name, element = atom.name.strip(), atom.element.name
                if res.name == "MSE" and atom_name == "SE":
                    atom_name, element = "SD", ("S" if element == "Se" else element)
                names.append(atom_name)
                if not all(math.isfinite(x) and abs(x) <= 1e6 for x in (atom.pos.x, atom.pos.y, atom.pos.z)):
                    block("m7_condition_unsupported", item, name, "invalid protein coordinate")
                if element not in HYDROGENS:
                    observed[atom_name] = element
                    observed_heavy += 1
            if len(set(names)) != len(names) or any(not ATOM_NAME.fullmatch(n) for n in names):
                block("m7_condition_unsupported", item, name, "ambiguous atom identity")
            if res.name not in STANDARD and res.name != "MSE":
                block("unsupported_residue", item, name, "polymer residue is neither standard nor MSE")
            else:
                if res.name == "MSE":
                    nonstandard.append({"ref": item, "record": "HETATM" if res.het_flag == "H" else "ATOM"})
                expected = tpl.expected(res.name, terminal=last)
                extra = sorted(n for n, el in observed.items() if n not in expected or el not in HEAVY_ELEMENTS)
                if extra:
                    block("unexpected_atoms", item, name, f"atoms not in the template: {extra}")
                if not BACKBONE <= set(observed):
                    block("backbone_atoms_missing", item, name, f"missing {sorted(BACKBONE - set(observed))}")
                else:
                    missing = sorted(expected - set(observed) - BACKBONE - {"OXT"})
                    if missing:
                        side_chain.append({"ref": item, "missing": missing})
                        added_heavy += len(missing)
                    if last and "OXT" not in observed:
                        oxt.append({"ref": item})
                        added_heavy += 1
            if not index:
                continue
            _pchain, prev = polymer[index - 1]
            prev_item = polymer_refs[-2]
            if prev.label_seq is not None and res.label_seq is not None:
                step = res.label_seq - prev.label_seq
                if step < 1:
                    block("m7_condition_unsupported", item, name, "label sequence out of order")
                elif step == 1:
                    c_atom = next((a for a in prev if a.name.strip() == "C"), None)
                    n_atom = next((a for a in res if a.name.strip() == "N"), None)
                    if c_atom is not None and n_atom is not None:
                        distance = c_atom.pos.dist(n_atom.pos)
                        if not PEPTIDE_CN[0] <= distance <= PEPTIDE_CN[1]:
                            block("m7_condition_unsupported", item, name, f"peptide_geometry C-N {distance:.3f} A")
                elif prev.subchain == res.subchain:
                    entity = asym_entity.get(res.subchain)
                    residues, missing_positions = [], []
                    for position in range(prev.label_seq + 1, res.label_seq):
                        rows = unobs.get((res.subchain, position), [])
                        listed = seq.get(entity, {}).get(position, []) if entity else []
                        if (len(rows) != 1 or len(listed) != 1 or rows[0]["resname"] != listed[0]
                                or rows[0]["chain_auth"] != name):
                            missing_positions.append(position)
                        else:
                            residues.append({"model_number": num, **rows[0]})
                    gap = {"chain_auth": name, "after": prev_item, "before": item,
                           "length": res.label_seq - prev.label_seq - 1, "determined": not missing_positions,
                           "residues": residues}
                    gaps.append(gap)
                    if missing_positions:
                        block("gap_listing_missing", item, name, f"label positions {missing_positions[:5]} not "
                                                                 f"determinable (listing present: {has_unobs})")
                    else:
                        if gap["length"] > MAX_GAP_RESIDUES:
                            block("gap_too_long", item, name, f"gap of {gap['length']} residues")
                        for gap_residue in residues:
                            if gap_residue["resname"] in STANDARD:
                                added_heavy += len(tpl.expected(gap_residue["resname"], terminal=False))
                            else:
                                block("unsupported_residue", gap_residue, name, "gap residue is not standard")
        first, last_res = polymer[0][1], polymer[-1][1]
        entity = asym_entity.get(last_res.subchain)
        numbers = seq.get(entity) if entity in seq else None
        chain_ends.append({"chain_auth": name, "observed_first": ref(polymer[0][0], first, num),
                           "observed_last": ref(polymer[-1][0], last_res, num),
                           "first_is_sequence_start": (first.label_seq == min(numbers)) if numbers else None,
                           "last_is_sequence_end": (last_res.label_seq == max(numbers)) if numbers else None})
    if observed_heavy == 0:
        block("m7_condition_unsupported", None, None, "no protein")
    after = observed_heavy + added_heavy
    if after > ATOM_CAP:
        block("atom_limit_exceeded", None, None, f"protein heavy atoms after repair {after} > {ATOM_CAP}")
    part_counts = Counter(parts)
    found = {"chain_parts_merged": any(count > 1 for count in part_counts.values()),
             "side_chain_atoms_added": bool(side_chain), "terminal_oxt_added": bool(oxt),
             "internal_gap_filled": any(gap["determined"] for gap in gaps), "nonstandard_replaced": bool(nonstandard)}
    classes = [name for name in CLASSES if found[name]]
    blockers.sort(key=lambda item: ORDER.index(item["reason_code"]))
    if blockers:
        verdict = f"out_of_scope({blockers[0]['reason_code']})"
    elif not classes:
        verdict = "out_of_scope(nothing_to_repair)"
    else:
        verdict = "in_scope"
    determined = [gap for gap in gaps if gap["determined"]]
    return {"waters": waters, "verdict": verdict, "code": None if verdict == "in_scope" else verdict[13:-1],
            "first_blocker": blockers[0] if blockers else None, "blockers": blockers, "classes": classes,
            "chain_part_order": parts, "parts_per_chain": dict(part_counts),
            "side_chain": side_chain, "side_chain_atoms": sum(len(item["missing"]) for item in side_chain),
            "terminal_oxt": oxt, "gaps": gaps, "gap_lengths": [gap["length"] for gap in determined],
            "nonstandard": nonstandard, "chain_ends": chain_ends, "zero_occupancy_atoms": zero_atoms,
            "protein_heavy_observed": observed_heavy, "expected_added_heavy_atoms": added_heavy,
            "expected_added_residues": sum(len(gap["residues"]) for gap in determined), "protein_heavy_after": after,
            "unobs_listing_present": has_unobs, "polymer": polymer_refs,
            "prepared_sha256": hashlib.sha256(prepared_text.encode()).hexdigest(), "template_sha256": tpl.sha256}


def summary(row: dict) -> dict:
    """The table fields of one classification row (no residue lists)."""
    first = row["first_blocker"]
    return {"verdict": row["verdict"], "code": row["code"],
            "firstBlocker": None if first is None else {
                "reason_code": first["reason_code"], "chain_auth": first["chain_auth"],
                "residue": short(first["residue"]) if first["residue"] else None},
            "classes": row["classes"], "chainParts": {name: n for name, n in row["parts_per_chain"].items() if n > 1},
            "sideChainResidues": len(row["side_chain"]), "sideChainAtoms": row["side_chain_atoms"],
            "terminalOxt": [short(item["ref"]) for item in row["terminal_oxt"]], "gapLengths": row["gap_lengths"],
            "mse": [short(item["ref"]) for item in row["nonstandard"]],
            "zeroOccupancyAtoms": row["zero_occupancy_atoms"], "expectedAddedResidues": row["expected_added_residues"],
            "expectedAddedHeavyAtoms": row["expected_added_heavy_atoms"],
            "proteinHeavyAfter": row["protein_heavy_after"]}


def receptor_atoms_lower_bound(row: dict, tpl: Templates) -> int:
    """A lower bound of the M18 receptor atom count (hydrogens included) of a one-point M21 model on the repaired
    structure of ``row``: every protein residue after repair (the observed polymer residues and the listed gap residues)
    at its fewest-atom template form, and the one mutated residue at the fewest-atom form of any standard residue. The
    model can only hold more (another protonation, a ligand or water kept); never fewer."""
    names = [item["resname"] for item in row["polymer"]]
    names += [residue["resname"] for gap in row["gaps"] if gap["determined"] for residue in gap["residues"]]
    counts = [tpl.fewest_atoms(name) for name in names]
    if not counts:
        return 0
    return sum(counts) - max(counts) + min(tpl.fewest_atoms(name) for name in STANDARD)


def shell_residues(raw: bytes, waters: str, ligand: dict, radius_A: float) -> list[dict]:
    """The polymer residues (``het_flag`` A, as the M20 walk) of the prepared view of ``raw`` whose heavy atoms come
    within ``radius_A`` of the heavy atoms of the ligand residue ``ligand`` (model, chain_auth, seq_auth, icode,
    resname), in file order; empty when the ligand is not in the file."""
    st, _text = prepared_view(raw, waters)
    model = st[0]

    def heavy(res: Any) -> list[tuple]:
        return [(a.pos.x, a.pos.y, a.pos.z) for a in res if a.element.name not in HYDROGENS]
    want = (ligand["chain_auth"], ligand["seq_auth"], ligand.get("icode") or "", ligand["resname"])
    target = [xyz for chain in model for res in chain
              if (chain.name, res.seqid.num, res.seqid.icode.strip(), res.name) == want for xyz in heavy(res)]
    if not target:
        return []
    out = []
    for chain in model:
        for res in chain:
            own = heavy(res)
            if res.het_flag == "A" and not res.is_water() and own and \
                    min(math.dist(a, b) for a in own for b in target) <= radius_A:
                out.append(ref(chain, res, model.num))
    return out


def mutable_residue(row: dict, skip: tuple[str, ...] = ()) -> dict | None:
    """The third residue of the first chain that is standard, not GLY / PRO / CYS (MSE is not standard) and has
    every side-chain atom (a deterministic runner choice; ``skip`` short names are passed over)."""
    incomplete = {key7(item["ref"]) for item in row["side_chain"]}
    chains = [item["chain_auth"] for item in row["polymer"]]
    if not chains:
        return None
    first_chain = chains[0]
    fitting = [item for item in row["polymer"] if item["chain_auth"] == first_chain and item["resname"] in STANDARD
               and item["resname"] not in {"GLY", "PRO", "CYS"} and key7(item) not in incomplete
               and short(item) not in skip]
    return fitting[2] if len(fitting) > 2 else (fitting[0] if fitting else None)


# ---------------------------------------------------------------------------------------------------- stored repair
def _atoms(raw: bytes) -> tuple[int, list[dict]]:
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())
    model = st[0]
    out = []
    for chain in model:
        for res in chain:
            item = ref(chain, res, model.num)
            for atom in res:
                out.append({"residue": item, "name": atom.name.strip(), "element": atom.element.name,
                            "altloc": atom.altloc.strip("\x00 "), "xyz": (atom.pos.x, atom.pos.y, atom.pos.z),
                            "calc": atom.calc_flag == gemmi.CalcFlag.Calculated})
    return model.num, out


def _four_decimals(value: float) -> bool:
    return abs(round(value * 1e4) - value * 1e4) < 1e-6


def repair_problems(row: dict, prepared: bytes, repaired: bytes, tpl: Templates) -> dict:
    """See the module docstring. ``row`` is ``classify`` of the input file under the repair's water policy."""
    problems: list[str] = []
    _num, before = _atoms(prepared)
    _num, after = _atoms(repaired)
    mse = {key7(item["ref"]) for item in row["nonstandard"]}

    def output_key(atom: dict) -> tuple:
        residue = atom["residue"]
        name, element = atom["name"], atom["element"]
        if key7(residue) in mse:
            residue = dict(residue, resname="MET")
            if name == "SE":
                name, element = "SD", "S"
        return (*key7(residue), name, atom["altloc"]), element

    observed = {key: atom for key, atom in ((k, a) for a in after if not a["calc"]
                                            for k in [(*key7(a["residue"]), a["name"], a["altloc"])])}
    moved = 0.0
    for atom in before:
        key, element = output_key(atom)
        found = observed.pop(key, None)
        if found is None:
            problems.append(f"input atom {key} missing from the output")
            continue
        if found["element"] != element:
            problems.append(f"input atom {key} element {found['element']} != {element}")
        delta = max(abs(a - b) for a, b in zip(found["xyz"], atom["xyz"], strict=True))
        moved = max(moved, delta)
    if moved > COORDINATE_TOLERANCE_A:
        problems.append(f"an observed atom moved {moved} A")
    if observed:
        problems.append(f"{len(observed)} output atoms without calc_flag c are not input atoms")
    new = [atom for atom in after if atom["calc"]]
    expected: Counter = Counter()
    for item in row["side_chain"]:
        for name in item["missing"]:
            expected[(*key7(item["ref"]), name)] += 1
    for item in row["terminal_oxt"]:
        residue = dict(item["ref"], resname="MET") if key7(item["ref"]) in mse else item["ref"]
        expected[(*key7(residue), "OXT")] += 1
    gap_keys = set()
    for gap in row["gaps"]:
        for residue in gap["residues"]:
            gap_keys.add(key7(residue))
            for name in tpl.expected(residue["resname"], terminal=False):
                expected[(*key7(residue), name)] += 1
    got = Counter((*key7(atom["residue"]), atom["name"]) for atom in new)
    if got != expected:
        problems.append(f"new atoms differ from the expected additions: {len(got - expected)} unexpected, "
                        f"{len(expected - got)} missing")
    if any(atom["element"] in HYDROGENS for atom in new):
        problems.append("a new atom is a hydrogen")
    if not all(_four_decimals(value) for atom in new for value in atom["xyz"]):
        problems.append("a new atom coordinate is not at four decimals")
    output_residues = {key7(atom["residue"]) for atom in after}
    input_residues = {key7(dict(a["residue"], resname="MET") if key7(a["residue"]) in mse else a["residue"])
                      for a in before}
    added_residues = output_residues - input_residues
    if added_residues != gap_keys:
        problems.append(f"new residues {len(added_residues)} are not the {len(gap_keys)} listed gap residues")
    return {"inputAtoms": len(before), "outputAtoms": len(after), "newAtoms": len(new),
            "newResidues": len(added_residues), "maxObservedDeltaA": moved, "problems": problems}


def modeled_basis_expected(repaired: bytes, positions: list[dict], parameters: dict) -> list[bool]:
    """Spec 5.4 per stored position (``positions`` in stored order, ``parameters`` the set's stored parameters)."""
    _num, atoms = _atoms(repaired)
    residues: dict[tuple, list[dict]] = {}
    polymer: set[tuple] = set()
    for atom in atoms:
        residues.setdefault(key7(atom["residue"]), []).append(atom)
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(repaired.decode()).sole_block())
    metals = []
    for chain in st[0]:
        for res in chain:
            item = key7(ref(chain, res, st[0].num))
            if res.het_flag == "A":
                polymer.add(item)
            elif not res.is_water() and res.name in METALS:
                metals.append(item)

    def heavy(key: tuple, observed: bool) -> list[tuple]:
        return [a["xyz"] for a in residues.get(key, []) if a["element"] not in HYDROGENS
                and not (observed and a["calc"])]

    def dmin(first: list[tuple], second: list[tuple]) -> float:
        return min(math.dist(a, b) for a in first for b in second)

    ligand = parameters.get("ligand")
    ligand_key = key7({**ligand, "chain_label": ligand.get("chain_label"), "seq_label": ligand.get("seq_label")}) \
        if ligand and "chain_label" in ligand else None
    if ligand and ligand_key not in residues:
        ligand_key = next((key for key in residues if (key[0], key[1], key[3], key[5], key[6]) == (
            ligand["model_number"], ligand["chain_auth"], ligand["seq_auth"], ligand["icode"], ligand["resname"])),
            None)
    shell = (parameters.get("sources") or {}).get("ligand_shell")
    metal_cut = parameters.get("metal_contact_A")
    cys = [key for key in polymer if key[6] in ("CYS", "CYX")]

    def sg(key: tuple, observed: bool) -> list[tuple]:
        return [a["xyz"] for a in residues.get(key, []) if a["name"] == "SG" and not (observed and a["calc"])]

    def judge(key: tuple, observed: bool) -> tuple:
        own = heavy(key, observed)
        in_shell = bool(shell and own and ligand_key and dmin(own, heavy(ligand_key, observed)) <= shell["radius_A"])
        metal = None
        if metals and own and metal_cut is not None:
            distances = [dmin(own, [a["xyz"] for a in residues[m]]) for m in metals]
            if min(distances) <= metal_cut:
                metal = metals[distances.index(min(distances))]
        partner = None
        if key[6] in ("CYS", "CYX") and sg(key, observed):
            others = [(dmin(sg(key, observed), sg(c, observed)), c) for c in cys if c != key and sg(c, observed)]
            if others and min(others)[0] <= DISULFIDE_A:
                partner = min(others)[1]
        return in_shell, metal, partner

    out = []
    for position in positions:
        key = key7(position["residue"])
        modeled = any(a["calc"] for a in residues.get(key, []))
        out.append(modeled or judge(key, False) != judge(key, True))
    return out
