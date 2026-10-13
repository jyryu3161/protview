"""M29 T5: the ``pdbfixer_repair_v1`` job lane end to end on 8VF6 (real worker process), events-only reopening, the
same input twice, every closed job failure, timeout and cancellation.

Input: public 8VF6 (RCSB, CC0; ``fixtures/public_8vf6.cif``; a public structure, not experimentally validated here)
through the product path (upload -> ``load_structure`` -> ``prepare_structure`` -> POST /jobs -> approve -> start). The
real worker ``mw/jobs/structure_repair_worker.py`` runs PDBFixer 1.12.0 in the project ``.venv``; the tests FAIL,
never skip, when an engine or the process table is unavailable. Expected values come from the input file and the
installed template (``structure_repair_lane_fixture.oracle``), not from the product. Publication-guard tests reuse the
genuine worker output with a LABELLED simulated guardian result (no process); fault injections are labelled internal
test hooks (monkeypatched functions or limits), never request fields.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time

import gemmi
import pytest
import structure_repair_lane_fixture as F
import test_structure_repair_common as C

from mw import structure_repair as sr
from mw import structure_repair_bundle as bundle
from mw import structure_repair_constants as K
from mw import structure_repair_jobs as jobs
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.structure_origin import is_repaired, structure_origin
from mw.tools import openmm_method
from mw.workspace import new_run

VF6 = F.public("8vf6")
LABEL = "M29 8VF6 structure repair (public RCSB 8VF6, CC0; not experimental validation)"


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    """The full product path once with the real worker; the genuine ``result.json`` bytes are reused (labelled
    simulated guardian results) by the publication-guard tests."""
    root = tmp_path_factory.mktemp("m29_t5_real") / "runs"
    patch = pytest.MonkeyPatch()
    try:
        client = F.client(root, patch)
        world = F.world(client, LABEL, VF6, "public_8vf6.cif")
        rid = world["rid"]
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412   # nothing pending yet
        submitted = F.submit(client, rid, F.args(world["structure"]))
        assert submitted.status_code == 200, submitted.text
        job = submitted.json()
        first = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
        assert first.status_code == 409 and first.json()["approval"]["tool"] == K.TOOL
        used_before_approval = F.used(client, rid)
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = time.monotonic()
        try:
            done = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start").json()
        finally:
            F.kill_leftovers(root, rid)
        seconds = time.monotonic() - started
        raw = (root / rid / "jobs" / done["job_id"] / done["attempt_id"] / "result.json").read_bytes()
        return {"root": root, "world": world, "submitted": job, "done": done, "raw": raw, "seconds": seconds,
                "used_before_approval": used_before_approval, "used": F.used(client, rid)}
    finally:
        patch.undo()
        api_module.RUNS.clear()


def _st(raw: bytes) -> gemmi.Structure:
    return gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())


# ----------------------------------------------------------------- the product path (real worker)
def test_8vf6_job_publishes_the_independently_expected_repair(real, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    assert done["status"] == "done", done
    assert real["used_before_approval"] == 0 and real["used"] == 1
    assert done["timeout_s"] == 240 and done["cleanup_status"] == "verified"
    assert done["input_handles"] == [world["structure"]]
    record_handle, repaired = done["output_handles"]
    assert done["artifacts"] == {"structure_repair": record_handle, "prepared_structure": repaired}
    run = new_run(root, run_id=rid, dry_run=False)
    result = bundle.validated_result(run, record_handle)
    record = result["record"]
    assert record == run.store.load(record_handle) and result["prepared_structure"] == repaired
    # Independent expectation from the file's unobserved-residue listing and the installed template.
    expected = F.oracle("8vf6")
    assert expected["gap_lengths"] == {"A": [13], "B": [11]} and expected["added_residues"] == 24
    assert len(expected["side_chain_residues"]) == 23 and expected["terminal_oxt"] == 2
    assert expected["added_atoms"] == 266
    counts = record["counts"]
    assert (counts["added_residues"], counts["added_atoms"], counts["side_chain_residues"], counts["terminal_oxt"],
            counts["gaps"], counts["replaced"]) == (expected["added_residues"], expected["added_atoms"],
                                                    len(expected["side_chain_residues"]), expected["terminal_oxt"],
                                                    2, 0)
    assert [(g["chain_auth"], g["length"]) for g in record["gaps"]] == [("A", 13), ("B", 11)]
    assert [[(r["seq_label"], r["seq_auth"], r["resname"]) for r in g["residues"]] for g in record["gaps"]] == [
        [(label, auth, name) for label, auth, name in run_] for chain in ("A", "B") for run_ in expected["gaps"][chain]]
    assert sorted((s["residue"]["chain_auth"], s["residue"]["seq_auth"]) for s in record["side_chain_repairs"]) == \
        expected["side_chain_residues"]
    # Chain parts: counted from the prepared input itself (gemmi chains per author name).
    prepared_raw = run.store.load(run.store.load(world["structure"])["coordinates"])
    parts = {}
    for chain in _st(prepared_raw)[0]:
        parts[chain.name] = parts.get(chain.name, 0) + 1
    assert record["chain_parts"] == [{"chain_auth": name, "parts": n, "merged": n > 1} for name, n in parts.items()]
    assert record["classes_applied"] == ["chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added",
                                         "internal_gap_filled"]
    # Observed atoms: every prepared atom with its name, element, altloc and coordinates within 1e-9 A; the new
    # atoms are exactly the calc_flag c atoms, rounded to four decimals.
    raw = bundle.structure_bytes(run, record_handle)
    observed = {}
    for chain in _st(prepared_raw)[0]:
        for res in chain:
            for atom in res:
                observed[(*C.key(chain, res), atom.name, atom.altloc)] = (atom.element.name, atom.pos)
    new = 0
    seen = 0
    for chain in _st(raw)[0]:
        for res in chain:
            for atom in res:
                key = (*C.key(chain, res), atom.name, atom.altloc)
                if atom.calc_flag == gemmi.CalcFlag.Calculated:
                    new += 1
                    assert key not in observed and all(abs(v * 1e4 - round(v * 1e4)) < 1e-6
                                                       for v in (atom.pos.x, atom.pos.y, atom.pos.z))
                    continue
                element, pos = observed[key]
                assert element == atom.element.name and pos.dist(atom.pos) <= 1e-9, key
                seen += 1
    assert new == expected["added_atoms"] and seen == len(observed) == record["unchanged"]["atom_count"]
    # The worker returned exactly the T1 PDBFixer measurement (same procedure, seed 1), at PDBFixer precision.
    output = json.loads(real["raw"])
    fixture = json.loads((C.SR_FIX / "8vf6-additions.pdbfixer-measured.json").read_text())["added_atoms"]
    assert canonical_json(output["added_atoms"]) == canonical_json(fixture)
    # the worker saw the protein heavy atoms only (ligand atoms are observed atoms of the record, not of PDBFixer)
    assert output["diagnostics"]["observed_atoms"] == counts["protein_heavy_atoms"] - counts["added_atoms"]
    assert output["diagnostics"]["observed_max_delta_A"] <= 1e-9
    # The four objects, the published event and the manifest mark (the record names neither structure nor manifest).
    published = [e for e in F.events(root, rid) if e["type"] == K.EVENT_PUBLISHED]
    assert len(published) == 1
    event = published[0]
    assert {key: event[key] for key in K.EVENT_HANDLE_KEYS} == {
        "record": record_handle, "prepared_structure": repaired, "coordinates": result["coordinates"],
        "manifest": result["manifest"]}
    assert event["job_id"] == done["job_id"] and event["attempt_id"] == done["attempt_id"]
    text = canonical_json(record).decode()
    assert repaired not in text and result["manifest"] not in text and done["job_id"] not in text
    source = run.store.load(world["structure"])
    source_manifest = run.store.load(source["manifest"])
    manifest = run.store.load(result["manifest"])
    assert manifest == {**source_manifest, "missing_residues": "modeled_internal_gaps",
                        "repair": {"record": record_handle, "source": world["structure"]}}
    assert run.store.load(repaired) == {"coordinates": result["coordinates"], "manifest": result["manifest"],
                                        "model_index": source["model_index"], "model_number": source["model_number"]}
    meta = run.store.meta(repaired)
    assert (meta["kind"], meta["schema"]) == ("prepared_structure", "prepared_structure@1")
    assert run.store.meta(result["coordinates"])["fmt"] == "cif"
    assert is_repaired(run.store, repaired) and not is_repaired(run.store, world["structure"])
    assert structure_origin(run.store, repaired) == {"repair_record": record_handle, "repaired_structure": repaired,
                                                     "source_structure": world["structure"], "counts": counts}
    # Approval once by the human route, one reservation, the pinned method, no process left.
    events = F.events(root, rid)
    assert [e["type"] for e in events if e["type"] in {"approval_requested", "approval_resolved"}] == [
        "approval_requested", "approval_resolved"]
    assert len([e for e in events if e["type"] == "budget_reserved"]) == 1
    job = JobQueue(run).get(done["job_id"])
    assert job["method"] == jobs.require_ready() and job["call_key"] == jobs.call_key(job["parameters"], job["method"])
    F.workers_gone(root, rid)


def test_reads_validate_every_time_and_write_nothing(real, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    client = F.client(root, monkeypatch)
    record_handle, repaired = done["output_handles"]
    before = (root / rid / "events.jsonl").read_bytes()
    rows = client.get(f"/runs/{rid}/structure_repairs").json()
    assert rows["schema"] == "structure_repair_list@1" and rows["total"] == 1
    assert rows["rows"][0]["valid"] is True and rows["rows"][0]["prepared_structure"] == repaired
    detail = client.get(f"/runs/{rid}/structure_repairs/{record_handle}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["added_atom_count"] == 266 and "added_atoms" not in body["result"]
    assert body["prepared_structure"] == repaired and body["source_structure"] == world["structure"]
    assert body["meta"]["kind"] == K.KIND
    stored = new_run(root, run_id=rid, dry_run=False).store.load(record_handle)
    assert body["result"] == {key: value for key, value in stored.items() if key != "added_atoms"}
    pages = [client.get(f"/runs/{rid}/structure_repairs/{record_handle}/atoms", params=params).json()
             for params in ({}, {"page": 3}, {"page_size": 200, "page": 2})]
    assert [(p["page"], p["page_size"], p["total"], len(p["rows"])) for p in pages] == [
        (1, 100, 266, 100), (3, 100, 266, 66), (2, 200, 266, 66)]
    assert pages[1]["rows"][0]["index"] == 200
    assert [{k: v for k, v in row.items() if k != "index"} for row in pages[0]["rows"]] == stored["added_atoms"][:100]
    for params in ({"page_size": 0}, {"page_size": 201}, {"page": 0}, {"other": 1}):
        assert client.get(f"/runs/{rid}/structure_repairs/{record_handle}/atoms", params=params).status_code == 422
    download = client.get(f"/runs/{rid}/structure_repairs/{record_handle}/structure")
    assert download.status_code == 200 and download.headers["content-type"].startswith("chemical/x-mmcif")
    assert hashlib.sha256(download.content).hexdigest() == stored["result"]["coordinates_sha256"]
    assert record_handle.rsplit("/", 1)[-1][:12] in download.headers["content-disposition"]
    # Wrong kinds and unknown handles never read.
    for wrong in (repaired, world["structure"]):
        assert client.get(f"/runs/{rid}/structure_repairs/{wrong}").status_code == 422
    assert client.get(f"/runs/{rid}/structure_repairs/obj://{rid}/{K.KIND}/{'1' * 64}").status_code == 404
    assert (root / rid / "events.jsonl").read_bytes() == before


def test_events_only_reopen_without_engines_or_processes(real, tmp_path, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    record_handle, repaired = done["output_handles"]
    original = new_run(root, run_id=rid, dry_run=False)
    result = bundle.validated_result(original, record_handle)
    raw = bundle.structure_bytes(original, record_handle)
    before = (root / rid / "events.jsonl").read_bytes()
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(before)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "pdbfixer", None)     # labelled: PDBFixer cannot be imported
        patch.setattr(openmm_method, "dependencies", F.forbid)
        patch.setattr(openmm_method, "preflight", F.forbid)
        patch.setattr(jobs, "require_ready", F.forbid)
        patch.setattr(jobs, "stage", F.forbid)
        patch.setattr(JobQueue, "_supervise", F.forbid)
        patch.setattr(subprocess, "Popen", F.forbid)
        patch.setattr(Run, "call", F.forbid)
        recovered = new_run(replay, run_id=rid, dry_run=False)
        assert bundle.validated_result(recovered, record_handle) == result
        assert bundle.structure_bytes(recovered, record_handle) == raw
        assert structure_origin(recovered.store, repaired)["repair_record"] == record_handle
        assert JobQueue(recovered).get(done["job_id"])["status"] == "done"
        assert (replay / rid / "events.jsonl").read_bytes() == before
        # A tampered recovered record never reads.
        path = replay / rid / recovered.store.meta(record_handle)["path"]
        path.write_text(json.dumps({**result["record"], "limitations": result["record"]["limitations"][:-1]}))
        with pytest.raises(bundle.RepairEvidenceError):
            bundle.validated_result(recovered, record_handle)


def test_same_input_twice_is_the_same_job_and_handles_and_a_repaired_input_is_refused(real, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    client = F.client(root, monkeypatch)
    used = F.used(client, rid)
    before = len(F.events(root, rid))
    for timeout_s in (240, 120, None):    # the timeout is not in the call key
        again = F.submit(client, rid, F.args(world["structure"]), timeout_s)
        assert again.status_code == 200, again.text
        body = again.json()
        assert (body["job_id"], body["call_key"], body["output_handles"]) == (
            done["job_id"], done["call_key"], done["output_handles"])
    assert F.used(client, rid) == used and len(F.events(root, rid)) == before
    # The repaired structure is a prepared_structure@1 of this run, refused by admission (and by the preflight read).
    repaired = done["output_handles"][1]
    refused = F.submit(client, rid, F.args(repaired))
    assert refused.status_code == 422 and refused.json()["detail"]["reason_code"] == "already_repaired"
    preflight = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": repaired}).json()
    assert preflight["admission"]["admitted"] is False and preflight["admission"]["reason_code"] == "already_repaired"
    assert preflight["defects"] is None and preflight["starts_job"] is False
    # The call key binds the normalized arguments, the worker SHA-256, each dependency and the method record.
    run = new_run(root, run_id=rid, dry_run=False)
    job = JobQueue(run).get(done["job_id"])
    assert job["parameters"] == {"structure": world["structure"], "repair_policy": K.REPAIR_POLICY}
    assert jobs.call_key(job["parameters"], {**job["method"], "worker_sha256": "0" * 64}) != done["call_key"]
    for name in jobs.DEPENDENCIES:
        changed = {**job["method"], "dependency_sha256": {**job["method"]["dependency_sha256"], name: "0" * 64}}
        assert jobs.call_key(job["parameters"], changed) != done["call_key"], name
    assert F.used(client, rid) == used


def test_keep_all_stages_the_same_protein_and_publishes_with_its_own_policy(real, tmp_path, monkeypatch):
    """PDBFixer sees the protein only, so the keep_all payload equals the strip_all one; the genuine worker output is
    therefore the keep_all output too (LABELLED simulated guardian, no process)."""
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, LABEL + ", keep_all", VF6, "public_8vf6.cif", waters="keep_all")
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", F.simulated(real["raw"]))
        done = F.run_job(client, world["rid"], F.args(world["structure"]))
    assert done["status"] == "done", done
    run = new_run(root, run_id=world["rid"], dry_run=False)
    strip_job = JobQueue(new_run(real["root"], run_id=real["world"]["rid"], dry_run=False)).get(real["done"]["job_id"])
    keep_job = JobQueue(run).get(done["job_id"])
    assert keep_job["selected"]["payload"] == strip_job["selected"]["payload"]
    record = bundle.validated_result(run, done["output_handles"][0])["record"]
    assert record["parameters"]["waters"] == "keep_all"
    strip_record = new_run(real["root"], run_id=real["world"]["rid"], dry_run=False).store.load(
        real["done"]["output_handles"][0])
    assert record["counts"] == strip_record["counts"] and record["parameters"]["waters"] != \
        strip_record["parameters"]["waters"]
    assert record["collisions"]["water"]["min_distance_A"] is not None
    assert strip_record["collisions"]["water"] == {"min_distance_A": None, "count_lt_2_0": 0, "count_lt_1_5": 0,
                                                   "min_pair": None}


# ----------------------------------------------------------------- closed failures publish nothing
def _faulty_build(change):
    """LABELLED internal hook: the core builder's bytes or record changed after the build (the server validator
    must catch it)."""
    real_build = sr.build_repaired

    def build(inputs, added):
        raw, record = real_build(inputs, added)
        return change(raw, record)
    return build


def _edit(raw: bytes, edit) -> bytes:
    st = _st(raw)
    edit(st[0])
    return st.make_mmcif_document().as_string().encode()


def _move(raw, record):
    def move(model):
        atom = next(a for c in model for r in c for a in r if a.calc_flag == gemmi.CalcFlag.NotSet)
        atom.pos = gemmi.Position(atom.pos.x + 1e-3, atom.pos.y, atom.pos.z)
    return _edit(raw, move), record


def _renumber(raw, record):
    def renumber(model):
        next(r for c in model for r in c if r.seqid.num == 273 and r.subchain == "A").seqid = gemmi.SeqId(973, " ")
    return _edit(raw, renumber), record


def _recount(raw, record):
    return raw, {**record, "counts": {**record["counts"], "added_atoms": record["counts"]["added_atoms"] - 1}}


def _drop_nz(data):
    data["added_atoms"] = [a for a in data["added_atoms"] if not (
        a["residue"]["chain_auth"] == "A" and a["residue"]["seq_auth"] == 100 and a["atom_name"] == "NZ")]


def _add_hydrogen(data):
    first = data["added_atoms"][0]
    data["added_atoms"].append({**first, "atom_name": "HZ1", "element": "H"})


def _envelope(code: str) -> dict:
    return {"reason_code": code, "message": "labelled fixture envelope", "detail": {"reason_code": code}}


CASES = [   # (label, supervise output mutation or None, error envelope or None, build hook, limits, expected)
    ("unexpected atom row", _add_hydrogen, None, None, {}, ("input_invalid", "unexpected_atoms_added")),
    ("missing A/100 NZ", _drop_nz, None, None, {}, ("input_invalid", "repair_incomplete")),
    ("moved observed atom", None, None, _move, {}, ("input_invalid", "coordinates_changed")),
    ("renumbered gap residue", None, None, _renumber, {}, ("input_invalid", "repair_identity_mismatch")),
    ("changed record", None, None, _recount, {}, ("input_invalid", "repair_record_mismatch")),
    ("record bound", None, None, None, {"MAX_RECORD_BYTES": 10_000}, ("resource_exceeded", "resource_exceeded")),
    ("worker coordinates_changed", None, _envelope("coordinates_changed"), None, {},
     ("input_invalid", "coordinates_changed")),
    ("worker repair_modeling_failed", None, _envelope("repair_modeling_failed"), None, {},
     ("input_invalid", "repair_modeling_failed")),
    ("worker repair_identity_mismatch", None, _envelope("repair_identity_mismatch"), None, {},
     ("input_invalid", "repair_identity_mismatch")),
    ("worker engine_failed", None, _envelope("engine_failed"), None, {}, ("fatal", "engine_failed")),
    ("worker resource_exceeded", None, _envelope("resource_exceeded"), None, {},
     ("resource_exceeded", "resource_exceeded")),
    ("malformed envelope", None, {"reason_code": "not_closed", "message": "x", "detail": {}}, None, {},
     ("fatal", None)),
    ("forged engine", lambda d: d["engine"].update(pdbfixer_version="1.11"), None, None, {}, ("fatal", None)),
    ("extra output key", lambda d: d.update(extra=1), None, None, {}, ("fatal", None)),
]


def test_every_closed_failure_stores_nothing_and_charges_one_unit(real, tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    seen_codes = set()
    world = None
    attempts = 0
    for label, mutate, envelope, hook, limits, (failure_class, code) in CASES:
        if world is None or attempts == 4:    # four attempts per job (retry), a fresh world after that
            world = F.world(client, f"{LABEL}, failure cases", VF6, "public_8vf6.cif")
            attempts = 0
        rid = world["rid"]
        before_state = F.store_state(root, rid)
        used = F.used(client, rid)
        raw = F.tampered(real["raw"], mutate) if mutate is not None else real["raw"]
        supervise = (F.simulated(error=envelope, returncode=1) if envelope is not None else F.simulated(raw))
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_supervise", supervise)
            if hook is not None:
                patch.setattr(sr, "build_repaired", _faulty_build(hook))
            for name, value in limits.items():
                patch.setattr(K, name, value)
            if attempts == 0:
                failed = F.run_job(client, rid, F.args(world["structure"]))
            else:
                job_id = world["job_id"]
                retried = client.post(f"/runs/{rid}/jobs/{job_id}/retry")
                assert retried.status_code == 200, retried.text
                failed = F.approve_start(client, rid, job_id).json()
        world["job_id"] = failed["job_id"]
        attempts += 1
        assert failed["status"] == "failed" and failed["output_handles"] == [], (label, failed)
        failure = failed["failure"]
        assert failure["error"] == failure_class, (label, failure)
        if code is None:
            assert "reason_code" not in failure, (label, failure)
        else:
            assert failure["reason_code"] == code and failure["detail"]["reason_code"] == code, (label, failure)
            seen_codes.add(code)
        if label == "missing A/100 NZ":
            assert failure["detail"]["m7_reason"] == "heavy_template_mismatch"
            assert (failure["detail"]["residue"]["chain_auth"], failure["detail"]["residue"]["seq_auth"]) == ("A", 100)
        assert F.store_state(root, rid) == before_state, label
        assert F.used(client, rid) == used + 1, label
    assert seen_codes == set(K.FAILURE_REASON_CODES)
    # The same genuine output for its own input publishes (the guards above were the only refusals).
    other = F.world(client, f"{LABEL}, genuine", VF6, "public_8vf6.cif")
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", F.simulated(real["raw"]))
        done = F.run_job(client, other["rid"], F.args(other["structure"]))
    assert done["status"] == "done", done
    reference = new_run(real["root"], run_id=real["world"]["rid"], dry_run=False).store.load(
        real["done"]["output_handles"][0])
    content = new_run(root, run_id=other["rid"], dry_run=False).store.load(done["output_handles"][0])
    for record in (content, reference):   # identical apart from the run-scoped handles
        record.pop("source")
        record.pop("result")
    assert content == reference


def test_a_failed_publication_leaves_the_event_log_and_objects_byte_identical(real, tmp_path, monkeypatch):
    """The publication's pure part (``prepare``) on a copy of the run (events only): each refusal leaves events.jsonl
    and the object folder exactly as they were."""
    rid = real["world"]["rid"]
    copy = tmp_path / "copy"
    (copy / rid).mkdir(parents=True)
    (copy / rid / "events.jsonl").write_bytes((real["root"] / rid / "events.jsonl").read_bytes())
    run = new_run(copy, run_id=rid, dry_run=False)
    job = JobQueue(run).get(real["done"]["job_id"])
    attempt_dir = tmp_path / "attempt"
    cases = [(_drop_nz, None, "repair_incomplete"), (_add_hydrogen, None, "unexpected_atoms_added"),
             (None, _move, "coordinates_changed"), (None, _renumber, "repair_identity_mismatch"),
             (None, _recount, "repair_record_mismatch")]
    objects = sorted(p.name for p in (copy / rid / "objects").iterdir())
    for mutate, hook, code in cases:
        before = (copy / rid / "events.jsonl").read_bytes()
        shutil.rmtree(attempt_dir, ignore_errors=True)
        attempt_dir.mkdir()
        raw = F.tampered(real["raw"], mutate) if mutate is not None else real["raw"]
        (attempt_dir / "result.json").write_bytes(raw)
        descriptor = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        with monkeypatch.context() as patch:
            if hook is not None:
                patch.setattr(sr, "build_repaired", _faulty_build(hook))
            with pytest.raises(jobs.RepairJobFailure) as caught:
                jobs.prepare(run, job, attempt_dir, descriptor)
        assert caught.value.reason_code == code
        assert (copy / rid / "events.jsonl").read_bytes() == before, code
        assert sorted(p.name for p in (copy / rid / "objects").iterdir()) == objects, code


# ----------------------------------------------------------------- real worker: timeout and cancellation
def test_timeout_and_cancel_publish_nothing_and_charge_once(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, f"{LABEL}, timeout and cancel", VF6, "public_8vf6.cif")
    rid = world["rid"]
    other = F.world(client, f"{LABEL}, timeout", VF6, "public_8vf6.cif")
    original = JobQueue._record_control
    started_pids: list[int] = []

    def cancel_on_start(self, message, job_id, attempt_id, nonce):
        result = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            started_pids.append(message["pid"])
            time.sleep(1.0)       # the worker is inside PDBFixer now
            self.request_cancel(job_id)
        return result

    try:
        before = F.store_state(root, rid)
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_record_control", cancel_on_start)
            cancelled = F.run_job(client, rid, F.args(world["structure"]))
        assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
        assert cancelled["cleanup_status"] == "verified" and F.used(client, rid) == 1 and started_pids
        assert F.store_state(root, rid) == before
        before = F.store_state(root, other["rid"])
        timed_out = F.run_job(client, other["rid"], F.args(other["structure"]), timeout_s=3)
        assert timed_out["status"] == "failed" and timed_out["output_handles"] == []
        assert timed_out["failure"]["error"] == "resource_exceeded" and timed_out["failure"]["message"] == "job timeout"
        assert timed_out["cleanup_status"] == "verified" and F.used(client, other["rid"]) == 1
        assert any(e["type"] == "job_worker_started" and e["job_id"] == timed_out["job_id"]
                   for e in F.events(root, other["rid"]))
        assert F.store_state(root, other["rid"]) == before
        time.sleep(0.1)
        F.workers_gone(root, rid)
        F.workers_gone(root, other["rid"])
    finally:
        F.kill_leftovers(root, rid)
        F.kill_leftovers(root, other["rid"])


# ----------------------------------------------------------------- the publication window, the overlay, the environment
def test_a_cancel_after_the_m7_check_stores_nothing_and_ends_cancelled(real, tmp_path, monkeypatch):
    """A cancel requested after the pure part (assembly, validator, overlay M7) and before storing is seen in the one
    critical section that stores: the job ends cancelled and the run store is unchanged (LABELLED hook: the real
    ``m7_check`` followed by a user cancel from another queue object; simulated guardian, no process)."""
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, f"{LABEL}, cancel during publication", VF6, "public_8vf6.cif")
    rid = world["rid"]
    submitted = F.submit(client, rid, F.args(world["structure"])).json()
    before = F.store_state(root, rid)
    real_m7 = jobs.m7_check
    calls = []

    def m7_then_cancel(run, objects):
        real_m7(run, objects)
        calls.append(JobQueue(new_run(root, run_id=rid, dry_run=False)).request_cancel(submitted["job_id"])["status"])

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", F.simulated(real["raw"]))
        patch.setattr(jobs, "m7_check", m7_then_cancel)
        done = F.approve_start(client, rid, submitted["job_id"]).json()
    assert calls == ["accepted"]
    assert done["status"] == "cancelled" and done["output_handles"] == [], done
    assert F.store_state(root, rid) == before and F.used(client, rid) == 1
    assert not any(e["type"] == "job_result_candidate" for e in F.events(root, rid))
    assert client.get(f"/runs/{rid}/structure_repairs").json()["rows"] == []


def _verdict(store, handle: str, seed: int) -> tuple:
    try:
        return ("pass", canonical_json(openmm_method.preflight(store, handle, seed=seed)))
    except ToolFailure as exc:
        return ("fail", exc.cls.value, exc.message, canonical_json(exc.detail))


def test_the_overlay_m7_verdict_equals_the_verdict_after_storing(real, tmp_path):
    """Check 4 runs on the read-only overlay; storing the same four objects and running M7 on the store gives the
    same verdict byte for byte, for the genuine 8VF6 output and for one with A/100 NZ removed (refused)."""
    rid = real["world"]["rid"]
    copy = tmp_path / "copy"
    (copy / rid).mkdir(parents=True)
    (copy / rid / "events.jsonl").write_bytes((real["root"] / rid / "events.jsonl").read_bytes())
    run = new_run(copy, run_id=rid, dry_run=False)
    inputs = sr.load_inputs(run.store, real["world"]["structure"])
    genuine = json.loads(real["raw"])["added_atoms"]
    broken = [a for a in genuine if not (a["residue"]["chain_auth"] == "A" and a["residue"]["seq_auth"] == 100 and
                                         a["atom_name"] == "NZ")]
    verdicts = {}
    for label, rows in (("genuine", genuine), ("without A/100 NZ", broken)):
        raw, record = sr.build_repaired(inputs, rows)
        objects = bundle.pending(run, inputs, raw, record)
        before = (copy / rid / "events.jsonl").read_bytes()
        overlay = _verdict(bundle.Overlay(run.store, objects), objects.structure, run.seed)
        assert (copy / rid / "events.jsonl").read_bytes() == before, label
        if label == "genuine":   # the job of the shared run stored exactly these objects
            assert objects.structure == real["done"]["output_handles"][1]
        else:                    # LABELLED: really store the refused objects in the copy, then run M7 on the store
            bundle.store(run, objects, "job_labelled_copy", "attempt_labelled_copy")
        stored = _verdict(run.store, objects.structure, run.seed)
        assert overlay == stored, label
        verdicts[label] = overlay
    assert verdicts["genuine"][0] == "pass"
    assert verdicts["without A/100 NZ"][0] == "fail"
    assert json.loads(verdicts["without A/100 NZ"][3])["reason_code"] == "heavy_template_mismatch"


def _unavailable_templates():
    raise sr._unavailable()


def test_an_unavailable_template_is_a_precondition_never_invalid_evidence(real, tmp_path, monkeypatch):
    """Spec 4.6: re-verifying a stored record needs the installed template XML. Without it (LABELLED hook: the core's
    template loader raises its own ``openmm_unavailable``) every read answers the 412 ``precondition`` envelope, the
    list included, and a publication fails with that precondition, storing nothing."""
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    client = F.client(root, monkeypatch)
    record_handle = done["output_handles"][0]
    before = (root / rid / "events.jsonl").read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(sr, "_templates", _unavailable_templates)
        for sub in ("", "/atoms", "/structure"):
            response = client.get(f"/runs/{rid}/structure_repairs/{record_handle}{sub}")
            assert response.status_code == 412, (sub, response.text)
            assert response.json()["error"] == "precondition"
            assert response.json()["detail"]["reason_code"] == "openmm_unavailable", sub
        listing = client.get(f"/runs/{rid}/structure_repairs")
        assert listing.status_code == 412 and listing.json()["detail"]["reason_code"] == "openmm_unavailable"
        with pytest.raises(ToolFailure) as caught:
            bundle.validated_result(new_run(root, run_id=rid, dry_run=False), record_handle)
        assert caught.value.detail["reason_code"] == "openmm_unavailable"
    assert (root / rid / "events.jsonl").read_bytes() == before
    assert client.get(f"/runs/{rid}/structure_repairs").json()["rows"][0]["valid"] is True
    # Publication: submitted while the template was readable; it becomes unreadable before the output is assembled.
    other_root = tmp_path / "runs"
    client = F.client(other_root, monkeypatch)
    other = F.world(client, f"{LABEL}, template unavailable at publication", VF6, "public_8vf6.cif")
    submitted = F.submit(client, other["rid"], F.args(other["structure"])).json()
    state = F.store_state(other_root, other["rid"])
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", F.simulated(real["raw"]))
        patch.setattr(sr, "_templates", _unavailable_templates)
        failed = F.approve_start(client, other["rid"], submitted["job_id"]).json()
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("precondition", "openmm_unavailable")
    assert F.store_state(other_root, other["rid"]) == state and F.used(client, other["rid"]) == 1
