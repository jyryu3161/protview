"""M15 global sequence aligner: structure sequence vs UniProt sequence (pure module; numpy only, no I/O).

Method: Needleman–Wunsch global alignment with affine gaps (Gotoh, three matrices), BLOSUM62 (NCBI values,
including B, Z, X and ``*``), gap open 10 and gap extend 0.5 with EMBOSS ``needle`` semantics: a gap of length
k costs ``10 + 0.5 * (k - 1)``. End gaps are penalized exactly like internal gaps (unlike the EMBOSS default).
A gap in one sequence may directly follow a gap in the other (X <-> Y transitions pay a fresh gap open).
All scores are multiples of 0.5, so float64 arithmetic is exact and results are bit-reproducible.

Matrices (row i = structure prefix, column j = UniProt prefix):
  M  structure[i] aligned to uniprot[j]       ("diagonal")
  X  structure[i] opposite a gap              ("gap in UniProt")
  Y  uniprot[j] opposite a gap                ("gap in structure")

Tie-break (``TIE_BREAK``): whenever candidates have equal scores, M is preferred over X, and X over Y. The rule
is applied both to the choice of the final state at (n, m) and to every predecessor choice during traceback
(which runs from the end of both sequences back to the start). Consequence: among equal-scoring alignments,
matches are placed as late as possible and gaps as early as possible (e.g. ``A`` vs ``AA`` gives ``-A``).

Input: uppercase one-letter strings over the BLOSUM62 alphabet ``ARNDCQEGHILKMFPSTWYVBZX*``. The caller maps
non-standard structure residues to ``X`` (see ``to_one_letter``). Any other character (lowercase, ``-``, ``U``,
``O``, whitespace) raises ``ValueError``.

Output positions: ``structure_to_uniprot[i]`` is the **1-based** UniProt position aligned to structure index
``i`` (0-based index into the structure string), or ``None`` when structure residue ``i`` is opposite a gap.

Statistics: ``aligned_pairs`` = columns with both residues present; ``identical`` = aligned columns with the same
letter, where ``X`` never counts as identical (unknown residue); ``identity_pct = identical / aligned_pairs *
100`` (``None`` when ``aligned_pairs == 0``); ``coverage_pct = aligned_pairs / len(structure) * 100`` (``None``
when the structure sequence is empty). Both sequences empty gives score 0.0 and an empty alignment.

Memory: DP scores are kept for two rows only; traceback uses one uint8 per cell (2 bits per matrix, three
matrices), so ``MAX_ALIGNMENT_CELLS`` = 20M cells needs about 20 MB.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

IMPLEMENTATION_VERSION = "mw.sequence_alignment/gotoh-global-v1"
TIE_BREAK = "M>X>Y (diagonal > gap_in_uniprot > gap_in_structure), traceback from end"
GAP_OPEN = 10
GAP_EXTEND = 0.5
MAX_ALIGNMENT_CELLS = 20_000_000

_ALPHABET = "ARNDCQEGHILKMFPSTWYVBZX*"
# NCBI BLOSUM62, rows/columns in _ALPHABET order.
_BLOSUM62_ROWS = (
    (4, -1, -2, -2, 0, -1, -1, 0, -2, -1, -1, -1, -1, -2, -1, 1, 0, -3, -2, 0, -2, -1, 0, -4),
    (-1, 5, 0, -2, -3, 1, 0, -2, 0, -3, -2, 2, -1, -3, -2, -1, -1, -3, -2, -3, -1, 0, -1, -4),
    (-2, 0, 6, 1, -3, 0, 0, 0, 1, -3, -3, 0, -2, -3, -2, 1, 0, -4, -2, -3, 3, 0, -1, -4),
    (-2, -2, 1, 6, -3, 0, 2, -1, -1, -3, -4, -1, -3, -3, -1, 0, -1, -4, -3, -3, 4, 1, -1, -4),
    (0, -3, -3, -3, 9, -3, -4, -3, -3, -1, -1, -3, -1, -2, -3, -1, -1, -2, -2, -1, -3, -3, -2, -4),
    (-1, 1, 0, 0, -3, 5, 2, -2, 0, -3, -2, 1, 0, -3, -1, 0, -1, -2, -1, -2, 0, 3, -1, -4),
    (-1, 0, 0, 2, -4, 2, 5, -2, 0, -3, -3, 1, -2, -3, -1, 0, -1, -3, -2, -2, 1, 4, -1, -4),
    (0, -2, 0, -1, -3, -2, -2, 6, -2, -4, -4, -2, -3, -3, -2, 0, -2, -2, -3, -3, -1, -2, -1, -4),
    (-2, 0, 1, -1, -3, 0, 0, -2, 8, -3, -3, -1, -2, -1, -2, -1, -2, -2, 2, -3, 0, 0, -1, -4),
    (-1, -3, -3, -3, -1, -3, -3, -4, -3, 4, 2, -3, 1, 0, -3, -2, -1, -3, -1, 3, -3, -3, -1, -4),
    (-1, -2, -3, -4, -1, -2, -3, -4, -3, 2, 4, -2, 2, 0, -3, -2, -1, -2, -1, 1, -4, -3, -1, -4),
    (-1, 2, 0, -1, -3, 1, 1, -2, -1, -3, -2, 5, -1, -3, -1, 0, -1, -3, -2, -2, 0, 1, -1, -4),
    (-1, -1, -2, -3, -1, 0, -2, -3, -2, 1, 2, -1, 5, 0, -2, -1, -1, -1, -1, 1, -3, -1, -1, -4),
    (-2, -3, -3, -3, -2, -3, -3, -3, -1, 0, 0, -3, 0, 6, -4, -2, -2, 1, 3, -1, -3, -3, -1, -4),
    (-1, -2, -2, -1, -3, -1, -1, -2, -2, -3, -3, -1, -2, -4, 7, -1, -1, -4, -3, -2, -2, -1, -2, -4),
    (1, -1, 1, 0, -1, 0, 0, 0, -1, -2, -2, 0, -1, -2, -1, 4, 1, -3, -2, -2, 0, 0, 0, -4),
    (0, -1, 0, -1, -1, -1, -1, -2, -2, -1, -1, -1, -1, -2, -1, 1, 5, -2, -2, 0, -1, -1, 0, -4),
    (-3, -3, -4, -4, -2, -2, -3, -2, -2, -3, -2, -3, -1, 1, -4, -3, -2, 11, 2, -3, -4, -3, -2, -4),
    (-2, -2, -2, -3, -2, -1, -2, -3, 2, -1, -1, -2, -1, 3, -3, -2, -2, 2, 7, -1, -3, -2, -1, -4),
    (0, -3, -3, -3, -1, -2, -2, -3, -3, 3, 1, -2, 1, -1, -2, -2, 0, -3, -1, 4, -3, -2, -1, -4),
    (-2, -1, 3, 4, -3, 0, 1, -1, 0, -3, -4, 0, -3, -3, -2, 0, -1, -4, -3, -3, 4, 1, -1, -4),
    (-1, 0, 0, 1, -3, 3, 4, -2, 0, -3, -3, 1, -1, -3, -1, 0, -1, -3, -2, -2, 1, 4, -1, -4),
    (0, -1, -1, -1, -2, -1, -1, -1, -1, -1, -1, -1, -1, -1, -2, 0, 0, -2, -1, -1, -1, -1, -1, -4),
    (-4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, 1),
)
BLOSUM62: dict[str, dict[str, int]] = {
    a: {b: _BLOSUM62_ROWS[i][j] for j, b in enumerate(_ALPHABET)} for i, a in enumerate(_ALPHABET)
}
_MATRIX = np.array(_BLOSUM62_ROWS, dtype=np.float64)
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E", "GLY": "G",
    "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P", "SER": "S",
    "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

_M, _X, _Y = 0, 1, 2
_NEG = -np.inf


def to_one_letter(resname3: str) -> str:
    """Standard 20 uppercase three-letter codes -> one letter; anything else (MSE, HIE, UNK, lowercase) -> 'X'."""
    return THREE_TO_ONE.get(resname3, "X")


def alignment_too_large(n_struct: int, n_uniprot: int, max_cells: int = MAX_ALIGNMENT_CELLS) -> bool:
    """True when the DP grid ``n_struct * n_uniprot`` exceeds ``max_cells`` (exactly at the cap is allowed)."""
    return n_struct * n_uniprot > max_cells


@dataclass(frozen=True)
class SequenceAlignment:
    score: float
    structure_to_uniprot: tuple[int | None, ...]  # 1-based UniProt position per structure index, None = gap
    aligned_structure: str
    aligned_uniprot: str
    aligned_pairs: int
    identical: int
    identity_pct: float | None
    coverage_pct: float | None
    params: dict[str, Any]


def _encode(seq: str, name: str) -> np.ndarray:
    bad = sorted({c for c in seq if c not in _INDEX})
    if bad:
        raise ValueError(f"{name} contains characters outside the BLOSUM62 alphabet: {''.join(bad)!r}")
    return np.fromiter((_INDEX[c] for c in seq), dtype=np.intp, count=len(seq))


def _pick(m: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Element-wise max of three candidates and the chosen state with priority M > X > Y on ties."""
    best = np.maximum(np.maximum(m, x), y)
    state = np.where(m == best, _M, np.where(x == best, _X, _Y)).astype(np.uint8)
    return best, state


