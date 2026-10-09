"""Builder (M26 T9b) of the LABELLED SYNTHETIC reaction reference set of the M26 offscreen acceptance (fixture stage).

``scripts/m26_offscreen_acceptance.py`` runs this file as a subprocess (the runner never imports ``mw``); it writes one
set into ``--root`` with ``reaction_fixture.build_set`` (the importer's layout: ``active.json`` +
``sets/<hash>/manifest.json`` + ``files/…``) and prints ``{"set_hash", "imported_at", "rows"}`` as one JSON line.

Rows (every value is made up; see SYNTHETIC-PROVENANCE-t9.md):

* M-CSA: the T2 rows (``../t2/mcsa_entries.json``: 0SY1–0SY3), the T6 rows (``../t6/mcsa_entries_0sy6.json``: 0SY6) and
  the T9 rows (``mcsa_entries_t9.json``: 0T91 and the 60-residue 0T92 list), in ``mcsa_id`` order.
* UniProt: the T2 rows and the T9 stand-in row for O14965 (``uniprot_entries_t9.json``), in accession order.
* Rhea: the T2 rows. Skipped accessions and the request log are ``reaction_fixture``'s synthetic defaults.

``--imported-at`` makes a second set of the same rows with another set hash (the "이전 스냅샷 기준" case);
``--no-activate`` leaves ``active.json`` as it is. No network; not product code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[2]
for extra in (str(TESTS.parent), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import reaction_fixture as RF

from mw import reaction_knowledge_constants as K

T6 = HERE.parent / "t6"


def qa_rows() -> dict[str, list[dict]]:
    """The fixture-stage rows per source, each in its fixed order."""
    rows = RF.synthetic_rows()
    mcsa = rows["mcsa"] + json.loads((T6 / "mcsa_entries_0sy6.json").read_text(encoding="utf-8"))
    mcsa += json.loads((HERE / "mcsa_entries_t9.json").read_text(encoding="utf-8"))
    uniprot = rows["uniprot_function"] + json.loads((HERE / "uniprot_entries_t9.json").read_text(encoding="utf-8"))
    return {"mcsa": sorted(mcsa, key=lambda row: K.row_sort_key("mcsa", row)),
            "uniprot_function": sorted(uniprot, key=lambda row: K.row_sort_key("uniprot_function", row)),
            "rhea": sorted(rows["rhea"], key=lambda row: K.row_sort_key("rhea", row))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", required=True, help="reaction reference folder (MW_REACTION_REFERENCE_DIR)")
    parser.add_argument("--imported-at", default=RF.IMPORTED_AT, help="UTC YYYY-MM-DDTHH:MM:SSZ (another set hash)")
    parser.add_argument("--no-activate", action="store_true", help="write the set without changing active.json")
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    rows = qa_rows()
    set_hash = RF.build_set(root, rows=rows, imported_at=args.imported_at, activate_set=not args.no_activate)
    print(json.dumps({"set_hash": set_hash, "imported_at": args.imported_at,
                      "rows": {source: len(items) for source, items in rows.items()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
