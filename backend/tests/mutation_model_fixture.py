"""Shared M21 test world for the read API and report tests (built once per test session).

The model is made by the product path with the REAL worker (``mw/jobs/openmm_mutation_worker.py``: OpenMM 8.6.0,
PDBFixer 1.12.0, FreeSASA 2.2.1): upload public 1UBQ (public structure, not experimentally validated here) ->
``load_structure`` -> ``prepare_structure`` -> ``generate_mutation_candidates`` (I44) -> POST /jobs (I44W) -> approve
-> start. It FAILS, never skips, when an engine is missing.

A second run ("other") receives the SAME genuine worker output through a LABELED SIMULATED GUARDIAN (no process is
launched; the bytes are the real worker's ``result.json``), so its model passes the same publication checks and is a
real, validated ``mutation_model@1`` of another run. The first run also gets one M20 ``mutation_candidates`` report
before any M21 report, so the tests can show existing report bytes stay unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mw import mutation_model_constants as K
from mw.api import app as api_module
from mw.jobs import process_identity
from mw.jobs.queue import JobQueue

FIX = Path(__file__).parent / "fixtures"
UBQ = (FIX / "public_1ubq.cif").read_bytes()
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
ORDER = "ACDEFGHKLMNPQRSTVWY"     # M20 candidate order for I44 (19 candidates, I excluded)
TRP = ORDER.index("W")
SEED = 20261004
SIDES = ("wild_type_reference", "mutant")

_CACHE: dict[str, Any] = {}


def client_for(root: Path) -> TestClient:
    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _command(client: TestClient, rid: str, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _world(client: TestClient, label: str) -> dict:
    created = client.post("/runs", json={"goal": label})
    assert created.status_code == 201, created.text
    rid = created.json()["run_id"]
    uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": "public_1ubq.cif"}, content=UBQ)
    assert uploaded.status_code in (200, 201), uploaded.text
    source = _command(client, rid, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
    prepared = _command(client, rid, "prepare_structure", {
        "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    candidate_set = _command(client, rid, "generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}})
    return {"rid": rid, "structure": prepared, "candidate_set": candidate_set}


def _job(client: TestClient, rid: str, candidate_set: str) -> dict:
    args = {"candidate_set": candidate_set, "candidate_index": TRP, "seed": SEED,
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": K.PROTOCOL, "args": args, "timeout_s": 120})
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job_id"]
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    done = started.json()
    assert done["status"] == "done", done
    return done


def _simulated(raw: bytes):
    """LABELED SIMULATED GUARDIAN: writes the genuine worker output and reports a clean RESULT (no process)."""
    def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        (attempt_dir / "result.json").write_bytes(raw)
        payload = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        return {"kind": "RESULT", "reason": "completed", "returncode": 0, "clean": True,
                "direct_child_reaped": True, "unexpected_members": False, "payload": payload}, None
    return supervise


def _kill_leftovers(root: Path, rid: str) -> None:
    import json

    import psutil
    for line in (root / rid / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
            except psutil.Error:
                pass


def shared_world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Build once per session: the real model run, the other-run model and one M20 report made before M21."""
    if "world" in _CACHE:
        return _CACHE["world"]
    root = tmp_path_factory.mktemp("m21_reads_reports") / "runs"
    saved_dir = api_module.RUNS_DIR
    try:
        client = client_for(root)
        main = _world(client, "M21 I44W reads and reports (public 1UBQ, not experimental validation)")
        try:
            done = _job(client, main["rid"], main["candidate_set"])
        finally:
            _kill_leftovers(root, main["rid"])
        handle = done["artifacts"]["mutation_model"]
        raw = (root / main["rid"] / "jobs" / done["job_id"] / done["attempt_id"] / "result.json").read_bytes()
        m20 = client.post(f"/runs/{main['rid']}/method_reports", json={"result_handle": main["candidate_set"]})
        assert m20.status_code == 201, m20.text
        other = _world(client, "M21 other run (labeled simulated guardian, genuine worker output)")
        patch = pytest.MonkeyPatch()
        try:
            patch.setattr(JobQueue, "_supervise", _simulated(raw))
            other_done = _job(client, other["rid"], other["candidate_set"])
        finally:
            patch.undo()
        world = {"root": root, "rid": main["rid"], "structure": main["structure"],
                 "candidate_set": main["candidate_set"], "model": handle, "job": done,
                 "m20_report": m20.json(), "other_rid": other["rid"],
                 "other_model": other_done["artifacts"]["mutation_model"],
                 "other_candidate_set": other["candidate_set"]}
        _CACHE["world"] = world
        return world
    finally:
        api_module.RUNS_DIR = saved_dir
        api_module.RUNS.clear()
