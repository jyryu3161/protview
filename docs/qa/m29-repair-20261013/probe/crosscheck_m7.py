# PROTOTYPE (M29 T1 (a) cross-check only; never product code, never imported by mw).
"""Product M7 preflight on the original prepared structures and on the spliced repaired ones (both water policies).

The independent classification (classify_structures.py, gemmi + template XML only) is the expectation; this script
only reports what the unmodified product `openmm_method.preflight` says, so the two can be compared. Repaired
structures are spliced (splice_prototype.build, round4 + calc_flag) from the stored prepared coordinates and a
PDBFixer measurement (`pdbfixer_measure.py one` output, strip_all seed 1; the additions do not depend on the water
policy because PDBFixer sees the protein only) and are read through a read-only overlay (never stored). 1FIN gets a
merge-only splice (empty additions); 1S9I is not spliced (its gaps exceed 20 residues).

    PYTHONPATH=backend .venv/bin/python docs/qa/m29-repair-20261013/probe/crosscheck_m7.py <runs-root> <measure-dir>

``<measure-dir>`` holds ``<id>_strip_all_s1_a.json`` from pdbfixer_measure.py (8VF6: probe/8vf6_additions.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402
from marker_and_preflight import Overlay, pending_objects  # noqa: E402
from splice_prototype import build  # noqa: E402

from mw.core.errors import ToolFailure  # noqa: E402
from mw.tools.openmm_method import preflight  # noqa: E402
from mw.workspace import new_run  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "backend" / "tests" / "fixtures"


def verdict(fn) -> str:
    try:
        out = fn()
        return f"pass heavy={out['heavy_atom_count']} chains={','.join(c['chain_auth'] for c in out['protein'])}"
    except ToolFailure as exc:
        res = (exc.detail or {}).get("residue") or {}
        at = f" at {res.get('chain_auth')}/{res.get('seq_auth')}{res.get('icode') or ''}/{res.get('resname')}" if res else ""
        return f"fail {exc.cls.value} {(exc.detail or {}).get('reason_code')} '{exc.message}'{at}"


def main(argv: list[str]) -> int:
    root, measure = Path(argv[0]), Path(argv[1])
    if str(root.resolve()).startswith(("/tmp", "/private/tmp")):
        raise SystemExit("root must not be under /tmp")
    root.mkdir(parents=True, exist_ok=False)
    inputs = {"1M17": FIX / "public_1m17.cif", "1FIN": FIX / "public_1fin.cif", "1MQ4": FIX / "public_1mq4.cif",
              "1S9I": FIX / "public_1s9i.cif", "1A30": FIX / "public_1a30.cif", "1A4I": FIX / "public_1a4i.cif",
              "1UBQ": FIX / "public_1ubq.cif", "1HSG": FIX / "public_1hsg.cif",
              "8VF6": REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif"}
    print("pdb\twaters\toriginal_M7\trepaired_M7")
    for pdb, path in inputs.items():
        run = new_run(root, dry_run=False, run_id=f"run_m29t1_x_{pdb.lower()}")
        src = run.call("load_structure", {"source": path.name, "model_index": 0}, source_bytes=path.read_bytes(),
                       source_format="cif")
        if pdb == "8VF6":
            additions = json.loads((REPO / "docs/qa/m29-repair-20261013/probe/8vf6_additions.json").read_text())
        elif pdb in {"1FIN", "1UBQ"}:
            additions = {"gaps": [], "added_atoms": []}
        elif pdb == "1S9I":
            additions = None
        else:
            additions = json.loads((measure / f"{pdb.lower()}_strip_all_s1_a.json").read_text())
        for waters in ("strip_all", "keep_all"):
            prep = run.call("prepare_structure", {"structure": src.handle, "altloc": "highest_occupancy",
                                                  "waters": waters, "hydrogens": "strip",
                                                  "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
            original = verdict(lambda: preflight(run.store, prep.handle, seed=run.seed))
            if additions is None:
                repaired = "not spliced (gap > 20 residues)"
            else:
                prepared = run.store.load(prep.handle)
                prepared["__handle__"] = prep.handle
                text = build(run.store.load(prepared["coordinates"]).decode(), additions, decimals=4,
                             marker="calc_flag")
                sh, pending = pending_objects(run.store.run_id, prepared, run.store.load(prepared["manifest"]), text)
                repaired = verdict(lambda: preflight(Overlay(run.store, pending), sh, seed=run.seed))
            print(f"{pdb}\t{waters}\t{original}\t{repaired}")
    print(f"# {netguard.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
