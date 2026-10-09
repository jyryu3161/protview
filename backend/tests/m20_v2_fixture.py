"""Test utility (M26 T6b): M20 v2 candidate sets of public 1UBQ for the consumer tests (M21, M23, M24, M25).

* ``activate_ubq(root, patch)``: a LABELLED SYNTHETIC reaction reference set in the importer's layout
  (``reaction_fixture.build_set``, through the T6a helper's cache reset) whose only M-CSA entry
  (``fixtures/reaction/t6/mcsa_entries_0sy8.json``, see ``SYNTHETIC-PROVENANCE-t6b.md``) names the made-up PDB ID
  ``0SY8`` for chain A of public 1UBQ: A6 Lys and A68 His ``matched``, A76 listed as Ala (``conflict``
  ``residue_name_differs``), A300 (``unmatched`` ``residue_not_in_structure``). Ubiquitin is not an M-CSA entry and
  nothing here is a real M-CSA response; "matched" only means the made-up row and the structure name agree.
* ``make_sets(run, prepared)``: the two v2 sets of the TINY positions of ``fixtures/sequence_ga`` (I3 user-protected,
  K6, I44, G76; allowed residues ``AW``) built by the product tools through ``Run.call``: ``not_checked`` (no catalytic
  annotation) and ``checked`` (``link_reaction_knowledge`` of 0SY8 chain A as the annotation: K6 is protected by
  ``catalytic_residue``, G76 stays a position with candidates).
* ``stored(name)`` / ``put_stored(root, name)``: the committed copies ``fixtures/reaction/t6/m20-candidate-set-v2-1ubq-
  {not_checked,checked}.json`` ({handle, content}), made once by ``make_sets`` in run ``RUN_ID`` (path-loaded public
  1UBQ, default preparation; ``fixtures/reaction/t6/build_v2_fixtures.py``). ``put_stored`` rebuilds that run's
  structure the same way and puts the stored content with ``store.put`` (no M20 tool call), so a test reads a stored
  v2 set exactly as a later code version would.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import m20_catalytic_fixture as CF
import reaction_fixture as RF

from mw import reaction_knowledge_constants as RK
from mw.workspace import new_run

TESTS = Path(__file__).resolve().parent
FIX = TESTS / "fixtures"
T6 = FIX / "reaction" / "t6"
UBQ = FIX / "public_1ubq.cif"
PDB_ID = "0SY8"                   # made up (no real PDB ID starts with 0); named by the test as a person would
RUN_ID = "run_m26_t6b_v2"
SET_KIND, SET_SCHEMA = "mutation_candidate_set", "mutation_candidate_set@1"
V2 = "mw.mutation_candidates/v2"
NAMES = ("not_checked", "checked")


def res(seq_auth: int, resname: str) -> dict[str, Any]:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq_auth, "icode": "", "resname": resname}


# The TINY positions of fixtures/sequence_ga (sequence_ga_fixture.SETS["tiny"]).
TINY_ARGS = {"sources": {"pocket": None, "ligand_shell": None,
                         "residues": [res(3, "ILE"), res(6, "LYS"), res(44, "ILE"), res(76, "GLY")]},
             "protected_residues": [res(3, "ILE")], "allowed_residues": "AW"}


def mcsa_rows() -> list[dict[str, Any]]:
    return json.loads((T6 / "mcsa_entries_0sy8.json").read_text(encoding="utf-8"))


def activate_ubq(root: Path, patch: Any) -> str:
    """Point ``MW_REACTION_REFERENCE_DIR`` (``patch.setenv``) at ``root`` and install the 0SY8 set there."""
    (Path(root) / "sets").mkdir(parents=True, exist_ok=True)
    patch.setenv(RK.ENV_VAR, str(root))
    CF.reset_caches()
    rows = RF.synthetic_rows()
    rows["mcsa"] = mcsa_rows()
    return RF.build_set(root, rows=rows)


def link_ubq(run: Any, prepared: str) -> str:
    """The ``reaction_knowledge@1`` of 0SY8 chain A on ``prepared`` (the product tool through ``Run.call``)."""
    return CF.link(run, prepared, ["A"], pdb_id=PDB_ID)


def make_sets(run: Any, prepared: str, knowledge: str) -> dict[str, str]:
    """{name: handle} of the two v2 TINY sets, built by the product M20 tool."""
    return {"not_checked": run.call("generate_mutation_candidates", {"structure": prepared, **TINY_ARGS}).handle,
            "checked": run.call("generate_mutation_candidates", {"structure": prepared, **TINY_ARGS,
                                                                 "catalytic_annotation": knowledge}).handle}


def load_prepare(run: Any) -> str:
    loaded = run.call("load_structure", {"source": str(UBQ), "model_index": 0}).handle
    return run.call("prepare_structure", {"structure": loaded}).handle


def fixture_path(name: str) -> Path:
    return T6 / f"m20-candidate-set-v2-1ubq-{name}.json"


def stored(name: str) -> dict[str, Any]:
    """{handle, content} of a committed stored v2 set."""
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def put_stored(run: Any, name: str) -> str:
    """Put a stored v2 set into ``run`` (its id must be ``RUN_ID``, its 1UBQ already loaded and prepared)."""
    fixture = stored(name)
    assert run.run_id == RUN_ID, run.run_id
    handle = run.store.put(SET_KIND, SET_SCHEMA, fixture["content"]).handle
    assert handle == fixture["handle"], (handle, fixture["handle"])
    return handle


def stored_world(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """A run of id ``RUN_ID`` under ``root`` with path-loaded, default-prepared 1UBQ and both stored v2 sets."""
    run = new_run(root, run_id=RUN_ID, dry_run=dry_run)
    prepared = load_prepare(run)
    assert all(stored(name)["content"]["structure"]["handle"] == prepared for name in NAMES)
    return {"run": run, "root": root, "run_id": RUN_ID, "prepared": prepared,
            **{name: put_stored(run, name) for name in NAMES}}
