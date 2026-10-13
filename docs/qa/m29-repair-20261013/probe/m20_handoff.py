# PROTOTYPE (M29 T1 (d) measurement only; never product code, never imported by mw).
"""M20 hand-off of original-structure reference results to a repaired structure, without changing any product file.

    PYTHONPATH=backend .venv/bin/python docs/qa/m29-repair-20261013/probe/m20_handoff.py <runs-root>

In a throwaway run under ``<runs-root>`` (Git-ignored, not /tmp): 8VF6 -> load/prepare (strip_all) ->
compute_interactions (A1AAY A) -> map_residue_numbering (8VF6, A/B = Q9BYT3, local .deps/reference) ->
annotate_reference_sites -> M20 on the ORIGINAL prepared structure (ligand shell 5 A + numbering + annotation).
Then the repaired 8VF6 (splice_prototype, round4 + calc_flag) is stored IN THIS THROWAWAY RUN as a
prepared_structure@1 whose manifest has `repair`, and:
  1. the product tool on the repaired structure with the original references -> expected `structure_mismatch`
     (shows where the check lives: tools/mutations.py, not the hash file);
  2. the hash-file pure functions called directly (`normalize_request` + `build_candidate_set` + `validated_set`),
     i.e. what T7 gets by relaxing only the tools/mutations.py structure check -> does the set validate, are the
     original klifs_key_site exclusions kept, what is stored for modeled residues;
  3. `modeled_basis` re-derived as a pure function of stored data only (repaired structure bytes + the additions
     list + the set's parameters, using mutation_candidates._walk/_min_distance read-only).
Only identifiers, counts and reason codes are printed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402
from marker_and_preflight import pending_objects  # noqa: E402
from splice_prototype import build  # noqa: E402

from mw import mutation_candidates as mc  # noqa: E402
from mw.core.errors import ToolFailure  # noqa: E402
from mw.mutation_constants import DISULFIDE_SG_A  # noqa: E402
from mw.tools.registry import ToolContext  # noqa: E402
from mw.tools.structural import _parse, structure_residues  # noqa: E402
from mw.workspace import new_run  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
SOURCE = REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif"
ADDITIONS = REPO / "docs" / "qa" / "m29-repair-20261013" / "probe" / "8vf6_additions.json"
LIG_A = {"model_number": 1, "chain_auth": "A", "seq_auth": 600, "icode": "", "chain_label": "C", "seq_label": None,
         "resname": "A1AAY"}


def short(r: dict) -> str:
    return f"{r['chain_auth']}{r['seq_auth']}{r['icode']}/{r['resname']}"


def excluded_by(content: dict, reason: str) -> list[str]:
    return [short(p["residue"]) for p in content["positions"] if reason in p["exclusion_reasons"]]


def scenario(store, run, ph, sh, nm, ann, sources, only_repaired, additions):
    orig_sources = {**sources, "residues": [r for r in sources["residues"] if r not in only_repaired]}
    args = {"structure": ph, "sources": orig_sources, "ligand": LIG_A, "numbering_map": nm, "annotation": ann}
    original = run.call("generate_mutation_candidates", args)
    orig = store.load(original.handle)
    print(f"original M20: positions={orig['counts']['positions']} candidates={orig['counts']['candidates']} "
          f"klifs_key_site={excluded_by(orig, 'klifs_key_site')}")
    args = {**args, "sources": sources}
    # 1. product tool as is
    try:
        run.call("generate_mutation_candidates", {**args, "structure": sh})
        print("1. product tool on repaired + original references: accepted (unexpected)")
    except ToolFailure as exc:
        print(f"1. product tool on repaired + original references: {exc.cls.value} "
              f"{(exc.detail or {}).get('reason_code')} ({exc.message})")
    except Exception as exc:  # noqa: BLE001
        print(f"1. product tool on repaired + original references: {type(exc).__name__}: {str(exc)[:200]}")
    # 2. hash-file pure functions directly (what relaxing only tools/mutations.py would give)
    listing = structure_residues(store, sh)
    params = mc.normalize_request({**args, "structure": sh}, listing["residues"], listing["ligands"])
    st = _parse(ToolContext(store=store, call_id="t1d"), sh)
    content = mc.build_candidate_set(sh, st, params, numbering_content=store.load(nm),
                                     annotation_content=store.load(ann))
    mc.validated_set(content)
    print(f"2. build_candidate_set(repaired, original numbering+annotation): validated_set OK; "
          f"positions={content['counts']['positions']} candidates={content['counts']['candidates']} "
          f"klifs_key_site={excluded_by(content, 'klifs_key_site')}")
    same_klifs = excluded_by(content, "klifs_key_site") == excluded_by(orig, "klifs_key_site")
    print(f"   klifs_key_site exclusions identical to the original set: {same_klifs}")
    orig_pos = {short(p["residue"]): p for p in orig["positions"]}
    rep_pos = {short(p["residue"]): p for p in content["positions"]}
    print(f"   positions only in repaired: {sorted(set(rep_pos) - set(orig_pos))}; "
          f"only in original: {sorted(set(orig_pos) - set(rep_pos))}")
    lost = [k for k, p in orig_pos.items() if k in rep_pos
            and not set(p["protection"]["reasons"]) <= set(rep_pos[k]["protection"]["reasons"])]
    print(f"   original protection reasons lost on observed residues: {lost}")
    gap_keys = {(r["chain_auth"], r["seq_auth"], r["icode"]) for g in additions["gaps"] for r in g["residues"]}
    modeled_side = {(a["residue"]["chain_auth"], a["residue"]["seq_auth"], a["residue"]["icode"])
                    for a in additions["added_atoms"] if a["origin"] in {"side_chain", "oxt"}}
    stored_for_gap = [(short(p["residue"]), p["numbering"]["status"], p["protection"]["klifs_sites"],
                       p["protection"]["catalytic"]) for p in content["positions"]
                      if (p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"]) in gap_keys]
    print(f"   gap-residue positions (stored numbering.status, klifs_sites, catalytic): {stored_for_gap}")
    # 3. modeled_basis as a pure function of stored data
    walk_all = mc._walk(st)
    st_obs = _parse(ToolContext(store=store, call_id="t1d"), sh)
    for ch in st_obs[0]:
        for res in ch:
            for i in range(len(res) - 1, -1, -1):
                if res[i].calc_flag.name == "Calculated":
                    del res[i]
    walk_obs = mc._walk(st_obs)
    by_key_all = {mc.identity(e["residue"]): e for e in walk_all}
    by_key_obs = {mc.identity(e["residue"]): e for e in walk_obs}
    lig_heavy = by_key_obs[mc.identity(content["ligand"]["residue"])]["heavy"]
    radius = content["parameters"]["sources"]["ligand_shell"]["radius_A"]
    rows = []
    for p in content["positions"]:
        key = mc.identity(p["residue"])
        k3 = (p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"])
        has_modeled = k3 in gap_keys or k3 in modeled_side
        obs_heavy = by_key_obs[key]["heavy"]
        shell_obs = bool(len(obs_heavy)) and mc._min_distance(obs_heavy, lig_heavy) <= radius
        shell_all = any(s["kind"] == "ligand_shell" for s in p["sources"])
        sg_all, sg_obs = by_key_all[key]["sg"], by_key_obs[key]["sg"]
        disulfide_changes = len(sg_all) != len(sg_obs)
        reasons = []
        if has_modeled:
            reasons.append("modeled_atoms_in_residue")
        if shell_all != shell_obs:
            reasons.append("ligand_shell_depends_on_modeled_atoms")
        if disulfide_changes:
            reasons.append("sg_is_modeled")
        rows.append((short(p["residue"]), bool(reasons), reasons))
    true_rows = [r for r in rows if r[1]]
    metals = [e for e in walk_all if e["metal"]]
    print(f"3. modeled_basis (pure re-derivation): positions={len(rows)} true={len(true_rows)}; metals in structure="
          f"{len(metals)}; disulfide threshold {DISULFIDE_SG_A} A")
    for r in true_rows:
        print(f"   {r[0]}: {r[2]}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    root = Path(argv[0])
    if str(root.resolve()).startswith(("/tmp", "/private/tmp")):
        raise SystemExit("root must not be under /tmp")
    root.mkdir(parents=True, exist_ok=False)
    run = new_run(root, dry_run=False, run_id="run_m29t1_d")
    store = run.store
    src = run.call("load_structure", {"source": "8VF6.cif", "model_index": 0}, source_bytes=SOURCE.read_bytes(),
                   source_format="cif")
    prep = run.call("prepare_structure", {"structure": src.handle, "altloc": "highest_occupancy", "waters": "strip_all",
                                          "hydrogens": "strip", "missing_residues": "leave_gaps",
                                          "symmetry_mates": "ignore"})
    contacts = run.call("compute_interactions", {"structure": prep.handle, "ligand": LIG_A, "cutoff_A": 4.0,
                                                 "types": ["contact", "polar_contact", "hydrophobic_contact"],
                                                 "engine": "geometric"})
    nm = run.call("map_residue_numbering", {"structure": prep.handle, "pdb_id": "8VF6",
                                            "chains": [{"chain_auth": "A", "uniprot_accession": "Q9BYT3"},
                                                       {"chain_auth": "B", "uniprot_accession": "Q9BYT3"}]})
    ann = run.call("annotate_reference_sites", {"numbering_map": nm.handle, "contacts": contacts.handle})
    additions = json.loads(ADDITIONS.read_text())
    prepared = store.load(prep.handle)
    prepared["__handle__"] = prep.handle
    text = build(store.load(prepared["coordinates"]).decode(), additions, decimals=4, marker="calc_flag")
    sh, pending = pending_objects(store.run_id, prepared, store.load(prepared["manifest"]), text)
    for h, p in sorted(pending.items(), key=lambda kv: ["prepared_coordinates", "preparation_manifest",
                                                       "prepared_structure"].index(kv[1]["kind"])):
        assert store.put(p["kind"], p["schema"], p["content"], fmt=p["fmt"]).handle == h
    gap_residue = additions["gaps"][0]["residues"][7]
    gap_ref = {k: gap_residue[k] for k in ("model_number", "chain_auth", "seq_auth", "icode", "chain_label",
                                           "seq_label", "resname")}
    side = next(a["residue"] for a in additions["added_atoms"] if a["origin"] == "side_chain")
    oxt = next(a["residue"] for a in additions["added_atoms"] if a["origin"] == "oxt")
    scenarios = {
        "S1 ligand_shell 5 A (the 8VF6 probe request)": ({"pocket": None, "ligand_shell": {"radius_A": 5.0},
                                                          "residues": []}, []),
        "S2 ligand_shell 12 A + user residues (side-chain-repaired, OXT, one gap residue)": (
            {"pocket": None, "ligand_shell": {"radius_A": 12.0}, "residues": [side, oxt, gap_ref]}, [gap_ref]),
    }
    for name, (sources, only_repaired) in scenarios.items():
        print(f"## {name}")
        scenario(store, run, prep.handle, sh, nm.handle, ann.handle, sources, only_repaired, additions)
    print(f"# {netguard.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
