# PROTOTYPE (M28 T1 (c) measurement only; never product code, never imported by mw).
"""Re-run the M7 OpenMM preflight on the eight local public structures under both water policies.

For each ``backend/tests/fixtures/public_<id>.cif`` and each ``waters`` value (``keep_all`` / ``strip_all``) this
makes a fresh run with ``mw.workspace.new_run`` under ``<runs-root>``, then ``load_structure`` (model 0) ->
``prepare_structure`` (altloc highest_occupancy, hydrogens strip, leave_gaps, ignore) -> ``mw.tools.openmm_method
.preflight`` (the unmodified product function M21/M23 admission uses). No engine minimisation, no network.

    PYTHONPATH=backend .venv/bin/python docs/qa/m28-final-20261011/m7_probe.py <runs-root>

``<runs-root>`` must be a new Git-ignored folder (e.g. ``runs/m28-preflight-<date>/m7-probe``), not under /tmp.
Output: one tab-separated line per (structure, waters) plus a summary; only IDs, counts and reason codes.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from mw.core.errors import ToolFailure
from mw.tools.openmm_method import preflight
from mw.workspace import new_run

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "backend" / "tests" / "fixtures"
IDS = ("1m17", "1fin", "1mq4", "1s9i", "1a30", "1a4i", "1ubq", "1hsg")
WATERS = ("keep_all", "strip_all")


def probe(root: Path, pdb: str, waters: str) -> dict:
    name = f"public_{pdb}.cif"
    data = (FIXTURES / name).read_bytes()
    run = new_run(root, dry_run=False, run_id=f"run_m7probe_{pdb}_{waters}")
    source = run.call("load_structure", {"source": name, "model_index": 0}, source_bytes=data, source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                              "waters": waters, "hydrogens": "strip",
                                              "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    row = {"pdb": pdb.upper(), "waters": waters, "input_sha256": hashlib.sha256(data).hexdigest()[:16]}
    try:
        selected = preflight(run.store, prepared.handle, seed=run.seed)
    except ToolFailure as exc:
        detail = exc.detail
        residue = detail.get("residue") or {}
        row.update(result="fail", failure_class=exc.cls.value, message=exc.message,
                   reason_code=detail.get("reason_code"),
                   at=(f"{residue.get('chain_auth')}/{residue.get('seq_auth')}{residue.get('icode') or ''}"
                       f"/{residue.get('resname')}" if residue else None))
        return row
    row.update(result="pass", heavy_atom_count=selected["heavy_atom_count"], excluded=len(selected["excluded"]),
               chains=len(selected["protein"]))
    return row


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    root = Path(argv[0])
    if root.exists() and any(root.iterdir()):
        print("runs-root must be new or empty", file=sys.stderr)
        return 2
    if str(root.resolve()).startswith(("/tmp", "/private/tmp")):
        print("runs-root must not be under /tmp", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    rows = [probe(root, pdb, waters) for pdb in IDS for waters in WATERS]
    keys = ("pdb", "waters", "input_sha256", "result", "heavy_atom_count", "excluded", "chains", "failure_class",
            "reason_code", "message", "at")
    print("\t".join(keys))
    for row in rows:
        print("\t".join("" if row.get(k) is None else str(row.get(k)) for k in keys))
    passed = sorted({r["pdb"] for r in rows if r["result"] == "pass"})
    same = all(next(r for r in rows if r["pdb"] == p and r["waters"] == "keep_all").get("result")
               == next(r for r in rows if r["pdb"] == p and r["waters"] == "strip_all").get("result")
               and next(r for r in rows if r["pdb"] == p and r["waters"] == "keep_all").get("reason_code")
               == next(r for r in rows if r["pdb"] == p and r["waters"] == "strip_all").get("reason_code")
               for p in {r["pdb"] for r in rows})
    print(f"# runs={len(rows)} passed_structures={','.join(passed) or '-'} "
          f"same_result_both_water_policies={str(same).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
