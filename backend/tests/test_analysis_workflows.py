"""M13 analysis plans: checked-in templates, strict inputs, prerequisites, admission and zero science."""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mw import analysis_executions as ax
from mw import analysis_plans, chemical_reports, comparison_reports, method_reports, openmm_reports, pocket_reports
from mw import reports as inspection_reports
from mw.api import app as api_module
from mw.chemical_inputs import _bonds, _sdf_records, _source_rows, import_raw, preview, receptor_atoms
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools import openmm_method, sasa
from mw.tools.comparison import atom_rows
from mw.tools.structural import structure_residues

FIX = Path(__file__).parent / "fixtures"
CHEM = FIX / "chemical"
M10 = Path(__file__).parents[2] / "frontend/tests/offscreen/fixtures"
PREP = {"altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip"}
ACK = {"schema": "chemical_preparation_ack@1", "supplied_graph_complete": True,
       "supplied_hydrogens_complete": True, "use_supplied_protonation_tautomer": True,
       "infer_receptor_orders_charges": True, "description": "public ProLIF fixture", "ph_annotation": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _new(client: TestClient, dry_run: bool = False) -> tuple[str, Run]:
    rid = client.post("/runs", json={"goal": "m13 plans", "dry_run": dry_run}).json()["run_id"]
    return rid, api_module._run(rid)


def _load(run: Run, path: Path) -> str:
    fmt = path.suffix.lstrip(".")
    return run.call("load_structure", {"source": path.name, "model_index": 0}, source_bytes=path.read_bytes(),
                    source_format=fmt).handle


def _prepare(run: Run, handle: str) -> str:
    return run.call("prepare_structure", {"structure": handle, **PREP}).handle


def _post(client: TestClient, rid: str, goal: str, inputs: dict, request_id: str | None = None):
    return client.post(f"/runs/{rid}/analysis/plans",
                       json={"request_id": request_id or str(uuid.uuid4()), "goal": goal, "inputs": inputs})


def _ok(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def _codes(body: dict) -> list[str]:
    return [item["code"] for item in body["plan"]["unmet_prerequisites"]]


def _ligand(run: Run, handle: str) -> dict:
    ligands = structure_residues(run.store, handle)["ligands"]
    assert len(ligands) == 1  # mini_complex has exactly one organic ligand instance (LIG B 301)
    return ligands[0]


def _atom(catalog: dict, seq: int, name: str, alt: str = "") -> dict:
    return next(row["ref"] for row in catalog["rows"] if row["ref"]["residue"]["seq_auth"] == seq
                and row["ref"]["atom_name"] == name and row["ref"]["altloc"] == alt)


def _pairs(ref: dict, mov: dict) -> list[dict]:
    return [{"reference": _atom(ref, seq, "CA", alt), "moving": _atom(mov, seq, "CA", alt)}
            for seq, alt in [(10, "A"), (11, ""), (12, ""), (13, "")]]


def _create_new_request(run: Run) -> dict:
    receptor = import_raw(run.store, "receptor", "rec.pdb", (CHEM / "prolif-vina-rec.pdb").read_bytes())
    ligand = import_raw(run.store, "ligand_sdf", "lig.sdf", (CHEM / "prolif-vina-output.sdf").read_bytes())
    request = {"schema": "chemical_prepare_request@1", "mode": "create_new",
               "receptor_input_handle": receptor["handle"], "receptor_model_number": 1,
               "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
               "ligand_sdf_handle": ligand["handle"], "sdf_record_index": 0,
               "ligand_instance": {"model_number": 1, "chain_auth": "L", "chain_label": None, "seq_auth": 1,
                                   "seq_label": None, "icode": "", "resname": "LIG"},
               "terminal_extensions": [], "acknowledgement": dict(ACK)}
    first = preview(run.store, request)
    request["terminal_extensions"] = [{"residue": item["residue"], "atom_names": item["atom_names"],
                                       "approve_supplied_graph": True} for item in first["terminal_extensions"]]
    assert preview(run.store, request, strict=True)["ready"]
    return request


def _attach_request(run: Run) -> dict:
    """Same construction as test_chemical_interactions (public ProLIF fixture, ligand appended as HETATM)."""
    receptor = (CHEM / "prolif-vina-rec.pdb").read_text()
    sdf = (CHEM / "prolif-vina-output.sdf").read_bytes()
    lig_atoms = _sdf_records(sdf.decode())[0]["atoms"]
    appended = []
    for i, atom in enumerate(lig_atoms):
        x, y, z = atom["coordinate_A"]
        appended.append(f'HETATM{4989 + i:5d} {f"X{i + 1}":<4s} LIG L   1    '
                        f'{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{0.00:6.2f}'
                        f'          {atom["element"].upper():>2s}  ')
    combined = (receptor.split("CONECT")[0] + "\n".join(appended) + "\nEND\n").encode()
    raw_source = run.store.put("structure_source", "structure_source@1", combined, fmt="pdb")
    complex_source = run.store.put("structure", "structure_selection@2",
                                   {"source": raw_source.handle, "format": "pdb", "model_index": 0})
    ligand = import_raw(run.store, "ligand_sdf", "lig.sdf", sdf)
    original = import_raw(run.store, "receptor", "rec.pdb", receptor.encode())
    original_rows = receptor_atoms(run.store, original["handle"], 1)
    original_bonds = _bonds(run.store, {"connectivity": {"kind": "pdb_conect", "sidecar_handle": None}},
                            original_rows, receptor.encode(), original["handle"])
    request = {"schema": "chemical_prepare_request@1", "mode": "attach_existing",
               "complex_handle": complex_source.handle, "complex_model_number": 1,
               "selected_ligand": {"model_number": 1, "chain_auth": "L", "chain_label": None, "seq_auth": 1,
                                   "seq_label": None, "icode": "", "resname": "LIG"},
               "connectivity": {"kind": "sidecar", "sidecar_handle": None},
               "ligand_sdf_handle": ligand["handle"], "sdf_record_index": 0, "hydrogen_policy": "map_existing",
               "mapping": [], "terminal_extensions": [], "acknowledgement": dict(ACK)}
    rows, _, _ = _source_rows(run.store, request)
    sidecar = {"schema": "receptor_bonds@1", "source_handle": complex_source.handle, "complete": True,
               "bonds": [{"first": rows[a]["ref"], "second": rows[b]["ref"]} for a, b in original_bonds]}
    request["connectivity"]["sidecar_handle"] = import_raw(run.store, "receptor_bonds", "bonds.json",
                                                           json.dumps(sidecar).encode())["handle"]
    request["mapping"] = [{"sdf_atom_index": i, "source_atom": rows[4988 + i]["ref"]} for i in range(len(lig_atoms))]
    first = preview(run.store, request)
    request["terminal_extensions"] = [{"residue": item["residue"], "atom_names": item["atom_names"],
                                       "approve_supplied_graph": True} for item in first["terminal_extensions"]]
    assert preview(run.store, request, strict=True)["ready"]
    return request


def _event_types(run: Run) -> list[str]:
    return [event["type"] for event in run.events.read()]


class _Denied(AssertionError):
    pass


@pytest.fixture
def deny_science(monkeypatch):
    """Spy that raises on every scientific implementation, job transition, report build and transport."""
    calls: list[str] = []

    def denied(name: str):
        def fail(*_args, **_kwargs):
            calls.append(name)
            raise _Denied(name)
        return fail

    for name in list(api_module.REGISTRY.impls):
        monkeypatch.setitem(api_module.REGISTRY.impls, name, denied(f"tool:{name}"))
    monkeypatch.setattr(Run, "call", denied("Run.call"))
    for name in ("submit", "start", "retry", "request_cancel", "execute_claim", "claim_next"):
        monkeypatch.setattr(JobQueue, name, denied(f"JobQueue.{name}"))
    for module, name in ((inspection_reports, "build_inspection_report"), (method_reports, "build_method_report"),
                         (comparison_reports, "build_comparison_report"), (openmm_reports, "build_openmm_report"),
                         (chemical_reports, "build_chemical_report"), (pocket_reports, "build_pocket_report")):
        monkeypatch.setattr(module, name, denied(name))
        monkeypatch.setattr(api_module, name, denied(name))
    # Real network transports only; the in-process TestClient transport stays usable.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied("httpx.HTTPTransport"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied("httpx.AsyncHTTPTransport"))
    return calls


# ------------------------------------------------------------------------------ templates and capability
def test_templates_and_capability_list_exactly_six_goals_and_nl_unavailable(client):
    rid, _ = _new(client)
    body = client.get(f"/runs/{rid}/analysis/templates").json()
    assert [row["goal"] for row in body["templates"]] == list(analysis_plans.GOALS) == [
        "inspect_ligand", "measure_atoms", "compare_structures", "chemical_interactions", "find_cavities",
        "minimize_protein"]
    assert body["planner"] == "local_rules@1" and body["source"] == "local_rules"
    assert body["natural_language_planning"] == {"available": False,
                                                 "reason": analysis_plans.NATURAL_LANGUAGE_REASON}
    assert "M24" in body["natural_language_planning"]["reason"]
    chem = next(row for row in body["templates"] if row["goal"] == "chemical_interactions")
    assert chem["fixed"] == {"categories": ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]}
    capability = client.get("/capabilities").json()["methods"]["analysis_workflows"]
    assert capability["planner"] == "local_rules@1"
    assert capability["natural_language_planning"]["available"] is False
    assert set(capability["templates"]) == set(analysis_plans.GOALS)
    # The installed engines are required at acceptance: every template is available here.
    assert all(item["available"] for item in capability["templates"].values()), capability["templates"]
    assert client.get("/runs/run_missing/analysis/templates").status_code == 404


def test_capability_mirrors_unavailable_method(client, monkeypatch):
    def missing():
        raise ToolFailure(FailureClass.precondition, "FreeSASA missing", detail={"reason_code": "engine_missing"})

    monkeypatch.setattr(sasa, "engine_capability", missing)
    templates = client.get("/capabilities").json()["methods"]["analysis_workflows"]["templates"]
    assert templates["inspect_ligand"]["available"] is False
    assert templates["inspect_ligand"]["reason_code"] == "engine_missing_or_invalid"
    assert templates["measure_atoms"]["available"] is True


# ------------------------------------------------------------------------------ inspect_ligand
@pytest.fixture
def ligand_run(client):
    rid, run = _new(client)
    raw = _load(run, FIX / "mini_complex.pdb")
    prepared = _prepare(run, raw)
    return rid, run, raw, prepared, _ligand(run, raw)


def test_inspect_ligand_raw_and_prepared_plans(client, ligand_run, deny_science):
    rid, run, raw, prepared, ligand = ligand_run
    assert ligand["seq_label"] is None  # non-polymer: null label identity must survive unchanged
    before = _event_types(run)
    body = _ok(_post(client, rid, "inspect_ligand", {"source": raw, "preparation": PREP, "ligand": ligand,
                                                     "cutoff_A": 4, "types": ["polar_contact", "contact"]}))
    plan = body["plan"]
    assert set(plan) == analysis_plans.TOP_LEVEL_KEYS
    assert (plan["schema"], plan["planner"], plan["source"], plan["plan_only"], plan["template_version"]) == (
        "analysis_plan@1", "local_rules@1", "local_rules", True, "inspect_ligand@1")
    assert body["executable"] is True and plan["unmet_prerequisites"] == []
    assert [step["operation"] for step in plan["steps"]] == [
        "prepare_structure", "compute_interactions", "compute_interface_sasa", "inspection_report", "method_report"]
    assert [step["step_id"] for step in plan["steps"]] == ["s01", "s02", "s03", "s04", "s05"]
    assert [step["lane"] for step in plan["steps"]] == ["run_call", "run_call", "run_call", "report", "report"]
    prep, contacts, area, contact_report, area_report = plan["steps"]
    params = {step["step_id"]: analysis_plans.resolved_params(plan, step) for step in plan["steps"]}
    # Each explicit input is stored once (in ``inputs``); steps reference it.
    assert prep["params"] == {"input_ref": "preparation"} and contacts["params"]["ligand"] == {"input_ref": "ligand"}
    assert prep["bindings"] == {"structure": {"kind": "existing", "handle": raw, "expected_kind": "structure",
                                              "expected_schema": "structure_selection@2"}}
    assert params["s01"] == {**PREP, "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}
    assert contacts["bindings"]["structure"] == {"kind": "step_output", "step_id": "s01",
                                                 "output_name": "prepared_structure",
                                                 "expected_kind": "prepared_structure",
                                                 "expected_schema": "prepared_structure@1"}
    assert params["s02"] == {"ligand": ligand, "cutoff_A": 4.0, "types": ["contact", "polar_contact"],
                             "engine": "geometric"}
    assert set(params["s02"]["ligand"]) == set(ligand) and len(ligand) == 7
    assert params["s02"]["ligand"]["seq_label"] is None
    assert params["s03"] == {"ligand": ligand} and area["depends_on"] == ["s01"]
    assert contact_report["depends_on"] == ["s01", "s02"] and area_report["depends_on"] == ["s03"]
    assert contact_report["params"] == {"analysis_type": "interaction_contacts"}
    assert contact_report["operation_version"] == "report_manifest@1/inspection_markdown@1"
    assert area_report["operation_version"] == "method_report_manifest@1/interface_sasa_markdown@1"
    assert area["operation_version"] == run.registry.specs["compute_interface_sasa"].version
    sasa_compat = plan["compatibility"]["steps"][2]["method"]
    assert sasa_compat["available"] is True and sasa_compat["engine_version"]
    assert plan["inputs"]["ligand"] == ligand and plan["inputs"]["preparation"]["waters"] == "strip_all"
    assert plan["limits"] == {"max_steps": 8, "max_physical_attempts": 24, "max_active_wall_s": 1800,
                              "max_retries_per_step": 1}
    assert {(item["step_id"], item["output_name"]) for item in plan["deferred_bindings"]} == {
        ("s01", "prepared_structure"), ("s02", "interaction_set"), ("s03", "interface_sasa"),
        ("s04", "report"), ("s05", "report")}
    assert _event_types(run)[len(before):] == ["object_created", "analysis_plan_created"]
    meta = run.store.meta(body["handle"])
    assert (meta["kind"], meta["schema"]) == ("analysis_plan", "analysis_plan@1")

    from_prepared = _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand,
                                                              "cutoff_A": 4.5, "types": ["contact"]}))
    ops = [step["operation"] for step in from_prepared["plan"]["steps"]]
    assert ops == ["compute_interactions", "compute_interface_sasa", "inspection_report", "method_report"]
    assert from_prepared["plan"]["steps"][0]["bindings"]["structure"]["handle"] == prepared
    assert from_prepared["plan"]["steps"][2]["bindings"]["prepared_handle"]["handle"] == prepared
    assert from_prepared["handle"] != body["handle"] and deny_science == []


