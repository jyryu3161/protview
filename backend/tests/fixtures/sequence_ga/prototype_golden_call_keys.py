# PROTOTYPE (M23 T1 measurement only; never product code, never imported by mw).
"""Record the golden M18/M19/M21 call keys and result bytes BEFORE any M23 server extension (spec 8, 12).

Builds one run with the fixed id ``RUN_ID`` through the unmodified product paths (HTTP for the 1UBQ upload and the
cheap tools, ``JobQueue`` for jobs, the real engines; a missing engine FAILS) and writes ``golden_call_keys.json``:

* ``m18_imported_receptor``: a standalone ``qvina_dock_v1`` free docking on an imported receptor (public prepared
  docking example ``fixtures/chemical/prolif-vina-rec.pdb`` + public-derived parent SDF, see
  ``fixtures/docking/SYNTHETIC-PROVENANCE.md``),
* ``m21_mutation_model``: the M21 ``openmm_mutation_model_v1`` job for 1UBQ I44W (public structure, not experimental
  validation) from the M20 candidate set of this folder (user-selected 1UBQ positions, allowed ``AFHWY``; since M26 T1
  the stored v1 content of ``fixtures/reaction/t1/m20-v1-candidate-set-run_m23_golden_keys-8pos.json`` put with
  ``store.put``, so M20 v2 does not change the recorded set),
* ``m18_mutation_model_source``: a standalone ``qvina_dock_v1`` on the M21 mutant side (``receptor_source``) with the
  labeled synthetic phenol ``fixtures/mutation_model/synthetic-phenol-ligand.sdf``,
* ``m19_batch_row``: a one-row ``qvina_batch_dock_v1`` (real M17 inspect + enumerate first),

each with its call key and the SHA-256 of the stored object bytes, plus the SHA-256 of the files whose change would
end existing result reuse. Handles are content-addressed with the fixed run id, so a later rebuild with the same
inputs reproduces every value (measured twice in T1, ``docs/qa/m23-sequence-ga-20261005/preflight.txt`` (d)).

    .venv/bin/python backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py <runs-root> [<out.json>]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
ROOT = HERE.parents[3]
sys.path.insert(0, str(TESTS))

from fastapi.testclient import TestClient
from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import docking_batch_inputs, docking_bundle
from mw import docking_constants as C
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.runtime.guards import BudgetLimits

RUN_ID = "run_m23_golden_keys"
FIX = TESTS / "fixtures"
V1_SET = FIX / "reaction/t1/m20-v1-candidate-set-run_m23_golden_keys-8pos.json"   # SYNTHETIC-PROVENANCE-t1.md
UBQ = (FIX / "public_1ubq.cif").read_bytes()
PHENOL = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
REC = (FIX / "chemical/prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "docking/public-derived-parent-record0.sdf").read_bytes()
BLOCKS = (FIX / "docking/synthetic-docking-blocks.smi").read_bytes()
EXPECTED = json.loads((FIX / "docking/expected.json").read_text())
SMALL_BOX = {"source": "manual", "center_A": EXPECTED["public_example_box"]["center_A"], "size_A": [12.0, 12.0, 12.0]}
FAST = {"seed": 1, "exhaustiveness": 1, "num_modes": 2}
MODEL_DOCKING = {"seed": 20261004, "exhaustiveness": 4, "num_modes": 5}
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
# 1UBQ chain A positions chosen by the user list (N terminus, adjacent pairs, the M21 I44, the C terminus).
POSITIONS = [(1, "MET"), (2, "GLN"), (3, "ILE"), (6, "LYS"), (8, "LEU"), (44, "ILE"), (75, "GLY"), (76, "GLY")]
ALLOWED = "AFHWY"
HASHED = ("backend/mw/jobs/docking_worker.py", "backend/mw/docking_constants.py",
          "backend/mw/jobs/openmm_mutation_worker.py", "backend/mw/mutation_model_constants.py",
          "backend/mw/mutation_model_math.py", "backend/mw/mutation_candidates.py")
ALSO_HASHED = ("backend/mw/jobs/openmm_worker.py", "backend/mw/tools/openmm_method.py",
               "backend/mw/jobs/docking_batch_worker.py", "backend/mw/docking_batch_constants.py",
               "backend/mw/jobs/ligand_ga_worker.py", "backend/mw/ligand_ga_constants.py",
               "backend/mw/ligand_ga_bundle.py", "backend/mw/ligand_ga_inputs.py", "backend/mw/ligand_ga_jobs.py",
               "backend/mw/ligand_ga_reads.py", "backend/mw/ligand_ga_reports.py")


def residue(seq: int, name: str) -> dict:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq, "icode": "", "resname": name}


def sha_file(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _command(client: TestClient, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{RUN_ID}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def structure_and_candidates(client: TestClient) -> dict:
    uploaded = client.post(f"/runs/{RUN_ID}/uploads", params={"filename": "public_1ubq.cif"}, content=UBQ)
    assert uploaded.status_code in (200, 201), uploaded.text
    source = _command(client, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
    prepared = _command(client, "prepare_structure", {
        "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return {"structure": prepared}


def stored_v1_candidates(run, structure: str) -> str:
    """The M20 v1 set for ``POSITIONS`` / ``ALLOWED`` on ``structure``: stored content, not a new tool call."""
    fixture = json.loads(V1_SET.read_text())
    content = fixture["content"]
    params = content["parameters"]
    assert content["structure"]["handle"] == structure and params["allowed_residues"] == ALLOWED
    assert [(r["seq_auth"], r["resname"]) for r in params["sources"]["residues"]] == POSITIONS
    with run._owner(), run._transition():
        run.store.rebuild_from_events()
        handle = run.store.put("mutation_candidate_set", "mutation_candidate_set@1", content,
                               summary={"structure": structure, **content["counts"],
                                        "null_result": content["null_result"]},
                               null_result=content["null_result"]).handle
    assert handle == fixture["handle"], handle
    return handle


def candidate_index(content: dict, seq: int, to: str) -> int:
    rows = [c for c in content["candidates"]
            if content["positions"][c["position_index"]]["residue"]["seq_auth"] == seq and c["to"] == to]
    assert len(rows) == 1, rows
    return rows[0]["index"]


def stored(run, handle: str) -> dict:
    raw = canonical_json(run.store.load(handle))
    return {"handle": handle, "content_sha256": hashlib.sha256(raw).hexdigest(), "content_bytes": len(raw)}


def job_entry(run, job: dict, request: dict) -> dict:
    """``request`` = the arguments as submitted (resubmittable); ``parameters`` = the job's normalized record."""
    assert job["status"] == "done", job
    return {"protocol_id": job["protocol_id"], "call_key": job["call_key"], "request": request,
            "timeout_s": job["timeout_s"], "parameters": job["parameters"],
            "output": stored(run, job["output_handles"][0])}


