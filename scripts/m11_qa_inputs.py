#!/usr/bin/env python3
"""Deterministically rebuild the M11 QA synthetic derivative inputs from the public ProLIF fixtures.

Outputs are synthetic derivatives of the licensed public ProLIF tutorial receptor/SDF, not
experimental evidence (see backend/tests/fixtures/chemical/SYNTHETIC-PROVENANCE.md). Each
output must match its pinned SHA-256 or the script exits non-zero without writing it.

- m11-attach-complex.pdb: public receptor text up to its first CONECT, plus public SDF record 0
  atoms as HETATM LIG chain L residue 1, names X1..X79, serials from 4989, then END.
- m11-synthetic-empty-1000A.sdf: public SDF with only record 0 coordinates translated by
  (+1000, +1000, +1000) A (the transformation in test_native_valid_empty_after_ligand_translation).
- m11-attach-receptor-edges.json: 0-based receptor atom index pairs from the public receptor's
  PDB CONECT records (same result as the product pdb_conect connectivity path).

Usage: .venv/bin/python scripts/m11_qa_inputs.py --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "backend/tests/fixtures/chemical"
RECEPTOR = FIXTURES / "prolif-vina-rec.pdb"
LIGAND_SDF = FIXTURES / "prolif-vina-output.sdf"
RECEPTOR_SHA = "745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc"
LIGAND_SHA = "810b8c714edd3140585664f980c8e6644ba9c76372029cb3abbfa4d13b5899e0"
EXPECTED = {
    "m11-attach-complex.pdb": "9c4426ae0c459e656040b11c10e51e36ff09b7a4adeb5c162d1b2dc32f96ee03",
    "m11-synthetic-empty-1000A.sdf": "a856c3c5495ad5d757575d780ebe0fc95f1111d1805f51545f5f3f026591a778",
    "m11-attach-receptor-edges.json": "76b01a9e3e02d27fe31a1aa3887a82c722dce6c7b2ab4c953b4c624dd758b03f",
}
RECEPTOR_ATOMS = 4988
LIGAND_ATOMS = 79
EDGE_COUNT = 5053


def verify(name: str, data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    expected = EXPECTED.get(name, {"prolif-vina-rec.pdb": RECEPTOR_SHA, "prolif-vina-output.sdf": LIGAND_SHA}.get(name))
    if digest != expected:
        raise SystemExit(f"SHA-256 mismatch for {name}: {digest} != {expected}")
    return data


def _record0_atoms(sdf: str) -> list[tuple[float, float, float, str]]:
    lines = sdf.split("$$$$")[0].splitlines()
    count = int(lines[3][0:3])
    return [(*(float(line[j:j + 10]) for j in (0, 10, 20)), line[31:34].strip().upper())
            for line in lines[4:4 + count]]


def attach_complex(receptor: str, sdf: str) -> bytes:
    ligand = [f"HETATM{4989 + i:5d} {f'X{i + 1}':<4s} LIG L   1    {x:8.3f}{y:8.3f}{z:8.3f}"
              f"{1.00:6.2f}{0.00:6.2f}          {element:>2s}  "
              for i, (x, y, z, element) in enumerate(_record0_atoms(sdf))]
    return (receptor.split("CONECT")[0] + "\n".join(ligand) + "\nEND\n").encode()


def empty_translated_sdf(sdf: str) -> bytes:
    records = sdf.split("$$$$")
    first_lines = records[0].splitlines()
    count = int(first_lines[3][0:3])
    for i in range(4, 4 + count):
        line = first_lines[i]
        shifted = [float(line[j:j + 10]) + 1000.0 for j in (0, 10, 20)]
        first_lines[i] = "".join(f"{x:10.4f}" for x in shifted) + line[30:]
    records[0] = "\n".join(first_lines) + "\n"
    return "$$$$".join(records).encode()


def receptor_edges(receptor: str) -> bytes:
    serials = [int(line[6:11]) for line in receptor.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    if len(serials) != RECEPTOR_ATOMS or len(set(serials)) != len(serials):
        raise SystemExit("public receptor atom serials are not the expected unique set")
    lookup = {serial: index for index, serial in enumerate(serials)}
    pairs: set[tuple[int, int]] = set()
    for line in receptor.splitlines():
        if not line.startswith("CONECT"):
            continue
        values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
        for second in values[1:]:
            if values[0] not in lookup or second not in lookup or values[0] == second:
                raise SystemExit("dangling or self PDB CONECT in public receptor")
            pairs.add(tuple(sorted((lookup[values[0]], lookup[second]))))
    if len(pairs) != EDGE_COUNT:
        raise SystemExit(f"expected {EDGE_COUNT} receptor edges, found {len(pairs)}")
    payload = {"schema": "m11_attach_receptor_edge_indices@1", "public_receptor_sha256": RECEPTOR_SHA,
               "expected_receptor_atoms": RECEPTOR_ATOMS, "expected_ligand_atoms": LIGAND_ATOMS,
               "edges": [list(pair) for pair in sorted(pairs)]}
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def build_inputs() -> dict[str, bytes]:
    receptor = verify("prolif-vina-rec.pdb", RECEPTOR.read_bytes()).decode()
    sdf = verify("prolif-vina-output.sdf", LIGAND_SDF.read_bytes()).decode()
    built = {"m11-attach-complex.pdb": attach_complex(receptor, sdf),
             "m11-synthetic-empty-1000A.sdf": empty_translated_sdf(sdf),
             "m11-attach-receptor-edges.json": receptor_edges(receptor)}
    return {name: verify(name, data) for name, data in built.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="output directory (use a git-ignored path, not /tmp)")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    built = build_inputs()
    out.mkdir(parents=True, exist_ok=True)
    for name, data in built.items():
        (out / name).write_bytes(data)
    print(json.dumps({"out": str(out), "public_receptor": str(RECEPTOR), "public_ligand_sdf": str(LIGAND_SDF),
                      "files": {name: {"sha256": EXPECTED[name], "bytes": len(data)} for name, data in built.items()}},
                     indent=2))


if __name__ == "__main__":
    main()
