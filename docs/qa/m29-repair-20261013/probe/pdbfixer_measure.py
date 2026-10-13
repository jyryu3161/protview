# PROTOTYPE (M29 T1 (g)(j) measurement only; never product code, never imported by mw).
"""PDBFixer 1.12.0 measurement on the protein of a prepared structure, without product code.

Procedure (one structure, one water policy):
  1. Prepared view re-implemented with gemmi (classify_structures.prepared_view: model 0, H stripped, altloc
     highest_occupancy, waters per policy), chain parts merged by author chain name (polymer residues only).
  2. Internal gaps (label sequence jump > 1) and their residues from the ORIGINAL file's `_entity_poly_seq` and
     `_pdbx_unobs_or_zero_occ_residues` (occupancy_flag 1). Terminal tails are never built.
  3. M21-style topology (chain id str(chain index), residue id str(global index + 1), heavy atoms, Å) ->
     createStandardBonds + createDisulfideBonds -> PDBxFile.writeFile(keepIds=True) -> PDBFixer(pdbxfile=...,
     platform=CPU Threads=1) -> missingResidues set explicitly from step 2 (findMissingResidues is NOT used) ->
     findMissingAtoms -> addMissingAtoms(seed).
  4. Map PDBFixer's output back to the 7 residue fields (observed residues by position; gap residues from the listing),
     measure the displacement of every observed atom, collect added atoms (origin side_chain / oxt / gap_residue).
  5. Clash record (new heavy atom vs nearest heavy atom outside its own and the directly adjacent residues; partners
     classified protein / ligand / metal / water from the prepared view) and the C-N distance of every peptide link.

    .venv/bin/python docs/qa/m29-repair-20261013/probe/pdbfixer_measure.py one FILE --waters strip_all --seed 1 \
        --out OUT.json
    .venv/bin/python docs/qa/m29-repair-20261013/probe/pdbfixer_measure.py additions FILE --out 8vf6_additions.json

`one` prints a timing / counts line and writes the full measurement (full-precision coordinates) as canonical JSON.
`additions` writes the T3a fixture form (PDBFixer-measured, not a product value) for strip_all, seed 1.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import time
from collections import OrderedDict
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402  (must precede engine imports)
from classify_structures import Templates, prepared_view, rel, source_listing, template_path  # noqa: E402

import numpy as np  # noqa: E402
import openmm  # noqa: E402
from openmm import app, unit  # noqa: E402
from pdbfixer import PDBFixer  # noqa: E402

METALS = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"}


def seven(model_num, chain, res, resname=None) -> dict:
    return {"model_number": model_num, "chain_auth": chain.name, "seq_auth": res.seqid.num,
            "icode": res.seqid.icode.strip(), "chain_label": res.subchain or None, "seq_label": res.label_seq,
            "resname": resname or res.name}


def cpu() -> openmm.Platform:
    platform = openmm.Platform.getPlatformByName("CPU")
    platform.setPropertyDefaultValue("Threads", "1")
    return platform


def protein_chains(st):
    model = st[0]
    merged: "OrderedDict[str, list]" = OrderedDict()
    for ch in model:
        merged.setdefault(ch.name, []).extend((ch, r) for r in ch)
    chains = []
    for name, items in merged.items():
        pol = [(ch, r) for ch, r in items if r.het_flag == "A" or r.label_seq is not None]
        if pol:
            chains.append((name, pol))
    return model, chains


def gap_plan(path: Path, chains, model_num):
    seq, unobs, asym_entity, _ = source_listing(path)
    plan = {}   # (chain_index, index_in_chain of the residue after the gap) -> list of 7-field dicts
    for ci, (name, pol) in enumerate(chains):
        for idx in range(1, len(pol)):
            prev, cur = pol[idx - 1][1], pol[idx][1]
            if prev.label_seq is None or cur.label_seq is None or cur.label_seq - prev.label_seq <= 1:
                continue
            entity = asym_entity.get(cur.subchain)
            rows = []
            for k in range(prev.label_seq + 1, cur.label_seq):
                found = unobs.get((cur.subchain, k), [])
                names = seq.get(entity, {}).get(k, [])
                if len(found) != 1 or len(names) != 1 or found[0]["resname"] != names[0]:
                    raise SystemExit(f"gap residue L{k} of {name} is not determinable from the listing")
                rows.append({"model_number": model_num, **found[0]})
            plan[(ci, idx)] = rows
    return plan


def run_pdbfixer(chains, plan, seed: int):
    topology = app.Topology()
    positions = []
    refs = []
    gidx = 0
    for ci, (name, pol) in enumerate(chains):
        chain = topology.addChain(str(ci))
        for ch, r in pol:
            resname = "MET" if r.name == "MSE" else r.name
            added = topology.addResidue(resname, chain, id=str(gidx + 1))
            gidx += 1
            for a in r:
                nm, el = a.name, a.element.name
                if r.name == "MSE" and nm == "SE":
                    nm, el = "SD", "S"
                topology.addAtom(nm, app.element.get_by_symbol(el), added)
                positions.append(openmm.Vec3(a.pos.x, a.pos.y, a.pos.z))
            refs.append((ci, ch, r))
    positions = unit.Quantity(positions, unit.angstrom)
    topology.createStandardBonds()
    topology.createDisulfideBonds(positions)
    text = io.StringIO()
    app.PDBxFile.writeFile(topology, positions, text, keepIds=True)
    fixer = PDBFixer(pdbxfile=io.StringIO(text.getvalue()), platform=cpu())
    fixer.findMissingResidues()
    found_by_pdbfixer = dict(fixer.missingResidues)
    fixer.missingResidues = {key: [row["resname"] for row in rows] for key, rows in plan.items()}
    fixer.findMissingAtoms()
    flagged = {"missing_atoms": {f"{r.chain.id}:{r.id}": sorted(a.name for a in atoms)
                                 for r, atoms in fixer.missingAtoms.items()},
               "missing_terminals": {f"{r.chain.id}:{r.id}": list(t) for r, t in fixer.missingTerminals.items()},
               "pdbfixer_found_missing_residues_without_sequence": len(found_by_pdbfixer)}
    t0 = time.perf_counter()
    fixer.addMissingAtoms(seed=seed)
    seconds = time.perf_counter() - t0
    out = []
    for r in fixer.topology.residues():
        out.append({"chain_id": r.chain.id, "id": r.id, "resname": r.name,
                    "atoms": [(a.name, a.element.symbol if a.element is not None else None,
                               [float(x) for x in fixer.positions[a.index].value_in_unit(unit.angstrom)])
                              for a in r.atoms()]})
    return out, flagged, seconds, refs


def measure(path: Path, waters: str, seed: int) -> dict:
    tpl = Templates(template_path())
    st, _ = prepared_view(path, waters)
    model, chains = protein_chains(st)
    plan = gap_plan(path, chains, model.num)
    t0 = time.perf_counter()
    out, flagged, seconds, refs = run_pdbfixer(chains, plan, seed)
    total = time.perf_counter() - t0
    # walk output residues against the expected order (observed residues with gap residues inserted before them)
    expected = []
    for ci, (name, pol) in enumerate(chains):
        for idx, (ch, r) in enumerate(pol):
            for row in plan.get((ci, idx), []):
                expected.append(("gap", ci, row))
            expected.append(("obs", ci, (ch, r)))
    if len(out) != len(expected):
        raise SystemExit(f"PDBFixer returned {len(out)} residues, expected {len(expected)}")
    added, max_delta, unchanged, residues_out = [], 0.0, 0, []
    side_chain, oxt = [], []
    for item, (kind, ci, payload) in zip(out, expected):
        if item["chain_id"] != str(ci):
            raise SystemExit("PDBFixer changed the chain order")
        if kind == "gap":
            ref = dict(payload)
            if item["resname"] != ref["resname"]:
                raise SystemExit(f"gap residue name {item['resname']} != listing {ref['resname']}")
            for name, el, xyz in item["atoms"]:
                added.append({"residue": ref, "atom_name": name, "element": el, "coordinates_A": xyz,
                              "origin": "gap_residue"})
            residues_out.append((ci, ref, item["atoms"], set()))
            continue
        ch, r = payload
        resname = "MET" if r.name == "MSE" else r.name
        ref = seven(model.num, ch, r, resname)
        if item["resname"] != resname:
            raise SystemExit("PDBFixer renamed an observed residue")
        inputs = {}
        for a in r:
            nm = "SD" if (r.name == "MSE" and a.name == "SE") else a.name
            inputs[nm] = (a.pos.x, a.pos.y, a.pos.z)
        names_out = [a[0] for a in item["atoms"]]
        if not set(inputs) <= set(names_out):
            raise SystemExit(f"PDBFixer removed observed atoms in {ref}")
        new_names = []
        for name, el, xyz in item["atoms"]:
            if name in inputs:
                d = math.dist(xyz, inputs[name])
                max_delta = max(max_delta, d)
                unchanged += 1
            else:
                new_names.append(name)
                added.append({"residue": ref, "atom_name": name, "element": el, "coordinates_A": xyz,
                              "origin": "oxt" if name == "OXT" else "side_chain"})
        sc = [n for n in new_names if n != "OXT"]
        if sc:
            side_chain.append({"residue": ref, "added_atoms": sc})
        if "OXT" in new_names:
            oxt.append({"residue": ref})
        residues_out.append((ci, ref, item["atoms"], set(inputs)))
    hydrogens = sum(1 for a in added if a["element"] in {"H", "D"})
    # independent template expectation (classify_structures logic): side-chain names per residue + OXT
    expected_sc = {}
    for ci, (name, pol) in enumerate(chains):
        for idx, (ch, r) in enumerate(pol):
            obs = {("SD" if (r.name == "MSE" and a.name == "SE") else a.name) for a in r}
            miss = tpl.expected(r.name, terminal=idx == len(pol) - 1) - obs - {"N", "CA", "C", "O"}
            if miss:
                expected_sc[json.dumps(seven(model.num, ch, r, "MET" if r.name == "MSE" else r.name),
                                       sort_keys=True)] = sorted(miss)
    got_sc = {}
    for s in side_chain:
        got_sc.setdefault(json.dumps(s["residue"], sort_keys=True), []).extend(s["added_atoms"])
    for o in oxt:
        got_sc.setdefault(json.dumps(o["residue"], sort_keys=True), []).append("OXT")
    got_sc = {k: sorted(v) for k, v in got_sc.items()}
    template_match = got_sc == expected_sc
    gap_template_match = all(
        sorted(a[0] for a in atoms) == sorted(tpl.expected(ref["resname"], terminal=False))
        for ci, ref, atoms, inputs in residues_out if not inputs)
    # clash record and peptide links
    coords, owner, cls = [], [], []
    flat_index = {}
    for k, (ci, ref, atoms, inputs) in enumerate(residues_out):
        flat_index[k] = ci
        for name, el, xyz in atoms:
            if el in {"H", "D"}:
                continue
            coords.append(xyz)
            owner.append(k)
            cls.append("protein")
    keep_st, _ = prepared_view(path, "keep_all")
    partners = {"ligand": [], "metal": [], "water": []}
    for ch in keep_st[0]:
        for r in ch:
            if r.het_flag == "A" or r.label_seq is not None:
                continue
            kind = "water" if r.is_water() else "metal" if r.name in METALS else "ligand"
            partners[kind].extend((a.pos.x, a.pos.y, a.pos.z) for a in r if a.element.name not in {"H", "D"})
    coords = np.array(coords)
    owner = np.array(owner)
    chain_of = np.array([flat_index[o] for o in owner])
    new_mask = []
    for k, (ci, ref, atoms, inputs) in enumerate(residues_out):
        for name, el, xyz in atoms:
            if el in {"H", "D"}:
                continue
            new_mask.append(name not in inputs)
    new_mask = np.array(new_mask)
    clash = {"protein": {"min_distance_A": None, "count_lt_2_0": 0, "count_lt_1_5": 0}}
    mins = []
    for i in np.where(new_mask)[0]:
        d = np.linalg.norm(coords - coords[i], axis=1)
        neighbour = (owner == owner[i]) | ((np.abs(owner - owner[i]) == 1) & (chain_of == chain_of[i]))
        d = d[~neighbour]
        mins.append(float(d.min()) if d.size else math.inf)
    mins = np.array(mins)
    if mins.size:
        clash["protein"] = {"min_distance_A": float(mins.min()), "count_lt_2_0": int((mins < 2.0).sum()),
                            "count_lt_1_5": int((mins < 1.5).sum())}
    for kind, pts in partners.items():
        if not pts or not mins.size:
            clash[kind + "_keep_all"] = {"min_distance_A": None, "count_lt_2_0": 0, "count_lt_1_5": 0,
                                         "partners": len(pts)}
            continue
        p = np.array(pts)
        m = np.array([np.linalg.norm(p - coords[i], axis=1).min() for i in np.where(new_mask)[0]])
        clash[kind + "_keep_all"] = {"min_distance_A": float(m.min()), "count_lt_2_0": int((m < 2.0).sum()),
                                     "count_lt_1_5": int((m < 1.5).sum()), "partners": len(pts)}
    links = []
    for k in range(1, len(residues_out)):
        if residues_out[k][0] != residues_out[k - 1][0]:
            continue
        c = next((a[2] for a in residues_out[k - 1][2] if a[0] == "C"), None)
        n = next((a[2] for a in residues_out[k][2] if a[0] == "N"), None)
        if c and n:
            links.append(math.dist(c, n))
    links = np.array(links)
    gaps = [{"chain_auth": chains[ci][0], "after_residue": seven(model.num, *chains[ci][1][idx - 1]),
             "before_residue": seven(model.num, *chains[ci][1][idx]), "length": len(rows), "residues": rows}
            for (ci, idx), rows in sorted(plan.items())]
    heavy_after = int(len(coords))
    return {"file": rel(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "waters": waters,
            "seed": seed, "pdbfixer_version": version("pdbfixer"), "openmm_version": version("openmm"),
            "platform": "CPU Threads=1", "seconds_addMissingAtoms": round(seconds, 3),
            "seconds_total_fixer": round(total, 3), "flagged_before_add": flagged,
            "counts": {"added_atoms": len(added), "added_hydrogens": hydrogens,
                       "added_residues": sum(len(r) for r in plan.values()), "gaps": len(plan),
                       "side_chain_residues": len(side_chain), "terminal_oxt": len(oxt),
                       "observed_atoms_returned": unchanged, "protein_heavy_after": heavy_after},
            "observed_max_delta_A": max_delta, "template_match": template_match,
            "gap_residue_template_match": gap_template_match, "clash": clash,
            "peptide_links": {"count": int(links.size), "min_A": float(links.min()) if links.size else None,
                              "max_A": float(links.max()) if links.size else None,
                              "outside_1_1_to_1_7": int(((links < 1.1) | (links > 1.7)).sum())},
            "gaps": gaps, "side_chain_repairs": side_chain, "terminal_oxt": oxt, "added_atoms": added}


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("one", "additions"))
    ap.add_argument("file", type=Path)
    ap.add_argument("--waters", default="strip_all", choices=("strip_all", "keep_all"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    result = measure(args.file, args.waters, args.seed)
    if args.mode == "one":
        raw = canonical(result)
        args.out.write_bytes(raw)
        additions_digest = hashlib.sha256(canonical(result["added_atoms"])).hexdigest()
        print(f"{rel(args.file)}\t{args.waters}\tseed={args.seed}\taddMissingAtoms_s={result['seconds_addMissingAtoms']}"
              f"\tcounts={json.dumps(result['counts'], sort_keys=True)}\tobserved_max_delta_A="
              f"{result['observed_max_delta_A']:.3e}\ttemplate_match={result['template_match']}"
              f"\tgap_template_match={result['gap_residue_template_match']}\tclash_protein="
              f"{json.dumps(result['clash']['protein'], sort_keys=True)}\tpeptide_links="
              f"{json.dumps(result['peptide_links'], sort_keys=True)}\tadded_atoms_sha256={additions_digest}"
              f"\t{netguard.summary()}")
        return 0
    if args.waters != "strip_all" or args.seed != 1:
        raise SystemExit("the fixture form is strip_all, seed 1")
    keep = measure(args.file, "keep_all", 1)
    fixture = {
        "schema": "m29_t1_pdbfixer_measured_additions@1",
        "label": "PDBFixer 측정 고정 자료(제품 값 아님) / PDBFixer-measured fixture, not a product value",
        "produced_by": "docs/qa/m29-repair-20261013/probe/pdbfixer_measure.py additions (M29 T1 (j), prototype)",
        "input": {"file": result["file"], "sha256": result["input_sha256"],
                  "size_bytes": args.file.stat().st_size},
        "procedure": {"prepared_view": "gemmi re-implementation of prepare_structure (model 0, hydrogens strip, "
                                       "altloc highest_occupancy, waters strip_all)",
                      "pdbfixer_input": "protein polymer residues only, chain parts merged by author chain, M21-style "
                                        "PDBx text (chain id str(index), residue id str(global index + 1))",
                      "missing_residues": "set explicitly from _entity_poly_seq + _pdbx_unobs_or_zero_occ_residues "
                                          "(occupancy_flag 1) internal gaps only; findMissingResidues not used",
                      "engine": f"PDBFixer {result['pdbfixer_version']} / OpenMM {result['openmm_version']} "
                                f"{result['platform']}", "seed": 1,
                      "coordinates": "full float precision (Angstrom = PDBFixer nm * 10), not rounded"},
        "water_policy_independent": canonical(keep["added_atoms"]) == canonical(result["added_atoms"]),
        "counts": result["counts"], "observed_max_delta_A": result["observed_max_delta_A"],
        "clash": result["clash"], "peptide_links": result["peptide_links"],
        "gaps": result["gaps"], "side_chain_repairs": result["side_chain_repairs"],
        "terminal_oxt": result["terminal_oxt"], "added_atoms": result["added_atoms"]}
    args.out.write_text(json.dumps(fixture, indent=1, sort_keys=True, allow_nan=False) + "\n")
    print(f"wrote {rel(args.out)} bytes={args.out.stat().st_size} water_policy_independent="
          f"{fixture['water_policy_independent']} added_atoms={len(fixture['added_atoms'])} {netguard.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
