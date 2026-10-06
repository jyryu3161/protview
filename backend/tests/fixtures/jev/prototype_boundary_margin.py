"""PROTOTYPE (M24 T1 measurement only): how close do 1UBQ / 1MQ4 residue pairs come to the 5.0 A neighbor boundary,
and do the oracle's ``math.dist`` and an M20-style NumPy minimum (``sqrt(sum(diff**2))``, float64) agree?

Membership (<= 5.0) must be identical; values may differ in the last bits, so later tests compare distances with an
absolute tolerance. Imports gemmi, numpy and the oracle module only (no ``mw``). Prints one JSON report.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import independent_neighbors as oracle


def numpy_min(a: list[tuple[float, float, float]], b: list[tuple[float, float, float]]) -> float:
    left, right = np.array(a, dtype=np.float64), np.array(b, dtype=np.float64)
    diff = left[:, None, :] - right[None, :, :]
    return float(np.sqrt((diff * diff).sum(axis=2)).min())


def main() -> int:
    report = {}
    for name, path in oracle.STRUCTURES.items():
        protein = [entry for entry in oracle.residues(oracle.load_path(path)) if entry["protein"] and entry["heavy"]]
        closest, membership_mismatch, max_abs_diff, unequal_values, pairs = math.inf, 0, 0.0, 0, 0
        for i, left in enumerate(protein):
            for right in protein[i + 1:]:
                exact = oracle.min_distance(left["heavy"], right["heavy"])
                fast = numpy_min(left["heavy"], right["heavy"])
                pairs += 1
                closest = min(closest, abs(exact - oracle.NEIGHBOR_RADIUS_A))
                membership_mismatch += (exact <= oracle.NEIGHBOR_RADIUS_A) != (fast <= oracle.NEIGHBOR_RADIUS_A)
                max_abs_diff = max(max_abs_diff, abs(exact - fast))
                unequal_values += exact != fast
        report[name] = {"residue_pairs": pairs, "closest_to_5A_boundary": closest,
                        "membership_mismatch_math_vs_numpy": membership_mismatch,
                        "values_not_bit_identical": unequal_values, "max_abs_difference": max_abs_diff}
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