def test_inspect_ligand_prerequisites_and_invalid_inputs(client, ligand_run, deny_science):
    rid, run, raw, prepared, ligand = ligand_run
    missing = _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": None, "cutoff_A": 4.0,
                                                        "types": ["contact"]}))
    assert missing["executable"] is False and _codes(missing) == ["ligand_required"]
    assert "첫" not in json.dumps(missing["plan"]["inputs"]) and missing["plan"]["inputs"]["ligand"] is None
    other = copy.deepcopy(ligand)
    other["seq_auth"] += 1
    base = {"source": prepared, "ligand": ligand, "cutoff_A": 4.0, "types": ["contact"]}
    invalid = [
        {**base, "ligand": other},                              # not an instance of the source
        {**base, "ligand": {k: v for k, v in ligand.items() if k != "seq_label"}},  # incomplete identity
        {**base, "cutoff_A": 7.0}, {**base, "cutoff_A": True}, {**base, "types": []},
        {**base, "types": ["contact", "contact"]}, {**base, "types": ["hbond"]},
        {**base, "preparation": PREP},                          # prepared source already fixes preparation
        {**base, "source": raw},                                # raw source needs explicit preparation
        {**base, "unexpected": 1},
        {**base, "source": run.store.load(prepared)["manifest"]},  # wrong handle kind
        {**base, "source": "not-a-handle"},
    ]
    for inputs in invalid:
        response = _post(client, rid, "inspect_ligand", inputs)
        assert response.status_code == 422 and response.json()["error"] == "input_invalid", (inputs, response.text)
    nan = client.post(f"/runs/{rid}/analysis/plans", content=(
        f'{{"request_id":"{uuid.uuid4()}","goal":"inspect_ligand","inputs":{{"source":"{prepared}",'
        '"ligand":null,"cutoff_A":NaN,"types":["contact"]}}').encode(),
        headers={"content-type": "application/json"})
    assert nan.status_code == 422
    assert _post(client, rid, "dock_ligand", base).status_code == 422
    assert client.post(f"/runs/{rid}/analysis/plans", json={"request_id": "x", "goal": "inspect_ligand",
                                                             "inputs": base}).status_code == 422
    assert client.post(f"/runs/{rid}/analysis/plans", json={"request_id": str(uuid.uuid4()),
                                                             "goal": "inspect_ligand", "inputs": base,
                                                             "steps": []}).status_code == 422
    other_rid, _ = _new(client)
    foreign = _post(client, other_rid, "inspect_ligand", base)
    assert foreign.status_code == 422 and foreign.json()["error"] == "input_invalid"
    assert deny_science == []


def test_inspect_ligand_unsupported_source_and_engine_unavailable(client, ligand_run, monkeypatch):
    rid, run, _raw, prepared, ligand = ligand_run
    fake = run.store.put("openmm_minimized_structure", "openmm_minimized_structure@1", {"fixture": True})
    body = _ok(_post(client, rid, "inspect_ligand", {"source": fake.handle, "ligand": ligand, "cutoff_A": 4.0,
                                                     "types": ["contact"]}))
    assert _codes(body) == ["unsupported_source"] and body["executable"] is False

    def missing():
        raise ToolFailure(FailureClass.precondition, "FreeSASA missing")

    monkeypatch.setattr(sasa, "engine_capability", missing)
    unavailable = _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand,
                                                            "cutoff_A": 4.0, "types": ["contact"]}))
    assert _codes(unavailable) == ["engine_unavailable"]
    assert unavailable["plan"]["unmet_prerequisites"][0]["detail"]["method"] == "interface_sasa"
    # No substitute step: the SASA step and its report stay in the plan.
    assert [step["operation"] for step in unavailable["plan"]["steps"]][1] == "compute_interface_sasa"


# ------------------------------------------------------------------------------ idempotency, dedup, limits
def test_request_id_idempotency_conflict_and_content_dedup(client, ligand_run):
    rid, run, _, prepared, ligand = ligand_run
    inputs = {"source": prepared, "ligand": ligand, "cutoff_A": 4.0, "types": ["contact"]}
    request_id = str(uuid.uuid4())
    first = _ok(_post(client, rid, "inspect_ligand", inputs, request_id))
    events = len(list(run.events.read()))
    again = _ok(_post(client, rid, "inspect_ligand", inputs, request_id))
    assert again["handle"] == first["handle"] and again["replayed"] is True and first["replayed"] is False
    assert len(list(run.events.read())) == events
    conflict = _post(client, rid, "inspect_ligand", {**inputs, "cutoff_A": 5.0}, request_id)
    assert conflict.status_code == 409 and conflict.json()["error"] == "request_id_conflict"
    dedup = _ok(_post(client, rid, "inspect_ligand", {**inputs, "types": ["contact"]}))
    assert dedup["handle"] == first["handle"] and dedup["ordinal"] == 1
    created = [e for e in run.events.read() if e["type"] == "object_created" and e["handle"] == first["handle"]]
    assert len(created) == 1
    listed = client.get(f"/runs/{rid}/analysis/plans").json()
    assert listed["total"] == 1 and listed["rows"][0]["handle"] == first["handle"]
    assert listed["rows"][0]["executable"] is True and listed["rows"][0]["goal"] == "inspect_ligand"
    detail = client.get(f"/runs/{rid}/analysis/plans/detail", params={"handle": first["handle"]}).json()
    assert detail["plan"] == first["plan"] and detail["plan_sha256"] == analysis_plans.canonical_plan_hash(
        first["plan"])
    assert client.get(f"/runs/{rid}/analysis/plans/detail", params={"handle": prepared}).status_code == 422
    other_rid, _ = _new(client)
    assert client.get(f"/runs/{other_rid}/analysis/plans/detail",
                      params={"handle": first["handle"]}).status_code == 422


def test_plan_count_and_size_limits(client, ligand_run, monkeypatch):
    rid, _run, _, prepared, ligand = ligand_run
    assert analysis_plans.MAX_PLANS_PER_RUN == 100 and analysis_plans.MAX_PLAN_BYTES == 1024 * 1024
    monkeypatch.setattr(analysis_plans, "MAX_PLANS_PER_RUN", 2)
    for cutoff in (4.0, 4.5):
        _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": cutoff,
                                                  "types": ["contact"]}))
    third = _post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 5.0,
                                                  "types": ["contact"]})
    assert third.status_code == 429 and third.json()["error"] == "resource_exceeded"
    # An identical plan is not a new plan and still dedups under the limit.
    assert _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 4.0,
                                                     "types": ["contact"]}))["ordinal"] == 1
    monkeypatch.setattr(analysis_plans, "MAX_PLANS_PER_RUN", 100)
    monkeypatch.setattr(analysis_plans, "MAX_PLAN_BYTES", 2048)
    large = _post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 5.5,
                                                  "types": ["contact"]})
    assert large.status_code == 429 and large.json()["detail"]["reason_code"] == "plan_too_large"
    oversized = client.post(f"/runs/{rid}/analysis/plans", content=b"{" + b" " * (1024 * 1024) + b"}",
                            headers={"content-type": "application/json"})
    assert oversized.status_code == 413
    # A plan body above the old 64 KiB bound is accepted (the other analysis routes keep 64 KiB).
    padded = client.post(f"/runs/{rid}/analysis/plans", content=b"{" + b" " * (200 * 1024) + b"}",
                         headers={"content-type": "application/json"})
    assert padded.status_code == 422


def test_validate_plan_rejects_over_eight_steps_and_forward_dependencies(client, ligand_run):
    rid, _, _, prepared, ligand = ligand_run
    plan = _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 4.0,
                                                     "types": ["contact"]}))["plan"]
    analysis_plans.validate_plan(plan)
    nine = copy.deepcopy(plan)
    extra = copy.deepcopy(nine["steps"][0])
    while len(nine["steps"]) < 9:
        nine["steps"].append({**copy.deepcopy(extra), "step_id": f"s{len(nine['steps']) + 1:02d}"})
    for bad in (nine,):
        with pytest.raises(ValueError, match="step count"):
            analysis_plans.validate_plan(bad)
    forward = copy.deepcopy(plan)
    forward["steps"][0]["depends_on"] = ["s02"]
    renamed = copy.deepcopy(plan)
    renamed["steps"][0]["operation"] = "run_script"
    pointer = copy.deepcopy(plan)
    pointer["steps"][2]["bindings"]["interaction_handle"] = {"kind": "json_pointer", "path": "/steps/0"}
    wrong_lane = copy.deepcopy(plan)
    wrong_lane["steps"][0]["lane"] = "durable_job"
    extra_key = copy.deepcopy(plan) | {"notes": "x"}
    for bad in (forward, renamed, pointer, wrong_lane, extra_key):
        with pytest.raises(ValueError):
            analysis_plans.validate_plan(bad)


# ------------------------------------------------------------------------------ M10 templates
@pytest.fixture
def m10_run(client):
    rid, run = _new(client)
    reference = _load(run, M10 / "m10-reference.pdb")
    moving = _load(run, M10 / "m10-moving.pdb")
    return rid, run, reference, moving, atom_rows(run.store, reference), atom_rows(run.store, moving)


def test_m10_templates(client, m10_run, deny_science):
    rid, _run, reference, moving, ref_catalog, mov_catalog = m10_run
    first, second = _atom(ref_catalog, 10, "N"), _atom(ref_catalog, 11, "O")
    measure = _ok(_post(client, rid, "measure_atoms", {"source": reference, "first": first, "second": second}))
    assert measure["executable"] is True
    assert [step["operation"] for step in measure["plan"]["steps"]] == ["measure_distance", "method_report"]
    assert analysis_plans.resolved_params(measure["plan"], measure["plan"]["steps"][0]) == {"first": first,
                                                                                            "second": second}
    assert measure["plan"]["inputs"]["first"]["residue"]["seq_label"] is None  # null label kept
    missing = _ok(_post(client, rid, "measure_atoms", {"source": reference, "first": first}))
    assert _codes(missing) == ["atoms_required"]
    foreign_atom = _atom(mov_catalog, 10, "N")
    assert _post(client, rid, "measure_atoms", {"source": reference, "first": first,
                                                "second": foreign_atom}).status_code == 422
    wrong_site = {**second, "site_index": second["site_index"] + 1}
    assert _post(client, rid, "measure_atoms", {"source": reference, "first": first,
                                                "second": wrong_site}).status_code == 422

    pairs = _pairs(ref_catalog, mov_catalog)
    compare = _ok(_post(client, rid, "compare_structures", {"reference": reference, "moving": moving,
                                                            "pairs": pairs}))
    assert compare["executable"] is True
    step = compare["plan"]["steps"][0]
    assert step["operation"] == "align_structures" and step["params"] == {"pairs": {"input_ref": "pairs"}}
    assert analysis_plans.resolved_params(compare["plan"], step) == {"pairs": pairs}
    assert compare["plan"]["inputs"]["pairs"] == pairs
    assert set(step["bindings"]) == {"reference", "moving"}
    assert _codes(_ok(_post(client, rid, "compare_structures", {"reference": reference, "moving": moving}))) == [
        "ca_pairs_required"]
    assert _codes(_ok(_post(client, rid, "compare_structures", {"reference": reference, "moving": moving,
                                                                "pairs": []}))) == ["ca_pairs_required"]
    for bad in (pairs[:2], [pairs[0], pairs[0], pairs[1]],
                [{"reference": _atom(ref_catalog, 10, "N"), "moving": _atom(mov_catalog, 10, "N")}, *pairs[1:]],
                [{**pairs[0], "extra": 1}, *pairs[1:]]):
        response = _post(client, rid, "compare_structures", {"reference": reference, "moving": moving,
                                                             "pairs": bad})
        assert response.status_code == 422, response.text
    assert _post(client, rid, "compare_structures", {"reference": reference, "moving": reference,
                                                     "pairs": pairs}).status_code == 422
    assert deny_science == []


# ------------------------------------------------------------------------------ M12 and OpenMM templates
@pytest.fixture
def ubq_run(client):
    rid, run = _new(client)
    raw = _load(run, FIX / "public_1ubq.cif")
    return rid, run, raw, _prepare(run, raw)


