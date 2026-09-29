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

from mw import analysis_plans, chemical_reports, comparison_reports, method_reports, openmm_reports, pocket_reports
from mw import reports as inspection_reports
from mw.api import app as api_module
from mw.chemical_inputs import _bonds, _sdf_records, _source_rows, import_raw, preview, receptor_atoms
from mw.core.errors import FailureClass, ToolFailure
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
    assert prep["bindings"] == {"structure": {"kind": "existing", "handle": raw, "expected_kind": "structure",
                                              "expected_schema": "structure_selection@2"}}
    assert prep["params"] == {**PREP, "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}
    assert contacts["bindings"]["structure"] == {"kind": "step_output", "step_id": "s01",
                                                 "output_name": "prepared_structure",
                                                 "expected_kind": "prepared_structure",
                                                 "expected_schema": "prepared_structure@1"}
    assert contacts["params"] == {"ligand": ligand, "cutoff_A": 4.0, "types": ["contact", "polar_contact"],
                                  "engine": "geometric"}
    assert set(contacts["params"]["ligand"]) == set(ligand) and len(ligand) == 7
    assert contacts["params"]["ligand"]["seq_label"] is None
    assert area["params"] == {"ligand": ligand} and area["depends_on"] == ["s01"]
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
    assert analysis_plans.MAX_PLANS_PER_RUN == 100 and analysis_plans.MAX_PLAN_BYTES == 64 * 1024
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
    oversized = client.post(f"/runs/{rid}/analysis/plans", content=b"{" + b" " * (64 * 1024) + b"}",
                            headers={"content-type": "application/json"})
    assert oversized.status_code == 413


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
    assert measure["plan"]["steps"][0]["params"] == {"first": first, "second": second}
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
    assert step["operation"] == "align_structures" and step["params"] == {"pairs": pairs}
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
    assert pockets["plan"]["steps"][0]["params"] == {"chains": ["A"], "timeout_s": 120}
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
    assert minimize["plan"]["steps"][0]["params"] == {"selection_policy": "protein_only",
                                                      "hydrogen_policy": "rebuild_pH7", "timeout_s": 120}
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
        assert prepare["params"] == {"request": request, "timeout_s": 120}
        assert detect["params"] == {"schema": "chemical_detect_request@1", "timeout_s": 120,
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
