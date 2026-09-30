"""M15 measurement: our KLIFS numbering (mw.klifs_numbering) vs KLIFS ``match_residues`` through SIFTS. No network.

Usage: python scripts/measure_klifs_numbering.py [--reference-dir DIR] [--out docs/qa/m15-numbering-draft/klifs_measurement.txt]

Reads the active reference set (``mw.reference_snapshots``; ``MW_REFERENCE_DIR`` or ``--reference-dir``). The KLIFS
``match_residues.jsonl`` file is comparison-only and is opened with ``allow_comparison_only=True``; it is never an
input of our numbering. For every ``match_residues`` row whose PDB chain decodes in SIFTS (``mw.sifts_mapping``) and
whose UniProt accession (via the KLIFS ``kinase_ID``) gets a KLIFS table (``klifs_table`` with the UniProt snapshot
sequence), each KLIFS entry is mapped:

    Xray_position (author residue number, insertion code "") -> SIFTS residue of an entity that has UniProt segments
    for this chain -> PDBe number -> UniProt position by the segment rule

and compared with the UniProt position our table gives to the same KLIFS index. Outcomes per entry:

* ``agree`` / ``disagree``: both sides have a UniProt position (same / different).
* ``ours_missing``: KLIFS maps to a UniProt position of the accession, our table has no number for that index.
* ``ours_extra``: our table numbers the index, KLIFS gives no structure residue (non-numeric ``Xray_position``).
* ``excluded_non_numeric``: ``Xray_position`` is not an integer string (``"_"``, null, ``"_1"`` ...), counted by value.
* ``sifts_no_residue`` / ``sifts_ambiguous_author`` / ``sifts_outside_segments`` / ``sifts_other_accession``: the KLIFS
  author number could not be taken to a UniProt position of the accession through SIFTS (not a disagreement).

This is a measurement for review, not a product result.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from mw import reference_snapshots as rs
from mw import sifts_mapping as sm
from mw.klifs_numbering import index_kinases_by_uniprot, klifs_table
from mw.sequence_alignment import to_one_letter

DEFAULT_OUT = ROOT / "docs" / "qa" / "m15-numbering-draft" / "klifs_measurement.txt"
_INT = re.compile(r"-?\d+\Z")
MAX_DETAILS = 20


def _region(label: str) -> str:
    return label.rsplit(".", 1)[0]


def compare_structure(entries: Iterable[Mapping[str, Any]], chain: sm.SiftsChain, accession: str,
                      table: Mapping[str, Any], pocket: str, uniprot_sequence: str) -> dict[str, Any]:
    """Compare one ``match_residues`` row's entries with our KLIFS table for ``accession`` (pure function).

    Returns ``{"counts", "by_match", "disagree_by_region", "ours_missing_by_region", "excluded_values",
    "details"}``; ``details`` lists every disagreement as ``{klifs_index, klifs_label, xray_position,
    klifs_uniprot, ours_uniprot, klifs_match, pocket_letter, klifs_residue, ours_letter}`` where ``klifs_residue``
    is the one-letter SIFTS residue name at the KLIFS author number and ``ours_letter`` the UniProt letter at our
    position. A disagreement is also counted as ``disagree_klifs_residue_differs_from_pocket`` when the residue KLIFS
    points to is not the KLIFS pocket letter for that index (an inconsistency inside the KLIFS data itself), and as
    ``disagree_ours_letter_differs_from_pocket`` when our UniProt letter is not the pocket letter.
    """
    by_author: dict[tuple[int, str], list[tuple[int, int]]] = {}
    names = {(res["entity_id"], res["pdbe_number"]): res["residue_name"] for res in chain.residues}
    for res in chain.residues:
        if res["entity_id"] in chain.segments and res["author_number"] is not None:
            by_author.setdefault((res["author_number"], res["icode"]), []).append((res["entity_id"], res["pdbe_number"]))
    ours = {info["klifs_index"]: (pos, info) for pos, info in table["positions"].items()}
    counts: Counter[str] = Counter()
    by_match: dict[str, Counter[str]] = {}
    disagree_by_region: Counter[str] = Counter()
    missing_by_region: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    for entry in entries:
        index, label, xray = entry["index"], entry["KLIFS_position"], entry["Xray_position"]
        mine = ours.get(index)
        if mine is not None and mine[1]["klifs_label"] != label:
            counts["label_mismatch"] += 1
        match = mine[1]["klifs_match"] if mine is not None else None
        if not (isinstance(xray, str) and _INT.fullmatch(xray)):
            counts["excluded_non_numeric"] += 1
            excluded[json.dumps(xray)] += 1
            if mine is not None:
                counts["ours_extra"] += 1
                by_match.setdefault(match, Counter())["ours_extra"] += 1
            continue
        hits = by_author.get((int(xray), ""), [])
        if not hits:
            counts["sifts_no_residue"] += 1
            continue
        if len(hits) > 1:
            counts["sifts_ambiguous_author"] += 1
            continue
        entity_id, pdbe = hits[0]
        found = chain.uniprot_position(entity_id, pdbe)
        if found is None:
            counts["sifts_outside_segments"] += 1
            continue
        if found[0] != accession:
            counts["sifts_other_accession"] += 1
            continue
        if mine is None:
            counts["ours_missing"] += 1
            missing_by_region[_region(label)] += 1
            continue
        counts["compared"] += 1
        outcome = "agree" if mine[0] == found[1] else "disagree"
        counts[outcome] += 1
        by_match.setdefault(match, Counter())[outcome] += 1
        if outcome == "disagree":
            disagree_by_region[_region(label)] += 1
            klifs_residue = to_one_letter(names[(entity_id, pdbe)])
            if klifs_residue != pocket[index - 1]:
                counts["disagree_klifs_residue_differs_from_pocket"] += 1
            if uniprot_sequence[mine[0] - 1] != pocket[index - 1]:
                counts["disagree_ours_letter_differs_from_pocket"] += 1
            details.append({"klifs_index": index, "klifs_label": label, "xray_position": xray,
                            "klifs_uniprot": found[1], "ours_uniprot": mine[0], "klifs_match": match,
                            "pocket_letter": pocket[index - 1], "klifs_residue": klifs_residue,
                            "ours_letter": uniprot_sequence[mine[0] - 1]})
    return {"counts": dict(counts), "by_match": {k: dict(v) for k, v in by_match.items()},
            "disagree_by_region": dict(disagree_by_region), "ours_missing_by_region": dict(missing_by_region),
            "excluded_values": dict(excluded), "details": details}


def _merge(total: dict[str, Any], part: dict[str, Any], pdb_chain: str, accession: str) -> None:
    for key in ("counts", "disagree_by_region", "ours_missing_by_region", "excluded_values"):
        bucket = total.setdefault(key, Counter())
        bucket.update(part[key])
    for match, counter in part["by_match"].items():
        total.setdefault("by_match", {}).setdefault(match, Counter()).update(counter)
    for detail in part["details"]:
        total.setdefault("details", []).append({"structure": pdb_chain, "accession": accession, **detail})


def measure(pinned: rs.PinnedSet) -> dict[str, Any]:
    uniprot = {}
    for row in pinned.iter_jsonl("uniprot", "entries.jsonl"):
        data = row.get("data") if isinstance(row, dict) else None
        if row.get("status") == "ok" and isinstance(data, dict) and isinstance(data.get("sequence"), str):
            uniprot[row["id"]] = data["sequence"]
    kinase_rows = list(pinned.iter_jsonl("klifs", "kinases.jsonl"))
    by_accession = index_kinases_by_uniprot(kinase_rows)
    accession_of = {row["kinase_ID"]: row.get("uniprot") for row in kinase_rows}
    sifts = sm.index_for_set(pinned)
    tables: dict[str, dict[str, Any]] = {}
    skipped: Counter[str] = Counter()
    total: dict[str, Any] = {"counts": Counter(), "by_match": {}, "disagree_by_region": Counter(),
                             "ours_missing_by_region": Counter(), "excluded_values": Counter(), "details": []}
    structures = 0
    rows = 0
    disagreeing: dict[str, int] = {}
    for row in pinned.iter_jsonl("klifs", "match_residues.jsonl", allow_comparison_only=True):
        rows += 1
        if row.get("status") != "ok" or not isinstance(row.get("data"), list):
            skipped["match_row_not_ok"] += 1
            continue
        accession = accession_of.get(row.get("kinase_ID"))
        if not accession:
            skipped["kinase_without_uniprot"] += 1
            continue
        chain = sifts.lookup(row["pdb_id"], row["chain"])
        if isinstance(chain, sm.SiftsUnusable):
            skipped[f"sifts:{chain.reason_code}"] += 1
            continue
        if accession not in chain.accessions:
            skipped["accession_not_in_sifts_chain"] += 1
            continue
        if accession not in uniprot:
            skipped["uniprot_entry_missing"] += 1
            continue
        if accession not in tables:
            tables[accession] = klifs_table(accession, by_accession.get(accession, []), uniprot[accession])
        table = tables[accession]
        if table["absent_reason"] is not None:
            skipped[f"klifs_table:{table['absent_reason']}"] += 1
            continue
        structures += 1
        part = compare_structure(row["data"], chain, accession, table, by_accession[accession][0]["pocket"],
                                 uniprot[accession])
        _merge(total, part, f"{row['pdb_id']}:{row['chain']}", accession)
        if part["details"]:
            disagreeing[f"{row['pdb_id']}:{row['chain']}"] = len(part["details"])
    counts = total["counts"]
    compared = counts.get("compared", 0)
    return {
        "set_hash": pinned.set_hash,
        "snapshots": {s["source"]: s["snapshot_id"] for s in pinned.summary()},
        "match_rows": rows,
        "structures_compared": structures,
        "structures_skipped": dict(sorted(skipped.items())),
        "accessions_with_table": sum(1 for t in tables.values() if t["absent_reason"] is None),
        "positions_compared": compared,
        "agree": counts.get("agree", 0),
        "disagree": counts.get("disagree", 0),
        "agreement_pct": round(100.0 * counts.get("agree", 0) / compared, 3) if compared else None,
        "ours_missing": counts.get("ours_missing", 0),
        "ours_extra": counts.get("ours_extra", 0),
        "excluded_non_numeric": counts.get("excluded_non_numeric", 0),
        "excluded_values": dict(sorted(total["excluded_values"].items())),
        "sifts_unmapped": {k: counts.get(k, 0) for k in ("sifts_no_residue", "sifts_ambiguous_author",
                                                          "sifts_outside_segments", "sifts_other_accession")},
        "label_mismatch": counts.get("label_mismatch", 0),
        "disagree_klifs_residue_differs_from_pocket": counts.get("disagree_klifs_residue_differs_from_pocket", 0),
        "disagree_ours_letter_differs_from_pocket": counts.get("disagree_ours_letter_differs_from_pocket", 0),
        "disagreeing_structures": dict(sorted(disagreeing.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_klifs_match": {str(k): dict(sorted(v.items())) for k, v in sorted(total["by_match"].items(),
                                                                               key=lambda kv: str(kv[0]))},
        "disagree_by_region": dict(sorted(total["disagree_by_region"].items())),
        "ours_missing_by_region": dict(sorted(total["ours_missing_by_region"].items())),
        "disagreements_total": len(total["details"]),
        "disagreements_first": total["details"][:MAX_DETAILS],
    }


def _text(result: dict[str, Any]) -> str:
    lines = [
        "M15 T5 KLIFS numbering measurement (draft, Opus 5.5 implementer; not a review; not a product result)",
        "command: python scripts/measure_klifs_numbering.py  (no network; comparison-only match_residues)",
        f"reference set: {result['set_hash']}",
        "snapshots: " + ", ".join(f"{k}={v}" for k, v in result["snapshots"].items()),
        (f"match_residues rows: {result['match_rows']}; structures compared: {result['structures_compared']}; "
         f"skipped: {json.dumps(result['structures_skipped'])}"),
        (f"positions compared: {result['positions_compared']}; agree {result['agree']}; disagree {result['disagree']}; "
         f"agreement {result['agreement_pct']}%"),
        (f"ours_missing (KLIFS maps, we have no number): {result['ours_missing']} by region "
         f"{json.dumps(result['ours_missing_by_region'], ensure_ascii=False)}"),
        f"ours_extra (we number, KLIFS has no structure residue): {result['ours_extra']}",
        f"excluded non-numeric Xray_position: {result['excluded_non_numeric']} {json.dumps(result['excluded_values'])}",
        f"KLIFS number not mappable through SIFTS: {json.dumps(result['sifts_unmapped'])}",
        f"label mismatches (our label vs KLIFS_position for the same index): {result['label_mismatch']}",
        f"by klifs_match: {json.dumps(result['by_klifs_match'])}",
        f"disagreements by region: {json.dumps(result['disagree_by_region'], ensure_ascii=False)}",
        ("disagreements where the residue at the KLIFS Xray_position is not the KLIFS pocket letter: "
         f"{result['disagree_klifs_residue_differs_from_pocket']} of {result['disagree']}"),
        ("disagreements where our UniProt letter is not the KLIFS pocket letter: "
         f"{result['disagree_ours_letter_differs_from_pocket']} of {result['disagree']}"),
        f"disagreements per structure: {json.dumps(result['disagreeing_structures'])}",
        f"first {MAX_DETAILS} of {result['disagreements_total']} disagreements:",
    ]
    lines += ["  " + json.dumps(d, ensure_ascii=False) for d in result["disagreements_first"]]
    lines += ["", "JSON:", json.dumps(result, indent=2, ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference-dir", type=Path, default=None, help="reference folder (default: MW_REFERENCE_DIR)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"text report path (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)
    try:
        pinned = rs.pin_active_set(args.reference_dir)
        result = measure(pinned)
    except rs.SnapshotUnavailable as exc:
        print(f"measure_klifs_numbering: reference set unavailable: {exc.reason_code}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_text(result))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
