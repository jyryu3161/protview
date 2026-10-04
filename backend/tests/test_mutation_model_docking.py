"""M21 T6: the M18 receptor source ``mutation_model`` (spec .dryforge/spec.md 7; single M18 only, M19 refuses it).

The model comes from the real M21 worker through the product job path (``mutation_model_fixture.shared_world``; public
1UBQ I44W, public structure, not experimental validation). Its run is copied here from ``events.jsonl`` alone
(events-only recovery), so the shared run stays untouched. Docking runs the REAL M18 worker
(``.deps/docking/venv-locked`` + ``.deps/qvina/env/bin/qvina2``) through POST /jobs -> approve -> start, with the
labeled synthetic phenol ``fixtures/mutation_model/synthetic-phenol-ligand.sdf`` (hand-built, not experimental; no
public ligand-bearing structure passes the M7 preflight). Tests FAIL, never skip, when an environment is absent. Engine
values are checked for shape, closed sets and reproducibility only; scores are never compared between structures.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient
from mutation_model_fixture import SIDES, shared_world

from mw import docking_bundle, docking_inputs
from mw import docking_constants as C
from mw import mutation_model_bundle as mmb
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.jobs import process_identity
from mw.workspace import new_run

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
LIGAND = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
SEED = 20261004
PARAMS = {"seed": SEED, "exhaustiveness": 4, "num_modes": 5}
TWELFTH = ("수용체는 변이 모델링으로 최소화한 구조이며 리간드 자세는 이 수용체에 맞춰 조정하지 않았다"
           "(리간드 좌표는 사용자가 준 SDF 그대로).")
LEGACY_KEYS = ("receptor_handle", "receptor_model_number", "connectivity", "receptor_instance")


# ----------------------------------------------------------------- helpers
def _copy(world: dict, root: Path) -> None:
    """Events-only copy of the shared model run (no object files, no attempt directories)."""
    (root / world["rid"]).mkdir(parents=True)
    shutil.copyfile(world["root"] / world["rid"] / "events.jsonl", root / world["rid"] / "events.jsonl")
    new_run(root, run_id=world["rid"], dry_run=False)


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def _kill_leftovers(root: Path, rid: str) -> None:
    for event in _events(root, rid):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
            except psutil.Error:
                pass


def _import_sdf(client: TestClient, rid: str) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": "ligand_sdf", "filename": "phenol.sdf"},
                           content=LIGAND, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    return response.json()["handle"]


def _source(model: str, side: str) -> dict:
    return {"kind": "mutation_model", "mutation_model": model, "side": side}


def _args(source: dict | None, sdf: str, **extra) -> dict:
    out = {"ligand": {"source": "sdf", "sdf_handle": sdf}, "mode": "free",
           "box": {"source": "ligand_range", "margin_A": 8}, "parameters": dict(PARAMS), "acknowledgement": ACK}
    if source is not None:
        out["receptor_source"] = source
    out.update(extra)
    return out


def _submit(client: TestClient, rid: str, args: dict, protocol: str = "qvina_dock_v1"):
    return client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args, "timeout_s": 600})


def _run_job(client: TestClient, rid: str, args: dict) -> dict:
    submitted = _submit(client, rid, args)
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    started = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
    assert started.status_code == 200, started.text
    return started.json()


def _reason(response) -> str:
    assert response.status_code == 422, response.text
    return response.json()["detail"]["reason_code"]


# ----------------------------------------------------------------- the docked world (built once per module)
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


@pytest.fixture(scope="module")
def docked(world, tmp_path_factory):
    root = tmp_path_factory.mktemp("m21_docking") / "runs"
    _copy(world, root)
    rid = world["rid"]
    saved = api_module.RUNS_DIR
    patch = pytest.MonkeyPatch()
    try:
        client = _client(root, patch)
        sdf = _import_sdf(client, rid)
        jobs = {side: _run_job(client, rid, _args(_source(world["model"], side), sdf)) for side in SIDES}
        return {"root": root, "rid": rid, "sdf": sdf, "jobs": jobs}
    finally:
        _kill_leftovers(root, rid)
        patch.undo()
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()


@pytest.fixture
def client(docked, monkeypatch):
    return _client(docked["root"], monkeypatch)


def _run(docked):
    return api_module._run(docked["rid"])


# ----------------------------------------------------------------- pure argument rules
def test_receptor_source_replaces_the_four_receptor_keys():
    normalized = docking_inputs.validate_arguments(_args(_source("h", "mutant"), "sdf"))
    assert normalized["receptor_source"] == _source("h", "mutant")
    assert not set(LEGACY_KEYS) & set(normalized)
    legacy = {"receptor_handle": "r", "receptor_model_number": 1,
              "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
              **_args(None, "sdf")}
    assert set(docking_inputs.validate_arguments(legacy)) == {*LEGACY_KEYS, "ligand", "mode", "box", "parameters",
                                                              "acknowledgement"}
    # the source joins the call key: two sides never share an input hash
    assert docking_inputs.input_sha256(normalized) != docking_inputs.input_sha256(
        docking_inputs.validate_arguments(_args(_source("h", "wild_type_reference"), "sdf")))


@pytest.mark.parametrize("change,reason", [
    ({"receptor_handle": "r"}, "invalid_job_arguments"),                        # both sources
    ({"receptor_instance": None}, "invalid_job_arguments"),                     # a legacy key next to the source
    ({"connectivity": {"kind": "pdb_conect", "sidecar_handle": None}}, "invalid_job_arguments"),
    ({"receptor_model_number": 1}, "invalid_job_arguments"),
    ({"receptor_source": {"kind": "import", "mutation_model": "h", "side": "mutant"}}, "invalid_job_arguments"),
    ({"receptor_source": {"kind": "mutation_model", "mutation_model": "h"}}, "invalid_job_arguments"),
    ({"receptor_source": None}, "invalid_job_arguments"),
    ({"receptor_source": _source("h", "wild_type")}, "mutation_model_invalid"),
    ({"receptor_source": _source("", "mutant")}, "mutation_model_invalid"),
    ({"receptor_source": _source(7, "mutant")}, "mutation_model_invalid"),
    ({"box": {"source": "instance_range", "margin_A": 8}}, "box_invalid"),
    ({"acknowledgement": {**ACK, "rigid_no_optimization": False}}, "acknowledgement_missing"),
])
def test_receptor_source_argument_refusals(change, reason):
    args = {**_args(_source("h", "mutant"), "sdf"), **change}
    with pytest.raises(ToolFailure) as caught:
        docking_inputs.validate_arguments(args)
    assert caught.value.detail["reason_code"] == reason


def test_neither_source_is_refused_as_missing_keys():
    with pytest.raises(ToolFailure) as caught:
        docking_inputs.validate_arguments(_args(None, "sdf"))
    assert caught.value.detail["reason_code"] == "invalid_job_arguments"


def test_twelfth_sentence_only_for_the_mutation_model_source():
    legacy = C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                      unspecified_stereo_centers=None)
    assert legacy == C.LIMITATIONS[:6] and TWELFTH not in legacy
    new = C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                   unspecified_stereo_centers=None, receptor_source="mutation_model")
    assert new == (*legacy, TWELFTH) and C.LIMITATIONS[11] == TWELFTH and len(C.LIMITATIONS) == 12
    for kwargs in ({"receptor_source": "import"}, {"receptor_source": "mutation_model", "removed_instance": True}):
        with pytest.raises(ValueError):
            C.applicable_limitations(**{"mode": "free", "source": "sdf", "removed_instance": False,
                                        "unspecified_stereo_centers": None, **kwargs})
    assert "mutation_model_invalid" in C.ADMISSION_ONLY_REASONS and "mutation_model_invalid" not in C.REASONS


# ----------------------------------------------------------------- real docking on both sides
def test_both_sides_dock_for_real_with_the_source_shape(docked, world, client):
    run = _run(docked)
    model = mmb.validated_result(run, world["model"])
    submitted = {e["job"]["job_id"]: e["job"] for e in _events(docked["root"], docked["rid"])
                 if e["type"] == "job_submitted"}
    for side in SIDES:
        job = docked["jobs"][side]
        assert job["status"] == "done", job
        record = submitted[job["job_id"]]
        assert record["parameters"]["receptor_source"] == _source(world["model"], side)
        assert not set(LEGACY_KEYS) & set(record["parameters"])
        assert record["input_handles"] == [world["model"], docked["sdf"]]
        assert record["selected"]["sidecar"] is None and "receptor_source" in record["selected"]
        content = docking_bundle.validated_result(run, job["output_handles"][0])
        assert content["inputs"]["receptor"] == {
            "source": _source(world["model"], side), "sha256": model["structures"][side]["structure_sha256"],
            "model_number": 1, "connectivity": {"kind": "mutation_model_topology"}, "removed_instance": None,
            "acknowledgement": ACK}
        assert content["limitations"][-1] == TWELFTH
        assert content["limitations"] == [*C.LIMITATIONS[:6], TWELFTH]
        assert content["counts"]["modes"] > 0 and content["parameters"]["seed"] == SEED
        # contacts name heavy atoms of the stored model structure of this side (residue fields, atom names)
        names = {(json.dumps(a["residue"], sort_keys=True), a["atom_name"])
                 for a in model["structures"][side]["atom_mapping"]}
        for mode in content["modes"]:
            for contact in mode["contacts"]:
                atom = contact["receptor_atom"]
                assert (json.dumps(atom["residue"], sort_keys=True), atom["atom_name"]) in names
        listed = client.get(f"/runs/{docked['rid']}/docking/results", params={"offset": 0, "limit": 50})
        assert listed.status_code == 200, listed.text
        row = next(r for r in listed.json()["rows"] if r["handle"] == job["output_handles"][0])
        assert row["valid"] is True and row["receptor_handle"] is None
    first, second = (docked["jobs"][side]["output_handles"][0] for side in SIDES)
    assert first != second


def test_same_input_returns_the_same_job_and_handle(docked, world, client):
    used = client.get(f"/runs/{docked['rid']}/budget").json()["expensive_calls"]["used"]
    again = _submit(client, docked["rid"], _args(_source(world["model"], "mutant"), docked["sdf"]))
    assert again.status_code == 200, again.text
    assert again.json()["job_id"] == docked["jobs"]["mutant"]["job_id"]
    assert again.json()["output_handles"] == docked["jobs"]["mutant"]["output_handles"]
    assert client.get(f"/runs/{docked['rid']}/budget").json()["expensive_calls"]["used"] == used


def test_same_seed_twice_gives_identical_results(docked, world, tmp_path, monkeypatch):
    """Reproducibility: a second events-only copy of the same run docks again (new worker process, same seed)."""
    root = tmp_path / "runs"
    _copy(world, root)
    client = _client(root, monkeypatch)
    try:
        sdf = _import_sdf(client, world["rid"])
        assert sdf == docked["sdf"]
        again = _run_job(client, world["rid"], _args(_source(world["model"], "mutant"), sdf))
    finally:
        _kill_leftovers(root, world["rid"])
    assert again["status"] == "done", again
    handle = docked["jobs"]["mutant"]["output_handles"][0]
    assert again["output_handles"] == [handle]
    first = docking_bundle.validated_result(_run(docked), handle)
    second = docking_bundle.validated_result(api_module._run(world["rid"]), handle)
    assert canonical_json(first) == canonical_json(second)


# ----------------------------------------------------------------- admission refusals (no job, no budget)
def test_admission_refusals_start_nothing(docked, world, client):
    rid = docked["rid"]
    run = _run(docked)
    model = mmb.validated_result(run, world["model"])
    before = len(_events(docked["root"], rid))
    used = client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"]
    legacy = {"receptor_handle": docked["sdf"], "receptor_model_number": 1,
              "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None}
    cases = [
        (_args(_source(world["model"], "mutant"), docked["sdf"], **legacy), "invalid_job_arguments"),
        (_args(None, docked["sdf"]), "invalid_job_arguments"),
        (_args(_source(world["model"], "mutant"), docked["sdf"], receptor_instance=None), "invalid_job_arguments"),
        (_args(_source(world["model"], "wild"), docked["sdf"]), "mutation_model_invalid"),
        (_args(_source(world["other_model"], "mutant"), docked["sdf"]), "mutation_model_invalid"),     # other run
        (_args(_source(world["candidate_set"], "mutant"), docked["sdf"]), "mutation_model_invalid"),   # wrong kind
        (_args(_source(world["structure"], "mutant"), docked["sdf"]), "mutation_model_invalid"),
        (_args(_source(model["structures"]["mutant"]["structure_object"], "mutant"), docked["sdf"]),
         "mutation_model_invalid"),
        (_args(_source(docked["jobs"]["mutant"]["output_handles"][0], "mutant"), docked["sdf"]),
         "mutation_model_invalid"),
    ]
    for args, reason in cases:
        assert _reason(_submit(client, rid, args)) == reason, args
    assert len(_events(docked["root"], rid)) == before
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == used


def test_receptor_atom_limit_is_a_clear_admission_refusal(docked, world, client, monkeypatch):
    """The M18 10,000-atom receptor limit (hydrogens included) applies unchanged; lowered here (labeled test hook)
    below the I44W model's atom count to show the refusal is ``receptor_invalid`` before any job."""
    atoms = len(mmb.validated_result(_run(docked), world["model"])["structures"]["mutant"]["atom_mapping"])
    monkeypatch.setattr(C, "MAX_RECEPTOR_ATOMS", atoms - 1)
    response = _submit(client, docked["rid"], _args(_source(world["model"], "mutant"), docked["sdf"],
                                                    parameters={**PARAMS, "seed": 7}))
    assert _reason(response) == "receptor_invalid"
    assert f"receptor atom count must be 1-{atoms - 1}" in response.text


