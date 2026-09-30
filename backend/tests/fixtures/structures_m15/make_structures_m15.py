"""Deterministic generator of the M15 derived structure FIXTURES from the public entry 1MQ4 (chain A, Aurora A).

Every output is a DERIVED TEST FIXTURE (not an observed structure and not experimental evidence): fragments of the
unmodified ``backend/tests/fixtures/public_1mq4.cif`` with the edits listed in ``PROVENANCE_fixture.json``.
Coordinates, occupancies and B factors are copied from the source rows (PDB files re-format them to the fixed PDB
columns); only the edits named per file are made. ``build_all()`` returns ``{file name: bytes}``; the provenance test
regenerates the bytes and compares them with the committed files.

Run ``python make_structures_m15.py --write`` to (re)write the files next to this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "public_1mq4.cif"

STANDARD = frozenset({"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET",
                      "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"})
MSE_AUTH_SEQ = 300  # MET 300 of 1MQ4 chain A becomes MSE (HETATM, SD -> SE) in the MSE fixtures
ICODE_AUTH_SEQ = 241  # residue 241 of 1MQ4 chain A is renumbered 240A in the insertion-code fixture


def _loop(lines: list[str], prefix: str) -> tuple[list[str], list[str], int]:
    """(column names, row lines, index of the first header line) of the mmCIF loop whose tags start with prefix."""
    start = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    assert lines[start - 1].strip() == "loop_", prefix
    end = start
    while lines[end].startswith(prefix):
        end += 1
    columns = [line.strip()[len(prefix):] for line in lines[start:end]]
    rows = []
    while not lines[end].startswith("#"):
        rows.append(lines[end])
        end += 1
    return columns, rows, start


def _source() -> tuple[list[str], list[str], list[str], list[str]]:
    lines = SOURCE.read_text().split("\n")
    atom_cols, atom_rows, atom_start = _loop(lines, "_atom_site.")
    _seq_cols, seq_rows, _seq_start = _loop(lines, "_entity_poly_seq.")
    return atom_cols, atom_rows, lines[atom_start:atom_start + len(atom_cols)], seq_rows


def _records(atom_cols: list[str], atom_rows: list[str]) -> list[dict[str, str]]:
    """Chain A standard-residue ATOM rows of model 1 as dicts (plus the verbatim ``_line``)."""
    out = []
    for line in atom_rows:
        tokens = line.split()
        assert len(tokens) == len(atom_cols), line
        row = dict(zip(atom_cols, tokens, strict=True))
        if (row["group_PDB"] == "ATOM" and row["auth_asym_id"] == "A" and row["pdbx_PDB_model_num"] == "1"
                and row["auth_comp_id"] in STANDARD):
            assert row["label_alt_id"] == "." and row["pdbx_PDB_ins_code"] == "?", line
            row["_line"] = line
            out.append(row)
    return out


def _fragment(records: list[dict[str, str]], first: int, last: int) -> list[dict[str, str]]:
    rows = [dict(r) for r in records if first <= int(r["auth_seq_id"]) <= last]
    numbers = sorted({int(r["auth_seq_id"]) for r in rows})
    assert numbers == list(range(first, last + 1)), (first, last)  # contiguous, no missing residue
    return rows


def _to_mse(row: dict[str, str]) -> dict[str, str]:
    row = dict(row)
    row.pop("_line", None)
    row["group_PDB"] = "HETATM"
    row["label_comp_id"] = row["auth_comp_id"] = "MSE"
    if row["auth_atom_id"] == "SD":
        row["label_atom_id"] = row["auth_atom_id"] = "SE"
        row["type_symbol"] = "SE"
    return row


# --- PDB format ------------------------------------------------------------------------------------------------

def _atom_name(name: str, element: str) -> str:
    return f" {name:<3}" if len(element) == 1 and len(name) < 4 else f"{name:<4}"


def _pdb_atom(serial: int, row: dict[str, str], chain: str, number: int, icode: str) -> str:
    return (f"{row['group_PDB']:<6}{serial:>5} {_atom_name(row['auth_atom_id'], row['type_symbol'])} "
            f"{row['auth_comp_id']:>3} {chain}{number:>4}{icode:1}   "
            f"{float(row['Cartn_x']):8.3f}{float(row['Cartn_y']):8.3f}{float(row['Cartn_z']):8.3f}"
            f"{float(row['occupancy']):6.2f}{float(row['B_iso_or_equiv']):6.2f}          {row['type_symbol']:>2}")


def _pdb_chain(rows: list[dict[str, str]], chain: str, serial: int, icodes: dict[int, tuple[int, str]] | None = None
               ) -> tuple[list[str], int]:
    out = []
    last = None
    for row in rows:
        number, icode = (icodes or {}).get(int(row["auth_seq_id"]), (int(row["auth_seq_id"]), ""))
        out.append(_pdb_atom(serial, row, chain, number, icode))
        serial += 1
        last = (row["auth_comp_id"], number, icode)
    out.append(f"TER   {serial:>5}      {last[0]:>3} {chain}{last[1]:>4}{last[2]:1}")
    return out, serial + 1


def _remarks(text: str) -> list[str]:
    return [f"REMARK 999 {part}" for part in text.split("\n")]


def _pdb(remark: str, body: list[str], header: list[str] | None = None) -> bytes:
    return ("\n".join(_remarks(remark) + (header or []) + body + ["END"]) + "\n").encode()


def _seqres(names: list[str], chain: str) -> list[str]:
    out = []
    for i in range(0, len(names), 13):
        out.append(f"SEQRES {i // 13 + 1:>3} {chain} {len(names):>4}  " + " ".join(f"{n:>3}" for n in names[i:i + 13]))
    return out


# --- builders --------------------------------------------------------------------------------------------------

def build_all() -> dict[str, bytes]:
    atom_cols, atom_rows, atom_header, seq_rows = _source()
    records = _records(atom_cols, atom_rows)
    head = "DERIVED TEST FIXTURE from public PDB entry 1MQ4 chain A (RCSB mmCIF, CC0); not an observed structure."
    out: dict[str, bytes] = {}

    # (a) PDB format, no SEQRES (no label_seq_id available), residues 200-285 of chain A.
    a = _fragment(records, 200, 285)
    body, _ = _pdb_chain(a, "A", 1)
    out["derived_1mq4_a200_285_fixture.pdb"] = _pdb(head + "\nATOM rows of chain A residues 200-285, no SEQRES.", body)

    # (b) MET 300 -> MSE (HETATM, SD -> SE), residues 288-360; mmCIF with the full entity sequence and PDB with
    # SEQRES + MODRES.
    b = [(_to_mse(r) if int(r["auth_seq_id"]) == MSE_AUTH_SEQ else r) for r in _fragment(records, 288, 360)]
    mse_label = {r["label_seq_id"] for r in b if r["auth_comp_id"] == "MSE"}
    assert len(mse_label) == 1
    mse_num = mse_label.pop()
    seq = []
    for line in seq_rows:
        entity, num, mon, hetero = line.split()
        if entity != "1":
            continue
        if num == mse_num:
            assert mon == "MET"
            line = f"1 {num} MSE {hetero}"
        seq.append(line)
    cif_rows = [r["_line"] if "_line" in r else " ".join(r[c] for c in atom_cols) for r in b]
    name = "1MQ4_DERIVED_A288_360_MSE_FIXTURE"
    cif = [f"data_{name}", "#", f"_entry.id {name}", "#",
           "loop_", "_entity.id", "_entity.type", "_entity.pdbx_description",
           "1 polymer 'Aurora kinase A, derived test fixture'", "#",
           "_entity_poly.entity_id 1", "_entity_poly.type 'polypeptide(L)'", "_entity_poly.pdbx_strand_id A", "#",
           "loop_", "_entity_poly_seq.entity_id", "_entity_poly_seq.num", "_entity_poly_seq.mon_id",
           "_entity_poly_seq.hetero", *seq, "#",
           "loop_", "_struct_asym.id", "_struct_asym.entity_id", "A 1", "#",
           "loop_", *atom_header, *cif_rows, "#"]
    out["derived_1mq4_a288_360_mse_fixture.cif"] = ("\n".join(cif) + "\n").encode()
    names = [line.split()[2] for line in seq]
    body, _ = _pdb_chain(b, "A", 1)
    modres = [f"MODRES {'1MQ4':4} MSE A {MSE_AUTH_SEQ:>4}  MET  SELENOMETHIONINE"]
    out["derived_1mq4_a288_360_mse_fixture.pdb"] = _pdb(
        head + "\nChain A residues 288-360, MET 300 renamed MSE (HETATM, SD->SE); SEQRES = full entity 1 sequence.",
        body, _seqres(names, "A") + modres)

    # (c) insertion code: residues 200-285, residue 241 renumbered 240A (PDB format, no SEQRES).
    body, _ = _pdb_chain(a, "A", 1, {ICODE_AUTH_SEQ: (ICODE_AUTH_SEQ - 1, "A")})
    out["derived_1mq4_a200_285_icode_fixture.pdb"] = _pdb(
        head + "\nChain A residues 200-285; residue 241 renumbered 240A (insertion code). No SEQRES.", body)

    # (d1) two chains: A = residues 200-285, B = residues 126-199 of the same source chain (relabeled B).
    body_a, serial = _pdb_chain(a, "A", 1)
    body_b, _ = _pdb_chain(_fragment(records, 126, 199), "B", serial)
    out["derived_1mq4_two_chain_fixture.pdb"] = _pdb(
        head + "\nChain A = source residues 200-285; chain B = source chain A residues 126-199 relabeled B.",
        body_a + body_b)

    # (d2) two models: model 1 = residues 126-199, model 2 = residues 200-285 (both chain A).
    body_1, _ = _pdb_chain(_fragment(records, 126, 199), "A", 1)
    body_2, _ = _pdb_chain(a, "A", 1)
    out["derived_1mq4_two_model_fixture.pdb"] = _pdb(
        head + "\nMODEL 1 = chain A residues 126-199; MODEL 2 = chain A residues 200-285.",
        [f"MODEL     {1:>4}", *body_1, "ENDMDL", f"MODEL     {2:>4}", *body_2, "ENDMDL"])
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        for file_name, data in build_all().items():
            (HERE / file_name).write_bytes(data)
            print(file_name, len(data))
    else:
        print("usage: make_structures_m15.py --write", file=sys.stderr)
        sys.exit(2)
