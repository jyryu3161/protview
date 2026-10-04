"""Shared M22 T5 world for the GA read API and report tests: real product output only.

Real M17 jobs make the ten-candidate pool (labeled synthetic blocks, ``fixtures/ligand_ga/SYNTHETIC-PROVENANCE.md``),
then two real GA jobs run through ``JobQueue`` with the pinned GA worker and the real ``qvina2`` (a missing environment
FAILS, never skips): a ``partial`` GA that stops at ``docking_limit`` (G1, G2) and a ``complete`` GA that reuses the
partial GA's stored results (G1, G3). Paths are checked against the independent oracle of T1
(``fixtures/ligand_ga/independent_ga_oracle.py``), never against product code. The helpers are the T4 job-test ones.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ligand_job_fixture import import_file, new_ligand_run, run_job
from test_ligand_ga_jobs import (
    BLOCKS,
    GA,
    IDS,
    PARENT,
    REC,
    RID,
    evaluated,
    ga_args,
    oracle_path,
    path,
    raise_limits,
    run_ga,
    summary,
)

PARTIAL_GA = {**GA, "seed": 3, "max_new_dockings": 4}   # reserved_units = min(4, 4 + 1 x 2) = 4 -> docking_limit


def build_world(root: Path) -> dict[str, Any]:
    run = new_ligand_run(root, RID)
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    parent = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    candidate_set = enumerated["output_handles"][0]
    assert [row["id"] for row in run.store.load(candidate_set)["candidates"]] == IDS
    base = {"receptor": receptor, "parent": parent, "candidate_set": candidate_set}
    # The M17-only prefix (no GA yet), for preflight cases on an unused pool.
    base_root = root.parent / "base"
    (base_root / RID).mkdir(parents=True)
    shutil.copyfile(root / RID / "events.jsonl", base_root / RID / "events.jsonl")
    raise_limits(run)
    expected_partial = oracle_path(PARTIAL_GA)
    assert expected_partial["stop_reason"] == "docking_limit"
    partial_job = run_ga(run, ga_args(base, **PARTIAL_GA))
    assert partial_job["status"] == "done", partial_job
    partial_handle, partial = summary(run, partial_job)
    assert path(partial) == path(expected_partial)
    assert (partial["status"], partial["stop_reason"], partial["limitations"]) == ("partial", "docking_limit",
                                                                                ["G1", "G2"])
    reused = {entry["candidate_id"] for entry in evaluated(partial)}
    expected_complete = oracle_path(GA, reusable=reused)
    complete_job = run_ga(run, ga_args(base))
    assert complete_job["status"] == "done", complete_job
    complete_handle, complete = summary(run, complete_job)
    assert path(complete) == path(expected_complete)
    assert (complete["status"], complete["stop_reason"]) == ("complete", expected_complete["stop_reason"])
    assert complete["reused_count"] >= 1 and complete["limitations"] == ["G1", "G3"]
    return {"root": root, "base_root": base_root, **base,
            "args": {"partial": ga_args(base, **PARTIAL_GA), "complete": ga_args(base)},
            "jobs": {"partial": partial_job, "complete": complete_job},
            "handles": {"partial": partial_handle, "complete": complete_handle},
            "stored": {"partial": partial, "complete": complete}}


def reopen(root: Path):
    """Events-only reopen of a copied runs root (the store is rebuilt from the event log)."""
    run = new_ligand_run(root, RID)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    return run
