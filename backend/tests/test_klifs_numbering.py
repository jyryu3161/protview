"""KLIFS pocket -> UniProt position table (mw.klifs_numbering).

Synthetic cases use sequences built in this file (marked synthetic fixtures). The real-data check reads the
local kbase_kinase KLIFS 2026-09-19 / UniProt 2026-09-15 snapshots read-only and uses literature gatekeeper
positions (EGFR T790, ABL1 T315, CDK2 F80, BRAF T529) as an independent oracle.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from mw.klifs_numbering import (
    KLIFS_REGIONS,
    index_kinases_by_uniprot,
    klifs_table,
    parse_kinases_jsonl,
)

SPACER = "WW"  # synthetic fixture spacer; pocket letters never contain W
ALPHABET = "ACDEFGHIKLMNPQRSTVY"


def _synthetic_pocket(seed: int = 7) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(ALPHABET) for _ in range(85))


def _regions(pocket: str) -> list[tuple[str, str]]:
    return [(name, pocket[start - 1:end]) for name, start, end in KLIFS_REGIONS]


def _sequence(pocket: str, *, insert_after: dict[str, str] | None = None, prefix: str = "") -> str:
    """Synthetic fixture: N-term spacer, then each region's residues (gaps dropped) separated by spacers."""
    insert_after = insert_after or {}
    parts = [prefix + "WWWW"]
    for name, text in _regions(pocket):
        parts.append(text.replace("-", "").replace("_", ""))
        parts.append(SPACER + insert_after.get(name, ""))
    parts.append("WWWW")
    return "".join(parts)


def _entry(pocket, accession: str = "P00000") -> dict:
    return {"family": "SYN", "kinase_ID": 1, "name": "SYN_FIXTURE", "pocket": pocket, "species": "Human",
            "uniprot": accession}


def _true_positions(pocket: str, sequence: str) -> dict[int, int]:
    """Oracle for the synthetic layout: walk the construction independently of the module."""
    expected: dict[int, int] = {}
    pos = 4  # 0-based after "WWWW"
    for _name, start, end in KLIFS_REGIONS:
        for idx in range(start, end + 1):
            ch = pocket[idx - 1]
            if ch in "-_":
                continue
            assert sequence[pos] == ch
            expected[pos + 1] = idx
            pos += 1
        pos += len(SPACER)
    return expected


def _label(idx: int) -> str:
    for name, start, end in KLIFS_REGIONS:
        if start <= idx <= end:
            return f"{name}.{idx}"
    raise AssertionError(idx)


def test_region_table_matches_snapshot_spelling():
    names = [r[0] for r in KLIFS_REGIONS]
    assert names == ["I", "g.l", "II", "III", "αC", "b.l", "IV", "V", "GK", "hinge", "linker", "αD", "αE", "VI",
                     "c.l", "VII", "VIII", "xDFG", "a.l"]
    covered = [i for _n, s, e in KLIFS_REGIONS for i in range(s, e + 1)]
    assert covered == list(range(1, 86))


def test_all_regions_resolve_on_clean_synthetic_sequence():
    pocket = _synthetic_pocket()
    seq = _sequence(pocket)
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["absent_reason"] is None
    assert out["unresolved_regions"] == []
    expected = _true_positions(pocket, seq)
    assert len(out["positions"]) == 85
    for pos, idx in expected.items():
        assert out["positions"][pos] == {"klifs_index": idx, "klifs_label": _label(idx), "klifs_match": "contiguous"}
        assert seq[pos - 1] == pocket[idx - 1]
    assert out["positions"][min(expected)]["klifs_label"] == "I.1"


@pytest.mark.parametrize("gap", ["-", "_"])
def test_gap_positions_get_no_number(gap):
    base = _synthetic_pocket()
    pocket = base[:46] + gap + base[47:]  # hinge.47 is a gap, hinge splits into two fragments
    pocket = pocket[:21] + gap + gap + pocket[23:]  # αC.22, αC.23
    seq = _sequence(pocket)
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["absent_reason"] is None
    assert out["unresolved_regions"] == []
    indexes = {v["klifs_index"] for v in out["positions"].values()}
    assert indexes == set(range(1, 86)) - {22, 23, 47}
    for pos, idx in _true_positions(pocket, seq).items():
        assert out["positions"][pos]["klifs_index"] == idx


@pytest.mark.parametrize("pocket", ["", None, "-" * 85])
def test_empty_pocket(pocket):
    out = klifs_table("P00000", [_entry(pocket)], "MKV")
    assert out == {"accession": "P00000", "absent_reason": "klifs_pocket_empty", "positions": {},
                   "unresolved_regions": [], "gapped_regions": []}


