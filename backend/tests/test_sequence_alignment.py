"""M15 T2: global sequence aligner (Gotoh, BLOSUM62, EMBOSS needle gap semantics, penalized end gaps).

Hand-solved examples state the expected score in comments. The independent oracle at the bottom is a plain
pure-Python three-matrix Gotoh written separately from the vectorized module (different recurrences layout,
no numpy, own copy of the matrix lookups via the module's public BLOSUM62 table only).
"""
from __future__ import annotations

import random
import time

import pytest

from mw import sequence_alignment as sa
from mw.sequence_alignment import (
    BLOSUM62,
    MAX_ALIGNMENT_CELLS,
    align_global,
    alignment_too_large,
    to_one_letter,
)

B = BLOSUM62


# --------------------------------------------------------------------------------------------- matrix

def test_blosum62_spot_values_and_symmetry():
    # Standard NCBI BLOSUM62 values.
    assert B["A"]["A"] == 4 and B["W"]["W"] == 11 and B["C"]["C"] == 9 and B["H"]["H"] == 8
    assert B["A"]["R"] == -1 and B["W"]["F"] == 1 and B["Y"]["F"] == 3 and B["I"]["V"] == 3
    assert B["X"]["X"] == -1 and B["X"]["A"] == 0 and B["X"]["P"] == -2 and B["X"]["C"] == -2
    assert B["B"]["D"] == 4 and B["Z"]["E"] == 4 and B["*"]["*"] == 1 and B["*"]["A"] == -4
    letters = "ARNDCQEGHILKMFPSTWYVBZX*"
    assert set(B) == set(letters)
    for a in letters:
        for b in letters:
            assert B[a][b] == B[b][a]


# --------------------------------------------------------------------------------------------- to_one_letter

def test_to_one_letter_standard_and_other():
    assert to_one_letter("ALA") == "A"
    assert to_one_letter("TRP") == "W"
    assert to_one_letter("HIS") == "H"
    for other in ("MSE", "HOH", "SEC", "UNK", "HIE", "ala", "", "A"):
        assert to_one_letter(other) == "X"
    assert len({to_one_letter(r) for r in sa.THREE_TO_ONE}) == 20


# --------------------------------------------------------------------------------------------- hand-solved

def test_identical_sequences():
    # H-E-A-G: 8 + 5 + 4 + 6 = 23
    r = align_global("HEAG", "HEAG")
    assert r.score == 23.0
    assert r.aligned_structure == "HEAG" and r.aligned_uniprot == "HEAG"
    assert r.structure_to_uniprot == (1, 2, 3, 4)
    assert (r.aligned_pairs, r.identical) == (4, 4)
    assert r.identity_pct == 100.0 and r.coverage_pct == 100.0


def test_one_insertion_in_uniprot_internal_gap():
    # structure WWCC vs uniprot WWGCC: W W - C C
    # 11 + 11 - 10 (gap length 1) + 9 + 9 = 30
    r = align_global("WWCC", "WWGCC")
    assert r.score == 30.0
    assert r.aligned_structure == "WW-CC" and r.aligned_uniprot == "WWGCC"
    assert r.structure_to_uniprot == (1, 2, 4, 5)
    assert r.aligned_pairs == 4 and r.identical == 4 and r.coverage_pct == 100.0


def test_one_deletion_structure_residue_unaligned():
    # structure WWGCC vs uniprot WWCC: structure G opposite a gap
    # 11 + 11 - 10 + 9 + 9 = 30
    r = align_global("WWGCC", "WWCC")
    assert r.score == 30.0
    assert r.aligned_structure == "WWGCC" and r.aligned_uniprot == "WW-CC"
    assert r.structure_to_uniprot == (1, 2, None, 3, 4)
    assert r.aligned_pairs == 4 and r.identical == 4
    assert r.coverage_pct == pytest.approx(80.0)


def test_affine_prefers_one_long_gap_over_two_short_gaps():
    # structure WWCC vs uniprot WWGGGCC: one gap of length 3 costs 10 + 0.5*2 = 11
    # score = 11 + 11 + 9 + 9 - 11 = 29
    r = align_global("WWCC", "WWGGGCC")
    assert r.score == 29.0
    assert r.aligned_structure == "WW---CC"
    # Two separate gaps would cost 10 + 10.5 (lengths 1 and 2) = 20.5 > 11.


def test_gap_length_cost_formula():
    # structure W vs uniprot W + k Gs after it: gap length k costs 10 + 0.5*(k-1), end gaps penalized.
    for k in range(1, 8):
        r = align_global("W", "W" + "G" * k)
        assert r.score == 11 - (10 + 0.5 * (k - 1))
        assert r.aligned_structure == "W" + "-" * k


