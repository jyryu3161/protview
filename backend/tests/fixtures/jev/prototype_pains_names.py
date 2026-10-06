"""PROTOTYPE (M24 T1 measurement only, never product code): do all RDKit PAINS entry names fit the spec 3 wire rule?

Run with the pinned M17 RDKit interpreter (``.deps/prolif/venv-locked/bin/python``); imports RDKit only (no ``mw``).
The M17 worker stores ``{"catalog": "PAINS_A|B|C", "name": FilterCatalogEntry.GetDescription()}`` per match, so the
set of names a stored row can hold is exactly the catalog descriptions printed here.
"""
from __future__ import annotations

import json
import re
import sys

from rdkit import rdBase
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

NAME_RE = re.compile(r"[A-Za-z0-9_().\-]{1,64}")
CATALOGS = (("PAINS_A", FilterCatalogParams.FilterCatalogs.PAINS_A),
            ("PAINS_B", FilterCatalogParams.FilterCatalogs.PAINS_B),
            ("PAINS_C", FilterCatalogParams.FilterCatalogs.PAINS_C))


def main() -> int:
    report: dict[str, object] = {"rdkit_version": rdBase.rdkitVersion, "catalogs": {}}
    failing: list[list[str]] = []
    longest = ("", "")
    for name, which in CATALOGS:
        params = FilterCatalogParams()
        params.AddCatalog(which)
        catalog = FilterCatalog(params)
        names = [catalog.GetEntryWithIdx(i).GetDescription() for i in range(catalog.GetNumEntries())]
        report["catalogs"][name] = {"entries": len(names), "distinct_names": len(set(names))}
        for entry in names:
            if not NAME_RE.fullmatch(entry):
                failing.append([name, entry])
            if len(entry) > len(longest[1]):
                longest = (name, entry)
    report["names_failing_wire_rule"] = failing
    report["longest_name"] = {"catalog": longest[0], "name": longest[1], "chars": len(longest[1])}
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