def test_m19_batch_refuses_the_receptor_source_key(docked, world, client):
    args = {"receptor_source": _source(world["model"], "mutant"), "candidate_set_handle": "x",
            "parent_sdf_handle": docked["sdf"], "candidate_ids": ["c1"], "mode": "free",
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": dict(PARAMS), "acknowledgement": ACK}
    assert _reason(_submit(client, docked["rid"], args, "qvina_batch_dock_v1")) == "invalid_job_arguments"


# ----------------------------------------------------------------- the carboxylate relaxation is source-bound
def test_imported_free_c_terminus_receptor_is_still_refused(docked, world, client):
    """The same stored mutant mmCIF and the same OpenMM bonds, imported as an ordinary receptor + sidecar: the M18
    check (C=O double on every residue) is unchanged, so the C-terminal carboxylate is ``receptor_prep_failed``."""
    rid = docked["rid"]
    run = _run(docked)
    entry = mmb.validated_result(run, world["model"])["structures"]["mutant"]
    raw = mmb.structure_bytes(run, world["model"], "mutant")
    receptor = client.post(f"/runs/{rid}/chemical/imports", params={"kind": "receptor", "filename": "i44w.cif"},
                           content=raw, headers={"content-type": "application/octet-stream"})
    assert receptor.status_code == 201, receptor.text
    handle = receptor.json()["handle"]
    atoms = entry["atom_mapping"]

    def ref(index: int) -> dict:     # built here from atom_mapping, independently of the server helper
        atom = atoms[index]
        return {"structure_handle": handle, "residue": atom["residue"], "atom_name": atom["atom_name"],
                "altloc": "", "element": atom["element"], "site_index": index}

    sidecar_raw = json.dumps({"schema": "receptor_bonds@1", "complete": True, "source_handle": handle,
                              "bonds": [{"first": ref(a), "second": ref(b)} for a, b in entry["final_bonds"]]}).encode()
    sidecar = client.post(f"/runs/{rid}/chemical/imports", params={"kind": "receptor_bonds", "filename": "b.json"},
                          content=sidecar_raw, headers={"content-type": "application/octet-stream"})
    assert sidecar.status_code == 201, sidecar.text
    args = {"receptor_handle": handle, "receptor_model_number": 1,
            "connectivity": {"kind": "sidecar", "sidecar_handle": sidecar.json()["handle"]},
            "receptor_instance": None, **_args(None, docked["sdf"])}
    try:
        failed = _run_job(client, rid, args)
    finally:
        _kill_leftovers(docked["root"], rid)
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    assert failed["failure"]["reason_code"] == "receptor_prep_failed", failed
    assert "backbone inferred bond order invalid" in failed["failure"]["message"]


# ----------------------------------------------------------------- report
def test_report_names_the_mutation_model_source(docked, world, client):
    rid = docked["rid"]
    for side in SIDES:
        handle = docked["jobs"][side]["output_handles"][0]
        created = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
        assert created.status_code == 201, created.text
        manifest, markdown = created.json()["manifest"], created.json()["markdown"]
        lines = markdown.split("\n")
        source_line = [line for line in lines if line.startswith("- 출처: 변이 모델링 구조")]
        assert len(source_line) == 1 and side.replace("_", "\\_") in source_line[0]
        assert world["model"].replace("_", "\\_") in source_line[0]
        assert not any(line.startswith("- 가져오기:") for line in lines)
        assert "- 연결 정보: mutation\\_model\\_topology" in lines
        assert TWELFTH in lines and lines.index(TWELFTH) > lines.index(C.LIMITATIONS[5])
        assert f"- 점수 이름: {C.SCORE_LABEL}" in lines
        assert manifest["inputs"]["receptor"]["source"] == _source(world["model"], side)
        assert "inputs.receptor.handle" not in {claim["field_path"] for claim in manifest["claims"]}
        reopened = client.get(f"/runs/{rid}/reports/selected", params={"handle": created.json()["handle"]})
        assert reopened.status_code == 200, reopened.text
