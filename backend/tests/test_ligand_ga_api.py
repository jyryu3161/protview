"""M22 T5: GA design read API (spec .dryforge/spec.md 6, 8): preflight (POST read), summary list (newest first),
summary detail (generations and individuals), an individual's link to its standalone M18 result, job progress.

The world is real product output (``ligand_ga_fixture``: real M17 jobs and real GA jobs with the pinned GA worker and
qvina2; a missing environment FAILS, never skips). Hand values come from spec 6 arithmetic on the test's GA values
(never from product code). Every read is checked to leave the event log unchanged (no event, job, tool or budget
record). Tampered objects are labeled test fabrications written only to prove the reads refuse them.
"""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ligand_ga_fixture import RID, build_world, reopen

from mw import docking_bundle
from mw import docking_constants as C
from mw import ligand_ga_constants as GC
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.runtime.guards import BudgetLimits

MW = Path(__file__).resolve().parents[1] / "mw"
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")
BASE = f"/runs/{RID}/ligand/ga"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("m22_reads") / "runs")


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


@pytest.fixture
def client(world, monkeypatch):
    return _client(world["root"], monkeypatch)


@pytest.fixture
def fresh(world, tmp_path, monkeypatch):
    """A function-scoped events-only copy of the M17-only prefix (no GA yet), and its client."""
    root = tmp_path / "runs"
    (root / RID).mkdir(parents=True)
    shutil.copyfile(world["base_root"] / RID / "events.jsonl", root / RID / "events.jsonl")
    reopen(root)
    return root, _client(root, monkeypatch)


def _events(root: Path) -> list[dict]:
    return [json.loads(line) for line in (root / RID / "events.jsonl").read_text().splitlines() if line.strip()]


def _unchanged(root: Path, call):
    before = _events(root)
    response = call()
    assert _events(root) == before, "a read wrote an event"
    return response


def _preflight(client, root, args, **params):
    return _unchanged(root, lambda: client.post(f"{BASE}/preflight", json=args, params=params))


def _entries(content: dict) -> list[tuple[int, int, dict]]:
    return [(gen["index"], position, entry) for gen in content["generations"]
            for position, entry in enumerate(gen["individuals"])]