def test_end_gaps_are_penalized():
    # structure CC vs uniprot GCCG: leading and trailing uniprot overhangs are two end gaps of length 1.
    # 9 + 9 - 10 - 10 = -2  (with free end gaps the score would be 18)
    r = align_global("CC", "GCCG")
    assert r.score == -2.0
    assert r.aligned_structure == "-CC-"
    assert r.structure_to_uniprot == (2, 3)


def test_end_gap_on_structure_side():
    # structure CCW vs uniprot CC: trailing structure residue opposite a gap -> 9 + 9 - 10 = 8
    r = align_global("CCW", "CC")
    assert r.score == 8.0
    assert r.structure_to_uniprot == (1, 2, None)
    assert r.coverage_pct == pytest.approx(200 / 3)


def test_x_scoring_and_identity_rule():
    # X vs X scores -1 (BLOSUM62) and never counts as identical; X vs A scores 0.
    r = align_global("AXA", "AXA")
    assert r.score == 4 - 1 + 4
    assert r.aligned_pairs == 3 and r.identical == 2
    assert r.identity_pct == pytest.approx(200 / 3)
    r2 = align_global("X", "A")
    assert r2.score == 0.0 and r2.aligned_pairs == 1 and r2.identical == 0 and r2.identity_pct == 0.0


def test_mismatch_preferred_over_two_gaps():
    # A vs W: mismatch -3 vs two length-1 gaps -20
    r = align_global("A", "W")
    assert r.score == -3.0 and r.aligned_structure == "A" and r.aligned_uniprot == "W"
    assert r.aligned_pairs == 1 and r.identical == 0


# --------------------------------------------------------------------------------------------- empty / one letter

def test_empty_inputs():
    r = align_global("", "")
    assert r.score == 0.0 and r.structure_to_uniprot == () and r.aligned_structure == ""
    assert r.aligned_pairs == 0 and r.identity_pct is None and r.coverage_pct is None

    r = align_global("", "ACD")
    # one end gap of length 3: -(10 + 1) = -11
    assert r.score == -11.0 and r.aligned_structure == "---" and r.aligned_uniprot == "ACD"
    assert r.identity_pct is None and r.coverage_pct is None

    r = align_global("ACD", "")
    assert r.score == -11.0 and r.structure_to_uniprot == (None, None, None)
    assert r.aligned_pairs == 0 and r.identity_pct is None and r.coverage_pct == 0.0


def test_one_letter_inputs():
    r = align_global("W", "W")
    assert r.score == 11.0 and r.structure_to_uniprot == (1,)
    r = align_global("W", "AWA")
    assert r.score == 11 - 20 and r.structure_to_uniprot == (2,)


def test_invalid_characters_rejected():
    for bad in ("acd", "AC D", "AU", "A-C", "A1"):
        with pytest.raises(ValueError):
            align_global(bad, "ACD")
        with pytest.raises(ValueError):
            align_global("ACD", bad)


# --------------------------------------------------------------------------------------------- tie-break

def test_tie_break_is_documented_and_deterministic():
    # Genuine tie: structure A vs uniprot AA. Either uniprot residue can pair with A (4 - 10 = -6 both ways).
    r1 = align_global("A", "AA")
    r2 = align_global("A", "AA")
    assert r1 == r2
    assert r1.score == -6.0
    assert r1.params["tie_break"] == sa.TIE_BREAK
    # Documented rule: traceback from the end prefers the diagonal state, so the last uniprot residue is
    # matched and the gap is placed first ("-A").
    assert r1.aligned_structure == "-A" and r1.structure_to_uniprot == (2,)

    r3 = align_global("AA", "A")
    assert r3.score == -6.0 and r3.aligned_uniprot == "-A" and r3.structure_to_uniprot == (None, 1)


def test_tie_break_repeatable_on_random_inputs():
    rng = random.Random(7)
    for _ in range(20):
        s1 = "".join(rng.choice("AG") for _ in range(rng.randint(1, 12)))
        s2 = "".join(rng.choice("AG") for _ in range(rng.randint(1, 12)))
        assert align_global(s1, s2) == align_global(s1, s2)


# --------------------------------------------------------------------------------------------- params / consistency

def test_params():
    p = align_global("A", "A").params
    assert p == {
        "matrix": "BLOSUM62", "gap_open": 10, "gap_extend": 0.5, "end_gaps": "penalized",
        "tie_break": sa.TIE_BREAK, "implementation": sa.IMPLEMENTATION_VERSION,
    }


