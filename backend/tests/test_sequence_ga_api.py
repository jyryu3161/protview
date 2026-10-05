"""M23 T6: the sequence GA read API (spec .dryforge/spec.md 4, 5, 9): preflight (POST read), summary list (newest
first), summary detail (generations, individuals, the wild-type reference row), one individual or the reference row
by key (its stored model without rows, every appearance, the M18 detail read of its result) and the stored mmCIF of
its model.

The world is real product output (``sequence_ga_world``: real GA jobs with the real GA worker, modeling child and
qvina2; a missing environment FAILS, never skips). Hand values come from spec 2, 3, 7 arithmetic on the test's GA
values and from an independent count of the public 1UBQ file (never from product code). Every read is checked to leave
the event log unchanged (no event, job, tool or budget record) and to run no engine, job or staging. Tampered objects
are labeled test fabrications written only to prove the reads refuse them.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sequence_ga_fixture import UBQ
from sequence_ga_world import copy_run, shared_world

from mw import docking_bundle
from mw import docking_constants as C
from mw import sequence_ga_constants as SC
from mw import sequence_ga_jobs as SJ
from mw.api import app as api_module
from mw.core import events as events_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.runtime.guards import BudgetLimits
from mw.tools import openmm_method

MW = Path(__file__).resolve().parents[1] / "mw"
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm")
PREFLIGHT_NUMBERS = ("selection_sha256", "conditions_sha256", "space", "projection_heavy_atoms", "heavy_atom_warning",
                     "reusable_count", "reference_reusable", "reserved_evaluations", "reserved_units", "needed",
                     "shortfall", "full_run_may_be_partial", "ga", "statements", "existing_job")
ALWAYS = ("S1", "S4", "S5", "S6")
NAMES = ("complete", "partial", "faulted", "reference_failed")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


@pytest.fixture
def client(world, monkeypatch):
    yield _client(world["root"], monkeypatch)
    api_module.RUNS.clear()


@pytest.fixture
def fresh(world, tmp_path, monkeypatch):
    """A function-scoped events-only copy of the run before any GA (an unused combination space), and its client."""
    root = tmp_path / "runs"
    (root / world["rid"]).mkdir(parents=True)
    (root / world["rid"] / "events.jsonl").write_bytes((world["base_root"] / world["rid"] / "events.jsonl")
                                                       .read_bytes())
    client = _client(root, monkeypatch)
    api_module._run(world["rid"]).store.rebuild_from_events()
    yield root, client
    api_module.RUNS.clear()


def _base(world) -> str:
    return f"/runs/{world['rid']}/sequence_ga"


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines() if line.strip()]


def _unchanged(world, root: Path, call):
    before = _events(root, world["rid"])
    response = call()
    assert _events(root, world["rid"]) == before, "a read wrote an event"
    return response


def _slots(content: dict) -> list[tuple[int, int, dict]]:
    return [(gen["index"], position, entry) for gen in content["generations"]
            for position, entry in enumerate(gen["individuals"])]


def _evaluated(content: dict) -> list[dict]:
    return [entry for _g, _p, entry in _slots(content) if entry["origin"] != "carried"]


def _no_work(monkeypatch) -> None:
    """Every engine, job and staging entry point raises: a read must reach none of them."""
    def forbidden(*_a, **_k):
        raise AssertionError("a sequence GA read must not run a job, an engine or a staging step")

    for target, name in ((JobQueue, "submit"), (JobQueue, "start"), (JobQueue, "_supervise"),
                         (docking_bundle, "stage"), (SJ, "manifest"), (SJ, "finish"), (SJ, "start_plan"),
                         (SJ, "limit_approval"), (openmm_method, "preflight")):
        monkeypatch.setattr(target, name, forbidden)


# ----------------------------------------------------------------- preflight
def test_preflight_hand_values_on_an_unused_space_and_no_side_effects(world, fresh):
    root, client = fresh
    run = api_module._run(world["rid"])
    snapshot = run.budget_snapshot()
    used_calls, used_wall = snapshot["expensive_calls"]["used"], snapshot["wall_clock_s"]["used"]
    # GA: P 4, G 2, E 1, max 7, total 600 -> reserved_evaluations = min(7, 4 + 1 x (4 - 1)) = 7;
    # reserved_units = 2 x (7 + 1) = 16; needed wall = min(600 + 600, 16 x 270 + 300) = 1200; 16 x 270 > 600.
    run.update_limits(BudgetLimits(expensive_calls=used_calls + 10, wall_clock_s=used_wall + 1800), by="test")
    jobs_before = JobQueue(run).list()
    response = _unchanged(world, root, lambda: client.post(f"{_base(world)}/preflight",
                                                           json=world["args"]["complete"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "sequence_ga_preflight@1" and body["starts_job"] is False
    assert body["admission"] == {"admitted": True, "error": None, "reason_code": None, "message": None,
                                 "detail": None}
    # tiny set: I3 protected, K6 / I44 / G76 with A and W -> P = 3, n = (2, 2, 2), M = 3,
    # N = e1 + e2 + e3 = 6 + 12 + 8 = 26
    assert body["space"] == {"positions": 3, "candidates": 6, "effective_max_mutations": 3, "size": 26}
    heavy = sum(line.startswith(b"ATOM") for line in UBQ.splitlines())   # independent count of the public file
    assert body["projection_heavy_atoms"] == heavy == 602 and body["heavy_atom_warning"] is False
    assert body["reusable_count"] == 0 and body["reference_reusable"] is False
    assert (body["reserved_evaluations"], body["reserved_units"]) == (7, 16)
    assert body["needed"] == {"expensive_calls": 16, "wall_clock_s": 1200}
    assert body["full_run_may_be_partial"] is True
    for axis in ("expensive_calls", "wall_clock_s"):
        left = body["budget"][axis]["limit"] - body["budget"][axis]["used"]
        assert body["remaining"][axis] == left
        assert body["shortfall"][axis] == max(0, body["needed"][axis] - left)
    assert body["shortfall"] == {"expensive_calls": 6, "wall_clock_s": 0}   # a short budget is not a refusal
    assert body["ga"] == {**world["args"]["complete"]["ga"], "crossover_fraction": 0.5, "random_fraction": 0.25}
    stored = world["stored"]["complete"]   # same request, same environment as the stored run
    assert body["selection_sha256"] == stored["selection_sha256"]
    assert body["conditions_sha256"] == stored["conditions_sha256"]
    assert body["existing_job"] is None
    assert body["statements"] == [{"id": item, "text": SC.STATEMENTS[item]} for item in ALWAYS]
    assert body["capability"]["available"] is True and body["capability"]["protocol_id"] == SC.PROTOCOL
    assert body["score_label"] == SC.SCORE_LABEL == C.SCORE_LABEL
    assert JobQueue(run).list() == jobs_before and run.budget_snapshot()["expensive_calls"]["used"] == used_calls


def test_preflight_on_the_world_counts_reuse_and_returns_the_complete_job(world, client):
    root = world["root"]
    stored = world["stored"]
    reusable = {e["key"] for name in ("complete", "partial") for e in _evaluated(stored[name])
                if e["state"] in ("scored", "null_result")}
    body = _unchanged(world, root, lambda: client.post(f"{_base(world)}/preflight",
                                                       json=world["args"]["complete"])).json()
    assert body["admission"]["admitted"] is True and body["reusable_count"] == len(reusable)
    assert body["reference_reusable"] is True
    assert body["reserved_units"] == 16   # reserved whatever is reused (spec 7)
    assert body["existing_job"] == {"job_id": world["jobs"]["complete"]["job_id"], "status": "done",
                                    "summary_handle": world["handles"]["complete"]}
    partial = _unchanged(world, root, lambda: client.post(f"{_base(world)}/preflight",
                                                          json=world["args"]["partial"])).json()
    # GA seed 4, max 4: reserved_evaluations = min(4, 7) = 4 -> 2 x 5 = 10; wall min(1200, 10 x 270 + 300) = 1200
    assert partial["existing_job"] is None   # a partial summary never deduplicates
    assert (partial["reserved_evaluations"], partial["reserved_units"]) == (4, 10)
    assert partial["needed"] == {"expensive_calls": 10, "wall_clock_s": 1200}
    faulted = _unchanged(world, root, lambda: client.post(f"{_base(world)}/preflight",
                                                          json=world["args"]["faulted"])).json()
    scored = [e for e in _evaluated(stored["faulted"]) if e["state"] != "failed"]
    assert faulted["reusable_count"] == len(scored) == 2   # the two refused individuals have no stored result
    assert faulted["conditions_sha256"] == stored["faulted"]["conditions_sha256"] != body["conditions_sha256"]
    assert faulted["existing_job"]["summary_handle"] == world["handles"]["faulted"]


def _refusal_args(world, case: str) -> dict:
    args = world["args"]["complete"]
    base = world["base"]
    far = {"source": "manual", "center_A": [500.0, 500.0, 500.0], "size_A": [20.0, 20.0, 20.0]}
    return {
        "unknown_key": {**args, "mode": "free"},
        "elite_rule": {**args, "ga": {**args["ga"], "elite_count": 3}},
        "confirmation": {**args, "hydrogen_policy": "keep"},
        "acknowledgement": {**args, "acknowledgement": {}},
        "wrong_kind": {**args, "candidate_set": base["structure"]},
        "other_run": {**args, "candidate_set": base["tiny"].replace(world["rid"], "run_other")},
        "planar": {**args, "ligand": {"source": "sdf", "sdf_handle": base["planar"]}},
        "instance_box": {**args, "box": {"source": "instance_range"}},
        "far_box": {**args, "box": far},
        "empty_set": {**args, "candidate_set": base["empty"]},
    }[case]


@pytest.mark.parametrize(("case", "reason", "error"), [
    ("unknown_key", "invalid_job_arguments", "input_invalid"),
    ("elite_rule", "invalid_job_arguments", "input_invalid"),
    ("confirmation", "confirmation_missing", "input_invalid"),
    ("acknowledgement", "acknowledgement_missing", "input_invalid"),
    ("wrong_kind", "candidate_set_invalid", "input_invalid"),
    ("other_run", "candidate_set_invalid", "input_invalid"),
    ("planar", "ligand_not_3d", "input_invalid"),
    ("instance_box", "box_invalid", "input_invalid"),
    ("far_box", "box_no_receptor_atoms", "input_invalid"),
    ("empty_set", "ga_space_too_small", "input_invalid"),
])
def test_preflight_admission_refusals_are_200_with_reasons_and_no_numbers(world, client, case, reason, error):
    response = _unchanged(world, world["root"], lambda: client.post(f"{_base(world)}/preflight",
                                                                    json=_refusal_args(world, case)))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admission"]["admitted"] is False and body["admission"]["error"] == error
    assert body["admission"]["reason_code"] == reason, body["admission"]
    assert type(body["admission"]["message"]) is str and body["admission"]["detail"]["reason_code"] == reason
    for key in PREFLIGHT_NUMBERS:
        assert body[key] is None, key
    assert set(body["remaining"]) == {"expensive_calls", "wall_clock_s"}   # the run's budget is a fact


def test_preflight_environment_staging_and_body_limits(world, client, monkeypatch, tmp_path):
    root = world["root"]
    url = f"{_base(world)}/preflight"
    args = world["args"]["complete"]
    with monkeypatch.context() as patch:   # environment missing: 412 reason in the body, no numbers
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        body = _unchanged(world, root, lambda: client.post(url, json=args)).json()
    assert body["capability"]["available"] is False and body["capability"]["reason_code"] == "engine_missing"
    assert body["admission"] == {"admitted": False, "error": "precondition", "reason_code": "engine_missing",
                                 "message": docking_bundle.REASONS["engine_missing"],
                                 "detail": {"reason_code": "engine_missing"}}
    assert all(body[key] is None for key in PREFLIGHT_NUMBERS)
    with monkeypatch.context() as patch:   # labeled internal hook: the 16 MiB staging bound reached
        patch.setattr(SC, "MAX_STAGED_BYTES", 1000)
        body = _unchanged(world, root, lambda: client.post(url, json=args)).json()
    assert body["admission"]["error"] == "resource_exceeded"
    assert body["admission"]["reason_code"] == "staged_input_bytes" and body["reserved_units"] is None
    refused = [
        _unchanged(world, root, lambda: client.post(url, json=args, params={"dry": "1"})),
        _unchanged(world, root, lambda: client.post(url, content=b"{not json",
                                                    headers={"content-type": "application/json"})),
        _unchanged(world, root, lambda: client.post(url, json=[1, 2])),
        _unchanged(world, root, lambda: client.post(url, content=b'{"ga": {}, "ga": {}}',
                                                    headers={"content-type": "application/json"})),
        _unchanged(world, root, lambda: client.post(url, content=b'{"ga": NaN}',
                                                    headers={"content-type": "application/json"})),
    ]
    assert [item.status_code for item in refused] == [422] * 5
    assert all(item.json()["detail"]["error"] == "input_invalid" for item in refused)
    large = b'{"x": "' + b"a" * (512 * 1024) + b'"}'
    too_big = _unchanged(world, root, lambda: client.post(url, content=large,
                                                          headers={"content-type": "application/json"}))
    assert too_big.status_code == 413


# ----------------------------------------------------------------- list
def test_list_is_newest_first_validated_and_paged(world, client):
    root = world["root"]
    response = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "sequence_ga_list@1" and body["total"] == 4
    assert (body["offset"], body["limit"]) == (0, 50)
    names = tuple(reversed(NAMES))   # newest first
    assert [row["handle"] for row in body["rows"]] == [world["handles"][name] for name in names]
    for name, row in zip(names, body["rows"], strict=True):
        stored = world["stored"][name]
        assert row["valid"] is True and row["reason_code"] is None
        assert (row["job_id"], row["attempt_id"]) == (world["jobs"][name]["job_id"], world["jobs"][name]["attempt_id"])
        for key in ("status", "stop_reason", "generations_done", "new_evaluations_used", "reused_count",
                    "reserved_units", "space", "candidate_set", "selection_sha256", "ga"):
            assert row[key] == stored[key], key
    assert [row["published_seq"] for row in body["rows"]] == sorted((row["published_seq"] for row in body["rows"]),
                                                                    reverse=True)
    assert set(body["rows"][0]) == {"handle", "published_seq", "valid", "reason_code", "job_id", "attempt_id",
                                    "status", "stop_reason", "generations_done", "new_evaluations_used",
                                    "reused_count", "reserved_units", "space", "candidate_set", "selection_sha256",
                                    "ga"}
    page = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results", params={"offset": 1, "limit": 2}))
    assert [row["handle"] for row in page.json()["rows"]] == [world["handles"]["faulted"],
                                                              world["handles"]["partial"]]
    for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}, {"handle": "x"}):
        refused = _unchanged(world, root, lambda params=params: client.get(f"{_base(world)}/results", params=params))
        assert refused.status_code == 422, params


# ----------------------------------------------------------------- detail
def test_detail_matches_the_stored_summary_individuals_and_reference_row(world, client):
    root = world["root"]
    for name in NAMES:
        handle = world["handles"][name]
        response = _unchanged(world, root, lambda handle=handle: client.get(f"{_base(world)}/results/{handle}"))
        assert response.status_code == 200, response.text
        body = response.json()
        stored = world["stored"][name]
        assert body["schema"] == "sequence_ga_detail@1" and body["handle"] == handle
        assert canonical_json(body["summary"]) == canonical_json(stored)
        assert (body["job_id"], body["attempt_id"]) == (world["jobs"][name]["job_id"],
                                                        world["jobs"][name]["attempt_id"])
        assert type(body["published_seq"]) is int and body["meta"]["kind"] == SC.OUTPUT_KIND
        assert body["score_label"] == SC.SCORE_LABEL and body["score_column_label"] == C.SCORE_COLUMN_LABEL
        assert body["score_row_label"] == SC.SCORE_ROW_LABEL
        assert body["statements"] == [{"id": item, "text": SC.STATEMENTS[item]} for item in stored["limitations"]]
        assert body["reference"] == {**stored["reference"],
                                     "detail_available": stored["reference"]["result_handle"] is not None}
        assert len(body["generations"]) == len(stored["generations"])
        for gen, kept in zip(body["generations"], stored["generations"], strict=True):
            assert {key: gen[key] for key in ("index", "complete", "min_score", "max_score")} == {
                key: kept[key] for key in ("index", "complete", "min_score", "max_score")}
            for entry, original in zip(gen["individuals"], kept["individuals"], strict=True):
                assert {key: entry[key] for key in original} == original
                assert entry["detail_available"] is (original["result_handle"] is not None)
        text = response.text
        for word in ("rank", "best", "improve", "delta", "difference"):
            assert word not in text.lower()
    failed = world["stored"]["reference_failed"]["reference"]
    body = client.get(f"{_base(world)}/results/{world['handles']['reference_failed']}").json()
    assert body["reference"]["score"] is None and body["reference"]["detail_available"] is False
    assert body["reference"]["state"] == failed["state"] == "failed" and body["generations"] == []


# ----------------------------------------------------------------- individual / reference row
def _model_view(run, handle: str) -> dict:
    model = run.store.load(handle)
    (side,) = model["structures"]
    entry = {key: value for key, value in model["structures"][side].items()
             if key not in ("final_bonds", "atom_mapping")}
    return {**{key: value for key, value in model.items() if key != "structures"}, "structures": {side: entry}}


def _m18(world, client, root, handle):
    detail = _unchanged(world, root, lambda: client.get(f"/runs/{world['rid']}/docking/results/detail",
                                                        params={"handle": handle}))
    assert detail.status_code == 200, detail.text
    return {key: value for key, value in detail.json().items() if key != "meta"}


def test_individual_and_reference_rows_by_key(world, client):
    root = world["root"]
    run = api_module._run(world["rid"])
    for name in ("complete", "partial"):
        handle = world["handles"][name]
        stored = world["stored"][name]
        keys = list(dict.fromkeys([*(e["key"] for _g, _p, e in _slots(stored)), "wild_type"]))
        assert any(e["origin"] == "carried" for _g, _p, e in _slots(stored))
        for key in keys:
            response = _unchanged(world, root, lambda handle=handle, key=key: client.get(
                f"{_base(world)}/results/{handle}/individual", params={"key": key}))
            assert response.status_code == 200, response.text
            body = response.json()
            if key == "wild_type":
                row, mutations, pick, appearances = stored["reference"], [], None, []
            else:
                row = next(e for e in _evaluated(stored) if e["key"] == key)
                mutations, pick = row["mutations"], row["pick_index"]
                appearances = [{"generation": g, "position": p, "origin": e["origin"]}
                               for g, p, e in _slots(stored) if e["key"] == key]
            assert body["schema"] == "sequence_ga_individual@1" and body["summary_handle"] == handle
            assert (body["key"], body["is_reference"], body["mutations"]) == (key, key == "wild_type", mutations)
            assert (body["pick_index"], body["eval_index"]) == (pick, row.get("eval_index"))
            for field in ("evaluation", "state", "reason_code", "score", "model_handle", "result_handle"):
                assert body[field] == row[field], field
            assert body["appearances"] == appearances
            assert body["model"] == _model_view(run, row["model_handle"])
            assert "atom_mapping" not in response.text and "final_bonds" not in response.text
            assert body["statements"] == [{"id": "S5", "text": SC.STATEMENTS["S5"]}]
            assert body["score_label"] == SC.SCORE_LABEL and body["score_row_label"] == SC.SCORE_ROW_LABEL
            # the same body as the M18 detail read of that result handle
            assert body["m18_detail"] == _m18(world, client, root, row["result_handle"])
            assert body["m18_detail"]["result"]["inputs"]["receptor"]["source"]["mutation_model"] == \
                row["model_handle"]
            assert body["m18_detail"]["result"]["modes"][0]["score_kcal_mol"] == row["score"]


def test_rows_without_a_score_are_null_never_zero(world, client):
    root = world["root"]
    stored = world["stored"]["faulted"]
    handle = world["handles"]["faulted"]
    failed, no_model = [e for e in _evaluated(stored) if e["state"] == "failed"]
    body = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results/{handle}/individual",
                                                      params={"key": failed["key"]})).json()
    assert (body["state"], body["reason_code"], body["score"], body["result_handle"], body["m18_detail"]) == (
        "failed", "engine_output_invalid", None, None, None)
    assert body["model"] is not None and body["model_handle"] == failed["model_handle"]
    body = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results/{handle}/individual",
                                                      params={"key": no_model["key"]})).json()
    assert (body["state"], body["reason_code"], body["score"], body["model_handle"], body["model"],
            body["result_handle"], body["m18_detail"]) == ("failed", "worker_failed", None, None, None, None, None)
    missing = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results/{handle}/structure",
                                                         params={"key": no_model["key"]}))
    assert missing.status_code == 404 and missing.json()["detail"]["error"] == "not_found"
    detail = client.get(f"{_base(world)}/results/{handle}").json()
    for kept in (failed, no_model):
        entry = next(e for gen in detail["generations"] for e in gen["individuals"] if e["key"] == kept["key"])
        assert entry["score"] is None and entry["state"] == "failed" and entry["detail_available"] is False
    scores = [e["score"] for e in detail["generations"][0]["individuals"] if e["state"] == "scored"]
    assert len(scores) == 2 and detail["generations"][0]["min_score"] == min(scores)
    assert detail["generations"][0]["max_score"] == max(scores)
    reference = _unchanged(world, root, lambda: client.get(
        f"{_base(world)}/results/{world['handles']['reference_failed']}/individual",
        params={"key": "wild_type"})).json()
    kept = world["stored"]["reference_failed"]["reference"]
    assert (reference["state"], reference["score"], reference["result_handle"], reference["m18_detail"]) == (
        "failed", None, None, None)
    assert reference["reason_code"] == kept["reason_code"] and reference["reason_code"].startswith("ligand_")
    assert reference["model"]["mutations"] == [] and reference["appearances"] == []


def test_individual_key_errors(world, client):
    root = world["root"]
    handle = world["handles"]["complete"]
    seen = {e["key"] for e in _evaluated(world["stored"]["complete"])}
    absent = next(key for key in ("0", "2", "0-3", "1-3", "2-4") if key not in seen)
    url = f"{_base(world)}/results/{handle}/individual"
    for params, status in (({}, 422), ({"key": ""}, 422), ({"key": "3-1"}, 422), ({"key": "01"}, 422),
                           ({"key": "a"}, 422), ({"key": "wild-type"}, 422), ({"key": "1-2-3-4-5"}, 422),
                           ({"key": "3", "x": "1"}, 422), ({"key": absent}, 404), ({"key": "999"}, 404)):
        response = _unchanged(world, root, lambda params=params: client.get(url, params=params))
        assert response.status_code == status, (params, response.text)
        assert "score" not in response.text


# ----------------------------------------------------------------- structure download
def test_structure_download_is_the_stored_mmcif(world, client):
    root = world["root"]
    run = api_module._run(world["rid"])
    for name, key in (("complete", "wild_type"), ("complete", _evaluated(world["stored"]["complete"])[1]["key"]),
                      ("faulted", next(e["key"] for e in _evaluated(world["stored"]["faulted"])
                                       if e["state"] == "failed")),
                      ("reference_failed", "wild_type")):
        handle = world["handles"][name]
        stored = world["stored"][name]
        row = stored["reference"] if key == "wild_type" else next(e for e in _evaluated(stored) if e["key"] == key)
        response = _unchanged(world, root, lambda handle=handle, key=key: client.get(
            f"{_base(world)}/results/{handle}/structure", params={"key": key}))
        assert response.status_code == 200, response.text
        (entry,) = run.store.load(row["model_handle"])["structures"].values()
        assert response.content == run.store.load(entry["structure_object"])
        assert hashlib.sha256(response.content).hexdigest() == entry["structure_sha256"]
        assert response.headers["content-type"].startswith("chemical/x-mmcif")
        assert response.headers["cache-control"] == "private, no-store"
        sha = handle.rsplit("/", 1)[-1][:12]
        assert response.headers["content-disposition"] == \
            f'attachment; filename="protview-sequence-ga-{sha}-{key}.cif"'
    url = f"{_base(world)}/results/{world['handles']['complete']}/structure"
    for params, status in (({}, 422), ({"key": "x"}, 422), ({"key": "999"}, 404), ({"key": "wild_type", "y": 1}, 422)):
        response = _unchanged(world, root, lambda params=params: client.get(url, params=params))
        assert response.status_code == status, (params, response.text)


def test_sub_resource_routes_are_registered_before_the_detail_route(world, client):
    paths = [getattr(route, "path", "") for route in api_module.app.routes]
    prefix = "/runs/{rid}/sequence_ga/results/{handle:path}"
    detail = paths.index(prefix)
    assert paths.index(prefix + "/individual") < detail and paths.index(prefix + "/structure") < detail
    handle = world["handles"]["complete"]
    individual = client.get(f"{_base(world)}/results/{handle}/individual", params={"key": "wild_type"})
    assert individual.status_code == 200 and individual.json()["schema"] == "sequence_ga_individual@1"
    structure = client.get(f"{_base(world)}/results/{handle}/structure", params={"key": "wild_type"})
    assert structure.status_code == 200 and structure.content.startswith(b"data_")


# ----------------------------------------------------------------- refusals, tampering, cost
def test_reads_refuse_wrong_kind_other_run_unknown_params_and_tampered_objects(world, client, tmp_path, monkeypatch):
    root = world["root"]
    rid = world["rid"]
    complete = world["handles"]["complete"]
    individual = _evaluated(world["stored"]["complete"])[0]
    cases = [(world["base"]["receptor"], 422), (individual["result_handle"], 422), (individual["model_handle"], 422),
             (world["base"]["tiny"], 422), (complete.replace(rid, "run_other"), None),
             (f"obj://{rid}/sequence_ga_result/{'1' * 64}", 404)]
    for handle, status in cases:
        for suffix, params in (("", {}), ("/individual", {"key": individual["key"]}),
                               ("/structure", {"key": individual["key"]})):
            response = _unchanged(world, root, lambda h=handle, s=suffix, p=params: client.get(
                f"{_base(world)}/results/{h}{s}", params=p))
            assert response.status_code in ((404, 422) if status is None else (status,)), (handle, response.text)
            assert "score" not in response.text
    response = _unchanged(world, root, lambda: client.get(f"{_base(world)}/results/{complete}", params={"x": "1"}))
    assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"
    # LABELED TEST FABRICATION: a copy of the run whose summary object was edited in place
    copy_root = copy_run(world, tmp_path / "runs")
    copied = _client(copy_root, monkeypatch)
    assert copied.get(f"{_base(world)}/results/{complete}").status_code == 200
    stored_path = copy_root / rid / "objects" / f"{complete.rsplit('/', 1)[-1]}.json"
    content = json.loads(stored_path.read_bytes())
    scored = next(e for e in content["generations"][0]["individuals"] if e["state"] == "scored")
    scored["score"] = -99.0
    stored_path.write_bytes(canonical_json(content))
    for suffix, params in (("", {}), ("/individual", {"key": scored["key"]}), ("/structure", {"key": "wild_type"})):
        response = _unchanged(world, copy_root, lambda s=suffix, p=params: copied.get(
            f"{_base(world)}/results/{complete}{s}", params=p))
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
        assert "-99" not in response.text
    listed = _unchanged(world, copy_root, lambda: copied.get(f"{_base(world)}/results")).json()
    row = next(item for item in listed["rows"] if item["handle"] == complete)
    assert row["valid"] is False and row["reason_code"] == "evidence_invalid"
    assert all(row[key] is None for key in ("job_id", "status", "space", "ga", "reserved_units"))
    assert sum(item["valid"] for item in listed["rows"]) == 3
    # LABELED FAULT: one individual's stored mmCIF edited in place; its summary, row and download refuse
    partial = world["handles"]["partial"]
    row = next(e for e in _evaluated(world["stored"]["partial"]) if e["evaluation"] == "computed")
    (entry,) = api_module._run(rid).store.load(row["model_handle"])["structures"].values()
    cif = copy_root / rid / "objects" / f"{entry['structure_object'].rsplit('/', 1)[-1]}.cif"
    cif.write_bytes(cif.read_bytes().replace(b"data_", b"data_X", 1))
    for suffix, params in (("", {}), ("/individual", {"key": row["key"]}), ("/structure", {"key": row["key"]})):
        response = copied.get(f"{_base(world)}/results/{partial}{suffix}", params=params)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"


def test_one_read_parses_the_event_log_once_whatever_the_individual_count(world, client, monkeypatch):
    _no_work(monkeypatch)
    rid = world["rid"]
    client.get(f"/runs/{rid}/budget")   # the run is open (reopening reads its events)
    counted = []
    original = events_module.EventLog._read_unlocked

    def counting(self):
        counted.append(1)
        return original(self)

    monkeypatch.setattr(events_module.EventLog, "_read_unlocked", counting)
    calls = [("list", f"{_base(world)}/results", {})]
    for name in NAMES:
        handle = world["handles"][name]
        stored = world["stored"][name]
        calls.append((f"detail {name}", f"{_base(world)}/results/{handle}", {}))
        for key in ["wild_type", *(e["key"] for e in _evaluated(stored))]:
            calls.append((f"individual {name} {key}", f"{_base(world)}/results/{handle}/individual", {"key": key}))
            calls.append((f"structure {name} {key}", f"{_base(world)}/results/{handle}/structure", {"key": key}))
    sizes = {name: 1 + len(_evaluated(world["stored"][name])) for name in NAMES}
    assert sizes["complete"] == 8 and sizes["reference_failed"] == 1   # 8 validated rows vs 1: the same one read
    no_model = {(name, e["key"]) for name in NAMES for e in _evaluated(world["stored"][name])
                if e["model_handle"] is None}
    assert len(no_model) == 1
    for label, url, params in calls:
        counted.clear()
        response = client.get(url, params=params)
        missing = label.startswith("structure") and tuple(label.split()[1:]) in no_model
        assert response.status_code == (404 if missing else 200), (label, response.text)
        assert len(counted) == 1, (label, len(counted))


def test_capabilities_still_report_the_sequence_ga_method(world, client):
    methods = client.get("/capabilities").json()["methods"]
    assert methods["sequence_ga_design"] == SJ.capability()
    assert methods["sequence_ga_design"]["available"] is True


def test_read_module_imports_no_chemistry_and_runs_nothing():
    source = (MW / "sequence_ga_reads.py").read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in FORBIDDEN_MODULES for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", ".submit(", ".start(", "stage(",
                      "qvina2", "events.append", "raise_limits", "update_limits", "reserve_attempt", "finish(",
                      "store.put"):
        assert forbidden not in source, forbidden
    assert not re.search(r"\b(rank|best|improv|delta|difference)", source, re.IGNORECASE)
