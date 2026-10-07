"""PROTOTYPE (M25 T1 measurement only, never product code): loop call keys, stored-result lookup, engine time.

Preflight items (b), (f), (h) of the M25 plan. Every job runs through the UNMODIFIED product queue
(``JobQueue.submit`` -> approve -> ``start``) with the pinned workers: M17 RDKit jobs (``.deps/prolif``), M18
``qvina_dock_v1`` and one M19 ``qvina_batch_dock_v1`` (``.deps/docking`` + ``.deps/qvina``), M21
``openmm_mutation_model_v1`` (project ``.venv``: OpenMM 8.6.0, PDBFixer 1.12.0). A missing engine FAILS, never skips.

Inputs (not copied, read from the fixture folders): the public prepared docking example receptor
``../chemical/prolif-vina-rec.pdb``, the public-derived parent ``../docking/public-derived-parent-record0.sdf``, the
labelled synthetic blocks ``../ligand_ga/synthetic-ga-small-blocks.smi`` (M17 small pool, 10 candidates), the public
``../public_1ubq.cif`` / ``../public_1mq4.cif`` and the labelled synthetic phenol
``../mutation_model/synthetic-phenol-ligand.sdf``. The loop requests below are this script's reading of spec 3.1
``setup`` and 6.1 (ligand: ``docking_batch_inputs.row_request`` with ``mode: "free"``; protein: the M21 arguments and
the M18 ``receptor_source`` request); they are compared with the existing standalone M18 / M19 / M22 / M23 / M21
paths, never with themselves.

Runs live under ``--work`` (default ``runs/m25-t1-preflight/engine``, Git-excluded) and are deleted at the end unless
``--keep``. No network, no credential. qvina scores printed here are observations (kcal/mol, Vina-family scoring
function values, not affinities); nothing is ranked or compared between receptors. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
for extra in (str(BACKEND), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import psutil
from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import (
    docking_batch_inputs,
    docking_bundle,
    docking_inputs,
    ligand_ga_inputs,
    mutation_model_bundle,
    mutation_model_inputs,
    mutation_model_reads,
    sequence_ga_inputs,
)
from mw import docking_constants as C
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.jobs import process_identity
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import ApprovalRequired
from mw.workspace import new_run

FIX = TESTS / "fixtures"
REC = (FIX / "chemical/prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "docking/public-derived-parent-record0.sdf").read_bytes()
BLOCKS = (FIX / "ligand_ga/synthetic-ga-small-blocks.smi").read_bytes()
PHENOL = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
LIGAND_SEED = 7
PROTEIN_SEED = 20261007
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
K143 = {"model_number": 1, "chain_auth": "A", "seq_auth": 143, "icode": "", "resname": "LYS"}
GA = {"seed": 7, "population_size": 4, "generations": 2, "elite_count": 2, "tournament_size": 2, "neighbor_count": 3,
      "random_fraction": 0.25, "patience": 2, "max_new_dockings": 6, "total_s": 600}
TIMEOUTS = {"ligand_dock": 300, "model": 120, "dock": 300}   # spec 6.1 adjustable defaults


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def events(run: Any) -> list[dict[str, Any]]:
    return list(run.events.read())


def kill_leftovers(run: Any) -> int:
    killed = 0
    for event in events(run):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
                killed += 1
            except psutil.Error:
                pass
    return killed


def start(queue: JobQueue, job_id: str) -> tuple[dict[str, Any], float]:
    began = time.monotonic()
    try:
        done = queue.start(job_id)
    except ApprovalRequired:
        queue.run.approve("expensive_first_call", by="test")
        began = time.monotonic()
        done = queue.start(job_id)
    return done, round(time.monotonic() - began, 2)


def job_trace(run: Any, job_id: str) -> list[str]:
    """Event types of one job in log order (root_call_id = job_id links its reservation, which has no job_id)."""
    attempts: set[str] = set()
    out = []
    for event in events(run):
        linked = (event.get("job_id") == job_id or event.get("root_call_id") == job_id or
                  (event.get("attempt_id") in attempts and event.get("attempt_id") is not None) or
                  (event["type"] == "job_submitted" and event["job"]["job_id"] == job_id))
        if event["type"] == "budget_reserved" and event.get("root_call_id") == job_id:
            attempts.add(event["attempt_id"])
        if event["type"] == "wall_charged" and event.get("call_id") in attempts:
            linked = True
        if linked:
            out.append(event["type"] + (f":{event['status']}" if event["type"] == "job_terminal" else ""))
    return out


def m21_published(evts: list[dict[str, Any]], key: str) -> str | None:
    """PROTOTYPE of a server lookup: M21 call key -> output handle of a done ``openmm_mutation_model_v1`` job."""
    jobs = {e["job"]["job_id"] for e in evts if e["type"] == "job_submitted"
            and e["job"].get("protocol_id") == mutation_model_bundle.PROTOCOL and e["job"].get("call_key") == key}
    return next((e["output_handles"][0] for e in evts if e["type"] == "job_terminal" and e.get("status") == "done"
                 and e.get("job_id") in jobs and type(e.get("output_handles")) is list
                 and len(e["output_handles"]) == 1), None)


def first_score(content: dict[str, Any]) -> Any:
    return content["modes"][0]["score_kcal_mol"] if content["modes"] else None


# ----------------------------------------------------------------------------------------------------- ligand
def ligand_part(work: Path) -> dict[str, Any]:
    run = new_ligand_run(work, "m25_t1_ligand")
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    parent = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert (inspected["status"], enumerated["status"]) == ("done", "done"), (inspected, enumerated)
    candidate_set = enumerated["output_handles"][0]
    rows = run.store.load(candidate_set)["candidates"]
    ids = [row["id"] for row in rows]
    out: dict[str, Any] = {"run_id": run.run_id, "pool_size": len(ids)}

    # spec 3.1 ligand setup (M22 shared fields + parent_sdf_handle); the receptor/box/values are test choices
    setup = {"receptor_handle": receptor, "receptor_model_number": 1,
             "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
             "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": LIGAND_SEED},
             "acknowledgement": ACK, "parent_sdf_handle": parent}
    shared = {key: setup[key] for key in ("receptor_handle", "receptor_model_number", "connectivity",
                                          "receptor_instance", "box", "parameters", "acknowledgement")}

    def loop_request(cid: str, *, raw_setup: dict[str, Any] | None = None) -> dict[str, Any]:
        source = raw_setup or shared
        return docking_batch_inputs.row_request({**source, "mode": "free", "candidate_set_handle": candidate_set,
                                                 "parent_sdf_handle": parent}, "candidate", cid)

    t0 = time.monotonic()
    pins = docking_bundle.require_ready()
    out["m18_pins_seconds_first_call"] = round(time.monotonic() - t0, 3)
    t0 = time.monotonic()
    docking_bundle.require_ready()
    out["m18_pins_seconds_cached"] = round(time.monotonic() - t0, 4)

    def loop_key(request: dict[str, Any]) -> tuple[dict[str, Any], str]:
        normalized = docking_inputs.validate_arguments(request)
        return normalized, docking_bundle.call_key(normalized, pins)

    cid0, cid1 = ids[0], ids[1]
    norm0, key0 = loop_key(loop_request(cid0))
    # encoding variants of the same setup: explicit defaults, floats, key order
    variants = {
        "explicit_defaults": {**shared, "parameters": {"seed": LIGAND_SEED, "exhaustiveness": 8, "num_modes": 9,
                                                       "energy_range": 3}},
        "float_margin_energy": {**shared, "box": {"margin_A": 8.0, "source": "ligand_range"},
                                "parameters": {"energy_range": 3.0, "seed": LIGAND_SEED}},
        "reversed_key_order": dict(reversed(list(shared.items()))),
    }
    out["ligand_variants_equal"] = {}
    for name, raw in variants.items():
        normalized, key = loop_key(loop_request(cid0, raw_setup=raw))
        out["ligand_variants_equal"][name] = {"normalized_sha256_equal": sha(normalized) == sha(norm0),
                                              "call_key_equal": key == key0}
    # M19: the batch-normalized shared fields, then row_arguments
    batch_args = {**shared, "mode": "free", "candidate_set_handle": candidate_set, "parent_sdf_handle": parent,
                  "candidate_ids": [cid0], "include_parent": False}
    batch_norm = docking_batch_inputs.validate_arguments(batch_args)
    m19_row = docking_batch_inputs.row_arguments(batch_norm, "candidate", cid0)
    # M22: GA-normalized shared fields, row_arguments and individual_selection
    ga_args = {key: setup[key] for key in ("receptor_handle", "receptor_model_number", "connectivity",
                                           "receptor_instance", "box", "parameters", "acknowledgement")}
    ga_args.update(candidate_set_handle=candidate_set, parent_sdf_handle=parent, ga=GA)
    ga_norm = ligand_ga_inputs.validate_arguments(ga_args, 1200)
    m22_row = ligand_ga_inputs.row_arguments(ga_norm, cid0)
    ga_selected, _, _ = ligand_ga_inputs.submission(run, ga_args, 1200)
    individual = ligand_ga_inputs.individual_selection(ga_selected, rows[0])
    loop_selected, loop_normalized, _ = docking_bundle.submission(run, loop_request(cid0))
    out["ligand_key_equality"] = {
        "loop_normalized_canonical_sha256": sha(norm0), "loop_call_key": key0,
        "m19_row_arguments_equal": canonical_json(m19_row) == canonical_json(norm0),
        "m22_row_arguments_equal": canonical_json(m22_row) == canonical_json(norm0),
        "m22_individual_selection_equal_docking_bundle_submission":
            canonical_json(individual) == canonical_json(loop_selected),
        "submission_normalized_equal_validate_arguments": canonical_json(loop_normalized) == canonical_json(norm0),
        "m19_row_call_key_equal": docking_bundle.call_key(m19_row, pins) == key0,
        "m22_individual_call_key_equal": docking_bundle.call_key(individual["arguments"], pins) == key0,
    }

    # Real standalone M18 job made with the loop request (timeout 300) and a UI-shaped resubmission (timeout 60)
    queue = JobQueue(run)
    job = queue.submit(C.PROTOCOL, loop_request(cid0), timeout_s=TIMEOUTS["ligand_dock"])
    again = queue.submit(C.PROTOCOL, {**loop_request(cid0, raw_setup=variants["explicit_defaults"])}, timeout_s=60)
    out["ligand_job"] = {"job_call_key_equal_loop_key": job["call_key"] == key0,
                         "resubmit_other_timeout_same_job": again["job_id"] == job["job_id"],
                         "resubmit_keeps_first_timeout_s": again["timeout_s"]}
    done, seconds = start(queue, job["job_id"])
    handle = done["output_handles"][0] if done["status"] == "done" else None
    index = docking_batch_inputs.published_m18_results(events(run))
    content = docking_bundle.validated_result(run, handle) if handle else None
    out["ligand_job"].update(
        status=done["status"], seconds=seconds, timeout_s=done["timeout_s"],
        published_m18_results_key_to_handle=index.get(key0) == handle,
        validated_input_sha256_equal=(content or {}).get("input_sha256") == docking_inputs.input_sha256(norm0),
        modes=None if content is None else len(content["modes"]), first_mode_score_kcal_mol_observed=(
            None if content is None else first_score(content)),
        event_trace=job_trace(run, job["job_id"]))

    # M19 one-row batch on cid1 under the same setup: its row is found under the loop key of cid1
    _, key1 = loop_key(loop_request(cid1))
    batch_args1 = {**batch_args, "candidate_ids": [cid1]}
    batch = queue.submit(docking_batch_inputs.BC.PROTOCOL, batch_args1, timeout_s=1200)
    batch_done, batch_seconds = start(queue, batch["job_id"])
    index = docking_batch_inputs.published_m18_results(events(run))
    rows_published = [e for e in events(run) if e["type"] == "docking_batch_row_published"
                      and e.get("job_id") == batch["job_id"]]
    row_handle = rows_published[0]["handle"] if rows_published else None
    out["m19_batch_row"] = {"status": batch_done["status"], "seconds": batch_seconds,
                            "published_m18_results_loop_key_to_row_handle": index.get(key1) == row_handle,
                            "row_handle_validates": bool(row_handle and docking_bundle.validated_result(run,
                                                                                                         row_handle))}

    # A heavier candidate (most heavy atoms among the not yet docked ones) as a second standalone timing
    heavy = max(range(2, len(rows)), key=lambda i: (rows[i]["properties"]["heavy_atoms"],
                                                    rows[i]["properties"]["rotatable_bonds"], -i))
    heavy_job = queue.submit(C.PROTOCOL, loop_request(ids[heavy]), timeout_s=TIMEOUTS["ligand_dock"])
    heavy_done, heavy_seconds = start(queue, heavy_job["job_id"])
    heavy_content = (docking_bundle.validated_result(run, heavy_done["output_handles"][0])
                     if heavy_done["status"] == "done" else None)
    out["ligand_heavy_job"] = {"pool_index": heavy, "heavy_atoms": rows[heavy]["properties"]["heavy_atoms"],
                               "rotatable_bonds": rows[heavy]["properties"]["rotatable_bonds"],
                               "status": heavy_done["status"], "seconds": heavy_seconds,
                               "modes": None if heavy_content is None else len(heavy_content["modes"])}

    # M18 path of (a): a job cancelled before start is returned again by submit and cannot start or retry
    cancel_req = loop_request(ids[next(i for i in range(2, len(ids)) if i != heavy)])
    first = queue.submit(C.PROTOCOL, cancel_req, timeout_s=TIMEOUTS["ligand_dock"])
    cancelled = queue.request_cancel(first["job_id"])
    resubmitted = queue.submit(C.PROTOCOL, cancel_req, timeout_s=TIMEOUTS["ligand_dock"])
    refusals = {}
    for name, call in (("start", lambda: queue.start(first["job_id"])), ("retry", lambda: queue.retry(first["job_id"]))):
        try:
            call()
            refusals[name] = "accepted"
        except ToolFailure as exc:
            refusals[name] = f"{exc.cls.value}: {exc.message}"
    reserved = [e for e in events(run) if e["type"] == "budget_reserved" and e.get("root_call_id") == first["job_id"]]
    out["m18_cancel_before_start"] = {"cancel_status": cancelled["status"], "terminal": cancelled["job"]["status"],
                                      "resubmit_same_job_id": resubmitted["job_id"] == first["job_id"],
                                      "resubmit_status": resubmitted["status"], "refusals": refusals,
                                      "reservations_for_job": len(reserved)}
    out["budget_after"] = {axis: run.budget_snapshot()[axis] for axis in ("expensive_calls", "wall_clock_s")}
    out["killed_leftovers"] = kill_leftovers(run)
    return out


# ---------------------------------------------------------------------------------------------------- protein
def protein_run(work: Path, run_id: str, cif: Path, residue: dict[str, Any]) -> tuple[Any, str, str, dict[str, Any]]:
    run = new_run(work, run_id=run_id, dry_run=False)
    loaded = run.call("load_structure", {"source": str(cif), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    candidate_set = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [residue]}}).handle
    content = run.store.load(candidate_set)
    return run, prepared, candidate_set, content


def protein_part(work: Path) -> dict[str, Any]:
    run, _, candidate_set, content = protein_run(work, "m25_t1_protein", FIX / "public_1ubq.cif", I44)
    trp = next(row["index"] for row in content["candidates"] if row["to"] == "W")
    sdf = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    setup = {"ligand": {"source": "sdf", "sdf_handle": sdf}, "box": {"source": "ligand_range", "margin_A": 8},
             "parameters": {"seed": PROTEIN_SEED}, "selection_policy": "protein_only",
             "hydrogen_policy": "rebuild_pH7", "acknowledgement": ACK, "contact_cutoff_A": 4.0}
    out: dict[str, Any] = {"run_id": run.run_id, "candidate_index_I44W": trp}

    def model_args(**override: Any) -> dict[str, Any]:
        return {"candidate_set": candidate_set, "candidate_index": trp, "seed": setup["parameters"]["seed"],
                "contact_cutoff_A": setup["contact_cutoff_A"], "selection_policy": setup["selection_policy"],
                "hydrogen_policy": setup["hydrogen_policy"], **override}

    t0 = time.monotonic()
    m21_pins = mutation_model_bundle.require_ready()
    out["m21_pins_seconds_first_call"] = round(time.monotonic() - t0, 3)
    m21_key = mutation_model_bundle.call_key(mutation_model_inputs.normalize_arguments(model_args()), m21_pins)
    variants = {"cutoff_int_4": model_args(contact_cutoff_A=4),
                "cutoff_omitted_default": {k: v for k, v in model_args().items() if k != "contact_cutoff_A"}}
    out["m21_variants_call_key_equal"] = {
        name: mutation_model_bundle.call_key(mutation_model_inputs.normalize_arguments(args), m21_pins) == m21_key
        for name, args in variants.items()}
    queue = JobQueue(run)
    job = queue.submit(mutation_model_bundle.PROTOCOL, model_args(), timeout_s=TIMEOUTS["model"])
    other_timeout = queue.submit(mutation_model_bundle.PROTOCOL, model_args(), timeout_s=240)
    done, seconds = start(queue, job["job_id"])
    model = done["output_handles"][0] if done["status"] == "done" else None
    out["m21_job"] = {"job_call_key_equal_loop_key": job["call_key"] == m21_key,
                      "resubmit_timeout_240_same_job": other_timeout["job_id"] == job["job_id"],
                      "status": done["status"], "seconds": seconds, "timeout_s": done["timeout_s"],
                      "lookup_key_to_model_handle": m21_published(events(run), m21_key) == model,
                      "model_validates": bool(model and mutation_model_bundle.validated_result(run, model)),
                      "event_trace": job_trace(run, job["job_id"])}

    def dock_request(raw: dict[str, Any] | None = None) -> dict[str, Any]:
        source = raw or setup
        return {"receptor_source": {"kind": "mutation_model", "mutation_model": model, "side": "mutant"},
                "ligand": source["ligand"], "mode": "free", "box": source["box"], "parameters": source["parameters"],
                "acknowledgement": source["acknowledgement"]}

    pins = docking_bundle.require_ready()
    normalized = docking_inputs.validate_arguments(dock_request())
    key = docking_bundle.call_key(normalized, pins)
    m23_like = sequence_ga_inputs.individual_arguments(
        {"ligand": setup["ligand"], "box": docking_inputs.validate_arguments(dock_request())["box"],
         "parameters": {"seed": PROTEIN_SEED, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0},
         "acknowledgement": ACK}, model, "mutant")
    out["dock_key_equality"] = {
        "loop_normalized_canonical_sha256": sha(normalized), "loop_call_key": key,
        "m23_individual_arguments_equal": canonical_json(m23_like) == canonical_json(normalized),
        "m23_individual_call_key_equal": docking_bundle.call_key(m23_like, pins) == key,
        "explicit_defaults_equal": docking_bundle.call_key(docking_inputs.validate_arguments(dock_request({
            **setup, "parameters": {"seed": PROTEIN_SEED, "exhaustiveness": 8, "num_modes": 9,
                                    "energy_range": 3}})), pins) == key}
    dock_job = queue.submit(C.PROTOCOL, dock_request(), timeout_s=TIMEOUTS["dock"])
    dock_done, dock_seconds = start(queue, dock_job["job_id"])
    dock_handle = dock_done["output_handles"][0] if dock_done["status"] == "done" else None
    dock_content = docking_bundle.validated_result(run, dock_handle) if dock_handle else None
    index = docking_batch_inputs.published_m18_results(events(run))
    out["dock_job"] = {"job_call_key_equal_loop_key": dock_job["call_key"] == key, "status": dock_done["status"],
                       "seconds": dock_seconds, "published_m18_results_key_to_handle": index.get(key) == dock_handle,
                       "modes": None if dock_content is None else len(dock_content["modes"]),
                       "first_mode_score_kcal_mol_observed": None if dock_content is None else first_score(
                           dock_content)}
    # (h) the M21 same-condition pair read of a mutant-only (loop-shaped) docking
    pairs = mutation_model_reads.docking_pairs(run, model)
    out["docking_pairs_mutant_only"] = {
        "total": pairs["total"],
        "sides": [{side: {k: entry[k] for k in ("job_status", "reason_code", "score_kcal_mol", "result_handle")}
                   for side, entry in pair["sides"].items()} for pair in pairs["pairs"]],
        "both_published": [pair["both_published"] for pair in pairs["pairs"]],
        "pair_keys": sorted(pairs["pairs"][0]) if pairs["pairs"] else [],
        "side_keys": sorted(pairs["pairs"][0]["sides"]["mutant"]) if pairs["pairs"] else []}
    out["budget_after"] = {axis: run.budget_snapshot()[axis] for axis in ("expensive_calls", "wall_clock_s")}
    out["killed_leftovers"] = kill_leftovers(run)

    # 1MQ4: does an M21 job pass admission and the M7 preflight at all?
    mq4, _, mq4_set, mq4_content = protein_run(work, "m25_t1_protein_1mq4", FIX / "public_1mq4.cif", K143)
    index_1mq4 = mq4_content["candidates"][0]["index"] if mq4_content["candidates"] else None
    try:
        submitted = JobQueue(mq4).submit(mutation_model_bundle.PROTOCOL, {
            "candidate_set": mq4_set, "candidate_index": index_1mq4, "seed": PROTEIN_SEED,
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}, timeout_s=TIMEOUTS["model"])
        out["m21_1mq4_submit"] = {"accepted": True, "status": submitted["status"]}
    except ToolFailure as exc:
        out["m21_1mq4_submit"] = {"accepted": False, "class": exc.cls.value,
                                  "reason_code": exc.detail.get("reason_code")}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/engine")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    started = time.monotonic()
    try:
        report = {"ligand": ligand_part(args.work), "protein": protein_part(args.work)}
        report["total_seconds"] = round(time.monotonic() - started, 1)
        text = json.dumps(report, indent=1, ensure_ascii=False)
        (args.work / "report.json").write_text(text + "\n", encoding="utf-8")
        print(text)
    finally:
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