def _rescore(aligned_a: str, aligned_b: str) -> float:
    total = 0.0
    k = 0
    while k < len(aligned_a):
        a, b = aligned_a[k], aligned_b[k]
        if a != "-" and b != "-":
            total += B[a][b]
            k += 1
            continue
        side = 0 if a == "-" else 1
        length = 0
        while k < len(aligned_a) and (aligned_a[k] == "-") == (side == 0) and (aligned_b[k] == "-") == (side == 1):
            length += 1
            k += 1
        total -= 10 + 0.5 * (length - 1)
    return total


# --------------------------------------------------------------------------------------------- independent oracle

def _oracle_score(a: str, b: str) -> float:
    """Plain O(n*m) Gotoh with separate full tables; no numpy, no shared code with the module."""
    neg = float("-inf")
    go, ge = 10.0, 0.5
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return 0.0
    mm = [[neg] * (m + 1) for _ in range(n + 1)]
    ia = [[neg] * (m + 1) for _ in range(n + 1)]  # a[i] opposite gap
    ib = [[neg] * (m + 1) for _ in range(n + 1)]  # b[j] opposite gap
    mm[0][0] = 0.0
    for i in range(1, n + 1):
        ia[i][0] = -(go + ge * (i - 1))
    for j in range(1, m + 1):
        ib[0][j] = -(go + ge * (j - 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            mm[i][j] = max(mm[i - 1][j - 1], ia[i - 1][j - 1], ib[i - 1][j - 1]) + B[a[i - 1]][b[j - 1]]
            ia[i][j] = max(mm[i - 1][j] - go, ia[i - 1][j] - ge, ib[i - 1][j] - go)
            ib[i][j] = max(mm[i][j - 1] - go, ib[i][j - 1] - ge, ia[i][j - 1] - go)
    return max(mm[n][m], ia[n][m], ib[n][m])


def test_oracle_matches_on_random_sequences():
    rng = random.Random(20260930)
    alphabet = "ARNDCQEGHILKMFPSTWYVX"
    for trial in range(300):
        s1 = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        s2 = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        if trial % 3 == 0 and s1:  # related pair: mutate s1 into s2
            s2 = "".join(c if rng.random() > 0.2 else rng.choice(alphabet) for c in s1)
            s2 = s2[rng.randint(0, 3):] + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 4)))
        r = align_global(s1, s2)
        assert r.score == _oracle_score(s1, s2), (s1, s2)
        # returned alignment is consistent with its score and inputs
        assert r.aligned_structure.replace("-", "") == s1 and r.aligned_uniprot.replace("-", "") == s2
        assert _rescore(r.aligned_structure, r.aligned_uniprot) == r.score
        assert len(r.structure_to_uniprot) == len(s1)
        mapped = [p for p in r.structure_to_uniprot if p is not None]
        assert mapped == sorted(mapped) and len(set(mapped)) == len(mapped)
        assert all(1 <= p <= len(s2) for p in mapped)
        assert r.aligned_pairs == len(mapped)
        assert r.identical == sum(1 for i, p in enumerate(r.structure_to_uniprot)
                                  if p is not None and s1[i] == s2[p - 1] and s1[i] != "X")


# --------------------------------------------------------------------------------------------- size cap

def test_size_cap_boundary():
    assert MAX_ALIGNMENT_CELLS == 20_000_000
    assert alignment_too_large(4000, 5000) is False  # exactly at cap
    assert alignment_too_large(4000, 5000 + 1) is True
    assert alignment_too_large(20_000_001, 1) is True
    assert alignment_too_large(0, 10**9) is False
    assert alignment_too_large(10, 10, max_cells=100) is False
    assert alignment_too_large(10, 11, max_cells=100) is True


def test_300x700_runs_quickly():
    rng = random.Random(1)
    alphabet = "ARNDCQEGHILKMFPSTWYV"
    s2 = "".join(rng.choice(alphabet) for _ in range(700))
    s1 = s2[200:500]
    t0 = time.perf_counter()
    r = align_global(s1, s2)
    assert time.perf_counter() - t0 < 5.0
    assert r.structure_to_uniprot == tuple(range(201, 501))
    assert r.identity_pct == 100.0 and r.coverage_pct == 100.0


# --------------------------------------------------------------------------------------------- co-optimal ambiguity

