"""M17 ligand read API and capability (spec 4.1, 5, 6.3, 6.4, 7): no event, no job, no tool on any read.

Objects are made by real RDKit jobs (``ligand_job_fixture``: labeled synthetic methacetin + block libraries,
pinned ``.deps/prolif/venv-locked`` worker). Missing environment -> these tests FAIL, never skip. Expected
filter outcomes are compared against the stored row values with the test's own comparisons; the server never
recomputes a property.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import NO_H, VALID_RULE_IDS, import_file, new_ligand_run, run_job, standard_run

from mw import ligand_bundle, ligand_reads
from mw import ligand_constants as C
from mw.api import app as api_module
from mw.core.handles import canonical_json

PRIOR_METHODS = {"interface_sasa", "openmm_protein_minimize", "chemical_interactions", "pocket_detection",
                 "analysis_workflows", "residue_numbering", "reference_site_annotation"}


# ----------------------------------------------------------------- shared world (real jobs, built once)
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("ligand_api") / "runs"
    std = standard_run(root, "run_ligand_api")
    run = std["run"]
    # Zero-candidate set (spec 11: empty scientific result): user_3 only matches the acetyl group outside the site.
    empty = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": std["inspection"], "site_atoms": [11, 12],
                                                "use_fixed": False, "rule_ids": ["user_3"]})
    assert empty["status"] == "done", empty
    # Cap reached (labeled internal hook lowers the candidate cap; never a request field).
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ligand_bundle, "ENUMERATE_LIMITS", {"max_candidates": 3, "max_attempts": C.MAX_ATTEMPTS})
        capped = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": std["inspection"], "site_atoms": [11, 12],
                                                     "use_fixed": True})
    assert capped["status"] == "done", capped
    other = new_ligand_run(root, "run_ligand_api_other")
    other_parent = import_file(other, "ligand_sdf", "parent.sdf", NO_H)
    return {**std, "root": root, "rid": "run_ligand_api", "empty": empty["output_handles"][0],
            "capped": capped["output_handles"][0], "other_rid": "run_ligand_api_other", "other_parent": other_parent}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _events(world, rid: str | None = None) -> int:
    return len((world["root"] / (rid or world["rid"]) / "events.jsonl").read_text().splitlines())


def _rows(client, world, **params):
    return client.get(f"/runs/{world['rid']}/ligand/candidate_sets/rows",
                      params={"handle": world["candidate_set"], **params})


def _stored(world, handle: str | None = None) -> dict:
    return world["run"].store.load(handle or world["candidate_set"])


# ----------------------------------------------------------------- reads write no event
def test_every_read_leaves_the_event_log_unchanged(client, world):
    rid = world["rid"]
    client.get(f"/runs/{rid}/ligand/prerequisites")  # first touch reopens the run (job reconcile happens here)
    before = _events(world)
    reads = [("get", f"/runs/{rid}/ligand/prerequisites", {}),
             ("get", f"/runs/{rid}/ligand/inspections", {}),
             ("get", f"/runs/{rid}/ligand/inspections/detail", {"handle": world["inspection"]}),
             ("get", f"/runs/{rid}/ligand/candidate_sets", {}),
             ("get", f"/runs/{rid}/ligand/candidate_sets", {"inspection": world["inspection"]}),
             ("get", f"/runs/{rid}/ligand/candidate_sets/detail", {"handle": world["candidate_set"]}),
             ("get", f"/runs/{rid}/ligand/candidate_sets/rows", {"handle": world["candidate_set"],
                                                                  "mol_weight_max": "200", "pains_exclude": "true"}),
             ("get", "/capabilities", {})]
    for method, path, params in reads:
        response = getattr(client, method)(path, params=params)
        assert response.status_code == 200, (path, response.text)
    previews = [{"inspection_handle": world["inspection"], "site_atoms": [11, 12], "use_fixed": True},
                {"inspection_handle": world["inspection"], "site_atoms": [], "use_fixed": True}]
    for body in previews:
        assert client.post(f"/runs/{rid}/ligand/preview", json=body).status_code == 200
    # Refused reads also write nothing.
    assert _rows(client, world, bogus="1").status_code == 422
    assert client.post(f"/runs/{rid}/ligand/preview", json={"inspection_handle": 1}).status_code == 422
    assert _events(world) == before


# ----------------------------------------------------------------- prerequisites and lists
def test_prerequisites_counts_and_capability(client, world):
    body = client.get(f"/runs/{world['rid']}/ligand/prerequisites").json()
    assert body["schema"] == "ligand_prerequisites@1" and body["starts_job"] is False
    assert body["import_counts"] == {"ligand_sdf": 1, "building_blocks_sdf": 1, "building_blocks_smiles": 1}
    assert [(row["handle"], row["input_kind"]) for row in body["imports"]] == [
        (world["parent"], "ligand_sdf"), (world["smiles"], "building_blocks_smiles"),
        (world["sdf"], "building_blocks_sdf")]
    assert body["inspections"] == 1 and body["candidate_sets"] == 3
    assert body["capability"]["available"] is True and body["capability"]["schema"] == "ligand_capability@1"
    other = client.get(f"/runs/{world['other_rid']}/ligand/prerequisites").json()
    assert other["import_counts"] == {"ligand_sdf": 1, "building_blocks_sdf": 0, "building_blocks_smiles": 0}
    assert other["inspections"] == 0 and other["candidate_sets"] == 0
    assert client.get(f"/runs/{world['rid']}/ligand/prerequisites", params={"x": "1"}).status_code == 422
    # The M11 prerequisites route keeps its three kinds.
    m11 = client.get(f"/runs/{world['rid']}/chemical/prerequisites", params={"mode": "create_new"}).json()
    assert set(m11["import_counts"]) == {"receptor", "ligand_sdf", "receptor_bonds"}


def test_lists_are_in_creation_order_and_paged(client, world):
    rid = world["rid"]
    inspections = client.get(f"/runs/{rid}/ligand/inspections").json()
    assert inspections["schema"] == "ligand_inspection_list@1" and inspections["total"] == 1
    row = inspections["rows"][0]
    assert row["handle"] == world["inspection"] and row["valid"] is True
    assert row["job_id"] == world["inspect_job"]["job_id"] and row["parent_handle"] == world["parent"]
    assert row["heavy_atom_count"] == 12 and row["rules_total"] == 10 and row["rules_valid"] == 4
    assert "svg" not in json.dumps(row)
    sets = client.get(f"/runs/{rid}/ligand/candidate_sets").json()
    assert sets["schema"] == "ligand_candidate_set_list@1" and sets["total"] == 3
    assert [r["handle"] for r in sets["rows"]] == [world["candidate_set"], world["empty"], world["capped"]]
    assert [r["created_seq"] for r in sets["rows"]] == sorted(r["created_seq"] for r in sets["rows"])
    assert [(r["candidates"], r["null_result"], r["limit_reached"], r["stop_reason"]) for r in sets["rows"]] == [
        (10, False, False, None), (0, True, False, None), (3, False, True, "candidate_limit")]
    assert all(r["valid"] and r["inspection_handle"] == world["inspection"] for r in sets["rows"])
    assert "candidates_rows" not in sets["rows"][0] and "smiles" not in json.dumps(sets)
    page = client.get(f"/runs/{rid}/ligand/candidate_sets", params={"offset": 1, "limit": 1}).json()
    assert page["total"] == 3 and [r["handle"] for r in page["rows"]] == [world["empty"]]
    assert client.get(f"/runs/{rid}/ligand/candidate_sets", params={"offset": 9}).json()["rows"] == []
    filtered = client.get(f"/runs/{rid}/ligand/candidate_sets", params={"inspection": world["inspection"]}).json()
    assert filtered["total"] == 3
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}, {"what": "1"}):
        assert client.get(f"/runs/{rid}/ligand/candidate_sets", params=params).status_code == 422, params
        assert client.get(f"/runs/{rid}/ligand/inspections", params=params).status_code == 422, params
    empty = client.get(f"/runs/{world['other_rid']}/ligand/candidate_sets").json()
    assert empty["total"] == 0 and empty["rows"] == []


# ----------------------------------------------------------------- detail reads
def test_inspection_and_candidate_set_details(client, world):
    rid = world["rid"]
    detail = client.get(f"/runs/{rid}/ligand/inspections/detail", params={"handle": world["inspection"]}).json()
    assert detail["schema"] == "ligand_inspection_detail@1" and detail["handle"] == world["inspection"]
    assert detail["inspection"] == world["run"].store.load(world["inspection"])  # SVG only on this route
    assert detail["inspection"]["parent"]["svg"].lstrip().startswith(("<?xml", "<svg"))
    assert detail["job_id"] == world["inspect_job"]["job_id"]
    summary = client.get(f"/runs/{rid}/ligand/candidate_sets/detail",
                         params={"handle": world["candidate_set"]}).json()
    stored = _stored(world)
    assert summary["schema"] == "ligand_candidate_set_detail@1" and "candidates" not in summary["candidate_set"]
    assert summary["candidate_count"] == 10
    assert summary["candidate_set"] == {k: v for k, v in stored.items() if k != "candidates"}
    assert summary["candidate_set"]["limitations"] == list(C.LIMITATIONS)
    for path in ("inspections/detail", "candidate_sets/detail"):
        assert client.get(f"/runs/{rid}/ligand/{path}", params={"handle": "x", "y": "1"}).status_code == 422


@pytest.mark.parametrize("path", ["inspections/detail", "candidate_sets/detail", "candidate_sets/rows"])
def test_wrong_kind_foreign_and_unknown_handles_are_refused(client, world, monkeypatch, path):
    calls = []
    monkeypatch.setattr(ligand_bundle, "_handshake", lambda: calls.append("handshake"))
    monkeypatch.setattr(ligand_bundle, "stage", lambda *a, **k: calls.append("stage"))
    rid = world["rid"]
    wrong = world["candidate_set"] if path.startswith("inspections") else world["inspection"]
    response = client.get(f"/runs/{rid}/ligand/{path}", params={"handle": wrong})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"
    response = client.get(f"/runs/{rid}/ligand/{path}", params={"handle": world["parent"]})  # an import object
    assert response.status_code == 422
    foreign = client.get(f"/runs/{rid}/ligand/{path}", params={"handle": world["other_parent"]})
    assert foreign.status_code == 404
    unknown = world["inspection"].rsplit("/", 1)[0] + "/" + "0" * 64
    assert client.get(f"/runs/{rid}/ligand/{path}", params={"handle": unknown}).status_code == 404
    assert client.get(f"/runs/{rid}/ligand/{path}", params={"handle": "not-a-handle"}).status_code == 404
    assert client.get(f"/runs/{rid}/ligand/{path}").status_code == 422  # handle is required
    assert calls == []


def test_tampered_objects_never_read(world, monkeypatch, tmp_path):
    """A copy of the run whose stored object bytes were edited in place (labeled fault injection)."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / world["rid"], root / world["rid"])
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = world["rid"]
    objects = root / rid / "objects"
    assert client.get(f"/runs/{rid}/ligand/prerequisites").status_code == 200  # reopen before the edit
    def rewrite(handle: str, edit) -> None:
        path = objects / f"{handle.rsplit('/', 1)[-1]}.json"
        content = json.loads(path.read_bytes())
        edit(content)
        path.write_bytes(canonical_json(content))

    # A stored property value changed in place: the store content-hash check refuses the bytes.
    rewrite(world["candidate_set"], lambda c: c["candidates"][0]["properties"].__setitem__("mol_weight", 1.0))
    for path in ("candidate_sets/detail", "candidate_sets/rows"):
        response = client.get(f"/runs/{rid}/ligand/{path}", params={"handle": world["candidate_set"]})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    listed = client.get(f"/runs/{rid}/ligand/candidate_sets").json()["rows"]
    bad = next(r for r in listed if r["handle"] == world["candidate_set"])
    assert bad["valid"] is False and bad["candidates"] is None and bad["reason_code"] == "evidence_invalid"
    # A tampered inspection invalidates its own reads, every set built on it, and the preview.
    rewrite(world["inspection"], lambda c: c["parent"]["properties"].__setitem__("tpsa", 0.0))
    response = client.get(f"/runs/{rid}/ligand/inspections/detail", params={"handle": world["inspection"]})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    response = client.get(f"/runs/{rid}/ligand/candidate_sets/rows", params={"handle": world["empty"]})
    assert response.status_code == 422
    preview = client.post(f"/runs/{rid}/ligand/preview", json={"inspection_handle": world["inspection"],
                                                               "site_atoms": [11, 12], "use_fixed": True})
    assert preview.status_code == 422 and preview.json()["detail"]["reason_code"] == "inspection_invalid"
    assert client.get(f"/runs/{rid}/ligand/inspections").json()["rows"][0]["valid"] is False