def test_find_cavities_and_minimize_protein(client, ubq_run, deny_science):
    rid, _run, raw, prepared = ubq_run
    pockets = _ok(_post(client, rid, "find_cavities", {"source": prepared, "chains": ["A"]}))
    assert pockets["executable"] is True, pockets["plan"]["unmet_prerequisites"]
    assert [step["operation"] for step in pockets["plan"]["steps"]] == ["fpocket_detect_v1", "method_report"]
    assert pockets["plan"]["steps"][0]["lane"] == "durable_job"
    assert analysis_plans.resolved_params(pockets["plan"], pockets["plan"]["steps"][0]) == {"chains": ["A"],
                                                                                            "timeout_s": 120}
    compat = pockets["plan"]["compatibility"]["steps"][0]
    assert compat["protocol_id"] == "fpocket_detect_v1" and compat["method"]["executable_sha256"]
    assert _codes(_ok(_post(client, rid, "find_cavities", {"source": prepared, "chains": []}))) == [
        "chains_required"]
    raw_plan = _ok(_post(client, rid, "find_cavities", {"source": raw, "chains": ["A"]}))
    assert _codes(raw_plan) == ["unsupported_source"]
    assert raw_plan["plan"]["unmet_prerequisites"][0]["detail"]["reason_code"] == "raw_structure_requires_preparation"
    for chains in (["Z"], ["A", "A"], [""]):
        assert _post(client, rid, "find_cavities", {"source": prepared, "chains": chains}).status_code == 422
    assert _post(client, rid, "find_cavities", {"source": prepared}).status_code == 422

    minimize = _ok(_post(client, rid, "minimize_protein", {"source": prepared, "selection_policy": "protein_only",
                                                           "hydrogen_policy": "rebuild_pH7"}))
    assert minimize["executable"] is True, minimize["plan"]["unmet_prerequisites"]
    assert analysis_plans.resolved_params(minimize["plan"], minimize["plan"]["steps"][0]) == {
        "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "timeout_s": 120}
    assert minimize["plan"]["steps"][1]["params"] == {"analysis_type": "openmm_protein_minimize"}
    assert _codes(_ok(_post(client, rid, "minimize_protein", {"source": raw, "selection_policy": "protein_only",
                                                              "hydrogen_policy": "rebuild_pH7"}))) == [
        "unsupported_source"]
    assert _post(client, rid, "minimize_protein", {"source": prepared}).status_code == 422
    assert _post(client, rid, "minimize_protein", {"source": prepared, "selection_policy": "all_atoms",
                                                   "hydrogen_policy": "rebuild_pH7"}).status_code == 422
    assert deny_science == []


def test_minimize_protein_preflight_rejection_is_a_prerequisite(client):
    rid, run = _new(client)
    prepared = _prepare(run, _load(run, FIX / "public_1hsg.cif"))  # 1HSG lacks terminal OXT (known rejection)
    body = _ok(_post(client, rid, "minimize_protein", {"source": prepared, "selection_policy": "protein_only",
                                                       "hydrogen_policy": "rebuild_pH7"}))
    assert _codes(body) == ["method_preflight_rejected"] and body["executable"] is False


# ------------------------------------------------------------------------------ M11 template, both modes
def test_chemical_interactions_both_preparation_modes(client, deny_science):
    rid, run = _new(client)
    for request in (_create_new_request(run), _attach_request(run)):
        body = _ok(_post(client, rid, "chemical_interactions", {"request": request}))
        plan = body["plan"]
        assert body["executable"] is True, plan["unmet_prerequisites"]
        assert [step["operation"] for step in plan["steps"]] == ["prolif_prepare_v1", "prolif_detect_v1",
                                                                 "method_report"]
        prepare, detect, report = plan["steps"]
        assert prepare["params"] == {"request": {"input_ref": "request"}, "timeout_s": 120}
        assert plan["inputs"]["request"] == request  # stored once
        assert analysis_plans.resolved_params(plan, prepare) == {"request": request, "timeout_s": 120}
        assert analysis_plans.resolved_params(plan, detect) == {
            "schema": "chemical_detect_request@1", "timeout_s": 120,
            "categories": ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]}
        assert detect["bindings"] == {"graph_handle": {"kind": "step_output", "step_id": "s01",
                                                       "output_name": "chemical_graph",
                                                       "expected_kind": "chemical_graph",
                                                       "expected_schema": "chemical_graph@1"}}
        assert report["params"] == {"analysis_type": "chemical_interactions"}
        expected = ({"complex", "ligand_sdf", "connectivity_sidecar"} if request["mode"] == "attach_existing"
                    else {"receptor_input", "ligand_sdf"})
        assert set(prepare["bindings"]) == expected
        assert plan["inputs"]["mode"] == request["mode"]
        method = plan["compatibility"]["steps"][0]["method"]
        assert method["available"] is True and method["worker_sha256"] and method["dependency_manifest_sha256"]
    request = _create_new_request(run)
    blocked = copy.deepcopy(request)
    blocked["acknowledgement"]["supplied_graph_complete"] = False
    not_ready = _ok(_post(client, rid, "chemical_interactions", {"request": blocked}))
    assert _codes(not_ready) == ["chemical_preparation_not_ready"]
    assert "supplied_graph_complete" in not_ready["plan"]["unmet_prerequisites"][0]["detail"]["blocker_codes"]
    assert _codes(_ok(_post(client, rid, "chemical_interactions", {"request": None}))) == [
        "chemical_request_required"]
    assert _codes(_ok(_post(client, rid, "chemical_interactions", {}))) == ["chemical_request_required"]
    partial = {key: value for key, value in request.items() if key != "acknowledgement"}
    assert _post(client, rid, "chemical_interactions", {"request": partial}).status_code == 422
    assert _post(client, rid, "chemical_interactions", {"request": request,
                                                        "categories": ["HBDonor"]}).status_code == 422
    other_rid, _ = _new(client)
    assert _post(client, other_rid, "chemical_interactions", {"request": request}).status_code == 422
    assert deny_science == []


# ------------------------------------------------------------------------------ zero science, dry-run, recovery
def test_dry_run_plan_creation_makes_zero_scientific_calls(client, deny_science):
    rid, run = _new(client, dry_run=True)
    # Setup through the object store only (no Run.call is possible under the spy).
    raw_source = run.store.put("structure_source", "structure_source@1", (FIX / "mini_complex.pdb").read_bytes(),
                               fmt="pdb")
    structure = run.store.put("structure", "structure_selection@2",
                              {"source": raw_source.handle, "format": "pdb", "model_index": 0})
    ligand = _ligand(run, structure.handle)
    body = _ok(_post(client, rid, "inspect_ligand", {"source": structure.handle, "preparation": PREP,
                                                     "ligand": ligand, "cutoff_A": 4.0, "types": ["contact"]}))
    assert body["executable"] is True and body["plan"]["plan_only"] is True
    assert client.get(f"/runs/{rid}/analysis/templates").status_code == 200
    assert client.get(f"/runs/{rid}/analysis/plans").json()["total"] == 1
    types = set(_event_types(run))
    assert not types & {"tool_called", "tool_succeeded", "job_submitted", "report_created",
                        "method_report_created", "branch_proposed", "budget_reserved", "egress"}
    assert deny_science == []


def test_events_only_recovery_restores_plan_bytes(client, ligand_run, tmp_path):
    rid, _run, _, prepared, ligand = ligand_run
    body = _ok(_post(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 4.0,
                                                     "types": ["contact"]}))
    run_dir = tmp_path / rid
    shutil.rmtree(run_dir / "objects")
    (run_dir / "index.sqlite").unlink()
    api_module.RUNS.clear()
    detail = client.get(f"/runs/{rid}/analysis/plans/detail", params={"handle": body["handle"]})
    assert detail.status_code == 200, detail.text
    assert detail.json()["plan"] == body["plan"]
    assert client.get(f"/runs/{rid}/analysis/plans").json()["rows"][0]["handle"] == body["handle"]


def test_check_compatibility_reports_changed_method_versions(client, ubq_run, monkeypatch):
    rid, run, _, prepared = ubq_run
    body = _ok(_post(client, rid, "minimize_protein", {"source": prepared, "selection_policy": "protein_only",
                                                       "hydrogen_policy": "rebuild_pH7"}))
    plan = analysis_plans.load_plan(run, body["handle"])
    assert analysis_plans.check_compatibility(run, plan)["compatible"] is True
    original = openmm_method.capability()
    monkeypatch.setattr(openmm_method, "capability", lambda: {**original, "engine_build": "different-build"})
    changed = analysis_plans.check_compatibility(run, plan)
    assert changed["compatible"] is False and changed["mismatched_steps"] == ["s01"]
    monkeypatch.setattr(openmm_method, "capability", lambda: {"available": False, "reason_code": "openmm_unavailable",
                                                              "explanation": "fixture: engine removed"})
    assert analysis_plans.check_compatibility(run, plan)["compatible"] is False
    stale = _ok(_post(client, rid, "minimize_protein", {"source": prepared, "selection_policy": "protein_only",
                                                        "hydrogen_policy": "rebuild_pH7"}))
    assert stale["handle"] != body["handle"] and _codes(stale) == ["engine_unavailable"]


# ==============================================================================================
# M13 T3: executions (approval, one-step Advance, retry, scoped Stop, idempotency, recovery, summary)
# ==============================================================================================


def _plan(client: TestClient, rid: str, goal: str, inputs: dict) -> dict:
    body = _ok(_post(client, rid, goal, inputs))
    assert body["executable"] is True, body["plan"]["unmet_prerequisites"]
    return body


def _create(client: TestClient, rid: str, plan_handle: str, request_id: str | None = None):
    return client.post(f"/runs/{rid}/analysis/executions",
                       json={"request_id": request_id or str(uuid.uuid4()), "plan_handle": plan_handle})


def _execution(client: TestClient, rid: str, plan_handle: str) -> dict:
    response = _create(client, rid, plan_handle)
    assert response.status_code == 201, response.text
    return response.json()["execution"]


def _get(client: TestClient, rid: str, eid: str) -> dict:
    response = client.get(f"/runs/{rid}/analysis/executions/{eid}")
    assert response.status_code == 200, response.text
    return response.json()


def _act(client: TestClient, rid: str, eid: str, action: str, revision: int | None = None,
         request_id: str | None = None, **extra):
    if revision is None:
        revision = _get(client, rid, eid)["revision"]
    return client.post(f"/runs/{rid}/analysis/executions/{eid}/{action}",
                       json={"request_id": request_id or str(uuid.uuid4()), "expected_revision": revision, **extra})


