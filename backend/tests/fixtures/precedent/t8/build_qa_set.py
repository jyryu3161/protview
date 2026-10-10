"""Builder (M27 T8) of the LABELLED SYNTHETIC inputs of the M27 offscreen acceptance (not product code).

``scripts/m27_offscreen_acceptance.py`` runs this file as a subprocess (the runner never imports ``mw``). Two commands:

``set --root DIR [--imported-at T] [--no-activate]``
    Writes one SYNTHETIC precedent reference set into ``DIR`` with ``precedent_fixture.build_set`` (the importer's
    layout and manifest rule) and prints one JSON line ``{"set_hash", "imported_at", "rows", "expect"}``. ``expect``
    is counted here from the records this file made (never from product code): per accession the move / flagged /
    reference counts and variants, the unresolved totals, and the record filters the harness clicks.

``derive --runs DIR --run RUN --source HANDLE --stage fixture|real``
    Stores LABELLED SYNTHETIC numbering-map variants of one REAL ``residue_numbering_map@1`` that the M15 tool made in
    that run (``ObjectStore.put``, ``produced_by: synthetic_fixture``, a ``qa_fixture`` label inside the object): each
    variant keeps the map as M15 wrote it and only replaces ``uniprot_accession`` on the ``mapped`` rows of a chain
    (a chain given two accessions gets the first one on its first half of mapped rows and the second on the rest, the
    fused-chain case). Run only while no backend has the run open. Prints ``{"maps": {name: {handle, chains}}}``.

Every precedent value is made up (SYNTHETIC-PROVENANCE-t8.md): accessions ``P0QA01``-``P0QA04`` (format only),
PMIDs ``9100000n``, move ids ``MOVE-7xxx``, texts that say SYNTHETIC. The real stage's single derived map attaches
real accessions to chains of a real structure only to make a request above the 1 MiB cap (refused, nothing stored).
No network. Not a ``test_*`` file (Stop hook collection).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[2]
for extra in (str(TESTS.parent), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import precedent_fixture as PF

from mw import precedent_constants as K

IMPORTED_AT = "2026-10-10T01:00:00Z"
LABEL = ("SYNTHETIC M27 T8 QA set (made-up records, accessions P0QA01-P0QA04, PMIDs 9100000n; "
         "SYNTHETIC-PROVENANCE-t8.md)")
SEARCH_TOKEN = "QA-SEARCH-ALPHA"     # in one P0QA01 observation text
TITLE_TOKEN = "QA-TITLE-BETA"        # in the bibliography title of PMID 91000003
SITES = ("bp_I_A", "gate", "front", "back")
GOALS = ("potency", "selectivity", "solubility")
TACTICS = ("add_hydrophobic_bulk", "scaffold_hop", "hbond_engagement")
P01, P02, P03, P04 = "P0QA01", "P0QA02", "P0QA03", "P0QA04"
PADDING = "SYNTHETIC fixture padding for the 1 MiB result cap test. " * 450
# derive: variant name -> chain -> accessions put on that chain's mapped rows (in this order)
DERIVED = {
    "fixture": {"d-two": {"A": [P01], "B": [P02]}, "d-fusion": {"A": [P01, P03], "B": [P03]},
                "d-big": {"A": [P04], "B": [P01]}},
    "real": {"d-size": {"A": ["P00533"], "C": ["Q06187"]}},
}
DERIVED_LABEL = {
    "fixture": "SYNTHETIC derived from a real M15 map of the derived two-chain 1MQ4 fixture: the mapped rows' accession "
               "replaced by made-up accessions (M27 T8 QA, SYNTHETIC-PROVENANCE-t8.md)",
    "real": "SYNTHETIC derived from the real M15 map of public 1FIN chains A and C: chain A rows given P00533 and chain C "
            "rows Q06187 (no such structure; only to make a request above the 1 MiB cap, refused and never stored; "
            "M27 T8 QA, SYNTHETIC-PROVENANCE-t8.md)",
}


def _location(kind: str, page: int, **fields: Any) -> dict[str, Any]:
    base = {"kind": kind, "page": page, "table_index": None, "row": None, "figure_id": None, "panel": None, "bbox": None}
    base.update(fields)
    return base


def _pmid(i: int) -> str:
    return f"9100{(i % 10) + 1:04d}"


def p0qa01_moves() -> list[dict[str, Any]]:
    """30 SYNTHETIC ``moves`` records of P0QA01 (two record pages at 25)."""
    records = []
    for i in range(30):
        site = [SITES[i % 4]] + (["back"] if i % 7 == 0 and SITES[i % 4] != "back" else [])
        basis = {10: "alias", 11: "alias", 12: "name_token", 13: "name_token", 14: "pubmed_title", 15: "notation"}
        variant = "not_reported" if i < 20 else "SYN-A1V" if i < 26 else "SYN-G2C"
        text = f"합성 SYNTHETIC fixture observation {i + 1} of P0QA01."
        if i == 6:
            text = f"합성 SYNTHETIC fixture observation with the search token {SEARCH_TOKEN}."
        record = PF.make_move(f"MOVE-{7001 + i}", uniprot=P01, resolution_basis=basis.get(i, "gene"),
                              name_as_written="SYN-QA-KINASE-1", variant=variant, pmid=_pmid(i), site=site,
                              goal=[GOALS[i % 3]], tactic=[TACTICS[i % 3]], observation_text=text,
                              quote=f"SYNTHETIC fixture quote words {i + 1}")
        records.append(record)
    first = records[0]   # MOVE-7001: the detail case with every display variant
    first["source"]["locations"] = [_location("table", 3, table_index=1, row=2), _location("text", 5),
                                    _location("figure", 7, figure_id="SYN-F1", panel="a")]
    first["effects"] = [
        PF.default_effect(),
        PF.default_effect(target_ref="SYN-QA-OFF-KINASE", target_role="off_target", direction="worsened",
                          direction_basis="text", magnitude_bucket="moderate", comparable=False,
                          comparability_reason="SYNTHETIC different assay", fold_change=None,
                          before={"qualifier": None, "value": None, "unit": None},
                          after={"qualifier": None, "value": None, "unit": None}),
        PF.default_effect(metric="SYN-metric", target_ref=None, target_role="not_applicable", direction="unknown",
                          direction_basis="none", magnitude_bucket="unknown", comparable=False, fold_change=None)]
    first["structure_links"] = [{"basis": "paper_context", "candidates": [], "chain": "A",
                                 "confidence_note": "SYNTHETIC low", "ligand": None, "pdb_id": "0QA1",
                                 "structure_id": "STRUCT-SYN-QA-1"}]
    first["tradeoffs"] = [{"text": "SYNTHETIC tradeoff without quote", "quote": None, "quote_truncated": False,
                           "evidence": None},
                          {"text": "SYNTHETIC tradeoff", "quote": "SYNTHETIC tradeoff quote words",
                           "quote_truncated": True, "evidence": {"synthetic": True}}]
    first["observation"]["quote_truncated"] = True
    first["checks"]["duplicate"] = {"status": "fail", "candidate_ids": [], "effect_conflicts": [{"synthetic": 1}]}
    first["checks"]["chembl_crosscheck"] = {"status": "lookup_failed", "reason": "SYNTHETIC lookup"}
    first["checks"]["quote_in_source"] = {"status": "pass", "quote_assembled": [
        {"path": ["observation", "quote"], "fragment_count": 2, "page": 3}]}
    long_quote = records[8]  # MOVE-7009: 26-word quote, PMID 91000009 has no bibliography row
    long_quote["observation"]["quote"] = " ".join(["SYNTHETIC"] + [f"word{n}" for n in range(25)])
    for record in records:
        PF.rehash(record)
    return records


def p0qa01_flagged() -> list[dict[str, Any]]:
    return [PF.make_move(f"MOVE-{7201 + i}", uniprot=P01, resolution_basis="klifs_name" if i == 0 else "gene",
                         name_as_written="SYN-QA-KINASE-1", variant="SYN-G2C" if i % 2 == 0 else "not_reported",
                         pmid="91000002", site=["gate"], goal=["selectivity"], tactic=["scaffold_hop"],
                         observation_text=f"합성 SYNTHETIC flagged fixture observation {i + 1} of P0QA01.",
                         quote=f"SYNTHETIC flagged quote {i + 1}") for i in range(6)]


def p0qa02_flagged() -> list[dict[str, Any]]:
    return [PF.make_move(f"MOVE-{7301 + i}", uniprot=P02, name_as_written="SYN-QA-KINASE-2", pmid="91000004",
                         site=["front"], goal=["potency"], tactic=["vector_extension"],
                         observation_text=f"합성 SYNTHETIC flagged fixture observation {i + 1} of P0QA02.",
                         quote=f"SYNTHETIC flagged quote P0QA02 {i + 1}") for i in range(3)]


def p0qa04_moves() -> list[dict[str, Any]]:
    return [PF.make_move(f"MOVE-{7101 + i}", uniprot=P04, name_as_written="SYN-QA-KINASE-4", pmid="91000005",
                         observation_text=f"합성 SYNTHETIC fixture observation {i + 1} of P0QA04.") for i in range(2)]


def p0qa04_flagged() -> list[dict[str, Any]]:
    """40 large SYNTHETIC flagged records: P0QA04 with ``moves_flagged`` included is above 1 MiB, without it far below."""
    return [PF.make_move(f"MOVE-{7401 + i}", uniprot=P04, name_as_written="SYN-QA-KINASE-4", pmid="91000005",
                         observation_text=f"SYNTHETIC large flagged observation {i + 1}. {PADDING}",
                         quote=f"SYNTHETIC large flagged quote {i + 1}") for i in range(40)]


def unresolved() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    moves = [PF.make_move("MOVE-7501", uniprot=None, resolution_basis="unmapped", name_as_written="SYN-QA-UNRESOLVED-A",
                          pmid="91000001"),
             PF.make_move("MOVE-7502", uniprot=None, resolution_basis="absent", name_as_written=None, pmid="91000002")]
    ambiguous = PF.make_move("MOVE-7601", uniprot=None, resolution_basis="ambiguous",
                             name_as_written="SYN-QA-UNRESOLVED-B", pmid="91000003")
    ambiguous["target"]["candidates"] = [P01, P02]
    flagged = [PF.rehash(ambiguous),
               PF.make_move("MOVE-7602", uniprot=None, resolution_basis="unmapped",
                            name_as_written="SYN-QA-UNRESOLVED-A", pmid="91000004")]
    return moves, flagged


def qa_records() -> dict[str, list[dict[str, Any]]]:
    loose_moves, loose_flagged = unresolved()
    moves = p0qa01_moves() + p0qa04_moves() + loose_moves
    flagged = p0qa01_flagged() + p0qa02_flagged() + p0qa04_flagged() + loose_flagged
    references = [PF.make_reference("REF-QA-0001", P01), PF.make_reference("REF-QA-0002", P01),
                  PF.make_reference("REF-QA-0003", P02), PF.make_reference("REF-QA-0004", P04)]
    pubmed = [PF.make_pubmed_row("91000001", title="합성 SYNTHETIC QA fixture title 91000001",
                                 doi="10.0000/synthetic.qa1", pmc="PMC0000091", year="2019"),
              PF.make_pubmed_row("91000002", year="2021"),
              PF.make_pubmed_row("91000003", title=f"합성 SYNTHETIC QA fixture title {TITLE_TOKEN}", year="2015"),
              PF.make_pubmed_row("91000004", year="2023"),
              PF.make_pubmed_row("91000005", year="2018"),
              PF.make_pubmed_row("91000006", year=None, journal=None),
              PF.make_pubmed_row("91000007", year="n.d.")]
    return {"moves": moves, "moves_flagged": flagged, "references": references, "pubmed": pubmed}


# ------------------------------------------------------------------------------------------- expectations

def _filter_expectations(items: list[tuple[str, dict[str, Any]]], books: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Counts for the record filters the harness clicks, counted over (file, record) pairs of one target."""
    def count(keep) -> dict[str, Any]:
        kept = sorted(record["move_id"] for file, record in items if keep(file, record))
        return {"total": len(kept), "move_ids": kept}

    def has(axis: str, *terms: str):
        return lambda _file, record: bool(set(terms) & set(record["tags"][axis]))

    def search(token: str):
        needle = token.casefold()

        def keep(_file, record) -> bool:
            texts = [record["move_id"], record["source"]["pmid"], record["target"]["name_as_written"],
                     record["target"]["variant"], record["observation"]["text"], record["observation"]["quote"],
                     record["change"]["description"], record["change"]["from_compound"],
                     record["change"]["to_compound"], *(t["text"] for t in record["tradeoffs"]),
                     *(t["quote"] for t in record["tradeoffs"]),
                     (books.get(record["source"]["pmid"]) or {}).get("title")]
            return any(type(text) is str and needle in text.casefold() for text in texts)
        return keep
    return {
        "all": count(lambda _f, _r: True),
        "file:moves_flagged": count(lambda file, _r: file == "moves_flagged"),
        "site:gate": count(has("site", "gate")),
        "site:gate|back": count(has("site", "gate", "back")),
        "site:gate|back&goal:potency": count(lambda f, r: has("site", "gate", "back")(f, r)
                                             and has("goal", "potency")(f, r)),
        "variant:SYN-A1V": count(lambda _f, r: r["target"]["variant"] == "SYN-A1V"),
        f"q:{SEARCH_TOKEN}": count(search(SEARCH_TOKEN)),
        f"q:{TITLE_TOKEN.lower()}": count(search(TITLE_TOKEN.lower())),
    }