def test_isolated_terminal_residue_with_two_equal_placements_is_ambiguous():
    # Like 1MQ4 S388: "WS" vs "WSKKKS". S at UniProt 2 (end gap of 4 after) or at 6 (internal gap of 4 before)
    # both score 11 + 4 - (10 + 0.5 * 3) = 3.5. W has one placement.
    r = align_global("WS", "WSKKKS")
    assert r.score == 3.5 and r.structure_to_uniprot == (1, 6)
    assert r.ambiguous_positions == (1,)


def test_unique_cases_stay_unambiguous():
    r = align_global("WS", "WSKKKA")                      # only one S -> unique
    assert r.structure_to_uniprot == (1, 2) and r.ambiguous_positions == ()
    r = align_global("WCW", "WW")                         # C is a gap in the only optimal alignment
    assert r.score == 12.0 and r.structure_to_uniprot == (1, None, 2) and r.ambiguous_positions == ()
    assert align_global("", "").ambiguous_positions == () and align_global("A", "").ambiguous_positions == ()
    assert align_global("ARNDCQEGHI", "ARNDCQEGHI").ambiguous_positions == ()


def test_gap_in_some_optimal_alignments_is_ambiguous():
    # "A" vs "AA": A at 1 or at 2 (the other UniProt A is an end gap either way) -> ambiguous.
    r = align_global("A", "AA")
    assert r.structure_to_uniprot == (2,) and r.ambiguous_positions == (0,)


def _all_optimal_placements(a: str, b: str) -> list[set]:
    """Brute force: every optimal alignment enumerated from full plain-Python Gotoh tables (general recurrence
    everywhere, no boundary shortcuts); per structure index the set of UniProt positions (None = gap) it takes."""
    neg = float("-inf")
    go, ge = 10.0, 0.5
    n, m = len(a), len(b)
    tab = {s: [[neg] * (m + 1) for _ in range(n + 1)] for s in "MXY"}
    tab["M"][0][0] = 0.0

    def preds(s, i, j):
        if s == "M" and i and j:
            return [(t, i - 1, j - 1, B[a[i - 1]][b[j - 1]]) for t in "MXY"]
        if s == "X" and i:
            return [("M", i - 1, j, -go), ("X", i - 1, j, -ge), ("Y", i - 1, j, -go)]
        if s == "Y" and j:
            return [("M", i, j - 1, -go), ("Y", i, j - 1, -ge), ("X", i, j - 1, -go)]
        return []

    for i in range(n + 1):
        for j in range(m + 1):
            for s in "MXY":
                if (i, j, s) != (0, 0, "M"):
                    tab[s][i][j] = max([tab[t][p][q] + w for t, p, q, w in preds(s, i, j)], default=neg)
    best = max(tab[s][n][m] for s in "MXY")
    placements: list[set] = [set() for _ in range(n)]

    def walk(s, i, j, path):
        if (s, i, j) == ("M", 0, 0):
            for k, pos in path:
                placements[k].add(pos)
            return
        if s == "M":
            path = path + [(i - 1, j)]
        elif s == "X":
            path = path + [(i - 1, None)]
        for t, p, q, w in preds(s, i, j):
            if tab[t][p][q] > neg and tab[t][p][q] + w == tab[s][i][j]:
                walk(t, p, q, path)

    for s in "MXY":
        if tab[s][n][m] == best:
            walk(s, n, m, [])
    return placements


def test_ambiguity_matches_brute_force_enumeration_of_all_optimal_alignments():
    rng = random.Random(930)
    ambiguous_seen = unique_seen = 0
    for trial in range(400):
        alphabet = "AAGS" if trial % 2 else "ARNDW"
        s1 = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 7)))
        s2 = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
        r = align_global(s1, s2)
        placements = _all_optimal_placements(s1, s2)
        expected = tuple(k for k, p in enumerate(placements) if len(p) > 1)
        assert r.ambiguous_positions == expected, (s1, s2, placements)
        for k, p in enumerate(placements):
            assert r.structure_to_uniprot[k] in p
            if len(p) == 1:
                unique_seen += 1
        ambiguous_seen += len(expected)
    assert ambiguous_seen > 50 and unique_seen > 200


def test_near_cap_runs_within_cheap_budget():
    rng = random.Random(2)
    alphabet = "ARNDCQEGHILKMFPSTWYV"
    u = "".join(rng.choice(alphabet) for _ in range(5000))
    s = u[500:4500]
    t0 = time.perf_counter()
    r = align_global(s, u)
    elapsed = time.perf_counter() - t0
    assert not alignment_too_large(len(s), len(u))
    assert r.structure_to_uniprot == tuple(range(501, 4501)) and r.ambiguous_positions == ()
    assert elapsed < 10.0, elapsed
