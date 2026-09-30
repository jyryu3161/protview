"""Tests for scripts/measure_klifs_numbering.py on the M15 reference FIXTURE set (no network, no real reference set).

The set is assembled by ``backend/tests/reference_fixture_set.py`` from verbatim kbase_kinase snapshot rows
(fixtures, not a reference import). Oracle for 1MQ4 chain A: its SIFTS segment maps PDBe 6-272 to O14965 125-391
and author number = PDBe + 119, so a KLIFS author number equals the O14965 position.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import reference_fixture_set as rfs
from mw import reference_snapshots as rs
from mw import sifts_mapping as sm
from mw.klifs_numbering import index_kinases_by_uniprot, klifs_table

from scripts import measure_klifs_numbering as mk


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    rfs.build_fixture_set(root)
    return rs.pin_active_set()


def _case(pinned):
    row = next(r for r in pinned.iter_jsonl("klifs", "match_residues.jsonl", allow_comparison_only=True)
               if r["pdb_id"] == "1MQ4")
    chain = sm.index_for_set(pinned).lookup("1MQ4", "A")
    entry = next(r for r in pinned.iter_jsonl("klifs", "kinases.jsonl") if r["uniprot"] == "O14965")
    sequence = next(r for r in pinned.iter_jsonl("uniprot", "entries.jsonl") if r["id"] == "O14965")["data"]["sequence"]
    table = klifs_table("O14965", index_kinases_by_uniprot([entry])["O14965"], sequence)
    return row["data"], chain, table, entry["pocket"], sequence


def test_1mq4_agrees_with_author_numbers(pinned):
    entries, chain, table, pocket, sequence = _case(pinned)
    result = mk.compare_structure(entries, chain, "O14965", table, pocket, sequence)
    ours = {info["klifs_index"]: pos for pos, info in table["positions"].items()}
    numbered = [e for e in entries if e["index"] in ours]
    assert all(ours[e["index"]] == int(e["Xray_position"]) for e in numbered)  # independent oracle (see docstring)
    assert result["counts"]["agree"] == result["counts"]["compared"] == len(numbered)
    assert result["counts"]["ours_missing"] == len(entries) - len(numbered)
    assert "disagree" not in result["counts"] and result["details"] == []


def test_disagreement_non_numeric_and_outside_segment_are_counted_apart(pinned):
    entries, chain, table, pocket, sequence = _case(pinned)
    ours = {info["klifs_index"]: pos for pos, info in table["positions"].items()}
    first, second, third = [e["index"] for e in entries if e["index"] in ours][:3]
    edited = copy.deepcopy(entries)
    by_index = {e["index"]: e for e in edited}
    by_index[first]["Xray_position"] = str(ours[first] + 1)  # FIXTURE edit: shifted by one
    by_index[second]["Xray_position"] = "_"                   # FIXTURE edit: KLIFS has no structure residue
    by_index[third]["Xray_position"] = "121"                  # FIXTURE edit: PDBe 2, before the SIFTS segment
    result = mk.compare_structure(edited, chain, "O14965", table, pocket, sequence)
    counts = result["counts"]
    assert counts["disagree"] == 1 and counts["excluded_non_numeric"] == 1 and counts["ours_extra"] == 1
    assert counts["sifts_outside_segments"] == 1
    assert result["excluded_values"] == {json.dumps("_"): 1}
    detail = result["details"][0]
    assert (detail["klifs_index"], detail["klifs_uniprot"], detail["ours_uniprot"]) == (first, ours[first] + 1,
                                                                                         ours[first])
    assert detail["ours_letter"] == detail["pocket_letter"] == pocket[first - 1]
    assert counts.get("disagree_ours_letter_differs_from_pocket", 0) == 0


def test_measure_on_fixture_set(pinned):
    result = mk.measure(pinned)
    assert result["match_rows"] == 4 and result["structures_compared"] == 3
    assert result["structures_skipped"] == {"sifts:sifts_chain_no_segments": 1}  # 1AD5:A
    assert result["disagree"] == 0 and result["positions_compared"] == result["agree"] > 0


def test_main_writes_report_and_fails_without_a_set(pinned, tmp_path, capsys):
    out = tmp_path / "report.txt"
    assert mk.main(["--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["set_hash"] == pinned.set_hash
    assert "positions compared" in out.read_text()
    assert mk.main(["--reference-dir", str(tmp_path / "missing"), "--out", str(out)]) == 1