# ----------------------------------------------------------------- preflight
def test_preflight_hand_values_on_an_unused_pool_and_no_side_effects(world, fresh):
    root, client = fresh
    run = api_module._run(RID)
    snapshot = run.budget_snapshot()
    used_calls, used_wall = snapshot["expensive_calls"]["used"], snapshot["wall_clock_s"]["used"]
    # GA: P 4, G 2, E 2, max 6, total 600 -> reserved_units = min(6, 4 + 1 x (4 - 2)) = 6;
    # needed wall = min(600 + 600, 6 x 300 + 300) = 1200; 6 x 300 = 1800 > 600 -> may be partial.
    run.update_limits(BudgetLimits(expensive_calls=used_calls + 4, wall_clock_s=used_wall + 1800), by="test")
    response = _preflight(client, root, world["args"]["complete"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "ligand_ga_preflight@1" and body["starts_job"] is False
    assert body["admission"] == {"admitted": True, "error": None, "reason_code": None, "message": None,
                                 "detail": None}
    assert body["pool"] == {"size": 10, "eligible_count": 10, "filter_excluded_count": 0}
    assert body["reusable_count"] == 0 and body["reserved_units"] == 6 and body["max_new_dockings_expected"] == 6
    assert body["needed"] == {"expensive_calls": 6, "wall_clock_s": 1200}
    assert body["full_run_may_be_partial"] is True
    assert body["shortfall"]["expensive_calls"] == 2
    for axis in ("expensive_calls", "wall_clock_s"):
        left = body["budget"][axis]["limit"] - body["budget"][axis]["used"]
        assert body["remaining"][axis] == left
        assert body["shortfall"][axis] == max(0, body["needed"][axis] - left)
    assert body["shortfall"]["wall_clock_s"] == 0
    assert body["ga"] == world["args"]["complete"]["ga"]
    assert len(body["selection_sha256"]) == 64 and body["existing_job"] is None
    assert body["capability"]["available"] is True and body["capability"]["protocol_id"] == GC.PROTOCOL
    assert body["score_label"] == C.SCORE_LABEL
    assert body["statements"] == [{"id": "G1", "text": GC.STATEMENTS["G1"]}]
    # an excluding filter: excluded candidates are counted, never planned
    heavy = sorted(row["properties"]["heavy_atoms"] for row in run.store.load(world["candidate_set"])["candidates"])
    spec = {"ranges": {"heavy_atoms": {"max": heavy[5]}}}
    filtered = _preflight(client, root, {**world["args"]["complete"], "filter": spec}).json()
    eligible = sum(value <= heavy[5] for value in heavy)
    assert filtered["admission"]["admitted"] is True
    assert filtered["pool"] == {"size": 10, "eligible_count": eligible, "filter_excluded_count": 10 - eligible}


def test_preflight_on_the_world_counts_reuse_and_returns_the_complete_job(world, client):
    root = world["root"]
    seen = {entry["candidate_id"] for name in ("partial", "complete")
            for _g, _p, entry in _entries(world["stored"][name]) if entry["origin"] != "carried"}
    body = _preflight(client, root, world["args"]["complete"]).json()
    assert body["admission"]["admitted"] is True and body["reusable_count"] == len(seen)
    assert body["reserved_units"] == 6   # reserved whatever is reused (spec 6)
    assert body["existing_job"] == {"job_id": world["jobs"]["complete"]["job_id"], "status": "done",
                                    "summary_handle": world["handles"]["complete"]}
    partial = _preflight(client, root, world["args"]["partial"]).json()   # a partial GA never deduplicates
    assert partial["existing_job"] is None and partial["reserved_units"] == 4
    assert partial["needed"] == {"expensive_calls": 4, "wall_clock_s": 1200}


@pytest.mark.parametrize(("case", "reason", "error"), [
    ("unknown_key", "invalid_job_arguments", "input_invalid"),
    ("elite_rule", "invalid_job_arguments", "input_invalid"),
    ("pool_too_small", "ga_pool_too_small", "input_invalid"),
    ("filter_empty_pool", "ga_pool_too_small", "input_invalid"),
    ("other_run_handle", "invalid_job_arguments", "input_invalid"),
    ("parent_wrong_kind", None, "input_invalid"),
])
def test_preflight_admission_refusals_have_reasons_and_no_numbers(world, client, case, reason, error):
    args = world["args"]["complete"]
    args = {
        "unknown_key": {**args, "mode": "free"},
        "elite_rule": {**args, "ga": {**args["ga"], "elite_count": 3}},
        "pool_too_small": {**args, "ga": {**args["ga"], "population_size": 12, "max_new_dockings": 12}},
        "filter_empty_pool": {**args, "filter": {"ranges": {"heavy_atoms": {"max": 1}}}},
        "other_run_handle": {**args, "candidate_set_handle": world["candidate_set"].replace(RID, "run_other")},
        "parent_wrong_kind": {**args, "parent_sdf_handle": world["receptor"]},
    }[case]
    response = _preflight(client, world["root"], args)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admission"]["admitted"] is False and body["admission"]["error"] == error
    if reason is None:   # an M18 admission reason (step 2), unchanged
        assert body["admission"]["reason_code"] in (*C.REASONS, "invalid_job_arguments"), body["admission"]
    else:
        assert body["admission"]["reason_code"] == reason, body["admission"]
    assert type(body["admission"]["message"]) is str
    for key in ("selection_sha256", "pool", "reusable_count", "reserved_units", "max_new_dockings_expected",
                "needed", "shortfall", "full_run_may_be_partial", "ga", "statements", "existing_job"):
        assert body[key] is None, key
    assert set(body["remaining"]) == {"expensive_calls", "wall_clock_s"}   # the run's budget is a fact


def test_preflight_reuse_size_capability_and_body_limits(world, client, monkeypatch, tmp_path):
    root = world["root"]
    with monkeypatch.context() as patch:   # labeled internal hook: the staging bound reached by stored results
        patch.setattr(GC, "MAX_REUSE_STAGING_BYTES", -1)
        body = _preflight(client, root, world["args"]["complete"]).json()
    assert body["admission"]["reason_code"] == "ga_reuse_too_large" and body["reserved_units"] is None
    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        body = _preflight(client, root, world["args"]["complete"]).json()
    assert body["capability"]["available"] is False and body["capability"]["reason_code"] == "engine_missing"
    assert body["admission"] == {"admitted": False, "error": "precondition", "reason_code": "engine_missing",
                                 "message": docking_bundle.REASONS["engine_missing"],
                                 "detail": {"reason_code": "engine_missing"}}
    assert body["needed"] is None and body["pool"] is None
    unknown = _preflight(client, root, world["args"]["complete"], dry="1")
    assert unknown.status_code == 422 and unknown.json()["detail"]["error"] == "input_invalid"
    bad = _unchanged(root, lambda: client.post(f"{BASE}/preflight", content=b"{not json",
                                               headers={"content-type": "application/json"}))
    assert bad.status_code == 422
    assert _unchanged(root, lambda: client.post(f"{BASE}/preflight", json=[1, 2])).status_code == 422


# ----------------------------------------------------------------- list, detail, individual, progress
def test_list_is_newest_first_validated_and_paged(world, client):
    root = world["root"]
    response = _unchanged(root, lambda: client.get(f"{BASE}/results"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "ligand_ga_list@1" and body["total"] == 2
    names = ("complete", "partial")   # newest first
    assert [row["handle"] for row in body["rows"]] == [world["handles"][name] for name in names]
    for name, row in zip(names, body["rows"], strict=True):
        stored = world["stored"][name]
        assert row["valid"] is True and row["reason_code"] is None
        assert row["job_id"] == world["jobs"][name]["job_id"]
        for key in ("status", "stop_reason", "generations_done", "new_dockings_used", "reused_count",
                    "reserved_units", "pool", "candidate_set_handle", "selection_sha256", "ga"):
            assert row[key] == stored[key], key
    assert body["rows"][0]["published_seq"] > body["rows"][1]["published_seq"]
    page = _unchanged(root, lambda: client.get(f"{BASE}/results", params={"offset": 1, "limit": 1})).json()
    assert [row["handle"] for row in page["rows"]] == [world["handles"]["partial"]] and page["total"] == 2
    for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}, {"handle": "x"}):
        refused = _unchanged(root, lambda params=params: client.get(f"{BASE}/results", params=params))
        assert refused.status_code == 422, params


def test_detail_matches_the_stored_summary_and_individuals(world, client):
    root = world["root"]
    for name in ("complete", "partial"):
        handle = world["handles"][name]
        response = _unchanged(root, lambda handle=handle: client.get(f"{BASE}/results/{handle}"))
        assert response.status_code == 200, response.text
        body = response.json()
        stored = world["stored"][name]
        assert body["schema"] == "ligand_ga_detail@1" and body["handle"] == handle
        assert canonical_json(body["summary"]) == canonical_json(stored)
        assert body["job_id"] == world["jobs"][name]["job_id"] and body["meta"]["kind"] == GC.OUTPUT_KIND
        assert body["score_label"] == C.SCORE_LABEL and body["score_column_label"] == C.SCORE_COLUMN_LABEL
        assert body["score_row_label"] == GC.SCORE_ROW_LABEL
        assert body["statements"] == [{"id": item, "text": GC.STATEMENTS[item]} for item in stored["limitations"]]
        assert len(body["generations"]) == len(stored["generations"])
        for gen, kept in zip(body["generations"], stored["generations"], strict=True):
            assert {key: gen[key] for key in ("index", "complete", "min_score", "max_score")} == {
                key: kept[key] for key in ("index", "complete", "min_score", "max_score")}
            for entry, original in zip(gen["individuals"], kept["individuals"], strict=True):
                assert {key: entry[key] for key in original} == original
                assert entry["detail_available"] is (original["result_handle"] is not None)
    partial = world["stored"]["partial"]
    assert partial["generations"][-1]["complete"] is False
    assert len(partial["generations"][-1]["individuals"]) < partial["ga"]["population_size"]


def test_individual_links_to_its_standalone_m18_result(world, client):
    root = world["root"]
    handle = world["handles"]["complete"]
    stored = world["stored"]["complete"]
    carried = [entry for _g, _p, entry in _entries(stored) if entry["origin"] == "carried"]
    assert carried
    for _g, _p, entry in _entries(stored):
        cid = entry["candidate_id"]
        response = _unchanged(root, lambda cid=cid: client.get(f"{BASE}/results/{handle}/individual",
                                                               params={"candidate_id": cid}))
        assert response.status_code == 200, response.text
        body = response.json()
        evaluated = next(e for _gg, _pp, e in _entries(stored) if e["candidate_id"] == cid and
                         e["origin"] != "carried")
        assert body["schema"] == "ligand_ga_individual@1" and body["summary_handle"] == handle
        for key in ("candidate_id", "evaluation", "eval_index", "state", "reason_code", "score", "result_handle"):
            assert body[key] == evaluated[key], key
        assert body["appearances"] == [{"generation": g, "position": p, "origin": e["origin"]}
                                       for g, p, e in _entries(stored) if e["candidate_id"] == cid]
        # the same body as the M18 detail read of that result handle
        m18 = _unchanged(root, lambda h=evaluated["result_handle"]: client.get(
            f"/runs/{RID}/docking/results/detail", params={"handle": h}))
        assert m18.status_code == 200
        assert body["m18_detail"] == {key: value for key, value in m18.json().items() if key != "meta"}
        assert body["m18_detail"]["result"]["inputs"]["ligand"]["candidate_id"] == cid
        assert body["m18_detail"]["result"]["modes"][0]["score_kcal_mol"] == evaluated["score"]
    for params in ({"candidate_id": "c_0000000000000000"}, {},
                   {"candidate_id": carried[0]["candidate_id"], "y": "1"}):
        refused = _unchanged(root, lambda params=params: client.get(f"{BASE}/results/{handle}/individual",
                                                                    params=params))
        assert refused.status_code == 422, params


def test_job_progress_read_counts_staged_files_only(world, client):
    root = world["root"]
    for name in ("complete", "partial"):
        job = world["jobs"][name]
        response = _unchanged(root, lambda job=job: client.get(f"/runs/{RID}/jobs/{job['job_id']}"))
        assert response.status_code == 200
        progress = response.json()["ga"]
        stored = world["stored"][name]
        evaluated = [e for _g, _p, e in _entries(stored) if e["origin"] != "carried"]
        assert progress["summary_handle"] == world["handles"][name]
        assert (progress["summary_status"], progress["summary_stop_reason"]) == (stored["status"],
                                                                                 stored["stop_reason"])
        assert progress["reserved_units"] == stored["reserved_units"] and progress["pool"] == stored["pool"]
        assert progress["generations_complete"] == stored["generations_done"]
        assert progress["individuals_finished"] == sum(e["evaluation"] == "docked" for e in evaluated)
        # Result files = new dockings with a stored result (scored or null_result); reused individuals have none.
        assert progress["individuals_result_files"] == sum(e["evaluation"] == "docked" and e["state"] != "failed"
                                                           for e in evaluated)
        assert progress["reused_planned"] >= stored["reused_count"]


def test_reads_refuse_wrong_kind_other_run_unknown_params_and_tampered_summary(world, client, tmp_path,
                                                                                monkeypatch):
    root = world["root"]
    complete = world["handles"]["complete"]
    individual = next(e for _g, _p, e in _entries(world["stored"]["complete"]) if e["result_handle"])
    cases = [(world["receptor"], 422), (individual["result_handle"], 422), (world["candidate_set"], 422),
             (complete.replace(RID, "run_other"), None), (f"obj://{RID}/ligand_ga_result/{'1' * 64}", 404)]
    for handle, status in cases:
        for suffix, params in (("", {}), ("/individual", {"candidate_id": individual["candidate_id"]})):
            response = _unchanged(root, lambda h=handle, s=suffix, p=params: client.get(f"{BASE}/results/{h}{s}",
                                                                                        params=p))
            assert response.status_code in ((404, 422) if status is None else (status,)), (handle, response.text)
            assert "score" not in response.text
    response = _unchanged(root, lambda: client.get(f"{BASE}/results/{complete}", params={"x": "1"}))
    assert response.status_code == 422
    # LABELED TEST FABRICATION: a copy of the run whose summary object was edited in place
    copy_root = tmp_path / "runs"
    shutil.copytree(root / RID, copy_root / RID)
    copied = _client(copy_root, monkeypatch)
    assert copied.get(f"{BASE}/results/{complete}").status_code == 200
    stored_path = copy_root / RID / "objects" / f"{complete.rsplit('/', 1)[-1]}.json"
    content = json.loads(stored_path.read_bytes())
    scored = next(e for e in content["generations"][0]["individuals"] if e["state"] == "scored")
    scored["score"] = -99.0
    stored_path.write_bytes(canonical_json(content))
    for suffix, params in (("", {}), ("/individual", {"candidate_id": scored["candidate_id"]})):
        response = _unchanged(copy_root, lambda s=suffix, p=params: copied.get(f"{BASE}/results/{complete}{s}",
                                                                               params=p))
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
        assert "-99" not in response.text
    listed = _unchanged(copy_root, lambda: copied.get(f"{BASE}/results")).json()
    row = listed["rows"][0]
    assert row["handle"] == complete and row["valid"] is False and row["reason_code"] == "evidence_invalid"
    assert row["status"] is None and row["pool"] is None and row["ga"] is None
    assert listed["rows"][1]["valid"] is True


def test_read_module_imports_no_chemistry_and_runs_nothing():
    source = (MW / "ligand_ga_reads.py").read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in FORBIDDEN_MODULES for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", ".submit(", ".start(", "stage(",
                      "qvina2", "events.append", "raise_limits", "update_limits", "reserve_attempt", "finish("):
        assert forbidden not in source, forbidden
