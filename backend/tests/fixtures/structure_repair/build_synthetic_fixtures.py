"""Rebuild the M29 T4 SYNTHETIC structure-repair fixtures in this folder from the public 1UBQ fixture (gemmi 0.7.5).

Run: ``.venv/bin/python backend/tests/fixtures/structure_repair/build_synthetic_fixtures.py [--check]``. ``--check``
rebuilds in memory and exits non-zero unless every file on disk (the structures and
``synthetic-fixtures.provenance.json``) is byte-identical to a fresh build.

Every structure here is a SYNTHETIC edit of the public 1UBQ fixture (``../public_1ubq.cif``, unmodified RCSB file),
made only to reach one structure-repair rule that no real local file reaches. It is labelled SYNTHETIC in its file
name, in the mmCIF data block name / PDB REMARK 999 line, and in the provenance file. None of them is an experimental
structure; the edits (renames, deletions, a 60 A copy, a 6 A shift, added listing lines) are recorded per file in
``synthetic-fixtures.provenance.json``. No coordinate is invented: atoms are deleted, renamed, relabelled, copied or
rigidly shifted. Waters are removed from every file (1UBQ's chain A protein only).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import gemmi

HERE = Path(__file__).resolve().parent
UBQ = HERE.parent / "public_1ubq.cif"
NOTE = "SYNTHETIC TEST FIXTURE (M29 T4) derived from public 1UBQ; not an experimental structure"
GAP = (30, 31, 32)           # I30, Q31, D32 removed in the gap fixtures
SHIFT_FROM = 40              # residues 40-76 shifted +6 A along x in the chain-break fixture
PROVENANCE = "synthetic-fixtures.provenance.json"


def _ubq(name: str) -> gemmi.Structure:
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(UBQ.read_text()).sole_block())
    st.remove_hydrogens()
    st.remove_waters()
    # The entry metadata (id, title, method, dates, resolution, refinement, assemblies) is the real 1UBQ's; replace it
    # with the synthetic label so no file reads as the experimental entry.
    st.name = name
    st.info = gemmi.InfoMap()
    st.info["_entry.id"] = name
    st.info["_struct.title"] = NOTE
    st.resolution = 0
    for field in ("authors", "crystals", "experiments", "refinement", "software"):
        setattr(st.meta, field, [])
    st.assemblies.clear()
    return st


def _residue(st: gemmi.Structure, number: int):
    return next(res for res in st[0]["A"] if res.seqid.num == number)


def _cif(st: gemmi.Structure) -> bytes:
    text = st.make_mmcif_document().as_string()
    head, rest = text.split("\n", 1)
    return f"{head}\n# {NOTE}\n{rest}".encode()


def _pdb(st: gemmi.Structure, remark465: list[tuple[int, str]] | None = None) -> bytes:
    lines = st.make_pdb_string().splitlines()
    extra = [f"REMARK 999 {NOTE}"]
    if remark465:
        extra += ["REMARK 465", "REMARK 465 MISSING RESIDUES", "REMARK 465   M RES C SSSEQI"]
        extra += [f"REMARK 465     {name:>3} A {number:>5} " for number, name in remark465]
    at = next(i for i, line in enumerate(lines) if line.startswith(("SEQRES", "CRYST1", "ATOM")))
    return ("\n".join(lines[:at] + extra + lines[at:]) + "\n").encode()


def chain_identity_duplicate() -> bytes:
    """A second copy of the chain A protein, shifted +60 A along x and numbered 1001-1076, as label chain B under
    author chain A (distinct author numbers, else a reader merges the two copies' atoms into one residue)."""
    st = _ubq("SYNTHETIC_M29_CHAIN_IDENTITY_DUPLICATE")
    copy = gemmi.Chain("A")
    for res in st[0]["A"]:
        copy.add_residue(res)
    for res in copy:
        res.subchain = "B"
        res.seqid = gemmi.SeqId(res.seqid.num + 1000, " ")
        for atom in res:
            atom.pos = gemmi.Position(atom.pos.x + 60.0, atom.pos.y, atom.pos.z)
    st[0].add_chain(copy)
    st.entities[0].subchains = [*st.entities[0].subchains, "B"]
    return _cif(st)


def unsupported_residue() -> bytes:
    """Residue A/20 SER renamed SEP (atoms unchanged): a polymer residue that is neither standard nor MSE."""
    st = _ubq("SYNTHETIC_M29_UNSUPPORTED_RESIDUE")
    _residue(st, 20).name = "SEP"
    return _cif(st)


def unexpected_atoms() -> bytes:
    """A/12 THR atom CG2 renamed XG2 (a name outside the template) and A/14 THR atom OG1 relabelled element Cl."""
    st = _ubq("SYNTHETIC_M29_UNEXPECTED_ATOMS")
    next(atom for atom in _residue(st, 12) if atom.name == "CG2").name = "XG2"
    next(atom for atom in _residue(st, 14) if atom.name == "OG1").element = gemmi.Element("Cl")
    return _cif(st)


def backbone_atoms_missing() -> bytes:
    """Atom O of A/30 ILE deleted."""
    st = _ubq("SYNTHETIC_M29_BACKBONE_ATOMS_MISSING")
    res = _residue(st, 30)
    del res[next(i for i, atom in enumerate(res) if atom.name == "O")]
    return _cif(st)


def _without_gap(name: str) -> gemmi.Structure:
    st = _ubq(name)
    chain = st[0]["A"]
    for index in sorted((i for i, res in enumerate(chain) if res.seqid.num in GAP), reverse=True):
        del chain[index]
    return st


def gap_listing_missing() -> bytes:
    """Residues A/30-32 deleted; the file keeps _entity_poly_seq but has no unobserved-residue listing."""
    return _cif(_without_gap("SYNTHETIC_M29_GAP_LISTING_MISSING"))


def gap_pdb() -> bytes:
    """PDB format (gemmi writer, SEQRES kept), residues A/30-32 deleted and listed in REMARK 465."""
    names = {res.seqid.num: res.name for res in _ubq("x")[0]["A"]}
    return _pdb(_without_gap("SYNTHETIC_M29_GAP_PDB"), [(number, names[number]) for number in GAP])


def chain_break_pdb() -> bytes:
    """PDB format, residues A/40-76 rigidly shifted +6 A along x: consecutive author numbers, broken C-N distance."""
    st = _ubq("SYNTHETIC_M29_CHAIN_BREAK_PDB")
    for res in st[0]["A"]:
        if res.seqid.num >= SHIFT_FROM:
            for atom in res:
                atom.pos = gemmi.Position(atom.pos.x + 6.0, atom.pos.y, atom.pos.z)
    return _pdb(st)


def calc_flag() -> bytes:
    """``_atom_site.calc_flag`` already set on input atoms (A/1 MET ``d``, A/2 GLN ``c``) and atoms CE, NZ of A/6 LYS
    deleted (a side-chain repair is needed)."""
    st = _ubq("SYNTHETIC_M29_CALC_FLAG")
    for atom in _residue(st, 1):
        atom.calc_flag = gemmi.CalcFlag.Determined
    for atom in _residue(st, 2):
        atom.calc_flag = gemmi.CalcFlag.Calculated
    res = _residue(st, 6)
    for index in sorted((i for i, atom in enumerate(res) if atom.name in ("CE", "NZ")), reverse=True):
        del res[index]
    return _cif(st)


BUILDERS = {
    "synthetic-chain-identity-duplicate.cif": chain_identity_duplicate,
    "synthetic-unsupported-residue.cif": unsupported_residue,
    "synthetic-unexpected-atoms.cif": unexpected_atoms,
    "synthetic-backbone-atoms-missing.cif": backbone_atoms_missing,
    "synthetic-gap-listing-missing.cif": gap_listing_missing,
    "synthetic-gap.pdb": gap_pdb,
    "synthetic-chain-break.pdb": chain_break_pdb,
    "synthetic-calc-flag.cif": calc_flag,
}
REACHES = {
    "synthetic-chain-identity-duplicate.cif": "refusal chain_identity_duplicate",
    "synthetic-unsupported-residue.cif": "refusal unsupported_residue",
    "synthetic-unexpected-atoms.cif": "refusal unexpected_atoms (a name outside the template; an unsupported element)",
    "synthetic-backbone-atoms-missing.cif": "refusal backbone_atoms_missing",
    "synthetic-gap-listing-missing.cif": "refusal gap_listing_missing (mmCIF without _pdbx_unobs_or_zero_occ_residues)",
    "synthetic-gap.pdb": "PDB-format internal gap from REMARK 465 + SEQRES + C-N distance (in scope)",
    "synthetic-chain-break.pdb": "refusal m7_condition_unsupported (m7_reason peptide_geometry) in PDB format",
    "synthetic-calc-flag.cif": "input calc_flag values normalised to '.' and counted (unchanged.input_calc_flag_cleared)",
}


def build() -> dict[str, bytes]:
    files = {name: make() for name, make in BUILDERS.items()}
    provenance = {
        "label": "SYNTHETIC test fixtures (M29 T4 structure repair); not experimental structures",
        "made_by": "backend/tests/fixtures/structure_repair/build_synthetic_fixtures.py (gemmi " + gemmi.__version__ + ")",
        "base": {"file": "backend/tests/fixtures/public_1ubq.cif",
                 "sha256": hashlib.sha256(UBQ.read_bytes()).hexdigest(),
                 "note": "public RCSB 1UBQ fixture, unmodified; hydrogens and waters removed before every edit"},
        "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                         "rule": BUILDERS[name].__doc__.strip().replace("\n", " "), "reaches": REACHES[name]}
                  for name, raw in files.items()},
    }
    files[PROVENANCE] = (json.dumps(provenance, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode()
    return files


def main(argv: list[str]) -> int:
    files = build()
    if argv == ["--check"]:
        stale = [name for name, raw in files.items() if not (HERE / name).is_file() or (HERE / name).read_bytes() != raw]
        print("stale: " + ", ".join(stale) if stale else "all synthetic fixtures are current")
        return 1 if stale else 0
    for name, raw in files.items():
        (HERE / name).write_bytes(raw)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
