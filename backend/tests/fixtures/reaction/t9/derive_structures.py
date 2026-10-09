"""Writer (M26 T9b) of the two LABELLED SYNTHETIC derived structures of the M26 offscreen acceptance (conflict case).

Each derived file is its public source file with exactly two edits, nothing else (see SYNTHETIC-PROVENANCE-t9.md):

1. the first line ``data_<ID>`` becomes ``data_<ID>_DERIVED_<CHAIN><NUM>_<FROM>_TO_<TO>`` (a label only; ``_entry.id`` is
   kept, so the product's PDB ID suggestion still names the source entry and the person confirms or edits it);
2. in every ``_atom_site`` row whose ``auth_asym_id`` and ``auth_seq_id`` are the chosen residue, the two residue name
   fields ``label_comp_id`` and ``auth_comp_id`` change from ``FROM`` to ``TO`` (same width, so the column layout and
   every other byte of the row stay as they were). Atom names, coordinates and all other categories (``_entity_poly_seq``,
   ``_pdbx_poly_seq_scheme``, ``_struct_site_gen`` …) are left untouched on purpose.

Standard library only (no gemmi, no ``mw``). ``--check`` exits 0 only if both committed files equal a fresh derivation;
``--write`` writes them. Not product code; the files are test inputs, never experimental structures.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[1]
# (derived file, source file, auth chain, auth number, from, to)
DERIVATIONS = (
    ("derived_1hsg_A25_asp_to_glu.cif", "public_1hsg.cif", "A", "25", "ASP", "GLU"),
    ("derived_1s9i_A194_asp_to_glu.cif", "public_1s9i.cif", "A", "194", "ASP", "GLU"),
)
_SPLIT = re.compile(r"(\s+)")


def derive(source: bytes, chain: str, number: str, old: str, new: str) -> tuple[bytes, int]:
    """The derived bytes and the number of ``_atom_site`` rows changed (refuses anything it cannot do exactly)."""
    if len(old) != len(new):
        raise ValueError("the residue names must have the same width")
    lines = source.decode("utf-8").split("\n")
    first = lines[0]
    if not first.startswith("data_") or " " in first:
        raise ValueError("the source does not start with a single data_ line")
    lines[0] = f"{first}_DERIVED_{chain}{number}_{old}_TO_{new}"
    columns: list[str] = []
    changed = 0
    index = 1
    while index < len(lines):
        if lines[index].strip() == "loop_" and index + 1 < len(lines) and lines[index + 1].startswith("_atom_site."):
            index += 1
            while lines[index].startswith("_atom_site."):
                columns.append(lines[index].strip())
                index += 1
            break
        index += 1
    if not columns:
        raise ValueError("no _atom_site loop")
    position = {name: at for at, name in enumerate(columns)}
    want = ("_atom_site.label_comp_id", "_atom_site.auth_comp_id", "_atom_site.auth_asym_id", "_atom_site.auth_seq_id")
    if any(name not in position for name in want):
        raise ValueError("the _atom_site loop lacks a needed column")
    while index < len(lines) and lines[index].startswith(("ATOM", "HETATM")):
        parts = _SPLIT.split(lines[index])
        tokens = parts[0::2]
        if tokens and tokens[-1] == "":
            tokens = tokens[:-1]
        if len(tokens) != len(columns):
            raise ValueError(f"line {index + 1}: {len(tokens)} values for {len(columns)} columns")
        if (tokens[position["_atom_site.auth_asym_id"]] == chain
                and tokens[position["_atom_site.auth_seq_id"]] == number):
            for name in ("_atom_site.label_comp_id", "_atom_site.auth_comp_id"):
                at = position[name]
                if tokens[at] != old:
                    raise ValueError(f"line {index + 1}: {name} is {tokens[at]}, not {old}")
                parts[2 * at] = new
            lines[index] = "".join(parts)
            changed += 1
        index += 1
    if not changed:
        raise ValueError(f"no _atom_site row for {chain} {number}")
    return "\n".join(lines).encode("utf-8"), changed


def build() -> dict[str, tuple[bytes, int]]:
    out = {}
    for name, source, chain, number, old, new in DERIVATIONS:
        out[name] = derive((FIXTURES / source).read_bytes(), chain, number, old, new)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    same = True
    for name, (data, changed) in build().items():
        target = HERE / name
        digest = hashlib.sha256(data).hexdigest()
        if check:
            ok = target.is_file() and target.read_bytes() == data
            same = same and ok
            print(f"{name}: {'same' if ok else 'DIFFERS'} sha256 {digest} rows changed {changed}")
        else:
            target.write_bytes(data)
            print(f"{name}: written sha256 {digest} bytes {len(data)} rows changed {changed}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
