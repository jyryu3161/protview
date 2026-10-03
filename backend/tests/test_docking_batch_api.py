"""M19 T6: batch docking read API (spec .dryforge/spec.md 6.2, 8): preflight (POST read), summary list, detail.

The world is real product output (``docking_batch_fixture``: real M17 jobs and real batch jobs with the pinned
worker; a missing environment FAILS, never skips). Hand values come from ``fixtures/docking/m19-batch-input.json``
(``hand_oracle``: arithmetic from the spec only, no product code). Every read is checked to leave the event log
unchanged (no event, job, tool or budget record). Tampered objects are labeled test fabrications written only to prove
the reads refuse them.
"""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from docking_batch_fixture import BATCH_FIXTURE, IDS, RID, args_for, build_world, reopen
from fastapi.testclient import TestClient

from mw import docking_batch_constants as BC
from mw import docking_bundle
from mw import docking_constants as C
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.runtime.guards import BudgetLimits

MW = Path(__file__).resolve().parents[1] / "mw"
HAND = BATCH_FIXTURE["hand_oracle"]
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("m19_reads") / "runs", pytest.MonkeyPatch.context)


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


@pytest.fixture
def client(world, monkeypatch):
    return _client(world["root"], monkeypatch)


@pytest.fixture
def fresh(world, tmp_path, monkeypatch):
    """A function-scoped events-only copy of the M17-only prefix (no batch yet), and its client."""
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
    return _unchanged(root, lambda: client.post(f"/runs/{RID}/docking/batches/preflight", json=args, params=params))


# ----------------------------------------------------------------- preflight
def test_preflight_hand_values_rows_reuse_and_no_side_effects(world, fresh, monkeypatch):
    root, client = fresh
    assert IDS == BATCH_FIXTURE["inputs"]["candidate_ids_in_set_order"]
    run = api_module._run(RID)
    snapshot = run.budget_snapshot()
    used_calls, used_wall = snapshot["expensive_calls"]["used"], snapshot["wall_clock_s"]["used"]
    # hand case 1 (N = 4, enough budget): remaining 8 / 1800 like the default limits on an unused run
    run.update_limits(BudgetLimits(expensive_calls=used_calls + 8, wall_clock_s=used_wall + 1800), by="test")
    order = HAND["row_order"][1]   # parent first, then set order (not click order)
    args = args_for(world, order["selected_ids"], include_parent=order["include_parent"])
    response = _preflight(client, root, args)
    assert response.status_code == 200, response.text
    body = response.json()
    case = HAND["budget_cases"][0]
    assert body["schema"] == "docking_batch_preflight@1" and body["starts_job"] is False
    assert body["admission"] == {"admitted": True, "error": None, "reason_code": None, "message": None,
                                 "detail": None}
    assert [[row["kind"], row["candidate_id"]] for row in body["rows"]] == order["rows"]
    assert [row["row_index"] for row in body["rows"]] == [0, 1, 2, 3]
    assert all(row["reuse"] is False and row["new_docking"] is True and row["reused_handle"] is None
               for row in body["rows"])
    assert body["new_dockings"] == case["new_dockings"] == 4 and body["reused_rows"] == 0
    assert body["needed"] == case["needed"]
    assert body["full_batch_may_be_partial"] is case["full_batch_may_be_partial"]
    assert body["shortfall"]["expensive_calls"] == case["shortfall"]["expensive_calls"]
    assert body["shortfall"]["wall_clock_s"] == pytest.approx(case["shortfall"]["wall_clock_s"], abs=1e-6)
    budget = body["budget"]
    assert set(budget) == {"expensive_calls", "wall_clock_s"}
    for axis in ("expensive_calls", "wall_clock_s"):
        left = budget[axis]["limit"] - budget[axis]["used"]
        assert body["remaining"][axis] == left
        assert body["shortfall"][axis] == max(0, body["needed"][axis] - left)
    assert body["mode"] == "free" and body["include_parent"] is True and body["existing_job"] is None
    assert body["candidate_ids"] == IDS and len(body["batch_input_sha256"]) == 64
    assert body["capability"]["available"] is True and body["capability"]["protocol_id"] == BC.PROTOCOL
    assert body["score_label"] == C.SCORE_LABEL
    assert body["statements"]["batch"] == [{"id": "B1", "text": BC.BATCH_STATEMENTS["B1"]}]
    # free, parent (sdf) + candidates, no instance removed: M18 sentences 1-7 and 10 (11 depends on docking)
    assert [item["number"] for item in body["statements"]["m18"]] == [1, 2, 3, 4, 5, 6, 7, 10]
    assert all(item["text"] == C.LIMITATIONS[item["number"] - 1] for item in body["statements"]["m18"])
    # hand case 2: remaining 2 units / 1200 s -> shortfall 2 units / 300 s
    run = api_module._run(RID)
    run.update_limits(BudgetLimits(expensive_calls=used_calls + 2, wall_clock_s=used_wall + 1200), by="test")
    body = _preflight(client, root, args).json()
    case = HAND["budget_cases"][1]
    assert body["needed"] == case["needed"]
    assert body["shortfall"]["expensive_calls"] == case["shortfall"]["expensive_calls"]
    # the limit change itself charges a few ms of runtime overhead, so the remaining time is 1200 s minus that
    assert body["shortfall"]["wall_clock_s"] == pytest.approx(case["shortfall"]["wall_clock_s"], abs=0.5)
    left = body["budget"]["wall_clock_s"]["limit"] - body["budget"]["wall_clock_s"]["used"]
    assert body["shortfall"]["wall_clock_s"] == 1500 - left
    # row order case 1: set order, no parent
    order = HAND["row_order"][0]
    body = _preflight(client, root, args_for(world, order["selected_ids"])).json()
    assert [[row["kind"], row["candidate_id"]] for row in body["rows"]] == order["rows"]
    assert [item["number"] for item in body["statements"]["m18"]] == [1, 2, 3, 4, 5, 6, 7, 10]
    # core-fixed: no parent row, sentences 1-5, 7, 8
    core = _preflight(client, root, args_for(world, IDS[:1], mode="core_fixed",
                                             params={"seed": 1, "conformers": 2})).json()
    assert core["admission"]["admitted"] is True and core["mode"] == "core_fixed"
    assert [item["number"] for item in core["statements"]["m18"]] == [1, 2, 3, 4, 5, 7, 8]


