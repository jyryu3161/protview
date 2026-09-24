"""PyRosetta worker entry point. Runs ONE job per process and prints ONE JSON line.

    python -m mw.jobs.rosetta_worker '{"id":..., "protocol":..., "params":{...}, "seed":...}'

Every result records: rosetta version, scorefxn name, seed, wall clock.
Units are REU. Do not convert to kcal/mol here (display concern).
TODO(M4): implement the protocol bodies; keep outputs matching the schemas in docs/contracts.md.
"""
from __future__ import annotations

import json
import sys
import time


def _fail(cls: str, msg: str) -> None:
    print(json.dumps({"error": cls, "message": msg}))
    sys.exit(1)


def main(arg: str) -> None:
    job = json.loads(arg)
    try:
        import pyrosetta  # noqa: F401  (licensed, installed separately)
    except ImportError:
        _fail("fatal", "PyRosetta is not installed in this environment")
    seed = int(job["seed"])
    pyrosetta.init(f"-mute all -constant_seed -jran {seed}")
    t0 = time.time()
    proto = job["protocol"]
    p = job["params"]
    if proto == "relax":
        # pose = pyrosetta.pose_from_file(p["input_pdb"]); FastRelax(scorefxn, ...) with
        # cartesian settings when scorefxn endswith _cart; dump to p["output_pdb"]
        _fail("fatal", "relax not implemented yet (M4)")
    elif proto == "cartesian_ddg":
        # per mutation: `iterations` rounds of WT and MUT; report mean/sd of total and per-term deltas
        _fail("fatal", "cartesian_ddg not implemented yet (M4)")
    elif proto == "interface_analyzer":
        # InterfaceAnalyzerMover(p["interface"]): dG_separated, dSASA_int, packstat, delta_unsatHbonds, hbonds_int
        _fail("fatal", "interface_analyzer not implemented yet (M4)")
    else:
        _fail("input_invalid", f"unknown protocol {proto}")
    print(json.dumps({"rosetta_version": pyrosetta.__version__, "seed": seed, "wall_s": time.time() - t0}))


if __name__ == "__main__":
    main(sys.argv[1])