def build(root: Path) -> dict:
    run = new_ligand_run(root, RUN_ID)
    run.update_limits(BudgetLimits(expensive_calls=40, wall_clock_s=7200), by="test")
    saved = api_module.RUNS_DIR
    try:
        api_module.RUNS_DIR = root
        api_module.RUNS.clear()
        world = structure_and_candidates(TestClient(api_module.app, base_url="http://127.0.0.1"))
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()
    run = new_ligand_run(root, RUN_ID)        # reopen: the HTTP calls appended events
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    world["candidate_set"] = stored_v1_candidates(run, world["structure"])
    cset = run.store.load(world["candidate_set"])
    i44w = candidate_index(cset, 44, "W")
    phenol = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    parent = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    asked = {"m21": {"candidate_set": world["candidate_set"], "candidate_index": i44w, "seed": MODEL_DOCKING["seed"],
                     "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}}
    m21 = run_job(run, "openmm_mutation_model_v1", asked["m21"], timeout_s=120)
    assert m21["status"] == "done", m21
    model = m21["output_handles"][0]
    asked["m18_source"] = {
        "receptor_source": {"kind": "mutation_model", "mutation_model": model, "side": "mutant"},
        "ligand": {"source": "sdf", "sdf_handle": phenol}, "mode": "free",
        "box": {"source": "ligand_range", "margin_A": 8}, "parameters": dict(MODEL_DOCKING), "acknowledgement": ACK}
    m18_source = run_job(run, "qvina_dock_v1", asked["m18_source"], timeout_s=600)
    asked["m18_import"] = {
        "receptor_handle": receptor, "receptor_model_number": 1,
        "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
        "ligand": {"source": "sdf", "sdf_handle": parent}, "mode": "free", "box": SMALL_BOX, "parameters": dict(FAST),
        "acknowledgement": ACK}
    m18_import = run_job(run, "qvina_dock_v1", asked["m18_import"], timeout_s=600)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    ligand_set = enumerated["output_handles"][0]
    first_id = run.store.load(ligand_set)["candidates"][0]["id"]
    asked["m19"] = {
        "receptor_handle": receptor, "receptor_model_number": 1,
        "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
        "candidate_set_handle": ligand_set, "parent_sdf_handle": parent, "candidate_ids": [first_id],
        "include_parent": False, "mode": "free", "box": SMALL_BOX, "parameters": dict(FAST), "acknowledgement": ACK}
    batch = run_job(run, "qvina_batch_dock_v1", asked["m19"], timeout_s=1200)
    assert batch["status"] == "done", batch
    events = list(run.events.read())
    rows = [e for e in events if e["type"] == "docking_batch_row_published" and e["job_id"] == batch["job_id"]]
    assert len(rows) == 1, rows
    jobs = {e["job"]["job_id"]: e["job"] for e in events if e["type"] == "job_submitted"}
    batch_job = jobs[batch["job_id"]]
    row_key = docking_batch_inputs.row_call_keys(batch_job["selected"], batch_job["method"])[0]
    published = docking_batch_inputs.published_m18_results(events)
    assert published[row_key] == rows[0]["handle"]
    for job in (m18_source, m18_import):
        recomputed = docking_bundle.call_key(jobs[job["job_id"]]["parameters"], jobs[job["job_id"]]["method"])
        assert recomputed == job["call_key"] and published[job["call_key"]] == job["output_handles"][0]
    model_content = run.store.load(model)
    return {
        "schema": "m23_golden_call_keys@1",
        "how": "Recorded in M23 T1 before any M23 server change by prototype_golden_call_keys.py (unmodified product "
               "paths, real engines). Values are call keys and SHA-256 of stored object bytes, not science values. "
               "Valid for the pinned environments of this machine (qvina2 / Meeko / RDKit / MDAnalysis / gemmi / "
               "OpenMM 8.6.0 / PDBFixer 1.12.0 pins are inside the keys).",
        "run_id": RUN_ID,
        "inputs": {"public_1ubq_sha256": hashlib.sha256(UBQ).hexdigest(),
                   "synthetic_phenol_sha256": hashlib.sha256(PHENOL).hexdigest(),
                   "receptor_sha256": hashlib.sha256(REC).hexdigest(),
                   "parent_sha256": hashlib.sha256(PARENT).hexdigest(),
                   "blocks_sha256": hashlib.sha256(BLOCKS).hexdigest(),
                   "m20_positions": [residue(seq, name) for seq, name in POSITIONS], "m20_allowed": ALLOWED},
        "hashed_files": {rel: sha_file(rel) for rel in HASHED},
        "also_hashed_files": {rel: sha_file(rel) for rel in ALSO_HASHED},
        "pins": {"m18": jobs[m18_import["job_id"]]["method"], "m21": jobs[m21["job_id"]]["method"]},
        "handles": {"structure": world["structure"], "candidate_set": world["candidate_set"], "phenol_sdf": phenol,
                    "receptor": receptor, "parent_sdf": parent, "ligand_candidate_set": ligand_set},
        "requests": {
            "m18_imported_receptor": job_entry(run, m18_import, asked["m18_import"]),
            "m21_mutation_model": {**job_entry(run, m21, asked["m21"]), "candidate_index": i44w,
                                   "structure_objects": {side: entry["structure_object"] for side, entry in
                                                         sorted(model_content["structures"].items())}},
            "m18_mutation_model_source": job_entry(run, m18_source, asked["m18_source"]),
            "m19_batch_row": {"protocol_id": batch["protocol_id"], "batch_call_key": batch["call_key"],
                              "request": asked["m19"], "timeout_s": batch["timeout_s"],
                              "parameters": batch["parameters"], "row_call_key": row_key,
                              "row_output": stored(run, rows[0]["handle"]),
                              "summary": stored(run, next(e for e in events if e["type"] == "docking_batch_published"
                                                          and e["job_id"] == batch["job_id"])["summary_handle"])},
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        return 2
    golden = build(Path(argv[0]))
    out = Path(argv[1]) if len(argv) == 2 else HERE / "golden_call_keys.json"
    out.write_text(json.dumps(golden, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
