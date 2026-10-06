"""PROTOTYPE (M24 T1 measurement only): where each spec 3 wire field comes from in the STORED M17 / M20 objects.

Reads committed real product outputs (no job is run): ``../ligand_ga/m17-candidate-set-small-pool.json`` (a real
``ligand_candidate_set@1`` content from unmodified M17 jobs) and ``../sequence_ga/m20-candidate-set-1ubq-8pos.json``
(a real ``mutation_candidate_set@1``), plus the validators' closed key sets in ``mw.ligand_bundle`` /
``mw.mutation_candidates`` (the shapes every stored object must have). Prints one JSON report with the observed key
sets, sample closed values and the spec-name -> stored-path map. No network, nothing written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mw import ligand_bundle as lb
from mw import ligand_constants as lc
from mw import mutation_candidates as mc
from mw import mutation_constants as mk

FIX = HERE.parent


def main() -> int:
    ligand = json.loads((FIX / "ligand_ga/m17-candidate-set-small-pool.json").read_text(encoding="utf-8"))
    mutation = json.loads((FIX / "sequence_ga/m20-candidate-set-1ubq-8pos.json").read_text(encoding="utf-8"))["content"]
    mc.validated_set(mutation)
    row = ligand["candidates"][0]
    position = mutation["positions"][0]
    report: dict[str, Any] = {
        "m17_set_keys_stored": sorted(ligand), "m17_set_keys_validator": sorted(lb.SET_KEYS),
        "m17_row_keys_stored": sorted(row), "m17_row_keys_validator": sorted(lb.ROW_KEYS),
        "m17_inspection_keys_validator": sorted(lb.INSPECTION_KEYS),
        "m17_inspection_parent_keys_validator": sorted(lb.PARENT_KEYS),
        "m17_origin_keys": sorted(row["origins"][0]), "m17_pains_keys": sorted(row["pains"]),
        "m17_pains_match_keys_validator": ["catalog", "name"], "m17_pains_catalogs": list(lb.PAINS_CATALOGS),
        "m17_property_names": list(lc.PROPERTY_NAMES), "m17_stereo_flags": list(lc.STEREO_FLAGS),
        "m17_rule_ids": {"fixed": lc.FIXED_RULE_ID, "fixed_method": lc.FIXED_METHOD,
                         "user_method": lc.USER_RULE_METHOD, "user_prefix": lc.USER_RULE_PREFIX},
        "m17_property_methods_stored": ligand["property_methods"],
        "m17_rules_used_stored": ligand["rules_used"], "m17_methods_stored": ligand["methods"],
        "m17_row_has_generation_order_field": "generation_order" in row,
        "m17_ids_in_string_order": [r["id"] for r in ligand["candidates"]] == sorted(r["id"] for r in
                                                                                    ligand["candidates"]),
        "m20_top_keys_stored": sorted(mutation), "m20_position_keys_stored": sorted(position),
        "m20_protection_keys_stored": sorted(position["protection"]),
        "m20_residue_keys_stored": sorted(position["residue"]),
        "m20_source_items_stored": [p["sources"] for p in mutation["positions"][:2]],
        "m20_source_kinds": list(mk.SOURCE_KINDS),
        "m20_protection_checks_stored": mutation["protection_checks"],
        "m20_protection_check_statuses": [mk.CHECKED, mk.NOT_CHECKED, mk.NOT_AVAILABLE],
        "m20_pockets_stored": mutation["pockets"],
        "m20_candidate_keys_stored": sorted(mutation["candidates"][0]),
        "m20_candidates_in_index_order": [c["index"] for c in mutation["candidates"]] ==
        list(range(len(mutation["candidates"]))),
        "m20_numbering_and_klifs_fields_present_on_position": {"numbering": position["numbering"],
                                                               "klifs_sites": position["protection"]["klifs_sites"]},
    }
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