def test_preflight_reuse_n0_and_existing_complete_batch(world, client):
    root = world["root"]
    body = _preflight(client, root, world["args"]["free"]).json()
    assert body["admission"]["admitted"] is True
    stored = world["stored"]["free"]
    assert [row["reused_handle"] for row in body["rows"]] == [row["result_handle"] for row in stored["rows"]]
    assert all(row["reuse"] and not row["new_docking"] for row in body["rows"])
    case = HAND["budget_cases"][5]
    assert body["new_dockings"] == 0 and body["reused_rows"] == 3 and body["needed"] == case["needed"]
    assert body["full_batch_may_be_partial"] is False
    assert body["existing_job"] == {"job_id": world["jobs"]["free"]["job_id"], "status": "done",
                                    "summary_handle": world["handles"]["free"]}
    # the partial batch never deduplicates: rows 0-1 are reused, the cancelled and unstarted rows are new
    partial = _preflight(client, root, world["args"]["partial"]).json()
    assert partial["existing_job"] is None and partial["new_dockings"] == 2
    assert [row["reuse"] for row in partial["rows"]] == [True, True, False, False]
    assert partial["statements"]["batch"] == [{"id": "B1", "text": BC.BATCH_STATEMENTS["B1"]}]


@pytest.mark.parametrize(("case", "reason", "error"), [
    ("empty", "batch_empty", "input_invalid"),
    ("too_large", "batch_too_large", "input_invalid"),
    ("parent_core", "batch_parent_not_allowed", "input_invalid"),
    ("unknown_id", "candidate_unknown", "input_invalid"),
    ("parent_mismatch", "parent_mismatch", "input_invalid"),
    ("other_run_handle", "invalid_job_arguments", "input_invalid"),
    ("unknown_key", "invalid_job_arguments", "input_invalid"),
])
def test_preflight_admission_refusals_have_reasons_and_no_numbers(world, client, case, reason, error):
    by_case = {item["reason_code"]: item for item in HAND["admission"]}
    args = {
        "empty": args_for(world, []),
        "too_large": args_for(world, [f"c_{index:016x}" for index in range(51)]),
        "parent_core": args_for(world, IDS[:1], mode="core_fixed", include_parent=True,
                                params={"seed": 1, "conformers": 2}),
        "unknown_id": args_for(world, ["c_0000000000000000"]),
        "parent_mismatch": args_for(world, IDS[:1], parent=world["planar"]),
        "other_run_handle": {**args_for(world, IDS[:1]),
                             "candidate_set_handle": world["candidate_set"].replace(RID, "run_other")},
        "unknown_key": {**args_for(world, IDS[:1]), "timeout_s": 7800},
    }[case]
    if reason in by_case:
        assert by_case[reason]["reason_code"] == reason
    response = _preflight(client, world["root"], args)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admission"]["admitted"] is False and body["admission"]["error"] == error
    assert body["admission"]["reason_code"] == reason and type(body["admission"]["message"]) is str
    for key in ("rows", "new_dockings", "reused_rows", "needed", "shortfall", "full_batch_may_be_partial",
                "batch_input_sha256", "statements", "existing_job", "mode", "include_parent", "candidate_ids"):
        assert body[key] is None, key
    assert set(body["remaining"]) == {"expensive_calls", "wall_clock_s"}   # the run's budget is a fact