def test_not_in_klifs_and_multiple_entries():
    pocket = _synthetic_pocket()
    seq = _sequence(pocket)
    out = klifs_table("P00000", [], seq)
    assert out["absent_reason"] == "accession_not_in_klifs"
    assert out["positions"] == {} and out["unresolved_regions"] == []
    out = klifs_table("P00000", [_entry(pocket), _entry(_synthetic_pocket(8))], seq)
    assert out["absent_reason"] == "klifs_multiple_entries"
    assert out["positions"] == {} and out["unresolved_regions"] == []
    # multiple entries win even when one of them has an empty pocket
    out = klifs_table("P00000", [_entry(pocket), _entry(None)], seq)
    assert out["absent_reason"] == "klifs_multiple_entries"


def test_ambiguous_region_is_unresolved_as_a_whole():
    pocket = _synthetic_pocket()
    alpha_e = pocket[59:64]
    # a second copy of αE sits between αE and VI: both placements satisfy the order constraints
    seq = _sequence(pocket, insert_after={"αE": alpha_e + SPACER})
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["absent_reason"] is None
    assert out["unresolved_regions"] == ["αE"]
    indexes = {v["klifs_index"] for v in out["positions"].values()}
    assert indexes == set(range(1, 86)) - set(range(60, 65))


def test_ambiguous_region_with_gap_is_unresolved_as_a_whole():
    base = _synthetic_pocket()
    pocket = base[:55] + "-" + base[56:]  # αD.56 gap: αD = 3 + 3 residue fragments
    frag2 = pocket[56:59]
    # an extra copy of αD's second fragment right after αD: the first fragment is unique, the second is not
    seq = _sequence(pocket, insert_after={"αD": frag2 + SPACER})
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["αD"]
    indexes = {v["klifs_index"] for v in out["positions"].values()}
    assert not indexes & set(range(53, 60))


def test_order_constraint_excludes_copies_outside_the_window():
    pocket = _synthetic_pocket()
    hinge = pocket[45:48]
    gk = pocket[44]
    # copies of hinge and of the one-residue GK before region I, and GK again after a.l: order excludes them
    seq = _sequence(pocket, prefix=hinge + gk + "WW")
    seq = seq + gk + hinge
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == []
    shifted = {pos + 6: idx for pos, idx in _true_positions(pocket, seq[6:]).items()}
    for pos, idx in shifted.items():
        assert out["positions"][pos]["klifs_index"] == idx


def test_missing_region_is_unresolved_and_neighbours_still_resolve():
    pocket = _synthetic_pocket()
    seq = _sequence(pocket)
    expected = _true_positions(pocket, seq)
    ac_pos = next(p for p, i in expected.items() if i == 25)
    seq = seq[:ac_pos - 1] + "W" + seq[ac_pos:]  # point change inside αC
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["αC"]
    assert {v["klifs_index"] for v in out["positions"].values()} == set(range(1, 86)) - set(range(20, 31))


def test_fragments_out_of_order_within_region_do_not_match():
    base = _synthetic_pocket()
    pocket = base[:72] + "-" + base[73:]  # c.l = 68-72 | 74-75
    frag1, frag2 = pocket[67:72], pocket[73:75]
    seq = _sequence(pocket)
    good = frag1 + frag2
    assert seq.count(good) == 1
    seq = seq.replace(good, frag2 + "WW" + frag1)
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert "c.l" in out["unresolved_regions"]


def test_no_consistent_order_leaves_every_region_unresolved():
    pocket = _synthetic_pocket()
    regions = _regions(pocket)
    seq = "WWWW" + SPACER.join(text for _n, text in reversed(regions)) + "WWWW"
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["absent_reason"] is None
    assert out["positions"] == {}
    assert out["unresolved_regions"] == [n for n, _s, _e in KLIFS_REGIONS]


def _with_segment(pocket: str, old: str, new: str) -> str:
    seq = _sequence(pocket)
    assert seq.count(old) == 1
    return seq.replace(old, new)


def test_dropped_residue_region_resolves_as_gapped_unique():
    pocket = _synthetic_pocket()
    bl = pocket[30:37]  # b.l.31-37, fixture "CICVFLQ"
    # EGFR-like: the sequence has an extra residue inside b.l that the pocket drops without a gap character
    seq = _with_segment(pocket, bl, bl[:3] + "W" + bl[3:])
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == []
    assert out["gapped_regions"] == ["b.l"]
    assert len(out["positions"]) == 85
    for pos, entry in out["positions"].items():
        idx = entry["klifs_index"]
        assert seq[pos - 1] == pocket[idx - 1]
        assert entry["klifs_label"] == _label(idx)
        assert entry["klifs_match"] == ("gapped_unique" if 31 <= idx <= 37 else "contiguous")
    by_index = {v["klifs_index"]: pos for pos, v in out["positions"].items()}
    assert by_index[34] == by_index[33] + 2  # the extra residue is skipped, not numbered
    assert [by_index[i] for i in (31, 32, 33)] == [by_index[31] + k for k in range(3)]
    assert seq[by_index[33]] == "W"