# ----------------------------------------------------------------- candidate rows: filters, sort, page
def test_rows_default_page_has_no_active_filter(client, world):
    body = _rows(client, world).json()
    stored = _stored(world)
    assert body["schema"] == "ligand_candidate_page@1" and body["handle"] == world["candidate_set"]
    assert body["inspection_handle"] == world["inspection"] and body["site_atoms"] == [11, 12]
    assert body["rules_used"] == stored["rules_used"] and body["parent_properties"] == stored["parent_properties"]
    assert body["counts"] == stored["counts"] and body["limitations"] == list(C.LIMITATIONS)
    assert (body["limit_reached"], body["stop_reason"]) == (False, None)
    assert body["filter_spec"] == {"ranges": {}, "pains_exclude": False}
    assert body["total"] == 10 and body["passing"] is None and body["failing"] is None
    assert body["filter_pass_counts"] == {} and body["hidden_by_filter"] == 0
    assert (body["sort"], body["direction"], body["offset"], body["limit"]) == ("generation_order", "asc", 0, 50)
    assert [row["candidate"] for row in body["rows"]] == stored["candidates"]
    assert [row["generation_order"] for row in body["rows"]] == list(range(10))
    assert all(row["passes_all"] is None and row["filters"] == {} for row in body["rows"])
    # passes_only with no active filter hides nothing.
    assert _rows(client, world, passes_only="true").json()["hidden_by_filter"] == 0