def test_preflight_capability_unavailable_and_query_and_body_limits(world, client, monkeypatch, tmp_path):
    root = world["root"]
    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        body = _preflight(client, root, world["args"]["free"]).json()
    assert body["capability"]["available"] is False and body["capability"]["reason_code"] == "engine_missing"
    assert body["admission"] == {"admitted": False, "error": "precondition", "reason_code": "engine_missing",
                                 "message": docking_bundle.REASONS["engine_missing"], "detail": {"reason_code":
                                                                                               "engine_missing"}}
    assert body["rows"] is None and body["needed"] is None
    unknown = _preflight(client, root, world["args"]["free"], dry="1")
    assert unknown.status_code == 422 and unknown.json()["detail"]["error"] == "input_invalid"
    bad = _unchanged(root, lambda: client.post(f"/runs/{RID}/docking/batches/preflight", content=b"{not json",
                                               headers={"content-type": "application/json"}))
    assert bad.status_code == 422
    listed = _unchanged(root, lambda: client.post(f"/runs/{RID}/docking/batches/preflight", json=[1, 2]))
    assert listed.status_code == 422


# ----------------------------------------------------------------- list and detail
def test_list_summaries_validated_in_publication_order(world, client):
    root = world["root"]
    response = _unchanged(root, lambda: client.get(f"/runs/{RID}/docking/batches"))
    assert response.status_code == 200, response.text
    body = response.json()
    names = ("free", "core", "reused", "partial")
    assert body["schema"] == "docking_batch_list@1" and body["total"] == 4
    assert [row["handle"] for row in body["rows"]] == [world["handles"][name] for name in names]
    for name, row in zip(names, body["rows"], strict=True):
        stored = world["stored"][name]
        assert row["valid"] is True and row["reason_code"] is None
        assert row["job_id"] == world["jobs"][name]["job_id"]
        assert (row["status"], row["stop_reason"], row["mode"], row["method"]) == (
            stored["status"], stored["stop_reason"], stored["inputs"]["mode"], stored["method"])
        assert row["counts"] == stored["counts"] and row["include_parent"] == stored["inputs"]["include_parent"]
        assert row["batch_input_sha256"] == stored["batch_input_sha256"]
        assert row["candidate_set_handle"] == stored["inputs"]["candidate_set"]["handle"]
    assert body["rows"][2]["reused_rows"] == [0] and body["rows"][0]["reused_rows"] == []
    page = _unchanged(root, lambda: client.get(f"/runs/{RID}/docking/batches", params={"offset": 1, "limit": 2}))
    assert [row["handle"] for row in page.json()["rows"]] == [world["handles"]["core"], world["handles"]["reused"]]
    for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}, {"handle": "x"}):
        refused = _unchanged(root, lambda params=params: client.get(f"/runs/{RID}/docking/batches", params=params))
        assert refused.status_code == 422, params