def _done(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["execution"]


def _approve(client: TestClient, rid: str, eid: str, plan_sha: str) -> dict:
    return _done(_act(client, rid, eid, "approve", plan_hash=plan_sha))


def _drive(client: TestClient, rid: str, eid: str, *, science: bool = True, limit: int = 12) -> dict:
    """Press Advance one step at a time (the UI's only control); approve science when the gate is shown."""
    record = _get(client, rid, eid)
    for _ in range(limit):
        if record["status"] in {"complete", "failed", "cancelled", "blocked"}:
            return record
        if record["status"] == "awaiting_scientific_approval":
            assert science
            record = _done(_act(client, rid, eid, "scientific-approval"))
            continue
        record = _done(_act(client, rid, eid, "advance"))
    return record


def _types(run: Run, kind: str) -> list[dict]:
    return [event for event in run.events.read() if event["type"] == kind]


def _linked(run: Run, eid: str, kind: str) -> list[dict]:
    return [event for event in run.events.read() if event["type"] == kind and
            (event.get("execution_link") or {}).get("execution_id") == eid]


@pytest.fixture
def faults(monkeypatch):
    """FAULT FIXTURE: raise a process-crash stand-in (BaseException) at named driver boundaries."""
    stages: dict[str, int] = {}

    class Crash(BaseException):
        pass

    def hook(stage: str) -> None:
        if stages.get(stage, 0) > 0:
            stages[stage] -= 1
            raise Crash(stage)

    monkeypatch.setattr(ax, "_FAULT_HOOK", hook)
    return stages, Crash


def _measure_setup(client: TestClient) -> tuple[str, Run, dict]:
    rid, run = _new(client)
    reference = _load(run, M10 / "m10-reference.pdb")
    catalog = atom_rows(run.store, reference)
    body = _plan(client, rid, "measure_atoms", {"source": reference, "first": _atom(catalog, 10, "N"),
                                                "second": _atom(catalog, 11, "O")})
    return rid, run, body


def test_measure_atoms_execution_end_to_end_with_summary_and_reads_that_never_write(client, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *a, **k: calls.append("http"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", lambda *a, **k: calls.append("http"))
    rid, run, body = _measure_setup(client)
    capability = client.get("/capabilities").json()["methods"]["analysis_workflows"]
    assert capability["available"] is True and capability["max_plan_bytes"] == 1024 * 1024
    assert capability["max_executions_per_run"] == 100
    record = _execution(client, rid, body["handle"])
    assert record["status"] == "awaiting_approval" and record["execution_id"].startswith("exec_")
    assert set(record["steps"][0]) >= {"step_id", "status", "attempts", "child_call_ids", "job_ownership"}
    assert [step["status"] for step in record["steps"]] == ["pending", "pending"]
    record = _approve(client, rid, record["execution_id"], body["plan_sha256"])
    eid = record["execution_id"]
    assert record["status"] == "ready" and record["plan_approval"]["approved"] is True
    assert record["scientific_approval"]["state"] == "not_required"
    before = len(list(run.events.read()))
    for _ in range(3):
        assert _get(client, rid, eid)["revision"] == record["revision"]
        client.get(f"/runs/{rid}/analysis/executions")
    assert len(list(run.events.read())) == before  # reads never append events
    first = _done(_act(client, rid, eid, "advance"))
    assert first["status"] == "ready" and first["steps"][0]["status"] == "completed"
    assert first["steps"][1]["status"] == "pending"  # one step per Advance, never chained
    distance = first["steps"][0]["outputs"]["atom_distance"]
    assert run.store.meta(distance)["kind"] == "atom_distance"
    assert first["steps"][0]["attempts"] == 1 and first["physical_attempts"] == 1
    assert len(first["steps"][0]["child_call_ids"]) == 1
    final = _done(_act(client, rid, eid, "advance"))
    assert final["status"] == "complete" and final["steps"][1]["status"] == "completed"
    report = final["steps"][1]["report_handle"]
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": report}).status_code == 200
    assert final["summary_handle"]
    summary = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary").json()
    content = summary["summary"]
    assert content["schema"] == "workflow_summary@1" and content["execution_id"] == eid
    assert content["plan_handle"] == body["handle"] and content["plan_hash"] == body["plan_sha256"]
    assert [row["step_id"] for row in content["steps"]] == ["s01", "s02"]
    assert content["steps"][0]["output_handles"] == [distance] and content["steps"][1]["report_handle"] == report
    assert content["physical_attempts"] == 1
    assert "distance_A" not in json.dumps(content)  # links only, no numeric science
    raw = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary", params={"download": "json"})
    assert raw.status_code == 200 and raw.content == canonical_json(run.store.load(final["summary_handle"]))
    # Linked child events carry the exact execution link; the run itself was never cancelled.
    assert all(e["execution_link"]["execution_id"] == eid for e in _linked(run, eid, "tool_called"))
    assert not _types(run, "cancel_requested") and calls == []
    again = _done(_act(client, rid, eid, "advance"))
    assert again["status"] == "complete" and len(_types(run, "tool_called")) == 2  # load + distance only


def _approved_measure(client: TestClient) -> tuple[str, Run, dict, str]:
    rid, run, body = _measure_setup(client)
    eid = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, eid, body["plan_sha256"])
    return rid, run, body, eid


def _fixture_tool(monkeypatch, name: str, behaviour):
    """FAULT FIXTURE: wrap one registered tool; ``behaviour(call_index, real, ctx, kwargs)`` decides."""
    real = api_module.REGISTRY.impls[name]
    count = {"n": 0}

    def wrapped(ctx, **kwargs):
        count["n"] += 1
        return behaviour(count["n"], real, ctx, kwargs)

    monkeypatch.setitem(api_module.REGISTRY.impls, name, wrapped)
    return count


def _transient(times: int):
    def behaviour(n, real, ctx, kwargs):
        if n <= times:
            raise ToolFailure(FailureClass.transient, "fixture transient failure")
        return real(ctx, **kwargs)
    return behaviour


def test_plan_approval_is_required_bound_to_hash_and_separate_from_scientific_approval(client):
    rid, run, body = _measure_setup(client)
    eid = _execution(client, rid, body["handle"])["execution_id"]
    refused = _act(client, rid, eid, "advance")
    assert refused.status_code == 412 and refused.json()["error"] == "plan_not_approved"
    wrong = _act(client, rid, eid, "approve", plan_hash="0" * 64)
    assert wrong.status_code == 412 and wrong.json()["error"] == "plan_hash_mismatch"
    science = _act(client, rid, eid, "scientific-approval")
    assert science.status_code == 412 and science.json()["error"] == "no_pending_scientific_approval"
    record = _approve(client, rid, eid, body["plan_sha256"])
    assert record["plan_approval"]["plan_sha256"] == body["plan_sha256"]
    # Plan approval never records the run's scientific approval (nor limits / consent).
    assert not [e for e in run.events.read() if e["type"] in {"approval_resolved", "budget_limit_updated",
                                                            "viewer_consent_changed"}]
    assert _act(client, rid, eid, "approve", plan_hash=body["plan_sha256"]).status_code == 412
    # An edited input is a new plan: the old approval does not carry over to its execution.
    catalog = atom_rows(run.store, body["plan"]["inputs"]["source"])
    edited = _plan(client, rid, "measure_atoms", {"source": body["plan"]["inputs"]["source"],
                                                  "first": _atom(catalog, 12, "CA"), "second": _atom(catalog, 11, "O")})
    assert edited["handle"] != body["handle"]
    other = _execution(client, rid, edited["handle"])
    assert other["status"] == "awaiting_approval"
    assert _act(client, rid, other["execution_id"], "advance").status_code == 412
    stale_hash = _act(client, rid, other["execution_id"], "approve", plan_hash=body["plan_sha256"])
    assert stale_hash.status_code == 412
    # Revocation before any dispatch returns to awaiting_approval; after dispatch it cancels.
    revoked = _done(_act(client, rid, eid, "revoke"))
    assert revoked["status"] == "awaiting_approval" and revoked["plan_approval"]["approved"] is False
    _approve(client, rid, eid, body["plan_sha256"])
    _done(_act(client, rid, eid, "advance"))
    after = _done(_act(client, rid, eid, "revoke"))
    assert after["status"] == "cancelled" and after["steps"][1]["status"] == "pending"
    assert _done(_act(client, rid, eid, "advance"))["status"] == "cancelled"
    assert len(_linked(run, eid, "tool_called")) == 1 and not _types(run, "cancel_requested")
    blocked_plan = _ok(_post(client, rid, "measure_atoms", {"source": body["plan"]["inputs"]["source"]}))
    refused_create = _create(client, rid, blocked_plan["handle"])
    assert refused_create.status_code == 412 and refused_create.json()["error"] == "plan_blocked"
    assert _create(client, rid, "obj://nope").status_code == 422
    other_rid, _ = _new(client)
    assert _create(client, other_rid, body["handle"]).status_code == 422
    assert client.get(f"/runs/{rid}/analysis/executions/exec_{'0' * 32}").status_code == 404
    assert client.get(f"/runs/{other_rid}/analysis/executions/{eid}").status_code == 404


def test_dry_run_execution_is_plan_only_with_zero_science(client, deny_science):
    rid, run = _new(client, dry_run=True)
    raw_source = run.store.put("structure_source", "structure_source@1", (FIX / "mini_complex.pdb").read_bytes(),
                               fmt="pdb")
    structure = run.store.put("structure", "structure_selection@2",
                              {"source": raw_source.handle, "format": "pdb", "model_index": 0})
    body = _plan(client, rid, "inspect_ligand", {"source": structure.handle, "preparation": PREP,
                                                 "ligand": _ligand(run, structure.handle), "cutoff_A": 4.0,
                                                 "types": ["contact"]})
    record = _execution(client, rid, body["handle"])
    eid = record["execution_id"]
    assert record["status"] == "plan_only" and record["dry_run"] is True
    for action, extra in (("approve", {"plan_hash": body["plan_sha256"]}), ("advance", {}),
                          ("retry", {"step_id": "s01"}), ("scientific-approval", {}), ("revoke", {})):
        response = _act(client, rid, eid, action, **extra)
        assert response.status_code == 412 and response.json()["error"] == "dry_run_plan_only", (action, response.text)
    assert _get(client, rid, eid)["status"] == "plan_only"
    cancelled = _done(_act(client, rid, eid, "cancel"))
    assert cancelled["status"] == "cancelled"
    types = set(_event_types(run))
    assert not types & {"tool_called", "tool_succeeded", "job_submitted", "report_created", "method_report_created",
                        "branch_proposed", "budget_reserved", "execution_call_admitted", "cancel_requested"}
    assert deny_science == []


def test_request_idempotency_conflict_and_stale_revision(client):
    rid, run, body = _measure_setup(client)
    request_id = str(uuid.uuid4())
    first = _create(client, rid, body["handle"], request_id)
    again = _create(client, rid, body["handle"], request_id)
    assert first.status_code == again.status_code == 201
    assert again.json()["replayed"] is True and again.json()["execution"]["execution_id"] == \
        first.json()["execution"]["execution_id"]
    eid = first.json()["execution"]["execution_id"]
    assert len(_types(run, "analysis_execution_created")) == 1
    assert _create(client, rid, "obj://other", request_id).status_code == 409
    # A plan request_id cannot be reused for an execution and vice versa (unique per run).
    assert _post(client, rid, "measure_atoms", body["plan"]["inputs"], request_id).status_code == 409
    _approve(client, rid, eid, body["plan_sha256"])
    revision = _get(client, rid, eid)["revision"]
    advance_id = str(uuid.uuid4())
    done = _act(client, rid, eid, "advance", revision, advance_id)
    assert done.status_code == 200
    events = len(list(run.events.read()))
    replay = _act(client, rid, eid, "advance", revision, advance_id)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["request"]["state"] == "completed"
    assert len(list(run.events.read())) == events and len(_linked(run, eid, "tool_called")) == 1
    conflict = _act(client, rid, eid, "cancel", revision, advance_id)
    assert conflict.status_code == 409 and conflict.json()["error"] == "request_id_conflict"
    stale = _act(client, rid, eid, "advance", revision)
    assert stale.status_code == 409 and stale.json()["error"] == "stale_revision"
    bad = client.post(f"/runs/{rid}/analysis/executions/{eid}/advance",
                      json={"request_id": str(uuid.uuid4()), "expected_revision": "1"})
    assert bad.status_code == 422
    extra = client.post(f"/runs/{rid}/analysis/executions/{eid}/advance",
                        json={"request_id": str(uuid.uuid4()), "expected_revision": 1, "steps": []})
    assert extra.status_code == 422
    big = client.post(f"/runs/{rid}/analysis/executions/{eid}/advance", content=b"{" + b" " * (64 * 1024) + b"}",
                      headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_execution_count_limit_per_run(client, monkeypatch):
    rid, _run, body = _measure_setup(client)
    monkeypatch.setattr(ax, "MAX_EXECUTIONS_PER_RUN", 2)
    _execution(client, rid, body["handle"])
    _execution(client, rid, body["handle"])  # several executions may share one plan
    third = _create(client, rid, body["handle"])
    assert third.status_code == 429 and third.json()["error"] == "resource_exceeded"


def test_concurrent_advance_is_busy_and_creates_no_competing_work(client, monkeypatch):
    import threading
    rid, run, _body, eid = _approved_measure(client)
    entered, release = threading.Event(), threading.Event()

    def slow(n, real, ctx, kwargs):
        entered.set()
        assert release.wait(10)
        return real(ctx, **kwargs)

    _fixture_tool(monkeypatch, "measure_distance", slow)
    revision = _get(client, rid, eid)["revision"]
    results: list = []
    in_flight = str(uuid.uuid4())
    worker = threading.Thread(target=lambda: results.append(ax.advance(run, eid, in_flight, revision)))
    worker.start()
    assert entered.wait(10)
    live = _get(client, rid, eid)
    assert live["status"] == "executing" and live["driver"]["in_progress"] is True
    pending = _act(client, rid, eid, "advance", revision, in_flight)  # the same request from a second tab
    assert pending.status_code == 200 and pending.json()["request"]["state"] == "pending"
    busy = _act(client, rid, eid, "advance", live["revision"])
    assert busy.status_code == 409 and busy.json()["error"] == "busy"
    busy_retry = _act(client, rid, eid, "retry", live["revision"], step_id="s01")
    assert busy_retry.status_code == 409 and busy_retry.json()["error"] == "busy"
    release.set()
    worker.join(20)
    assert results and results[0]["execution"]["steps"][0]["status"] == "completed"
    assert len(_linked(run, eid, "tool_called")) == 1 and len(_linked(run, eid, "execution_call_admitted")) == 1


def test_transient_retry_rule_attempt_charging_and_one_explicit_retry(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)
    api_module._run(rid).sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(100))
    failed = _done(_act(client, rid, eid, "advance"))
    assert failed["status"] == "failed" and failed["retryable_step"] == "s01"
    assert failed["steps"][0]["status"] == "failed" and failed["steps"][0]["attempts"] == 4  # existing 2/4/8 chain
    assert len(_linked(run, eid, "tool_failed")) == 4
    refused = _act(client, rid, eid, "advance")
    assert refused.status_code == 412 and refused.json()["error"] == "retry_or_stop_required"
    assert _act(client, rid, eid, "retry", step_id="s02").status_code == 412
    retried = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert retried["status"] == "failed" and retried["retryable_step"] is None  # one explicit retry only
    assert retried["physical_attempts"] == 8 and retried["steps"][0]["retries_used"] == 1
    assert _act(client, rid, eid, "retry", step_id="s01").status_code == 412
    extra = _act(client, rid, eid, "advance")
    assert extra.json()["request"]["outcome"] == "no_op_failed"  # a terminal failure is never re-dispatched
    assert extra.json()["execution"]["status"] == "failed"
    assert len(_linked(run, eid, "tool_called")) == 8  # nothing refunded or repeated behind the user's back


def test_retry_success_and_non_retryable_classes(client, monkeypatch):
    rid, _run, _body, eid = _approved_measure(client)
    api_module._run(rid).sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(4))
    assert _done(_act(client, rid, eid, "advance"))["retryable_step"] == "s01"
    recovered = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert recovered["steps"][0]["status"] == "completed" and recovered["status"] == "ready"
    assert _drive(client, rid, eid)["status"] == "complete"

    def fatal(n, real, ctx, kwargs):
        raise ToolFailure(FailureClass.fatal, "fixture fatal")

    rid2, _run2, _body2, eid2 = _approved_measure(client)
    _fixture_tool(monkeypatch, "measure_distance", fatal)
    record = _done(_act(client, rid2, eid2, "advance"))
    assert record["status"] == "failed" and record["retryable_step"] is None

    def invalid(n, real, ctx, kwargs):
        raise ToolFailure(FailureClass.input_invalid, "fixture invalid input")

    rid3, _run3, _body3, eid3 = _approved_measure(client)
    _fixture_tool(monkeypatch, "measure_distance", invalid)
    record = _done(_act(client, rid3, eid3, "advance"))
    assert record["status"] == "blocked" and record["steps"][0]["status"] == "blocked"
    assert record["blocked_reason"]["reason_code"] == "step_input_invalid"


def test_physical_attempt_and_active_wall_limits(client, monkeypatch):
    monkeypatch.setitem(analysis_plans.LIMITS, "max_physical_attempts", 2)
    rid, run, _body, eid = _approved_measure(client)
    api_module._run(rid).sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(100))
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "failed" and record["retryable_step"] is None
    assert record["physical_attempts"] == 2 and record["steps"][0]["failure"]["reason_code"] == \
        "max_physical_attempts"
    assert len(_linked(run, eid, "tool_called")) == 2  # the third start was refused before it began
    assert any(e["type"] == "analysis_attempt_refused" for e in run.events.read())
    monkeypatch.setitem(analysis_plans.LIMITS, "max_physical_attempts", 24)
    monkeypatch.setitem(analysis_plans.LIMITS, "max_active_wall_s", 1e-9)
    monkeypatch.setitem(api_module.REGISTRY.impls, "measure_distance", _real("measure_distance"))
    rid, run, _body, eid = _approved_measure(client)
    first = _done(_act(client, rid, eid, "advance"))
    assert first["steps"][0]["status"] == "completed" and first["active_wall_s"] > 0
    # The wall limit refuses physical starts only: the report step still runs after the limit is reached.
    second = _done(_act(client, rid, eid, "advance"))
    assert second["status"] == "complete" and second["steps"][1]["status"] == "completed"
    assert not any(e["type"] == "analysis_attempt_refused" for e in run.events.read())
    # A physical restart after a charged attempt is refused by the wall limit before it begins.
    rid, run, _body, eid = _approved_measure(client)
    api_module._run(rid).sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(1))
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "failed" and record["steps"][0]["failure"]["reason_code"] == "max_active_wall"
    assert len(_linked(run, eid, "tool_called")) == 1 and record["physical_attempts"] == 1


