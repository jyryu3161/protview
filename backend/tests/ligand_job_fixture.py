"""Shared M17 job helpers: real ligand jobs through ``JobQueue`` (Python API, no HTTP).

Inputs are the labeled synthetic fixtures in ``fixtures/ligand`` (see SYNTHETIC-PROVENANCE.md). Jobs run the
pinned RDKit worker through the guardian; when the environment is missing these helpers fail (never skip).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mw.chemical_inputs import import_raw
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import ApprovalRequired, Run
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures/ligand"
EXPECTED = json.loads((FIX / "expected.json").read_text())
RULES = json.loads((FIX / "synthetic-reaction-rules.json").read_text())["rules"]
NO_H = (FIX / "synthetic-parent-methacetin-no-h.sdf").read_bytes()
EXPLICIT_H = (FIX / "synthetic-parent-methacetin-explicit-h.sdf").read_bytes()
SMI = (FIX / "synthetic-blocks.smi").read_bytes()
SDF = (FIX / "synthetic-blocks.sdf").read_bytes()
VALID_RULE_IDS = ["user_1", "user_2", "user_3", "user_10"]


def new_ligand_run(root: Path, run_id: str, *, dry_run: bool = False) -> Run:
    return new_run(root, run_id=run_id, dry_run=dry_run)


def import_file(run: Run, kind: str, filename: str, raw: bytes) -> str:
    with run._owner(), run._transition():
        run.store.rebuild_from_events()
        return import_raw(run.store, kind, filename, raw)["handle"]


def run_job(run: Run, protocol: str, args: dict[str, Any], *, timeout_s: float = 120,
            queue: JobQueue | None = None) -> dict[str, Any]:
    queue = queue or JobQueue(run)
    job = queue.submit(protocol, args, timeout_s=timeout_s)
    if job["status"] != "queued":
        return job
    try:
        return queue.start(job["job_id"])
    except ApprovalRequired:
        run.approve("expensive_first_call", by="test")
        return queue.start(job["job_id"])


def standard_run(root: Path, run_id: str) -> dict[str, Any]:
    """Methacetin (no H) + both block libraries + all ten oracle rules; inspect, then enumerate the methoxy site."""
    run = new_ligand_run(root, run_id)
    parent = import_file(run, "ligand_sdf", "parent.sdf", NO_H)
    smiles = import_file(run, "building_blocks_smiles", "blocks.smi", SMI)
    sdf = import_file(run, "building_blocks_sdf", "blocks.sdf", SDF)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [smiles, sdf],
                                                  "rules": RULES})
    assert inspected["status"] == "done", inspected
    inspection = inspected["output_handles"][0]
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspection, "site_atoms": [11, 12],
                                                     "use_fixed": True, "rule_ids": VALID_RULE_IDS})
    assert enumerated["status"] == "done", enumerated
    return {"run": run, "parent": parent, "smiles": smiles, "sdf": sdf, "inspect_job": inspected,
            "inspection": inspection, "enumerate_job": enumerated, "candidate_set": enumerated["output_handles"][0]}


def events(run: Run) -> list[dict[str, Any]]:
    return list(run.events.read())