def align_global(structure_seq: str, uniprot_seq: str) -> SequenceAlignment:
    a = _encode(structure_seq, "structure_seq")
    b = _encode(uniprot_seq, "uniprot_seq")
    n, m = len(a), len(b)
    go, ge = float(GAP_OPEN), float(GAP_EXTEND)
    ramp = ge * np.arange(m, dtype=np.float64)  # ge * k for k = 0..m-1

    # ptr[i, j]: bits 0-1 predecessor state of M, bits 2-3 of X, bits 4-5 of Y.
    ptr = np.zeros((n + 1, m + 1), dtype=np.uint8)

    def gap_row(mc: np.ndarray, xc: np.ndarray, row: int) -> np.ndarray:
        # Y[j] = max_{k<j}(max(M[k], X[k]) - go - ge*(j-1-k)); prefix max of (H[k] + ge*k).
        yc = np.full(m + 1, _NEG)
        if m:
            h = np.maximum(mc[:-1], xc[:-1])
            yc[1:] = np.maximum.accumulate(h + ramp) - go - ramp
            _, ystate = _pick(mc[:-1] - go, xc[:-1] - go, yc[:-1] - ge)
            ptr[row, 1:] |= ystate << 4
        return yc

    mp = np.full(m + 1, _NEG)
    mp[0] = 0.0
    xp = np.full(m + 1, _NEG)
    yp = gap_row(mp, xp, 0)

    for i in range(1, n + 1):
        mc = np.full(m + 1, _NEG)
        if m:
            diag, dstate = _pick(mp[:-1], xp[:-1], yp[:-1])
            mc[1:] = diag + _MATRIX[a[i - 1], b]
            ptr[i, 1:] = dstate
        xc, xstate = _pick(mp - go, xp - ge, yp - go)
        ptr[i] |= xstate << 2
        yc = gap_row(mc, xc, i)
        mp, xp, yp = mc, xc, yc

    score, end_state = _pick(mp[m:], xp[m:], yp[m:])
    state = int(end_state[0])

    cols_s: list[str] = []
    cols_u: list[str] = []
    mapping: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        p = int(ptr[i, j])
        if state == _M:
            mapping[i - 1] = j
            cols_s.append(structure_seq[i - 1])
            cols_u.append(uniprot_seq[j - 1])
            state = p & 3
            i, j = i - 1, j - 1
        elif state == _X:
            cols_s.append(structure_seq[i - 1])
            cols_u.append("-")
            state = (p >> 2) & 3
            i -= 1
        else:
            cols_s.append("-")
            cols_u.append(uniprot_seq[j - 1])
            state = (p >> 4) & 3
            j -= 1

    pairs = sum(1 for p in mapping if p is not None)
    identical = sum(1 for k, p in enumerate(mapping)
                    if p is not None and structure_seq[k] == uniprot_seq[p - 1] and structure_seq[k] != "X")
    return SequenceAlignment(
        score=float(score[0]),
        structure_to_uniprot=tuple(mapping),
        aligned_structure="".join(reversed(cols_s)),
        aligned_uniprot="".join(reversed(cols_u)),
        aligned_pairs=pairs,
        identical=identical,
        identity_pct=identical / pairs * 100 if pairs else None,
        coverage_pct=pairs / n * 100 if n else None,
        params={
            "matrix": "BLOSUM62", "gap_open": GAP_OPEN, "gap_extend": GAP_EXTEND, "end_gaps": "penalized",
            "tie_break": TIE_BREAK, "implementation": IMPLEMENTATION_VERSION,
        },
    )
