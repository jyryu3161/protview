"""Rebuild the hand-written / generated M22 GA building-block fixtures (standard library only).

SYNTHETIC-FIXTURE. Nothing here is a real compound library, a measured value or a docking result.

- ``synthetic-ga-small-blocks.smi``: ten hand-written fixed-replacement blocks (``*`` attachment) for the small
  oracle pool (one parent site, M17 ``replace_single_bond_v1``).
- ``synthetic-ga-pool2000-blocks.smi``: 1,000 generated mono-bromide blocks ``BrC<s>`` where ``<s>`` runs over the
  strings on the alphabet ``C``, ``N``, ``O`` of length 1..6 in (length, lexicographic) order, first 1,000 kept.
  Every string is a distinct linear chain (Br fixes the direction), so the blocks are distinct molecules.
- ``synthetic-ga-pool2000-rules.json``: three user reaction SMARTS that attach the bromide carbon to the site methyl
  carbon directly, through ``O`` and through ``C(=O)``. 1,000 blocks x 3 rules = 3,000 attempts, so the real M17
  enumeration stops at its 2,000-candidate cap (``candidate_limit``).

``python3 backend/tests/fixtures/ligand_ga/build_ligand_ga_fixtures.py --check`` exits 0 only when the files on disk
are byte-identical to a fresh build; without ``--check`` it writes them.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SMALL_BLOCKS = [
    ("*CC", "ethyl"), ("*CCC", "propyl"), ("*C(C)C", "isopropyl"), ("*CCCC", "butyl"),
    ("*C1CC1", "cyclopropyl"), ("*C1CCC1", "cyclobutyl"), ("*CO", "hydroxymethyl"), ("*CF", "fluoromethyl"),
    ("*C(F)(F)F", "trifluoromethyl"), ("*CCO", "hydroxyethyl"),
]
RULES = [
    "[CH3:1].[C:2][Br]>>[C:1][C:2]",
    "[CH3:1].[C:2][Br]>>[C:1]O[C:2]",
    "[CH3:1].[C:2][Br]>>[C:1]C(=O)[C:2]",
]


def small_blocks() -> bytes:
    lines = ["# SYNTHETIC-FIXTURE M22 GA small oracle pool: hand-written fixed-replacement blocks (N-methyl site)"]
    lines += [f"{smiles} {name}" for smiles, name in SMALL_BLOCKS]
    return ("\n".join(lines) + "\n").encode()


def pool_blocks() -> bytes:
    strings = [
        "".join(chars) for length in range(1, 7) for chars in itertools.product("CNO", repeat=length)
    ][:1000]
    lines = ["# SYNTHETIC-FIXTURE M22 GA 2,000-candidate pool: generated linear mono-bromides BrC<CNO chain>"]
    lines += [f"BrC{chain} ga_block_{index:04d}" for index, chain in enumerate(strings)]
    return ("\n".join(lines) + "\n").encode()


def pool_rules() -> bytes:
    doc = {"_fixture": "SYNTHETIC-FIXTURE ProtView M22 T1 user reaction SMARTS for the 2,000-candidate pool; request "
                       "order gives rule_id user_<n>. See SYNTHETIC-PROVENANCE.md.",
           "rules": RULES}
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode()


FILES = {"synthetic-ga-small-blocks.smi": small_blocks, "synthetic-ga-pool2000-blocks.smi": pool_blocks,
         "synthetic-ga-pool2000-rules.json": pool_rules}


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    if argv and not check:
        return 2
    bad = []
    for name, build in FILES.items():
        raw = build()
        path = HERE / name
        if check:
            if not path.is_file() or path.read_bytes() != raw:
                bad.append(name)
        else:
            path.write_bytes(raw)
    for name in bad:
        print(f"differs: {name}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