def test_rows_filter_boundaries_are_inclusive(client, world):
    stored = _stored(world)["candidates"]
    weights = [row["properties"]["mol_weight"] for row in stored]
    pivot = sorted(weights)[4]
    body = _rows(client, world, mol_weight_min=repr(pivot)).json()
    expected = [w >= pivot for w in weights]
    assert [row["filters"]["mol_weight"] for row in body["rows"]] == expected
    assert [row["passes_all"] for row in body["rows"]] == expected
    assert body["passing"] == sum(expected) and body["failing"] == 10 - sum(expected)
    assert body["filter_pass_counts"] == {"mol_weight": sum(expected)}
    exact = _rows(client, world, mol_weight_min=repr(pivot), mol_weight_max=repr(pivot)).json()
    assert exact["passing"] == weights.count(pivot) >= 1
    hbd = [row["properties"]["hbd"] for row in stored]
    low = min(hbd)
    at_max = _rows(client, world, hbd_max=str(low)).json()
    assert at_max["filter_pass_counts"] == {"hbd": hbd.count(low)}
    below = _rows(client, world, hbd_max=str(low - 1)).json()
    assert below["passing"] == 0 and below["filter_pass_counts"] == {"hbd": 0}
    assert below["filter_spec"] == {"ranges": {"hbd": {"min": None, "max": low - 1}}, "pains_exclude": False}
    # Values pass through as given (integers stay integers, decimals stay floats).
    spec = _rows(client, world, tpsa_min="10", crippen_logp_max="2.5").json()["filter_spec"]
    assert spec["ranges"] == {"crippen_logp": {"min": None, "max": 2.5}, "tpsa": {"min": 10, "max": None}}


