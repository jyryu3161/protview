# PROTOTYPE (M29 T1 (g) measurement only; never product code, never imported by mw).
"""Run the unmodified M21 worker on a repaired 8VF6 (one candidate) and count the M18 receptor atoms.

    PYTHONPATH=backend .venv/bin/python docs/qa/m29-repair-20261013/probe/m21_on_repaired.py <runs-root> \
        [--variant round4|full_precision] [--residue A:122:LEU] [--mutant ALA] [--waters strip_all]

8VF6 is loaded/prepared with the product tools in a throwaway run under ``<runs-root>`` (Git-ignored, not /tmp);
the repaired mmCIF is spliced from the stored prepared coordinates + probe/8vf6_additions.json (calc_flag marker);
the M7 projection comes from the unmodified `openmm_method.preflight` through a read-only overlay (nothing stored);
the staged payload is built exactly as `mutation_model_bundle.selection` builds it (pins from `require_ready()`),
and the worker `backend/mw/jobs/openmm_mutation_worker.py` is launched like the guardian does
(`<venv python> -I <worker>`, cwd = a private attempt directory, minimal environment). The wall time of that one
process is the "single job" time (staging/guardian/publication excluded). The M18 receptor atom count is the number
of atom rows of each output mmCIF (M18 counts every atom row of the receptor, hydrogens included; limit 10,000).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402,F401
from marker_and_preflight import Overlay, pending_objects  # noqa: E402
from splice_prototype import build  # noqa: E402

import gemmi  # noqa: E402

from mw import mutation_model_bundle as mmb  # noqa: E402
from mw.core.handles import canonical_json  # noqa: E402
from mw.tools.openmm_method import preflight  # noqa: E402
from mw.workspace import new_run  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
SOURCE = REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif"
WORKER = REPO / "backend" / "mw" / "jobs" / "openmm_mutation_worker.py"
ADDITIONS = REPO / "docs" / "qa" / "m29-repair-20261013" / "probe" / "8vf6_additions.json"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--variant", default="round4", choices=("round4", "full_precision"))
    ap.add_argument("--residue", default="A:122:LEU")
    ap.add_argument("--mutant", default="ALA")
    ap.add_argument("--waters", default="strip_all", choices=("strip_all", "keep_all"))
    ap.add_argument("--seed", type=int, default=1207)
    ap.add_argument("--source", type=Path, default=SOURCE, help="input mmCIF (default 8VF6)")
    ap.add_argument("--additions", type=Path, default=ADDITIONS,
                    help="additions JSON with gaps + added_atoms (8vf6_additions.json or pdbfixer_measure one output)")
    args = ap.parse_args(argv)
    if str(args.root.resolve()).startswith(("/tmp", "/private/tmp")):
        raise SystemExit("root must not be under /tmp")
    args.root.mkdir(parents=True, exist_ok=False)
    run = new_run(args.root / "base", dry_run=False, run_id="run_m29t1_m21")
    raw = args.source.read_bytes()
    src = run.call("load_structure", {"source": args.source.name, "model_index": 0}, source_bytes=raw,
                   source_format="cif")
    prep = run.call("prepare_structure", {"structure": src.handle, "altloc": "highest_occupancy",
                                          "waters": args.waters, "hydrogens": "strip",
                                          "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    prepared = run.store.load(prep.handle)
    prepared["__handle__"] = prep.handle
    manifest = run.store.load(prepared["manifest"])
    text = build(run.store.load(prepared["coordinates"]).decode(), json.loads(args.additions.read_text()),
                 decimals=4 if args.variant == "round4" else None, marker="calc_flag")
    sh, pending = pending_objects(run.store.run_id, prepared, manifest, text)
    view = Overlay(run.store, pending)
    projection = preflight(view, sh, seed=args.seed)
    if args.residue == "auto":   # first LEU of the projection
        found = [next(r["residue"] for c in projection["protein"] for r in c["residues"]
                      if r["residue"]["resname"] == "LEU")]
        args.residue = f"{found[0]['chain_auth']}:{found[0]['seq_auth']}:LEU"
    else:
        chain, seq, resname = args.residue.split(":")
        found = [r["residue"] for c in projection["protein"] for r in c["residues"]
                 if r["residue"]["chain_auth"] == chain and r["residue"]["seq_auth"] == int(seq)
                 and r["residue"]["resname"] == resname]
    if len(found) != 1:
        raise SystemExit("residue not found exactly once in the projection")
    pins = mmb.require_ready()
    payload = {"schema": mmb.INPUT_SCHEMA, "method": pins["method"], "model_number": projection["model_number"],
               "protein": projection["protein"], "seed": args.seed, "residue": found[0],
               "mutant_resname": args.mutant, "contact_cutoff_A": 4.0}
    staged = canonical_json(payload)
    attempt = args.root / "attempt"
    (attempt / "tmp").mkdir(parents=True)
    (attempt / "structure.json").write_bytes(staged)
    (attempt / "input.json").write_text(json.dumps({"input_sha256": hashlib.sha256(staged).hexdigest()}))
    env = {"LANG": "C", "PYTHONUTF8": "1", "TMPDIR": str((attempt / "tmp").resolve()), "PATH": "/usr/bin:/bin"}
    t0 = time.perf_counter()
    proc = subprocess.run([str(REPO / ".venv" / "bin" / "python"), "-I", str(WORKER)], cwd=attempt, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    line = {"source": args.source.name, "variant": args.variant, "waters": args.waters, "residue": args.residue, "mutant": args.mutant,
            "projection_heavy_atoms": projection["heavy_atom_count"], "staged_bytes": len(staged),
            "staged_limit": mmb.STAGED_LIMIT, "worker_exit": proc.returncode, "worker_wall_s": round(wall, 2),
            "timeout_default_s": 120, "timeout_max_s": 240}
    if (attempt / "result.json").exists():
        result = json.loads((attempt / "result.json").read_text())
        line["result_bytes"] = (attempt / "result.json").stat().st_size
        for side, cif in result["structure_cifs"].items():
            model = gemmi.make_structure_from_block(gemmi.cif.read_string(cif).sole_block())[0]
            atoms = [a for ch in model for r in ch for a in r]
            line[f"{side}_atoms_total"] = len(atoms)
            line[f"{side}_atoms_hydrogen"] = sum(1 for a in atoms if a.element.name in {"H", "D"})
        line["m18_receptor_atom_limit"] = 10_000
    if (attempt / "error.json").exists():
        line["error"] = json.loads((attempt / "error.json").read_text())
    if proc.returncode and not (attempt / "error.json").exists():
        line["stderr_tail"] = proc.stderr[-400:]
    print(json.dumps(line, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
