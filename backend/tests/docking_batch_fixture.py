"""Shared M19 batch docking world for the read API and report tests (real M17 jobs, real batch jobs).

Every summary here is real product output: chemical imports -> real M17 inspect/enumerate jobs -> ``JobQueue``
``qvina_batch_dock_v1`` jobs with the pinned batch worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env``; a
missing environment FAILS, never skips). Inputs: the public prepared docking example receptor (``fixtures/chemical``,
not experimental validation), the public-derived parent SDF and the labeled synthetic building blocks (see
``fixtures/docking/SYNTHETIC-PROVENANCE.md``). Small manual boxes and exhaustiveness 1 keep the rows short; engine
values are only compared with the stored per-row results, never used as an oracle. The partial batch is a real user
cancel sent through the queue's own cancel path when row 2 starts (an internal test hook on ``_record_control``,
never a request field).
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import docking_constants as C
from mw.jobs.queue import JobQueue
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired, Run

CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
EXPECTED = json.loads((FIX / "expected.json").read_text())
BATCH_FIXTURE = json.loads((FIX / "m19-batch-input.json").read_text())
ENUM = json.loads((FIX / "m17-enumerate-result-record0-nmethyl.json").read_text())
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
PLANAR = (FIX / "synthetic-ligand-planar-z0.sdf").read_bytes()
BLOCKS = (FIX / "synthetic-docking-blocks.smi").read_bytes()
IDS = [row["id"] for row in ENUM["candidates"]]
CENTER = EXPECTED["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
FAST = {"seed": 1, "exhaustiveness": 1, "num_modes": 2}
CORE = {"seed": 1, "exhaustiveness": 1, "num_modes": 2, "conformers": 2}
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
RID = "run_m19_batch_reads"
PROTOCOL = "qvina_batch_dock_v1"


def args_for(world: dict, ids: list[str], *, mode: str = "free", include_parent: bool = False,
             params: dict | None = None, parent: str | None = None) -> dict:
    return {"receptor_handle": world["receptor"], "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "candidate_set_handle": world["candidate_set"], "parent_sdf_handle": parent or world["parent"],
            "candidate_ids": ids, "include_parent": include_parent, "mode": mode, "box": SMALL_BOX,
            "parameters": params or FAST, "acknowledgement": ACK}


def raise_limits(run: Run, calls: int = 40, wall: float = 7200) -> None:
    run.update_limits(BudgetLimits(expensive_calls=calls, wall_clock_s=wall), by="test")


def _start(queue: JobQueue, job_id: str) -> dict:
    try:
        return queue.start(job_id)
    except ApprovalRequired:
        queue.run.approve("expensive_first_call", by="test")
        return queue.start(job_id)


def batch(run: Run, args: dict, timeout_s: float = 1200) -> dict:
    queue = JobQueue(run)
    job = queue.submit(PROTOCOL, args, timeout_s=timeout_s)
    return job if job["status"] != "queued" else _start(queue, job["job_id"])


def summary_handle(run: Run, job: dict) -> str:
    published = [e for e in run.events.read() if e["type"] == "docking_batch_published" and
                 e.get("job_id") == job["job_id"]]
    assert len(published) == 1, published
    return published[0]["summary_handle"]


def _cancel_when_row_starts(index: int):
    """Wrap _record_control: on STARTED, a thread waits for rows/<index>.started, then requests the cancel."""
    original = JobQueue._record_control

    def record(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            marker = self.run.run_dir / "jobs" / job_id / attempt_id / "rows" / f"{index}.started"

            def watch() -> None:
                end = time.monotonic() + 300
                while time.monotonic() < end and not marker.exists():
                    time.sleep(0.02)
                if marker.exists():
                    self.request_cancel(job_id)
            threading.Thread(target=watch, daemon=True).start()
        return done

    return record


def reopen(root: Path) -> Run:
    """Events-only reopen of the run under ``root`` (same handles, no staged files)."""
    run = new_ligand_run(root, RID)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    return run


def build_world(root: Path, monkeypatch_context) -> dict[str, Any]:
    """M17 candidate set + four batches: free complete with the parent row, free partial (user cancel at row 2,
    with the parent row), core-fixed complete, and an all-reused (N = 0) batch. Returns handles and job ids."""
    run = new_ligand_run(root, RID)
    world: dict[str, Any] = {"root": root, "rid": RID}
    world["receptor"] = import_file(run, "receptor", "rec.pdb", REC)
    world["parent"] = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    world["planar"] = import_file(run, "ligand_sdf", "planar.sdf", PLANAR)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": world["parent"], "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    world["candidate_set"] = enumerated["output_handles"][0]
    assert [row["id"] for row in run.store.load(world["candidate_set"])["candidates"]] == IDS
    world["base_root"] = root.parent / f"{root.name}_m17_only"   # events of the M17-only prefix (no batch yet)
    (world["base_root"] / RID).mkdir(parents=True)
    shutil.copyfile(root / RID / "events.jsonl", world["base_root"] / RID / "events.jsonl")
    raise_limits(run)
    jobs, handles = {}, {}
    plans = {"free": args_for(world, [IDS[1], IDS[0]], include_parent=True),
             "core": args_for(world, [IDS[0], IDS[1]], mode="core_fixed", params=CORE),
             "reused": args_for(world, [IDS[0]])}
    for name in ("free", "core", "reused"):
        jobs[name] = batch(run, plans[name])
        assert jobs[name]["status"] == "done", jobs[name]
        handles[name] = summary_handle(run, jobs[name])
    plans["partial"] = args_for(world, IDS, include_parent=True, params={**FAST, "seed": 2})
    with monkeypatch_context() as patch:
        patch.setattr(JobQueue, "_record_control", _cancel_when_row_starts(2))
        jobs["partial"] = batch(run, plans["partial"])
    assert jobs["partial"]["status"] == "cancelled", jobs["partial"]
    handles["partial"] = summary_handle(run, jobs["partial"])
    world.update(jobs=jobs, handles=handles, args=plans,
                 stored={name: run.store.load(handle) for name, handle in handles.items()})
    assert world["stored"]["partial"]["status"] == "partial"
    assert [row["state"] for row in world["stored"]["partial"]["rows"]][2:] == ["cancelled", "not_run"]
    assert world["stored"]["free"]["status"] == world["stored"]["core"]["status"] == "complete"
    return world