def test_rows_pains_exclude_and_passes_only(client, world):
    stored = _stored(world)["candidates"]
    clean = [not row["pains"]["matches"] for row in stored]
    body = _rows(client, world, pains_exclude="true").json()
    assert body["filter_spec"]["pains_exclude"] is True
    assert [row["filters"]["pains_exclude"] for row in body["rows"]] == clean
    assert body["filter_pass_counts"] == {"pains_exclude": sum(clean)}
    off = _rows(client, world, pains_exclude="false").json()
    assert off["passing"] is None and off["filter_pass_counts"] == {}
    weights = [row["properties"]["mol_weight"] for row in stored]
    cut = sorted(weights)[6]
    passing = [i for i, w in enumerate(weights) if w <= cut and clean[i]]
    shown = _rows(client, world, mol_weight_max=repr(cut), pains_exclude="true", passes_only="true").json()
    assert [row["generation_order"] for row in shown["rows"]] == passing
    assert shown["matched"] == len(passing) and shown["hidden_by_filter"] == 10 - len(passing)
    assert shown["total"] == 10 and shown["passes_only"] is True


def test_rows_sort_direction_and_paging(client, world):
    stored = _stored(world)["candidates"]
    weights = [row["properties"]["mol_weight"] for row in stored]
    asc = sorted(range(10), key=lambda i: (weights[i], i))
    desc = sorted(range(10), key=lambda i: (-weights[i], i))
    body = _rows(client, world, sort="mol_weight").json()
    assert [row["generation_order"] for row in body["rows"]] == asc
    body = _rows(client, world, sort="mol_weight", direction="desc").json()
    assert [row["generation_order"] for row in body["rows"]] == desc
    back = _rows(client, world, direction="desc").json()
    assert [row["generation_order"] for row in back["rows"]] == list(range(9, -1, -1))
    page = _rows(client, world, sort="mol_weight", offset="3", limit="4").json()
    assert [row["generation_order"] for row in page["rows"]] == asc[3:7]
    assert (page["offset"], page["limit"], page["total"], page["matched"]) == (3, 4, 10, 10)
    assert _rows(client, world, offset="10").json()["rows"] == []


