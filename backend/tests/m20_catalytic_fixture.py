"""Test utility (M26 T6): a LABELLED SYNTHETIC reaction reference set for the M20 v2 catalytic protection tests.

The set names the M20 synthetic fixture (``fixtures/mutation/synthetic-mutation-fixture.cif``, chains A, B, CC) as the
made-up PDB ID ``0SY6``. Its M-CSA rows are ``fixtures/reaction/t6/mcsa_entries_0sy6.json`` (see
``SYNTHETIC-PROVENANCE-t6.md``); the UniProt and Rhea rows are the T2 synthetic ones. The set is written with
``reaction_fixture.build_set`` (the importer's layout) under a temporary ``MW_REACTION_REFERENCE_DIR``; results come
from the product tool ``link_reaction_knowledge`` through ``Run.call``. Nothing here is a real M-CSA response.

What the 0SY6 rows give on that structure (``link_reaction_knowledge`` on the prepared structure, chains A and B):

* chain A ``covered``: matched 601/0 HID A6, 601/1 ASP A26, 601/6 CYS A5, 601/7 ALA A2, 602/0 HID A6, 602/1 HIS A27;
  conflict 601/2 MSE A9 (``residue_name_differs``); unmatched 601/3 (A10 and A10A: ``ambiguous_residue_number``),
  601/4 (A99: ``residue_not_in_structure``), 601/5 (``no_author_number``), 601/11 (code X: ``non_standard_code``).
* chain B ``covered``: matched 601/8 HID B6, 601/9 ALA B2, 602/2 VAL B7; conflict 601/10 (Asn/Asp:
  ``mcsa_rows_disagree``).
* chain CC: no row (``chain_not_listed`` when the request names it).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import reaction_fixture as RF

from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as K
from mw import reaction_snapshots as rs

T6 = Path(__file__).resolve().parent / "fixtures" / "reaction" / "t6"
PDB_ID = "0SY6"
OTHER_PDB_ID = "0SY7"          # made up too, and in no row of the set (``pdb_not_in_snapshot``)
TOOL = K.TOOL


def mcsa_rows(long_unmatched: int = 0) -> list[dict[str, Any]]:
    """The 0SY6 rows; ``long_unmatched`` adds entry 603 with that many chain-A residues at numbers 1000.. that the
    structure does not have (each one ``unmatched`` / ``residue_not_in_structure``), for the list cap."""
    rows = json.loads((T6 / "mcsa_entries_0sy6.json").read_text(encoding="utf-8"))
    if long_unmatched:
        template = rows[0]["residues"][4]   # 601/4: A99, not in the structure
        residues = []
        for i in range(long_unmatched):
            residue = copy.deepcopy(template)
            residue["residue_chains"][0].update(resid=1000 + i, auth_resid=1000 + i)
            residue["roles_summary"] = f"SYNTHETIC fixture roles summary 603-{i} (not in structure)"
            residues.append(residue)
        rows.append({"mcsa_id": 603, "enzyme_name": "SYNTHETIC fixture enzyme t6 long", "reference_uniprot_id": "Q0SYN5",
                     "all_ecs": ["9.99.6.3"], "reaction": {"ec": None, "compounds": []}, "residues": residues})
    return rows


def reset_caches() -> None:
    rs._VERIFIED.clear()
    rk.clear_index_cache()


def activate(root: Path, patch: Any, *, long_unmatched: int = 0, imported_at: str = RF.IMPORTED_AT) -> str:
    """Point ``MW_REACTION_REFERENCE_DIR`` (through ``patch.setenv``) at ``root`` and install the 0SY6 set there."""
    (Path(root) / "sets").mkdir(parents=True, exist_ok=True)
    patch.setenv(K.ENV_VAR, str(root))
    reset_caches()
    rows = RF.synthetic_rows()
    rows["mcsa"] = mcsa_rows(long_unmatched)
    return RF.build_set(root, rows=rows, imported_at=imported_at)


def link(run: Any, structure: str, chains: list[str], *, pdb_id: str | None = PDB_ID,
         accessions: dict[str, str] | None = None, numbering_map: str | None = None) -> str:
    """A ``reaction_knowledge@1`` result of ``structure`` through the product tool path (``Run.call``)."""
    accessions = accessions or {}
    return run.call(TOOL, {"structure": structure, "pdb_id": pdb_id,
                           "chains": [{"chain_auth": c, "uniprot_accession": accessions.get(c)} for c in chains],
                           "numbering_map": numbering_map}).handle