def _real(name: str):
    from mw.workspace import build_registry
    return build_registry().impls[name]


# ------------------------------------------------------------------------------ scoped Stop (run_call / report)
def _assert_run_not_cancelled(run: Run) -> None:
    assert not _types(run, "cancel_requested") and not _types(run, "run_cancelled")
    assert not (run.run_dir / "cancel.request").exists()


def test_stop_before_dispatch_starts_nothing_and_other_work_continues(client):
    rid, run, body, eid = _approved_measure(client)
    other_rid, _other_run, _other_body, other_eid = _approved_measure(client)
    other_revision = _get(client, other_rid, other_eid)["revision"]
    stopped = _done(_act(client, rid, eid, "cancel"))
    assert stopped["status"] == "cancelled" and stopped["stop"]["reason"] == "stop"
    assert _done(_act(client, rid, eid, "advance"))["status"] == "cancelled"
    assert not _linked(run, eid, "tool_called") and not _linked(run, eid, "execution_call_admitted")
    _assert_run_not_cancelled(run)
    # A second execution of the same plan in the same run and manual tools still work; other runs untouched.
    second = _execution(client, rid, body["handle"])
    _approve(client, rid, second["execution_id"], body["plan_sha256"])
    assert _drive(client, rid, second["execution_id"])["status"] == "complete"
    manual = client.post(f"/runs/{rid}/commands", json={"tool": "measure_distance", "args": {
        "structure": body["plan"]["inputs"]["source"], "first": body["plan"]["inputs"]["second"],
        "second": body["plan"]["inputs"]["first"]}})
    assert manual.status_code == 200, manual.text
    assert _get(client, other_rid, other_eid)["revision"] == other_revision
    assert _drive(client, other_rid, other_eid)["status"] == "complete"


def test_stop_during_backoff_prevents_the_retry_and_keeps_the_charged_attempt(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)
    _fixture_tool(monkeypatch, "measure_distance", _transient(100))

    def sleep(seconds):
        # The user presses Stop while Run.call waits between transient attempts.
        ax.cancel(run, eid, str(uuid.uuid4()), ax.execution_detail(run, eid)["revision"])

    api_module._run(rid).sleep = sleep
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "cancelled" and record["steps"][0]["status"] == "cancelled"
    assert len(_linked(run, eid, "tool_called")) == 1 and len(_linked(run, eid, "tool_failed")) == 1
    assert _linked(run, eid, "execution_call_stopped")[0]["stage"] == "before_attempt"
    assert record["physical_attempts"] == 1 and record["active_wall_s"] >= 0
    _assert_run_not_cancelled(run)


def test_stop_during_a_running_call_does_not_adopt_its_result(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)

    def during(n, real, ctx, kwargs):
        ax.cancel(run, eid, str(uuid.uuid4()), ax.execution_detail(run, eid)["revision"])
        return real(ctx, **kwargs)  # the in-flight attempt completes and is recorded as charged

    _fixture_tool(monkeypatch, "measure_distance", during)
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "cancelled" and record["steps"][0]["status"] == "cancelled"
    assert record["steps"][0]["failure"]["reason_code"] == "result_after_stop_not_adopted"
    assert len(_linked(run, eid, "tool_succeeded")) == 1 and record["steps"][0]["outputs"] == {}
    assert record["steps"][1]["status"] == "pending" and not _types(run, "method_report_created")
    _assert_run_not_cancelled(run)


def test_stop_after_the_call_keeps_the_completed_step_and_starts_nothing_more(client, faults):
    _stages, _crash = faults
    rid, run, _body, eid = _approved_measure(client)

    def stop_then_continue(stage):
        if stage == "after_child":
            ax.cancel(run, eid, str(uuid.uuid4()), ax.execution_detail(run, eid)["revision"])

    ax._FAULT_HOOK = stop_then_continue
    record = _done(_act(client, rid, eid, "advance"))
    # The call finished before Stop was recorded: its step is truthfully completed, the execution is cancelled.
    assert record["status"] == "cancelled" and record["steps"][0]["status"] == "completed"
    assert record["steps"][1]["status"] == "pending" and record["summary_handle"] is None
    assert _done(_act(client, rid, eid, "advance"))["status"] == "cancelled"
    assert not _types(run, "method_report_created")
    assert client.get(f"/runs/{rid}/analysis/executions/{eid}/summary").status_code == 404


def test_report_publication_racing_stop_is_not_adopted_or_rewritten(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)
    _done(_act(client, rid, eid, "advance"))
    original = comparison_reports.build_comparison_report

    def racing(run_, handle, *, execution_link=None):
        ax.cancel(run, eid, str(uuid.uuid4()), ax.execution_detail(run, eid)["revision"])
        return original(run_, handle, execution_link=execution_link)

    monkeypatch.setattr(comparison_reports, "build_comparison_report", racing)
    record = _done(_act(client, rid, eid, "advance"))
    # Stop was recorded before the linked report admission: nothing is published for this execution.
    assert record["status"] == "cancelled" and record["steps"][1]["status"] == "cancelled"
    assert not _types(run, "method_report_created") and record["summary_handle"] is None


# ------------------------------------------------------------------------------ crash windows (run_call/report)
def _counts(run: Run, eid: str) -> dict[str, int]:
    return {kind: len(_linked(run, eid, kind)) for kind in ("tool_called", "execution_call_admitted", "cache_hit",
                                                             "method_report_created")} | {
        "branch_proposed": len([e for e in run.events.read() if e["type"] == "branch_proposed" and
                                e.get("branch_id") == f"analysis_{eid}"])}