@pytest.mark.parametrize("params", [
    {"bogus": "1"}, {"handle_x": "1"}, {"mol_weight": "1"}, {"density_min": "1"},
    {"mol_weight_min": "300", "mol_weight_max": "200"}, {"mol_weight_min": "abc"}, {"mol_weight_min": ""},
    {"mol_weight_min": "nan"}, {"mol_weight_min": "inf"}, {"mol_weight_min": "1e999"}, {"hbd_max": "true"},
    {"sort": "smiles"}, {"sort": "id"}, {"direction": "up"}, {"offset": "-1"}, {"offset": "1.5"},
    {"limit": "0"}, {"limit": "101"}, {"limit": "x"}, {"passes_only": "yes"}, {"pains_exclude": "1"},
])
def test_rows_refuse_unknown_or_invalid_parameters(client, world, params):
    response = _rows(client, world, **params)
    assert response.status_code == 422, (params, response.text)
    assert response.json()["detail"]["error"] == "input_invalid"


def test_rows_refuse_repeated_parameters(client, world):
    url = f"/runs/{world['rid']}/ligand/candidate_sets/rows?handle={world['candidate_set']}"
    assert client.get(url + "&limit=5&limit=6").status_code == 422
    assert client.get(url + f"&handle={world['candidate_set']}").status_code == 422


def test_zero_candidate_set_reads_as_an_empty_scientific_result(client, world):
    body = _rows(client, world, handle=world["empty"], mol_weight_min="100").json()
    stored = _stored(world, world["empty"])
    assert body["total"] == 0 and body["rows"] == [] and body["passing"] == 0
    assert body["filter_pass_counts"] == {"mol_weight": 0}
    assert body["counts"] == stored["counts"] and body["counts"]["candidates"] == 0
    assert body["counts"]["rejected"]["outside_site"] >= 1
    assert body["counts"]["not_applicable"] == stored["counts"]["not_applicable"]
    assert body["limit_reached"] is False and body["stop_reason"] is None
    detail = client.get(f"/runs/{world['rid']}/ligand/candidate_sets/detail",
                        params={"handle": world["empty"]}).json()
    assert detail["candidate_count"] == 0 and detail["meta"]["null_result"] is True


