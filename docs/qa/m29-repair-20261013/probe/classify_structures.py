# PROTOTYPE (M29 T1 (a) independent classification only; never product code, never imported by mw).
"""Classify structures as M29 repair `in_scope` / `out_of_scope(<spec 2.2 code>)` without product code.

Uses only gemmi and the installed Amber14 template XML (`openmm/app/data/amber14/protein.ff14SB.xml`, located
with importlib.util.find_spec so neither openmm nor any `mw` module is imported). For each input file and each
water policy (`strip_all`, `keep_all`) it re-implements the preparation the product applies before M7
(model 0, hydrogens stripped, altloc `highest_occupancy`, waters per policy), writes it with gemmi and reads
it back (as M7 reads the prepared coordinates), then checks the spec 2.2 refusal reasons in order:

  1 chain_identity_duplicate  2 unsupported_residue  3 unexpected_atoms  4 backbone_atoms_missing
  5 gap_listing_missing       6 gap_too_long          7 m7_condition_unsupported
  8 atom_limit_exceeded       9 nothing_to_repair

Gap residues (name, author number, insertion code, label number) are read from the ORIGINAL file's
`_entity_poly_seq` and `_pdbx_unobs_or_zero_occ_residues` (occupancy_flag 1 rows), never guessed.

    .venv/bin/python docs/qa/m29-repair-20261013/probe/classify_structures.py [--json OUT.json] [FILE ...]

Without FILE arguments it classifies the eight local public fixtures plus `runs/stk33-8vf6-20261013/8VF6.cif`.
Output: tab-separated rows (paths are printed relative to the repository root), then a summary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from pathlib import Path

import gemmi

REPO = Path(__file__).resolve().parents[4]
DEFAULT = [REPO / "backend" / "tests" / "fixtures" / f"public_{x}.cif"
           for x in ("1m17", "1fin", "1mq4", "1s9i", "1a30", "1a4i", "1ubq", "1hsg")]
DEFAULT.append(REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif")
WATERS = ("strip_all", "keep_all")
STANDARD = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
            "PRO", "SER", "THR", "TRP", "TYR", "VAL"}
BACKBONE = {"N", "CA", "C", "O"}
HEAVY_ELEMENTS = {"C", "N", "O", "S"}
MAX_GAP_RESIDUES = 20
ATOM_CAP = 6000
ORDER = ("chain_identity_duplicate", "unsupported_residue", "unexpected_atoms", "backbone_atoms_missing",
         "gap_listing_missing", "gap_too_long", "m7_condition_unsupported", "atom_limit_exceeded")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.name


def template_path() -> Path:
    spec = importlib.util.find_spec("openmm")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("openmm package not found (template XML is located inside it)")
    return Path(list(spec.submodule_search_locations)[0]) / "app" / "data" / "amber14" / "protein.ff14SB.xml"


class Templates:
    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        root = ET.fromstring(raw)
        elements = {n.attrib["name"]: n.attrib["element"] for n in root.findall("./AtomTypes/Type")}
        self.heavy: dict[str, set[str]] = {}
        for node in root.findall("./Residues/Residue"):
            self.heavy[node.attrib["name"]] = {a.attrib["name"] for a in node.findall("Atom")
                                               if elements[a.attrib["type"]] not in {"H", "D"}}

    def expected(self, resname: str, terminal: bool) -> set[str]:
        key = {"HIS": "HID", "MSE": "MET"}.get(resname, resname)
        return set(self.heavy[("C" if terminal else "") + key])


def ref(chain, res, model_num) -> dict:
    return {"model_number": model_num, "chain_auth": chain.name, "seq_auth": res.seqid.num,
            "icode": res.seqid.icode.strip(), "chain_label": res.subchain or None, "seq_label": res.label_seq,
            "resname": res.name}


def short(r: dict) -> str:
    return f"{r['chain_auth']}/{r['seq_auth']}{r['icode']}/{r['resname']}"


def select_altlocs(st) -> int:
    """Independent re-implementation of altloc `highest_occupancy` (mean occupancy, tie -> first letter)."""
    removed = 0
    for chain in st[0]:
        for res in chain:
            alts: dict[str, list[float]] = {}
            for atom in res:
                a = atom.altloc.strip("\x00 ")
                if a:
                    alts.setdefault(a, []).append(atom.occ)
            if not alts:
                continue
            chosen = min(alts, key=lambda a: (-sum(alts[a]) / len(alts[a]), a))
            for i in range(len(res) - 1, -1, -1):
                a = res[i].altloc.strip("\x00 ")
                if a and a != chosen:
                    del res[i]
                    removed += 1
            for atom in res:
                if atom.altloc.strip("\x00 ") == chosen:
                    atom.altloc = "\0"
    return removed


def prepared_view(path: Path, waters: str):
    text = path.read_text()
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    for i in range(len(st) - 1, 0, -1):
        del st[i]
    st.remove_hydrogens()
    select_altlocs(st)
    if waters == "strip_all":
        st.remove_waters()
    out = st.make_mmcif_document().as_string()
    again = gemmi.make_structure_from_block(gemmi.cif.read_string(out).sole_block())
    return again, out


def source_listing(path: Path):
    block = gemmi.cif.read(str(path)).sole_block()
    seq: dict[str, dict[int, list[str]]] = {}
    for row in block.find("_entity_poly_seq.", ["entity_id", "num", "mon_id"]):
        seq.setdefault(row[0], {}).setdefault(int(row[1]), []).append(row[2])
    unobs: dict[tuple[str, int], list[dict]] = {}
    tab = block.find("_pdbx_unobs_or_zero_occ_residues.",
                     ["polymer_flag", "occupancy_flag", "auth_asym_id", "auth_seq_id", "PDB_ins_code",
                      "label_asym_id", "label_seq_id", "label_comp_id"])
    for row in tab:
        if row[0] != "Y" or row[1] != "1" or row[6] in {"?", "."}:
            continue
        icode = "" if row[4] in {"?", "."} else row[4]
        unobs.setdefault((row[5], int(row[6])), []).append(
            {"chain_auth": row[2], "seq_auth": int(row[3]), "icode": icode, "chain_label": row[5],
             "seq_label": int(row[6]), "resname": row[7]})
    asym_entity = {row[0]: row[1] for row in block.find("_struct_asym.", ["id", "entity_id"])}
    has_unobs = block.find_mmcif_category("_pdbx_unobs_or_zero_occ_residues.") is not None and len(tab) > 0
    return seq, unobs, asym_entity, has_unobs


def classify(path: Path, waters: str, tpl: Templates) -> dict:
    st, prepared_text = prepared_view(path, waters)
    model = st[0]
    seq, unobs, asym_entity, has_unobs = source_listing(path)
    parts = [ch.name for ch in model]
    merged: "OrderedDict[str, list]" = OrderedDict()
    for ch in model:
        merged.setdefault(ch.name, []).extend((ch, r) for r in ch)
    blockers: list[dict] = []
    side_chain: list[dict] = []
    oxt: list[dict] = []
    gaps: list[dict] = []
    nonstandard: list[dict] = []
    chain_ends: list[dict] = []
    zero_occ_atoms = 0
    zero_occ_residues: list[str] = []
    protein_heavy = 0
    added_heavy = 0
    idents: set[str] = set()

    def block(code: str, residue: dict | None, detail: str) -> None:
        blockers.append({"reason_code": code, "residue": short(residue) if residue else None, "detail": detail})

    for name, items in merged.items():
        polymer = [(ch, r) for ch, r in items if r.het_flag == "A" or r.label_seq is not None]
        subchains = sorted({r.subchain for _, r in polymer})
        if len(subchains) > 1:
            block("chain_identity_duplicate", None, f"author chain {name} holds polymer label chains {subchains}")
        for ch, r in items:
            occ0 = sum(1 for a in r if a.occ == 0)
            if occ0:
                zero_occ_atoms += occ0
                if occ0 == len(r):
                    zero_occ_residues.append(short(ref(ch, r, model.num)))
        if not polymer:
            continue
        for idx, (ch, r) in enumerate(polymer):
            rr = ref(ch, r, model.num)
            key = json.dumps(rr, sort_keys=True)
            if key in idents:
                block("m7_condition_unsupported", rr, "ambiguous residue identity (duplicate 7 fields)")
            idents.add(key)
            last = idx == len(polymer) - 1
            if r.name not in STANDARD and r.name != "MSE":
                block("unsupported_residue", rr, "polymer residue is neither standard nor MSE")
                continue
            if r.name == "MSE":
                nonstandard.append({"residue": short(rr), "record": "HETATM" if r.het_flag == "H" else "ATOM"})
            names = [a.name.strip() for a in r]
            if len(set(names)) != len(names) or any(not re.fullmatch(r"[A-Za-z0-9']{1,4}", n) for n in names):
                block("m7_condition_unsupported", rr, "ambiguous atom identity")
            observed = set()
            for a in r:
                el = a.element.name
                nm = a.name.strip()
                if r.name == "MSE" and nm == "SE" and el == "Se":
                    nm, el = "SD", "S"
                if el not in HEAVY_ELEMENTS:
                    block("unexpected_atoms", rr, f"atom {a.name} element {a.element.name} unsupported")
                observed.add(nm)
            for a in r:
                if not all(map(math.isfinite, (a.pos.x, a.pos.y, a.pos.z))) or max(abs(a.pos.x), abs(a.pos.y),
                                                                                   abs(a.pos.z)) > 1e6:
                    block("m7_condition_unsupported", rr, "invalid protein coordinate")
            protein_heavy += len(observed)
            expected = tpl.expected(r.name, terminal=last)
            extra = sorted(observed - expected)
            if extra:
                block("unexpected_atoms", rr, f"atoms not in template: {extra}")
            if not BACKBONE <= observed:
                block("backbone_atoms_missing", rr, f"missing {sorted(BACKBONE - observed)}")
            missing = expected - observed - BACKBONE
            sc = sorted(missing - {"OXT"})
            if sc:
                side_chain.append({"residue": short(rr), "missing": sc})
                added_heavy += len(sc)
            if "OXT" in missing:
                oxt.append({"residue": short(rr)})
                added_heavy += 1
            if idx:
                pch, prev = polymer[idx - 1]
                pr = ref(pch, prev, model.num)
                if prev.label_seq is not None and r.label_seq is not None and r.label_seq - prev.label_seq != 1:
                    diff = r.label_seq - prev.label_seq
                    if diff < 1:
                        block("m7_condition_unsupported", rr, f"label sequence out of order ({prev.label_seq}->"
                                                              f"{r.label_seq})")
                        continue
                    want = list(range(prev.label_seq + 1, r.label_seq))
                    entity = asym_entity.get(r.subchain)
                    residues, problems = [], []
                    for k in want:
                        rows = unobs.get((r.subchain, k), [])
                        names_k = seq.get(entity, {}).get(k, []) if entity else []
                        if len(rows) != 1 or len(names_k) != 1 or rows[0]["resname"] != names_k[0] \
                                or rows[0]["chain_auth"] != name:
                            problems.append(k)
                        else:
                            residues.append(rows[0])
                    gap = {"chain_auth": name, "after": short(pr), "before": short(rr),
                           "after_label": prev.label_seq, "before_label": r.label_seq, "length": len(want),
                           "identity_determined": not problems,
                           "residues": [f"{x['seq_auth']}{x['icode']}/{x['resname']}/L{x['seq_label']}"
                                        for x in residues]}
                    gaps.append(gap)
                    if problems:
                        block("gap_listing_missing", rr, f"label positions {problems[:5]} not determinable "
                                                         f"(listing present: {has_unobs})")
                    if len(want) > MAX_GAP_RESIDUES:
                        block("gap_too_long", rr, f"gap of {len(want)} residues")
                    for x in residues:
                        if x["resname"] in STANDARD:
                            added_heavy += len(tpl.expected(x["resname"], terminal=False))
                        else:
                            block("unsupported_residue", None, f"gap residue {x['resname']} L{x['seq_label']}")
                    continue
                c = next((a for a in prev if a.name.strip() == "C"), None)
                n = next((a for a in r if a.name.strip() == "N"), None)
                if c is not None and n is not None:
                    d = c.pos.dist(n.pos)
                    if not 1.1 <= d <= 1.7:
                        block("m7_condition_unsupported", rr, f"peptide_geometry C-N {d:.3f} A")
        first, last = polymer[0][1], polymer[-1][1]
        entity = asym_entity.get(last.subchain)
        seq_len = max(seq.get(entity, {0: []}).keys()) if entity in seq else None
        chain_ends.append({"chain_auth": name, "observed_first_label": first.label_seq,
                           "observed_last_label": last.label_seq, "sequence_length": seq_len,
                           "first_is_sequence_start": first.label_seq == 1,
                           "last_is_sequence_end": seq_len is not None and last.label_seq == seq_len})
    if protein_heavy == 0:
        block("m7_condition_unsupported", None, "no protein")
    after = protein_heavy + added_heavy
    if after > ATOM_CAP:
        block("atom_limit_exceeded", None, f"protein heavy atoms after repair {after} > {ATOM_CAP}")
    part_counts = Counter(parts)
    merged_needed = any(v > 1 for v in part_counts.values())
    classes = [c for c, on in (("chain_parts_merged", merged_needed), ("side_chain_atoms_added", bool(side_chain)),
                               ("terminal_oxt_added", bool(oxt)),
                               ("internal_gap_filled", any(g["identity_determined"] for g in gaps)),
                               ("nonstandard_replaced", bool(nonstandard))) if on]
    blockers.sort(key=lambda b: ORDER.index(b["reason_code"]))
    if blockers:
        verdict = f"out_of_scope({blockers[0]['reason_code']})"
    elif not classes:
        verdict = "out_of_scope(nothing_to_repair)"
    else:
        verdict = "in_scope"
    gap_residues = sum(g["length"] for g in gaps if g["identity_determined"])
    return {"file": rel(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "waters": waters,
            "verdict": verdict, "first_blocker": blockers[0] if blockers else None,
            "blocker_codes": sorted({b["reason_code"] for b in blockers}, key=ORDER.index),
            "blocker_count": len(blockers), "blockers": blockers, "classes": classes,
            "chain_part_order": parts, "parts_per_chain": dict(part_counts),
            "side_chain_residues": len(side_chain),
            "side_chain_residues_per_chain": dict(Counter(s["residue"].split("/")[0] for s in side_chain)),
            "side_chain_atoms": sum(len(s["missing"]) for s in side_chain), "side_chain": side_chain,
            "terminal_oxt": oxt, "gaps": gaps, "nonstandard": nonstandard, "chain_ends": chain_ends,
            "zero_occupancy_atoms": zero_occ_atoms, "zero_occupancy_residues": zero_occ_residues,
            "protein_heavy_observed": protein_heavy, "expected_added_heavy_atoms": added_heavy,
            "expected_added_residues": gap_residues, "protein_heavy_after": after,
            "unobs_listing_present": has_unobs, "prepared_sha256": hashlib.sha256(prepared_text.encode()).hexdigest()}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--json", type=Path, help="write full per-row details here")
    args = ap.parse_args(argv)
    tpl = Templates(template_path())
    files = args.files or DEFAULT
    rows = [classify(f, w, tpl) for f in files for w in WATERS]
    print(f"# template protein.ff14SB.xml sha256 {tpl.sha256}; gemmi {gemmi.__version__}")
    cols = ("file", "waters", "verdict", "first_blocker", "blocker_codes", "classes", "chain_part_order",
            "side_chain_residues", "side_chain_residues_per_chain", "side_chain_atoms", "oxt", "gaps",
            "mse", "zero_occ_atoms", "zero_occ_residues", "added_res", "added_heavy", "heavy_before", "heavy_after")
    print("\t".join(cols))
    for r in rows:
        fb = r["first_blocker"]
        gaps = ";".join(f"{g['chain_auth']}:{g['after']}..{g['before']}(n={g['length']},"
                        f"{'ids' if g['identity_determined'] else 'NO-ids'})" for g in r["gaps"]) or "-"
        print("\t".join(str(x) for x in (
            r["file"].split("/")[-1], r["waters"], r["verdict"],
            f"{fb['reason_code']}@{fb['residue']}" if fb else "-", ",".join(r["blocker_codes"]) or "-",
            ",".join(r["classes"]) or "-", ",".join(r["chain_part_order"]), r["side_chain_residues"],
            json.dumps(r["side_chain_residues_per_chain"], sort_keys=True), r["side_chain_atoms"],
            ",".join(o["residue"] for o in r["terminal_oxt"]) or "-", gaps,
            ",".join(n["residue"] for n in r["nonstandard"]) or "-", r["zero_occupancy_atoms"],
            ",".join(r["zero_occupancy_residues"]) or "-", r["expected_added_residues"],
            r["expected_added_heavy_atoms"], r["protein_heavy_observed"], r["protein_heavy_after"])))
    same = all(a["verdict"] == b["verdict"] for a, b in zip(rows[::2], rows[1::2]))
    print(f"# rows={len(rows)} in_scope={sorted({r['file'].split('/')[-1] for r in rows if r['verdict'] == 'in_scope'})}"
          f" same_verdict_both_water_policies={str(same).lower()}")
    if args.json:
        args.json.write_text(json.dumps({"template_sha256": tpl.sha256, "gemmi": gemmi.__version__, "rows": rows},
                                        indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