def test_crash_window_1_before_child_admission_runs_the_operation_once(client, faults):
    stages, crash = faults
    rid, run, _body, eid = _approved_measure(client)
    stages["after_dispatch"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    pending = _get(client, rid, eid)
    assert pending["steps"][0]["status"] == "dispatched" and pending["recovery_pending"] is True
    assert _counts(run, eid)["tool_called"] == 0
    record = _done(_act(client, rid, eid, "advance"))
    assert record["steps"][0]["status"] == "completed"
    assert _counts(run, eid) == {"tool_called": 1, "execution_call_admitted": 1, "cache_hit": 0,
                                 "method_report_created": 0, "branch_proposed": 1}
    released = [e for e in run.events.read() if e["type"] == "analysis_dispatch_released"]
    assert len(released) == 1 and released[0]["reason_code"] == "not_started"
    interrupted = [e for e in run.events.read() if e["type"] == "analysis_request_completed" and
                   e["outcome"] == "interrupted"]
    assert len(interrupted) == 1


def test_crash_window_2_after_admission_is_interrupted_not_rerun(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)

    class Crash(BaseException):  # FAULT FIXTURE: the process dies inside the physical attempt
        pass

    def die(n, real, ctx, kwargs):
        if n == 1:
            raise Crash()
        return real(ctx, **kwargs)

    _fixture_tool(monkeypatch, "measure_distance", die)
    with pytest.raises(Crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    assert _get(client, rid, eid)["recovery_pending"] is True
    refused = _act(client, rid, eid, "advance")
    # Recovery ran first (recording the interruption), so this Advance is refused: retry or stop is required.
    assert refused.status_code == 412 and refused.json()["error"] == "retry_or_stop_required"
    record = _get(client, rid, eid)
    # Existing orphan reconciliation charged and closed the attempt; nothing ran again silently.
    assert record["status"] == "failed" and record["retryable_step"] == "s01"
    assert record["steps"][0]["status"] == "interrupted"
    assert _counts(run, eid)["tool_called"] == 1 and len(_linked(run, eid, "tool_interrupted")) == 1
    assert any(e["type"] == "wall_charged" and e.get("reason") == "orphan_recovery" for e in run.events.read())
    retried = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert retried["steps"][0]["status"] == "completed" and _counts(run, eid)["tool_called"] == 2


def test_crash_window_3_after_success_records_without_new_work(client, faults):
    stages, crash = faults
    rid, run, _body, eid = _approved_measure(client)
    stages["after_child"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    before = _counts(run, eid)
    guard_events = [e for e in run.events.read() if e["type"] in {"branch_proposed", "branch_observed", "checkpoint"}]
    reserved = _types(run, "budget_reserved")
    record = _done(_act(client, rid, eid, "advance"))
    assert record["steps"][0]["status"] == "completed"
    # The recorded completion reused the durable child; the same request then ran at most one next step.
    assert record["steps"][1]["status"] == "completed"
    after = _counts(run, eid)
    assert after["tool_called"] == before["tool_called"] == 1 and after["cache_hit"] == 0
    assert after["branch_proposed"] == before["branch_proposed"]
    assert [e for e in run.events.read() if e["type"] in {"branch_proposed", "branch_observed", "checkpoint"}] == \
        guard_events
    assert _types(run, "budget_reserved") == reserved


def test_crash_window_3_for_a_report_does_not_rewrite_it(client, faults):
    stages, crash = faults
    rid, run, _body, eid = _approved_measure(client)
    _done(_act(client, rid, eid, "advance"))
    stages["after_child"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    report_events = _types(run, "method_report_created")
    objects = len(_types(run, "object_created"))
    assert len(report_events) == 1
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "complete" and record["steps"][1]["report_handle"] == report_events[0]["report_handle"]
    assert _types(run, "method_report_created") == report_events
    assert len(_types(run, "object_created")) == objects + 1  # only the workflow summary object


def test_crash_window_4_rebuilds_completion_and_the_same_summary(client, faults):
    stages, crash = faults
    rid, run, body, eid = _approved_measure(client)
    _done(_act(client, rid, eid, "advance"))
    stages["before_summary"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    pending = _get(client, rid, eid)
    assert [step["status"] for step in pending["steps"]] == ["completed", "completed"]
    assert pending["status"] == "ready" and pending["recovery_pending"] is True and pending["summary_handle"] is None
    reports_before = _types(run, "method_report_created")
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "complete" and record["summary_handle"]
    assert _types(run, "method_report_created") == reports_before
    state = ax._fold(list(run.events.read()), eid, analysis_plans.load_plan(run, body["handle"]))
    expected = ax._summary_content(state, analysis_plans.load_plan(run, body["handle"]), list(run.events.read()))
    assert run.store.load(record["summary_handle"]) == expected
    # A crash after the summary object but before the completion event reuses the same handle.
    rid2, run2, _body2, eid2 = _approved_measure(client)
    _done(_act(client, rid2, eid2, "advance"))
    original = run2.events.append

    def crash_on_complete(*args, **data):
        if (args[0] if args else data.get("type")) == "analysis_execution_completed":
            raise crash("after summary object")
        return original(*args, **data)

    run2.events.append = crash_on_complete
    with pytest.raises(crash):
        ax.advance(run2, eid2, str(uuid.uuid4()), _get(client, rid2, eid2)["revision"])
    run2.events.append = original
    summaries = [e for e in run2.events.read() if e["type"] == "object_created" and e["kind"] == "workflow_summary"]
    assert len(summaries) == 1
    record2 = _done(_act(client, rid2, eid2, "advance"))
    assert record2["summary_handle"] == summaries[0]["handle"]
    assert len([e for e in run2.events.read() if e["type"] == "object_created" and
                e["kind"] == "workflow_summary"]) == 1


# ------------------------------------------------------------------------------ compatibility, identity, recovery
def test_compatibility_change_blocks_at_approval_and_at_dispatch(client, ligand_run, monkeypatch):
    rid, run, _raw, prepared, ligand = ligand_run
    body = _plan(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand, "cutoff_A": 4.0,
                                                 "types": ["contact"]})
    first = _execution(client, rid, body["handle"])["execution_id"]
    second = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, first, body["plan_sha256"])
    original = sasa.engine_capability()
    monkeypatch.setattr(sasa, "engine_capability", lambda: {**original, "engine_version": "fixture-changed"})
    blocked = _done(_act(client, rid, second, "approve", plan_hash=body["plan_sha256"]))
    assert blocked["status"] == "blocked" and blocked["blocked_reason"]["reason_code"] == "compatibility_changed"
    dispatch_blocked = _done(_act(client, rid, first, "advance"))
    assert dispatch_blocked["status"] == "blocked"
    assert dispatch_blocked["blocked_reason"]["reason_code"] == "compatibility_changed"
    assert not _linked(run, first, "tool_called") and not _linked(run, first, "execution_call_admitted")
    assert _act(client, rid, first, "advance").status_code == 200  # terminal: no-op


def test_identity_revalidation_after_preparation_blocks_without_remapping(client, ligand_run, monkeypatch):
    rid, run, raw, _prepared, ligand = ligand_run
    body = _plan(client, rid, "inspect_ligand", {"source": raw, "preparation": PREP, "ligand": ligand,
                                                 "cutoff_A": 4.0, "types": ["contact"]})
    eid = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, eid, body["plan_sha256"])
    assert _done(_act(client, rid, eid, "advance"))["steps"][0]["status"] == "completed"
    # FAULT FIXTURE: the prepared bytes no longer list the selected ligand instance (another one exists).
    other = {**ligand, "seq_auth": ligand["seq_auth"] + 1}
    monkeypatch.setattr(ax, "structure_residues", lambda store, handle: {"ligands": [other]})
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "blocked" and record["blocked_reason"]["reason_code"] == "identity_changed"
    assert not _linked(run, eid, "execution_call_admitted")[1:]  # only the preparation step was admitted


def test_events_only_recovery_without_engines_uploads_objects_or_sqlite(client, monkeypatch, tmp_path):
    rid, _run, _body, eid = _approved_measure(client)
    record = _drive(client, rid, eid)
    assert record["status"] == "complete"
    summary_raw = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary", params={"download": "json"}).content
    budget = client.get(f"/runs/{rid}/budget").json()
    run_dir = tmp_path / rid
    shutil.rmtree(run_dir / "objects")
    (run_dir / "index.sqlite").unlink()
    for name in ("uploads", "jobs.sqlite"):
        target = run_dir / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    api_module.RUNS.clear()

    def unavailable(*_args, **_kwargs):
        raise AssertionError("no engine or scientific implementation may run during recovery")

    for name in list(api_module.REGISTRY.impls):
        monkeypatch.setitem(api_module.REGISTRY.impls, name, unavailable)
    monkeypatch.setattr(sasa, "engine_capability", unavailable)
    monkeypatch.setattr(openmm_method, "capability", unavailable)
    restored = _get(client, rid, eid)
    assert {key: restored[key] for key in ("status", "revision", "summary_handle", "physical_attempts")} == {
        key: record[key] for key in ("status", "revision", "summary_handle", "physical_attempts")}
    assert [step["outputs"] for step in restored["steps"]] == [step["outputs"] for step in record["steps"]]
    assert client.get(f"/runs/{rid}/analysis/executions/{eid}/summary",
                      params={"download": "json"}).content == summary_raw
    assert client.get(f"/runs/{rid}/reports/selected",
                      params={"handle": record["steps"][1]["report_handle"]}).status_code == 200
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"] == budget["expensive_calls"]
    assert client.get(f"/runs/{rid}/analysis/executions").json()["rows"][0]["status"] == "complete"


def test_compare_plan_with_1000_ca_pairs_fits_and_is_stored_once(client):
    rid, run = _new(client)
    lines = []
    for index in range(1000):
        x, y, z = 3.8 * (index % 40), 3.8 * ((index // 40) % 25), 0.0
        lines.append(f"ATOM  {index + 1:5d}  CA  GLY A{index + 1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C")
    reference_bytes = ("\n".join(lines) + "\nEND\n").encode()  # DERIVED FIXTURE: synthetic CA-only chain
    moved = [line[:30] + f"{float(line[30:38]) + 1.5:8.3f}" + line[38:] for line in lines]
    moving_bytes = ("\n".join(moved) + "\nEND\n").encode()
    reference = run.call("load_structure", {"source": "ref.pdb", "model_index": 0}, source_bytes=reference_bytes,
                         source_format="pdb").handle
    moving = run.call("load_structure", {"source": "mov.pdb", "model_index": 0}, source_bytes=moving_bytes,
                      source_format="pdb").handle
    ref_rows, mov_rows = atom_rows(run.store, reference)["rows"], atom_rows(run.store, moving)["rows"]
    pairs = [{"reference": a["ref"], "moving": b["ref"]} for a, b in zip(ref_rows, mov_rows, strict=True)]
    assert len(pairs) == 1000
    request = json.dumps({"request_id": str(uuid.uuid4()), "goal": "compare_structures",
                          "inputs": {"reference": reference, "moving": moving, "pairs": pairs}}).encode()
    assert len(request) > 64 * 1024
    response = client.post(f"/runs/{rid}/analysis/plans", content=request, headers={"content-type": "application/json"})
    assert response.status_code == 201, response.text
    plan = response.json()["plan"]
    size = len(canonical_json(plan))
    assert 64 * 1024 < size <= analysis_plans.MAX_PLAN_BYTES
    assert canonical_json(plan).count(canonical_json(pairs[0])) == 1  # the pair map is stored once
    assert analysis_plans.resolved_params(plan, plan["steps"][0]) == {"pairs": pairs}


# ------------------------------------------------------------------------------ durable-job lane (real fpocket)
def _cavities(client: TestClient, ubq_run) -> tuple[str, Run, dict, str]:
    rid, run, _raw, prepared = ubq_run
    body = _plan(client, rid, "find_cavities", {"source": prepared, "chains": ["A"]})
    eid = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, eid, body["plan_sha256"])
    return rid, run, body, eid


def test_find_cavities_job_scientific_approval_gate_and_already_approved_state(client, ubq_run):
    rid, run, body, eid = _cavities(client, ubq_run)
    record = _get(client, rid, eid)
    assert record["scientific_approval"]["state"] == "not_yet_requested"
    gated = _done(_act(client, rid, eid, "advance"))
    # Submission and start are one transition; the run's first expensive call stops at the existing gate.
    assert gated["status"] == "awaiting_scientific_approval"
    step = gated["steps"][0]
    assert step["status"] == "waiting_job" and step["job_ownership"] == "owned" and step["job_status"] == "claimed"
    assert gated["scientific_approval"]["state"] == "pending"
    assert gated["scientific_approval"]["pending_tool"] == "detect_pockets"
    assert gated["plan_approval"]["approved"] is True and not _types(run, "approval_resolved")
    assert not _types(run, "budget_reserved")
    # Advance does not bypass the gate.
    assert _done(_act(client, rid, eid, "advance"))["status"] == "awaiting_scientific_approval"
    approved = _done(_act(client, rid, eid, "scientific-approval"))
    assert approved["scientific_approval"]["state"] == "already_approved_in_run" and approved["status"] == "ready"
    assert _types(run, "approval_resolved")[0]["by"] == "human_api"
    assert _act(client, rid, eid, "scientific-approval").status_code == 412
    ran = _done(_act(client, rid, eid, "advance"))
    assert ran["steps"][0]["status"] == "completed" and ran["steps"][0]["job_status"] == "done"
    pocket_set = ran["steps"][0]["outputs"]["pocket_set"]
    assert run.store.meta(pocket_set)["kind"] == "pocket_set"
    assert ran["steps"][0]["attempts"] == 1 and len(_types(run, "job_submitted")) == 1
    final = _done(_act(client, rid, eid, "advance"))
    assert final["status"] == "complete"
    report = client.get(f"/runs/{rid}/reports/selected", params={"handle": final["steps"][1]["report_handle"]})
    assert report.status_code == 200 and report.json()["manifest"]["analysis_type"] == "pocket_detection"
    summary = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary").json()["summary"]
    assert summary["steps"][0]["job_ids"] == [ran["steps"][0]["job_id"]]
    assert summary["steps"][0]["job_ownership"] == "owned"
    # A second execution in the same run shows the prior run approval and never asks again.
    body2 = _plan(client, rid, "find_cavities", {"source": body["plan"]["inputs"]["source"], "chains": ["A"]})
    second = _execution(client, rid, body2["handle"])
    assert second["scientific_approval"]["state"] == "already_approved_in_run"
    assert second["plan_approval"]["approved"] is False  # the run approval never substitutes plan approval


def test_job_crash_windows_resume_the_same_owned_job_without_duplicates(client, ubq_run, faults):
    stages, crash = faults
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    stages["after_dispatch"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    assert not _types(run, "job_submitted")
    stages["after_job_submit"] = 1
    with pytest.raises(crash):
        _act(client, rid, eid, "advance")
    submitted = _types(run, "job_submitted")
    assert len(submitted) == 1 and submitted[0]["execution_link"]["execution_id"] == eid
    waiting = _get(client, rid, eid)
    assert waiting["steps"][0]["job_status"] == "queued" and waiting["status"] == "ready"
    stages["after_child"] = 1
    with pytest.raises(crash):
        _act(client, rid, eid, "advance")  # starts the same owned job (no new submission) then dies
    assert len(_types(run, "job_submitted")) == 1 and len(_types(run, "budget_reserved")) == 1
    done_job = _get(client, rid, eid)
    assert done_job["steps"][0]["job_status"] == "done" and done_job["steps"][0]["status"] == "dispatched"
    assert done_job["recovery_pending"] is True  # derived only: the read recorded nothing
    reserved = _types(run, "budget_reserved")
    record = _done(_act(client, rid, eid, "advance"))
    assert record["steps"][0]["status"] == "completed" and record["steps"][1]["status"] == "completed"
    assert _types(run, "budget_reserved") == reserved and len(_types(run, "job_submitted")) == 1
    assert len(_types(run, "job_dispatch_intent")) == 1
    assert _done(_act(client, rid, eid, "advance"))["status"] == "complete"


def test_run_budget_checkpoint_dispatches_nothing_and_stays_ready(client, ubq_run):
    from mw.runtime.guards import BudgetLimits
    rid, run, _body, eid = _cavities(client, ubq_run)
    live = api_module._run(rid)
    live.approve("expensive_first_call")
    live.update_limits(BudgetLimits(expensive_calls=0))
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "ready" and record["notice"]["code"] == "run_budget_exhausted"
    assert "run 예산" in record["notice"]["message"]
    assert not _types(run, "budget_reserved") and not _types(run, "job_dispatch_intent")
    assert not [e for e in run.events.read() if e["type"] == "budget_limit_updated" and e.get("by") != "human"]
    live.update_limits(BudgetLimits(expensive_calls=8))
    assert _done(_act(client, rid, eid, "advance"))["steps"][0]["status"] == "completed"


def test_stop_during_owned_real_job_cancels_only_that_job(client, ubq_run, monkeypatch):
    import threading
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    reached, release = threading.Event(), threading.Event()

    def barrier(stage):
        if stage == "after_go":
            reached.set()
            assert release.wait(20)

    monkeypatch.setattr(ax, "_job_queue", lambda run_: JobQueue(run_, barrier=barrier))
    results: list = []
    worker = threading.Thread(target=lambda: results.append(
        ax.advance(run, eid, str(uuid.uuid4()), ax.execution_detail(run, eid)["revision"])))
    worker.start()
    try:
        assert reached.wait(30)
        running = _get(client, rid, eid)
        assert running["status"] == "waiting_job" and running["steps"][0]["job_status"] == "running"
        stopped = _done(_act(client, rid, eid, "cancel"))  # never busy while the owner runs the job
        assert stopped["status"] == "cancelled" and stopped["steps"][0]["job_cancel_requested"] is True
    finally:
        release.set()
        worker.join(60)
    record = _get(client, rid, eid)
    job = JobQueue(run).get(record["steps"][0]["job_id"])
    assert job["status"] == "cancelled" and job["cleanup_status"] == "verified"
    assert record["steps"][0]["status"] == "cancelled" and record["steps"][1]["status"] == "pending"
    assert len(_types(run, "budget_reserved")) == 1  # the started attempt stays charged
    assert any(e["type"] == "job_cancel_requested" and e["execution_link"]["execution_id"] == eid
               for e in run.events.read())
    _assert_run_not_cancelled(run)


def test_shared_manual_job_is_observed_never_started_or_cancelled(client, ubq_run):
    rid, run, body, eid = _cavities(client, ubq_run)
    manual = JobQueue(run).submit("fpocket_detect_v1", {"structure": body["plan"]["inputs"]["source"],
                                                        "chains": ["A"]}, timeout_s=120)
    record = _done(_act(client, rid, eid, "advance"))
    step = record["steps"][0]
    assert step["job_id"] == manual["job_id"] and step["job_ownership"] == "observed_shared"
    assert record["status"] == "waiting_job" and step["shared_job_notice"]
    assert not _types(run, "job_claimed") and _types(run, "job_observed")
    assert _done(_act(client, rid, eid, "advance"))["status"] == "waiting_job"  # observe only
    stopped = _done(_act(client, rid, eid, "cancel"))
    assert stopped["status"] == "cancelled" and stopped["steps"][0]["status"] == "cancelled"
    assert JobQueue(run).get(manual["job_id"])["status"] == "queued"  # untouched
    assert not _types(run, "job_cancel_requested")
    # A new execution observes the same manual job; once the user runs it manually the step completes.
    second = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, second, body["plan_sha256"])
    assert _done(_act(client, rid, second, "advance"))["steps"][0]["job_ownership"] == "observed_shared"
    api_module._run(rid).approve("expensive_first_call")
    assert client.post(f"/runs/{rid}/jobs/{manual['job_id']}/start").status_code == 200
    done = _done(_act(client, rid, second, "advance"))
    assert done["steps"][0]["status"] == "completed" and done["steps"][0]["job_ownership"] == "observed_shared"
    assert len(_types(run, "job_submitted")) == 1
    assert _done(_act(client, rid, second, "advance"))["status"] == "complete"


# ------------------------------------------------------------------------------ real engines: every template
def _run_template(client: TestClient, rid: str, goal: str, inputs: dict) -> tuple[dict, dict]:
    body = _plan(client, rid, goal, inputs)
    eid = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, eid, body["plan_sha256"])
    record = _drive(client, rid, eid)
    assert record["status"] == "complete", record
    assert [step["operation"] for step in record["steps"]] == [step["operation"] for step in body["plan"]["steps"]]
    assert all(step["status"] == "completed" for step in record["steps"])
    for step in record["steps"]:
        if step["lane"] == "report":
            report = client.get(f"/runs/{rid}/reports/selected", params={"handle": step["report_handle"]})
            assert report.status_code == 200, report.text
            for fmt in ("markdown", "json"):
                download = client.get(f"/runs/{rid}/reports/download",
                                      params={"handle": step["report_handle"], "format": fmt})
                assert download.status_code == 200 and download.content
    summary = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary").json()["summary"]
    assert [row["step_id"] for row in summary["steps"]] == [step["step_id"] for step in record["steps"]]
    return body, record


def test_inspect_ligand_from_raw_structure_with_real_freesasa(client, ligand_run):
    rid, run, raw, _prepared, ligand = ligand_run
    _body, record = _run_template(client, rid, "inspect_ligand", {"source": raw, "preparation": PREP,
                                                                 "ligand": ligand, "cutoff_A": 4.0,
                                                                 "types": ["contact", "polar_contact"]})
    prepared = record["steps"][0]["outputs"]["prepared_structure"]
    contacts = run.store.load(record["steps"][1]["outputs"]["interaction_set"])
    assert contacts["structure"] == prepared and contacts["selection"]["ligand"] == ligand  # 7 fields, nulls kept
    sasa_result = run.store.load(record["steps"][2]["outputs"]["interface_sasa"])
    assert sasa_result["ligand"] == ligand
    inspection = client.get(f"/runs/{rid}/reports/selected",
                            params={"handle": record["steps"][3]["report_handle"]}).json()["manifest"]
    assert inspection["interaction_handle"] == record["steps"][1]["outputs"]["interaction_set"]
    assert inspection["prepared_handle"] == prepared
    branch = f"analysis_{record['execution_id']}"
    assert not [e for e in run.events.read() if e["type"] == "checkpoint" and e.get("branch_id") == branch]
    calls = _linked(run, record["execution_id"], "tool_called")
    # The fixture already prepared the same source with the same policy: the preparation step reuses that
    # immutable result through the ordinary cache rule, attributed to this operation (no physical attempt).
    hits = _linked(run, record["execution_id"], "cache_hit")
    assert [e["tool"] for e in hits] == ["prepare_structure"] and record["steps"][0]["attempts"] == 0
    assert record["steps"][0]["child_call_ids"] == [hits[0]["source_call_id"]]
    assert [e["tool"] for e in calls] == ["compute_interactions", "compute_interface_sasa"]
    assert all(e["decided_by"] == "rule" and e["execution_mode"] == "autonomous" and e["branch_id"] == branch
               for e in calls)


def test_scientific_null_step_completes_and_later_steps_continue(client):
    rid, run = _new(client)
    lines = (FIX / "mini_complex.pdb").read_text().splitlines()
    shifted = []
    for line in lines:  # DERIVED FIXTURE: the LIG B 301 instance moved 40 A away (no protein contact)
        if line.startswith("HETATM") and line[17:20] == "LIG":
            line = line[:30] + f"{float(line[30:38]) + 40.0:8.3f}" + line[38:]
        shifted.append(line)
    raw = run.call("load_structure", {"source": "far.pdb", "model_index": 0},
                   source_bytes=("\n".join(shifted) + "\n").encode(), source_format="pdb").handle
    prepared = _prepare(run, raw)
    ligand = _ligand(run, raw)
    _body, record = _run_template(client, rid, "inspect_ligand", {"source": prepared, "ligand": ligand,
                                                                 "cutoff_A": 4.0, "types": ["contact"]})
    contacts = record["steps"][0]
    assert contacts["null_result"] is True and run.store.meta(contacts["outputs"]["interaction_set"])["null_result"]
    report = client.get(f"/runs/{rid}/reports/selected", params={"handle": record["steps"][2]["report_handle"]})
    assert report.json()["manifest"]["scientific_null"] is True
    assert record["physical_attempts"] == 2 and not any(step["retries_used"] for step in record["steps"])


def test_compare_structures_with_real_alignment(client, m10_run):
    rid, run, reference, moving, ref_catalog, mov_catalog = m10_run
    pairs = _pairs(ref_catalog, mov_catalog)
    _body, record = _run_template(client, rid, "compare_structures", {"reference": reference, "moving": moving,
                                                                     "pairs": pairs})
    alignment = run.store.load(record["steps"][0]["outputs"]["rigid_alignment"])
    assert alignment["reference_handle"] == reference or reference in json.dumps(alignment)


def test_minimize_protein_with_real_openmm(client, ubq_run):
    rid, _run, _raw, prepared = ubq_run
    _body, record = _run_template(client, rid, "minimize_protein", {"source": prepared,
                                                                   "selection_policy": "protein_only",
                                                                   "hydrogen_policy": "rebuild_pH7"})
    result = client.get(f"/runs/{rid}/openmm_minimization",
                        params={"handle": record["steps"][0]["outputs"]["openmm_minimization"]})
    assert result.status_code == 200 and result.json()["result"]["structure"] == prepared
    assert record["steps"][0]["job_ownership"] == "owned" and record["steps"][0]["attempts"] == 1


@pytest.mark.parametrize("mode", ["create_new", "attach_existing"])
def test_chemical_interactions_with_the_real_prolif_environment(client, mode):
    rid, run = _new(client)
    request = _create_new_request(run) if mode == "create_new" else _attach_request(run)
    _body, record = _run_template(client, rid, "chemical_interactions", {"request": request})
    prepare, detect, report = record["steps"]
    assert prepare["job_ownership"] == detect["job_ownership"] == "owned"
    manifest = run.store.load_bounded_json(prepare["outputs"]["preparation_manifest"], 8 * 1024 * 1024)
    assert manifest["request"] == request and manifest["mode"] == mode
    result = client.get(f"/runs/{rid}/chemical/results",
                        params={"handle": detect["outputs"]["chemical_interaction_set"]})
    assert result.status_code == 200
    assert result.json()["result"]["graph_handle"] == prepare["outputs"]["chemical_graph"]
    manifest_json = client.get(f"/runs/{rid}/reports/selected", params={"handle": report["report_handle"]}).json()
    assert manifest_json["manifest"]["analysis_type"] == "chemical_interactions"
    assert record["physical_attempts"] == 2


def test_owned_job_failure_allows_one_explicit_retry_of_the_same_job(client, ubq_run, monkeypatch):
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    original = JobQueue._publish_pocket

    def broken(self, *args, **kwargs):  # FAULT FIXTURE: the real worker ran; its publication fails once
        raise ValueError("fixture publication failure")

    monkeypatch.setattr(JobQueue, "_publish_pocket", broken)
    failed = _done(_act(client, rid, eid, "advance"))
    assert failed["status"] == "failed" and failed["retryable_step"] == "s01"
    job_id = failed["steps"][0]["job_id"]
    assert JobQueue(run).get(job_id)["status"] == "failed" and failed["steps"][0]["attempts"] == 1
    monkeypatch.setattr(JobQueue, "_publish_pocket", original)
    retried = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert retried["steps"][0]["status"] == "completed" and retried["steps"][0]["job_id"] == job_id
    assert len(_types(run, "job_submitted")) == 1 and len(_types(run, "budget_reserved")) == 2  # both charged
    retry_events = _types(run, "job_retry_queued")
    assert len(retry_events) == 1 and retry_events[0]["execution_link"]["execution_id"] == eid
    assert retried["physical_attempts"] == 2 and retried["steps"][0]["retries_used"] == 1


def test_revoke_after_dispatch_cancels_the_owned_waiting_job(client, ubq_run):
    rid, run, _body, eid = _cavities(client, ubq_run)
    gated = _done(_act(client, rid, eid, "advance"))
    assert gated["status"] == "awaiting_scientific_approval"
    revoked = _done(_act(client, rid, eid, "revoke"))
    assert revoked["status"] == "cancelled" and revoked["plan_approval"]["revocations"][0]["outcome"] == "cancelled"
    job = JobQueue(run).get(gated["steps"][0]["job_id"])
    assert job["status"] == "cancelled" and revoked["steps"][0]["status"] == "cancelled"
    assert not _types(run, "approval_resolved") and not _types(run, "budget_reserved")
    assert _act(client, rid, eid, "scientific-approval").status_code == 412
    _assert_run_not_cancelled(run)


# ------------------------------------------------------------------------------ review follow-up (recovery first)
def test_stop_after_crash_window_4_finishes_the_complete_execution_first(client, faults):
    stages, crash = faults
    rid, run, _body, eid = _approved_measure(client)
    _done(_act(client, rid, eid, "advance"))
    stages["before_summary"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    stopped = _done(_act(client, rid, eid, "cancel"))
    # Recovery runs first: every step was already complete, so the execution completes with its summary.
    assert stopped["status"] == "complete" and stopped["summary_handle"] and stopped["stop"] is None
    summary = client.get(f"/runs/{rid}/analysis/executions/{eid}/summary").json()["summary"]
    last_completion = max(e["seq"] for e in run.events.read() if e["type"] == "analysis_step_completed")
    assert summary["last_event_seq"] == last_completion  # seq of the last step-completion event
    assert "last_event_seq" in summary["note"]


def test_stop_after_crash_window_3_on_the_last_step_completes(client, faults):
    stages, crash = faults
    rid, run, _body, eid = _approved_measure(client)
    _done(_act(client, rid, eid, "advance"))
    stages["after_child"] = 1
    with pytest.raises(crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    stopped = _done(_act(client, rid, eid, "cancel"))
    assert stopped["status"] == "complete" and stopped["summary_handle"]
    assert len(_types(run, "method_report_created")) == 1


def test_retry_after_crash_window_2_is_accepted_after_recovery(client, monkeypatch):
    rid, run, _body, eid = _approved_measure(client)

    class Crash(BaseException):  # FAULT FIXTURE: the process dies inside the physical attempt
        pass

    def die(n, real, ctx, kwargs):
        if n == 1:
            raise Crash()
        return real(ctx, **kwargs)

    _fixture_tool(monkeypatch, "measure_distance", die)
    with pytest.raises(Crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    retried = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert retried["steps"][0]["status"] == "completed" and retried["steps"][0]["retries_used"] == 1
    assert len(_linked(run, eid, "tool_called")) == 2 and len(_linked(run, eid, "tool_interrupted")) == 1


def test_existing_loop_guard_stops_repeated_linked_calls(client, monkeypatch, tmp_path):
    from mw.workspace import load_config, new_run
    rid = f"run_{uuid.uuid4().hex}"
    config = load_config()
    config["runtime"]["loop_guards"] = {**config["runtime"]["loop_guards"], "repeated_call_hash": 1}
    # The run is created with a stricter repeat guard; the API reopens it with its recorded configuration.
    new_run(tmp_path, run_id=rid, registry=api_module.REGISTRY, dry_run=False, config=config)
    run = api_module._run(rid)
    assert run.guard.repeated_call_hash == 1
    reference = _load(run, M10 / "m10-reference.pdb")
    catalog = atom_rows(run.store, reference)
    body = _plan(client, rid, "measure_atoms", {"source": reference, "first": _atom(catalog, 10, "N"),
                                                "second": _atom(catalog, 11, "O")})
    eid = _execution(client, rid, body["handle"])["execution_id"]
    _approve(client, rid, eid, body["plan_sha256"])
    run.sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(100))
    assert _done(_act(client, rid, eid, "advance"))["retryable_step"] == "s01"
    stopped = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert stopped["status"] == "failed" and stopped["retryable_step"] is None
    assert stopped["steps"][0]["failure"]["reason_code"] == "loop_guard_repeated_call_hash"
    branch = f"analysis_{eid}"
    assert [e for e in run.events.read() if e["type"] == "checkpoint" and e.get("branch_id") == branch]
    proposals = [e for e in run.events.read() if e["type"] == "branch_proposed" and e.get("branch_id") == branch]
    assert _done(_act(client, rid, eid, "advance"))["status"] == "failed"
    assert _done(_act(client, rid, eid, "cancel"))["status"] == "failed"  # terminal: Stop is a no-op
    assert [e for e in run.events.read() if e["type"] == "branch_proposed" and
            e.get("branch_id") == branch] == proposals  # recovery manufactured no proposals


def test_job_crash_window_2_while_running_is_interrupted_without_a_second_job(client, ubq_run, monkeypatch):
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")

    class Crash(BaseException):  # FAULT FIXTURE: the server process dies while the owned job runs
        pass

    def barrier(stage):
        if stage == "after_go":
            raise Crash(stage)

    monkeypatch.setattr(ax, "_job_queue", lambda run_: JobQueue(run_, barrier=barrier))
    with pytest.raises(Crash):
        ax.advance(run, eid, str(uuid.uuid4()), _get(client, rid, eid)["revision"])
    monkeypatch.setattr(ax, "_job_queue", JobQueue)
    assert JobQueue(run).get(_types(run, "job_submitted")[0]["job"]["job_id"])["status"] == "running"
    api_module.RUNS.clear()  # restart: the existing supervisor reconciles the orphaned job on reopen
    response = _act(client, rid, eid, "advance")
    run = api_module._run(rid)
    record = _get(client, rid, eid)
    step = record["steps"][0]
    if step["job_status"] == "interrupted":  # supervisor verified the group empty and closed the attempt
        # Recovery ran first and recorded the interruption, so the Advance itself is refused.
        assert response.status_code == 412 and response.json()["error"] == "retry_or_stop_required"
        assert step["status"] == "interrupted" and record["status"] == "failed" and record["retryable_step"] == "s01"
    else:  # cleanup pending per existing supervisor semantics: still observed, nothing restarted
        assert response.status_code == 200 and step["job_cleanup_status"] == "pending"
    assert len(_types(run, "job_submitted")) == 1 and len(_types(run, "job_dispatch_intent")) == 1
    assert len(_types(run, "budget_reserved")) == 1
    assert any(e["type"] == "wall_charged" and e.get("reason") in {"job_attempt", "job_orphan_recovery"}
               for e in run.events.read())


def test_owned_job_timeout_is_retryable_once(client, ubq_run, monkeypatch):
    rid, _run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    original = JobQueue._publish_pocket

    def timed_out(self, *args, **kwargs):  # FAULT FIXTURE: the job ends as the queue's timeout failure
        return {"status": "failed", "failure": {"error": "resource_exceeded", "message": "job timeout"}}

    monkeypatch.setattr(JobQueue, "_publish_pocket", timed_out)
    failed = _done(_act(client, rid, eid, "advance"))
    assert failed["status"] == "failed" and failed["retryable_step"] == "s01"
    monkeypatch.setattr(JobQueue, "_publish_pocket", original)
    assert _done(_act(client, rid, eid, "retry", step_id="s01"))["steps"][0]["status"] == "completed"


def test_revoke_after_a_released_dispatch_returns_to_awaiting_approval(client):
    import threading
    rid, run, _body, eid = _approved_measure(client)
    held, release = threading.Event(), threading.Event()

    def hold_owner():
        with run._owner():
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold_owner)
    holder.start()
    try:
        assert held.wait(10)
        busy = _done(_act(client, rid, eid, "advance"))
        assert busy["notice"]["code"] == "run_busy" and busy["steps"][0]["status"] == "pending"
    finally:
        release.set()
        holder.join(10)
    revoked = _done(_act(client, rid, eid, "revoke"))
    assert revoked["status"] == "awaiting_approval"  # no child was admitted: nothing to cancel


def test_read_probe_never_makes_a_concurrent_advance_busy(client):
    import threading
    _rid, run, _body, eid = _approved_measure(client)
    stop = threading.Event()

    def hammer():
        while not stop.is_set():
            ax.execution_detail(run, eid)
            ax._driver_live(run, eid)

    readers = [threading.Thread(target=hammer) for _ in range(3)]
    for reader in readers:
        reader.start()
    try:
        for _ in range(40):
            revision = ax.execution_detail(run, eid)["revision"]
            result = ax.advance(run, eid, str(uuid.uuid4()), revision)
            assert result["execution"]["status"] in {"ready", "complete"}
    finally:
        stop.set()
        for reader in readers:
            reader.join(10)


# ------------------------------------------------------------------------------ review follow-up (guards, jobs, list)
def _branch_proposals(run: Run, eid: str) -> list[dict]:
    return [e for e in run.events.read() if e["type"] == "branch_proposed" and e.get("branch_id") == f"analysis_{eid}"]


def test_run_budget_release_never_raises_the_loop_guard_and_resumes_after_the_limit_change(client):
    from mw.runtime.guards import BudgetLimits
    rid, run, _body, eid = _approved_measure(client)
    live = api_module._run(rid)
    live.update_limits(BudgetLimits(wall_clock_s=max(live.budget.wall_clock_s, 1e-6)))
    for _ in range(4):
        record = _done(_act(client, rid, eid, "advance"))
        assert record["status"] == "ready" and record["notice"]["code"] == "run_budget_exhausted"
        assert record["steps"][0]["status"] == "pending" and record["steps"][0]["failure"] is None
    assert not _branch_proposals(run, eid) and not _linked(run, eid, "tool_called")
    assert record["physical_attempts"] == 0
    live.update_limits(BudgetLimits(wall_clock_s=1800))  # the existing limit-change path; never the workflow
    record = _done(_act(client, rid, eid, "advance"))
    assert record["steps"][0]["status"] == "completed" and len(_branch_proposals(run, eid)) == 1
    assert _drive(client, rid, eid)["status"] == "complete"


def test_retry_released_by_the_run_budget_never_raises_the_loop_guard(client, monkeypatch):
    from mw.runtime.guards import BudgetLimits
    rid, run, _body, eid = _approved_measure(client)
    live = api_module._run(rid)
    live.sleep = lambda seconds: None
    _fixture_tool(monkeypatch, "measure_distance", _transient(4))
    assert _done(_act(client, rid, eid, "advance"))["retryable_step"] == "s01"
    live.update_limits(BudgetLimits(wall_clock_s=max(live.budget.wall_clock_s, 1e-6)))
    released = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert released["status"] == "ready" and released["notice"]["code"] == "run_budget_exhausted"
    assert released["steps"][0]["retries_used"] == 0  # a released retry is not used up
    for _ in range(3):
        again = _done(_act(client, rid, eid, "advance"))  # resumes the released retry; still not started
        assert again["status"] == "ready" and again["notice"]["code"] == "run_budget_exhausted"
    assert len(_branch_proposals(run, eid)) == 1  # only the first real call proposed
    live.update_limits(BudgetLimits(wall_clock_s=1800))
    record = _done(_act(client, rid, eid, "advance"))
    assert record["steps"][0]["status"] == "completed" and record["steps"][0]["retries_used"] == 1
    assert len(_branch_proposals(run, eid)) == 2


def test_unclosed_job_release_records_no_proposal(client):
    rid, run, _body, eid = _approved_measure(client)
    live = api_module._run(rid)

    def pending():  # FAULT FIXTURE: an unclosed physical job elsewhere in the run
        raise ToolFailure(FailureClass.precondition, "running job needs verified cleanup before new work",
                          detail={"job_id": "job_x", "reason_code": "job_cleanup_pending"})

    live._check_jobs_clear = pending
    try:
        for _ in range(3):
            record = _done(_act(client, rid, eid, "advance"))
            assert record["status"] == "ready" and record["notice"]["code"] == "job_cleanup_pending"
    finally:
        del live._check_jobs_clear
    assert not _branch_proposals(run, eid)
    assert _done(_act(client, rid, eid, "advance"))["steps"][0]["status"] == "completed"


@pytest.mark.parametrize(("failure", "retryable"), [
    ({"error": "resource_exceeded", "message": "worker memory or output limit exceeded"}, False),
    ({"error": "resource_exceeded", "message": "job timeout during guardian bootstrap"}, True),
    ({"error": "fatal", "message": "worker exit or abandoned helper"}, True),
])
def test_owned_job_resource_exceeded_is_not_retryable_but_failure_and_timeout_are(client, ubq_run, monkeypatch,
                                                                                    failure, retryable):
    rid, _run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    monkeypatch.setattr(JobQueue, "_publish_pocket",  # FAULT FIXTURE: the real worker ran; the queue records this
                        lambda self, *a, **k: {"status": "failed", "failure": dict(failure)})
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "failed" and record["steps"][0]["failure"]["error"] == failure["error"]
    assert record["retryable_step"] == ("s01" if retryable else None)
    assert record["steps"][0]["failure"]["retryable"] is retryable


def test_manual_start_and_retry_refuse_workflow_owned_jobs_but_cancel_is_observed(client, ubq_run):
    rid, run, _body, eid = _cavities(client, ubq_run)
    gated = _done(_act(client, rid, eid, "advance"))
    job_id = gated["steps"][0]["job_id"]
    assert gated["status"] == "awaiting_scientific_approval" and gated["steps"][0]["job_ownership"] == "owned"
    api_module._run(rid).approve("expensive_first_call")
    for action in ("start", "retry"):
        refused = client.post(f"/runs/{rid}/jobs/{job_id}/{action}")
        assert refused.status_code == 412, refused.text
        assert refused.json()["detail"]["reason_code"] == "job_owned_by_analysis_execution"
    assert not _types(run, "budget_reserved") and not _types(run, "job_retry_queued")
    # Manual cancel stays a user safety control; the workflow observes it as a cancelled job.
    assert client.post(f"/runs/{rid}/jobs/{job_id}/cancel").json()["status"] == "accepted"
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "failed" and record["retryable_step"] is None
    assert record["steps"][0]["failure"]["reason_code"] == "job_cancelled"


def test_workflow_retry_that_finds_its_job_requeued_elsewhere_is_released_not_blocked(client, ubq_run, monkeypatch):
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    monkeypatch.setattr(JobQueue, "_publish_pocket",  # FAULT FIXTURE: an ordinary owned-job failure
                        lambda self, *a, **k: {"status": "failed",
                                               "failure": {"error": "fatal", "message": "fixture failure"}})
    failed = _done(_act(client, rid, eid, "advance"))
    job_id = failed["steps"][0]["job_id"]
    assert failed["retryable_step"] == "s01"
    with run._transition():  # FAULT FIXTURE: re-queued outside this execution (e.g. a pre-fix manual retry)
        run.events.append("job_retry_queued", job_id=job_id, retry_index=1)
    assert JobQueue(run).get(job_id)["status"] == "queued"
    record = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert record["status"] != "blocked" and record["blocked_reason"] is None
    assert record["notice"]["code"] == "not_started" and record["steps"][0]["status"] == "pending"
    assert JobQueue(run).get(job_id)["status"] == "queued" and not _types(run, "job_cancel_requested")


def test_attempt_limit_never_refuses_a_report_step(client, monkeypatch):
    monkeypatch.setitem(analysis_plans.LIMITS, "max_physical_attempts", 1)
    rid, run, _body, eid = _approved_measure(client)
    first = _done(_act(client, rid, eid, "advance"))
    assert first["steps"][0]["status"] == "completed" and first["physical_attempts"] == 1
    final = _done(_act(client, rid, eid, "advance"))
    assert final["status"] == "complete" and final["steps"][1]["status"] == "completed"
    assert not _types(run, "analysis_attempt_refused")


def test_execution_list_reads_once_and_isolates_a_corrupt_execution(client):
    rid, run, body, eid = _approved_measure(client)
    other = _execution(client, rid, body["handle"])["execution_id"]
    third = _execution(client, rid, body["handle"])["execution_id"]
    _done(_act(client, rid, eid, "advance"))
    reads = {"n": 0}
    original = run.events.read

    def counted(*args, **kwargs):
        reads["n"] += 1
        return original(*args, **kwargs)

    run.events.read = counted
    try:
        listed = client.get(f"/runs/{rid}/analysis/executions").json()
    finally:
        del run.events.read
    assert reads["n"] == 1 and listed["total"] == 3
    assert [row["execution_id"] for row in listed["rows"]] == [eid, other, third]
    assert all(row["error"] is None for row in listed["rows"])
    assert listed["rows"][0]["status"] == "ready" and listed["rows"][1]["status"] == "awaiting_approval"
    with run._transition():  # FAULT FIXTURE: a damaged causal record names a step outside the plan
        run.events.append(ax.STEP_DONE, execution_id=other, step_id="s09", operation_id="op_x", outputs={},
                          null_result=False, child={})
    listed = client.get(f"/runs/{rid}/analysis/executions")
    assert listed.status_code == 200
    rows = {row["execution_id"]: row for row in listed.json()["rows"]}
    assert rows[other]["error"]["code"] == "execution_record_invalid" and rows[other]["status"] is None
    assert rows[eid]["status"] == "ready" and rows[third]["status"] == "awaiting_approval"
    assert client.get(f"/runs/{rid}/analysis/executions/{other}").status_code == 409  # detail fails closed


# ------------------------------------------------------------------------------ final review follow-up
def test_manual_retry_of_an_owned_job_is_allowed_once_its_execution_has_ended(client, ubq_run, monkeypatch):
    rid, run, _body, eid = _cavities(client, ubq_run)
    api_module._run(rid).approve("expensive_first_call")
    original = JobQueue._publish_pocket
    monkeypatch.setattr(JobQueue, "_publish_pocket",  # FAULT FIXTURE: the real worker ran; publication fails
                        lambda self, *a, **k: {"status": "failed",
                                               "failure": {"error": "fatal", "message": "fixture failure"}})
    failed = _done(_act(client, rid, eid, "advance"))
    job_id = failed["steps"][0]["job_id"]
    assert failed["retryable_step"] == "s01"
    # The execution still drives the job (its explicit retry is left): manual retry stays refused.
    refused = client.post(f"/runs/{rid}/jobs/{job_id}/retry")
    assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "job_owned_by_analysis_execution"
    ended = _done(_act(client, rid, eid, "retry", step_id="s01"))
    assert ended["status"] == "failed" and ended["retryable_step"] is None
    assert JobQueue(run).get(job_id)["status"] == "failed"
    # The owning execution ended: the existing manual retry rules apply again (up to 4 attempts).
    monkeypatch.setattr(JobQueue, "_publish_pocket", original)
    requeued = client.post(f"/runs/{rid}/jobs/{job_id}/retry")
    assert requeued.status_code == 200, requeued.text
    assert requeued.json()["status"] == "queued"
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    assert JobQueue(run).get(job_id)["status"] == "done"
    after = _get(client, rid, eid)  # the ended execution is not rewritten by the manual rerun
    assert after["status"] == "failed" and after["steps"][0]["status"] == "failed"


def _gated_owned_job(client: TestClient, ubq_run) -> tuple[str, Run, str, str]:
    rid, run, _body, eid = _cavities(client, ubq_run)
    gated = _done(_act(client, rid, eid, "advance"))
    assert gated["status"] == "awaiting_scientific_approval" and gated["steps"][0]["job_status"] == "claimed"
    api_module._run(rid).approve("expensive_first_call")
    assert _get(client, rid, eid)["status"] == "ready"
    return rid, run, eid, gated["steps"][0]["job_id"]


def test_limits_exhausted_with_an_open_owned_job_dispatch_cancels_that_job(client, ubq_run, monkeypatch):
    rid, run, eid, job_id = _gated_owned_job(client, ubq_run)
    # FAULT FIXTURE: the execution's wall limit is reached while its owned job waits to start.
    monkeypatch.setattr(ax, "_limits_exhausted", lambda *a, **k: "max_active_wall")
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "failed" and record["retryable_step"] is None
    assert record["steps"][0]["failure"]["reason_code"] == "max_active_wall"
    assert JobQueue(run).get(job_id)["status"] == "cancelled"
    assert not _types(run, "budget_reserved") and not _types(run, "job_dispatch_intent")


def test_compatibility_block_with_an_open_owned_job_dispatch_cancels_that_job(client, ubq_run, monkeypatch):
    rid, run, eid, job_id = _gated_owned_job(client, ubq_run)
    # FAULT FIXTURE: a method version changed while the owned job waits to start.
    monkeypatch.setattr(analysis_plans, "check_compatibility",
                        lambda run, plan: {"compatible": False, "mismatched_steps": ["s01"], "current": {}})
    record = _done(_act(client, rid, eid, "advance"))
    assert record["status"] == "blocked" and record["blocked_reason"]["reason_code"] == "compatibility_changed"
    assert JobQueue(run).get(job_id)["status"] == "cancelled"
    assert not _types(run, "budget_reserved") and not _types(run, "job_dispatch_intent")


def test_revoke_after_a_budget_released_call_returns_to_awaiting_approval(client):
    from mw.runtime.guards import BudgetLimits
    rid, run, _body, eid = _approved_measure(client)
    live = api_module._run(rid)
    live.update_limits(BudgetLimits(wall_clock_s=max(live.budget.wall_clock_s, 1e-6)))
    released = _done(_act(client, rid, eid, "advance"))
    assert released["notice"]["code"] == "run_budget_exhausted" and released["steps"][0]["status"] == "pending"
    assert _linked(run, eid, "execution_call_admitted") and not _linked(run, eid, "tool_called")
    revoked = _done(_act(client, rid, eid, "revoke"))
    assert revoked["status"] == "awaiting_approval"  # the admitted call never started: nothing to cancel