def test_capped_set_shows_the_limit(client, world):
    body = _rows(client, world, handle=world["capped"]).json()
    assert body["limit_reached"] is True and body["stop_reason"] == "candidate_limit"
    assert body["limits"] == {"max_candidates": 3, "max_attempts": C.MAX_ATTEMPTS}
    assert body["total"] == 3 == len(body["rows"])


# ----------------------------------------------------------------- site preview (pure graph, no event)
def _preview(client, world, rid=None, **body):
    payload = {"inspection_handle": world["inspection"], "site_atoms": [11, 12], "use_fixed": True, **body}
    return client.post(f"/runs/{rid or world['rid']}/ligand/preview", json=payload)


def test_preview_valid_site_matches_admission(client, world):
    body = _preview(client, world, site_atoms=[12, 11], rule_ids=VALID_RULE_IDS).json()
    assert body["schema"] == "ligand_site_preview@1" and body["starts_job"] is False
    assert body["ready"] is True and body["blocking_reasons"] == []
    site = body["site_check"]
    assert site["valid"] is True and site["site_atoms"] == [11, 12] and site["core_atoms"] == list(range(1, 11))
    assert site["crossing_bonds"] == [{"core_atom": 8, "site_atom": 11, "order": "single"}]
    assert body["rules"] == [{"rule_id": r, "status": "valid", "usable": True} for r in VALID_RULE_IDS]
    assert body["generation_method_selected"] is True and body["use_fixed"] is True


@pytest.mark.parametrize("site,reason", [([], "site_empty"), ([99, 11], "site_atom_unknown"),
                                         (list(range(1, 13)), "core_empty"), ([7, 8, 11, 12], "crossing_bond_count"),
                                         ([3], "crossing_bond_not_single")])
def test_preview_site_reasons(client, world, site, reason):
    body = _preview(client, world, site_atoms=site).json()
    assert body["ready"] is False and body["site_check"]["valid"] is False
    assert body["site_check"]["reason"] == reason and body["blocking_reasons"] == [reason]


def test_preview_rule_and_method_reasons(client, world):
    body = _preview(client, world, rule_ids=["user_1", "user_4", "user_99"]).json()
    assert body["rules"] == [{"rule_id": "user_1", "status": "valid", "usable": True},
                             {"rule_id": "user_4", "status": "reactant_count", "usable": False},
                             {"rule_id": "user_99", "status": None, "usable": False}]
    assert body["ready"] is False and body["blocking_reasons"] == ["rule_invalid"]
    none = _preview(client, world, use_fixed=False, site_atoms=[], rule_ids=[]).json()
    assert none["generation_method_selected"] is False
    assert none["blocking_reasons"] == ["no_generation_method", "site_empty"]
    rules_only = _preview(client, world, use_fixed=False, rule_ids=["user_2"]).json()
    assert rules_only["ready"] is True


@pytest.mark.parametrize("body", [
    {"inspection_handle": "x", "site_atoms": [11], "use_fixed": True, "extra": 1},
    {"site_atoms": [11], "use_fixed": True},
    {"inspection_handle": "x", "use_fixed": True},
    {"inspection_handle": "x", "site_atoms": [11]},
    {"inspection_handle": "x", "site_atoms": [11], "use_fixed": "yes"},
    {"inspection_handle": "x", "site_atoms": "11", "use_fixed": True},
    {"inspection_handle": "x", "site_atoms": [11, 11], "use_fixed": True},
    {"inspection_handle": "x", "site_atoms": [True], "use_fixed": True},
    {"inspection_handle": "x", "site_atoms": [1.5], "use_fixed": True},
    {"inspection_handle": "x", "site_atoms": [11], "use_fixed": True, "rule_ids": ["user_1", "user_1"]},
    {"inspection_handle": "x", "site_atoms": [11], "use_fixed": True, "rule_ids": [1]},
    {"inspection_handle": "x", "site_atoms": [11], "use_fixed": True, "rule_ids": "user_1"},
])
def test_preview_refuses_malformed_bodies(client, world, body):
    if "inspection_handle" in body:
        body = {**body, "inspection_handle": world["inspection"]}
    response = client.post(f"/runs/{world['rid']}/ligand/preview", json=body)
    assert response.status_code == 422, (body, response.text)


