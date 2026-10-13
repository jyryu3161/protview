"""M29 T6: a repaired structure is refused outside the modeling path (spec .dryforge/spec.md 5.1, 5.2; plan T6).

Every refusal target of spec 5.2 and of the T1 inventory is sent a real repaired structure through the HTTP API (FastAPI
TestClient on 127.0.0.1; no port is opened) and answers 422 ``input_invalid`` with ``detail.reason_code``
``repaired_structure_not_accepted`` and the fixed message, before any engine, job, budget or object: the run only gains
the ``proposal_rejected`` record of each refused ``Run.call`` (the record every refused tool call gets). The same
requests with the original prepared structure are not refused, and the modeling path (M20 tool, M21 admission) and the
reads (structure residues, bytes, atoms, PDB ID hint, object meta) are not refused. The places that take no structure
handle themselves are blocked upstream (declared in ``test_structure_repair_consumers.py``): M27 reads only a numbering
map and ``map_residue_numbering`` refuses; viewer intents and session state need a refused session; ``/method_reports``
takes results that the refused tools and jobs make.

Inputs (labelled): public 1HSG prepared by the product tools, and its repaired structure built by T4's splice builder
from the PDBFixer-measured addition fixture (``fixtures/structure_repair/1hsg-additions.pdbfixer-measured.json``),
stored in the spec order (coordinates -> record -> manifest -> structure) as T7's hand-off tests do (T5 owns the job
publication path). A SYNTHETIC ``residue_numbering_map@1`` stub (labelled in its content) stands in for a numbering map
of the repaired structure, which ``map_residue_numbering`` can no longer make. No ``.deps`` is needed: every refusal
happens before fpocket, ProLIF, a reference set or the OpenMM preflight would be used.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw import structure_repair_jobs as RJ
from mw.api import app as api_module
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import ApprovalRequired

FIX = Path(__file__).parent / "fixtures"
SR_FIX = FIX / "structure_repair"
CAMERA = {"mode": "perspective", "fov": 0.8, "position": [1.0, 2.0, 40.0], "target": [0.0, 0.0, 0.0],
          "up": [0.0, 1.0, 0.0], "radius": 10.0, "radiusMax": 20.0, "fog": 50.0, "clipFar": True, "minNear": 0.0,
          "minFar": 0.0}
ACK = {"schema": "chemical_preparation_ack@1", "supplied_graph_complete": True, "supplied_hydrogens_complete": True,
       "use_supplied_protonation_tautomer": True, "infer_receptor_orders_charges": True, "description": "M29 T6",
       "ph_annotation": None}
STUB_LABEL = "SYNTHETIC M29 T6 stub: a numbering map whose structure is the repaired one (no product tool made it)"


def _command(client: TestClient, rid: str, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _simulated_worker(additions: list[dict]):
    """LABELLED SIMULATED GUARDIAN (as in T7's hand-off tests): writes a worker output whose ``added_atoms`` are the
    PDBFixer-measured ``additions`` for the job's own method record and reports a clean RESULT; no process is launched."""
    def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        fixed = sr.fixed_method()
        output = {"schema": RJ.OUTPUT_SCHEMA, "method": job["method"]["method"],
                  "engine": {key: fixed[key] for key in RJ.ENGINE_KEYS}, "added_atoms": additions,
                  "diagnostics": {"simulated_guardian": "M29 T6 test, no PDBFixer run"}}
        raw = json.dumps(output, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        (attempt_dir / "result.json").write_bytes(raw)
        return {"kind": "RESULT", "reason": "completed", "returncode": 0, "clean": True, "direct_child_reaped": True,
                "unexpected_members": False,
                "payload": {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}}, None
    return supervise


def _store_repaired(run: Any, prepared: str) -> str:
    """The repaired structure of ``prepared`` published by the product repair job (T5), with the measured 1HSG
    additions through a labelled simulated guardian: reads, reports and the M20 admission need the publication."""
    additions = json.loads((SR_FIX / "1hsg-additions.pdbfixer-measured.json").read_text())["added_atoms"]
    queue = JobQueue(run)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", _simulated_worker(additions))
        job = queue.submit(K.PROTOCOL, {"structure": prepared, "repair_policy": K.REPAIR_POLICY}, timeout_s=240)
        try:
            done = queue.start(job["job_id"])
        except ApprovalRequired:
            run.approve("expensive_first_call", by="test")
            done = queue.start(job["job_id"])
    assert done["status"] == "done", done
    return done["output_handles"][1]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setattr(api_module, "RUNS_DIR", tmp_path_factory.mktemp("m29_t6_refusals"))
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    try:
        rid = client.post("/runs", json={"goal": "M29 T6 default refusal"}).json()["run_id"]
        uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": "1hsg.cif"},
                               content=(FIX / "public_1hsg.cif").read_bytes())
        assert uploaded.status_code == 201, uploaded.text
        source = _command(client, rid, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
        original = _command(client, rid, "prepare_structure", {
            "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
            "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
        run = api_module.RUNS[rid]
        repaired = _store_repaired(run, original)
        ligands = client.get(f"/runs/{rid}/structures/residues", params={"handle": original}).json()["ligands"]
        assert len(ligands) == 1 and ligands[0]["resname"] == "MK1", ligands
        stubs = {handle: run.store.put("residue_numbering_map", "residue_numbering_map@1", {
            "schema": "residue_numbering_map@1", "label": STUB_LABEL, "structure": {"handle": handle}},
            produced_by="test").handle for handle in (original, repaired)}
        yield {"client": client, "rid": rid, "run": run, "original": original, "repaired": repaired,
               "ligand": ligands[0], "stubs": stubs, "root": api_module.RUNS_DIR}
    finally:
        api_module.RUNS.clear()
        patch.undo()


# --- the refusal targets: (name, request) with the structure handle as the variable --------------------------------

def _commands(w: dict, s: str) -> list[tuple[str, dict]]:
    """``Run.call`` targets (POST /commands): refused by ``Run._validated_bound`` (M16: by its pre-check)."""
    other, ligand = w["original"], w["ligand"]
    atom = {"structure_handle": s, "residue": ligand, "atom_name": "C1", "altloc": ""}
    return [
        ("compute_interactions", {"structure": s, "ligand": ligand, "cutoff_A": 4.0}),
        ("compute_interface_sasa", {"structure": s, "ligand": ligand}),
        ("measure_distance", {"structure": s, "first": atom, "second": atom}),
        ("align_structures", {"reference": s, "moving": other, "pairs": []}),
        ("align_structures", {"reference": other, "moving": s, "pairs": []}),
        ("compile_state", {"inputs": [other, s]}),
        ("map_residue_numbering", {"structure": s, "pdb_id": "1HSG", "chains": [
            {"chain_auth": "A", "uniprot_accession": None}]}),
        ("link_reaction_knowledge", {"structure": s, "pdb_id": "1HSG", "chains": [
            {"chain_auth": "A", "uniprot_accession": None}]}),
        ("annotate_reference_sites", {"numbering_map": w["stubs"][s], "contacts": None}),
    ]


def _routes(w: dict, s: str) -> list[tuple[str, str, str, dict]]:
    """(name, method, path, json body | query params) of the HTTP refusal targets other than POST /commands."""
    ids = {"client_instance_id": str(uuid.uuid4()), "viewer_session_id": str(uuid.uuid4()), "scene_generation": 1,
           "action_revision": 0, "request_id": str(uuid.uuid4())}
    view = {"structure_handle": s, "selection": None, "representation": "cartoon", "camera": CAMERA, "theme": "dark"}
    attach = {"schema": "chemical_prepare_request@1", "mode": "attach_existing", "complex_handle": s,
              "complex_model_number": 1}
    strict = {**attach, "selected_ligand": None, "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
              "ligand_sdf_handle": "obj://none", "sdf_record_index": 0, "hydrogen_policy": "map_existing",
              "mapping": [], "terminal_extensions": [], "acknowledgement": dict(ACK)}
    m7 = {"structure": s, "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    return [
        ("M7 preflight read", "GET", "/jobs/preflight", {"structure": s}),
        ("M7 minimization job", "POST", "/jobs", {"protocol_id": "openmm_protein_minimize", "args": m7}),
        ("PyRosetta relax job", "POST", "/jobs", {"protocol_id": "relax", "args": {"structure": s}}),
        ("PyRosetta interface_analyzer job", "POST", "/jobs",
         {"protocol_id": "interface_analyzer", "args": {"structure": s, "interface": "A_B"}}),
        ("M12 pocket preflight read", "GET", "/pockets/preflight", {"structure": s}),
        ("M12 fpocket job", "POST", "/jobs", {"protocol_id": "fpocket_detect_v1",
                                              "args": {"structure": s, "chains": None}}),
        ("M11 preview", "POST", "/chemical/preview", attach),
        ("M11 prolif_prepare_v1 job", "POST", "/jobs", {"protocol_id": "prolif_prepare_v1", "args": strict}),
        ("viewer session", "POST", "/viewer/sessions", {"client_instance_id": ids["client_instance_id"],
                                                         "scene_generation": 1, "structure_handle": s}),
        ("saved view", "POST", "/viewer/scenes", {"schema": "viewer_scene@1", "name": "view", **view, **ids}),
        ("figure", "POST", "/viewer/figures", {
            "schema": "viewer_figure@1", "scene_handle": f"obj://{w['rid']}/viewer_scene/{'0' * 64}", **view,
            "png_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(), **ids}),
        ("inspection report", "POST", "/reports", {
            "interaction_handle": f"obj://{w['rid']}/interaction_set/{'0' * 64}", "prepared_handle": s}),
        ("inspect_complex pipeline", "POST", "/inspect_complex", {"input_handle": s, "ligand": w["ligand"]}),
        ("M13 analysis plan", "POST", "/analysis/plans", {
            "request_id": str(uuid.uuid4()), "goal": "inspect_ligand",
            "inputs": {"source": s, "ligand": w["ligand"], "cutoff_A": 4.0, "types": ["contact"]}}),
    ]


def _send(w: dict, method: str, path: str, value: dict):
    url = f"/runs/{w['rid']}{path}"
    return (w["client"].get(url, params=value) if method == "GET" else w["client"].post(url, json=value))


def _refused(response) -> bool:
    if response.status_code != 422:
        return False
    body = response.json()
    return (body.get("error"), body.get("message"), body.get("detail")) == (
        "input_invalid", K.REPAIRED_NOT_ACCEPTED_MESSAGE, {"reason_code": K.REPAIRED_NOT_ACCEPTED})


def _state(w: dict) -> dict:
    client, rid = w["client"], w["rid"]
    events = [json.loads(line) for line in (w["root"] / rid / "events.jsonl").read_text().splitlines()]
    return {"events": events, "objects": sorted(path.name for path in (w["root"] / rid / "objects").iterdir()),
            "jobs": client.get(f"/runs/{rid}/jobs").json(), "budget": client.get(f"/runs/{rid}/budget").json(),
            "plans": client.get(f"/runs/{rid}/analysis/plans").json(),
            "scenes": client.get(f"/runs/{rid}/viewer/scenes").json(),
            "reports": client.get(f"/runs/{rid}/reports").json()}


# --- tests ----------------------------------------------------------------------------------------------------------

def test_every_refusal_target_refuses_the_repaired_structure_with_one_code_and_records_nothing(world):
    repaired = world["repaired"]
    before = _state(world)
    names = []
    for tool, args in _commands(world, repaired):
        response = world["client"].post(f"/runs/{world['rid']}/commands", json={"tool": tool, "args": args})
        assert _refused(response), (tool, response.status_code, response.text)
        names.append(tool)
    for name, method, path, value in _routes(world, repaired):
        response = _send(world, method, path, value)
        assert _refused(response), (name, response.status_code, response.text)
        names.append(name)
    after = _state(world)
    assert len(names) == 23
    # no object, job, expensive or external budget unit, plan, view or report
    for key in ("objects", "jobs", "plans", "scenes", "reports"):
        assert after[key] == before[key], key
    assert ({axis: value for axis, value in after["budget"].items() if axis != "wall_clock_s"} ==
            {axis: value for axis, value in before["budget"].items() if axis != "wall_clock_s"})
    # the only new events are what every refused Run.call records: its proposal_rejected and the owner's runtime
    # overhead (wall_charged), which is also the only wall-clock change
    added = after["events"][len(before["events"]):]
    assert after["events"][:len(before["events"])] == before["events"]
    rejected = [event for event in added if event["type"] == "proposal_rejected"]
    charged = [event for event in added if event["type"] == "wall_charged"]
    assert len(rejected) + len(charged) == len(added)
    assert {event["reason"] for event in charged} <= {"runtime_overhead"}
    assert [(event["tool"], event["error"], event["detail"]) for event in rejected] == [
        (tool, "input_invalid", {"reason_code": K.REPAIRED_NOT_ACCEPTED}) for tool, _args in _commands(world, repaired)]
    assert after["budget"]["wall_clock_s"]["used"] == pytest.approx(
        before["budget"]["wall_clock_s"]["used"] + sum(event["seconds"] for event in charged))


def test_the_original_structure_reaches_past_every_guard(world):
    """The same requests with the original prepared structure are never this refusal (their own outcomes are the
    existing behaviour, kept by the existing tests of each lane)."""
    original = world["original"]
    # outcomes that need no engine, reference set or approval (the others depend on the installed environment)
    expected = {"compute_interactions": 200, "compile_state": 200, "M12 pocket preflight read": 200,
                "viewer session": 201, "inspect_complex pipeline": 200, "M13 analysis plan": 201}
    for tool, args in _commands(world, original):
        if tool == "annotate_reference_sites":
            continue   # the SYNTHETIC stub is no valid map; the M16 tests keep the tool's behaviour
        response = world["client"].post(f"/runs/{world['rid']}/commands", json={"tool": tool, "args": args})
        assert not _refused(response) and K.REPAIRED_NOT_ACCEPTED not in response.text, (tool, response.text)
        assert response.status_code == expected.get(tool, response.status_code), (tool, response.text)
    for name, method, path, value in _routes(world, original):
        response = _send(world, method, path, value)
        assert not _refused(response) and K.REPAIRED_NOT_ACCEPTED not in response.text, (name, response.text)
        assert response.status_code == expected.get(name, response.status_code), (name, response.text)
    pocket = _send(world, "GET", "/pockets/preflight", {"structure": original})
    assert pocket.json()["schema"] == "pocket_input_preflight@1" and pocket.json()["reject"] is None


def test_the_modeling_path_and_the_reads_take_the_repaired_structure(world):
    client, rid, repaired = world["client"], world["rid"], world["repaired"]
    for path, params in (("/structures/residues", {"handle": repaired}), ("/structures/bytes", {"handle": repaired}),
                         ("/structures/atoms", {"handle": repaired}), ("/objects/meta", {"handle": repaired}),
                         ("/reference/pdb_id_hint", {"structure": repaired})):
        response = client.get(f"/runs/{rid}{path}", params=params)
        assert response.status_code == 200, (path, response.text)
    # the repair lane answers with its own closed admission reason, not this refusal (spec 4.2)
    preflight = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": repaired}).json()
    assert preflight["admission"]["reason_code"] == "already_repaired"
    # M20 receives it (spec 5.1); its candidate set enters M21 admission (the M7 preflight there passes)
    candidate_set = _command(client, rid, "generate_mutation_candidates", {
        "structure": repaired, "sources": {"pocket": None, "ligand_shell": None, "residues": [
            {"model_number": 1, "chain_auth": "A", "seq_auth": 25, "icode": "", "resname": "ASP"}]}})
    assert client.get(f"/runs/{rid}/objects/meta", params={"handle": candidate_set}).json()["kind"] == \
        "mutation_candidate_set"
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "openmm_mutation_model_v1", "args": {
        "candidate_set": candidate_set, "candidate_index": 0, "seed": 0, "selection_policy": "protein_only",
        "hydrogen_policy": "rebuild_pH7"}, "timeout_s": 120})
    assert submitted.status_code == 200 and submitted.json()["status"] == "queued", submitted.text
    cancelled = client.post(f"/runs/{rid}/jobs/{submitted.json()['job_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