def test_gapped_region_keeps_klifs_indexes_of_its_own_gaps():
    base = _synthetic_pocket()
    pocket = base[:32] + "-" + base[33:]  # b.l.33 is a gap: letters C I | V F L Q
    bl_letters = pocket[30:32] + pocket[33:37]
    seq = _with_segment(pocket, bl_letters, bl_letters[:4] + "W" + bl_letters[4:])
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == [] and out["gapped_regions"] == ["b.l"]
    got = {v["klifs_index"] for v in out["positions"].values() if v["klifs_match"] == "gapped_unique"}
    assert got == {31, 32, 34, 35, 36, 37}


def test_two_embeddings_stay_unresolved():
    pocket = _synthetic_pocket()
    bl = pocket[30:37]
    assert bl[2] == "C"
    # "CIC" + "C" + "VFLQ": the second C of the pocket can sit on either C -> two placements
    seq = _with_segment(pocket, bl, bl[:3] + bl[2] + bl[3:])
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["b.l"]
    assert out["gapped_regions"] == []
    assert not {v["klifs_index"] for v in out["positions"].values()} & set(range(31, 38))
    assert {v["klifs_match"] for v in out["positions"].values()} == {"contiguous"}


def test_region_without_resolved_neighbour_on_both_sides_is_not_attempted():
    pocket = _synthetic_pocket()[:83] + "KA"  # fixture a.l letters that occur nowhere else
    al = pocket[83:85]  # a.l.84-85, last region: no resolved region after it
    first = pocket[0:3]  # I.1-3, first region: no resolved region before it
    seq = _with_segment(pocket, al + "WWWW", al[0] + "W" + al[1] + "WWWW")
    seq = seq.replace("WWWW" + first, "WWWW" + first[0] + "W" + first[1:], 1)
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["I", "a.l"]
    assert out["gapped_regions"] == []
    assert len(out["positions"]) == 85 - 5


def _pocket_unique_gk() -> str:
    base = _synthetic_pocket()
    return base[:44] + "K" + base[45:]  # fixture GK letter that occurs nowhere else (base has no K)


def test_conflicting_gapped_placements_in_one_window_are_dropped():
    pocket = _pocket_unique_gk()
    iv, v = pocket[37:41], pocket[41:44]  # IV "FVEY", V "LVG"
    # window "FLVWEYG": IV embeds only as F.V.EY, V only as LV.G, and both use the same V
    seq = _with_segment(pocket, iv + SPACER + v, "FLVWEYG")
    assert iv not in seq and v not in seq
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["IV", "V"]
    assert out["gapped_regions"] == []
    assert len(out["positions"]) == 85 - 7


def test_consecutive_unresolved_regions_get_no_gapped_numbers():
    # spec 5.7: the second pass needs BOTH immediately adjacent regions resolved in the first pass; IV and V
    # are next to each other, so neither qualifies even though each would embed uniquely in the shared window
    pocket = _pocket_unique_gk()
    iv, v = pocket[37:41], pocket[41:44]
    seq = _with_segment(pocket, iv + SPACER + v, iv[:2] + "W" + iv[2:] + SPACER + v[0] + "W" + v[1:])
    out = klifs_table("P00000", [_entry(pocket)], seq)
    assert out["unresolved_regions"] == ["IV", "V"]
    assert out["gapped_regions"] == []
    assert len(out["positions"]) == 85 - 7
    assert {v["klifs_match"] for v in out["positions"].values()} == {"contiguous"}


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        klifs_table("P00000", [_entry("ACD")], "ACD")
    with pytest.raises(ValueError):
        klifs_table("P00000", [_entry(_synthetic_pocket(), accession="Q99999")], "ACD")
    with pytest.raises(ValueError):
        klifs_table("P00000", [_entry("X" * 84 + "1")], "ACD")


