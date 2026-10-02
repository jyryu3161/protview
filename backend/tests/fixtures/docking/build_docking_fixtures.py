"""Rebuild the M18 docking fixtures in this folder from the public ProLIF example files (standard library only).

Run: ``python3 backend/tests/fixtures/docking/build_docking_fixtures.py [--check]``. ``--check`` rebuilds in
memory and exits non-zero unless every file on disk is byte-identical. Every output is a labelled derivative of
the public ProLIF 2.2.2 example (``../chemical/prolif-vina-rec.pdb``, ``../chemical/prolif-vina-output.sdf``
record 0) or a hand-written synthetic geometry. None is an experimental structure or an observed binding pose.
See ``SYNTHETIC-PROVENANCE.md``.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHEM = HERE.parent / "chemical"
REC_SHA = "745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc"
SDF_SHA = "810b8c714edd3140585664f980c8e6644ba9c76372029cb3abbfa4d13b5899e0"
TITLE = "PUBLIC-DERIVED-FIXTURE prolif-vina-output.sdf record 0 (not experimental)"


def _read(name: str, sha: str) -> str:
    raw = (CHEM / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise SystemExit(f"public input changed: {name}")
    return raw.decode()


def _record0(sdf: str) -> list[str]:
    lines = sdf.split("\n")
    end = lines.index("$$$$")
    return lines[:end + 1]


def _parse_v2000(rec: list[str]) -> tuple[list[tuple[float, float, float, str]], list[tuple[int, int, str]], list[str]]:
    counts = rec[3]
    n_atoms, n_bonds = int(counts[0:3]), int(counts[3:6])
    atoms = [(float(x[0:10]), float(x[10:20]), float(x[20:30]), x[31:34].strip()) for x in rec[4:4 + n_atoms]]
    bonds = [(int(x[0:3]), int(x[3:6]), x) for x in rec[4 + n_atoms:4 + n_atoms + n_bonds]]
    tail = rec[4 + n_atoms + n_bonds:]
    return atoms, bonds, tail


def parent_sdf(sdf: str) -> str:
    rec = _record0(sdf)
    return "\n".join([TITLE] + rec[1:]) + "\n"


def planar_sdf(sdf: str) -> str:
    rec = _record0(sdf)
    atoms, _, _ = _parse_v2000(rec)
    out = ["SYNTHETIC-FIXTURE planar: record 0 with every z set to 0.0000 (ligand_not_3d negative)"] + rec[1:4]
    for line in rec[4:4 + len(atoms)]:
        out.append(line[:20] + f"{0.0:10.4f}" + line[30:])
    out += rec[4 + len(atoms):]
    return "\n".join(out) + "\n"


def implicit_h_sdf(sdf: str) -> str:
    rec = _record0(sdf)
    atoms, bonds, tail = _parse_v2000(rec)
    heavy = [i for i, a in enumerate(atoms, 1) if a[3] != "H"]
    if heavy != list(range(1, len(heavy) + 1)):
        raise SystemExit("record 0 heavy atoms are not first; renumbering would be needed")
    kept = [b for b in bonds if b[0] <= len(heavy) and b[1] <= len(heavy)]
    counts = rec[3]
    out = ["SYNTHETIC-FIXTURE implicit H: record 0 with all H atoms and H bonds removed (ligand_hydrogens_missing)",
           rec[1], rec[2], f"{len(heavy):3d}{len(kept):3d}" + counts[6:]]
    out += rec[4:4 + len(heavy)] + [b[2] for b in kept] + tail
    return "\n".join(out) + "\n"


def _hetatm(serial: int, name: str, resname: str, chain: str, seq: int, xyz: tuple[float, float, float],
            element: str) -> str:
    return (f"HETATM{serial:5d} {name:<4s} {resname:<3s} {chain}{seq:4d}    {xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
            f"{1.0:6.2f}{0.0:6.2f}          {element:>2s}  ")


def _conect(pairs: list[tuple[int, int]]) -> list[str]:
    neighbours: dict[int, list[int]] = {}
    for a, b in pairs:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    lines = []
    for atom in sorted(neighbours):
        others = neighbours[atom]
        for start in range(0, len(others), 4):
            lines.append(f"CONECT{atom:5d}" + "".join(f"{x:5d}" for x in others[start:start + 4]))
    return lines


def _ligand_block(sdf: str, first_serial: int, shift: tuple[float, float, float] = (0.0, 0.0, 0.0),
                  chain: str = "L", seq: int = 1) -> tuple[list[str], list[tuple[int, int]]]:
    atoms, bonds, _ = _parse_v2000(_record0(sdf))
    counter: dict[str, int] = {}
    lines = []
    for i, (x, y, z, el) in enumerate(atoms):
        counter[el] = counter.get(el, 0) + 1
        name = f"{el}{counter[el]}"
        lines.append(_hetatm(first_serial + i, name, "LIG", chain, seq, (x + shift[0], y + shift[1], z + shift[2]), el))
    pairs = [(first_serial + a - 1, first_serial + b - 1) for a, b, _ in bonds]
    return lines, pairs


def _receptor_parts(rec: str) -> tuple[list[str], list[str]]:
    lines = rec.rstrip("\n").split("\n")
    first = next(i for i, x in enumerate(lines) if x.startswith("CONECT"))
    conect = [x for x in lines[first:] if x.startswith("CONECT")]
    return lines[:first], conect


def complex_pdb(rec: str, sdf: str, *, duplicate: bool = False, covalent: bool = False) -> str:
    head, conect = _receptor_parts(rec)
    lig, pairs = _ligand_block(sdf, 4989)
    body = head + lig
    if duplicate:
        # Two copies with the SAME seven residue fields (model 1, chain L, LIG 1, no label fields in PDB): copy 1
        # between receptor chain A and chain B, copy 2 (translated +40 A in x) after chain B. A chain name that
        # reappears after another chain is read as a separate chain, so the two residues are not merged.
        lig2, pairs2 = _ligand_block(sdf, 4989 + len(lig), (40.0, 0.0, 0.0))
        split = next(i for i, x in enumerate(head) if x.startswith("ATOM") and x[21] == "B")
        body = head[:split] + lig + head[split:] + lig2
        pairs += pairs2
    if covalent:
        # One extra CONECT: ligand C22 (serial 4989+21, N-methyl carbon) to receptor atom serial 1 (CAY, TYR A 38).
        pairs.append((4989 + 21, 1))
    return "\n".join(body + conect + _conect(pairs) + ["END"]) + "\n"


def water_zinc_pdb(rec: str) -> str:
    head, conect = _receptor_parts(rec)
    extra = [_hetatm(4989, "O", "HOH", "W", 1, (60.000, 60.000, 60.000), "O"),
             _hetatm(4990, "H1", "HOH", "W", 1, (60.957, 60.000, 60.000), "H"),
             _hetatm(4991, "H2", "HOH", "W", 1, (59.760, 60.927, 60.000), "H"),
             _hetatm(4992, "ZN", "ZN", "Z", 1, (-60.000, -60.000, -60.000), "ZN")]
    return "\n".join(head + extra + conect + _conect([(4989, 4990), (4989, 4991)]) + ["END"]) + "\n"


def altloc_pdb(rec: str) -> str:
    head, conect = _receptor_parts(rec)
    out = []
    for line in head:
        # Serial 11 is CB of TYR A 38: write it as altloc A, keeping all other atoms unchanged.
        if line.startswith("ATOM") and int(line[6:11]) == 11:
            line = line[:16] + "A" + line[17:]
        out.append(line)
    return "\n".join(out + conect + ["END"]) + "\n"


def build() -> dict[str, str]:
    rec = _read("prolif-vina-rec.pdb", REC_SHA)
    sdf = _read("prolif-vina-output.sdf", SDF_SHA)
    return {
        "public-derived-parent-record0.sdf": parent_sdf(sdf),
        "synthetic-ligand-planar-z0.sdf": planar_sdf(sdf),
        "synthetic-ligand-implicit-h.sdf": implicit_h_sdf(sdf),
        "synthetic-complex-receptor-lig.pdb": complex_pdb(rec, sdf),
        "synthetic-complex-duplicate-instance.pdb": complex_pdb(rec, sdf, duplicate=True),
        "synthetic-complex-covalent-instance.pdb": complex_pdb(rec, sdf, covalent=True),
        "synthetic-receptor-water-zinc.pdb": water_zinc_pdb(rec),
        "synthetic-receptor-altloc.pdb": altloc_pdb(rec),
    }


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    bad = 0
    for name, text in build().items():
        raw = text.encode()
        path = HERE / name
        if check:
            same = path.is_file() and path.read_bytes() == raw
            bad += not same
            print(("OK  " if same else "DIFF"), name)
        else:
            path.write_bytes(raw)
            print(hashlib.sha256(raw).hexdigest(), len(raw), name)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