def test_detail_matches_stored_summary_and_per_row_m18_results(world, client):
    root = world["root"]
    for name in ("free", "partial", "core", "reused"):
        handle = world["handles"][name]
        response = _unchanged(root, lambda handle=handle: client.get(f"/runs/{RID}/docking/batches/detail",
                                                                      params={"handle": handle}))
        assert response.status_code == 200, response.text
        body = response.json()
        stored = world["stored"][name]
        assert body["schema"] == "docking_batch_detail@1" and body["handle"] == handle
        assert canonical_json(body["summary"]) == canonical_json(stored)
        assert body["job_id"] == world["jobs"][name]["job_id"] and body["meta"]["kind"] == BC.OUTPUT_KIND
        assert body["score_label"] == C.SCORE_LABEL and body["score_column_label"] == C.SCORE_COLUMN_LABEL
        assert [item["id"] for item in body["statements"]["batch"]] == stored["limitations"]["batch_statements"]
        assert [item["number"] for item in body["statements"]["m18"]] == stored["limitations"]["m18_sentences"]
        assert all(item["text"] == BC.BATCH_STATEMENTS[item["id"]] for item in body["statements"]["batch"])
        assert len(body["rows"]) == len(stored["rows"])
        for row, kept in zip(body["rows"], stored["rows"], strict=True):
            assert {key: row[key] for key in kept} == kept
            assert row["reused"] is (row["row_index"] in body["reused_rows"])
            assert row["detail_available"] is (kept["state"] in ("scored", "null_result"))
            if kept["result_handle"] is None:
                continue
            # the per-row result opens in the existing M18 detail read (batch-published rows are M18 results)
            detail = _unchanged(root, lambda h=kept["result_handle"]: client.get(
                f"/runs/{RID}/docking/results/detail", params={"handle": h}))
            assert detail.status_code == 200, detail.text
            result = detail.json()["result"]
            assert result["inputs"]["ligand"]["candidate_id"] == kept["candidate_id"]
            assert result["modes"][0]["score_kcal_mol"] == kept["score_kcal_mol"]
    partial = _unchanged(root, lambda: client.get(f"/runs/{RID}/docking/batches/detail",
                                                  params={"handle": world["handles"]["partial"]})).json()
    assert [(row["state"], row["reason_code"], row["score_kcal_mol"]) for row in partial["rows"]][2:] == [
        ("cancelled", "cancelled", None), ("not_run", "cancelled", None)]
    assert partial["summary"]["status"] == "partial" and [i["id"] for i in partial["statements"]["batch"]] == [
        "B1", "B2", "B3"]
    reused = _unchanged(root, lambda: client.get(f"/runs/{RID}/docking/batches/detail",
                                                 params={"handle": world["handles"]["reused"]})).json()
    assert reused["reused_rows"] == [0] and reused["rows"][0]["reused"] is True


def test_detail_refuses_wrong_kind_other_run_unknown_params_and_tampered_summary(world, client, tmp_path,
                                                                                  monkeypatch):
    root = world["root"]
    free = world["handles"]["free"]
    row_handle = world["stored"]["free"]["rows"][1]["result_handle"]
    cases = [(world["receptor"], 422), (row_handle, 422), (world["candidate_set"], 422),
             (free.replace(RID, "run_other"), None), (f"obj://{RID}/docking_batch_result/{'1' * 64}", 404),
             ("not-a-handle", None)]
    for handle, status in cases:
        response = _unchanged(root, lambda handle=handle: client.get(f"/runs/{RID}/docking/batches/detail",
                                                                      params={"handle": handle}))
        assert response.status_code in ((404, 422) if status is None else (status,)), (handle, response.text)
        assert "score_kcal_mol" not in response.text
    for params in ({"handle": free, "x": "1"}, {}):
        response = _unchanged(root, lambda params=params: client.get(f"/runs/{RID}/docking/batches/detail",
                                                                      params=params))
        assert response.status_code == 422
    # LABELED TEST FABRICATION: a copy of the run whose summary object was edited in place
    copy_root = tmp_path / "runs"
    shutil.copytree(root / RID, copy_root / RID)
    copied = _client(copy_root, monkeypatch)
    assert copied.get(f"/runs/{RID}/docking/batches/detail", params={"handle": free}).status_code == 200
    path = copy_root / RID / "objects" / f"{free.rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["rows"][1]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    response = _unchanged(copy_root, lambda: copied.get(f"/runs/{RID}/docking/batches/detail",
                                                         params={"handle": free}))
    assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    assert "-99" not in response.text
    listed = _unchanged(copy_root, lambda: copied.get(f"/runs/{RID}/docking/batches")).json()
    row = listed["rows"][0]
    assert row["handle"] == free and row["valid"] is False and row["reason_code"] == "evidence_invalid"
    assert row["status"] is None and row["counts"] is None
    assert all(item["valid"] for item in listed["rows"][1:])


def test_read_module_imports_no_chemistry_and_runs_nothing():
    source = (MW / "docking_batch_reads.py").read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in FORBIDDEN_MODULES for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", ".submit(", ".start(", "stage(",
                      "qvina2", "events.append", "raise_limits", "update_limits", "reserve_attempt"):
        assert forbidden not in source, forbidden