def test_index_helpers():
    text = "\n".join(json.dumps(r) for r in [
        {"uniprot": "P1", "pocket": "A" * 85, "kinase_ID": 1},
        {"uniprot": "P1", "pocket": None, "kinase_ID": 2},
        {"uniprot": "P2", "pocket": "", "kinase_ID": 3},
    ]) + "\n\n"
    rows = parse_kinases_jsonl(text)
    assert len(rows) == 3
    idx = index_kinases_by_uniprot(rows)
    assert [r["kinase_ID"] for r in idx["P1"]] == [1, 2]
    assert [r["kinase_ID"] for r in idx["P2"]] == [3]
    assert idx.get("P3", []) == []


# kbase_kinase checkout next to the repository (<repo>/../kbase_kinase/ref); MW_KBASE_REF overrides (e.g. a worktree).
KBASE = Path(os.environ.get("MW_KBASE_REF") or Path(__file__).resolve().parents[2].parent / "kbase_kinase" / "ref")
KLIFS_KINASES = KBASE / "klifs/2026-09-19/kinases.jsonl"
UNIPROT_ENTRIES = KBASE / "uniprot/2026-09-15/entries.jsonl"


@pytest.mark.skipif(not (KLIFS_KINASES.exists() and UNIPROT_ENTRIES.exists()),
                    reason=f"kbase_kinase KLIFS/UniProt snapshots absent at {KBASE} (set MW_KBASE_REF)")
def test_real_snapshot_gatekeeper_and_hinge():
    index = index_kinases_by_uniprot(parse_kinases_jsonl(KLIFS_KINASES.read_text(encoding="utf-8")))
    sequences = {}
    for line in UNIPROT_ENTRIES.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("status") == "ok":
            sequences[row["id"]] = row["data"]["sequence"]
    # literature gatekeepers (UniProt canonical numbering) as the independent oracle
    gatekeepers = {"P00533": 790, "P00519": 315, "P24941": 80, "P15056": 529, "P12931": None}
    for accession, gk_pos in gatekeepers.items():
        entries = index[accession]
        pocket = entries[0]["pocket"]
        out = klifs_table(accession, entries, sequences[accession])
        assert out["absent_reason"] is None, accession
        assert "GK" not in out["unresolved_regions"] and "hinge" not in out["unresolved_regions"], accession
        by_index = {v["klifs_index"]: pos for pos, v in out["positions"].items()}
        for idx in (45, 46, 47, 48):
            pos = by_index[idx]
            assert sequences[accession][pos - 1] == pocket[idx - 1], (accession, idx)
            assert out["positions"][pos]["klifs_label"] == ("GK.45" if idx == 45 else f"hinge.{idx}")
        assert by_index[46] == by_index[45] + 1 and by_index[48] == by_index[46] + 2
        if gk_pos is not None:
            assert by_index[45] == gk_pos, accession


@pytest.mark.skipif(not (KLIFS_KINASES.exists() and UNIPROT_ENTRIES.exists()),
                    reason=f"kbase_kinase KLIFS/UniProt snapshots absent at {KBASE} (set MW_KBASE_REF)")
def test_real_snapshot_every_numbered_letter_matches_the_pocket():
    index = index_kinases_by_uniprot(parse_kinases_jsonl(KLIFS_KINASES.read_text(encoding="utf-8")))
    sequences = {}
    for line in UNIPROT_ENTRIES.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("status") == "ok":
            sequences[row["id"]] = row["data"]["sequence"]
    applied = 0
    for accession, entries in index.items():
        if accession not in sequences:
            continue
        out = klifs_table(accession, entries, sequences[accession])
        if out["absent_reason"] is not None:
            continue
        applied += 1
        pocket = entries[0]["pocket"]
        assert not set(out["gapped_regions"]) & set(out["unresolved_regions"]), accession
        by_index = {}
        for pos, entry in out["positions"].items():
            idx = entry["klifs_index"]
            assert sequences[accession][pos - 1] == pocket[idx - 1], (accession, pos, idx)
            region = entry["klifs_label"].rsplit(".", 1)[0]
            assert entry["klifs_match"] == ("gapped_unique" if region in out["gapped_regions"] else "contiguous")
            by_index[idx] = pos
        ordered = [by_index[i] for i in sorted(by_index)]
        assert ordered == sorted(ordered) and len(set(ordered)) == len(ordered), accession
    assert applied == 494
    # EGFR b.l: KLIFS "VDPHVCR" drops N771 of UniProt V769-R776 without a gap character
    out = klifs_table("P00533", index["P00533"], sequences["P00533"])
    assert "b.l" in out["gapped_regions"]
    bl = {v["klifs_index"]: pos for pos, v in out["positions"].items() if v["klifs_label"].startswith("b.l.")}
    assert bl == {31: 769, 32: 770, 33: 772, 34: 773, 35: 774, 36: 775, 37: 776}
