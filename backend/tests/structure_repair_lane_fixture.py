"""Shared helpers of the M29 T5 job-lane tests (this module holds no tests).

Worlds are made through the product API (upload -> ``load_structure`` -> ``prepare_structure``) with the FastAPI
TestClient on 127.0.0.1 (no port is opened). Simulated guardian results are LABELLED: they write a genuine worker
output (or an error envelope) into the attempt directory without launching a process, as the M21 tests do. Expected
values come from the input files and the installed template (``oracle``), never from the product's record.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import gemmi
import psutil
import test_structure_repair_common as C
from fastapi.testclient import TestClient

from mw import structure_repair_constants as K
from mw.api import app as api_module
from mw.jobs import process_identity

FIX = Path(__file__).parent / "fixtures"
REPAIR_KINDS = (K.KIND, K.COORDINATES_KIND, K.MANIFEST_KIND, K.STRUCTURE_KIND)


def client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def command(test_client: TestClient, rid: str, tool: str, args: dict) -> str:
    response = test_client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def world(test_client: TestClient, label: str, raw: bytes, name: str, *, waters: str = "strip_all",
          hydrogens: str = "strip", dry_run: bool = False) -> dict[str, Any]:
    created = test_client.post("/runs", json={"goal": label, "dry_run": dry_run})
    assert created.status_code == 201, created.text
    rid = created.json()["run_id"]
    uploaded = test_client.post(f"/runs/{rid}/uploads", params={"filename": name}, content=raw)
    assert uploaded.status_code in (200, 201), uploaded.text
    source = command(test_client, rid, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
    prepared = command(test_client, rid, "prepare_structure", {
        "structure": source, "altloc": "highest_occupancy", "waters": waters, "hydrogens": hydrogens,
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return {"rid": rid, "source": source, "structure": prepared}


def public(name: str) -> bytes:
    return (FIX / f"public_{name}.cif").read_bytes()


def args(structure: str, **extra) -> dict[str, Any]:
    return {"structure": structure, "repair_policy": K.REPAIR_POLICY, **extra}


def submit(test_client: TestClient, rid: str, job_args: Any, timeout_s: Any = 240):
    body: dict[str, Any] = {"protocol_id": K.PROTOCOL, "args": job_args}
    if timeout_s is not None:
        body["timeout_s"] = timeout_s
    return test_client.post(f"/runs/{rid}/jobs", json=body)


def approve_start(test_client: TestClient, rid: str, job_id: str):
    started = test_client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert started.json()["approval"] == {"gate": "expensive_first_call", "tool": K.TOOL,
                                              "reason": "first expensive call needs approval"}
        approved = test_client.post(f"/runs/{rid}/jobs/approve")
        assert approved.status_code == 200, approved.text
        started = test_client.post(f"/runs/{rid}/jobs/{job_id}/start")
    return started


def run_job(test_client: TestClient, rid: str, job_args: dict, timeout_s: float = 240) -> dict[str, Any]:
    submitted = submit(test_client, rid, job_args, timeout_s)
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["protocol_id"] == K.PROTOCOL, job
    started = approve_start(test_client, rid, job["job_id"])
    assert started.status_code == 200, started.text
    return started.json()


def events(root: Path, rid: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def used(test_client: TestClient, rid: str) -> int:
    return test_client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"]


def store_state(root: Path, rid: str) -> tuple[int, int, int]:
    """(object_created events, objects in the run's object folder, published events)."""
    found = events(root, rid)
    return (sum(e["type"] == "object_created" for e in found),
            sum(1 for path in (root / rid / "objects").iterdir() if not path.name.startswith(".")),
            sum(e["type"] == K.EVENT_PUBLISHED for e in found))


def workers_gone(root: Path, rid: str) -> None:
    for event in events(root, rid):
        if event["type"] == "job_worker_started":
            try:
                process = psutil.Process(event["pid"])
                assert (process.status() == psutil.STATUS_ZOMBIE or
                        not process_identity.matches(event["pid"], event["start_identity"]))
            except psutil.NoSuchProcess:
                pass


def kill_leftovers(root: Path, rid: str) -> None:
    """A process left by a failed assertion is killed only when its recorded start identity still matches."""
    for event in events(root, rid):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
            except psutil.Error:
                pass


def forbid(*_args, **_kwargs):
    raise AssertionError("this path must not run scientific work or launch a process")


def simulated(raw: bytes | None = None, *, error: dict | None = None, returncode: int = 0):
    """LABELLED simulated guardian: writes a genuine worker output (or an error envelope) into the attempt directory and
    reports a clean RESULT without launching any process."""
    def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        payload = None
        if raw is not None:
            (attempt_dir / "result.json").write_bytes(raw)
            payload = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        if error is not None:
            (attempt_dir / "error.json").write_text(json.dumps(error))
        return {"kind": "RESULT", "reason": "completed", "returncode": returncode, "clean": True,
                "direct_child_reaped": True, "unexpected_members": False, "payload": payload}, None
    return supervise


def tampered(raw: bytes, mutate) -> bytes:
    data = json.loads(raw)
    mutate(data)
    return json.dumps(data, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


# ----------------------------------------------------------------- independent expectation from the input file
def oracle(name: str) -> dict[str, Any]:
    """From the mmCIF file alone (gemmi document, not the product): observed polymer residues of model 1 (atom_site,
    heavy atoms, label sequence set), the internal unobserved residues of ``_pdbx_unobs_or_zero_occ_residues``
    (polymer, occupancy flag 1, label number strictly inside the chain's observed range), the template side-chain
    atoms each observed residue lacks, the missing C-terminal OXT and the template heavy atoms of every gap residue."""
    block = gemmi.cif.read_string(public(name).decode()).sole_block()
    observed: dict[str, dict[int, dict[str, Any]]] = {}
    for row in block.find("_atom_site.", ["auth_asym_id", "label_seq_id", "auth_seq_id", "pdbx_PDB_ins_code",
                                          "label_comp_id", "label_atom_id", "type_symbol", "pdbx_PDB_model_num"]):
        if gemmi.cif.is_null(row[1]) or row[6] in ("H", "D") or row[7] != "1":
            continue
        residue = observed.setdefault(row[0], {}).setdefault(int(row[1]), {"auth": int(row[2]), "name": row[4],
                                                                          "atoms": set()})
        residue["atoms"].add(row[5])
    listed: dict[str, list[tuple[int, int, str]]] = {}
    for row in block.find("_pdbx_unobs_or_zero_occ_residues.", ["polymer_flag", "occupancy_flag", "auth_asym_id",
                                                                "label_seq_id", "auth_seq_id", "label_comp_id"]):
        if row[0] == "Y" and row[1] == "1":
            listed.setdefault(row[2], []).append((int(row[3]), int(row[4]), row[5]))
    gaps: dict[str, list[list[tuple[int, int, str]]]] = {}
    side = oxt = gap_atoms = 0
    side_residues: list[tuple[str, int]] = []
    tails = False
    for chain, residues in observed.items():
        labels = sorted(residues)
        tails |= any(not labels[0] <= item[0] <= labels[-1] for item in listed.get(chain, []))
        inside = sorted(item for item in listed.get(chain, []) if labels[0] < item[0] < labels[-1])
        runs: list[list[tuple[int, int, str]]] = []
        for item in inside:
            if runs and runs[-1][-1][0] + 1 == item[0]:
                runs[-1].append(item)
            else:
                runs.append([item])
        gaps[chain] = runs
        gap_atoms += sum(len(C.template_heavy_names(item[2])) for item in inside)
        for label in labels:
            residue = residues[label]
            terminal = label == labels[-1]
            template = C.template_heavy_names(residue["name"], terminal)
            missing = [n for n in template if n not in residue["atoms"] and n not in ("N", "CA", "C", "O", "OXT")]
            if missing:
                side += len(missing)
                side_residues.append((chain, residue["auth"]))
            oxt += terminal and "OXT" not in residue["atoms"]
    return {"gaps": gaps, "gap_lengths": {chain: [len(run) for run in runs] for chain, runs in gaps.items()},
            "added_residues": sum(len(run) for runs in gaps.values() for run in runs),
            "side_chain_residues": sorted(side_residues), "side_chain_atoms": side, "terminal_oxt": oxt,
            "added_atoms": side + oxt + gap_atoms, "unobserved_tails": tails}