def test_preview_refuses_bad_handles_and_bodies(client, world):
    rid = world["rid"]
    for handle in (world["candidate_set"], world["parent"], world["other_parent"], "nope"):
        response = _preview(client, world, inspection_handle=handle)
        assert response.status_code == 422 and response.json()["detail"]["reason_code"] == "inspection_invalid"
    assert client.post(f"/runs/{rid}/ligand/preview", content=b"[]").status_code == 422
    assert client.post(f"/runs/{rid}/ligand/preview", content=b'{"a":1,"a":2}').status_code == 422
    big = b'{"inspection_handle":"' + b"x" * (70 * 1024) + b'"}'
    assert client.post(f"/runs/{rid}/ligand/preview", content=big).status_code == 413


def test_preview_before_any_inspection_is_a_precondition(client, world):
    before = _events(world, world["other_rid"])
    response = _preview(client, world, rid=world["other_rid"], inspection_handle=world["other_parent"])
    assert response.status_code == 412
    assert response.json()["detail"]["reason_code"] == "inspection_required"
    assert _events(world, world["other_rid"]) == before


# ----------------------------------------------------------------- capability
def test_capability_ready_and_existing_methods_unchanged(client, world):
    methods = client.get("/capabilities").json()["methods"]
    assert set(methods) == PRIOR_METHODS | {"ligand_candidates"}
    ligand = methods["ligand_candidates"]
    assert ligand == ligand_bundle.capability()
    assert ligand["available"] is True and ligand["status"] == "ready" and ligand["reason"] is None
    assert ligand["pins"]["rdkit_version"] == "2026.03.6"
    assert ligand["pains_catalog_entries"] == {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 409}
    assert methods["reference_site_annotation"] == {"available": True, "reason_code": None, "reason": None}


def _fake_handshake(version: str) -> dict:
    """Labeled fake handshake record for the capability-state test (never a scientific result)."""
    return {"schema": "ligand_worker_handshake@1", "rdkit_version": version, "rdkit_version_expected": "2026.03.6",
            "pains_catalog_entries": {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 0},
            "protocols": ["rdkit_inspect_v1", "rdkit_enumerate_v1"], "worker_sha256": "0" * 64, "python": "3.11.11"}


@pytest.mark.parametrize("case,reason", [("missing", "worker_missing"), ("version", "rdkit_version_mismatch"),
                                         ("pains", "pains_catalog_unavailable")])
def test_capability_unavailable_paths(client, world, monkeypatch, tmp_path, case, reason):
    ligand_bundle._HANDSHAKE_CACHE.clear()
    if case == "missing":
        monkeypatch.setattr(ligand_bundle, "WORKER_PYTHON", tmp_path / "missing/python")
    else:
        monkeypatch.setattr(ligand_bundle, "_handshake",
                            lambda: _fake_handshake("2026.03.5" if case == "version" else "2026.03.6"))
    try:
        before = client.get("/capabilities").json()["methods"]
        ligand = before["ligand_candidates"]
        assert ligand["available"] is False and ligand["reason_code"] == reason == ligand["status"]
        assert ligand["reason"] == ligand_bundle.REASONS[reason]
        assert ligand["pins"] is None and ligand["pains_catalog_entries"] is None
        assert set(before) == PRIOR_METHODS | {"ligand_candidates"}
        prereq = client.get(f"/runs/{world['rid']}/ligand/prerequisites").json()
        assert prereq["capability"]["available"] is False and prereq["capability"]["reason_code"] == reason
        # Reads of stored results stay available: they never run RDKit.
        assert _rows(client, world).status_code == 200
    finally:
        monkeypatch.undo()
        ligand_bundle._HANDSHAKE_CACHE.clear()
    assert client.get("/capabilities").json()["methods"]["ligand_candidates"]["available"] is True


def test_read_module_imports_no_rdkit():
    import ast
    tree = ast.parse(Path(ligand_reads.__file__).read_text())
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name == "rdkit" or name.startswith("rdkit.") for name in names)