def expectations(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    books = {row["id"]: row["data"] for row in records["pubmed"] if row["status"] == "ok" and row["data"]["pmid"] == row["id"]}
    by_acc: dict[str, dict[str, Any]] = {}
    for file in ("moves", "moves_flagged"):
        for record in records[file]:
            acc = record["target"]["uniprot"]
            if acc is None:
                continue
            entry = by_acc.setdefault(acc, {"moves": 0, "moves_flagged": 0, "items": []})
            entry[file] += 1
            entry["items"].append((file, record))
    refs = Counter(ref["uniprot"] for ref in records["references"])
    accessions = {}
    for acc in sorted(set(by_acc) | set(refs) | {P03}):
        entry = by_acc.get(acc, {"moves": 0, "moves_flagged": 0, "items": []})
        items = entry["items"]
        moves_only = [pair for pair in items if pair[0] == "moves"]
        accessions[acc] = {
            "moves": entry["moves"], "moves_flagged": entry["moves_flagged"], "references": refs.get(acc, 0),
            "variants_moves": dict(sorted(Counter(r["target"]["variant"] for _f, r in moves_only).items())),
            "variants_all": dict(sorted(Counter(r["target"]["variant"] for _f, r in items).items())),
            "filters": {"include_flagged_false": _filter_expectations(moves_only, books),
                        "include_flagged_true": _filter_expectations(items, books)}}
    unresolved_moves = sum(1 for r in records["moves"] if r["target"]["uniprot"] is None)
    unresolved_flagged = sum(1 for r in records["moves_flagged"] if r["target"]["uniprot"] is None)
    names = {r["target"]["name_as_written"] for file in ("moves", "moves_flagged") for r in records[file]
             if r["target"]["uniprot"] is None}
    return {"label": LABEL, "accessions": accessions, "searchToken": SEARCH_TOKEN, "titleToken": TITLE_TOKEN,
            "unresolved": {"moves": unresolved_moves, "moves_flagged": unresolved_flagged, "names_total": len(names)},
            "bibliographyPmids": sorted(books), "files": {"moves": len(records["moves"]),
                                                           "moves_flagged": len(records["moves_flagged"]),
                                                           "references": len(records["references"])}}


# ------------------------------------------------------------------------------------------- derived maps

def derive_content(source: dict[str, Any], plan: dict[str, list[str]], label: str) -> dict[str, Any]:
    """A copy of a real M15 map with the accessions of ``plan`` on each chain's mapped rows."""
    content = copy.deepcopy(source)
    names = [chain["chain_auth"] for chain in content["chains"]]
    if sorted(plan) != sorted(names):
        raise SystemExit(f"derive plan chains {sorted(plan)} differ from the map chains {names}")
    for chain in content["chains"]:
        accessions = plan[chain["chain_auth"]]
        mapped = [row for row in content["rows"]
                  if row["residue"]["chain_auth"] == chain["chain_auth"] and row["status"] == "mapped"]
        if len(mapped) < len(accessions):
            raise SystemExit(f"chain {chain['chain_auth']} has too few mapped rows for {accessions}")
        cut = len(mapped) // len(accessions)
        for i, row in enumerate(mapped):
            row["uniprot_accession"] = accessions[min(i // cut, len(accessions) - 1)]
        if chain.get("requested_uniprot_accession") is not None:
            chain["requested_uniprot_accession"] = accessions[0]
    content["qa_fixture"] = label
    return content


def derive(runs: Path, run_id: str, source_handle: str, stage: str) -> dict[str, Any]:
    from mw.core.handles import ObjectStore

    store = ObjectStore(runs / run_id, run_id)
    try:
        meta = store.meta(source_handle)
        if (meta["kind"], meta["schema"]) != ("residue_numbering_map", "residue_numbering_map@1"):
            raise SystemExit(f"{source_handle} is not a residue_numbering_map")
        if meta.get("produced_by") == "synthetic_fixture":
            raise SystemExit("the source must be a map the M15 tool made, not a derived one")
        source = store.load(source_handle)
        made = {}
        for name, plan in DERIVED[stage].items():
            content = derive_content(source, plan, f"{DERIVED_LABEL[stage]} [{name}]")
            handle = store.put("residue_numbering_map", "residue_numbering_map@1", content,
                               produced_by="synthetic_fixture", summary={"qa_fixture": name},
                               null_result=content["null_result"])
            made[name] = {"handle": handle.handle, "chains": plan, "label": DERIVED_LABEL[stage]}
        return {"source": source_handle, "maps": made}
    finally:
        store.db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("set", help="write the SYNTHETIC precedent set")
    one.add_argument("--root", required=True, help="precedent reference folder (MW_PRECEDENT_REFERENCE_DIR)")
    one.add_argument("--imported-at", default=IMPORTED_AT, help="UTC YYYY-MM-DDTHH:MM:SSZ (another set hash)")
    one.add_argument("--no-activate", action="store_true", help="write the set without changing active.json")
    two = sub.add_parser("derive", help="store the SYNTHETIC derived numbering maps of one real M15 map")
    two.add_argument("--runs", required=True)
    two.add_argument("--run", required=True)
    two.add_argument("--source", required=True)
    two.add_argument("--stage", choices=sorted(DERIVED), required=True)
    args = parser.parse_args()
    if args.command == "derive":
        print(json.dumps(derive(Path(args.runs), args.run, args.source, args.stage)))
        return 0
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    records = qa_records()
    set_hash = PF.build_set(root, moves=records["moves"], moves_flagged=records["moves_flagged"],
                            references=records["references"], pubmed=records["pubmed"], imported_at=args.imported_at,
                            activate_set=not args.no_activate)
    for name in ("moves", "moves_flagged"):
        for record in records[name]:
            K.validate_move(record)
    print(json.dumps({"set_hash": set_hash, "imported_at": args.imported_at, "label": LABEL,
                      "rows": {name: len(items) for name, items in records.items()},
                      "expect": expectations(records)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
