# PROTOTYPE (M29 T1 (c) measurement only; never product code, never imported by mw).
"""Would a marker collide with values already present in real inputs? (gemmi only)

For the eight local public fixtures and 8VF6: does `_atom_site.calc_flag` already exist, how many atoms have
occupancy 0 (why occupancy 0 cannot mark new atoms), how many have B_iso 0 (why a B-factor sentinel is ambiguous),
and the largest number of decimals in the coordinate cells (M21 hands coordinates to PDBFixer as %10.4f text).

    .venv/bin/python docs/qa/m29-repair-20261013/probe/input_marker_survey.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import gemmi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_structures import DEFAULT, rel  # noqa: E402


def decimals(cell: str) -> int:
    return len(cell.split(".", 1)[1]) if "." in cell else 0


def main() -> int:
    print("file\tatom_rows\tcalc_flag_column\tcalc_flag_values\toccupancy_0\tB_iso_0\tmax_coordinate_decimals")
    for path in DEFAULT:
        block = gemmi.cif.read(str(path)).sole_block()
        table = block.find_mmcif_category("_atom_site.")
        tags = list(table.tags)
        flag = "_atom_site.calc_flag" in tags
        values = sorted(set(block.find_values("_atom_site.calc_flag"))) if flag else []
        occ = [float(v) for v in block.find_values("_atom_site.occupancy")]
        biso = [float(v) for v in block.find_values("_atom_site.B_iso_or_equiv")]
        dec = max(decimals(v) for axis in "xyz" for v in block.find_values(f"_atom_site.Cartn_{axis}"))
        print(f"{rel(path)}\t{len(occ)}\t{flag}\t{values}\t{sum(o == 0 for o in occ)}\t{sum(b == 0 for b in biso)}\t{dec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
